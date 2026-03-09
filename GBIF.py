# GBIF.py

import csv
import math
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Stop early if your key isn't set in environment through .env or cli
import os
api_key = os.getenv("OPENAI_API_KEY")
if "OPENAI_API_KEY" not in os.environ:
    raise RuntimeError("OPENAI_API_KEY environment variable not set. Please rerun after setting your key.")


GBIF_MATCH = "https://api.gbif.org/v1/species/match"
GBIF_OCC_SEARCH = "https://api.gbif.org/v1/occurrence/search"
MAX_SPECIES = int(os.getenv("MAX_SPECIES_FOR_AI", 10)) # Highest amount of species that can be sent to our openAI call

def miles_to_km(mi: float) -> float:
    return mi * 1.609344

def bounding_box_polygon(lat: float, lon: float, radius_km: float) -> str:
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)) + 1e-12)
    min_lat, max_lat = lat - lat_delta, lat + lat_delta
    min_lon, max_lon = lon - lon_delta, lon + lon_delta
    return (
        f"POLYGON(({min_lon} {min_lat},"
        f"{min_lon} {max_lat},"
        f"{max_lon} {max_lat},"
        f"{max_lon} {min_lat},"
        f"{min_lon} {min_lat}))"
    )

def load_il_scientific_names(path: str) -> list[str]:
    names = set()
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            nm = (row.get("Scientific Name") or "").strip()
            if nm:
                # keep binomial only (Genus species)
                parts = nm.split()
                if len(parts) >= 2:
                    names.add(f"{parts[0]} {parts[1]}")
                else:
                    names.add(nm)
    return sorted(names)

def gbif_match_to_taxonkey(name: str) -> int | None:
    # /species/match is the intended GBIF endpoint for name→backbone key mapping
    j = requests.get(GBIF_MATCH, params={"name": name}, timeout=20).json()
    key = j.get("usageKey") or j.get("speciesKey")
    return int(key) if key else None

def gbif_count_occurrences(geometry_wkt: str, taxon_key: int) -> int:
    params = {
        "geometry": geometry_wkt,
        "taxonKey": taxon_key,
        "hasCoordinate": "true",
        "year": "2020,2025", # range
        "limit": 0,  # we only need the total "count"
    }
    j = requests.get(GBIF_OCC_SEARCH, params=params, timeout=30).json()
    return int(j.get("count", 0))

def main():
    # Example location
    # TODO:
    lat, lon = 41.8781, -87.6298
    radius_miles = 7
    radius_km = miles_to_km(radius_miles)
    geom = bounding_box_polygon(lat, lon, radius_km)

    il_names = load_il_scientific_names("IsEndangered.csv")
    print(f"Loaded {len(il_names)} unique IL-listed scientific names")

    # 1) Map IL names -> GBIF taxonKeys (parallel w/ workers)
    name_to_key = {}
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(gbif_match_to_taxonkey, nm): nm for nm in il_names}
        for fut in as_completed(futures):
            nm = futures[fut]
            try:
                key = fut.result()
                if key:
                    name_to_key[nm] = key
            except Exception:
                pass

    print(f"Matched {len(name_to_key)} names to GBIF backbone keys")

    # 2) Count occurrences for each taxonKey in the geometry (parallel w/ workers)
    hits = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(gbif_count_occurrences, geom, key): (nm, key)
                   for nm, key in name_to_key.items()}
        for fut in as_completed(futures):
            nm, key = futures[fut]
            try:
                cnt = fut.result()
                if cnt > 0:
                    hits.append((nm, cnt, key))
            except Exception:
                pass

    hits.sort(key=lambda x: x[1], reverse=True)

    print(f"\nIL endangered species with GBIF occurrences in ~{radius_miles} miles:\n")
    if not hits:
        print("No matches found.")
        return

    print(f"{'Scientific Name':35} {'GBIF Count':>10} {'taxonKey':>10}")
    print("-" * 60)
    for nm, cnt, key in hits:
        print(f"{nm[:35]:35} {cnt:10d} {key:10d}")


    hits = hits[:MAX_SPECIES] # Cap for at most 10 of our species to be sent for additional context for openai

    # openAI --- additional context calls
    from openai_species_context import enrich_gbif_results_with_openai_batch

    # Convert results into the structure expected by the OpenAI module
    gbif_result = {
        "input": {
            "lat": lat,
            "lon": lon,
            "radius_miles": radius_miles,
            "year_start": 2020,
            "year_end": 2025
        },
        "hits": [
            {
                "scientific_name": nm,
                "gbif_count": cnt,
                "taxon_key": key
            }
            for nm, cnt, key in hits
        ]
    }

    enriched = enrich_gbif_results_with_openai_batch(gbif_result)

    print("\nAI Species Context:\n")

    for item in enriched["species_context"]:
        print(item["scientific_name"])
        print(item["analysis"])
        print()

if __name__ == "__main__":
    main()