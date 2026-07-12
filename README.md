# 🌊 caldip

**Calibration dip analysis for oceanographic instruments**

Caldip provides tools for processing, analyzing, and visualizing data from calibration dips performed with CTD profiles and multiple instrument types including MicroCATs and RBR thermistors. The package enables comparison and calibration analysis between reference CTD measurements and deployed oceanographic instruments during calibration dips.

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/ocean-uhh/caldip.git
cd caldip
pip install -r requirements.txt
pip install -e .
```

### Basic Usage

```bash
# Scaffold a configuration file for a new cast directory
caldip init data/proc_calib/msm142_2026/cal_dip/castM4/

# Pre-process the CTD file (normalize, wild-edit, 1 Hz resample, save NetCDF)
caldip ctd data/proc_calib/msm142_2026/cal_dip/castM4/

# Generate interactive plots
caldip plot data/proc_calib/msm142_2026/cal_dip/castM4/

# Generate statistics (use secondary CTD sensor as reference)
caldip stats data/proc_calib/msm142_2026/cal_dip/castM4/ --ctd-sensor 2
```

## 📁 Project Structure

```
caldip/
├── caldip/                     # Python package
│   ├── __init__.py            # Public API: plot, stats, find_bottle_stops, load_config
│   ├── core.py                # Core algorithms
│   ├── readers.py             # Data loading and normalization
│   ├── scaffold.py            # Stub YAML generator (caldip init)
│   ├── tools.py               # Shared utilities
│   ├── parameters.py          # Canonical variable names (synced from seasenselib)
│   ├── sbe_hex_reader.py      # SBE hex format reader
│   ├── _plot.py               # Plotly implementation (internal)
│   ├── _writers.py            # Output formatting and NetCDF saving (internal)
│   └── cli/                   # CLI entry points
│       ├── __init__.py        # `caldip` dispatcher
│       ├── init.py            # `caldip init` subcommand
│       ├── ctd.py             # `caldip ctd` subcommand
│       ├── instrument.py      # `caldip instrument` subcommand
│       ├── plot.py            # `caldip plot` subcommand
│       └── stats.py           # `caldip stats` subcommand
├── generate_all_caldip_plots.sh  # Batch processing script
├── pyproject.toml             # Package configuration
└── requirements.txt           # Package dependencies
```

## 🏗️ Workflow

The recommended workflow runs each step once per cast:

### Step 1 — Scaffold the configuration

```bash
caldip init data/proc_calib/cruise_year/cal_dip/castM4/
```

Scans the cast directory for CTD and instrument files and writes a stub
`castM4.caldip.yaml`. Edit the file to set `deployment_time`, `recovery_time`,
and any `clock_offset` values before proceeding.

### Step 2 — Pre-process the CTD

```bash
caldip ctd data/proc_calib/cruise_year/cal_dip/castM4/
```

Normalizes variable names, applies wild-edit spike removal, resamples to 1 Hz,
and saves the result as `<ctd_file_stem>.nc` alongside the source CNV file.
Also generates a comparison plot of raw vs processed data. Subsequent
`caldip plot` and `caldip stats` calls load this `.nc` file automatically.

### Step 3 — Cache instrument data (optional but recommended)

```bash
# Save all records to NetCDF for fast re-use
caldip instrument castM4/castM4.caldip.yaml --serial 013874
caldip instrument castM4/castM4.caldip.yaml --serial 13840
```

Produces `caldip_{type}_{serial}_raw.nc` (full normalized record) and
`caldip_{type}_{serial}_use.nc` (trimmed to `deployment_time`/`recovery_time`).
If you skip this step, `caldip plot` and `caldip stats` will create these files
automatically on the first run.

**Cache priority**: `caldip plot` and `caldip stats` load from `_use.nc` if it
exists, otherwise from `_raw.nc`, otherwise from the source file. To force a
re-read from the source (e.g. after editing the source file or changing
`clock_offset`), either re-run `caldip instrument` for that serial or delete
the cached `.nc` files:

```bash
# Force regeneration of one instrument
caldip instrument castB1/castB1.caldip.yaml --serial 26269

# Or delete the cache files manually
rm castB1/caldip_microcat_26269_raw.nc castB1/caldip_microcat_26269_use.nc
```

### Step 4 — Analyse

```bash
# Interactive plot of all instruments vs CTD
caldip plot castM4/castM4.caldip.yaml

# Per-bottle-stop statistics
caldip stats castM4/castM4.caldip.yaml --ctd-sensor 2 -o outputs/
```

### Configuration file

`caldip init` writes a stub; here is a minimal example of the finished file:

```yaml
name: castM4
ctd_file: 'msm_142_1_032_1sec.cnv'
ctd_sensor: 2
deployment_time: '2026-04-03T03:05:36'
recovery_time: '2026-04-03T05:08:24'
directory: 'data/proc_calib/msm142_2026/cal_dip/castM4/'

instruments:
- position: '1'
  serial: 013874
  label: 'TR1050'
  instrument: rbr
  file_type: 'rbr-matlab-legacy'
  filename: '013874_20260403_1302.mat'
  clock_offset: 7175   # seconds; positive = add to instrument time

- position: '2'
  serial: 13840
  label: 'SBE37'
  instrument: MicroCAT
  file_type: 'sbe-cnv'
  filename: '13840_cal_dip_data_time.cnv'
```

#### Instrument selection

Two optional keys control which instruments are recorded and processed:

```yaml
# All instruments physically on the rosette during this cast (serial numbers only).
# "Dipped" means the instrument went into the water, even if no data file is available yet.
# This is a record-keeping field — it has no effect on processing.
dipped_serials: [2942, 25586, 2941, 5367, 7507, 3026, 26202, 26269]

