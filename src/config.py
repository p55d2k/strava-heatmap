"""
Configuration management for Strava Heatmap Generator.
"""

import json
from pathlib import Path


class Config:
    """Configuration container loaded from config.json."""

    def __init__(self, config_path: Path):
        if not config_path.exists():
            raise FileNotFoundError("config.json file not found.")

        with open(config_path, "r") as f:
            cfg = json.load(f)

        self.activities_dir = Path(cfg["ACTIVITIES_DIR"])
        self.activity_types = set(cfg["ACTIVITY_TYPES"])
        self.date_from = cfg["DATE_FROM"]
        self.date_to = cfg["DATE_TO"]

        self.home_lat = cfg["HOME_LAT"]
        self.home_lon = cfg["HOME_LON"]
        self.radius_km = cfg["RADIUS_KM"]

        self.gps_spread_min_m = cfg["GPS_SPREAD_MIN_M"]
        self.meters_per_pixel = cfg["METERS_PER_PIXEL"]
        self.padding_m = cfg["PADDING_M"]
        self.track_clip_radius_km = cfg["TRACK_CLIP_RADIUS_KM"]

        self.blur_sigma_px = cfg["BLUR_SIGMA_PX"]
        self.map_opacity = cfg["MAP_OPACITY"]

        self.speed_min_ms = cfg["SPEED_MIN_MS"]
        self.speed_max_ms = cfg["SPEED_MAX_MS"]
        self.hr_min_bpm = cfg["HR_MIN_BPM"]
        self.hr_max_bpm = cfg["HR_MAX_BPM"]
        self.auto_range_pct = cfg["AUTO_RANGE_PCT"]

        # Configurable paths with sensible defaults
        self.cache_dir = Path(cfg.get("CACHE_DIR", "cache"))
        self.output_dir = Path(cfg.get("OUTPUT_DIR", "outputs"))
        self.cache_dir.mkdir(exist_ok=True)
        self.output_dir.mkdir(exist_ok=True)

        self.activities_csv = self.activities_dir / cfg.get("ACTIVITIES_CSV", "activities.csv")
        self.track_cache = self.cache_dir / cfg.get("TRACK_CACHE", "track_cache.json")
        self.output_html = self.output_dir / cfg.get("OUTPUT_HTML", "heatmap.html")

    def log_summary(self):
        import logging
        log = logging.getLogger(__name__)
        log.info(f"Source:  {self.activities_dir}/")
        log.info(f"Types:   {', '.join(self.activity_types)}")
        log.info(f"Output:  {self.output_html}")