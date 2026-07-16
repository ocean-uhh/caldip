"""
Functional CalDip Processing Module

This module provides simple functions for calibration dip processing using
xarray and numpy.

Currently Used Functions:
- find_bottle_stops() -> List[Dict]
  Detect bottle stops from CTD pressure data (primary algorithm)
- stats_for_time_period() -> Dict
  Calculate statistics for any dataset within a specified time period
- stats() -> pd.DataFrame
  Calculate statistics for each bottle stop and each instrument (any type)
"""

import numpy as np
import pandas as pd
import xarray as xr
from typing import Dict, List, Optional


def find_bottle_stops(
    ctd_data: xr.Dataset,
    threshold_dbar_per_min: float = 10.0,
    min_duration_seconds: float = 180.0,
) -> List[Dict]:
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
    for var in ["pressure", "prDM", "press", "PRES"]:
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
        while (
            future_idx < len(pressure)
            and (time_seconds[future_idx] - time_seconds[i]) < window_seconds
        ):
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
                        time_diff_min = (
                            time_seconds[next_idx] - time_seconds[end_idx]
                        ) / 60
                        if time_diff_min > 0:
                            pressure_diff = abs(pressure[next_idx] - pressure[end_idx])
                            rate = pressure_diff / time_diff_min
                            if rate >= threshold_dbar_per_min:
                                break
                        end_idx += 1

                    # Check minimum duration (at least 30 seconds initially, we'll subselect for minimum 3 minutes later)
                    duration = time_seconds[end_idx] - time_seconds[i]
                    if duration >= 30:
                        # Calculate median pressure during the original stop boundaries
                        median_pressure = float(np.median(pressure[i : end_idx + 1]))

                        # Refine boundaries to within 2 dbar of median
                        # Find first point within 2 dbar of median (searching from original start)
                        refined_start = i
                        for j in range(i, end_idx + 1):
                            if abs(pressure[j] - median_pressure) <= 2.0:
                                refined_start = j
                                break

                        # Find last point within 2 dbar of median (searching backward from original end)
                        refined_end = end_idx
                        for j in range(end_idx, i - 1, -1):
                            if abs(pressure[j] - median_pressure) <= 2.0:
                                refined_end = j
                                break

                        # Calculate refined duration (this will be slightly less than original)
                        refined_duration = (
                            time_seconds[refined_end] - time_seconds[refined_start]
                        )

                        bottle_stops.append(
                            {
                                "start_idx": refined_start,
                                "end_idx": refined_end,
                                "start_time": time[refined_start],
                                "end_time": time[refined_end],
                                "pressure": median_pressure,
                                "duration_seconds": refined_duration,
                                "original_duration": duration,  # Keep track of original duration too
                            }
                        )

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
            if stop["start_idx"] - last_stop["end_idx"] < 10:  # Within 10 samples
                last_stop["end_idx"] = stop["end_idx"]
                last_stop["end_time"] = stop["end_time"]
                last_stop["duration_seconds"] = (
                    time_seconds[stop["end_idx"]] - time_seconds[last_stop["start_idx"]]
                )
                last_stop["pressure"] = float(
                    np.mean(pressure[last_stop["start_idx"] : last_stop["end_idx"] + 1])
                )
            else:
                merged_stops.append(stop)

    # Sub-select to only keep bottle stops >= minimum duration
    final_stops = [
        stop
        for stop in merged_stops
        if stop["duration_seconds"] >= min_duration_seconds
    ]

    return final_stops


def stats_for_time_period(
    data: xr.Dataset,
    start_time: pd.Timestamp,
    end_time: pd.Timestamp,
    variables: List[str],
) -> Dict:
    """
    Calculate statistics for any dataset within a specified time period.  Normally this time period will be 3 minutes long ending 30 seconds before the end of a bottle stop, but this function can be used for any time period and any variables.

    Parameters
    ----------
    data : xr.Dataset
        Dataset to analyze
    start_time : pd.Timestamp
        Start of time period
    end_time : pd.Timestamp
        End of time period
    variables : List[str]
        List of variable names to calculate statistics for

    Returns
    -------
    Dict
        Statistics dictionary with means, stds, and sample count for each variable
    """
    # Normalize to nanoseconds before int64 so xarray (μs) and pandas (ns) agree
    time_numeric = (
        pd.to_datetime(data.time.values).astype("datetime64[ns]").astype(np.int64) / 1e9
    )
    start_ts = pd.Timestamp(start_time).value / 1e9
    end_ts = pd.Timestamp(end_time).value / 1e9

    # Create time mask
    time_mask = (time_numeric >= start_ts) & (time_numeric <= end_ts)
    n_samples = np.sum(time_mask)

    stats = {"n_samples": n_samples}

    # Calculate stats for each requested variable
    for var in variables:
        if var in data.data_vars and n_samples > 0:
            var_data = data[var].values[time_mask]
            if len(var_data) > 0:
                stats[f"mean_{var}"] = np.nanmean(var_data)
                stats[f"std_{var}"] = np.nanstd(var_data)
            else:
                stats[f"mean_{var}"] = np.nan
                stats[f"std_{var}"] = np.nan
        else:
            stats[f"mean_{var}"] = np.nan
            stats[f"std_{var}"] = np.nan

    return stats


