"""
tests/test_scan.py

Unit tests for scan.py covering:
  - ScanRequest Pydantic model validation
  - cleanup_old_jobs() logic
  - run_scan_job() state-machine transitions (called directly, not in a thread)
  - verify_turnstile() success/failure/misconfiguration paths
  - POST /scan/start endpoint behavior
  - GET /scan/status/{job_id} endpoint behavior

All external calls (GBIF, Cloudflare Turnstile) are mocked.
The test client uses a minimal app without SlowAPI middleware so endpoints
can be exercised freely without hitting rate limits.
"""

import threading
import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import redis_client
import scan
from scan import (
    JOB_TTL_SECONDS,
    SCAN_CACHE_TTL_SECONDS,
    ScanRequest,
    cleanup_old_jobs,
    jobs,
    run_scan_job,
    scan_cache_key,
)


# ---------------------------------------------------------------------------
# Fixtures & shared helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """
    Minimal FastAPI app with only the scan router and no SlowAPI middleware.
    This lets tests call endpoints repeatedly without tripping rate limits.
    """
    app = FastAPI()
    app.include_router(scan.router)
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clear_jobs():
    """Wipe module-level job state before and after every test."""
    jobs.clear()
    yield
    jobs.clear()


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """
    Reset the SlowAPI in-memory storage before each test.

    The rate limiter is a module-level singleton (limiter.py).  Without this
    fixture, the 1/hour limit on /scan/start would be exhausted after the
    first test that calls that endpoint, causing subsequent tests to receive
    429 instead of the response they're asserting on.
    """
    from limiter import limiter
    limiter._storage.reset()
    yield
    limiter._storage.reset()


def _wait_for_job(client, job_id: str, timeout: float = 5.0):
    """Poll the status endpoint until the job leaves the 'queued'/'running' states."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/scan/status/{job_id}").json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


def _make_job(age_seconds: float = 0, status: str = "complete") -> dict:
    """Build a job dict for direct insertion into the jobs store."""
    return {
        "status": status,
        "step": "Complete",
        "progress": 100,
        "result": None,
        "error": None,
        "cached": False,
        "created_at": time.time() - age_seconds,
        "started_at": None,
        "completed_at": None,
    }


_FAKE_SCAN_RESULT = {
    "input": {
        "lat": 41.8781,
        "lon": -87.6298,
        "radius_miles": 5.0,
        "year_start": 2025,
        "year_end": 2026,
    },
    "found_species_count": 1,
    "gbif_hits": [
        {"scientific_name": "Myotis sodalis", "gbif_count": 10, "taxon_key": 2435099}
    ],
    "species_context": [
        {
            "scientific_name": "Myotis sodalis",
            "common_name": "Indiana Bat",
            "tags": ["Overwintering", "Tree Clearing"],
            "overview": "Cave-roosting federally endangered bat.",
            "seasonal_concerns": "Hibernates October through April.",
            "disruptive_activities": "Tree clearing and noise.",
            "recommendation": "Avoid winter disturbance.",
        }
    ],
}

_VALID_SCAN_BODY = {
    "lat": 41.8781,
    "lon": -87.6298,
    "radius_miles": 5.0,
    "captcha_token": "valid-token",
}


# ---------------------------------------------------------------------------
# 1. ScanRequest Pydantic model validation
# ---------------------------------------------------------------------------

