"""
Main map building function for the heatmap.

This module provides the primary `build_map` function that assembles
the Folium map with layers, controls, legend, and saves to HTML.
"""

import os
from pathlib import Path

import folium
from dotenv import load_dotenv

from src.map_builder.constants import (
    DEFAULT_CARTO_STYLE,
    DEFAULT_DECAY_STRATEGY,
    TRACK_OPACITY,
)
from src.map_builder.control import (
    ControlPanel,
    ExclusiveLayerControl,
    build_layer_group_config,
    controls_css,
)

# Load variables from .env (without overriding already-set environment variables).
load_dotenv()

CARTO_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> '
    'contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
)


def get_carto_api_key() -> str:
    """Return the CARTO API key from the `CARTO_API_KEY` environment variable.

    The key must be provided via a `.env` file (see ``.env.example``) or the
    exported `CARTO_API_KEY` environment variable.

    Raises:
        ValueError: If `CARTO_API_KEY` is missing or blank.
    """
    key = os.getenv("CARTO_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "CARTO_API_KEY is not set.\n"
            "  -> Copy .env.example to .env and add your CARTO_API_KEY.\n"
            "  -> Get a key at https://carto.com/developers/tiles"
        )
    return key


def build_tile_url(style: str = DEFAULT_CARTO_STYLE) -> str:
    """Build the CARTO raster tile URL, including the API key.

    Args:
        style: CARTO tile style. One of "voyager", "light_all", "dark_all".

    Returns:
        A tile URL template with {z}/{x}/{y} placeholders and the API key.
    """
    key = get_carto_api_key()
    return f"https://basemaps.cartocdn.com/rastertiles/{style}/{{z}}/{{x}}/{{y}}.png?key={key}"


def build_map(
    tracks: list[tuple[str, list]],
    layers: list[tuple[str, str, bool]],
    bounds: list[list[float]],
    centre: list[float],
    legend_html: str,
    output_path: Path,
    map_opacity: float,
    carto_style: str = DEFAULT_CARTO_STYLE,
    decay_strategy: str = DEFAULT_DECAY_STRATEGY,
    exclusive_layer_names: list[str] | None = None,
    metric_layer_names: list[str] | None = None,
    legend_ids: dict[str, str] | None = None,
    control_panel: bool = True,
    progress_callback=None,
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
        carto_style: CARTO basemap tile style ("voyager", "light_all", "dark_all").
        decay_strategy: Active decay strategy key; drives the density layer pair
            shown in the control panel's radio group and the dropdown default.
        exclusive_layer_names: Density layer names that should be mutually
            exclusive (radio) and drive density legend visibility. Defaults to
            ``DENSITY_LAYER_NAMES``.
        metric_layer_names: Distinct metric layer names shown as independent
            checkboxes whose legend rows follow their on/off state. Defaults to
            ``METRIC_LAYER_NAMES``.
        legend_ids: Mapping from layer name to legend row DOM id for dynamic
            legend visibility. Defaults to the constants in ``LEGEND_IDS``.
        control_panel: When True, embed the in-HTML control panel (basemap
            style switcher, opacity slider, fit/reset, legend toggle).
        progress_callback: Optional callable invoked with a step count.
    """
    m = folium.Map(location=centre, zoom_start=14, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles=build_tile_url(carto_style),
        attr=CARTO_ATTRIBUTION,
        name="Basemap",
        control=False,
        show=True,
        max_zoom=20,
    ).add_to(m)

    track_group = folium.FeatureGroup(name="Raw GPS tracks", show=False)
    for label, pts in tracks:
        folium.PolyLine(
            locations=[(p[0], p[1]) for p in pts],
            color="#fc4c02",
            weight=1,
            opacity=TRACK_OPACITY,
            tooltip=label,
        ).add_to(track_group)
    track_group.add_to(m)

    if progress_callback:
        progress_callback(1)  # Tracks added

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

    if progress_callback:
        progress_callback(1)  # All layers added

    # A (visually hidden) LayerControl is kept purely so Folium emits its
    # `<layer_control>_layers.overlays` registry, which both the control panel
    # and ExclusiveLayerControl rely on to locate overlay layers by name.
    folium.LayerControl(collapsed=True).add_to(m)
    m.get_root().html.add_child(folium.Element(controls_css()))
    m.get_root().html.add_child(folium.Element(legend_html))
    ExclusiveLayerControl(
        exclusive_names=exclusive_layer_names,
        legend_ids=legend_ids,
        metric_names=metric_layer_names,
    ).add_to(m)

    if control_panel:
        ControlPanel(
            map_opacity=map_opacity,
            carto_style=carto_style,
            decay_strategy=decay_strategy,
            api_key=get_carto_api_key(),
            bounds=bounds,
            centre=centre,
            layer_groups=build_layer_group_config(
                overlay_layers=layers,
                has_tracks=bool(tracks),
                exclusive_layer_names=exclusive_layer_names,
                metric_layer_names=metric_layer_names,
                decay_strategy=decay_strategy,
                map_opacity=map_opacity,
            ),
        ).add_to(m)

    if progress_callback:
        progress_callback(1)  # Controls and legend added

    m.save(output_path)
    import logging

    log = logging.getLogger(__name__)
    log.info(f"Saved: {output_path}")
    log.info(f"Open:  file://{os.path.abspath(output_path)}")
