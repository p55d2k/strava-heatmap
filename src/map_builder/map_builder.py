"""
Main map building function for the heatmap.

This module provides the primary `build_map` function that assembles
the Folium map with layers, controls, legend, and saves to HTML.
"""

import os
from pathlib import Path

import folium

from src.map_builder.constants import LAYER_CONTROL_CSS
from src.map_builder.control import ExclusiveLayerControl


def build_map(
    tracks: list[tuple[str, list]],
    layers: list[tuple[str, str, bool]],
    bounds: list[list[float]],
    centre: list[float],
    legend_html: str,
    output_path: Path,
    map_opacity: float,
) -> None:
    """Build and save the Folium map.

    Args:
        tracks: List of (label, points) where points are [lat, lon] pairs.
        layers: List of (name, image_uri, visible) for each overlay layer.
        bounds: [[lat_sw, lon_sw], [lat_ne, lon_ne]] bounds for image overlays.
        centre: [lat, lon] center point for initial map view.
        legend_html: HTML string for the legend (from LegendBuilder.build()).
        output_path: Path to save the output HTML file.
        map_opacity: Opacity value (0-1) for the heatmap image overlays.
    """
    m = folium.Map(location=centre, zoom_start=14, tiles=None, control_scale=True)
    folium.TileLayer(
        "CartoDB.DarkMatterNoLabels",
        name="Basemap",
        control=False,
        show=True,
    ).add_to(m)

    track_group = folium.FeatureGroup(name="Raw GPS tracks", show=False)
    for label, pts in tracks:
        folium.PolyLine(
            locations=[(p[0], p[1]) for p in pts],
            color="#fc4c02",
            weight=1,
            opacity=0.4,
            tooltip=label,
        ).add_to(track_group)
    track_group.add_to(m)

    for name, uri, visible in layers:
        fg = folium.FeatureGroup(name=name, show=visible)
        folium.raster_layers.ImageOverlay(
            image=uri,
            bounds=bounds,
            opacity=map_opacity,
            interactive=False,
            cross_origin=False,
            zindex=1,
        ).add_to(fg)
        fg.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.get_root().html.add_child(folium.Element(LAYER_CONTROL_CSS))
    m.get_root().html.add_child(folium.Element(legend_html))
    ExclusiveLayerControl().add_to(m)

    m.save(output_path)
    import logging

    log = logging.getLogger(__name__)
    log.info(f"Saved: {output_path}")
    log.info(f"Open:  file://{os.path.abspath(output_path)}")
