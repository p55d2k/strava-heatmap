"""
Layer control, exclusive layer handling, and the unified in-HTML control panel.

This module provides:

* ``ExclusiveLayerControl`` — injects JavaScript to make overlay layers
  mutually exclusive and switches legends based on the active layer.
* ``ControlPanel`` — a single, self-contained control panel embedded in the
  generated HTML. It merges the stock Leaflet layer control and the basemap
  style switcher into one top-right panel: layer toggles with per-layer opacity
  sliders (collapsible to keep the panel compact), fit/reset, legend toggle and
  collapse/expand. The interactive behaviour
  lives in the companion ``assets/panel.js`` file which is inlined into the
  output so that everything works from a ``file://`` URL with no server.

All HTML/CSS/JS is kept in external ``assets/`` files so the code stays
readable and the styling stays consistent with the legend.
"""

import json
from pathlib import Path

from folium import MacroElement
from jinja2 import Template as JinjaTemplate

from src.map_builder.constants import (
    CARTO_STYLE_LABELS,
    CARTO_STYLES,
    COVERAGE_LAYER,
    DEFAULT_CARTO_STYLE,
    DEFAULT_RASTER_MODE,
    DENSITY_LAYER_NAMES,
    DENSITY_MODE_LAYERS,
    DENSITY_VIRTUAL_LAYER,
    INDEPENDENT_LAYER_NAMES,
    LEGEND_IDS,
    METRIC_LAYER_NAMES,
    RASTER_MODE_LABELS,
    RASTER_MODES,
    TRACK_OPACITY,
)

# Filename the panel's "Export GPX" button offers when the build does not name
# one; main passes the configured OUTPUT_GPX name, so this is the fallback.
DEFAULT_GPX_FILENAME = "tracks.gpx"

# Directory holding the external CSS / HTML / JS assets.
_ASSETS_DIR = Path(__file__).parent / "assets"


def _read(name: str) -> str:
    """Return the raw contents of an asset file inside ``assets/``."""
    return (_ASSETS_DIR / name).read_text(encoding="utf-8")


def legend_css() -> str:
    """Return the ``<style>`` block for just the legend card.

    The embeddable widget carries no control panel, so it takes this rather
    than :func:`controls_css`: the panel stylesheet docks a 300px sidebar and
    offsets the map by its width, which would leave a blank strip beside a
    widget that has no sidebar.
    """
    return f"<style>\n{_read('legend.css')}\n</style>"


def controls_css() -> str:
    """Return the unified ``<style>`` block for the panel, legend, and the hidden Leaflet layer control.

    ``legend.css`` supplies the shared custom properties and the legend card;
    ``panel.css`` builds on them, so it is concatenated after it.
    """
    return f"<style>\n{_read('legend.css')}\n{_read('panel.css')}\n</style>"


def carto_basemap_choices(styles: list[str] | None = None) -> list[dict[str, str]]:
    """Return the basemap style ``{key, label}`` choices for the control panel.

    Args:
        styles: CARTO style keys to expose. Defaults to ``CARTO_STYLES``.

    Returns:
        A list of ``{"key": ..., "label": ...}`` dicts, in the given order.
    """
    chosen = styles if styles is not None else list(CARTO_STYLES)
    return [{"key": style, "label": CARTO_STYLE_LABELS.get(style, style)} for style in chosen]


def control_panel_script() -> str:
    """Return the contents of the companion ``assets/panel.js`` browser script."""
    return _read("panel.js")


def build_control_panel_html() -> str:
    """Generate the control panel markup as an HTML string.

    There is no standalone global opacity slider in the markup: per-layer
    opacity sliders (one per overlay layer) are rendered client-side by
    ``assets/panel.js`` and default to the runtime ``opacity`` value in the
    panel config. Styling is applied separately via :func:`controls_css`, so it
    stays consistent with the legend.

    Returns:
        The ``<div>`` snippet for the panel.
    """
    return _read("control_panel.html")


