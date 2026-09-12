"""
Layer control, exclusive layer handling, and the unified in-HTML control panel.

This module provides:

* ``ExclusiveLayerControl`` — injects JavaScript to make overlay layers
  mutually exclusive and switches legends based on the active layer.
* ``ControlPanel`` — a single, self-contained control panel embedded in the
  generated HTML. It merges the stock Leaflet layer control and the basemap
  style switcher into one top-right panel: layer toggles, opacity slider,
  fit/reset, legend toggle and collapse/expand. The interactive behaviour
  lives in the companion ``assets/panel.js`` file which is inlined into the
  output so that everything works from a ``file://`` URL with no server.

All HTML/CSS/JS is kept in external ``assets/`` files so the code stays
readable and the styling stays consistent with the legend.
"""

import json
from pathlib import Path
from string import Template

from folium import MacroElement
from jinja2 import Template as JinjaTemplate

from src.map_builder.constants import (
    CARTO_STYLE_LABELS,
    CARTO_STYLES,
    DEFAULT_CARTO_STYLE,
    EXCLUSIVE_LAYER_NAMES,
    LEGEND_IDS,
)

# Directory holding the external CSS / HTML / JS assets.
_ASSETS_DIR = Path(__file__).parent / "assets"


def _read(name: str) -> str:
    """Return the raw contents of an asset file inside ``assets/``."""
    return (_ASSETS_DIR / name).read_text(encoding="utf-8")


def controls_css() -> str:
    """Return the unified ``<style>`` block for the panel, legend, and the hidden Leaflet layer control."""
    return f"<style>\n{_read('panel.css')}\n</style>"


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


def build_control_panel_html(opacity: float = 0.85) -> str:
    """Generate the control panel markup as an HTML string.

    Args:
        opacity: Initial heatmap overlay opacity (0.0-1.0), used to set the
            slider's starting value and displayed percentage.

    Returns:
        The ``<div>`` snippet for the panel. Styling is applied separately via
        :func:`controls_css`, so it stays consistent with the legend.
    """
    pct = int(round(float(opacity) * 100))
    return Template(_read("control_panel.html")).substitute(opacity_pct=pct)


def build_layer_group_config(
    overlay_layers: list[tuple[str, str, bool]],
    has_tracks: bool = True,
    exclusive_layer_names: list[str] | None = None,
) -> list[dict]:
    """Build the ``layerGroups`` config consumed by ``assets/panel.js``.

    Args:
        overlay_layers: The ``(name, image_uri, visible)`` tuples handed to
            ``build_map`` for each heatmap overlay layer.
        has_tracks: Whether raw GPS tracks are present (adds a checkbox group).
        exclusive_layer_names: Layer names that should be mutually exclusive
            (radio group). Defaults to ``EXCLUSIVE_LAYER_NAMES``.

    Returns:
        A list of ``{label, mode, layers}`` groups for the panel's layer list.
    """
    exclusive = set(exclusive_layer_names or EXCLUSIVE_LAYER_NAMES)
    groups: list[dict] = []

    if has_tracks:
        groups.append(
            {
                "label": "Raw GPS tracks",
                "mode": "check",
                "layers": [{"name": "Raw GPS tracks", "visible": False}],
            }
        )

    heatmap_layers = [
        {"name": name, "visible": visible}
        for name, _, visible in overlay_layers
        if name in exclusive
    ]
    other_layers = [
        {"name": name, "visible": visible}
        for name, _, visible in overlay_layers
        if name not in exclusive
    ]

    if heatmap_layers:
        groups.append({"label": "Heatmap", "mode": "radio", "layers": heatmap_layers})
    if other_layers:
        groups.append({"label": "Overlays", "mode": "check", "layers": other_layers})

    return groups


class ControlPanel(MacroElement):
    """Inlines a unified control panel into the generated heatmap HTML.

    The element renders an ``html`` macro (the panel markup) and a ``script``
    macro (the inlined ``assets/panel.js`` logic plus the runtime config),
    which Folium emits into the map's body and script fragments respectively.
    The styling comes from the separate :func:`controls_css` stylesheet.

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
        zoom_start: int = 14,
        panel_id: str = "heatmap-control-panel",
        legend_id: str = "heatmap-legend",
        layer_groups: list[dict] | None = None,
    ):
        """Initialize the ControlPanel.

        Args:
            map_opacity: Initial heatmap overlay opacity (0.0-1.0).
            carto_style: Active CARTO basemap style key.
            api_key: CARTO API key used by the basemap style switcher.
            styles: Available basemap style keys. Defaults to ``CARTO_STYLES``.
            bounds: Heatmap bounds ``[[lat, lon], [lat, lon]]`` for "Fit map".
            centre: ``[lat, lon]`` used by "Reset".
            zoom_start: Zoom level used by "Reset".
            panel_id: DOM id of the control panel container.
            legend_id: DOM id of the legend container toggled by the panel.
            layer_groups: ``layerGroups`` config for the panel's layer toggles;
                see :func:`build_layer_group_config`.
        """
        super().__init__()
        self._name = "ControlPanel"
        self.html = build_control_panel_html(opacity=map_opacity)
        self.script_code = control_panel_script()
        config = {
            "panelId": panel_id,
            "basemapStyles": carto_basemap_choices(styles),
            "activeBasemap": carto_style,
            "apiKey": api_key,
            "opacity": map_opacity,
            "bounds": bounds,
            "centre": centre,
            "zoomStart": zoom_start,
            "legendId": legend_id,
            "layerGroups": layer_groups or [],
        }
        self.config_json = json.dumps(config)


class ExclusiveLayerControl(MacroElement):
    """Injects JavaScript to make overlay layers mutually exclusive and switch legends."""

    _template = JinjaTemplate(
        """
    {% macro script(this, kwargs) %}
    (function() {
        var exclusiveNames = [
            {% for name in this.exclusive_names %}
            "{{ name }}"{% if not loop.last %},{% endif %}
            {% endfor %}
        ];
        var legendIds = {
            {% for key, val in this.legend_ids.items() %}
            "{{ key }}": "{{ val }}"{% if not loop.last %},{% endif %}
            {% endfor %}
        };
        function showLegend(activeName) {
            Object.keys(legendIds).forEach(function(name) {
                var el = document.getElementById(legendIds[name]);
                if (el) el.style.display = (name === activeName) ? "block" : "none";
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
            map.on('overlayadd', function(e) {
                // For overlay layers the event carries the layer name in
                // e.name. Fall back to e.layer.options.name if needed.
                var layerName = e.name || (e.layer && e.layer.options && e.layer.options.name);
                if (!layerName || !exclusiveNames.includes(layerName)) return;
                exclusiveNames.forEach(function(name) {
                    if (name !== layerName && overlays[name] && map.hasLayer(overlays[name])) {
                        map.removeLayer(overlays[name]);
                    }
                });
                showLegend(layerName);
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
        self, exclusive_names: list[str] | None = None, legend_ids: dict[str, str] | None = None
    ):
        """Initialize the ExclusiveLayerControl.

        Args:
            exclusive_names: List of layer names that should be mutually exclusive.
                Defaults to EXCLUSIVE_LAYER_NAMES.
            legend_ids: Mapping from layer name to legend DOM element ID.
                Defaults to LEGEND_IDS.
        """
        super().__init__()
        self._name = "ExclusiveLayerControl"
        self.exclusive_names = (
            exclusive_names if exclusive_names is not None else EXCLUSIVE_LAYER_NAMES
        )
        self.legend_ids = legend_ids if legend_ids is not None else LEGEND_IDS
