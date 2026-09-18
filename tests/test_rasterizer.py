"""
Unit tests for src/rasterizer.py - grid computation, rasterization, and normalization functions.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

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
        """Should return all 13 grid arrays."""
        result = create_grids(0.0, 100.0, 0.0, 100.0, 10.0)

        assert len(result) == 13
        grid_w, grid_h = result[0], result[1]
        grids = result[2:]

        assert len(grids) == 11
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
            max_consecutive_same_cell=3,
            decay_factor=0.5,
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
            max_consecutive_same_cell=3,
            decay_factor=0.5,
            grids=self.grids,
        )

        # Only first point should be rasterized
        count_grid = self.grids[2]
        assert np.sum(count_grid) > 0

    def test_caps_consecutive_same_cell(self):
        """Should cap counts for a stationary stretch of same-cell points.

        Simulates forgetting to stop the watch: many consecutive samples land
        in the same grid cell. Only up to `max_consecutive_same_cell`
        consecutive samples should be counted (with decay applied).
        """
        # All points map to the same pixel (same web-mercator coords)
        n_points = 38
        self.to_utm.transform.return_value = (
            np.full(n_points, 500100.0),
            np.full(n_points, 5000100.0),
        )
        # px = (xm - x_min_wm)/10 = 5 ; py = (y_max_wm - ym)/10 = 5  -> in bounds
        self.to_wm.transform.return_value = (
            np.full(n_points, -13499950.0),
            np.full(n_points, 5699950.0),
        )

        tracks = [
            ("stationary", [[45.0, -122.0, None, None, 100.0]] * n_points),
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
            max_consecutive_same_cell=3,
            decay_factor=0.5,
            grids=self.grids,
        )

        count_grid = self.grids[2]
        # With decay: 1.0 + 0.5 + 0.25 = 1.75 (not 3 as before)
        assert np.sum(count_grid) == pytest.approx(1.75)

    def test_resets_counter_on_cell_change(self):
        """Should reset the consecutive counter when the cell changes.

        A later return to the same cell should be counted again (genuine
        re-visit), so the cap only limits *consecutive* same-cell samples.
        With per-activity decay, the second visit to a cell is weighted less.
        """
        # Coordinates alternate between two pixels
        # px: (xm - x_min_wm)/10 = 5, 10 ; py: (y_max_wm - ym)/10 = 5, 10
        xs_wm = np.array([-13499950.0, -13499900.0] * 3)
        ys_wm = np.array([5699950.0, 5699900.0] * 3)
        self.to_utm.transform.return_value = (
            np.array([500100.0, 500000.0] * 3),
            np.array([5000100.0, 5000000.0] * 3),
        )
        self.to_wm.transform.return_value = (xs_wm, ys_wm)

        tracks = [
            ("back_and_forth", [[45.0, -122.0, None, None, 100.0]] * 6),
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
            max_consecutive_same_cell=3,
            decay_factor=0.5,
            grids=self.grids,
        )

        count_grid = self.grids[2]
        # Sequence of cells: A B A B A B. Each cell is visited 3x within the
        # activity but never consecutively; with per-activity decay the repeats
        # are weighted 1 + 0.5 + 0.25 = 1.75 per cell -> 2 * 1.75 = 3.5.
        assert np.sum(count_grid) == pytest.approx(3.5)

    def test_decay_laps_in_single_activity(self):
        """Repeated same-cell visits within ONE activity should decay.

        Simulates a running-track session: the athlete passes the same pixel
        multiple times. Each additional pass within the activity contributes
        less (1, d, d^2, ...) so a 10-lap session is not 10x a 1-lap session.
        """
        # 6 consecutive points all in the SAME pixel (same cell, different times)
        n_points = 6
        self.to_utm.transform.return_value = (
            np.full(n_points, 500100.0),
            np.full(n_points, 5000100.0),
        )
        self.to_wm.transform.return_value = (
            np.full(n_points, -13499950.0),
            np.full(n_points, 5699950.0),
        )

        tracks = [
            ("track_laps", [[45.0, -122.0, None, None, 100.0]] * n_points),
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
            max_consecutive_same_cell=100,  # disable consecutive cap to isolate decay
            decay_factor=0.5,
            grids=self.grids,
        )

        count_grid = self.grids[2]
        # 1 + 0.5 + 0.25 + 0.125 + 0.0625 + 0.03125 = 1.96875
        assert np.sum(count_grid) == pytest.approx(1.96875)

    def test_decay_resets_across_activities(self):
        """Decay should reset for each new activity (different days = fresh 1.0).

        The same cell visited once per activity across 3 activities should sum to 3.0,
        not decay as if it were a single activity.
        """
        # Single point per activity, all in the SAME pixel
        self.to_utm.transform.return_value = (
            np.array([500100.0, 500100.0, 500100.0]),
            np.array([5000100.0, 5000100.0, 5000100.0]),
        )
        self.to_wm.transform.return_value = (
            np.array([-13499950.0, -13499950.0, -13499950.0]),
            np.array([5699950.0, 5699950.0, 5699950.0]),
        )

        tracks = [
            ("run_1", [[45.0, -122.0, None, None, 100.0]]),
            ("run_2", [[45.0, -122.0, None, None, 100.0]]),
            ("run_3", [[45.0, -122.0, None, None, 100.0]]),
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
            max_consecutive_same_cell=100,
            decay_factor=0.5,
            grids=self.grids,
        )

        count_grid = self.grids[2]
        # 3 separate activities, each first visit -> 1 + 1 + 1 = 3.0
        assert np.sum(count_grid) == pytest.approx(3.0)

    def test_derives_all_strategy_grids_in_one_pass(self):
        """Raw/binary counts and the decay total share the same per-cell visits.

        6 counted passes of the same cell within one activity must produce:
        * raw-count grid = 6
        * binary-per-activity grid = 1
        * decay grid = 1.96875 (geometric sum for decay_factor=0.5)
        """
        n_points = 6
        self.to_utm.transform.return_value = (
            np.full(n_points, 500100.0),
            np.full(n_points, 5000100.0),
        )
        self.to_wm.transform.return_value = (
            np.full(n_points, -13499950.0),
            np.full(n_points, 5699950.0),
        )

        tracks = [
            ("track_laps", [[45.0, -122.0, None, None, 100.0]] * n_points),
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
            max_consecutive_same_cell=100,
            decay_factor=0.5,
            grids=self.grids,
        )

        raw_grid = self.grids[11]
        binary_grid = self.grids[12]
        decay_grid = self.grids[2]

        assert np.sum(raw_grid) == 6
        assert np.sum(binary_grid) == 1
        assert np.sum(decay_grid) == pytest.approx(1.96875)

    def test_raw_and_binary_cross_activities(self):
        """Raw-count sums passes across activities; binary counts coverage.

        One pass per cell across 3 activities -> raw = 3, binary = 3, decay = 3.
        """
        self.to_utm.transform.return_value = (
            np.array([500100.0, 500100.0, 500100.0]),
            np.array([5000100.0, 5000100.0, 5000100.0]),
        )
        self.to_wm.transform.return_value = (
            np.array([-13499950.0, -13499950.0, -13499950.0]),
            np.array([5699950.0, 5699950.0, 5699950.0]),
        )

        tracks = [
            ("run_1", [[45.0, -122.0, None, None, 100.0]]),
            ("run_2", [[45.0, -122.0, None, None, 100.0]]),
            ("run_3", [[45.0, -122.0, None, None, 100.0]]),
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
            max_consecutive_same_cell=100,
            decay_factor=0.5,
            grids=self.grids,
        )

        raw_grid = self.grids[11]
        binary_grid = self.grids[12]

        assert np.sum(raw_grid) == 3
        assert np.sum(binary_grid) == 3
        assert np.sum(self.grids[2]) == pytest.approx(3.0)  # decay == raw here

    def test_rasterize_tracks_returns_activity_count(self):
        """rasterize_tracks should return the number of activities that contributed cells."""
        to_wm = MagicMock()
        to_utm = MagicMock()

        to_utm.transform.return_value = (
            np.array([500000.0, 500010.0]),
            np.array([5000000.0, 5000010.0]),
        )
        to_wm.transform.return_value = (
            np.array([-13500050.0, -13500040.0]),
            np.array([5700050.0, 5700060.0]),
        )

        grids = create_grids(
            -13500100.0,
            -13500000.0,
            5700000.0,
            5700100.0,
            10.0,
        )

        tracks = [
            ("track1", [[45.0, -122.0, 5.0, 150, 100.0], [45.001, -122.001, 5.0, 150, 101.0]]),
            ("track2", [[45.0, -122.0, 5.0, 150, 200.0], [45.001, -122.001, 5.0, 150, 201.0]]),
        ]

        count = rasterize_tracks(
            tracks,
            to_wm,
            to_utm,
            500000.0,
            5000000.0,
            clip_m=None,
            x_min_wm=-13500100.0,
            y_max_wm=5700100.0,
            meters_per_pixel=10.0,
            max_consecutive_same_cell=3,
            grids=grids,
        )

        assert count == 2


class TestRasterizeTracksCellActivities:
    """The optional cell_activities collector behind the map's click tooltips."""

    def setup_method(self):
        """Set up transformers/grids over a 1000 x 1000 m area at 10 m/pixel."""
        self.to_wm = MagicMock()
        self.to_utm = MagicMock()
        self.x_min_wm = -13500000.0
        self.y_max_wm = 5700000.0
        self.grids = create_grids(
            self.x_min_wm, self.x_min_wm + 1000, self.y_max_wm - 1000, self.y_max_wm, 10.0
        )

    def _rasterize(self, cells):
        tracks = [
            ("activity-a", [[45.0, -122.0, 5.0, 150, 100.0]]),
            ("activity-b", [[45.0, -122.0, 5.0, 150, 100.0]]),
        ]
        rasterize_tracks(
            tracks,
            self.to_wm,
            self.to_utm,
            500000.0,
            5000000.0,
            clip_m=None,
            x_min_wm=self.x_min_wm,
            y_max_wm=self.y_max_wm,
            meters_per_pixel=10.0,
            max_consecutive_same_cell=3,
            grids=self.grids,
            cell_activities=cells,
        )

    def test_records_each_activity_under_its_cell(self):
        """Every activity is mapped to the cell its points were counted in."""
        # Each track is transformed once, so the mock answers per track:
        # track 0 -> cell (row 5, col 5); track 1 -> cell (row 10, col 10).
        self.to_utm.transform.side_effect = [
            (np.array([500000.0]), np.array([5000000.0])),
            (np.array([500000.0]), np.array([5000000.0])),
        ]
        self.to_wm.transform.side_effect = [
            (np.array([-13499950.0]), np.array([5699950.0])),
            (np.array([-13499900.0]), np.array([5699900.0])),
        ]

        cells: dict = {}
        self._rasterize(cells)

        assert cells == {(5, 5): {0}, (10, 10): {1}}

    def test_same_cell_keeps_every_visiting_activity(self):
        """Activities sharing a cell are both listed against it."""
        self.to_utm.transform.side_effect = [
            (np.array([500000.0]), np.array([5000000.0])),
            (np.array([500000.0]), np.array([5000000.0])),
        ]
        # Both tracks land in the same cell (row 5, col 5).
        self.to_wm.transform.side_effect = [
            (np.array([-13499950.0]), np.array([5699950.0])),
            (np.array([-13499950.0]), np.array([5699950.0])),
        ]

        cells: dict = {}
        self._rasterize(cells)

        assert cells == {(5, 5): {0, 1}}

    def test_collection_is_optional(self):
        """Omitting the collector leaves rasterize_tracks unchanged."""
        self.to_utm.transform.return_value = (
            np.array([500000.0]),
            np.array([5000000.0]),
        )
        self.to_wm.transform.return_value = (
            np.array([-13499950.0]),
            np.array([5699950.0]),
        )
        rasterize_tracks(
            [("a", [[45.0, -122.0, 5.0, 150, 100.0]])],
            self.to_wm,
            self.to_utm,
            500000.0,
            5000000.0,
            clip_m=None,
            x_min_wm=self.x_min_wm,
            y_max_wm=self.y_max_wm,
            meters_per_pixel=10.0,
            max_consecutive_same_cell=3,
            grids=self.grids,
        )
        # No error, and the count grid still holds the visit.
        assert np.sum(self.grids[2]) > 0


