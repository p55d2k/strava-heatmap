"""
Pytest configuration and shared fixtures for strava-heatmap tests.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_activities_csv(temp_dir):
    """Create a sample activities.csv file."""
    csv_path = temp_dir / "activities.csv"
    content = """Filename,Activity Type,Activity Date,Activity Name
2024-01-01-12345.fit.gz,Run,01/01/2024,Morning Run
2024-01-02-12346.fit.gz,Ride,02/01/2024,Evening Ride
2024-01-03-12347.fit.gz,Run,03/01/2024,Long Run
2024-01-04-12348.fit.gz,Swim,04/01/2024,Pool Swim
"""
    csv_path.write_text(content)
    return csv_path


@pytest.fixture
def sample_config_dict(temp_dir):
    """Return a valid config dictionary."""
    return {
        "ACTIVITIES_DIR": str(temp_dir),
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
    }


@pytest.fixture
def config_path(temp_dir, sample_config_dict):
    """Create a config.json file and return its path."""
    import json

    config_path = temp_dir / "config.json"
    config_path.write_text(json.dumps(sample_config_dict))
    return config_path


@pytest.fixture
def mock_config(config_path):
    """Create a Config instance for testing."""
    from src.config import Config

    return Config(config_path)


@pytest.fixture
def sample_runs_df():
    """Create a sample runs DataFrame."""
    return pd.DataFrame(
        {
            "Filename": ["2024-01-01-12345.fit.gz", "2024-01-02-12346.fit.gz"],
            "Activity Type": ["Run", "Ride"],
            "Activity Date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "Activity Name": ["Morning Run", "Evening Ride"],
            "start_lat": [45.0, 45.1],
            "start_lon": [-122.0, -122.1],
            "gps_spread_m": [500.0, 1000.0],
        }
    )


@pytest.fixture
def sample_tracks():
    """Create sample track data."""
    return [
        (
            "2024-01-01 Morning Run",
            [
                [45.0, -122.0, 5.0, 150, 100.0],
                [45.001, -122.001, 5.0, 150, 101.0],
                [45.002, -122.002, 5.0, 150, 102.0],
            ],
        ),
        (
            "2024-01-02 Evening Ride",
            [
                [45.1, -122.1, 8.0, 140, 105.0],
                [45.101, -122.101, 8.0, 140, 106.0],
            ],
        ),
    ]


@pytest.fixture
def sample_grids():
    """Create sample grid arrays for testing."""
    grid_w, grid_h = 100, 100
    count_grid = np.zeros((grid_h, grid_w), dtype=np.float32)
    speed_sum = np.zeros((grid_h, grid_w), dtype=np.float32)
    speed_n = np.zeros((grid_h, grid_w), dtype=np.float32)
    hr_sum = np.zeros((grid_h, grid_w), dtype=np.float32)
    hr_n = np.zeros((grid_h, grid_w), dtype=np.float32)
    grad_sum = np.zeros((grid_h, grid_w), dtype=np.float32)
    grad_n = np.zeros((grid_h, grid_w), dtype=np.float32)
    elev_sum = np.zeros((grid_h, grid_w), dtype=np.float32)
    elev_n = np.zeros((grid_h, grid_w), dtype=np.float32)

    # Add some test data in the center
    count_grid[50, 50] = 10.0
    speed_sum[50, 50] = 50.0
    speed_n[50, 50] = 10.0
    hr_sum[50, 50] = 1500.0
    hr_n[50, 50] = 10.0
    grad_sum[50, 50] = 0.5
    grad_n[50, 50] = 10.0
    elev_sum[50, 50] = 10.0
    elev_n[50, 50] = 10.0

    return (
        grid_w,
        grid_h,
        count_grid,
        speed_sum,
        speed_n,
        hr_sum,
        hr_n,
        grad_sum,
        grad_n,
        elev_sum,
        elev_n,
    )


@pytest.fixture
def mock_transformer():
    """Create a mock pyproj Transformer."""
    transformer = MagicMock()
    transformer.transform.return_value = (
        np.array([-13500000.0, -13500100.0]),
        np.array([5700000.0, 5700100.0]),
    )
    return transformer


@pytest.fixture
def normalized_grids():
    """Create sample normalized grids dict."""
    h, w = 50, 50
    return {
        "count_norm": np.zeros((h, w), dtype=np.float32),
        "count_log_norm": np.zeros((h, w), dtype=np.float32),
        "speed_norm": np.zeros((h, w), dtype=np.float32),
        "hr_norm": np.zeros((h, w), dtype=np.float32),
        "grad_norm": np.zeros((h, w), dtype=np.float32),
        "elev_norm": np.zeros((h, w), dtype=np.float32),
        "alpha_speed": np.zeros((h, w), dtype=np.float32),
        "alpha_hr": np.zeros((h, w), dtype=np.float32),
        "alpha_grad": np.zeros((h, w), dtype=np.float32),
        "alpha_elev": np.zeros((h, w), dtype=np.float32),
        "s_lo": 3.0,
        "s_hi": 6.0,
        "hr_lo": 120,
        "hr_hi": 180,
        "g_lo": 0.02,
        "g_hi": 0.10,
        "max_passes": 50,
    }


@pytest.fixture
def colormaps():
    """Create colormaps for testing."""
    from src.colormaps import create_colormaps

    return create_colormaps()


# Pytest configuration
def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests as integration tests")


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers."""
    for item in items:
        # Mark tests that use tempfile as slow
        if "tempfile" in str(item.fspath):
            item.add_marker(pytest.mark.slow)
