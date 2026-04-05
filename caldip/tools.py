
"""
Shared utility functions for caldip processing.

This module contains general-purpose utilities used across multiple
modules in the caldip package.

Currently Used Functions:
- instrument_data_to_xarray() -> xr.Dataset
  Convert seabirdscientific objects to xarray Datasets
- trim_data_to_deployment() -> tuple
  Trim instrument and reference data to deployment/recovery times

These functions are used by data_loader.py and the main processing scripts.
"""

import numpy as np
import pandas as pd
import xarray as xr
from typing import Dict

def instrument_data_to_xarray(instrument_data) -> xr.Dataset:
    """
    Convert seabirdscientific InstrumentData object to xarray Dataset.
    
    Parameters
    ----------
    instrument_data : seabirdscientific.InstrumentData
        The InstrumentData object from seabirdscientific
        
    Returns
    -------
    xarray.Dataset
        Dataset with measurements as data variables and time coordinate
    """
    measurements = instrument_data.measurements
    
    # Handle interval_s safely - default to 1.0 if not available or None
    interval_s = getattr(instrument_data, 'interval_s', None)
    if interval_s is None:
        # For CTD data without interval, try to infer from timestamps or use default
        if hasattr(instrument_data, 'sample_count') and instrument_data.sample_count and instrument_data.sample_count > 1:
            # Use first two timestamps if available in measurements
            time_keys = [k for k in measurements.keys() if 'time' in k.lower()]
            if time_keys and len(measurements[time_keys[0]]) > 1:
                dt = measurements[time_keys[0]].iloc[1] - measurements[time_keys[0]].iloc[0]
                interval_s = dt.total_seconds()
            else:
                # Default interval for CTD data
                interval_s = 1.0
        else:
            interval_s = 1.0
    
    # Create time coordinate
    if instrument_data.start_time is not None and instrument_data.sample_count is not None:
        time_index = pd.date_range(
            start=instrument_data.start_time,
            periods=instrument_data.sample_count,
            freq=f"{interval_s}s",
        )
    else:
        # Fallback: create index from data length
        data_length = max(len(v) for v in measurements.values()) if measurements else 0
        time_index = pd.date_range(
            start=pd.Timestamp.now(),
            periods=data_length,
            freq=f"{interval_s}s",
        )
    
    # Create data variables dict
    data_vars = {}
    for key, measurement_series in measurements.items():
        data_vars[key] = (["time"], measurement_series.values)
    
    # Create Dataset
    ds = xr.Dataset(
        data_vars,
        coords={"time": time_index},
        attrs={
            "latitude": instrument_data.latitude,
            "longitude": getattr(instrument_data, 'longitude', None),
            "start_time": instrument_data.start_time.isoformat(),
            "sample_count": instrument_data.sample_count,
            "interval_s": instrument_data.interval_s,
        }
    )
    
    return ds


def trim_data_to_deployment(
    instruments: Dict[str, Dict], 
    reference_data: Dict[str, Dict], 
    config: Dict
) -> tuple:
    """
    Trim instrument and reference data to deployment/recovery times.
    
    Parameters
    ----------
    instruments : dict
        Instrument data dictionary
    reference_data : dict
        Reference data dictionary
    config : dict
        Configuration with deployment_time and recovery_time
        
    Returns
    -------
    tuple
        (trimmed_instruments, trimmed_reference_data)
    """
    if not ('deployment_time' in config and 'recovery_time' in config):
        print("No deployment/recovery times in config - skipping trimming")
        return instruments, reference_data
    
    deployment_time = pd.to_datetime(config['deployment_time'])
    recovery_time = pd.to_datetime(config['recovery_time'])
    
    print(f"Trimming data to: {deployment_time} - {recovery_time}")
    
    # Trim instrument data
    trimmed_instruments = {}
    for serial, info in instruments.items():
        ds = info['data']
        time_mask = (ds.time >= deployment_time) & (ds.time <= recovery_time)
        
        if np.any(time_mask):
            trimmed_info = info.copy()
            trimmed_info['data'] = ds.sel(time=time_mask)
            trimmed_instruments[serial] = trimmed_info
            n_samples = int(np.sum(time_mask))
            print(f"  Trimmed {serial}: {n_samples} samples")
        else:
            print(f"  Warning: No data for {serial} in deployment period")
    
    # Trim reference data
    trimmed_reference = {}
    for name, info in reference_data.items():
        ds = info['data']
        time_mask = (ds.time >= deployment_time) & (ds.time <= recovery_time)
        
        if np.any(time_mask):
            trimmed_info = info.copy()
            trimmed_info['data'] = ds.sel(time=time_mask)
            trimmed_reference[name] = trimmed_info
            n_samples = int(np.sum(time_mask))
            print(f"  Trimmed {name}: {n_samples} samples")
        else:
            print(f"  Warning: No reference data for {name} in deployment period")
    
    return trimmed_instruments, trimmed_reference