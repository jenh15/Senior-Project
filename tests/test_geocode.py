"""
tests/test_geocode.py

Unit tests for geocode.py covering:
  - normalize_result() pure function
  - geocode_cache_key() and reverse_cache_key() pure functions
  - geocode_with_maptiler() and reverse_with_maptiler() (async, mocked httpx)
  - geocode_with_nominatim() and reverse_with_nominatim() (async, mocked httpx)
  - GET /geocode/search endpoint — cache hit/miss, provider dispatch, error handling
  - GET /geocode/reverse endpoint — cache hit/miss, coordinate validation, errors

All external HTTP calls are mocked.  Cache and rate-limiter state is reset
between tests via autouse fixtures.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import geocode
from geocode import (
    geocode_cache_key,
    normalize_result,
    reverse_cache_key,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """
    Minimal test app with the geocode router mounted at /geocode — matching
    production — but without SlowAPI middleware so rate limits don't fire.
    """
    app = FastAPI()
    app.include_router(geocode.router, prefix="/geocode")
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clear_caches(fake_redis):
    """Flush Redis before and after every test to guarantee a clean cache."""
    fake_redis.flushall()
    yield
    fake_redis.flushall()


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset SlowAPI in-memory storage so rate limits don't bleed between tests."""
    from limiter import limiter
    limiter._storage.reset()
    yield
    limiter._storage.reset()


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

def _mock_httpx(mocker, json_payload):
    """
    Patch geocode.httpx.AsyncClient so any `async with httpx.AsyncClient()`
    block yields a client whose .get() returns json_payload.
    """
    mock_response = MagicMock()
    mock_response.json.return_value = json_payload
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    mocker.patch("geocode.httpx.AsyncClient", return_value=mock_client)
    return mock_client


# Realistic API response payloads
_MAPTILER_FEATURE = {
    "center": [-87.6298, 41.8781],
    "place_name": "Chicago, Illinois, United States",
    "text": "Chicago",
    "bbox": [-87.9, 41.6, -87.5, 42.0],
}

_MAPTILER_RESPONSE = {"features": [_MAPTILER_FEATURE]}

_NOMINATIM_ITEM = {
    "lat": "41.8781",
    "lon": "-87.6298",
    "display_name": "Chicago, Cook County, Illinois, United States",
    "boundingbox": ["41.6", "42.0", "-87.9", "-87.5"],
}

_NOMINATIM_RESPONSE = [_NOMINATIM_ITEM]

_NOMINATIM_REVERSE_RESPONSE = {
    "lat": "41.8781",
    "lon": "-87.6298",
    "display_name": "Chicago, Cook County, Illinois, United States",
    "boundingbox": ["41.6", "42.0", "-87.9", "-87.5"],
}


# ---------------------------------------------------------------------------
# 1. normalize_result() — pure function
# ---------------------------------------------------------------------------

class TestNormalizeResult:

    def test_returns_all_required_keys(self):
        result = normalize_result("Chicago, IL", 41.8781, -87.6298)
        assert set(result.keys()) == {"label", "lat", "lon", "bbox", "raw"}

    def test_label_stored(self):
        result = normalize_result("Chicago, IL", 41.8781, -87.6298)
        assert result["label"] == "Chicago, IL"

    def test_coordinates_stored(self):
        result = normalize_result("Chicago, IL", 41.8781, -87.6298)
        assert result["lat"] == 41.8781
        assert result["lon"] == -87.6298

    def test_bbox_defaults_to_none(self):
        result = normalize_result("Chicago, IL", 41.8781, -87.6298)
        assert result["bbox"] is None

    def test_raw_defaults_to_none(self):
        result = normalize_result("Chicago, IL", 41.8781, -87.6298)
        assert result["raw"] is None

    def test_optional_bbox_stored(self):
        bbox = [-87.9, 41.6, -87.5, 42.0]
        result = normalize_result("Chicago, IL", 41.8781, -87.6298, bbox=bbox)
        assert result["bbox"] == bbox

    def test_optional_raw_stored(self):
        raw = {"source": "test"}
        result = normalize_result("Chicago, IL", 41.8781, -87.6298, raw=raw)
        assert result["raw"] == raw


