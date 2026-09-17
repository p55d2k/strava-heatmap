# Strava Activity Heatmap

Turn a Strava data export into a self-contained, interactive activity heatmap.
No Strava API access is needed: the input is the ZIP file Strava provides. A
Basemap tiles work out of the box with OpenStreetMap. An optional
[CARTO maps key](https://carto.com/developers/tiles) enables the CARTO styles.

This is a custom fork of [Sam Wilson's original project](https://github.com/moresamwilson/running-heatmap).

## Features and outputs

Running the generator writes `outputs/heatmap.html`, a Leaflet map with:

- Three GPS-density views: **Time Spent**, **Raw Passes**, and **Unique Visits**.
  They are generated at build time and swapped instantly from the **Advanced**
  raster-mode menu.
- **Coverage (Places Visited)**, showing the percentage of activities that
  visited each cell.
- Optional metric overlays for average **Pace**, **Heart rate**, **Gradient
  (absolute)**, and **Gradient (change)**.
- **Raw GPS tracks**, a zoom-scaled home marker, basemap selection, opacity
  sliders, and controls with short hover/focus explanations.
- Browser-side **Save as PNG**, **Export GeoJSON**, and **Export GPX** actions.

| Layer | Colour | Shows |
| --- | --- | --- |
| GPS Density (Time Spent) | Orange | Decay-weighted pass counts (log scale); brightness reflects time spent per cell |
| GPS Density (Raw Passes) | Orange | Every GPS point increments its cell |
| GPS Density (Unique Visits) | Orange | Each activity contributes at most once per cell |
| Coverage (Places Visited) | Orange | Share of activities that visited each cell |
| Pace (average) | Blue | Average pace; brighter means faster |
| Heart rate (average) | Red | Average heart rate; brighter means higher |
| Gradient (absolute) | White | Steepness; brighter means steeper |
| Gradient (change) | Green / purple | Direction; green is descending and purple is ascending |

The GPS Density and Coverage layers are mutually exclusive in the panel.
Metric layers can be overlaid on the selected density view. Counts shown beside
each control indicate the data available to that layer: tracks count tracks,
density and coverage count source activities, and metric layers count only
activities that recorded that metric.

## Setup

```bash
uv tool install .
```

This installs the `strava-heatmap` command and its dependencies in an isolated
tool environment. If the command is not found afterward, run `uv tool update-shell`
and restart your shell.

### Optional CARTO basemap key

This step is optional. Without a key, OpenStreetMap tiles are used. To use
CARTO basemaps, copy the ignored environment-file template and add a key:

```bash
cp .env.example .env
```

```text
CARTO_API_KEY = your_key_here
```

Get a free key at <https://carto.com/developers/tiles>.

## Quick start

1. Request your data from Strava: **Settings → My Account → Download or Delete
   Your Account → Download Request**.
2. Unzip the export in the project directory. The generator automatically finds
   a folder containing `activities.csv`, detects activity types with GPS files,
   detects your most common start location, and chooses bounds from the data.
3. Generate the map:

```bash
strava-heatmap generate
```

The map is saved to `outputs/heatmap.html`; the filtered tracks are also
written to `outputs/tracks.gpx` by default.

## Automatic defaults

These settings are inferred or chosen automatically and normally need no
configuration:

- the export directory and activity types with GPS files;
- the most common activity start as home;
- a local activity radius that excludes exceptional travel;
- map bounds from the selected tracks and a bounded raster resolution;
- cache/output directories, date bounds, filtering, styling, and exports.

## Optional configuration

Most users do not need a config file. Create a partial `config.toml` only when
you want to override a setting; unspecified values keep the automatic defaults.
TOML is the primary configuration format. Existing JSON configuration files
continue to work for compatibility and can still be passed with `--config`.
The complete `example_configs/config.toml` file lists every available option.

```toml
ACTIVITY_TYPES = ["Run", "Ride"]
DATE_FROM = "2024-01-01"
METERS_PER_PIXEL = 5
OUTPUT_HTML = "my_heatmap.html"
```

Copy `example_configs/config.toml` when you want a starting point containing
every option, then remove or change the values you do not need.

When no `--config` is supplied, `config.toml` is loaded if present. An existing
`config.json` is still used as a compatibility fallback. Pass a different file
with `--config path/to/config.toml` (or a legacy `.json` file). Use
`strava-heatmap validate` to check the export and effective settings.

## Configuration

### Common settings

| Setting | Description |
| --- | --- |
| `ACTIVITY_TYPES` | Activity types such as `["Run"]`, `["Ride"]`, or `["Run", "Ride"]`. Verbose aliases are accepted, including `"Running"`, `"Cycling"`, `"Bike"`, `"Swimming"`, `"Walking"`, `"Hiking"`, `"Ski"`, `"Snowboarding"`, `"Kayaking"`, and `"Stand Up Paddling"`; see `src/config.py` and `ACTIVITY_TYPE_ALIASES` for the full list. |
| `DATE_FROM` / `DATE_TO` | ISO date bounds, or `null` for no bound. |
| `HOME_LAT` / `HOME_LON` | Override the automatically detected home location. |
| `RADIUS_KM` / `TRACK_CLIP_RADIUS_KM` | Optional activity-selection and track-clipping radii around home. `RADIUS_KM` is inferred from the export when omitted; use `null` explicitly to include all activities. |
| `GPS_SPREAD_MIN_M` | Minimum GPS spread used when selecting activities. |
| `METERS_PER_PIXEL` | Grid resolution; lower values add detail and file size. Use about `3` for runs and `10` for rides. |
| `PADDING_M` | Padding around the calculated map bounds. |
| `BLUR_SIGMA_PX` | Gaussian blur radius in pixels. |
| `MAP_OPACITY` | Heatmap opacity from `0` to `1`. |
| `CARTO_STYLE` | `dark_all` (default), `light_all`, or `voyager`. |
| `SPEED_MIN_MS` / `SPEED_MAX_MS` | Speed filters in metres per second, or `null`. |
| `HR_MIN_BPM` / `HR_MAX_BPM` | Heart-rate filters in BPM, or `null`. |
| `AUTO_RANGE_PCT` | Percentile used for automatic colour ranges; lower values increase contrast. |
| `MAX_CONSECUTIVE_SAME_CELL` | Maximum consecutive GPS points in one cell before they are skipped; minimum `1`, default `3`. Helps prevent stationary stops dominating the frequency layer. |

### Advanced settings

The remaining processing, filtering, path, and embed settings are supported for
custom workflows and debugging. Their defaults and validation are defined in
`src/config_schema.py`.

### Density and coverage

`RASTER_MODE` controls the primary GPS Density statistics (including
`max_passes` in the legend and log normalization). All three density layers are
always generated; this setting selects the initially visible one:

| Value | Meaning |
| --- | --- |
| `"decay"` (default) | Repeated passes of a cell within one activity receive geometric decay controlled by `DECAY_FACTOR`. |
| `"raw-count"` | Every GPS point increments its cell. |
| `"binary-per-activity"` | Each activity contributes at most once per cell. |

`DECAY_FACTOR` is `0.0–1.0` and applies only to `"decay"`: `0` counts each cell
once per activity, while `1` counts every pass. `COVERAGE_NORMALIZATION` is
`"pct"` (default), where each cell is the percentage of all activities visiting
it, or `"max"` for the legacy scale relative to the most-visited cell.

### Files and paths

All path settings are relative to the project root unless an absolute path is
provided.

| Setting | Default | Purpose |
| --- | --- | --- |
| `ACTIVITIES_DIR` | `strava_export` | Strava export directory |
| `ACTIVITIES_CSV` | `activities.csv` | CSV filename inside `ACTIVITIES_DIR` |
| `CACHE_DIR` | `cache` | Cached parsed activity data |
| `CACHE_FILE` | `cache.pkl` | Cache filename inside `CACHE_DIR` |
| `OUTPUT_DIR` | `outputs` | Generated files |
| `OUTPUT_HTML` | `heatmap.html` | Main map filename |
| `OUTPUT_GPX` | `tracks.gpx` | GPX filename written on every `generate` run |

## CLI

The CLI defaults to `generate` when no subcommand is supplied. `--config` and
`--dev` can be passed globally or on a subcommand.

```bash
# Generate (default); --dry-run validates and prints the activity count
strava-heatmap generate --config config.toml --dry-run

# Validate config.toml, the activities directory, and activities.csv
strava-heatmap validate --config config.toml

# Re-export filtered tracks without rebuilding the map
strava-heatmap export-gpx --config config.toml --output runs.gpx

# Equivalent global-option forms
strava-heatmap --config config.toml --dry-run
strava-heatmap validate --config config.toml --dev
```

`--no-open` prevents generated maps from opening automatically in a browser.
`--embed` also builds the iframe widget for that run.

## Exports

### PNG

**Save as PNG** captures the current map view to `heatmap.png`, including the
basemap, enabled layers, attribution, and legend. It runs in the browser and
loads `html2canvas` from a CDN on the first click. CARTO tiles use CORS so they
remain readable in the canvas.

During capture, in-flight movement is allowed to finish, gliding is cancelled,
and map input and zoom controls are disabled until rendering completes. The
home marker is intentionally omitted from the image because it identifies a
personal location; it remains visible on the interactive map.

### GeoJSON

**Export GeoJSON** downloads `heatmap.geojson` as an RFC 7946 WGS84
`FeatureCollection`. Each populated grid cell is a polygon. Values are the
same Gaussian-blurred values rendered by the map; metrics without samples are
omitted rather than written as zero.

| Property | Meaning |
| --- | --- |
| `passes_time_spent` | Decay-weighted pass count per cell |
| `passes_raw` | Raw GPS samples per cell |
| `visits_unique` | Activities visiting the cell, at most once per activity |
| `coverage_pct` | Percentage of all activities visiting the cell |
| `pace_mps` | Average speed in metres per second |
| `heart_rate_bpm` | Average heart rate in BPM |
| `gradient` | Average absolute gradient (rise / run) |
| `elev_change_norm` | Elevation change normalized to `-1…1` (negative is descending) |

The grid is embedded in the HTML as an inert
`<script type="application/geo+json">` block, zlib-compressed and base64-encoded.
It is inflated only when the button is clicked, keeping the output
self-contained without slowing initial page load.

### GPX

`generate` writes one `<trk>` per filtered activity to `OUTPUT_GPX` (default
`outputs/tracks.gpx`), named from its date and activity name. The standalone
command is useful when only filters changed:

```bash
strava-heatmap export-gpx --output runs.gpx
```

The export applies the same `ACTIVITY_TYPES`, `DATE_FROM` / `DATE_TO`,
`GPS_SPREAD_MIN_M`, and `RADIUS_KM` filters as the map. Points include latitude,
longitude, and elevation. Strava exports do not retain per-point timestamps, so
there are no `<time>` elements. Heart rate and speed use Garmin's
`TrackPointExtension`; compatible tools display them and other tools ignore them.
The loader reads this extension, so re-importing this file preserves HR and
speed. Tracks cached by an older version are reparsed once on the next run.

The map's **Export GPX** button downloads the same build-produced file from the
page. It is zlib-compressed and base64-encoded in an inert
`<script type="application/gpx+xml">` block, then inflated with the browser's
built-in `DecompressionStream` on click. This requires Chrome 80+, Firefox 113+,
or Safari 16.4+; `OUTPUT_GPX` is always available on disk.

## Embeddable widget

Use `--embed` or set `EMBED_ENABLED` to build `OUTPUT_DIR/heatmap_embed.html`.
The widget is a minimal, interactive Leaflet map without the control panel,
layer control, scale bar, hidden-layer payloads, GeoJSON, or GPX. It includes
the configured raster mode and only the layers selected for embedding, keeping
it much smaller than the full page. Visitors can pan, zoom, scroll, and pinch;
the initial view is framed to the data bounds.

| Setting | Default | Effect |
| --- | --- | --- |
| `EMBED_ENABLED` | `false` | Build the widget on every run; `--embed` enables it once |
| `EMBED_HTML` | `heatmap_embed.html` | Widget filename in `OUTPUT_DIR` |
| `EMBED_LEGEND` | `true` | Include the colour legend |
| `EMBED_ATTRIBUTION` | `true` | Include tile attribution; required by CARTO/OpenStreetMap terms |
| `EMBED_HOME_MARKER` | `true` | Include the home marker |
| `EMBED_TRACKS` | `false` | Draw raw GPS tracks |
| `EMBED_METRICS` | `[]` | Metric layers to include and show: full names or `pace`, `heart_rate`, `gradient`, `elev_change` |
| `EMBED_DEMO` | `true` | Write a responsive demo page beside the widget |

The widget's density layer follows `RASTER_MODE`. Because it has no toggles,
`EMBED_METRICS` both ships and displays its named layers; each extra layer is a
base64 PNG, so keep the list short. The demo is named from `EMBED_HTML` with a
`_demo` suffix.

```bash
strava-heatmap --embed
```

This leaves `outputs/heatmap.html` unchanged and adds
`outputs/heatmap_embed.html` and, by default,
`outputs/heatmap_embed_demo.html`. Embed the widget with a fluid wrapper:

```html
<div style="position:relative;width:100%;aspect-ratio:16/10">
  <iframe src="heatmap_embed.html" title="Strava activity heatmap"
          loading="lazy"
          style="position:absolute;inset:0;width:100%;height:100%;border:0">
  </iframe>
</div>
```

Give the iframe a sensible fixed size. Because it zooms on scroll, consider
`scrolling="no"` or a click-to-activate overlay if wheel scrolling is
intrusive. Keep `EMBED_ATTRIBUTION` enabled.

## Schema, caching, and technical notes

`config.schema.json` is generated from the Pydantic model in
`src/config_schema.py`. It remains available for tools that validate legacy
JSON configuration files; TOML is the primary format documented above.

```bash
uv run python scripts/generate_schema.py
```

Home is auto-detected from the most common activity start point and can be
overridden with `HOME_LAT` / `HOME_LON`. Parsing `.fit.gz` files is slow, so GPS
data is cached in `cache/` after the first run.

- GPS Density represents GPS samples/pixel and time on path, not distinct passes;
  log scaling helps when a few routes dominate.
- Pace and heart-rate layers are all-time per-pixel averages; use date bounds
  for a specific period.
- Gradient quality depends on GPS altitude (about ±10–20 m vertical noise):
  reliable on hills and noisy on flats.
- Web Mercator (EPSG:3857) aligns with tile rendering; UTM is used for
  ground-metre calculations such as clipping and gradient.

## Contributing and license

Contributions are welcome; please open an issue or pull request. Licensed under
the MIT License; see [LICENSE](LICENSE).
