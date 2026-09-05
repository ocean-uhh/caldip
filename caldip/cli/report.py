"""caldip report — build a per-cruise HTML calibration report from results."""

import sys
import argparse
from pathlib import Path

from caldip.report import build_report


def build_parser(subparsers=None):
    """Build the argument parser for ``caldip report``.

    Parameters
    ----------
    subparsers : argparse._SubParsersAction or None, optional
        If given, register ``report`` on this subparser group; otherwise build a
        standalone parser.

    Returns
    -------
    argparse.ArgumentParser
        The configured parser.
    """
    kwargs = dict(
        help="build a per-cruise HTML report from caldip stats output",
        description="Build a per-cruise HTML report from caldip stats output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  caldip report data/proc_calib/odb_2026/cal_dip/
  caldip report data/proc_calib/odb_2026/cal_dip/ -o reports/odb_2026
  caldip report outputs/ --cruise msm142_2026
        """,
    )
    if subparsers is not None:
        parser = subparsers.add_parser("report", **kwargs)
    else:
        parser = argparse.ArgumentParser(prog="caldip report", **kwargs)

    parser.add_argument(
        "results_dir",
        help="Directory of caldip stats output (the cruise cal_dip/ folder)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        help="Directory to write the report (default: <results_dir>/report)",
    )
    parser.add_argument(
        "--cruise",
        help="Cruise label for the index heading (default: inferred from path)",
    )
    return parser


def run(args):
    """Execute the report subcommand. Returns exit code."""
    results_dir = Path(args.results_dir)
    if not results_dir.is_dir():
        print(f"Error: Not a directory: {results_dir}")
        return 1

    out_dir = Path(args.output_dir) if args.output_dir else results_dir / "report"

    try:
        index_path = build_report(results_dir, out_dir, cruise_name=args.cruise)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    print(f"Report written to: {index_path}")
    return 0


def main(argv=None):
    """Run ``caldip report`` as a standalone command."""
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
