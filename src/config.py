"""
Configuration management for Strava Heatmap Generator.

This module provides the Config class which wraps the Pydantic ConfigModel
for validation and IDE support while maintaining backward compatibility.
"""

import json
import os
from pathlib import Path

from src.config_schema import ConfigModel, normalize_activity_type

__all__ = ["Config", "normalize_activity_type"]


class Config:
    """Configuration container loaded from config.json.

    This class wraps ConfigModel (Pydantic) to provide validation,
    IDE support, and path handling while maintaining the same interface
    as the original Config class.
    """

    def __init__(self, config_path: Path):
        if not config_path.exists():
            raise FileNotFoundError(
                f"Config file not found: {config_path}\n"
                f"  -> Create a config.json file (see example_configs/ for templates)"
            )

        with open(config_path) as f:
            cfg = json.load(f)

        # Use Pydantic model for validation
        # We need to pass the config file's parent directory as context
        # for resolving relative paths. We do this by temporarily changing cwd.
        original_cwd = os.getcwd()
        try:
            os.chdir(config_path.parent)
            model = ConfigModel(**cfg)
        finally:
            os.chdir(original_cwd)

        # Copy all validated fields from the model
        self.activities_dir = Path(model.activities_dir)
        self.activity_types = set(model.activity_types)
        self.date_from = model.date_from
        self.date_to = model.date_to

        self.home_lat = model.home_lat
        self.home_lon = model.home_lon
        self.radius_km = model.radius_km

        self.gps_spread_min_m = model.gps_spread_min_m
        self.meters_per_pixel = model.meters_per_pixel
        self.padding_m = model.padding_m
        self.track_clip_radius_km = model.track_clip_radius_km

        self.blur_sigma_px = model.blur_sigma_px
        self.map_opacity = model.map_opacity

        self.speed_min_ms = model.speed_min_ms
        self.speed_max_ms = model.speed_max_ms
        self.hr_min_bpm = model.hr_min_bpm
        self.hr_max_bpm = model.hr_max_bpm
        self.auto_range_pct = model.auto_range_pct
        self.max_consecutive_same_cell = model.max_consecutive_same_cell
        self.decay_factor = model.decay_factor

        # Paths are already resolved by ConfigModel
        self.cache_dir = Path(model.cache_dir)
        self.output_dir = Path(model.output_dir)
        self.activities_csv = self.activities_dir / model.activities_csv
        self.cache_file = self.cache_dir / model.cache_file
        self.output_html = self.output_dir / model.output_html

    def log_summary(self):
        import logging

        log = logging.getLogger(__name__)
        log.info(f"Source:  {self.activities_dir}/")
        log.info(f"Types:   {', '.join(self.activity_types)}")
        log.info(f"Output:  {self.output_html}")
