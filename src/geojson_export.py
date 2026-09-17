"""
Pipeline Stage 3b: GeoJSON Export
Turns the rasterized grids into a single GeoJSON FeatureCollection.

Each non-empty grid cell becomes one polygon feature carrying the density pass
counts, coverage and the metric layers as properties, so the same data can be
opened in GIS tools such as QGIS or Mapbox. Coordinates are WGS84 (EPSG:4326),
converted from the Web Mercator grid with the same transformer the map uses;
that is the only CRS RFC 7946 allows.

The GeoJSON is embedded in the generated HTML (see
``src/map_builder/control.py``) and downloaded by the control panel's
"Export GeoJSON" button, so no companion file is needed.
"""

import json
import logging

import numpy as np
from pyproj import Transformer

log = logging.getLogger(__name__)

# Positions inside the ``grids`` tuple returned by ``rasterizer.create_grids``.
# Only the raw (un-blurred) grids are read here, to decide which cells actually
# hold data; the values themselves come from the normalized grids.
_GRID_W = 0
_GRID_H = 1
_COUNT_DECAY = 2
_SPEED_N = 4
_HR_N = 6
_GRAD_N = 8
_ELEV_N = 10
_COUNT_RAW = 11
_UNIQUE = 12

# Coordinate precision: 6 decimal degrees is ~0.11 m, well below a grid cell.
_COORD_DECIMALS = 6

# Property names for the three density strategies, in rasteriser order.
_DENSITY_PROPERTIES = (
    ("decay", "passes_time_spent"),
    ("raw-count", "passes_raw"),
    ("binary-per-activity", "visits_unique"),
)

# (property, normalized grid key, raw count grid index, lo, hi, decimals) for the
# metric layers whose real-value scale is recoverable from the legend bounds.
_METRIC_PROPERTIES = (
    ("pace_mps", "speed_norm", _SPEED_N, "s_lo", "s_hi", 3),
    ("heart_rate_bpm", "hr_norm", _HR_N, "hr_lo", "hr_hi", 1),
    ("gradient", "grad_norm", _GRAD_N, "g_lo", "g_hi", 5),
)

# The gradient-change (elevation) layer is only stored normalized to [-1, 1]
# (its absolute metre scale is not kept), so it is exported as-is.
_ELEV_PROPERTY = "elev_change_norm"

# Metric value arrays are rounded to this many decimals before being written.
_ELEV_DECIMALS = 4


def _number(value: float) -> str:
    """Format a float as a compact JSON number (shortest round-trip repr)."""
    return repr(float(value))


def _cell_mask(grids: tuple) -> np.ndarray:
    """Return the boolean grid of cells that hold any data at all.

    A cell counts as populated when any raw (un-blurred) strategy or metric grid
    recorded a sample there. The blurred/normalized grids would smear this into
    a halo of near-zero cells, which is exactly what we do not want to export.
    """
    return (
        (grids[_COUNT_DECAY] > 0)
        | (grids[_COUNT_RAW] > 0)
        | (grids[_UNIQUE] > 0)
        | (grids[_SPEED_N] > 0)
        | (grids[_HR_N] > 0)
        | (grids[_GRAD_N] > 0)
        | (grids[_ELEV_N] > 0)
    )


def _density_values(normalized: dict, rows: np.ndarray, cols: np.ndarray) -> list[np.ndarray]:
    """Recover the per-cell pass counts behind each strategy's log-normalized grid.

    ``count_log_norm`` is ``log1p(blurred_count) / log1p(max)``, so inverting it
    gives the blurred pass count in real units (rather than the 0-1 the map
    paints), which is what a GIS user expects to find in the properties.
    """
    log_norms = normalized["count_log_norms"]
    maxes = normalized["max_passes_by_strategy"]
    values = []
    for mode, _ in _DENSITY_PROPERTIES:
        norm = np.asarray(log_norms[mode], dtype=np.float64)[rows, cols]
        top = float(maxes[mode])
        counts = np.expm1(np.log1p(top) * norm) if top > 0 else np.zeros_like(norm)
        values.append(np.round(counts, 2))
    return values


