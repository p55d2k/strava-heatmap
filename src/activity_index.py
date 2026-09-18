"""
Pipeline Stage 3c: Per-cell activity index for the map's click tooltips.

The generated map lets a visitor click a painted heatmap pixel and see which
activities passed through it. Doing that in the browser needs two things the
page does not otherwise carry:

* a small record per activity (date, name, average pace, average heart rate and
  the Strava link when the export has an activity id), and
* a mapping from each rasterized grid cell to the activities that visited it.

Both are assembled here as one compact JSON document. The rasterizer already
knows which cells each activity touches (see
``rasterizer.rasterize_tracks(cell_activities=...)``), so the index reuses that
instead of re-walking every track. The document is embedded in the page
zlib-compressed and base64-encoded — the same treatment as the GeoJSON and GPX
exports — and inflated lazily in the browser on the first click.

The cell key is ``row * grid_width + col`` with ``(row, col)`` the same
"nearest cell" coordinates the rasterizer bins points into, so a click can be
resolved to a key by converting its WGS84 lat/lng to Web Mercator and rounding.
"""

import json
import logging

import pandas as pd

from src.map_builder.legend import pace_str

log = logging.getLogger(__name__)

# Strava's public activity URL; an export's "Activity ID" column is the only
# piece of the page that can be turned into a link back to strava.com.
STRAVA_ACTIVITY_URL = "https://www.strava.com/activities/{activity_id}"


def activity_label(activity_date, activity_name) -> str:
    """Return the label ``load_tracks`` gives an activity's track.

    Kept in one place so the links keyed here and the labels the loader builds
    cannot drift apart: the loader uses ``f"{row['Activity Date'].date()} {row['Activity Name']}"``.
    """
    return f"{pd.Timestamp(activity_date).date()} {activity_name}"


def split_activity_label(label: str) -> tuple[str, str]:
    """Split a track label into ``(date, name)``, tolerating bespoke labels.

    The loader always builds ``"YYYY-MM-DD Name"``, but the map builder can also
    be called with hand-made labels; anything unrecognised returns an empty date
    so the popup simply omits it rather than showing a bogus one.
    """
    text = str(label or "")
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10], text[11:].strip()
    return "", text.strip()


def _clean_activity_id(value) -> str:
    """Return a Strava activity id as a digit string, or ``""`` when unusable.

    Values arrive as ints from a clean export, but pandas turns the column into
    floats (with ``NaN`` for blank rows) as soon as one activity has no id, so
    both shapes are handled.
    """
    try:
        if value is None or pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return ""
    if isinstance(value, float):
        return str(int(value))
    return str(value).strip()


def build_strava_links(runs) -> dict[str, str]:
    """Map every activity's track label to its Strava activity URL.

    Args:
        runs: The filtered activities DataFrame passed to ``load_tracks``. The
            ``Activity ID`` column is optional — exports produced by other
            tools, and the test fixtures, often omit it.

    Returns:
        ``{label: url}`` for the activities that carry a usable id. An empty
        mapping means no popup row can be linked back to Strava, which the
        browser then simply leaves out.
    """
    links: dict[str, str] = {}
    if runs is None or "Activity ID" not in getattr(runs, "columns", []):
        return links

    for _, row in runs.iterrows():
        activity_id = _clean_activity_id(row.get("Activity ID"))
        if not activity_id:
            continue
        name = row.get("Activity Name")
        date = row.get("Activity Date")
        if name is None or pd.isna(name) or date is None or pd.isna(date):
            continue
        links[activity_label(date, name)] = STRAVA_ACTIVITY_URL.format(activity_id=activity_id)
    return links


def build_activity_types(runs) -> dict[str, str]:
    """Map every activity's track label to its (normalized) activity type.

    The loader normalizes the CSV's ``Activity Type`` to canonical Strava names
    before anything else runs, so grouping here is already sensible: a verbose
    export label such as "Running" reads as ``Run``, and the popup's type filter
    therefore groups equivalent spellings automatically.

    Args:
        runs: The filtered activities DataFrame passed to ``load_tracks``.
            ``Activity Type`` is optional so a hand-made frame still works.

    Returns:
        ``{label: type}`` for the activities that carry a type.
    """
    types: dict[str, str] = {}
    if runs is None or "Activity Type" not in getattr(runs, "columns", []):
        return types

    for _, row in runs.iterrows():
        name = row.get("Activity Name")
        date = row.get("Activity Date")
        activity_type = row.get("Activity Type")
        if name is None or pd.isna(name) or date is None or pd.isna(date):
            continue
        if activity_type is None or pd.isna(activity_type):
            continue
        types[activity_label(date, name)] = str(activity_type).strip()
    return types


