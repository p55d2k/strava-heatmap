"""
Pipeline Stage 2: Rasterization & Grid Computation
Handles coordinate transforms, grid creation, track rasterization, and normalization.
"""

import gc
import math

import numpy as np
from pyproj import Transformer
from scipy.ndimage import gaussian_filter


def setup_transformers(home_lat: float, home_lon: float, track_clip_radius_km: float | None):
    """Set up coordinate transformers for Web Mercator and UTM."""
    to_wm = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    from_wm = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

    # UTM for clip radius and gradient distance — true ground metres
    utm_zone = int((home_lon + 180) / 6) + 1
    utm_base = 32700 if home_lat < 0 else 32600
    utm_crs = f"EPSG:{utm_base + utm_zone}"
    to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)

    home_x_utm, home_y_utm = to_utm.transform(home_lon, home_lat)
    clip_m = track_clip_radius_km * 1000 if track_clip_radius_km is not None else None

    return to_wm, from_wm, to_utm, home_x_utm, home_y_utm, clip_m


def compute_grid_bounds(
    tracks: list[tuple[str, list]],
    to_wm: Transformer,
    to_utm: Transformer,
    home_x_utm: float,
    home_y_utm: float,
    clip_m: float | None,
    padding_m: float,
) -> tuple[float, float, float, float]:
    """Compute grid bounds in Web Mercator coordinates."""
    if clip_m is not None:
        clipped_wm_xs, clipped_wm_ys = [], []
        for _, pts in tracks:
            lats_a = np.array([p[0] for p in pts])
            lons_a = np.array([p[1] for p in pts])
            xs_utm, ys_utm = to_utm.transform(lons_a, lats_a)
            mask = ((xs_utm - home_x_utm) ** 2 + (ys_utm - home_y_utm) ** 2) <= clip_m**2
            if mask.any():
                xs_wm_c, ys_wm_c = to_wm.transform(lons_a[mask], lats_a[mask])
                clipped_wm_xs.extend(xs_wm_c.tolist())
                clipped_wm_ys.extend(ys_wm_c.tolist())
        x_min_wm = min(clipped_wm_xs) - padding_m
        x_max_wm = max(clipped_wm_xs) + padding_m
        y_min_wm = min(clipped_wm_ys) - padding_m
        y_max_wm = max(clipped_wm_ys) + padding_m
    else:
        all_lats = np.array([p[0] for _, pts in tracks for p in pts])
        all_lons = np.array([p[1] for _, pts in tracks for p in pts])
        xs_wm_all, ys_wm_all = to_wm.transform(all_lons, all_lats)
        x_min_wm = xs_wm_all.min() - padding_m
        x_max_wm = xs_wm_all.max() + padding_m
        y_min_wm = ys_wm_all.min() - padding_m
        y_max_wm = ys_wm_all.max() + padding_m

    return x_min_wm, x_max_wm, y_min_wm, y_max_wm


def create_grids(
    x_min_wm: float, x_max_wm: float, y_min_wm: float, y_max_wm: float, meters_per_pixel: float
):
    """Create empty grids for rasterization."""
    grid_w = int((x_max_wm - x_min_wm) / meters_per_pixel) + 1
    grid_h = int((y_max_wm - y_min_wm) / meters_per_pixel) + 1

    count_grid = np.zeros((grid_h, grid_w), dtype=np.float32)
    speed_sum = np.zeros((grid_h, grid_w), dtype=np.float32)
    speed_n = np.zeros((grid_h, grid_w), dtype=np.float32)
    hr_sum = np.zeros((grid_h, grid_w), dtype=np.float32)
    hr_n = np.zeros((grid_h, grid_w), dtype=np.float32)
    grad_sum = np.zeros((grid_h, grid_w), dtype=np.float32)
    grad_n = np.zeros((grid_h, grid_w), dtype=np.float32)
    elev_sum = np.zeros((grid_h, grid_w), dtype=np.float32)
    elev_n = np.zeros((grid_h, grid_w), dtype=np.float32)

    return (
        grid_w,
        grid_h,
        count_grid,
        speed_sum,
        speed_n,
        hr_sum,
        hr_n,
        grad_sum,
        grad_n,
        elev_sum,
        elev_n,
    )


