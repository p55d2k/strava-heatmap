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
 *   - Heatmap opacity slider
 *   - Fit-to-heatmap / Reset view
 *   - Legend toggle
 *   - Collapse / expand
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

  function setOverlayOpacity(opacity) {
    var overlays = findOverlays();
    if (!overlays) return;
    for (var name in overlays) {
      if (!Object.prototype.hasOwnProperty.call(overlays, name)) continue;
      var layer = overlays[name];
      if (layer && typeof layer.eachLayer === "function") {
        layer.eachLayer(function (sub) {
          if (sub && typeof sub.setOpacity === "function") {
            sub.setOpacity(opacity);
          }
        });
      } else if (layer && typeof layer.setOpacity === "function") {
        layer.setOpacity(opacity);
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

  // Build the toggle rows for each configured layer group.
  function buildLayerList(container, layerGroups, map, overlays) {
    layerGroups.forEach(function (group, gIdx) {
      var groupLabel = document.createElement("div");
      groupLabel.className = "hcp-label hcp-layer-group-label";
      groupLabel.textContent = group.label;
      container.appendChild(groupLabel);

      var rows = document.createElement("div");
      rows.className = "hcp-layer-rows";
      container.appendChild(rows);

      group.layers.forEach(function (lDef) {
        var row = document.createElement("label");
        row.className = "hcp-layer-row";

        var input = document.createElement("input");
        input.type = group.mode === "radio" ? "radio" : "checkbox";
        if (group.mode === "radio") {
          input.name = "hcp-layer-group-" + gIdx;
        }
        input.setAttribute("data-layer-name", lDef.name);

        var layer = overlays ? overlays[lDef.name] : null;
        input.checked = layer ? map.hasLayer(layer) : Boolean(lDef.visible);

        input.addEventListener("change", function () {
          if (!layer) return;
          if (input.checked) {
            if (!map.hasLayer(layer)) map.addLayer(layer);
          } else {
            if (map.hasLayer(layer)) map.removeLayer(layer);
          }
        });

        row.appendChild(input);
        var span = document.createElement("span");
        span.textContent = lDef.name;
        row.appendChild(span);
        rows.appendChild(row);
      });
    });
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
    if (layersContainer && config.layerGroups && config.layerGroups.length) {
      var layerOverlays = null;

      function setupLayerToggles() {
        layerOverlays = findOverlays();
        if (!layerOverlays) return false;
        buildLayerList(layersContainer, config.layerGroups, map, layerOverlays);
        wireLayerEvents(layersContainer, config.layerGroups, map, layerOverlays);
        return true;
      }

      if (!setupLayerToggles()) {
        var attempts = 0;
        (function retryLayers() {
          if (setupLayerToggles()) return;
          if (++attempts > 30) return;
          setTimeout(retryLayers, 100);
        })();
      }
    }

    /* --- Opacity slider -------------------------------------------------- */
    var slider = panel.querySelector("#hcp-opacity");
    var valueLabel = panel.querySelector("#hcp-opacity-value");
    var initialOpacity =
      typeof config.opacity === "number" ? config.opacity : 0.85;

    if (slider) {
      slider.value = String(Math.round(initialOpacity * 100));
      if (valueLabel) {
        valueLabel.textContent = Math.round(initialOpacity * 100) + "%";
      }
      slider.addEventListener("input", function () {
        var pct = parseFloat(slider.value) || 0;
        if (valueLabel) valueLabel.textContent = Math.round(pct) + "%";
        setOverlayOpacity(pct / 100);
      });
      setOverlayOpacity(initialOpacity);
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
        if (map.setView) map.setView(config.centre, config.zoomStart);
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

    /* --- Collapse / expand ---------------------------------------------- */
    var toggle = panel.querySelector("#hcp-toggle");
    if (toggle) {
      toggle.addEventListener("click", function () {
        var collapsed = panel.classList.toggle("hcp-collapsed");
        toggle.textContent = collapsed ? "\u2026" : "\u2212";
      });
    }
  }

  global.initHeatmapControlPanel = init;
})(window);
