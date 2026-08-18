"""
Unit tests for src/rasterizer.py - grid computation, rasterization, and normalization functions.
"""

from unittest.mock import MagicMock

import numpy as np

from src.rasterizer import (
    compute_grid_bounds,
    compute_normalized_grids,
    create_grids,
    paint_segment,
    rasterize_tracks,
    setup_transformers,
)


class TestSetupTransformers:
    """Tests for setup_transformers function."""

    def test_returns_six_values(self):
        """Should return 6 transformers/values."""
        result = setup_transformers(45.0, -122.0, 10.0)
        assert len(result) == 6

    def test_returns_transformers_and_values(self):
        """Should return proper transformer objects and computed values."""
        to_wm, from_wm, to_utm, home_x_utm, home_y_utm, clip_m = setup_transformers(
            45.0, -122.0, 10.0
        )

        # Check transformers are callable
        assert callable(to_wm.transform)
        assert callable(from_wm.transform)
        assert callable(to_utm.transform)

        # Check home UTM coordinates are reasonable
        assert isinstance(home_x_utm, float)
        assert isinstance(home_y_utm, float)
        assert home_x_utm != 0
        assert home_y_utm != 0

        # Check clip_m is converted to meters
        assert clip_m == 10000.0

    def test_clip_m_none_when_radius_none(self):
        """Should return None for clip_m when track_clip_radius_km is None."""
        _, _, _, _, _, clip_m = setup_transformers(45.0, -122.0, None)
        assert clip_m is None


class TestComputeGridBounds:
    """Tests for compute_grid_bounds function."""

    def setup_method(self):
        """Set up common test fixtures."""
        self.to_wm = MagicMock()
        self.to_utm = MagicMock()
        self.home_x_utm = 500000.0
        self.home_y_utm = 5000000.0
        self.padding_m = 100.0

    def test_with_clip_radius(self):
        """Should compute bounds from clipped tracks."""
        # Mock transformers
        self.to_utm.transform.return_value = (
            np.array([500100.0, 500200.0]),
            np.array([5000100.0, 5000200.0]),
        )
        self.to_wm.transform.return_value = (
            np.array([-13500000.0, -13500100.0]),
            np.array([5700000.0, 5700100.0]),
        )

        tracks = [
            ("track1", [[45.0, -122.0, 5.0, 150, 100.0], [45.001, -122.001, 5.0, 150, 101.0]]),
        ]

        x_min, x_max, y_min, y_max = compute_grid_bounds(
            tracks,
            self.to_wm,
            self.to_utm,
            self.home_x_utm,
            self.home_y_utm,
            clip_m=10000.0,
            padding_m=self.padding_m,
        )

        assert x_min < x_max
        assert y_min < y_max
        # Check padding is applied
        assert x_min == -13500100.0 - self.padding_m
        assert x_max == -13500000.0 + self.padding_m

    def test_without_clip_radius(self):
        """Should compute bounds from all tracks when no clip radius."""
        self.to_wm.transform.return_value = (
            np.array([-13500000.0, -13500100.0, -13500200.0]),
            np.array([5700000.0, 5700100.0, 5700200.0]),
        )

        tracks = [
            ("track1", [[45.0, -122.0, 5.0, 150, 100.0], [45.001, -122.001, 5.0, 150, 101.0]]),
            ("track2", [[45.002, -122.002, 5.0, 150, 102.0]]),
        ]

        x_min, x_max, y_min, y_max = compute_grid_bounds(
            tracks,
            self.to_wm,
            self.to_utm,
            self.home_x_utm,
            self.home_y_utm,
            clip_m=None,
            padding_m=self.padding_m,
        )

        assert x_min < x_max
        assert y_min < y_max
        assert x_min == -13500200.0 - self.padding_m
        assert x_max == -13500000.0 + self.padding_m