class TestScanRequestValidation:

    def test_valid_request_accepted(self):
        req = ScanRequest(lat=41.8781, lon=-87.6298, radius_miles=5.0, captcha_token="tok")
        assert req.lat == 41.8781
        assert req.lon == -87.6298
        assert req.radius_miles == 5.0

    # -- Latitude boundaries --

    def test_lat_lower_boundary_accepted(self):
        ScanRequest(lat=-90.0, lon=0.0, radius_miles=0.0, captcha_token="t")

    def test_lat_upper_boundary_accepted(self):
        ScanRequest(lat=90.0, lon=0.0, radius_miles=0.0, captcha_token="t")

    def test_lat_above_max_rejected(self):
        with pytest.raises(ValidationError):
            ScanRequest(lat=90.1, lon=0.0, radius_miles=5.0, captcha_token="t")

    def test_lat_below_min_rejected(self):
        with pytest.raises(ValidationError):
            ScanRequest(lat=-90.1, lon=0.0, radius_miles=5.0, captcha_token="t")

    # -- Longitude boundaries --

    def test_lon_lower_boundary_accepted(self):
        ScanRequest(lat=0.0, lon=-180.0, radius_miles=0.0, captcha_token="t")

    def test_lon_upper_boundary_accepted(self):
        ScanRequest(lat=0.0, lon=180.0, radius_miles=0.0, captcha_token="t")

    def test_lon_above_max_rejected(self):
        with pytest.raises(ValidationError):
            ScanRequest(lat=0.0, lon=180.1, radius_miles=5.0, captcha_token="t")

    def test_lon_below_min_rejected(self):
        with pytest.raises(ValidationError):
            ScanRequest(lat=0.0, lon=-180.1, radius_miles=5.0, captcha_token="t")

    # -- Radius boundaries --

    def test_radius_zero_accepted(self):
        ScanRequest(lat=0.0, lon=0.0, radius_miles=0.0, captcha_token="t")

    def test_radius_max_accepted(self):
        ScanRequest(lat=0.0, lon=0.0, radius_miles=100.0, captcha_token="t")

    def test_radius_above_max_rejected(self):
        with pytest.raises(ValidationError):
            ScanRequest(lat=0.0, lon=0.0, radius_miles=100.1, captcha_token="t")

    def test_radius_negative_rejected(self):
        with pytest.raises(ValidationError):
            ScanRequest(lat=0.0, lon=0.0, radius_miles=-0.1, captcha_token="t")

    # -- Captcha token --

    def test_empty_captcha_token_rejected(self):
        with pytest.raises(ValidationError):
            ScanRequest(lat=0.0, lon=0.0, radius_miles=5.0, captcha_token="")

    def test_captcha_token_at_max_length_accepted(self):
        ScanRequest(lat=0.0, lon=0.0, radius_miles=5.0, captcha_token="t" * 2048)

    def test_captcha_token_exceeding_max_length_rejected(self):
        with pytest.raises(ValidationError):
            ScanRequest(lat=0.0, lon=0.0, radius_miles=5.0, captcha_token="t" * 2049)


# ---------------------------------------------------------------------------
# 2. cleanup_old_jobs()
# ---------------------------------------------------------------------------

class TestCleanupOldJobs:

    def test_expired_job_is_removed(self):
        jobs["old"] = _make_job(age_seconds=JOB_TTL_SECONDS + 1)
        cleanup_old_jobs()
        assert "old" not in jobs

    def test_fresh_job_is_kept(self):
        jobs["fresh"] = _make_job(age_seconds=0)
        cleanup_old_jobs()
        assert "fresh" in jobs

    def test_empty_dict_does_not_crash(self):
        cleanup_old_jobs()  # must not raise

    def test_only_expired_jobs_removed(self):
        jobs["old"] = _make_job(age_seconds=JOB_TTL_SECONDS + 10)
        jobs["fresh"] = _make_job(age_seconds=10)
        cleanup_old_jobs()
        assert "old" not in jobs
        assert "fresh" in jobs

    def test_multiple_expired_jobs_all_removed(self):
        for i in range(5):
            jobs[f"old_{i}"] = _make_job(age_seconds=JOB_TTL_SECONDS + 100)
        cleanup_old_jobs()
        assert len(jobs) == 0

    def test_job_just_past_ttl_is_removed(self):
        jobs["borderline"] = _make_job(age_seconds=JOB_TTL_SECONDS + 0.001)
        cleanup_old_jobs()
        assert "borderline" not in jobs


