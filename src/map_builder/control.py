"""
Layer control and exclusive layer handling for the heatmap.

This module provides the ``ExclusiveLayerControl`` class which injects
JavaScript to make overlay layers mutually exclusive and switch legends
based on the active layer.
"""

from folium import MacroElement
from jinja2 import Template

from src.map_builder.constants import EXCLUSIVE_LAYER_NAMES, LEGEND_IDS


class ExclusiveLayerControl(MacroElement):
    """Injects JavaScript to make overlay layers mutually exclusive and switch legends.

    This uses Folium's generated global ``layer_control_<id>_layers.overlays`` map
    (which Folium always exposes) to look up overlays by name, so it does not
    depend on any internal/non-existent Leaflet Map property such as
    ``map._controlsById``.

    ``_template`` must be a **class-level** ``Template`` attribute so that
    Folium's ``MacroElement`` rendering pipeline can invoke its ``script``
    macro at render time.  Instance attributes (``exclusive_names``,
    ``legend_ids``) are referenced inside the template via ``this.<attr>``,
    which Jinja2 resolves against the live instance at render time.
    """

    _template = Template(
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

    def __init__(self, exclusive_names: list[str] | None = None, legend_ids: dict[str, str] | None = None):
        """Initialize the ExclusiveLayerControl.

        Args:
            exclusive_names: List of layer names that should be mutually exclusive.
                Defaults to EXCLUSIVE_LAYER_NAMES.
            legend_ids: Mapping from layer name to legend DOM element ID.
                Defaults to LEGEND_IDS.
        """
        super().__init__()
        self._name = "ExclusiveLayerControl"
        self.exclusive_names = exclusive_names if exclusive_names is not None else EXCLUSIVE_LAYER_NAMES
        self.legend_ids = legend_ids if legend_ids is not None else LEGEND_IDS