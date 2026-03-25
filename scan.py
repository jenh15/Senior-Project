import os
import threading
import uuid
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from limiter import limiter

import GBIF

load_dotenv()

router = APIRouter()

TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")

jobs: dict[str, dict] = {}


class ScanRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lon: float = Field(..., ge=-180, le=180, description="Longitude")
    radius_miles: float = Field(..., ge=0, le=100, description="Scan radius in miles")
    captcha_token: str = Field(..., min_length=1, description="Cloudflare Turnstile token")


async def verify_turnstile(token: str, remote_ip: Optional[str] = None) -> bool:
    if not TURNSTILE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="TURNSTILE_SECRET_KEY is not configured")

    payload = {
        "secret": TURNSTILE_SECRET_KEY,
        "response": token,
    }

    if remote_ip:
        payload["remoteip"] = remote_ip

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=payload,
        )
        resp.raise_for_status()
        result = resp.json()

    return bool(result.get("success", False))


def run_scan_job(job_id: str, lat: float, lon: float, radius_miles: float):
    def progress_callback(step_text: str, percent: int):
        jobs[job_id]["step"] = step_text
        jobs[job_id]["progress"] = percent

    try:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["step"] = "Starting scan"
        jobs[job_id]["progress"] = 0

        
        result = GBIF.run_scan(
            lat=lat,
            lon=lon,
            radius_miles=radius_miles,
            progress_callback=progress_callback,
        )

        jobs[job_id]["status"] = "complete"
        jobs[job_id]["step"] = "Complete"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["result"] = result
        jobs[job_id]["error"] = None

    except Exception as exc:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["step"] = "Failed"
        jobs[job_id]["error"] = str(exc)


@router.post("/scan/start")
@limiter.limit("5/minute;50/hour")
async def start_scan(request: Request, req: ScanRequest):
    is_human = await verify_turnstile(
        req.captcha_token,
        request.client.host if request.client else None,
    )

    if not is_human:
        raise HTTPException(status_code=400, detail="Human verification failed")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued",
        "step": "Queued",
        "progress": 0,
        "result": None,
        "error": None,
    }

    thread = threading.Thread(
        target=run_scan_job,
        args=(job_id, req.lat, req.lon, req.radius_miles),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id}


@router.get("/scan/status/{job_id}")
@limiter.limit("180/minute")
def scan_status(request: Request, job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job