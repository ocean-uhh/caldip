"""caldip inspect — build an HTML inventory of a caldip netCDF file."""

import sys
import argparse
from pathlib import Path

from caldip.report.inventory import write_inventory


def build_parser(subparsers=None):
    """Build the argument parser for ``caldip inspect``.

    Parameters
    ----------
    subparsers : argparse._SubParsersAction or None, optional
        If given, register ``inspect`` on this subparser group; otherwise build a
        standalone parser.

    Returns
    -------
    argparse.ArgumentParser
        The configured parser.
    """
    kwargs = dict(
        help="build an HTML inventory of a caldip netCDF file",
        description="Build a viewable HTML inventory (dims, variables, attributes) "
        "of a caldip netCDF file — a styled counterpart to 'ncdump -h'.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  caldip inspect outputs/castM4_caldip.nc
  caldip inspect outputs/castM4_caldip.nc -o reports/
        """,
    )
    if subparsers is not None:
        parser = subparsers.add_parser("inspect", **kwargs)
    else:
        parser = argparse.ArgumentParser(
            prog="caldip inspect", **{k: v for k, v in kwargs.items() if k != "help"}
        )

    parser.add_argument("nc_path", help="Path to a caldip netCDF file")
    parser.add_argument(
        "--output-dir",
        "-o",
        help="Directory to write the inventory HTML (default: beside the netCDF)",
    )
    return parser


def run(args):
    """Execute the inspect subcommand. Returns exit code."""
    nc_path = Path(args.nc_path)
    if not nc_path.is_file():
        print(f"Error: Not a file: {nc_path}")
        return 1

    out_dir = Path(args.output_dir) if args.output_dir else nc_path.parent
    out_path = out_dir / f"{nc_path.stem}_inventory.html"

    try:
        write_inventory(nc_path, out_path)
    except OSError as e:
        print(f"Error: could not write {out_path}: {e}")
        return 1

    print(f"Inventory written to: {out_path}")
    return 0


def main(argv=None):
    """Run ``caldip inspect`` as a standalone command."""
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
