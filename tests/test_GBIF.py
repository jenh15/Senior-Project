"""
tests/test_GBIF.py

Unit tests for GBIF.py — covering unit conversion, bounding-box geometry,
CSV loading, and the GBIF occurrence API call (mocked).

FUTURE-PROOFING NOTE
--------------------
The project plans to replace the square bounding box with a true circle or
polygon search area.  Tests are split into two logical groups:

  1. TestBoundingBoxGeometry  — tests specific to the *current* square-bbox
     implementation.  These may need to be updated when the shape changes.

  2. TestSearchAreaContract   — tests that express *invariants* that should
     hold for ANY search-area implementation (bbox, circle, polygon).
     When you refactor get_bounding_box() into, say, get_search_polygon(),
     update the `search_area_contains` helper below and all contract tests
     should continue to pass without modification.
"""

import csv
import io
import math
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

import GBIF


# ---------------------------------------------------------------------------
# Geometry helpers — update these when the search-area shape changes
# ---------------------------------------------------------------------------

def bbox_contains_point(bbox, lat: float, lon: float) -> bool:
    """Return True if (lat, lon) falls inside a bounding-box 4-tuple."""
    min_lat, max_lat, min_lon, max_lon = bbox
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def bbox_span_degrees(bbox):
    """Return (lat_span, lon_span) in degrees for a bounding-box 4-tuple."""
    min_lat, max_lat, min_lon, max_lon = bbox
    return max_lat - min_lat, max_lon - min_lon


# When you switch to polygon/circle, replace the two functions above with
# something like:
#
#   def polygon_contains_point(polygon_vertices, lat, lon) -> bool: ...
#   def circle_contains_point(center, radius_km, lat, lon) -> bool: ...
#
# and update the `search_area_contains` alias below:

search_area_contains = bbox_contains_point


# ---------------------------------------------------------------------------
# 1. Unit conversion
# ---------------------------------------------------------------------------

class TestMilesToKm:
    def test_known_value(self):
        assert GBIF.miles_to_km(1.0) == pytest.approx(1.609344)

    def test_zero(self):
        assert GBIF.miles_to_km(0.0) == 0.0

    def test_ten_miles(self):
        assert GBIF.miles_to_km(10.0) == pytest.approx(16.09344)

    def test_fractional(self):
        assert GBIF.miles_to_km(0.5) == pytest.approx(0.804672)

    def test_linearity(self):
        """Conversion must be strictly linear: f(2x) == 2*f(x)."""
        assert GBIF.miles_to_km(10.0) == pytest.approx(2 * GBIF.miles_to_km(5.0))


# ---------------------------------------------------------------------------
# 2. Bounding-box geometry — current square implementation
# ---------------------------------------------------------------------------

