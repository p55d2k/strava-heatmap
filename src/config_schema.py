"""
JSON Schema generation for config.json using Pydantic.

This module defines Pydantic models that match the configuration structure
and provides a function to generate the JSON Schema.
"""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    "rollerblade": "InlineSkate",
    "rollerblading": "InlineSkate",
    "skate": "InlineSkate",
    # --- Water Sports ---
    "kayak": "Kayaking",
    "kayaking": "Kayaking",
    "canoe": "Canoeing",
    "canoeing": "Canoeing",
    "stand up paddle": "StandUpPaddling",
    "stand up paddling": "StandUpPaddling",
    "sup": "StandUpPaddling",
    "paddle board": "StandUpPaddling",
    "paddle boarding": "StandUpPaddling",
    "surf": "Surfing",
    "surfing": "Surfing",
    "windsurf": "Windsurf",
    "windsurfing": "Windsurf",
    "kitesurf": "Kitesurf",
    "kitesurfing": "Kitesurf",
    "kiteboard": "Kitesurf",
    "kiteboarding": "Kitesurf",
    "row": "Rowing",
    "rowing": "Rowing",
    "sail": "Sailing",
    "sailing": "Sailing",
    # --- Other ---
    "workout": "Workout",
    "strength training": "Workout",
    "crossfit": "Workout",
    "yoga": "Yoga",
    "pilates": "Workout",
    "stretch": "Workout",
    "stretching": "Workout",
    "core": "Workout",
    "weight training": "Workout",
    "weightlifting": "Workout",
    "hiit": "Workout",
    "circuit training": "Workout",
    "elliptical": "Elliptical",
    "stair stepper": "StairStepper",
    "stair climbing": "StairStepper",
    "wheelchair": "Wheelchair",
    "handcycle": "Handcycle",
}


def normalize_activity_type(raw: str | None) -> str:
    """
    Map a raw activity type string to its canonical Strava type.

    Parameters
    ----------
    raw
        User-supplied or CSV value such as "Running", "bike", "Alpine Ski".
        Case-insensitive; surrounding whitespace is ignored.

    Returns
    -------
    str
        Canonical Strava activity type if the normalized key exists in
        ACTIVITY_TYPE_ALIASES; otherwise the original string is returned so
        unknown values still match exactly.
    """
    if raw is None:
        return ""
    key = str(raw).strip().lower()
    if key in ACTIVITY_TYPE_ALIASES:
        return ACTIVITY_TYPE_ALIASES[key]
    # Preserve unknown types so user-configured values still match exactly.
    return str(raw).strip()