# ---------------------------------------------------------------------------
# 3. run_scan_job() — state-machine transitions
#    Called directly (not in a thread) so state is observable synchronously.
# ---------------------------------------------------------------------------

class TestRunScanJob:

    def _seed_job(self, job_id: str):
        """Pre-populate jobs dict exactly as start_scan does."""
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

    def test_success_sets_complete_status(self, mocker):
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        mocker.patch("GBIF.run_scan", return_value=_FAKE_SCAN_RESULT)

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        assert jobs[jid]["status"] == "complete"
        assert jobs[jid]["progress"] == 100
        assert jobs[jid]["error"] is None

    def test_success_stores_result(self, mocker):
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        mocker.patch("GBIF.run_scan", return_value=_FAKE_SCAN_RESULT)

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        assert jobs[jid]["result"] == _FAKE_SCAN_RESULT

    def test_gbif_error_sets_error_status(self, mocker):
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        mocker.patch("GBIF.run_scan", side_effect=RuntimeError("GBIF unavailable"))

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        assert jobs[jid]["status"] == "error"

    def test_gbif_error_message_stored(self, mocker):
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        mocker.patch("GBIF.run_scan", side_effect=RuntimeError("GBIF unavailable"))

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        assert "GBIF unavailable" in jobs[jid]["error"]

    def test_error_path_leaves_result_as_none(self, mocker):
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        mocker.patch("GBIF.run_scan", side_effect=ValueError("bad input"))

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        assert jobs[jid]["result"] is None

    def test_progress_callback_updates_step_and_percent(self, mocker):
        """GBIF.run_scan receives a live callback that writes into the job."""
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        snapshots = []

        def fake_run_scan(lat, lon, radius_miles, progress_callback=None):
            if progress_callback:
                progress_callback("Loading taxon lookup", 10)
                snapshots.append(jobs[jid].copy())
                progress_callback("Querying GBIF", 35)
                snapshots.append(jobs[jid].copy())
            return _FAKE_SCAN_RESULT

        mocker.patch("GBIF.run_scan", side_effect=fake_run_scan)
        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        assert snapshots[0]["step"] == "Loading taxon lookup"
        assert snapshots[0]["progress"] == 10
        assert snapshots[1]["step"] == "Querying GBIF"
        assert snapshots[1]["progress"] == 35

    def test_completed_at_set_on_success(self, mocker):
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        mocker.patch("GBIF.run_scan", return_value=_FAKE_SCAN_RESULT)

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        assert jobs[jid]["completed_at"] is not None

    def test_completed_at_set_on_error(self, mocker):
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        mocker.patch("GBIF.run_scan", side_effect=RuntimeError("fail"))

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        assert jobs[jid]["completed_at"] is not None


# ---------------------------------------------------------------------------
# 4. verify_turnstile() — tested directly with a mocked httpx.AsyncClient
# ---------------------------------------------------------------------------

def _build_httpx_mock(mocker, json_payload: dict):
    """
    Patch scan.httpx.AsyncClient so that any `async with httpx.AsyncClient()`
    block resolves to a mock whose .post() returns json_payload.
    """
    mock_response = MagicMock()
    mock_response.json.return_value = json_payload
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    mocker.patch("scan.httpx.AsyncClient", return_value=mock_client)
    return mock_client


@pytest.mark.anyio
async def test_verify_turnstile_returns_true_on_success(mocker):
    _build_httpx_mock(mocker, {"success": True})
    result = await scan.verify_turnstile("valid-token", "1.2.3.4")
    assert result is True


@pytest.mark.anyio
async def test_verify_turnstile_returns_false_on_failure(mocker):
    _build_httpx_mock(mocker, {"success": False, "error-codes": ["invalid-input-response"]})
    result = await scan.verify_turnstile("bad-token", "1.2.3.4")
    assert result is False


@pytest.mark.anyio
async def test_verify_turnstile_raises_500_when_secret_key_missing(mocker):
    from fastapi import HTTPException

    mocker.patch("scan.TURNSTILE_SECRET_KEY", "")
    with pytest.raises(HTTPException) as exc_info:
        await scan.verify_turnstile("any-token")
    assert exc_info.value.status_code == 500


