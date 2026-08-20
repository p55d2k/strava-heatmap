"""
Pipeline Stage 1: Data Loading & Filtering
Loads activities CSV, applies filters, and loads GPS tracks.
"""

import logging
import pickle
from datetime import date
from pathlib import Path

import pandas as pd
from tqdm import tqdm

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
    # Check if activities CSV exists
    if not config.activities_csv.exists():
        raise FileNotFoundError(
            f"Activities CSV not found: {config.activities_csv}\n"
            f"  → Make sure your Strava export folder contains activities.csv\n"
            f"  → Export from Strava: Settings > My Account > Download or Request Your Data"
        )

    df = pd.read_csv(config.activities_csv)
    df["Activity Date"] = pd.to_datetime(df["Activity Date"], format="mixed", dayfirst=True)

    # Normalize Activity Type column so verbose CSV labels (e.g. "Running", "Cycling")
    # match the canonical types in config.activity_types
    df["Activity Type"] = df["Activity Type"].apply(normalize_activity_type)

    runs = df[df["Activity Type"].isin(config.activity_types)].copy()
    log.info(f"Total matching activities in export: {len(runs)}")

    if runs.empty:
        available_types = sorted(df["Activity Type"].dropna().unique().tolist())
        raise ValueError(
            f"No activities found matching configured types: {sorted(config.activity_types)}\n"
            f"  → Available types in your export: {available_types}\n"
            f"  → Check ACTIVITY_TYPES in config.json (use names like 'Run', 'Ride', 'Hike', etc.)"
        )

    date_from = pd.Timestamp(config.date_from) if config.date_from else pd.Timestamp.min
    date_to = pd.Timestamp(config.date_to) if config.date_to else pd.Timestamp(date.today())
    runs = runs[runs["Activity Date"].between(date_from, date_to)].copy()
    log.info(f"After date filter ({date_from.date()} – {date_to.date()}): {len(runs)}")

    if runs.empty:
        min_date = df["Activity Date"].min().date()
        max_date = df["Activity Date"].max().date()
        raise ValueError(
            f"No activities in date range {date_from.date()} – {date_to.date()}\n"
            f"  → Your export covers: {min_date} to {max_date}\n"
            f"  → Adjust DATE_FROM / DATE_TO in config.json"
        )

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

    if runs.empty:
        total_with_gps = len([r for r in rows if r["start_lat"] is not None])
        raise ValueError(
            f"No activities with valid GPS data after filtering\n"
            f"  → {len(rows)} activities had GPS files, but {len(rows) - total_with_gps} had no GPS data\n"
            f"  → {total_with_gps - len(runs)} activities had GPS spread < {config.gps_spread_min_m}m (likely indoor)\n"
            f"  → Try lowering GPS_SPREAD_MIN_M in config.json (current: {config.gps_spread_min_m}m)"
        )

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
    original_count = len(runs)
    runs = runs[runs["dist_from_home_km"] <= radius_km].copy()
    log.info(f"After home-radius filter (≤{radius_km} km): {len(runs)} activities")

    if runs.empty:
        # Get distances before filtering to provide better info
        raise ValueError(
            f"No activities within {radius_km} km of home location ({home_lat:.4f}, {home_lon:.4f})\n"
            f"  → All {original_count} activities were outside this radius\n"
            f"  → Try increasing RADIUS_KM in config.json (current: {radius_km} km)\n"
            f"  → Or check your HOME_LAT/HOME_LON coordinates"
        )

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
    for _, row in tqdm(runs.iterrows(), total=len(runs), desc="Loading tracks", unit="activity"):
        fn = str(row["Filename"])
        fp = config.activities_dir / fn
        lbl = f"{row['Activity Date'].date()} {row['Activity Name']}"

        pts = track_cache.get(fn)
        if pts is None:
            pts = parse_track_file(fp)
            track_cache[fn] = pts

        if pts:
            tracks.append((lbl, pts))

    # Save updated track cache
    cache["tracks"] = track_cache
    _save_cache(config, cache)

    if not tracks:
        raise ValueError(
            f"No valid GPS tracks could be loaded from {len(runs)} activities\n"
            f"  → Check that .fit.gz or .gpx files exist in {config.activities_dir}\n"
            f"  → Files may be corrupted or in an unsupported format\n"
            f"  → Try deleting the cache/ folder and re-running"
        )

    return tracks
