"""
Pipeline Stage 3: Color Maps & Image Generation
Handles colormap creation and layer URI generation.
"""

import base64
from io import BytesIO

import matplotlib.colors as mcolors
import numpy as np
from PIL import Image


def build_cmap(name: str, nodes: list) -> mcolors.LinearSegmentedColormap:
    """Build a LinearSegmentedColormap from a list of (position, (R,G,B,A)) nodes."""
    pos = [n[0] for n in nodes]
    cdict = {}
    for ci, ch in enumerate(("red", "green", "blue", "alpha")):
        vals = [n[1][ci] for n in nodes]
        cdict[ch] = [(pos[i], vals[i], vals[i]) for i in range(len(pos))]
    return mcolors.LinearSegmentedColormap(name, cdict, N=512)


def create_colormaps() -> dict:
    """Create all colormaps used for visualization."""
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

    return {
        "cmap_count": cmap_count,
        "cmap_speed_rgb": cmap_speed_rgb,
        "cmap_hr_rgb": cmap_hr_rgb,
        "cmap_elev_rgb": cmap_elev_rgb,
    }


def _to_uri(rgba_u8: np.ndarray) -> str:
    """Convert RGBA array to base64 data URI."""
    buf = BytesIO()
    Image.fromarray(rgba_u8, mode="RGBA").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _count_uri(norm: np.ndarray, cmap_count) -> str:
    return _to_uri((cmap_count(norm) * 255).clip(0, 255).astype(np.uint8))


def _rgba_uri(rgb_norm: np.ndarray, alpha_norm: np.ndarray, cmap_rgb) -> str:
    arr = cmap_rgb(rgb_norm).copy()
    arr[:, :, 3] = alpha_norm
    return _to_uri((arr * 255).clip(0, 255).astype(np.uint8))


def _white_uri(alpha_norm: np.ndarray) -> str:
    h, w = alpha_norm.shape
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:, :, :3] = 255
    arr[:, :, 3] = (alpha_norm * 255).clip(0, 255).astype(np.uint8)
    return _to_uri(arr)


def generate_layer_uris(normalized: dict, colormaps: dict) -> list[tuple[str, str, bool]]:
    """Generate data URIs for all map layers."""
    layers = [
        (
            "GPS Density (log)",
            _count_uri(normalized["count_log_norm"], colormaps["cmap_count"]),
            True,
        ),
        (
            "GPS Density (linear)",
            _count_uri(normalized["count_norm"], colormaps["cmap_count"]),
            False,
        ),
        (
            "Pace (average)",
            _rgba_uri(
                normalized["speed_norm"], normalized["alpha_speed"], colormaps["cmap_speed_rgb"]
            ),
            False,
        ),
        (
            "Heart rate (average)",
            _rgba_uri(normalized["hr_norm"], normalized["alpha_hr"], colormaps["cmap_hr_rgb"]),
            False,
        ),
        ("Gradient (absolute)", _white_uri(normalized["alpha_grad"]), False),
        (
            "Gradient (change)",
            _rgba_uri(
                (normalized["elev_norm"] + 1) / 2,
                normalized["alpha_elev"],
                colormaps["cmap_elev_rgb"],
            ),
            False,
        ),
    ]
    return layers
