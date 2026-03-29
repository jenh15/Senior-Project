# Precompute taxon key lookup for all species in IsEndangered.csv
# to speed up our API response time (since taxon key lookup is a bottleneck)
# One-time script — re-run if data/IsEndangered.csv is updated.
#
# Usage (from project root):  python scripts/build_taxon_lookup.py
#
# Input : data/IsEndangered.csv
# Output: data/IllinoisTaxonLookup.csv

import csv
import pathlib
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

GBIF_MATCH = "https://api.gbif.org/v1/species/match"

DATA_DIR = pathlib.Path(__file__).parent.parent / "data"
INPUT_CSV = str(DATA_DIR / "IsEndangered.csv")
OUTPUT_CSV = str(DATA_DIR / "IllinoisTaxonLookup.csv")

MAX_WORKERS = 20


def normalize_scientific_name(name: str) -> str:
    """
    Keep only binomial name (Genus species) for simpler matching.
    Example:
        'Tilia americana var. heterophylla' -> 'Tilia americana'
        'Phlox pilosa ssp. sangamonensis'   -> 'Phlox pilosa'
    """
    parts = (name or "").strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return (name or "").strip()


def load_unique_scientific_names(path: str) -> list[str]:
    names = set()

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        if "Scientific Name" not in reader.fieldnames:
            raise ValueError(
                f"'Scientific Name' column not found. Found columns: {reader.fieldnames}"
            )

        for row in reader:
            raw_name = row.get("Scientific Name", "").strip()
            if raw_name:
                normalized = normalize_scientific_name(raw_name)
                if normalized:
                    names.add(normalized)

    return sorted(names)


def gbif_match_to_taxonkey(name: str) -> tuple[str, str]:
    """
    Returns:
        (scientific_name, taxon_key_as_string_or_blank)
    """
    try:
        response = requests.get(
            GBIF_MATCH,
            params={"name": name},
            timeout=20
        )
        response.raise_for_status()
        data = response.json()

        key = data.get("usageKey") or data.get("speciesKey")
        return name, str(key) if key else ""

    except Exception:
        return name, ""


def main():
    print(f"Loading scientific names from {DATA_DIR / 'IsEndangered.csv'}...")
    names = load_unique_scientific_names(INPUT_CSV)
    print(f"Loaded {len(names)} unique normalized scientific names")

    results = []

    print("Matching names to GBIF taxon keys...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(gbif_match_to_taxonkey, name): name for name in names}

        for future in as_completed(futures):
            name, taxon_key = future.result()
            results.append((name, taxon_key))

    # Sort alphabetically for cleaner output
    results.sort(key=lambda x: x[0])

    matched_count = sum(1 for _, key in results if key)
    unmatched_count = len(results) - matched_count

    print(f"Matched {matched_count} names")
    print(f"Unmatched {unmatched_count} names")

    print(f"Writing lookup CSV to {DATA_DIR / 'IllinoisTaxonLookup.csv'}...")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Scientific Name", "Taxon Key"])
        writer.writerows(results)

    print("Done.")


if __name__ == "__main__":
    main()