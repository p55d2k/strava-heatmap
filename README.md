# Strava Activity Heatmap

A custom fork of the original Strava Activity Heatmap project by [Sam Wilson](https://github.com/moresamwilson/running-heatmap).

Turns a Strava data export into an interactive heatmap. No API needed - just the zip file Strava lets you download.

The output is a single HTML file with six layers you can switch between:

| Layer                | Colour         | Shows                                              |
| -------------------- | -------------- | -------------------------------------------------- |
| GPS Density (linear)   | Orange         | How often you've run each path                     |
| GPS Density (log)      | Orange         | Same, log scale - better when a few paths dominate |
| Pace (average)       | Blue           | Average pace - brighter = faster                   |
| Heart rate (average) | Red            | Average HR - brighter = higher                     |
| Gradient (absolute)  | White          | Steepness - brighter = steeper                     |
| Gradient (change)    | Green / purple | Direction - green = descending, purple = ascending |

## Setup

```bash
pip install -r requirements.txt
```

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
  "SPEED_MIN_MS": null,
  "SPEED_MAX_MS": null,
  "HR_MIN_BPM": null,
  "HR_MAX_BPM": null,
  "AUTO_RANGE_PCT": 5
}
```

Key settings:
- `ACTIVITY_TYPES`: `["Run"]`, `["Ride"]`, `["Run", "Ride"]`, etc. Verbose aliases are also accepted, e.g. `"Running"`, `"Cycling"`, `"Bike"`, `"Swimming"`, `"Walking"`, `"Hiking"`, `"Ski"`, `"Snowboarding"`, `"Kayaking"`, `"Stand Up Paddling"` — see `src/config.py` `ACTIVITY_TYPE_ALIASES` for the full list.
- `DATE_FROM` / `DATE_TO`: ISO dates or `null` for no limit
- `HOME_LAT` / `HOME_LON`: Override auto-detected home location
- `METERS_PER_PIXEL`: Resolution (lower = more detail). Use ~3 for runs, ~10 for rides.
- `RADIUS_KM` / `TRACK_CLIP_RADIUS_KM`: Filter radius around home

4. Run:
```bash
python main.py
```
Map is saved to `outputs/heatmap.html`.

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
