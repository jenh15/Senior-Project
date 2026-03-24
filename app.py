from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
import threading
import uuid
import os

jobs = {}


import GBIF
from openai_species_context import enrich_gbif_results_with_openai_batch

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

load_dotenv()

TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

jobs = {}

app = FastAPI(
    title="Environmental Screening API",
    description="Environmental screening for endangered species near construction sites",
    version="1.1"
)

# Allow frontend requests during development / deployment
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

Limiter = Limiter(key_func=get_remote_address, default_limits=["100/hour"])
app.state.limiter = Limiter
app.add_middleware(SlowAPIMiddleware)

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please try again later."}
    )

# Request schema
class ScanRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude of the construction site")
    lon: float = Field(..., ge=-180, le=180, description="Longitude of the construction site")
    radius_miles: float = Field(default=0, ge=0, le=100, description="Radius in miles")
    captcha_token: str = Field(..., min_length=1, description="Cloudflare Turnstile token")

async def verify_turnstile(token: str, remote_ip: str | None = None) -> bool:
    if not TURNSTILE_SITE_KEY:
        raise HTTPException(status_code=500, detail="Turnstile secret key not configured")
    data = {
        "secret": TURNSTILE_SITE_KEY,
        "response": token,
    }
    if remote_ip:
        data["remoteip"] = remote_ip

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post("https://challenges.cloudflare.com/turnstile/v0/siteverify", data=data)
        result = response.json()
        response.raise_for_status()

        return bool(result.get("success", False))


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
@Limiter.limit("5/minute;25/hour")
async def start_scan(request: Request, req: ScanRequest):
    is_human = await verify_turnstile(req.captcha_token, request.client.host if request.client else None)

    if not is_human:
        raise HTTPException(status_code=400, detail="Human verification failed")

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
@Limiter.limit("30/minute")
def scan_status(request: Request, job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

