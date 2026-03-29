import csv
import math
import pathlib
import requests

from dotenv import load_dotenv
load_dotenv()
import os

if "OPENAI_API_KEY" not in os.environ:
    raise RuntimeError("OPENAI_API_KEY environment variable not set.")

GBIF_OCC_SEARCH = "https://api.gbif.org/v1/occurrence/search"
MAX_SPECIES = int(os.getenv("MAX_SPECIES_FOR_AI", 1))

DATA_DIR = pathlib.Path(__file__).parent / "data"


def miles_to_km(mi: float) -> float:
    return mi * 1.609344


def get_bounding_box(lat: float, lon: float, radius_miles: float):
    radius_km = miles_to_km(radius_miles)

    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)) + 1e-12)

    min_lat = lat - lat_delta
    max_lat = lat + lat_delta
    min_lon = lon - lon_delta
    max_lon = lon + lon_delta

    print(f"Bounding box = [min_lat: {min_lat}, max_lat: {max_lat}, min_lon: {min_lon}, max_lon: {max_lon}]")

    return min_lat, max_lat, min_lon, max_lon


def load_precomputed_taxon_keys(path: str) -> dict[str, int]:
    """
    Reads IllinoisTaxonLookup.csv and returns two dicts:
        name_to_key: {"Myotis sodalis": 2435099, ...}
        key_to_name: {2435099: "Myotis sodalis", ...}
    """
    name_to_key = {}
    key_to_name = {}

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            name = (row.get("Scientific Name") or "").strip()
            key = (row.get("Taxon Key") or "").strip()

            if name and key:
                try:
                    name_to_key[name] = int(key)
                    key_to_name[int(key)] = name
                except ValueError:
                    pass

    return name_to_key, key_to_name


def gbif_species_counts_in_area(lat: float, lon: float, radius_miles: float) -> list[tuple[int, int]]:
    """Facet search returning all (taxon_key, count) pairs in the bounding box."""
    min_lat, max_lat, min_lon, max_lon = get_bounding_box(lat, lon, radius_miles)

    params = {
        "decimalLatitude": f"{min_lat},{max_lat}",
        "decimalLongitude": f"{min_lon},{max_lon}",
        "hasCoordinate": "true",
        "year": "2025,2026",
        "facet": "speciesKey",
        "facetMincount": 1,
        "speciesKey.facetLimit": 1000,
        "limit": 0,
    }

    j = requests.get(GBIF_OCC_SEARCH, params=params, timeout=120).json()

    counts = j.get("facets", [])[0].get("counts", [])
    return [(int(row["name"]), int(row["count"])) for row in counts if row.get("name")]


def run_scan(lat, lon, radius_miles, progress_callback=None):
    if progress_callback:
        progress_callback("Loading Illinois taxon lookup", 10)

    name_to_key, key_to_name = load_precomputed_taxon_keys(str(DATA_DIR / "IllinoisTaxonLookup.csv"))

    if progress_callback:
        progress_callback("Querying GBIF species in area", 35)

    area_species = gbif_species_counts_in_area(lat, lon, radius_miles)

    if progress_callback:
        progress_callback("Cross-referencing Illinois endangered species", 60)

    hits = []
    for taxon_key, count in area_species:
        if taxon_key in key_to_name:
            name = key_to_name[taxon_key]
            hits.append((name, count, taxon_key))

    hits.sort(key=lambda x: x[1], reverse=True)
    found_species_count = len(hits)
    hits = hits[:MAX_SPECIES]

    print("AI Context will be generated for the following species:")
    for name, count, key in hits:
        print(f" - {name} ({count} occurrences)")

    if progress_callback:
        progress_callback("Generating AI ecological context", 85)

    from openai_species_context import enrich_gbif_results_with_openai_batch

    gbif_result = {
        "input": {
            "lat": lat,
            "lon": lon,
            "radius_miles": radius_miles,
            "year_start": 2025,
            "year_end": 2026,
        },
        "hits": [
            {"scientific_name": nm, "gbif_count": cnt, "taxon_key": key}
            for nm, cnt, key in hits
        ],
    }

    enriched = enrich_gbif_results_with_openai_batch(gbif_result)

    if progress_callback:
        progress_callback("Finalizing results", 100)

    return {
        "input": gbif_result["input"],
        "found_species_count": found_species_count,
        "gbif_hits": [
            {"scientific_name": nm, "gbif_count": cnt, "taxon_key": key}
            for nm, cnt, key in hits
        ],
        "species_context": enriched["species_context"],
    }


def main():
    lat, lon = 38.617110, -90.207191
    radius_miles = 5

    result = run_scan(lat, lon, radius_miles)

    print(f"\nIllinois endangered species with GBIF occurrences in ~{radius_miles} miles:\n")

    hits = result["gbif_hits"]
    if not hits:
        print("No matches found.")
        return

    print(f"{'Scientific Name':35} {'GBIF Count':>10} {'taxonKey':>10}")
    print("-" * 60)
    for item in hits:
        print(
            f"{item['scientific_name'][:35]:35} "
            f"{item['gbif_count']:10d} "
            f"{item['taxon_key']:10d}"
        )

    print("\nAI Species Context:\n")
    for item in result["species_context"]:
        print(item["scientific_name"])
        print(item["analysis"])
        print()


if __name__ == "__main__":
    main()
