"""
Strava Activity Heatmap Generator
Parses .fit.gz files, generates rasterized overlays, and outputs an interactive Folium map.
"""

from datetime import date
import base64
import gc
import gzip
from io import BytesIO
import json
import logging
import math
import os
from pathlib import Path
import sys
import warnings

import folium
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd
from PIL import Image
from pyproj import Transformer
from scipy.ndimage import gaussian_filter

from src.helpers import haversine_km, get_gps_start, detect_home, load_fit_track_full, parse_fit_file

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# Suppress non-critical third-party warnings
warnings.filterwarnings("ignore", category=UserWarning, module="folium")
warnings.filterwarnings("ignore", category=FutureWarning, module="pandas")
warnings.filterwarnings("ignore", category=UserWarning, module="pyproj")

# ==============================================================================
# CONFIGURATION & INITIALIZATION
# ==============================================================================

CONFIG_PATH = Path("config.json")
if not CONFIG_PATH.exists():
    raise FileNotFoundError("config.json file not found.")

with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

ACTIVITIES_DIR = Path(config["ACTIVITIES_DIR"])
ACTIVITY_TYPES = set(config["ACTIVITY_TYPES"])
DATE_FROM = config["DATE_FROM"]
DATE_TO = config["DATE_TO"]

HOME_LAT = config["HOME_LAT"]
HOME_LON = config["HOME_LON"]
RADIUS_KM = config["RADIUS_KM"]

GPS_SPREAD_MIN_M = config["GPS_SPREAD_MIN_M"]
METERS_PER_PIXEL = config["METERS_PER_PIXEL"]
PADDING_M = config["PADDING_M"]
TRACK_CLIP_RADIUS_KM = config["TRACK_CLIP_RADIUS_KM"]

BLUR_SIGMA_PX = config["BLUR_SIGMA_PX"]
MAP_OPACITY = config["MAP_OPACITY"]

SPEED_MIN_MS = config["SPEED_MIN_MS"]
SPEED_MAX_MS = config["SPEED_MAX_MS"]
HR_MIN_BPM = config["HR_MIN_BPM"]
HR_MAX_BPM = config["HR_MAX_BPM"]
AUTO_RANGE_PCT = config["AUTO_RANGE_PCT"]

# Configurable paths with sensible defaults
CACHE_DIR = Path(config.get("CACHE_DIR", "cache"))
OUTPUT_DIR = Path(config.get("OUTPUT_DIR", "outputs"))
CACHE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ACTIVITIES_CSV = ACTIVITIES_DIR / config.get("ACTIVITIES_CSV", "activities.csv")
TRACK_CACHE = CACHE_DIR / config.get("TRACK_CACHE", "track_cache.json")
OUTPUT_HTML = OUTPUT_DIR / config.get("OUTPUT_HTML", "heatmap.html")

log.info(f"Source:  {ACTIVITIES_DIR}/")
log.info(f"Types:   {', '.join(ACTIVITY_TYPES)}")
log.info(f"Output:  {OUTPUT_HTML}")

# ==============================================================================
# DATA PROCESSING & FILTERING
# ==============================================================================

df = pd.read_csv(ACTIVITIES_CSV)
df["Activity Date"] = pd.to_datetime(df["Activity Date"], format="mixed", dayfirst=True)
runs = df[df["Activity Type"].isin(ACTIVITY_TYPES)].copy()
log.info(f"Total matching activities in export: {len(runs)}")

date_from = pd.Timestamp(DATE_FROM) if DATE_FROM else pd.Timestamp.min
date_to = pd.Timestamp(DATE_TO) if DATE_TO else pd.Timestamp(date.today())
runs = runs[runs["Activity Date"].between(date_from, date_to)].copy()
log.info(f"After date filter ({date_from.date()} – {date_to.date()}): {len(runs)}")

