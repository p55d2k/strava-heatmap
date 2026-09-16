"""Integration tests proving the control panel toggles drive legend visibility.

The generated heatmap has two independently-authored pieces of client-side
JavaScript that are only loosely coupled: the control panel
(``assets/panel.js``) toggles overlay layers on/off by calling
``map.addLayer`` / ``map.removeLayer``, and ``ExclusiveLayerControl`` listens
to Leaflet's ``overlayadd`` / ``overlayremove`` events to show/hide the matching
legend rows (the two GPS density concepts are mutually-exclusive radio layers;
the remaining metric layers are independent checkboxes whose legend rows
follow their on/off state).

This module runs the *real* production scripts (rendered exactly as they are
embedded into the HTML) through Node with a lightweight fake DOM / Leaflet map, so
that a regression in either half is caught. The fake map faithfully emulates the
one piece of the real pipeline that cannot run outside a browser: Leaflet's
``Control.Layers`` re-firing a programmatic layer add/remove as an
``overlayadd``/``overlayremove`` event with the layer's ``options.name``.

The test is skipped when Node is not available, and is otherwise hermetic
(no browser, no npm install).
"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import folium
import pytest

from src.map_builder.constants import (
    DENSITY_LAYER_NAMES,
    LEGEND_IDS,
    METRIC_LAYER_NAMES,
)
from src.map_builder.control import (
    ControlPanel,
    ExclusiveLayerControl,
    build_control_panel_html,
    build_layer_group_config,
    control_panel_script,
)

# Not bound to a legend row (raw GPS tracks); used as a negative case.
_RAW_TRACKS = "Raw GPS tracks"

# ---------------------------------------------------------------------------
# Node harness (see the module docstring). Kept as a plain string so nothing is
# interpolated by Python; all runtime data flows in via config.json.
# ---------------------------------------------------------------------------
_HARNESS = r"""
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const DIR = __dirname;
const config = JSON.parse(fs.readFileSync(path.join(DIR, "config.json"), "utf8"));

const legendIdByLayer = config.__legendIdByLayer; // layer name -> legend row id
const layerNames = config.__layerNames;           // overlay registry keys
const panelId = config.panelId;
const mapVar = config.__mapVar;                   // e.g. "map_<hex>" -> free global

// ---- Minimal fake DOM ----------------------------------------------------
function mkClassList() {
  const s = new Set();
  return {
    add: (c) => s.add(c),
    remove: (c) => s.delete(c),
    toggle(c) { const had = s.has(c); if (had) s.delete(c); else s.add(c); return !had; },
    contains: (c) => s.has(c),
  };
}
function matchSelector(el, sel) {
  const t = sel.trim();
  let m = /^([a-z0-9-]*)#([-_a-zA-Z0-9]+)$/i.exec(t);
  if (m) return (!m[1] || el.tagName === m[1].toUpperCase()) && el.id === m[2];
  m = /^([a-z0-9-]*)\.([-_a-zA-Z0-9]+)$/i.exec(t);
  if (m) {
    const tagOk = !m[1] || el.tagName === m[1].toUpperCase();
    const clsOk = typeof el.className === "string" && el.className.split(/\s+/).indexOf(m[2]) !== -1;
    return tagOk && clsOk;
  }
  m = /^([a-z0-9-]*)\[([a-zA-Z0-9-]+)="([^"]*)"\]$/i.exec(t);
  if (m) return (!m[1] || el.tagName === m[1].toUpperCase()) && el.getAttribute(m[2]) === m[3];
  return false;
}
function querySelectorIn(root, sel) {
  const stack = root.children.slice();
  while (stack.length) {
    const n = stack.pop();
    if (matchSelector(n, sel)) return n;
    for (const c of n.children) stack.push(c);
  }
  return null;
}
function makeEl(tag, id) {
  const el = {
    tagName: (tag || "div").toUpperCase(), id: id || "",
    type: "", name: "", value: "", textContent: "",
    className: "", checked: false, style: { display: "" }, hidden: false,
    children: [], attributes: {}, _listeners: {}, _html: "", classList: mkClassList(),
    setAttribute(k, v) { this.attributes[k] = String(v); },
    getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(evt, fn) { (this._listeners[evt] = this._listeners[evt] || []).push(fn); },
    dispatch(evt, detail) { (this._listeners[evt] || []).forEach((f) => f(detail || {})); },
    querySelector(sel) { return querySelectorIn(this, sel); },
  };
  // Faithfully mirror real DOM containers: innerHTML = "" empties the children.
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; },
    set(v) { el._html = String(v); if (String(v) === "") el.children.length = 0; },
  });
  return el;
}

