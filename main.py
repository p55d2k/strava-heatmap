"""
Strava Activity Heatmap Generator
Main entry point that orchestrates the pipeline.
"""

import argparse
import logging
import warnings
from pathlib import Path

from tqdm import tqdm

# Suppress specific non-critical third-party warnings (narrow filters)
warnings.filterwarnings("ignore", message=".*Folium.*", category=UserWarning, module="folium")
warnings.filterwarnings("ignore", message=".*pandas.*", category=FutureWarning, module="pandas")
warnings.filterwarnings("ignore", message=".*pyproj.*", category=UserWarning, module="pyproj")

# Import pipeline modules
from src.colormaps import create_colormaps, generate_layer_uris
from src.config import Config
from src.data_loader import (
    determine_home_location,
    filter_by_home_radius,
    load_and_filter_activities,
    load_tracks,
)
from src.map_builder import build_legend_html, build_map
from src.rasterizer import (
    compute_grid_bounds,
    compute_normalized_grids,
    create_grids,
    rasterize_tracks,
    setup_transformers,
)


def setup_logging(dev: bool) -> None:
    """Configure logging level based on dev flag."""
    level = logging.DEBUG if dev else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def print_stage(title: str, icon: str = "▸") -> None:
    """Print a nicely formatted stage header."""
    print(f"\n{icon}  {title}")
    print("─" * (len(title) + 4))


def print_info(label: str, value: str) -> None:
    """Print a nicely formatted info line."""
    print(f"  {label}: {value}")


def print_success(message: str) -> None:
    """Print a success message."""
    print(f"  ✓ {message}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    print(f"  ⚠ {message}")


def print_debug(dev: bool, message: str) -> None:
    """Print a debug message only when dev mode is enabled."""
    if dev:
        print(f"  › {message}")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Strava Activity Heatmap Generator")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config, show activity count, and exit without generating map",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.json"),
        help="Path to config.json file (default: config.json)",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Enable verbose/debug logging for development",
    )
    return parser.parse_args()


def main():
    """Main pipeline function."""
    args = parse_args()

    # Setup logging based on dev flag
    setup_logging(args.dev)

    # Load configuration
    config = Config(args.config)
    config.log_summary()

    # Stage 1: Data loading & filtering
    print_stage("Stage 1: Loading & Filtering Activities")
    runs = load_and_filter_activities(config)
    home_lat, home_lon = determine_home_location(config, runs)
    runs = filter_by_home_radius(runs, home_lat, home_lon, config.radius_km)

    print_info("Activities after all filters", str(len(runs)))

    if args.dry_run:
        print_success("Dry run complete. Exiting without generating map.")
        return

    # Stage 2: Loading GPS Tracks (has progress bar)
    print_stage("Stage 2: Loading GPS Tracks")
    tracks = load_tracks(config, runs)

    # Stage 3: Rasterizing Tracks (has progress bar)
    print_stage("Stage 3: Rasterizing Tracks")
    to_wm, from_wm, to_utm, home_x_utm, home_y_utm, clip_m = setup_transformers(
        home_lat, home_lon, config.track_clip_radius_km
    )

    x_min_wm, x_max_wm, y_min_wm, y_max_wm = compute_grid_bounds(
        tracks, to_wm, to_utm, home_x_utm, home_y_utm, clip_m, config.padding_m
    )

    grids = create_grids(x_min_wm, x_max_wm, y_min_wm, y_max_wm, config.meters_per_pixel)

    rasterize_tracks(
        tracks,
        to_wm,
        to_utm,
        home_x_utm,
        home_y_utm,
        clip_m,
        x_min_wm,
        y_max_wm,
        config.meters_per_pixel,
        config.max_consecutive_same_cell,
        grids,
        config.decay_factor,
    )

    # Stage 4: Computing Normalized Grids (6 steps: count, speed, hr, gradient, elevation, alpha)
    print_stage("Stage 4: Computing Normalized Grids")
    with tqdm(total=6, desc="Normalizing grids", unit="step", disable=not args.dev) as pbar:
        normalized = compute_normalized_grids(
            grids, config.blur_sigma_px, config, progress_callback=pbar.update
        )
    print_success("Grid normalization complete")

    # Stage 5: Generating Map Layers (7 steps: colormaps + 6 layers)
    print_stage("Stage 5: Generating Map Layers")
    with tqdm(total=7, desc="Generating layers", unit="layer", disable=not args.dev) as pbar:
        colormaps = create_colormaps()
        pbar.update(1)
        layers = generate_layer_uris(normalized, colormaps, progress_callback=pbar.update)
    print_success(f"Created {len(layers)} map layers")

    # Stage 6: Building Interactive Map (4 steps: bounds/centre, legend, build_map (3 sub-steps))
    print_stage("Stage 6: Building Interactive Map")
    with tqdm(total=4, desc="Building map", unit="step", disable=not args.dev) as pbar:
        lon_nw, lat_nw = from_wm.transform(x_min_wm, y_max_wm)
        lon_se, lat_se = from_wm.transform(x_max_wm, y_min_wm)
        bounds = [[lat_se, lon_nw], [lat_nw, lon_se]]
        centre = [(lat_nw + lat_se) / 2, (lon_nw + lon_se) / 2]
        pbar.update(1)

        legend_html = build_legend_html(normalized, colormaps, normalized["max_passes"])
        pbar.update(1)

        build_map(
            tracks,
            layers,
            bounds,
            centre,
            legend_html,
            config.output_html,
            config.map_opacity,
            progress_callback=pbar.update,
        )
        pbar.update(1)

        pbar.update(1)

    print_success(f"Heatmap saved to: {config.output_html}")
    print(f"\n  Open in browser: file://{config.output_html.absolute()}\n")


if __name__ == "__main__":
    main()