# ---------------------------------------------------------------------------
# 2. Cache key functions — pure functions
# ---------------------------------------------------------------------------

class TestCacheKeyFunctions:

    # geocode_cache_key
    def test_cache_key_lowercases(self):
        assert geocode_cache_key("CHICAGO") == "chicago"

    def test_cache_key_strips_whitespace(self):
        assert geocode_cache_key("  Chicago  ") == "chicago"

    def test_cache_key_strips_and_lowercases(self):
        assert geocode_cache_key("  CHICAGO IL  ") == "chicago il"

    def test_cache_key_identical_for_case_variants(self):
        assert geocode_cache_key("Chicago IL") == geocode_cache_key("chicago il")

    # reverse_cache_key
    def test_reverse_key_is_a_string(self):
        key = reverse_cache_key(41.8781, -87.6298)
        assert isinstance(key, str)

    def test_reverse_key_rounds_to_three_decimals(self):
        key = reverse_cache_key(41.87812345, -87.62981234)
        assert key == "41.878:-87.63"

    def test_reverse_key_same_for_nearby_coords(self):
        """Tiny float differences within rounding tolerance must share a cache key."""
        assert reverse_cache_key(41.87800, -87.62800) == reverse_cache_key(41.87801, -87.62801)

    def test_reverse_key_differs_for_distant_coords(self):
        assert reverse_cache_key(41.878, -87.629) != reverse_cache_key(42.000, -88.000)


# ---------------------------------------------------------------------------
# 3. geocode_with_maptiler() — async, direct
# ---------------------------------------------------------------------------

class TestGeocodeWithMaptiler:

    @pytest.mark.anyio
    async def test_returns_correct_structure(self, mocker):
        _mock_httpx(mocker, _MAPTILER_RESPONSE)
        result = await geocode.geocode_with_maptiler("Chicago")
        assert result["provider"] == "maptiler"
        assert result["query"] == "Chicago"
        assert "count" in result
        assert "best_match" in result
        assert "results" in result

    @pytest.mark.anyio
    async def test_parses_feature_coordinates(self, mocker):
        _mock_httpx(mocker, _MAPTILER_RESPONSE)
        result = await geocode.geocode_with_maptiler("Chicago")
        best = result["best_match"]
        # MapTiler center is [lon, lat] — function must swap to lat/lon
        assert best["lat"] == pytest.approx(41.8781)
        assert best["lon"] == pytest.approx(-87.6298)

    @pytest.mark.anyio
    async def test_parses_place_name_as_label(self, mocker):
        _mock_httpx(mocker, _MAPTILER_RESPONSE)
        result = await geocode.geocode_with_maptiler("Chicago")
        assert result["best_match"]["label"] == "Chicago, Illinois, United States"

    @pytest.mark.anyio
    async def test_empty_features_returns_no_results(self, mocker):
        _mock_httpx(mocker, {"features": []})
        result = await geocode.geocode_with_maptiler("Nowhere")
        assert result["count"] == 0
        assert result["best_match"] is None
        assert result["results"] == []

    @pytest.mark.anyio
    async def test_skips_features_without_center(self, mocker):
        _mock_httpx(mocker, {"features": [{"place_name": "Bad Feature"}]})
        result = await geocode.geocode_with_maptiler("Bad")
        assert result["count"] == 0

    @pytest.mark.anyio
    async def test_raises_500_when_api_key_missing(self, mocker):
        from fastapi import HTTPException
        mocker.patch("geocode.MAPTILER_API_KEY", "")
        with pytest.raises(HTTPException) as exc_info:
            await geocode.geocode_with_maptiler("Chicago")
        assert exc_info.value.status_code == 500

    @pytest.mark.anyio
    async def test_multiple_features_all_returned(self, mocker):
        two_features = {
            "features": [_MAPTILER_FEATURE, _MAPTILER_FEATURE]
        }
        _mock_httpx(mocker, two_features)
        result = await geocode.geocode_with_maptiler("Chicago")
        assert result["count"] == 2
        assert len(result["results"]) == 2


# ---------------------------------------------------------------------------
# 4. reverse_with_maptiler() — async, direct
# ---------------------------------------------------------------------------

