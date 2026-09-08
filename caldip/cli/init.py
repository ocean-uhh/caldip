"""caldip init — generate a stub YAML configuration for a cast directory."""

import argparse
import sys

from caldip.scaffold import generate_stub_yaml


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,
) -> argparse.ArgumentParser:
    """Build the argument parser for ``caldip init``.

    Parameters
    ----------
    subparsers : argparse._SubParsersAction or None, optional
        If given, register ``init`` on this subparser group; otherwise build a
        standalone parser.

    Returns
    -------
    argparse.ArgumentParser
        The configured parser.
    """
    kwargs = {
        "help": "generate a stub .caldip.yaml for a cast directory",
        "description": "Generate a stub .caldip.yaml configuration for a cast directory",
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "epilog": """
Examples:
  caldip init data/proc_calib/msm142_2026/cal_dip/castM4/
  caldip init --print-only data/proc_calib/msm142_2026/cal_dip/castM4/
        """,
    }
    if subparsers is not None:
        parser = subparsers.add_parser("init", **kwargs)
    else:
        parser = argparse.ArgumentParser(
            prog="caldip init", **{k: v for k, v in kwargs.items() if k != "help"}
        )

    parser.add_argument(
        "directory",
        help="Path to caldip cast directory containing CTD and instrument files",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print YAML to stdout instead of writing file",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """Execute the init subcommand. Returns exit code.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments with ``directory`` and ``print_only``.

    Returns
    -------
    int
        Process exit code (0 on success, 1 on error).
    """
    try:
        generate_stub_yaml(args.directory, print_only=args.print_only)
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:  # noqa: BLE001  # I/O boundary: stub generation writes a YAML file and reads the cast dir; report any failure as exit 1
        print(f"Error generating stub YAML: {e}")
        return 1


def main(argv: list[str] | None = None) -> int:
    """Run ``caldip init`` as a standalone command.

    Parameters
    ----------
    argv : list of str or None, optional
        Argument vector to parse; when None, ``sys.argv`` is used.

    Returns
    -------
    int
        Process exit code from :func:`run`.
    """
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
