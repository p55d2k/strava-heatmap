"""
Tests for src/timeline.py - period buckets for the map's timeline control.
"""

from datetime import date, datetime

from src.timeline import build_timeline


class TestBuildTimeline:
    """Period bucket generation for each granularity."""

    def test_none_without_dates(self):
        """No usable dates means no control."""
        assert build_timeline([]) is None
        assert build_timeline(["", None, "not-a-date"]) is None

    def test_year_buckets_cover_the_span(self):
        payload = build_timeline(["2022-05-01", "2024-03-02"], "year")

        years = payload["periods"]["year"]
        assert [b["label"] for b in years] == ["2022", "2023", "2024"]
        assert [b["to"] for b in years] == ["2022-12-31", "2023-12-31", "2024-12-31"]

    def test_month_buckets_cross_a_year_boundary(self):
        payload = build_timeline(["2023-11-15", "2024-02-03"], "month")

        months = payload["periods"]["month"]
        assert [b["label"] for b in months] == ["2023-11", "2023-12", "2024-01", "2024-02"]
        assert [b["to"] for b in months] == ["2023-11-30", "2023-12-31", "2024-01-31", "2024-02-29"]

    def test_week_buckets_end_on_sunday(self):
        payload = build_timeline(["2024-01-03", "2024-01-20"], "week")

        weeks = payload["periods"]["week"]
        assert [b["label"] for b in weeks] == ["2024-W01", "2024-W02", "2024-W03"]
        # Weeks run Monday..Sunday, so each period ends on the Sunday.
        assert [b["to"] for b in weeks] == ["2024-01-07", "2024-01-14", "2024-01-21"]

    def test_default_period_is_reported_and_falls_back(self):
        assert build_timeline(["2024-01-01"], "week")["default"] == "week"
        # Unknown granularity falls back to the month default.
        assert build_timeline(["2024-01-01"], "fortnight")["default"] == "month"

    def test_accepts_datetimes_dates_and_strings(self):
        payload = build_timeline(
            [datetime(2024, 3, 1, 12, 0), date(2024, 1, 1), "2024-02-01"],
            "month",
        )

        assert [b["label"] for b in payload["periods"]["month"]] == [
            "2024-01",
            "2024-02",
            "2024-03",
        ]

    def test_single_day_still_yields_one_bucket_each(self):
        payload = build_timeline(["2024-06-15"], "month")

        assert payload["periods"]["year"] == [{"label": "2024", "to": "2024-12-31"}]
        assert payload["periods"]["month"] == [{"label": "2024-06", "to": "2024-06-30"}]
        assert payload["periods"]["week"] == [{"label": "2024-W24", "to": "2024-06-16"}]
