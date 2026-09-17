"""
Pipeline Stage 2b: GPX Track Re-export
Writes the filtered GPS tracks back out as a single GPX file — one ``<trk>`` per
activity — so the very activities the heatmap is built from can be opened in
other tools (Garmin Connect, QGIS, gpsbabel, GPX viewers, ...).

The input is the ``(label, points)`` list returned by
``data_loader.load_tracks``: exactly the activities that survived the type /
date / home-radius filters. Each point is ``[lat, lon, speed, hr, alt]``.

Strava's export files do not keep per-point timestamps, so the output carries
geometry, elevation and — through the Garmin TrackPointExtension — heart rate and
speed, but no ``<time>`` elements. The file is therefore valid GPX 1.1 that every
consumer accepts, and honest about what is actually known.

Unlike the GeoJSON grid export (which is embedded in the HTML), this file is
written to disk next to the map, because its whole purpose is being handed to
another program. The document is streamed rather than assembled in memory:
a dense export can hold millions of track points.
"""

import logging
from collections.abc import Iterator
from pathlib import Path
from xml.sax.saxutils import escape

log = logging.getLogger(__name__)

# Provenance written into the <gpx creator> attribute.
GPX_CREATOR = "strava-heatmap"

_GPX_NS = "http://www.topografix.com/GPX/1/1"
_GPX_SCHEMA = "http://www.topografix.com/GPX/1/1/gpx.xsd"
# Garmin's TrackPointExtension is the de-facto home for heart rate and speed,
# which GPX 1.1 itself has no elements for.
_TPX_NS = "http://www.garmin.com/xmlschemas/TrackPointExtension/v2"

DEFAULT_TITLE = "Strava heatmap tracks"

# Coordinate precision: 7 decimal degrees is ~1 cm, finer than consumer GPS, and
# well inside the range tools such as gpsbabel round-trip cleanly.
_COORD_DECIMALS = 7
_ELEV_DECIMALS = 1
_SPEED_DECIMALS = 3


def _point_values(point: list) -> tuple:
    """Split one ``[lat, lon, speed, hr, alt]`` point, tolerating short tuples.

    Points missing the optional trailing fields (older cache entries, or a point
    built by hand) are treated as having no speed / heart rate / elevation
    rather than failing the whole export.
    """
    lat, lon = point[0], point[1]
    speed = point[2] if len(point) > 2 else None
    hr = point[3] if len(point) > 3 else None
    alt = point[4] if len(point) > 4 else None
    return lat, lon, speed, hr, alt


def _trkpt_xml(point: list) -> str:
    """Render one ``<trkpt>`` element, or an empty string for a point without a fix."""
    lat, lon, speed, hr, alt = _point_values(point)
    if lat is None or lon is None:
        return ""

    lat_s = f"{float(lat):.{_COORD_DECIMALS}f}"
    lon_s = f"{float(lon):.{_COORD_DECIMALS}f}"
    parts = [f'<trkpt lat="{lat_s}" lon="{lon_s}">']
    if alt is not None:
        parts.append(f"<ele>{float(alt):.{_ELEV_DECIMALS}f}</ele>")

    if hr is not None or speed is not None:
        parts.append("<extensions><gpxtpx:TrackPointExtension>")
        if hr is not None:
            parts.append(f"<gpxtpx:hr>{int(round(float(hr)))}</gpxtpx:hr>")
        if speed is not None:
            parts.append(f"<gpxtpx:speed>{float(speed):.{_SPEED_DECIMALS}f}</gpxtpx:speed>")
        parts.append("</gpxtpx:TrackPointExtension></extensions>")

    parts.append("</trkpt>\n")
    return "".join(parts)


def _iter_header(title: str) -> Iterator[str]:
    """Yield the XML declaration, ``<gpx>`` opening tag and ``<metadata>``."""
    yield '<?xml version="1.0" encoding="UTF-8"?>\n'
    yield (
        f'<gpx version="1.1" creator="{GPX_CREATOR}"\n'
        f'    xmlns="{_GPX_NS}"\n'
        '    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        f'    xsi:schemaLocation="{_GPX_NS} {_GPX_SCHEMA}"\n'
        f'    xmlns:gpxtpx="{_TPX_NS}">\n'
        f"  <metadata>\n    <name>{escape(str(title))}</name>\n  </metadata>\n"
    )


def _iter_track(label: str, points: list) -> Iterator[str]:
    """Yield one ``<trk>`` element, named after the activity label."""
    yield f"  <trk>\n    <name>{escape(str(label))}</name>\n    <trkseg>\n"
    for point in points:
        xml = _trkpt_xml(point)
        if xml:
            yield "      " + xml
    yield "    </trkseg>\n  </trk>\n"


def _has_fix(point: list) -> bool:
    """Whether a point carries the lat/lon pair that makes it writable."""
    return point[0] is not None and point[1] is not None


def iter_gpx(tracks: list[tuple[str, list]], title: str = DEFAULT_TITLE) -> Iterator[str]:
    """Yield the GPX document in chunks, without building it all in memory.

    Args:
        tracks: ``(label, points)`` pairs from ``data_loader.load_tracks``. Each
            label becomes a ``<trk><name>`` so activities stay distinguishable
            in the consuming tool.
        title: Human-readable ``<metadata><name>`` for the whole file.

    Yields:
        Successive pieces of the GPX 1.1 document.
    """
    yield from _iter_header(title)
    for label, points in tracks:
        yield from _iter_track(label, points)
    yield "</gpx>\n"


def build_gpx(tracks: list[tuple[str, list]], title: str = DEFAULT_TITLE) -> str:
    """Return the whole GPX document as a string (handy for tests and small sets).

    Args:
        tracks: ``(label, points)`` pairs from ``data_loader.load_tracks``.
        title: ``<metadata><name>`` for the file.

    Returns:
        The GPX 1.1 document, one ``<trk>`` per input track.
    """
    return "".join(iter_gpx(tracks, title))


def write_gpx(
    tracks: list[tuple[str, list]], path: Path, title: str = DEFAULT_TITLE
) -> tuple[int, int]:
    """Stream the filtered tracks to ``path`` as one GPX file.

    Args:
        tracks: ``(label, points)`` pairs from ``data_loader.load_tracks``.
        path: Destination file; missing parent directories are created.
        title: ``<metadata><name>`` for the file.

    Returns:
        ``(tracks_written, points_written)``, for progress reporting. The point
        count is what actually landed in the file: a point without a fix (which
        the parsers already drop) is not given a ``<trkpt>``.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n_points = 0
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(_iter_header(title))
        for label, points in tracks:
            f.writelines(_iter_track(label, points))
            n_points += sum(1 for point in points if _has_fix(point))
        f.write("</gpx>\n")

    n_tracks = len(tracks)
    log.info(f"GPX export: {n_tracks} tracks, {n_points} track points -> {path}")
    return n_tracks, n_points
