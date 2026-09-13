"""
Map Builder Package - Modular map building components.

This package provides components for building interactive heatmap visualizations
with customizable legends and layer controls.

Modules:
- constants: Shared constants and configuration
- legend: Legend generation functions
- control: Layer control and exclusive layer handling
- map_builder: Main map building function
- utils: Utility functions
"""

from src.map_builder.constants import (
    CARTO_STYLE_LABELS,
    CARTO_STYLES,
    DEFAULT_CARTO_STYLE,
    DEFAULT_LEGEND_STYLES,
    DENSITY_LAYER_NAMES,
    EXCLUSIVE_LAYER_NAMES,
    LEGEND_IDS,
    METRIC_LAYER_NAMES,
)
from src.map_builder.control import (
    ControlPanel,
    ExclusiveLayerControl,
    build_control_panel_html,
    build_layer_group_config,
    carto_basemap_choices,
    control_panel_script,
    controls_css,
)
from src.map_builder.legend import (
    LegendBuilder,
    LegendContext,
    LegendRow,
    build_legend_html,
    legend_row,
    pace_str,
)
from src.map_builder.map_builder import (
    build_map,
    build_tile_url,
    get_carto_api_key,
)
from src.map_builder.utils import (
    cmap_to_css,
)

__all__ = [
    # Constants
    "EXCLUSIVE_LAYER_NAMES",
    "DENSITY_LAYER_NAMES",
    "METRIC_LAYER_NAMES",
    "LEGEND_IDS",
    "DEFAULT_LEGEND_STYLES",
    "CARTO_STYLES",
    "CARTO_STYLE_LABELS",
    "DEFAULT_CARTO_STYLE",
    # Legend
    "pace_str",
    "legend_row",
    "build_legend_html",
    "LegendBuilder",
    "LegendContext",
    "LegendRow",
    # Control
    "ExclusiveLayerControl",
    "ControlPanel",
    "controls_css",
    "build_control_panel_html",
    "build_layer_group_config",
    "control_panel_script",
    "carto_basemap_choices",
    # Map builder
    "build_map",
    "build_tile_url",
    "get_carto_api_key",
    # Utils
    "cmap_to_css",
]
