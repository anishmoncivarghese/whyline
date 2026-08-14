"""Command dispatch. Keep imports light — cold start budget is 200 ms."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from whyline import __version__

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_UNINITIALISED = 3


def _add_explain(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "explain", help="Why does this code exist?"
    )
    parser.add_argument("target", metavar="<file>[:line]")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="whyline",
        description="Records why your code exists, and tells the next agent.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    _add_explain(subparsers)
    return parser


def _split_target(target: str) -> tuple[str, int | None]:
    path, separator, line = target.rpartition(":")
    if separator and line.isdigit():
        return path, int(line)
    return target, None


def _require_repo() -> Path:
    from whyline import paths

    root = paths.find_repo_root()
    if root is None:
        print("Not inside a git repository.", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)
    return root


def cmd_explain(args: argparse.Namespace) -> int:
    from whyline import gitq, paths, render, resolve

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    rel_path, line = _split_target(args.target)
    try:
        result = resolve.explain(root, rel_path, line)
    except gitq.GitUnavailable as error:
        print(f"git is unavailable: {error}", file=sys.stderr)
        return EXIT_ERROR
    if result.skipped_ledger_lines:
        count = result.skipped_ledger_lines
        noun = "line" if count == 1 else "lines"
        print(
            f"warning: skipped {count} unreadable ledger {noun}",
            file=sys.stderr,
        )
    if args.json:
        render.emit_json(render.explanation_json(result))
    else:
        render.emit(render.explanation_text(result))
    return EXIT_OK


COMMANDS = {"explain": cmd_explain}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    return COMMANDS[args.command](args)


def entry() -> None:
    raise SystemExit(main())