# Subset of serials from `instruments` to actually load and process.
# Omit this key (or leave it empty) to process all entries in `instruments`.
# Use it to isolate one instrument, or to skip serials whose data files are missing.
process_serials: [2942, 2941, 7507]
```

If `process_serials` is absent, all entries in `instruments` are loaded. If it is
present, only those serials are loaded — useful for a quick single-instrument check
or when some data files have not yet been downloaded.

MicroCAT and CTD data must be in `*.cnv` (or `*.asc`) format — `*.hex` must be
converted to `*.cnv` using SBEDataProcessing first. For RBR data, `*.rsk` is
supported; the older `*.hex` format must be converted to legacy `*.mat` using
Ruskin.

## 🔬 Core Algorithm: Bottle Stop Detection

The bottle stop detection algorithm in `caldip/core.py:find_bottle_stops()`:

1. **Pressure variable detection** — searches for `pressure` in the dataset
2. **Search region** — starts detection from max_pressure − 10 dbar
3. **Rate-based detection** — 60-second sliding window; flags periods where pressure change rate < threshold (default: 10 dbar/min)
4. **Boundary refinement** — refines start/end to within 2 dbar of the median pressure
5. **Merging** — merges stops within 10 samples of each other
6. **Duration filter** — keeps only stops ≥ minimum duration (default: 180 s)

## 🎯 Supported Instruments

| Instrument | Formats | `file_type` |
|---|---|---|
| Sea-Bird CTD (SBE9) | `.cnv` | `ctd-cnv` |
| Sea-Bird MicroCAT (SBE37) | `.cnv`, `.asc` | `sbe-cnv`, `sbe-asc` |
| RBR solo/duet/concerto | `.rsk` | `rbr-rsk` |
| RBR (legacy Ruskin export) | `.mat` | `rbr-matlab-legacy` |

## 📊 CLI Reference

| Command | Description |
|---|---|
| `caldip init <dir>` | Write a stub `.caldip.yaml` for a cast directory |
| `caldip ctd <yaml>` | Normalize, wild-edit, resample CTD; save `.nc` + comparison plot |
| `caldip instrument <yaml> --serial N` | Save one instrument to `_raw.nc` / `_use.nc` and generate a time-series plot |
| `caldip plot <yaml>` | Interactive Plotly plot of instruments vs CTD |
| `caldip stats <yaml>` | Per-bottle-stop statistics; write CSV files |

Both `caldip ctd` and `caldip instrument` accept `--format` to control what outputs are
produced. Valid values (comma-separated): `nc` and `html`.

```bash
# CTD: save NetCDF only, skip the plot
caldip ctd castB1/castB1.caldip.yaml --format nc

# CTD: regenerate the comparison plot without re-saving the NetCDF
caldip ctd castB1/castB1.caldip.yaml --format html

# instrument: save NetCDF files only (no plot)
caldip instrument castB1/castB1.caldip.yaml --serial 7507 --format nc

# instrument: plot only, skip NetCDF
caldip instrument castB1/castB1.caldip.yaml --serial 240230 --format html
```

The default for both commands is `--format nc,html` (produce both outputs).

All subcommands accept `--help` for full option details.

## 🐍 Python API

For use in Jupyter notebooks or custom scripts. Prefer `import caldip` over
`from caldip import plot, stats` to avoid shadowing common names like
`scipy.stats`.

### Typical notebook workflow

```python
import caldip
from pathlib import Path

# 1. Load configuration
config   = caldip.load_config("castM4/castM4.caldip.yaml")
data_dir = Path("castM4/")

# 2. Load instrument and CTD data
instruments = caldip.load_instruments_from_config(config, data_dir)
reference   = caldip.load_reference_data(config, data_dir)

# 3. Trim to deployment window (optional — uses deployment_time/recovery_time from YAML)
instruments, reference = caldip.trim_to_deployment(instruments, reference, config)

# 4. Interactive plot (opens in browser or notebook)
fig = caldip.plot(instruments, reference, config=config)
fig.show()

# 5. Per-bottle-stop statistics
df = caldip.stats(instruments, reference, config)
print(df[["serial", "bl_press", "temp_diff", "cond_diff"]])
```

### Lower-level access

```python
import caldip

# Detect bottle stops from a CTD xarray Dataset
reference = caldip.load_reference_data(config, data_dir)
ctd_ds    = list(reference.values())[0]["data"]
stops     = caldip.find_bottle_stops(ctd_ds)

for stop in stops:
    print(f"  {stop['pressure']:.0f} dbar — {stop['duration_seconds']/60:.1f} min")
```

See the [API documentation](https://ocean-uhh.github.io/caldip) for full details.

## 🛠️ Dependencies

**Core Scientific**: numpy, pandas, xarray, scipy, netcdf4  
**Configuration**: pyyaml  
**Visualization**: plotly  
**Oceanographic Data**: seabirdscientific, seasenselib (optional)

## 🔧 Advanced Usage

### Custom bottle stop detection
```bash
caldip plot config.yaml --threshold 25.0 --min-duration 90
caldip plot config.yaml --no-bottle-stops
```

### Override CTD sensor for a quick check
```bash
# Use primary CTD sensor
caldip stats config.yaml --ctd-sensor 1

# Use secondary CTD sensor (overrides YAML ctd_sensor setting)
caldip stats config.yaml --ctd-sensor 2
```

### Batch processing
```bash
bash generate_all_caldip_plots.sh
```

---

The package is designed for oceanographic researchers performing instrument calibration checks and requires familiarity with CTD operations and oceanographic data formats.
