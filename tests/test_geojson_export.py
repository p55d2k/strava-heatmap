"""
Tests for src/geojson_export.py - rasterized grids exported as GeoJSON.

The export is built from the raw (un-blurred) grids to decide which cells hold
data, and from the normalized grids for the values, so the tests build both by
hand and check the resulting FeatureCollection structurally.
"""

import json

import numpy as np
import pytest
from pyproj import Transformer

from src.geojson_export import build_geojson, geojson_feature_count

# Small grid: 3x3 cells of 10 m, anchored at the equator/prime meridian so the
# expected Web Mercator coordinates are easy to reason about.
GRID_W = 3
GRID_H = 3
MPP = 10.0
X_MIN_WM = 0.0
Y_MAX_WM = 1000.0


@pytest.fixture
def from_wm():
    """The same WGS84 transformer the map build uses for its bounds."""
    return Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)


@pytest.fixture
def to_wm():
    """Inverse transformer, used to verify the exported polygon coordinates."""
    return Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


def _grids(**overrides):
    """Build a ``create_grids``-shaped 13-tuple with zeros except for overrides.

    Only the arrays the export reads are meaningful; the sum grids (speed_sum,
    hr_sum, grad_sum, elev_sum) stay zero.
    """

    def zeros():
        return np.zeros((GRID_H, GRID_W), dtype=np.float32)

    grids = {
        "count": zeros(),
        "speed_n": zeros(),
        "hr_n": zeros(),
        "grad_n": zeros(),
        "elev_n": zeros(),
        "count_raw": zeros(),
        "unique": zeros(),
    }
    grids.update(overrides)
    return (
        GRID_W,
        GRID_H,
        grids["count"],
        zeros(),
        grids["speed_n"],
        zeros(),
        grids["hr_n"],
        zeros(),
        grids["grad_n"],
        zeros(),
        grids["elev_n"],
        grids["count_raw"],
        grids["unique"],
    )


def _normalized(**overrides):
    """Build a ``compute_normalized_grids``-shaped dict of zeros."""

    def zeros():
        return np.zeros((GRID_H, GRID_W), dtype=np.float32)

    normalized = {
        "count_log_norms": {
            "decay": zeros(),
            "raw-count": zeros(),
            "binary-per-activity": zeros(),
        },
        "max_passes_by_strategy": {
            "decay": 10,
            "raw-count": 20,
            "binary-per-activity": 4,
        },
        "unique_pct_norm": zeros(),
        "speed_norm": zeros(),
        "hr_norm": zeros(),
        "grad_norm": zeros(),
        "elev_norm": zeros(),
        "s_lo": 3.0,
        "s_hi": 6.0,
        "hr_lo": 120.0,
        "hr_hi": 180.0,
        "g_lo": 0.02,
        "g_hi": 0.10,
    }
    normalized.update(overrides)
    return normalized


def _build(normalized, grids, from_wm):
    return json.loads(build_geojson(normalized, grids, X_MIN_WM, Y_MAX_WM, MPP, from_wm))


def test_empty_grids_produce_an_empty_feature_collection(from_wm):
    """A grid with no samples exports a valid but featureless collection."""
    raw = build_geojson(_normalized(), _grids(), X_MIN_WM, Y_MAX_WM, MPP, from_wm)
    collection = json.loads(raw)

    assert collection["type"] == "FeatureCollection"
    assert collection["features"] == []
    assert collection["cell_size_m"] == MPP
    assert geojson_feature_count(raw) == 0


def test_only_populated_cells_become_features(from_wm):
    """One polygon per cell that recorded a sample, and none for empty cells."""
    grids = _grids()
    grids[2][0, 0] = 3.0  # decay count
    grids[12][2, 2] = 1.0  # unique-per-activity

    collection = _build(_normalized(), grids, from_wm)

    assert len(collection["features"]) == 2
    # Features are emitted in row-major order.
    xs = [feature["geometry"]["coordinates"][0][0][0] for feature in collection["features"]]
    assert xs == sorted(xs)