const byId = new Map();
const documentObj = {
  readyState: "complete",
  getElementById: (id) => byId.get(id) || null,
  createElement: (tag) => makeEl(tag),
};

// Legend rows: one stub element per legend id the ExclusiveLayerControl knows.
for (const id of Object.values(legendIdByLayer)) byId.set(id, makeEl("div", id));

// Control panel: the panel container plus every id'd control from the template.
const panel = makeEl("div", panelId);
byId.set(panelId, panel);
for (const pid of config.__panelIds) {
  const el = makeEl(null, pid);
  panel.appendChild(el);
  byId.set(pid, el);
}
// ---- Minimal fake Leaflet map + overlay registry ------------------------
function makeOverlay(name) {
  // A FeatureGroup exposing a single ImageOverlay child, mirroring how Folium
  // nests heatmap overlays. setOpacity must be reached through eachLayer().
  const sub = { opts: [], setOpacity(o) { this.opts.push(o); }, redraw() {} };
  return {
    name,
    options: { name },
    sub,
    setOpacity(o) { sub.opts.push(o); },
    eachLayer(fn) { fn(sub); },
    redraw() {},
  };
}
function makeVectorOverlay(name) {
  // A FeatureGroup wrapping vector children (Leaflet PolyLines), mirroring the
  // Raw GPS tracks layer: like a real Path it exposes setStyle, not setOpacity.
  const sub = { styles: [], setStyle(o) { this.styles.push(o); }, redraw() {} };
  return {
    name,
    options: { name },
    sub,
    eachLayer(fn) { fn(sub); },
    redraw() {},
  };
}
function makeMap() {
  const onMap = new Set();
  const handlers = {};
  const map = {
    addLayer(layer) {
      if (onMap.has(layer)) return this;
      onMap.add(layer);
      const name = layer && layer.options && layer.options.name;
      if (name) map.fire("overlayadd", { name, layer });
      return this;
    },
    removeLayer(layer) {
      if (!onMap.has(layer)) return this;
      onMap.delete(layer);
      const n = layer && layer.options && layer.options.name;
      if (n) map.fire("overlayremove", { name: n, layer });
      return this;
    },
    hasLayer: (layer) => onMap.has(layer),
    eachLayer(fn) { onMap.forEach((l) => fn(l)); },
    on(evt, fn) { (handlers[evt] = handlers[evt] || []).push(fn); },
    fire(evt, data) { (handlers[evt] || []).forEach((f) => f(data || {})); },
    fitBounds() {}, setView() {},
  };
  return map;
}

const map = makeMap();
const overlays = {};
for (const nm of layerNames) {
  // The raw GPS tracks are vector polylines, so model them as a vector overlay.
  overlays[nm] = nm === "Raw GPS tracks" ? makeVectorOverlay(nm) : makeOverlay(nm);
}

// Global scope so the free `window` / `document` / `<mapVar>` lookups resolve.
const windowObj = {};
windowObj[config.__registryKey] = { base_layers: {}, overlays }; // findOverlays() scans this
global.window = windowObj;
global.document = documentObj;
global[mapVar] = map; // the exclusive script's `var map = <name>;`

// Mirror Folium's first paint: the default-on Time Spent layer is on the map.
map.addLayer(overlays["GPS Density (Time Spent)"]);

// The home marker is rendered server-side by ScalableHomeMarker and added
// directly to the map (not the overlay registry), tagged with options.homeMarker.
// It is only rendered when the build had a home location (hasHomeMarker).
let homeMarker = null;
if (config.hasHomeMarker) {
  homeMarker = {
    options: { homeMarker: true },
    setRadius() {},
    addTo(m) { m.addLayer(this); return this; },
  };
  map.addLayer(homeMarker);
}

