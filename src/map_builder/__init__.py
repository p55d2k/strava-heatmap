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
    DEFAULT_LEGEND_STYLES,
    EXCLUSIVE_LAYER_NAMES,
    LAYER_CONTROL_CSS,
    LEGEND_IDS,
)
from src.map_builder.control import (
    ExclusiveLayerControl,
)
from src.map_builder.legend import (
    LegendBuilder,
    build_legend_html,
    legend_row,
    pace_str,
)
from src.map_builder.map_builder import (
    build_map,
)
from src.map_builder.utils import (
    cmap_to_css,
)

__all__ = [
    # Constants
    "LAYER_CONTROL_CSS",
    "EXCLUSIVE_LAYER_NAMES",
    "LEGEND_IDS",
    "DEFAULT_LEGEND_STYLES",
    # Legend
    "pace_str",
    "legend_row",
    "build_legend_html",
    "LegendBuilder",
    # Control
    "ExclusiveLayerControl",
    # Map builder
    "build_map",
    # Utils
    "cmap_to_css",
]
