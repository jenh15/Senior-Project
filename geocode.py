import os
import threading
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query, Request
from limiter import limiter
from cachetools import TTLCache

load_dotenv()

router = APIRouter()

GEOCODER_PROVIDER = os.getenv("GEOCODER_PROVIDER", "maptiler").lower()
MAPTILER_API_KEY = os.getenv("MAPTILER_API_KEY", "")
APP_USER_AGENT = os.getenv("APP_USER_AGENT", "environmental-screening-prototype/1.0")


# Cache settings
GEOCODE_CACHE_TTL_SECONDS = 86400   # 24 hours
REVERSE_CACHE_TTL_SECONDS = 86400
GEOCODE_CACHE_MAXSIZE = 1000
REVERSE_CACHE_MAXSIZE = 1000

# In memory TTL caches
geocode_cache = TTLCache(maxsize=GEOCODE_CACHE_MAXSIZE, ttl=GEOCODE_CACHE_TTL_SECONDS)
reverse_cache = TTLCache(maxsize=REVERSE_CACHE_MAXSIZE, ttl=REVERSE_CACHE_TTL_SECONDS)

# cachetools caches are not thread safe by default, so guard access
geocode_cache_lock = threading.Lock()
reverse_cache_lock = threading.Lock()


def normalize_result(label: str, lat: float, lon: float, bbox=None, raw=None):
    return {
        "label": label,
        "lat": lat,
        "lon": lon,
        "bbox": bbox,
        "raw": raw,
    }

def geocode_cache_key(query: str) -> str:
    return query.strip().lower()

def reverse_cache_key(lat: float, lon: float) -> tuple[float, float]:
    # round a bit so tiny float differences don't miss cache
    return (round(lat, 5), round(lon, 5))

async def geocode_with_maptiler(query: str) -> dict:
    if not MAPTILER_API_KEY:
        raise HTTPException(status_code=500, detail="MAPTILER_API_KEY is not configured")

    encoded_query = quote(query)
    url = f"https://api.maptiler.com/geocoding/{encoded_query}.json"
    params = {
        "key": MAPTILER_API_KEY,
        "limit": 5,
        "country": "us",
    }
    print("[MAPTILER CALL]")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    features = data.get("features", [])
    results = []

    for feature in features:
        center = feature.get("center", [])
        if len(center) < 2:
            continue

        lon, lat = center[0], center[1]
        results.append(
            normalize_result(
                label=feature.get("place_name") or feature.get("text") or "Unknown location",
                lat=lat,
                lon=lon,
                bbox=feature.get("bbox"),
                raw=feature,
            )
        )

    return {
        "provider": "maptiler",
        "query": query,
        "count": len(results),
        "best_match": results[0] if results else None,
        "results": results,
    }


async def reverse_with_maptiler(lat: float, lon: float) -> dict:
    if not MAPTILER_API_KEY:
        raise HTTPException(status_code=500, detail="MAPTILER_API_KEY is not configured")

    url = f"https://api.maptiler.com/geocoding/{lon},{lat}.json"
    params = {
        "key": MAPTILER_API_KEY,
        "limit": 1,
    }
    print("[MAPTILER CALL]")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    features = data.get("features", [])
    if not features:
        return {
            "provider": "maptiler",
            "count": 0,
            "best_match": None,
            "results": [],
            "cached": False,
        }

    feature = features[0]
    center = feature.get("center", [lon, lat])

    result = normalize_result(
        label=feature.get("place_name") or feature.get("text") or "Unknown location",
        lat=center[1],
        lon=center[0],
        bbox=feature.get("bbox"),
        raw=feature,
    )

    return {
        "provider": "maptiler",
        "count": 1,
        "best_match": result,
        "results": [result],
        "cached": False,
    }


async def geocode_with_nominatim(query: str) -> dict:
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 5,
        "countrycodes": "us",
    }
    headers = {
        "User-Agent": APP_USER_AGENT,
    }
    print("[NOMINATIM CALL]")
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data:
        results.append(
            normalize_result(
                label=item.get("display_name", "Unknown location"),
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                bbox=item.get("boundingbox"),
                raw=item,
            )
        )

    return {
        "provider": "nominatim",
        "query": query,
        "count": len(results),
        "best_match": results[0] if results else None,
        "results": results,
        "cached": False,
    }


async def reverse_with_nominatim(lat: float, lon: float) -> dict:
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
    }
    headers = {
        "User-Agent": APP_USER_AGENT,
    }
    print("[NOMINATIM CALL]")
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    if not data:
        return {
            "provider": "nominatim",
            "count": 0,
            "best_match": None,
            "results": [],
            "cached": False,
        }

    result = normalize_result(
        label=data.get("display_name", "Unknown location"),
        lat=float(data["lat"]),
        lon=float(data["lon"]),
        bbox=data.get("boundingbox"),
        raw=data,
    )

    return {
        "provider": "nominatim",
        "count": 1,
        "best_match": result,
        "results": [result],
        "cached": False,
    }


@router.get("/search")
@limiter.limit("3/minute")
async def geocode_search(
    request: Request,
    q: str = Query(..., min_length=3, description="Address or place query"),
):
    
    key = geocode_cache_key(q)

    with geocode_cache_lock:
        cached = geocode_cache.get(key)

    if cached is not None:
        print(f"[CACHE HIT] geocode search: {q}") # DEBUG
        return {
            **cached,
            "cached": True,
        }
    print(f"[CACHE MISS] geocode search: {q}") #DEBUG

    try:
        if GEOCODER_PROVIDER == "maptiler":
            result = await geocode_with_maptiler(q)
        elif GEOCODER_PROVIDER == "nominatim":
            result = await geocode_with_nominatim(q)
        else :
            raise HTTPException(
                status_code=500,
                detail=f"Unsupported geocoder provider: {GEOCODER_PROVIDER}",
            )
        with geocode_cache_lock:
            geocode_cache[key] = result

        return result

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Geocoding provider error: {exc.response.text}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Geocoding request failed: {str(exc)}",
        ) from exc


@router.get("/reverse")
@limiter.limit("3/minute")
async def reverse_geocode(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    key = reverse_cache_key(lat, lon)

    with reverse_cache_lock:
        cached = reverse_cache.get(key)

    if cached is not None:
        print(f"[CACHE HIT] reverse: {lat}, {lon}") # DEBUG
        return {
            **cached,
            "cached": True,
        }
    print(f"[CACHE MISS] reverse: {lat}, {lon}") # DEBUG

    try:
        if GEOCODER_PROVIDER == "maptiler":
            result = await reverse_with_maptiler(lat, lon)
        elif GEOCODER_PROVIDER == "nominatim":
            result = await reverse_with_nominatim(lat, lon)

        else:
            raise HTTPException(
            status_code=500,
            detail=f"Unsupported geocoder provider: {GEOCODER_PROVIDER}",
        )
    
        with reverse_cache_lock:
            reverse_cache[key] = result

        return result
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Reverse geocoding provider error: {exc.response.text}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Reverse geocoding request failed: {str(exc)}",
        ) from exc