"""
Configuration management for Strava Heatmap Generator.
"""

import json
from pathlib import Path

# ==============================================================================
# ACTIVITY TYPE ALIASES
# ==============================================================================
# Maps a normalized (lowercase, stripped) activity string to its canonical
# Strava activity type. This lets users write verbose / common names such as
# "Running", "Cycling" or "Bike" in ACTIVITY_TYPES, and also ingest CSV exports
# that use verbose labels (e.g. "Alpine Ski", "Stand Up Paddling") while still
# matching the canonical Strava type used for filtering.
#
# Covers the Strava activity types that carry GPS / location data.
ACTIVITY_TYPE_ALIASES = {
    # --- Running ---
    "run": "Run",
    "running": "Run",
    "jog": "Run",
    "jogging": "Run",
    "trail run": "Run",
    "virtual run": "VirtualRun",
    "virtualrun": "VirtualRun",
    "indoor run": "VirtualRun",
    "treadmill": "VirtualRun",
    # --- Cycling / Riding ---
    "ride": "Ride",
    "cycling": "Ride",
    "bike": "Ride",
    "biking": "Ride",
    "bicycle": "Ride",
    "bicycling": "Ride",
    "cycle": "Ride",
    "commute": "Ride",
    "mtb": "Ride",
    "mountain bike": "Ride",
    "mountain biking": "Ride",
    "road bike": "Ride",
    "road biking": "Ride",
    "gravel ride": "Ride",
    "gravel biking": "Ride",
    "virtual ride": "VirtualRide",
    "virtualride": "VirtualRide",
    "indoor cycle": "VirtualRide",
    "indoor cycling": "VirtualRide",
    "trainer": "VirtualRide",
    "e-bike": "EBikeRide",
    "e-bike ride": "EBikeRide",
    "e bike": "EBikeRide",
    "ebike": "EBikeRide",
    "ebikeride": "EBikeRide",
    "electric bike": "EBikeRide",
    "electric bicycle": "EBikeRide",
    # --- Swimming ---
    "swim": "Swim",
    "swimming": "Swim",
    "pool swim": "Swim",
    "open water swim": "Swim",
    "open water swimming": "Swim",
    "virtual swim": "Swim",
    # --- Walking / Hiking ---
    "walk": "Walk",
    "walking": "Walk",
    "walks": "Walk",
    "stroll": "Walk",
    "hike": "Hike",
    "hiking": "Hike",
    "trek": "Hike",
    "trekking": "Hike",
    "backpacking": "Hike",
    "trail hike": "Hike",
    # --- Skiing / Snowboarding ---
    "ski": "AlpineSki",
    "skiing": "AlpineSki",
    "alpine ski": "AlpineSki",
    "alpineski": "AlpineSki",
    "downhill ski": "AlpineSki",
    "downhill skiing": "AlpineSki",
    "backcountry ski": "BackcountrySki",
    "backcountryski": "BackcountrySki",
    "backcountry skiing": "BackcountrySki",
    "ski touring": "BackcountrySki",
    "ski mountaineering": "BackcountrySki",
    "randonee": "BackcountrySki",
    "nordic ski": "NordicSki",
    "nordicski": "NordicSki",
    "nordic skiing": "NordicSki",
    "cross country ski": "NordicSki",
    "cross country skiing": "NordicSki",
    "xc ski": "NordicSki",
    "xc skiing": "NordicSki",
    "classic ski": "NordicSki",
    "skate ski": "NordicSki",
    "roller ski": "RollerSki",
    "rollerski": "RollerSki",
    "roller skiing": "RollerSki",
    "snowboard": "Snowboard",
    "snowboarding": "Snowboard",
    "snow board": "Snowboard",
    "splitboard": "Snowboard",
    # --- Skating ---
    "ice skate": "IceSkate",
    "iceskate": "IceSkate",
    "ice skating": "IceSkate",
    "figure skating": "IceSkate",
    "inline skate": "InlineSkate",
    "inlineskate": "InlineSkate",
    "inline skating": "InlineSkate",
    "roller skate": "InlineSkate",
    "roller skating": "InlineSkate",
    "rollerblade": "InlineSkate",
    "rollerblading": "InlineSkate",
    "skateboard": "Skateboard",
    "skateboarding": "Skateboard",
    # --- Paddling / Water ---
    "canoe": "Canoe",
    "canoeing": "Canoe",
    "kayak": "Kayak",
    "kayaking": "Kayak",
    "kayak trip": "Kayak",
    "row": "Row",
    "rowing": "Row",
    "stand up paddling": "StandUpPaddling",
    "standuppaddling": "StandUpPaddling",
    "stand up paddle": "StandUpPaddling",
    "stand up paddleboard": "StandUpPaddling",
    "paddleboard": "StandUpPaddling",
    "paddleboarding": "StandUpPaddling",
    "sup": "StandUpPaddling",
    "surf": "Surf",
    "surfing": "Surf",
    "windsurf": "Windsurf",
    "windsurfing": "Windsurf",
    "kitesurf": "Kitesurf",
    "kitesurfing": "Kitesurf",
    "sail": "Sail",
    "sailing": "Sail",
    # --- Other location-based activities ---
    "wheelchair": "Wheelchair",
    "handcycle": "Handcycle",
    "handcycling": "Handcycle",
    "velomobile": "Velomobile",
    "golf": "Golf",
    "skijor": "Skijor",
    "skijoring": "Skijor",
}


