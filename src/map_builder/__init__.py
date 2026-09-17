"""
Map Builder Package - Modular map building components.

This package provides components for building interactive heatmap visualizations
with customizable legends and layer controls.

Modules:
- constants: Shared constants and configuration
- embed: Compressed payloads embedded in the generated page
- legend: Legend generation functions
- control: Layer control and exclusive layer handling
- map_builder: Main map building function
- utils: Utility functions
"""

from src.map_builder.constants import (
    CARTO_STYLE_LABELS,
    CARTO_STYLES,
    COVERAGE_LAYER,
    DEFAULT_CARTO_STYLE,
    DEFAULT_LEGEND_STYLES,
    DEFAULT_RASTER_MODE,
    DENSITY_LAYER_NAMES,
    DENSITY_MODE_LAYERS,
    DENSITY_VIRTUAL_LAYER,
    EXCLUSIVE_LAYER_NAMES,
    INDEPENDENT_LAYER_NAMES,
    LEGEND_IDS,
    METRIC_LAYER_NAMES,
    RASTER_MODE_LABELS,
    RASTER_MODES,
    TIME_SPENT_LAYER,
)
from src.map_builder.control import (
    ControlPanel,
    ExclusiveLayerControl,
    build_advanced_config,
    build_control_panel_html,
    build_layer_group_config,
    carto_basemap_choices,
    control_panel_script,
    controls_css,
)
from src.map_builder.embed import (
    decode_embedded,
    encode_for_embedding,
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
    ScalableHomeMarker,
    build_map,
    build_tile_url,
    get_carto_api_key,
    home_marker_radius,
)
from src.map_builder.utils import (
    cmap_to_css,
)

__all__ = [
    # Constants
    "EXCLUSIVE_LAYER_NAMES",
    "DENSITY_LAYER_NAMES",
    "METRIC_LAYER_NAMES",
    "INDEPENDENT_LAYER_NAMES",
    "TIME_SPENT_LAYER",
    "COVERAGE_LAYER",
    "DENSITY_VIRTUAL_LAYER",
    "DENSITY_MODE_LAYERS",
    "LEGEND_IDS",
    "DEFAULT_LEGEND_STYLES",
    "CARTO_STYLES",
    "CARTO_STYLE_LABELS",
    "DEFAULT_CARTO_STYLE",
    "RASTER_MODES",
    "RASTER_MODE_LABELS",
    "DEFAULT_RASTER_MODE",
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
    "build_advanced_config",
    "control_panel_script",
    "carto_basemap_choices",
    # Embed
    "encode_for_embedding",
    "decode_embedded",
    # Map builder
    "ScalableHomeMarker",
    "build_map",
    "build_tile_url",
    "get_carto_api_key",
    "home_marker_radius",
    # Utils
    "cmap_to_css",
]
