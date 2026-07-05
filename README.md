# 🌊 caldip

[![Tests](https://github.com/ocean-uhh/caldip/actions/workflows/tests.yml/badge.svg)](https://github.com/ocean-uhh/caldip/actions/workflows/tests.yml)
[![Docs](https://github.com/ocean-uhh/caldip/actions/workflows/docs.yml/badge.svg)](https://github.com/ocean-uhh/caldip/actions/workflows/docs.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

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
# Generate interactive plots
caldip plot data/proc_calib/msm142_2026/cal_dip/castM4/

# Generate statistics (compared to CTD secondary sensors)
caldip stats data/proc_calib/msm142_2026/cal_dip/castM4/ --ctd-sensor 2

# Batch processing
bash generate_all_caldip_plots.sh
```

## 📁 Project Structure

```
caldip/
├── caldip/                     # Python package
│   ├── __init__.py            # Public API: plot, stats, find_bottle_stops, load_config
│   ├── core.py                # Core algorithms
│   ├── readers.py             # Universal data loading
│   ├── scaffold.py            # Stub YAML generator (caldip init)
│   ├── tools.py               # Shared utilities
│   ├── sbe_hex_reader.py      # SBE hex format reader
│   ├── _plot.py               # Plotly implementation (internal)
│   ├── _writers.py            # Output formatting (internal)
│   └── cli/                   # CLI entry points
│       ├── __init__.py        # `caldip` dispatcher
│       ├── init.py            # `caldip init` subcommand
│       ├── plot.py            # `caldip plot` subcommand
│       └── stats.py           # `caldip stats` subcommand
├── generate_all_caldip_plots.sh  # Batch processing script
├── pyproject.toml             # Package configuration
└── requirements.txt           # Package dependencies
```

## 🏗️ Workflow

The caldip package enables comparison and calibration analysis through a simple workflow:

### 1. Data Organization
Create a directory with your calibration dip data:
```
data/proc_calib/cruise_year/cal_dip/castM4/
├── castM4.caldip.yaml          # Configuration file
├── ctd_data_file.cnv           # CTD reference data
├── instrument1_data.rsk        # Instrument data files
├── instrument2_data.cnv
└── ...
```

### 2. Configuration
Create a YAML configuration file (`castM4.caldip.yaml`):

```yaml
name: castM4
ctd_file: 'msm_142_1_032_1sec.cnv'
ctd_sensors: 2
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
  clock_offset: 7175  # seconds: positive = add to instrument time, negative = subtract from instrument time
  
- position: '2'
  serial: 13840
  label: 'SBE37'
  instrument: sbe
  file_type: 'sbe-cnv'
  filename: '13840_cal_dip_data_time.cnv'
```

Note that microCAT and CTD data need to be in `*.cnv` (or for microCAT, `*.asc`) format.  `*.hex` is not supported and needs to be converted to `*.cnv` using SBEDataProcessing.  For RBR data, `*.rsk` is supported, but the older `*.hex` needs to be converted to legacy `*.mat` format using Ruskin.

### 3. Processing
Run analysis and generate outputs:

```bash
# Interactive plots with bottle stop detection
caldip plot data/proc_calib/msm142_2026/cal_dip/castM4/

# Detailed comparison statistics
caldip stats data/proc_calib/msm142_2026/cal_dip/castM4/ --ctd-sensor 2
```

## 🔬 Core Algorithm: Bottle Stop Detection

The core algorithm for detecting bottle stops in CTD data (`caldip/core.py:find_bottle_stops()`) works as follows:

1. **Pressure Variable Detection**: Searches for pressure data in common variable names
2. **Search Region Definition**: Finds maximum pressure depth and begins detection from max_pressure - 10 dbar
3. **Rate-Based Initial Detection**: Uses 60-second sliding window to identify periods where pressure change rate is below threshold (default: 10 dbar/min)
4. **Median-Based Boundary Refinement**: Calculates median pressure and refines boundaries to within 2 dbar tolerance
5. **Merging Close Stops**: Merges bottle stops within 10 samples of each other
6. **Final Duration Filtering**: Applies minimum duration filter (default: 180 seconds / 3 minutes)

## 🎯 Supported Instruments

### Current Support
- **Sea-Bird CTD**: CNV format (`.cnv`)
- **Sea-Bird MicroCAT (SBE37)**: CNV, ASCII, and hex formats (`.cnv`, `.asc`)
- **RBR Instruments**: RSK and MATLAB formats (`.rsk`, `.mat`)
- **Planned: Universal support**: Through `seasenselib` integration

### File Type Mapping
- `.cnv` files → `file_type: 'sbe-cnv'` or `'ctd-cnv'`
- `.asc` files → `file_type: 'sbe-asc'`
- `.hex` files → `file_type: 'sbe-hex'`
- `.rsk` files → `file_type: 'rbr-rsk'`
- `.mat` files → `file_type: 'rbr-matlab-legacy'`

## 📊 Features

### Interactive Visualization (`caldip plot`)
- **3 subplots**: Pressure, Temperature, Conductivity
- **Interactive zooming**: Click and drag on any plot, all sync on x-axis
- **Color coding**: Different colors for each instrument, black/gray for CTD
- **Bottle stop markers**:
  - Blue vertical lines: Start of bottle stop
  - Red vertical lines: End of bottle stop  
  - Black dotted lines: Comparison period boundaries

### Statistical Analysis (`caldip stats`)
- **Detailed per-bottle-stop statistics**: Mean differences, standard deviations
- **Quality flags**: GOOD/WARNING/BAD based on tolerance thresholds
- **Comparison periods**: Last 3 minutes of each bottle stop
- **CSV output**: Formatted tables for further analysis

### Key Features
- **Clock Offset Correction**: Applies time corrections specified in YAML configuration
- **CTD Sensor Selection**: Supports primary/secondary CTD sensor analysis
- **Automatic Detection**: No manual bottle stop timing required
- **Reproducible Analysis**: YAML configuration files ensure repeatable processing

## 🐍 Python API

For use in Jupyter notebooks or custom scripts. Prefer `import caldip` over `from caldip import plot, stats` to avoid shadowing common names like `scipy.stats`.

### Typical notebook workflow

```python
import caldip
from pathlib import Path

# 1. Load configuration
config = caldip.load_config("data/proc_calib/msm142_2026/cal_dip/castM4/castM4.caldip.yaml")
data_dir = Path("data/proc_calib/msm142_2026/cal_dip/castM4/")

# 2. Load instrument and CTD data
instruments = caldip.load_instruments_from_config(config, data_dir)
reference   = caldip.load_reference_data(config, data_dir)

# 3. Trim to deployment window (optional — uses deployment_time/recovery_time from YAML)
instruments, reference = caldip.trim_to_deployment(instruments, reference, config)

# 4. Interactive plot (opens in browser or notebook)
fig = caldip.plot(instruments, reference, config=config)
fig.show()

# 5. Per-bottle-stop statistics
df = caldip.stats(instruments, reference, config, ctd_sensor=2)
print(df[["serial", "bl_press", "temp_diff", "cond_diff"]])
```

### Lower-level access

```python
import caldip

# Detect bottle stops from a CTD xarray Dataset
ctd_data = caldip.load_reference_data(config, data_dir)
ctd_ds   = list(ctd_data.values())[0]["data"]
stops    = caldip.find_bottle_stops(ctd_ds)

for stop in stops:
    print(f"  {stop['pressure']:.0f} dbar — {stop['duration_seconds']/60:.1f} min")
```

See the [API documentation](https://ocean-uhh.github.io/caldip) for full details.

## 🛠️ Dependencies

**Core Scientific**: numpy, pandas, xarray, scipy, netcdf4  
**Configuration**: pyyaml  
**Visualization**: plotly  
**Oceanographic Data**: seabirdscientific, seasenselib

## 📋 Configuration File Setup

### Step 1: Get CTD Timing
```bash
python -c "
from caldip.readers import load_ctd_data
import pandas as pd
ds = load_ctd_data('path/to/your_ctd_file.cnv')
start = pd.to_datetime(ds.time.values[0])
end = pd.to_datetime(ds.time.values[-1])
print(f'deployment_time: {start.strftime(\"%Y-%m-%dT%H:%M:%S\")}')
print(f'recovery_time: {end.strftime(\"%Y-%m-%dT%H:%M:%S\")}')
"
```

### Step 2: List Your Instruments
For each instrument file in your directory, add an entry to the YAML configuration with the appropriate `file_type` and any necessary `clock_offset`.  Start with `clock_offset` zero or omit this line if your clocks are good.  Note that this only shifts the instrument clock but does not de-drift it.

## 🔧 Advanced Usage

### Custom Bottle Stop Detection
```bash
# Adjust detection parameters
caldip plot config.yaml --threshold 25.0 --min-duration 90

# Disable bottle stop detection
caldip plot config.yaml --no-bottle-stops
```

### CTD Sensor Selection
```bash
# Use primary CTD sensor (default)
caldip stats config.yaml --ctd-sensor 1

# Use secondary CTD sensor
caldip stats config.yaml --ctd-sensor 2
```

---

The package is designed for oceanographic researchers performing instrument calibration checks and requires familiarity with CTD operations and oceanographic data formats.
