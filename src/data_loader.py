"""
Pipeline Stage 1: Data Loading & Filtering
Loads activities CSV, applies filters, and loads GPS tracks.
"""

import logging
import pickle
from datetime import date
from pathlib import Path

import pandas as pd

from src.config import normalize_activity_type
from src.helpers import detect_home, get_gps_start, haversine_km, parse_track_file

log = logging.getLogger(__name__)


def _load_cache(config) -> dict:
    """Load unified cache (gps + tracks) from pickle file."""
    if config.cache_file.exists():
        try:
            with open(config.cache_file, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            log.warning(f"Failed to load cache: {e}")
    return {"gps": {}, "tracks": {}}


def _save_cache(config, cache: dict) -> None:
    """Save unified cache to pickle file."""
    try:
        with open(config.cache_file, "wb") as f:
            pickle.dump(cache, f)
    except Exception as e:
        log.warning(f"Failed to save cache: {e}")


def load_and_filter_activities(config) -> pd.DataFrame:
    """Load activities CSV, apply date/type filters, and parse GPS start points."""
    df = pd.read_csv(config.activities_csv)
    df["Activity Date"] = pd.to_datetime(df["Activity Date"], format="mixed", dayfirst=True)

    # Normalize Activity Type column so verbose CSV labels (e.g. "Running", "Cycling")
    # match the canonical types in config.activity_types
    df["Activity Type"] = df["Activity Type"].apply(normalize_activity_type)

    runs = df[df["Activity Type"].isin(config.activity_types)].copy()
    log.info(f"Total matching activities in export: {len(runs)}")

    date_from = pd.Timestamp(config.date_from) if config.date_from else pd.Timestamp.min
    date_to = pd.Timestamp(config.date_to) if config.date_to else pd.Timestamp(date.today())
    runs = runs[runs["Activity Date"].between(date_from, date_to)].copy()
    log.info(f"After date filter ({date_from.date()} – {date_to.date()}): {len(runs)}")

    # Load unified cache
    cache = _load_cache(config)
    gps_cache = cache.get("gps", {})

    rows = []
    for _, row in runs.iterrows():
        fn = str(row["Filename"])
        if fn in gps_cache:
            lat, lon, spread = gps_cache[fn]
        else:
            lat, lon, spread = get_gps_start(Path(config.activities_dir) / fn)
            gps_cache[fn] = [lat, lon, spread]  # cache even if no GPS (None values)
        rows.append({**row, "start_lat": lat, "start_lon": lon, "gps_spread_m": spread})

    # Save updated GPS cache
    cache["gps"] = gps_cache
    _save_cache(config, cache)

    runs = pd.DataFrame(rows)
    runs = runs[
        runs["start_lat"].notna() & (runs["gps_spread_m"] >= config.gps_spread_min_m)
    ].copy()
    log.info(f"After removing no-GPS / indoor: {len(runs)}")

    return runs


def determine_home_location(config, runs: pd.DataFrame) -> tuple[float, float]:
    """Auto-detect or use manual home location."""
    if config.home_lat is None or config.home_lon is None:
        home_lat, home_lon, n_home_starts = detect_home(runs)
        log.info(
            f"Auto-detected home: {home_lat:.4f}, {home_lon:.4f}  "
            f"({n_home_starts} of {len(runs)} activities started there)"
        )
    else:
        home_lat, home_lon = config.home_lat, config.home_lon
        log.info(f"Using manual home: {home_lat}, {home_lon}")
    return home_lat, home_lon


def filter_by_home_radius(
    runs: pd.DataFrame, home_lat: float, home_lon: float, radius_km: float
) -> pd.DataFrame:
    """Filter activities by distance from home."""
    runs["dist_from_home_km"] = runs.apply(
        lambda r: haversine_km(home_lat, home_lon, r["start_lat"], r["start_lon"]), axis=1
    )
    runs = runs[runs["dist_from_home_km"] <= radius_km].copy()
    log.info(f"After home-radius filter (≤{radius_km} km): {len(runs)} activities")
    return runs


def load_tracks(config, runs: pd.DataFrame) -> list[tuple[str, list]]:
    """Load full GPS tracks from .fit.gz / .gpx files with caching."""
    cache = _load_cache(config)
    track_cache = cache.get("tracks", {})

    # Purge cache missing altitude schema
    stale = [k for k, v in track_cache.items() if v and len(v[0]) < 5]
    if stale:
        log.info(f"Clearing {len(stale)} stale cache entries...")
        for k in stale:
            del track_cache[k]

    tracks = []
    for _, row in runs.iterrows():
        fn = str(row["Filename"])
        fp = config.activities_dir / fn
        lbl = f"{row['Activity Date'].date()} {row['Activity Name']}"

        pts = track_cache.get(fn)
        if pts is None:
            log.info(f"Parsing {fn}...")
            pts = parse_track_file(fp)
            track_cache[fn] = pts

        if pts:
            tracks.append((lbl, pts))

    # Save updated track cache
    cache["tracks"] = track_cache
    _save_cache(config, cache)

    if not tracks:
        log.warning("No valid tracks loaded. Check your configuration and date ranges.")

    return tracks
