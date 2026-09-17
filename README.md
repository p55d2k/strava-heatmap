# Strava Activity Heatmap

A custom fork of the original Strava Activity Heatmap project by [Sam Wilson](https://github.com/moresamwilson/running-heatmap).

Turns a Strava data export into an interactive heatmap. No API needed just for the data - just the zip file Strava lets you download. (A free CARTO maps key is required for the basemap tiles.)

The output is a single HTML file with eight layers — three GPS-density views (one per raster mode, swapped by the panel's **Advanced** dropdown), a coverage layer, and four metrics — plus **Save as PNG**, **Export GeoJSON** and **Export GPX** buttons — and the filtered tracks re-exported as a GPX file next to the map (see below):

| Layer                      | Colour         | Shows                                              |
| -------------------------- | -------------- | -------------------------------------------------- |
| GPS Density (Time Spent)   | Orange         | Decay-weighted pass counts (log scale), so brightness reflects time spent per cell |
| GPS Density (Raw Passes)   | Orange         | Every GPS point increments its cell (raw sample density) |
| GPS Density (Unique Visits) | Orange        | Each activity contributes max 1 per cell (pure per-activity coverage) |
| Coverage (Places Visited)  | Orange         | Share of activities that visited each cell (a clean 1x–Nx gradient, no sqrt flattening) |
| Pace (average)             | Blue           | Average pace - brighter = faster                   |
| Heart rate (average)       | Red            | Average HR - brighter = higher                     |
| Gradient (absolute)        | White          | Steepness - brighter = steeper                     |
| Gradient (change)          | Green / purple | Direction - green = descending, purple = ascending |

The three **GPS Density (…)** layers are the same data rasterized three ways (see
`RASTER_MODE` below); all three are baked at build time, so switching between
them in the panel is instant. **Coverage (Places Visited)** always counts each
cell once per activity, regardless of `DECAY_FACTOR`.

In the on-map control panel, the **Heatmap** group shows just two density
concepts as a mutually-exclusive radio pair (only one can be shown at a time —
stacking them produces no meaningful result): **GPS Density** and **Coverage
(Places Visited)**. The single **GPS Density** row is bound to whichever
rasterization mode is picked in the collapsible **Advanced** section's dropdown
(**Time Spent** / **Raw Passes** / **Unique Visits**), so switching modes is an
instant swap of the pre-baked layer. The four metric layers (**Pace**, **Heart
rate**, **Gradient absolute**, **Gradient change**) can each be toggled on and
overlaid on the density heatmap.

Each layer toggle also shows how much data it carries: a muted count on the right
of the row, so a layer's size is visible before it is switched on. **Raw GPS
tracks** counts the tracks themselves, while the density and coverage layers
count the activities they were rasterized from. The metric layers count only the
activities whose devices actually recorded that metric, so **Heart rate** or a
**Gradient** layer can read noticeably lower than the activity total when some
devices recorded no heart rate or elevation.

Raw GPS tracks are a separate checkbox. The home location is marked with a
google-maps-style pin that scales with zoom — it is on by default and can be
hidden via the **Home marker** checkbox in the panel.

Controls that aren't self-explanatory — the basemap, each layer toggle, the
heatmap raster mode, the home marker and the opacity sliders — carry a small
**i** badge: hovering the control (or tabbing to it) opens a short,
plain-English card explaining what it does, so the map is usable without knowing
anything about the underlying data pipeline.

The **Save as PNG** button below the map actions exports the current view as a
static image: the basemap, every layer you have turned on (including raw GPS
tracks), the map attribution and the legend are rendered to a PNG and downloaded
as `heatmap.png`, entirely in the browser. The rendering library (html2canvas)
is fetched from a CDN the first time you click the button, so the page loads
exactly as before and the button reports a clear error if the library cannot be
reached. Basemap tiles are requested with CORS (CARTO allows this) so the canvas
stays readable and can actually be saved.

Two details keep the exported picture clean:

- **The map is held still for the capture.** Tiles that shuffle mid-render smear
the image, so a zoom or pan that is already in flight is waited out (the status
line says so), any glide is cancelled, and drag / wheel / pinch / keyboard input
and the zoom buttons are switched off until the render finishes — then
everything is released again.- **The home marker is left out.** It points at a personal location and reads as
  a stray dot in a shared still image, so the export filters it out (it stays on
  the interactive map).

The **Export GeoJSON** button downloads the rasterized grids themselves as a
GeoJSON `FeatureCollection` (`heatmap.geojson`) for QGIS, Mapbox or any other
mapping tool. Every populated grid cell becomes one polygon in WGS84 lon/lat
(as RFC 7946 requires), carrying the data as properties:

| Property               | Meaning                                                            |
| ---------------------- | ------------------------------------------------------------------ |
| `passes_time_spent`    | Time Spent density: decay-weighted pass count per cell             |
| `passes_raw`           | Raw Passes: every GPS sample counted                               |
| `visits_unique`        | Unique Visits: activities that visited the cell (max 1 per activity) |
| `coverage_pct`         | Percentage of all activities that visited the cell                 |
| `pace_mps`             | Average speed, metres per second                                   |
| `heart_rate_bpm`       | Average heart rate, beats per minute                               |
| `gradient`             | Average absolute gradient (rise / run)                             |
| `elev_change_norm`     | Elevation change, normalized to −1…1 (negative = descending)       |

Density and metric values are the same Gaussian-blurred values the map paints,
so each cell reflects its surroundings rather than a single sample. A metric
with no samples in a cell is left out of that feature's properties entirely
rather than written as a misleading zero.

The grids are embedded in the HTML as an inert
`<script type="application/geo+json">` block, zlib-compressed and base64-encoded
(the same treatment the GPX export below gets): the browser never parses it on
load, so the map still opens quickly, and the button inflates it in the browser
and hands the text over as a download. That keeps the output a single
self-contained file, and the compression keeps a dense city-wide grid at a fine
`METERS_PER_PIXEL` from adding tens of MB to the HTML.

The **GPX track export** goes the other way: instead of the rasterized grid it
writes the activities themselves back out as a single GPX file
(`outputs/tracks.gpx`) — one `<trk>` per activity, named from its date and
activity name — so the exact rides/runs the heatmap was built from can be opened
in Garmin Connect, QGIS, OsmAnd or any other GPX tool. The file is rewritten on every `generate` run (its
name comes from `OUTPUT_GPX`), and can also be produced on its own, without
rebuilding the map:

```bash
uv run python main.py export-gpx --output runs.gpx
```

The export re-applies the same `ACTIVITY_TYPES`, `DATE_FROM` / `DATE_TO`,
`GPS_SPREAD_MIN_M` and `RADIUS_KM` filters as the map, so the tracks always match
the heatmap you are looking at. Each point carries latitude, longitude and
elevation; Strava's export files keep no per-point timestamps, so there are no
`<time>` elements, and heart rate and speed ride in Garmin's
`TrackPointExtension` — the de-facto place for them, since GPX 1.1 has no element
for either — so tools that understand the extension show them and the rest
ignore it. The GPX loader reads that extension back, so feeding this file (or a
Garmin/Strava one) back into the project keeps HR and speed instead of dropping
them; tracks cached by an older version are reparsed once on the next run.

The panel's **Export GPX** button downloads that same file without leaving the
page. The document travels with the HTML — zlib-compressed and base64-encoded in
an inert `<script type="application/gpx+xml">` block, because it is an order of
magnitude smaller that way (a ~180,000-point export is 22.7 MB of GPX and 2.3 MB
embedded) — and the button inflates it in the browser with the built-in
`DecompressionStream`, so what lands in your downloads folder is byte for byte
the file the build wrote. Unpacking happens on click and needs a browser with
`DecompressionStream` (Chrome 80+, Firefox 113+, Safari 16.4+); on an older one
the button says so instead of failing silently, and `outputs/tracks.gpx` is
always there regardless.

## Setup

```bash
uv sync
```

This creates (or updates) the project virtual environment in `.venv` and installs
the runtime and development dependencies from `pyproject.toml` and `uv.lock`.

### Environment: CARTO basemap API key (required)

The basemap tiles are served by [CARTO](https://carto.com/developers/tiles) and require an API key. Set it in a `.env` file (git-ignored):

```bash
cp .env.example .env
```

Then edit `.env` and add your key:

```
CARTO_API_KEY = default_public_xxxxxxxxxxxxxxxxxxxxx
```

> Get a free key at https://carto.com/developers/tiles and paste it into `CARTO_API_KEY`. If the key is missing or blank, the program will fail with a clear error.

## Usage

1. Request your data from Strava: **Settings → My Account → Download or Delete Your Account → Download Request**
2. Unzip the export and place the folder next to `config.json` (default folder name: `strava_export`)
3. Create a `config.json` (or copy from `example_configs/`):

```json
{
  "ACTIVITIES_DIR": "strava_export",
  "ACTIVITY_TYPES": ["Run"],
  "DATE_FROM": null,
  "DATE_TO": null,
  "HOME_LAT": null,
  "HOME_LON": null,
  "RADIUS_KM": 20.0,
  "GPS_SPREAD_MIN_M": 200,
  "METERS_PER_PIXEL": 10,
  "PADDING_M": 500,
  "TRACK_CLIP_RADIUS_KM": 50.0,
  "BLUR_SIGMA_PX": 2,
  "MAP_OPACITY": 0.85,
  "CARTO_STYLE": "dark_all",
  "SPEED_MIN_MS": null,
  "SPEED_MAX_MS": null,
  "HR_MIN_BPM": null,
  "HR_MAX_BPM": null,
  "AUTO_RANGE_PCT": 5,
  "MAX_CONSECUTIVE_SAME_CELL": 3,
  "DECAY_FACTOR": 0.5,
  "COVERAGE_NORMALIZATION": "pct"
}
```

Key settings:
- `ACTIVITY_TYPES`: `["Run"]`, `["Ride"]`, `["Run", "Ride"]`, etc. Verbose aliases are also accepted, e.g. `"Running"`, `"Cycling"`, `"Bike"`, `"Swimming"`, `"Walking"`, `"Hiking"`, `"Ski"`, `"Snowboarding"`, `"Kayaking"`, `"Stand Up Paddling"` — see `src/config.py` `ACTIVITY_TYPE_ALIASES` for the full list.
- `DATE_FROM` / `DATE_TO`: ISO dates or `null` for no limit
- `HOME_LAT` / `HOME_LON`: Override auto-detected home location
- `METERS_PER_PIXEL`: Resolution (lower = more detail). Use ~3 for runs, ~10 for rides.
- `RADIUS_KM` / `TRACK_CLIP_RADIUS_KM`: Filter radius around home
- `CARTO_STYLE`: Basemap style — one of `"dark_all"` (default), `"light_all"`, or `"voyager"`
- `MAX_CONSECUTIVE_SAME_CELL`: Maximum consecutive GPS points binned into the same grid cell before they are skipped (1–10, default `3`). Prevents a stationary stretch (e.g. a forgotten stop) from dominating the frequency layer.
- `DECAY_FACTOR`: Geometric decay (0.0–1.0) applied to repeated passes of the same cell *within a single activity*. `DECAY_FACTOR = 0` counts each cell once per activity (maximal spread); `DECAY_FACTOR = 1` counts every pass (inflates intensity for loops / out-and-backs). Only used by the `"decay"` raster mode. Default: `0.5`.
- `RASTER_MODE`: Which rasterization drives the **primary** density statistics (`max_passes` in the legend, log normalization). One of:
  - `"raw-count"` — every GPS point increments its cell (raw sample density).
  - `"decay"` (default) — exponential decay (`DECAY_FACTOR`) on repeated passes of the same cell within a single activity.
  - `"binary-per-activity"` — each activity contributes max 1 per cell (pure coverage).

  Regardless of the configured mode, **all three** GPS Density layers are always
  generated and selectable in the panel; `RASTER_MODE` only decides which one is
  visible at first paint.
- `COVERAGE_NORMALIZATION`: How the **Coverage (Places Visited)** layer is scaled. `"pct"` (default) = each cell shows the percentage of all activities that visited it; `"max"` = each cell is scaled relative to the most-visited cell (legacy behavior). Default: `"pct"`.
- `OUTPUT_GPX`: Name of the GPX track export written into `OUTPUT_DIR` on every run (default `tracks.gpx`). See the GPX section above.
The three GPS Density layers and the Coverage layer are shown as mutually-exclusive radio toggles in the control panel (only one density view at a time).

4. Run:
```bash
uv run python main.py
```
Map is saved to `outputs/heatmap.html`.

### CLI Commands

The CLI supports subcommands. If no subcommand is given, it defaults to `generate`.

- `generate` (default) — build the heatmap:
  ```bash
  uv run python main.py generate --config config.json --dry-run
  ```
  Use `--dry-run` to validate the config and show the activity count without generating the map.

- `validate` — load and validate `config.json`, check that the activities directory and
  `activities.csv` exist, and print a summary of the resolved settings:
  ```bash
uv run python main.py validate --config config.json
  ```

- `export-gpx` — re-export the filtered tracks as one GPX file without building the
  map. Applies the same filters as `generate` and writes to `OUTPUT_GPX` (or
  `--output`, including a path outside `OUTPUT_DIR`). Useful for handing your
  activities to another tool, or for re-exporting after only changing a filter:
  ```bash
uv run python main.py export-gpx --config config.json --output runs.gpx
  ```

Common options (`--config`, `--dev`) can be passed at the top level or on a subcommand:
```bash
uv run python main.py --config config.json --dry-run
uv run python main.py validate --config config.json --dev
```

### JSON Schema for config.json

A JSON Schema (`config.schema.json`) is auto-generated from the Pydantic model in `src/config_schema.py`. It provides IDE autocompletion and validation for `config.json` and `example_configs/*.json` (configured via `.vscode/settings.json`).

To regenerate the schema after changing `ConfigModel`:

```bash
uv run python scripts/generate_schema.py
```

The schema validates required fields (`ACTIVITIES_DIR`, `ACTIVITY_TYPES`), value constraints (e.g. `METERS_PER_PIXEL > 0`, `MAP_OPACITY` between 0 and 1), and types.

### Home detection
Home is auto-detected from the most common activity start point. Override with `HOME_LAT` / `HOME_LON` if needed.

### Caching
Parsing `.fit.gz` is slow; GPS data is cached after first run. Cache files are stored in `cache/`.

---

## Notes

- **GPS Density** measures time on path (GPS samples/pixel), not distinct passes. Log scale helps when a few routes dominate.
- **Pace & HR** are all-time averages per pixel. Narrow the date range for a specific period.
- **Gradient** layers are only as good as GPS altitude (±10–20 m vertical noise). Reliable on hills, noisy on flats.
- **Two projections**: Web Mercator (EPSG:3857) for tile alignment; UTM for true ground-metre calculations (clip radius, gradient).

---

## Contributing & License

Contributions welcome! Open an issue or PR.

Licensed under the MIT License — see [LICENSE](LICENSE) for details.
