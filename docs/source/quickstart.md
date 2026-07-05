# Quickstart: single cast

This guide walks through setting up and running caldip for one calibration dip cast from scratch.

## Prerequisites

Install the package (see [Installation](installation.md)):

```bash
pip install -r requirements-dev.txt
pip install -e .
```

---

## Directory structure

Each cast needs its own folder containing:

```
moor/proc_calib/{cruise_id}/cal_dip/cast{ID}/
├── {mooring_id}.caldip.yaml        ← you create this
├── {cast}.cnv                      ← CTD reference cast (1 Hz, SBE processed)
├── {serial}_{date}.hex             ← one file per SBE37 MicroCAT
├── {serial}_{date}.mat             ← one file per RBR thermistor
└── ...
```

All instrument data files must be in the **same folder** as the YAML.
The `directory` field in the YAML tells caldip where that folder is.

---

## Step 1 — Generate a stub YAML

Point `caldip init` at the cast folder and it will scan for recognised instrument files and write a skeleton configuration:

```bash
caldip init moor/proc_calib/msm142_2026/cal_dip/castM4/
```

Open the resulting YAML and fill in any fields left as `null` or `.nan`:
- `deployment_time` and `recovery_time` (from the ship's CTD log)
- `latitude` / `longitude`
- `clock_offset` for any instrument whose clock was not set to UTC before deployment
- `ctd_sensors` — which CTD sensor pair to use (`1` = primary, `2` = secondary)

See the [YAML configuration reference](configuration.md) for a full field description.

---

## Step 2 — Generate the interactive plot

```bash
caldip plot moor/proc_calib/msm142_2026/cal_dip/castM4/castM4.caldip.yaml \
    --output castM4 -o outputs/
```

This produces a self-contained HTML file (`outputs/castM4_plot.html`) you can open in any browser.
No internet required — the file works at sea.

If you omit `--output` and `-o`, the plot opens interactively in your browser instead.

**Inspecting a bottle stop in the plot:** The plot has three synchronised panels (pressure, temperature, conductivity). To check instrument agreement within a single bottle stop:

1. Find the bottle stop in the **pressure panel** — it appears as a flat segment flanked by blue (start) and red (end) vertical lines.
2. Click and drag across that flat segment in the pressure panel to zoom in. All three panels zoom together on the time axis.
3. Check that instrument temperatures (and conductivities, if available) lie close to the CTD reference (black) within that window.
4. Double-click anywhere to zoom back out.

---

## Step 3 — Generate statistics

```bash
caldip stats moor/proc_calib/msm142_2026/cal_dip/castM4/castM4.caldip.yaml \
    --ctd-sensor 2 -o outputs/
```

This writes three files to `outputs/`:
- `castM4_summary_statistics.csv` — one row per instrument (deepest bottle stop)
- `castM4_detailed_statistics.csv` — one row per instrument per bottle stop
- `castM4_timing.txt` — bottle stop start/end times and pressures

---

## Choosing the CTD sensor (`--ctd-sensor`)

CTD rosettes typically carry two independent sensor packages (primary=1, and secondary=2). Use `--ctd-sensor 2` (secondary) if it is the more accurate sensor package.

> **Important:** `--ctd-sensor` only applies to `caldip stats` — the plot always shows both primary and secondary CTD data. Set `ctd_sensors: 2` in the YAML to make sensor 2 the default for that cast, so you do not have to pass the flag each time.

| Flag | Sensor |
|------|--------|
| `--ctd-sensor 1` | Primary (default) |
| `--ctd-sensor 2` | Secondary |

> **Rerunning after CTD reprocessing:** If the CTD `.cnv` file is updated (spike removal, pressure correction, salinity calibration, sensor swap), regenerate both the plot and statistics for corrections to be applied to moored instruments.