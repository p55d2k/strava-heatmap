"""Integration tests proving the control panel toggles drive legend visibility.

The generated heatmap has two independently-authored pieces of client-side
JavaScript that are only loosely coupled: the control panel
(``assets/panel.js``) toggles overlay layers on/off by calling
``map.addLayer`` / ``map.removeLayer``, and ``ExclusiveLayerControl`` listens
to Leaflet's ``overlayadd`` / ``overlayremove`` events to show/hide the matching
legend rows (the Heatmap group shows two density *concepts* — a virtual "GPS
Density" row bound to the raster mode picked in the Advanced dropdown, plus
Coverage — as mutually-exclusive radio rows; the remaining metric layers are
independent checkboxes whose legend rows follow their on/off state).

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
    DEFAULT_RASTER_MODE,
    DENSITY_LAYER_NAMES,
    DENSITY_MODE_LAYERS,
    LEGEND_IDS,
    METRIC_LAYER_NAMES,
)
from src.map_builder.control import (
    ControlPanel,
    ExclusiveLayerControl,
    build_advanced_config,
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
    // Support the DOM's optional `force` argument: toggle(c, force) adds when
    // force is truthy and removes when force is falsy, regardless of state.
    toggle(c, force) {
      const had = s.has(c);
      const want = force === undefined ? !had : Boolean(force);
      if (want && !had) s.add(c);
      if (!want && had) s.delete(c);
      return want;
    },
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
    appendChild(c) { c.parentNode = this; this.children.push(c); return c; },
    addEventListener(evt, fn) { (this._listeners[evt] = this._listeners[evt] || []).push(fn); },
    dispatch(evt, detail) { (this._listeners[evt] || []).forEach((f) => f(detail || {})); },
    querySelector(sel) { return querySelectorIn(this, sel); },
    // Deterministic geometry so the tooltip positioning maths can run headless.
    getBoundingClientRect() {
      return { left: 10, top: 10, right: 30, bottom: 24, width: 20, height: 14 };
    },
  };
  // Faithfully mirror real DOM containers: innerHTML = "" empties the children.
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; },
    set(v) { el._html = String(v); if (String(v) === "") el.children.length = 0; },
  });
  // Reflect the `type` property into the attributes map (as real inputs do) so
  // attribute selectors like input[type="range"] resolve against this stub.
  let typeVal = el.type;
  Object.defineProperty(el, "type", {
    get() { return typeVal; },
    set(x) { typeVal = String(x); if (typeVal) el.attributes.type = typeVal; },
    configurable: true,
  });
  return el;
}

const byId = new Map();
const documentObj = {
  readyState: "complete",
  // The info-tooltip card is appended to <body>, so the fake document needs one.
  body: makeEl("body"),
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
// Mirror the static markup's initial state: elements rendered with the hidden
// attribute (e.g. #hcp-advanced-body, #hcp-home-section) start out hidden.
for (const hid of config.__hiddenIds || []) {
  const el = byId.get(hid);
  if (el) el.hidden = true;
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
    fitBounds() {},
    // Record setView calls so the Reset-button scenario can assert the view
    // re-centres on the home location.
    views: [],
    setView(centre, zoom) { map.views.push([centre, zoom]); },
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
const windowObj = { innerWidth: 1024, innerHeight: 768 };
windowObj[config.__registryKey] = { base_layers: {}, overlays }; // findOverlays() scans this
global.window = windowObj;
global.document = documentObj;
global[mapVar] = map; // the exclusive script's `var map = <name>;`

// Mirror Folium's first paint: the default mode's density layer is on the map.
map.addLayer(overlays[config.__defaultDensityLayer]);

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
delete cfg.__defaultDensityLayer;
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

  // Initial paint: the default mode's density row is visible, the other
  // density rows are hidden, and metrics start hidden.
  ok(rowVisible(config.__defaultDensityLayer) === "block",
     "initial: default density row visible");
  ok(rowVisible("Coverage (Places Visited)") === "none",
     "initial: Coverage density row hidden");
  ok(rowVisible("Pace (average)") === "none", "initial: pace metric row hidden");

  // Scenario A - the two density concepts (GPS Density / Coverage) are
  // mutually-exclusive radio rows: toggling Coverage on removes the default
  // density layer from the map and hides its legend row (stacked heatmaps must
  // never overlap). The virtual "GPS Density" row drives the raster-mode layer
  // selected in the Advanced dropdown (Time Spent by default).
  const densityRow = 'input[data-layer-name="GPS Density"]';
  assert.ok(panel.querySelector(densityRow), "virtual GPS Density row exists");
  ok(panel.querySelector(densityRow).checked === true,
     "virtual GPS Density row reflects the default mode layer being on");
  toggle("Coverage (Places Visited)", true);
  ok(rowVisible("Coverage (Places Visited)") === "block",
     "coverage row shown after radio on");
  ok(rowVisible(config.__defaultDensityLayer) === "none",
     "default density row hidden — density concepts are mutually exclusive");
  ok(map.hasLayer(overlays[config.__defaultDensityLayer]) === false,
     "default density layer removed from the map when Coverage is selected");
  // Selecting the GPS Density concept again restores the default mode layer.
  toggle("GPS Density", true);
  ok(map.hasLayer(overlays[config.__defaultDensityLayer]) === true,
     "GPS Density row re-adds the active raster-mode layer");
  ok(rowVisible(config.__defaultDensityLayer) === "block",
     "default density row shown again after radio re-selected");
  ok(rowVisible("Coverage (Places Visited)") === "none",
     "Coverage hidden when the default density layer is re-selected");

  // Scenario B - an independent metric checkbox shows/hides only its own row.
  toggle("Pace (average)", true);
  ok(rowVisible("Pace (average)") === "block", "pace row shown after toggle on");
  toggle("Pace (average)", false);
  ok(rowVisible("Pace (average)") === "none", "pace row hidden after toggle off");

  // Scenario C - a metric toggle must not disturb density / other metrics.
  toggle("Heart rate (average)", true);
  ok(rowVisible("Heart rate (average)") === "block", "HR row shown after toggle on");
  ok(rowVisible(config.__defaultDensityLayer) === "block",
     "density row unaffected by a metric toggle");

  // Scenario D - toggling an unbound layer (Raw GPS tracks) changes no legend row.
  const before = rowVisible(config.__defaultDensityLayer);
  toggle("Raw GPS tracks", true);
  ok(rowVisible(config.__defaultDensityLayer) === before,
     "density row unchanged when toggling an unbound layer");

  // Scenario E - the home marker is on by default and its checkbox hides /
  // re-shows it without touching overlay events or legend rows. Without a home
  // location the section stays hidden and toggling it is a no-op.
  const homeSection = byId.get("hcp-home-section");
  const homeCheckbox = byId.get("hcp-home-marker");
  const tsBeforeHomeToggle = rowVisible(config.__defaultDensityLayer);
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
  ok(rowVisible(config.__defaultDensityLayer) === tsBeforeHomeToggle,
     "home marker toggle does not disturb legend rows");

  // Scenario H - Reset re-centres the home location (falling back to the data
  // bounding-box centre when no home was configured) and restores zoomStart.
  const resetBtn = byId.get("hcp-reset");
  assert.ok(resetBtn, "reset button exists");
  resetBtn.dispatch("click");
  const expectedReset = config.home || config.centre;
  const lastView = map.views[map.views.length - 1];
  ok(Array.isArray(lastView) && lastView[0][0] === expectedReset[0] &&
     lastView[0][1] === expectedReset[1],
     "Reset centres the home location (or the centre fallback)");
  ok(Array.isArray(lastView) && lastView[1] === config.zoomStart,
     "Reset restores the initial zoom level");

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
  // group, so instead of one slider per layer they share a single combined
  // "Heatmap" slider that drives whichever concept is currently active. It
  // defaults to 100% and carries its value across radio switches and Advanced
  // dropdown mode changes.
  const heatmapSlider = panel.querySelector('input[data-layer-opacity="Heatmap"]');
  assert.ok(heatmapSlider, "a single combined Heatmap opacity slider exists");
  // None of the density variants may have their own slider.
  ok(config.__densityLayers.every(
       (n) => !panel.querySelector('input[data-layer-opacity="' + n + '"]')),
     "density variants share one Heatmap slider (no per-variant sliders)");
  ok(heatmapSlider.value === "100", "Heatmap slider defaults to 100%");
  const tsLayer = overlays[config.__defaultDensityLayer];
  ok(tsLayer.sub.opts[tsLayer.sub.opts.length - 1] === 1.0,
     "active density layer initialised to Heatmap 100% opacity");

  // Moving the shared slider drives the currently active heatmap layer only.
  heatmapSlider.value = "40";
  heatmapSlider.dispatch("input");
  ok(tsLayer.sub.opts[tsLayer.sub.opts.length - 1] === 0.4,
     "Heatmap slider drives the active density layer to 0.4");

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

  // Scenario N - the Advanced section is its own collapsible menu (like Layer
  // opacity) and holds the rasterization-mode dropdown. The dropdown swaps the
  // pre-baked GPS Density layers on the map without re-rasterizing.
  const advToggle = byId.get("hcp-advanced-toggle");
  const advBody = byId.get("hcp-advanced-body");
  const modeSelect = byId.get("hcp-density-mode");
  assert.ok(advToggle && advBody && modeSelect, "advanced section elements exist");
  ok(advBody.hidden === true, "advanced section starts collapsed");
  advToggle.dispatch("click");
  ok(advBody.hidden === false, "advanced toggle expands the section");
  ok(advToggle.getAttribute("aria-expanded") === "true", "advanced toggle aria-expanded");
  advToggle.dispatch("click");
  ok(advBody.hidden === true, "advanced toggle collapses the section again");

  // The dropdown lists one option per raster mode, with the build's mode active.
  const optionKeys = modeSelect.children.map((o) => o.value);
  ok(JSON.stringify(optionKeys) === JSON.stringify(config.__modeLayers.map((m) => m.mode)),
     "advanced dropdown lists every raster mode in order");
  ok(modeSelect.value === config.__activeMode,
     "advanced dropdown preselects the configured raster mode");

  // Coverage is still selected from Scenario F2; switching the mode to
  // "raw-count" must swap the density layer back on (radio exclusivity) and
  // hide Coverage, with the GPS Density row still bound to the new layer.
  modeSelect.value = "raw-count";
  modeSelect.dispatch("change");
  ok(map.hasLayer(overlays["GPS Density (Raw Passes)"]) === true,
     "advanced dropdown puts the raw-count layer on the map");
  ok(map.hasLayer(overlays["Coverage (Places Visited)"]) === false,
     "advanced dropdown removes Coverage (radio exclusivity)");
  ok(rowVisible("GPS Density (Raw Passes)") === "block",
     "raw-count legend row becomes visible via the dropdown");
  ok(rowVisible("Coverage (Places Visited)") === "none",
     "coverage legend row hidden after dropdown switch");
  ok(panel.querySelector(densityRow).checked === true,
     "virtual GPS Density row re-binds to the new mode layer");

  // Stepping through every remaining mode keeps exclusivity at all times.
  for (const { mode, layer } of config.__modeLayers) {
    if (mode === "raw-count") continue;
    modeSelect.value = mode;
    modeSelect.dispatch("change");
    ok(map.hasLayer(overlays[layer]) === true, "mode layer on the map: " + mode);
    ok(rowVisible(layer) === "block", "mode legend row shown: " + mode);
    for (const other of config.__densityLayers) {
      if (other === layer) continue;
      ok(map.hasLayer(overlays[other]) === false,
         "no stacking: " + other + " is off while " + layer + " is on");
      ok(rowVisible(other) === "none",
         "no stacked legend: " + other + " row hidden while " + layer + " is on");
    }
  }
  // Restoring the default mode leaves the map in its initial visual state.
  modeSelect.value = config.__activeMode;
  modeSelect.dispatch("change");
  ok(map.hasLayer(overlays[config.__defaultDensityLayer]) === true,
     "default density layer restored via the advanced dropdown");
  ok(rowVisible(config.__defaultDensityLayer) === "block",
     "default density row restored after stepping through all modes");

  // The Heatmap slider still drives whichever mode layer the dropdown swapped
  // in — here the restored default (decay) layer, at its new 60% value.
  heatmapSlider.value = "60";
  heatmapSlider.dispatch("input");
  const rawLayer = overlays["GPS Density (Raw Passes)"];
  ok(tsLayer.sub.opts[tsLayer.sub.opts.length - 1] === 0.6,
     "Heatmap slider drives the dropdown-selected density layer");
  ok(rawLayer.sub.opts[rawLayer.sub.opts.length - 1] === 0.4,
     "the off raw-count layer keeps the value it had when it was swapped out");

  // Scenario F3 - a slider whose layer is not on the map is greyed out
  // (disabled): the row keeps its position but the range input no longer
  // accepts input, and it re-enables as soon as the layer becomes visible.
  const paceRowEl = panel.querySelector('div[data-layer-opacity="Pace (average)"]');
  const heatRowEl = panel.querySelector('div[data-layer-opacity="Heatmap"]');
  assert.ok(paceRowEl && heatRowEl, "slider row wrappers exist for pace and heatmap");
  ok(paceRowEl.classList.contains("hcp-opacity-disabled") === true,
     "pace slider row is greyed out while the pace layer is off");
  ok(paceSlider.disabled === true,
     "pace range input is disabled while the pace layer is off");
  ok(heatRowEl.classList.contains("hcp-opacity-disabled") === false,
     "Heatmap slider row stays enabled while a density layer is on");

  toggle("Pace (average)", true);
  ok(paceRowEl.classList.contains("hcp-opacity-disabled") === false,
     "pace slider row enables when the pace layer is toggled on");
  ok(paceSlider.disabled === false,
     "pace range input is enabled after the layer is toggled on");
  toggle("Pace (average)", false);
  ok(paceRowEl.classList.contains("hcp-opacity-disabled") === true,
     "pace slider row greys out again when the pace layer is toggled off");

  // The shared Heatmap slider follows the radio concept: turning the virtual
  // GPS Density row off greys it out; turning it back on re-enables it.
  toggle("GPS Density", false);
  ok(heatRowEl.classList.contains("hcp-opacity-disabled") === true,
     "Heatmap slider row greys out when the density concept is turned off");
  ok(heatmapSlider.disabled === true,
     "Heatmap range input is disabled while no density layer is on the map");
  toggle("GPS Density", true);
  ok(heatRowEl.classList.contains("hcp-opacity-disabled") === false,
     "Heatmap slider row re-enables when the density concept is back on");

  // Scenario T - every control carries a plain-language explanation, and the
  // explanation appears in a floating card while the pointer rests on it.
  const rawInput = panel.querySelector('input[data-layer-name="Raw GPS tracks"]');
  assert.ok(rawInput, "raw GPS tracks toggle exists");
  const rawRow = rawInput.parentNode;
  const rawHelp = rawRow && rawRow.getAttribute("data-hcp-help");
  ok(typeof rawHelp === "string" && rawHelp.length > 30,
     "each layer toggle carries an explanation");
  ok(rawRow.querySelector(".hcp-info") !== null,
     "each explained toggle shows the info badge");

  // Hovering any part of the row (here the checkbox itself) finds the
  // explanation through the delegated listeners on the panel.
  panel.dispatch("mouseover", { target: rawInput, relatedTarget: null });
  await delay(500);
  const tip = document.body.children.filter(
    (el) => el.className === "hcp-tooltip"
  ).pop();
  ok(Boolean(tip && tip.classList.contains("hcp-tooltip-visible")),
     "hovering a control opens the help card");
  ok(Boolean(tip) && tip.textContent === rawHelp,
     "help card shows that control's explanation");

  // Leaving the control closes the card again.
  panel.dispatch("mouseout", { target: rawInput, relatedTarget: null });
  ok(Boolean(tip) && !tip.classList.contains("hcp-tooltip-visible"),
     "leaving the control closes the help card");

  // The shared Heatmap slider and the per-layer sliders are explained too.
  const heatSliderRow = panel.querySelector('div[data-layer-opacity="Heatmap"]');
  ok(Boolean(heatSliderRow && heatSliderRow.getAttribute("data-hcp-help")),
     "the shared Heatmap opacity slider carries an explanation");
  const paceSliderRow = panel.querySelector('div[data-layer-opacity="Pace (average)"]');
  ok(Boolean(paceSliderRow && paceSliderRow.getAttribute("data-hcp-help")),
     "a per-layer opacity slider carries an explanation");
  // The basemap style buttons are explained individually (no badge needed —
  // the "Basemap" label carries the visible cue).
  const basemapBox = byId.get("hcp-basemap");
  ok(Boolean(basemapBox) && basemapBox.children.length > 0 &&
     basemapBox.children.every((b) => Boolean(b.getAttribute("data-hcp-help"))),
     "each basemap style button carries an explanation");

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


def _panel_hidden_ids() -> list[str]:
    """Return the template element ids rendered with the ``hidden`` attribute."""
    html = build_control_panel_html()
    return re.findall(r'id="([^"]+)"[^>]*\bhidden\b', html)


def _overlay_layers() -> list[tuple[str, str, bool]]:
    """Build a production-shaped overlay layer list for the panel config.

    Mirrors ``generate_layer_uris``: one GPS Density layer per raster mode with
    only the default mode's layer visible, then Coverage and the metrics.
    """
    layers = [
        (name, "data:image/png;base64,x", name == DENSITY_MODE_LAYERS[DEFAULT_RASTER_MODE])
        for name in DENSITY_LAYER_NAMES
    ]
    layers += [(n, "data:image/png;base64,x", False) for n in METRIC_LAYER_NAMES]
    return layers


def _write_harness(tmp: Path, panel_cfg: dict) -> None:
    """Write the node harness inputs derived from real production assets."""
    config = dict(panel_cfg)
    config["__legendIdByLayer"] = LEGEND_IDS
    config["__layerNames"] = list(LEGEND_IDS.keys()) + [_RAW_TRACKS]
    config["__panelIds"] = [pid for pid in _panel_ids() if pid != config["panelId"]]
    config["__hiddenIds"] = _panel_hidden_ids()
    config["__densityLayers"] = list(DENSITY_LAYER_NAMES)
    config["__defaultDensityLayer"] = DENSITY_MODE_LAYERS[DEFAULT_RASTER_MODE]
    config["__activeMode"] = DEFAULT_RASTER_MODE
    config["__modeLayers"] = [
        {"mode": mode, "layer": layer} for mode, layer in DENSITY_MODE_LAYERS.items()
    ]

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
        advanced=build_advanced_config(
            DEFAULT_RASTER_MODE,
            overlay_layers=_overlay_layers(),
            default_opacity=0.85,
        ),
    )
    panel_cfg = json.loads(panel.config_json)

    # Parent the ExclusiveLayerControl to a real folium map so its output uses
    # production values (map variable name, embedded legend ids), not stand-ins.
    m = folium.Map(location=[45.0, -122.0], zoom_start=14, tiles=None)
    excl = ExclusiveLayerControl(legend_ids=LEGEND_IDS)
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
