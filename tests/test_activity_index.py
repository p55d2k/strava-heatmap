"""
Unit tests for src/activity_index.py - the per-cell activity index behind the
map's click tooltips.

The index is the contract between the Python build and the browser: the payload
the tests here pin is exactly what assets/panel.js inflates on the first click,
so the cell-key convention and the per-activity record layout must not drift.
"""

import json

import pandas as pd
import pytest

from src.activity_index import (
    STRAVA_ACTIVITY_URL,
    activity_label,
    build_activities,
    build_activity_index,
    build_activity_types,
    build_strava_links,
    split_activity_label,
)


class TestSplitActivityLabel:
    """The label loader format is '<YYYY-MM-DD> <name>'."""

    def test_splits_date_and_name(self):
        assert split_activity_label("2024-01-02 Evening Ride") == (
            "2024-01-02",
            "Evening Ride",
        )

    def test_keeps_multi_word_names(self):
        assert split_activity_label("2024-03-09 Early Morning Long Run") == (
            "2024-03-09",
            "Early Morning Long Run",
        )

    def test_handles_date_only_label(self):
        assert split_activity_label("2024-01-02") == ("2024-01-02", "")

    def test_tolerates_a_bespoke_label(self):
        """A hand-made label gets no date rather than a wrong one."""
        assert split_activity_label("custom track") == ("", "custom track")

    def test_handles_none(self):
        assert split_activity_label(None) == ("", "")


class TestActivityLabel:
    """build_strava_links must key on the exact label load_tracks builds."""

    def test_matches_the_loader_label_format(self):
        label = activity_label(pd.Timestamp("2024-01-02"), "Evening Ride")
        assert label == "2024-01-02 Evening Ride"


class TestBuildStravaLinks:
    """Strava links come from the export's optional Activity ID column."""

    def test_maps_ids_to_urls(self):
        runs = pd.DataFrame(
            {
                "Activity Date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
                "Activity Name": ["Morning Run", "Evening Ride"],
                "Activity ID": [123456, 987654],
            }
        )

        links = build_strava_links(runs)

        assert links["2024-01-01 Morning Run"] == STRAVA_ACTIVITY_URL.format(activity_id=123456)
        assert links["2024-01-02 Evening Ride"] == STRAVA_ACTIVITY_URL.format(activity_id=987654)

    def test_handles_float_ids_from_missing_rows(self):
        """pandas widens the column to floats when any row has no id."""
        runs = pd.DataFrame(
            {
                "Activity Date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
                "Activity Name": ["Morning Run", "Evening Ride"],
                "Activity ID": [123456.0, float("nan")],
            }
        )

        links = build_strava_links(runs)

        assert links == {"2024-01-01 Morning Run": STRAVA_ACTIVITY_URL.format(activity_id=123456)}

    def test_returns_empty_without_the_column(self):
        runs = pd.DataFrame(
            {
                "Activity Date": pd.to_datetime(["2024-01-01"]),
                "Activity Name": ["Morning Run"],
            }
        )
        assert build_strava_links(runs) == {}

    def test_returns_empty_for_none(self):
        assert build_strava_links(None) == {}


class TestBuildActivities:
    """Per-activity popup records: [date, name, pace, hr, url]."""

    def test_averages_speed_and_heart_rate(self):
        tracks = [
            (
                "2024-01-01 Morning Run",
                [
                    [45.0, -122.0, 5.0, 150, 100.0],
                    [45.001, -122.001, 3.0, 170, 101.0],
                ],
            )
        ]

        activities = build_activities(tracks)

        # [date, name, pace, hr, url, type] - url and type are empty here.
        assert activities == [["2024-01-01", "Morning Run", "4:10/km", 160, "", ""]]

    def test_ignores_pauses_and_missing_metrics(self):
        """Zero-speed samples are stops, not movement; absent fields stay null."""
        tracks = [
            (
                "2024-01-01 Walk",
                [
                    [45.0, -122.0, 0.0, None, 100.0],
                    [45.001, -122.001, 2.0, None, 101.0],
                ],
            )
        ]

        activities = build_activities(tracks)

        pace, hr = activities[0][2], activities[0][3]
        assert pace == "8:20/km"  # only the 2 m/s sample counts
        assert hr is None

    def test_record_without_any_metrics(self):
        activities = build_activities([("custom", [[45.0, -122.0]])])
        assert activities == [["", "custom", "", None, "", ""]]

    def test_attaches_links_by_label(self):
        tracks = [("2024-01-01 Morning Run", [[45.0, -122.0, 5.0, 150, 100.0]])]
        url = STRAVA_ACTIVITY_URL.format(activity_id=42)

        activities = build_activities(tracks, {"2024-01-01 Morning Run": url})

        assert activities[0][4] == url

    def test_attaches_types_by_label(self):
        """The type backs the popup's filter chips, so it rides in the record."""
        tracks = [("2024-01-01 Morning Run", [[45.0, -122.0, 5.0, 150, 100.0]])]

        activities = build_activities(tracks, None, {"2024-01-01 Morning Run": "Run"})

        assert activities[0][5] == "Run"

    def test_unknown_type_is_an_empty_string(self):
        assert build_activities([("custom", [[45.0, -122.0]])])[0][5] == ""


