"""
Synthetic, Strava-shaped benchmark data.

Nothing here needs a real Strava export: tracks are generated from a fixed
route around a fixed home, and the FIT writer produces a genuinely valid
``.fit.gz`` that ``fitparse`` reads back (header, definition message, record
messages and both CRCs).
"""

import gzip
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

HOME_LAT, HOME_LON = 45.0, -122.0
HOME_ALT_M = 100.0

# ---------------------------------------------------------------------------
# FIT writer
# ---------------------------------------------------------------------------

# The FIT CRC-16 nibble table (see the FIT Protocol document).
_FIT_CRC_TABLE = (
    0x0000,
    0xCC01,
    0xD801,
    0x1400,
    0xF001,
    0x3C00,
    0x2800,
    0xE401,
    0xA001,
    0x6C00,
    0x7800,
    0xB401,
    0x5000,
    0x9C01,
    0x8801,
    0x4400,
)

# (field definition number, size in bytes, base type) for the record message.
# 0/1 = position_lat/lon (sint32 semicircles), 2 = altitude (uint16, scale 5
# offset 500), 3 = heart_rate (uint8).
_RECORD_FIELDS = ((0, 4, 0x85), (1, 4, 0x85), (2, 2, 0x84), (3, 1, 0x02))
_RECORD_GLOBAL_NUM = 20
_SEMICIRCLE = (2**31) / 180.0


def _fit_crc(data: bytes, crc: int = 0) -> int:
    """FIT CRC-16 over ``data``."""
    table = _FIT_CRC_TABLE
    for byte in data:
        tmp = table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc ^= tmp ^ table[byte & 0xF]
        tmp = table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc ^= tmp ^ table[(byte >> 4) & 0xF]
    return crc


def _definition_message(global_num: int, fields, local: int = 0) -> bytes:
    """Encode one little-endian FIT definition message."""
    out = bytearray((0x40 | local, 0x00, 0x00))
    out += struct.pack("<H", global_num)
    out.append(len(fields))
    for field_num, size, base_type in fields:
        out += bytes((field_num, size, base_type))
    return bytes(out)


def build_fit_bytes(points) -> bytes:
    """Return a valid FIT document for ``(lat, lon, alt_m, hr)`` points."""
    records = bytearray(_definition_message(_RECORD_GLOBAL_NUM, _RECORD_FIELDS))
    for lat, lon, alt, hr in points:
        records.append(0x00)  # data message, local message type 0
        records += struct.pack("<i", int(lat * _SEMICIRCLE))
        records += struct.pack("<i", int(lon * _SEMICIRCLE))
        records += struct.pack("<H", int((alt + 500.0) * 5.0))
        records.append(int(hr) & 0xFF)

    header = (
        bytes((14, 0x10))
        + struct.pack("<H", 0x0891)  # profile version
        + struct.pack("<I", len(records))
        + b".FIT"
    )
    return (
        header
        + struct.pack("<H", _fit_crc(header))
        + bytes(records)
        + struct.pack("<H", _fit_crc(records))
    )


# ---------------------------------------------------------------------------
# GPX writer
# ---------------------------------------------------------------------------

_GPX_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<gpx version="1.1" creator="benchmark"'
    ' xmlns="http://www.topografix.com/GPX/1/1"'
    ' xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v2">'
)


def build_gpx_text(points) -> str:
    """Return a GPX 1.1 document for ``(lat, lon, alt_m, hr)`` points."""
    body = []
    for lat, lon, alt, hr in points:
        body.append(
            f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>{alt:.1f}</ele>'
            "<extensions><gpxtpx:TrackPointExtension>"
            f"<gpxtpx:hr>{int(hr)}</gpxtpx:hr><gpxtpx:speed>3.0</gpxtpx:speed>"
            "</gpxtpx:TrackPointExtension></extensions></trkpt>"
        )
    return f"{_GPX_HEADER}<trk><trkseg>{''.join(body)}</trkseg></trk></gpx>"


