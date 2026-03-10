from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
import threading
import uuid
import os

jobs = {}


import GBIF
from openai_species_context import enrich_gbif_results_with_openai_batch

app = FastAPI(
    title="Environmental Screening API",
    description="Environmental screening for endangered species near construction sites",
    version="1.0"
)

# Allow frontend requests during development / deployment
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request schema
class ScanRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude of the construction site")
    lon: float = Field(..., ge=-180, le=180, description="Longitude of the construction site")
    radius_miles: float = Field(default=0, ge=0, le=100, description="Radius in miles")


def run_scan_job(job_id: str, lat: float, lon: float, radius_miles: float):
    def progress_callback(step_text: str, percent: int):
        jobs[job_id]["step"] = step_text
        jobs[job_id]["progress"] = percent

    try:
        result = GBIF.run_scan(
            lat=lat,
            lon=lon,
            radius_miles=radius_miles,
            progress_callback=progress_callback
        )
        jobs[job_id]["status"] = "complete"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["step"] = "Complete"
        jobs[job_id]["result"] = result
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


@app.get("/")
def root():
    return {"message": "Environmental Screening API is running"}


@app.post("/scan/start")
def start_scan(req: ScanRequest):
    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "status": "running",
        "step": "Starting scan",
        "progress": 0,
        "result": None,
        "error": None
    }

    thread = threading.Thread(
        target=run_scan_job,
        args=(job_id, req.lat, req.lon, req.radius_miles),
        daemon=True
    )
    thread.start()

    return {"job_id": job_id}


@app.get("/scan/status/{job_id}")
def scan_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

