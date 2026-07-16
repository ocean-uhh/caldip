"""
Output formatting functions for caldip processing.

This module contains functions for formatting and writing caldip analysis results
to various output formats (console, CSV, NetCDF, etc.).

Currently Used Functions:
- save_instrument_nc() -> bool
  Save a normalized instrument Dataset to NetCDF, sanitizing un-serializable attrs
- print_stats_report() -> None
  Print formatted statistics report to console
"""

import datetime
import numpy as np
import pandas as pd
import xarray as xr
from typing import Dict


def save_instrument_nc(ds: xr.Dataset, path, label: str) -> bool:
    """Save instrument Dataset to NetCDF, converting un-serializable attrs to strings.

    Returns True on success, False on failure.
    """
    try:
        out = ds.copy()
        cleaned = {}
        for k, v in out.attrs.items():
            if v is None:
                continue
            if isinstance(v, datetime.datetime):
                cleaned[k] = v.isoformat()
            else:
                cleaned[k] = v
        out.attrs = cleaned
        out.to_netcdf(path)
        print(f"  💾 Saved {label} ({len(ds.time)} samples)")
        return True
    except Exception as _e:
        print(f"  ⚠️  {label} save failed: {_e}")
        return False


def print_stats_report(stats_df: pd.DataFrame, config: Dict):
    """Print formatted statistics report for universal instrument types."""

    print("\n" + "=" * 80)
    print(f"UNIVERSAL CALDIP CHECK REPORT - {config['name']}")
    print("=" * 80)

    # CTD statistics
    ctd_stats = stats_df.iloc[0]["ctd_stats"]

    # Timing information
    print("\nTiming Information:")

    # Show all bottle stops if available
    if "timing_info" in ctd_stats and "bottle_stops" in ctd_stats["timing_info"]:
        bottle_stops = ctd_stats["timing_info"]["bottle_stops"]
        print(f"  Found {len(bottle_stops)} bottle stop(s):")
        for i, stop in enumerate(bottle_stops, 1):
            print(f"\n  Bottle Stop {i}:")
            print(f"    Start: {stop['start_time']}")
            print(f"    End: {stop['end_time']}")
            print(f"    Duration: {stop['duration_seconds'] / 60:.1f} minutes")
            print(f"    Pressure: {stop['pressure']:.1f} dbar")
        print("\n  Using deepest bottle stop for comparison:")
    else:
        print("  Bottle stop period to compare:")

    print(f"    Start: {ctd_stats['comparison_start']}")
    print(f"    End: {ctd_stats['comparison_end']}")

    print("\nCTD Statistics during comparison period:")
    print(
        f"  Mean Pressure: {ctd_stats['bl_press']:.1f} dbar (std: {ctd_stats['press_std']:.2f})"
    )
    print(
        f"  Mean Temperature: {ctd_stats['ctd_temp']:.4f} °C (std: {ctd_stats['temp_std']:.5f})"
    )
    if "mean_cond" in ctd_stats:
        print(
            f"  Mean Conductivity: {ctd_stats['ctd_cond']:.3f} mS/cm (std: {ctd_stats['cond_std']:.4f})"
        )

    # Instrument statistics
    print(f"\nNumber of Instruments: {len(stats_df)}")

    # Group by instrument type
    type_counts = stats_df["instrument_type"].value_counts()
    print("Instrument Types:")
    for inst_type, count in type_counts.items():
        print(f"  {inst_type}: {count}")

    print("\nInstrument Comparison Statistics:")
    print("-" * 80)
    print(
        "Serial  Type    Samples  Temp Diff (°C)        Cond Diff (mS/cm)     Press Diff (dbar)"
    )
    print(
        "                         Mean      Std         Mean      Std         Mean      Std"
    )
    print("-" * 80)

    for _, row in stats_df.iterrows():
        # Format conductivity and pressure with proper handling of NaN
        cond_mean = (
            f"{row['cond_diff']:8.2f}" if not np.isnan(row["cond_diff"]) else "     N/A"
        )
        cond_std = (
            f"{row['cond_diff_std']:8.3f}"
            if not np.isnan(row["cond_diff_std"])
            else "     N/A"
        )
        press_mean = (
            f"{row['press_diff']:7.2f}"
            if not np.isnan(row["press_diff"])
            else "    N/A"
        )
        press_std = (
            f"{row['press_diff_std']:7.2f}"
            if not np.isnan(row["press_diff_std"])
            else "    N/A"
        )

        print(
            f"{row['serial']:6s}  {row['instrument_type']:6s}  {row['N']:6d}  "
            f"{row['temp_diff']:8.3f}  {row['temp_diff_std']:8.4f}  "
            f"{cond_mean}  {cond_std}  "
            f"{press_mean}  {press_std}"
        )

    print("=" * 80)
