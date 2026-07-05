"""caldip init — generate a stub YAML configuration for a cast directory."""

import sys
import argparse

from caldip.readers import generate_stub_yaml


def build_parser(subparsers=None):
    kwargs = dict(
        description="Generate a stub .caldip.yaml configuration for a cast directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  caldip init data/proc_calib/msm142_2026/cal_dip/castM4/
  caldip init --print-only data/proc_calib/msm142_2026/cal_dip/castM4/
        """,
    )
    if subparsers is not None:
        parser = subparsers.add_parser("init", **kwargs)
    else:
        parser = argparse.ArgumentParser(prog="caldip init", **kwargs)

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


def run(args):
    """Execute the init subcommand. Returns exit code."""
    try:
        generate_stub_yaml(args.directory, print_only=args.print_only)
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:
        print(f"Error generating stub YAML: {e}")
        return 1


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