# Parse GPS start points (cached per export)
gps_cache_path = Path(ACTIVITIES_DIR) / "_gps_cache.json"
gps_cache = json.loads(gps_cache_path.read_text()) if gps_cache_path.exists() else {}

rows = []
for _, row in runs.iterrows():
    fn = str(row["Filename"])
    if fn in gps_cache:
        lat, lon, spread = gps_cache[fn]
    else:
        lat, lon, spread = get_gps_start(Path(ACTIVITIES_DIR) / fn)
        gps_cache[fn] = [lat, lon, spread]  # cache even if no GPS (None values)
    rows.append({**row, "start_lat": lat, "start_lon": lon, "gps_spread_m": spread})

gps_cache_path.write_text(json.dumps(gps_cache))

runs = pd.DataFrame(rows)
runs = runs[
    runs["start_lat"].notna() & (runs["gps_spread_m"] >= GPS_SPREAD_MIN_M)
].copy()
log.info(f"After removing no-GPS / indoor: {len(runs)}")

# Auto-detect or use manual home location
if HOME_LAT is None or HOME_LON is None:
    home_lat, home_lon, n_home_starts = detect_home(runs)
    log.info(
        f"Auto-detected home: {home_lat:.4f}, {home_lon:.4f}  "
        f"({n_home_starts} of {len(runs)} activities started there)"
    )
else:
    home_lat, home_lon = HOME_LAT, HOME_LON
    log.info(f"Using manual home: {home_lat}, {home_lon}")

# Filter by home radius
runs["dist_from_home_km"] = runs.apply(
    lambda r: haversine_km(home_lat, home_lon, r["start_lat"], r["start_lon"]), axis=1
)
runs = runs[runs["dist_from_home_km"] <= RADIUS_KM].copy()
log.info(f"After home-radius filter (≤{RADIUS_KM} km): {len(runs)} activities")

# Load full tracks
track_cache = json.loads(TRACK_CACHE.read_text()) if TRACK_CACHE.exists() else {}

# Purge cache missing altitude schema
stale = [k for k, v in track_cache.items() if v and len(v[0]) < 5]
if stale:
    log.info(f"Clearing {len(stale)} stale cache entries...")
    for k in stale:
        del track_cache[k]

tracks = []
for _, row in runs.iterrows():
    fn = str(row["Filename"])
    fp = ACTIVITIES_DIR / fn
    lbl = f"{row['Activity Date'].date()} {row['Activity Name']}"

    pts = track_cache.get(fn)
    if pts is None:
        log.info(f"Parsing {fn}...")
        pts = load_fit_track_full(fp)
        track_cache[fn] = pts

    if pts:
        tracks.append((lbl, pts))

TRACK_CACHE.write_text(json.dumps(track_cache))

if not tracks:
    log.error("No valid tracks loaded. Check your configuration and date ranges.")
    sys.exit(1)

# ==============================================================================
# RASTERIZATION & MAP BUILDING
# ==============================================================================

# Rasterising in Web Mercator means pixels map directly to basemap tile space —
# no reprojection needed when placing the image overlay in Leaflet.
to_wm = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
from_wm = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

# UTM for clip radius and gradient distance — true ground metres
utm_zone = int((home_lon + 180) / 6) + 1
utm_base = 32700 if home_lat < 0 else 32600
utm_crs = f"EPSG:{utm_base + utm_zone}"
to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)

_home_x_utm, _home_y_utm = to_utm.transform(home_lon, home_lat)
_clip_m = TRACK_CLIP_RADIUS_KM * 1000 if TRACK_CLIP_RADIUS_KM is not None else None

