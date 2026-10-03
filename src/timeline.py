"""
Period buckets for the map's timeline control.

The timeline animates how coverage grew over time. It aggregates by activity
date — every activity has exactly one date, so year / month / week buckets need
no per-point timestamps — and provides, for each granularity, the ordered list
of periods together with the inclusive end date the browser filters up to
(a cumulative "coverage so far" view).

The buckets are computed here and embedded in the page; the browser then
re-rasterizes the density / coverage layers from the per-activity cell counts it
already carries (see :mod:`src.activity_index`), so the timeline needs no
server round trip.
"""

import calendar
from datetime import date, datetime, timedelta

# Granularities the panel offers, in the order shown.
TIMELINE_PERIODS = ("year", "month", "week")
DEFAULT_TIMELINE_PERIOD = "month"


def _coerce(value) -> date | None:
    """Return ``value`` as a ``date``, or ``None`` when it cannot be parsed."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _year_buckets(first: date, last: date) -> list[dict]:
    return [
        {"label": str(year), "to": date(year, 12, 31).isoformat()}
        for year in range(first.year, last.year + 1)
    ]


def _month_buckets(first: date, last: date) -> list[dict]:
    buckets = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        buckets.append(
            {"label": f"{year:04d}-{month:02d}", "to": _month_end(year, month).isoformat()}
        )
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return buckets


def _week_buckets(first: date, last: date) -> list[dict]:
    buckets = []
    cursor = first - timedelta(days=first.weekday())  # Monday of the first week
    while cursor <= last:
        iso_year, iso_week, _ = cursor.isocalendar()
        buckets.append(
            {
                "label": f"{iso_year:04d}-W{iso_week:02d}",
                "to": (cursor + timedelta(days=6)).isoformat(),  # Sunday
            }
        )
        cursor += timedelta(days=7)
    return buckets


def build_timeline(dates, default_period: str = DEFAULT_TIMELINE_PERIOD) -> dict | None:
    """Return the timeline payload for the given activity dates, or ``None``.

    Args:
        dates: Anything date-like — the ``YYYY-MM-DD`` strings / timestamps the
            activity labels carry.
        default_period: Granularity selected first (``year`` / ``month`` /
            ``week``); falls back to :data:`DEFAULT_TIMELINE_PERIOD` when unknown.

    Returns:
        ``{"default": <period>, "periods": {"year": [...], "month": [...],
        "week": [...]}}`` where each period is ``{"label", "to"}`` and ``to`` is
        the inclusive end date. ``None`` when no valid date is supplied, so the
        caller can simply omit the control.
    """
    days = sorted({day for day in (_coerce(value) for value in dates) if day is not None})
    if not days:
        return None

    first, last = days[0], days[-1]
    if default_period not in TIMELINE_PERIODS:
        default_period = DEFAULT_TIMELINE_PERIOD

    return {
        "default": default_period,
        "periods": {
            "year": _year_buckets(first, last),
            "month": _month_buckets(first, last),
            "week": _week_buckets(first, last),
        },
    }
