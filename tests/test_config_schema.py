"""
Unit tests for src/config_schema.py - JSON Schema generation.
"""

import tempfile
from pathlib import Path

import pytest

from src.config_schema import ConfigModel, generate_json_schema


class TestConfigSchema:
    """Tests for JSON Schema generation from Pydantic model."""

    def test_generate_json_schema_returns_dict(self):
        """Should return a dictionary with schema properties."""
        schema = generate_json_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema
        assert "required" in schema

    def test_schema_has_required_fields(self):
        """Schema should require ACTIVITIES_DIR and ACTIVITY_TYPES (using aliases)."""
        schema = generate_json_schema()
        assert "ACTIVITIES_DIR" in schema["required"]
        assert "ACTIVITY_TYPES" in schema["required"]

    def test_schema_has_all_config_fields(self):
        """Schema should include all config fields using UPPERCASE aliases."""
        schema = generate_json_schema()
        expected_fields = {
            "ACTIVITIES_DIR",
            "ACTIVITY_TYPES",
            "DATE_FROM",
            "DATE_TO",
            "HOME_LAT",
            "HOME_LON",
            "RADIUS_KM",
            "GPS_SPREAD_MIN_M",
            "METERS_PER_PIXEL",
            "PADDING_M",
            "TRACK_CLIP_RADIUS_KM",
            "BLUR_SIGMA_PX",
            "MAP_OPACITY",
            "CARTO_STYLE",
            "SPEED_MIN_MS",
            "SPEED_MAX_MS",
            "HR_MIN_BPM",
            "HR_MAX_BPM",
            "AUTO_RANGE_PCT",
            "MAX_CONSECUTIVE_SAME_CELL",
            "DECAY_FACTOR",
            "RASTER_MODE",
            "COVERAGE_NORMALIZATION",
            "CACHE_DIR",
            "OUTPUT_DIR",
            "ACTIVITIES_CSV",
            "CACHE_FILE",
            "OUTPUT_HTML",
            "OUTPUT_GPX",
            "EMBED_ENABLED",
            "EMBED_HTML",
            "EMBED_LEGEND",
            "EMBED_ATTRIBUTION",
            "EMBED_HOME_MARKER",
            "EMBED_TRACKS",
            "EMBED_METRICS",
            "EMBED_DEMO",
        }
        assert expected_fields.issubset(set(schema["properties"].keys()))

    def test_metric_aliases_match_map_builder_layer_names(self):
        """The schema's metric aliases must resolve to the map builder's metric
        layer names, so a widget layer request can never name a layer that does
        not exist in the generated overlay list."""
        from src.config_schema import METRIC_LAYER_ALIASES
        from src.map_builder.constants import METRIC_LAYER_NAMES

        assert set(METRIC_LAYER_ALIASES.values()) == set(METRIC_LAYER_NAMES)

    def test_config_model_validates_example_config(self):
        """Should validate the example config.json files."""
        # Create a temporary directory for the activities directory
        with tempfile.TemporaryDirectory() as tmpdir:
            activities_dir = Path(tmpdir) / "strava_export"
            activities_dir.mkdir()

            # Test the main config
            config_data = {
                "ACTIVITIES_DIR": str(activities_dir),
                "ACTIVITY_TYPES": ["Run"],
                "DATE_FROM": None,
                "DATE_TO": None,
                "HOME_LAT": None,
                "HOME_LON": None,
                "RADIUS_KM": 20.0,
                "GPS_SPREAD_MIN_M": 200,
                "METERS_PER_PIXEL": 3,
                "PADDING_M": 500,
                "TRACK_CLIP_RADIUS_KM": 50.0,
                "BLUR_SIGMA_PX": 2,
                "MAP_OPACITY": 0.85,
                "SPEED_MIN_MS": None,
                "SPEED_MAX_MS": None,
                "HR_MIN_BPM": None,
                "HR_MAX_BPM": None,
                "AUTO_RANGE_PCT": 5,
                "MAX_CONSECUTIVE_SAME_CELL": 3,
                "DECAY_FACTOR": 0.5,
            }

            # ConfigModel uses aliases to match config.json keys
            model = ConfigModel(**config_data)
            assert model.activities_dir == str(activities_dir)
            assert model.activity_types == ["Run"]
            assert model.decay_factor == 0.5

    def test_schema_validates_valid_config(self):
        """Schema should validate against valid config data using UPPERCASE keys."""
        import jsonschema  # type: ignore

        with tempfile.TemporaryDirectory() as tmpdir:
            activities_dir = Path(tmpdir) / "strava_export"
            activities_dir.mkdir()

            schema = generate_json_schema()
            valid_config = {
                "ACTIVITIES_DIR": str(activities_dir),
                "ACTIVITY_TYPES": ["Run"],
                "RADIUS_KM": 20.0,
            }
            jsonschema.validate(valid_config, schema)

    def test_schema_rejects_missing_required(self):
        """Schema should reject config missing required fields."""
        import jsonschema  # type: ignore

        schema = generate_json_schema()
        invalid_config = {"ACTIVITY_TYPES": ["Run"]}  # missing ACTIVITIES_DIR
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_config, schema)

    def test_schema_rejects_invalid_carto_style(self):
        """Schema should reject CARTO_STYLE values outside the allowed set."""
        import jsonschema  # type: ignore

        with tempfile.TemporaryDirectory() as tmpdir:
            activities_dir = Path(tmpdir) / "strava_export"
            activities_dir.mkdir()

            schema = generate_json_schema()
            invalid_config = {
                "ACTIVITIES_DIR": str(activities_dir),
                "ACTIVITY_TYPES": ["Run"],
                "CARTO_STYLE": "rainbow",
            }
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(invalid_config, schema)

    def test_config_model_accepts_valid_carto_styles(self):
        """ConfigModel should accept all valid CARTO_STYLE values."""
        from src.config_schema import ConfigModel

        def build_config(style):
            with tempfile.TemporaryDirectory() as tmpdir:
                activities_dir = Path(tmpdir) / "strava_export"
                activities_dir.mkdir()
                return ConfigModel(
                    ACTIVITIES_DIR=str(activities_dir),
                    ACTIVITY_TYPES=["Run"],
                    CARTO_STYLE=style,
                ).carto_style

        for style in ("voyager", "light_all", "dark_all"):
            assert build_config(style) == style

    def test_config_model_rejects_invalid_carto_style(self):
        """ConfigModel should reject unsupported CARTO_STYLE values."""
        from pydantic import ValidationError

        from src.config_schema import ConfigModel

        with tempfile.TemporaryDirectory() as tmpdir:
            activities_dir = Path(tmpdir) / "strava_export"
            activities_dir.mkdir()
            with pytest.raises(ValidationError):
                ConfigModel(
                    ACTIVITIES_DIR=str(activities_dir),
                    ACTIVITY_TYPES=["Run"],
                    CARTO_STYLE="rainbow",
                )

    def test_config_model_rejects_invalid_raster_mode(self):
        """ConfigModel should reject RASTER_MODE values outside the allowed set."""
        from pydantic import ValidationError

        from src.config_schema import ConfigModel

        with tempfile.TemporaryDirectory() as tmpdir:
            activities_dir = Path(tmpdir) / "strava_export"
            activities_dir.mkdir()
            with pytest.raises(ValidationError):
                ConfigModel(
                    ACTIVITIES_DIR=str(activities_dir),
                    ACTIVITY_TYPES=["Run"],
                    RASTER_MODE="bogus",
                )

    def test_raster_mode_defaults_to_decay(self):
        """ConfigModel should default RASTER_MODE to 'decay' (current behavior)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            activities_dir = Path(tmpdir) / "strava_export"
            activities_dir.mkdir()
            model = ConfigModel(
                ACTIVITIES_DIR=str(activities_dir),
                ACTIVITY_TYPES=["Run"],
            )
        assert model.raster_mode == "decay"

    def test_config_model_accepts_all_raster_modes(self):
        """ConfigModel should accept all three raster modes."""
        from src.config_schema import ConfigModel

        def build_config(mode):
            with tempfile.TemporaryDirectory() as tmpdir:
                activities_dir = Path(tmpdir) / "strava_export"
                activities_dir.mkdir()
                return ConfigModel(
                    ACTIVITIES_DIR=str(activities_dir),
                    ACTIVITY_TYPES=["Run"],
                    RASTER_MODE=mode,
                ).raster_mode

        for mode in ("raw-count", "decay", "binary-per-activity"):
            assert build_config(mode) == mode

    def test_carto_style_defaults_to_dark_all(self):
        """ConfigModel should default CARTO_STYLE to dark_all."""
        from src.config_schema import ConfigModel

        with tempfile.TemporaryDirectory() as tmpdir:
            activities_dir = Path(tmpdir) / "strava_export"
            activities_dir.mkdir()
            model = ConfigModel(
                ACTIVITIES_DIR=str(activities_dir),
                ACTIVITY_TYPES=["Run"],
            )
            assert model.carto_style == "dark_all"
