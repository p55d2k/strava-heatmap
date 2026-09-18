"""
Pipeline Stage 2: Rasterization & Grid Computation
Handles coordinate transforms, grid creation, track rasterization, and normalization.
"""

import gc
import math

import numpy as np
from pyproj import Transformer
from scipy.ndimage import gaussian_filter
from tqdm import tqdm

# Available rasterization modes. The mode decides which of the three strategy
# grids (all painted in a single pass per track) drives the primary "GPS
# Density (Time Spent)" layer:
#
# * "raw-count": every counted GPS point increments its cell (sample density).
# * "decay": exponential decay (DECAY_FACTOR) applied to repeated passes of the
#   same cell within a single activity (time-spent weighting; default).
# * "binary-per-activity": each activity contributes at most 1 per cell
#   (pure coverage).
RASTER_MODES = ("raw-count", "decay", "binary-per-activity")
DEFAULT_RASTER_MODE = "decay"


def _validate_raster_mode(raster_mode: str) -> str:
    """Validate a rasterization mode name, returning it unchanged.

    Raises:
        ValueError: If ``raster_mode`` is not one of :data:`RASTER_MODES`.
    """
    if raster_mode not in RASTER_MODES:
        raise ValueError(
            f"Unknown raster_mode: {raster_mode!r}. Expected one of: {', '.join(RASTER_MODES)}"
        )
    return raster_mode


def _select_primary_count_grid(
    count_grid: np.ndarray,
    count_raw_grid: np.ndarray,
    unique_grid: np.ndarray,
    raster_mode: str,
) -> np.ndarray:
    """Return the count grid that drives the primary density layer.

    Args:
        count_grid: Decay-weighted pass-count grid ("decay" mode).
        count_raw_grid: Raw GPS sample count grid ("raw-count" mode).
        unique_grid: Binary-per-activity coverage grid
            ("binary-per-activity" mode).
        raster_mode: One of :data:`RASTER_MODES`.

    Returns:
        The strategy grid selected by ``raster_mode``.
    """
    _validate_raster_mode(raster_mode)
    if raster_mode == "raw-count":
        return count_raw_grid
    if raster_mode == "binary-per-activity":
        return unique_grid
    return count_grid


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

    # Additional count grids for the other decay strategies. These are appended at
    # the END of the tuple so that `paint_segment`'s positional metric-grid indices
    # (3..10) remain unchanged.
    count_raw_grid = np.zeros((grid_h, grid_w), dtype=np.float32)
    unique_grid = np.zeros((grid_h, grid_w), dtype=np.float32)

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
        count_raw_grid,
        unique_grid,
    )


def _geom_sum(n_visits: int, decay_factor: float) -> float:
    """Return the geometric sum 1 + d + d^2 + ... + d^(n-1) for a decay factor d."""
    if n_visits <= 1:
        return 1.0
    if decay_factor <= 0.0:
        return 1.0
    if decay_factor >= 1.0:
        return float(n_visits)
    return (1.0 - decay_factor**n_visits) / (1.0 - decay_factor)