class TestBoundingBoxGeometry:
    """Tests specific to the current square bounding-box implementation."""

    # -- Return type / structure --

    def test_returns_four_values(self):
        result = GBIF.get_bounding_box(41.8781, -87.6298, 5.0)
        assert len(result) == 4, "get_bounding_box must return exactly 4 values"

    def test_all_floats(self):
        result = GBIF.get_bounding_box(41.8781, -87.6298, 5.0)
        assert all(isinstance(v, float) for v in result)

    def test_ordering(self):
        min_lat, max_lat, min_lon, max_lon = GBIF.get_bounding_box(41.8781, -87.6298, 5.0)
        assert min_lat < max_lat
        assert min_lon < max_lon

    # -- Symmetry: center of the box should equal the input coordinates --

    def test_center_lat(self):
        lat = 41.8781
        min_lat, max_lat, min_lon, max_lon = GBIF.get_bounding_box(lat, -87.6298, 5.0)
        assert (min_lat + max_lat) / 2 == pytest.approx(lat, abs=1e-9)

    def test_center_lon(self):
        lon = -87.6298
        min_lat, max_lat, min_lon, max_lon = GBIF.get_bounding_box(41.8781, lon, 5.0)
        assert (min_lon + max_lon) / 2 == pytest.approx(lon, abs=1e-9)

    # -- Known numeric values for Chicago at 5 miles --

    def test_chicago_lat_span(self):
        """Latitude span should be 2 * (radius_km / 111.0) degrees."""
        radius_km = GBIF.miles_to_km(5.0)
        expected_span = 2 * radius_km / 111.0
        min_lat, max_lat, _, _ = GBIF.get_bounding_box(41.8781, -87.6298, 5.0)
        assert max_lat - min_lat == pytest.approx(expected_span, rel=1e-6)

    def test_chicago_lon_span(self):
        """Longitude span shrinks at higher latitudes (cos correction)."""
        lat = 41.8781
        radius_km = GBIF.miles_to_km(5.0)
        expected_span = 2 * radius_km / (111.0 * math.cos(math.radians(lat)) + 1e-12)
        _, _, min_lon, max_lon = GBIF.get_bounding_box(lat, -87.6298, 5.0)
        assert max_lon - min_lon == pytest.approx(expected_span, rel=1e-6)

    def test_lon_span_smaller_than_lat_span_at_high_latitude(self):
        """At high latitudes lon degrees span MORE than lat degrees for the same km radius.

        cos(lat) < 1  →  denominator of lon_delta is smaller  →  lon_delta > lat_delta.
        """
        lat = 60.0
        min_lat, max_lat, min_lon, max_lon = GBIF.get_bounding_box(lat, 25.0, 10.0)
        lat_span = max_lat - min_lat
        lon_span = max_lon - min_lon
        assert lon_span > lat_span

    def test_equator_lat_lon_span_equal(self):
        """At the equator cos(0)=1 so lat_delta and lon_delta should be equal."""
        min_lat, max_lat, min_lon, max_lon = GBIF.get_bounding_box(0.0, 0.0, 10.0)
        lat_span = max_lat - min_lat
        lon_span = max_lon - min_lon
        # They won't be exactly equal because of the +1e-12 guard, but very close
        assert lat_span == pytest.approx(lon_span, rel=1e-6)

    # -- Zero radius edge case --

    def test_zero_radius_is_degenerate_point(self):
        lat, lon = 41.8781, -87.6298
        min_lat, max_lat, min_lon, max_lon = GBIF.get_bounding_box(lat, lon, 0.0)
        assert min_lat == pytest.approx(lat, abs=1e-9)
        assert max_lat == pytest.approx(lat, abs=1e-9)
        assert min_lon == pytest.approx(lon, abs=1e-9)
        assert max_lon == pytest.approx(lon, abs=1e-9)

    # -- Southern hemisphere --

    def test_southern_hemisphere(self):
        """Negative latitudes should work; box should still be valid."""
        min_lat, max_lat, min_lon, max_lon = GBIF.get_bounding_box(-33.8688, 151.2093, 5.0)
        assert min_lat < max_lat
        assert min_lon < max_lon
        assert min_lat < -33.8688 < max_lat
        assert min_lon < 151.2093 < max_lon

    # -- Monotonicity: larger radius → larger box --

    def test_larger_radius_gives_larger_box(self):
        lat, lon = 41.8781, -87.6298
        box_5 = GBIF.get_bounding_box(lat, lon, 5.0)
        box_10 = GBIF.get_bounding_box(lat, lon, 10.0)
        lat_span_5, lon_span_5 = bbox_span_degrees(box_5)
        lat_span_10, lon_span_10 = bbox_span_degrees(box_10)
        assert lat_span_10 > lat_span_5
        assert lon_span_10 > lon_span_5

    def test_span_scales_linearly_with_radius(self):
        """Doubling the radius should exactly double the degree spans."""
        lat, lon = 41.8781, -87.6298
        box_5 = GBIF.get_bounding_box(lat, lon, 5.0)
        box_10 = GBIF.get_bounding_box(lat, lon, 10.0)
        lat_span_5, lon_span_5 = bbox_span_degrees(box_5)
        lat_span_10, lon_span_10 = bbox_span_degrees(box_10)
        assert lat_span_10 == pytest.approx(2 * lat_span_5, rel=1e-6)
        assert lon_span_10 == pytest.approx(2 * lon_span_5, rel=1e-6)


