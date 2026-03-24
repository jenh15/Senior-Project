# Endangered Species Detection Prototype
> Authors: Jacob Mitchell    
> Date: 3/10/26   

> Our servers spin down with inactivity, so please be sure to allow for an additional 60 seconds upon arriving to our landing page.    
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

### User Interface
3. Supply coordinates and a radius in miles
4. The program then computes a bounding box (note this bounding box is currently square for simplicity)
5. Make a GBIF call to return all species within the given bounding box
6. Cross checks returned species with **precomputed** `IllinoisTaxonLookup.csv`
7. Send batch request to openAI for additional construction and species context (capped with .env MAX_AI_... default=3)
8. Display flagged results to user

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
> Currently local. Ideal to datascrape new list daily and run `build_taxon_lookup.py` along with it to update our table.  
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

## Geometry based queries
- A bounding box is generated from the radius to perform more reliable GBIF searches.

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

# Requirements

`conda env create -f environment.yml`

---   

# Running the Prototype

Find our frontend here:    
https://environmentscreen.onrender.com    

Example usage inside GBIF.py:   
> Within conda GBIF_env (and with .env file keys / parameters set):   
```
python GBIF.py
``` 

---   

# Environment Variables
- Our project uses environmental variables such as max species openai call count and of course our api key
    - These variables are automatically read by python SDK through vscode reading each members .env file
    - To configure or view format please see `.env.example` - This can be easily created with `cp .env.example .env` before adding your own keys / parameters.

---

# Future Improvements

- Implement species key / taxonID translation daily with updated IllinoisIsEndangered.csv 
- Add geospatial visualization for computed radius  
- Export construction timeline recommendations  
- Improve AI ecological analysis using external species data sources (Wikipedia, species databases)

---   



### Disclaimer
- Our program provides **informational screening only**  
- Results should **always** be verified with environmental professionals and official regulatory databases before making construction decisions.    

---    

https://environmentscreen.onrender.com    