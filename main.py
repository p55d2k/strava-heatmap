"""
Strava Activity Heatmap Generator
Main entry point that orchestrates the pipeline.
"""

import argparse
import logging
import sys
import warnings
import webbrowser
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
from src.geojson_export import build_geojson, geojson_feature_count
from src.gpx_export import write_gpx
from src.map_builder import (
    DENSITY_MODE_LAYERS,
    INDEPENDENT_LAYER_NAMES,
    LegendBuilder,
    build_embed_demo_html,
    build_map,
    encode_for_embedding,
)
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


def format_embed_size(n_chars: int) -> str:
    """Format an embedded payload's size for the stage output."""
    if n_chars >= 1_000_000:
        return f"{n_chars / 1e6:.1f} MB"
    return f"{n_chars / 1000:.0f} KB"


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
    # Options every subcommand accepts.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        type=Path,
        default=Path("config.json"),
        help="Path to config.json file (default: config.json)",
    )
    common.add_argument(
        "--dev",
        action="store_true",
        help="Enable verbose/debug logging for development",
    )
    # The map-building subcommands additionally open the result in a browser.
    parent = argparse.ArgumentParser(add_help=False, parents=[common])
    parent.add_argument(
        "--no-open",
        action="store_true",
        dest="no_open",
        help="Do not automatically open the generated heatmap in the browser",
    )
    parent.add_argument(
        "--embed",
        action="store_true",
        dest="embed",
        help=("Also build the minimal, interactive widget (no control panel) for iframe embedding"),
    )

    # Also add them to the main parser for backward compatibility when no subcommand is used
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Validate config, show activity count, and exit without generating map",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        dest="no_open",
        help="Do not automatically open the generated heatmap in the browser",
    )
    parser.add_argument(
        "--embed",
        action="store_true",
        dest="embed",
        help=("Also build the minimal, interactive widget (no control panel) for iframe embedding"),
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Default command: generate heatmap
    generate_parser = subparsers.add_parser(
        "generate",
        parents=[parent],
        help="Generate heatmap (default)",
    )
    generate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config, show activity count, and exit without generating map",
    )

    # Validate command: just validate config
    subparsers.add_parser(
        "validate",
        parents=[parent],
        help="Validate config.json file",
    )

    # Export command: re-export the filtered tracks as GPX, without building the map
    export_parser = subparsers.add_parser(
        "export-gpx",
        parents=[common],
        help="Re-export the filtered GPS tracks as a single GPX file",
        description=(
            "Apply the same type / date / home-radius filters as `generate` and "
            "write the surviving tracks to one GPX file (one track per activity), "
            "ready for Garmin Connect, QGIS or any other GPX tool."
        ),
    )
    export_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Destination file (default: OUTPUT_GPX in OUTPUT_DIR, e.g. outputs/tracks.gpx)",
    )

    # If no subcommand is provided, default to 'generate'
    args = parser.parse_args()
    if args.command is None:
        args.command = "generate"
    return args


def print_error(message: str) -> None:
    """Print an error message."""
    print(f"  ✗ {message}")


def gpx_title(config: Config) -> str:
    """Return the ``<metadata><name>`` written into the GPX track export."""
    return f"Strava {'/'.join(sorted(config.activity_types))} tracks"


def run_validate(args: argparse.Namespace) -> None:
    """Validate config.json file."""
    # Setup logging based on dev flag
    setup_logging(args.dev)

    try:
        # Load and validate configuration
        config = Config(args.config)
        config.log_summary()

        # Also validate that activities.csv exists and can be read
        if not config.activities_csv.exists():
            raise FileNotFoundError(
                f"Activities CSV not found: {config.activities_csv}\n"
                f"  → Check ACTIVITIES_CSV in config.json matches the file in ACTIVITIES_DIR"
            )

        print_success("Config validation passed!")
        print_info("Activities directory", str(config.activities_dir))
        print_info("Activities CSV", str(config.activities_csv))
        print_info("Activity types", ", ".join(config.activity_types))
        print_info("Date range", f"{config.date_from} to {config.date_to}")
        print_info("Home location", f"{config.home_lat}, {config.home_lon}")
        print_info("Radius", f"{config.radius_km} km")
        print_info("Output directory", str(config.output_dir))
        print_info("Cache directory", str(config.cache_dir))
        if config.embed_enabled:
            print_info("Embed widget", str(config.output_embed_html))

    except (FileNotFoundError, NotADirectoryError, ValueError) as e:
        print_error(str(e))
        if args.dev:
            import traceback

            traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        if args.dev:
            import traceback

            traceback.print_exc()
        sys.exit(1)