def _rasterize_track_points(
    track_pts: list,
    px: np.ndarray,
    py: np.ndarray,
    grid_w: int,
    grid_h: int,
    count_grid: np.ndarray,
    max_consecutive_same_cell: int,
) -> None:
    """Rasterize a single track's points onto the count grid with consecutive cell cap."""
    same_cell_run = 0
    prev_xi = prev_yi = None
    for i in range(len(track_pts)):
        xi = int(round(px[i]))
        yi = int(round(py[i]))
        if 0 <= xi < grid_w and 0 <= yi < grid_h:
            if (xi, yi) == (prev_xi, prev_yi):
                same_cell_run += 1
            else:
                same_cell_run = 1
                prev_xi, prev_yi = xi, yi
            if same_cell_run <= max_consecutive_same_cell:
                count_grid[yi, xi] += 1


def paint_segment(x1, y1, x2, y2, speed_val, hr_val, grad_val, elev_val, grids):
    """Paint a line segment onto the grids using vectorized NumPy operations."""
    dx, dy = x2 - x1, y2 - y1
    n_steps = max(int(max(abs(dx), abs(dy))) + 1, 1)
    h, w = grids[2].shape  # speed_sum shape

    # Generate all t values at once
    t = np.linspace(0, 1, n_steps + 1)

    # Calculate all coordinates at once
    xi = np.round(x1 + t * dx).astype(int)
    yi = np.round(y1 + t * dy).astype(int)

    # Filter valid coordinates (within bounds)
    valid_mask = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
    xi_valid = xi[valid_mask]
    yi_valid = yi[valid_mask]

    if len(xi_valid) == 0:
        return

    # Use advanced indexing to update grids in bulk
    if speed_val is not None:
        np.add.at(grids[3], (yi_valid, xi_valid), speed_val)  # speed_sum
        np.add.at(grids[4], (yi_valid, xi_valid), 1)  # speed_n
    if hr_val is not None:
        np.add.at(grids[5], (yi_valid, xi_valid), hr_val)  # hr_sum
        np.add.at(grids[6], (yi_valid, xi_valid), 1)  # hr_n
    if grad_val is not None:
        np.add.at(grids[7], (yi_valid, xi_valid), grad_val)  # grad_sum
        np.add.at(grids[8], (yi_valid, xi_valid), 1)  # grad_n
    if elev_val is not None:
        np.add.at(grids[9], (yi_valid, xi_valid), elev_val)  # elev_sum
        np.add.at(grids[10], (yi_valid, xi_valid), 1)  # elev_n


def rasterize_tracks(
    tracks: list[tuple[str, list]],
    to_wm: Transformer,
    to_utm: Transformer,
    home_x_utm: float,
    home_y_utm: float,
    clip_m: float | None,
    x_min_wm: float,
    y_max_wm: float,
    meters_per_pixel: float,
    max_consecutive_same_cell: int,
    grids: tuple,
) -> None:
    """Rasterize all tracks onto the grids.

    Points are incrementally binned into the count grid. To avoid a single
    stationary stretch (e.g. forgetting to stop the watch) from dominating the
    linear frequency layer, at most `max_consecutive_same_cell` consecutive
    samples that fall in the *same* grid cell are counted; once the cap is hit,
    subsequent consecutive samples in that cell are skipped until the track
    leaves the cell (a later return to the cell resets the counter, so genuine
    re-visits are still counted).
    """
    (
        grid_w,
        grid_h,
        count_grid,
        speed_sum,
        speed_n,
        hr_sum,
        hr_n,
        grad_sum,
        grad_n,
        elev_sum,
        elev_n,
    ) = grids

    for _, track_pts in tracks:
        lats_a = np.array([p[0] for p in track_pts])
        lons_a = np.array([p[1] for p in track_pts])
        xs_utm, ys_utm = to_utm.transform(lons_a, lats_a)
        xs_wm, ys_wm = to_wm.transform(lons_a, lats_a)

        if clip_m is not None:
            _mask = ((xs_utm - home_x_utm) ** 2 + (ys_utm - home_y_utm) ** 2) <= clip_m**2
            if not _mask.any():
                continue
            track_pts = [track_pts[i] for i in range(len(track_pts)) if _mask[i]]  # noqa: PLW2901
            xs_utm = xs_utm[_mask]
            ys_utm = ys_utm[_mask]
            xs_wm = xs_wm[_mask]
            ys_wm = ys_wm[_mask]

        px = (xs_wm - x_min_wm) / meters_per_pixel
        py = (y_max_wm - ys_wm) / meters_per_pixel

        _rasterize_track_points(
            track_pts, px, py, grid_w, grid_h, count_grid, max_consecutive_same_cell
        )

        for i in range(len(track_pts) - 1):
            s0, s1 = track_pts[i][2], track_pts[i + 1][2]
            h0, h1 = track_pts[i][3], track_pts[i + 1][3]
            a0, a1 = track_pts[i][4], track_pts[i + 1][4]

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
                px[i], py[i], px[i + 1], py[i + 1], seg_speed, seg_hr, seg_grad, seg_elev, grids
            )


