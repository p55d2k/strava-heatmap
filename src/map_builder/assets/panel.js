/*
 * Strava Heatmap — Unified Control Panel behaviour.
 *
 * Self-contained client-side logic for the single top-right control panel
 * embedded in the generated heatmap HTML. It merges what used to be the
 * stock Leaflet layer control into one central panel:
 *
 *   - Basemap style switching  (Voyager / Light / Dark family buttons plus a
 *                               "Labels" checkbox that swaps the active family
 *                               between its labeled and nolabels tile variants)
 *   - Layer toggles            (radio for the density concepts — one virtual
 *                               "GPS Density" row plus Coverage — checkbox
 *                               for independent layers such as raw GPS tracks)
 *   - Per-layer opacity sliders (one per layer, collapsible via "Opacity";
 *                               a slider is greyed out while its layer is not
 *                               on the map)
 *   - Advanced section          (collapsible; rasterization-mode dropdown that
 *                               swaps which pre-baked GPS Density overlay is
 *                               bound to the "GPS Density" row)
 *   - Date range filter         (From/To range slider that re-rasterizes the
 *                               density / coverage layers in the browser within
 *                               the chosen span, using the per-activity cell
 *                               counts the tooltip index already carries — no
 *                               rebuild, colours stay on the legend scale)
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
 *     basemapFamilies: [{ key: "dark", label: "Dark" }, ...],
 *     familyStyles:   { dark: { labels: "dark_all", noLabels: "dark_nolabels" }, ... },
 *     activeBasemap:  "dark_all"  (the starting tile style key),
 *     showLabels:     true  (initial state of the Labels checkbox),
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
 *     dateBounds:     ["2019-01-01", "2024-12-31"]  (seeds the date filter),
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
 *   * Basemap: CARTO is the only basemap provider. The configured CARTO tile
 *     layer is already on the map; we switch styles by creating a new
 *     L.tileLayer for the target style (with the embedded API key) and removing
 *     any existing tile layers whose URL matches the CARTO domain.
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
    // CARTO is the only basemap provider, so a page without a key cannot show a
    // basemap at all. Fail loudly instead of requesting keyless tiles.
    if (!apiKey) {
      throw new Error("No CARTO API key was embedded in this page.");
    }
    var url =
      "https://basemaps.cartocdn.com/rastertiles/" + style +
      "/{z}/{x}/{y}.png?key=" + encodeURIComponent(apiKey);
    var attribution =
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
      'contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';
    return L.tileLayer(url, {
      maxZoom: 20,
      maxNativeZoom: 20,
      keepBuffer: 0,
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

  // One line per basemap family (the group itself is explained by the label).
  var BASEMAP_HELP = {
    voyager: "A colourful street map with lots of road and place names — handy for keeping your bearings.",
    light: "A plain light background. Easiest to see against in bright daylight.",
    dark: "A dark background that makes the heatmap colours stand out. Easy on the eyes at night.",
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

  // Plural nouns for the badge's units. "activity" cannot be pluralized by
  // suffixing an "s" (that reads "activitys"), so the plural forms are spelled
  // out here; an unknown unit falls back to the naive “s”.
  var UNIT_PLURALS = { activity: "activities", track: "tracks", item: "items" };

  // Build the muted badge showing how much data a layer carries (the number of
  // tracks / activities it is built from). The figure is computed at build time
  // (see src/map_builder/control.py::compute_layer_counts); layers with no count
  // in the config render no badge, so bespoke overlays stay uncluttered.
  function makeLayerCountBadge(lDef) {
    if (!lDef || typeof lDef.count !== "number") return null;
    var unit = lDef.unit || "item";
    var word = lDef.count === 1 ? unit : UNIT_PLURALS[unit] || unit + "s";
    var badge = document.createElement("span");
    badge.className = "hcp-layer-count";
    badge.textContent = lDef.count + " " + word;
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
  // screen except the home marker and the Leaflet controls, which are left out
  // on purpose (see EXPORT_EXCLUDED_CLASSES).
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
  // Classes left out of the exported picture. ScalableHomeMarker puts the class
  // it excludes on the home marker's SVG path: the marker points at a personal
  // location, and as a lone dot in a still image it reads as an artefact rather
  // than as information. The click-tolerance control no longer rides on the map
  // (it lives in the panel's Advanced section), so it sits outside the captured
  // region and needs no exclusion.
  //
  // The Leaflet chrome goes too: the zoom buttons, the scale bar and the
  // attribution line are interaction furniture for the page, and printing them
  // into a shareable picture only pins the screenshot to one UI state (and adds
  // a caption over the bottom of the map). Each of them is a single element, so
  // dropping it takes its whole subtree with it. (The stock layer control is
  // already display:none, and the control panel and legend are siblings of the
  // map rather than inside it, so they never reach the capture.)
  var EXPORT_EXCLUDED_CLASSES = [
    "hcp-home-marker",
    "leaflet-control-zoom",
    "leaflet-control-scale",
    "leaflet-control-attribution",
  ];
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
      // Drop the home marker and the Leaflet chrome from the picture (see
      // EXPORT_EXCLUDED_CLASSES).
      ignoreElements: function (node) {
        if (!node || !node.classList) return false;
        for (var i = 0; i < EXPORT_EXCLUDED_CLASSES.length; i++) {
          if (node.classList.contains(EXPORT_EXCLUDED_CLASSES[i])) return true;
        }
        return false;
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

  /* ---- Activity tooltips (click near a route) --------------------------- */

  // Clicking the map opens a popup listing the activities whose route passes
  // near the click: date, name, average pace, average heart rate and a link
  // back to Strava when the export carried an activity id. The click tolerance
  // (ACTIVITY_SEARCH_RADIUS_PX, below) is what makes this usable — a route is
  // a thin line, so a pixel-perfect hit would rarely succeed. The data is the
  // per-cell index embedded by ControlPanel (see src/activity_index.py) —
  // zlib-compressed and base64-encoded like the export payloads — and it is
  // inflated lazily on the first click, never at page load.
  var ACTIVITY_DATA_ID = "hcp-activity-data";
  // Cap how many rows a single popup renders. A well-used junction can be
  // visited by hundreds of activities; the popup then says how many more.
  var ACTIVITY_MAX_LISTED = 50;
  // The order a popup lists what it found: newest first ("recent", the default)
  // or closest to the click first ("nearest"). The choice is remembered across
  // clicks — every click builds a fresh popup — so it sticks while the visitor
  // explores.
  var ACTIVITY_SORT_RECENT = "recent";
  var ACTIVITY_SORT_NEAREST = "nearest";
  var activitySortOrder = ACTIVITY_SORT_RECENT;
  // Click tolerance, in screen pixels. A route is a thin line that rarely sits
  // under the exact pixel clicked, and the painted heatmap is blurred wider
  // than the raw data cells, so requiring a pixel-perfect hit mostly returns
  // "nothing here". Instead the click gathers every cell whose centre falls
  // within this many pixels, which also picks up the far side of a road.
  // Defining it in screen pixels (rather than cells or metres) keeps the
  // gesture feeling the same at every zoom level.
  var ACTIVITY_SEARCH_RADIUS_PX = 14;
  // Bounds for the live tolerance slider (see buildActivityControl). Below the
  // minimum a click would have to be pixel-perfect to find anything; above the
  // maximum the search stops meaning "near here" and starts scanning a large
  // square of the grid on every click.
  var ACTIVITY_RADIUS_MIN_PX = 4;
  var ACTIVITY_RADIUS_MAX_PX = 40;
  // Used only when the map cannot report its zoom (a minimal shim): a modest
  // fixed number of cells keeps the search useful without a huge scan.
  var ACTIVITY_SEARCH_RADIUS_CELLS_FALLBACK = 6;
  // Hard ceiling on the search radius in cells, so a world-zoom view cannot
  // ask for a scan of millions of cells. 40 cells is a generous click area at
  // any realistic map zoom.
  var ACTIVITY_MAX_SEARCH_RADIUS_CELLS = 40;

  // Web Mercator (EPSG:3857) helpers. The index is keyed on the same raster grid
  // the heatmap is painted from, whose geometry is stored in metres in that
  // projection, while Leaflet hands us WGS84 lat/lng — so a click has to be
  // converted before it can be looked up. The formulas mirror Leaflet's own
  // spherical Mercator (and pyproj's EPSG:3857).
  var EARTH_HALF_CIRCUMFERENCE = 20037508.342789244;

  function lonToMercator(lon) {
    return (lon * EARTH_HALF_CIRCUMFERENCE) / 180;
  }

  function latToMercator(lat) {
    var clamped = Math.max(-89.999999, Math.min(89.999999, lat));
    var y = Math.log(Math.tan(((90 + clamped) * Math.PI) / 360)) / (Math.PI / 180);
    return (y * EARTH_HALF_CIRCUMFERENCE) / 180;
  }

  function mercatorToLon(x) {
    return (x * 180) / EARTH_HALF_CIRCUMFERENCE;
  }

  function mercatorToLat(y) {
    var rad = 2 * Math.atan(Math.exp((y * Math.PI) / EARTH_HALF_CIRCUMFERENCE)) - Math.PI / 2;
    return (rad * 180) / Math.PI;
  }

  // How many grid cells make up the click tolerance at the current zoom. The
  // tolerance is defined in screen pixels, so it is converted through the map's
  // own Web Mercator scale (the EPSG:3857 world is 2 * EARTH_HALF_CIRCUMFERENCE
  // metres across 256 * 2^zoom pixels) and clamped so a zoomed-out view cannot
  // ask for an enormous scan.
  function activitySearchRadiusCells(map, index) {
    if (!index || !index.cellSize) return ACTIVITY_SEARCH_RADIUS_CELLS_FALLBACK;
    var zoom = map && typeof map.getZoom === "function" ? map.getZoom() : null;
    if (zoom === null || !isFinite(zoom)) return ACTIVITY_SEARCH_RADIUS_CELLS_FALLBACK;
    var metresPerPixel = (2 * EARTH_HALF_CIRCUMFERENCE) / (256 * Math.pow(2, zoom));
    var cells = (ACTIVITY_SEARCH_RADIUS_PX * metresPerPixel) / index.cellSize;
    return Math.max(1, Math.min(ACTIVITY_MAX_SEARCH_RADIUS_CELLS, Math.round(cells)));
  }

  // Every activity whose route passes within the click tolerance, nearest
  // first, each as ``{ id, distance }`` with ``distance`` in ground metres so
  // the popup can say how far the route is (which is how you tell routes apart
  // when a click catches more than one — a junction, or both sides of a road).
  //
  // The exact clicked cell follows the rasterizer's "nearest cell" convention
  // (round to the closest bin centre); cells are then walked in a square around
  // it and an activity seen in several cells keeps its smallest distance, so a
  // route is listed once, at its closest approach to the click.
  //
  // Returns ``null`` for a click that is off the data entirely (outside the
  // grid with nothing nearby), and the possibly-empty list otherwise.
  function activitiesNear(index, latlng, map) {
    if (!index || !index.cells || !latlng) return null;
    var col = Math.round((lonToMercator(latlng.lng) - index.xMin) / index.cellSize);
    var row = Math.round((index.yMax - latToMercator(latlng.lat)) / index.cellSize);
    var inside = col >= 0 && col < index.cols && row >= 0 && row < index.rows;
    var radius = activitySearchRadiusCells(map, index);

    // Nearest squared cell distance seen so far, per activity id.
    var nearest = {};
    var ids = [];
    for (var dr = -radius; dr <= radius; dr++) {
      var r = row + dr;
      if (r < 0 || r >= index.rows) continue;
      for (var dc = -radius; dc <= radius; dc++) {
        var c = col + dc;
        if (c < 0 || c >= index.cols) continue;
        var members = index.cells[String(r * index.cols + c)];
        if (!members) continue;
        var distance = dr * dr + dc * dc;
        for (var i = 0; i < members.length; i++) {
          var id = members[i];
          if (nearest[id] === undefined) {
            nearest[id] = distance;
            ids.push(id);
          } else if (distance < nearest[id]) {
            nearest[id] = distance;
          }
        }
      }
    }
    if (!ids.length && !inside) return null;

    // Cell distances are Web Mercator metres (the projection is conformal, so
    // one of those corresponds to cos(latitude) ground metres).
    var latRadians = (Math.max(-89.999999, Math.min(89.999999, latlng.lat)) * Math.PI) / 180;
    var groundMetresPerCell = index.cellSize * Math.cos(latRadians);
    var results = ids.map(function (id) {
      return { id: id, distance: Math.sqrt(nearest[id]) * groundMetresPerCell };
    });
    results.sort(function (a, b) {
      return a.distance - b.distance || a.id - b.id;
    });
    return results;
  }

  // A short, readable distance from the click to the route.
  function formatDistance(metres) {
    if (typeof metres !== "number" || !isFinite(metres)) return "";
    if (metres < 1000) return Math.round(metres) + " m";
    return (metres / 1000).toFixed(1) + " km";
  }

  var activityIndexPromise = null;

  // Inflate the embedded index once, on demand. A page with no index (an older
  // build, or a hand-made page) resolves to null and the click is ignored.
  function loadActivityIndex() {
    if (activityIndexPromise) return activityIndexPromise;
    var el = document.getElementById(ACTIVITY_DATA_ID);
    var payload = el && el.textContent ? el.textContent.replace(/\s+/g, "") : "";
    if (!payload) {
      activityIndexPromise = Promise.resolve(null);
      return activityIndexPromise;
    }
    activityIndexPromise = inflateZlib(decodeBase64Bytes(payload)).then(function (text) {
      return JSON.parse(text);
    });
    return activityIndexPromise;
  }

  // One muted metadata line: whatever of date / type / pace / heart rate is
  // known. The type is what the filter chips act on, so it is worth showing.
  function activityMetaLine(activity) {
    var parts = [];
    if (activity[0]) parts.push(activity[0]);
    if (activity[5]) parts.push(activity[5]);
    if (activity[2]) parts.push(activity[2]);
    if (typeof activity[3] === "number") parts.push(activity[3] + " bpm");
    return parts.join(" \u00b7 ");
  }

  // Build one row of the list, as DOM nodes rather than an HTML string:
  // activity names come from the export and must never be treated as markup.
  function buildActivityRow(activity, distanceMetres) {
    var item = document.createElement("li");
    item.className = "hcp-activity";

    // The activity name is the row's link back to Strava when the export
    // carries an activity id: the name doubling as the link removes the need
    // for a separate "View on Strava" button, while the row as a whole still
    // previews the route on hover (see wrapActivityHover).
    var name;
    if (activity[4]) {
      name = document.createElement("a");
      name.className = "hcp-activity-name";
      name.href = activity[4];
      name.target = "_blank";
      name.rel = "noopener noreferrer";
      name.title = "Open this activity on Strava.";
    } else {
      name = document.createElement("div");
      name.className = "hcp-activity-name";
    }
    name.textContent = activity[1] || "Activity";

    // Name on the left, how far the route is on the right.
    var head = document.createElement("div");
    head.className = "hcp-activity-head";
    head.appendChild(name);

    var distance = document.createElement("span");
    distance.className = "hcp-activity-distance";
    distance.textContent = formatDistance(distanceMetres);
    head.appendChild(distance);
    item.appendChild(head);

    var meta = document.createElement("div");
    meta.className = "hcp-activity-meta";
    meta.textContent = activityMetaLine(activity);
    item.appendChild(meta);

    return item;
  }

  // The distinct activity types (and dates) among a result set, in nearest-first
  // order. A filter is only offered when it would actually do something, so a
  // popup listing one type and one date stays uncluttered.
  function distinctActivityValues(results, activities) {
    var types = [];
    var dates = [];
    results.forEach(function (result) {
      var activity = activities[result.id];
      if (!activity) return;
      var type = activity[5] || "";
      if (types.indexOf(type) === -1) types.push(type);
      var date = activity[0] || "";
      if (date && dates.indexOf(date) === -1) dates.push(date);
    });
    return { types: types, dates: dates };
  }

  // Build the popup body. ``results`` is the output of activitiesNear (nearest
  // first); the list is re-sorted into the order the visitor picked with the
  // popup's own Sort segment (newest-first by default — see byRecency /
  // byNearest). Every row carries the distance from the click so several routes
  // in one popup stay tellable apart. When the result set spans more than one
  // activity type, or more than one date, a compact filter bar is added so the
  // list can be narrowed without moving the map.
  function buildActivityPopup(index, results) {
    var activities = index.activities || [];
    var root = document.createElement("div");
    root.className = "hcp-activities";

    var title = document.createElement("div");
    title.className = "hcp-activities-title";
    root.appendChild(title);

    // The order choice only means anything with more than one activity to order.
    if (results.length > 1) {
      root.appendChild(buildSortToggle());
    }

    var list = document.createElement("ul");
    list.className = "hcp-activities-list";

    var notice = document.createElement("div");
    notice.className = "hcp-activities-more";

    // Filter state. No type selected and no date bounds means "everything".
    // The date bounds seed from the panel's date-range slider, so a click
    // while a range is active already lists only the activities in range; the
    // popup's own From/To inputs can then narrow further. The slider pushes
    // fresh bounds in (datePopupApply) so the open popup follows later moves.
    var selectedType = null;
    var dateFrom = dateFilterBounds.from;
    var dateTo = dateFilterBounds.to;
    var dateFromInput = null;
    var dateToInput = null;

    function filtersActive() {
      return selectedType !== null || Boolean(dateFrom) || Boolean(dateTo);
    }

    function matches(activity) {
      if (!activity) return false;
      if (selectedType !== null && (activity[5] || "") !== selectedType) return false;
      // ISO dates compare correctly as plain strings.
      var date = activity[0] || "";
      if (dateFrom && date < dateFrom) return false;
      if (dateTo && date > dateTo) return false;
      return true;
    }

    // The two orders the list can be shown in. Both fall back to the activity
    // id so the sequence is total rather than relying on the sort being stable.
    //
    // Nearest first: the route closest to the click heads the list. This is the
    // order ``activitiesNear`` already returns, so it matches the distance
    // figures each row carries.
    function byNearest(a, b) {
      return a.distance - b.distance || a.id - b.id;
    }

    // Recency first: the newest activity heads the list. The dates are ISO
    // strings (yyyy-mm-dd), so a plain string compare is already chronological.
    // Activities sharing a date keep their nearest-first order, and a row with
    // no date — a hand-made track label the loader could not parse — sinks below
    // the dated ones rather than crowding them out.
    function byRecency(a, b) {
      var dateA = (activities[a.id] && activities[a.id][0]) || "";
      var dateB = (activities[b.id] && activities[b.id][0]) || "";
      if (dateA !== dateB) {
        if (!dateA) return 1;
        if (!dateB) return -1;
        return dateA < dateB ? 1 : -1;
      }
      return byNearest(a, b);
    }

    // The two-way "Sort" segment. Only built for a click that found more than
    // one activity, so a single-activity popup stays uncluttered. Switching
    // re-sorts the open popup in place, and the choice is remembered for the
    // next one (see activitySortOrder).
    function buildSortToggle() {
      var box = document.createElement("div");
      box.className = "hcp-sort";

      var label = document.createElement("span");
      label.className = "hcp-sort-label";
      label.textContent = "Sort";
      box.appendChild(label);

      var buttons = [];
      [
        {
          value: ACTIVITY_SORT_RECENT,
          label: "Newest",
          title: "List the most recent activity first.",
        },
        {
          value: ACTIVITY_SORT_NEAREST,
          label: "Nearest",
          title: "List the route closest to the click first.",
        },
      ].forEach(function (option) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "hcp-sort-option";
        // Active state is managed through classList (like the basemap segments)
        // so the buttons stay consistent with the click handler below.
        if (activitySortOrder === option.value) {
          btn.classList.add("hcp-sort-option-active");
        }
        btn.setAttribute("data-sort", option.value);
        btn.title = option.title;
        btn.textContent = option.label;
        btn.addEventListener("click", function () {
          activitySortOrder = option.value;
          buttons.forEach(function (other) {
            other.classList.toggle("hcp-sort-option-active", other === btn);
          });
          render();
        });
        buttons.push(btn);
        box.appendChild(btn);
      });
      return box;
    }

    // Rebuild the rows for the current filters. The controls below mutate the
    // state and call this again, so the open popup updates in place.
    function render() {
      var matching = results.filter(function (result) {
        return matches(activities[result.id]);
      });
      matching.sort(
        activitySortOrder === ACTIVITY_SORT_NEAREST ? byNearest : byRecency
      );

      title.textContent = filtersActive()
        ? matching.length + " of " + results.length + " activities shown"
        : results.length === 1
          ? "1 activity near here"
          : results.length + " activities near here";

      list.innerHTML = "";
      clearActivityFootprint(activityMap);
      var shown = Math.min(matching.length, ACTIVITY_MAX_LISTED);
      for (var i = 0; i < shown; i++) {
        var row = buildActivityRow(activities[matching[i].id], matching[i].distance);
        // Hover (and keyboard focus) previews the activity's route on the map;
        // leaving the row takes the preview off again.
        row.addEventListener("mouseenter", function (id) {
          return function () {
            showActivityFootprint(activityMap, index, id);
          };
        }(matching[i].id));
        row.addEventListener("mouseleave", function () {
          clearActivityFootprint(activityMap);
        });
        list.appendChild(row);
      }

      if (matching.length > shown) {
        notice.textContent = "+" + (matching.length - shown) + " more";
      } else if (matching.length === 0) {
        notice.textContent = "No activities match these filters.";
      } else {
        notice.textContent = "";
      }
    }

    var present = distinctActivityValues(results, activities);

    // Type chips: one per distinct type, plus "All". Only worth showing when
    // there is actually a choice to make.
    if (present.types.length > 1) {
      var filters = document.createElement("div");
      filters.className = "hcp-activities-filters";

      var typeBox = document.createElement("div");
      typeBox.className = "hcp-filter-types";
      var chips = [];
      var chipDefs = [{ label: "All", value: null }];
      present.types.forEach(function (type) {
        chipDefs.push({ label: type || "Other", value: type });
      });
      chipDefs.forEach(function (def) {
        var chip = document.createElement("button");
        chip.type = "button";
        chip.className =
          "hcp-filter-chip" + (def.value === null ? " hcp-filter-chip-active" : "");
        chip.textContent = def.label;
        chip.addEventListener("click", function () {
          selectedType = def.value;
          chips.forEach(function (other) {
            other.classList.toggle("hcp-filter-chip-active", other === chip);
          });
          render();
        });
        chips.push(chip);
        typeBox.appendChild(chip);
      });
      filters.appendChild(typeBox);

      // Date bounds: a from/to pair, again only when the dates differ.
      if (present.dates.length > 1) {
        var dateBox = document.createElement("div");
        dateBox.className = "hcp-filter-dates";
        var addDateBound = function (bound, labelText) {
          var label = document.createElement("label");
          label.className = "hcp-filter-date";
          label.textContent = labelText;
          var input = document.createElement("input");
          input.type = "date";
          input.className = "hcp-filter-date-input";
          input.setAttribute("data-bound", bound);
          // Show the bounds the popup opened with (the slider's current range)
          // so the narrow-in-narrow-out controls read honestly.
          input.value = (bound === "from" ? dateFrom : dateTo) || "";
          input.addEventListener("change", function () {
            if (bound === "from") dateFrom = input.value || "";
            else dateTo = input.value || "";
            render();
          });
          label.appendChild(input);
          dateBox.appendChild(label);
          if (bound === "from") dateFromInput = input;
          else dateToInput = input;
        };
        addDateBound("from", "From ");
        addDateBound("to", "To ");
        filters.appendChild(dateBox);
      }

      root.appendChild(filters);
    }

    // The slider's latest range is the master filter: while this popup is open
    // it is pushed in here (see refresh), widening or narrowing in place. The
    // From/To inputs follow so what the list shows stays legible.
    function applyDateBounds(from, to) {
      dateFrom = from || "";
      dateTo = to || "";
      if (dateFromInput) dateFromInput.value = dateFrom;
      if (dateToInput) dateToInput.value = dateTo;
      render();
    }
    datePopupApply = applyDateBounds;

    root.appendChild(list);
    root.appendChild(notice);
    render();
    return root;
  }

  function buildEmptyActivityPopup() {
    var root = document.createElement("div");
    root.className = "hcp-activities hcp-activities-empty";
    root.textContent = "No activities recorded near here.";
    return root;
  }

  // Open a popup at the click. Leaflet's own ``map.openPopup`` is preferred;
  // the explicit L.popup path covers a map shim that only exposes the factory.
  function openActivityPopup(map, latlng, node) {
    var options = { className: "hcp-activity-popup", maxWidth: 340, autoPan: true };
    if (map && typeof map.openPopup === "function") {
      map.openPopup(node, latlng, options);
      return;
    }
    if (global.L && typeof global.L.popup === "function") {
      global.L.popup(options).setLatLng(latlng).setContent(node).openOn(map);
    }
  }

  // Ring the click at exactly the search tolerance, so it is visible why the
  // listed activities count as "near here" (the click is not pixel-perfect and
  // may sit beside the route it found). Only the most recent ring is kept.
  var activityHighlight = null;

  function highlightSearchArea(map, latlng) {
    if (!map || !global.L || typeof global.L.circleMarker !== "function") return;
    if (activityHighlight && typeof map.removeLayer === "function") {
      map.removeLayer(activityHighlight);
    }
    activityHighlight = global.L.circleMarker(latlng, {
      radius: ACTIVITY_SEARCH_RADIUS_PX,
      color: "#fc4c02",
      weight: 1,
      opacity: 0.9,
      fillColor: "#fc4c02",
      fillOpacity: 0.12,
      interactive: false,
    });
    if (typeof activityHighlight.addTo === "function") activityHighlight.addTo(map);
  }

  // The ring marks the popup's search area, so once the popup is closed (its x
  // button, a dismissal click elsewhere on the map, Escape) the ring has no
  // meaning left and is taken off the map.
  function clearActivityHighlight(map) {
    if (!activityHighlight) return;
    if (map && typeof map.removeLayer === "function") {
      map.removeLayer(activityHighlight);
    }
    activityHighlight = null;
  }

  // Hovering a popup row previews that activity's route on the map. The index
  // carries no track geometry — the whole point of rasterizing is to avoid
  // shipping every track to the browser — but it does carry which grid cells
  // every activity visited (the same cells the heatmap paints), so the preview
  // re-paints exactly that footprint: every cell the activity passed through.
  // That is the route as the map actually shows it, lit up with no extra page
  // weight. Rows are re-created whenever the popup re-renders, so each carries
  // fresh listeners; a re-render also clears any preview left over from the row
  // it replaced.
  var activityMap = null;
  var activityFootprint = null;

  // The opacity the non-hovered heatmap is dropped to while a row is hovered:
  // only the heatmap overlays are dimmed, so the basemap and home marker stay
  // at full brightness behind the lit route. The per-layer opacity sliders are
  // left alone — dimming reads each overlay's current opacity first and puts it
  // back when the pointer leaves.
  var ACTIVITY_HEATMAP_DIM_OPACITY = 0.15;

  // The heatmap overlay leaves being dimmed during a hover, each with the
  // opacity to restore (see setActivityHeatmapDim).
  var dimmedSubLayers = null;

  function currentSubOpacity(sub) {
    if (sub && sub.options && typeof sub.options.opacity === "number") {
      return sub.options.opacity;
    }
    if (sub && sub.options && typeof sub.options.fillOpacity === "number") {
      return sub.options.fillOpacity;
    }
    return 1;
  }

  function setActivityHeatmapDim(map, dim) {
    var overlays = findOverlays();
    if (!overlays) return;
    if (dim) {
      if (dimmedSubLayers) return;
      dimmedSubLayers = [];
      for (var name in overlays) {
        if (!Object.prototype.hasOwnProperty.call(overlays, name)) continue;
        var layer = overlays[name];
        if (!layer || !map.hasLayer(layer)) continue;
        if (typeof layer.eachLayer === "function") {
          (function (group) {
            group.eachLayer(function (sub) {
              rememberAndDim(sub);
            });
          })(layer);
        } else {
          rememberAndDim(layer);
        }
      }
    } else if (dimmedSubLayers) {
      dimmedSubLayers.forEach(function (item) {
        applyOpacityToLayer(item.sub, item.opacity);
      });
      dimmedSubLayers = null;
    }

    function rememberAndDim(sub) {
      dimmedSubLayers.push({ sub: sub, opacity: currentSubOpacity(sub) });
      applyOpacityToLayer(sub, ACTIVITY_HEATMAP_DIM_OPACITY);
    }
  }

  // The reverse map activity id -> cell keys, built lazily once from the index
  // (which stores cells -> members, the direction a click needs).
  var cellsByActivity = null;

  function activityCellsById(index, id) {
    if (!index || !index.cells) return [];
    if (!cellsByActivity) {
      cellsByActivity = {};
      for (var key in index.cells) {
        if (!Object.prototype.hasOwnProperty.call(index.cells, key)) continue;
        var members = index.cells[key];
        for (var i = 0; i < members.length; i++) {
          if (!cellsByActivity[members[i]]) cellsByActivity[members[i]] = [];
          cellsByActivity[members[i]].push(key);
        }
      }
    }
    return cellsByActivity[id] || [];
  }

  // The [[south, west], [north, east]] bounds of one grid cell, converted from
  // the index's Web Mercator metres back to the lat/lng Leaflet draws in.
  function activityCellBounds(index, key) {
    var cell = parseInt(key, 10);
    var col = cell % index.cols;
    var row = Math.floor(cell / index.cols);
    var west = index.xMin + col * index.cellSize;
    var east = west + index.cellSize;
    var north = index.yMax - row * index.cellSize;
    var south = north - index.cellSize;
    return [
      [mercatorToLat(south), mercatorToLon(west)],
      [mercatorToLat(north), mercatorToLon(east)],
    ];
  }

  // The bright paint the hovered route is drawn in, standing out against the
  // dimmed heatmap behind it.
  var ACTIVITY_FOOTPRINT_COLOR = "#ffe14d";

  function showActivityFootprint(map, index, id) {
    if (!map || !index || !global.L || typeof global.L.rectangle !== "function") return;
    clearActivityFootprint(map);
    setActivityHeatmapDim(map, true);
    var keys = activityCellsById(index, id);
    if (!keys.length) return;
    var rects = [];
    keys.forEach(function (key) {
      var rect = global.L.rectangle(activityCellBounds(index, key), {
        color: ACTIVITY_FOOTPRINT_COLOR,
        weight: 2,
        opacity: 1,
        fillColor: ACTIVITY_FOOTPRINT_COLOR,
        fillOpacity: 0.9,
        interactive: false,
      });
      if (typeof rect.addTo === "function") rect.addTo(map);
      rects.push(rect);
    });
    activityFootprint = rects;
  }

  function clearActivityFootprint(map) {
    if (activityFootprint) {
      activityFootprint.forEach(function (rect) {
        if (map && typeof map.removeLayer === "function") map.removeLayer(rect);
      });
      activityFootprint = null;
    }
    setActivityHeatmapDim(map, false);
  }

  // The click tolerance is adjustable while the page is open, from a control in
  // the panel's Advanced section (see buildActivityControl): the tolerance tunes
  // the click search, so it sits with the other tuning controls rather than
  // floating over the map. Narrowing it pins a click to the exact pixel in a
  // busy corner; widening it reaches a route beside a road or a junction's other
  // arm.
  var ACTIVITY_CONTROL_CLASS = "hcp-activity-control";

  // Apply a new tolerance. A ring left on the map by the last click is resized
  // too, so a drag shows its effect immediately rather than only on the next
  // click.
  function setActivitySearchRadius(px) {
    var rounded = Math.round(px);
    if (!isFinite(rounded)) return;
    ACTIVITY_SEARCH_RADIUS_PX = Math.max(
      ACTIVITY_RADIUS_MIN_PX,
      Math.min(ACTIVITY_RADIUS_MAX_PX, rounded)
    );
    if (activityHighlight && typeof activityHighlight.setRadius === "function") {
      activityHighlight.setRadius(ACTIVITY_SEARCH_RADIUS_PX);
    }
  }

  // Build the click-radius row and slot it into the Advanced section's body,
  // before the Home marker subsection. Returns null when the panel has no
  // Advanced body — the click handling still works, only the slider is missing.
  function buildActivityControl(container) {
    if (!container || typeof container.appendChild !== "function") return null;

    var row = document.createElement("div");
    row.className = ACTIVITY_CONTROL_CLASS;

    var label = document.createElement("label");
    label.className = "hcp-activity-control-label";
    label.setAttribute(
      "data-hcp-help",
      "How far from your click the map looks for a route. Narrow the radius to pin a click to one road in a busy junction, or widen it to sweep in a route alongside it."
    );
    var labelText = document.createElement("span");
    labelText.textContent = "Click radius";
    label.appendChild(labelText);
    label.appendChild(makeHelpIcon());

    var slider = document.createElement("input");
    slider.type = "range";
    slider.className = "hcp-activity-control-slider";
    slider.min = String(ACTIVITY_RADIUS_MIN_PX);
    slider.max = String(ACTIVITY_RADIUS_MAX_PX);
    slider.step = "1";
    slider.value = String(ACTIVITY_SEARCH_RADIUS_PX);
    slider.setAttribute("aria-label", "Click radius in pixels");
    slider.title = "How far from a click to look for a route.";
    slider.addEventListener("input", function () {
      setActivitySearchRadius(parseFloat(slider.value));
      value.textContent = ACTIVITY_SEARCH_RADIUS_PX + " px";
    });

    var value = document.createElement("span");
    value.className = "hcp-activity-control-value";
    value.textContent = ACTIVITY_SEARCH_RADIUS_PX + " px";

    var control = document.createElement("div");
    control.className = "hcp-activity-control-slider-row";
    control.appendChild(slider);
    control.appendChild(value);

    row.appendChild(label);
    row.appendChild(control);

    // Insert before the Home marker subsection when it is present, so the
    // tuning controls read top-down: raster mode, click radius, home marker.
    var homeSection = document.getElementById("hcp-home-section");
    if (homeSection && typeof container.insertBefore === "function") {
      container.insertBefore(row, homeSection);
    } else {
      container.appendChild(row);
    }
    return row;
  }

  function installActivityTooltips(map) {
    if (!map || typeof map.on !== "function") return;
    // No embedded index means nothing to show; leave clicks alone entirely.
    if (!document.getElementById(ACTIVITY_DATA_ID)) return;
    activityMap = map;
    // The tolerance slider rides along with the click handling it governs,
    // living in the panel's Advanced section (see buildActivityControl).
    buildActivityControl(document.getElementById("hcp-advanced-body"));
    // Closing the popup (its x button, an Escape, a click elsewhere) leaves the
    // ring around the old click, and any route preview, meaningless — both are
    // removed with it.
    map.on("popupclose", function () {
      clearActivityHighlight(map);
      clearActivityFootprint(map);
      // The popup's per-popup filter closures are gone; the next click builds
      // a fresh popup that re-seeds from the slider (see buildActivityPopup).
      datePopupApply = null;
    });
    map.on("click", function (event) {
      if (!event || !event.latlng) return;
      loadActivityIndex()
        .then(function (index) {
          if (!index) return;
          var results = activitiesNear(index, event.latlng, map);
          if (results === null) return;
          var node = results.length
            ? buildActivityPopup(index, results)
            : buildEmptyActivityPopup();
          // Open the popup first: Leaflet closes any popup already on the map
          // (firing popupclose, which clears the old ring) before the new one
          // opens, so the fresh ring must be drawn after it.
          openActivityPopup(map, event.latlng, node);
          highlightSearchArea(map, event.latlng);
        })
        .catch(function () {
          // A corrupt or undecodable payload must not break the rest of the
          // panel; the click simply produces no popup.
        });
    });
  }

  /* ---- Date range filter (client-side re-rasterization) ------------------ */

  // The panel's From/To range slider (see control_panel.html) re-rasterizes the
  // density / coverage layers entirely in the browser, so narrowing the range
  // does not require rebuilding (or even re-downloading) the page. This is
  // possible because the build already ships everything needed inside the
  // tooltip index (see src/activity_index.py::build_activity_index):
  //
  //   * ``visits`` — a flat ``[activity_index, cell_key, n_visits]`` list, the
  //     per-activity counted-visit breakdown collected by the rasterizer. The
  //     three strategy grids the server paints are recomputed from it per
  //     activity: decay (geometric sum of ``n`` visits), raw-count (sum of
  //     ``n``) and binary-per-activity (1 per visited cell).
  //   * ``render`` — the exact render parameters (blur sigma, decay factor,
  //     coverage normalization basis, the full-grid per-strategy pass maxima
  //     and the total activity count), so the browser normalizes by the SAME
  //     maxima the server's baked images use. Filtered colours therefore stay
  //     on the legend's scale — a quiet year reads dimmer, not brighter.
  //
  // The approximation of scipy's gaussian_filter uses a separable gaussian
  // kernel with the same reflect edge handling and the same default radius
  // (4 * sigma), which keeps a filtered layer visually aligned with the baked
  // one. Only the density and coverage layers are re-drawn; the metric layers
  // (pace, heart rate, gradient) are built from per-activity averages rather
  // than these cells, so they are left untouched by the filter.

  var DATE_FILTER_COVERAGE = "Coverage (Places Visited)";

  // The date-range slider is the map-wide filter, so the click popup's own
  // From/To bounds start from the slider's current range and follow its moves
  // while the popup is open (see datePopupApply / refresh). Empty bounds read
  // as "everything", which is what an inactive slider reports.
  var dateFilterBounds = { from: "", to: "" };
  var datePopupApply = null; // function to push new bounds into the open popup

  // While a ranged render runs, a full-map overlay dims the map and swallows
  // interaction (see .hcp-date-filtering) so the user cannot pan/zoom/click
  // into a state that fights the refresh. Created once, attached per filter.
  var dateFilterBlocker = null;

  function dateShowBlocker(map, show) {
    if (!map || !map._container || typeof document === "undefined") return;
    if (show) {
      if (!dateFilterBlocker) {
        dateFilterBlocker = document.createElement("div");
        dateFilterBlocker.className = "hcp-date-filtering";
        dateFilterBlocker.setAttribute("aria-busy", "true");
      }
      if (dateFilterBlocker.parentNode !== map._container) {
        map._container.appendChild(dateFilterBlocker);
      }
    } else if (dateFilterBlocker && dateFilterBlocker.parentNode) {
      dateFilterBlocker.parentNode.removeChild(dateFilterBlocker);
    }
  }
  // Mirrors the server's "count" colormap (src/colormaps.py::create_colormaps):
  // (position, [R, G, B, A]) nodes in 0..1 space, baked into a 512-entry LUT
  // the same way matplotlib's LinearSegmentedColormap does.
  var DATE_COUNT_CMAP = [
    { pos: 0.0, rgba: [0.0, 0.0, 0.0, 0.0] },
    { pos: 0.01, rgba: [0.4, 0.1, 0.0, 0.55] },
    { pos: 0.2, rgba: [0.99, 0.3, 0.01, 0.8] },
    { pos: 0.5, rgba: [1.0, 0.65, 0.0, 0.92] },
    { pos: 0.8, rgba: [1.0, 0.92, 0.2, 0.97] },
    { pos: 1.0, rgba: [1.0, 1.0, 0.8, 1.0] },
  ];
  var DATE_COUNT_LUT_SIZE = 512;

  // Piecewise-linear lookup for one channel (matplotlib's per-channel segment
  // interpolation), given nodes as ``{ pos, v }`` sorted by ``pos``.
  function dateChannelAt(nodes, t) {
    if (t <= nodes[0].pos) return nodes[0].v;
    for (var i = 1; i < nodes.length; i++) {
      if (t <= nodes[i].pos) {
        var span = nodes[i].pos - nodes[i - 1].pos;
        var f = span > 0 ? (t - nodes[i - 1].pos) / span : 0;
        return nodes[i - 1].v + f * (nodes[i].v - nodes[i - 1].v);
      }
    }
    return nodes[nodes.length - 1].v;
  }

  var dateColormapLut = null;

  function dateEnsureLut() {
    if (dateColormapLut) return dateColormapLut;
    var lut = new Uint8Array(DATE_COUNT_LUT_SIZE * 4);
    var channels = [[], [], [], []];
    for (var c = 0; c < 4; c++) {
      channels[c] = DATE_COUNT_CMAP.map(function (node) {
        return { pos: node.pos, v: node.rgba[c] };
      });
    }
    for (var i = 0; i < DATE_COUNT_LUT_SIZE; i++) {
      var t = i / (DATE_COUNT_LUT_SIZE - 1);
      for (var ch = 0; ch < 4; ch++) {
        lut[i * 4 + ch] = Math.round(255 * dateChannelAt(channels[ch], t));
      }
    }
    dateColormapLut = lut;
    return lut;
  }

  // The geometric sum 1 + d + d^2 + ... + d^(n-1) the "decay" strategy adds
  // per cell (see rasterizer._geom_sum). Powers of the decay factor get very
  // small very fast, so the closed-form avoids iterating n times per cell.
  function dateGeomSum(n, decay) {
    if (n <= 1) return 1;
    if (decay <= 0) return 1;
    if (decay >= 1) return n;
    return (1 - Math.pow(decay, n)) / (1 - decay);
  }

  // Separable gaussian blur approximating scipy.ndimage.gaussian_filter: same
  // kernel (exp(-x^2 / 2 sigma^2), normalised), same edge mode ("reflect") and
  // the same radius (int(truncate * sigma + 0.5) with the default truncate of 4).
  // Returns a fresh Float64Array so the caller keeps the raw strategy grid.
  function dateGaussianBlur(src, rows, cols, sigma) {
    var size = rows * cols;
    var out = new Float64Array(size);
    if (!size) return out;
    if (!sigma || sigma <= 0 || rows < 1 || cols < 1) {
      for (var q = 0; q < size; q++) out[q] = src[q];
      return out;
    }
    var radius = Math.max(0, Math.round(4 * sigma + 0.5));
    if (radius === 0) {
      for (var z = 0; z < size; z++) out[z] = src[z];
      return out;
    }
    var inv = 1 / (2 * sigma * sigma);
    var kLen = 2 * radius + 1;
    var kernel = [];
    var wsum = 0;
    for (var k = -radius; k <= radius; k++) {
      var w = Math.exp(-(k * k) * inv);
      kernel.push(w);
      wsum += w;
    }
    var row = new Float64Array(size);
    var y, x, i, acc, gx, gy, base;
    // Horizontal pass.
    for (y = 0; y < rows; y++) {
      base = y * cols;
      for (x = 0; x < cols; x++) {
        acc = 0;
        for (i = 0; i < kLen; i++) {
          gx = x - radius + i;
          if (gx < 0) gx = -gx;
          else if (gx >= cols) gx = 2 * cols - gx - 2;
          if (gx < 0) gx = 0;
          else if (gx >= cols) gx = cols - 1;
          acc += src[base + gx] * kernel[i];
        }
        row[base + x] = acc / wsum;
      }
    }
    // Vertical pass.
    for (x = 0; x < cols; x++) {
      for (y = 0; y < rows; y++) {
        acc = 0;
        for (i = 0; i < kLen; i++) {
          gy = y - radius + i;
          if (gy < 0) gy = -gy;
          else if (gy >= rows) gy = 2 * rows - gy - 2;
          if (gy < 0) gy = 0;
          else if (gy >= rows) gy = rows - 1;
          acc += row[gy * cols + x] * kernel[i];
        }
        out[y * cols + x] = acc / wsum;
      }
    }
    return out;
  }

  // Normalize a blurred strategy grid against the FULL-grid pass maximum (from
  // index.render.maxPassesByStrategy), so filtered colours stay on the baked
  // legend scale instead of re-maxing to the filtered subset. Mirrors
  // rasterizer._compute_count_grid's log1p normalization with max_count == 0
  // guarded to an all-zero grid.
  function dateLogNorm(blurred, rows, cols, fullMax) {
    var size = rows * cols;
    var norm = new Float64Array(size);
    if (!fullMax || fullMax <= 0) return norm;
    var denom = Math.log(1 + fullMax);
    for (var i = 0; i < size; i++) {
      norm[i] = Math.log(1 + blurred[i]) / denom;
    }
    return norm;
  }

  // Coverage normalization basis: "pct" divides the blurred per-activity counts
  // by the TOTAL activity count (a cell 1.0 = every activity visited it),
  // "max" scales relative to the most-visited cell (legacy). Mirrors
  // rasterizer.compute_normalized_grids' unique_pct_norm / unique_norm.
  function dateCoverageNorm(blurredBinary, rows, cols, render, maxByStrategy) {
    var size = rows * cols;
    var norm = new Float64Array(size);
    var total, i, q;
    if (render.coverageNormalization === "pct") {
      total = render.nActivities || 0;
      if (total <= 0) return norm;
      for (i = 0; i < size; i++) {
        q = blurredBinary[i] / total;
        norm[i] = q > 1 ? 1 : q;
      }
    } else {
      total = maxByStrategy["binary-per-activity"];
      if (!total || total <= 0) return norm;
      for (i = 0; i < size; i++) {
        q = blurredBinary[i] / total;
        norm[i] = q > 1 ? 1 : q;
      }
    }
    return norm;
  }

  // Apply the count colormap to a normalized grid and hand back a PNG data URI.
  // A normalized value of 0 maps to cmap(0) = fully transparent black, so cells
  // with no filtered data vanish rather than painting a dark splotch. The PNG
  // is produced on a canvas (the same trick the baked overlays use); when a
  // binned frame is being returned, datePngUri scales it back up smoothly (see
  // there) so the overlay is as smooth as the baked full-resolution image.
  function dateColorizeAndUri(norm, rows, cols, outRows, outCols) {
    var lut = dateEnsureLut();
    var size = norm.length;
    var rgba = new Uint8ClampedArray(size * 4);
    for (var i = 0; i < size; i++) {
      var v = norm[i];
      if (!(v > 0)) continue;
      var idx = v >= 1 ? DATE_COUNT_LUT_SIZE - 1 : Math.round(v * (DATE_COUNT_LUT_SIZE - 1));
      var src = idx * 4;
      var dst = i * 4;
      rgba[dst] = lut[src];
      rgba[dst + 1] = lut[src + 1];
      rgba[dst + 2] = lut[src + 2];
      rgba[dst + 3] = lut[src + 3];
    }
    return datePngUri(rgba, rows, cols, outRows, outCols);
  }

  var dateFilterCanvas = null;

  // Encode a grid as a PNG data URI. When ``outRows/outCols`` differ from the
  // grid's own size, the frame is painted back up to the baked image's
  // resolution with the canvas's memory/GPU-accelerated smoothed scaling
  // (imageSmoothingEnabled, the default), so a binned-down filtered frame still
  // looks as smooth and high-res as the original overlay. Premultiplied-alpha
  // smoothing is handled by the canvas for us, so transparent edges blend in
  // without dark halos.
  function datePngUri(rgba, rows, cols, outRows, outCols) {
    if (!rgba || !cols || !rows) return null;
    if (typeof document === "undefined" || typeof document.createElement !== "function") {
      return null;
    }
    var up = outRows && outCols && (outRows !== rows || outCols !== cols);
    if (!up) {
      if (!dateFilterCanvas) dateFilterCanvas = document.createElement("canvas");
      dateFilterCanvas.width = cols;
      dateFilterCanvas.height = rows;
      var context = dateFilterCanvas.getContext && dateFilterCanvas.getContext("2d");
      if (!context) return null;
      var image = context.createImageData(cols, rows);
      image.data.set(rgba);
      context.putImageData(image, 0, 0);
      return dateFilterCanvas.toDataURL("image/png");
    }
    // Binned frame -> full-resolution overlay, scaled with smoothing.
    if (!dateFilterCanvas) dateFilterCanvas = document.createElement("canvas");
    var small = dateFilterCanvas;
    small.width = cols;
    small.height = rows;
    var smallCtx = small.getContext && small.getContext("2d");
    if (!smallCtx) return null;
    var smallImage = smallCtx.createImageData(cols, rows);
    smallImage.data.set(rgba);
    smallCtx.putImageData(smallImage, 0, 0);
    var big = document.createElement("canvas");
    big.width = outCols;
    big.height = outRows;
    var bigCtx = big.getContext && big.getContext("2d");
    if (!bigCtx) return null;
    bigCtx.imageSmoothingEnabled = true;
    bigCtx.clearRect(0, 0, outCols, outRows);
    bigCtx.drawImage(small, 0, 0, cols, rows, 0, 0, outCols, outRows);
    return big.toDataURL("image/png");
  }

  /* ---- Date-range rasterization worker ---------------------------------- */

  // Re-rasterizing is pure number-crunching (grid accumulation, gaussian blur,
  // normalization, colormap). The date filter renders a binned ~2.5M-cell
  // preview (see dateRenderRange) so the work stays well under a second per
  // strategy, and it runs in a Web Worker to keep the map and control panel
  // responsive while the filtered heatmap is computed; the page simply repaints
  // when the worker returns. The build has no module system, so the worker
  // script is assembled at runtime by stringifying the shared pure helpers —
  // dateGaussianBlur / dateLogNorm / dateCoverageNorm are exactly the functions
  // the synchronous fallback path uses, so a ranged render cannot drift from
  // the baked math. The worker returns raw RGBA buffers; PNG encoding stays on
  // the main thread because datePngUri needs a DOM canvas.

  function dateWorkerDispatch(selfScope) {
    "use strict";
    selfScope.onmessage = function (event) {
      var msg = event.data || {};
      try {
        var results = [];
        var blurs = {};
        msg.bands.forEach(function (band) {
          var blurred = blurs[band.key];
          if (!blurred) {
            blurred = dateGaussianBlur(band.grid, msg.rows, msg.cols, msg.render.blurSigmaPx);
            // The grid arrived binned down by 1/F^2 the render was re-scaled
            // into full-cell magnitudes before blurring, so dividing it back
            // lands the colour exactly on the baked (full-resolution) legend
            // scale — the blur is linear, so binned blur ~= F^2 . full blur.
            if (msg.binInvScale && msg.binInvScale !== 1) {
              for (var q = 0; q < blurred.length; q++) blurred[q] *= msg.binInvScale;
            }
            blurs[band.key] = blurred;
          }
          var norm = dateLogNorm(blurred, msg.rows, msg.cols, msg.render.maxPassesByStrategy[band.key]);
          var rgba = dateWorkerColorize(norm, msg.lut, msg.lutSize);
          results.push({ layer: band.layer, rows: msg.rows, cols: msg.cols, rgba: rgba });
        });
        // Coverage shares the blurred binary grid (see dateCoverageNorm).
        if (blurs["binary-per-activity"] && msg.coverageLayer) {
          var cov = dateCoverageNorm(
            blurs["binary-per-activity"],
            msg.rows,
            msg.cols,
            msg.render,
            msg.render.maxPassesByStrategy
          );
          var covRgba = dateWorkerColorize(cov, msg.lut, msg.lutSize);
          results.push({ layer: msg.coverageLayer, rows: msg.rows, cols: msg.cols, rgba: covRgba });
        }
        var buffers = results.map(function (r) {
          return r.rgba.buffer;
        });
        selfScope.postMessage({ ok: true, results: results }, buffers);
      } catch (err) {
        selfScope.postMessage({ ok: false });
      }
    };
  }

  function dateWorkerColorize(norm, lut, lutSize) {
    var size = norm.length;
    var rgba = new Uint8ClampedArray(size * 4);
    for (var i = 0; i < size; i++) {
      var v = norm[i];
      if (!(v > 0)) continue;
      var idx = v >= 1 ? lutSize - 1 : Math.round(v * (lutSize - 1));
      var src = idx * 4;
      var dst = i * 4;
      rgba[dst] = lut[src];
      rgba[dst + 1] = lut[src + 1];
      rgba[dst + 2] = lut[src + 2];
      rgba[dst + 3] = lut[src + 3];
    }
    return rgba;
  }

  var dateWorkerSrc = null;
  var dateWorker = null;

  function dateWorkerSource() {
    if (dateWorkerSrc) return dateWorkerSrc;
    dateWorkerSrc = [
      dateWorkerDispatch.toString(),
      dateGaussianBlur.toString(),
      dateLogNorm.toString(),
      dateCoverageNorm.toString(),
      dateWorkerColorize.toString(),
      "dateWorkerDispatch(self);",
    ].join("\n");
    return dateWorkerSrc;
  }

  // A worker is created per render; any worker still crunching the PREVIOUS
  // range is terminated first, so a fast user at the slider never queues stale
  // renders behind old ones — the newest range is always the one that matters.
  function dateEnsureWorker() {
    if (typeof Worker !== "function" || typeof Blob !== "function") return null;
    if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") return null;
    try {
      if (!dateWorker) {
        dateWorker = new Worker(
          URL.createObjectURL(new Blob([dateWorkerSource()], { type: "application/javascript" }))
        );
      }
      return dateWorker;
    } catch (e) {
      return null;
    }
  }

  // Post a job, resolving with the worker's result bands (raw RGBA buffers).
  // Returns null when workers are unavailable so the caller can fall back to
  // the synchronous math. A render superseded by a newer job is terminated
  // before it can reply, so its promise never settles; callers guard against
  // painting anything stale with the render sequence number (see refresh).
  function dateRunWorker(msg) {
    if (dateWorker) {
      try {
        dateWorker.terminate();
      } catch (e) {
        /* already gone */
      }
      dateWorker = null;
    }
    var worker = dateEnsureWorker();
    if (!worker) return null;
    return new Promise(function (resolve, reject) {
      function cleanup() {
        worker.removeEventListener("message", onMessage);
        worker.removeEventListener("error", onError);
      }
      function onError() {
        cleanup();
        reject(new Error("date-range worker failed"));
      }
      function onMessage(event) {
        cleanup();
        var data = event.data || {};
        if (!data.ok) {
          reject(new Error("date-range worker error"));
          return;
        }
        resolve(data.results || []);
      }
      worker.addEventListener("message", onMessage);
      worker.addEventListener("error", onError);
      worker.postMessage(msg, msg.transfer || []);
    });
  }

  // Turn the three strategy grids into overlay renditions. Prefers the worker
  // so the blur + colour work run off the main thread; falls back to the
  // identical synchronous math when a worker cannot be created. When
  // ``binFactor`` is > 1 the grids are already binned down, so the blur runs at
  // sigma / binFactor and the result is scaled back by 1/binFactor^2 (see
  // dateWorkerDispatch) to stay on the full-resolution legend scale. The binned
  // frames are then painted back up to the baked image's resolution
  // (``fullRows x fullCols``) with the canvas's own smoothed scaling in
  // datePngUri, so the filtered overlay keeps the map's smooth, high-res look.
  // Returns a Promise of ``{layer: PNG data URI}``.
  function dateEncodeRange(
    decay,
    raw,
    binary,
    cols,
    rows,
    render,
    maxByStrategy,
    binFactor,
    fullRows,
    fullCols
  ) {
    var bands = [];
    (dateDensityModes || []).forEach(function (mode) {
      if (!mode || !mode.key || !mode.layer) return;
      var grid =
        mode.key === "raw-count"
          ? raw
          : mode.key === "binary-per-activity"
            ? binary
            : decay;
      bands.push({ key: mode.key, layer: mode.layer, grid: grid });
    });
    if (!bands.length) return Promise.resolve({});

    // Both render paths normalise options the same way the baked pipeline
    // does, so a missing sigma falls back to the same default here.
    var binInvScale = binFactor > 1 ? 1 / (binFactor * binFactor) : 1;
    var workerRender = {
      decayFactor: render.decayFactor,
      blurSigmaPx: typeof render.blurSigmaPx === "number" ? render.blurSigmaPx : 2,
      coverageNormalization: render.coverageNormalization,
      nActivities: render.nActivities,
      maxPassesByStrategy: maxByStrategy,
    };
    // A binned grid is F cells per sample, so the same physical blur needs a
    // F-times wider footprint; the counts are then un-scaled after the blur.
    if (binFactor > 1) workerRender.blurSigmaPx = workerRender.blurSigmaPx / binFactor;

    var workerJob = dateRunWorker({
      rows: rows,
      cols: cols,
      binInvScale: binInvScale,
      render: workerRender,
      lut: dateEnsureLut(),
      lutSize: DATE_COUNT_LUT_SIZE,
      coverageLayer: DATE_FILTER_COVERAGE,
      bands: bands,
      transfer: bands.map(function (b) {
        return b.grid.buffer;
      }),
    });
    if (workerJob) {
      return workerJob.then(function (results) {
        var urisByName = {};
        for (var i = 0; i < results.length; i++) {
          var r = results[i];
          var uri = datePngUri(r.rgba, r.rows, r.cols, fullRows, fullCols);
          if (uri !== null) urisByName[r.layer] = uri;
        }
        return urisByName;
      });
    }

    // Synchronous fallback — the same math dateWorkerDispatch runs (mirrors the
    // strategy selection above, including the shared binary blur for coverage).
    var sigma = workerRender.blurSigmaPx;
    var blurs = {};
    var urisByName = {};
    for (var i = 0; i < bands.length; i++) {
      var b = bands[i];
      var blurred = blurs[b.key];
      if (!blurred) {
        blurred = dateGaussianBlur(b.grid, rows, cols, sigma);
        if (binInvScale !== 1) {
          for (var q = 0; q < blurred.length; q++) blurred[q] *= binInvScale;
        }
        blurs[b.key] = blurred;
      }
      var norm = dateLogNorm(blurred, rows, cols, maxByStrategy[b.key]);
      var uri = dateColorizeAndUri(norm, rows, cols, fullRows, fullCols);
      if (uri !== null) urisByName[b.layer] = uri;
    }
    if (blurs["binary-per-activity"]) {
      var cov = dateCoverageNorm(blurs["binary-per-activity"], rows, cols, workerRender, maxByStrategy);
      var covUri = dateColorizeAndUri(cov, rows, cols, fullRows, fullCols);
      if (covUri !== null) urisByName[DATE_FILTER_COVERAGE] = covUri;
    }
    return Promise.resolve(urisByName);
  }

  // The visits payload is already grouped by activity, so one pass turns it
  // into per-activity cell lists — [cell_key, n_visits] pairs — and a range
  // change never has to re-scan the whole document (only accumulate the
  // in-range activities' lists).
  var dateVisitLists = null;

  function dateBuildVisitLists(index) {
    var visits = index.visits || [];
    var total = (index.activities || []).length;
    var lists = new Array(total);
    for (var i = 0; i < total; i++) lists[i] = null;
    for (var k = 0; k < visits.length; k++) {
      var rec = visits[k];
      var id = rec[0];
      if (id < 0 || id >= total || !rec[1]) continue;
      if (!lists[id]) lists[id] = [];
      lists[id].push([rec[1], rec[2]]);
    }
    return lists;
  }

  // ISO dates compare correctly as plain strings ("YYYY-MM-DD"). Activities
  // with no date (a bespoke track label the loader could not parse) are only
  // shown when no bound is set, mirroring the click popup's date filter.
  function dateMatchesRange(date, from, to) {
    if (!from && !to) return true;
    if (!date) return false;
    if (from && date < from) return false;
    if (to && date > to) return false;
    return true;
  }

  // Which overlay holds the pre-baked layer for each raster mode; resolving it
  // from the panel's advanced config keeps this in step with the Advanced
  // dropdown (mode key -> layer name, see build_advanced_config).
  var dateDensityModes = null;

  // The date filter renders onto a grid binned down so the blur + colour work
  // scale with the VIEW (a couple of million cells) instead of the bake (the
  // full grids here reach tens of millions of cells, which would take the blur
  // ~10s per strategy at full resolution). The bins land back on the baked
  // legend scale because the binned counts are re-scaled by 1/F^2 after the
  // blur (see dateEncodeRange): the blur operator is linear, so the binned
  // blurred field is ~F^2 times the full-resolution blurred field, which
  // divides straight back out against the full maxPassesByStrategy.
  var DATE_FILTER_TARGET_CELLS = 2500000;

  // Bin factor for a grid: the smallest integer F so a cell count <= the
  // target; grids already at or below the target render at full resolution.
  function dateBinFactor(rows, cols) {
    var cells = rows * cols;
    if (cells <= DATE_FILTER_TARGET_CELLS) return 1;
    return Math.ceil(Math.sqrt(cells / DATE_FILTER_TARGET_CELLS));
  }

  // Recompute the strategy grids from the in-range activities and produce one
  // overlay image URI per density mode plus the coverage layer. The grids are
  // accumulated onto a binned-down grid (see dateBinFactor) so the raster work
  // scales with the viewport-sized preview rather than the full bake. Returns a
  // Promise of ``{ urisByName, shown, total }`` — the URI painting is handed to
  // the Web Worker (see dateEncodeRange) so the panel never blocks on it.
  function dateRenderRange(index, from, to) {
    var activities = index.activities || [];
    var cols = index.cols;
    var rows = index.rows;
    var render = index.render || {};
    var maxByStrategy = render.maxPassesByStrategy || {};
    if (!dateVisitLists || dateVisitLists.length !== activities.length) {
      dateVisitLists = dateBuildVisitLists(index);
    }

    var included = [];
    for (var id = 0; id < activities.length; id++) {
      var date = (activities[id] && activities[id][0]) || "";
      if (dateMatchesRange(date, from, to)) included.push(id);
    }

    // Accumulate straight into the binned grid — the date filter's raster work
    // then scales with the ~2.5M-cell preview, not the tens-of-millions-cell
    // bake, and the 1/F^2 scaling in dateEncodeRange keeps the colours on the
    // full-resolution legend scale.
    var binFactor = dateBinFactor(rows, cols);
    var colsB = Math.ceil(cols / binFactor);
    var rowsB = Math.ceil(rows / binFactor);
    var sizeB = rowsB * colsB;
    var decay = new Float64Array(sizeB);
    var raw = new Float64Array(sizeB);
    var binary = new Float64Array(sizeB);
    var df = render.decayFactor;
    var cell, n, b, row;
    for (var i = 0; i < included.length; i++) {
      var list = dateVisitLists[included[i]];
      if (!list) continue;
      for (var j = 0; j < list.length; j++) {
        cell = list[j][0];
        n = list[j][1];
        row = (cell / cols) | 0;
        b = ((row / binFactor) | 0) * colsB + ((cell % cols) / binFactor | 0);
        decay[b] += dateGeomSum(n, df);
        raw[b] += n;
        binary[b] += 1;
      }
    }

    return dateEncodeRange(decay, raw, binary, colsB, rowsB, render, maxByStrategy, binFactor, rows, cols).then(
      function (urisByName) {
        return { urisByName: urisByName, shown: included.length, total: activities.length };
      }
    );
  }

  // The baked (unfiltered) image each re-rendered layer must be restored to
  // when the range is reset. Captured from the overlay's own options on the
  // first override, so no constants have to mirror the build.
  var dateOriginals = {};
  var dateFilterCache = {};

  function dateEachSub(layer, fn) {
    if (!layer) return;
    if (typeof layer.eachLayer === "function") layer.eachLayer(fn);
    else if (typeof fn === "function") fn(layer);
  }

  function dateSetLayerUri(layer, uri) {
    dateEachSub(layer, function (sub) {
      if (sub && typeof sub.setUrl === "function") sub.setUrl(uri);
    });
  }

  function dateLayerUri(layer) {
    var found = null;
    dateEachSub(layer, function (sub) {
      if (found !== null || !sub) return;
      // The baked overlays are L.imageOverlay(url, bounds, opts) — folium
      // passes the image positionally, so Leaflet keeps it as ``_url`` and
      // ``options.image`` never exists. Read the real source so the reset can
      // put the original full-resolution PNG back (see dateRestoreOriginals).
      var src =
        (sub.options && (sub.options.image || sub.options.url)) ||
        (typeof sub._url === "string" ? sub._url : null);
      if (typeof src === "string") found = src;
    });
    return found;
  }

  function dateApplyResult(result, overlays) {
    var uris = result.urisByName || {};
    for (var name in uris) {
      if (!Object.prototype.hasOwnProperty.call(uris, name)) continue;
      var layer = overlays[name];
      if (!layer) continue;
      if (!dateOriginals[name]) dateOriginals[name] = dateLayerUri(layer);
      dateSetLayerUri(layer, uris[name]);
    }
  }

  function dateRestoreOriginals(overlays) {
    var originals = dateOriginals;
    for (var name in originals) {
      if (!Object.prototype.hasOwnProperty.call(originals, name)) continue;
      var layer = overlays[name];
      if (layer && originals[name]) dateSetLayerUri(layer, originals[name]);
    }
    dateOriginals = {};
  }

  /* ---- Date range filter: per-activity GPS tracks ----------------------- */

  // The "Raw GPS tracks" polylines are one per activity, so the date range can
  // fade them instantly — one setStyle per line, no raster work — giving the
  // slider immediate visual feedback while the heatmap re-rasterizes in the
  // worker. Each polyline's bound tooltip carries the activity label
  // "YYYY-MM-DD Name" (see activity_index.split_activity_label), so the date is
  // read straight off the layer, matching the range the same way the index
  // rows do. Undated (bespoke) labels are hidden whenever a filter is active,
  // exactly as the click popup and heatmap treat them.

  var dateTrackMap = null;
  var dateTrackStyles = {}; // sub-layer -> the style to restore it with

  function dateTracksGroup(overlays) {
    if (!overlays) return null;
    for (var name in overlays) {
      if (Object.prototype.hasOwnProperty.call(overlays, name) && /^Raw GPS tracks$/.test(name)) {
        return overlays[name];
      }
    }
    return null;
  }

  function dateTrackDate(sub) {
    var tooltip = sub && sub._tooltip;
    var content = tooltip && tooltip._content;
    if (typeof content === "string") {
      var m = content.match(/\d{4}-\d{2}-\d{2}/);
      if (m) return m[0];
    }
    return null;
  }

  // Fade every track outside [from, to] to fully transparent and restore the
  // ones inside. Styles are captured the first time a line is hidden so reset
  // puts each Tracks-layer line back exactly as it was (including any opacity
  // the "Raw GPS tracks" slider had set).
  function dateTracksFiltered(overlays, from, to) {
    var group = dateTracksGroup(overlays);
    if (!group || typeof group.eachLayer !== "function") return;
    if (!dateTrackMap || !dateTrackMap.hasLayer(group)) return;
    var changed = false;
    group.eachLayer(function (sub) {
      if (!sub || typeof sub.setStyle !== "function") return;
      var hidden = dateTrackStyles[sub] || null;
      if (dateMatchesRange(dateTrackDate(sub), from, to)) {
        if (hidden) {
          sub.setStyle(hidden);
          delete dateTrackStyles[sub];
          changed = true;
        }
        return;
      }
      if (!hidden) {
        dateTrackStyles[sub] = {
          color: sub.options && sub.options.color,
          weight: sub.options && sub.options.weight,
          opacity: sub.options && sub.options.opacity,
        };
        sub.setStyle({ opacity: 0 });
        changed = true;
      }
    });
    return changed;
  }

  function dateRestoreTracks(overlays) {
    var group = dateTracksGroup(overlays);
    if (!group || typeof group.eachLayer !== "function") return;
    group.eachLayer(function (sub) {
      if (!sub || typeof sub.setStyle !== "function") return;
      var hidden = dateTrackStyles[sub];
      if (hidden) sub.setStyle(hidden);
    });
    dateTrackStyles = {};
  }

  // True while the chosen range is narrower than the data's full span. No
  // bounds set, or bounds that cover everything, count as "not filtering".
  function dateFeatureActive(from, to, bounds) {
    return (
      (from && String(from) > String(bounds[0])) || (to && String(to) < String(bounds[1]))
    );
  }

  // Wire the From/To range slider. The section stays hidden unless the build
  // carried both the date bounds AND the per-activity cell counts (see
  // src/activity_index.build_activity_index) — a page without them cannot
  // re-rasterize anything, so the control is simply not offered.
  function installDateFilter(config) {
    if (!config || !config.dateBounds || config.dateBounds.length < 2) return;
    if (typeof document === "undefined" || typeof document.getElementById !== "function") {
      return;
    }
    var panel = document.getElementById(config.panelId);
    if (!panel || typeof panel.querySelector !== "function") return;
    dateTrackMap = config.map || null;
    var section = panel.querySelector("#hcp-dates-section");
    var fromEl = panel.querySelector("#hcp-date-from");
    var toEl = panel.querySelector("#hcp-date-to");
    var fromReadout = panel.querySelector("#hcp-date-from-readout");
    var toReadout = panel.querySelector("#hcp-date-to-readout");
    var resetEl = panel.querySelector("#hcp-date-reset");
    var statusEl = panel.querySelector("#hcp-date-status");
    var fillEl = panel.querySelector("#hcp-date-slider-fill");
    if (!section || !fromEl || !toEl || !fromReadout || !toReadout || !resetEl || !statusEl || !fillEl) return;

    dateDensityModes = (config.advanced && config.advanced.modes) || null;
    if (!dateDensityModes || !dateDensityModes.length) return;

    var bounds = config.dateBounds;
    var DAY_MS = 24 * 60 * 60 * 1000;
    var startMs = Date.parse(bounds[0]);
    var endMs = Date.parse(bounds[1]);
    // The slider steps one day at a time between the two bounds.
    var totalDays = Math.max(1, Math.round((endMs - startMs) / DAY_MS));

    // Slider position i maps to bounds[0] + i days.
    function indexToDate(i) {
      return new Date(startMs + i * DAY_MS);
    }

    function toIso(d) {
      // Parse/build in UTC so the day boundaries match the ISO bounds no
      // matter the viewer's timezone.
      var m = d.getUTCMonth() + 1;
      var day = d.getUTCDate();
      return (
        d.getUTCFullYear() +
        "-" +
        (m < 10 ? "0" : "") + m +
        "-" +
        (day < 10 ? "0" : "") + day
      );
    }

    // The ISO strings the filter logic compares (see refresh). A thumb on an
    // edge of the full range reports an empty bound, so the whole range reads
    // as "not filtering" exactly like an unset picker did (dateFeatureActive).
    function fromDate() {
      var i = parseInt(fromEl.value, 10);
      return i > 0 ? toIso(indexToDate(i)) : "";
    }

    function toDate() {
      var i = parseInt(toEl.value, 10);
      return i < totalDays ? toIso(indexToDate(i)) : "";
    }

    // Keep the From/To readouts and the fill bar between the thumbs in step
    // with the slider positions. Cheap enough to run on every "input" event.
    function syncReadouts() {
      fromReadout.textContent = toIso(indexToDate(parseInt(fromEl.value, 10)));
      toReadout.textContent = toIso(indexToDate(parseInt(toEl.value, 10)));
      var fromPct = (parseInt(fromEl.value, 10) / totalDays) * 100;
      var toPct = (parseInt(toEl.value, 10) / totalDays) * 100;
      fillEl.style.left = fromPct + "%";
      fillEl.style.width = (toPct - fromPct) + "%";
    }

    // Dragging one thumb past the other would leave an inverted range; swap
    // the two positions so the range stays valid and the fill bar keeps sense.
    function enforceOrder() {
      var from = parseInt(fromEl.value, 10);
      var to = parseInt(toEl.value, 10);
      if (from > to) {
        fromEl.value = String(to);
        toEl.value = String(from);
      }
      syncReadouts();
    }

    fromEl.min = "0";
    fromEl.max = String(totalDays);
    fromEl.value = "0";
    toEl.min = "0";
    toEl.max = String(totalDays);
    toEl.value = String(totalDays);
    syncReadouts();

    // Confirm the index can actually re-render before showing the control: a
    // page with bounds but no per-activity visits (e.g. an index built without
    // the filter's payload) must not offer a dead toggle.
    loadActivityIndex()
      .then(function (index) {
        section.hidden = !(index && index.visits && index.render);
      })
      .catch(function () {
        section.hidden = true;
      });

    var timer = null;
    // Each refresh is stamped; when a render resolves, only the newest stamp
    // may paint. A superseded render (the slider moved on, or a fresh worker
    // replaced the job) is dropped instead of flashing a stale heatmap.
    var renderSeq = 0;

    function schedule() {
      if (timer) clearTimeout(timer);
      timer = setTimeout(refresh, 250);
    }

    function refresh() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      var from = fromDate();
      var to = toDate();
      // Remember the range so a click popup opened while the range is active
      // filters to the same dates (buildActivityPopup reads dateFilterBounds)
      // and push the latest bounds into a popup already on the map.
      dateFilterBounds.from = from;
      dateFilterBounds.to = to;
      if (datePopupApply) datePopupApply(from, to);
      var overlays = findOverlays();
      if (!overlays) return;
      if (!dateFeatureActive(from, to, bounds)) {
        dateRestoreOriginals(overlays);
        dateRestoreTracks(overlays);
        // Drop any stale render still in flight from before the reset: without
        // this it would resolve and repaint the filtered image, and re-capture
        // THAT as the new "original" for the next reset.
        renderSeq++;
        statusEl.textContent = "";
        dateShowBlocker(dateTrackMap, false);
        return;
      }
      // Tracks fade instantly (one setStyle per line); the heatmap re-rasterises
      // in the worker and paints over when it is ready. The map is dimmed and
      // its interaction disabled while the render runs.
      dateTracksFiltered(overlays, from, to);
      statusEl.textContent = "Filtering\u2026";
      dateShowBlocker(dateTrackMap, true);
      var seq = ++renderSeq;
      loadActivityIndex()
        .then(function (index) {
          if (!index || !index.visits || !index.render) {
            section.hidden = true;
            dateShowBlocker(dateTrackMap, false);
            return;
          }
          var key = from + "|" + to;
          var pending = dateFilterCache[key];
          if (!pending) {
            pending = dateRenderRange(index, from, to);
            var keys = Object.keys(dateFilterCache);
            // Each cached frame is a set of full-resolution PNG data URIs (as big as the
    // baked overlays), so only a handful of ranges are kept; the slider revisit
    // case that matters most is a few adjacent ranges.
    if (keys.length >= 8) delete dateFilterCache[keys[0]];
            dateFilterCache[key] = pending;
          }
          return pending.then(function (result) {
            if (seq !== renderSeq) return;
            dateApplyResult(result, overlays);
            statusEl.textContent =
              result.shown === result.total
                ? result.total + " activities"
                : result.shown + " of " + result.total + " activities";
            dateShowBlocker(dateTrackMap, false);
          });
        })
        .catch(function () {
          if (seq === renderSeq) {
            statusEl.textContent = "";
            dateShowBlocker(dateTrackMap, false);
          }
        });
    }

    fromEl.addEventListener("input", enforceOrder);
    toEl.addEventListener("input", enforceOrder);
    fromEl.addEventListener("change", schedule);
    toEl.addEventListener("change", schedule);
    resetEl.addEventListener("click", function () {
      fromEl.value = "0";
      toEl.value = String(totalDays);
      syncReadouts();
      refresh();
    });

    // Enabling the "Raw GPS tracks" layer while a range is active must respect
    // it immediately; otherwise only the next slider move would fade the lines.
    if (dateTrackMap && typeof dateTrackMap.on === "function") {
      dateTrackMap.on("overlayadd", function (e) {
        if (!e || !/^Raw GPS tracks$/.test(e.name || "")) return;
        var overlays = findOverlays();
        if (!overlays) return;
        var from = fromDate();
        var to = toDate();
        if (dateFeatureActive(from, to, bounds)) {
          dateTracksFiltered(overlays, from, to);
        }
      });
    }
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

    /* --- Basemap family segments + Labels checkbox ----------------------- */
    // Each family button plus the Labels checkbox resolves to a full CARTO
    // style key through familyStyles (e.g. dark + labels -> "dark_all",
    // dark + no labels -> "dark_nolabels").
    var familyStyles = config.familyStyles || {};
    var currentStyle = currentBasemapStyle(map) || config.activeBasemap;
    var cached = {};
    var segmentBox = panel.querySelector("#hcp-basemap");
    var labelsBox = panel.querySelector("#hcp-basemap-labels");

    function familyOfStyle(styleKey) {
      for (var family in familyStyles) {
        var variants = familyStyles[family];
        if (variants.labels === styleKey || variants.noLabels === styleKey) return family;
      }
      return null;
    }

    function styleHasLabels(styleKey) {
      for (var family in familyStyles) {
        var variants = familyStyles[family];
        if (variants.labels === styleKey) return true;
        if (variants.noLabels === styleKey) return false;
      }
      return null;
    }

    function styleForFamily(family, showLabels) {
      var variants = familyStyles[family];
      if (!variants) return null;
      return showLabels ? variants.labels : variants.noLabels;
    }

    function applyBasemapStyle(styleKey) {
      if (!styleKey || styleKey === currentStyle) return;
      var layer = cached[styleKey];
      if (!layer) {
        layer = makeTileLayer(styleKey, config.apiKey);
        cached[styleKey] = layer;
      }
      removeBasemapLayers(map, layer);
      layer.addTo(map);
      currentStyle = styleKey;
      var family = familyOfStyle(styleKey);
      if (segmentBox && family) updateSegmentStates(segmentBox, family);
      if (labelsBox) {
        var hasLabels = styleHasLabels(styleKey);
        if (hasLabels !== null) labelsBox.checked = hasLabels;
      }
    }

    function selectFamily(family) {
      var showLabels = labelsBox ? labelsBox.checked : config.showLabels !== false;
      applyBasemapStyle(styleForFamily(family, showLabels));
    }

    if (segmentBox && config.basemapFamilies) {
      var activeFamily = familyOfStyle(currentStyle);
      config.basemapFamilies.forEach(function (option) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "hcp-segment";
        btn.setAttribute("data-style", option.key);
        // Each family gets its own explanation; the "Basemap" label carries the
        // visible info badge, so the buttons themselves stay uncluttered.
        btn.setAttribute("data-hcp-help", BASEMAP_HELP[option.key] || BASEMAP_HELP_FALLBACK);
        btn.textContent = option.label;
        if (option.key === activeFamily) {
          btn.classList.add("hcp-segment-active");
        }
        btn.addEventListener("click", function () {
          selectFamily(option.key);
        });
        segmentBox.appendChild(btn);
      });
    }

    if (labelsBox) {
      var initialLabels = styleHasLabels(currentStyle);
      labelsBox.checked = initialLabels === null ? config.showLabels !== false : initialLabels;
      labelsBox.addEventListener("change", function () {
        var family = familyOfStyle(currentStyle);
        if (!family && config.basemapFamilies && config.basemapFamilies.length) {
          family = config.basemapFamilies[0].key;
        }
        applyBasemapStyle(styleForFamily(family, labelsBox.checked));
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

    /* --- Activity click tooltips ----------------------------------------- */
    // Clicking a painted pixel lists the activities behind it (see
    // installActivityTooltips). A no-op on a page built without the index.
    installActivityTooltips(map);

    /* --- Date range filter ------------------------------------------------ */
    // From/To range slider that re-rasterizes the density / coverage layers in
    // the browser (see installDateFilter). A no-op unless the build embedded
    // the date bounds and the tooltip index carries the per-activity cells.
    installDateFilter(config);
  }

  global.initHeatmapControlPanel = init;
})(window);
