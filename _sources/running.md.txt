# Running caldip

## The two main scripts

caldip has two entry-point scripts that operate on the same YAML configuration file but produce different outputs.

| Script | Output | Use for |
|--------|--------|---------|
| `caldip_plot_all.py` | Interactive HTML plot | Visual inspection, QC at sea |
| `caldip_check_all.py` | Summary + detailed statistics CSVs | Quantitative calibration offsets |

Both accept either a path to the YAML file or the cast directory (caldip will find the YAML automatically).

---

## caldip_plot_all.py

Generates an interactive Plotly time series showing all instruments alongside the CTD reference, with bottle stop periods highlighted.

```bash
python caldip_plot_all.py <config_path> [options]
```

**Key options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--output FILE` | — | Write to HTML file (omit to open in browser) |
| `--title TEXT` | from config | Plot title |
| `--ctd-sensor {1,2}` | 1 | Which CTD sensor pair to use |
| `--threshold FLOAT` | 30.0 | Bottle stop detection threshold (dbar/min) |
| `--min-duration FLOAT` | 120.0 | Minimum bottle stop duration (seconds) |
| `--no-bottle-stops` | — | Disable bottle stop markers |
| `--show` | — | Open browser even when `--output` is set |

**Example:**

```bash
python caldip_plot_all.py moor/proc_calib/msm142_2026/cal_dip/castM4/castM4.caldip.yaml \
    --output outputs/castM4_plot.html \
    --title "castM4: Instruments vs CTD (sensor 2)" \
    --ctd-sensor 2
```

---

## caldip_check_all.py

Detects bottle stops, computes per-instrument statistics during each stop, and writes CSV output.

```bash
python caldip_check_all.py <config_path> [options]
```

**Key options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--ctd-sensor {1,2}` | 1 | Which CTD sensor pair to use |
| `--output FILE` | auto | Path for the detailed statistics CSV |
| `--output-dir DIR` | cast directory | Directory for all output files |

**Example:**

```bash
python caldip_check_all.py moor/proc_calib/msm142_2026/cal_dip/castM4/castM4.caldip.yaml \
    --ctd-sensor 2 \
    --output-dir outputs/
```

See [Outputs](outputs.md) for a description of the CSV columns.

---

## Batch processing a cruise

`generate_all_caldip_plots.sh` is a shell script that runs both scripts for every cast in a cruise.
Copy and edit it for each cruise, uncommenting casts as their data become available.

### Template

```bash
#!/bin/bash
# Generate caldip plots and statistics for cruise msm142_2026
# Set CTD_SENSOR=1 for primary, CTD_SENSOR=2 for secondary

CTD_SENSOR=2
CRUISE=msm142_2026
DATA=moor/proc_calib/${CRUISE}/cal_dip

echo "Generating plots and statistics (CTD sensor ${CTD_SENSOR})..."

# castM3
python caldip_plot_all.py  ${DATA}/castM3/ --ctd-sensor ${CTD_SENSOR} \
    --output outputs/castM3_plot.html \
    --title "castM3: Instruments vs CTD (sensor ${CTD_SENSOR})"
python caldip_check_all.py ${DATA}/castM3/ --ctd-sensor ${CTD_SENSOR} \
    --output-dir outputs/

# castM4
python caldip_plot_all.py  ${DATA}/castM4/ --ctd-sensor ${CTD_SENSOR} \
    --output outputs/castM4_plot.html \
    --title "castM4: Instruments vs CTD (sensor ${CTD_SENSOR})"
python caldip_check_all.py ${DATA}/castM4/ --ctd-sensor ${CTD_SENSOR} \
    --output-dir outputs/

# castM5
# python caldip_plot_all.py  ${DATA}/castM5/ --ctd-sensor ${CTD_SENSOR} \
#     --output outputs/castM5_plot.html \
#     --title "castM5: Instruments vs CTD (sensor ${CTD_SENSOR})"
# python caldip_check_all.py ${DATA}/castM5/ --ctd-sensor ${CTD_SENSOR} \
#     --output-dir outputs/

echo "Done. Outputs written to outputs/"
```

### Switching CTD sensor

To reprocess an entire cruise with the other sensor, change `CTD_SENSOR=2` to `CTD_SENSOR=1` at the top and rerun.
Comment out any casts you do not want to reprocess.

### Adding a new cast

1. Create the cast directory and copy instrument files into it.
2. Run `generate_stub_yaml.py` to create the YAML (see [Quickstart](quickstart.md)).
3. Fill in the YAML fields.
4. Add the cast block to the script and run.
