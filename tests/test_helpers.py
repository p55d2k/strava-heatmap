"""
Unit tests for src/helpers.py - math, parsing, and normalization functions.
"""

import gzip
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.helpers import (
    detect_home,
    get_gps_start,
    haversine_km,
    parse_fit_file,
    parse_gpx_file,
    parse_track_file,
)


class TestHaversineKm:
    """Tests for haversine_km function."""

    def test_same_point_returns_zero(self):
        """Distance between identical points should be 0."""
        assert haversine_km(0, 0, 0, 0) == 0.0
        assert haversine_km(45.0, -122.0, 45.0, -122.0) == 0.0

    def test_known_distances(self):
        """Test against known distances."""
        # Equator: 1 degree longitude ≈ 111.32 km
        dist = haversine_km(0, 0, 0, 1)
        assert abs(dist - 111.32) < 0.5

        # Prime meridian: 1 degree latitude ≈ 111.11 km
        dist = haversine_km(0, 0, 1, 0)
        assert abs(dist - 111.11) < 0.5

    def test_antipodal_points(self):
        """Distance between antipodal points should be ~20015 km (half Earth circumference)."""
        dist = haversine_km(0, 0, 0, 180)
        assert abs(dist - 20015) < 100

    def test_symmetry(self):
        """Distance should be symmetric."""
        d1 = haversine_km(10, 20, 30, 40)
        d2 = haversine_km(30, 40, 10, 20)
        assert abs(d1 - d2) < 1e-10

    def test_north_pole_to_equator(self):
        """Distance from North Pole to equator should be ~10007 km (quarter circumference)."""
        dist = haversine_km(90, 0, 0, 0)
        assert abs(dist - 10007) < 50


class TestParseFitFile:
    """Tests for parse_fit_file function."""

    def test_empty_file_returns_empty_list(self):
        """Empty .fit.gz file should return empty list."""
        with tempfile.NamedTemporaryFile(suffix=".fit.gz", delete=False) as f:
            f.write(gzip.compress(b""))
            temp_path = Path(f.name)

        try:
            result = parse_fit_file(temp_path)
            assert result == []
        finally:
            temp_path.unlink()

    def test_invalid_file_returns_empty_list(self):
        """Invalid .fit.gz file should return empty list (not raise)."""
        with tempfile.NamedTemporaryFile(suffix=".fit.gz", delete=False) as f:
            f.write(gzip.compress(b"not a fit file"))
            temp_path = Path(f.name)

        try:
            result = parse_fit_file(temp_path)
            assert result == []
        finally:
            temp_path.unlink()

    @patch("src.helpers.fitparse.FitFile")
    def test_parses_record_messages(self, mock_fitfile):
        """Should parse record messages and convert coordinates."""

        # Create mock field objects with name and value attributes
        def make_field(name, value):
            field = MagicMock()
            field.name = name
            field.value = value
            return field

        # Mock fitparse to return record messages
        # 1073741824 semicircles = 90 degrees (2^30 / 2^31 * 180)
        # -2147483648 semicircles = -180 degrees (-2^31 / 2^31 * 180)
        mock_msg = MagicMock()
        mock_msg.__iter__ = lambda self: iter(
            [
                make_field("position_lat", 1073741824),  # 90 deg in semicircles
                make_field("position_long", -2147483648),  # -180 deg in semicircles
                make_field("enhanced_speed", 5.0),
                make_field("heart_rate", 150),
                make_field("enhanced_altitude", 100.0),
            ]
        )
        mock_fitfile.return_value.get_messages.return_value = [mock_msg]

        with tempfile.NamedTemporaryFile(suffix=".fit.gz", delete=False) as f:
            f.write(gzip.compress(b"dummy"))
            temp_path = Path(f.name)

        try:
            result = parse_fit_file(temp_path)
            assert len(result) == 1
            lat, lon, speed, hr, alt = result[0]
            assert abs(lat - 90.0) < 0.001
            assert abs(lon - (-180.0)) < 0.001
            assert speed == 5.0
            assert hr == 150
            assert alt == 100.0
        finally:
            temp_path.unlink()

    @patch("src.helpers.fitparse.FitFile")
    def test_skips_records_without_gps(self, mock_fitfile):
        """Should skip records without position data."""

        def make_field(name, value):
            field = MagicMock()
            field.name = name
            field.value = value
            return field

        # First message: no position_lat
        msg1 = MagicMock()
        msg1.__iter__ = lambda self: iter(
            [
                make_field("position_lat", None),
                make_field("position_long", -2147483648),
                make_field("enhanced_speed", 5.0),
            ]
        )

        # Second message: has valid GPS
        msg2 = MagicMock()
        msg2.__iter__ = lambda self: iter(
            [
                make_field("position_lat", 1073741824),
                make_field("position_long", -2147483648),
                make_field("enhanced_speed", 5.0),
            ]
        )

        mock_fitfile.return_value.get_messages.return_value = [msg1, msg2]

        with tempfile.NamedTemporaryFile(suffix=".fit.gz", delete=False) as f:
            f.write(gzip.compress(b"dummy"))
            temp_path = Path(f.name)

        try:
            result = parse_fit_file(temp_path)
            assert len(result) == 1  # Only second record has valid GPS
        finally:
            temp_path.unlink()

    @patch("src.helpers.fitparse.FitFile")
    def test_falls_back_to_speed_if_enhanced_missing(self, mock_fitfile):
        """Should use 'speed' field if 'enhanced_speed' is missing."""

        def make_field(name, value):
            field = MagicMock()
            field.name = name
            field.value = value
            return field

        mock_msg = MagicMock()
        mock_msg.__iter__ = lambda self: iter(
            [
                make_field("position_lat", 1073741824),
                make_field("position_long", -2147483648),
                make_field("enhanced_speed", None),
                make_field("speed", 4.5),
                make_field("heart_rate", None),
                make_field("enhanced_altitude", None),
                make_field("altitude", 50.0),
            ]
        )
        mock_fitfile.return_value.get_messages.return_value = [mock_msg]

        with tempfile.NamedTemporaryFile(suffix=".fit.gz", delete=False) as f:
            f.write(gzip.compress(b"dummy"))
            temp_path = Path(f.name)

        try:
            result = parse_fit_file(temp_path)
            assert len(result) == 1
            assert result[0][2] == 4.5  # speed
            assert result[0][4] == 50.0  # altitude
        finally:
            temp_path.unlink()