class ConfigModel(BaseModel):
    """Pydantic model for Strava Heatmap configuration.

    Uses alias mapping to accept the UPPERCASE keys from config.json
    and populate the snake_case model fields.
    """

    model_config = ConfigDict(populate_by_name=True)

    # Required fields
    activities_dir: str = Field(
        ...,
        alias="ACTIVITIES_DIR",
        description="Path to the directory containing your Strava export data (activities.csv and .fit.gz/.gpx files)",
        examples=["strava_export"],
    )
    activity_types: list[str] = Field(
        ...,
        alias="ACTIVITY_TYPES",
        min_length=1,
        description="List of activity types to include in the heatmap. Can use canonical types (Run, Ride, Swim, etc.) or common aliases (Running, Cycling, Bike, etc.)",
        examples=[["Run"], ["Run", "Ride", "Swim"]],
    )

    # Optional date filters (ISO format YYYY-MM-DD or null)
    date_from: str | None = Field(
        default=None,
        alias="DATE_FROM",
        description="Start date for filtering activities (YYYY-MM-DD). Use null for no start limit.",
        examples=["2024-01-01", None],
    )
    date_to: str | None = Field(
        default=None,
        alias="DATE_TO",
        description="End date for filtering activities (YYYY-MM-DD). Use null for no end limit.",
        examples=["2024-12-31", None],
    )

    # Optional home location for radius filtering
    home_lat: float | None = Field(
        default=None,
        alias="HOME_LAT",
        description="Home latitude for radius filtering. Use null to disable radius filtering.",
        examples=[45.0, None],
    )
    home_lon: float | None = Field(
        default=None,
        alias="HOME_LON",
        description="Home longitude for radius filtering. Use null to disable radius filtering.",
        examples=[-122.0, None],
    )
    radius_km: float = Field(
        default=20.0,
        alias="RADIUS_KM",
        ge=0,
        description="Radius in kilometers around home location to include activities. Only used if HOME_LAT and HOME_LON are set.",
        examples=[20.0, 50.0],
    )

    # GPS processing parameters
    gps_spread_min_m: float = Field(
        default=200,
        alias="GPS_SPREAD_MIN_M",
        ge=0,
        description="Minimum GPS spread in meters. Activities with less spread are treated as stationary.",
        examples=[200, 100],
    )
    meters_per_pixel: float = Field(
        default=3,
        alias="METERS_PER_PIXEL",
        gt=0,
        description="Ground resolution in meters per pixel for the heatmap raster.",
        examples=[3, 10],
    )
    padding_m: float = Field(
        default=500,
        alias="PADDING_M",
        ge=0,
        description="Padding in meters around the activity bounds for the heatmap extent.",
        examples=[500, 1000],
    )
    track_clip_radius_km: float = Field(
        default=50.0,
        alias="TRACK_CLIP_RADIUS_KM",
        ge=0,
        description="Maximum distance in km from home to clip tracks. Tracks beyond this are clipped.",
        examples=[50.0, 100.0],
    )

    # Visual parameters
    blur_sigma_px: float = Field(
        default=2,
        alias="BLUR_SIGMA_PX",
        ge=0,
        description="Gaussian blur sigma in pixels for smoothing the heatmap.",
        examples=[2, 3],
    )
    map_opacity: float = Field(
        default=0.85,
        alias="MAP_OPACITY",
        ge=0,
        le=1,
        description="Opacity of the heatmap overlay (0.0 to 1.0).",
        examples=[0.85, 0.7],
    )

    # Optional filters
    speed_min_ms: float | None = Field(
        default=None,
        alias="SPEED_MIN_MS",
        ge=0,
        description="Minimum speed in m/s to include GPS points. Use null for no minimum.",
        examples=[2.0, None],
    )
    speed_max_ms: float | None = Field(
        default=None,
        alias="SPEED_MAX_MS",
        ge=0,
        description="Maximum speed in m/s to include GPS points. Use null for no maximum.",
        examples=[8.0, None],
    )
    hr_min_bpm: int | None = Field(
        default=None,
        alias="HR_MIN_BPM",
        ge=0,
        le=300,
        description="Minimum heart rate in BPM to include GPS points. Use null for no minimum.",
        examples=[100, None],
    )
    hr_max_bpm: int | None = Field(
        default=None,
        alias="HR_MAX_BPM",
        ge=0,
        le=300,
        description="Maximum heart rate in BPM to include GPS points. Use null for no maximum.",
        examples=[200, None],
    )
    auto_range_pct: int = Field(
        default=5,
        alias="AUTO_RANGE_PCT",
        ge=0,
        le=100,
        description="Percentile for auto-ranging color scale (0-100). Lower values increase contrast.",
        examples=[5, 10],
    )
    max_consecutive_same_cell: int = Field(
        default=3,
        alias="MAX_CONSECUTIVE_SAME_CELL",
        ge=1,
        description="Maximum consecutive GPS points in the same raster cell before skipping.",
        examples=[3, 5],
    )
    decay_factor: float = Field(
        default=0.5,
        alias="DECAY_FACTOR",
        ge=0,
        le=1,
        description="Decay factor for temporal fading of older activities (0.0 to 1.0).",
        examples=[0.5, 0.3],
    )

    # Optional path overrides (relative to project root)
    cache_dir: str = Field(
        default="cache",
        alias="CACHE_DIR",
        description="Directory for cached data (relative to project root).",
        examples=["cache", "my_cache"],
    )
    output_dir: str = Field(
        default="outputs",
        alias="OUTPUT_DIR",
        description="Directory for output files (relative to project root).",
        examples=["outputs", "my_outputs"],
    )
    activities_csv: str = Field(
        default="activities.csv",
        alias="ACTIVITIES_CSV",
        description="Name of the activities CSV file in ACTIVITIES_DIR.",
        examples=["activities.csv"],
    )
    cache_file: str = Field(
        default="cache.pkl",
        alias="CACHE_FILE",
        description="Name of the cache file in CACHE_DIR.",
        examples=["cache.pkl"],
    )
    output_html: str = Field(
        default="heatmap.html",
        alias="OUTPUT_HTML",
        description="Name of the output HTML file in OUTPUT_DIR.",
        examples=["heatmap.html", "my_heatmap.html"],
    )

    @field_validator("activity_types", mode="before")
    @classmethod
    def normalize_activity_types_input(cls, v: list[str]) -> list[str]:
        """Normalize activity types using the alias mapping at input time."""
        return [normalize_activity_type(t) for t in v]

    @model_validator(mode="after")
    def validate_paths_and_create_dirs(self) -> "ConfigModel":
        """Validate paths exist and create cache/output directories."""
        # Validate ACTIVITIES_DIR exists
        activities_dir = Path(self.activities_dir)
        if not activities_dir.exists():
            raise FileNotFoundError(
                f"Activities directory not found: {activities_dir}\n"
                f"  → Check ACTIVITIES_DIR in config.json points to your Strava export folder\n"
                f"  → The folder should contain activities.csv and .fit.gz/.gpx files"
            )
        if not activities_dir.is_dir():
            raise NotADirectoryError(
                f"ACTIVITIES_DIR is not a directory: {activities_dir}\n"
                f"  → Please point to a folder containing your Strava export"
            )

        # Configurable paths with sensible defaults (relative to project root)
        # We need to find the project root - use the config file location if available,
        # otherwise use current working directory
        project_root = Path.cwd()
        cache_dir = Path(self.cache_dir)
        output_dir = Path(self.output_dir)

        # Resolve relative to project root
        if not cache_dir.is_absolute():
            cache_dir = (project_root / cache_dir).resolve()
        if not output_dir.is_absolute():
            output_dir = (project_root / output_dir).resolve()

        # Store resolved paths as strings (will be converted to Path in Config wrapper)
        self.cache_dir = str(cache_dir)
        self.output_dir = str(output_dir)

        # Create directories
        cache_dir.mkdir(exist_ok=True)
        output_dir.mkdir(exist_ok=True)

        return self


def generate_json_schema(output_path: Path | None = None) -> dict[str, Any]:
    """
    Generate JSON Schema from the Pydantic model.

    Args:
        output_path: Optional path to write the schema to a file.

    Returns:
        The JSON Schema as a dictionary.
    """
    schema = ConfigModel.model_json_schema()

    # Add some metadata
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Strava Heatmap Configuration"
    schema["description"] = "Configuration for Strava Activity Heatmap Generator"
    schema["type"] = "object"

    if output_path:
        import json

        output_path.write_text(json.dumps(schema, indent=2))

    return schema


if __name__ == "__main__":
    # Generate schema when run directly
    project_root = Path(__file__).parent.parent
    schema_path = project_root / "config.schema.json"
    generate_json_schema(schema_path)
    print(f"JSON Schema written to {schema_path}")