class TestRasterModes:
    """Tests for raster_mode selection (raw-count / decay / binary-per-activity)."""

    def setup_method(self):
        """Set up transformers/grids: 6 points of one activity all in the same cell."""
        self.to_wm = MagicMock()
        self.to_utm = MagicMock()
        self.x_min_wm = -13500000.0
        self.y_max_wm = 5700000.0

        n_points = 6
        self.to_utm.transform.return_value = (
            np.full(n_points, 500100.0),
            np.full(n_points, 5000100.0),
        )
        self.to_wm.transform.return_value = (
            np.full(n_points, -13499950.0),
            np.full(n_points, 5699950.0),
        )
        self.tracks = [("track_laps", [[45.0, -122.0, None, None, 100.0]] * n_points)]

        self.grids = self._fresh_grids()

        self.config = MagicMock()
        self.config.coverage_normalization = "max"

    def _fresh_grids(self):
        result = create_grids(
            self.x_min_wm, self.x_min_wm + 1000, self.y_max_wm - 1000, self.y_max_wm, 10.0
        )
        return result

    def _rasterize(self, raster_mode, tracks=None):
        return rasterize_tracks(
            tracks if tracks is not None else self.tracks,
            self.to_wm,
            self.to_utm,
            500000.0,
            5000000.0,
            clip_m=None,
            x_min_wm=self.x_min_wm,
            y_max_wm=self.y_max_wm,
            meters_per_pixel=10.0,
            max_consecutive_same_cell=100,
            decay_factor=0.9,
            grids=self.grids,
            raster_mode=raster_mode,
        )

    @pytest.mark.parametrize(
        ("raster_mode", "expected_max_passes", "source_key"),
        [
            ("decay", 4, "count_norm"),  # 1+0.9+...+0.9^5 = 4.68559 -> int 4
            ("raw-count", 6, "count_raw_norm"),  # every GPS point counted
            ("binary-per-activity", 1, "unique_norm"),  # one activity -> max 1 per cell
        ],
    )
    def test_mode_selects_primary_grid(self, raster_mode, expected_max_passes, source_key):
        """The primary density output must come from the grid chosen by the mode."""
        self._rasterize(raster_mode)
        normalized = compute_normalized_grids(
            self.grids, sigma=0.0, config=self.config, raster_mode=raster_mode
        )

        assert normalized["raster_mode"] == raster_mode
        assert normalized["max_passes"] == expected_max_passes
        # Primary normalized grids saturate at 1.0 for the visited cell.
        assert normalized["count_norm"].max() == 1.0
        assert normalized["count_log_norm"].max() == 1.0
        # The primary grid is exactly the strategy grid the mode selects.
        assert np.allclose(normalized["count_norm"], normalized[source_key])

    def test_by_strategy_counts_independent_of_mode(self):
        """max_passes_by_strategy reflects all strategies no matter the mode."""
        self._rasterize("binary-per-activity")
        normalized = compute_normalized_grids(
            self.grids, sigma=0.0, config=self.config, raster_mode="binary-per-activity"
        )
        assert normalized["max_passes_by_strategy"] == {
            "decay": 4,
            "raw-count": 6,
            "binary-per-activity": 1,
        }

    def test_modes_differ_across_activities(self):
        """Three activities x 6 passes: raw=18, decay=14, binary=3 (per-cell max)."""
        tracks = [
            ("run_1", [[45.0, -122.0, None, None, 100.0]] * 6),
            ("run_2", [[45.0, -122.0, None, None, 100.0]] * 6),
            ("run_3", [[45.0, -122.0, None, None, 100.0]] * 6),
        ]
        expected = {"decay": 14, "raw-count": 18, "binary-per-activity": 3}
        for mode, expected_max in expected.items():
            self._rasterize(mode, tracks=tracks)
            normalized = compute_normalized_grids(
                self.grids, sigma=0.0, config=self.config, raster_mode=mode
            )
            assert normalized["raster_mode"] == mode
            assert normalized["max_passes"] == expected_max
            # Fresh grids for the next mode (normalization deletes its copies,
            # but the tuple still references the painted arrays).
            self.grids = self._fresh_grids()

    def test_default_mode_is_decay(self):
        """compute_normalized_grids defaults to the decay mode (current behavior)."""
        self._rasterize("decay")
        normalized = compute_normalized_grids(self.grids, sigma=0.0, config=self.config)
        assert normalized["raster_mode"] == "decay"
        assert normalized["max_passes"] == 4

    def test_invalid_mode_rejected_by_rasterize_tracks(self):
        """rasterize_tracks should fail fast on an unknown mode."""
        with pytest.raises(ValueError, match="Unknown raster_mode"):
            self._rasterize("bogus")

    def test_invalid_mode_rejected_by_compute_normalized_grids(self):
        """compute_normalized_grids should fail fast on an unknown mode."""
        with pytest.raises(ValueError, match="Unknown raster_mode"):
            compute_normalized_grids(self.grids, sigma=0.0, config=self.config, raster_mode="bogus")


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
            np.zeros((self.grid_h, self.grid_w), dtype=np.float32),
            np.zeros((self.grid_h, self.grid_w), dtype=np.float32),
        )

        # Mock config
        self.config = MagicMock()
        self.config.speed_min_ms = None
        self.config.speed_max_ms = None
        self.config.hr_min_bpm = None
        self.config.hr_max_bpm = None
        self.config.auto_range_pct = 5
        self.config.coverage_normalization = "max"

    def test_returns_all_normalized_grids(self):
        """Should return dict with all expected normalized grids."""
        result = compute_normalized_grids(self.grids, sigma=1.0, config=self.config)

        expected_keys = [
            "count_norm",
            "count_log_norm",
            "count_raw_norm",
            "count_raw_log_norm",
            "unique_norm",
            "unique_log_norm",
            "unique_pct_norm",
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
            "max_passes_raw",
            "max_passes_unique",
            "max_passes_by_strategy",
            "n_activities",
            "coverage_normalization",
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
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
        )
        count_only[2][5, 5] = 3.0  # Add a single count so decay norm is valid
        count_only[11][5, 5] = 3.0  # raw-count grid
        count_only[12][5, 5] = 1.0  # binary grid

        # Should not raise and return all expected keys
        result = compute_normalized_grids(count_only, sigma=1.0, config=self.config)

        expected_keys = [
            "count_norm",
            "count_log_norm",
            "count_raw_norm",
            "count_raw_log_norm",
            "unique_norm",
            "unique_log_norm",
            "unique_pct_norm",
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
            "max_passes_raw",
            "max_passes_unique",
            "max_passes_by_strategy",
            "n_activities",
            "coverage_normalization",
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
            np.zeros((10, 10), dtype=np.float32),
            np.zeros((10, 10), dtype=np.float32),
        )

        # Should not raise on empty grids
        result = compute_normalized_grids(empty_grids, sigma=1.0, config=self.config)

        assert "count_norm" in result
        assert "speed_norm" in result
        assert "hr_norm" in result
        assert result["max_passes"] == 0

    def test_binary_pct_normalization(self):
        """unique_pct_norm should equal (blurred binary) / n_activities,
        clamped to [0, 1]."""
        # Build a small grid with known binary coverage
        grids = (
            10,
            10,
            np.zeros((10, 10), dtype=np.float32),  # count_grid (decay)
            np.zeros((10, 10), dtype=np.float32),  # speed_sum
            np.zeros((10, 10), dtype=np.float32),  # speed_n
            np.zeros((10, 10), dtype=np.float32),  # hr_sum
            np.zeros((10, 10), dtype=np.float32),  # hr_n
            np.zeros((10, 10), dtype=np.float32),  # grad_sum
            np.zeros((10, 10), dtype=np.float32),  # grad_n
            np.zeros((10, 10), dtype=np.float32),  # elev_sum
            np.zeros((10, 10), dtype=np.float32),  # elev_n
            np.zeros((10, 10), dtype=np.float32),  # count_raw_grid
            np.zeros((10, 10), dtype=np.float32),  # unique_grid
        )
        # Put known binary values — 2 activities visited cell (5,5), 4 visited (6,6)
        grids[12][5, 5] = 2.0
        grids[12][6, 6] = 4.0

        config = MagicMock()
        config.speed_min_ms = None
        config.speed_max_ms = None
        config.hr_min_bpm = None
        config.hr_max_bpm = None
        config.auto_range_pct = 5
        config.coverage_normalization = "pct"

        # With sigma=0, gaussian_filter is identity
        result = compute_normalized_grids(grids, sigma=0.0, config=config, n_activities=10)

        assert result["n_activities"] == 10
        assert result["coverage_normalization"] == "pct"
        assert result["unique_pct_norm"].dtype == np.float32
        # Cell (5,5) was visited by 2 out of 10 activities → pct = 0.2
        assert abs(result["unique_pct_norm"][5, 5] - 0.2) < 1e-6
        # Cell (6,6) was visited by 4 out of 10 → pct = 0.4
        assert abs(result["unique_pct_norm"][6, 6] - 0.4) < 1e-6
        # All other cells should be 0
        assert abs(result["unique_pct_norm"][0, 0]) < 1e-6
        assert result["unique_pct_norm"].max() <= 1.0

    def test_binary_pct_normalization_clips_at_one(self):
        """Percentage should be clamped to 1.0 even if n_activities is very small."""
        grids = (
            5,
            5,
            np.zeros((5, 5), dtype=np.float32),
            np.zeros((5, 5), dtype=np.float32),
            np.zeros((5, 5), dtype=np.float32),
            np.zeros((5, 5), dtype=np.float32),
            np.zeros((5, 5), dtype=np.float32),
            np.zeros((5, 5), dtype=np.float32),
            np.zeros((5, 5), dtype=np.float32),
            np.zeros((5, 5), dtype=np.float32),
            np.zeros((5, 5), dtype=np.float32),
            np.zeros((5, 5), dtype=np.float32),
            np.zeros((5, 5), dtype=np.float32),
        )
        grids[12][2, 2] = 15.0  # more than n_activities

        config = MagicMock()
        config.coverage_normalization = "pct"

        result = compute_normalized_grids(grids, sigma=0.0, config=config, n_activities=3)
        # 15/3 = 5.0 but clipped to 1.0
        assert result["unique_pct_norm"][2, 2] == 1.0
