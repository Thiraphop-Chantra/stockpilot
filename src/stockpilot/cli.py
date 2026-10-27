"""Command-line entry point: ``stockpilot <command>``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from stockpilot import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stockpilot",
        description="StockPilot: raw distributor data to replenishment decisions (synthetic data).",
    )
    parser.add_argument("--version", action="version", version=f"stockpilot {__version__}")
    parser.add_subparsers(dest="command", metavar="<command>")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code (argparse exits are turned into return codes)."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help, --version and usage errors
        return exc.code if isinstance(exc.code, int) else 0
    if args.command is None:
        parser.print_help()
        return 0
    return args.handler(args)