# ---------------------------------------------------------------------------
# Scenarios and export generation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """One representative export size."""

    name: str
    n_activities: int
    points_per_activity: int

    @property
    def total_points(self) -> int:
        return self.n_activities * self.points_per_activity


# The default ladder: a smoke size, a typical size, and a large export. The
# "tiny" size exists so tests can exercise the full harness quickly.
SCENARIOS = {
    "tiny": Scenario("tiny", 4, 40),
    "small": Scenario("small", 30, 300),
    "medium": Scenario("medium", 120, 800),
    "large": Scenario("large", 300, 1500),
}


def scenario_route(scenario: Scenario, activity_index: int = 0):
    """A closed route of ``points_per_activity`` points near the fixed home.

    The route is bounded (~2 km) regardless of the point count, so the grid
    stays renderable while the number of parsed points still scales with the
    scenario. Every activity shares the route with a small offset, which is what
    makes the density layers representative.
    """
    n = scenario.points_per_activity
    offset = 0.0002 * (activity_index % 5)
    points = []
    for i in range(n):
        frac = i / max(n - 1, 1)
        lat = HOME_LAT + 0.010 * math.sin(2 * math.pi * frac) + offset
        lon = HOME_LON + 0.010 * math.cos(2 * math.pi * frac) + offset
        points.append((lat, lon, HOME_ALT_M + (i % 20), 120 + (i % 40)))
    return points


@dataclass
class Export:
    """A generated synthetic export on disk."""

    scenario: Scenario
    root: Path
    activities_dir: Path
    cache_dir: Path
    output_dir: Path
    activities_csv: Path
    config_path: Path
    filenames: list[str] = field(default_factory=list)


def generate_export(root: Path, scenario: Scenario, fmt: str = "fit") -> Export:
    """Write a synthetic export (tracks + ``activities.csv`` + ``config.toml``)."""
    root = Path(root)
    activities_dir = root / "activities"
    cache_dir = root / "cache"
    output_dir = root / "outputs"
    activities_dir.mkdir(parents=True, exist_ok=True)
    # The app cache/config resolve these; create them so cache writes succeed.
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    filenames: list[str] = []
    for i in range(scenario.n_activities):
        points = scenario_route(scenario, i)
        if fmt == "fit":
            name = f"activity_{i:04d}.fit.gz"
            with gzip.open(activities_dir / name, "wb") as handle:
                handle.write(build_fit_bytes(points))
        else:
            name = f"activity_{i:04d}.gpx"
            (activities_dir / name).write_text(build_gpx_text(points), encoding="utf-8")
        filenames.append(name)

    csv_path = activities_dir / "activities.csv"
    rows = ["Filename,Activity Type,Activity Date,Activity Name"]
    for i, name in enumerate(filenames):
        day = (i % 28) + 1
        rows.append(f"{name},Run,2024-01-{day:02d},Activity {i}")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    config_path = root / "config.toml"
    config_path.write_text(
        f'ACTIVITIES_DIR = "{activities_dir}"\n'
        'ACTIVITY_TYPES = ["Run"]\n'
        f'CACHE_DIR = "{cache_dir}"\n'
        f'OUTPUT_DIR = "{output_dir}"\n',
        encoding="utf-8",
    )

    return Export(
        scenario=scenario,
        root=root,
        activities_dir=activities_dir,
        cache_dir=cache_dir,
        output_dir=output_dir,
        activities_csv=csv_path,
        config_path=config_path,
        filenames=filenames,
    )


def runs_frame(export: Export) -> pd.DataFrame:
    """The runs DataFrame ``load_tracks`` expects, without re-reading the CSV."""
    return pd.DataFrame(
        {
            "Filename": export.filenames,
            "Activity Date": [pd.Timestamp("2024-01-01")] * len(export.filenames),
            "Activity Name": [f"Activity {i}" for i in range(len(export.filenames))],
        }
    )
