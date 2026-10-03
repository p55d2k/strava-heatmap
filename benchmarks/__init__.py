"""
Repeatable performance benchmarks for the Strava heatmap pipeline.

The suite synthesises its own Strava-shaped export (real ``.fit.gz`` / ``.gpx``
files plus ``activities.csv``), so it needs no private Strava data and produces
comparable numbers between runs and releases. Run it with::

    uv run python -m benchmarks

See ``benchmarks/__main__.py`` for the CLI options (scenario selection, repeat
count, JSON output and baseline comparison).
"""
