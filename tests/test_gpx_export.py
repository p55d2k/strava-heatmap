"""
Tests for src/gpx_export.py - filtered tracks re-exported as one GPX file.

The document is written by hand (so it can be streamed for large exports), so
the tests check it from both ends: the raw XML with ElementTree, and the
document as an external tool would read it, through gpxpy.
"""

import xml.etree.ElementTree as ET

import gpxpy
import pytest

from src.gpx_export import DEFAULT_TITLE, GPX_CREATOR, build_gpx, write_gpx

GPX_NS = "http://www.topografix.com/GPX/1/1"
TPX_NS = "http://www.garmin.com/xmlschemas/TrackPointExtension/v2"

# Two activities shaped like data_loader.load_tracks output: the label is
# "<date> <name>" and each point is [lat, lon, speed, hr, alt], where the three
# trailing fields may be None. The second label carries characters that must be
# escaped in XML.
TRACKS = [
    (
        "2024-01-01 Morning Run",
        [
            [45.0, -122.0, 5.0, 150, 100.0],
            [45.001, -122.001, None, None, 101.0],
            [45.002, -122.002, 8.25, 151, None],
        ],
    ),
    ("2024-01-02 Evening & Ride <hard>", [[45.1, -122.1, 8.0, 140, 105.0]]),
]


def _tracks(markup: str) -> list[ET.Element]:
    return ET.fromstring(markup).findall(f"{{{GPX_NS}}}trk")


def _track_points(markup: str, track_index: int = 0) -> list[ET.Element]:
    return _tracks(markup)[track_index].findall(f"{{{GPX_NS}}}trkseg/{{{GPX_NS}}}trkpt")


def _extension_values(markup: str, tag: str) -> list[str | None]:
    """Every text value of ``<tag>`` in the Garmin TrackPointExtension namespace."""
    return [el.text for el in ET.fromstring(markup).iter(f"{{{TPX_NS}}}{tag}")]


def test_gpxpy_reads_every_activity_and_point():
    """The document is valid GPX a reader library round-trips, one trk per activity."""
    gpx = gpxpy.parse(build_gpx(TRACKS))

    assert len(gpx.tracks) == 2
    assert [track.name for track in gpx.tracks] == [label for label, _ in TRACKS]
    assert [len(track.segments[0].points) for track in gpx.tracks] == [3, 1]

    points = gpx.tracks[0].segments[0].points
    assert points[0].latitude == pytest.approx(45.0, abs=1e-7)
    assert points[0].longitude == pytest.approx(-122.0, abs=1e-7)
    # Elevation survives; a point without altitude has none.
    assert points[0].elevation == pytest.approx(100.0)
    assert points[1].elevation == pytest.approx(101.0)
    assert points[2].elevation is None


def test_document_declares_gpx_1_1_and_the_extension_namespace():
    """The root declares the GPX 1.1 namespace and the Garmin extension prefix."""
    markup = build_gpx(TRACKS)

    assert markup.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert f'xmlns="{GPX_NS}"' in markup
    assert f'xmlns:gpxtpx="{TPX_NS}"' in markup
    root = ET.fromstring(markup)
    assert root.tag == f"{{{GPX_NS}}}gpx"
    assert root.attrib["version"] == "1.1"
    assert root.attrib["creator"] == GPX_CREATOR


def test_metadata_title_defaults_and_can_be_set():
    """The file carries a <metadata><name>, defaulting to the module constant."""
    default_name = ET.fromstring(build_gpx(TRACKS)).find(f"{{{GPX_NS}}}metadata/{{{GPX_NS}}}name")
    custom_name = ET.fromstring(build_gpx(TRACKS, "Runs around home")).find(
        f"{{{GPX_NS}}}metadata/{{{GPX_NS}}}name"
    )

    assert default_name.text == DEFAULT_TITLE
    assert custom_name.text == "Runs around home"


def test_heart_rate_and_speed_go_into_the_garmin_extension():
    """HR/speed have no GPX 1.1 elements, so they ride in TrackPointExtension."""
    markup = build_gpx(TRACKS)

    assert _extension_values(markup, "hr") == ["150", "151", "140"]
    assert _extension_values(markup, "speed") == ["5.000", "8.250", "8.000"]


def test_point_without_hr_or_speed_carries_no_extensions():
    """A point with neither value gets no <extensions> block at all."""
    points = _track_points(build_gpx(TRACKS))

    assert points[1].find(f"{{{GPX_NS}}}extensions") is None
    assert points[0].find(f"{{{GPX_NS}}}extensions") is not None


def test_elevation_is_omitted_when_unknown():
    """Only points with a known altitude get an <ele> element."""
    points = _track_points(build_gpx(TRACKS))

    assert points[0].findtext(f"{{{GPX_NS}}}ele") == "100.0"
    assert points[2].find(f"{{{GPX_NS}}}ele") is None


def test_labels_are_xml_escaped():
    """Activity names with & or <> stay verbatim in the parsed document."""
    markup = build_gpx(TRACKS)

    assert _tracks(markup)[1].findtext(f"{{{GPX_NS}}}name") == TRACKS[1][0]
    assert "&amp;" in markup
    assert "<hard>" not in markup  # escaped as &lt;hard&gt;


def test_points_without_a_fix_are_dropped():
    """A point with no lat/lon is not written as a <trkpt>."""
    markup = build_gpx([("no fix", [[None, None, 1.0, 120, 5.0]])])

    assert _track_points(markup) == []
    assert len(_tracks(markup)) == 1


def test_short_points_are_tolerated():
    """A bare [lat, lon] point is written without elevation or extensions."""
    points = _track_points(build_gpx([("bare", [[45.0, -122.0]])]))

    assert len(points) == 1
    assert not list(points[0])  # no <ele> and no <extensions>
    assert points[0].attrib["lat"] == "45.0000000"


def test_no_time_elements_are_emitted():
    """Strava's export keeps no per-point timestamps, so neither does the GPX."""
    assert list(ET.fromstring(build_gpx(TRACKS)).iter(f"{{{GPX_NS}}}time")) == []


def test_empty_track_list_is_still_a_valid_document():
    """Nothing to export still produces a parseable, track-less GPX file."""
    markup = build_gpx([])

    assert _tracks(markup) == []
    assert gpxpy.parse(markup).tracks == []


def test_write_gpx_writes_the_same_document_as_build_gpx(tmp_path):
    """The streamed file is byte-for-byte the string builder's output."""
    path = tmp_path / "tracks.gpx"

    counts = write_gpx(TRACKS, path)

    assert counts == (2, 4)  # two activities, four track points
    assert path.read_text(encoding="utf-8") == build_gpx(TRACKS)


def test_write_gpx_counts_only_points_that_are_written(tmp_path):
    """The reported point count matches the <trkpt> elements in the file."""
    path = tmp_path / "tracks.gpx"

    counts = write_gpx([("mixed", [[45.0, -122.0], [None, None]])], path)

    assert counts == (1, 1)


def test_write_gpx_creates_missing_parent_directories(tmp_path):
    """Writing into a subdirectory that does not exist yet still works."""
    path = tmp_path / "gpx" / "nested" / "tracks.gpx"

    write_gpx(TRACKS, path, "Runs")

    assert path.exists()
    assert len(gpxpy.parse(path.read_text(encoding="utf-8")).tracks) == 2


def test_write_gpx_accepts_a_string_path(tmp_path):
    """Callers may pass a str path (as config-derived paths are not always Path)."""
    path = tmp_path / "tracks.gpx"

    assert write_gpx(TRACKS, str(path))[0] == 2
    assert path.exists()