def _as_float(value) -> float | None:
    """Return ``value`` as a float, or ``None`` when it is not a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _point_metric_averages(points) -> tuple[str, int | None]:
    """Return ``(pace, heart rate)`` averaged over one activity's track points.

    Points are ``[lat, lon, speed, hr, alt]`` with any optional field possibly
    ``None``. Speed samples of zero or less are dropped (they are pauses, not
    movement) so the pace reflects how the activity was actually travelled; an
    activity whose device recorded no speed gets an empty pace, and its row then
    shows only what is known.
    """
    speeds: list[float] = []
    heart_rates: list[float] = []
    for point in points or []:
        speed = _as_float(point[2]) if len(point) > 2 else None
        if speed is not None and speed > 0:
            speeds.append(speed)
        heart_rate = _as_float(point[3]) if len(point) > 3 else None
        if heart_rate is not None:
            heart_rates.append(heart_rate)

    pace = pace_str(sum(speeds) / len(speeds)) if speeds else ""
    heart_rate = int(round(sum(heart_rates) / len(heart_rates))) if heart_rates else None
    return pace, heart_rate


def build_activities(
    tracks,
    links: dict[str, str] | None = None,
    types: dict[str, str] | None = None,
) -> list[list]:
    """Build the popup record for every track, in the map's activity order.

    Each record is a fixed-length list ``[date, name, pace, hr, url, type]``
    (rather than an object) because the same keys would otherwise be repeated
    for every activity in the embedded payload. The index's cell memberships
    reference activities by their position in this list.

    The date and type exist so the browser can filter a popup's list without
    another round trip: the date bounds a range comparison, and the type backs
    the type chips. Unknown values are empty strings, which the browser treats
    as "no type" (and can still list).
    """
    link_map = links or {}
    type_map = types or {}
    activities: list[list] = []
    for label, points in tracks:
        date, name = split_activity_label(label)
        pace, heart_rate = _point_metric_averages(points)
        activities.append(
            [date, name, pace, heart_rate, link_map.get(label, ""), type_map.get(label, "")]
        )
    return activities


def build_activity_index(
    tracks,
    cell_activities: dict[tuple[int, int], set[int]],
    *,
    x_min_wm: float,
    y_max_wm: float,
    meters_per_pixel: float,
    grid_w: int,
    grid_h: int,
    links: dict[str, str] | None = None,
    types: dict[str, str] | None = None,
) -> str:
    """Assemble the click-tooltip index as a minified JSON string.

    Args:
        tracks: ``(label, points)`` pairs from ``data_loader.load_tracks``.
        cell_activities: Mapping from ``(row, col)`` to the set of track indices
            that visited the cell, as collected by ``rasterize_tracks``.
        x_min_wm: Western edge of the raster grid in Web Mercator metres.
        y_max_wm: Northern edge of the raster grid in Web Mercator metres.
        meters_per_pixel: Raster cell size in metres.
        grid_w: Grid width in cells (columns).
        grid_h: Grid height in cells (rows).
        links: Optional ``{label: url}`` map from :func:`build_strava_links`.
        types: Optional ``{label: type}`` map from :func:`build_activity_types`.

    Returns:
        A minified JSON payload carrying the grid geometry, the per-activity
        records and the cell memberships. ``cells`` is keyed by
        ``row * grid_w + col`` so the browser can address it as a flat object.
    """
    activities = build_activities(tracks, links, types)

    cells: dict[str, list[int]] = {}
    for (row, col), members in cell_activities.items():
        if not members:
            continue
        cells[str(int(row) * int(grid_w) + int(col))] = sorted(int(index) for index in members)

    payload = {
        "cellSize": float(meters_per_pixel),
        "xMin": float(x_min_wm),
        "yMax": float(y_max_wm),
        "cols": int(grid_w),
        "rows": int(grid_h),
        "activities": activities,
        "cells": cells,
    }
    log.info(
        "Activity tooltip index: %d activities across %d grid cells",
        len(activities),
        len(cells),
    )
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
