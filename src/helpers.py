# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

import logging
import math
import gzip
from pathlib import Path

import fitparse
from fitparse.utils import FitParseError
import pandas as pd

log = logging.getLogger(__name__)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate Great Circle distance in kilometers between two points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    return R * 2.0 * math.asin(math.sqrt(a))


def parse_fit_file(filepath: Path) -> list:
    """
    Parse .fit.gz file once and return full track points.
    Returns list of [lat, lon, speed, hr, alt] or empty list on failure.
    Some Strava FIT files have corrupted records at the end (truncated/incomplete).
    We catch the parse error and return whatever valid points we extracted before the corruption.
    """
    points = []
    try:
        with gzip.open(filepath, "rb") as f:
            for msg in fitparse.FitFile(f).get_messages("record"):
                d = {x.name: x.value for x in msg}
                lat, lon = d.get("position_lat"), d.get("position_long")
                if lat is None or lon is None:
                    continue

                lat_deg = lat * (180.0 / 2**31)
                lon_deg = lon * (180.0 / 2**31)
                speed = (
                    d.get("enhanced_speed")
                    if d.get("enhanced_speed") is not None
                    else d.get("speed")
                )
                hr = d.get("heart_rate")
                alt = (
                    d.get("enhanced_altitude")
                    if d.get("enhanced_altitude") is not None
                    else d.get("altitude")
                )

                points.append([lat_deg, lon_deg, speed, hr, alt])
    except FitParseError as e:
        if points:
            # Partial success - log at debug level since we got useful data
            log.debug(
                f"Partial parse of {filepath.name}: got {len(points)} points before corruption: {e}"
            )
        else:
            # Complete failure - no valid points extracted
            log.warning(f"Failed to parse {filepath.name}: {e}")
    except Exception as e:
        # Other unexpected errors
        log.warning(f"Failed to parse {filepath.name}: {e}")
    return points


def get_gps_start(filepath: Path) -> tuple:
    """
    Get (start_lat, start_lon, spread_m) from a .fit.gz file.
    Parses the full track once and derives start/spread from it.
    """
    pts = parse_fit_file(filepath)
    if not pts:
        log.debug(f"No GPS records in {filepath.name}")
        return None, None, None

    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]

    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    mid_lat = (min_lat + max_lat) / 2.0

    spread_m = max(
        (max_lat - min_lat) * 111_000.0,
        (max_lon - min_lon) * 111_000.0 * math.cos(math.radians(mid_lat)),
    )
    return lats[0], lons[0], spread_m


def detect_home(df_gps: pd.DataFrame) -> tuple:
    """Bins starting points to a ~1 km grid to discover home location."""
    if df_gps.empty:
        raise ValueError("Cannot detect home: no GPS data available")

    cell_lats, cell_lons = {}, {}
    for lat, lon in zip(df_gps["start_lat"], df_gps["start_lon"]):
        cell = (round(lat, 2), round(lon, 2))
        cell_lats.setdefault(cell, []).append(lat)
        cell_lons.setdefault(cell, []).append(lon)

    best_cell = max(cell_lats, key=lambda c: len(cell_lats[c]))
    home_lat = sum(cell_lats[best_cell]) / len(cell_lats[best_cell])
    home_lon = sum(cell_lons[best_cell]) / len(cell_lons[best_cell])
    n_starts = len(cell_lats[best_cell])
    log.debug(f"Home detection: best cell has {n_starts} starts")
    return home_lat, home_lon, n_starts


def load_fit_track_full(filepath: Path) -> list:
    """Parse .fit.gz and extract array of [lat, lon, speed, hr, alt]."""
    return parse_fit_file(filepath)