def compute_layer_counts(tracks: list[tuple[str, list]]) -> dict[str, int]:
    """Count the activities behind each panel layer, for the toggle badges.

    Every heatmap layer is rasterized from the same activity set, so the density
    and coverage layers carry the full activity count. The metric layers only
    carry the activities whose devices actually recorded that metric, so their
    counts can be lower: a phone without a chest strap records no heart rate,
    and a device without a barometer records no elevation. The panel shows these
    counts on the layer toggles so each layer's data volume is visible before it
    is switched on.

    Args:
        tracks: ``(label, points)`` pairs from ``data_loader.load_tracks``.
            Points are ``[lat, lon, speed, hr, alt]``; any optional field may be
            ``None`` (or missing entirely, in a short legacy point).

    Returns:
        Mapping from layer name to the number of activities it is built from,
        covering every layer the panel can show a count on. Layer names absent
        from the mapping (bespoke overlays) simply get no badge.
    """
    n_activities = len(tracks)
    has_speed = has_hr = has_elevation = 0
    for _, points in tracks:
        if any(len(p) > 2 and p[2] is not None for p in points):
            has_speed += 1
        if any(len(p) > 3 and p[3] is not None for p in points):
            has_hr += 1
        if any(len(p) > 4 and p[4] is not None for p in points):
            has_elevation += 1

    return {
        "Raw GPS tracks": n_activities,
        DENSITY_VIRTUAL_LAYER: n_activities,
        COVERAGE_LAYER: n_activities,
        "Pace (average)": has_speed,
        "Heart rate (average)": has_hr,
        "Gradient (absolute)": has_elevation,
        "Gradient (change)": has_elevation,
    }


