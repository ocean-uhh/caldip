# 🌊 caldip

**Calibration dip analysis for oceanographic instruments**

Caldip provides tools for processing, analyzing, and visualizing data from calibration dips performed with CTD profiles and multiple instrument types including MicroCATs and RBR thermistors. The package enables comparison and calibration analysis between reference CTD measurements and deployed oceanographic instruments during calibration dips.

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/your-repo/caldip.git
cd caldip
pip install -r requirements.txt
pip install -e .
```

### Basic Usage

```bash
# Generate interactive plots
python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM4/ --output castM4_plot.html

# Generate statistics
python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM4/ --output castM4_stats.csv --ctd-sensor 2

# Batch processing
bash generate_all_caldip_plots.sh
```

## 📁 Project Structure

```
caldip/
├── caldip/                     # Python package
│   ├── __init__.py            # Package initialization
│   ├── caldip_functions.py    # Core processing algorithms
│   ├── data_loader.py         # Universal data loading
│   ├── plotting.py            # Interactive visualization
│   └── tools.py               # Shared utilities
├── caldip_plot_all.py         # Universal plotting script
├── caldip_check_all.py        # Universal statistics script
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

### 3. Processing
Run analysis and generate outputs:

```bash
# Interactive plots with bottle stop detection
python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM4/

# Detailed comparison statistics
python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM4/ --ctd-sensor 2
```

## 🔬 Core Algorithm: Bottle Stop Detection

The core algorithm for detecting bottle stops in CTD data (`caldip_functions.py:find_bottle_stops()`) works as follows:

1. **Pressure Variable Detection**: Searches for pressure data in common variable names
2. **Search Region Definition**: Finds maximum pressure depth and begins detection from max_pressure - 10 dbar
3. **Rate-Based Initial Detection**: Uses 60-second sliding window to identify periods where pressure change rate is below threshold (default: 10 dbar/min)
4. **Median-Based Boundary Refinement**: Calculates median pressure and refines boundaries to within 2 dbar tolerance
5. **Merging Close Stops**: Merges bottle stops within 10 samples of each other
6. **Final Duration Filtering**: Applies minimum duration filter (default: 180 seconds / 3 minutes)

## 🎯 Supported Instruments

### Current Support
- **Sea-Bird CTD**: CNV format (`.cnv`)
- **Sea-Bird MicroCAT (SBE37)**: CNV, ASCII, and hex formats (`.cnv`, `.asc`, `.hex`)
- **RBR Instruments**: RSK and MATLAB formats (`.rsk`, `.mat`)
- **Universal support**: Through seasenselib integration

### File Type Mapping
- `.cnv` files → `file_type: 'sbe-cnv'` or `'ctd-cnv'`
- `.asc` files → `file_type: 'sbe-asc'`
- `.hex` files → `file_type: 'sbe-hex'`
- `.rsk` files → `file_type: 'rbr-rsk'`
- `.mat` files → `file_type: 'rbr-matlab-legacy'`

## 📊 Features

### Interactive Visualization (`caldip_plot_all.py`)
- **3 synchronized subplots**: Pressure, Temperature, Conductivity
- **Interactive zooming**: Click and drag on any plot, all sync on x-axis
- **Smart y-axis ranges**: Automatically calculated to show variations
- **Color coding**: Different colors for each instrument, black/gray for CTD
- **Bottle stop markers**:
  - Blue vertical lines: Start of bottle stop
  - Red vertical lines: End of bottle stop  
  - Black dotted lines: Comparison period boundaries

### Statistical Analysis (`caldip_check_all.py`)
- **Detailed per-bottle-stop statistics**: Mean differences, standard deviations
- **Quality flags**: GOOD/WARNING/BAD based on tolerance thresholds
- **Comparison periods**: Last 3 minutes of each bottle stop
- **CSV output**: Formatted tables for further analysis

### Key Features
- **Universal Instrument Support**: Handles CTD, MicroCAT, and RBR instruments through unified interface
- **Clock Offset Correction**: Applies time corrections specified in YAML configuration
- **CTD Sensor Selection**: Supports primary/secondary CTD sensor analysis
- **Automatic Detection**: No manual bottle stop timing required
- **Reproducible Analysis**: YAML configuration files ensure repeatable processing

## 🛠️ Dependencies

**Core Scientific**: numpy, pandas, xarray, scipy, netcdf4  
**Configuration**: pyyaml  
**Visualization**: plotly  
**Oceanographic Data**: seabirdscientific, seasenselib (optional)

## 📋 Configuration File Setup

### Step 1: Get CTD Timing
```bash
python -c "
from caldip.data_loader import load_ctd_data
import pandas as pd
ds = load_ctd_data('path/to/your_ctd_file.cnv')
start = pd.to_datetime(ds.time.values[0])
end = pd.to_datetime(ds.time.values[-1])
print(f'deployment_time: {start.strftime(\"%Y-%m-%dT%H:%M:%S\")}')
print(f'recovery_time: {end.strftime(\"%Y-%m-%dT%H:%M:%S\")}')
"
```

### Step 2: List Your Instruments
For each instrument file in your directory, add an entry to the YAML configuration with the appropriate `file_type` and any necessary `clock_offset`.

## 🔧 Advanced Usage

### Custom Bottle Stop Detection
```bash
# Adjust detection parameters
python caldip_plot_all.py config.yaml --threshold 25.0 --min-duration 90

# Disable bottle stop detection
python caldip_plot_all.py config.yaml --no-bottle-stops
```

### CTD Sensor Selection
```bash
# Use primary CTD sensor (default)
python caldip_check_all.py config.yaml --ctd-sensor 1

# Use secondary CTD sensor
python caldip_check_all.py config.yaml --ctd-sensor 2
```

## 📖 Example Output

### Interactive Plots
- Synchronized time series plots showing all instruments vs CTD reference
- Automatic bottle stop detection and marking
- Responsive design with hover information and zoom capabilities

### Statistical Tables
CSV files with detailed comparison metrics:
- Mean temperature/conductivity/pressure differences
- Standard deviations during stable periods
- Quality assessment flags
- Sample counts and timing information

---

The package is designed for oceanographic researchers performing instrument calibrations and requires familiarity with CTD operations and oceanographic data formats.