def compute_normalized_grids(grids: tuple, sigma: float, config) -> dict:
    """Apply Gaussian blur and compute normalized grids for all metrics."""
    (
        grid_w,
        grid_h,
        count_grid,
        speed_sum,
        speed_n,
        hr_sum,
        hr_n,
        grad_sum,
        grad_n,
        elev_sum,
        elev_n,
    ) = grids

    # Count grid
    b_count = gaussian_filter(count_grid, sigma=sigma)
    max_count = b_count.max()
    if max_count > 0:
        count_norm = b_count / max_count
        count_log_norm = np.log1p(b_count) / np.log1p(max_count)
    else:
        count_norm = np.zeros_like(b_count)
        count_log_norm = np.zeros_like(b_count)

    # Speed (average) grid
    b_speed_sum = gaussian_filter(speed_sum, sigma=sigma)
    b_speed_n = gaussian_filter(speed_n, sigma=sigma)
    mean_speed = np.divide(
        b_speed_sum, b_speed_n, out=np.zeros_like(b_speed_sum), where=b_speed_n > 0
    )
    visited_speeds = mean_speed[b_speed_n > 0.01]
    if len(visited_speeds):
        s_lo = (
            config.speed_min_ms
            if config.speed_min_ms is not None
            else np.percentile(visited_speeds, config.auto_range_pct)
        )
        s_hi = (
            config.speed_max_ms
            if config.speed_max_ms is not None
            else np.percentile(visited_speeds, 100 - config.auto_range_pct)
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
            config.hr_min_bpm
            if config.hr_min_bpm is not None
            else np.percentile(visited_hrs, config.auto_range_pct)
        )
        hr_hi = (
            config.hr_max_bpm
            if config.hr_max_bpm is not None
            else np.percentile(visited_hrs, 100 - config.auto_range_pct)
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
        g_lo = np.percentile(visited_grads, config.auto_range_pct)
        g_hi = np.percentile(visited_grads, 100 - config.auto_range_pct)
        grad_norm = np.clip((mean_grad - g_lo) / (g_hi - g_lo), 0, 1)
        grad_norm = np.where(b_grad_n > 0, grad_norm, 0)
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
            abs(np.percentile(visited_elevs, config.auto_range_pct)),
            abs(np.percentile(visited_elevs, 100 - config.auto_range_pct)),
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
        if not np.any(binary):
            return np.zeros_like(binary)
        blurred = gaussian_filter(binary, sigma=blur_sigma)
        sat = np.percentile(blurred[binary > 0], pct)
        return np.clip(blurred / sat, 0, 1) if sat > 0 else blurred

    alpha_speed = presence_alpha(speed_n, sigma)
    alpha_hr = presence_alpha(hr_n, sigma)
    _presence_grad = presence_alpha(grad_n, sigma) if n_grad_px else np.zeros_like(grad_norm)
    alpha_grad = _presence_grad * (0.15 + 0.85 * grad_norm)
    alpha_elev = presence_alpha(elev_n, sigma) if n_elev_px else np.zeros_like(elev_norm)

    # Save max_passes before cleanup
    max_passes = int(max_count)

    # Clean up intermediate arrays
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

    return {
        "count_norm": count_norm,
        "count_log_norm": count_log_norm,
        "speed_norm": speed_norm,
        "hr_norm": hr_norm,
        "grad_norm": grad_norm,
        "elev_norm": elev_norm,
        "alpha_speed": alpha_speed,
        "alpha_hr": alpha_hr,
        "alpha_grad": alpha_grad,
        "alpha_elev": alpha_elev,
        "s_lo": s_lo,
        "s_hi": s_hi,
        "hr_lo": hr_lo,
        "hr_hi": hr_hi,
        "g_lo": g_lo,
        "g_hi": g_hi,
        "max_passes": max_passes,
    }
