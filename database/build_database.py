import requests
import sqlite3
import time
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import IUCN_TOKEN

'''
In order to run this file, you must have an
API token from https://api.iucnredlist.org/
and assign your token to `IUCN_TOKEN`

Tokens must be kept private to prevent others from misusing
it, which is why our token was stored in a config.py file
'''

HEADERS = {'Authorization': f'Bearer {IUCN_TOKEN}'}
IUCN_BASE = "https://api.iucnredlist.org/api/v4"
DB_PATH = "database/threatened_species.db"

# Categories we want to include
CATEGORIES = ["CR", "EN", "VU"]


# Creates the SQLite database and table if they don't exist.
def create_database():

    # SQL Queries
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS threatened_species (
            iucn_id           INTEGER PRIMARY KEY,
            scientific_name   TEXT NOT NULL,
            threat_status     TEXT NOT NULL,
            gbif_species_key  INTEGER,
            match_type        TEXT
        )
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_gbif_key 
        ON threatened_species(gbif_species_key)
    ''')
    
    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")


# Only fetches 100 results per page, so it is slow
def fetch_species_for_category(category_code):
    # Building API call 
    url = f"{IUCN_BASE}/red_list_categories/{category_code}"
    
    species_list = []
    skipped_regional = 0
    page = 1

    while True:
        print(f"  Fetching {category_code} page {page}...")
        response = requests.get(url, headers=HEADERS, params={'page': page})

        if response.status_code != 200:
            print(f"Error fetching {category_code} page {page}: {response.status_code}")
            break

        data = response.json()
        assessments = data.get('assessments', [])

        # If no assessments came back we've gone past the last page
        if not assessments:
            print(f"  No more results at page {page}, stopping.")
            break

        for assessment in assessments:
            if not assessment.get('latest', False):
                continue

            # Only keep global assessments (scope code '1')
            # Regional assessments can list a species as threatened even if
            # it is Least Concern globally, which would cause false positives
            scopes = assessment.get('scopes', [])
            scope_codes = [s.get('code') for s in scopes]
            if '1' not in scope_codes:
                skipped_regional += 1
                continue

            species_list.append({
                'iucn_id':         assessment['sis_taxon_id'],
                'scientific_name': assessment['taxon_scientific_name'],
                'threat_status':   assessment['red_list_category_code']
            })

        # If less than 100 came back we're on the last page
        if len(assessments) < 100:
            break

        page += 1
        time.sleep(1.0)  # be polite between page calls

    print(f"  Found {len(species_list)} latest global {category_code} species "
          f"({skipped_regional} regional assessments skipped)")
    
    return species_list


def save_species_to_db(species_list):
    """
    Saves a list of species to the SQLite database.
    Uses INSERT OR IGNORE so re-running the script won't create duplicates.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    inserted = 0
    skipped = 0

    # SQL Query
    for species in species_list:
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO threatened_species 
                (iucn_id, scientific_name, threat_status)
                VALUES (?, ?, ?)
            ''', (
                species['iucn_id'],
                species['scientific_name'],
                species['threat_status']
            ))

            if cursor.rowcount > 0:
                inserted += 1
            else:
                skipped += 1

        except Exception as e:
            print(f"Error inserting {species['scientific_name']}: {e}")

    conn.commit()
    conn.close()
    print(f"  Inserted {inserted} new species, skipped {skipped} duplicates")


def verify_database():
    """Prints a summary of what was saved to the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Total count
    cursor.execute("SELECT COUNT(*) FROM threatened_species")
    total = cursor.fetchone()[0]
    print(f"\nDatabase Summary:")
    print(f"  Total species: {total}")

    # Count per threat status
    cursor.execute('''
        SELECT threat_status, COUNT(*) 
        FROM threatened_species 
        GROUP BY threat_status
        ORDER BY threat_status
    ''')
    rows = cursor.fetchall()
    for row in rows:
        print(f"  {row[0]}: {row[1]} species")

    # Show a few example rows
    print(f"\nExample rows:")
    cursor.execute("SELECT * FROM threatened_species LIMIT 5")
    rows = cursor.fetchall()
    for row in rows:
        print(f"  {row}")

    conn.close()


# MAIN: RUN ALL STEPS
if __name__ == "__main__":

    # Create the database
    create_database()

    # Fetch each category and save to database
    for category in CATEGORIES:
        species_list = fetch_species_for_category(category)

        if species_list:
            save_species_to_db(species_list)

        # Small delay between category calls to be polite to the API
        time.sleep(1)

    # Verify what was saved
    verify_database()

    print(f"\nDone! Database saved to {DB_PATH}")
    print("You can now use this database to match against GBIF species keys.")
