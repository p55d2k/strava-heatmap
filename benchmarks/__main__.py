"""
Run the benchmark suite: ``uv run python -m benchmarks``.

Writes a human-readable table, optionally a JSON report (``--json``) to keep as
a baseline for a release, and optionally compares against a stored baseline
(``--baseline``) to flag runtime/memory regressions.
"""

import argparse
import json
import sys
from pathlib import Path

from benchmarks.suite import (
    DEFAULT_END_TO_END_SCENARIOS,
    SCENARIOS,
    compare_results,
    run_benchmarks,
)

_METRIC_COLUMNS = (
    ("seconds_min", "min s", "{:>9.4f}"),
    ("seconds_median", "median s", "{:>9.4f}"),
    ("peak_mb", "peak MB", "{:>9.3f}"),
    ("peak_rss_delta_mb", "rss MB", "{:>8.3f}"),
)


def _print_report(report: dict) -> None:
    env = report["environment"]
    print(f"Benchmarks (Python {env['python']}, {env['platform']}, repeat={env['repeat']})\n")
    header = f"{'stage':<24}" + "".join(f"{label:>12}" for _, label, _ in _METRIC_COLUMNS)
    for scenario, data in report["scenarios"].items():
        export = data["export"]
        print(f"[{scenario}] {export['activities']} activities, {export['points']:,} points")
        print(header)
        for stage, metrics in data["stages"].items():
            row = f"{stage:<24}"
            row += "".join(fmt.format(metrics.get(key, 0.0)) for key, _, fmt in _METRIC_COLUMNS)
            extra = []
            if "grid" in metrics:
                extra.append(f"grid {metrics['grid'][0]}x{metrics['grid'][1]}")
            if "html_bytes" in metrics:
                extra.append(f"html {metrics['html_bytes'] / 1024:.0f} KB")
            if "points_per_run" in metrics:
                extra.append(f"{metrics['points_per_run']:,} pts")
            print(row + ("   " + ", ".join(extra) if extra else ""))
        print()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=["small", "medium", "large"],
        choices=sorted(SCENARIOS),
        help="Scenario sizes to run (default: all)",
    )
    parser.add_argument("--repeat", type=int, default=3, help="Timed repetitions per stage")
    parser.add_argument(
        "--end-to-end",
        nargs="*",
        default=list(DEFAULT_END_TO_END_SCENARIOS),
        choices=sorted(SCENARIOS),
        help="Scenarios to run the full CLI pipeline for (default: small medium)",
    )
    parser.add_argument("--json", type=Path, default=None, help="Write the report as JSON here")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Compare against a previously saved JSON report",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=15.0,
        help="Regression threshold in percent (default: 15)",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit non-zero when a regression exceeds --threshold",
    )
    args = parser.parse_args(argv)

    report = run_benchmarks(
        scenario_names=args.scenarios,
        repeat=args.repeat,
        end_to_end_scenarios=set(args.end_to_end),
    )
    _print_report(report)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote report to {args.json}")

    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        regressions = compare_results(report, baseline, threshold_pct=args.threshold)
        if regressions:
            print(f"Regressions over {args.threshold:.0f}% vs {args.baseline}:")
            for item in regressions:
                print(
                    f"  {item['scenario']}/{item['stage']} {item['metric']}: "
                    f"{item['baseline']} -> {item['current']} (+{item['change_pct']}%)"
                )
            if args.fail_on_regression:
                return 1
        else:
            print(f"No regressions over {args.threshold:.0f}% vs {args.baseline}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
