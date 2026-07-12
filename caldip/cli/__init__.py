"""caldip command-line interface.

Entry point: the `caldip` command dispatches to subcommands.

  caldip init       — generate a stub .caldip.yaml for a cast directory
  caldip ctd        — pre-process CTD file (normalize, wild-edit, 1 Hz, save NetCDF, plot)
  caldip instrument — save one instrument to _raw.nc and/or _use.nc
  caldip plot       — interactive Plotly plot of instruments vs CTD
  caldip stats      — per-bottle-stop statistics vs CTD
"""

import sys
import argparse

from caldip.cli.ctd import build_parser as _build_ctd, run as _run_ctd
from caldip.cli.instrument import (
    build_parser as _build_instrument,
    run as _run_instrument,
)
from caldip.cli.plot import build_parser as _build_plot, run as _run_plot
from caldip.cli.stats import build_parser as _build_stats, run as _run_stats
from caldip.cli.init import build_parser as _build_init, run as _run_init


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="caldip",
        description="Calibration dip analysis for oceanographic instruments",
    )
    subparsers = parser.add_subparsers(
        dest="command", title="commands", metavar="COMMAND"
    )
    subparsers.required = True

    _build_init(subparsers)
    _build_ctd(subparsers)
    _build_instrument(subparsers)
    _build_plot(subparsers)
    _build_stats(subparsers)

    args = parser.parse_args(argv)

    if args.command == "init":
        return _run_init(args)
    if args.command == "ctd":
        return _run_ctd(args)
    if args.command == "instrument":
        return _run_instrument(args)
    if args.command == "plot":
        return _run_plot(args)
    if args.command == "stats":
        return _run_stats(args)


if __name__ == "__main__":
    sys.exit(main())
