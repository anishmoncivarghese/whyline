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


def _add_note(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("note", help="Record a decision")
    parser.add_argument("decision")
    parser.add_argument("--because", default="", help="Why this was chosen")
    parser.add_argument(
        "--rejected",
        action="append",
        default=[],
        metavar='"option: why not"',
        help="An alternative you rejected. Repeatable.",
    )
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        dest="files",
        help="Affected path. Repeatable.",
    )


def _add_brief(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("brief", help="Summary for the next agent")
    parser.add_argument("--limit", type=int, default=10)


def _add_init(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("init", help="Set whyline up in this repository")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Accept instruction-file and hook changes without prompting",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="whyline",
        description="Records why your code exists, and tells the next agent.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    _add_explain(subparsers)
    _add_note(subparsers)
    _add_brief(subparsers)
    _add_init(subparsers)
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


def cmd_note(args: argparse.Namespace) -> int:
    from whyline import decisions, events, ledger, paths

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    event = events.new_event(
        events.NOTE,
        decision=args.decision,
        because=args.because,
        alternatives=events.parse_rejected(args.rejected),
        files=args.files,
    )
    ledger.append(paths.ledger_path(root), event)
    decisions.append_entry(paths.decisions_path(root), event)
    print(f"Recorded: {args.decision}")
    return EXIT_OK


def cmd_brief(args: argparse.Namespace) -> int:
    from whyline import brief, paths

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    print(brief.compose(root, limit=args.limit))
    return EXIT_OK


GITIGNORE_LINES = ("ledger.jsonl", "index.db", "!decisions.md")


def _confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _merge_gitignore(path: Path) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    found = set(existing.splitlines())
    missing = [line for line in GITIGNORE_LINES if line not in found]
    if not missing:
        return
    separator = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(
        existing + separator + "\n".join(missing) + "\n",
        encoding="utf-8",
    )


def cmd_init(args: argparse.Namespace) -> int:
    from whyline import agentsmd, claudemd, hooks, paths

    root = _require_repo()
    directory = paths.whyline_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(root).touch()
    _merge_gitignore(directory / ".gitignore")
    print(f"Initialised {directory}")

    if _confirm(
        "Install shared instructions in AGENTS.md and CLAUDE.md?", args.yes
    ):
        print(f"AGENTS.md: {agentsmd.install(root / 'AGENTS.md')}")
        print(f"CLAUDE.md: {claudemd.install(root / 'CLAUDE.md')}")

    if _confirm("Install the Claude Code hook for this project?", args.yes):
        try:
            outcome = hooks.install(root / ".claude" / "settings.json")
            print(f"Hook: {outcome}")
        except hooks.SettingsUnreadable as error:
            print(str(error), file=sys.stderr)
            return EXIT_ERROR
    return EXIT_OK


COMMANDS = {"explain": cmd_explain, "note": cmd_note, "brief": cmd_brief, "init": cmd_init}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    return COMMANDS[args.command](args)


def entry() -> None:
    raise SystemExit(main())