# Grid bounds
if _clip_m is not None:
    clipped_wm_xs, clipped_wm_ys = [], []
    for _, pts in tracks:
        lats_a = np.array([p[0] for p in pts])
        lons_a = np.array([p[1] for p in pts])
        xs_utm, ys_utm = to_utm.transform(lons_a, lats_a)
        mask = ((xs_utm - _home_x_utm) ** 2 + (ys_utm - _home_y_utm) ** 2) <= _clip_m**2
        if mask.any():
            xs_wm_c, ys_wm_c = to_wm.transform(lons_a[mask], lats_a[mask])
            clipped_wm_xs.extend(xs_wm_c.tolist())
            clipped_wm_ys.extend(ys_wm_c.tolist())
    x_min_wm = min(clipped_wm_xs) - PADDING_M
    x_max_wm = max(clipped_wm_xs) + PADDING_M
    y_min_wm = min(clipped_wm_ys) - PADDING_M
    y_max_wm = max(clipped_wm_ys) + PADDING_M
else:
    all_lats = np.array([p[0] for _, pts in tracks for p in pts])
    all_lons = np.array([p[1] for _, pts in tracks for p in pts])
    xs_wm_all, ys_wm_all = to_wm.transform(all_lons, all_lats)
    x_min_wm = xs_wm_all.min() - PADDING_M
    x_max_wm = xs_wm_all.max() + PADDING_M
    y_min_wm = ys_wm_all.min() - PADDING_M
    y_max_wm = ys_wm_all.max() + PADDING_M

grid_w = int((x_max_wm - x_min_wm) / METERS_PER_PIXEL) + 1
grid_h = int((y_max_wm - y_min_wm) / METERS_PER_PIXEL) + 1

count_grid = np.zeros((grid_h, grid_w), dtype=np.float32)
speed_sum = np.zeros((grid_h, grid_w), dtype=np.float32)
speed_n = np.zeros((grid_h, grid_w), dtype=np.float32)
hr_sum = np.zeros((grid_h, grid_w), dtype=np.float32)
hr_n = np.zeros((grid_h, grid_w), dtype=np.float32)
grad_sum = np.zeros((grid_h, grid_w), dtype=np.float32)
grad_n = np.zeros((grid_h, grid_w), dtype=np.float32)
elev_sum = np.zeros((grid_h, grid_w), dtype=np.float32)
elev_n = np.zeros((grid_h, grid_w), dtype=np.float32)


def paint_segment(x1, y1, x2, y2, speed_val, hr_val, grad_val, elev_val):
    dx, dy = x2 - x1, y2 - y1
    n_steps = max(int(max(abs(dx), abs(dy))) + 1, 1)
    h, w = speed_sum.shape
    for i in range(n_steps + 1):
        t = i / n_steps
        xi = int(round(x1 + t * dx))
        yi = int(round(y1 + t * dy))
        if not (0 <= xi < w and 0 <= yi < h):
            continue
        if speed_val is not None:
            speed_sum[yi, xi] += speed_val
            speed_n[yi, xi] += 1
        if hr_val is not None:
            hr_sum[yi, xi] += hr_val
            hr_n[yi, xi] += 1
        if grad_val is not None:
            grad_sum[yi, xi] += grad_val
            grad_n[yi, xi] += 1
        if elev_val is not None:
            elev_sum[yi, xi] += elev_val
            elev_n[yi, xi] += 1