class TestCreateGrids:
    """Tests for create_grids function."""

    def test_creates_correct_grid_dimensions(self):
        """Should create grids with correct width/height."""
        x_min, x_max = 0.0, 1000.0
        y_min, y_max = 0.0, 500.0
        meters_per_pixel = 10.0

        result = create_grids(x_min, x_max, y_min, y_max, meters_per_pixel)

        grid_w, grid_h = result[0], result[1]
        assert grid_w == 101  # (1000-0)/10 + 1
        assert grid_h == 51  # (500-0)/10 + 1

    def test_returns_all_grid_arrays(self):
        """Should return all 11 grid arrays."""
        result = create_grids(0.0, 100.0, 0.0, 100.0, 10.0)

        assert len(result) == 11
        grid_w, grid_h = result[0], result[1]
        grids = result[2:]

        assert len(grids) == 9
        for grid in grids:
            assert grid.shape == (grid_h, grid_w)
            assert grid.dtype == np.float32
            assert np.all(grid == 0)  # All initialized to zero


class TestPaintSegment:
    """Tests for paint_segment function."""

    def setup_method(self):
        """Set up test grids."""
        self.grid_w, self.grid_h = 100, 100
        self.count_grid = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.speed_sum = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.speed_n = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.hr_sum = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.hr_n = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.grad_sum = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.grad_n = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.elev_sum = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.elev_n = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)

        self.grids = (
            self.grid_w,
            self.grid_h,
            self.count_grid,
            self.speed_sum,
            self.speed_n,
            self.hr_sum,
            self.hr_n,
            self.grad_sum,
            self.grad_n,
            self.elev_sum,
            self.elev_n,
        )

    def test_paints_horizontal_line(self):
        """Should paint a horizontal line segment."""
        paint_segment(10, 50, 20, 50, 5.0, 150, 0.05, 1.0, self.grids)

        # Check that pixels along the line were painted
        assert self.speed_sum[50, 10] > 0
        assert self.speed_sum[50, 15] > 0
        assert self.speed_sum[50, 20] > 0
        assert self.speed_n[50, 15] > 0

    def test_paints_vertical_line(self):
        """Should paint a vertical line segment."""
        paint_segment(50, 10, 50, 20, 5.0, 150, 0.05, 1.0, self.grids)

        assert self.speed_sum[10, 50] > 0
        assert self.speed_sum[15, 50] > 0
        assert self.speed_sum[20, 50] > 0

    def test_paints_diagonal_line(self):
        """Should paint a diagonal line segment."""
        paint_segment(10, 10, 20, 20, 5.0, 150, 0.05, 1.0, self.grids)

        # Should paint along diagonal
        assert self.speed_sum[10, 10] > 0
        assert self.speed_sum[15, 15] > 0
        assert self.speed_sum[20, 20] > 0

    def test_handles_none_values(self):
        """Should handle None values for optional metrics."""
        paint_segment(10, 10, 20, 20, None, None, None, None, self.grids)

        # Count grid should still be incremented (handled by caller)
        # But other grids should remain zero
        assert np.all(self.speed_sum == 0)
        assert np.all(self.hr_sum == 0)
        assert np.all(self.grad_sum == 0)
        assert np.all(self.elev_sum == 0)

    def test_clips_to_grid_bounds(self):
        """Should not paint outside grid bounds."""
        paint_segment(-10, -10, -5, -5, 5.0, 150, 0.05, 1.0, self.grids)

        # Nothing should be painted (all coordinates negative)
        assert np.all(self.speed_sum == 0)

        paint_segment(95, 95, 105, 105, 5.0, 150, 0.05, 1.0, self.grids)

        # Only in-bounds portion should be painted
        assert self.speed_sum[95, 95] > 0
        assert self.speed_sum[99, 99] > 0


