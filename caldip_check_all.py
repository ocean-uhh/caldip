#!/usr/bin/env python3
"""
Universal caldip check script for any instrument type.

This script can handle:
- MicroCAT data (SBE 37) from .cnv and .asc files
- RBR thermistor data from .rsk files  
- Any other instrument type supported by seasenselib
- Temperature-only or full T/C/P instruments

Generates the same statistics format as caldip_check.py but universally.

Usage:
    python caldip_check_all.py config_file.yaml [options]
    python caldip_check_all.py data_directory [options]
"""

import sys
import argparse
import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path
from typing import Dict, List
from scipy.interpolate import interp1d

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Import universal data loading modules
from caldip.data_loader import (
    load_caldip_config,
    load_instruments_from_config,
    load_reference_data
)
from caldip.tools import trim_data_to_deployment
import caldip.caldip_functions as cf


def find_config_file(path):
    """Find caldip configuration file in directory or use provided file."""
    path = Path(path)
    
    # If it's a YAML file, use it directly
    if path.is_file() and path.suffix in ['.yaml', '.yml']:
        return path
    
    # If it's a directory, look for .caldip.yaml files
    if path.is_dir():
        config_files = list(path.glob("*.caldip.yaml"))
        if config_files:
            return config_files[0]  # Use first config file found
        
        # Also check for .yaml files
        config_files = list(path.glob("*.yaml"))
        if config_files:
            return config_files[0]
    
    return None