class TestReverseWithMaptiler:

    @pytest.mark.anyio
    async def test_returns_correct_structure(self, mocker):
        _mock_httpx(mocker, _MAPTILER_RESPONSE)
        result = await geocode.reverse_with_maptiler(41.8781, -87.6298)
        assert result["provider"] == "maptiler"
        assert result["count"] == 1
        assert result["best_match"] is not None

    @pytest.mark.anyio
    async def test_empty_features_returns_null_result(self, mocker):
        _mock_httpx(mocker, {"features": []})
        result = await geocode.reverse_with_maptiler(41.8781, -87.6298)
        assert result["count"] == 0
        assert result["best_match"] is None

    @pytest.mark.anyio
    async def test_raises_500_when_api_key_missing(self, mocker):
        from fastapi import HTTPException
        mocker.patch("geocode.MAPTILER_API_KEY", "")
        with pytest.raises(HTTPException) as exc_info:
            await geocode.reverse_with_maptiler(41.8781, -87.6298)
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# 5. geocode_with_nominatim() — async, direct
# ---------------------------------------------------------------------------

class TestGeocodeWithNominatim:

    @pytest.mark.anyio
    async def test_returns_correct_structure(self, mocker):
        _mock_httpx(mocker, _NOMINATIM_RESPONSE)
        result = await geocode.geocode_with_nominatim("Chicago")
        assert result["provider"] == "nominatim"
        assert result["count"] == 1
        assert result["best_match"] is not None

    @pytest.mark.anyio
    async def test_parses_coordinates_as_floats(self, mocker):
        _mock_httpx(mocker, _NOMINATIM_RESPONSE)
        result = await geocode.geocode_with_nominatim("Chicago")
        best = result["best_match"]
        # Nominatim returns lat/lon as strings — function must cast to float
        assert isinstance(best["lat"], float)
        assert isinstance(best["lon"], float)
        assert best["lat"] == pytest.approx(41.8781)

    @pytest.mark.anyio
    async def test_parses_display_name_as_label(self, mocker):
        _mock_httpx(mocker, _NOMINATIM_RESPONSE)
        result = await geocode.geocode_with_nominatim("Chicago")
        assert "Chicago" in result["best_match"]["label"]

    @pytest.mark.anyio
    async def test_empty_list_returns_no_results(self, mocker):
        _mock_httpx(mocker, [])
        result = await geocode.geocode_with_nominatim("Nowhere")
        assert result["count"] == 0
        assert result["best_match"] is None


# ---------------------------------------------------------------------------
# 6. reverse_with_nominatim() — async, direct
# ---------------------------------------------------------------------------

class TestReverseWithNominatim:

    @pytest.mark.anyio
    async def test_returns_correct_structure(self, mocker):
        _mock_httpx(mocker, _NOMINATIM_REVERSE_RESPONSE)
        result = await geocode.reverse_with_nominatim(41.8781, -87.6298)
        assert result["provider"] == "nominatim"
        assert result["count"] == 1
        assert result["best_match"] is not None

    @pytest.mark.anyio
    async def test_parses_coordinates_as_floats(self, mocker):
        _mock_httpx(mocker, _NOMINATIM_REVERSE_RESPONSE)
        result = await geocode.reverse_with_nominatim(41.8781, -87.6298)
        best = result["best_match"]
        assert isinstance(best["lat"], float)
        assert isinstance(best["lon"], float)

    @pytest.mark.anyio
    async def test_empty_response_returns_null_result(self, mocker):
        _mock_httpx(mocker, {})
        result = await geocode.reverse_with_nominatim(41.8781, -87.6298)
        assert result["count"] == 0
        assert result["best_match"] is None


# ---------------------------------------------------------------------------
# 7. GET /geocode/search endpoint
# ---------------------------------------------------------------------------

