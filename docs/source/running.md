# Running caldip

## The two main commands

caldip has two subcommands that operate on the same YAML configuration file but produce different outputs.

| Command | Output | Use for |
|---------|--------|---------|
| `caldip plot` | Interactive HTML plot | Visual inspection, QC at sea |
| `caldip stats` | Summary + detailed statistics CSVs | Quantitative calibration offsets |

Both accept either a path to the YAML file or the cast directory (caldip will find the YAML automatically).

---

## caldip plot

Generates an interactive Plotly time series showing all instruments alongside the CTD reference, with bottle stop periods highlighted.

```bash
caldip plot <config_path> [options]
```

**Key options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--output NAME` | — | Base filename for the HTML file (no extension; `_plot.html` is appended) |
| `-o DIR` | parent of cast dir | Directory to write the HTML file |
| `--title TEXT` | from config | Plot title |
| `--threshold FLOAT` | 10.0 | Bottle stop detection threshold (dbar/min) |
| `--min-duration FLOAT` | 180.0 | Minimum bottle stop duration (seconds) |
| `--no-bottle-stops` | — | Disable bottle stop markers |
| `--show` | — | Open browser even when `--output` is set |

> **Note:** `caldip plot` does not have a `--ctd-sensor` flag — it always shows all CTD channels. Sensor selection only applies to `caldip stats`.

**Example:**

```bash
caldip plot moor/proc_calib/msm142_2026/cal_dip/castM4/castM4.caldip.yaml \
    --output castM4 -o outputs/ \
    --title "castM4: Instruments vs CTD"
```

This writes `outputs/castM4_plot.html`.

### Inspecting a bottle stop in the plot

The plot has three synchronised panels (pressure, temperature, conductivity). To check instrument agreement within a single bottle stop:

1. Find the bottle stop in the **pressure panel** — it appears as a flat segment flanked by blue (start) and red (end) vertical lines.
2. Click and drag across that flat segment in the pressure panel to zoom in. All three panels zoom together on the time axis.
3. Check that instrument temperatures (and conductivities, if available) lie close to the CTD reference (black) within that window.
4. Double-click anywhere to zoom back out.

Zooming on the pressure panel first makes it easy to confirm the CTD was actually stationary, before checking the temperature and conductivity agreement.

---

## caldip stats

Detects bottle stops, computes per-instrument statistics during each stop, and writes CSV and timing output.

```bash
caldip stats <config_path> [options]
```

**Key options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--ctd-sensor {1,2}` | from YAML, else 1 | Which CTD sensor pair to use |
| `--output NAME` | cast name from YAML | Base filename for output files (no extension) |
| `-o DIR` | parent of cast dir | Directory for all output files |
| `--threshold FLOAT` | 10.0 | Bottle stop detection threshold (dbar/min) |
| `--min-duration FLOAT` | 180.0 | Minimum bottle stop duration (seconds) |

**Example:**

```bash
caldip stats moor/proc_calib/msm142_2026/cal_dip/castM4/castM4.caldip.yaml \
    --ctd-sensor 2 -o outputs/
```

This writes three files to `outputs/`:
- `castM4_summary_statistics.csv`
- `castM4_detailed_statistics.csv`
- `castM4_timing.txt`

See [Outputs](outputs.md) for a description of all columns.

### Choosing the CTD sensor

CTD rosettes typically carry two independent sensor packages. Use `--ctd-sensor 2` (secondary) if the primary sensor had problems during the cast. You can also set `ctd_sensors: 2` in the YAML so the default is applied automatically without passing the flag each time.

> **Gotcha — sensor consistency:** `caldip plot` has no `--ctd-sensor` flag and always shows all CTD data. If you run `caldip stats --ctd-sensor 2`, verify in the plot that sensor 2 is the one that looks correct (no spikes, not flagged during the cast) or that sensor 2 is the one confirmed better by checks with a stable thermistor (temperature) or salinometer values.

> **Gotcha — threshold/duration consistency:** If you change `--threshold` or `--min-duration` from the defaults, apply the same values to both `caldip plot` and `caldip stats`. Otherwise the bottle stops shown in the plot will not match those used to compute the statistics.

> **Gotcha — rerunning after CTD reprocessing:** If the CTD `.cnv` file is updated (spike removal, pressure drift correction, conductivity slope corrections, sensor swap), regenerate all `caldip stats` outputs for that cast. 

---

## Batch processing a cruise

`generate_all_caldip_plots.sh` is a shell script that runs both commands for every cast in a cruise.
Copy and edit it for each cruise, uncommenting casts as their data become available.

### Template

```bash
#!/usr/bin/env bash
# Generate caldip plots and statistics for cruise msm142_2026
# Requires: pip install -e .

CTD_SENSOR=2
CRUISE=msm142_2026
DATA=moor/proc_calib/${CRUISE}/cal_dip

echo "Generating plots and statistics (CTD sensor ${CTD_SENSOR})..."

# castM3
caldip plot  ${DATA}/castM3/ --output castM3 -o outputs/ --title "castM3: Instruments vs CTD"
caldip stats ${DATA}/castM3/ --output castM3 -o outputs/ --ctd-sensor ${CTD_SENSOR}

# castM4
caldip plot  ${DATA}/castM4/ --output castM4 -o outputs/ --title "castM4: Instruments vs CTD"
caldip stats ${DATA}/castM4/ --output castM4 -o outputs/ --ctd-sensor ${CTD_SENSOR}

# castM5 — uncomment when data are available
# caldip plot  ${DATA}/castM5/ --output castM5 -o outputs/ --title "castM5: Instruments vs CTD"
# caldip stats ${DATA}/castM5/ --output castM5 -o outputs/ --ctd-sensor ${CTD_SENSOR}

echo "Done. Outputs written to outputs/"
```

### Switching CTD sensor

To reprocess an entire cruise with the other sensor, change `CTD_SENSOR=2` to `CTD_SENSOR=1` at the top and rerun.
Comment out any casts you do not want to reprocess.

### Adding a new cast

1. Create the cast directory and copy instrument files into it.
2. Run `caldip init` to create the stub YAML (see [Quickstart](quickstart.md)):
   ```bash
   caldip init moor/proc_calib/msm142_2026/cal_dip/castM5/
   ```
3. Fill in the YAML fields (deployment/recovery times, clock offsets).
4. Add the cast block to the script and run.