// ---- Run the REAL production scripts ------------------------------------
eval(fs.readFileSync(path.join(DIR, "exclusive.js"), "utf8"));
eval(fs.readFileSync(path.join(DIR, "panel.js"), "utf8"));

const cfg = Object.assign({}, config);
delete cfg.__legendIdByLayer; delete cfg.__layerNames;
delete cfg.__panelIds; delete cfg.__mapVar; delete cfg.__registryKey;
cfg.map = map;
windowObj.initHeatmapControlPanel(cfg);

const delay = (ms) => new Promise((r) => setTimeout(r, ms));

function rowVisible(layerName) {
  const el = byId.get(legendIdByLayer[layerName]);
  return el ? el.style.display : "(no legend row)";
}
function toggle(layerName, checked) {
  const input = panel.querySelector('input[data-layer-name="' + layerName + '"]');
  assert.ok(input, "toggle input exists for " + layerName);
  input.checked = checked;
  input.dispatch("change");
}

(async () => {
  // Let ExclusiveLayerControl's initial sync run (scheduled via setTimeout(0)).
  await delay(20);

  const ok = (cond, msg) => { assert.ok(cond, msg); console.log("PASS: " + msg); };

  // Initial paint: the default-on Time Spent density row is visible, the
  // independent Coverage concept is hidden, and metrics start hidden.
  ok(rowVisible("GPS Density (Time Spent)") === "block",
     "initial: Time Spent density row visible");
  ok(rowVisible("Coverage (Places Visited)") === "none",
     "initial: Coverage density row hidden");
  ok(rowVisible("Pace (average)") === "none", "initial: pace metric row hidden");

  // Scenario A - the two GPS density concepts are mutually-exclusive radio
  // layers: toggling Coverage on removes Time Spent from the map and hides its
  // legend row (stacked heatmaps must never overlap).
  toggle("Coverage (Places Visited)", true);
  ok(rowVisible("Coverage (Places Visited)") === "block",
     "coverage row shown after radio on");
  ok(rowVisible("GPS Density (Time Spent)") === "none",
     "Time Spent hidden — density concepts are mutually exclusive");
  // Selecting Time Spent again restores it and hides Coverage.
  toggle("GPS Density (Time Spent)", true);
  ok(rowVisible("GPS Density (Time Spent)") === "block",
     "Time Spent shown again after radio re-selected");
  ok(rowVisible("Coverage (Places Visited)") === "none",
     "Coverage hidden when Time Spent is re-selected");

  // Scenario B - an independent metric checkbox shows/hides only its own row.
  toggle("Pace (average)", true);
  ok(rowVisible("Pace (average)") === "block", "pace row shown after toggle on");
  toggle("Pace (average)", false);
  ok(rowVisible("Pace (average)") === "none", "pace row hidden after toggle off");

  // Scenario C - a metric toggle must not disturb density / other metrics.
  toggle("Heart rate (average)", true);
  ok(rowVisible("Heart rate (average)") === "block", "HR row shown after toggle on");
  ok(rowVisible("GPS Density (Time Spent)") === "block",
     "density row unaffected by a metric toggle");

  // Scenario D - toggling an unbound layer (Raw GPS tracks) changes no legend row.
  const before = rowVisible("GPS Density (Time Spent)");
  toggle("Raw GPS tracks", true);
  ok(rowVisible("GPS Density (Time Spent)") === before,
     "density row unchanged when toggling an unbound layer");

  // Scenario E - the home marker is on by default and its checkbox hides /
  // re-shows it without touching overlay events or legend rows. Without a home
  // location the section stays hidden and toggling it is a no-op.
  const homeSection = byId.get("hcp-home-section");
  const homeCheckbox = byId.get("hcp-home-marker");
  const tsBeforeHomeToggle = rowVisible("GPS Density (Time Spent)");
  if (config.hasHomeMarker) {
    ok(homeSection && homeSection.hidden === false,
       "home marker section is revealed when a home marker exists");
    ok(homeCheckbox && homeCheckbox.checked === true,
       "home marker checkbox is checked by default");
    homeCheckbox.checked = false;
    homeCheckbox.dispatch("change");
    ok(map.hasLayer(homeMarker) === false, "unchecking removes the home marker");
    homeCheckbox.checked = true;
    homeCheckbox.dispatch("change");
    ok(map.hasLayer(homeMarker) === true, "re-checking re-adds the home marker");
  } else {
    ok(homeSection && homeSection.hidden === true,
       "home marker section stays hidden without a home location");
    homeCheckbox.checked = false;
    homeCheckbox.dispatch("change");
    ok(map.hasLayer(homeMarker) === false,
       "toggling is a no-op when no home marker was rendered");
  }
  ok(rowVisible("GPS Density (Time Spent)") === tsBeforeHomeToggle,
     "home marker toggle does not disturb legend rows");

// Scenario F - per-layer opacity sliders affect only their own layer, and the
  // "Opacity" toggle collapses every slider at once.
  const paceSlider = panel.querySelector('input[data-layer-opacity="Pace (average)"]');
  assert.ok(paceSlider, "per-layer opacity slider exists for Pace (average)");
  paceSlider.value = "30";
  paceSlider.dispatch("input");
  const paceLayer = overlays["Pace (average)"];
  ok(paceLayer.sub.opts[paceLayer.sub.opts.length - 1] === 0.3,
     "paced overlay takes the slider value 0.3");

  const hrLayer = overlays["Heart rate (average)"];
  ok(hrLayer.sub.opts[hrLayer.sub.opts.length - 1] === 0.85,
     "unrelated HR layer keeps its own default opacity 0.85");

  // Scenario G - the Raw GPS tracks layer is a set of vector polylines (Leaflet
  // Paths expose setStyle, not setOpacity), so its slider must drive the layer
  // via setStyle instead. Regression test for "changing tracks opacity did nothing".
  const trackLayer = overlays["Raw GPS tracks"];
  ok(trackLayer && typeof trackLayer.sub.setStyle === "function",
     "raw GPS tracks overlay is modelled as a vector layer");
  const trackSlider = panel.querySelector('input[data-layer-opacity="Raw GPS tracks"]');
  assert.ok(trackSlider, "tracks opacity slider exists");
  const initialTrack = trackLayer.sub.styles[trackLayer.sub.styles.length - 1];
  ok(initialTrack && initialTrack.opacity === 0.4,
     "tracks slider initialises to TRACK_OPACITY 0.4");
  trackSlider.value = "20";
  trackSlider.dispatch("input");
  const lastTrack = trackLayer.sub.styles[trackLayer.sub.styles.length - 1];
  ok(lastTrack && lastTrack.opacity === 0.2 && lastTrack.fillOpacity === 0.2,
     "tracks vector layer takes the slider value 0.2 via setStyle");
  ok(hrLayer.sub.opts[hrLayer.sub.opts.length - 1] === 0.85,
     "heatmap image-overlay opacity unaffected by the tracks slider");

  // Scenario F2 - the Heatmap density concepts are a mutually-exclusive radio
  // pair, so instead of two per-layer sliders they share a single combined
  // "Heatmap" slider that drives whichever variant is currently active. It
  // defaults to 100% and carries its value across radio switches.
  const heatmapSlider = panel.querySelector('input[data-layer-opacity="Heatmap"]');
  assert.ok(heatmapSlider, "a single combined Heatmap opacity slider exists");
  // The individual density variants must no longer have their own sliders.
  ok(!panel.querySelector('input[data-layer-opacity="GPS Density (Time Spent)"]') &&
     !panel.querySelector('input[data-layer-opacity="Coverage (Places Visited)"]'),
     "Time Spent / Coverage share one Heatmap slider (no per-variant sliders)");
  ok(heatmapSlider.value === "100", "Heatmap slider defaults to 100%");
  const tsLayer = overlays["GPS Density (Time Spent)"];
  ok(tsLayer.sub.opts[tsLayer.sub.opts.length - 1] === 1.0,
     "active Time Spent layer initialised to Heatmap 100% opacity");

  // Moving the shared slider drives the currently active heatmap layer only.
  heatmapSlider.value = "40";
  heatmapSlider.dispatch("input");
  ok(tsLayer.sub.opts[tsLayer.sub.opts.length - 1] === 0.4,
     "Heatmap slider drives the active Time Spent layer to 0.4");

  // Switching the radio to Coverage carries the shared 40% value over to it.
  toggle("Coverage (Places Visited)", true);
  const covLayer = overlays["Coverage (Places Visited)"];
  ok(covLayer.sub.opts[covLayer.sub.opts.length - 1] === 0.4,
     "Heatmap slider value carried over to Coverage when it becomes active");
  ok(heatmapSlider.value === "40", "Heatmap slider retains its 40% across radio switch");

  const opToggle = byId.get("hcp-opacity-toggle");
  opToggle.dispatch("click");
  ok(panel.classList.contains("hcp-opacity-collapsed"),
     "opacity toggle collapses the per-layer sliders");

  console.log("ALL_PASS");
  process.exit(0);
})().catch((err) => {
  console.error("FAIL: " + (err && err.message ? err.message : String(err)));
  process.exit(1);
});
"""


def _panel_ids() -> list[str]:
    """Return the element ids present in the real control-panel template."""
    html = build_control_panel_html()
    return re.findall(r'id="([^"]+)"', html)


def _overlay_layers():
    """Build a production-shaped overlay layer list for the panel config."""
    layers = [(n, "data:image/png;base64,x", False) for n in DENSITY_LAYER_NAMES]
    layers += [(n, "data:image/png;base64,x", False) for n in METRIC_LAYER_NAMES]
    return layers


def _write_harness(tmp: Path, panel_cfg: dict) -> None:
    """Write the node harness inputs derived from real production assets."""
    config = dict(panel_cfg)
    config["__legendIdByLayer"] = LEGEND_IDS
    config["__layerNames"] = list(LEGEND_IDS.keys()) + [_RAW_TRACKS]
    config["__panelIds"] = [pid for pid in _panel_ids() if pid != config["panelId"]]

    (tmp / "harness.js").write_text(_HARNESS, encoding="utf-8")
    (tmp / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (tmp / "panel.js").write_text(control_panel_script(), encoding="utf-8")


@pytest.fixture
def node_available():
    """Yield the node binary when available; otherwise skip the JS test."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available; skipping control-panel JS integration test")
    return node


