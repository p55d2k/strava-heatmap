"""
Unit tests for src/config_schema.py - JSON Schema generation.
"""

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
            "SPEED_MIN_MS",
            "SPEED_MAX_MS",
            "HR_MIN_BPM",
            "HR_MAX_BPM",
            "AUTO_RANGE_PCT",
            "MAX_CONSECUTIVE_SAME_CELL",
            "DECAY_FACTOR",
            "CACHE_DIR",
            "OUTPUT_DIR",
            "ACTIVITIES_CSV",
            "CACHE_FILE",
            "OUTPUT_HTML",
        }
        assert expected_fields.issubset(set(schema["properties"].keys()))

    def test_config_model_validates_example_config(self):
        """Should validate the example config.json files."""
        # Test the main config
        config_data = {
            "ACTIVITIES_DIR": "strava_export",
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
        assert model.activities_dir == "strava_export"
        assert model.activity_types == ["Run"]
        assert model.decay_factor == 0.5

    def test_schema_validates_valid_config(self):
        """Schema should validate against valid config data using UPPERCASE keys."""
        import jsonschema  # type: ignore

        schema = generate_json_schema()
        valid_config = {
            "ACTIVITIES_DIR": "strava_export",
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
