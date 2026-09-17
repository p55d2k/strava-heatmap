"""
Configuration management for Strava Heatmap Generator.

This module provides the Config class which wraps the Pydantic ConfigModel
for validation and IDE support while maintaining backward compatibility.
"""

import json
from pathlib import Path

import pandas as pd
import tomllib

from src.config_schema import ConfigModel, normalize_activity_type

__all__ = ["Config", "normalize_activity_type"]


class Config:
    """Configuration container loaded from an optional config.toml.

    This class wraps ConfigModel (Pydantic) to provide validation,
    IDE support, and path handling. JSON remains supported for compatibility.
    """

    def __init__(self, config_path: Path | None = None):
        """Load optional configuration and infer safe values from the export."""
        requested_path = config_path
        if config_path is None:
            config_path = next(
                (path for path in (Path("config.toml"), Path("config.json")) if path.exists()),
                Path("config.toml"),
            )
        if config_path.exists():
            cfg = _load_config_file(config_path)
            base_dir = config_path.parent.resolve()
        elif requested_path is not None:
            raise FileNotFoundError(
                f"Config file not found: {config_path}\n"
                "  -> Omit --config to use automatic defaults, or create the file"
            )
        else:
            cfg = {}
            base_dir = Path.cwd().resolve()

        activities_dir = _discover_activities_dir(base_dir, cfg.get("ACTIVITIES_DIR"))
        cfg.setdefault("ACTIVITIES_DIR", str(activities_dir))
        if "ACTIVITY_TYPES" not in cfg:
            cfg["ACTIVITY_TYPES"] = _discover_activity_types(activities_dir)

        # Use Pydantic model for validation after resolving directory paths.
        model = ConfigModel(**_resolve_relative_paths(cfg, base_dir))

        # Copy all validated fields from the model
        self.activities_dir = Path(model.activities_dir)
        self.activity_types = set(model.activity_types)
        self.date_from = model.date_from
        self.date_to = model.date_to

        self.home_lat = model.home_lat
        self.home_lon = model.home_lon
        self.radius_km = model.radius_km
        self.radius_km_auto = "RADIUS_KM" not in cfg

        self.gps_spread_min_m = model.gps_spread_min_m
        self.meters_per_pixel = model.meters_per_pixel
        self.padding_m = model.padding_m
        self.track_clip_radius_km = model.track_clip_radius_km

        self.blur_sigma_px = model.blur_sigma_px
        self.map_opacity = model.map_opacity
        self.carto_style = model.carto_style

        self.speed_min_ms = model.speed_min_ms
        self.speed_max_ms = model.speed_max_ms
        self.hr_min_bpm = model.hr_min_bpm
        self.hr_max_bpm = model.hr_max_bpm
        self.auto_range_pct = model.auto_range_pct
        self.max_consecutive_same_cell = model.max_consecutive_same_cell
        self.decay_factor = model.decay_factor
        self.raster_mode = model.raster_mode
        self.coverage_normalization = model.coverage_normalization

        # Paths are already resolved by ConfigModel
        self.cache_dir = Path(model.cache_dir)
        self.output_dir = Path(model.output_dir)
        self.activities_csv = self.activities_dir / model.activities_csv
        self.cache_file = self.cache_dir / model.cache_file
        self.output_html = self.output_dir / model.output_html
        self.output_gpx = self.output_dir / model.output_gpx

        # Embeddable widget (iframe) mode.
        self.embed_enabled = model.embed_enabled
        self.output_embed_html = self.output_dir / model.embed_html
        self.embed_legend = model.embed_legend
        self.embed_attribution = model.embed_attribution
        self.embed_home_marker = model.embed_home_marker
        self.embed_tracks = model.embed_tracks
        self.embed_metrics = list(model.embed_metrics)
        self.embed_demo = model.embed_demo
        # The demo page sits beside the widget, so its filename follows EMBED_HTML.
        self.output_embed_demo_html = self.output_embed_html.with_name(
            f"{self.output_embed_html.stem}_demo.html"
        )

    def log_summary(self):
        import logging

        log = logging.getLogger(__name__)
        log.info(f"Source:  {self.activities_dir}/")
        log.info(f"Types:   {', '.join(self.activity_types)}")
        log.info(f"Output:  {self.output_html}")


def _load_config_file(config_path: Path) -> dict:
    """Load a TOML config, or a JSON config for backward compatibility."""
    with open(config_path, "rb") as file:
        if config_path.suffix.lower() == ".toml":
            return tomllib.load(file)
        return json.load(file)


def _resolve_relative_paths(cfg: dict, base_dir: Path) -> dict:
    """Resolve directory paths relative to the config or working directory."""
    result = dict(cfg)
    result.setdefault("CACHE_DIR", str(base_dir / "cache"))
    result.setdefault("OUTPUT_DIR", str(base_dir / "outputs"))
    for key in ("ACTIVITIES_DIR", "CACHE_DIR", "OUTPUT_DIR"):
        path = Path(result[key]) if key in result else None
        if path is not None and not path.is_absolute():
            result[key] = str((base_dir / path).resolve())
    return result


def _discover_activities_dir(base_dir: Path, configured: str | None) -> Path:
    """Find a Strava export directory without requiring a config file."""
    if configured:
        path = Path(configured)
        return (base_dir / path).resolve() if not path.is_absolute() else path

    candidates = [base_dir / "strava_export", base_dir]
    candidates.extend(
        path.parent
        for path in base_dir.glob("*/activities.csv")
        if path.parent.name not in {".venv", "build", "cache", "outputs"}
    )
    for candidate in candidates:
        if (candidate / "activities.csv").is_file():
            return candidate.resolve()
    return (base_dir / "strava_export").resolve()


def _discover_activity_types(activities_dir: Path) -> list[str]:
    """Select all activity types with at least one track file in the export."""
    csv_path = activities_dir / "activities.csv"
    if not csv_path.is_file():
        return ["Run"]
    frame = pd.read_csv(csv_path, usecols=["Activity Type", "Filename"])
    found: list[str] = []
    for raw_type, group in frame.groupby("Activity Type", sort=False):
        if any((activities_dir / str(name)).is_file() for name in group["Filename"]):
            normalized = normalize_activity_type(raw_type)
            if normalized and normalized not in found:
                found.append(normalized)
    return found or ["Run"]
