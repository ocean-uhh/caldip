"""
Universal data loading functions for caldip processing.

This module provides a unified interface for loading data from different
instrument types using their file_type specifications.

Currently Used Functions:
- load_caldip_config() -> Dict
  Load YAML configuration files for caldip processing
- load_instruments_from_config() -> Dict[str, Dict]
  Load all instruments specified in a caldip configuration
- load_reference_data() -> Dict[str, Dict]
  Load CTD reference data from configuration
- load_instrument_data() -> xr.Dataset
  Load individual instrument data using appropriate loader (internal utility)
- load_ctd_data() -> xr.Dataset
  Load CTD data from SeaBird hex/cnv files
- load_microcat_data() -> xr.Dataset
  Load MicroCAT data from SeaBird hex/asc/cnv files

All functions are actively used in caldip_plot_all.py and caldip_check_all.py
for the main processing workflow. Note: trim_data_to_deployment() moved to tools.py.
"""

import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path
from typing import Dict, Union, Optional
import yaml
from datetime import datetime, timedelta
import warnings

try:
    import seasenselib as sl
    SEASENSELIB_AVAILABLE = True
except ImportError:
    SEASENSELIB_AVAILABLE = False

# Import seabirdscientific if available
try:
    import seabirdscientific.instrument_data as id
    SEABIRD_AVAILABLE = True
except ImportError:
    SEABIRD_AVAILABLE = False
    warnings.warn("seabirdscientific not available. Some features will be limited.")

# Import tools for shared utilities
from caldip.tools import instrument_data_to_xarray


def load_caldip_config(yaml_file: Union[str, Path]) -> Dict:
    """Load caldip configuration from YAML file."""
    with open(yaml_file, 'r') as f:
        config = yaml.safe_load(f)
    return config