class TestGetGpsStart:
    """Tests for get_gps_start function."""

    @patch("src.helpers.parse_fit_file")
    def test_returns_start_and_spread(self, mock_parse):
        """Should return first point lat/lon and spread in meters."""
        mock_parse.return_value = [
            [45.0, -122.0, 5.0, 150, 100.0],
            [45.001, -122.001, 5.0, 150, 101.0],
            [45.002, -122.002, 5.0, 150, 102.0],
        ]

        lat, lon, spread = get_gps_start(Path("dummy.fit.gz"))

        assert lat == 45.0
        assert lon == -122.0
        assert spread > 0  # Should compute spread from min/max

    @patch("src.helpers.parse_fit_file")
    def test_returns_none_for_empty_tracks(self, mock_parse):
        """Should return (None, None, None) for empty tracks."""
        mock_parse.return_value = []

        lat, lon, spread = get_gps_start(Path("dummy.fit.gz"))

        assert lat is None
        assert lon is None
        assert spread is None


class TestDetectHome:
    """Tests for detect_home function."""

    def test_raises_on_empty_dataframe(self):
        """Should raise ValueError for empty DataFrame."""
        import pandas as pd

        df = pd.DataFrame(columns=["start_lat", "start_lon"])

        with pytest.raises(
            ValueError, match="Cannot auto-detect home location: no GPS data available"
        ):
            detect_home(df)

    def test_detects_most_common_start_cell(self):
        """Should detect home as the cell with most starts."""
        import pandas as pd

        # Create data with clear cluster at (45.0, -122.0)
        lats = [45.0] * 10 + [45.5] * 3 + [46.0] * 2
        lons = [-122.0] * 10 + [-122.5] * 3 + [-123.0] * 2
        df = pd.DataFrame({"start_lat": lats, "start_lon": lons})

        home_lat, home_lon, n_starts = detect_home(df)

        assert abs(home_lat - 45.0) < 0.01
        assert abs(home_lon - (-122.0)) < 0.01
        assert n_starts == 10

    def test_averages_within_best_cell(self):
        """Should average coordinates within the best cell."""
        import pandas as pd

        # Points in same ~1km cell (round to 2 decimal places = same cell)
        lats = [45.001, 45.002, 45.003, 45.004]
        lons = [-122.001, -122.002, -122.003, -122.004]
        df = pd.DataFrame({"start_lat": lats, "start_lon": lons})

        home_lat, home_lon, n_starts = detect_home(df)

        assert abs(home_lat - 45.0025) < 0.001
        assert abs(home_lon - (-122.0025)) < 0.001
        assert n_starts == 4