def calculate_universal_statistics_by_bottle_stop(instrument_data: Dict, reference_data: Dict, 
                                                   config: Dict, ctd_sensor: int = 1) -> pd.DataFrame:
    """
    Calculate statistics for each bottle stop and each instrument (any type).
    
    Returns DataFrame with one row per bottle stop per instrument.
    """
    # Get the first (and likely only) reference dataset
    if not reference_data:
        print("No reference data available!")
        return pd.DataFrame()
    
    ref_name = list(reference_data.keys())[0]
    ctd_data = reference_data[ref_name]['data']
    
    # Get bottle stops using the detection function
    bottle_stops = cf.find_bottle_stops(ctd_data)
    
    if not bottle_stops:
        print("No bottle stops found!")
        return pd.DataFrame()
    
    print(f"Found {len(bottle_stops)} bottle stops for analysis")
    
    # Get CTD variable names
    if ctd_sensor == 1:
        ctd_temp = 't090C' if 't090C' in ctd_data else 'temp1'
        ctd_cond = 'c0mS/cm' if 'c0mS/cm' in ctd_data else 'cond1'
    else:
        ctd_temp = 't190C' if 't190C' in ctd_data else 'temp2'
        ctd_cond = 'c1mS/cm' if 'c1mS/cm' in ctd_data else 'cond2'
    
    ctd_press = 'prDM' if 'prDM' in ctd_data else 'press'
    
    # Convert CTD time to numeric for interpolation
    ctd_time_dt = pd.to_datetime(ctd_data.time.values)
    ctd_time_numeric = np.array([t.timestamp() for t in ctd_time_dt])
    
    # Create interpolation functions for CTD data
    interp_press = interp1d(ctd_time_numeric, ctd_data[ctd_press].values, 
                           bounds_error=False, fill_value=np.nan)
    interp_temp = interp1d(ctd_time_numeric, ctd_data[ctd_temp].values,
                          bounds_error=False, fill_value=np.nan)
    
    # Only create conductivity interpolation if CTD has conductivity
    interp_cond = None
    if ctd_cond in ctd_data.data_vars:
        interp_cond = interp1d(ctd_time_numeric, ctd_data[ctd_cond].values,
                              bounds_error=False, fill_value=np.nan)
    
    results = []
    
    # Loop through each bottle stop
    for stop_num, stop in enumerate(bottle_stops, 1):
        
        # Calculate comparison period (last 2 minutes ending 30 seconds before stop end)
        stop_end_dt = pd.to_datetime(stop['end_time'])
        comp_end = stop_end_dt - pd.Timedelta(seconds=30)
        comp_start = comp_end - pd.Timedelta(minutes=2)
        
        comp_start_ts = comp_start.timestamp()
        comp_end_ts = comp_end.timestamp()
        
        print(f"  Stop {stop_num} at {stop['pressure']:.1f} dbar: comparison period {comp_start} to {comp_end}")
        
        # Get CTD data during comparison period
        comp_mask = (ctd_time_numeric >= comp_start_ts) & (ctd_time_numeric <= comp_end_ts)
        
        if not np.any(comp_mask):
            print(f"    Warning: No CTD data in comparison period")
            continue
            
        ctd_press_comp = np.nanmean(ctd_data[ctd_press].values[comp_mask])
        ctd_temp_comp = np.nanmean(ctd_data[ctd_temp].values[comp_mask])
        
        # Only get CTD conductivity if available
        if interp_cond is not None:
            ctd_cond_comp = np.nanmean(ctd_data[ctd_cond].values[comp_mask])
        else:
            ctd_cond_comp = np.nan
        
        # Loop through each instrument
        for serial, inst_info in instrument_data.items():
            inst_data = inst_info['data']
            inst_config = inst_info['config']
            inst_type = inst_info['type']
            
            # Convert instrument time to numeric
            inst_time_dt = pd.to_datetime(inst_data.time.values)
            inst_time_numeric = np.array([t.timestamp() for t in inst_time_dt])
            
            # Find instrument data during comparison period
            inst_comp_mask = (inst_time_numeric >= comp_start_ts) & (inst_time_numeric <= comp_end_ts)
            
            if not np.any(inst_comp_mask):
                continue
            
            # Get instrument variables - handle different naming conventions universally
            
            # Temperature
            inst_temp = np.nan
            inst_temp_std = np.nan
            temp_vars = ['tv290C', 'temperature', 'temp', 'TEMP']
            for var in temp_vars:
                if var in inst_data.data_vars:
                    inst_temp_values = inst_data[var].values[inst_comp_mask]
                    inst_temp = np.nanmean(inst_temp_values)
                    inst_temp_std = np.nanstd(inst_temp_values)
                    break
                    
            # Conductivity (only if instrument has it)
            inst_cond = np.nan
            inst_cond_std = np.nan
            cond_vars = ['cond0mS/cm', 'conductivity', 'cond', 'COND']
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
            press_vars = ['prdM', 'pressure', 'press', 'PRES']
            for var in press_vars:
                if var in inst_data.data_vars:
                    inst_press_values = inst_data[var].values[inst_comp_mask]
                    inst_press = np.nanmean(inst_press_values)
                    inst_press_std = np.nanstd(inst_press_values)
                    break
            
            # Calculate differences
            temp_diff = inst_temp - ctd_temp_comp
            cond_diff = inst_cond - ctd_cond_comp if not np.isnan(inst_cond) and not np.isnan(ctd_cond_comp) else np.nan
            press_diff = inst_press - ctd_press_comp if not np.isnan(inst_press) else np.nan
            
            # Quality flags (thresholds: T ±0.005°C, C ±0.02 mS/cm, P ±5 dbar)
            def format_status(diff, threshold, var_name):
                if np.isnan(diff):
                    return f"{var_name} NO DATA"
                elif abs(diff) <= threshold:
                    return f"{var_name} OK"
                elif diff > 0:
                    return f"{var_name} reads high by {abs(diff):.3f}"
                else:
                    return f"{var_name} reads low by {abs(diff):.3f}"
            
            temp_status = format_status(temp_diff, 0.005, "T")
            cond_status = format_status(cond_diff, 0.02, "C") if not np.isnan(inst_cond) else "C NO DATA"
            press_status = format_status(press_diff, 5.0, "P") if not np.isnan(inst_press) else "P NO DATA"
            
            # Extract date and time components  
            date_part = comp_start.strftime('%Y-%m-%d')
            time_start = comp_start.strftime('%H:%M:%S')
            time_end = comp_end.strftime('%H:%M:%S')
            
            results.append({
                'serial': serial,
                'instrument_type': inst_config.get('instrument', 'unknown'),
                'label': inst_config.get('label', 'Unknown'),
                'bl_press': round(stop['pressure']),
                'N': int(np.sum(inst_comp_mask)),
                'date': date_part,
                'time_start': time_start,
                'time_end': time_end,
                'ctd_temp': ctd_temp_comp,
                'ctd_cond': ctd_cond_comp if not np.isnan(ctd_cond_comp) else '',
                'inst_temp': inst_temp,
                'inst_cond': inst_cond if not np.isnan(inst_cond) else '',
                'inst_press': inst_press if not np.isnan(inst_press) else '',
                'temp_diff': round(temp_diff, 4) if not np.isnan(temp_diff) else '',
                'temp_std': inst_temp_std,
                'cond_diff': round(cond_diff, 4) if not np.isnan(cond_diff) else '',
                'cond_std': inst_cond_std if not np.isnan(inst_cond_std) else '',
                'press_diff': round(press_diff, 1) if not np.isnan(press_diff) else '',
                'press_std': inst_press_std if not np.isnan(inst_press_std) else '',
                'temp_status': temp_status,
                'cond_status': cond_status,
                'press_status': press_status
            })
    
    return pd.DataFrame(results)


