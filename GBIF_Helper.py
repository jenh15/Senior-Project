"""
GBIF_Helper.py

Helper utilities for :
- Query GBIF occurrences around a point and aggregate by speciesKey (fast via facets)
- Resolve speciesKey -> canonical/scientific name.
- Load Illinois endangered species (Scientific Name column) and flag matches

Dependencies:
conda environment.yml
"""

from __future__ import annotations

import csv
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence, Set, Tuple

import requests

GBIF_OCCURRENCE_SEARCH = "https://api.gbif.org/v1/occurrence/search"
GBIF_SPECIES = "https://api.gbif.org/v1/species/{}"


# Small utilities
def miles_to_km(miles: float) -> float:
    return miles * 1.609344


def normalize_binomial(name: str) -> str:
    """
    Normalize scientific names to Genus + species (binomial),
    helpful if GBIF returns a subspecies/variety.
    """
    parts = (name or "").strip().split()
    return " ".join(parts[:2]) if len(parts) >= 2 else (name or "").strip()


def bounding_box_polygon(lat: float, lon: float, radius_km: float) -> str:
    """
    Approximate a radius search as a bounding-box polygon.
    GBIF geometry uses WKT (lon lat).
    """
    # 1 degree latitude ~= 111 km
    lat_delta = radius_km / 111.0
    # longitude degrees shrink by cos(latitude)
    lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)) + 1e-12)

    min_lat = lat - lat_delta
    max_lat = lat + lat_delta
    min_lon = lon - lon_delta
    max_lon = lon + lon_delta

    # WKT polygon must be closed
    return (
        f"POLYGON(({min_lon} {min_lat},"
        f"{min_lon} {max_lat},"
        f"{max_lon} {max_lat},"
        f"{max_lon} {min_lat},"
        f"{min_lon} {min_lat}))"
    )



# Illinois endangered list

def load_illinois_endangered_set(csv_path: str) -> Set[str]:
    """
    Loads 'Scientific Name' column into a set for O(1) lookups.
    Keeps both original and normalized binomial form to improve matching.
    """
    out: Set[str] = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "Scientific Name" not in (reader.fieldnames or []):
            raise ValueError(
                f"CSV missing 'Scientific Name' header. Found headers: {reader.fieldnames}"
            )

        for row in reader:
            name = (row.get("Scientific Name") or "").strip()
            if not name:
                continue
            out.add(name)
            out.add(normalize_binomial(name))
    return out



# GBIF querying w/ geometry 

def gbif_species_facet_geometry(
    polygon_wkt: str,
    *,
    min_count: int = 1,
    basis_of_record: Optional[str] = None,
    year_range: Optional[Tuple[int, int]] = None,
    user_agent: str = "Preliminary Screening (student project)",
    timeout: int = 30,
) -> List[Dict]:
    """
    Same as gbif_species_facet, but uses WKT geometry=POLYGON(...) instead of distance.
    More reliable for larger areas.
    """
    params: Dict[str, object] = {
        "geometry": polygon_wkt,
        "hasCoordinate": "true",
        "facet": "speciesKey",
        "facetMincount": min_count,
        "limit": 0,
    }
    if basis_of_record:
        params["basisOfRecord"] = basis_of_record
    if year_range:
        params["year"] = f"{year_range[0]},{year_range[1]}"

    r = requests.get(
        GBIF_OCCURRENCE_SEARCH, params=params, headers={"User-Agent": user_agent}, timeout=timeout
    )
    r.raise_for_status()
    j = r.json()
    facets = j.get("facets", [])
    if not facets:
        return []
    return facets[0].get("counts", []) or []


def resolve_species_keys_to_names(
    species_key_counts: Sequence[Dict],
    *,
    top_n: int = 50,
    max_workers: int = 10,
    user_agent: str = "Preliminary Screening (student project)",
    timeout: int = 20,
) -> List[Tuple[str, int, str]]:
    """
    Resolves GBIF speciesKey -> canonical/scientific name using threaded requests.

    Returns list of tuples:
      (canonical_or_scientific_name, count, species_key)
    """
    top = list(species_key_counts) if top_n is None else list(species_key_counts)[:top_n]

    def _lookup(entry: Dict) -> Tuple[str, int, str]:
        key = str(entry.get("name", ""))
        count = int(entry.get("count", 0))
        url = GBIF_SPECIES.format(key)

        r = requests.get(url, headers={"User-Agent": user_agent}, timeout=timeout)
        r.raise_for_status()
        j = r.json()
        name = j.get("canonicalName") or j.get("scientificName") or "Unknown"
        return name, count, key

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(_lookup, top))

    return results


def get_species_names_in_radius(
    lat: float,
    lon: float,
    radius_miles: float,
    *,
    top_n: int = 50,
    min_count: int = 1,
    max_workers: int = 10,
    basis_of_record: Optional[str] = None,
    year_range: Optional[Tuple[int, int]] = None,
) -> List[Tuple[str, int, str]]:
    """
    Geometry-first helper:
    - Build a bounding-box polygon from (lat, lon, radius)
    - Query GBIF using geometry facets 
    - Resolve top N keys into canonical/scientific names (parallel)

    Returns: [(name, count, speciesKey), ...] sorted by count desc
    """
    radius_km = miles_to_km(radius_miles)
    poly = bounding_box_polygon(lat, lon, radius_km)

    counts = gbif_species_facet_geometry(
        poly,
        min_count=min_count,
        basis_of_record=basis_of_record,
        year_range=year_range,
    )

    if not counts:
        return []

    counts = sorted(counts, key=lambda x: int(x.get("count", 0)), reverse=True)

    resolved = resolve_species_keys_to_names(
        counts, top_n=top_n, max_workers=max_workers
    )
    resolved = sorted(resolved, key=lambda t: t[1], reverse=True)
    return resolved

def flag_illinois_endangered(
    resolved_species: Sequence[Tuple[str, int, str]],
    illinois_endangered_set: Set[str],
    *,
    normalize: bool = True,
) -> List[Tuple[str, int, str, bool]]:
    """
    Adds an Illinois endangered boolean flag to each resolved species record.

    Returns: [(name, count, speciesKey, is_il_listed), ...]
    """
    out = []
    for name, cnt, key in resolved_species:
        chk = normalize_binomial(name) if normalize else name
        is_listed = (chk in illinois_endangered_set) or (name in illinois_endangered_set)
        out.append((name, cnt, key, is_listed))
    return out