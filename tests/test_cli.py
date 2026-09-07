"""Tests for the caldip CLI subcommand parsers."""

import importlib

import pytest

_CLI_MODULES = ["ctd", "init", "inspect", "instrument", "plot", "report", "stats"]


@pytest.mark.parametrize("name", _CLI_MODULES)
def test_build_parser_standalone(name):
    """build_parser() with no subparsers builds a standalone parser without raising.

    Regression: the shared kwargs dict carries a ``help`` entry valid only for
    ``add_parser``; passing it to a top-level ``ArgumentParser`` raised TypeError.
    """
    module = importlib.import_module(f"caldip.cli.{name}")
    parser = module.build_parser()
    assert parser.prog == f"caldip {name}"
