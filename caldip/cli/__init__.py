"""caldip command-line interface.

Entry point: the `caldip` command dispatches to subcommands.

  caldip plot  — interactive Plotly plot of instruments vs CTD
  caldip stats — per-bottle-stop statistics vs CTD
"""

import sys
import argparse

from caldip.cli.plot import build_parser as _build_plot, run as _run_plot
from caldip.cli.stats import build_parser as _build_stats, run as _run_stats
from caldip.cli.init import build_parser as _build_init, run as _run_init


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="caldip",
        description="Calibration dip analysis for oceanographic instruments",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    _build_init(subparsers)
    _build_plot(subparsers)
    _build_stats(subparsers)

    args = parser.parse_args(argv)

    if args.command == "init":
        return _run_init(args)
    if args.command == "plot":
        return _run_plot(args)
    if args.command == "stats":
        return _run_stats(args)


if __name__ == "__main__":
    sys.exit(main())
