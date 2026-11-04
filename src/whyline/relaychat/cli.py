"""`whyline ask`: question the running relay from the command line.

Exit codes: 0 on an answer, 1 on a failed answer, 2 on a bad setting or usage.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from whyline.relaychat import ask as relay_ask
from whyline.relaychat import history, settings, snapshot

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

_SETTERS = (
    ("set_agent", "agent"),
    ("set_timeout", "timeout_seconds"),
    ("set_snapshot_chars", "snapshot_chars"),
)


def add_parser(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "ask",
        help="Ask a read-only agent about the running relay",
        description="Ask a read-only agent a question about the running relay, "
        "without disturbing it.",
    )
    parser.add_argument("question", nargs="?", default=None, help="The question, as one argument")
    parser.add_argument("--agent", default=None, help="Agent to answer (default: chosen for you)")
    parser.add_argument("--repo", default=None, help="Repository (default: the current one)")
    parser.add_argument("--history", action="store_true", help="Print the conversation")
    parser.add_argument("--run", default=None, help="Relay run id for --history or --clear")
    parser.add_argument("--clear", action="store_true", help="Start a new conversation")
    parser.add_argument("--set-agent", default=None, metavar="X", help="Save the default agent")
    parser.add_argument("--set-timeout", type=int, default=None, metavar="N",
                        help="Save the answer time limit in seconds (0 means none)")
    parser.add_argument("--set-snapshot-chars", type=int, default=None, metavar="N",
                        help="Save how many characters of relay state the agent sees")


def _repo(args: argparse.Namespace) -> Path | None:
    if args.repo:
        return Path(args.repo).expanduser()
    from whyline import paths

    return paths.find_repo_root()


def _run_id(repo: Path, args: argparse.Namespace) -> str | None:
    if args.run:
        return args.run
    return snapshot.build(repo, max_chars=1).run_id


def _save(repo: Path, args: argparse.Namespace) -> int:
    changes = {name: getattr(args, flag) for flag, name in _SETTERS
               if getattr(args, flag) is not None}
    try:
        saved = settings.save(repo, **changes)
    except ValueError as error:
        print(f"whyline ask: {error}", file=sys.stderr)
        return EXIT_USAGE
    for name in changes:
        print(f"{name} = {getattr(saved, name)}")
    return EXIT_OK


def _show_history(repo: Path, args: argparse.Namespace) -> int:
    try:
        items = history.load(repo, _run_id(repo, args))
    except ValueError as error:
        print(f"whyline ask: {error}", file=sys.stderr)
        return EXIT_USAGE
    if not items:
        print("No conversation yet.")
        return EXIT_OK
    for item in items:
        if item.get("role") == "user":
            print(f"Question: {item.get('text', '')}")
        else:
            who = f" ({item['agent']})" if item.get("agent") else ""
            print(f"Answer{who}: {item.get('text', '')}")
    return EXIT_OK


def _clear(repo: Path, args: argparse.Namespace) -> int:
    try:
        moved = history.clear(repo, _run_id(repo, args))
    except ValueError as error:
        print(f"whyline ask: {error}", file=sys.stderr)
        return EXIT_USAGE
    print("Started a new conversation." if moved else "No conversation to clear.")
    return EXIT_OK


def run(args: argparse.Namespace) -> int:
    repo = _repo(args)
    if repo is None:
        print("Not inside a git repository.", file=sys.stderr)
        return EXIT_USAGE
    if any(getattr(args, flag) is not None for flag, _ in _SETTERS):
        return _save(repo, args)
    if args.history:
        return _show_history(repo, args)
    if args.clear:
        return _clear(repo, args)
    if not args.question or not args.question.strip():
        print('usage: whyline ask "<question>" | --history | --clear | '
              "--set-agent X | --set-timeout N | --set-snapshot-chars N", file=sys.stderr)
        return EXIT_USAGE
    answer = relay_ask.ask(repo, args.question, agent=args.agent)
    print(answer.text)
    if answer.agent:
        print(f"Agent: {answer.agent}")
    if answer.shares_quota:
        print("(shares quota with the relay)")
    return EXIT_OK if answer.ok else EXIT_ERROR