class TestRasterizeTracks:
    """Tests for rasterize_tracks function."""

    def setup_method(self):
        """Set up common test fixtures."""
        self.to_wm = MagicMock()
        self.to_utm = MagicMock()
        self.home_x_utm = 500000.0
        self.home_y_utm = 5000000.0
        self.x_min_wm = -13500000.0
        self.y_max_wm = 5700000.0
        self.meters_per_pixel = 10.0

        # Create grids
        result = create_grids(
            self.x_min_wm,
            self.x_min_wm + 1000,
            self.y_max_wm - 1000,
            self.y_max_wm,
            self.meters_per_pixel,
        )
        self.grids = result

    def test_rasterizes_tracks_without_clip(self):
        """Should rasterize all tracks when no clip radius."""
        self.to_utm.transform.return_value = (
            np.array([500100.0, 500200.0]),
            np.array([5000100.0, 5000200.0]),
        )
        self.to_wm.transform.return_value = (
            np.array([-13500050.0, -13500000.0]),
            np.array([5700050.0, 5700000.0]),
        )

        tracks = [
            (
                "track1",
                [
                    [45.0, -122.0, 5.0, 150, 100.0],
                    [45.001, -122.001, 5.0, 150, 101.0],
                ],
            ),
        ]

        rasterize_tracks(
            tracks,
            self.to_wm,
            self.to_utm,
            self.home_x_utm,
            self.home_y_utm,
            clip_m=None,
            x_min_wm=self.x_min_wm,
            y_max_wm=self.y_max_wm,
            meters_per_pixel=self.meters_per_pixel,
            grids=self.grids,
        )

        # Count grid should have points
        count_grid = self.grids[2]
        assert np.sum(count_grid) > 0

    def test_clips_tracks_with_clip_radius(self):
        """Should clip tracks to radius when clip_m is provided."""
        # First point inside radius, second outside
        self.to_utm.transform.return_value = (
            np.array([500100.0, 510000.0]),  # Second point far away
            np.array([5000100.0, 5000100.0]),
        )
        # Both map inside the grid; only first survives the clip mask
        self.to_wm.transform.return_value = (
            np.array([-13500000.0, -13500000.0]),
            np.array([5700000.0, 5700000.0]),
        )

        tracks = [
            (
                "track1",
                [
                    [45.0, -122.0, 5.0, 150, 100.0],  # Inside clip radius
                    [45.5, -122.5, 5.0, 150, 101.0],  # Outside clip radius
                ],
            ),
        ]

        rasterize_tracks(
            tracks,
            self.to_wm,
            self.to_utm,
            self.home_x_utm,
            self.home_y_utm,
            clip_m=5000.0,
            x_min_wm=self.x_min_wm,
            y_max_wm=self.y_max_wm,
            meters_per_pixel=self.meters_per_pixel,
            grids=self.grids,
        )

        # Only first point should be rasterized
        count_grid = self.grids[2]
        assert np.sum(count_grid) > 0


