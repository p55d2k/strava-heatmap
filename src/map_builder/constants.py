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

# GPS density variants are alternative renderings of the SAME count data, so
# they stay mutually exclusive (a radio group) in the layer control.
DENSITY_LAYER_NAMES = [
    "GPS Density (linear)",
    "GPS Density (log)",
]

# Distinct analysis metrics that may each be overlaid independently; these are
# rendered as independent checkboxes in the layer control.
METRIC_LAYER_NAMES = [
    "Pace (average)",
    "Heart rate (average)",
    "Gradient (absolute)",
    "Gradient (change)",
]

# Backwards-compatible alias for the set of mutually exclusive (radio) layers.
EXCLUSIVE_LAYER_NAMES = DENSITY_LAYER_NAMES

# Maps each exclusive layer name to its corresponding legend DIV id.
LEGEND_IDS = {
    "GPS Density (linear)": "legend-frequency",
    "GPS Density (log)": "legend-frequency-log",
    "Pace (average)": "legend-pace-avg",
    "Heart rate (average)": "legend-heart-rate-avg",
    "Gradient (absolute)": "legend-gradient",
    "Gradient (change)": "legend-elev-change",
}

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
