# Running caldip

## The main commands

`caldip plot` and `caldip stats` operate on the same YAML configuration file but produce different outputs. `caldip report` gathers their outputs for a whole cruise into a browsable HTML report.

| Command | Output | Use for |
|---------|--------|---------|
| `caldip plot` | Interactive HTML plot | Visual inspection, QC at sea |
| `caldip stats` | Summary + detailed statistics CSVs | Quantitative calibration offsets |
| `caldip report` | Per-cruise HTML report (index + per-cast pages) | Reviewing a whole cruise at once |

`plot` and `stats` accept either a path to the YAML file or the cast directory (caldip will find the YAML automatically). `report` takes the directory the CSVs and plots were written to.

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
| `-o DIR`, `--output-dir DIR` | parent of cast dir | Directory to write the HTML file |
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
| `-o DIR`, `--output-dir DIR` | parent of cast dir | Directory for all output files |
| `--threshold FLOAT` | 10.0 | Bottle stop detection threshold (dbar/min) |
| `--min-duration FLOAT` | 180.0 | Minimum bottle stop duration (seconds) |

**Example:**

```bash
caldip stats moor/proc_calib/msm142_2026/cal_dip/castM4/castM4.caldip.yaml \
    --ctd-sensor 2 -o outputs/
```

This writes to `outputs/`:
- `castM4_caldip.nc` — the machine-readable statistics (the primary output)
- `castM4_detailed_statistics.csv` — a CSV export of the netCDF
- `castM4_summary_statistics.csv`
- `castM4_timing.txt`

See [Outputs](outputs.md) for a description of the variables and columns.

### Choosing the CTD sensor

CTD rosettes typically carry two independent sensor packages. Use `--ctd-sensor 2` (secondary) if the primary sensor had problems during the cast. You can also set `ctd_sensors: 2` in the YAML so the default is applied automatically without passing the flag each time.

> **Gotcha — sensor consistency:** `caldip plot` has no `--ctd-sensor` flag and always shows all CTD data. If you run `caldip stats --ctd-sensor 2`, verify in the plot that sensor 2 is the one that looks correct (no spikes, not flagged during the cast) or that sensor 2 is the one confirmed better by checks with a stable thermistor (temperature) or salinometer values.

> **Gotcha — threshold/duration consistency:** If you change `--threshold` or `--min-duration` from the defaults, apply the same values to both `caldip plot` and `caldip stats`. Otherwise the bottle stops shown in the plot will not match those used to compute the statistics.

> **Gotcha — rerunning after CTD reprocessing:** If the CTD `.cnv` file is updated (spike removal, pressure drift correction, conductivity slope corrections, sensor swap), regenerate all `caldip stats` outputs for that cast. 

---

## caldip report

```
caldip report <results_dir> [options]
```

`caldip report` reads the CSVs and saved plots that `caldip stats` and `caldip plot` already wrote for a cruise, and builds a browsable HTML report: a per-cruise index listing every cast, and one page per cast with its summary table, per-stop detail, and the interactive figure. It reads only files already on disk — no reprocessing, no access to the raw instrument data needed.

`results_dir` is the directory those outputs were written to (the cruise `cal_dip/` folder by default, or wherever `-o` sent them).

| Option | Meaning |
|--------|---------|
| `--output-dir DIR`, `-o DIR` | Where to write the report (default: `<results_dir>/report`) |
| `--cruise NAME` | Cruise label for the index heading (default: inferred from the path) |

```
caldip report data/proc_calib/odb_2026/cal_dip/
caldip report outputs/ --cruise msm142_2026 -o reports/msm142_2026
```

Every page ends with a footer naming caldip, its version and the UTC time the page was generated. The report is a self-contained folder: `index.html`, a `casts/` subfolder of per-cast pages, and one shared `plotly.min.js`. Open `index.html` in a browser; it works offline. It is a folder rather than single files because the figures are interactive Plotly sharing one bundle — which also means there is no print/PDF version: a headless renderer will not run the figure script, so a printed cast page has no figure. If PDF is ever needed, the figures would have to be saved as static images alongside the interactive ones.

**Index findings.** The index's "Flagged by caldip" column counts *instruments* (not stops) that caldip marked as reading high or low, using its configured thresholds — it is not an absolute pass/fail. Variables an instrument does not measure (for example conductivity on a temperature-only RBRsolo) are not counted as flags. A Cruise column is always shown, read per cast from its `{cast}_caldip.nc` (`UNK` when the netCDF is absent); it is the cruise recorded with that cast, which need not match the report heading when a directory mixes casts from more than one cruise (the heading then reads `multiple cruises`).

**Cast pages.** Each cast page shows the interactive figure, a **CTD reference** block, a bottle-stops table (pressure and the comparison-period times, deepest first), the deepest-stop summary, and the full per-stop detail. The CTD reference block names the CTD sensor used for the comparison (primary or secondary) and its provenance — reference file, data mode, and, when the reference is a ctdcast netCDF, the temperature and conductivity sensor serials, calibration dates and any conductivity slope applied. These are constant for the cast, so they are stated once here rather than repeated on every detail row. Table headers use compact symbols with units on a second line (`ΔT` °C, `σ`​`C` mS/cm, `⟨ΔP⟩` dbar, …); `Δ` is instrument − CTD. Per-stop rows caldip flagged as out of tolerance are shaded amber.

> **Gotcha — regenerate plots after upgrading plotly:** the report reuses the figure saved in each `{cast}_plot.html`, but loads the Plotly library once at report level from the installed version. If a saved plot was made with a different Plotly version, `caldip report` warns and that figure may render blank; re-run `caldip plot` for the affected cast.

### Checking finality (`--check`)

`caldip report --check <path>` answers, for a cruise, "should any casts be re-run?" — one line per cast, and a non-zero exit code if any cast is not `final`, so it fits a post-cruise checklist or CI. It reads recorded values against current ones (never file mtimes): the config against the output (`ctd_file`, `ctd_sensor`, thresholds, and a `config_digest` over the instrument list and clock offsets), the output against the CTD reference file it recorded, and the two finality gates — the reference is delayed-mode (`data_mode = D`) and its `preferred_pair` is declared.

`<path>` is either a `caldip.cruise.yaml` (casts are discovered under its `cal_dip` directory) or a directory of per-cast configs; add `--nc-dir` if the `{cast}_caldip.nc` outputs are not beside the configs. States: `final` (done, never asked again), `waiting on reference` (output current, reference not yet finalised), `rerun needed` (config or reference changed since the run), `not run`, `no reference (cnv input)`, `unknown`. The same recorded-vs-now comparison is shown per attribute on each cast's `caldip inspect` inventory page.

```bash
caldip report --check data/proc_calib/msm142_2026/caldip.cruise.yaml
caldip report --check data/proc_calib/msm142_2026/cal_dip/ --nc-dir outputs/
```

A **cruise YAML** (`caldip.cruise.yaml`, placed at the cruise directory) holds the per-cruise facts — `cruise`, `ship`, `year`, and the `cal_dip` directory — so they live in one place instead of being repeated (and drifting) across every per-cast config. A per-cast config inherits them from the nearest cruise YAML; a per-cast value that disagrees warns and the cruise value wins.

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
