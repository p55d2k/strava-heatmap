"""
Shared constants for the map_builder package.

These constants encapsulate styling and configuration that can be customized
independently of the map building logic.
"""

# CARTO raster tile styles available in the in-HTML control panel.
DEFAULT_CARTO_STYLE = "dark_all"
CARTO_STYLES = ["voyager", "light_all", "dark_all"]

# Human-friendly labels for the CARTO basemap styles shown in the control panel.
CARTO_STYLE_LABELS = {
    "voyager": "Voyager",
    "light_all": "Light",
    "dark_all": "Dark",
}

# Density concept layers. They render alternative views of the same GPS data
# on different scales, so they form a mutually-exclusive (radio) group in the
# panel — only one is shown at a time:
#   * "GPS Density (Time Spent)"      — decay-weighted pass counts (log scale;
#     DECAY_FACTOR), so brightness reflects time spent on each path.
#   * "GPS Density (Raw Passes)"      — every GPS point increments its cell.
#   * "GPS Density (Unique Visits)"   — each activity contributes max 1 per
#     cell (pure coverage per activity).
#   * "Coverage (Places Visited)"     — fraction of all activities that
#     visited each cell (percentage-of-activities normalization).
# The three "GPS Density (...)" layers are the SAME raster data viewed through
# the three rasterization modes (see src/rasterizer.py::RASTER_MODES); all are
# pre-computed at build time and selectable in the panel without re-rasterizing.
TIME_SPENT_LAYER = "GPS Density (Time Spent)"
COVERAGE_LAYER = "Coverage (Places Visited)"

# One layer name per rasterization mode (keys mirror RASTER_MODES in
# src/rasterizer.py; the default "decay" keeps the historical layer name).
DENSITY_MODE_LAYERS = {
    "decay": TIME_SPENT_LAYER,
    "raw-count": "GPS Density (Raw Passes)",
    "binary-per-activity": "GPS Density (Unique Visits)",
}

DENSITY_LAYER_NAMES = [
    DENSITY_MODE_LAYERS["decay"],
    DENSITY_MODE_LAYERS["raw-count"],
    DENSITY_MODE_LAYERS["binary-per-activity"],
    COVERAGE_LAYER,
]

# Rasterization modes accepted by the pipeline and offered in the panel; the
# default ("decay") comes first.
RASTER_MODES = ("decay", "raw-count", "binary-per-activity")
DEFAULT_RASTER_MODE = "decay"

# Human-friendly labels for the raster modes (used in legend titles).
RASTER_MODE_LABELS = {
    "decay": "Time Spent",
    "raw-count": "Raw Passes",
    "binary-per-activity": "Unique Visits",
}

# Distinct analysis metrics that may each be overlaid independently; these are
# rendered as independent checkboxes in the layer control.
METRIC_LAYER_NAMES = [
    "Pace (average)",
    "Heart rate (average)",
    "Gradient (absolute)",
    "Gradient (change)",
]

# All independently-toggleable concept + metric layers. The raw GPS tracks
# overlay is separate (a vector layer) and is NOT bound to a legend row.
INDEPENDENT_LAYER_NAMES = DENSITY_LAYER_NAMES + METRIC_LAYER_NAMES

# The density-concept Heatmap group (GPS Density / Coverage) is mutually
# exclusive (radio) and is defined by the panel's layer-group config; map-level
# exclusivity is enforced client-side by panel.js. This legacy constant is kept
# empty for backward compatibility — no exclusive names flow into
# ExclusiveLayerControl.
EXCLUSIVE_LAYER_NAMES: list[str] = []

# Default stroke opacity for the raw GPS track polylines.  Kept as a constant
# so that both the Folium PolyLine build step and the control-panel layer-group
# config agree on the initial value the per-layer opacity slider starts at.
TRACK_OPACITY = 0.4


# Maps each layer name to its corresponding legend DIV id. The ids mirror the
# ones produced by ``LegendBuilder.default_rows`` (one GPS Density row per
# raster-mode layer, id ``legend-density-<mode>``) so the dynamic layer control
# can show/hide the right legend row.
def _build_legend_ids() -> dict[str, str]:
    return {layer: f"legend-density-{mode}" for mode, layer in DENSITY_MODE_LAYERS.items()} | {
        COVERAGE_LAYER: "legend-coverage",
        "Pace (average)": "legend-pace-avg",
        "Heart rate (average)": "legend-heart-rate-avg",
        "Gradient (absolute)": "legend-gradient",
        "Gradient (change)": "legend-elev-change",
    }


LEGEND_IDS = _build_legend_ids()

# Optional inline styles for the legend container. The default legend now uses
# the shared ``.hcp-legend`` class from ``assets/panel.css``; these are only
# applied when explicitly passed to ``LegendBuilder(styles=...)`` for custom
# positioning (kept for backward compatibility).
DEFAULT_LEGEND_STYLES = {
    "position": "fixed",
    "bottom": "28px",
    "right": "10px",
    "z-index": "9999",
    "background": "rgba(15,15,15,0.88)",
    "padding": "13px 16px 14px",
    "border-radius": "9px",
    "color": "#ddd",
    "font-family": "sans-serif",
    "font-size": "12px",
    "min-width": "210px",
    "line-height": "1.4",
    "border": "1px solid rgba(255,255,255,0.10)",
    "box-shadow": "0 2px 8px rgba(0,0,0,0.6)",
}