def calculate_stats_for_time_period(data: xr.Dataset, start_time: pd.Timestamp, end_time: pd.Timestamp, 
                                   variables: List[str]) -> Dict:
    """
    Calculate statistics for any dataset within a specified time period.
    
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
    # Convert dataset time to numeric
    time_numeric = pd.to_datetime(data.time.values).astype(np.int64) / 1e9
    start_ts = start_time.timestamp()
    end_ts = end_time.timestamp()
    
    # Create time mask
    time_mask = (time_numeric >= start_ts) & (time_numeric <= end_ts)
    n_samples = np.sum(time_mask)
    
    stats = {'n_samples': n_samples}
    
    # Calculate stats for each requested variable
    for var in variables:
        if var in data.data_vars and n_samples > 0:
            var_data = data[var].values[time_mask]
            if len(var_data) > 0:
                stats[f'mean_{var}'] = np.nanmean(var_data)
                stats[f'std_{var}'] = np.nanstd(var_data)
            else:
                stats[f'mean_{var}'] = np.nan
                stats[f'std_{var}'] = np.nan
        else:
            stats[f'mean_{var}'] = np.nan
            stats[f'std_{var}'] = np.nan
            
    return stats




def extract_summary_from_detailed_stats(detailed_stats_df: pd.DataFrame, config: Dict) -> pd.DataFrame:
    """
    Extract summary statistics from detailed bottle stop statistics.
    Uses the deepest bottle stop data for each instrument.
    """
    if detailed_stats_df.empty:
        return pd.DataFrame()
    
    # Find deepest bottle stop for each instrument
    summary_rows = []
    
    for serial in detailed_stats_df['serial'].unique():
        inst_data = detailed_stats_df[detailed_stats_df['serial'] == serial]
        
        # Get the deepest bottle stop row for this instrument
        deepest_row = inst_data.loc[inst_data['bl_press'].idxmax()]
        
        # Convert empty strings to NaN for proper numeric handling
        def convert_empty_to_nan(value):
            return np.nan if value == '' else value
        
        summary_rows.append({
            'serial': deepest_row['serial'],
            'instrument_type': deepest_row['instrument_type'], 
            'label': deepest_row['label'],
            'N': deepest_row['N'],  # Column is named 'N' in detailed stats
            'bl_press': deepest_row.get('bl_press'),  # May not exist
            'temp_diff': convert_empty_to_nan(deepest_row['temp_diff']),
            'temp_diff_std': convert_empty_to_nan(deepest_row['temp_std']),
            'cond_diff': convert_empty_to_nan(deepest_row['cond_diff']),
            'cond_diff_std': convert_empty_to_nan(deepest_row['cond_std']),
            'press_diff': convert_empty_to_nan(deepest_row['press_diff']),
            'press_diff_std': convert_empty_to_nan(deepest_row['press_std']),
        })
    
    summary_df = pd.DataFrame(summary_rows)
    
    # Add ctd_stats using the deepest bottle stop data (same as what's used for instruments)
    if not detailed_stats_df.empty:
        # Find the deepest bottle stop row (same logic as instruments)
        deepest_ctd_row = detailed_stats_df.loc[detailed_stats_df['bl_press'].idxmax()]
        
        ctd_stats = {
            'comparison_start': deepest_ctd_row['time_start'],
            'comparison_end': deepest_ctd_row['time_end'],
            'mean_temp': deepest_ctd_row['ctd_temp'],
            'mean_cond': deepest_ctd_row['ctd_cond'],
            'mean_pressure': deepest_ctd_row['bl_press'],
            'bl_press': deepest_ctd_row['bl_press'],  # For print statement
            'ctd_temp': deepest_ctd_row['ctd_temp'],  # For print statement  
            'ctd_cond': deepest_ctd_row['ctd_cond'],  # For print statement
            # Note: CTD std values aren't in detailed stats - using placeholder
            'press_std': 0.0,  # Placeholder - not available in detailed stats
            'temp_std': 0.0,   # Placeholder - not available in detailed stats  
            'cond_std': 0.0,   # Placeholder - not available in detailed stats
            'timing_info': {'bottle_stops': []}  # placeholder
        }
        summary_df['ctd_stats'] = [ctd_stats] * len(summary_df)
    
    return summary_df


def print_universal_statistics_report(stats_df: pd.DataFrame, config: Dict, ctd_sensor: int = 1):
    """Print formatted statistics report for universal instrument types."""
    
    print("\n" + "="*80)
    print(f"UNIVERSAL CALDIP CHECK REPORT - {config['name']}")
    print("="*80)
    
    # CTD statistics
    ctd_stats = stats_df.iloc[0]['ctd_stats']
    
    # Timing information
    print(f"\nTiming Information:")
    
    # Show all bottle stops if available
    if 'timing_info' in ctd_stats and 'bottle_stops' in ctd_stats['timing_info']:
        bottle_stops = ctd_stats['timing_info']['bottle_stops']
        print(f"  Found {len(bottle_stops)} bottle stop(s):")
        for i, stop in enumerate(bottle_stops, 1):
            print(f"\n  Bottle Stop {i}:")
            print(f"    Start: {stop['start_time']}")
            print(f"    End: {stop['end_time']}")
            print(f"    Duration: {stop['duration_seconds']/60:.1f} minutes")
            print(f"    Pressure: {stop['pressure']:.1f} dbar")
        print(f"\n  Using deepest bottle stop for comparison:")
    else:
        print(f"  Bottle stop period to compare:")
    
    print(f"    Start: {ctd_stats['comparison_start']}")
    print(f"    End: {ctd_stats['comparison_end']}")
    
    print(f"\nCTD Statistics (Sensor {ctd_sensor}) during comparison period:")
    print(f"  Mean Pressure: {ctd_stats['bl_press']:.1f} dbar (std: {ctd_stats['press_std']:.2f})")
    print(f"  Mean Temperature: {ctd_stats['ctd_temp']:.4f} °C (std: {ctd_stats['temp_std']:.5f})")
    if 'mean_cond' in ctd_stats:
        print(f"  Mean Conductivity: {ctd_stats['ctd_cond']:.3f} mS/cm (std: {ctd_stats['cond_std']:.4f})")
    
    # Instrument statistics
    print(f"\nNumber of Instruments: {len(stats_df)}")
    
    # Group by instrument type
    type_counts = stats_df['instrument_type'].value_counts()
    print("Instrument Types:")
    for inst_type, count in type_counts.items():
        print(f"  {inst_type}: {count}")
    
    print("\nInstrument Comparison Statistics:")
    print("-"*80)
    print("Serial  Type    Samples  Temp Diff (°C)        Cond Diff (mS/cm)     Press Diff (dbar)")
    print("                         Mean      Std         Mean      Std         Mean      Std")
    print("-"*80)
    
    for _, row in stats_df.iterrows():
        # Format conductivity and pressure with proper handling of NaN
        cond_mean = f"{row['cond_diff']:8.2f}" if not np.isnan(row['cond_diff']) else "     N/A"
        cond_std = f"{row['cond_diff_std']:8.3f}" if not np.isnan(row['cond_diff_std']) else "     N/A"
        press_mean = f"{row['press_diff']:7.2f}" if not np.isnan(row['press_diff']) else "    N/A"
        press_std = f"{row['press_diff_std']:7.2f}" if not np.isnan(row['press_diff_std']) else "    N/A"
        
        print(f"{row['serial']:6s}  {row['instrument_type']:6s}  {row['N']:6d}  "
              f"{row['temp_diff']:8.3f}  {row['temp_diff_std']:8.4f}  "
              f"{cond_mean}  {cond_std}  "
              f"{press_mean}  {press_std}")
    
    print("="*80)


def main():
    """Main function for universal caldip check."""
    parser = argparse.ArgumentParser(
        description="Universal caldip analysis for any instrument type",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze using config file
  python caldip_check_all.py castM6/castM6.caldip.yaml --output results.csv
  
  # Analyze by pointing to directory (auto-finds config)
  python caldip_check_all.py data/proc_calib/msm142_2026/cal_dip/castM6/
  
  # Use CTD sensor 2 and save to specific directory
  python caldip_check_all.py config.yaml --ctd-sensor 2 --output-dir /path/to/results/
        """
    )
    
    parser.add_argument("config_path", 
                       help="Path to .caldip.yaml config file or directory containing config")
    parser.add_argument("--ctd-sensor", type=int, default=1, choices=[1, 2],
                       help="Which CTD sensor to use (1 or 2, default: 1)")
    parser.add_argument("--output", "-o", 
                       help="Output CSV file for detailed statistics")
    parser.add_argument("--output-dir", 
                       help="Directory to save output files (default: parent of data dir)")
    parser.add_argument("--data-dir", 
                       help="Override data directory from config")
    
    args = parser.parse_args()
    
    # Find configuration file
    config_file = find_config_file(args.config_path)
    if not config_file:
        print(f"Error: No caldip configuration file found in {args.config_path}")
        print("Looking for files matching: *.caldip.yaml or *.yaml")
        return 1
    
    print(f"Using config file: {config_file}")
    
    # Load configuration
    try:
        config = load_caldip_config(config_file)
        print(f"Loaded config for: {config.get('name', 'Unknown')}")
    except Exception as e:
        print(f"Error loading config file: {e}")
        return 1
    
    # Determine data directory
    if args.data_dir:
        data_dir = Path(args.data_dir)
    elif config_file.parent.name.startswith('cast'):
        # Config is in the data directory
        data_dir = config_file.parent
    else:
        # Use directory from config
        data_dir = Path(config.get('directory', config_file.parent))
    
    print(f"Using data directory: {data_dir}")
    
    if not data_dir.exists():
        print(f"Error: Data directory does not exist: {data_dir}")
        return 1
    
    print("="*60)
    
    # Load instrument data
    print("Loading instrument data...")
    try:
        instruments = load_instruments_from_config(config, data_dir)
    except Exception as e:
        print(f"Error loading instrument data: {e}")
        return 1
    
    # Load reference data
    print("\nLoading reference data...")
    try:
        reference_data = load_reference_data(config, data_dir)
    except Exception as e:
        print(f"Error loading reference data: {e}")
        return 1
    
    if not instruments and not reference_data:
        print("Error: No data could be loaded!")
        return 1
    
    # Trim data to deployment period
    if 'deployment_time' in config and 'recovery_time' in config:
        print()
        instruments, reference_data = trim_data_to_deployment(
            instruments, reference_data, config
        )
    
    print(f"\nLoaded:")
    print(f"  Instruments: {len(instruments)}")
    print(f"  Reference datasets: {len(reference_data)}")
    
    # Calculate statistics
    print("\nCalculating statistics...")
    
    try:
        # Detailed statistics (per bottle stop)
        detailed_stats_df = calculate_universal_statistics_by_bottle_stop(instruments, reference_data, config, args.ctd_sensor)
        
        # Summary statistics - extract from deepest bottle stop in detailed stats
        stats_df = extract_summary_from_detailed_stats(detailed_stats_df, config)
        
        # Print report
        print_universal_statistics_report(stats_df, config, args.ctd_sensor)
        
    except Exception as e:
        print(f"Error calculating statistics: {e}")
        return 1
    
    # Save outputs
    if args.output_dir:
        output_path = Path(args.output_dir)
    elif args.output:
        output_path = Path(args.output).parent
    else:
        # Save in cal_dip directory (parent of castM1, castM2, etc)
        output_path = data_dir.parent
    
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Save detailed statistics (one row per bottle stop per instrument)
    if args.output:
        detailed_csv_file = Path(args.output)
    else:
        detailed_csv_file = output_path / f"{config['name']}_detailed_statistics.csv"
    
    if not detailed_stats_df.empty:
        # Round floating point columns for detailed CSV
        detailed_float_cols = ['ctd_temp', 'ctd_cond', 'inst_temp', 'inst_cond', 'inst_press', 
                               'temp_std', 'cond_std', 'press_std']
        
        detailed_csv_df = detailed_stats_df.copy()
        for col in detailed_float_cols:
            if col in detailed_csv_df.columns and not detailed_csv_df[col].empty:
                # Only process non-empty string columns
                detailed_csv_df[col] = detailed_csv_df[col].apply(
                    lambda x: round(x, 5) if isinstance(x, (int, float)) and not pd.isna(x) else x
                )
        
        # Add CTD sensor information to the DataFrame
        detailed_csv_df['ctd_sensor_used'] = args.ctd_sensor
        
        # Sort by serial number, then by bottle depth
        detailed_csv_df = detailed_csv_df.sort_values(['serial', 'bl_press'], ascending=[True, False]).reset_index(drop=True)
        
        detailed_csv_df.to_csv(detailed_csv_file, index=False)
        print(f"\nSaved detailed statistics to {detailed_csv_file}")
        print(f"  Contains {len(detailed_stats_df)} rows ({len(detailed_stats_df['bl_press'].unique())} bottle stops × {len(detailed_stats_df['serial'].unique())} instruments)")
    
    # Save summary statistics (clean format using deepest bottle stop data)
    summary_csv_file = output_path / f"{config['name']}_summary_statistics.csv"
    
    # Create clean summary CSV with consistent columns
    csv_df = stats_df.drop('ctd_stats', axis=1).copy()
    
    # Rename columns to match expected format and round appropriately
    csv_df = csv_df.rename(columns={
        'N': 'n_samples',
        'temp_diff': 'temp_diff_mean',
        'temp_diff_std': 'temp_diff_std',
        'cond_diff': 'cond_diff_mean', 
        'cond_diff_std': 'cond_diff_std',
        'press_diff': 'press_diff_mean',
        'press_diff_std': 'press_diff_std'
    })
    
    # Round floating point columns with appropriate precision
    csv_df['temp_diff_mean'] = csv_df['temp_diff_mean'].round(3)
    csv_df['temp_diff_std'] = csv_df['temp_diff_std'].round(4)
    csv_df['cond_diff_mean'] = csv_df['cond_diff_mean'].round(3)
    csv_df['cond_diff_std'] = csv_df['cond_diff_std'].round(4)
    csv_df['press_diff_mean'] = csv_df['press_diff_mean'].round(2)
    csv_df['press_diff_std'] = csv_df['press_diff_std'].round(2)
    
    csv_df.to_csv(summary_csv_file, index=False)
    print(f"Saved summary statistics to {summary_csv_file}")
    
    # Save timing information - rewrite to reflect the actual detailed analysis
    timing_file = output_path / f"{config['name']}_timing.txt"
    
    # Get bottle stops from the detailed analysis function instead
    ref_name = list(reference_data.keys())[0]
    ctd_data = reference_data[ref_name]['data']
    bottle_stops = cf.find_bottle_stops(ctd_data)
    
    with open(timing_file, 'w') as f:
        f.write(f"UNIVERSAL CALDIP TIMING REPORT - {config['name']}\n")
        f.write("="*60 + "\n\n")
        
        if bottle_stops:
            f.write(f"Found {len(bottle_stops)} bottle stop(s):\n\n")
            for i, stop in enumerate(bottle_stops, 1):
                f.write(f"Bottle Stop {i}:\n")
                f.write(f"  Start: {stop['start_time']}\n")
                f.write(f"  End: {stop['end_time']}\n")
                f.write(f"  Duration: {stop['duration_seconds']/60:.1f} minutes\n")
                f.write(f"  Pressure: {stop['pressure']:.1f} dbar\n\n")
                
            f.write(f"DETAILED ANALYSIS METHOD:\n")
            f.write(f"  - Analyzes ALL {len(bottle_stops)} bottle stops individually\n")
            f.write(f"  - For each stop: 2-minute comparison period ending 30 seconds before stop end\n")
            f.write(f"  - Generates {len(bottle_stops)} × {len(instruments)} = {len(bottle_stops) * len(instruments)} comparison rows\n")
            f.write(f"  - Each instrument compared against CTD during each bottle stop\n\n")
            
            f.write(f"COMPARISON PERIODS (per bottle stop):\n")
            for i, stop in enumerate(bottle_stops, 1):
                stop_end_dt = pd.to_datetime(stop['end_time'])
                comp_end = stop_end_dt - pd.Timedelta(seconds=30)
                comp_start = comp_end - pd.Timedelta(minutes=2)
                f.write(f"  Stop {i} ({stop['pressure']:.0f} dbar): {comp_start.strftime('%H:%M:%S')} to {comp_end.strftime('%H:%M:%S')}\n")
        else:
            f.write(f"No bottle stops detected.\n")
        
        f.write(f"\nCTD sensor used: {args.ctd_sensor}\n")
        
        # Write instrument summary
        type_counts = stats_df['instrument_type'].value_counts()
        f.write(f"\nInstruments analyzed:\n")
        for inst_type, count in type_counts.items():
            f.write(f"  {inst_type}: {count}\n")
        
        f.write(f"\nOutput files:\n")
        f.write(f"  - Detailed statistics: {len(bottle_stops)} bottle stops × {len(instruments)} instruments\n")
        f.write(f"  - Summary statistics: Overall statistics (for legacy compatibility)\n")
    
    print(f"Saved timing information to {timing_file}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())