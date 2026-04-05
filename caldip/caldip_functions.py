"""
Functional CalDip Processing Module

This module provides simple functions for calibration dip processing using
xarray and numpy, without classes. Based on seabirdscientific data structures.

Currently Used Functions:
- find_bottle_stops() -> List[Dict]
  Detect bottle stops from CTD pressure data (primary algorithm)
"""

import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path
from typing import Dict, List








def find_bottle_stops(ctd_data: xr.Dataset, threshold_dbar_per_min: float = 10.0, min_duration_seconds: float = 180.0) -> List[Dict]:
    """
    Find bottle stops in CTD data based on pressure rate of change.
    
    Looks for periods where pressure change rate is < threshold_dbar_per_min
    (typically < 10 dbar/min for bottle stops vs 30-60 dbar/min for normal ops).
    
    Parameters
    ----------
    ctd_data : xr.Dataset
        CTD dataset with pressure and time variables
    threshold_dbar_per_min : float, optional
        Maximum pressure change rate for bottle stops (dbar/min), default 10.0
    min_duration_seconds : float, optional
        Minimum duration for valid bottle stops (seconds), default 180.0
        
    Returns
    -------
    List[Dict]
        List of bottle stop dictionaries with keys:
        - start_idx, end_idx: indices in the data
        - start_time, end_time: timestamps
        - pressure: mean pressure during stop
        - duration_seconds: duration in seconds
    """
    bottle_stops = []
    
    # Get pressure variable
    pressure_var = None
    for var in ['prDM', 'pressure', 'press', 'PRES']:
        if var in ctd_data.data_vars:
            pressure_var = var
            break
    
    if not pressure_var:
        return bottle_stops
    
    pressure = ctd_data[pressure_var].values
    time = ctd_data.time.values
    
    # Convert time to seconds for rate calculation
    time_dt = pd.to_datetime(time)
    time_seconds = np.array([t.timestamp() for t in time_dt])
    
    # Calculate pressure rate of change (dbar/min)
    window_seconds = 60  # 1 minute window
    
    # Find max pressure point
    max_pressure_idx = np.argmax(pressure)
    max_pressure = pressure[max_pressure_idx]
    
    # Find first time we reach max_pressure - 10 dbar to start looking for bottle stops
    # This accounts for bottle stops that occur at or near maximum depth
    search_threshold = max_pressure - 10.0
    deep_enough_mask = pressure >= search_threshold
    
    if np.any(deep_enough_mask):
        search_start_idx = np.where(deep_enough_mask)[0][0]
    else:
        # Fallback to old behavior if we never reach the threshold
        search_start_idx = max_pressure_idx + 1
    
    # Only look for bottle stops after reaching deep enough depth
    i = search_start_idx
    while i < len(pressure) - 1:
        # Look 1 minute ahead
        future_idx = i
        while future_idx < len(pressure) and (time_seconds[future_idx] - time_seconds[i]) < window_seconds:
            future_idx += 1
        
        if future_idx < len(pressure):
            time_diff_min = (time_seconds[future_idx] - time_seconds[i]) / 60
            pressure_diff = abs(pressure[future_idx] - pressure[i])
            
            if time_diff_min > 0:
                rate = pressure_diff / time_diff_min
                
                # Check if we're in a stable period
                if rate < threshold_dbar_per_min:
                    # Find the end of this stable period
                    end_idx = future_idx
                    while end_idx < len(pressure) - 1:
                        next_idx = end_idx + 1
                        time_diff_min = (time_seconds[next_idx] - time_seconds[end_idx]) / 60
                        if time_diff_min > 0:
                            pressure_diff = abs(pressure[next_idx] - pressure[end_idx])
                            rate = pressure_diff / time_diff_min
                            if rate >= threshold_dbar_per_min:
                                break
                        end_idx += 1
                    
                    # Check minimum duration (at least 30 seconds initially, we'll filter by 3 minutes later)
                    duration = time_seconds[end_idx] - time_seconds[i]
                    if duration >= 30:
                        # Calculate median pressure during the original stop boundaries
                        median_pressure = float(np.median(pressure[i:end_idx+1]))
                        
                        # Refine boundaries to within 2 dbar of median
                        # Find first point within 2 dbar of median (searching from original start)
                        refined_start = i
                        for j in range(i, end_idx+1):
                            if abs(pressure[j] - median_pressure) <= 2.0:
                                refined_start = j
                                break
                        
                        # Find last point within 2 dbar of median (searching backward from original end)
                        refined_end = end_idx
                        for j in range(end_idx, i-1, -1):
                            if abs(pressure[j] - median_pressure) <= 2.0:
                                refined_end = j
                                break
                        
                        # Calculate refined duration (this will be slightly less than original)
                        refined_duration = time_seconds[refined_end] - time_seconds[refined_start]
                        
                        bottle_stops.append({
                            'start_idx': refined_start,
                            'end_idx': refined_end,
                            'start_time': time[refined_start],
                            'end_time': time[refined_end],
                            'pressure': median_pressure,
                            'duration_seconds': refined_duration,
                            'original_duration': duration  # Keep track of original duration too
                        })
                        
                        # Skip to end of this bottle stop
                        i = end_idx
        
        i += 1
    
    # Merge overlapping or very close bottle stops
    merged_stops = []
    for stop in bottle_stops:
        if not merged_stops:
            merged_stops.append(stop)
        else:
            last_stop = merged_stops[-1]
            # If this stop starts very close to the last one ending, merge them
            if stop['start_idx'] - last_stop['end_idx'] < 10:  # Within 10 samples
                last_stop['end_idx'] = stop['end_idx']
                last_stop['end_time'] = stop['end_time']
                last_stop['duration_seconds'] = (time_seconds[stop['end_idx']] - 
                                                  time_seconds[last_stop['start_idx']])
                last_stop['pressure'] = float(np.mean(pressure[last_stop['start_idx']:last_stop['end_idx']+1]))
            else:
                merged_stops.append(stop)
    
    # Filter to only keep bottle stops >= minimum duration
    final_stops = [stop for stop in merged_stops if stop['duration_seconds'] >= min_duration_seconds]
    
    return final_stops

