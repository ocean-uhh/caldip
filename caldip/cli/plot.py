"""caldip plot — interactive Plotly plot of instruments vs CTD reference."""

import sys
import argparse
from pathlib import Path

from caldip.readers import (
    find_config_file,
    load_config,
    load_instruments_from_config,
    load_reference_data,
    resolve_data_dir,
)
from caldip.tools import trim_to_deployment
from caldip._plot import plot

try:
    import plotly.graph_objects as go  # noqa: F401

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False


def build_parser(subparsers=None):
    kwargs = dict(
        help="interactive Plotly plot of instruments vs CTD reference",
        description="Interactive Plotly plot of instruments vs CTD reference",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  caldip plot data/proc_calib/msm142_2026/cal_dip/castM4/
  caldip plot castM4/castM4.caldip.yaml -o outputs/ --output castM4_rev2
  caldip plot castM4/castM4.caldip.yaml --title "castM4: Instruments vs CTD"
        """,
    )
    if subparsers is not None:
        parser = subparsers.add_parser("plot", **kwargs)
    else:
        parser = argparse.ArgumentParser(prog="caldip plot", **kwargs)

    parser.add_argument(
        "config_path",
        help="Path to .caldip.yaml config file or directory containing config",
    )
    parser.add_argument(
        "--output",
        help="Base filename for plot without extension (_plot.html is appended)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        help="Directory to save plot (default: parent of data dir)",
    )
    parser.add_argument(
        "--title",
        "-t",
        help="Plot title (default: auto-generated from config)",
    )
    parser.add_argument(
        "--no-bottle-stops", action="store_true", help="Disable bottle stop markers"
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
        "--show",
        action="store_true",
        help="Show interactive plot in browser (default when no output specified)",
    )
    parser.add_argument("--data-dir", help="Override data directory from config")
    return parser


def run(args):
    """Execute the plot subcommand. Returns exit code."""
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

    if args.title:
        title = args.title
    else:
        cast_name = config.get("name", "Unknown Cast")
        instrument_types = {
            info["config"].get("instrument", "unknown") for info in instruments.values()
        }
        title = f"{cast_name}: {len(instruments)} {'+'.join(sorted(instrument_types))} vs CTD"

    print(f"\nCreating plot: {title}")
    if not PLOTLY_AVAILABLE:
        print("Error: Plotly is required for plotting")
        return 1

    try:
        fig = plot(
            instruments,
            reference_data,
            config=config,
            title=title,
            show_bottle_stops=not args.no_bottle_stops,
            bottle_stop_params={
                "threshold_dbar_per_min": args.threshold,
                "min_duration_seconds": args.min_duration,
            },
        )
        if fig is None:
            print("Error: Failed to create plot")
            return 1
    except Exception as e:
        print(f"Error creating plot: {e}")
        return 1

    if args.output or args.output_dir:
        output_path = Path(args.output_dir) if args.output_dir else data_dir.parent
        output_path.mkdir(parents=True, exist_ok=True)
        base_name = (
            args.output if args.output else (config.get("name") or config_file.stem)
        )
        plot_file = output_path / f"{base_name}_plot.html"
        try:
            fig.write_html(plot_file)
            print(f"Plot saved to: {plot_file}")
        except Exception as e:
            print(f"Error saving plot: {e}")
            return 1

    if args.show or not (args.output or args.output_dir):
        try:
            fig.show()
        except Exception as e:
            print(f"Error displaying plot: {e}")
            return 1

    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
