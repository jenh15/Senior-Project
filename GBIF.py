from GBIF_Helper import (
    get_species_names_in_radius,
    load_illinois_endangered_set,
    flag_illinois_endangered,
)

lat, lon = 39.579827, -89.308537
radius_miles = 50

illinois_set = load_illinois_endangered_set("IsEndangered.csv")

resolved = get_species_names_in_radius(
    lat, lon, radius_miles,
    top_n=500,
    max_workers=10,
    # Optional filters to reduce noise:
    # basis_of_record="HUMAN_OBSERVATION",
    year_range=(2025, 2026),
)

flagged = flag_illinois_endangered(resolved, illinois_set)


print(f"{'Species Name':45} {'Count':>8} {'Key':>10} {'IL Listed':>10}")
print("-" * 80)
for name, cnt, key, il in flagged:
    prefix = "⚠ " if il else "  "
    il_txt = "YES" if il else ""
    print(f"{prefix}{name[:43]:43} {cnt:8d} {key:>10} {il_txt:>10}")