def load_instrument_data(file_path: Union[str, Path], file_type: str, **kwargs) -> xr.Dataset:
    """
    Load instrument data using the appropriate loader based on file_type.
    
    Parameters
    ----------
    file_path : str or Path
        Path to the data file
    file_type : str
        Type of file format (e.g., 'sbe-cnv', 'sbe-asc', 'rbr-rsk')
    **kwargs
        Additional arguments passed to the specific loader
        
    Returns
    -------
    xr.Dataset
        Dataset with standardized variable names and metadata
        
    Raises
    ------
    ValueError
        If file_type is not supported
    FileNotFoundError
        If file does not exist
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Data file not found: {file_path}")
    
    # Route to appropriate loader based on file_type
    if file_type in ['sbe-cnv', 'sbe-asc']:
        return load_microcat_data(file_path, **kwargs)
    
    elif file_type == 'rbr-rsk':
        if not SEASENSELIB_AVAILABLE:
            raise ImportError("seasenselib is required for RBR data loading")
        return sl.read(file_path, **kwargs)
    
    elif file_type == 'ctd-cnv':
        return load_ctd_data(file_path, **kwargs)
    
    else:
        return sl.read(file_path,file_format=file_type)
    #    raise ValueError(f"Unsupported file_type: {file_type}")


def load_instruments_from_config(config: Dict, data_dir: Optional[Union[str, Path]] = None) -> Dict[str, Dict]:
    """
    Load all instruments specified in a caldip configuration.
    
    Parameters
    ----------
    config : dict
        Caldip configuration dictionary
    data_dir : str or Path, optional
        Base directory for data files. If None, uses config['directory']
        
    Returns
    -------
    dict
        Dictionary with instrument serial numbers as keys and data info as values:
        {
            'serial_number': {
                'data': xr.Dataset,
                'config': dict,  # instrument config from YAML
                'type': str,     # file_type
                'file': str      # full file path
            }
        }
    """
    if data_dir is None:
        data_dir = config.get('directory', '.')
    
    data_dir = Path(data_dir)
    instruments = {}
    
    for instrument in config.get('instruments', []):
        serial = str(instrument['serial'])
        filename = instrument['filename']
        file_type = instrument['file_type']
        
        # Construct full file path
        file_path = data_dir / filename
        
        print(f"Loading {instrument.get('label', 'Unknown')} {serial} ({file_type.upper()})...")
        
        try:
            # Load the data
            dataset = load_instrument_data(file_path, file_type)
            
            # Apply clock offset if specified (positive offset = add time, negative = subtract time)
            if 'clock_offset' in instrument and instrument['clock_offset'] != 0:
                clock_offset = instrument['clock_offset']
                print(f"  ⏰ Applying clock offset: {clock_offset:+.0f} seconds")
                dataset = dataset.assign_coords(
                    time=dataset.time + pd.Timedelta(seconds=clock_offset)
                )
            
            instruments[serial] = {
                'data': dataset,
                'config': instrument,
                'type': file_type,
                'file': str(file_path)
            }
            
            print(f"  ✅ Loaded: {len(dataset.time)} samples")
            
        except Exception as e:
            print(f"  ❌ Failed to load {serial}: {e}")
    
    return instruments


def load_reference_data(config: Dict, data_dir: Optional[Union[str, Path]] = None) -> Dict[str, Dict]:
    """
    Load CTD reference data from config.
    
    Parameters
    ----------
    config : dict
        Caldip configuration dictionary
    data_dir : str or Path, optional
        Base directory for data files. If None, uses config['directory']
        
    Returns
    -------
    dict
        Dictionary with CTD data:
        {
            'ctd_name': {
                'data': xr.Dataset,
                'file': str
            }
        }
    """
    if data_dir is None:
        data_dir = config.get('directory', '.')
    
    data_dir = Path(data_dir)
    reference_data = {}
    
    # Load CTD data if specified
    ctd_file = config.get('ctd_file')
    if ctd_file:
        ctd_path = data_dir / ctd_file
        ctd_name = Path(ctd_file).stem
        
        print(f"Loading CTD reference {ctd_name}...")
        
        try:
            dataset = load_instrument_data(ctd_path, 'ctd-cnv')
            
            reference_data[ctd_name] = {
                'data': dataset,
                'file': str(ctd_path)
            }
            
            print(f"  ✅ Loaded: {len(dataset.time)} samples")
            
        except Exception as e:
            print(f"  ❌ Failed to load CTD: {e}")
    
    return reference_data



def load_ctd_data(file_path: Union[str, Path]) -> xr.Dataset:
    """
    Load CTD 911 data from SeaBird hex/cnv file.
    
    Parameters
    ----------
    file_path : str or Path
        Path to CTD data file (.hex or .cnv format)
        
    Returns
    -------
    xarray.Dataset
        CTD data with standardized variable names and metadata
    """
    file_path = Path(file_path)
    
    if file_path.suffix.lower() == '.hex':
        # For .hex files, use our custom MSM142 parser
        try:
            # Import the MSM142 parser
            import sys
            from pathlib import Path as PathlibPath
            parser_path = PathlibPath(__file__).parent.parent / "msm142_hex_parser.py"
            if parser_path.exists():
                sys.path.insert(0, str(parser_path.parent))
                from msm142_hex_parser import load_msm142_hex
                
                # Use the base path (without extension)
                base_path = str(file_path.with_suffix(''))
                ds = load_msm142_hex(base_path)
            else:
                raise ImportError("MSM142 hex parser not found")
            
        except Exception as e:
            warnings.warn(f"Failed to load hex with MSM142 parser: {e}. Falling back to basic approach.")
            # Fallback to basic approach if available
            if SEABIRD_AVAILABLE:
                ds = _load_hex_basic(file_path)
            else:
                raise ImportError("No suitable hex parser available")
    
    elif file_path.suffix.lower() == '.cnv':
        # For .cnv files, use seabirdscientific if available
        if not SEABIRD_AVAILABLE:
            raise ImportError("seabirdscientific package required for CNV data loading")
        
        # Use cnv_to_instrument_data to load CNV files
        instrument_data = id.cnv_to_instrument_data(str(file_path))
        ds = instrument_data_to_xarray(instrument_data)
        
        # Fix time if it's showing year 2000 incorrectly
        # CTD files have timeJ which is elapsed days since start of cast
        if pd.Timestamp(ds.time.values[0]).year == 2000:
            # Check the raw file for the actual start time
            actual_start = None
            with open(file_path, 'r') as f:
                for line in f:
                    if '* NMEA UTC' in line:
                        # Extract date from line like: * NMEA UTC (Time) = Mar 30 2026 21:06:33
                        try:
                            date_str = line.split('=')[-1].strip()
                            from datetime import datetime, timedelta
                            actual_start = datetime.strptime(date_str, '%b %d %Y %H:%M:%S')
                            break
                        except Exception:
                            continue
            
            if actual_start and 'timeJ' in ds.data_vars:
                # timeJ is elapsed time in days since start of cast
                # The first timeJ value corresponds to actual_start
                elapsed_days = ds.timeJ.values - ds.timeJ.values[0]
                
                actual_timestamps = []
                for ed in elapsed_days:
                    timestamp = actual_start + timedelta(days=float(ed))
                    actual_timestamps.append(timestamp)
                
                ds = ds.assign_coords(time=pd.DatetimeIndex(actual_timestamps))
                ds.attrs['start_time'] = actual_start.isoformat()
    else:
        raise ValueError(f"Unsupported file format: {file_path.suffix}")
    
    # Add standardized variable names and units
    ds.attrs['instrument_type'] = 'CTD'
    ds.attrs['filename'] = str(file_path)
    
    return ds



def _load_hex_basic(file_path: Path) -> xr.Dataset:
    """Basic hex file loading with minimal sensor configuration."""
    # Try with basic SBE911Plus configuration
    basic_sensors = [
        id.Sensors.Temperature,
        id.Sensors.Conductivity, 
        id.Sensors.Pressure,
        id.Sensors.SystemTime
    ]
    
    try:
        df = id.read_hex_file(
            str(file_path),
            id.InstrumentType.SBE911Plus,
            enabled_sensors=basic_sensors,
            moored_mode=False,
            is_shallow=False
        )
        # Convert to xarray Dataset
        return df.to_xarray()
    except Exception as e:
        raise ValueError(f"Could not load hex file {file_path}: {e}")


def load_microcat_data(file_path: Union[str, Path]) -> xr.Dataset:
    """
    Load microCAT (SBE37) data from SeaBird hex/asc/cnv file.
    
    Parameters
    ----------
    file_path : str or Path
        Path to microCAT data file (.hex, .asc, or .cnv format)
        
    Returns
    -------
    xarray.Dataset
        MicroCAT data with standardized variable names and metadata
    """
    file_path = Path(file_path)
    
    if file_path.suffix.lower() == '.cnv':
        # For .cnv files, use cnv_to_instrument_data (confirmed working)
        if not SEABIRD_AVAILABLE:
            raise ImportError("seabirdscientific package required for .cnv file loading")
        
        instrument_data = id.cnv_to_instrument_data(str(file_path))
        ds = instrument_data_to_xarray(instrument_data)
        
        # Fix time coordinate if timeJV2 (actual timestamps) is available
        if 'timeJV2' in ds.data_vars:
            # timeJV2 is in Julian days - SeaBird convention
            # SeaBird uses day 1 = Jan 1, day 2 = Jan 2, etc.
            # So day 0 = Dec 31 of previous year
            # Based on the data: 89.125 julian days = Mar 30, 2026 at 3:00
            
            import pandas as pd
            from datetime import datetime, timedelta
            
            julian_days = ds.timeJV2.values
            
            # Determine the year from the file or metadata
            # For 2026 data: day 0 = Dec 31, 2025
            reference_date = datetime(2025, 12, 31, 0, 0, 0)
            
            # Convert julian days to actual timestamps
            actual_timestamps = []
            for jd in julian_days:
                timestamp = reference_date + timedelta(days=float(jd))
                actual_timestamps.append(timestamp)
            
            # Replace the time coordinate with actual timestamps
            ds = ds.assign_coords(time=pd.DatetimeIndex(actual_timestamps))
            ds.attrs['time_corrected'] = 'Using actual timestamps from timeJV2'
        
    elif file_path.suffix.lower() == '.hex':
        # Parse MicroCAT hex files using proper timestamp extraction
        ds = _parse_microcat_hex(file_path)
        
    elif file_path.suffix.lower() == '.asc':
        # Parse ASCII files manually
        ds = _parse_microcat_ascii(file_path)
        
    else:
        raise ValueError(f"Unsupported file format: {file_path.suffix}")
    
    # Extract serial number from filename if not in metadata
    if 'serial_number' not in ds.attrs:
        serial_parts = file_path.stem.split('_')
        ds.attrs['serial_number'] = serial_parts[0] if serial_parts else 'unknown'
    
    ds.attrs['instrument_type'] = 'SBE37'
    ds.attrs['filename'] = str(file_path)
    
    return ds


def _parse_microcat_ascii(file_path: Path) -> xr.Dataset:
    """
    Parse ASCII microCAT files (legacy format).
    
    This handles the basic ASCII format structure from SeaBird instruments.
    Automatically detects column format based on data structure.
    """
    with open(file_path, 'r') as f:
        lines = f.readlines()
    
    # Find data start (after header lines starting with * or #)
    data_start = 0
    metadata = {}
    
    for i, line in enumerate(lines):
        line = line.strip()
        
        # Extract metadata from header
        if line.startswith('*'):
            if 'Temperature SN' in line:
                metadata['temperature_sn'] = line.split('=')[-1].strip()
            elif 'Conductivity SN' in line:
                metadata['conductivity_sn'] = line.split('=')[-1].strip()
            elif 'sample interval' in line:
                try:
                    interval_match = line.split('=')[-1].strip().split()[0]
                    metadata['interval_s'] = int(interval_match)
                except:
                    pass
            elif 'System UpLoad Time' in line:
                try:
                    time_str = line.split('=')[-1].strip()
                    metadata['upload_time'] = datetime.strptime(time_str, '%b %d %Y %H:%M:%S')
                except ValueError:
                    pass
        elif not line.startswith('*') and not line.startswith('#') and line:
            # Skip lines like "start time = ", "sample interval = ", "start sample number = "
            if 'start time' in line or 'sample interval' in line or 'start sample number' in line:
                continue
            # First actual data line marks data start
            data_start = i
            break
    
    # Parse data lines (skip comments and empty lines)
    data_lines = []
    time_stamps = []
    has_pressure = False
    
    for line in lines[data_start:]:
        line = line.strip()
        if line and not line.startswith('*') and not line.startswith('#'):
            # Skip metadata lines that might appear in data section
            if 'start time' in line or 'sample interval' in line or 'start sample number' in line:
                continue
                
            try:
                parts = [p.strip() for p in line.split(',')]
                
                # Detect format based on number of comma-separated values
                if len(parts) == 5:
                    # Format: temperature, conductivity, pressure, date, time
                    temp = float(parts[0])
                    cond = float(parts[1]) * 10.0  # Convert from S/m to mS/cm
                    press = float(parts[2])
                    date_str = f"{parts[3]} {parts[4]}"
                    has_pressure = True
                    
                elif len(parts) == 4:
                    # Format: temperature, conductivity, date, time (no pressure)
                    temp = float(parts[0])
                    cond = float(parts[1]) * 10.0  # Convert from S/m to mS/cm
                    press = 0.0
                    date_str = f"{parts[2]} {parts[3]}"
                    
                else:
                    continue
                    
                # Try multiple date formats
                date_formats = [
                    '%d %b %Y %H:%M:%S',    # "30 Mar 2026 03:00:01"
                    '%m-%d-%Y %H:%M:%S',    # "03-30-2026 03:00:01" 
                    '%d-%m-%Y %H:%M:%S',    # "30-03-2026 03:00:01"
                    '%Y-%m-%d %H:%M:%S',    # "2026-03-30 03:00:01"
                ]
                
                timestamp = None
                for fmt in date_formats:
                    try:
                        timestamp = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
                
                if timestamp:
                    time_stamps.append(timestamp)
                    data_lines.append([temp, cond, press])
                    
            except (ValueError, IndexError):
                continue
    
    if not data_lines:
        raise ValueError(f"No valid data found in ASCII file {file_path}")
    
    # Convert to numpy array
    data_array = np.array(data_lines)
    n_samples = len(data_array)
    
    # Create time coordinate - use parsed timestamps if available
    if time_stamps and any(t is not None for t in time_stamps):
        # Use the actual timestamps from the data
        valid_timestamps = [t for t in time_stamps if t is not None]
        if len(valid_timestamps) == len(time_stamps):
            time_index = pd.to_datetime(time_stamps)
        else:
            # Some timestamps missing, interpolate
            time_index = pd.to_datetime(time_stamps)
            time_index = time_index.fillna(method='ffill').fillna(method='bfill')
    else:
        # Fallback: create regular time series
        interval_s = metadata.get('interval_s', 10)  # Default 10 seconds
        start_time = metadata.get('upload_time', datetime.now())
        time_index = pd.date_range(
            start=start_time,
            periods=n_samples,
            freq=f"{interval_s}s"
        )
    
    # Create Dataset with appropriate variables
    data_vars = {
        'temperature': (['time'], data_array[:, 0]),
        'conductivity': (['time'], data_array[:, 1]),
    }
    
    # Only add pressure if it exists (not all zeros)
    if has_pressure and np.any(data_array[:, 2] != 0):
        data_vars['prdM'] = (['time'], data_array[:, 2])
    
    ds = xr.Dataset(
        data_vars,
        coords={'time': time_index},
        attrs=metadata
    )
    
    return ds


def _parse_microcat_hex(file_path: Path) -> xr.Dataset:
    """
    Parse MicroCAT hex files with actual timestamps.
    
    This handles SBE37 MicroCAT hex format with ODO sensor and timestamps.
    Format: 6 bytes temp + 6 bytes cond + 6 bytes pressure + 
            4 bytes temp comp + 6 bytes ODO phase + 6 bytes ODO temp + 8 bytes time
    Total: 42 hex characters per line
    """
    from datetime import datetime, timedelta
    
    # Constants from seabirdscientific
    SECONDS_BETWEEN_EPOCH_AND_2000 = 946684800
    
    with open(file_path, 'r') as f:
        lines = f.readlines()
    
    # Extract metadata from header
    metadata = {}
    serial_number = None
    
    for line in lines:
        if line.startswith('*'):
            if 'Temperature SN' in line:
                serial_number = line.split('=')[-1].strip()
                metadata['serial_number'] = serial_number
            elif 'System UpLoad Time' in line:
                upload_time_str = line.split('=')[-1].strip()
                try:
                    metadata['upload_time'] = datetime.strptime(upload_time_str, '%b %d %Y %H:%M:%S')
                except:
                    pass
    
    # Parse data lines
    timestamps = []
    temperature_counts = []
    conductivity_counts = []
    pressure_counts = []
    temp_comp_counts = []
    
    for line in lines:
        line = line.strip()
        
        # Skip header and empty lines
        if line.startswith('*') or line.startswith('#') or not line:
            continue
        
        # Parse hex data (42 chars for ODO-enabled MicroCAT)
        if len(line) == 42:
            try:
                # Extract raw counts
                temp_hex = line[0:6]
                cond_hex = line[6:12]
                press_hex = line[12:18]
                temp_comp_hex = line[18:22]
                # Skip ODO data at positions 22:34
                time_hex = line[34:42]
                
                # Convert to integers
                temp_count = int(temp_hex, 16)
                cond_count = int(cond_hex, 16)
                press_count = int(press_hex, 16) if press_hex != '000000' else 0
                temp_comp_count = int(temp_comp_hex, 16)
                
                # Parse timestamp (seconds since 2000)
                seconds_since_2000 = int(time_hex, 16)
                timestamp = datetime(1970, 1, 1) + timedelta(
                    seconds=seconds_since_2000 + SECONDS_BETWEEN_EPOCH_AND_2000
                )
                
                timestamps.append(timestamp)
                temperature_counts.append(temp_count)
                conductivity_counts.append(cond_count / 256)  # Conductivity needs division by 256
                pressure_counts.append(press_count)
                temp_comp_counts.append(temp_comp_count)
                
            except Exception as e:
                continue
    
    if not timestamps:
        raise ValueError(f"No valid data found in hex file {file_path}")
    
    # Convert counts to engineering units
    # Note: These conversions need calibration coefficients from the .xmlcon file
    # For now, using the raw counts which will be converted by the CNV processor
    
    # Create xarray dataset
    time_index = pd.to_datetime(timestamps)
    
    ds = xr.Dataset(
        {
            'temperature_counts': (['time'], temperature_counts),
            'conductivity_counts': (['time'], conductivity_counts),
            'pressure_counts': (['time'], pressure_counts),
            'temperature_compensation_counts': (['time'], temp_comp_counts),
        },
        coords={'time': time_index},
        attrs=metadata
    )
    
    # Add note that these are raw counts needing calibration
    ds.attrs['data_type'] = 'raw_counts'
    ds.attrs['note'] = 'Raw counts from hex file - requires calibration coefficients for conversion to physical units'
    
    # Try to load calibration from xmlcon file if available
    xmlcon_path = file_path.with_suffix('.xmlcon')
    if xmlcon_path.exists():
        try:
            # For now, just note that calibration is available
            ds.attrs['calibration_file'] = str(xmlcon_path)
            
            # TODO: Parse xmlcon and apply calibrations
            # This would involve extracting calibration coefficients and applying
            # the proper conversion formulas for each sensor
            
        except Exception as e:
            pass
    
    return ds