for label, pts in tracks:
    lats_a = np.array([p[0] for p in pts])
    lons_a = np.array([p[1] for p in pts])
    xs_utm, ys_utm = to_utm.transform(lons_a, lats_a)
    xs_wm, ys_wm = to_wm.transform(lons_a, lats_a)

    if _clip_m is not None:
        _mask = (
            (xs_utm - _home_x_utm) ** 2 + (ys_utm - _home_y_utm) ** 2
        ) <= _clip_m**2
        if not _mask.any():
            continue
        pts = [pts[i] for i in range(len(pts)) if _mask[i]]
        xs_utm = xs_utm[_mask]
        ys_utm = ys_utm[_mask]
        xs_wm = xs_wm[_mask]
        ys_wm = ys_wm[_mask]

    px = (xs_wm - x_min_wm) / METERS_PER_PIXEL
    py = (y_max_wm - ys_wm) / METERS_PER_PIXEL

    for i in range(len(pts)):
        xi = int(round(px[i]))
        yi = int(round(py[i]))
        if 0 <= xi < grid_w and 0 <= yi < grid_h:
            count_grid[yi, xi] += 1

    for i in range(len(pts) - 1):
        s0, s1 = pts[i][2], pts[i + 1][2]
        h0, h1 = pts[i][3], pts[i + 1][3]
        a0, a1 = pts[i][4], pts[i + 1][4]

        seg_speed = (
            (s0 + s1) / 2
            if s0 is not None and s1 is not None
            else (s0 if s0 is not None else s1)
        )
        seg_hr = (
            (h0 + h1) / 2
            if h0 is not None and h1 is not None
            else (h0 if h0 is not None else h1)
        )

        if a0 is not None and a1 is not None:
            d_dist = math.sqrt(
                (xs_utm[i + 1] - xs_utm[i]) ** 2 + (ys_utm[i + 1] - ys_utm[i]) ** 2
            )
            if d_dist >= 0.5:
                seg_grad = abs(a1 - a0) / d_dist
                seg_elev = a1 - a0
            else:
                seg_grad = seg_elev = None
        else:
            seg_grad = seg_elev = None

        paint_segment(
            px[i], py[i], px[i + 1], py[i + 1], seg_speed, seg_hr, seg_grad, seg_elev
        )

sigma = BLUR_SIGMA_PX

# Count grid
b_count = gaussian_filter(count_grid, sigma=sigma)
count_norm = b_count / b_count.max()
count_log_norm = np.log1p(b_count) / np.log1p(b_count.max())

# Speed (average) grid
b_speed_sum = gaussian_filter(speed_sum, sigma=sigma)
b_speed_n = gaussian_filter(speed_n, sigma=sigma)
mean_speed = np.divide(b_speed_sum, b_speed_n, out=np.zeros_like(b_speed_sum), where=b_speed_n > 0)
visited_speeds = mean_speed[b_speed_n > 0.01]
if len(visited_speeds):
    s_lo = (
        SPEED_MIN_MS
        if SPEED_MIN_MS is not None
        else np.percentile(visited_speeds, AUTO_RANGE_PCT)
    )
    s_hi = (
        SPEED_MAX_MS
        if SPEED_MAX_MS is not None
        else np.percentile(visited_speeds, 100 - AUTO_RANGE_PCT)
    )
    speed_norm = np.clip((mean_speed - s_lo) / (s_hi - s_lo), 0, 1)
    speed_norm = np.where(b_speed_n > 0, speed_norm, 0)
    _sw = gaussian_filter(speed_norm * (b_speed_n > 0.01).astype(float), sigma=sigma)
    _sn = gaussian_filter((b_speed_n > 0.01).astype(float), sigma=sigma)
    speed_norm = np.divide(_sw, _sn, out=np.zeros_like(_sw), where=_sn > 0)
else:
    s_lo, s_hi = 1.0, 5.0
    speed_norm = np.zeros_like(mean_speed)

# HR (average) grid
b_hr_sum = gaussian_filter(hr_sum, sigma=sigma)
b_hr_n = gaussian_filter(hr_n, sigma=sigma)
mean_hr = np.divide(b_hr_sum, b_hr_n, out=np.zeros_like(b_hr_sum), where=b_hr_n > 0)
visited_hrs = mean_hr[hr_n > 0]
if len(visited_hrs):
    hr_lo = (
        HR_MIN_BPM
        if HR_MIN_BPM is not None
        else np.percentile(visited_hrs, AUTO_RANGE_PCT)
    )
    hr_hi = (
        HR_MAX_BPM
        if HR_MAX_BPM is not None
        else np.percentile(visited_hrs, 100 - AUTO_RANGE_PCT)
    )
    hr_norm = np.clip((mean_hr - hr_lo) / (hr_hi - hr_lo), 0, 1)
    hr_norm = np.where(b_hr_n > 0, hr_norm, 0)
    _hw = gaussian_filter(hr_norm * (hr_n > 0).astype(float), sigma=sigma)
    _hn = gaussian_filter((hr_n > 0).astype(float), sigma=sigma)
    hr_norm = np.divide(_hw, _hn, out=np.zeros_like(_hw), where=_hn > 0)