def normalize_activity_type(raw) -> str:
    """Normalize an activity type string to its canonical Strava form.

    Accepts raw labels from config ACTIVITY_TYPES or CSV exports (which may use
    verbose names like "Running", "Alpine Ski" or "Cycling"). Unknown labels are
    returned stripped (case preserved) so explicitly-configured types still
    match exactly.
    """
    if raw is None:
        return ""
    key = str(raw).strip().lower()
    if key in ACTIVITY_TYPE_ALIASES:
        return ACTIVITY_TYPE_ALIASES[key]
    # Preserve unknown types so user-configured values still match exactly.
    return str(raw).strip()


class Config:
    """Configuration container loaded from config.json."""

    def __init__(self, config_path: Path):
        if not config_path.exists():
            raise FileNotFoundError("config.json file not found.")

        with open(config_path) as f:
            cfg = json.load(f)

        self.activities_dir = Path(cfg["ACTIVITIES_DIR"])
        # Normalize user-configured activity types so they match CSV values
        raw_types = cfg["ACTIVITY_TYPES"]
        self.activity_types = {normalize_activity_type(t) for t in raw_types}
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
        self.max_consecutive_same_cell = cfg["MAX_CONSECUTIVE_SAME_CELL"]
        self.decay_factor = cfg.get("DECAY_FACTOR", 0.5)

        # Configurable paths with sensible defaults (relative to project root)
        project_root = config_path.parent
        cache_dir = cfg.get("CACHE_DIR", "cache")
        output_dir = cfg.get("OUTPUT_DIR", "outputs")
        self.cache_dir = (project_root / cache_dir).resolve()
        self.output_dir = (project_root / output_dir).resolve()
        self.cache_dir.mkdir(exist_ok=True)
        self.output_dir.mkdir(exist_ok=True)

        self.activities_csv = self.activities_dir / cfg.get("ACTIVITIES_CSV", "activities.csv")
        self.cache_file = self.cache_dir / cfg.get("CACHE_FILE", "cache.pkl")
        self.output_html = self.output_dir / cfg.get("OUTPUT_HTML", "heatmap.html")

    def log_summary(self):
        import logging

        log = logging.getLogger(__name__)
        log.info(f"Source:  {self.activities_dir}/")
        log.info(f"Types:   {', '.join(self.activity_types)}")
        log.info(f"Output:  {self.output_html}")
