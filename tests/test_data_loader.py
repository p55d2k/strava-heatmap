"""
Unit tests for src/data_loader.py - data loading and filtering functions.
"""

import pickle
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from src.config import Config
from src.data_loader import (
    determine_home_location,
    filter_by_home_radius,
    load_and_filter_activities,
    load_tracks,
)


class TestLoadAndFilterActivities:
    """Tests for load_and_filter_activities function."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.activities_dir = Path(self.temp_dir)
        self.activities_csv = self.activities_dir / "activities.csv"
        self.cache_dir = Path(self.temp_dir) / "cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_path = self.cache_dir / "cache.pkl"

        # Create sample activities CSV
        self.sample_csv = """Filename,Activity Type,Activity Date,Activity Name
2024-01-01-12345.fit.gz,Run,01/01/2024,Morning Run
2024-01-02-12346.fit.gz,Ride,02/01/2024,Evening Ride
2024-01-03-12347.fit.gz,Run,03/01/2024,Long Run
2024-01-04-12348.fit.gz,Swim,04/01/2024,Pool Swim
"""
        self.activities_csv.write_text(self.sample_csv)

        # Create mock config
        self.config = MagicMock(spec=Config)
        self.config.activities_dir = self.activities_dir
        self.config.activity_types = {"Run", "Ride"}
        self.config.date_from = "2024-01-01"
        self.config.date_to = "2024-01-03"
        self.config.gps_spread_min_m = 100
        self.config.activities_csv = self.activities_csv
        self.config.cache_file = self.cache_path

    def teardown_method(self):
        """Clean up temp files."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("src.data_loader.get_gps_start")
    def test_loads_and_filters_by_type_and_date(self, mock_get_gps):
        """Should load CSV and filter by activity type and date range."""
        mock_get_gps.return_value = (45.0, -122.0, 500.0)

        df = load_and_filter_activities(self.config)

        # Should have 3 activities (Run, Ride, Run) - Swim filtered out
        # And date filter removes 2024-01-04
        assert len(df) == 3
        assert all(df["Activity Type"].isin(["Run", "Ride"]))
        assert all(df["Activity Date"] >= pd.Timestamp("2024-01-01"))
        assert all(df["Activity Date"] <= pd.Timestamp("2024-01-03"))

    @patch("src.data_loader.get_gps_start")
    def test_normalizes_verbose_csv_activity_types(self, mock_get_gps):
        """Should normalize verbose CSV activity types (Running, Cycling, etc.)."""
        # CSV uses verbose labels; config uses canonical types
        verbose_csv = """Filename,Activity Type,Activity Date,Activity Name
2024-01-01-12345.fit.gz,Running,01/01/2024,Morning Run
2024-01-02-12346.fit.gz,Cycling,02/01/2024,Evening Ride
2024-01-03-12347.fit.gz,Bike,03/01/2024,Commute
2024-01-04-12348.fit.gz,Swimming,04/01/2024,Pool Swim
"""
        self.activities_csv.write_text(verbose_csv)
        self.config.activity_types = {"Run", "Ride"}
        mock_get_gps.return_value = (45.0, -122.0, 500.0)

        df = load_and_filter_activities(self.config)

        # Running->Run, Cycling->Ride, Bike->Ride match; Swimming filtered out
        assert len(df) == 3
        assert all(df["Activity Type"].isin(["Run", "Ride"]))
        assert "Run" in df["Activity Type"].values
        assert "Ride" in df["Activity Type"].values
        assert "Swim" not in df["Activity Type"].values

    @patch("src.data_loader.get_gps_start")
    def test_config_accepts_alias_activity_types(self, mock_get_gps):
        """Config ACTIVITY_TYPES can use aliases (e.g. Running, Cycling)."""
        # Config uses normalized canonical types (as Config.__init__ would normalize them)
        self.config.activity_types = {"Run", "Ride"}  # normalized from "Running", "Cycling"
        mock_get_gps.return_value = (45.0, -122.0, 500.0)

        df = load_and_filter_activities(self.config)

        # All three (Run, Ride, Run) should match the canonical types
        assert len(df) == 3
        assert all(df["Activity Type"].isin(["Run", "Ride"]))

    @patch("src.data_loader.get_gps_start")
    def test_filters_by_gps_spread(self, mock_get_gps):
        """Should filter out activities with insufficient GPS spread."""
        mock_get_gps.side_effect = [
            (45.0, -122.0, 500.0),  # Good spread
            (45.0, -122.0, 50.0),  # Too small spread
            (45.0, -122.0, 1000.0),  # Good spread
        ]

        df = load_and_filter_activities(self.config)

        # Only 2 activities should pass GPS spread filter
        assert len(df) == 2
        assert all(df["gps_spread_m"] >= 100)

    @patch("src.data_loader.get_gps_start")
    def test_uses_gps_cache(self, mock_get_gps):
        """Should use cached GPS data when available."""
        # Pre-populate cache
        cache_data = {
            "gps": {
                "2024-01-01-12345.fit.gz": [45.0, -122.0, 500.0],
                "2024-01-02-12346.fit.gz": [45.0, -122.0, 500.0],
            },
            "tracks": {},
        }
        with open(self.cache_path, "wb") as f:
            pickle.dump(cache_data, f)

        mock_get_gps.return_value = (45.0, -122.0, 500.0)

        load_and_filter_activities(self.config)

        # Should only call get_gps_start for uncached files
        assert mock_get_gps.call_count == 1  # Only for 2024-01-03 file

    @patch("src.data_loader.get_gps_start")
    def test_updates_gps_cache(self, mock_get_gps):
        """Should update GPS cache with new entries."""
        mock_get_gps.return_value = (45.0, -122.0, 500.0)

        load_and_filter_activities(self.config)

        # Cache should be updated
        assert self.cache_path.exists()
        with open(self.cache_path, "rb") as f:
            cache = pickle.load(f)
        assert "2024-01-01-12345.fit.gz" in cache["gps"]
        assert "2024-01-02-12346.fit.gz" in cache["gps"]
        assert "2024-01-03-12347.fit.gz" in cache["gps"]


