# Threatened Species Database

This folder contains two files that build the threatened species database used by the species search feature. `build_database.py` pulls all threatened species from the IUCN Red List API and saves them to a local SQLite database. `match_gbif_keys.py` then matches each species to a GBIF species key using the GBIF backbone taxonomy file, which is what allows the search feature to find occurrences in GBIF.

This process only needs to be done once. The database can optionally be refreshed every 6 months or so since the IUCN Red List updates periodically.

---

## Requirements

Set up the environment using the provided `environment.yml` file:

```bash
conda env create -f environment.yml
conda activate search_env
```

---

## Before You Start

### 1. Get an IUCN API Token

Register for a free token at https://api.iucnredlist.org/

Once you have your token, create a file called `config.py` in the same directory as these scripts. This file must never be committed to GitHub:

```python
# config.py
IUCN_TOKEN = "your_token_here"
```

### 2. Download the GBIF Backbone Taxonomy

Download the backbone taxonomy file from:
https://www.gbif.org/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c

Click **Download** and extract the ZIP file. You need the file called `Taxon.tsv`. Place it in the same directory as these scripts.

This file is around 1-2GB and is not included in the repo. It only needs to be downloaded once.

---

## Step 1: Build the Database — `build_database.py`

Connects to the IUCN Red List API and fetches all species in the following threat categories:
- **CR** — Critically Endangered
- **EN** — Endangered
- **VU** — Vulnerable

Only the latest assessment for each species is kept to avoid historic duplicates. Results are saved to `threatened_species.db` with the following columns:

| Column | Description |
|---|---|
| `iucn_id` | IUCN species ID (primary key) |
| `scientific_name` | Scientific name from IUCN |
| `threat_status` | CR, EN, or VU |
| `gbif_species_key` | GBIF species key (added in Step 2) |
| `match_type` | Match confidence (added in Step 2) |

### How to Run

```bash
python build_database.py
```

### Notes

- The IUCN API returns 100 species per page so this script paginates automatically. Expect it to take 30–60 minutes to fetch all categories.
- Re-running the script is safe — `INSERT OR IGNORE` prevents duplicates.
- The database file `threatened_species.db` will be created in the same directory.

### Rate Limiting
The IUCN API may occasionally return a 429 (Too Many Requests) error during 
fetching. If this happens the script will stop early and your database will 
be incomplete for that category. Simply re-run the script — already inserted 
species will be skipped and it will re-fetch the category from the beginning 
until it completes successfully.

### Example Output

```
Database created at threatened_species.db
  Fetching CR page 1...
  Fetching CR page 2...
  Fetching CR page 3...
  .
  .
  Fetching CR page 175...
  Found 10774 latest global CR species (190 regional assessments skipped)
  Inserted 9213 new species, skipped 1561 duplicates
  .
  .
Database Summary:
  Total species: 48,646
  CR: 10774 species
  EN: 19873 species
  VU: 17999 species
```

---

## Step 2: Match GBIF Species Keys — `match_gbif_keys.py`

Loads the GBIF backbone taxonomy file and matches each species in the database to a GBIF species key using the scientific name. This key is what the search feature uses to find occurrences in GBIF.

Matching is done in this order:

1. **Exact match** against accepted species in the backbone
2. **Trimmed match** — trims subspecies info to just genus and species name
3. **Case insensitive match** against accepted species
4. **Fallback exact match** against the full unfiltered backbone
5. **Fallback trimmed match** against the full unfiltered backbone
6. **NONE** — no match found

Results are saved back to the database under `gbif_species_key` and `match_type`.

### How to Run

```bash
python match_gbif_keys.py
```

### Notes

- Progress is saved every 500 species so if the script is stopped it can be resumed — it automatically skips species that already have a key.
- Re-running the script will retry any species previously marked as NONE in case the backbone file has been updated.
- Expected results: approximately 92% EXACT, 6% FUZZY, 2% NONE.

### Match Types Explained

| Match Type | Meaning | Used in Search? |
|---|---|---|
| EXACT | Perfect name match on accepted species | Yes |
| FUZZY | Matched after name simplification or via fallback | Yes |
| NONE | No match found in backbone | No |

FUZZY matches are safe to use — they represent the same species matched at a slightly broader level, typically due to subspecies naming differences between IUCN and GBIF.

### Example Output (after being ran a second time)

```
Loading GBIF backbone file (this may take a moment)...
Backbone loaded: 2598208 accepted species found
Lookup dictionary built with 2552706 entries
Building fallback dictionary from full backbone...
Fallback dictionary built with 3326580 additional entries
Found 48646 unmatched or NONE species to process
  Progress: 500/48646 processed (EXACT: 440, FUZZY: 38, NONE: 22)
  Progress: 1000/48646 processed (EXACT: 893, FUZZY: 68, NONE: 39)
  Progress: 1500/48646 processed (EXACT: 1349, FUZZY: 89, NONE: 62)
  Progress: 2000/48646 processed (EXACT: 1794, FUZZY: 134, NONE: 72)
  Progress: 2500/48646 processed (EXACT: 2254, FUZZY: 150, NONE: 96)
  .
  .
Matching Summary (48646 total species):
  EXACT: 44725
  FUZZY: 2866
  NONE: 1055

Done! Your database now has GBIF species keys paired with IUCN threat status.
```

---

## Disclaimer

- Results reflect species assessed as threatened at the global level by the IUCN Red List. Species that are regionally threatened but globally stable are excluded.

- Global threat status does not equal legal protection. Always consult federal and state wildlife agencies before making construction or land use decisions.

- Threatened species data is sourced from the IUCN Red List. Some species may not be matched to a GBIF key due to naming differences between the two databases. These species will not appear in search results. This affects approximately 2% of species in the database.