def build_layer_group_config(
    overlay_layers: list[tuple[str, str, bool]],
    has_tracks: bool = True,
    metric_layer_names: list[str] | None = None,
    map_opacity: float = 0.85,
    layer_counts: dict[str, int] | None = None,
) -> list[dict]:
    """Build the ``layerGroups`` config consumed by ``assets/panel.js``.

    The layer ``mode`` controls how the panel presents toggles for each group:
    * ``Heatmap`` (radio) — the two density *concepts* — "GPS Density" and
      "Coverage (Places Visited)" — are mutually exclusive (only one can be
      visible at a time) because stacking them produces no meaningful result.
      "GPS Density" is a virtual row: it binds to whichever raster-mode layer
      (Time Spent / Raw Passes / Unique Visits) is selected in the Advanced
      section's dropdown (see :func:`build_advanced_config`).
    * ``Metrics`` (check) — the distinct analysis metrics (pace, HR, gradients)
      that may each be toggled independently.
    * ``Raw GPS tracks`` (check) — independent checkbox overlay.

    Every returned layer entry carries its own ``opacity`` (0.0-1.0), seeded
    from ``map_opacity``, so the panel can render a per-layer opacity slider for
    each layer independently. When ``layer_counts`` supplies a figure for a
    layer, the entry also carries ``count`` (an integer of activities) and
    ``unit`` (``"track"`` or ``"activity"``) so the panel can show the layer's
    data volume on its toggle.

    Args:
        overlay_layers: The ``(name, image_uri, visible)`` tuples handed to
            ``build_map`` for each heatmap overlay layer.
        has_tracks: Whether raw GPS tracks are present (adds a checkbox group).
        metric_layer_names: Distinct metric layer names shown as independent
            checkboxes. Defaults to ``METRIC_LAYER_NAMES``.
        map_opacity: Default per-layer opacity (0.0-1.0) applied to every layer.
        layer_counts: Optional mapping from layer name to the number of
            activities it is built from, e.g. from
            :func:`compute_layer_counts`. Layers without an entry get no count
            badge.

    Returns:
        A list of ``{label, mode, layers}`` groups for the panel's layer list.
    """
    density = set(DENSITY_LAYER_NAMES)
    metrics = set(metric_layer_names or METRIC_LAYER_NAMES)
    # The density concept layers (one GPS Density layer per raster mode plus
    # Coverage) belong in the "Heatmap" group only, never in "Metrics". A caller
    # may pass an all-inclusive list (e.g. INDEPENDENT_LAYER_NAMES) as
    # ``metric_layer_names`` for another purpose; without this guard those layers
    # would be bucketed into BOTH groups and the panel would render duplicate
    # toggles and duplicate opacity sliders.
    metrics -= density
    groups: list[dict] = []
    counts = layer_counts or {}

    def _count_fields(name: str) -> dict:
        """Per-layer data-volume fields for the toggle badge, when known."""
        if name not in counts:
            return {}
        return {
            "count": counts[name],
            # Raw tracks count polylines; every other layer counts activities.
            "unit": "track" if name == "Raw GPS tracks" else "activity",
        }

    if has_tracks:
        groups.append(
            {
                "label": "Raw GPS tracks",
                "mode": "check",
                "layers": [
                    {
                        "name": "Raw GPS tracks",
                        "visible": False,
                        "opacity": TRACK_OPACITY,  # mirrors the PolyLine stroke opacity
                        **_count_fields("Raw GPS tracks"),
                    }
                ],
            }
        )

    def _item(name: str, visible: bool) -> dict:
        return {
            "name": name,
            "visible": visible,
            "opacity": map_opacity,
            "label": name,
            **_count_fields(name),
        }

    # The Heatmap group presents the two density CONCEPTS, not the per-mode
    # layers: one virtual "GPS Density" row (panel.js binds it to whichever
    # raster-mode layer the Advanced dropdown selects) plus "Coverage". The
    # per-mode overlays never appear as their own toggles. The row's visibility
    # is inherited from whichever mode layer is currently visible, so first
    # paint matches the configured raster mode.
    mode_visibility = {name: visible for name, _, visible in overlay_layers if name in density}
    concept_layers = [
        {
            "name": DENSITY_VIRTUAL_LAYER,
            "visible": any(mode_visibility.values()),
            "opacity": map_opacity,
            **_count_fields(DENSITY_VIRTUAL_LAYER),
        },
        _item(COVERAGE_LAYER, bool(mode_visibility.get(COVERAGE_LAYER, False))),
    ]
    metric_layers = [_item(name, visible) for name, _, visible in overlay_layers if name in metrics]
    known = density | metrics
    other_layers = [
        _item(name, visible) for name, _, visible in overlay_layers if name not in known
    ]

    if mode_visibility:
        groups.append({"label": "Heatmap", "mode": "radio", "layers": concept_layers})
    if metric_layers:
        groups.append({"label": "Metrics", "mode": "check", "layers": metric_layers})
    if other_layers:
        groups.append({"label": "Overlays", "mode": "check", "layers": other_layers})

    return groups


def build_advanced_config(
    raster_mode: str = DEFAULT_RASTER_MODE,
    *,
    modes: list[str] | None = None,
    density_layers: dict[str, str] | None = None,
    density_layer_names: list[str] | None = None,
    default_opacity: float = 0.85,
    overlay_layers: list[tuple[str, str, bool]] | None = None,
) -> dict:
    """Build the ``advanced`` config consumed by ``assets/panel.js``.

    Drives the collapsible "Advanced" section of the control panel, which
    exposes a dropdown for switching the rasterization mode of the GPS Density
    heatmap. The modes all map to overlay layers that are pre-baked at build
    time (see ``generate_layer_uris``), so switching is instant — panel.js just
    swaps which FeatureGroup is on the map.

    Args:
        raster_mode: Rasterization mode selected at first paint.
        modes: Mode keys offered in the dropdown. Defaults to ``RASTER_MODES``.
        density_layers: Mapping from mode key to the overlay layer name it
            displays. Defaults to ``DENSITY_MODE_LAYERS``.
        density_layer_names: The per-mode layer names (exposed to the panel so
            the virtual "GPS Density" row and its shared slider can drive all
            of them). Defaults to the values of ``density_layers``.
        default_opacity: Fallback opacity (0.0-1.0) for layers absent from
            ``overlay_layers``.
        overlay_layers: The ``(name, image_uri, visible)`` tuples handed to
            ``build_map``; used to sync each mode layer's initial visibility.

    Returns:
        ``{"modes", "densityLayerNames", "active"}`` for the panel config.
    """
    layer_map = dict(density_layers if density_layers is not None else DENSITY_MODE_LAYERS)
    mode_keys = list(modes if modes is not None else RASTER_MODES)
    layer_names = list(
        density_layer_names
        if density_layer_names is not None
        else [layer_map[mode] for mode in mode_keys]
    )
    visibility = {name: visible for name, _, visible in (overlay_layers or [])}
    _validate_raster_mode_choice(raster_mode, mode_keys)

    return {
        "modes": [
            {
                "key": mode,
                "label": RASTER_MODE_LABELS.get(mode, mode),
                "layer": layer_map[mode],
                "visible": bool(visibility.get(layer_map[mode], False)),
                "opacity": default_opacity,
            }
            for mode in mode_keys
            if mode in layer_map
        ],
        "densityLayerNames": layer_names,
        "active": raster_mode,
    }