def run_generate(args: argparse.Namespace) -> None:
    """Run the full heatmap generation pipeline."""
    # Setup logging based on dev flag
    setup_logging(args.dev)

    try:
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

        # Stage 2: Loading GPS Tracks (has progress bar), then re-exporting the
        # same filtered tracks as GPX for other tools.
        print_stage("Stage 2: Loading GPS Tracks")
        tracks = load_tracks(config, runs)
        n_gpx_tracks, n_gpx_points = write_gpx(tracks, config.output_gpx, gpx_title(config))
        print_success(
            f"Re-exported {n_gpx_tracks} tracks ({n_gpx_points:,} points) to {config.output_gpx}"
        )

        # The panel's "Export GPX" button downloads that very document, so the
        # page carries a compressed copy of it. Reading back what was just
        # written means the download and the file on disk cannot drift apart.
        gpx_text = config.output_gpx.read_text(encoding="utf-8")
        gpx_embed = encode_for_embedding(gpx_text)
        del gpx_text  # the compressed copy is all the rest of the run needs
        print_info(
            "GPX embedded for the panel's Export GPX button",
            format_embed_size(len(gpx_embed)),
        )

        # Stage 3: Rasterizing Tracks (has progress bar)
        print_stage("Stage 3: Rasterizing Tracks")
        to_wm, from_wm, to_utm, home_x_utm, home_y_utm, clip_m = setup_transformers(
            home_lat, home_lon, config.track_clip_radius_km
        )

        x_min_wm, x_max_wm, y_min_wm, y_max_wm = compute_grid_bounds(
            tracks, to_wm, to_utm, home_x_utm, home_y_utm, clip_m, config.padding_m
        )

        grids = create_grids(x_min_wm, x_max_wm, y_min_wm, y_max_wm, config.meters_per_pixel)

        n_activities = rasterize_tracks(
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
            raster_mode=config.raster_mode,
        )

        # Stage 4: Computing Normalized Grids (6 steps: count, speed, hr, gradient, elevation, alpha)
        print_stage("Stage 4: Computing Normalized Grids")
        with tqdm(total=6, desc="Normalizing grids", unit="step", disable=not args.dev) as pbar:
            normalized = compute_normalized_grids(
                grids,
                config.blur_sigma_px,
                config,
                n_activities=n_activities,
                progress_callback=pbar.update,
                raster_mode=config.raster_mode,
            )
        print_success("Grid normalization complete")

        # Stage 5: Generating Map Layers and the GeoJSON export (1 colormap step
        # + 1 GeoJSON step + 8 layer steps: one GPS density layer per raster mode
        # + Coverage + four metrics)
        print_stage("Stage 5: Generating Map Layers")
        with tqdm(total=9, desc="Generating layers", unit="step", disable=not args.dev) as pbar:
            colormaps = create_colormaps()
            pbar.update(1)
            # One polygon per populated cell, for the panel's GeoJSON download.
            geojson = build_geojson(
                normalized,
                grids,
                x_min_wm,
                y_max_wm,
                config.meters_per_pixel,
                from_wm,
            )
            pbar.update(1)
            layers = generate_layer_uris(
                normalized,
                colormaps,
                coverage_normalization=config.coverage_normalization,
                raster_mode=config.raster_mode,
                progress_callback=pbar.update,
            )
        print_success(f"Created {len(layers)} map layers")
        print_success(f"GeoJSON export: {geojson_feature_count(geojson)} grid cells")

        # The grid export is repetitive plain text, so — like the GPX track
        # export above — it rides with the page compressed: a dense grid would
        # otherwise add tens of MB to the HTML.
        geojson_embed = encode_for_embedding(geojson)
        del geojson  # the compressed copy is all the rest of the run needs
        print_info(
            "GeoJSON embedded for the panel's Export GeoJSON button",
            format_embed_size(len(geojson_embed)),
        )

        # Stage 6: Building Interactive Map (4 steps: bounds/centre, legend, build_map (3 sub-steps))
        print_stage("Stage 6: Building Interactive Map")
        with tqdm(total=4, desc="Building map", unit="step", disable=not args.dev) as pbar:
            lon_nw, lat_nw = from_wm.transform(x_min_wm, y_max_wm)
            lon_se, lat_se = from_wm.transform(x_max_wm, y_min_wm)
            bounds = [[lat_se, lon_nw], [lat_nw, lon_se]]
            centre = [(lat_nw + lat_se) / 2, (lon_nw + lon_se) / 2]
            pbar.update(1)

            legend_builder = LegendBuilder()
            legend_html = legend_builder.build(
                normalized,
                colormaps,
                normalized["max_passes"],
                max_passes_by_strategy=normalized["max_passes_by_strategy"],
            )
            pbar.update(1)

            build_map(
                tracks,
                layers,
                bounds,
                centre,
                legend_html,
                config.output_html,
                config.map_opacity,
                carto_style=config.carto_style,
                metric_layer_names=INDEPENDENT_LAYER_NAMES,
                legend_ids=legend_builder.legend_ids,
                home=[home_lat, home_lon],
                geojson=geojson_embed,
                gpx=gpx_embed,
                gpx_filename=config.output_gpx.name,
                progress_callback=pbar.update,
            )
            pbar.update(1)

            pbar.update(1)

        print_success(f"Heatmap saved to: {config.output_html}")
        print_info("GPX track export", str(config.output_gpx))

        # Optional second build: the same heatmap as a minimal, still-interactive
        # widget (no control panel) for dropping into an <iframe> on another page.
        if args.embed or config.embed_enabled:
            print_stage("Stage 7: Building Embeddable Widget")
            # The widget has no layer control to sync legend rows, so its legend
            # is rendered with exactly the rows for the layers it ships: the
            # configured raster mode's density layer plus any EMBED_METRICS.
            widget_layer_names = [
                DENSITY_MODE_LAYERS[config.raster_mode],
                *config.embed_metrics,
            ]
            widget_legend = LegendBuilder(
                rows=legend_builder.visible_for(widget_layer_names)
            ).build(
                normalized,
                colormaps,
                normalized["max_passes"],
                max_passes_by_strategy=normalized["max_passes_by_strategy"],
            )
            build_map(
                tracks,
                layers,
                bounds,
                centre,
                widget_legend,
                config.output_embed_html,
                config.map_opacity,
                carto_style=config.carto_style,
                home=[home_lat, home_lon],
                embed=True,
                embed_legend=config.embed_legend,
                embed_attribution=config.embed_attribution,
                embed_home_marker=config.embed_home_marker,
                embed_tracks=config.embed_tracks,
                embed_metrics=config.embed_metrics,
            )
            print_success(f"Embeddable widget saved to: {config.output_embed_html}")
            if config.embed_metrics:
                print_info("Widget metric layers", ", ".join(config.embed_metrics))

            # A tiny demo page beside the widget: it hosts the widget in a
            # responsive iframe and repeats the snippet to copy, so opening it
            # shows how the widget is meant to be embedded.
            if config.embed_demo:
                config.output_embed_demo_html.write_text(
                    build_embed_demo_html(config.output_embed_html.name),
                    encoding="utf-8",
                )
                print_success(f"Embed demo page saved to: {config.output_embed_demo_html}")

        if not args.no_open:
            file_url = f"file://{config.output_html.absolute()}"
            print(f"\n  Opening in browser: {file_url}\n")
            webbrowser.open(file_url)
        else:
            print(f"\n  Open in browser: file://{config.output_html.absolute()}\n")

    except (FileNotFoundError, NotADirectoryError, ValueError) as e:
        print_error(str(e))
        if args.dev:
            import traceback

            traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        if args.dev:
            import traceback

            traceback.print_exc()
        sys.exit(1)