class TestComputeNormalizedGrids:
    """Tests for compute_normalized_grids function."""

    def setup_method(self):
        """Set up test grids with known data."""
        self.grid_w, self.grid_h = 100, 100
        self.count_grid = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.speed_sum = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.speed_n = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.hr_sum = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.hr_n = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.grad_sum = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.grad_n = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.elev_sum = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.elev_n = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)

        # Add some test data in the center
        self.count_grid[50, 50] = 10.0
        self.speed_sum[50, 50] = 50.0
        self.speed_n[50, 50] = 10.0
        self.hr_sum[50, 50] = 1500.0
        self.hr_n[50, 50] = 10.0
        self.grad_sum[50, 50] = 0.5
        self.grad_n[50, 50] = 10.0
        self.elev_sum[50, 50] = 10.0
        self.elev_n[50, 50] = 10.0

        self.grids = (
            self.grid_w,
            self.grid_h,
            self.count_grid,
            self.speed_sum,
            self.speed_n,
            self.hr_sum,
            self.hr_n,
            self.grad_sum,
            self.grad_n,
            self.elev_sum,
            self.elev_n,
        )

        # Mock config
        self.config = MagicMock()
        self.config.speed_min_ms = None
        self.config.speed_max_ms = None
        self.config.hr_min_bpm = None
        self.config.hr_max_bpm = None
        self.config.auto_range_pct = 5

    def test_returns_all_normalized_grids(self):
        """Should return dict with all expected normalized grids."""
        result = compute_normalized_grids(self.grids, sigma=1.0, config=self.config)

        expected_keys = [
            "count_norm",
            "count_log_norm",
            "speed_norm",
            "hr_norm",
            "grad_norm",
            "elev_norm",
            "alpha_speed",
            "alpha_hr",
            "alpha_grad",
            "alpha_elev",
            "s_lo",
            "s_hi",
            "hr_lo",
            "hr_hi",
            "g_lo",
            "g_hi",
            "max_passes",
        ]

        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_count_norm_range(self):
        """Count norm should be in [0, 1]."""
        result = compute_normalized_grids(self.grids, sigma=1.0, config=self.config)

        assert np.all(result["count_norm"] >= 0)
        assert np.all(result["count_norm"] <= 1)
        assert result["count_norm"].max() == 1.0

    def test_count_log_norm_range(self):
        """Count log norm should be in [0, 1]."""
        result = compute_normalized_grids(self.grids, sigma=1.0, config=self.config)

        assert np.all(result["count_log_norm"] >= 0)
        assert np.all(result["count_log_norm"] <= 1)

    def test_speed_norm_range(self):
        """Speed norm should be in [0, 1] where visited."""
        result = compute_normalized_grids(self.grids, sigma=1.0, config=self.config)

        # Where speed_n > 0, norm should be in [0, 1]
        visited = result["speed_norm"] > 0
        if np.any(visited):
            assert np.all(result["speed_norm"][visited] >= 0)
            assert np.all(result["speed_norm"][visited] <= 1)

    def test_hr_norm_range(self):
        """HR norm should be in [0, 1] where visited."""
        result = compute_normalized_grids(self.grids, sigma=1.0, config=self.config)

        visited = result["hr_norm"] > 0
        if np.any(visited):
            assert np.all(result["hr_norm"][visited] >= 0)
            assert np.all(result["hr_norm"][visited] <= 1)

    def test_grad_norm_range(self):
        """Grad norm should be in [0, 1] where visited."""
        result = compute_normalized_grids(self.grids, sigma=1.0, config=self.config)

        visited = result["grad_norm"] > 0
        if np.any(visited):
            assert np.all(result["grad_norm"][visited] >= 0)
            assert np.all(result["grad_norm"][visited] <= 1)

    def test_elev_norm_range(self):
        """Elev norm should be in [-1, 1] where visited."""
        result = compute_normalized_grids(self.grids, sigma=1.0, config=self.config)

        visited = result["elev_norm"] != 0
        if np.any(visited):
            assert np.all(result["elev_norm"][visited] >= -1)
            assert np.all(result["elev_norm"][visited] <= 1)

    def test_alpha_masks_range(self):
        """Alpha masks should be in [0, 1]."""
        result = compute_normalized_grids(self.grids, sigma=1.0, config=self.config)

        for key in ["alpha_speed", "alpha_hr", "alpha_grad", "alpha_elev"]:
            assert np.all(result[key] >= 0)
            assert np.all(result[key] <= 1)

    def test_max_passes_is_int(self):
        """max_passes should be an integer."""
        result = compute_normalized_grids(self.grids, sigma=1.0, config=self.config)

        assert isinstance(result["max_passes"], int)
        assert result["max_passes"] > 0

    def test_handles_count_only_grids(self):
        """Should return expected keys when only count data exists."""
        # Grid with only count data; all metric grids are zero
        count_only = (
            10,
            10,
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
        )
        count_only[2][5, 5] = 3.0  # Add a single count so count_norm is valid

        # Should not raise and return all expected keys
        result = compute_normalized_grids(count_only, sigma=1.0, config=self.config)

        expected_keys = [
            "count_norm",
            "count_log_norm",
            "speed_norm",
            "hr_norm",
            "grad_norm",
            "elev_norm",
            "alpha_speed",
            "alpha_hr",
            "alpha_grad",
            "alpha_elev",
            "s_lo",
            "s_hi",
            "hr_lo",
            "hr_hi",
            "g_lo",
            "g_hi",
            "max_passes",
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_handles_fully_empty_grids(self):
        """Should not raise on completely empty grids (all zeros)."""
        empty_grids = (
            10,
            10,
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
        )

        # Should not raise on empty grids
        result = compute_normalized_grids(empty_grids, sigma=1.0, config=self.config)

        assert "count_norm" in result
        assert "speed_norm" in result
        assert "hr_norm" in result
        assert result["max_passes"] == 0
