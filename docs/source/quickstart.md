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

Point `generate_stub_yaml.py` at the cast folder and it will scan for recognised instrument files and write a skeleton configuration:

```bash
python generate_stub_yaml.py moor/proc_calib/msm142_2026/cal_dip/castM4/
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
python caldip_plot_all.py moor/proc_calib/msm142_2026/cal_dip/castM4/castM4.caldip.yaml \
    --output castM4_plot.html \
    --ctd-sensor 2
```

This produces a self-contained HTML file you can open in any browser.
No internet required — the file works at sea.

If you omit `--output`, the plot opens interactively in your browser instead.

---

## Step 3 — Generate statistics

```bash
python caldip_check_all.py moor/proc_calib/msm142_2026/cal_dip/castM4/castM4.caldip.yaml \
    --ctd-sensor 2 \
    --output-dir outputs/
```

This writes two CSV files to `outputs/`:
- `castM4_summary_statistics.csv` — one row per instrument, averaged across all bottle stops
- `castM4_detailed_statistics.csv` — one row per instrument per bottle stop

---

## Choosing the CTD sensor (`--ctd-sensor`)

CTD rosettes typically carry two independent sensor packages. Use `--ctd-sensor 2` (secondary) if the primary sensor had problems during the cast. The flag applies to both scripts and must match between plot and statistics runs to keep comparisons consistent.

| Flag | Sensor |
|------|--------|
| `--ctd-sensor 1` | Primary (default) |
| `--ctd-sensor 2` | Secondary |
