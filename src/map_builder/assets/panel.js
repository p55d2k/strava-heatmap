/*
 * Strava Heatmap — Unified Control Panel behaviour.
 *
 * Self-contained client-side logic for the single top-right control panel
 * embedded in the generated heatmap HTML. It merges what used to be the
 * stock Leaflet layer control into one central panel:
 *
 *   - Basemap style switching  (Dark / Light / Voyager)
 *   - Layer toggles            (radio for exclusive heatmap layers, checkbox
 *                               for independent layers such as raw GPS tracks)
 *   - Per-layer opacity sliders (one per layer, collapsible via "Opacity")
 *   - Fit-to-heatmap / Reset view
 *   - Legend toggle
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
 *     layerGroups:    [{ label, mode, layers: [{ name, visible }, ...] }, ...],
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

  // Build a single toggle row (radio or checkbox) bound to an overlay layer.
  // Opacity sliders live in a separate section (see buildOpacityList) so the
  // toggle rows stay compact. For radio groups, onRadioChange(name) fires when
  // that variant becomes selected so the panel can swap which slider is shown.
  function buildToggleRow(lDef, mode, radioName, map, overlays, onRadioChange) {
    var row = document.createElement("label");
    row.className = "hcp-layer-row";

    var input = document.createElement("input");
    input.type = mode === "radio" ? "radio" : "checkbox";
    if (mode === "radio") {
      input.name = radioName;
    }
    input.setAttribute("data-layer-name", lDef.name);

    var layer = overlays ? overlays[lDef.name] : null;
    input.checked = layer ? map.hasLayer(layer) : Boolean(lDef.visible);

    input.addEventListener("change", function () {
      if (!layer) return;
      if (input.checked) {
        if (!map.hasLayer(layer)) map.addLayer(layer);
        if (mode === "radio" && onRadioChange) onRadioChange(lDef.name);
      } else {
        if (map.hasLayer(layer)) map.removeLayer(layer);
      }
    });

    row.appendChild(input);
    var span = document.createElement("span");
    span.textContent = lDef.label || lDef.name;
    row.appendChild(span);
    return row;
  }

  // Render a set of rows into a prepared container, replacing any previous rows.
  function buildGroupRows(rows, lDefs, mode, radioName, map, overlays, onRadioChange) {
    rows.innerHTML = "";
    lDefs.forEach(function (lDef) {
      rows.appendChild(buildToggleRow(lDef, mode, radioName, map, overlays, onRadioChange));
    });
  }

  // Build the toggle rows for each configured layer group. Groups use two modes:
  //   * "radio"  (Heatmap density concepts) — mutually exclusive; selecting one
  //     removes the other layer(s) in the group from the map so stacked
  //     heatmaps can never overlap.
  //   * "check"  (metrics, raw tracks) — each layer toggles independently.
  function buildLayerList(container, layerGroups, map, overlays, config) {
    layerGroups.forEach(function (group, gIdx) {
      var groupLabel = document.createElement("div");
      groupLabel.className = "hcp-label hcp-layer-group-label";
      groupLabel.textContent = group.label;
      container.appendChild(groupLabel);

      var rows = document.createElement("div");
      rows.className = "hcp-layer-rows";
      container.appendChild(rows);

      // For a radio group, enforce exclusivity at the map level: when one variant
      // is selected, hide every other variant in the same group. The resulting
      // overlayadd / overlayremove events keep legend rows in sync automatically.
      var onRadioChange = null;
      if (group.mode === "radio") {
        onRadioChange = function (selectedName) {
          group.layers.forEach(function (other) {
            if (other.name === selectedName) return;
            var otherLayer = overlays ? overlays[other.name] : null;
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
        onRadioChange
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
  function buildRadioGroupOpacitySlider(group, map, overlays) {
    var item = document.createElement("div");
    item.className = "hcp-layer-opacity";
    item.setAttribute("data-layer-opacity", group.label);

    var nameEl = document.createElement("span");
    nameEl.className = "hcp-layer-opacity-name";
    nameEl.textContent = group.label;
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

    // Apply the slider's current value to whichever layer in the group is on the map.
    function applyToActive() {
      var pct = parseFloat(input.value) || 0;
      group.layers.forEach(function (lDef) {
        var layer = overlays ? overlays[lDef.name] : null;
        if (layer && map.hasLayer(layer)) {
          setLayerOpacityByName(lDef.name, overlays, pct / 100);
        }
      });
    }

    input.addEventListener("input", function () {
      var pct = parseFloat(input.value) || 0;
      valueEl.textContent = Math.round(pct) + "%";
      applyToActive();
    });

    // When a different radio variant is switched on, carry the shared slider
    // value over to the newly active layer automatically.
    map.on("overlayadd", applyToActive);
    map.on("overlayremove", applyToActive);

    control.appendChild(input);
    control.appendChild(valueEl);
    item.appendChild(control);

    // Match the currently active layer's opacity to the slider on load.
    applyToActive();

    return item;
  }

  // Render the opacity sliders for every layer group, into a prepared container.
  // Checkbox groups (metrics, raw tracks) expose one slider per layer. Radio
  // groups (e.g. the Heatmap density concepts) are mutually exclusive — only
  // one is on the map at a time — so they share a single combined slider
  // labelled by the group name. That slider defaults to 100% and drives
  // whichever variant is currently active.
  function buildOpacityList(container, layerGroups, map, overlays, config, defaultOpacity) {
    container.innerHTML = "";

    layerGroups.forEach(function (group) {
      if (group.mode === "radio") {
        container.appendChild(buildRadioGroupOpacitySlider(group, map, overlays));
      } else {
        group.layers.forEach(function (lDef) {
          container.appendChild(
            buildOpacitySlider(lDef.name, initialOpacityFor(lDef, defaultOpacity), overlays)
          );
        });
      }
    });

    return {};
  }

  // Sync every toggle with the actual on-map state (after overlay events).
  function syncLayerToggles(container, layerGroups, map, overlays) {
    layerGroups.forEach(function (group) {
      group.layers.forEach(function (lDef) {
        var layer = overlays ? overlays[lDef.name] : null;
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
  function wireLayerEvents(container, layerGroups, map, overlays) {
    map.on("overlayadd", function () {
      syncLayerToggles(container, layerGroups, map, overlays);
    });
    map.on("overlayremove", function () {
      syncLayerToggles(container, layerGroups, map, overlays);
    });
  }

  /* ---- Init ------------------------------------------------------------- */

  function init(config) {
    var panel = document.getElementById(config.panelId);
    if (!panel || !config.map) return;
    var map = config.map;

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
        defaultOpacity
      );
    }

    function setupLayerToggles() {
      layerOverlays = findOverlays();
      if (!layerOverlays) return false;
      buildLayerList(
        layersContainer,
        config.layerGroups,
        map,
        layerOverlays,
        config
      );
      renderOpacityList();
      wireLayerEvents(layersContainer, config.layerGroups, map, layerOverlays);
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
