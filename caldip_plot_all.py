#!/usr/bin/env python3
"""
Universal caldip plotting script for any instrument type.

This script can handle:
- MicroCAT data (SBE 37) from .cnv and .asc files
- RBR thermistor data from .rsk files
- Any other instrument type supported by seasenselib
- CTD reference data from .cnv files
- Interactive plots for caldip analysis

Usage:
    python caldip_plot_all.py config_file.yaml [options]
    python caldip_plot_all.py data_directory [options]

Based on the reusable API design for instrument-agnostic processing.
"""

import sys
import argparse
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Import universal caldip modules
from caldip.readers import (
    find_config_file,
    load_caldip_config,
    load_instruments_from_config,
    load_reference_data,
)
from caldip.tools import trim_data_to_deployment
from caldip.plotters import create_universal_caldip_plot

# Import plotting libraries for fallback
try:
    import plotly.graph_objects as go

    PLOTLY_AVAILABLE = True
except ImportError:
    print("Warning: Plotly not available")
    PLOTLY_AVAILABLE = False


def main():
    """Main function for command line usage."""
    parser = argparse.ArgumentParser(
        description="Universal caldip plotting for any instrument type",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Plot using config file
  python caldip_plot_all.py castM2/castM2.caldip.yaml --output plot.html
  
  # Plot by pointing to directory (auto-finds config)  
  python caldip_plot_all.py data/proc_calib/msm142_2026/cal_dip/castM2/
  
  # Customize bottle stop detection
  python caldip_plot_all.py config.yaml --threshold 25.0 --min-duration 90
        """,
    )

    parser.add_argument(
        "config_path",
        help="Path to .caldip.yaml config file or directory containing config",
    )
    parser.add_argument("--output", "-o", help="Output file for plot (HTML format)")
    parser.add_argument(
        "--title", "-t", help="Plot title (default: from config or auto-generated)"
    )
    parser.add_argument(
        "--no-bottle-stops", action="store_true", help="Disable bottle stop markers"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=30.0,
        help="Bottle stop detection threshold (dbar/min, default: 30.0)",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=120.0,
        help="Minimum bottle stop duration (seconds, default: 120.0)",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show interactive plot (default if no output specified)",
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
    print("\\nLoading reference data...")
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

    print("\\nLoaded:")
    print(f"  Instruments: {len(instruments)}")
    print(f"  Reference datasets: {len(reference_data)}")

    # Generate plot title
    if args.title:
        title = args.title
    else:
        cast_name = config.get("name", "Unknown Cast")
        n_instruments = len(instruments)

        # Determine instrument types
        instrument_types = set()
        for info in instruments.values():
            inst_type = info["config"].get("instrument", "unknown")
            instrument_types.add(inst_type)

        type_str = "+".join(sorted(instrument_types))
        title = f"{cast_name}: {n_instruments} {type_str} vs CTD"

    # Set up bottle stop parameters
    bottle_stop_params = {
        "threshold_dbar_per_min": args.threshold,
        "min_duration_seconds": args.min_duration,
    }

    # Create plot
    print(f"\\nCreating plot: {title}")
    if not PLOTLY_AVAILABLE:
        print("Error: Plotly is required for universal plotting")
        return 1

    try:
        fig = create_universal_caldip_plot(
            instruments,
            reference_data,
            config=config,
            title=title,
            show_bottle_stops=not args.no_bottle_stops,
            bottle_stop_params=bottle_stop_params,
        )

        if fig is None:
            print("Error: Failed to create plot")
            return 1

    except Exception as e:
        print(f"Error creating plot: {e}")
        return 1

    # Output or show
    if args.output:
        try:
            fig.write_html(args.output)
            print(f"Plot saved to: {args.output}")
        except Exception as e:
            print(f"Error saving plot: {e}")
            return 1

    if args.show or not args.output:
        try:
            fig.show()
        except Exception as e:
            print(f"Error displaying plot: {e}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
