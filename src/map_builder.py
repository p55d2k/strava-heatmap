"""
Pipeline Stage 4: Map Building & Output
Handles legend creation, map building, and HTML output.
"""

import os
from pathlib import Path

import folium


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

EXCLUSIVE_JS = """
<script>
(function() {
    var exclusiveNames = [
        "Frequency (linear)", "Frequency (log)",
        "Pace (average)", "Heart rate (average)",
        "Gradient (absolute)", "Gradient (change)"
    ];
    var legendIds = {
        "Frequency (linear)":   "legend-frequency",
        "Frequency (log)":      "legend-frequency-log",
        "Pace (average)":       "legend-pace-avg",
        "Heart rate (average)": "legend-heart-rate-avg",
        "Gradient (absolute)":  "legend-gradient",
        "Gradient (change)":    "legend-elev-change"
    };
    function showLegend(activeName) {
        Object.keys(legendIds).forEach(function(name) {
            var el = document.getElementById(legendIds[name]);
            if (el) el.style.display = (name === activeName) ? "block" : "none";
        });
    }
    function setup() {
        var mapObj = null, overlays = null;
        for (var k in window) {
            try {
                if (!mapObj   && window[k] instanceof L.Map) mapObj = window[k];
                if (!overlays && window[k] && window[k].overlays && window[k].base_layers)
                    overlays = window[k].overlays;
            } catch(e) {}
        }
        if (!mapObj || !overlays) { setTimeout(setup, 100); return; }
        mapObj.on('overlayadd', function(e) {
            if (!exclusiveNames.includes(e.name)) return;
            exclusiveNames.forEach(function(name) {
                if (name !== e.name && overlays[name] && mapObj.hasLayer(overlays[name]))
                    mapObj.removeLayer(overlays[name]);
            });
            showLegend(e.name);
        });
    }
    document.addEventListener('DOMContentLoaded', setup);
})();
</script>
"""


def cmap_to_css(cmap, n=14) -> str:
    """Convert colormap to CSS linear-gradient string."""
    stops = []
    for i in range(n):
        t = i / (n - 1)
        r, g, b, a = cmap(t)
        stops.append(f"rgba({int(r*255)},{int(g*255)},{int(b*255)},{a:.2f})")
    return f"linear-gradient(to right, {', '.join(stops)})"


def pace_str(ms: float) -> str:
    """Convert m/s to pace string (min:sec/km)."""
    secs = 1000 / ms
    return f"{int(secs // 60)}:{int(secs % 60):02d}/km"


def legend_row(row_id: str, title: str, grad_css: str, label_lo: str, label_hi: str, visible: bool = False) -> str:
    """Generate HTML for a legend row."""
    display = "block" if visible else "none"
    return f"""
    <div id="{row_id}" style="display:{display}">
      <div style="font-weight:600;margin-bottom:3px;color:#eee">{title}</div>
      <div style="height:10px;border-radius:3px;background:{grad_css};
                  border:1px solid rgba(255,255,255,0.08)"></div>
      <div style="display:flex;justify-content:space-between;
                  margin-top:3px;color:#aaa;font-size:11px">
        <span>{label_lo}</span><span>{label_hi}</span>
      </div>
    </div>"""


def build_legend_html(normalized: dict, colormaps: dict, max_passes: int) -> str:
    """Build the complete legend HTML."""
    freq_css = cmap_to_css(colormaps["cmap_count"])
    pace_css = cmap_to_css(colormaps["cmap_speed_rgb"])
    hr_css = cmap_to_css(colormaps["cmap_hr_rgb"])

    legend_html = f"""
    <div id="heatmap-legend" style="
        position:fixed; bottom:28px; right:10px; z-index:9999;
        background:rgba(15,15,15,0.88);
        padding:13px 16px 14px; border-radius:9px;
        color:#ddd; font-family:sans-serif; font-size:12px;
        min-width:210px; line-height:1.4;
        border:1px solid rgba(255,255,255,0.10);
        box-shadow:0 2px 8px rgba(0,0,0,0.6);
    ">
      {legend_row("legend-frequency",      "Frequency (linear)",   freq_css, "1 pass", f"{max_passes} passes", visible=True)}
      {legend_row("legend-frequency-log",  "Frequency (log)",      freq_css, "1 pass", f"{max_passes} passes (log scale)")}
      {legend_row("legend-pace-avg",       "Pace (average)",       pace_css, pace_str(normalized["s_lo"]), pace_str(normalized["s_hi"]))}
      {legend_row("legend-heart-rate-avg", "Heart rate (average)", hr_css,   f"{normalized['hr_lo']:.0f} bpm", f"{normalized['hr_hi']:.0f} bpm")}
      {legend_row("legend-gradient",       "Gradient (absolute)",
          "linear-gradient(to right, rgba(0,0,0,0), rgba(255,255,255,1))",
          f"{normalized['g_lo']*100:.1f}%", f"{normalized['g_hi']*100:.1f}% grade")}
      {legend_row("legend-elev-change",    "Gradient (change)",
          cmap_to_css(colormaps["cmap_elev_rgb"]), "descending", "ascending")}
    </div>
    """
    return legend_html


def build_map(
    tracks: list[tuple[str, list]],
    layers: list[tuple[str, str, bool]],
    bounds: list[list[float]],
    centre: list[float],
    legend_html: str,
    output_path: Path,
    map_opacity: float,
) -> None:
    """Build and save the Folium map."""
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
    m.get_root().html.add_child(folium.Element(EXCLUSIVE_JS))

    m.save(output_path)
    import logging
    log = logging.getLogger(__name__)
    log.info(f"Saved: {output_path}")
    log.info(f"Open:  file://{os.path.abspath(output_path)}")