else:
    hr_lo, hr_hi = 100, 180
    hr_norm = np.zeros_like(mean_hr)

# Gradient grid
b_grad_sum = gaussian_filter(grad_sum, sigma=sigma)
b_grad_n = gaussian_filter(grad_n, sigma=sigma)
mean_grad = np.divide(b_grad_sum, b_grad_n, out=np.zeros_like(b_grad_sum), where=b_grad_n > 0)
visited_grads = mean_grad[b_grad_n > 0.01]
n_grad_px = (grad_n > 0).sum()
if n_grad_px and len(visited_grads):
    g_lo = np.percentile(visited_grads, AUTO_RANGE_PCT)
    g_hi = np.percentile(visited_grads, 100 - AUTO_RANGE_PCT)
    grad_norm = np.clip((mean_grad - g_lo) / (g_hi - g_lo), 0, 1)
    grad_norm = np.where(b_grad_n > 0, grad_norm, 0)
    observed_grads = visited_grads * 100
else:
    grad_norm = np.zeros_like(mean_grad)
    g_lo = g_hi = 0.0

# Elevation change grid (signed)
b_elev_sum = gaussian_filter(elev_sum, sigma=sigma)
b_elev_n = gaussian_filter(elev_n, sigma=sigma)
mean_elev = np.divide(b_elev_sum, b_elev_n, out=np.zeros_like(b_elev_sum), where=b_elev_n > 0)
n_elev_px = (elev_n > 0).sum()
if n_elev_px:
    visited_elevs = mean_elev[b_elev_n > 0.01]
    e_abs_hi = max(
        abs(np.percentile(visited_elevs, AUTO_RANGE_PCT)),
        abs(np.percentile(visited_elevs, 100 - AUTO_RANGE_PCT)),
    )
    elev_norm = np.clip(mean_elev / e_abs_hi, -1, 1)
    elev_norm = np.where(b_elev_n > 0, elev_norm, 0)
    _ew = gaussian_filter(elev_norm * (b_elev_n > 0.01).astype(float), sigma=sigma)
    _en = gaussian_filter((b_elev_n > 0.01).astype(float), sigma=sigma)
    elev_norm = np.divide(_ew, _en, out=np.zeros_like(_ew), where=_en > 0)
else:
    elev_norm = np.zeros_like(mean_elev)


# Alpha masks
def presence_alpha(sample_count_grid, blur_sigma, pct=10):
    binary = (sample_count_grid > 0).astype(np.float32)
    blurred = gaussian_filter(binary, sigma=blur_sigma)
    sat = np.percentile(blurred[binary > 0], pct)
    return np.clip(blurred / sat, 0, 1) if sat > 0 else blurred


alpha_speed = presence_alpha(speed_n, sigma)
alpha_hr = presence_alpha(hr_n, sigma)
_presence_grad = (
    presence_alpha(grad_n, sigma) if n_grad_px else np.zeros_like(grad_norm)
)
alpha_grad = _presence_grad * (0.15 + 0.85 * grad_norm)
alpha_elev = presence_alpha(elev_n, sigma) if n_elev_px else np.zeros_like(elev_norm)


def build_cmap(name, nodes):
    """Build a LinearSegmentedColormap from a list of (position, (R,G,B,A)) nodes."""
    pos = [n[0] for n in nodes]
    cdict = {}
    for ci, ch in enumerate(("red", "green", "blue", "alpha")):
        vals = [n[1][ci] for n in nodes]
        cdict[ch] = [(pos[i], vals[i], vals[i]) for i in range(len(pos))]
    return mcolors.LinearSegmentedColormap(name, cdict, N=512)


