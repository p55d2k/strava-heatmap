"""
Unit tests for src/config.py - configuration management.
"""

import json
import tempfile
from pathlib import Path

import pytest

from src.config import Config


class TestConfig:
    """Tests for Config class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = Path(self.temp_dir) / "config.json"

        # Create a valid config.json
        self.valid_config = {
            "ACTIVITIES_DIR": self.temp_dir,
            "ACTIVITY_TYPES": ["Run", "Ride"],
            "DATE_FROM": "2024-01-01",
            "DATE_TO": "2024-12-31",
            "HOME_LAT": 45.0,
            "HOME_LON": -122.0,
            "RADIUS_KM": 50.0,
            "GPS_SPREAD_MIN_M": 100,
            "METERS_PER_PIXEL": 10.0,
            "PADDING_M": 500.0,
            "TRACK_CLIP_RADIUS_KM": 20.0,
            "BLUR_SIGMA_PX": 2.0,
            "MAP_OPACITY": 0.7,
            "SPEED_MIN_MS": None,
            "SPEED_MAX_MS": None,
            "HR_MIN_BPM": None,
            "HR_MAX_BPM": None,
            "AUTO_RANGE_PCT": 5,
            "MAX_CONSECUTIVE_SAME_CELL": 3,
        }
        self.config_path.write_text(json.dumps(self.valid_config))

    def teardown_method(self):
        """Clean up temp files."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_loads_all_config_values(self):
        """Should load all configuration values from JSON."""
        config = Config(self.config_path)

        assert config.activities_dir == Path(self.temp_dir)
        assert config.activity_types == {"Run", "Ride"}
        assert config.date_from == "2024-01-01"
        assert config.date_to == "2024-12-31"
        assert config.home_lat == 45.0
        assert config.home_lon == -122.0
        assert config.radius_km == 50.0
        assert config.gps_spread_min_m == 100
        assert config.meters_per_pixel == 10.0
        assert config.padding_m == 500.0
        assert config.track_clip_radius_km == 20.0
        assert config.blur_sigma_px == 2.0
        assert config.map_opacity == 0.7
        assert config.carto_style == "dark_all"
        assert config.speed_min_ms is None
        assert config.speed_max_ms is None
        assert config.hr_min_bpm is None
        assert config.hr_max_bpm is None
        assert config.auto_range_pct == 5
        assert config.max_consecutive_same_cell == 3
        assert config.coverage_normalization == "pct"  # default when omitted

    def test_creates_cache_and_output_dirs(self):
        """Should create cache and output directories."""
        config = Config(self.config_path)

        assert config.cache_dir.exists()
        assert config.output_dir.exists()
        assert config.cache_dir.name == "cache"
        assert config.output_dir.name == "outputs"

    def test_uses_custom_cache_and_output_dirs(self):
        """Should use custom cache/output dirs when specified in config."""
        custom_config = self.valid_config.copy()
        custom_config["CACHE_DIR"] = "my_cache"
        custom_config["OUTPUT_DIR"] = "my_outputs"
        self.config_path.write_text(json.dumps(custom_config))

        config = Config(self.config_path)

        assert config.cache_dir.name == "my_cache"
        assert config.output_dir.name == "my_outputs"

    def test_uses_custom_carto_style(self):
        """Should use the CARTO_STYLE from config when specified."""
        custom_config = self.valid_config.copy()
        custom_config["CARTO_STYLE"] = "voyager"
        self.config_path.write_text(json.dumps(custom_config))

        config = Config(self.config_path)

        assert config.carto_style == "voyager"

    def test_sets_default_activities_csv(self):
        """Should set default activities CSV path."""
        config = Config(self.config_path)

        assert config.activities_csv == Path(self.temp_dir) / "activities.csv"

    def test_uses_custom_activities_csv(self):
        """Should use custom activities CSV when specified."""
        custom_config = self.valid_config.copy()
        custom_config["ACTIVITIES_CSV"] = "my_activities.csv"
        self.config_path.write_text(json.dumps(custom_config))

        config = Config(self.config_path)

        assert config.activities_csv == Path(self.temp_dir) / "my_activities.csv"

    def test_sets_default_cache_file(self):
        """Should set default cache file path."""
        config = Config(self.config_path)

        expected = (Path(self.temp_dir) / "cache" / "cache.pkl").resolve()
        assert config.cache_file == expected

    def test_uses_custom_cache_file(self):
        """Should use custom cache file when specified."""
        custom_config = self.valid_config.copy()
        custom_config["CACHE_FILE"] = "my_cache.pkl"
        self.config_path.write_text(json.dumps(custom_config))

        config = Config(self.config_path)

        expected = (Path(self.temp_dir) / "cache" / "my_cache.pkl").resolve()
        assert config.cache_file == expected

    def test_sets_default_output_html(self):
        """Should set default output HTML path."""
        config = Config(self.config_path)

        expected = (Path(self.temp_dir) / "outputs" / "heatmap.html").resolve()
        assert config.output_html == expected

    def test_uses_custom_output_html(self):
        """Should use custom output HTML when specified."""
        custom_config = self.valid_config.copy()
        custom_config["OUTPUT_HTML"] = "my_heatmap.html"
        self.config_path.write_text(json.dumps(custom_config))

        config = Config(self.config_path)

        expected = (Path(self.temp_dir) / "outputs" / "my_heatmap.html").resolve()
        assert config.output_html == expected

    def test_sets_default_output_gpx(self):
        """Should set default GPX track export path."""
        config = Config(self.config_path)

        expected = (Path(self.temp_dir) / "outputs" / "tracks.gpx").resolve()
        assert config.output_gpx == expected

    def test_uses_custom_output_gpx(self):
        """Should use custom GPX track export path when specified."""
        custom_config = self.valid_config.copy()
        custom_config["OUTPUT_GPX"] = "my_runs.gpx"
        self.config_path.write_text(json.dumps(custom_config))

        config = Config(self.config_path)

        expected = (Path(self.temp_dir) / "outputs" / "my_runs.gpx").resolve()
        assert config.output_gpx == expected

    def test_embed_defaults(self):
        """Embed widget mode should be off, named heatmap_embed.html, and keep
        the legend, attribution and home marker while leaving tracks out."""
        config = Config(self.config_path)

        assert config.embed_enabled is False
        assert (
            config.output_embed_html
            == (Path(self.temp_dir) / "outputs" / "heatmap_embed.html").resolve()
        )
        assert config.embed_legend is True
        assert config.embed_attribution is True
        assert config.embed_home_marker is True
        assert config.embed_tracks is False

    def test_uses_configured_embed_options(self):
        """Embed widget name and content flags should follow config.json."""
        custom_config = self.valid_config.copy()
        custom_config.update(
            {
                "EMBED_ENABLED": True,
                "EMBED_HTML": "widget.html",
                "EMBED_LEGEND": False,
                "EMBED_ATTRIBUTION": False,
                "EMBED_HOME_MARKER": False,
                "EMBED_TRACKS": True,
            }
        )
        self.config_path.write_text(json.dumps(custom_config))

        config = Config(self.config_path)

        assert config.embed_enabled is True
        assert (
            config.output_embed_html == (Path(self.temp_dir) / "outputs" / "widget.html").resolve()
        )
        assert config.embed_legend is False
        assert config.embed_attribution is False
        assert config.embed_home_marker is False
        assert config.embed_tracks is True

    def test_embed_demo_path_follows_embed_html(self):
        """The demo page sits beside the widget and is named after it."""
        config = Config(self.config_path)

        assert config.embed_demo is True
        expected = (Path(self.temp_dir) / "outputs" / "heatmap_embed_demo.html").resolve()
        assert config.output_embed_demo_html == expected

    def test_embed_demo_follows_custom_embed_html_and_can_be_disabled(self):
        """A renamed widget renames its demo page; EMBED_DEMO turns it off."""
        custom_config = self.valid_config.copy()
        custom_config["EMBED_HTML"] = "widget.html"
        custom_config["EMBED_DEMO"] = False
        self.config_path.write_text(json.dumps(custom_config))

        config = Config(self.config_path)

        assert config.embed_demo is False
        expected = (Path(self.temp_dir) / "outputs" / "widget_demo.html").resolve()
        assert config.output_embed_demo_html == expected

    def test_embed_metrics_defaults_to_empty(self):
        """No metric layers travel with the widget unless they are asked for."""
        assert Config(self.config_path).embed_metrics == []

    def test_embed_metrics_accept_layer_names_and_aliases(self):
        """EMBED_METRICS entries resolve to layer names, de-duplicated."""
        custom_config = self.valid_config.copy()
        custom_config["EMBED_METRICS"] = ["pace", "Heart rate (average)", "pace"]
        self.config_path.write_text(json.dumps(custom_config))

        config = Config(self.config_path)

        assert config.embed_metrics == ["Pace (average)", "Heart rate (average)"]

    def test_embed_metrics_rejects_unknown_entry(self):
        """A typo must fail loudly instead of silently dropping a layer."""
        import pydantic

        custom_config = self.valid_config.copy()
        custom_config["EMBED_METRICS"] = ["pace", "warp-drive"]
        self.config_path.write_text(json.dumps(custom_config))

        with pytest.raises(pydantic.ValidationError, match="Unknown EMBED_METRICS entry"):
            Config(self.config_path)

    def test_raises_on_missing_config_file(self):
        """Should raise FileNotFoundError for missing config file."""
        missing_path = Path(self.temp_dir) / "missing.json"

        with pytest.raises(FileNotFoundError, match="Config file not found"):
            Config(missing_path)

    def test_raises_on_invalid_json(self):
        """Should raise JSON decode error for invalid JSON."""
        self.config_path.write_text("{ invalid json }")

        with pytest.raises(json.JSONDecodeError):
            Config(self.config_path)

    def test_missing_optional_fields_use_defaults(self):
        """A partial config should be enough to get started."""
        incomplete_config = {"ACTIVITIES_DIR": self.temp_dir}
        self.config_path.write_text(json.dumps(incomplete_config))

        config = Config(self.config_path)
        assert config.activity_types == {"Run"}
        assert config.meters_per_pixel is None

    def test_log_summary_runs_without_error(self):
        """log_summary should run without error."""
        config = Config(self.config_path)

        # Should not raise
        config.log_summary()

    def test_activity_types_converted_to_set(self):
        """ACTIVITY_TYPES should be converted to a set."""
        config = Config(self.config_path)

        assert isinstance(config.activity_types, set)
        assert config.activity_types == {"Run", "Ride"}

    def test_activity_types_normalized_from_aliases(self):
        """ACTIVITY_TYPES should be normalized from verbose aliases."""
        alias_config = self.valid_config.copy()
        alias_config["ACTIVITY_TYPES"] = ["Running", "Cycling", "Bike"]
        self.config_path.write_text(json.dumps(alias_config))

        config = Config(self.config_path)

        # All aliases normalize to canonical Ride/Run
        assert config.activity_types == {"Run", "Ride"}

    def test_handles_none_values_for_optional_ranges(self):
        """Should handle None values for optional min/max ranges."""
        config = Config(self.config_path)

        assert config.speed_min_ms is None
        assert config.speed_max_ms is None
        assert config.hr_min_bpm is None
        assert config.hr_max_bpm is None

    def test_handles_numeric_values_for_optional_ranges(self):
        """Should handle numeric values for optional min/max ranges."""
        custom_config = self.valid_config.copy()
        custom_config["SPEED_MIN_MS"] = 2.0
        custom_config["SPEED_MAX_MS"] = 8.0
        custom_config["HR_MIN_BPM"] = 100
        custom_config["HR_MAX_BPM"] = 200
        self.config_path.write_text(json.dumps(custom_config))

        config = Config(self.config_path)

        assert config.speed_min_ms == 2.0
        assert config.speed_max_ms == 8.0
        assert config.hr_min_bpm == 100
        assert config.hr_max_bpm == 200
