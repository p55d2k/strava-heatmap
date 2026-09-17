/*
 * Strava Heatmap — Unified Control Panel behaviour.
 *
 * Self-contained client-side logic for the single top-right control panel
 * embedded in the generated heatmap HTML. It merges what used to be the
 * stock Leaflet layer control into one central panel:
 *
 *   - Basemap style switching  (Dark / Light / Voyager)
 *   - Layer toggles            (radio for the density concepts — one virtual
 *                               "GPS Density" row plus Coverage — checkbox
 *                               for independent layers such as raw GPS tracks)
 *   - Per-layer opacity sliders (one per layer, collapsible via "Opacity";
 *                               a slider is greyed out while its layer is not
 *                               on the map)
 *   - Advanced section          (collapsible; rasterization-mode dropdown that
 *                               swaps which pre-baked GPS Density overlay is
 *                               bound to the "GPS Density" row)
 *   - Fit-to-heatmap / Reset view
 *   - Legend toggle
 *   - Save as PNG              (static image export of the current view; the
 *                               html2canvas library it needs is fetched on the
 *                               first click, never at page load)
 *   - Export GeoJSON            (inflates the compressed rasterized grids
 *                               embedded in the page and downloads them as a
 *                               .geojson file for QGIS / Mapbox)
 *   - Export GPX                (inflates the compressed GPX track document
 *                               embedded in the page and downloads it for
 *                               Garmin Connect / QGIS / any other GPX tool)
 *   - Info tooltips             (every control carries plain-language help
 *                               text, shown in a floating card on hover or
 *                               keyboard focus)
 *
 * Folium's build pipeline inlines this file (see
 * src/map_builder/control.py::ControlPanel) and calls
 * `initHeatmapControlPanel(config)` with:
 *
 *   {
 *     panelId:        "heatmap-control-panel",
 *     basemapStyles:  [{ key: "dark_all", label: "Dark" }, ...],
 *     activeBasemap:  "dark_all",
 *     apiKey:         "<CARTO API key>",
 *     opacity:        0.85,
 *     bounds:         [[lat, lon], [lat, lon]],
 *     centre:         [lat, lon],
 *     home:           [lat, lon]  (fallback: centre),
 *     zoomStart:      14,
 *     legendId:       "heatmap-legend",
 *     layerGroups:    [{ label, mode,
 *                        layers: [{ name, visible, count?, unit? }, ...] }, ...],
 *     advanced:       { modes: [{ key, label, layer, visible, opacity }...],
 *                       densityLayerNames: [...], active: "decay" },
 *     gpxFilename:    "tracks.gpx"  (name offered by the Export GPX button),
 *     map:            <the Leaflet map instance>
 *   }
 *
 * Notes on how we talk to Folium's output without relying on Leaflet
 * internals:
 *
 *   * Overlays: Folium always emits a top-level `var` named
 *     `<layer_control>_layers = { base_layers, overlays }`. Because it is a
 *     top-level `var` it is visible on `window`, so we can walk `window` to
 *     locate the overlays map (same technique as ExclusiveLayerControl).
 *   * Basemap: the configured CARTO tile layer is already on the map; we
 *     switch styles by creating a new L.tileLayer for the target style and
 *     removing any existing tile layers whose URL matches the CARTO domain.
 */