class TestDetermineHomeLocation:
    """Tests for determine_home_location function."""

    def test_uses_manual_home_when_provided(self):
        """Should use manual home coordinates when provided in config."""
        config = MagicMock()
        config.home_lat = 45.0
        config.home_lon = -122.0

        runs = pd.DataFrame(
            {
                "start_lat": [45.0, 45.1, 45.2],
                "start_lon": [-122.0, -122.1, -122.2],
            }
        )

        home_lat, home_lon = determine_home_location(config, runs)

        assert home_lat == 45.0
        assert home_lon == -122.0

    @patch("src.data_loader.detect_home")
    def test_auto_detects_when_manual_not_provided(self, mock_detect):
        """Should auto-detect home when manual coordinates not provided."""
        config = MagicMock()
        config.home_lat = None
        config.home_lon = None

        mock_detect.return_value = (45.5, -122.5, 10)

        runs = pd.DataFrame(
            {
                "start_lat": [45.0, 45.1, 45.2],
                "start_lon": [-122.0, -122.1, -122.2],
            }
        )

        home_lat, home_lon = determine_home_location(config, runs)

        assert home_lat == 45.5
        assert home_lon == -122.5
        mock_detect.assert_called_once_with(runs)


class TestFilterByHomeRadius:
    """Tests for filter_by_home_radius function."""

    def test_filters_by_distance(self):
        """Should filter activities by distance from home."""
        runs = pd.DataFrame(
            {
                "start_lat": [45.0, 45.1, 46.0],  # ~0km, ~11km, ~111km
                "start_lon": [-122.0, -122.0, -122.0],
            }
        )

        filtered = filter_by_home_radius(runs, 45.0, -122.0, 20.0)

        # Only first two should be within 20km
        assert len(filtered) == 2
        assert all(filtered["dist_from_home_km"] <= 20.0)

    def test_preserves_other_columns(self):
        """Should preserve all original columns plus add distance."""
        runs = pd.DataFrame(
            {
                "Filename": ["a.fit.gz", "b.fit.gz"],
                "Activity Type": ["Run", "Ride"],
                "start_lat": [45.0, 45.1],
                "start_lon": [-122.0, -122.0],
            }
        )

        filtered = filter_by_home_radius(runs, 45.0, -122.0, 20.0)

        assert "Filename" in filtered.columns
        assert "Activity Type" in filtered.columns
        assert "dist_from_home_km" in filtered.columns