# ---------------------------------------------------------------------------
# 3. Search-area contract — shape-agnostic invariants
#    These should pass whether the implementation is bbox, circle, or polygon.
# ---------------------------------------------------------------------------

class TestSearchAreaContract:
    """
    Invariants that ANY search-area implementation must satisfy.

    When you switch from bounding-box to circle/polygon, keep these tests.
    Only update `search_area_contains` at the top of this file.
    """

    def test_center_is_always_inside(self):
        """The origin point must always be inside the search area."""
        lat, lon = 41.8781, -87.6298
        bbox = GBIF.get_bounding_box(lat, lon, 5.0)
        assert search_area_contains(bbox, lat, lon), \
            "The input coordinate must lie within the returned search area"

    def test_far_point_is_outside(self):
        """A point clearly outside the radius should not be contained."""
        lat, lon = 41.8781, -87.6298
        bbox = GBIF.get_bounding_box(lat, lon, 5.0)
        # 10 degrees away is hundreds of miles — must be outside
        far_lat = lat + 10.0
        assert not search_area_contains(bbox, far_lat, lon)

    def test_larger_area_contains_smaller_area_center(self):
        """A 10-mile search area must contain the center of the 5-mile area."""
        lat, lon = 41.8781, -87.6298
        small_box = GBIF.get_bounding_box(lat, lon, 5.0)
        large_box = GBIF.get_bounding_box(lat, lon, 10.0)
        # The center of the small box is just (lat, lon) — must be inside large box
        assert search_area_contains(large_box, lat, lon)

    def test_area_grows_with_radius(self):
        """Increasing radius must strictly increase the search area."""
        lat, lon = 41.8781, -87.6298
        box_5 = GBIF.get_bounding_box(lat, lon, 5.0)
        box_20 = GBIF.get_bounding_box(lat, lon, 20.0)
        lat_span_5, lon_span_5 = bbox_span_degrees(box_5)
        lat_span_20, lon_span_20 = bbox_span_degrees(box_20)
        assert lat_span_20 > lat_span_5
        assert lon_span_20 > lon_span_5

    def test_same_inputs_deterministic(self):
        """Calling with identical inputs must return identical results."""
        args = (41.8781, -87.6298, 7.5)
        assert GBIF.get_bounding_box(*args) == GBIF.get_bounding_box(*args)


# ---------------------------------------------------------------------------
# 4. CSV loading — load_precomputed_taxon_keys
# ---------------------------------------------------------------------------