def _metric_values(
    normalized: dict,
    grids: tuple,
    rows: np.ndarray,
    cols: np.ndarray,
) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """Return ``(property, present, values)`` per metric, in real units where recoverable.

    ``present`` comes from the raw sample-count grid, so a cell that merely sits
    in a metric layer's blur halo is left out of that property entirely instead
    of exporting a misleading zero.
    """
    results = []
    for name, norm_key, grid_index, lo_key, hi_key, decimals in _METRIC_PROPERTIES:
        present = np.asarray(grids[grid_index][rows, cols]) > 0
        norm = np.asarray(normalized[norm_key], dtype=np.float64)[rows, cols]
        lo = float(normalized[lo_key])
        values = np.round(norm * (float(normalized[hi_key]) - lo) + lo, decimals)
        results.append((name, present, values))

    elev_present = np.asarray(grids[_ELEV_N][rows, cols]) > 0
    elev_values = np.round(
        np.asarray(normalized["elev_norm"], dtype=np.float64)[rows, cols], _ELEV_DECIMALS
    )
    results.append((_ELEV_PROPERTY, elev_present, elev_values))
    return results


def build_geojson(
    normalized: dict,
    grids: tuple,
    x_min_wm: float,
    y_max_wm: float,
    meters_per_pixel: float,
    from_wm: Transformer,
) -> str:
    """Build a minified GeoJSON FeatureCollection of the populated grid cells.

    Args:
        normalized: Output of ``rasterizer.compute_normalized_grids``.
        grids: The raw grids tuple from ``rasterizer.create_grids`` (its
            un-blurred count grids decide which cells are exported).
        x_min_wm: Western edge of the grid in Web Mercator metres.
        y_max_wm: Northern edge of the grid in Web Mercator metres.
        meters_per_pixel: Grid cell size in metres.
        from_wm: Transformer from EPSG:3857 to EPSG:4326 (lon/lat), the same
            one the map bounds are computed with.

    Returns:
        A minified GeoJSON string: one polygon per populated cell, with the
        density pass counts and coverage on every feature and each metric
        property only where that metric has samples.
    """
    grid_w = int(grids[_GRID_W])
    grid_h = int(grids[_GRID_H])
    mask = _cell_mask(grids)
    rows, cols = np.nonzero(mask)
    n = int(rows.size)

    features: list[str] = []
    if n:
        # Cell (row, col) is the square centred on the point rounded into it, so
        # its edges sit half a cell either side of one grid step.
        x_edges = x_min_wm + (np.arange(grid_w + 1) - 0.5) * meters_per_pixel
        y_edges = y_max_wm - (np.arange(grid_h + 1) - 0.5) * meters_per_pixel
        lon_edges = np.round(from_wm.transform(x_edges, np.zeros_like(x_edges))[0], _COORD_DECIMALS)
        lat_edges = np.round(from_wm.transform(np.zeros_like(y_edges), y_edges)[1], _COORD_DECIMALS)
        # Pre-format the shared edges once: every cell reuses its neighbours'
        # coordinates, so this keeps the string building cheap.
        lon_s = [_number(v) for v in lon_edges.tolist()]
        lat_s = [_number(v) for v in lat_edges.tolist()]

        density = _density_values(normalized, rows, cols)
        coverage = np.round(
            np.asarray(normalized["unique_pct_norm"], dtype=np.float64)[rows, cols] * 100.0, 3
        )
        metrics = _metric_values(normalized, grids, rows, cols)

        for i in range(n):
            col = int(cols[i])
            row = int(rows[i])
            left = lon_s[col]
            right = lon_s[col + 1]
            top = lat_s[row]
            bottom = lat_s[row + 1]
            # Counter-clockwise exterior ring, as RFC 7946 recommends.
            ring = (
                f"[[{left},{top}],[{left},{bottom}],"
                f"[{right},{bottom}],[{right},{top}],[{left},{top}]]"
            )

            props = [
                f'"{name}":{_number(density[j][i])}'
                for j, (_, name) in enumerate(_DENSITY_PROPERTIES)
            ]
            props.append(f'"coverage_pct":{_number(coverage[i])}')
            for name, present, values in metrics:
                if present[i]:
                    props.append(f'"{name}":{_number(values[i])}')

            features.append(
                '{"type":"Feature","geometry":{"type":"Polygon","coordinates":['
                + ring
                + ']},"properties":{'
                + ",".join(props)
                + "}}"
            )

    log.info("GeoJSON export: %d populated grid cells", n)
    return (
        '{"type":"FeatureCollection","name":"strava-heatmap-grids",'
        f'"cell_size_m":{_number(meters_per_pixel)},"features":[{",".join(features)}]}}'
    )


def geojson_feature_count(geojson: str) -> int:
    """Return the number of features in an exported GeoJSON string.

    Small helper for progress reporting and tests; parses the produced JSON
    rather than relying on its formatting.
    """
    if not geojson:
        return 0
    return len(json.loads(geojson).get("features", []))