# A Garmin TrackPointExtension as devices, Strava's own GPX export and this
# project's gpx_export.py write it: GPX 1.1 has no <hr>/<speed> elements, so they
# live here instead. The header is swapped per test to exercise other spellings.
_GPX_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1"\n'
    '     xmlns:gpxtpx="{ns}">'
)
_TPX_V2 = "http://www.garmin.com/xmlschemas/TrackPointExtension/v2"
_TPX_V1 = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"


def _gpx_with_body(body: str, ns: str = _TPX_V2) -> str:
    """Wrap track point markup in a valid GPX 1.1 document declaring ``ns``."""
    return f"{_GPX_HEADER.format(ns=ns)}\n  <trk><trkseg>{body}</trkseg></trk>\n</gpx>\n"


def _point(lat: str, lon: str, extensions: str = "", ele: str = "31.4") -> str:
    """One <trkpt> with an optional elevation and extension block."""
    return f'\n    <trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele>{extensions}</trkpt>'


def _tpx(inner: str) -> str:
    """Wrap extension elements in Garmin's ``<gpxtpx:TrackPointExtension>``."""
    return (
        f"<extensions><gpxtpx:TrackPointExtension>{inner}</gpxtpx:TrackPointExtension></extensions>"
    )


class TestParseGpxFile:
    """Tests for parse_gpx_file function."""

    def test_empty_file_returns_empty_list(self):
        """Empty .gpx file should return empty list (invalid XML)."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".gpx", delete=False) as f:
            f.write(b"")
            temp_path = Path(f.name)

        try:
            result = parse_gpx_file(temp_path)
            assert result == []
        finally:
            temp_path.unlink()

    def test_invalid_file_returns_empty_list(self):
        """Invalid .gpx file should return empty list (not raise)."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".gpx", delete=False) as f:
            f.write(b"not a gpx file")
            temp_path = Path(f.name)

        try:
            result = parse_gpx_file(temp_path)
            assert result == []
        finally:
            temp_path.unlink()

    def test_parses_track_points(self):
        """Should parse track points with lat/lon/elevation."""
        import tempfile

        gpx_content = """<?xml version="1.0" encoding="UTF-8"?>
<gpx creator="StravaGPX" version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>test run</name>
    <type>running</type>
    <trkseg>
      <trkpt lat="1.4006150" lon="103.8064370">
        <ele>31.4</ele>
        <time>2025-03-31T02:46:39Z</time>
      </trkpt>
      <trkpt lat="1.4005970" lon="103.8064220">
        <ele>31.4</ele>
        <time>2025-03-31T02:46:40Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""
        with tempfile.NamedTemporaryFile(suffix=".gpx", delete=False) as f:
            f.write(gpx_content.encode())
            temp_path = Path(f.name)

        try:
            result = parse_gpx_file(temp_path)
            assert len(result) == 2
            assert result[0][0] == 1.4006150
            assert result[0][1] == 103.8064370
            assert result[0][4] == 31.4
            assert result[0][2] is None  # speed
            assert result[0][3] is None  # hr
        finally:
            temp_path.unlink()

    def test_reads_hr_and_speed_from_trackpoint_extension(self, temp_dir):
        """HR/speed in a Garmin TrackPointExtension should reach the point tuple."""
        content = _gpx_with_body(
            _point(
                "1.4006",
                "103.8064",
                _tpx("<gpxtpx:hr>142</gpxtpx:hr><gpxtpx:speed>3.25</gpxtpx:speed>"),
            )
            + _point("1.4005", "103.8063", _tpx("<gpxtpx:hr>143</gpxtpx:hr>"))
            + _point("1.4004", "103.8062"),
        )
        path = temp_dir / "run.gpx"
        path.write_text(content)

        result = parse_gpx_file(path)

        assert [p[2] for p in result] == [3.25, None, None]  # speed
        assert [p[3] for p in result] == [142, 143, None]  # hr
        assert [p[4] for p in result] == [31.4, 31.4, 31.4]  # elevation untouched

    def test_reads_extensions_in_v1_namespace(self, temp_dir):
        """Older devices write the same elements in the v1 namespace."""
        content = _gpx_with_body(
            _point("1.4006", "103.8064", _tpx("<gpxtpx:hr>98</gpxtpx:hr>")), ns=_TPX_V1
        )
        path = temp_dir / "run.gpx"
        path.write_text(content)

        _, _, speed, hr, _ = parse_gpx_file(path)[0]

        assert hr == 98
        assert speed is None  # v1 has no speed element

    def test_reads_bare_extension_elements(self, temp_dir):
        """Some writers skip the TrackPointExtension wrapper entirely."""
        content = _gpx_with_body(
            _point("1.4006", "103.8064", "<extensions><hr>155</hr><speed>4.5</speed></extensions>")
        )
        path = temp_dir / "run.gpx"
        path.write_text(content)

        _, _, speed, hr, _ = parse_gpx_file(path)[0]

        assert (speed, hr) == (4.5, 155)

    def test_ignores_other_extension_elements(self, temp_dir):
        """Cadence/temperature extensions are not speed or heart rate."""
        content = _gpx_with_body(
            _point(
                "1.4006",
                "103.8064",
                _tpx("<gpxtpx:cad>85</gpxtpx:cad><gpxtpx:atemp>24.0</gpxtpx:atemp>"),
            )
        )
        path = temp_dir / "run.gpx"
        path.write_text(content)

        _, _, speed, hr, _ = parse_gpx_file(path)[0]

        assert speed is None
        assert hr is None

    def test_ignores_non_numeric_extension_values(self, temp_dir):
        """Empty or unparseable extension text should not fail the file."""
        content = _gpx_with_body(
            _point(
                "1.4006", "103.8064", _tpx("<gpxtpx:hr>--</gpxtpx:hr><gpxtpx:speed></gpxtpx:speed>")
            )
            + _point("1.4005", "103.8063", _tpx("<gpxtpx:hr>142.6</gpxtpx:hr>"))
        )
        path = temp_dir / "run.gpx"
        path.write_text(content)

        result = parse_gpx_file(path)

        assert result[0][2] is None
        assert result[0][3] is None
        assert result[1][3] == 143  # beats are rounded to whole numbers


class TestParseTrackFile:
    """Tests for parse_track_file dispatcher."""

    def test_routes_gpx_to_gpx_parser(self):
        """Should route .gpx files to parse_gpx_file."""
        import tempfile

        gpx_content = """<?xml version="1.0" encoding="UTF-8"?>
<gpx creator="StravaGPX" version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="1.0" lon="2.0"><ele>10.0</ele></trkpt>
  </trkseg></trk>
</gpx>
"""
        with tempfile.NamedTemporaryFile(suffix=".gpx", delete=False) as f:
            f.write(gpx_content.encode())
            temp_path = Path(f.name)

        try:
            result = parse_track_file(temp_path)
            assert len(result) == 1
            assert result[0][0] == 1.0
            assert result[0][1] == 2.0
        finally:
            temp_path.unlink()

    def test_routes_fit_to_fit_parser(self):
        """Should route .fit.gz files to parse_fit_file."""
        with patch("src.helpers.parse_fit_file") as mock_parse:
            mock_parse.return_value = [[45.0, -122.0, 5.0, 150, 100.0]]
            result = parse_track_file(Path("dummy.fit.gz"))
            assert result == [[45.0, -122.0, 5.0, 150, 100.0]]
            mock_parse.assert_called_once_with(Path("dummy.fit.gz"))

    def test_unknown_format_returns_empty(self):
        """Should return empty list and warn for unknown formats."""
        with patch("src.helpers.log") as mock_log:
            result = parse_track_file(Path("weird.xyz"))
            assert result == []
            mock_log.warning.assert_called_once()