def _format_status(diff: float, threshold: float, var_name: str) -> str:
    """Return a human-readable quality flag string for a single variable difference."""
    if np.isnan(diff):
        return f"{var_name} NO DATA"
    elif abs(diff) <= threshold:
        return f"{var_name} OK"
    elif diff > 0:
        return f"{var_name} reads high by {abs(diff):.3f}"
    else:
        return f"{var_name} reads low by {abs(diff):.3f}"


def stats(
    instrument_data: Dict,
    reference_data: Dict,
    config: Dict,
    threshold_dbar_per_min: float = 10.0,
    min_duration_seconds: float = 180.0,
    temp_threshold: Optional[float] = None,
    cond_threshold: Optional[float] = None,
    press_threshold: Optional[float] = None,
) -> pd.DataFrame:
    """
    Calculate statistics for each bottle stop and each instrument (any type).

    Returns DataFrame with one row per bottle stop per instrument.

    Quality flag thresholds (``temp_threshold``, ``cond_threshold``,
    ``press_threshold``) determine when a difference is flagged as
    "reads high/low" vs "OK".  They can also be set per-cast in the YAML
    under ``quality_flags: {temp_threshold: 0.005, ...}``; explicit
    arguments take precedence over YAML values, which in turn override the
    built-in defaults (±0.005 °C, ±0.02 mS/cm, ±5 dbar).
    """
    # Precedence: explicit arg > YAML quality_flags > built-in default
    yaml_flags = config.get("quality_flags", {})
    if temp_threshold is None:
        temp_threshold = yaml_flags.get("temp_threshold", 0.005)
    if cond_threshold is None:
        cond_threshold = yaml_flags.get("cond_threshold", 0.02)
    if press_threshold is None:
        press_threshold = yaml_flags.get("press_threshold", 5.0)
    # Get the first (and likely only) reference dataset
    if not reference_data:
        print("No reference data available!")
        return pd.DataFrame()

    ref_name = list(reference_data.keys())[0]
    ctd_data = reference_data[ref_name]["data"]

    # Get bottle stops using the detection function
    bottle_stops = find_bottle_stops(
        ctd_data,
        threshold_dbar_per_min=threshold_dbar_per_min,
        min_duration_seconds=min_duration_seconds,
    )

    if not bottle_stops:
        print("No bottle stops found!")
        return pd.DataFrame()

    print(f"Found {len(bottle_stops)} bottle stops for analysis")

    # CTD variables are canonical names after normalization in load_reference_data
    ctd_temp = "temperature"
    ctd_cond = "conductivity"
    ctd_press = "pressure"

    # Validate canonical names exist in the CTD data
    for var_name, var_label in [(ctd_temp, "temperature"), (ctd_press, "pressure")]:
        if var_name not in ctd_data.data_vars:
            raise KeyError(
                f"CTD variable '{var_name}' not found. "
                f"Available variables: {list(ctd_data.data_vars)}\n"
                f"Run 'caldip ctd <yaml>' to pre-process the CTD file."
            )

    # Convert CTD time to numeric for time comparisons
    ctd_time_dt = pd.to_datetime(ctd_data.time.values)
    ctd_time_numeric = np.array([t.timestamp() for t in ctd_time_dt])

    results = []

    # Loop through each bottle stop
    for stop_num, stop in enumerate(bottle_stops, 1):
        # Calculate comparison period (last 2 minutes ending 30 seconds before stop end)
        stop_end_dt = pd.to_datetime(stop["end_time"])
        comp_end = stop_end_dt - pd.Timedelta(seconds=30)
        comp_start = comp_end - pd.Timedelta(minutes=2)

        comp_start_ts = comp_start.timestamp()
        comp_end_ts = comp_end.timestamp()

        print(
            f"  Stop {stop_num} at {stop['pressure']:.1f} dbar: comparison period {comp_start} to {comp_end}"
        )

        # Get CTD data during comparison period
        comp_mask = (ctd_time_numeric >= comp_start_ts) & (
            ctd_time_numeric <= comp_end_ts
        )

        if not np.any(comp_mask):
            print("    Warning: No CTD data in comparison period")
            continue

        ctd_press_comp = np.nanmean(ctd_data[ctd_press].values[comp_mask])
        ctd_temp_comp = np.nanmean(ctd_data[ctd_temp].values[comp_mask])

        # Only get CTD conductivity if available
        if ctd_cond in ctd_data.data_vars:
            ctd_cond_comp = np.nanmean(ctd_data[ctd_cond].values[comp_mask])
        else:
            ctd_cond_comp = np.nan

        # Loop through each instrument
        for serial, inst_info in instrument_data.items():
            inst_data = inst_info["data"]
            inst_config = inst_info["config"]
            inst_type = inst_info["type"]

            # Convert instrument time to numeric
            inst_time_dt = pd.to_datetime(inst_data.time.values)
            inst_time_numeric = np.array([t.timestamp() for t in inst_time_dt])

            # Find instrument data during comparison period
            inst_comp_mask = (inst_time_numeric >= comp_start_ts) & (
                inst_time_numeric <= comp_end_ts
            )

            if not np.any(inst_comp_mask):
                continue

            # Get instrument variables - handle different naming conventions universally

            # Temperature
            inst_temp = np.nan
            inst_temp_std = np.nan
            temp_vars = ["tv290C", "temperature", "temp", "TEMP"]
            for var in temp_vars:
                if var in inst_data.data_vars:
                    inst_temp_values = inst_data[var].values[inst_comp_mask]
                    inst_temp = np.nanmean(inst_temp_values)
                    inst_temp_std = np.nanstd(inst_temp_values)
                    break

            # Conductivity (only if instrument has it)
            inst_cond = np.nan
            inst_cond_std = np.nan
            cond_vars = ["cond0mS/cm", "conductivity", "cond", "COND"]
            for var in cond_vars:
                if var in inst_data.data_vars:
                    inst_cond_values = inst_data[var].values[inst_comp_mask]
                    # Only use if not all NaN
                    if not np.all(np.isnan(inst_cond_values)):
                        inst_cond = np.nanmean(inst_cond_values)
                        inst_cond_std = np.nanstd(inst_cond_values)
                    break

            # Pressure (only if instrument has it)
            inst_press = np.nan
            inst_press_std = np.nan
            press_vars = ["prdM", "pressure", "press", "PRES"]
            for var in press_vars:
                if var in inst_data.data_vars:
                    inst_press_values = inst_data[var].values[inst_comp_mask]
                    inst_press = np.nanmean(inst_press_values)
                    inst_press_std = np.nanstd(inst_press_values)
                    break

            # Calculate differences
            temp_diff = inst_temp - ctd_temp_comp
            cond_diff = (
                inst_cond - ctd_cond_comp
                if not np.isnan(inst_cond) and not np.isnan(ctd_cond_comp)
                else np.nan
            )
            press_diff = (
                inst_press - ctd_press_comp if not np.isnan(inst_press) else np.nan
            )

            temp_status = _format_status(temp_diff, temp_threshold, "T")
            cond_status = _format_status(cond_diff, cond_threshold, "C")
            press_status = _format_status(press_diff, press_threshold, "P")

            # Extract date and time components
            date_part = comp_start.strftime("%Y-%m-%d")
            time_start = comp_start.strftime("%H:%M:%S")
            time_end = comp_end.strftime("%H:%M:%S")

            results.append(
                {
                    "serial": serial,
                    "instrument_type": inst_config.get("instrument", "unknown"),
                    "bl_press": round(stop["pressure"]),
                    "temp_diff": (
                        round(temp_diff, 4) if not np.isnan(temp_diff) else np.nan
                    ),
                    "temp_std": inst_temp_std,
                    "cond_diff": (
                        round(cond_diff, 4) if not np.isnan(cond_diff) else np.nan
                    ),
                    "cond_std": inst_cond_std,
                    "press_diff": (
                        round(press_diff, 1) if not np.isnan(press_diff) else np.nan
                    ),
                    "press_std": inst_press_std,
                    "temp_status": temp_status,
                    "cond_status": cond_status,
                    "press_status": press_status,
                    "date": date_part,
                    "time_start": time_start,
                    "time_end": time_end,
                    "ctd_temp": ctd_temp_comp,
                    "ctd_cond": ctd_cond_comp,
                    "inst_temp": inst_temp,
                    "inst_cond": inst_cond,
                    "inst_press": inst_press,
                    "N": int(np.sum(inst_comp_mask)),
                    "label": inst_config.get("label", "Unknown"),
                }
            )

    return pd.DataFrame(results)