# Orange — frequency: dark orange → amber → yellow → cream
cmap_count = build_cmap(
    "count",
    [
        (0.00, (0.00, 0.00, 0.00, 0.00)),
        (0.01, (0.40, 0.10, 0.00, 0.55)),
        (0.20, (0.99, 0.30, 0.01, 0.80)),
        (0.50, (1.00, 0.65, 0.00, 0.92)),
        (0.80, (1.00, 0.92, 0.20, 0.97)),
        (1.00, (1.00, 1.00, 0.80, 1.00)),
    ],
)

# Blue — pace: dark navy → blue → royal blue → periwinkle → near-white blue
cmap_speed_rgb = build_cmap(
    "speed",
    [
        (0.00, (0.00, 0.10, 0.40, 1.00)),
        (0.35, (0.05, 0.30, 0.80, 1.00)),
        (0.65, (0.20, 0.55, 1.00, 1.00)),
        (0.85, (0.55, 0.75, 1.00, 1.00)),
        (1.00, (0.85, 0.92, 1.00, 1.00)),
    ],
)

# Red — heart rate: visible dark red → #ea4747 → rose → near-white pink
cmap_hr_rgb = build_cmap(
    "hr",
    [
        (0.00, (0.40, 0.05, 0.05, 1.00)),
        (0.35, (0.70, 0.12, 0.12, 1.00)),
        (0.65, (0.92, 0.28, 0.28, 1.00)),
        (0.85, (1.00, 0.65, 0.65, 1.00)),
        (1.00, (1.00, 0.90, 0.90, 1.00)),
    ],
)

# Diverging — gradient (change): green (descending) → dark neutral → purple (ascending)
# Green and purple endpoints are tuned to roughly equal perceived brightness:
#   green  (0.12, 0.80, 0.22) → luminance ≈ 0.60
#   purple (0.82, 0.22, 1.00) → luminance ≈ 0.36
# Pure perceptual equality isn't achievable (eye weights green at 72%) without
# making purple look lavender, so this is the closest natural-looking balance.
cmap_elev_rgb = build_cmap(
    "elev",
    [
        (0.00, (0.12, 0.80, 0.22, 1.00)),  # strong descent — vivid green
        (0.25, (0.06, 0.52, 0.16, 1.00)),  # moderate descent
        (0.45, (0.06, 0.20, 0.10, 1.00)),  # slight descent — dark green
        (0.50, (0.18, 0.18, 0.18, 1.00)),  # flat — near-black neutral
        (0.55, (0.22, 0.08, 0.30, 1.00)),  # slight ascent — dark purple
        (0.75, (0.52, 0.06, 0.75, 1.00)),  # moderate ascent
        (1.00, (0.82, 0.22, 1.00, 1.00)),  # strong ascent — bright purple
    ],
)


def _to_uri(rgba_u8):
    buf = BytesIO()
    Image.fromarray(rgba_u8, mode="RGBA").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _count_uri(norm):
    return _to_uri((cmap_count(norm) * 255).clip(0, 255).astype(np.uint8))


def _rgba_uri(rgb_norm, alpha_norm, cmap_rgb):
    arr = cmap_rgb(rgb_norm).copy()
    arr[:, :, 3] = alpha_norm
    return _to_uri((arr * 255).clip(0, 255).astype(np.uint8))


def _white_uri(alpha_norm):
    h, w = alpha_norm.shape
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:, :, :3] = 255
    arr[:, :, 3] = (alpha_norm * 255).clip(0, 255).astype(np.uint8)
    return _to_uri(arr)


lon_nw, lat_nw = from_wm.transform(x_min_wm, y_max_wm)
lon_se, lat_se = from_wm.transform(x_max_wm, y_min_wm)
bounds = [[lat_se, lon_nw], [lat_nw, lon_se]]
centre = [(lat_nw + lat_se) / 2, (lon_nw + lon_se) / 2]