@pytest.mark.anyio
async def test_verify_turnstile_includes_remote_ip_when_provided(mocker):
    mock_client = _build_httpx_mock(mocker, {"success": True})
    await scan.verify_turnstile("tok", remote_ip="10.0.0.1")

    call_kwargs = mock_client.post.call_args[1] if mock_client.post.call_args[1] else {}
    call_data = call_kwargs.get("data", mock_client.post.call_args[0][1] if mock_client.post.call_args[0][1:] else {})
    assert call_data.get("remoteip") == "10.0.0.1"


@pytest.mark.anyio
async def test_verify_turnstile_omits_remote_ip_when_none(mocker):
    mock_client = _build_httpx_mock(mocker, {"success": True})
    await scan.verify_turnstile("tok", remote_ip=None)

    call_kwargs = mock_client.post.call_args[1] if mock_client.post.call_args[1] else {}
    call_data = call_kwargs.get("data", {})
    assert "remoteip" not in call_data


# ---------------------------------------------------------------------------
# 5. POST /scan/start endpoint
# ---------------------------------------------------------------------------

class TestScanStartEndpoint:

    def test_returns_job_id_when_verified(self, client, mocker):
        mocker.patch("scan.verify_turnstile", new=AsyncMock(return_value=True))
        mocker.patch("GBIF.run_scan", return_value=_FAKE_SCAN_RESULT)

        resp = client.post("/scan/start", json=_VALID_SCAN_BODY)

        assert resp.status_code == 200
        assert "job_id" in resp.json()

    def test_job_id_is_a_valid_uuid(self, client, mocker):
        mocker.patch("scan.verify_turnstile", new=AsyncMock(return_value=True))
        mocker.patch("GBIF.run_scan", return_value=_FAKE_SCAN_RESULT)

        resp = client.post("/scan/start", json=_VALID_SCAN_BODY)
        job_id = resp.json()["job_id"]

        # Will raise ValueError if not a valid UUID
        uuid.UUID(job_id)

    def test_job_appears_in_jobs_store(self, client, mocker):
        mocker.patch("scan.verify_turnstile", new=AsyncMock(return_value=True))
        mocker.patch("GBIF.run_scan", return_value=_FAKE_SCAN_RESULT)

        resp = client.post("/scan/start", json=_VALID_SCAN_BODY)
        job_id = resp.json()["job_id"]

        assert job_id in jobs

    def test_returns_400_when_turnstile_fails(self, client, mocker):
        mocker.patch("scan.verify_turnstile", new=AsyncMock(return_value=False))

        resp = client.post("/scan/start", json=_VALID_SCAN_BODY)

        assert resp.status_code == 400
        assert "verification" in resp.json()["detail"].lower()

    def test_returns_422_for_invalid_coordinates(self, client, mocker):
        mocker.patch("scan.verify_turnstile", new=AsyncMock(return_value=True))

        resp = client.post("/scan/start", json={
            **_VALID_SCAN_BODY,
            "lat": 999.0,  # invalid
        })

        assert resp.status_code == 422

    def test_returns_422_for_missing_fields(self, client):
        resp = client.post("/scan/start", json={"lat": 41.8781})
        assert resp.status_code == 422

    def test_no_job_created_when_turnstile_fails(self, client, mocker):
        mocker.patch("scan.verify_turnstile", new=AsyncMock(return_value=False))

        client.post("/scan/start", json=_VALID_SCAN_BODY)

        assert len(jobs) == 0


# ---------------------------------------------------------------------------
# 6. GET /scan/status/{job_id} endpoint
# ---------------------------------------------------------------------------