@pytest.mark.parametrize("home", [[37.0, -122.0], None], ids=["with-home", "without-home"])
def test_control_panel_toggles_update_legend_via_overlay_events(node_available, home):
    """Toggling a control-panel layer must update legend rows via overlay events.

    Runs twice — with and without a home location — so both the home-marker
    toggle wiring and its no-marker fallback are exercised end to end.
    """
    panel = ControlPanel(
        centre=[37.0, -122.0],
        home=home,
        layer_groups=build_layer_group_config(_overlay_layers(), has_tracks=True),
    )
    panel_cfg = json.loads(panel.config_json)

    # Parent the ExclusiveLayerControl to a real folium map so its output uses
    # production values (map variable name, embedded legend ids), not stand-ins.
    m = folium.Map(location=[45.0, -122.0], zoom_start=14, tiles=None)
    excl = ExclusiveLayerControl()
    excl.add_to(m)
    exclusive_script = excl._template.module.script(excl, {})
    map_var = m.get_name()
    panel_cfg["__mapVar"] = map_var
    panel_cfg["__registryKey"] = f"{map_var}_layers"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        _write_harness(tmp, panel_cfg)
        (tmp / "exclusive.js").write_text(exclusive_script, encoding="utf-8")

        result = subprocess.run(
            [node_available, str(tmp / "harness.js")],
            capture_output=True,
            text=True,
            cwd=tmp,
            check=False,
        )

    assert result.returncode == 0, f"node harness failed:\n{result.stdout}\n{result.stderr}"
    assert "ALL_PASS" in result.stdout
