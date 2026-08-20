"""
JSON Schema generation for config.json using Pydantic.

This module defines Pydantic models that match the configuration structure
and provides a function to generate the JSON Schema.
"""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    def normalize_activity_types(cls, v: list[str]) -> list[str]:
        """Normalize activity types using the alias mapping."""
        # We'll apply the normalization logic from config.py
        # This is a simplified version - the actual normalization happens at runtime
        return v


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