def _validate_raster_mode_choice(raster_mode: str, mode_keys: list[str]) -> None:
    """Raise ``ValueError`` when ``raster_mode`` is not one of ``mode_keys``."""
    if raster_mode not in mode_keys:
        raise ValueError(
            f"Unknown raster_mode: {raster_mode!r}. Expected one of: {', '.join(mode_keys)}"
        )


class ControlPanel(MacroElement):
    """Inlines a unified control panel into the generated heatmap HTML.

    The element renders an ``html`` macro (the panel markup plus the embedded
    GeoJSON grid export and GPX track export) and a ``script`` macro (the
    inlined ``assets/panel.js`` logic plus the runtime config), which Folium
    emits into the map's body and script fragments respectively. The styling
    comes from the separate :func:`controls_css` stylesheet.

    Both exports are embedded as inert ``<script>`` blocks — the GeoJSON grid
    export in ``<script type="application/geo+json">`` and the GPX track export
    in ``<script type="application/gpx+xml">`` — and both are *compressed* (see
    :mod:`src.map_builder.embed`) because the documents are repetitive plain
    text that shrinks roughly tenfold; a dense grid would otherwise add tens of
    MB to the page. The browser never parses or executes either payload at load,
    so the map still loads quickly, and the panel's "Export GeoJSON" / "Export
    GPX" buttons inflate the payload in the browser before handing it over, so
    what the user gets is the document the build produced, byte for byte.

    The click-tooltip index (``tooltips``) rides along the same way, as an inert
    ``<script type="application/json">`` block. It is inflated on the first map
    click rather than at load, so the extra payload costs nothing until a
    visitor actually asks which activities passed through a pixel.

    ``_template`` must be a **class-level** ``Template`` so that Folium's
    ``MacroElement`` rendering pipeline can invoke its ``html``/``script``
    macros at render time. Instance attributes are referenced inside the
    template via ``this.<attr>``, which Jinja2 resolves against the live
    instance.
    """

    _template = JinjaTemplate(
        """
    {% macro html(this, kwargs) %}
    {{ this.html }}
    {% if this.geojson %}
    <script type="application/geo+json" id="hcp-geojson-data">{{ this.geojson }}</script>
    {% endif %}
    {% if this.gpx %}
    <script type="application/gpx+xml" id="hcp-gpx-data">{{ this.gpx }}</script>
    {% endif %}
    {% if this.tooltips %}
    <script type="application/json" id="hcp-activity-data">{{ this.tooltips }}</script>
    {% endif %}
    {% endmacro %}
    {% macro script(this, kwargs) %}
    (function() {
        var config = {{ this.config_json }};
        config.map = {{ this._parent.get_name() }};
        {{ this.script_code }}
        initHeatmapControlPanel(config);
    })();
    {% endmacro %}
    """
    )

    def __init__(
        self,
        *,
        map_opacity: float = 0.85,
        carto_style: str = DEFAULT_CARTO_STYLE,
        api_key: str = "",
        styles: list[str] | None = None,
        bounds: list[list[float]] | None = None,
        centre: list[float] | None = None,
        home: list[float] | None = None,
        zoom_start: int = 14,
        panel_id: str = "heatmap-control-panel",
        legend_id: str = "heatmap-legend",
        layer_groups: list[dict] | None = None,
        advanced: dict | None = None,
        geojson: str | None = None,
        gpx: str | None = None,
        gpx_filename: str | None = None,
        tooltips: str | None = None,
    ):
        """Initialize the ControlPanel.

        Args:
            map_opacity: Initial heatmap overlay opacity (0.0-1.0).
            carto_style: Active CARTO basemap style key.
            api_key: CARTO API key used by the basemap style switcher.
            styles: Available basemap style keys. Defaults to ``CARTO_STYLES``.
            bounds: Heatmap bounds ``[[lat, lon], [lat, lon]]`` for "Fit map".
            centre: ``[lat, lon]`` center point of the data bounding box.
            home: ``[lat, lon]`` home location used by "Reset"; falls back to
                ``centre`` when ``None``.
            zoom_start: Zoom level used by "Reset".
            panel_id: DOM id of the control panel container.
            legend_id: DOM id of the legend container toggled by the panel.
            layer_groups: ``layerGroups`` config for the panel's layer toggles;
                see :func:`build_layer_group_config`.
            advanced: ``advanced`` config for the collapsible Advanced section
                (rasterization-mode dropdown); see :func:`build_advanced_config`.
            geojson: The GeoJSON grid export, already run through
                :func:`src.map_builder.embed.encode_for_embedding`, embedded in
                the page for the "Export GeoJSON" button to inflate and
                download. Omit (or pass an empty string) to leave the block out.
            gpx: The GPX track export, already run through
                :func:`src.map_builder.embed.encode_for_embedding`, embedded in
                the page for the "Export GPX" button to inflate and download.
                Omit (or pass an empty string) to leave the block out.
            gpx_filename: Filename offered for the GPX download. Defaults to
                :data:`DEFAULT_GPX_FILENAME`; ``main`` passes the configured
                ``OUTPUT_GPX`` name so the download matches the file on disk.
            tooltips: The per-cell activity index, already run through
                :func:`src.map_builder.embed.encode_for_embedding`, embedded in
                the page for the map's click tooltips to inflate on demand.
                Omit (or pass an empty string) to leave the block out, which
                switches the click behaviour off.
        """
        super().__init__()
        self._name = "ControlPanel"
        self.html = build_control_panel_html()
        self.script_code = control_panel_script()
        self.geojson = geojson or ""
        self.gpx = gpx or ""
        self.tooltips = tooltips or ""
        config = {
            "panelId": panel_id,
            "basemapStyles": carto_basemap_choices(styles),
            "activeBasemap": carto_style,
            "apiKey": api_key,
            "opacity": map_opacity,
            "bounds": bounds,
            "centre": centre,
            "home": home if home is not None else centre,
            "hasHomeMarker": home is not None,
            "zoomStart": zoom_start,
            "legendId": legend_id,
            "layerGroups": layer_groups or [],
            "advanced": advanced or {},
            "gpxFilename": gpx_filename or DEFAULT_GPX_FILENAME,
        }
        self.config_json = json.dumps(config)


