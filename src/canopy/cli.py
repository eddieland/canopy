"""The `canopy` command line."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from importlib.metadata import version


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="canopy",
        description="Unattended, local agent loop driven by your issue tracker.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('canopy')}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments without the program name. Defaults to `sys.argv[1:]`.

    Returns:
        The process exit code.
    """
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
