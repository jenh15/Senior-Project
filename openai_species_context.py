"""
openai_species_context.py

Generate short species-specific construction context for screening using the OpenAI Responses API.

Requirements
    conda activate GBIF_env

Environment
    OPENAI_API_KEY must be set in your environment.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from openai import (
    OpenAI,
    AuthenticationError,
    RateLimitError,
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5.4"


def _build_batch_prompt(gbif_result: Dict[str, Any]) -> str:
    input_data = gbif_result.get("input", {})
    hits = gbif_result.get("hits", [])

    lat = input_data.get("lat")
    lon = input_data.get("lon")
    radius_miles = input_data.get("radius_miles")
    year_start = input_data.get("year_start")
    year_end = input_data.get("year_end")

    species_lines = []
    for hit in hits:
        scientific_name = hit.get("scientific_name", "Unknown")
        gbif_count = hit.get("gbif_count", "Unknown")
        taxon_key = hit.get("taxon_key", "Unknown")
        species_lines.append(
            f"- Scientific name: {scientific_name} | GBIF count: {gbif_count} | taxon key: {taxon_key}"
        )

    species_block = "\n".join(species_lines)

    return f"""
You are helping with an early-stage construction planning tool for Illinois.

A construction site has been screened for Illinois endangered species using GBIF occurrence data.

Construction site context:
- Latitude: {lat}
- Longitude: {lon}
- Radius screened: {radius_miles} miles
- GBIF year filter: {year_start if year_start is not None else "unknown"} to {year_end if year_end is not None else "present"}

Flagged species:
{species_block}

For EACH species, provide:
1. scientific_name
2. common_name (the widely-used English common name for this species)
3. tags: a compact list of 2–6 short keyword labels (1–3 words each) summarizing the most relevant concerns for this species — draw from seasonal sensitivities (e.g. "Nesting", "Breeding Season", "Migration", "Overwintering", "Spawning", "Dormancy") and disruptive activities (e.g. "Tree Clearing", "Ground Disturbance", "Vibration", "Noise", "Water Disturbance", "Night Lighting"). Only include tags that genuinely apply.
4. overview: 1–2 sentences of general background relevant to construction planning for this species
5. seasonal_concerns: a short paragraph on the most relevant seasonal sensitivities (breeding, nesting, migration, roosting, dormancy, spawning, etc.) and approximately when they occur
6. disruptive_activities: a short paragraph on which construction activities are most likely to cause disturbance (noise, tree clearing, grading, vibration, water disturbance, nighttime lighting, etc.)
7. recommendation: a cautious 1–2 sentence suggestion for when or how construction might be less disruptive, if reasonable — do not frame this as approval or a guarantee

Important rules:
- Do not invent legal requirements
- Do not say construction is approved or safe
- Do not sound absolute or definitive
- Keep the tone practical for a construction manager
- Mention uncertainty when appropriate

Return ONLY valid JSON in this exact format:
{{
  "species_context": [
    {{
      "scientific_name": "Species name here",
      "common_name": "Common name here",
      "tags": ["Tag One", "Tag Two"],
      "overview": "Brief general context here.",
      "seasonal_concerns": "Seasonal sensitivity paragraph here.",
      "disruptive_activities": "Disruptive activities paragraph here.",
      "recommendation": "Cautious timing suggestion here."
    }}
  ]
}}
""".strip()


def enrich_gbif_results_with_openai_batch(
    gbif_result: Dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    client: Optional[OpenAI] = None,
) -> Dict[str, Any]:
    if client is None:
        client = OpenAI()

    hits = gbif_result.get("hits", [])
    if not hits:
        return {
            "input": gbif_result.get("input", {}),
            "species_context": [],
            "disclaimer": (
                "These summaries are AI-generated planning aids based on species names and site context. "
                "They are not regulatory determinations and should be validated with qualified environmental professionals."
            ),
        }

    prompt = _build_batch_prompt(gbif_result)

    _DISCLAIMER = (
        "These summaries are AI-generated planning aids based on species names and site context. "
        "They are not regulatory determinations and should be validated with qualified environmental professionals."
    )

    def _error_result(error_tag: str, message: str) -> Dict[str, Any]:
        """Return a gracefully-degraded result when the AI call fails."""
        logger.error("OpenAI enrichment failed [%s]: %s", error_tag, message)
        return {
            "input": gbif_result.get("input", {}),
            "species_context": [
                {
                    "scientific_name": hit.get("scientific_name", "Unknown"),
                    "common_name": None,
                    "tags": [],
                    "overview": None,
                    "seasonal_concerns": None,
                    "disruptive_activities": None,
                    "recommendation": None,
                    "ai_error": message,
                }
                for hit in hits
            ],
            "ai_error": message,
            "disclaimer": _DISCLAIMER,
        }

    try:
        response = client.responses.create(
            model=model,
            input=prompt,
        )
    except AuthenticationError:
        return _error_result(
            "auth",
            "OpenAI API key is invalid or missing. AI ecological context is unavailable.",
        )
    except RateLimitError:
        return _error_result(
            "rate_limit",
            "OpenAI usage quota exceeded. AI ecological context is temporarily unavailable.",
        )
    except APITimeoutError:
        return _error_result(
            "timeout",
            "OpenAI request timed out. AI ecological context is unavailable for this scan.",
        )
    except APIConnectionError:
        return _error_result(
            "connection",
            "Could not reach the OpenAI API. Check network connectivity. AI ecological context is unavailable.",
        )
    except APIStatusError as exc:
        return _error_result(
            f"api_status_{exc.status_code}",
            f"OpenAI API returned an error (HTTP {exc.status_code}). AI ecological context is unavailable.",
        )

    raw_text = response.output_text.strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("OpenAI returned non-JSON output; storing raw text as fallback")
        parsed = {
            "species_context": [
                {
                    "scientific_name": "ParsingError",
                    "analysis": raw_text,
                }
            ]
        }

    return {
        "input": gbif_result.get("input", {}),
        "species_context": parsed.get("species_context", []),
        "disclaimer": _DISCLAIMER,
    }