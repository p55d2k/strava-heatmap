# Strava Activity Heatmap

A custom fork of the original Strava Activity Heatmap project by [Sam Wilson](https://github.com/moresamwilson/running-heatmap).

Turns a Strava data export into an interactive heatmap. No API needed just for the data - just the zip file Strava lets you download. (A free CARTO maps key is required for the basemap tiles.)

The output is a single HTML file with six layers — two GPS-density concepts plus four metrics:

| Layer                     | Colour         | Shows                                              |
| ------------------------- | -------------- | -------------------------------------------------- |
| GPS Density (Time Spent)  | Orange         | Decay-weighted pass counts (log scale), so brightness reflects time spent on each path |
| Coverage (Places Visited) | Orange         | Share of activities that visited each cell (a clean 1x–Nx gradient, no sqrt flattening) |
| Pace (average)            | Blue           | Average pace - brighter = faster                   |
| Heart rate (average)      | Red            | Average HR - brighter = higher                     |
| Gradient (absolute)       | White          | Steepness - brighter = steeper                     |
| Gradient (change)         | Green / purple | Direction - green = descending, purple = ascending |

The two density concepts are independent layers:

- **GPS Density (Time Spent)** is shown by default and weights how often you
  revisit a cell within a single activity using `DECAY_FACTOR` (0.0 counts each
  cell once per activity for maximal spread; 1.0 counts every pass).
- **Coverage (Places Visited)** always counts each cell once per activity,
  regardless of `DECAY_FACTOR`.

In the on-map control panel, the two density concepts are a mutually-exclusive
radio pair (only one can be shown at a time — stacking them produces no meaningful
result), labelled **Time Spent** / **Places Visited** in the toggle. The four
metric layers (**Pace**, **Heart rate**, **Gradient absolute**,
**Gradient change**) can each be toggled on and overlaid on the density heatmap.
Raw GPS tracks are a separate checkbox.

## Setup

```bash
pip install -r requirements.txt
```

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
- `DECAY_FACTOR`: Geometric decay (0.0–1.0) applied to repeated passes of the same cell *within a single activity*. `DECAY_FACTOR = 0` counts each cell once per activity (maximal spread); `DECAY_FACTOR = 1` counts every pass (inflates intensity for loops / out-and-backs). Controls the **GPS Density (Time Spent)** layer only; **Coverage (Places Visited)** always counts each cell once per activity regardless of this value. Default: `0.5`.
- `COVERAGE_NORMALIZATION`: How the **Coverage (Places Visited)** layer is scaled. `"pct"` (default) = each cell shows the percentage of all activities that visited it; `"max"` = each cell is scaled relative to the most-visited cell (legacy behavior). Default: `"pct"`.
Two GPS density concept layers are always shown as independent toggles in the control panel:
  - **GPS Density (Time Spent)** (default-on): decay-weighted pass counts on a log scale, driven by `DECAY_FACTOR`.
  - **Coverage (Places Visited)**: each cell counted once per activity (pure coverage, no intensity from re-visits), on a linear scale by percentage of activities (or relative to max visits when `COVERAGE_NORMALIZATION: "max"`).

4. Run:
```bash
python main.py
```
Map is saved to `outputs/heatmap.html`.

### CLI Commands

The CLI supports subcommands. If no subcommand is given, it defaults to `generate`.

- `generate` (default) — build the heatmap:
  ```bash
  python main.py generate --config config.json --dry-run
  ```
  Use `--dry-run` to validate the config and show the activity count without generating the map.

- `validate` — load and validate `config.json`, check that the activities directory and
  `activities.csv` exist, and print a summary of the resolved settings:
  ```bash
  python main.py validate --config config.json
  ```

Common options (`--config`, `--dev`) can be passed at the top level or on a subcommand:
```bash
python main.py --config config.json --dry-run
python main.py validate --config config.json --dev
```

### JSON Schema for config.json

A JSON Schema (`config.schema.json`) is auto-generated from the Pydantic model in `src/config_schema.py`. It provides IDE autocompletion and validation for `config.json` and `example_configs/*.json` (configured via `.vscode/settings.json`).

To regenerate the schema after changing `ConfigModel`:

```bash
python scripts/generate_schema.py
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