def test_polygon_is_a_closed_square_matching_the_grid_cell(from_wm, to_wm):
    """Each feature is a closed ring covering exactly its Web Mercator cell."""
    grids = _grids()
    grids[2][1, 1] = 1.0  # centre cell

    feature = _build(_normalized(), grids, from_wm)["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Polygon"

    ring = feature["geometry"]["coordinates"][0]
    # Closed ring: four corners plus a repeat of the first.
    assert len(ring) == 5
    assert ring[0] == ring[-1]

    # Every vertex maps back to the cell's corners in Web Mercator (within the
    # coordinate rounding, ~0.1 m).
    lons = [point[0] for point in ring]
    lats = [point[1] for point in ring]
    x_back, y_back = to_wm.transform(lons, lats)
    x_edges = sorted(set(np.round(x_back, 2).tolist()))
    y_edges = sorted(set(np.round(y_back, 2).tolist()))
    assert x_edges == pytest.approx([5.0, 15.0], abs=0.05)  # x edges of col 1
    assert y_edges == pytest.approx([985.0, 995.0], abs=0.05)  # y edges of row 1


def test_coordinates_are_wgs84_lon_lat(from_wm, to_wm):
    """Coordinates must be lon/lat degrees, not metres (RFC 7946)."""
    grids = _grids()
    grids[2][0, 0] = 1.0

    ring = _build(_normalized(), grids, from_wm)["features"][0]["geometry"]["coordinates"][0]
    lon, lat = ring[0]
    assert -180.0 <= lon <= 180.0
    assert -90.0 <= lat <= 90.0
    # At (0, ~1000 m) the latitude is a small positive angle while the longitude
    # at x = -5 m is a small negative one.
    assert lon < 0 < lat
    assert to_wm.transform(lon, lat)[0] == pytest.approx(-5.0, abs=0.5)


def test_density_properties_recover_blurred_pass_counts(from_wm):
    """The log-normalized density is inverted back to real pass counts."""
    normalized = _normalized()
    # blurred decay count of 5 with a max of 10 -> log-normalized value
    normalized["count_log_norms"]["decay"][0, 0] = np.log1p(5.0) / np.log1p(10.0)
    normalized["count_log_norms"]["raw-count"][0, 0] = np.log1p(8.0) / np.log1p(20.0)
    normalized["count_log_norms"]["binary-per-activity"][0, 0] = np.log1p(3.0) / np.log1p(4.0)
    grids = _grids(count=np.array([[1.0, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=np.float32))

    props = _build(normalized, grids, from_wm)["features"][0]["properties"]

    assert props["passes_time_spent"] == pytest.approx(5.0, abs=0.01)
    assert props["passes_raw"] == pytest.approx(8.0, abs=0.01)
    assert props["visits_unique"] == pytest.approx(3.0, abs=0.01)


def test_metric_properties_use_real_units_and_are_omitted_without_samples(from_wm):
    """Speed/HR/gradient are denormalized using the legend bounds, and a metric
    with no samples in a cell is left out rather than written as a false zero."""
    normalized = _normalized()
    # 50% of the way up each normalized scale.
    normalized["speed_norm"][0, 0] = 0.5
    normalized["hr_norm"][0, 0] = 0.5
    normalized["grad_norm"][0, 0] = 0.5
    normalized["elev_norm"][0, 0] = -0.25
    # Only speed and elevation actually recorded samples here; HR/gradient sit
    # in the blur halo only.
    grids = _grids(
        count=np.array([[1.0, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=np.float32),
        speed_n=np.array([[2.0, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=np.float32),
        elev_n=np.array([[2.0, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=np.float32),
    )

    props = _build(normalized, grids, from_wm)["features"][0]["properties"]

    assert props["pace_mps"] == pytest.approx(4.5, abs=0.01)  # 3.0 + 0.5 * (6.0 - 3.0)
    assert props["elev_change_norm"] == pytest.approx(-0.25, abs=0.0001)
    assert "heart_rate_bpm" not in props
    assert "gradient" not in props


def test_coverage_is_a_percentage(from_wm):
    """Coverage is exported as a percentage of all activities, not a fraction."""
    normalized = _normalized()
    normalized["unique_pct_norm"][1, 1] = 0.42
    grids = _grids(unique=np.array([[0, 0, 0], [0, 1.0, 0], [0, 0, 0]], dtype=np.float32))

    props = _build(normalized, grids, from_wm)["features"][0]["properties"]

    assert props["coverage_pct"] == pytest.approx(42.0, abs=0.001)


def test_exported_json_is_minified(from_wm):
    """The embedded payload stays compact: no pretty-printing whitespace."""
    grids = _grids()
    grids[2][0, 0] = 1.0

    raw = build_geojson(_normalized(), grids, X_MIN_WM, Y_MAX_WM, MPP, from_wm)

    assert ", " not in raw
    assert '": ' not in raw
    assert geojson_feature_count(raw) == 1