class TestGeocodeSearchEndpoint:

    def test_returns_200_on_valid_query(self, client, mocker):
        mocker.patch(
            "geocode.geocode_with_maptiler",
            new=AsyncMock(return_value={"provider": "maptiler", "count": 1,
                                        "best_match": None, "results": [], "query": "Chicago"}),
        )
        resp = client.get("/geocode/search", params={"q": "Chicago"})
        assert resp.status_code == 200

    def test_returns_422_when_query_too_short(self, client):
        resp = client.get("/geocode/search", params={"q": "ab"})
        assert resp.status_code == 422

    def test_returns_422_when_query_missing(self, client):
        resp = client.get("/geocode/search")
        assert resp.status_code == 422

    def test_cache_miss_on_first_call(self, client, mocker):
        provider_result = {"provider": "maptiler", "count": 1,
                           "best_match": None, "results": [], "query": "Chicago"}
        mock_fn = mocker.patch("geocode.geocode_with_maptiler",
                               new=AsyncMock(return_value=provider_result))
        client.get("/geocode/search", params={"q": "Chicago"})
        mock_fn.assert_called_once()

    def test_cache_hit_on_second_identical_call(self, client, mocker):
        provider_result = {"provider": "maptiler", "count": 1,
                           "best_match": None, "results": [], "query": "Chicago"}
        mock_fn = mocker.patch("geocode.geocode_with_maptiler",
                               new=AsyncMock(return_value=provider_result))
        client.get("/geocode/search", params={"q": "Chicago"})
        client.get("/geocode/search", params={"q": "Chicago"})
        # Provider should only be called once — second request hits the cache
        mock_fn.assert_called_once()

    def test_cache_hit_returns_cached_true(self, client, mocker):
        provider_result = {"provider": "maptiler", "count": 0,
                           "best_match": None, "results": [], "query": "Chicago"}
        mocker.patch("geocode.geocode_with_maptiler",
                     new=AsyncMock(return_value=provider_result))
        client.get("/geocode/search", params={"q": "Chicago"})
        resp = client.get("/geocode/search", params={"q": "Chicago"})
        assert resp.json()["cached"] is True

    def test_cache_key_is_case_insensitive(self, client, mocker):
        provider_result = {"provider": "maptiler", "count": 0,
                           "best_match": None, "results": [], "query": "chicago"}
        mock_fn = mocker.patch("geocode.geocode_with_maptiler",
                               new=AsyncMock(return_value=provider_result))
        client.get("/geocode/search", params={"q": "Chicago"})
        client.get("/geocode/search", params={"q": "chicago"})
        mock_fn.assert_called_once()

    def test_dispatches_to_nominatim_when_configured(self, client, mocker):
        mocker.patch("geocode.GEOCODER_PROVIDER", "nominatim")
        mock_fn = mocker.patch(
            "geocode.geocode_with_nominatim",
            new=AsyncMock(return_value={"provider": "nominatim", "count": 0,
                                        "best_match": None, "results": [], "query": "Chicago"}),
        )
        client.get("/geocode/search", params={"q": "Chicago"})
        mock_fn.assert_called_once()

    def test_returns_502_on_provider_http_error(self, client, mocker):
        import httpx
        mocker.patch(
            "geocode.geocode_with_maptiler",
            new=AsyncMock(side_effect=httpx.HTTPStatusError(
                "500", request=MagicMock(), response=MagicMock(text="Server Error")
            )),
        )
        resp = client.get("/geocode/search", params={"q": "Chicago"})
        assert resp.status_code == 502

    def test_returns_502_on_provider_request_error(self, client, mocker):
        import httpx
        mocker.patch(
            "geocode.geocode_with_maptiler",
            new=AsyncMock(side_effect=httpx.RequestError("timeout", request=MagicMock())),
        )
        resp = client.get("/geocode/search", params={"q": "Chicago"})
        assert resp.status_code == 502

    def test_unknown_provider_returns_500(self, client, mocker):
        mocker.patch("geocode.GEOCODER_PROVIDER", "unknown_provider")
        resp = client.get("/geocode/search", params={"q": "Chicago"})
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# 8. GET /geocode/reverse endpoint
# ---------------------------------------------------------------------------