max_passes = int(count_grid.max())

del count_grid, speed_sum, speed_n, hr_sum, hr_n, grad_sum, grad_n, elev_sum, elev_n
del (
    b_count,
    b_speed_sum,
    b_speed_n,
    b_hr_sum,
    b_hr_n,
    b_grad_sum,
    b_grad_n,
    b_elev_sum,
    b_elev_n,
)
gc.collect()

layers = [
    ("Frequency (linear)", _count_uri(count_norm), True),
    ("Frequency (log)", _count_uri(count_log_norm), False),
    ("Pace (average)", _rgba_uri(speed_norm, alpha_speed, cmap_speed_rgb), False),
    ("Heart rate (average)", _rgba_uri(hr_norm, alpha_hr, cmap_hr_rgb), False),
    ("Gradient (absolute)", _white_uri(alpha_grad), False),
    (
        "Gradient (change)",
        _rgba_uri((elev_norm + 1) / 2, alpha_elev, cmap_elev_rgb),
        False,
    ),
]


# Legend
def cmap_to_css(cmap, n=14):
    stops = []
    for i in range(n):
        t = i / (n - 1)
        r, g, b, a = cmap(t)
        stops.append(f"rgba({int(r*255)},{int(g*255)},{int(b*255)},{a:.2f})")
    return f"linear-gradient(to right, {', '.join(stops)})"


def pace_str(ms):
    secs = 1000 / ms
    return f"{int(secs // 60)}:{int(secs % 60):02d}/km"


def legend_row(row_id, title, grad_css, label_lo, label_hi, visible=False):
    display = "block" if visible else "none"
    return f"""
    <div id="{row_id}" style="display:{display}">
      <div style="font-weight:600;margin-bottom:3px;color:#eee">{title}</div>
      <div style="height:10px;border-radius:3px;background:{grad_css};
                  border:1px solid rgba(255,255,255,0.08)"></div>
      <div style="display:flex;justify-content:space-between;
                  margin-top:3px;color:#aaa;font-size:11px">
        <span>{label_lo}</span><span>{label_hi}</span>
      </div>
    </div>"""


freq_css = cmap_to_css(cmap_count)
pace_css = cmap_to_css(cmap_speed_rgb)
hr_css = cmap_to_css(cmap_hr_rgb)

legend_html = f"""
<div id="heatmap-legend" style="
    position:fixed; bottom:28px; right:10px; z-index:9999;
    background:rgba(15,15,15,0.88);
    padding:13px 16px 14px; border-radius:9px;
    color:#ddd; font-family:sans-serif; font-size:12px;
    min-width:210px; line-height:1.4;
    border:1px solid rgba(255,255,255,0.10);
    box-shadow:0 2px 8px rgba(0,0,0,0.6);
">
  {legend_row("legend-frequency",      "Frequency (linear)",   freq_css, "1 pass", f"{int(max_passes)} passes", visible=True)}
  {legend_row("legend-frequency-log",  "Frequency (log)",      freq_css, "1 pass", f"{int(max_passes)} passes (log scale)")}
  {legend_row("legend-pace-avg",       "Pace (average)",       pace_css, pace_str(s_lo), pace_str(s_hi))}
  {legend_row("legend-heart-rate-avg", "Heart rate (average)", hr_css,   f"{hr_lo:.0f} bpm", f"{hr_hi:.0f} bpm")}
  {legend_row("legend-gradient",       "Gradient (absolute)",
      "linear-gradient(to right, rgba(0,0,0,0), rgba(255,255,255,1))",
      f"{g_lo*100:.1f}%", f"{g_hi*100:.1f}% grade")}
  {legend_row("legend-elev-change",    "Gradient (change)",
      cmap_to_css(cmap_elev_rgb), "descending", "ascending")}
</div>
"""

