"""
Tests for the benchmarks package: synthetic data, the suite and comparison.

These keep the benchmark harness itself honest (the synthetic FIT/GPX files
parse, the suite returns sane numbers, and regression detection works) without
running the full default ladder.
"""

import json

import pytest

from benchmarks.suite import compare_results, run_benchmarks
from benchmarks.synthetic import (
    SCENARIOS,
    build_fit_bytes,
    build_gpx_text,
    generate_export,
    scenario_route,
)
from src.helpers import parse_fit_file, parse_gpx_file


class TestSyntheticData:
    """The generated files must be readable by the real parsers."""

    def test_fit_bytes_parse_back(self, tmp_path):
        points = [(45.0, -122.0, 100.0, 150), (45.001, -122.001, 105.0, 145)]
        path = tmp_path / "track.fit.gz"
        import gzip

        with gzip.open(path, "wb") as handle:
            handle.write(build_fit_bytes(points))

        parsed = parse_fit_file(path)

        assert parsed.shape == (2, 5)
        assert parsed[0][0] == pytest.approx(45.0, abs=1e-5)
        assert parsed[0][1] == pytest.approx(-122.0, abs=1e-5)
        assert parsed[0][3] == 150  # heart rate
        assert parsed[0][4] == pytest.approx(100.0, abs=0.2)  # altitude decoded

    def test_gpx_text_parses_back(self, tmp_path):
        points = [(45.0, -122.0, 100.0, 150)]
        path = tmp_path / "track.gpx"
        path.write_text(build_gpx_text(points), encoding="utf-8")

        parsed = parse_gpx_file(path)

        assert parsed.shape == (1, 5)
        assert parsed[0][0] == pytest.approx(45.0, abs=1e-6)
        assert parsed[0][3] == 150

    def test_scenario_route_is_bounded_and_scales(self):
        small = scenario_route(SCENARIOS["small"])
        large = scenario_route(SCENARIOS["large"])

        assert len(small) == SCENARIOS["small"].points_per_activity
        assert len(large) == SCENARIOS["large"].points_per_activity
        lats = [p[0] for p in large]
        # Bounded regardless of point count (keeps the benchmark grid renderable).
        assert max(lats) - min(lats) < 0.05

    def test_generate_export_writes_everything(self, tmp_path):
        export = generate_export(tmp_path, SCENARIOS["tiny"])

        assert export.activities_csv.is_file()
        assert export.config_path.is_file()
        assert export.cache_dir.is_dir()
        assert len(export.filenames) == SCENARIOS["tiny"].n_activities
        assert all((export.activities_dir / name).is_file() for name in export.filenames)


class TestRunBenchmarks:
    """The suite runs end to end and returns a JSON-serialisable report."""

    def test_small_run_reports_every_stage(self):
        report = run_benchmarks(scenario_names=["tiny"], repeat=1, end_to_end_scenarios=set())

        assert "environment" in report
        stages = report["scenarios"]["tiny"]["stages"]
        assert set(stages) == {
            "fit_parsing",
            "activity_normalization",
            "rasterization",
            "map_generation",
        }
        for metrics in stages.values():
            assert metrics["seconds_min"] > 0
            assert metrics["seconds_median"] > 0
            assert metrics["peak_mb"] >= 0

        # Must survive a JSON round trip for storing/loading baselines.
        json.dumps(report)

    def test_rejects_unknown_scenario(self):
        with pytest.raises(ValueError, match="Unknown scenario"):
            run_benchmarks(scenario_names=["nope"], repeat=1)


class TestCompareResults:
    """Regression detection between two reports."""

    @staticmethod
    def _report(seconds: float, peak_mb: float) -> dict:
        return {
            "scenarios": {
                "tiny": {"stages": {"fit_parsing": {"seconds_min": seconds, "peak_mb": peak_mb}}}
            }
        }

    def test_flags_runtime_regression(self):
        current = self._report(seconds=1.5, peak_mb=10.0)
        baseline = self._report(seconds=1.0, peak_mb=10.0)

        regressions = compare_results(current, baseline, threshold_pct=15.0)

        assert len(regressions) == 1
        assert regressions[0]["metric"] == "seconds_min"
        assert regressions[0]["change_pct"] == pytest.approx(50.0, abs=0.1)

    def test_flags_memory_regression(self):
        current = self._report(seconds=1.0, peak_mb=20.0)
        baseline = self._report(seconds=1.0, peak_mb=10.0)

        regressions = compare_results(current, baseline, threshold_pct=15.0)

        assert [r["metric"] for r in regressions] == ["peak_mb"]

    def test_ignores_changes_within_threshold(self):
        current = self._report(seconds=1.05, peak_mb=10.0)
        baseline = self._report(seconds=1.0, peak_mb=10.0)

        assert compare_results(current, baseline, threshold_pct=15.0) == []

    def test_ignores_improvements(self):
        current = self._report(seconds=0.5, peak_mb=5.0)
        baseline = self._report(seconds=1.0, peak_mb=10.0)

        assert compare_results(current, baseline, threshold_pct=15.0) == []
