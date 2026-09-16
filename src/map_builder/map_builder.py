"""
Main map building function for the heatmap.

This module provides the primary `build_map` function that assembles
the Folium map with layers, controls, legend, and saves to HTML.
"""

import os
from pathlib import Path

import folium
from dotenv import load_dotenv
from folium import MacroElement
from jinja2 import Template

from src.map_builder.constants import (
    DEFAULT_CARTO_STYLE,
    INDEPENDENT_LAYER_NAMES,
    METRIC_LAYER_NAMES,
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


# Home marker sizing — Google-Maps style: the marker should shrink as you zoom
# out and grow as you zoom in, instead of being a fixed-size dot that looks
# oversized on a zoomed-out map.
HOME_MARKER_BASE_ZOOM = 14  # the map's initial zoom_start
HOME_MARKER_MIN_RADIUS = 4  # px, at low zoom
HOME_MARKER_MAX_RADIUS = 18  # px, at high zoom


def home_marker_radius(zoom: int, base_zoom: int = HOME_MARKER_BASE_ZOOM) -> int:
    """Return the home-marker radius (px) for a given map zoom level.

    The radius grows gently with zoom: ~6 px at the default zoom of 14 up to a
    clamped maximum at very high zoom, and never smaller than ``MIN_RADIUS`` so
    the marker stays visible when zoomed all the way out.
    """
    radius = 6 + (zoom - base_zoom) * 1.2
    return max(HOME_MARKER_MIN_RADIUS, min(HOME_MARKER_MAX_RADIUS, round(radius)))


class ScalableHomeMarker(MacroElement):
    """A home pin that scales its radius with the map zoom level.

    Renders a ``L.circleMarker`` (a round, white-ringed dot in the Strava
    orange) and, client-side, listens on the map's ``zoomend`` event so the
    marker's pixel radius tracks the zoom — small when zoomed out, larger when
    zoomed in — instead of being a fixed-size icon.
    """

    _template = Template(
        """
        {% macro script(this, kwargs) %}
            var {{ this.get_name() }} = L.circleMarker(
                {{ this._location|tojson }},
                {
                    radius: {{ this._initial_radius }},
                    color: "#ffffff",
                    weight: 2.5,
                    opacity: 1,
                    fillColor: "#fc4c02",
                    fillOpacity: 1,
                    interactive: true,
                    homeMarker: true
                }
            ).addTo({{ this._parent.get_name() }});
            {{ this.get_name() }}.bindTooltip("Home");

            function {{ this.get_name() }}_radius(zoom) {
                var r = 6 + (zoom - {{ this._base_zoom }}) * 1.2;
                return Math.max({{ this._min_radius }}, Math.min({{ this._max_radius }}, Math.round(r)));
            }
            function {{ this.get_name() }}_resize() {
                {{ this.get_name() }}.setRadius(
                    {{ this.get_name() }}_radius({{ this._parent.get_name() }}.getZoom())
                );
            }
            {{ this.get_name() }}_resize();
            {{ this._parent.get_name() }}.on("zoomend", {{ this.get_name() }}_resize);
        {% endmacro %}
        """
    )

    def __init__(
        self,
        location: list[float],
        base_zoom: int = HOME_MARKER_BASE_ZOOM,
    ):
        """Initialize the scalable home marker.

        Args:
            location: ``[lat, lon]`` for the home position.
            base_zoom: Zoom level the radius formula is anchored to.
        """
        super().__init__()
        self._name = "ScalableHomeMarker"
        self._location = location
        self._base_zoom = base_zoom
        self._initial_radius = home_marker_radius(base_zoom, base_zoom)
        self._min_radius = HOME_MARKER_MIN_RADIUS
        self._max_radius = HOME_MARKER_MAX_RADIUS


def build_map(
    tracks: list[tuple[str, list]],
    layers: list[tuple[str, str, bool]],
    bounds: list[list[float]],
    centre: list[float],
    legend_html: str,
    output_path: Path,
    map_opacity: float,
    carto_style: str = DEFAULT_CARTO_STYLE,
    exclusive_layer_names: list[str] | None = None,
    metric_layer_names: list[str] | None = None,
    legend_ids: dict[str, str] | None = None,
    home: list[float] | None = None,
    control_panel: bool = True,
    progress_callback=None,
) -> None:
    """Build and save the Folium map.

    Args:
        tracks: List of (label, points) where points are [lat, lon] pairs.
        layers: List of (name, image_uri, visible) for each overlay layer.
        bounds: [[lat_sw, lon_sw], [lat_ne, lon_ne]] bounds for image overlays.
        centre: [lat, lon] center point for the bounding box of data.
        legend_html: HTML string for the legend (from LegendBuilder.build()).
        output_path: Path to save the output HTML file.
        map_opacity: Opacity value (0-1) for the heatmap image overlays.
        carto_style: CARTO basemap tile style ("voyager", "light_all", "dark_all").
        exclusive_layer_names: Layer names rendered as mutually exclusive (radio).
            Defaults to empty; the density-concept Heatmap radio group and its
            map-level exclusivity are defined by the panel layer-group config and
            enforced client-side by panel.js.
        metric_layer_names: Independent layer names whose legend rows follow their
            on/off state. Defaults to ``INDEPENDENT_LAYER_NAMES`` (the two density
            concepts plus the four metrics).
        legend_ids: Mapping from layer name to legend row DOM id for dynamic
            legend visibility. Defaults to the constants in ``LEGEND_IDS``.
        home: [lat, lon] home location used for initial map view, the Reset
            button, and a visible home marker. Falls back to ``centre`` when
            ``None``.
        control_panel: When True, embed the in-HTML control panel (basemap
            style switcher, opacity slider, fit/reset, legend toggle).
        progress_callback: Optional callable invoked with a step count.
    """
    map_location = home if home is not None else centre
    m = folium.Map(location=map_location, zoom_start=14, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles=build_tile_url(carto_style),
        attr=CARTO_ATTRIBUTION,
        name="Basemap",
        control=False,
        show=True,
        max_zoom=20,
    ).add_to(m)

    # Add a zoom-responsive marker for the home location so it is visually
    # identifiable on the map without being a giant fixed dot (it shrinks/grows
    # with zoom, Google-Maps style).
    if home is not None:
        ScalableHomeMarker(location=[home[0], home[1]]).add_to(m)

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
        metric_names=(
            metric_layer_names if metric_layer_names is not None else INDEPENDENT_LAYER_NAMES
        ),
    ).add_to(m)

    if control_panel:
        ControlPanel(
            map_opacity=map_opacity,
            carto_style=carto_style,
            api_key=get_carto_api_key(),
            bounds=bounds,
            centre=centre,
            home=home,
            layer_groups=build_layer_group_config(
                overlay_layers=layers,
                has_tracks=bool(tracks),
                metric_layer_names=METRIC_LAYER_NAMES,
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