def run_export_gpx(args: argparse.Namespace) -> None:
    """Re-export the filtered GPS tracks as a single GPX file (no map build)."""
    setup_logging(args.dev)

    try:
        config = Config(args.config)
        config.log_summary()

        # Deliberately the same filters as `generate`, so the GPX always matches
        # the set of activities baked into the heatmap.
        print_stage("Filtering Activities")
        runs = load_and_filter_activities(config)
        home_lat, home_lon = determine_home_location(config, runs)
        runs = filter_by_home_radius(runs, home_lat, home_lon, config.radius_km)
        print_info("Activities after all filters", str(len(runs)))

        print_stage("Loading GPS Tracks")
        tracks = load_tracks(config, runs)

        output_path = Path(args.output) if args.output else config.output_gpx
        n_tracks, n_points = write_gpx(tracks, output_path, gpx_title(config))
        print_success(f"Exported {n_tracks} tracks ({n_points:,} points) to {output_path}")

    except (FileNotFoundError, NotADirectoryError, ValueError) as e:
        print_error(str(e))
        if args.dev:
            import traceback

            traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        if args.dev:
            import traceback

            traceback.print_exc()
        sys.exit(1)


def main():
    """Main entry point that routes to the appropriate subcommand."""
    args = parse_args()

    if args.command == "validate":
        run_validate(args)
    elif args.command == "export-gpx":
        run_export_gpx(args)
    else:
        run_generate(args)


if __name__ == "__main__":
    main()
