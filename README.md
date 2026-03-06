# Endangered Species Detection Prototype
> Authors: Jacob Mitchell    
> Date: 3/5/26   


This program is a prototype application designed to help construction planners identify potential environmental risks **before** beginning a project. The system analyzes biodiversity data from the **Global Biodiversity Information Facility (GBIF)** and cross references it with the **Illinois Endangered Species list** to identify protected species near a proposed construction site.    

This tool performs a **preliminary environmental screening** by checking for documented or sighted species occurrences within a specified geographic radius.    

---      

# Project Purpose

Construction projects may be delayed or halted if endangered or threatened species are present near a site. Currently, this review process often requires manual research across multiple datasets.       

Our program automates this first step by:    

1. Accepting a project location    
2. Searching biodiversity databases for species sightings    
3. Comparing detected species with the Illinois endangered species list    
4. Returning flagged species that may impact a project plan   
5. Provide additional context to flagged species to user with additional information on how it may interact with their construction process     

This version focuses on the **data pipeline and detection logic and additional ecological analysis by openai api calls**     

---   

# System Workflow

**TODO:**
> This current version, 
1. Parse Illinois Endangered list
2. Translate Illinois Endangered list to taxonIDs (map)
3. Check our bounding box, computed because this is more reliable than GBIF radius, for sightings for each taxonID
4. Return flagged results and counts
5. Feed top flagged results (up until MAXAICOUNT configured in .env) in batch to openai api to output additional ecological analysis to user     

---   

# Data Sources

## GBIF (Global Biodiversity Information Facility)
https://www.gbif.org   

Used for retrieving species occurrence records based on geographic location.   

GBIF API endpoints used:  

Occurrence Search  
https://api.gbif.org/v1/occurrence/search   

Species Lookup  
https://api.gbif.org/v1/species/{speciesKey}   

Species Name Matching  
https://api.gbif.org/v1/species/match   

---   

## Illinois Endangered Species List
> Currently local. Ideal to datascrape new list daily.  
- Local CSV dataset containing endangered and threatened species observed in Illinois.

Example structure:   

"County","Scientific Name","Common Name","State Status","Informal Taxonomy","Last Observed","# of Records"   

**Example entries:**   

- Pulaski, Tilia americana var. heterophylla, White Basswood, LE, Dicots, 5/7/2005, 1  
- Piatt, Phlox pilosa ssp. sangamonensis, Sangamon Phlox, LE, Dicots, 6/4/2020, 4

The program extracts the **Scientific Name** column and uses it to identify endangered species.   

---   

# Key Features

## Geometry based queries
- A bounding box polygon is generated from the radius to perform reliable GBIF searches.

## Parallel species lookup
- Species names are resolved using concurrent requests to improve performance.

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
> Currently investigating how to solve this issue   

In these cases the species level occurrence is used   

This tool is intended for **early stage environmental screening**, not regulatory compliance, as we **cannot guarantee** the absence of false positives or false negatives.

---   

# Requirements

`conda env create -f environment.yml`

---   

# Running the Prototype

Example usage inside GBIF.py:   
> Within conda GBIF_env (and with .env file keys / parameters set):   
```
python GBIF.py
```

---   

# Repository Structure

Senior-Project/   
│   
├── GBIF.py   
├── openai_species_context.py   
├── .env.example   
├── IsEndangered.csv   
└── README.md   

GBIF.py – main script  
IsEndangered.csv – Illinois endangered species dataset  
openai_species_context.py - OpenAI ecological context analysis     
README.md - Project documentation    
.env.example - Environment variable template for runner parameters    


---   

# Environment Variables
- Our project uses environmental variables such as max species openai call count and of course our api key
    - These variables are automatically read by python SDK through vscode reading each members .env file
    - To configure or view format please see `.env.example` - This can be easily created with `cp .env.example .env` before adding your own keys / parameters.

---

# Future Improvements

- Integrate Illinois Natural Heritage Database directly (daily data scrape for updated information) 
- Implement species key / taxonID translation daily rather than during runtime (one time mass API call)
- Improve subspecies detection  
- ???Add geospatial visualization??? (map interface)  
- Export construction timeline recommendations  
- Improve AI ecological analysis using external species data sources (Wikipedia, species databases)

---   



### Disclaimer
- Our program provides **informational screening only**  
- Results should **always** be verified with environmental professionals and official regulatory databases before making construction decisions.