layer_control_css = """
<style>
  .leaflet-control-layers {
    background: rgba(15,15,15,0.88) !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    border-radius: 9px !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.6) !important;
    color: #ddd !important;
    font-family: sans-serif !important;
    font-size: 12px !important;
  }
  .leaflet-control-layers-expanded { padding: 11px 14px 13px !important; }
  .leaflet-control-layers label {
    color: #eee !important;
    font-weight: 600 !important;
    display: flex !important;
    align-items: center !important;
    gap: 6px !important;
    margin: 4px 0 !important;
  }
  .leaflet-control-layers-separator {
    border-color: rgba(255,255,255,0.12) !important;
    margin: 6px 0 !important;
  }
  .leaflet-control-layers-toggle {
    background-color: rgba(15,15,15,0.88) !important;
    border-radius: 9px !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
  }
</style>
"""

exclusive_js = """
<script>
(function() {
    var exclusiveNames = [
        "Frequency (linear)", "Frequency (log)",
        "Pace (average)", "Heart rate (average)",
        "Gradient (absolute)", "Gradient (change)"
    ];
    var legendIds = {
        "Frequency (linear)":   "legend-frequency",
        "Frequency (log)":      "legend-frequency-log",
        "Pace (average)":       "legend-pace-avg",
        "Heart rate (average)": "legend-heart-rate-avg",
        "Gradient (absolute)":  "legend-gradient",
        "Gradient (change)":    "legend-elev-change"
    };
    function showLegend(activeName) {
        Object.keys(legendIds).forEach(function(name) {
            var el = document.getElementById(legendIds[name]);
            if (el) el.style.display = (name === activeName) ? "block" : "none";
        });
    }
    function setup() {
        var mapObj = null, overlays = null;
        for (var k in window) {
            try {
                if (!mapObj   && window[k] instanceof L.Map) mapObj = window[k];
                if (!overlays && window[k] && window[k].overlays && window[k].base_layers)
                    overlays = window[k].overlays;
            } catch(e) {}
        }
        if (!mapObj || !overlays) { setTimeout(setup, 100); return; }
        mapObj.on('overlayadd', function(e) {
            if (!exclusiveNames.includes(e.name)) return;
            exclusiveNames.forEach(function(name) {
                if (name !== e.name && overlays[name] && mapObj.hasLayer(overlays[name]))
                    mapObj.removeLayer(overlays[name]);
            });
            showLegend(e.name);
        });
    }
    document.addEventListener('DOMContentLoaded', setup);
})();
</script>
"""

# Build map
m = folium.Map(location=centre, zoom_start=14, tiles=None, control_scale=True)
folium.TileLayer(
    "CartoDB.DarkMatterNoLabels",
    name="Basemap",
    control=False,
    show=True,
).add_to(m)

track_group = folium.FeatureGroup(name="Raw GPS tracks", show=False)
for label, pts in tracks:
    folium.PolyLine(
        locations=[(p[0], p[1]) for p in pts],
        color="#fc4c02",
        weight=1,
        opacity=0.4,
        tooltip=label,
    ).add_to(track_group)
track_group.add_to(m)

for name, uri, visible in layers:
    fg = folium.FeatureGroup(name=name, show=visible)
    folium.raster_layers.ImageOverlay(
        image=uri,
        bounds=bounds,
        opacity=MAP_OPACITY,
        interactive=False,
        cross_origin=False,
        zindex=1,
    ).add_to(fg)
    fg.add_to(m)

folium.LayerControl(collapsed=False).add_to(m)
m.get_root().html.add_child(folium.Element(layer_control_css))
m.get_root().html.add_child(folium.Element(legend_html))
m.get_root().html.add_child(folium.Element(exclusive_js))

m.save(OUTPUT_HTML)
log.info(f"Saved: {OUTPUT_HTML}")
log.info(f"Open:  file://{os.path.abspath(OUTPUT_HTML)}")