class TestScanStatusEndpoint:

    def test_returns_404_for_unknown_job(self, client):
        resp = client.get(f"/scan/status/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_returns_200_for_known_job(self, client):
        jid = str(uuid.uuid4())
        jobs[jid] = _make_job(status="complete")

        resp = client.get(f"/scan/status/{jid}")
        assert resp.status_code == 200

    def test_response_contains_required_fields(self, client):
        jid = str(uuid.uuid4())
        jobs[jid] = _make_job(status="running")

        body = client.get(f"/scan/status/{jid}").json()

        for field in ("status", "step", "progress", "result", "error", "cached"):
            assert field in body, f"Missing expected field: {field}"

    def test_reflects_queued_status(self, client):
        jid = str(uuid.uuid4())
        jobs[jid] = _make_job(status="queued")
        jobs[jid]["progress"] = 0

        body = client.get(f"/scan/status/{jid}").json()
        assert body["status"] == "queued"

    def test_reflects_error_status_and_message(self, client):
        jid = str(uuid.uuid4())
        jobs[jid] = _make_job(status="error")
        jobs[jid]["error"] = "Something went wrong"

        body = client.get(f"/scan/status/{jid}").json()
        assert body["status"] == "error"
        assert body["error"] == "Something went wrong"

    def test_reflects_progress_value(self, client):
        jid = str(uuid.uuid4())
        jobs[jid] = _make_job(status="running")
        jobs[jid]["progress"] = 60
        jobs[jid]["step"] = "Querying GBIF"

        body = client.get(f"/scan/status/{jid}").json()
        assert body["progress"] == 60
        assert body["step"] == "Querying GBIF"


# ---------------------------------------------------------------------------
# 7. Redis scan caching
# ---------------------------------------------------------------------------

class TestScanCaching:

    def test_cache_hit_skips_gbif(self, client, mocker, fake_redis):
        """A cached scan result must not trigger a GBIF API call."""
        key = scan_cache_key(41.8781, -87.6298, 5.0)
        redis_client.cache_set(key, _FAKE_SCAN_RESULT, SCAN_CACHE_TTL_SECONDS)

        mocker.patch("scan.verify_turnstile", new=AsyncMock(return_value=True))
        mock_gbif = mocker.patch("GBIF.run_scan")

        client.post("/scan/start", json=_VALID_SCAN_BODY)

        mock_gbif.assert_not_called()

    def test_cache_hit_job_is_immediately_complete(self, client, mocker, fake_redis):
        """A cache hit must return a job that is already in the 'complete' state."""
        key = scan_cache_key(41.8781, -87.6298, 5.0)
        redis_client.cache_set(key, _FAKE_SCAN_RESULT, SCAN_CACHE_TTL_SECONDS)

        mocker.patch("scan.verify_turnstile", new=AsyncMock(return_value=True))
        resp = client.post("/scan/start", json=_VALID_SCAN_BODY)
        job_id = resp.json()["job_id"]

        body = client.get(f"/scan/status/{job_id}").json()
        assert body["status"] == "complete"
        assert body["progress"] == 100

    def test_cache_hit_sets_cached_flag(self, client, mocker, fake_redis):
        """Jobs served from the cache must have cached=True."""
        key = scan_cache_key(41.8781, -87.6298, 5.0)
        redis_client.cache_set(key, _FAKE_SCAN_RESULT, SCAN_CACHE_TTL_SECONDS)

        mocker.patch("scan.verify_turnstile", new=AsyncMock(return_value=True))
        resp = client.post("/scan/start", json=_VALID_SCAN_BODY)
        job_id = resp.json()["job_id"]

        assert client.get(f"/scan/status/{job_id}").json()["cached"] is True

    def test_cache_hit_result_matches_cached_data(self, client, mocker, fake_redis):
        """The job result must equal the value that was stored in Redis."""
        key = scan_cache_key(41.8781, -87.6298, 5.0)
        redis_client.cache_set(key, _FAKE_SCAN_RESULT, SCAN_CACHE_TTL_SECONDS)

        mocker.patch("scan.verify_turnstile", new=AsyncMock(return_value=True))
        resp = client.post("/scan/start", json=_VALID_SCAN_BODY)
        job_id = resp.json()["job_id"]

        body = client.get(f"/scan/status/{job_id}").json()
        assert body["result"] == _FAKE_SCAN_RESULT

    def test_cache_miss_calls_gbif(self, client, mocker, fake_redis):
        """An empty cache must result in a real GBIF scan being started."""
        mocker.patch("scan.verify_turnstile", new=AsyncMock(return_value=True))
        mock_gbif = mocker.patch("GBIF.run_scan", return_value=_FAKE_SCAN_RESULT)

        resp = client.post("/scan/start", json=_VALID_SCAN_BODY)
        job_id = resp.json()["job_id"]

        # Wait for the background thread to finish before asserting.
        _wait_for_job(client, job_id)

        mock_gbif.assert_called_once()

    def test_run_scan_job_stores_result_in_redis(self, mocker, fake_redis):
        """After a successful scan, the result must be persisted in Redis."""
        jid = str(uuid.uuid4())
        jobs[jid] = {
            "status": "queued", "step": "Queued", "progress": 0,
            "result": None, "error": None, "cached": False,
            "created_at": time.time(), "started_at": None, "completed_at": None,
        }
        mocker.patch("GBIF.run_scan", return_value=_FAKE_SCAN_RESULT)

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        key = scan_cache_key(41.8781, -87.6298, 5.0)
        assert redis_client.cache_get(key) == _FAKE_SCAN_RESULT

    def test_run_scan_job_error_does_not_cache(self, mocker, fake_redis):
        """A failed scan must not write anything to Redis."""
        jid = str(uuid.uuid4())
        jobs[jid] = {
            "status": "queued", "step": "Queued", "progress": 0,
            "result": None, "error": None, "cached": False,
            "created_at": time.time(), "started_at": None, "completed_at": None,
        }
        mocker.patch("GBIF.run_scan", side_effect=RuntimeError("API down"))

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        key = scan_cache_key(41.8781, -87.6298, 5.0)
        assert redis_client.cache_get(key) is None

    def test_scan_cache_key_normalizes_nearby_coords(self):
        """Coordinates within 3 decimal place rounding must produce the same key."""
        assert scan_cache_key(41.87800, -87.62800, 5.0) == scan_cache_key(41.87801, -87.62801, 5.0)

    def test_scan_cache_key_distinguishes_different_coords(self):
        assert scan_cache_key(41.878, -87.629, 5.0) != scan_cache_key(42.000, -88.000, 5.0)

    def test_scan_cache_key_distinguishes_different_radii(self):
        assert scan_cache_key(41.878, -87.629, 5.0) != scan_cache_key(41.878, -87.629, 10.0)

    def test_scan_cache_key_has_scan_prefix(self):
        assert scan_cache_key(41.878, -87.629, 5.0).startswith("scan:")

    def test_scan_cache_key_rounds_radius_to_one_decimal(self):
        """Radii that differ only beyond 1 decimal place must share a cache key."""
        assert scan_cache_key(41.878, -87.629, 5.01) == scan_cache_key(41.878, -87.629, 5.04)

    def test_scan_cache_key_different_one_decimal_radii_differ(self):
        assert scan_cache_key(41.878, -87.629, 5.0) != scan_cache_key(41.878, -87.629, 5.1)


# ---------------------------------------------------------------------------
# 8. run_scan_job() — scanned_at timestamp
# ---------------------------------------------------------------------------

class TestRunScanJobTimestamp:

    def _seed_job(self, job_id):
        jobs[job_id] = {
            "status": "queued", "step": "Queued", "progress": 0,
            "result": None, "error": None, "cached": False,
            "created_at": time.time(), "started_at": None, "completed_at": None,
        }

    def test_success_embeds_scanned_at_in_result(self, mocker):
        """run_scan_job must inject scanned_at into the result before storing it."""
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        mocker.patch("GBIF.run_scan", return_value={**_FAKE_SCAN_RESULT})

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        assert "scanned_at" in jobs[jid]["result"]

    def test_scanned_at_is_a_float(self, mocker):
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        mocker.patch("GBIF.run_scan", return_value={**_FAKE_SCAN_RESULT})

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        assert isinstance(jobs[jid]["result"]["scanned_at"], float)

    def test_scanned_at_is_recent(self, mocker):
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        before = time.time()
        mocker.patch("GBIF.run_scan", return_value={**_FAKE_SCAN_RESULT})

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        assert jobs[jid]["result"]["scanned_at"] >= before


# ---------------------------------------------------------------------------
# 9. run_scan_job() — watchdog timer
# ---------------------------------------------------------------------------

class TestRunScanJobWatchdog:

    def _seed_job(self, job_id):
        jobs[job_id] = {
            "status": "queued", "step": "Queued", "progress": 0,
            "result": None, "error": None, "cached": False,
            "created_at": time.time(), "started_at": None, "completed_at": None,
        }

    def test_watchdog_timer_is_started(self, mocker):
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        mock_timer = MagicMock()
        mocker.patch("scan.threading.Timer", return_value=mock_timer)
        mocker.patch("GBIF.run_scan", return_value={**_FAKE_SCAN_RESULT})

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        mock_timer.start.assert_called_once()

    def test_watchdog_cancelled_after_success(self, mocker):
        """Timer must always be cancelled when the scan completes normally."""
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        mock_timer = MagicMock()
        mocker.patch("scan.threading.Timer", return_value=mock_timer)
        mocker.patch("GBIF.run_scan", return_value={**_FAKE_SCAN_RESULT})

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        mock_timer.cancel.assert_called_once()

    def test_watchdog_cancelled_after_error(self, mocker):
        """Timer must be cancelled even if GBIF raises an exception."""
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        mock_timer = MagicMock()
        mocker.patch("scan.threading.Timer", return_value=mock_timer)
        mocker.patch("GBIF.run_scan", side_effect=RuntimeError("GBIF down"))

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        mock_timer.cancel.assert_called_once()

    def test_watchdog_callback_marks_running_job_as_error(self, mocker):
        """If the watchdog fires while the job is still running, it must set status='error'."""
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        captured = {}

        def capture_timer(delay, fn):
            captured["fn"] = fn
            return MagicMock()

        mocker.patch("scan.threading.Timer", side_effect=capture_timer)
        mocker.patch("GBIF.run_scan", return_value={**_FAKE_SCAN_RESULT})

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        # Simulate the timer firing against a mid-scan "running" job
        jobs[jid]["status"] = "running"
        captured["fn"]()

        assert jobs[jid]["status"] == "error"
        assert "time limit" in jobs[jid]["error"]

    def test_watchdog_callback_is_noop_when_job_already_complete(self, mocker):
        """If the scan finishes before the timer fires, the callback must not overwrite status."""
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        captured = {}

        def capture_timer(delay, fn):
            captured["fn"] = fn
            return MagicMock()

        mocker.patch("scan.threading.Timer", side_effect=capture_timer)
        mocker.patch("GBIF.run_scan", return_value={**_FAKE_SCAN_RESULT})

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        assert jobs[jid]["status"] == "complete"
        captured["fn"]()  # fire the timer callback late
        assert jobs[jid]["status"] == "complete"

    def test_watchdog_callback_is_noop_when_job_errored(self, mocker):
        jid = str(uuid.uuid4())
        self._seed_job(jid)
        captured = {}

        def capture_timer(delay, fn):
            captured["fn"] = fn
            return MagicMock()

        mocker.patch("scan.threading.Timer", side_effect=capture_timer)
        mocker.patch("GBIF.run_scan", side_effect=RuntimeError("GBIF down"))

        run_scan_job(jid, 41.8781, -87.6298, 5.0)

        assert jobs[jid]["status"] == "error"
        original_error = jobs[jid]["error"]
        captured["fn"]()  # should not overwrite the existing error message
        assert jobs[jid]["error"] == original_error