class TestBuildActivityTypes:
    """Activity types come from the export's Activity Type column."""

    def test_maps_types_to_labels(self):
        runs = pd.DataFrame(
            {
                "Activity Date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
                "Activity Name": ["Morning Run", "Evening Ride"],
                "Activity Type": ["Run", "Ride"],
            }
        )

        types = build_activity_types(runs)

        assert types == {"2024-01-01 Morning Run": "Run", "2024-01-02 Evening Ride": "Ride"}

    def test_returns_empty_without_the_column(self):
        runs = pd.DataFrame(
            {
                "Activity Date": pd.to_datetime(["2024-01-01"]),
                "Activity Name": ["Morning Run"],
            }
        )
        assert build_activity_types(runs) == {}

    def test_returns_empty_for_none(self):
        assert build_activity_types(None) == {}


class TestBuildActivityIndex:
    """The embedded payload: geometry + activities + flat cell memberships."""

    def _build(self, tracks, cells):
        return json.loads(
            build_activity_index(
                tracks,
                cells,
                x_min_wm=-1000.0,
                y_max_wm=2000.0,
                meters_per_pixel=10.0,
                grid_w=100,
                grid_h=50,
                links={"2024-01-01 Morning Run": STRAVA_ACTIVITY_URL.format(activity_id=42)},
                types={"2024-01-01 Morning Run": "Run"},
            )
        )

    def test_carries_the_grid_geometry(self):
        payload = self._build([], {})
        assert payload["cellSize"] == 10.0
        assert payload["xMin"] == -1000.0
        assert payload["yMax"] == 2000.0
        assert payload["cols"] == 100
        assert payload["rows"] == 50

    def test_keys_cells_by_row_major_index(self):
        tracks = [("2024-01-01 Morning Run", [[45.0, -122.0, 5.0, 150, 100.0]])]
        payload = self._build(tracks, {(3, 7): {0}, (0, 0): {0}})

        assert payload["cells"] == {"307": [0], "0": [0]}

    def test_activity_records_are_positional(self):
        tracks = [("2024-01-01 Morning Run", [[45.0, -122.0, 5.0, 150, 100.0]])]
        payload = self._build(tracks, {})

        record = payload["activities"][0]
        assert record[0] == "2024-01-01"
        assert record[1] == "Morning Run"
        assert record[2] == "3:20/km"
        assert record[3] == 150
        assert record[4] == STRAVA_ACTIVITY_URL.format(activity_id=42)
        assert record[5] == "Run"

    def test_skips_empty_cell_memberships(self):
        payload = self._build([], {(1, 1): set()})
        assert payload["cells"] == {}

    def test_cell_members_are_sorted(self):
        payload = self._build([], {(0, 0): {3, 1, 2}})
        assert payload["cells"]["0"] == [1, 2, 3]

    def test_is_minified_json(self):
        text = build_activity_index(
            [], {}, x_min_wm=0.0, y_max_wm=0.0, meters_per_pixel=1.0, grid_w=1, grid_h=1
        )
        assert "\n" not in text
        assert ", " not in text
        assert json.loads(text)["cols"] == 1

    @pytest.mark.parametrize("grid_w", [1, 500])
    def test_cell_keys_fit_the_declared_width(self, grid_w):
        payload = json.loads(
            build_activity_index(
                [],
                {(1, 2): {0}},
                x_min_wm=0.0,
                y_max_wm=0.0,
                meters_per_pixel=1.0,
                grid_w=grid_w,
                grid_h=10,
            )
        )
        assert payload["cells"] == {str(1 * grid_w + 2): [0]}