class ExclusiveLayerControl(MacroElement):
    """Injects JavaScript to show only the legend rows for the layers currently
    visible on the map.

    The density concept layers (Heatmap group) are mutually exclusive radio
    layers; ``exclusive_names`` drives that density legend row behaviour — one
    legend row per raster-mode layer, each showing/hiding with its own layer.
    The remaining concept/metric layers (``metric_names``) are independent
    checkboxes — adding/removing one shows/hides its own legend row without
    affecting any other row. Defaults for both arguments are the empty list and
    ``INDEPENDENT_LAYER_NAMES`` respectively.
    """

    _template = JinjaTemplate(
        """
    {% macro script(this, kwargs) %}
    (function() {
        var exclusiveNames = [
            {% for name in this.exclusive_names %}
            "{{ name }}"{% if not loop.last %},{% endif %}
            {% endfor %}
        ];
        var metricNames = [
            {% for name in this.metric_names %}
            "{{ name }}"{% if not loop.last %},{% endif %}
            {% endfor %}
        ];
        var legendIds = {
            {% for key, val in this.legend_ids.items() %}
            "{{ key }}": "{{ val }}"{% if not loop.last %},{% endif %}
            {% endfor %}
        };
        function setLegend(name, visible) {
            var el = document.getElementById(legendIds[name]);
            if (el) el.style.display = visible ? "block" : "none";
        }
        // Density variants are mutually exclusive: show only the active row.
        function showDensityLegend(activeName) {
            exclusiveNames.forEach(function(name) {
                setLegend(name, name === activeName);
            });
        }
        var map = {{this._parent.get_name()}};
        // Folium exposes the overlay layers it passed to L.control.layers under a
        // global named `<layer_control_var>_layers`. Walk the global scope to find it.
        function findOverlays() {
            var overlays = null;
            for (var k in window) {
                try {
                    var v = window[k];
                    if (v && v.overlays && v.base_layers && !overlays) overlays = v.overlays;
                } catch (e) {}
            }
            return overlays;
        }
        function setup() {
            var overlays = findOverlays();
            if (!map || !overlays) { setTimeout(setup, 100); return; }
            // Initial sync: reconcile legend rows with the layers already on the
            // map at load. Without this the static legend would show every
            // density row until the first overlay event fires.
            var activeDensity = null;
            exclusiveNames.forEach(function(name) {
                var layer = overlays[name];
                if (layer && map.hasLayer(layer)) activeDensity = name;
            });
            if (activeDensity) {
                showDensityLegend(activeDensity);
            } else {
                exclusiveNames.forEach(function(name) { setLegend(name, false); });
            }
            metricNames.forEach(function(name) {
                var layer = overlays[name];
                if (layer) setLegend(name, map.hasLayer(layer));
            });
            map.on('overlayadd', function(e) {
                // For overlay layers the event carries the layer name in
                // e.name. Fall back to e.layer.options.name if needed.
                var layerName = e.name || (e.layer && e.layer.options && e.layer.options.name);
                if (!layerName) return;
                if (exclusiveNames.indexOf(layerName) !== -1) {
                    // Keep density variants mutually exclusive on the map.
                    exclusiveNames.forEach(function(name) {
                        if (name !== layerName && overlays[name] && map.hasLayer(overlays[name])) {
                            map.removeLayer(overlays[name]);
                        }
                    });
                    showDensityLegend(layerName);
                } else if (metricNames.indexOf(layerName) !== -1) {
                    setLegend(layerName, true);
                }
            });
            map.on('overlayremove', function(e) {
                // Hiding a metric checkbox removes its legend row again.
                var layerName = e.name || (e.layer && e.layer.options && e.layer.options.name);
                if (layerName && metricNames.indexOf(layerName) !== -1) {
                    setLegend(layerName, false);
                }
            });
        }
        // Run setup after the DOM is ready and Folium has declared its layer globals.
        if (document.readyState === "loading") {
            document.addEventListener('DOMContentLoaded', setup);
        } else {
            setTimeout(setup, 0);
        }
    })();
    {% endmacro %}
    """
    )

    def __init__(
        self,
        exclusive_names: list[str] | None = None,
        legend_ids: dict[str, str] | None = None,
        metric_names: list[str] | None = None,
    ):
        """Initialize the ExclusiveLayerControl.

        Args:
            exclusive_names: Layer names that are mutually exclusive (radio).
                Retained for backward compatibility; defaults to empty (all
                layers are independent checkboxes).
            legend_ids: Mapping from layer name to legend DOM element ID.
                Defaults to LEGEND_IDS.
            metric_names: Layer names whose legend rows follow their on/off
                state. Defaults to INDEPENDENT_LAYER_NAMES (the density concept
                layers plus the four metrics).
        """
        super().__init__()
        self._name = "ExclusiveLayerControl"
        self.exclusive_names = exclusive_names if exclusive_names is not None else []
        self.metric_names = metric_names if metric_names is not None else INDEPENDENT_LAYER_NAMES
        self.legend_ids = legend_ids if legend_ids is not None else LEGEND_IDS
