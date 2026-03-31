import os
import threading
import time
import uuid
from typing import Any, Optional

import logging

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from limiter import limiter
import redis_client
import GBIF

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter()

TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")
JOB_TTL_SECONDS = 3600           # Time-to-live for job records
SCAN_CACHE_TTL_SECONDS = 86400   # Cache completed scan results for 24 hours
MAX_JOB_SECONDS = 180            # Kill a scan that runs longer than 3 minutes

jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


class ScanRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lon: float = Field(..., ge=-180, le=180, description="Longitude")
    radius_miles: float = Field(..., ge=0, le=100, description="Scan radius in miles")
    captcha_token: str = Field(..., min_length=1, max_length=2048, description="Cloudflare Turnstile token")


def scan_cache_key(lat: float, lon: float, radius_miles: float) -> str:
    """
    Build a Redis key for a scan result.  Coordinates are rounded to 3 decimal
    places (~111 m precision) and radius to 1 decimal place so that requests
    for nearly identical locations reuse the same cached result.
    """
    return f"scan:{round(lat, 3)}:{round(lon, 3)}:{round(radius_miles, 1)}"


def cleanup_old_jobs():
    now = time.time()
    with _jobs_lock:
        expired = [
            job_id for job_id, job in jobs.items()
            if now - job.get("created_at", now) > JOB_TTL_SECONDS
        ]
        for job_id in expired:
            jobs.pop(job_id, None)


async def verify_turnstile(token: str, remote_ip: Optional[str] = None) -> bool:
    if not TURNSTILE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="TURNSTILE_SECRET_KEY is not configured")

    payload = {
        "secret": TURNSTILE_SECRET_KEY,
        "response": token,
    }

    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data=payload,
            )
            resp.raise_for_status()
            result = resp.json()
    except httpx.TimeoutException:
        logger.error("Turnstile verification timed out")
        raise HTTPException(status_code=503, detail="Human verification service timed out. Please try again.")
    except httpx.HTTPStatusError as exc:
        logger.error("Turnstile returned HTTP %s", exc.response.status_code)
        raise HTTPException(status_code=502, detail="Human verification service returned an error. Please try again.")
    except httpx.RequestError as exc:
        logger.error("Turnstile request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Could not reach human verification service. Please try again.")

    return bool(result.get("success", False))


def run_scan_job(job_id: str, lat: float, lon: float, radius_miles: float):
    def progress_callback(step_text: str, percent: int):
        jobs[job_id]["step"] = step_text
        jobs[job_id]["progress"] = percent

    def _on_timeout():
        if jobs.get(job_id, {}).get("status") in ("running", "queued"):
            jobs[job_id]["status"] = "error"
            jobs[job_id]["step"] = "Timed out"
            jobs[job_id]["error"] = f"Scan exceeded the {MAX_JOB_SECONDS}s time limit"
            jobs[job_id]["completed_at"] = time.time()
            logger.warning("Job %s timed out after %ds", job_id, MAX_JOB_SECONDS)

    watchdog = threading.Timer(MAX_JOB_SECONDS, _on_timeout)
    watchdog.daemon = True
    watchdog.start()

    try:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["step"] = "Starting scan"
        jobs[job_id]["progress"] = 0
        jobs[job_id]["started_at"] = time.time()

        result = GBIF.run_scan(
            lat=lat,
            lon=lon,
            radius_miles=radius_miles,
            progress_callback=progress_callback,
        )

        result["scanned_at"] = time.time()

        jobs[job_id]["status"] = "complete"
        jobs[job_id]["step"] = "Complete"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["result"] = result
        jobs[job_id]["error"] = None
        jobs[job_id]["completed_at"] = time.time()

        key = scan_cache_key(lat, lon, radius_miles)
        if redis_client.cache_set(key, result, SCAN_CACHE_TTL_SECONDS):
            logger.info("SCAN CACHE SET %s", key)
        else:
            logger.warning("SCAN CACHE SET FAILED %s — Redis unavailable or write error", key)

    except Exception as exc:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["step"] = "Failed"
        jobs[job_id]["error"] = str(exc)
        jobs[job_id]["completed_at"] = time.time()

    finally:
        watchdog.cancel()


@router.post("/scan/start")
@limiter.limit("3/hour")
async def start_scan(request: Request, req: ScanRequest):
    is_human = await verify_turnstile(
        req.captcha_token,
        request.client.host if request.client else None,
    )

    if not is_human:
        raise HTTPException(status_code=400, detail="Human verification failed")

    cleanup_old_jobs()

    cache_key = scan_cache_key(req.lat, req.lon, req.radius_miles)
    cached_result = redis_client.cache_get(cache_key)

    if cached_result is not None:
        logger.info("SCAN CACHE HIT %s", cache_key)
        job_id = str(uuid.uuid4())
        now = time.time()
        with _jobs_lock:
            jobs[job_id] = {
                "status": "complete",
                "step": "Complete (cached)",
                "progress": 100,
                "result": cached_result,
                "error": None,
                "cached": True,
                "created_at": now,
                "started_at": now,
                "completed_at": now,
            }
        return {"job_id": job_id}

    logger.info("SCAN CACHE MISS %s", cache_key)
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        jobs[job_id] = {
            "status": "queued",
            "step": "Queued",
            "progress": 0,
            "result": None,
            "error": None,
            "cached": False,
            "created_at": time.time(),
            "started_at": None,
            "completed_at": None,
        }

    thread = threading.Thread(
        target=run_scan_job,
        args=(job_id, req.lat, req.lon, req.radius_miles),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id}


@router.get("/scan/status/{job_id}")
@limiter.limit("60/minute")
def scan_status(request: Request, job_id: str):
    with _jobs_lock:
        job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