class TestLoadTracks:
    """Tests for load_tracks function."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.activities_dir = Path(self.temp_dir)
        self.cache_dir = Path(self.temp_dir) / "cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_path = self.cache_dir / "cache.pkl"

        self.config = MagicMock()
        self.config.activities_dir = self.activities_dir
        self.config.cache_file = self.cache_path

    def teardown_method(self):
        """Clean up temp files."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("src.data_loader.parse_track_file")
    def test_loads_tracks_from_fit_files(self, mock_load_fit):
        """Should load tracks from .fit.gz files."""
        mock_load_fit.return_value = [
            [45.0, -122.0, 5.0, 150, 100.0],
            [45.001, -122.001, 5.0, 150, 101.0],
        ]

        runs = pd.DataFrame(
            {
                "Filename": ["2024-01-01-12345.fit.gz"],
                "Activity Date": [pd.Timestamp("2024-01-01")],
                "Activity Name": ["Morning Run"],
            }
        )

        tracks = load_tracks(self.config, runs)

        assert len(tracks) == 1
        label, pts = tracks[0]
        assert "2024-01-01" in label
        assert "Morning Run" in label
        assert len(pts) == 2

    @patch("src.data_loader.parse_track_file")
    def test_uses_track_cache(self, mock_load_fit):
        """Should use cached tracks when available."""
        # Pre-populate cache
        cache_data = {
            "gps": {},
            "tracks": {
                "2024-01-01-12345.fit.gz": [
                    [45.0, -122.0, 5.0, 150, 100.0],
                ],
            },
        }
        with open(self.cache_path, "wb") as f:
            pickle.dump(cache_data, f)

        runs = pd.DataFrame(
            {
                "Filename": ["2024-01-01-12345.fit.gz"],
                "Activity Date": [pd.Timestamp("2024-01-01")],
                "Activity Name": ["Morning Run"],
            }
        )

        tracks = load_tracks(self.config, runs)

        # Should not call parse_track_file for cached file
        mock_load_fit.assert_not_called()
        assert len(tracks) == 1

    @patch("src.data_loader.parse_track_file")
    def test_skips_empty_tracks(self, mock_load_fit):
        """Should skip tracks with no GPS points."""
        mock_load_fit.return_value = []

        runs = pd.DataFrame(
            {
                "Filename": ["2024-01-01-12345.fit.gz"],
                "Activity Date": [pd.Timestamp("2024-01-01")],
                "Activity Name": ["Morning Run"],
            }
        )

        tracks = load_tracks(self.config, runs)

        assert len(tracks) == 0

    @patch("src.data_loader.parse_track_file")
    def test_updates_track_cache(self, mock_load_fit):
        """Should update track cache with new tracks."""
        mock_load_fit.return_value = [
            [45.0, -122.0, 5.0, 150, 100.0],
        ]

        runs = pd.DataFrame(
            {
                "Filename": ["2024-01-01-12345.fit.gz"],
                "Activity Date": [pd.Timestamp("2024-01-01")],
                "Activity Name": ["Morning Run"],
            }
        )

        load_tracks(self.config, runs)

        # Cache should be updated
        assert self.cache_path.exists()
        with open(self.cache_path, "rb") as f:
            cache = pickle.load(f)
        assert "2024-01-01-12345.fit.gz" in cache["tracks"]

    @patch("src.data_loader.parse_track_file")
    def test_clears_stale_cache_entries(self, mock_load_fit):
        """Should clear stale cache entries (missing altitude)."""
        # Cache with stale entry (only 4 values per point, missing altitude)
        cache_data = {
            "gps": {},
            "tracks": {
                "stale.fit.gz": [[45.0, -122.0, 5.0, 150]],  # Only 4 values
                "fresh.fit.gz": [[45.0, -122.0, 5.0, 150, 100.0]],  # 5 values
            },
        }
        with open(self.cache_path, "wb") as f:
            pickle.dump(cache_data, f)

        mock_load_fit.return_value = [
            [45.0, -122.0, 5.0, 150, 100.0],
        ]

        runs = pd.DataFrame(
            {
                "Filename": ["fresh.fit.gz"],
                "Activity Date": [pd.Timestamp("2024-01-01")],
                "Activity Name": ["Morning Run"],
            }
        )

        load_tracks(self.config, runs)

        # Stale entry should be removed
        with open(self.cache_path, "rb") as f:
            cache = pickle.load(f)
        assert "stale.fit.gz" not in cache["tracks"]
        assert "fresh.fit.gz" in cache["tracks"]
