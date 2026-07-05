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
import pandas as pd
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Import universal data loading modules
from caldip.readers import (
    find_config_file,
    load_caldip_config,
    load_instruments_from_config,
    load_reference_data,
)
from caldip.tools import trim_data_to_deployment, extract_summary_from_detailed_stats
from caldip.writers import print_universal_statistics_report
import caldip.caldip_functions as cf


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
        """,
    )

    parser.add_argument(
        "config_path",
        help="Path to .caldip.yaml config file or directory containing config",
    )
    parser.add_argument(
        "--ctd-sensor",
        type=int,
        default=None,
        choices=[1, 2],
        help="Which CTD sensor to use (1 or 2). Overrides ctd_sensors in YAML. Default: read from YAML, or 1.",
    )
    parser.add_argument(
        "--output", "-o", help="Output CSV file for detailed statistics"
    )
    parser.add_argument(
        "--output-dir",
        help="Directory to save output files (default: parent of data dir)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=10.0,
        help="Bottle stop detection threshold (dbar/min, default: 10.0)",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=180.0,
        help="Minimum bottle stop duration (seconds, default: 180.0)",
    )
    parser.add_argument("--data-dir", help="Override data directory from config")

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

    # Resolve CTD sensor: CLI flag overrides YAML field; YAML overrides default of 1
    if args.ctd_sensor is not None:
        ctd_sensor = args.ctd_sensor
    else:
        ctd_sensor = int(config.get("ctd_sensors", 1))
        if ctd_sensor not in (1, 2):
            print(f"Warning: ctd_sensors={ctd_sensor} in YAML is not 1 or 2; using 1")
            ctd_sensor = 1
    print(f"Using CTD sensor: {ctd_sensor}")

    # Determine data directory
    if args.data_dir:
        data_dir = Path(args.data_dir)
    elif config_file.parent.name.startswith("cast"):
        # Config is in the data directory
        data_dir = config_file.parent
    else:
        # Use directory from config
        data_dir = Path(config.get("directory", config_file.parent))

    print(f"Using data directory: {data_dir}")

    if not data_dir.exists():
        print(f"Error: Data directory does not exist: {data_dir}")
        return 1

    print("=" * 60)

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
    if "deployment_time" in config and "recovery_time" in config:
        print()
        instruments, reference_data = trim_data_to_deployment(
            instruments, reference_data, config
        )

    print("\nLoaded:")
    print(f"  Instruments: {len(instruments)}")
    print(f"  Reference datasets: {len(reference_data)}")

    # Calculate statistics
    print("\nCalculating statistics...")

    try:
        # Detailed statistics (per bottle stop)
        detailed_stats_df = cf.calculate_universal_statistics_by_bottle_stop(
            instruments,
            reference_data,
            config,
            ctd_sensor,
            threshold_dbar_per_min=args.threshold,
            min_duration_seconds=args.min_duration,
        )

        # Summary statistics - extract from deepest bottle stop in detailed stats
        stats_df = extract_summary_from_detailed_stats(detailed_stats_df, config)

        # Print report
        print_universal_statistics_report(stats_df, config, ctd_sensor)

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
        detailed_float_cols = [
            "ctd_temp",
            "ctd_cond",
            "inst_temp",
            "inst_cond",
            "inst_press",
            "temp_std",
            "cond_std",
            "press_std",
        ]

        detailed_csv_df = detailed_stats_df.copy()
        for col in detailed_float_cols:
            if col in detailed_csv_df.columns and not detailed_csv_df[col].empty:
                # Only process non-empty string columns
                detailed_csv_df[col] = detailed_csv_df[col].apply(
                    lambda x: (
                        round(x, 5)
                        if isinstance(x, (int, float)) and not pd.isna(x)
                        else x
                    )
                )

        # Add CTD sensor information to the DataFrame
        detailed_csv_df["ctd_sensor_used"] = ctd_sensor

        # Sort by serial number, then by bottle depth
        detailed_csv_df = detailed_csv_df.sort_values(
            ["serial", "bl_press"], ascending=[True, False]
        ).reset_index(drop=True)

        detailed_csv_df.to_csv(detailed_csv_file, index=False)
        print(f"\nSaved detailed statistics to {detailed_csv_file}")
        print(
            f"  Contains {len(detailed_stats_df)} rows ({len(detailed_stats_df['bl_press'].unique())} bottle stops × {len(detailed_stats_df['serial'].unique())} instruments)"
        )

    # Save summary statistics (clean format using deepest bottle stop data)
    summary_csv_file = output_path / f"{config['name']}_summary_statistics.csv"

    # Create clean summary CSV with consistent columns
    csv_df = stats_df.drop("ctd_stats", axis=1).copy()

    # Rename columns to match expected format and round appropriately
    csv_df = csv_df.rename(
        columns={
            "N": "n_samples",
            "temp_diff": "temp_diff_mean",
            "temp_diff_std": "temp_diff_std",
            "cond_diff": "cond_diff_mean",
            "cond_diff_std": "cond_diff_std",
            "press_diff": "press_diff_mean",
            "press_diff_std": "press_diff_std",
        }
    )

    # Round floating point columns with appropriate precision
    csv_df["temp_diff_mean"] = csv_df["temp_diff_mean"].round(3)
    csv_df["temp_diff_std"] = csv_df["temp_diff_std"].round(4)
    csv_df["cond_diff_mean"] = csv_df["cond_diff_mean"].round(3)
    csv_df["cond_diff_std"] = csv_df["cond_diff_std"].round(4)
    csv_df["press_diff_mean"] = csv_df["press_diff_mean"].round(2)
    csv_df["press_diff_std"] = csv_df["press_diff_std"].round(2)

    csv_df.to_csv(summary_csv_file, index=False)
    print(f"Saved summary statistics to {summary_csv_file}")

    # Save timing information - rewrite to reflect the actual detailed analysis
    timing_file = output_path / f"{config['name']}_timing.txt"

    # Get bottle stops from the detailed analysis function instead
    ref_name = list(reference_data.keys())[0]
    ctd_data = reference_data[ref_name]["data"]
    bottle_stops = cf.find_bottle_stops(ctd_data)

    with open(timing_file, "w") as f:
        f.write(f"UNIVERSAL CALDIP TIMING REPORT - {config['name']}\n")
        f.write("=" * 60 + "\n\n")

        if bottle_stops:
            f.write(f"Found {len(bottle_stops)} bottle stop(s):\n\n")
            for i, stop in enumerate(bottle_stops, 1):
                f.write(f"Bottle Stop {i}:\n")
                f.write(f"  Start: {stop['start_time']}\n")
                f.write(f"  End: {stop['end_time']}\n")
                f.write(f"  Duration: {stop['duration_seconds']/60:.1f} minutes\n")
                f.write(f"  Pressure: {stop['pressure']:.1f} dbar\n\n")

            f.write("DETAILED ANALYSIS METHOD:\n")
            f.write(f"  - Analyzes ALL {len(bottle_stops)} bottle stops individually\n")
            f.write(
                "  - For each stop: 2-minute comparison period ending 30 seconds before stop end\n"
            )
            f.write(
                f"  - Generates {len(bottle_stops)} × {len(instruments)} = {len(bottle_stops) * len(instruments)} comparison rows\n"
            )
            f.write(
                "  - Each instrument compared against CTD during each bottle stop\n\n"
            )

            f.write("COMPARISON PERIODS (per bottle stop):\n")
            for i, stop in enumerate(bottle_stops, 1):
                stop_end_dt = pd.to_datetime(stop["end_time"])
                comp_end = stop_end_dt - pd.Timedelta(seconds=30)
                comp_start = comp_end - pd.Timedelta(minutes=2)
                f.write(
                    f"  Stop {i} ({stop['pressure']:.0f} dbar): {comp_start.strftime('%H:%M:%S')} to {comp_end.strftime('%H:%M:%S')}\n"
                )
        else:
            f.write("No bottle stops detected.\n")

        f.write(f"\nCTD sensor used: {ctd_sensor}\n")

        # Write instrument summary
        type_counts = stats_df["instrument_type"].value_counts()
        f.write("\nInstruments analyzed:\n")
        for inst_type, count in type_counts.items():
            f.write(f"  {inst_type}: {count}\n")

        f.write("\nOutput files:\n")
        f.write(
            f"  - Detailed statistics: {len(bottle_stops)} bottle stops × {len(instruments)} instruments\n"
        )
        f.write(
            "  - Summary statistics: Overall statistics (for legacy compatibility)\n"
        )

    print(f"Saved timing information to {timing_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
