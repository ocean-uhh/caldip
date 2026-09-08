"""caldip command-line interface.

Entry point: the `caldip` command dispatches to subcommands.

  caldip init       — generate a stub .caldip.yaml for a cast directory
  caldip ctd        — pre-process CTD file (normalize, wild-edit, 1 Hz, save NetCDF, plot)
  caldip instrument — save one instrument to _raw.nc and/or _use.nc
  caldip plot       — interactive Plotly plot of instruments vs CTD
  caldip stats      — per-bottle-stop statistics vs CTD
  caldip report     — per-cruise HTML report from stats output
  caldip inspect    — HTML inventory of a caldip netCDF file
"""

import argparse
import sys

from caldip.cli.ctd import build_parser as _build_ctd
from caldip.cli.ctd import run as _run_ctd
from caldip.cli.init import build_parser as _build_init
from caldip.cli.init import run as _run_init
from caldip.cli.inspect import build_parser as _build_inspect
from caldip.cli.inspect import run as _run_inspect
from caldip.cli.instrument import (
    build_parser as _build_instrument,
)
from caldip.cli.instrument import (
    run as _run_instrument,
)
from caldip.cli.plot import build_parser as _build_plot
from caldip.cli.plot import run as _run_plot
from caldip.cli.report import build_parser as _build_report
from caldip.cli.report import run as _run_report
from caldip.cli.stats import build_parser as _build_stats
from caldip.cli.stats import run as _run_stats


def main(argv: list[str] | None = None) -> int | None:
    """Dispatch the ``caldip`` command to its subcommand.

    Parameters
    ----------
    argv : list of str or None, optional
        Argument vector to parse; when None, ``sys.argv`` is used.

    Returns
    -------
    int or None
        The exit code returned by the dispatched subcommand.
    """
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
    _build_report(subparsers)
    _build_inspect(subparsers)

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
    if args.command == "report":
        return _run_report(args)
    if args.command == "inspect":
        return _run_inspect(args)
    return None


if __name__ == "__main__":
    sys.exit(main())