def _rasterize_track_points(
    track_pts: list,
    px: np.ndarray,
    py: np.ndarray,
    grid_w: int,
    grid_h: int,
    count_grid: np.ndarray,
    count_raw_grid: np.ndarray,
    unique_grid: np.ndarray,
    max_consecutive_same_cell: int,
    decay_factor: float = 0.5,
    cell_activities: dict[tuple[int, int], set[int]] | None = None,
    activity_index: int | None = None,
) -> int:
    """Rasterize a single track's points onto the strategy count grids.

    Each activity (track) is processed in ONE pass with a consecutive-cell cap. For
    every cell that is actually counted (i.e. passes ``max_consecutive_same_cell``),
    we accumulate the number of counted visits ``n``. At the end of the activity we
    distribute ``n`` into the three strategy grids:

    * ``count_raw_grid``  — ``raw-count``: every counted pass contributes ``n``.
    * ``unique_grid``     — ``binary-per-activity`` (coverage): contributes ``1`` if ``n > 0``.
    * ``count_grid``       — ``decay``: contributes the geometric sum
      ``1 + decay_factor + decay_factor^2 + ... + decay_factor^(n-1)``.

    This keeps rasterization cost at a single point loop (no per-strategy re-passes)
    while deriving all three strategies from the same visit counts. The consecutive
    cap prevents a stationary stretch (e.g. a forgotten stop) from dominating, and
    the decay resets per activity so genuine multi-day coverage is unaffected.

    When ``cell_activities`` and ``activity_index`` are supplied, every cell the
    activity was counted in is recorded as ``cell_activities[(row, col)]``
    gaining ``activity_index``. That index is what the map's click tooltips
    query to list the activities behind a painted pixel (see
    :mod:`src.activity_index`); collecting it here keeps it in exact step with
    the heatmap, because it reuses the same counted visits rather than
    re-walking the track.

    Returns:
        ``1`` if the activity contributed at least one cell to the coverage
        (``unique_grid``), else ``0``. This is used as the denominator for
        percentage-of-activities coverage normalization.
    """
    same_cell_run = 0
    prev_xi = prev_yi = None
    # Track visits per cell within this activity (counted samples only)
    cell_visits: dict[tuple[int, int], int] = {}

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
                cell_visits[(xi, yi)] = cell_visits.get((xi, yi), 0) + 1

    if not cell_visits:
        return 0
    if cell_activities is not None and activity_index is not None:
        for xi, yi in cell_visits:
            cell_activities.setdefault((yi, xi), set()).add(activity_index)
    for (xi, yi), n_visits in cell_visits.items():
        count_raw_grid[yi, xi] += n_visits
        unique_grid[yi, xi] += 1
        count_grid[yi, xi] += _geom_sum(n_visits, decay_factor)
    return 1


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
    decay_factor: float = 0.5,
    raster_mode: str = DEFAULT_RASTER_MODE,
    cell_activities: dict[tuple[int, int], set[int]] | None = None,
) -> int:
    """Rasterize all tracks onto the grids.

    Points are incrementally binned into the count grid. To avoid a single
    stationary stretch (e.g. forgetting to stop the watch) from dominating the
    linear frequency layer, at most `max_consecutive_same_cell` consecutive
    samples that fall in the *same* grid cell are counted; once the cap is hit,
    subsequent consecutive samples in that cell are skipped until the track
    leaves the cell (a later return to the cell resets the counter, so genuine
    re-visits are still counted).

    All three count strategies are painted in the same single pass per track:

    * ``count_grid``       — "decay": geometric decay (``decay_factor``**n)
      applied to repeated passes of the same cell within one activity, so
      loop/out-and-back routes (e.g. running-track laps) don't inflate the pass
      count. The decay resets per activity, so genuine coverage across
      different days is preserved.
    * ``count_raw_grid``   — "raw-count": every counted GPS point increments
      its cell.
    * ``unique_grid``      — "binary-per-activity": each activity contributes
      at most 1 per cell.

    ``raster_mode`` only selects which of the three grids drives the primary
    density layer downstream (see :func:`compute_normalized_grids`); the
    painting itself is identical for every mode. It is validated here so an
    invalid mode fails fast before any rasterization work is done.

    When ``cell_activities`` is supplied it is filled with ``(row, col) ->``
    the set of track indices that were counted in that cell, using the same
    clipped points and bounds as the painting. The map's click tooltips read it
    to list the activities behind a painted pixel.

    Returns:
        The number of activities that contributed at least one counted cell.
        This is the denominator for the percentage-of-activities coverage
        normalization (activities that produced no in-bounds / counted samples
        are excluded).
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
        count_raw_grid,
        unique_grid,
    ) = grids

    _validate_raster_mode(raster_mode)

    rasterized_count = 0

    for activity_index, (_, track_pts) in enumerate(
        tqdm(tracks, desc="Rasterizing tracks", unit="track")
    ):
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

        rasterized_count += _rasterize_track_points(
            track_pts,
            px,
            py,
            grid_w,
            grid_h,
            count_grid,
            count_raw_grid,
            unique_grid,
            max_consecutive_same_cell,
            decay_factor,
            cell_activities,
            activity_index,
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

    return rasterized_count


def _compute_count_grid(count_grid: np.ndarray, sigma: float) -> tuple:
    """Compute normalized count grids."""
    b_count = gaussian_filter(count_grid, sigma=sigma)
    max_count = b_count.max()
    if max_count > 0:
        count_norm = b_count / max_count
        count_log_norm = np.log1p(b_count) / np.log1p(max_count)
    else:
        count_norm = np.zeros_like(b_count)
        count_log_norm = np.zeros_like(b_count)
    return count_norm, count_log_norm, b_count, max_count


def _compute_speed_grid(speed_sum: np.ndarray, speed_n: np.ndarray, sigma: float, config) -> tuple:
    """Compute normalized speed grid."""
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
    return speed_norm, s_lo, s_hi


def _compute_hr_grid(hr_sum: np.ndarray, hr_n: np.ndarray, sigma: float, config) -> tuple:
    """Compute normalized HR grid."""
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
    return hr_norm, hr_lo, hr_hi


def _compute_grad_grid(grad_sum: np.ndarray, grad_n: np.ndarray, sigma: float, config) -> tuple:
    """Compute normalized gradient grid."""
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
    return grad_norm, g_lo, g_hi, n_grad_px


def _compute_elev_grid(elev_sum: np.ndarray, elev_n: np.ndarray, sigma: float, config) -> tuple:
    """Compute normalized elevation grid."""
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
    return elev_norm, n_elev_px


def _compute_alpha_masks(
    speed_n: np.ndarray,
    hr_n: np.ndarray,
    grad_n: np.ndarray,
    elev_n: np.ndarray,
    grad_norm: np.ndarray,
    n_grad_px: int,
    n_elev_px: int,
    sigma: float,
) -> tuple:
    """Compute alpha masks for all grids."""

    def presence_alpha(
        sample_count_grid: np.ndarray, blur_sigma: float, pct: int = 10
    ) -> np.ndarray:
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
    alpha_elev = presence_alpha(elev_n, sigma) if n_elev_px else np.zeros_like(elev_n)
    return alpha_speed, alpha_hr, alpha_grad, alpha_elev


def compute_normalized_grids(
    grids: tuple,
    sigma: float,
    config,
    n_activities: int = 0,
    progress_callback=None,
    raster_mode: str = DEFAULT_RASTER_MODE,
) -> dict:
    """Apply Gaussian blur and compute normalized grids for all metrics.

    ``raster_mode`` selects which strategy grid (all painted by
    :func:`rasterize_tracks`) drives the primary "GPS Density (Time Spent)"
    layer:

    * ``"raw-count"`` — every GPS point increments its cell.
    * ``"decay"`` (default) — exponential decay (``DECAY_FACTOR``) on repeated
      passes of the same cell within one activity.
    * ``"binary-per-activity"`` — each activity contributes max 1 per cell.

    All strategy grids are still normalized and exposed in the result dict, so
    downstream consumers can switch views without re-rasterizing.
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
        count_raw_grid,
        unique_grid,
    ) = grids
    if progress_callback:
        progress_callback(1)  # Count grid done

    # Normalize EVERY strategy grid so the map builder can bake one GPS Density
    # layer per raster mode; ``count_log_norm`` / ``max_passes`` keep reflecting
    # the mode the pipeline was run with (``raster_mode``).
    count_norm, count_log_norm, b_count, max_count = _compute_count_grid(
        _select_primary_count_grid(count_grid, count_raw_grid, unique_grid, raster_mode),
        sigma,
    )
    count_raw_norm, count_raw_log_norm, _b_raw, max_count_raw = _compute_count_grid(
        count_raw_grid, sigma
    )
    unique_norm, unique_log_norm, _b_bin, max_count_unique = _compute_count_grid(unique_grid, sigma)
    count_log_norms = {
        "decay": count_log_norm,
        "raw-count": count_raw_log_norm,
        "binary-per-activity": unique_log_norm,
    }

    # Percentage-of-activities coverage normalization: each cell = (number of
    # distinct activities that visited it) / (total activities). 1.0 means every
    # activity visited the cell. This preserves the full 1x-to-Nx contrast so
    # frequently-visited and rarely-visited routes are clearly distinguishable.
    # Guard against a zero/absent activity count.
    unique_pct_norm = np.clip(_b_bin / max(int(n_activities), 1), 0, 1)
    coverage_normalization = getattr(config, "coverage_normalization", "pct")

    if progress_callback:
        progress_callback(1)  # Speed grid done

    speed_norm, s_lo, s_hi = _compute_speed_grid(speed_sum, speed_n, sigma, config)

    if progress_callback:
        progress_callback(1)  # HR grid done

    hr_norm, hr_lo, hr_hi = _compute_hr_grid(hr_sum, hr_n, sigma, config)

    if progress_callback:
        progress_callback(1)  # Gradient grid done

    grad_norm, g_lo, g_hi, n_grad_px = _compute_grad_grid(grad_sum, grad_n, sigma, config)

    if progress_callback:
        progress_callback(1)  # Elevation grid done

    elev_norm, n_elev_px = _compute_elev_grid(elev_sum, elev_n, sigma, config)

    if progress_callback:
        progress_callback(1)  # Alpha masks done

    alpha_speed, alpha_hr, alpha_grad, alpha_elev = _compute_alpha_masks(
        speed_n, hr_n, grad_n, elev_n, grad_norm, n_grad_px, n_elev_px, sigma
    )

    # Save max_passes before cleanup. ``max_count`` belongs to the *primary*
    # grid; the per-strategy breakdown must always report the decay grid's own
    # max, so blur it separately when another mode is primary.
    max_passes = int(max_count)
    if raster_mode == "decay":
        max_passes_decay = max_passes
    else:
        max_passes_decay = int(gaussian_filter(count_grid, sigma=sigma).max())

    # Clean up intermediate arrays
    del count_grid, count_raw_grid, unique_grid, speed_sum, speed_n, hr_sum, hr_n
    del grad_sum, grad_n, elev_sum, elev_n
    del b_count, _b_raw, _b_bin
    gc.collect()

    return {
        "count_norm": count_norm,
        "count_log_norm": count_log_norm,
        "count_raw_norm": count_raw_norm,
        "count_raw_log_norm": count_raw_log_norm,
        "unique_norm": unique_norm,
        "unique_log_norm": unique_log_norm,
        "unique_pct_norm": unique_pct_norm,
        "raster_mode": raster_mode,
        "count_log_norms": count_log_norms,
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
        "max_passes_raw": int(max_count_raw),
        "max_passes_unique": int(max_count_unique),
        "max_passes_by_strategy": {
            "decay": max_passes_decay,
            "raw-count": int(max_count_raw),
            "binary-per-activity": int(max_count_unique),
        },
        "n_activities": int(n_activities),
        "coverage_normalization": coverage_normalization,
    }