(function (global) {
  "use strict";

  /* ---- Helpers ---------------------------------------------------------- */

  function findOverlays() {
    var overlays = null;
    for (var key in global) {
      try {
        var value = global[key];
        if (value && value.overlays && value.base_layers && !overlays) {
          overlays = value.overlays;
        }
      } catch (e) {
        /* Cross-frame access can throw; ignore it. */
      }
    }
    return overlays;
  }

  // Locate the home marker on the map. The marker is a plain circleMarker added
  // directly to the map (not an overlay FeatureGroup), so we walk the layers and
  // match on the custom `homeMarker` option set by ScalableHomeMarker.
  function findHomeMarker(map) {
    var found = null;
    map.eachLayer(function (layer) {
      if (found === null && layer && layer.options && layer.options.homeMarker) {
        found = layer;
      }
    });
    return found;
  }

  function isBasemapLayer(layer) {
    return Boolean(
      layer &&
        layer._url &&
        typeof layer._url === "string" &&
        layer._url.indexOf("basemaps.cartocdn.com") !== -1
    );
  }

  function styleInUrl(url) {
    var match = /rastertiles\/([^/]+)\//.exec(url);
    return match ? match[1] : null;
  }

  function makeTileLayer(style, apiKey) {
    var url =
      "https://basemaps.cartocdn.com/rastertiles/" + style +
      "/{z}/{x}/{y}.png?key=" + encodeURIComponent(apiKey);
    var attribution =
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
      'contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';
    return L.tileLayer(url, {
      maxZoom: 20,
      maxNativeZoom: 20,
      attribution: attribution,
      // Ask for the tiles with CORS so "Save as PNG" can read them back out of
      // the canvas; a tile loaded without it would taint the canvas and make
      // the export unreadable (CARTO serves the tiles with
      // `Access-Control-Allow-Origin: *`).
      crossOrigin: true,
    });
  }

  function currentBasemapStyle(map) {
    var found = null;
    map.eachLayer(function (layer) {
      if (found === null && isBasemapLayer(layer)) {
        found = styleInUrl(layer._url);
      }
    });
    return found;
  }

  function removeBasemapLayers(map, keep) {
    var toRemove = [];
    map.eachLayer(function (layer) {
      if (isBasemapLayer(layer) && layer !== keep) {
        toRemove.push(layer);
      }
    });
    for (var i = 0; i < toRemove.length; i++) {
      map.removeLayer(toRemove[i]);
    }
  }

  // Apply an opacity value to a single child of an overlay layer. Raster
  // overlays (ImageOverlay) expose setOpacity, while vector layers such as the
  // raw GPS track polylines (Leaflet Path / PolyLine) expose setStyle instead.
  function applyOpacityToLayer(sub, opacity) {
    if (!sub) return;
    if (typeof sub.setOpacity === "function") {
      sub.setOpacity(opacity);
    } else if (typeof sub.setStyle === "function") {
      sub.setStyle({ opacity: opacity, fillOpacity: opacity });
    }
  }

  // Apply opacity to a single named overlay layer (used by the per-layer
  // sliders). Overlay layers are FeatureGroups that wrap a child layer, so we
  // walk eachLayer() to reach the leaf that owns the paint options.
  function setLayerOpacityByName(name, overlays, opacity) {
    if (!overlays) return;
    var layer = overlays[name];
    if (!layer) return;
    if (typeof layer.eachLayer === "function") {
      layer.eachLayer(function (sub) {
        applyOpacityToLayer(sub, opacity);
      });
    } else {
      applyOpacityToLayer(layer, opacity);
    }
  }

  // Force a fresh client-side redraw of every currently visible overlay layer.
  // Heatmap overlays are FeatureGroups wrapping ImageOverlays. ImageOverlays
  // (single static data-URI images) occasionally fail to reposition when the
  // map zooms while a layer is shown, leaving the heatmap stale until you pan.
  // Calling redraw() re-applies the layer's bounds so it always matches the
  // current view. It is invoked automatically on zoom end (see init), not by a
  // manual button — for already-correctly-rendered layers this is a cheap no-op.
  function redrawVisibleOverlays(map) {
    var overlays = findOverlays();
    if (!overlays) return;
    for (var name in overlays) {
      if (!Object.prototype.hasOwnProperty.call(overlays, name)) continue;
      var layer = overlays[name];
      if (!layer || !map.hasLayer(layer)) continue;
      if (typeof layer.eachLayer === "function") {
        layer.eachLayer(function (sub) {
          if (sub && typeof sub.redraw === "function") sub.redraw();
        });
      } else if (typeof layer.redraw === "function") {
        layer.redraw();
      }
    }
  }

  function updateSegmentStates(segmentBox, key) {
    var children = segmentBox.children;
    for (var i = 0; i < children.length; i++) {
      var active = children[i].getAttribute("data-style") === key;
      if (active) children[i].classList.add("hcp-segment-active");
      else children[i].classList.remove("hcp-segment-active");
    }
  }

  /* ---- Info tooltips ---------------------------------------------------- */

  // Plain-language explanations, keyed by the layer names used in the panel
  // config. Every toggle therefore gets an explanation, and a new layer only
  // needs one entry added here. The wording deliberately avoids jargon:
  // this is read by people who just want to know what a control does.
  var LAYER_HELP = {
    "GPS Density":
      "A heatmap of where you spend the most time. Brighter areas are places you visit more often or stay in longer.",
    "Coverage (Places Visited)":
      "Shows the places you have been to at least once. Brighter areas are spots that more of your activities passed through.",
    "Raw GPS tracks":
      "Draws the exact routes you travelled as thin lines, so you can see the paths behind the heatmap.",
    "Pace (average)":
      "Colours the map by how fast you were moving. Warm colours mean a faster pace, cool colours a slower one.",
    "Heart rate (average)":
      "Colours the map by your average heart rate. Warm colours mean your heart was beating faster.",
    "Gradient (absolute)":
      "Colours the map by how steep the ground is. Bright areas are steep, dark areas are flat.",
    "Gradient (change)":
      "Colours the map by whether you were going uphill or downhill: one colour for climbing, another for descending.",
  };
  var LAYER_HELP_FALLBACK = "Turn this layer on or off on the map.";

  var OPACITY_HELP =
    "How see-through this layer is. Drag left to make it fainter, right to make it stronger.";
  var HEATMAP_OPACITY_HELP =
    "How bold the heatmap looks. Drag left to make it fainter, right to make it bolder.";

  // One line per basemap style (the group itself is explained by the label).
  var BASEMAP_HELP = {
    voyager: "A colourful street map with lots of road and place names — handy for keeping your bearings.",
    light_all: "A plain light background. Easiest to see against in bright daylight.",
    dark_all: "A dark background that makes the heatmap colours stand out. Easy on the eyes at night.",
  };
  var BASEMAP_HELP_FALLBACK = "Changes the background map behind your heatmap.";

  // The floating card is created once and reused; it lives on <body> (not in
  // the sidebar) so the sidebar's own scrolling can never clip it.
  var helpTip = null;
  var helpTimer = null;
  var HELP_DELAY_MS = 250;

  function ensureHelpTip() {
    if (helpTip) return helpTip;
    if (!document || !document.body) return null;
    helpTip = document.createElement("div");
    helpTip.className = "hcp-tooltip";
    helpTip.setAttribute("role", "tooltip");
    document.body.appendChild(helpTip);
    return helpTip;
  }

  // Sit the card just to the right of the control, flipping to the left (or
  // above/below) rather than running off the edge of the viewport.
  function positionHelpTip(target) {
    var tip = ensureHelpTip();
    if (!tip || typeof target.getBoundingClientRect !== "function") return;
    var rect = target.getBoundingClientRect();
    var tipRect = tip.getBoundingClientRect();
    var left = rect.right + 10;
    if (left + tipRect.width > window.innerWidth - 8) {
      left = rect.left - tipRect.width - 10;
    }
    if (left < 8) left = 8;
    var top = rect.top + rect.height / 2 - tipRect.height / 2;
    if (top < 8) top = 8;
    if (top + tipRect.height > window.innerHeight - 8) {
      top = window.innerHeight - tipRect.height - 8;
    }
    tip.style.left = Math.round(left) + "px";
    tip.style.top = Math.round(top) + "px";
  }

  function showHelp(target) {
    var text = target && target.getAttribute ? target.getAttribute("data-hcp-help") : null;
    if (!text) return;
    var tip = ensureHelpTip();
    if (!tip) return;
    tip.textContent = text;
    positionHelpTip(target);
    tip.classList.add("hcp-tooltip-visible");
  }

  function hideHelp() {
    if (helpTimer) {
      clearTimeout(helpTimer);
      helpTimer = null;
    }
    if (helpTip) helpTip.classList.remove("hcp-tooltip-visible");
  }

  // Walk up from an event target to the nearest control that owns help text, so
  // hovering any part of a row (its label, its checkbox, its badge) works.
  function findHelpOwner(node) {
    var depth = 0;
    while (node && depth < 8) {
      if (node.getAttribute && node.getAttribute("data-hcp-help")) return node;
      node = node.parentNode;
    }
    return null;
  }

  // Add the small "i" badge that advertises an explanation. The hover handling
  // itself is delegated (see installHelpTooltips), so controls that are
  // re-rendered later keep working without re-wiring anything.
  function makeHelpIcon() {
    var icon = document.createElement("span");
    icon.className = "hcp-info";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "i";
    return icon;
  }

  function addHelpIcon(el, help) {
    if (!el || !help) return el;
    el.setAttribute("data-hcp-help", help);
    el.appendChild(makeHelpIcon());
    return el;
  }

  // Delegated listeners on the panel container: a short pause before the card
  // appears keeps quick taps on a checkbox from flashing it, and the card is
  // dismissed as soon as the pointer leaves (or the panel is scrolled).
  function installHelpTooltips(scope) {
    if (!scope || typeof scope.addEventListener !== "function") return;
    scope.addEventListener("mouseover", function (event) {
      var owner = findHelpOwner(event.target);
      if (!owner) return;
      if (helpTimer) clearTimeout(helpTimer);
      helpTimer = setTimeout(function () {
        showHelp(owner);
      }, HELP_DELAY_MS);
    });
    scope.addEventListener("mouseout", function (event) {
      var owner = findHelpOwner(event.target);
      if (!owner) return;
      // Sliding between two children of the same control must not close it.
      var next = event.relatedTarget;
      if (next && typeof owner.contains === "function" && owner.contains(next)) return;
      hideHelp();
    });
    scope.addEventListener("focusin", function (event) {
      var owner = findHelpOwner(event.target);
      if (owner) showHelp(owner);
    });
    scope.addEventListener("focusout", hideHelp);
    scope.addEventListener("scroll", hideHelp, true);
  }

  /* ---- Advanced section (rasterization-mode dropdown) ------------------- */

  // Resolve the raster-mode config into a lookup keyed by overlay layer name:
  // { label, key }. Returns null when the Advanced section is not configured.
  function densityModesByLayer(advanced) {
    if (!advanced || !advanced.modes || !advanced.modes.length) return null;
    var byLayer = {};
    advanced.modes.forEach(function (m) {
      if (m && m.layer) byLayer[m.layer] = { key: m.key, label: m.label || m.key };
    });
    return byLayer;
  }

  // Sync the Advanced dropdown + toggle rows with the mode layer currently on
  // the map. Used after external layer changes (overlay events) so the panel
  // never shows a mode that does not match the visible heatmap.
  function syncAdvancedFromMap(map, overlays, advanced) {
    if (!advanced || !advanced.modes) return;
    var activeKey = null;
    advanced.modes.forEach(function (m) {
      var layer = m.layer && overlays ? overlays[m.layer] : null;
      if (layer && map.hasLayer(layer)) activeKey = m.key;
    });
    if (activeKey && advanced.active !== activeKey) {
      advanced.active = activeKey;
      var select = document.getElementById("hcp-density-mode");
      if (select) select.value = activeKey;
    }
  }

  // Resolve which overlay layer a panel row actually drives. The Heatmap radio
  // group shows a single virtual "GPS Density" concept (no overlay is registered
  // under that name); it stands for whichever raster-mode layer the Advanced
  // dropdown currently selects (Time Spent / Raw Passes / Unique Visits). Rows
  // whose name IS a registered overlay resolve to themselves.
  function resolveDensityLayer(name, overlays, ctx) {
    if (overlays && overlays[name]) return overlays[name];
    if (!ctx || !ctx.advanced || !ctx.advanced.modes) return null;
    var match = null;
    ctx.advanced.modes.forEach(function (m) {
      if (m && m.layer && m.key === ctx.advanced.active) match = overlays ? overlays[m.layer] : null;
    });
    return match;
  }

  // Names excluded when a radio row is selected: the sibling rows in the group
  // plus — for the virtual "GPS Density" row — every raster-mode layer it may
  // stand for, so no stale density variant is ever left on the map. The one
  // exception is the mode layer the selected row currently resolves to (found
  // by identity in the overlay registry), which must stay available to add.
  function densityExclusionNames(group, selectedName, ctx, overlays) {
    var names = [];
    group.layers.forEach(function (lDef) {
      if (lDef.name !== selectedName && names.indexOf(lDef.name) === -1) {
        names.push(lDef.name);
      }
    });
    if (ctx && ctx.densityLayerNames && ctx.densityGroupLabel === group.label) {
      var keepName = resolveDensityLayer(selectedName, overlays, ctx);
      var keepKey = null;
      if (keepName && overlays) {
        for (var k in overlays) {
          if (Object.prototype.hasOwnProperty.call(overlays, k) && overlays[k] === keepName) {
            keepKey = k;
            break;
          }
        }
      }
      ctx.densityLayerNames.forEach(function (name) {
        if (name === keepKey) return;
        if (names.indexOf(name) === -1) names.push(name);
      });
    }
    return names;
  }

  /* ---- Layer toggle list ------------------------------------------------ */

  // Resolve the opacity a new layer/slider should start at: the layer's own
  // configured opacity (lDef.opacity) if set, else the global default.
  function initialOpacityFor(lDef, defaultOpacity) {
    return lDef && typeof lDef.opacity === "number"
      ? lDef.opacity
      : typeof defaultOpacity === "number"
        ? defaultOpacity
        : 0.85;
  }

  // Build the muted badge showing how much data a layer carries (the number of
  // tracks / activities it is built from). The figure is computed at build time
  // (see src/map_builder/control.py::compute_layer_counts); layers with no count
  // in the config render no badge, so bespoke overlays stay uncluttered.
  function makeLayerCountBadge(lDef) {
    if (!lDef || typeof lDef.count !== "number") return null;
    var unit = lDef.unit || "item";
    var badge = document.createElement("span");
    badge.className = "hcp-layer-count";
    badge.textContent = lDef.count + " " + unit + (lDef.count === 1 ? "" : "s");
    return badge;
  }

  // Build a single toggle row (radio or checkbox) bound to an overlay layer.
  // Opacity sliders live in a separate section (see buildOpacityList) so the
  // toggle rows stay compact. For radio groups, onRadioChange(name) fires when
  // that variant becomes selected so the panel can swap which slider is shown.
  //
  // A row whose name has no matching overlay (e.g. the virtual "GPS Density"
  // concept in the Heatmap radio group) binds to whichever raster-mode layer is
  // currently selected in the Advanced dropdown (see resolveDensityLayer), so
  // the three pre-baked density variants share this single row.
  function buildToggleRow(lDef, mode, radioName, map, overlays, onRadioChange, ctx) {
    var row = document.createElement("label");
    row.className = "hcp-layer-row";

    var input = document.createElement("input");
    input.type = mode === "radio" ? "radio" : "checkbox";
    if (mode === "radio") {
      input.name = radioName;
    }
    input.setAttribute("data-layer-name", lDef.name);

    // A virtual row has no overlay registered under its own name; resolve to
    // the active raster-mode layer so the row reflects real map state.
    var layer = resolveDensityLayer(lDef.name, overlays, ctx);
    input.checked = layer ? map.hasLayer(layer) : Boolean(lDef.visible);

    input.addEventListener("change", function () {
      // Re-resolve on every interaction: the Advanced dropdown can swap which
      // raster-mode layer the virtual row drives between clicks.
      var boundLayer = resolveDensityLayer(lDef.name, overlays, ctx);
      if (!boundLayer) return;
      if (input.checked) {
        // Enforce radio exclusivity BEFORE adding the target: the virtual
        // "GPS Density" row stands for a raster-mode layer that is also in
        // the exclusion set, so adding first would get it removed again.
        if (mode === "radio" && onRadioChange) onRadioChange(lDef.name);
        if (!map.hasLayer(boundLayer)) map.addLayer(boundLayer);
      } else {
        if (map.hasLayer(boundLayer)) map.removeLayer(boundLayer);
      }
    });

    row.appendChild(input);
    var span = document.createElement("span");
    span.textContent = lDef.label || lDef.name;
    row.appendChild(span);
    // Explain what the layer shows, in everyday language (see LAYER_HELP).
    addHelpIcon(row, LAYER_HELP[lDef.name] || LAYER_HELP[lDef.label] || LAYER_HELP_FALLBACK);
    // The data-size badge sits at the row's right edge (CSS), so the counts
    // line up in a column and the layer names stay scannable.
    var countBadge = makeLayerCountBadge(lDef);
    if (countBadge) row.appendChild(countBadge);
    return row;
  }

  // Render a set of rows into a prepared container, replacing any previous rows.
  function buildGroupRows(rows, lDefs, mode, radioName, map, overlays, onRadioChange, ctx) {
    rows.innerHTML = "";
    lDefs.forEach(function (lDef) {
      rows.appendChild(buildToggleRow(lDef, mode, radioName, map, overlays, onRadioChange, ctx));
    });
  }

  // Build the toggle rows for each configured layer group. Groups use two modes:
  //   * "radio"  (Heatmap density concepts) — mutually exclusive; selecting one
  //     removes the other layer(s) in the group from the map so stacked
  //     heatmaps can never overlap. The Heatmap group's "GPS Density" row is
  //     virtual: it stands for whichever raster-mode layer the Advanced
  //     dropdown selects (Time Spent / Raw Passes / Unique Visits), so its
  //     exclusivity must cover all of those layers, not just named rows.
  //   * "check"  (metrics, raw tracks) — each layer toggles independently.
  function buildLayerList(container, layerGroups, map, overlays, config, ctx) {
    layerGroups.forEach(function (group, gIdx) {
      var groupLabel = document.createElement("div");
      groupLabel.className = "hcp-label hcp-layer-group-label";
      groupLabel.textContent = group.label;
      container.appendChild(groupLabel);

      var rows = document.createElement("div");
      rows.className = "hcp-layer-rows";
      container.appendChild(rows);

      // For a radio group, enforce exclusivity at the map level: when one concept
      // is selected, hide every other layer in the same group. For the Heatmap
      // group the other layers include every raster-mode density variant (they
      // all belong to the virtual "GPS Density" row). The resulting overlayadd /
      // overlayremove events keep legend rows in sync automatically.
      var onRadioChange = null;
      if (group.mode === "radio") {
        onRadioChange = function (selectedName) {
          var otherNames = densityExclusionNames(group, selectedName, ctx, overlays);
          otherNames.forEach(function (name) {
            var otherLayer = overlays ? overlays[name] : null;
            if (otherLayer && map.hasLayer(otherLayer)) map.removeLayer(otherLayer);
          });
        };
      }

      buildGroupRows(
        rows,
        group.layers,
        group.mode,
        "hcp-layer-group-" + gIdx,
        map,
        overlays,
        onRadioChange,
        ctx
      );
    });
  }

  /* ---- Layer opacity sliders (collapsible section) --------------------- */

  // Build one slider row for a single layer. The 0-100 range maps to 0.0-1.0
  // opacity and only ever touches that layer's overlay.
  function buildOpacitySlider(name, initial, overlays) {
    var item = document.createElement("div");
    item.className = "hcp-layer-opacity";
    // Tag the wrapper too so UI state (show/hide) can be queried by layer name.
    item.setAttribute("data-layer-opacity", name);

    var nameEl = document.createElement("span");
    nameEl.className = "hcp-layer-opacity-name";
    nameEl.textContent = name;
    // The help text hangs off the whole row so hovering the slider explains it too.
    item.setAttribute("data-hcp-help", OPACITY_HELP);
    nameEl.appendChild(makeHelpIcon());
    item.appendChild(nameEl);

    var control = document.createElement("div");
    control.className = "hcp-layer-opacity-control";

    var input = document.createElement("input");
    input.type = "range";
    input.min = "0";
    input.max = "100";
    input.step = "1";
    input.value = String(Math.round(initial * 100));
    input.setAttribute("data-layer-opacity", name);
    input.title = name + " opacity";

    var valueEl = document.createElement("span");
    valueEl.className = "hcp-layer-opacity-value";
    valueEl.textContent = Math.round(initial * 100) + "%";

    input.addEventListener("input", function () {
      var pct = parseFloat(input.value) || 0;
      valueEl.textContent = Math.round(pct) + "%";
      setLayerOpacityByName(name, overlays, pct / 100);
    });

    control.appendChild(input);
    control.appendChild(valueEl);
    item.appendChild(control);

    // Match the layer's initial opacity to its slider on load.
    setLayerOpacityByName(name, overlays, initial);
    return item;
  }

  // Build a single shared opacity slider for an entire radio group (e.g. the
  // Heatmap density concepts "Time Spent" / "Coverage"). Because radio layers
  // are mutually exclusive (only one is on the map at a time), one slider
  // controls whichever variant is currently active rather than showing a slider
  // per layer. On load, and whenever the active variant switches, the slider
  // value is applied to the layer that is currently on the map.
  function buildRadioGroupOpacitySlider(group, map, overlays, ctx) {
    var item = document.createElement("div");
    item.className = "hcp-layer-opacity";
    item.setAttribute("data-layer-opacity", group.label);

    var nameEl = document.createElement("span");
    nameEl.className = "hcp-layer-opacity-name";
    nameEl.textContent = group.label;
    item.setAttribute("data-hcp-help", HEATMAP_OPACITY_HELP);
    nameEl.appendChild(makeHelpIcon());
    item.appendChild(nameEl);

    var control = document.createElement("div");
    control.className = "hcp-layer-opacity-control";

    // The combined radio-group slider defaults to fully opaque (100%).
    var initial = 1.0;

    var input = document.createElement("input");
    input.type = "range";
    input.min = "0";
    input.max = "100";
    input.step = "1";
    input.value = String(Math.round(initial * 100));
    input.setAttribute("data-layer-opacity", group.label);
    input.title = group.label + " opacity";

    var valueEl = document.createElement("span");
    valueEl.className = "hcp-layer-opacity-value";
    valueEl.textContent = Math.round(initial * 100) + "%";

    // Apply the slider's current value to whichever layer in the group is on
    // the map. For the Heatmap group the virtual "GPS Density" row stands for
    // every raster-mode layer, so the value also applies to all of them — that
    // way switching modes in the Advanced dropdown keeps the slider's value.
    function applyToActive() {
      var pct = parseFloat(input.value) || 0;
      var names = group.layers.map(function (lDef) {
        return lDef.name;
      });
      if (ctx && ctx.densityGroupLabel === group.label && ctx.densityLayerNames) {
        ctx.densityLayerNames.forEach(function (name) {
          if (names.indexOf(name) === -1) names.push(name);
        });
      }
      names.forEach(function (name) {
        var layer = overlays ? overlays[name] : null;
        if (layer && map.hasLayer(layer)) {
          setLayerOpacityByName(name, overlays, pct / 100);
        }
      });
    }

    input.addEventListener("input", function () {
      var pct = parseFloat(input.value) || 0;
      valueEl.textContent = Math.round(pct) + "%";
      applyToActive();
    });

    // When a different radio variant is switched on, carry the shared slider
    // value over to the newly active layer automatically. The handlers are
    // registered in ctx so re-rendering the sliders can remove them again.
    if (!ctx) ctx = {};
    if (!ctx.opacityHandlers) ctx.opacityHandlers = [];
    ctx.opacityHandlers.push({ map: map, fn: applyToActive });
    map.on("overlayadd", applyToActive);
    map.on("overlayremove", applyToActive);

    control.appendChild(input);
    control.appendChild(valueEl);
    item.appendChild(control);

    // Match the currently active layer's opacity to the slider on load.
    applyToActive();

    return item;
  }

  // Grey a slider row out while its layer is not on the map (hidden rows
  // keep their position, so the layout does not jump on every toggle).
  function setSliderRowEnabled(item, enabled) {
    item.classList.toggle("hcp-opacity-disabled", !enabled);
    var input = item.querySelector('input[type="range"]');
    if (input) input.disabled = !enabled;
  }

  // A layer is "in use" when it is on the map; for the shared Heatmap slider
  // any raster-mode variant (the virtual "GPS Density" row's possible targets)
  // or Coverage being visible counts as in use.
  function updateSliderRowState(item, name, map, overlays, ctx) {
    var inUse = false;
    if (name === "Heatmap") {
      var candidates = ctx && ctx.densityLayerNames ? ctx.densityLayerNames.slice() : [];
      if (ctx && ctx.densityGroupLabel === "Heatmap" && ctx.groupLayerNames) {
        ctx.groupLayerNames["Heatmap"].forEach(function (n) {
          if (candidates.indexOf(n) === -1) candidates.push(n);
        });
      }
      candidates.forEach(function (n) {
        var layer = overlays ? overlays[n] : null;
        if (layer && map.hasLayer(layer)) inUse = true;
      });
    } else {
      var layer = overlays ? overlays[name] : null;
      inUse = Boolean(layer && map.hasLayer(layer));
    }
    setSliderRowEnabled(item, inUse);
  }

  // Render the opacity sliders for every layer group, into a prepared container.
  // Checkbox groups (metrics, raw tracks) expose one slider per layer. Radio
  // groups (e.g. the Heatmap density concepts) are mutually exclusive — only
  // one is on the map at a time — so they share a single combined slider
  // labelled by the group name. That slider defaults to 100% and drives
  // whichever variant is currently active. Sliders whose layer is not currently
  // on the map are greyed out (disabled) and re-enable automatically via the
  // overlayadd / overlayremove listeners registered in ctx.opacityHandlers.
  function buildOpacityList(container, layerGroups, map, overlays, config, defaultOpacity, ctx) {
    container.innerHTML = "";
    // Drop the previous render's overlay listeners before re-registering.
    (ctx && ctx.opacityHandlers ? ctx.opacityHandlers : []).forEach(function (h) {
      h.map.off("overlayadd", h.fn);
      h.map.off("overlayremove", h.fn);
    });
    if (ctx) ctx.opacityHandlers = [];

    if (!ctx) ctx = {};
    if (!ctx.groupLayerNames) ctx.groupLayerNames = {};

    layerGroups.forEach(function (group) {
      ctx.groupLayerNames[group.label] = group.layers.map(function (lDef) {
        return lDef.name;
      });
      if (group.mode === "radio") {
        container.appendChild(buildRadioGroupOpacitySlider(group, map, overlays, ctx));
      } else {
        group.layers.forEach(function (lDef) {
          container.appendChild(
            buildOpacitySlider(lDef.name, initialOpacityFor(lDef, defaultOpacity), overlays)
          );
        });
      }
    });

    // Apply the initial greyed-out state, then keep it in sync with the map:
    // these listeners fire on every overlayadd / overlayremove, covering both
    // direct toggle clicks and the Advanced dropdown's mode swaps.
    var rows = {};
    Array.prototype.forEach.call(container.children, function (item) {
      var name = item.getAttribute && item.getAttribute("data-layer-opacity");
      if (name) rows[name] = item;
    });
    function syncSliderStates() {
      Object.keys(rows).forEach(function (name) {
        updateSliderRowState(rows[name], name, map, overlays, ctx);
      });
    }
    syncSliderStates();
    map.on("overlayadd", syncSliderStates);
    map.on("overlayremove", syncSliderStates);

    return {};
  }

  // Sync every toggle with the actual on-map state (after overlay events).
  // The virtual "GPS Density" row resolves to whichever raster-mode layer is
  // currently active (see resolveDensityLayer) before consulting the map.
  function syncLayerToggles(container, layerGroups, map, overlays, ctx) {
    layerGroups.forEach(function (group) {
      group.layers.forEach(function (lDef) {
        var layer = resolveDensityLayer(lDef.name, overlays, ctx);
        if (!layer) return;
        var input = container.querySelector(
          'input[data-layer-name="' + lDef.name + '"]'
        );
        if (input) {
          input.checked = map.hasLayer(layer);
        }
      });
    });
  }

  // Wire overlay add/remove events so exclusivity + manual ops stay in sync.
  function wireLayerEvents(container, layerGroups, map, overlays, advanced, ctx) {
    map.on("overlayadd", function () {
      syncLayerToggles(container, layerGroups, map, overlays, ctx);
      syncAdvancedFromMap(map, overlays, advanced);
    });
    map.on("overlayremove", function () {
      syncLayerToggles(container, layerGroups, map, overlays, ctx);
      syncAdvancedFromMap(map, overlays, advanced);
    });
  }

  /* ---- Save as PNG (static image export) -------------------------------- */

  // The renderer is fetched the first time the user actually asks for a PNG, so
  // the generated page keeps loading fast and stays usable when the CDN is
  // unreachable — the button then reports what went wrong instead of failing
  // silently. html2canvas draws the live DOM (basemap tiles, the data-URI
  // heatmap layers and the SVG track lines) to a canvas — everything that is on
  // screen except the home marker, which is left out on purpose.
  var HTML2CANVAS_URL =
    "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js";

  // The rasterized grids travel with the page as an inert
  // <script type="application/geo+json"> block (written by ControlPanel). Like
  // the GPX document below they are zlib-compressed and base64-encoded, because
  // a dense grid is tens of MB of highly repetitive text that compresses
  // roughly tenfold. The button inflates the payload in the browser before
  // handing the text to the browser as a download.
  var GEOJSON_DATA_ID = "hcp-geojson-data";
  var GEOJSON_FILENAME = "heatmap.geojson";
  var GEOJSON_MIME = "application/geo+json";

  // The raw tracks travel with the page the same way, but as the GPX document
  // itself — zlib-compressed and base64-encoded, because the file is roughly ten
  // times larger uncompressed. The button inflates it in the browser, so what
  // the user gets is byte for byte the file the build wrote to OUTPUT_GPX.
  var GPX_DATA_ID = "hcp-gpx-data";
  var GPX_FILENAME = "tracks.gpx";
  var GPX_MIME = "application/gpx+xml";

  // Render at 2x so the exported picture stays sharp on high-density screens.
  var EXPORT_SCALE = 2;
  var EXPORT_FILENAME = "heatmap.png";
  // Where the legend card sits inside the exported image. Mirrors the panel
  // CSS (bottom: 28px / right: 10px) so the PNG matches what was on screen.
  var EXPORT_LEGEND_RIGHT_PX = 10;
  var EXPORT_LEGEND_BOTTOM_PX = 28;
  // Class ScalableHomeMarker puts on the home marker's SVG path. It is left out
  // of the export: the marker points at a personal location, and as a lone dot
  // in a still image it reads as an artefact rather than as information.
  var EXPORT_EXCLUDED_CLASS = "hcp-home-marker";
  // Class put on the map container while a PNG is being built. The panel CSS
  // uses it to neutralise the Leaflet zoom buttons (pointer-events only, so the
  // exported picture is unaffected).
  var EXPORTING_CLASS = "hcp-exporting";
  // How long to wait for the map to stop moving before giving up and rendering
  // what is on screen anyway, and how often to re-check while waiting.
  var EXPORT_SETTLE_TIMEOUT_MS = 5000;
  var EXPORT_SETTLE_POLL_MS = 100;
  // Leaflet interaction handlers switched off for the duration of the render, so
  // a stray drag or wheel tick cannot move the map mid-capture.
  var EXPORT_INTERACTION_HANDLERS = [
    "dragging",
    "touchZoom",
    "doubleClickZoom",
    "scrollWheelZoom",
    "boxZoom",
    "keyboard",
  ];

  var html2canvasPromise = null;

  function loadHtml2Canvas() {
    if (global.html2canvas) return Promise.resolve(global.html2canvas);
    if (html2canvasPromise) return html2canvasPromise;
    html2canvasPromise = new Promise(function (resolve, reject) {
      if (!document || !document.head || typeof document.createElement !== "function") {
        reject(new Error("This page cannot load the image library."));
        return;
      }
      var script = document.createElement("script");
      script.src = HTML2CANVAS_URL;
      script.async = true;
      script.onload = function () {
        if (global.html2canvas) resolve(global.html2canvas);
        else reject(new Error("The image library failed to start."));
      };
      script.onerror = function () {
        // Clear the cached attempt so a later click retries the download.
        html2canvasPromise = null;
        reject(new Error("Could not download the image library. Check your connection."));
      };
      document.head.appendChild(script);
    });
    return html2canvasPromise;
  }

  // Render a DOM element to a canvas. Cross-origin basemap tiles are requested
  // with CORS (the tile layers also set crossOrigin, so this is usually a cache
  // hit) because a canvas holding a non-CORS image cannot be turned into a
  // downloadable picture.
  function renderToCanvas(element, html2canvas) {
    return html2canvas(element, {
      useCORS: true,
      backgroundColor: null,
      logging: false,
      scale: EXPORT_SCALE,
      // Drop the home marker from the picture (see EXPORT_EXCLUDED_CLASS).
      ignoreElements: function (node) {
        return Boolean(node && node.classList && node.classList.contains(EXPORT_EXCLUDED_CLASS));
      },
    });
  }

  // The legend is a fixed-position sibling of the map rather than part of it, so
  // it is missing from the map's own render; draw it into the bottom-right
  // corner (its on-screen spot) instead. A legend the user has hidden via the
  // Legend button is skipped, so the PNG matches the screen.
  function addLegendToCanvas(canvas, html2canvas, legendId) {
    var legend = legendId ? document.getElementById(legendId) : null;
    if (!legend || legend.style.display === "none") return Promise.resolve();
    return renderToCanvas(legend, html2canvas).then(function (legendCanvas) {
      var context = canvas.getContext("2d");
      if (!context) return;
      var right = EXPORT_LEGEND_RIGHT_PX * EXPORT_SCALE;
      var bottom = EXPORT_LEGEND_BOTTOM_PX * EXPORT_SCALE;
      context.drawImage(
        legendCanvas,
        Math.max(right, canvas.width - legendCanvas.width - right),
        Math.max(bottom, canvas.height - legendCanvas.height - bottom)
      );
    });
  }

  // Hand a URL (a blob: URL or a data: URI) to the browser as a file download.
  // Shared by the PNG and GeoJSON exports.
  function triggerDownloadFile(href, filename) {
    var link = document.createElement("a");
    link.href = href;
    link.download = filename;
    document.body.appendChild(link);
    if (typeof link.click === "function") link.click();
    document.body.removeChild(link);
  }

  // Hand a finished canvas to the browser as a file download. toBlob keeps
  // memory use sane for the large canvases the map produces; the data-URL path
  // is a fallback for browsers without it.
  function saveCanvasAsPng(canvas, filename) {
    if (
      typeof canvas.toBlob === "function" &&
      typeof URL !== "undefined" &&
      typeof URL.createObjectURL === "function"
    ) {
      canvas.toBlob(function (blob) {
        if (!blob) return;
        var url = URL.createObjectURL(blob);
        triggerDownloadFile(url, filename);
        setTimeout(function () {
          URL.revokeObjectURL(url);
        }, 1000);
      }, "image/png");
      return;
    }
    triggerDownloadFile(canvas.toDataURL("image/png"), filename);
  }

  /* ---- Export GeoJSON (rasterized grids) -------------------------------- */

  // Download the embedded rasterized grids as a GeoJSON file. The grids are
  // stored compressed in the page (never parsed by the browser at load), so this
  // inflates the payload and wraps the resulting text in a Blob. Resolves once
  // the file has been handed to the browser; rejects with a readable Error when
  // the page carries no grid data (the button then reports that instead of
  // failing silently).
  function exportGeojsonData() {
    var el = document.getElementById(GEOJSON_DATA_ID);
    var payload = el && el.textContent ? el.textContent.replace(/\s+/g, "") : "";
    if (!payload) throw new Error("No grid data is available to export.");

    return inflateZlib(decodeBase64Bytes(payload)).then(function (text) {
      if (
        typeof Blob === "undefined" ||
        typeof URL === "undefined" ||
        typeof URL.createObjectURL !== "function"
      ) {
        // Fallback for browsers without Blob/object URLs: a (large) data URI.
        triggerDownloadFile(
          "data:" + GEOJSON_MIME + ";charset=utf-8," + encodeURIComponent(text),
          GEOJSON_FILENAME
        );
        return;
      }

      var url = URL.createObjectURL(new Blob([text], { type: GEOJSON_MIME }));
      triggerDownloadFile(url, GEOJSON_FILENAME);
      setTimeout(function () {
        URL.revokeObjectURL(url);
      }, 1000);
    });
  }

  /* ---- Export GPX (raw tracks) ------------------------------------------ */

  // Decode a base64 payload to bytes. atob is used rather than fetching a data:
  // URL because this has to work just as well from a file:// page.
  function decodeBase64Bytes(payload) {
    if (typeof atob !== "function") {
      throw new Error("This browser cannot unpack the embedded file.");
    }
    var binary = atob(payload);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  }

  // Inflate zlib-wrapped bytes back to text. "deflate" in DecompressionStream is
  // the RFC 1950 format Python's zlib.compress writes; the decompressor is part
  // of the browser, so nothing is fetched.
  function inflateZlib(bytes) {
    if (typeof DecompressionStream === "undefined" || typeof Response === "undefined") {
      return Promise.reject(
        new Error("This browser cannot unpack the embedded file. Try a newer browser.")
      );
    }
    var stream = new Response(bytes).body.pipeThrough(new DecompressionStream("deflate"));
    return new Response(stream).text();
  }

  // Download the embedded tracks as GPX. Resolves once the file has been handed
  // to the browser; rejects with a readable Error when the page carries no track
  // data (the button then reports that instead of failing silently).
  function exportGpxTracks(filename) {
    var el = document.getElementById(GPX_DATA_ID);
    var payload = el && el.textContent ? el.textContent.replace(/\s+/g, "") : "";
    if (!payload) throw new Error("No track data is available to export.");

    return inflateZlib(decodeBase64Bytes(payload)).then(function (text) {
      if (
        typeof Blob === "undefined" ||
        typeof URL === "undefined" ||
        typeof URL.createObjectURL !== "function"
      ) {
        // Fallback for browsers without Blob/object URLs: a (large) data URI.
        triggerDownloadFile(
          "data:" + GPX_MIME + ";charset=utf-8," + encodeURIComponent(text),
          filename
        );
        return;
      }
      var url = URL.createObjectURL(new Blob([text], { type: GPX_MIME }));
      triggerDownloadFile(url, filename);
      setTimeout(function () {
        URL.revokeObjectURL(url);
      }, 1000);
    });
  }

  // Is the map mid-movement? Leaflet keeps no single "am I moving?" flag, so
  // combine the animation internals it does expose (the same way isBasemapLayer
  // reads layer._url) — an animated zoom, an inertia pan / fly-to, or a queued
  // fly-to frame. Tiles that shuffle during the capture smear the exported
  // picture, so nothing may be in flight when we render.
  function mapIsMoving(map) {
    if (map._animatingZoom) return true;
    if (map._panAnim && map._panAnim._inProgress) return true;
    if (map._flyToFrame) return true;
    return false;
  }

  // Call back once the map has stopped moving. Polling (rather than listening
  // for moveend/zoomend) also covers an interrupted or re-started animation
  // that reports no end event; the timeout guarantees we never hang the button.
  function whenMapSettled(map, callback) {
    var deadline = Date.now() + EXPORT_SETTLE_TIMEOUT_MS;
    function check() {
      if (!mapIsMoving(map) || Date.now() > deadline) {
        callback();
        return;
      }
      setTimeout(check, EXPORT_SETTLE_POLL_MS);
    }
    check();
  }

  // Switch off the interactions that can move the map, remembering which ones
  // were actually on so only those are switched back on afterwards.
  function freezeMapInteractions(map) {
    var frozen = [];
    EXPORT_INTERACTION_HANDLERS.forEach(function (name) {
      var handler = map[name];
      if (handler && typeof handler.disable === "function" && handler.enabled()) {
        handler.disable();
        frozen.push(handler);
      }
    });
    return frozen;
  }

  function thawMapInteractions(frozen) {
    frozen.forEach(function (handler) {
      handler.enable();
    });
  }

  // Export the current map view (plus the legend) as a PNG download. The map is
  // let settle and then held still for the duration of the render, so the image
  // always shows a single, stable view. Rejects with a human-readable Error when
  // anything goes wrong, so the caller can report it next to the button.
  //
  // ``onBuilding`` (optional) fires once the map has settled and the render is
  // about to start, which is when waiting is over and work actually begins.
  function exportMapPng(map, legendId, onBuilding) {
    var container = map && typeof map.getContainer === "function" ? map.getContainer() : null;
    if (!container) return Promise.reject(new Error("The map is not ready yet."));
    // Cancel any glide (inertia pan / fly-to) rather than waiting it out.
    if (typeof map.stop === "function") map.stop();
    var frozen = freezeMapInteractions(map);
    if (container.classList) container.classList.add(EXPORTING_CLASS);

    function release() {
      if (container.classList) container.classList.remove(EXPORTING_CLASS);
      thawMapInteractions(frozen);
    }

    return new Promise(function (resolve) {
      whenMapSettled(map, resolve);
    })
      .then(function () {
        if (onBuilding) onBuilding();
        return loadHtml2Canvas();
      })
      .then(function (html2canvas) {
        return renderToCanvas(container, html2canvas).then(function (canvas) {
          return addLegendToCanvas(canvas, html2canvas, legendId).then(function () {
            return canvas;
          });
        });
      })
      .then(
        function (canvas) {
          saveCanvasAsPng(canvas, EXPORT_FILENAME);
          release();
        },
        function (error) {
          release();
          throw error;
        }
      );
  }

  /* ---- Init ------------------------------------------------------------- */

  function init(config) {
    var panel = document.getElementById(config.panelId);
    if (!panel || !config.map) return;
    var map = config.map;

    // Hover / focus explanations for every control that carries help text.
    installHelpTooltips(panel);

    // Shared render context: resolves the virtual "GPS Density" row to the
    // raster-mode layer selected in the Advanced dropdown, and tracks the
    // opacity-slider listeners so re-renders can unregister them.
    var ctx = {
      advanced: config.advanced || null,
      densityLayerNames:
        config.advanced && config.advanced.densityLayerNames
          ? config.advanced.densityLayerNames
          : null,
      densityGroupLabel: "Heatmap",
      opacityHandlers: [],
    };

    /* --- Basemap style segments ------------------------------------------ */
    var currentKey = currentBasemapStyle(map) || config.activeBasemap;
    var cached = {};
    var segmentBox = panel.querySelector("#hcp-basemap");

    function selectStyle(key) {
      if (key === currentKey) return;
      var layer = cached[key];
      if (!layer) {
        layer = makeTileLayer(key, config.apiKey);
        cached[key] = layer;
      }
      removeBasemapLayers(map, layer);
      layer.addTo(map);
      currentKey = key;
      updateSegmentStates(segmentBox, key);
    }

    if (segmentBox && config.basemapStyles) {
      config.basemapStyles.forEach(function (option) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "hcp-segment";
        btn.setAttribute("data-style", option.key);
        // Each style gets its own explanation; the "Basemap" label carries the
        // visible info badge, so the buttons themselves stay uncluttered.
        btn.setAttribute("data-hcp-help", BASEMAP_HELP[option.key] || BASEMAP_HELP_FALLBACK);
        btn.textContent = option.label;
        if (option.key === currentKey) {
          btn.classList.add("hcp-segment-active");
        }
        btn.addEventListener("click", function () {
          selectStyle(option.key);
        });
        segmentBox.appendChild(btn);
      });
    }

    /* --- Layer toggles ------------------------------------------------- */
    var layersContainer = panel.querySelector("#hcp-layers");
    var layerOverlays = null;
    var defaultOpacity =
      typeof config.opacity === "number" ? config.opacity : 0.85;
    var opacityListEl = panel.querySelector("#hcp-opacity-list");

    // (Re)render the collapsible opacity sliders for the current overlay state.
    function renderOpacityList() {
      if (!opacityListEl) return;
      buildOpacityList(
        opacityListEl,
        config.layerGroups,
        map,
        layerOverlays,
        config,
        defaultOpacity,
        ctx
      );
    }

    function setupLayerToggles() {
      layerOverlays = findOverlays();
      if (!layerOverlays) return false;
      buildLayerList(layersContainer, config.layerGroups, map, layerOverlays, config, ctx);
      renderOpacityList();
      wireLayerEvents(layersContainer, config.layerGroups, map, layerOverlays, config.advanced, ctx);
      return true;
    }

    if (layersContainer && config.layerGroups && config.layerGroups.length) {
      if (!setupLayerToggles()) {
        var attempts = 0;
        (function retryLayers() {
          if (setupLayerToggles()) return;
          if (++attempts > 30) return;
          setTimeout(retryLayers, 100);
        })();
      }
    }

    /* --- Home marker toggle --------------------------------------------- */
    // The home marker is on by default. Expose a checkbox so it can be hidden or
    // re-shown without regenerating the map. The section is `hidden` in the static
    // markup and only revealed when a home location was provided (config.home is
    // set and a marker was rendered).
    var homeMarkerBtn = panel.querySelector("#hcp-home-marker");
    var homeSection = panel.querySelector("#hcp-home-section");
    if (config.hasHomeMarker && homeMarkerBtn && homeSection) {
      homeSection.hidden = false;
      var homeMarker = findHomeMarker(map);
      homeMarkerBtn.checked = homeMarker ? map.hasLayer(homeMarker) : true;
      homeMarkerBtn.addEventListener("change", function () {
        if (!homeMarker) return;
        if (homeMarkerBtn.checked && !map.hasLayer(homeMarker)) {
          homeMarker.addTo(map);
        } else if (!homeMarkerBtn.checked && map.hasLayer(homeMarker)) {
          map.removeLayer(homeMarker);
        }
      });
    } else if (homeSection) {
      homeSection.hidden = true;
    }

    /* --- Layer opacity sliders (collapsible) --------------------------- */
    // Per-layer opacity sliders live in their own section (#hcp-opacity-list),
    // right under the toggle groups. The "Layer opacity" header button collapses
    // / expands the whole list to keep the panel compact when not in use.
    var opacityToggle = panel.querySelector("#hcp-opacity-toggle");
    if (opacityToggle) {
      var opacityCaret = opacityToggle.querySelector(".hcp-caret");
      opacityToggle.addEventListener("click", function () {
        var collapsed = panel.classList.toggle("hcp-opacity-collapsed");
        opacityToggle.setAttribute("aria-expanded", String(!collapsed));
        if (opacityCaret) {
          opacityCaret.textContent = collapsed ? "\u25B8" : "\u25BE";
        }
      });
    }

    /* --- Advanced section (rasterization-mode dropdown) ------------------ */
    // Collapsible section (same pattern as "Layer opacity") holding the
    // dropdown that picks the rasterization mode. Every mode maps to an overlay
    // layer pre-baked at build time, so switching is an instant map swap with
    // no re-rasterization. The virtual "GPS Density" row in the Heatmap group
    // re-binds to the newly selected mode's layer.
    var advancedToggle = panel.querySelector("#hcp-advanced-toggle");
    var advancedBody = panel.querySelector("#hcp-advanced-body");
    if (advancedToggle && advancedBody) {
      var advancedCaret = advancedToggle.querySelector(".hcp-caret");
      advancedToggle.addEventListener("click", function () {
        var expanded = advancedBody.hidden ? true : false;
        advancedBody.hidden = !expanded;
        advancedToggle.setAttribute("aria-expanded", String(expanded));
        if (advancedCaret) {
          advancedCaret.textContent = expanded ? "\u25BE" : "\u25B8";
        }
      });
    }

    var modeSelect = panel.querySelector("#hcp-density-mode");
    if (modeSelect && config.advanced && config.advanced.modes) {
      config.advanced.modes.forEach(function (m) {
        var opt = document.createElement("option");
        opt.value = m.key;
        opt.textContent = m.label || m.key;
        modeSelect.appendChild(opt);
      });
      modeSelect.value = config.advanced.active;
      modeSelect.addEventListener("change", function () {
        if (!layerOverlays || !config.advanced) return;
        var key = modeSelect.value;
        var target = null;
        config.advanced.modes.forEach(function (m) {
          if (m.key === key) target = m;
        });
        if (!target || !target.layer) return;
        config.advanced.active = key;
        var targetLayer = layerOverlays[target.layer];
        if (!targetLayer) return;
        // Exclusivity: only one density layer (and never Coverage) may be on
        // the map together with the newly selected mode layer.
        (config.advanced.densityLayerNames || []).forEach(function (name) {
          if (name === target.layer) return;
          var other = layerOverlays[name];
          if (other && map.hasLayer(other)) map.removeLayer(other);
        });
        var coverageLayer = layerOverlays["Coverage (Places Visited)"];
        if (coverageLayer && map.hasLayer(coverageLayer)) map.removeLayer(coverageLayer);
        if (!map.hasLayer(targetLayer)) map.addLayer(targetLayer);
      });
    }

    /* --- Fit / reset / legend ------------------------------------------- */
    var fitBtn = panel.querySelector("#hcp-fit");
    if (fitBtn && config.bounds) {
      fitBtn.addEventListener("click", function () {
        if (map.fitBounds) map.fitBounds(config.bounds, { padding: [20, 20] });
      });
    }

    var resetBtn = panel.querySelector("#hcp-reset");
    if (resetBtn) {
      resetBtn.addEventListener("click", function () {
        // Reset returns to home (or the bounding-box centre as a fallback).
        var resetLocation = config.home || config.centre;
        if (map.setView && resetLocation) {
          map.setView(resetLocation, config.zoomStart);
        }
      });
    }

    var legendBtn = panel.querySelector("#hcp-legend");
    var legendVisible = true;
    if (legendBtn && config.legendId) {
      legendBtn.addEventListener("click", function () {
        var legend = document.getElementById(config.legendId);
        if (!legend) return;
        legendVisible = !legendVisible;
        legend.style.display = legendVisible ? "block" : "none";
      });
    }

    /* --- Save as PNG ----------------------------------------------------- */
    // Renders the current view (map + legend) to a PNG file entirely in the
    // browser. The button is disabled while the image is being built so a
    // double click cannot start two exports, and the small status line under
    // it reports progress and failures.
    var exportBtn = panel.querySelector("#hcp-export-png");
    var exportStatus = panel.querySelector("#hcp-export-status");

    function setExportStatus(message, isError) {
      if (!exportStatus) return;
      exportStatus.textContent = message || "";
      exportStatus.classList.toggle("hcp-export-status-error", Boolean(isError));
    }

    if (exportBtn) {
      exportBtn.addEventListener("click", function () {
        if (exportBtn.disabled) return;
        exportBtn.disabled = true;
        // The picture must show one still view, so a zoom or pan already in
        // flight is awaited before rendering starts (see whenMapSettled).
        setExportStatus(
          mapIsMoving(map)
            ? "Waiting for the map to stop moving\u2026"
            : "Building the image\u2026",
          false
        );
        exportMapPng(map, config.legendId, function () {
          setExportStatus("Building the image\u2026", false);
        })
          .then(function () {
            setExportStatus("Saved as " + EXPORT_FILENAME + ".", false);
          })
          .catch(function (error) {
            setExportStatus(
              error && error.message ? error.message : "The image could not be saved.",
              true
            );
          })
          .then(function () {
            exportBtn.disabled = false;
          });
      });
    }

    /* --- Export GeoJSON -------------------------------------------------- */
    // Hands the rasterized grids (embedded in the page, compressed) to the
    // browser as a .geojson download. Inflating takes a moment on a large
    // export, so the button is disabled while it works and reports the outcome
    // on the shared export status line.
    var geojsonBtn = panel.querySelector("#hcp-export-geojson");
    if (geojsonBtn) {
      geojsonBtn.addEventListener("click", function () {
        if (geojsonBtn.disabled) return;
        geojsonBtn.disabled = true;
        setExportStatus("Unpacking the GeoJSON file\u2026", false);
        Promise.resolve()
          .then(function () {
            return exportGeojsonData();
          })
          .then(function () {
            setExportStatus("Saved as " + GEOJSON_FILENAME + ".", false);
          })
          .catch(function (error) {
            setExportStatus(
              error && error.message
                ? error.message
                : "The GeoJSON file could not be saved.",
              true
            );
          })
          .then(function () {
            geojsonBtn.disabled = false;
          });
      });
    }

    /* --- Export GPX ------------------------------------------------------ */
    // Unpacking the embedded document takes a moment on a large export, so the
    // button is disabled while it works and reports the outcome on the shared
    // export status line. The filename comes from the build, so the download is
    // named after the OUTPUT_GPX file it reproduces.
    var gpxBtn = panel.querySelector("#hcp-export-gpx");
    if (gpxBtn) {
      var gpxFilename = config.gpxFilename || GPX_FILENAME;
      gpxBtn.addEventListener("click", function () {
        if (gpxBtn.disabled) return;
        gpxBtn.disabled = true;
        setExportStatus("Unpacking the GPX file\u2026", false);
        Promise.resolve()
          .then(function () {
            return exportGpxTracks(gpxFilename);
          })
          .then(function () {
            setExportStatus("Saved as " + gpxFilename + ".", false);
          })
          .catch(function (error) {
            setExportStatus(
              error && error.message ? error.message : "The GPX file could not be saved.",
              true
            );
          })
          .then(function () {
            gpxBtn.disabled = false;
          });
      });
    }

    /* --- Auto-correct overlay rendering after zoom ----------------------- */
    // ImageOverlays inside FeatureGroups can occasionally fail to reposition
    // when the map zooms while a layer is shown (the classic stale-overlay
    // bug). Redraw the visible overlays automatically on zoom end so the
    // heatmap matches the current view without any manual action.
    map.on("zoomend", function () {
      redrawVisibleOverlays(map);
    });
  }

  global.initHeatmapControlPanel = init;
})(window);