def _write_temp_csv(rows: list[dict], fieldnames: list[str]) -> str:
    """Write a CSV to a temp file and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    )
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    tmp.close()
    return tmp.name


class TestLoadPrecomputedTaxonKeys:

    def test_normal_load(self):
        path = _write_temp_csv(
            [
                {"Scientific Name": "Myotis sodalis", "Taxon Key": "2435099"},
                {"Scientific Name": "Pandion haliaetus", "Taxon Key": "2480506"},
            ],
            ["Scientific Name", "Taxon Key"],
        )
        name_to_key, key_to_name = GBIF.load_precomputed_taxon_keys(path)

        assert name_to_key["Myotis sodalis"] == 2435099
        assert name_to_key["Pandion haliaetus"] == 2480506
        assert key_to_name[2435099] == "Myotis sodalis"
        assert key_to_name[2480506] == "Pandion haliaetus"

    def test_returns_two_dicts(self):
        path = _write_temp_csv(
            [{"Scientific Name": "Myotis sodalis", "Taxon Key": "2435099"}],
            ["Scientific Name", "Taxon Key"],
        )
        result = GBIF.load_precomputed_taxon_keys(path)
        assert len(result) == 2
        assert isinstance(result[0], dict)
        assert isinstance(result[1], dict)

    def test_empty_csv_returns_empty_dicts(self):
        path = _write_temp_csv([], ["Scientific Name", "Taxon Key"])
        name_to_key, key_to_name = GBIF.load_precomputed_taxon_keys(path)
        assert name_to_key == {}
        assert key_to_name == {}

    def test_skips_row_with_empty_name(self):
        path = _write_temp_csv(
            [
                {"Scientific Name": "", "Taxon Key": "2435099"},
                {"Scientific Name": "Myotis sodalis", "Taxon Key": "2435099"},
            ],
            ["Scientific Name", "Taxon Key"],
        )
        name_to_key, _ = GBIF.load_precomputed_taxon_keys(path)
        assert len(name_to_key) == 1

    def test_skips_row_with_empty_key(self):
        path = _write_temp_csv(
            [
                {"Scientific Name": "Bad Species", "Taxon Key": ""},
                {"Scientific Name": "Myotis sodalis", "Taxon Key": "2435099"},
            ],
            ["Scientific Name", "Taxon Key"],
        )
        name_to_key, _ = GBIF.load_precomputed_taxon_keys(path)
        assert "Bad Species" not in name_to_key
        assert "Myotis sodalis" in name_to_key

    def test_skips_row_with_non_integer_key(self):
        path = _write_temp_csv(
            [
                {"Scientific Name": "Bad Species", "Taxon Key": "not-a-number"},
                {"Scientific Name": "Myotis sodalis", "Taxon Key": "2435099"},
            ],
            ["Scientific Name", "Taxon Key"],
        )
        name_to_key, _ = GBIF.load_precomputed_taxon_keys(path)
        assert "Bad Species" not in name_to_key

    def test_strips_whitespace_from_name_and_key(self):
        path = _write_temp_csv(
            [{"Scientific Name": "  Myotis sodalis  ", "Taxon Key": "  2435099  "}],
            ["Scientific Name", "Taxon Key"],
        )
        name_to_key, key_to_name = GBIF.load_precomputed_taxon_keys(path)
        assert "Myotis sodalis" in name_to_key
        assert 2435099 in key_to_name

    def test_inverse_dicts_are_consistent(self):
        """name_to_key and key_to_name must be exact inverses of each other."""
        path = _write_temp_csv(
            [
                {"Scientific Name": "Myotis sodalis", "Taxon Key": "2435099"},
                {"Scientific Name": "Pandion haliaetus", "Taxon Key": "2480506"},
            ],
            ["Scientific Name", "Taxon Key"],
        )
        name_to_key, key_to_name = GBIF.load_precomputed_taxon_keys(path)
        for name, key in name_to_key.items():
            assert key_to_name[key] == name


# ---------------------------------------------------------------------------
# 5. GBIF occurrence API — gbif_species_counts_in_area (mocked)
# ---------------------------------------------------------------------------

class TestGbifSpeciesCountsInArea:

    def _mock_response(self, counts: list[dict]) -> MagicMock:
        mock = MagicMock()
        mock.json.return_value = {"facets": [{"counts": counts}]}
        return mock

    def test_normal_response_returns_tuples(self, mocker):
        mocker.patch(
            "GBIF.requests.get",
            return_value=self._mock_response([
                {"name": "2435099", "count": "42"},
                {"name": "2480506", "count": "17"},
            ]),
        )
        result = GBIF.gbif_species_counts_in_area(41.8781, -87.6298, 5.0)
        assert result == [(2435099, 42), (2480506, 17)]

    def test_empty_counts_returns_empty_list(self, mocker):
        mocker.patch("GBIF.requests.get", return_value=self._mock_response([]))
        result = GBIF.gbif_species_counts_in_area(41.8781, -87.6298, 5.0)
        assert result == []

    def test_skips_rows_without_name(self, mocker):
        mocker.patch(
            "GBIF.requests.get",
            return_value=self._mock_response([
                {"count": "5"},           # missing "name"
                {"name": "2435099", "count": "10"},
            ]),
        )
        result = GBIF.gbif_species_counts_in_area(41.8781, -87.6298, 5.0)
        assert result == [(2435099, 10)]

    def test_bounding_box_params_sent_to_api(self, mocker):
        """Verify the correct bounding-box coordinates reach the GBIF API."""
        mock_get = mocker.patch(
            "GBIF.requests.get",
            return_value=self._mock_response([]),
        )
        lat, lon, radius = 41.8781, -87.6298, 5.0
        GBIF.gbif_species_counts_in_area(lat, lon, radius)

        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"] if call_kwargs[1] else call_kwargs[0][1]

        min_lat, max_lat, min_lon, max_lon = GBIF.get_bounding_box(lat, lon, radius)
        assert params["decimalLatitude"] == f"{min_lat},{max_lat}"
        assert params["decimalLongitude"] == f"{min_lon},{max_lon}"

    def test_api_called_exactly_once(self, mocker):
        mock_get = mocker.patch(
            "GBIF.requests.get",
            return_value=self._mock_response([]),
        )
        GBIF.gbif_species_counts_in_area(41.8781, -87.6298, 5.0)
        mock_get.assert_called_once()

    def test_year_filter_in_params(self, mocker):
        mock_get = mocker.patch(
            "GBIF.requests.get",
            return_value=self._mock_response([]),
        )
        GBIF.gbif_species_counts_in_area(41.8781, -87.6298, 5.0)
        params = mock_get.call_args[1]["params"] if mock_get.call_args[1] else mock_get.call_args[0][1]
        assert "year" in params

    # -- Network / HTTP error handling --

    def test_timeout_raises_runtime_error(self, mocker):
        import requests as req
        mocker.patch("GBIF.requests.get", side_effect=req.exceptions.Timeout())
        with pytest.raises(RuntimeError, match="timed out"):
            GBIF.gbif_species_counts_in_area(41.8781, -87.6298, 5.0)

    def test_connection_error_raises_runtime_error(self, mocker):
        import requests as req
        mocker.patch("GBIF.requests.get", side_effect=req.exceptions.ConnectionError())
        with pytest.raises(RuntimeError, match="connect"):
            GBIF.gbif_species_counts_in_area(41.8781, -87.6298, 5.0)

    def test_http_error_raises_runtime_error(self, mocker):
        import requests as req
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mocker.patch(
            "GBIF.requests.get",
            side_effect=req.exceptions.HTTPError(response=mock_resp),
        )
        with pytest.raises(RuntimeError, match="503"):
            GBIF.gbif_species_counts_in_area(41.8781, -87.6298, 5.0)

    def test_generic_request_error_raises_runtime_error(self, mocker):
        import requests as req
        mocker.patch("GBIF.requests.get", side_effect=req.exceptions.RequestException("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            GBIF.gbif_species_counts_in_area(41.8781, -87.6298, 5.0)

    def test_empty_facets_returns_empty_list(self, mocker):
        """GBIF sometimes returns no facets when area has no observations."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"facets": []}
        mock_resp.raise_for_status = MagicMock()
        mocker.patch("GBIF.requests.get", return_value=mock_resp)
        result = GBIF.gbif_species_counts_in_area(41.8781, -87.6298, 5.0)
        assert result == []

    def test_missing_facets_key_returns_empty_list(self, mocker):
        """Response missing 'facets' key entirely should not crash."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        mocker.patch("GBIF.requests.get", return_value=mock_resp)
        result = GBIF.gbif_species_counts_in_area(41.8781, -87.6298, 5.0)
        assert result == []


# ---------------------------------------------------------------------------
# 6. load_precomputed_taxon_keys() — file error handling
# ---------------------------------------------------------------------------

class TestLoadPrecomputedTaxonKeysErrors:

    def test_missing_file_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="not found"):
            GBIF.load_precomputed_taxon_keys("/nonexistent/path/IllinoisTaxonLookup.csv")

    def test_missing_file_error_message_includes_path(self):
        bad_path = "/nonexistent/path/IllinoisTaxonLookup.csv"
        with pytest.raises(RuntimeError, match=bad_path):
            GBIF.load_precomputed_taxon_keys(bad_path)

    def test_malformed_key_row_is_skipped_and_valid_row_loaded(self):
        """A row with a non-integer key must be skipped; other rows must load."""
        path = _write_temp_csv(
            [
                {"Scientific Name": "Bad Species", "Taxon Key": "not-a-number"},
                {"Scientific Name": "Myotis sodalis", "Taxon Key": "2435099"},
            ],
            ["Scientific Name", "Taxon Key"],
        )
        name_to_key, _ = GBIF.load_precomputed_taxon_keys(path)
        assert "Bad Species" not in name_to_key
        assert "Myotis sodalis" in name_to_key
