#!/usr/bin/env python3
"""
Memory profiler for the parse and rasterize stages of the pipeline.

Builds a synthetic Strava-shaped export (N activities, P GPS points each),
then reports peak memory while ``data_loader.load_tracks`` parses it and while
``rasterizer.rasterize_tracks`` paints it. Use it to check that large exports
stay within a sensible footprint and that the compact float32 point arrays are
actually smaller than the old list-of-lists.

Run:
    uv run python scripts/profile_memory.py
    uv run python scripts/profile_memory.py --activities 500 --points 5000

Two numbers are printed per stage:

* ``tracemalloc`` peak - Python-object allocations, which is what the compact
  point representation targets.
* process peak RSS (``ru_maxrss``) - the whole process, including NumPy's own
  buffers, which ``tracemalloc`` does not track.
"""

import argparse
import resource
import sys
import tempfile
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.data_loader import load_tracks  # noqa: E402
from src.rasterizer import (  # noqa: E402
    compute_grid_bounds,
    create_grids,
    rasterize_tracks,
    setup_transformers,
)

HOME_LAT, HOME_LON = 45.0, -122.0
_GPX_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<gpx version="1.1" creator="profile"'
    ' xmlns="http://www.topografix.com/GPX/1/1"'
    ' xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v2">'
)


def peak_rss_mb() -> float:
    """Process peak RSS in MB (macOS reports bytes, Linux kilobytes)."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024


def write_synthetic_export(
    root: Path, n_activities: int, points_per: int
) -> tuple[Path, pd.DataFrame]:
    """Write ``n_activities`` GPX tracks and return their directory and a runs frame."""
    activities_dir = root / "activities"
    activities_dir.mkdir(parents=True, exist_ok=True)

    filenames: list[str] = []
    for i in range(n_activities):
        name = f"activity_{i}.gpx"
        points = []
        for j in range(points_per):
            lat = HOME_LAT + j * 0.0002
            lon = HOME_LON + j * 0.0002
            points.append(
                f'<trkpt lat="{lat}" lon="{lon}"><ele>{10 + j % 5}.0</ele>'
                "<extensions><gpxtpx:TrackPointExtension>"
                f"<gpxtpx:hr>{120 + j % 40}</gpxtpx:hr>"
                f"<gpxtpx:speed>{2.0 + j % 3}.0</gpxtpx:speed>"
                "</gpxtpx:TrackPointExtension></extensions></trkpt>"
            )
        (activities_dir / name).write_text(
            f"{_GPX_HEADER}<trk><trkseg>{''.join(points)}</trkseg></trk></gpx>",
            encoding="utf-8",
        )
        filenames.append(name)

    runs = pd.DataFrame(
        {
            "Filename": filenames,
            "Activity Date": [pd.Timestamp("2024-01-01")] * n_activities,
            "Activity Name": [f"Activity {i}" for i in range(n_activities)],
        }
    )
    return activities_dir, runs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--activities", type=int, default=200, help="number of activities")
    parser.add_argument("-p", "--points", type=int, default=2000, help="GPS points per activity")
    parser.add_argument("-m", "--meters-per-pixel", type=float, default=5.0)
    args = parser.parse_args()

    total_points = args.activities * args.points
    print(
        f"Synthetic export: {args.activities} activities x {args.points} points "
        f"= {total_points:,} points\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        activities_dir, runs = write_synthetic_export(Path(tmp), args.activities, args.points)
        config = SimpleNamespace(activities_dir=activities_dir, cache_file=Path(tmp) / "cache.pkl")

        # --- Stage 1: parsing -------------------------------------------------
        tracemalloc.start()
        tracks = load_tracks(config, runs)
        _, parse_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        n_points = sum(len(points) for _, points in tracks)
        point_bytes = sum(points.nbytes for _, points in tracks)
        print("Parse (load_tracks)")
        print(f"  tracks                : {len(tracks):,}")
        print(f"  points                : {n_points:,}")
        print(f"  point array bytes     : {point_bytes / 1e6:.1f} MB")
        if n_points:
            print(f"  bytes per point       : {point_bytes / n_points:.1f}")
        print(f"  tracemalloc peak      : {parse_peak / 1e6:.1f} MB")
        print(f"  process peak RSS      : {peak_rss_mb():.1f} MB\n")

        # --- Stage 2: rasterization ------------------------------------------
        to_wm, from_wm, to_utm, home_x, home_y, clip_m = setup_transformers(
            HOME_LAT, HOME_LON, 25.0
        )
        x_min, x_max, y_min, y_max = compute_grid_bounds(
            tracks, to_wm, to_utm, home_x, home_y, clip_m, 200.0
        )
        grids = create_grids(x_min, x_max, y_min, y_max, args.meters_per_pixel)

        tracemalloc.start()
        n_activities = rasterize_tracks(
            tracks,
            to_wm,
            to_utm,
            home_x,
            home_y,
            clip_m,
            x_min,
            y_max,
            args.meters_per_pixel,
            3,
            grids,
            0.5,
        )
        _, raster_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        print("Rasterize (rasterize_tracks)")
        print(f"  grid size             : {grids[0]} x {grids[1]} cells")
        print(f"  activities rasterized : {n_activities:,}")
        print(f"  tracemalloc peak      : {raster_peak / 1e6:.1f} MB")
        print(f"  process peak RSS      : {peak_rss_mb():.1f} MB")


if __name__ == "__main__":
    main()
