"""
Shared constants for the map_builder package.

These constants encapsulate styling and configuration that can be customized
independently of the map building logic.
"""

LAYER_CONTROL_CSS = """
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

# Layer names that are mutually exclusive in the layer control.
EXCLUSIVE_LAYER_NAMES = [
    "GPS Density (linear)",
    "GPS Density (log)",
    "Pace (average)",
    "Heart rate (average)",
    "Gradient (absolute)",
    "Gradient (change)",
]

# Maps each exclusive layer name to its corresponding legend DIV id.
LEGEND_IDS = {
    "GPS Density (linear)": "legend-frequency",
    "GPS Density (log)": "legend-frequency-log",
    "Pace (average)": "legend-pace-avg",
    "Heart rate (average)": "legend-heart-rate-avg",
    "Gradient (absolute)": "legend-gradient",
    "Gradient (change)": "legend-elev-change",
}

# Default inline styles for the legend container.
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
