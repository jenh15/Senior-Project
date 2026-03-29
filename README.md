# Endangered Species Detection Prototype
> Authors: Jacob Mitchell    
> Date: 3/10/26   

> Our servers spin down with inactivity, so please be sure to allow for an additional 60 seconds upon making your first request to our backend.    
https://environmentscreen.onrender.com     


This program is a prototype application designed to help construction planners identify potential environmental risks **before** beginning a project. The system analyzes biodiversity data from the **Global Biodiversity Information Facility (GBIF)** and cross references it with the **Illinois Endangered Species list** to identify protected species near a proposed construction site.    

This tool performs a **preliminary environmental screening** by checking for documented or sighted species occurrences within a specified geographic radius.    

---      

# Project Purpose

Construction projects may be delayed or halted if endangered or threatened species are present near a site. Currently, this review process often requires manual research across multiple datasets.       

Our program automates this first step by:    

1. Accepting a project location    
2. Searching GBIF biodiversity databases for species sightings    
3. Comparing detected species with the Illinois endangered species list    
4. Returning flagged species that may impact a project plan   
5. Provide additional context to flagged species to user with additional information on how it may interact with their construction process     

This version focuses on the **data pipeline / detection logic / additional ecological analysis by openai api calls / frontend**     

---   

# System Workflow
### Precomputed
1. Parses Illinois Endangered list
2. Translate Illinois Endangered list to taxonIDs saving a CSV with scientific names and their corresponding taxonID
    - Script located at `scripts/build_taxon_lookup.py`, output written to `data/IllinoisTaxonLookup.csv`

### User Interface
3. Supply an address or coordinates and a radius in miles (address search powered by MapTiler Geocoding API)
4. The program then computes a bounding box (note this bounding box is currently square for simplicity)
5. Check Redis cache — if a matching scan exists for the same location and radius, return the cached result immediately
6. Make a GBIF call to return all species within the given bounding box
7. Cross checks returned species with **precomputed** `data/IllinoisTaxonLookup.csv`
8. Send batch request to openAI for additional construction and species context (capped with .env MAX_AI_... default=3)
9. Store result in Redis cache (24-hour TTL)
10. Display flagged results to user

---   

# Data Sources

## GBIF (Global Biodiversity Information Facility)
https://www.gbif.org   

Used for retrieving species occurrence records based on geographic location.   

GBIF API endpoints used:  

Occurrence Search  
https://api.gbif.org/v1/occurrence/search   

Species Name Matching  
- Only used during precomputed `IllinoisTaxonLookup.csv`   
https://api.gbif.org/v1/species/match   

---   

## Illinois Endangered Species List
> Currently local. Ideal to datascrape new list daily and run `scripts/build_taxon_lookup.py` along with it to update our table.
- Local CSV dataset containing endangered and threatened species observed in Illinois.

Example structure:   

"County","Scientific Name","Common Name","State Status","Informal Taxonomy","Last Observed","# of Records"   

**Example entries:**   

- Pulaski, Tilia americana var. heterophylla, White Basswood, LE, Dicots, 5/7/2005, 1  
- Piatt, Phlox pilosa ssp. sangamonensis, Sangamon Phlox, LE, Dicots, 6/4/2020, 4

The program precomputes a translated list, scientific name followed by taxonID, prior to user input to allow for faster runtimes   
**Example entries in precomputed translation csv:**    
- Justicia ovata,2393
- Kinosternon flavescens,2442437

---   

# Key Features

## Geocoding / Address Search
- The `/geocode/search` endpoint accepts a plain-text address and returns coordinates, powered by the **MapTiler Geocoding API**.
- `/geocode/reverse` accepts coordinates and returns a human-readable address label.
- Both endpoints are Redis-cached (24-hour TTL) to avoid duplicate lookups.

## Geometry based queries
- A bounding box is generated from the radius to perform more reliable GBIF searches.

