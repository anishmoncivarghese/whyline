"""Command dispatch. Keep imports light — cold start budget is 200 ms."""

from __future__ import annotations

import argparse
import sys

from whyline import __version__

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_UNINITIALISED = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="whyline",
        description="Records why your code exists, and tells the next agent.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_subparsers(dest="command", metavar="<command>")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    return EXIT_OK


def entry() -> None:
    raise SystemExit(main())