class TestReverseGeocodeEndpoint:

    def test_returns_200_on_valid_coordinates(self, client, mocker):
        mocker.patch(
            "geocode.reverse_with_maptiler",
            new=AsyncMock(return_value={"provider": "maptiler", "count": 1,
                                        "best_match": None, "results": [], "cached": False}),
        )
        resp = client.get("/geocode/reverse", params={"lat": 41.8781, "lon": -87.6298})
        assert resp.status_code == 200

    def test_returns_422_for_lat_out_of_range(self, client):
        resp = client.get("/geocode/reverse", params={"lat": 200.0, "lon": 0.0})
        assert resp.status_code == 422

    def test_returns_422_for_lon_out_of_range(self, client):
        resp = client.get("/geocode/reverse", params={"lat": 0.0, "lon": 200.0})
        assert resp.status_code == 422

    def test_returns_422_when_params_missing(self, client):
        resp = client.get("/geocode/reverse")
        assert resp.status_code == 422

    def test_cache_miss_calls_provider(self, client, mocker):
        mock_fn = mocker.patch(
            "geocode.reverse_with_maptiler",
            new=AsyncMock(return_value={"provider": "maptiler", "count": 0,
                                        "best_match": None, "results": [], "cached": False}),
        )
        client.get("/geocode/reverse", params={"lat": 41.8781, "lon": -87.6298})
        mock_fn.assert_called_once()

    def test_cache_hit_on_second_identical_call(self, client, mocker):
        mock_fn = mocker.patch(
            "geocode.reverse_with_maptiler",
            new=AsyncMock(return_value={"provider": "maptiler", "count": 0,
                                        "best_match": None, "results": [], "cached": False}),
        )
        client.get("/geocode/reverse", params={"lat": 41.8781, "lon": -87.6298})
        client.get("/geocode/reverse", params={"lat": 41.8781, "lon": -87.6298})
        mock_fn.assert_called_once()

    def test_cache_hit_returns_cached_true(self, client, mocker):
        mocker.patch(
            "geocode.reverse_with_maptiler",
            new=AsyncMock(return_value={"provider": "maptiler", "count": 0,
                                        "best_match": None, "results": [], "cached": False}),
        )
        client.get("/geocode/reverse", params={"lat": 41.8781, "lon": -87.6298})
        resp = client.get("/geocode/reverse", params={"lat": 41.8781, "lon": -87.6298})
        assert resp.json()["cached"] is True

    def test_nearby_coords_share_cache(self, client, mocker):
        """Coordinates within rounding tolerance (3 decimal places) hit the same cache entry."""
        mock_fn = mocker.patch(
            "geocode.reverse_with_maptiler",
            new=AsyncMock(return_value={"provider": "maptiler", "count": 0,
                                        "best_match": None, "results": [], "cached": False}),
        )
        client.get("/geocode/reverse", params={"lat": 41.878001, "lon": -87.629001})
        client.get("/geocode/reverse", params={"lat": 41.878002, "lon": -87.629002})
        mock_fn.assert_called_once()

    def test_dispatches_to_nominatim_when_configured(self, client, mocker):
        mocker.patch("geocode.GEOCODER_PROVIDER", "nominatim")
        mock_fn = mocker.patch(
            "geocode.reverse_with_nominatim",
            new=AsyncMock(return_value={"provider": "nominatim", "count": 0,
                                        "best_match": None, "results": [], "cached": False}),
        )
        client.get("/geocode/reverse", params={"lat": 41.8781, "lon": -87.6298})
        mock_fn.assert_called_once()

    def test_returns_502_on_provider_http_error(self, client, mocker):
        import httpx
        mocker.patch(
            "geocode.reverse_with_maptiler",
            new=AsyncMock(side_effect=httpx.HTTPStatusError(
                "500", request=MagicMock(), response=MagicMock(text="Server Error")
            )),
        )
        resp = client.get("/geocode/reverse", params={"lat": 41.8781, "lon": -87.6298})
        assert resp.status_code == 502

    def test_returns_502_on_provider_request_error(self, client, mocker):
        import httpx
        mocker.patch(
            "geocode.reverse_with_maptiler",
            new=AsyncMock(side_effect=httpx.RequestError("timeout", request=MagicMock())),
        )
        resp = client.get("/geocode/reverse", params={"lat": 41.8781, "lon": -87.6298})
        assert resp.status_code == 502
