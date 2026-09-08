"""caldip report — build a per-cruise HTML calibration report from results."""

import argparse
import sys
from pathlib import Path

from caldip.report import build_report
from caldip.report.finality import FINAL, check_cruise


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,
) -> argparse.ArgumentParser:
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
    kwargs = {
        "help": "build a per-cruise HTML report from caldip stats output",
        "description": "Build a per-cruise HTML report from caldip stats output",
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": """
Examples:
  caldip report data/proc_calib/odb_2026/cal_dip/
  caldip report data/proc_calib/odb_2026/cal_dip/ -o reports/odb_2026
  caldip report outputs/ --cruise msm142_2026
        """,
    }
    if subparsers is not None:
        parser = subparsers.add_parser("report", **kwargs)
    else:
        parser = argparse.ArgumentParser(
            prog="caldip report", **{k: v for k, v in kwargs.items() if k != "help"}
        )

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
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report each cast's finality (recorded vs current) instead of building "
        "the HTML: one line per cast, exit non-zero if any cast is not 'final'. The "
        "argument may be a caldip.cruise.yaml or a cal_dip directory.",
    )
    parser.add_argument(
        "--nc-dir",
        dest="nc_dir",
        help="Where the {cast}_caldip.nc outputs live, if not beside the configs "
        "(used with --check).",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """Execute the report subcommand. Returns exit code."""
    if args.check:
        return _run_check(args)

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


def _run_check(args: argparse.Namespace) -> int:
    """Run the finality sweep: one line per cast, exit non-zero if any is not final."""
    target = Path(args.results_dir)
    if not target.exists():
        print(f"Error: No such file or directory: {target}")
        return 1
    nc_dir = Path(args.nc_dir) if args.nc_dir else None
    results = check_cruise(target, results_dir=nc_dir)
    if not results:
        print(f"No casts discovered under {target}")
        return 1
    for cast, state, detail in results:
        print(f"{cast:12s} {state:22s} {detail}")
    unfinished = [c for c, state, _ in results if state != FINAL]
    return 1 if unfinished else 0


def main(argv: list[str] | None = None) -> int:
    """Run ``caldip report`` as a standalone command."""
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