## Redis Caching
> Requires a running Redis instance. See [Environment Variables](#environment-variables) for setup.
- Scan results are cached by location and radius so repeated requests for the same area skip all GBIF and OpenAI calls entirely.
    - Cache key: `scan:{lat}:{lon}:{radius}` — coordinates rounded to 3 decimal places (~111 m precision), radius rounded to 1 decimal place
    - Cache TTL: 24 hours
- Geocode and reverse-geocode responses are also cached in Redis (24-hour TTL) so address lookups aren't repeated unnecessarily.
- All Redis operations degrade gracefully — if Redis is unavailable, the app continues without caching and logs a `[REDIS ERROR]` message rather than crashing.
- In local development with Redis running (WSL2: `sudo service redis-server start`), cache hits will appear in the terminal as `[SCAN CACHE HIT]`.

## Bot Protection & API Security
> To prevent automated abuse of our environmental screening API, I've implemented human verification along with rate limiting.    
- Features Added:
    - Cloudflare Turnstile integration
        - Invisible / low friction human verification (no captchas)
        - Token generated on frontend then verified on backend
    - Backend token validation
        - All `/scan/start` requests now require a valid Turnstile token
    - Rate limiting
        - Limits applied per IP to prevent excessive calling abuse
    - CORS hardened
        - Restricted to approved frontend origin only
- How it works:
    - User submits scan request from frontend
    - Turnstile generates a verification token
    - Token is sent with the request to the backend
    - Backend validates token with Cloudflare
    - If valid proceed, if not reject

## Precomputed species lookup for Illinois Endangered Species List
- Species names are resolved to their taxonIDs prior to user input to improve performance.

## Endangered species detection
- Species are only considered from the official **Illinois Endangered Species List**, ignoring all other occurences of different species from **GBIF**

## AI Ecological Context Analysis
- After endangered species are detected, our system will generate additional context using openAI api to return more information to the user
- The module `openai_species_context.py` analyzes each flagged species in a batch call with a max count being defined in the .env by the runner
- The AI analysis may include
    - Important ecological behaviors
    - Breeding / migration seasonal considerations
    - Construction activities that are deemed most disruptive
    - A cautious recommendation for when construction may be the least disruptive
- Example output:
```
Myotis sodalis

Indiana bats are particularly sensitive to disturbance during maternity
season when females form roosting colonies in trees. Construction
activities involving tree clearing, heavy noise, or nighttime lighting
during late spring and summer may disrupt these colonies. If possible,
major disturbance activities may be less disruptive outside the
maternity season, typically late fall through winter.    
```
- To ensure performance remains high and reduce costs, the program will send **all** detected species in one single openai request rather than a request for each detected animal

---   

# Current Limitations
> [!WARNING]
> GBIF sightings may not always include subspecies names as seen in **Illinois Endangered Species List**   

Example:   

GBIF may report:   
Tilia americana   

Illinois listing:   
Tilia americana var. heterophylla   

In these cases the species level occurrence is used   

This tool is intended for **early stage environmental screening**, not regulatory compliance, as we **cannot guarantee** the absence of false positives or false negatives.

---   

# Project Structure

```
Senior-Project/
├── app.py                        # FastAPI application entry point
├── scan.py                       # Scan endpoint + background job runner
├── geocode.py                    # Geocode / reverse-geocode endpoints
├── GBIF.py                       # GBIF API interaction + species matching logic
├── openai_species_context.py     # OpenAI batch context analysis
├── redis_client.py               # Redis wrapper (cache_get / cache_set / cache_delete)
├── limiter.py                    # SlowAPI rate limiter configuration
├── data/
│   ├── IsEndangered.csv          # Raw Illinois Endangered Species list
│   └── IllinoisTaxonLookup.csv   # Precomputed scientific name → taxonID lookup
├── scripts/
│   └── build_taxon_lookup.py     # Script to regenerate IllinoisTaxonLookup.csv
├── tests/
│   ├── test_scan.py
│   ├── test_geocode.py
│   ├── test_GBIF.py
│   └── test_openai_species_context.py
├── conftest.py                   # Pytest fixtures (fakeredis autouse)
├── requirements.txt
├── requirements-dev.txt
├── environment.yml
└── .env.example
```

---

# Requirements

```
conda env create -f environment.yml
```

Or with pip directly:

```
pip install -r requirements.txt
pip install -r requirements-dev.txt   # for development / testing
```

---

# Running the Prototype

Find our frontend here:
https://environmentscreen.onrender.com

To run the backend locally:
> Within conda GBIF_env (and with `.env` file keys / parameters set):
```
uvicorn app:app --reload
```

To regenerate the taxon lookup CSV after updating `data/IsEndangered.csv`:
```
python scripts/build_taxon_lookup.py
```

---

# Testing

The project uses **pytest** with **fakeredis** for test isolation — no real Redis server is required to run the tests.

```
pytest tests/
```

A GitHub Actions CI workflow (`.github/workflows/test.yml`) runs the full test suite automatically on every push and pull request to `main`.

---

# Environment Variables
- Our project uses environmental variables such as max species openai call count and of course our api key
    - These variables are automatically read by python SDK through vscode reading each members `.env` file
    - To configure or view format please see `.env.example` — this can be created with `cp .env.example .env` before adding your own keys / parameters.

| Variable | Description | Default |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API key for ecological context analysis | — |
| `MAX_SPECIES_FOR_AI` | Max species sent to OpenAI per scan | `3` |
| `MAPTILER_API_KEY` | MapTiler API key for geocoding | — |
| `TURNSTILE_SECRET_KEY` | Cloudflare Turnstile secret for bot protection | — |
| `FRONTEND_ORIGIN` | Allowed CORS origin | `http://localhost:5173` |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379` |

> For Render.com deployments, set `REDIS_URL` to the **internal** Redis URL provided by your Render Redis service — `localhost` will not work in a hosted environment.

---

# Future Improvements

- Implement species key / taxonID translation daily with updated IllinoisIsEndangered.csv
- Export construction timeline recommendations
- Improve AI ecological analysis using external species data sources (Wikipedia, species databases)
- Expand coverage beyond Illinois to other state endangered species lists

---   



### Disclaimer
- Our program provides **informational screening only**  
- Results should **always** be verified with environmental professionals and official regulatory databases before making construction decisions.    

---    

https://environmentscreen.onrender.com    