"""caldip stats — per-bottle-stop statistics vs CTD reference."""

import sys
import argparse
from pathlib import Path

import pandas as pd

from caldip.readers import (
    find_config_file,
    load_config,
    load_instruments_from_config,
    load_reference_data,
    resolve_data_dir,
)
from caldip.tools import trim_to_deployment, summary_stats
from caldip._writers import print_stats_report
import caldip.core as core


def build_parser(subparsers=None):
    kwargs = dict(
        help="per-bottle-stop statistics for instruments vs CTD reference",
        description="Per-bottle-stop statistics for instruments vs CTD reference",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  caldip stats data/proc_calib/msm142_2026/cal_dip/castM4/
  caldip stats castM4/castM4.caldip.yaml -o outputs/
  caldip stats castM4/castM4.caldip.yaml --output castM4_rev2 -o outputs/
  caldip stats castM4/castM4.caldip.yaml --ctd-sensor 2
        """,
    )
    if subparsers is not None:
        parser = subparsers.add_parser("stats", **kwargs)
    else:
        parser = argparse.ArgumentParser(prog="caldip stats", **kwargs)

    parser.add_argument(
        "config_path",
        help="Path to .caldip.yaml config file or directory containing config",
    )
    parser.add_argument(
        "--output",
        help="Base filename for output files without extension; overrides cast name",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        help="Directory to save output files (default: parent of data dir)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=10.0,
        help="Bottle stop detection threshold in dbar/min (default: 10.0)",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=180.0,
        help="Minimum bottle stop duration in seconds (default: 180.0)",
    )
    parser.add_argument(
        "--ctd-sensor",
        type=int,
        choices=[1, 2],
        help="CTD sensor to use as reference (1=primary, 2=secondary); overrides YAML setting",
    )
    parser.add_argument("--data-dir", help="Override data directory from config")
    return parser


def run(args):
    """Execute the stats subcommand. Returns exit code."""
    config_file = find_config_file(args.config_path)
    if not config_file:
        print(f"Error: No caldip configuration file found in {args.config_path}")
        return 1

    print(f"Using config file: {config_file}")

    try:
        config = load_config(config_file)
        print(f"Loaded config for: {config.get('name', 'Unknown')}")
    except Exception as e:
        print(f"Error loading config file: {e}")
        return 1

    if args.ctd_sensor is not None:
        config["ctd_sensor"] = args.ctd_sensor
        print(f"CTD sensor overridden to: {args.ctd_sensor}")

    data_dir = resolve_data_dir(config_file, config, args.data_dir)
    print(f"Using data directory: {data_dir}")
    if not data_dir.exists():
        print(f"Error: Data directory does not exist: {data_dir}")
        return 1

    print("=" * 60)

    print("Loading instrument data...")
    try:
        instruments = load_instruments_from_config(config, data_dir)
    except Exception as e:
        print(f"Error loading instrument data: {e}")
        return 1

    print("\nLoading reference data...")
    try:
        reference_data = load_reference_data(config, data_dir)
    except Exception as e:
        print(f"Error loading reference data: {e}")
        return 1

    if not instruments and not reference_data:
        print("Error: No data could be loaded!")
        return 1

    if "deployment_time" in config and "recovery_time" in config:
        print()
        instruments, reference_data = trim_to_deployment(
            instruments, reference_data, config
        )

    print(
        f"\nLoaded: {len(instruments)} instruments, {len(reference_data)} reference datasets"
    )
    print("\nCalculating statistics...")

    try:
        detailed_df = core.stats(
            instruments,
            reference_data,
            config,
            threshold_dbar_per_min=args.threshold,
            min_duration_seconds=args.min_duration,
        )
        summary_df = summary_stats(detailed_df, config)
        print_stats_report(summary_df, config)
    except Exception as e:
        print(f"Error calculating statistics: {e}")
        return 1

    output_path = Path(args.output_dir) if args.output_dir else data_dir.parent
    output_path.mkdir(parents=True, exist_ok=True)
    cast_name = config.get("name") or config_file.stem
    base_name = args.output if args.output else cast_name

    detailed_csv = output_path / f"{base_name}_detailed_statistics.csv"
    summary_csv = output_path / f"{base_name}_summary_statistics.csv"
    timing_txt = output_path / f"{base_name}_timing.txt"

    if not detailed_df.empty:
        float_cols = [
            "ctd_temp",
            "ctd_cond",
            "inst_temp",
            "inst_cond",
            "inst_press",
            "temp_std",
            "cond_std",
            "press_std",
        ]
        out_df = detailed_df.copy()
        for col in float_cols:
            if col in out_df.columns:
                out_df[col] = out_df[col].apply(
                    lambda x: (
                        round(x, 5)
                        if isinstance(x, (int, float)) and not pd.isna(x)
                        else x
                    )
                )
        out_df = out_df.sort_values(
            ["serial", "bl_press"], ascending=[True, False]
        ).reset_index(drop=True)
        try:
            out_df.to_csv(detailed_csv, index=False)
            print(f"\nSaved detailed statistics to {detailed_csv}")
        except OSError as e:
            print(f"\n  ⚠️  Could not write {detailed_csv}: {e}")
            print(
                "     Try adding -o /local/path/ to write output to a local directory."
            )

    csv_df = summary_df.drop("ctd_stats", axis=1, errors="ignore").copy()
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
    for col, decimals in [
        ("temp_diff_mean", 3),
        ("temp_diff_std", 4),
        ("cond_diff_mean", 3),
        ("cond_diff_std", 4),
        ("press_diff_mean", 2),
        ("press_diff_std", 2),
    ]:
        if col in csv_df.columns:
            csv_df[col] = csv_df[col].round(decimals)
    try:
        csv_df.to_csv(summary_csv, index=False)
        print(f"Saved summary statistics to {summary_csv}")
    except OSError as e:
        print(f"  ⚠️  Could not write {summary_csv}: {e}")
        print("     Try adding -o /local/path/ to write output to a local directory.")

    bottle_stops = core.find_bottle_stops(
        list(reference_data.values())[0]["data"],
        threshold_dbar_per_min=args.threshold,
        min_duration_seconds=args.min_duration,
    )
    try:
        with open(timing_txt, "w") as f:
            f.write(f"CALDIP TIMING REPORT - {cast_name}\n")
            f.write("=" * 60 + "\n\n")
            if bottle_stops:
                f.write(f"Found {len(bottle_stops)} bottle stop(s):\n\n")
                for i, stop in enumerate(bottle_stops, 1):
                    f.write(f"Bottle Stop {i}:\n")
                    f.write(f"  Start: {stop['start_time']}\n")
                    f.write(f"  End: {stop['end_time']}\n")
                    f.write(
                        f"  Duration: {stop['duration_seconds'] / 60:.1f} minutes\n"
                    )
                    f.write(f"  Pressure: {stop['pressure']:.1f} dbar\n\n")
            else:
                f.write("No bottle stops detected.\n")
        print(f"Saved timing information to {timing_txt}")
    except OSError as e:
        print(f"  ⚠️  Could not write {timing_txt}: {e}")
        print("     Try adding -o /local/path/ to write output to a local directory.")

    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
