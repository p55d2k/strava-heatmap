"""
Strava Activity Heatmap Generator
Main entry point that orchestrates the pipeline.
"""

import logging
import sys
import warnings
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# Suppress non-critical third-party warnings
warnings.filterwarnings("ignore", category=UserWarning, module="folium")
warnings.filterwarnings("ignore", category=FutureWarning, module="pandas")
warnings.filterwarnings("ignore", category=UserWarning, module="pyproj")

# Import pipeline modules
from src.config import Config
from src.data_loader import (
    load_and_filter_activities,
    determine_home_location,
    filter_by_home_radius,
    load_tracks,
)
from src.rasterizer import (
    setup_transformers,
    compute_grid_bounds,
    create_grids,
    rasterize_tracks,
    compute_normalized_grids,
)
from src.colormaps import create_colormaps, generate_layer_uris
from src.map_builder import build_legend_html, build_map


def main():
    """Main pipeline function."""
    # Load configuration
    config = Config(Path("config.json"))
    config.log_summary()

    # Stage 1: Data loading & filtering
    runs = load_and_filter_activities(config)
    home_lat, home_lon = determine_home_location(config, runs)
    runs = filter_by_home_radius(runs, home_lat, home_lon, config.radius_km)
    tracks = load_tracks(config, runs)

    # Stage 2: Rasterization & grid computation
    to_wm, from_wm, to_utm, home_x_utm, home_y_utm, clip_m = setup_transformers(
        home_lat, home_lon, config.track_clip_radius_km
    )

    x_min_wm, x_max_wm, y_min_wm, y_max_wm = compute_grid_bounds(
        tracks, to_wm, to_utm, home_x_utm, home_y_utm, clip_m, config.padding_m
    )

    grids = create_grids(x_min_wm, x_max_wm, y_min_wm, y_max_wm, config.meters_per_pixel)

    rasterize_tracks(
        tracks, to_wm, to_utm, home_x_utm, home_y_utm, clip_m,
        x_min_wm, y_max_wm, config.meters_per_pixel, grids
    )

    normalized = compute_normalized_grids(grids, config.blur_sigma_px, config)

    # Stage 3: Color maps & image generation
    colormaps = create_colormaps()
    layers = generate_layer_uris(normalized, colormaps)

    # Stage 4: Map building & output
    lon_nw, lat_nw = from_wm.transform(x_min_wm, y_max_wm)
    lon_se, lat_se = from_wm.transform(x_max_wm, y_min_wm)
    bounds = [[lat_se, lon_nw], [lat_nw, lon_se]]
    centre = [(lat_nw + lat_se) / 2, (lon_nw + lon_se) / 2]

    legend_html = build_legend_html(normalized, colormaps, normalized["max_passes"])

    build_map(tracks, layers, bounds, centre, legend_html, config.output_html, config.map_opacity)


if __name__ == "__main__":
    main()