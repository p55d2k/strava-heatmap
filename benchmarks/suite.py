"""
The benchmark suite: time and measure memory for each pipeline stage.

Each stage is timed over a few repetitions (best and median reported) with
``tracemalloc`` peak and process-RSS growth captured alongside, so a run shows
both runtime and memory. Results are plain dicts, JSON-serialisable for storing
a baseline and comparing releases with :func:`compare_results`.
"""

import contextlib
import gc
import io
import os
import resource
import shutil
import statistics
import sys
import tempfile
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.synthetic import SCENARIOS, Export, generate_export, runs_frame

STAGE_NAMES = (
    "fit_parsing",
    "activity_normalization",
    "rasterization",
    "map_generation",
    "end_to_end",
)

# Restrict end-to-end runs on the largest scenario by default (it is the slowest
# and its stage numbers already come from the same data).
DEFAULT_END_TO_END_SCENARIOS = ("small", "medium")
BENCHMARK_METERS_PER_PIXEL = 5.0


def _rss_bytes() -> int:
    """Process peak RSS in bytes (``ru_maxrss`` is bytes on macOS, KiB elsewhere)."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss if sys.platform == "darwin" else rss * 1024


def measure(fn, repeat: int = 3, before_each=None):
    """Run ``fn`` ``repeat`` times; return (metrics, last_result).

    Metrics hold the best and median wall time plus the peak Python allocation
    (``tracemalloc``) and process-RSS growth seen across the repetitions. An
    optional ``before_each`` callback runs before each timed call (e.g. to drop
    a cache so every run is cold).
    """
    times: list[float] = []
    peak_traced = 0
    peak_rss = 0
    last = None
    for _ in range(repeat):
        if before_each is not None:
            before_each()
        gc.collect()
        rss_before = _rss_bytes()
        tracemalloc.start()
        start = time.perf_counter()
        last = fn()
        elapsed = time.perf_counter() - start
        _, traced = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        times.append(elapsed)
        peak_traced = max(peak_traced, traced)
        peak_rss = max(peak_rss, _rss_bytes() - rss_before)
    times.sort()
    metrics = {
        "seconds_min": round(times[0], 6),
        "seconds_median": round(statistics.median(times), 6),
        "peak_mb": round(peak_traced / 1e6, 3),
        "peak_rss_delta_mb": round(peak_rss / 1e6, 3),
    }
    return metrics, last


@dataclass
class _Context:
    """Per-scenario inputs prepared once and reused by the stage benchmarks."""

    export: Export
    tracks: list
    to_wm: object
    from_wm: object
    to_utm: object
    home_x_utm: float
    home_y_utm: float
    clip_m: float | None
    normalized: dict
    layers: list
    colormaps: dict
    legend_html: str
    bounds: list
    centre: list
    n_activities: int
    raster_config: SimpleNamespace


def _load_tracks_for(export: Export) -> list:
    """Parse every track in the export (fresh cache), returning ``(label, points)``."""
    from src.data_loader import load_tracks

    config = SimpleNamespace(
        activities_dir=export.activities_dir,
        cache_file=export.cache_dir / "cache.pkl",
    )
    return load_tracks(config, runs_frame(export))


def prepare(export: Export, work_root: Path) -> _Context:
    """Load the export once and precompute everything the stages share."""
    from src.colormaps import create_colormaps, generate_layer_uris
    from src.map_builder import LegendBuilder
    from src.rasterizer import (
        compute_grid_bounds,
        compute_normalized_grids,
        create_grids,
        rasterize_tracks,
        setup_transformers,
    )

    tracks = _load_tracks_for(export)
    to_wm, from_wm, to_utm, home_x, home_y, clip_m = setup_transformers(45.0, -122.0, 25.0)
    x_min, x_max, y_min, y_max = compute_grid_bounds(
        tracks, to_wm, to_utm, home_x, home_y, clip_m, 200.0
    )
    grids = create_grids(x_min, x_max, y_min, y_max, BENCHMARK_METERS_PER_PIXEL)

    raster_config = SimpleNamespace(
        speed_min_ms=None,
        speed_max_ms=None,
        hr_min_bpm=None,
        hr_max_bpm=None,
        auto_range_pct=20,
        coverage_normalization="max",
    )
    n_activities = rasterize_tracks(
        tracks,
        to_wm,
        to_utm,
        home_x,
        home_y,
        clip_m,
        x_min,
        y_max,
        BENCHMARK_METERS_PER_PIXEL,
        3,
        grids,
        0.5,
        raster_mode="decay",
    )
    normalized = compute_normalized_grids(
        grids, 3.0, raster_config, n_activities=n_activities, raster_mode="decay"
    )
    colormaps = create_colormaps()
    layers = generate_layer_uris(normalized, colormaps, raster_mode="decay")
    legend_html = LegendBuilder().build(
        normalized,
        colormaps,
        normalized["max_passes"],
        max_passes_by_strategy=normalized["max_passes_by_strategy"],
    )

    lon_nw, lat_nw = from_wm.transform(x_min, y_max)
    lon_se, lat_se = from_wm.transform(x_max, y_min)
    bounds = [[lat_se, lon_nw], [lat_nw, lon_se]]
    centre = [(lat_nw + lat_se) / 2, (lon_nw + lon_se) / 2]

    return _Context(
        export=export,
        tracks=tracks,
        to_wm=to_wm,
        from_wm=from_wm,
        to_utm=to_utm,
        home_x_utm=home_x,
        home_y_utm=home_y,
        clip_m=clip_m,
        normalized=normalized,
        layers=layers,
        colormaps=colormaps,
        legend_html=legend_html,
        bounds=bounds,
        centre=centre,
        n_activities=n_activities,
        raster_config=raster_config,
    )


# ---------------------------------------------------------------------------
# The individual stage benchmarks
# ---------------------------------------------------------------------------


def bench_fit_parsing(export: Export, repeat: int) -> dict:
    """Parse every FIT/GPX track in the export (raw parser throughput)."""
    from src.helpers import parse_track_file

    paths = [export.activities_dir / name for name in export.filenames]

    def run():
        return sum(len(parse_track_file(path)) for path in paths)

    metrics, points = measure(run, repeat)
    metrics["points_per_run"] = points
    metrics["bytes_on_disk"] = sum(p.stat().st_size for p in paths)
    return metrics


def bench_activity_normalization(export: Export, repeat: int) -> dict:
    """CSV load, activity-type normalization and the date/type/GPS filters."""
    from src.data_loader import load_and_filter_activities

    config = SimpleNamespace(
        activities_csv=export.activities_csv,
        activities_dir=export.activities_dir,
        activity_types={"Run"},
        date_from=None,
        date_to=None,
        gps_spread_min_m=0,
        cache_file=export.cache_dir / "cache.pkl",
    )
    # Warm the GPS cache so a repetition measures normalization, not parsing.
    load_and_filter_activities(config)

    def run():
        return len(load_and_filter_activities(config))

    metrics, count = measure(run, repeat)
    metrics["activities"] = count
    return metrics


def bench_rasterization(ctx: _Context, repeat: int) -> dict:
    """Grid bounds + grid creation + rasterize + normalize."""
    from src.rasterizer import (
        compute_grid_bounds,
        compute_normalized_grids,
        create_grids,
        rasterize_tracks,
    )

    def run():
        x_min, x_max, y_min, y_max = compute_grid_bounds(
            ctx.tracks, ctx.to_wm, ctx.to_utm, ctx.home_x_utm, ctx.home_y_utm, ctx.clip_m, 200.0
        )
        grids = create_grids(x_min, x_max, y_min, y_max, BENCHMARK_METERS_PER_PIXEL)
        n = rasterize_tracks(
            ctx.tracks,
            ctx.to_wm,
            ctx.to_utm,
            ctx.home_x_utm,
            ctx.home_y_utm,
            ctx.clip_m,
            x_min,
            y_max,
            BENCHMARK_METERS_PER_PIXEL,
            3,
            grids,
            0.5,
            raster_mode="decay",
        )
        return grids, compute_normalized_grids(
            grids, 3.0, ctx.raster_config, n_activities=n, raster_mode="decay"
        )

    metrics, last = measure(run, repeat)
    grids = last[0]
    metrics["grid"] = [int(grids[0]), int(grids[1])]
    metrics["activities"] = ctx.n_activities
    return metrics


def bench_map_generation(ctx: _Context, repeat: int, work_root: Path) -> dict:
    """Folium/HTML assembly for the main map (layers and legend precomputed)."""
    from src.map_builder import build_map

    output = work_root / "bench_map.html"

    def run():
        build_map(
            ctx.tracks,
            ctx.layers,
            ctx.bounds,
            ctx.centre,
            ctx.legend_html,
            output,
            0.8,
            home=[45.0, -122.0],
        )
        return output.stat().st_size

    metrics, size = measure(run, repeat)
    metrics["html_bytes"] = size
    return metrics


def bench_end_to_end(export: Export, repeat: int) -> dict:
    """The real CLI entry point (`heatmap generate`) on the synthetic export."""
    import main

    os.environ.setdefault("CARTO_API_KEY", "benchmark-key")
    argv = ["heatmap", "generate", "--config", str(export.config_path), "--no-open"]

    def before_each():
        # Cold run: drop the cache and prior outputs so parsing is included.
        shutil.rmtree(export.cache_dir, ignore_errors=True)
        shutil.rmtree(export.output_dir, ignore_errors=True)

    def run():
        with (
            patch.object(sys, "argv", argv),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            main.main()
        return (export.output_dir / "heatmap.html").stat().st_size

    metrics, size = measure(run, repeat, before_each=before_each)
    metrics["html_bytes"] = size
    return metrics


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_benchmarks(
    scenario_names=("small", "medium", "large"),
    repeat: int = 3,
    end_to_end_scenarios=DEFAULT_END_TO_END_SCENARIOS,
    work_root: Path | None = None,
) -> dict:
    """Run every stage for each scenario and return the JSON-serialisable report."""
    names = [name for name in scenario_names if name in SCENARIOS]
    for name in scenario_names:
        if name not in SCENARIOS:
            raise ValueError(f"Unknown scenario {name!r}; choose from {sorted(SCENARIOS)}")

    results: dict = {
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "repeat": repeat,
        },
        "scenarios": {},
    }

    own_root = work_root is None
    root = Path(work_root) if work_root is not None else Path(tempfile.mkdtemp(prefix="bench-"))
    try:
        for name in names:
            scenario = SCENARIOS[name]
            export = generate_export(root / name, scenario)
            ctx = prepare(export, root / name)

            stages: dict = {
                "fit_parsing": bench_fit_parsing(export, repeat),
                "activity_normalization": bench_activity_normalization(export, repeat),
                "rasterization": bench_rasterization(ctx, repeat),
                "map_generation": bench_map_generation(ctx, repeat, root / name),
            }
            if name in end_to_end_scenarios:
                stages["end_to_end"] = bench_end_to_end(export, repeat)

            results["scenarios"][name] = {
                "export": {
                    "activities": scenario.n_activities,
                    "points": scenario.total_points,
                },
                "stages": stages,
            }
    finally:
        if own_root:
            shutil.rmtree(root, ignore_errors=True)

    return results


def compare_results(current: dict, baseline: dict, threshold_pct: float = 15.0) -> list[dict]:
    """Compare ``current`` against ``baseline``; return regression records.

    Each record names the scenario, stage and metric, with the baseline/current
    values and the signed percentage change. Only changes *slower* or *larger*
    by more than ``threshold_pct`` are returned.
    """
    regressions: list[dict] = []
    for scenario, stages in current.get("scenarios", {}).items():
        base_stages = baseline.get("scenarios", {}).get(scenario, {}).get("stages", {})
        for stage, metrics in stages.get("stages", {}).items():
            base_metrics = base_stages.get(stage)
            if not base_metrics:
                continue
            for metric in ("seconds_min", "peak_mb"):
                base_value = base_metrics.get(metric)
                current_value = metrics.get(metric)
                if not base_value or current_value is None:
                    continue
                change = (current_value - base_value) / base_value * 100.0
                if change > threshold_pct:
                    regressions.append(
                        {
                            "scenario": scenario,
                            "stage": stage,
                            "metric": metric,
                            "baseline": base_value,
                            "current": current_value,
                            "change_pct": round(change, 1),
                        }
                    )
    return regressions
