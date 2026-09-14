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

# Decay strategies selectable in the control panel. These mirror the values of
# the DECAY_STRATEGY config key. Labels are shown in the panel dropdown; short
# tokens are used inside layer names and normalized-grid dict keys.
DECAY_STRATEGIES = ["decay", "binary-per-activity", "raw-count"]

DECAY_STRATEGY_LABELS = {
    "decay": "Decay",
    "binary-per-activity": "Binary per activity",
    "raw-count": "Raw count",
}

DEFAULT_DECAY_STRATEGY = "binary-per-activity"

DECAY_STRATEGY_SHORT = {
    "decay": "decay",
    "binary-per-activity": "binary",
    "raw-count": "raw",
}


def strategy_norm_keys(strategy: str) -> tuple[str, str]:
    """Return the ``(norm, log_norm)`` keys for a strategy in the normalized dict."""
    short = DECAY_STRATEGY_SHORT[strategy]
    if strategy == "decay":
        return "count_norm", "count_log_norm"
    return f"count_{short}_norm", f"count_{short}_log_norm"


def density_layer_names(strategy: str) -> list[str]:
    """Return the two density layer names (linear, log) for a strategy."""
    short = DECAY_STRATEGY_SHORT[strategy]
    return [f"GPS Density ({short} · linear)", f"GPS Density ({short} · log)"]


def strategy_layers_map() -> dict[str, list[str]]:
    """Map each strategy key to its ``[linear, log]`` density layer names."""
    return {strat: density_layer_names(strat) for strat in DECAY_STRATEGIES}


# GPS density variants are alternative renderings of the SAME count data, so
# they stay mutually exclusive (a radio group) in the layer control. Each
# strategy contributes a linear + log pair.
DENSITY_LAYER_NAMES = [layer for strat in DECAY_STRATEGIES for layer in density_layer_names(strat)]

# Distinct analysis metrics that may each be overlaid independently; these are
# rendered as independent checkboxes in the layer control.
METRIC_LAYER_NAMES = [
    "Pace (average)",
    "Heart rate (average)",
    "Gradient (absolute)",
    "Gradient (change)",
]

# Default stroke opacity for the raw GPS track polylines.  Kept as a constant
# so that both the Folium PolyLine build step and the control-panel layer-group
# config agree on the initial value the per-layer opacity slider starts at.
TRACK_OPACITY = 0.4

# Backwards-compatible alias for the set of mutually exclusive (radio) layers.
EXCLUSIVE_LAYER_NAMES = DENSITY_LAYER_NAMES


# Maps each exclusive layer name to its corresponding legend DIV id. The ids
# mirror the ones produced by ``LegendBuilder.default_rows`` so the dynamic
# layer control can show/hide the right legend row.
def _build_legend_ids() -> dict[str, str]:
    ids: dict[str, str] = {}
    for strat in DECAY_STRATEGIES:
        short = DECAY_STRATEGY_SHORT[strat]
        linear, log = density_layer_names(strat)
        ids[linear] = f"legend-frequency-{short}"
        ids[log] = f"legend-frequency-{short}-log"
    ids.update(
        {
            "Pace (average)": "legend-pace-avg",
            "Heart rate (average)": "legend-heart-rate-avg",
            "Gradient (absolute)": "legend-gradient",
            "Gradient (change)": "legend-elev-change",
        }
    )
    return ids


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
