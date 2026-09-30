"""Command dispatch. Keep imports light — cold start budget is 200 ms."""

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path

from whyline import __version__
from whyline import paths
from whyline import runner

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_UNINITIALISED = 3


def _relay_available() -> bool:
    """Whether whyline itself can import whyline-relay -- not whether a
    `whyline-relay` executable is on PATH. The two diverge: a separately
    installed whyline-relay tool lives in its own isolated environment, and
    a whyline install that depends on it doesn't put its executable on PATH
    at all. Checking PATH let the console open with a Chat mode that could
    only fail with "No module named 'whyline_relay'"."""
    import importlib.util

    return importlib.util.find_spec("whyline_relay") is not None


def _exec(binary: str, argv: list[str]) -> None:
    os.execvp(binary, argv)


# Relay subcommands are reached through `whyline relay ...`, never a bare
# `whyline-relay` executable: installed as a whyline dependency, the relay's
# own executable isn't on PATH.
RELAY_SETUP_ARGV = ["whyline", "relay", "setup"]


def run_entry_menu(
    relay_available=None, exec_fn=None, input_fn=None, print_fn=None,
    subprocess_fn=None,
) -> bool:
    """Ask "Chat or relay?" and act on it. Returns False only when
    whyline-relay isn't installed, so main()'s existing fallback-to-usage
    behavior is unchanged for anyone not using the relay side.

    `relay_available`/`exec_fn`/`subprocess_fn` are resolved here, not as default
    arguments -- binding them in the signature would capture the function
    objects at import time, so a test's monkeypatch would silently have no
    effect and this would exec/spawn something real during a test run.
    `runner.py` documents this exact defect happening twice already; the
    same shape is used here on purpose.
    """
    relay_available = relay_available if relay_available is not None else _relay_available
    exec_fn = exec_fn if exec_fn is not None else _exec
    input_fn = input_fn if input_fn is not None else input
    print_fn = print_fn if print_fn is not None else print
    subprocess_fn = subprocess_fn if subprocess_fn is not None else subprocess.run

    if not relay_available():
        return False

    from whyline import account

    freshly_detected = account.ensure_detected()
    if freshly_detected is not None:
        print_fn("First run: checking which agents you have access to...")
        for agent in ("codex", "claude", "antigravity", "grok"):
            info = freshly_detected.get(agent, {})
            state = "available" if info.get("available") else "not available"
            print_fn(f"  {agent}: {state}")

    from whyline.console import editor, repl, tui

    root = paths.find_repo_root()
    if root is not None:
        if tui.TUI_AVAILABLE:
            tui.launch(root)
            return True
        if editor.AVAILABLE:
            repl.run(root)
            return True

    choice = input_fn("Chat or relay? [chat]: ").strip().lower()
    if choice == "relay":
        exec_fn("whyline", RELAY_SETUP_ARGV)
        return True  # unreachable when exec_fn is the real os.execvp

    model_choice = input_fn(
        "Start chatting, or set a model first? [chat]: "
    ).strip().lower()
    if model_choice == "model":
        result = subprocess_fn(["whyline", "model"])
        if getattr(result, "returncode", 0) != 0:
            print_fn(
                "Model setup did not complete -- not starting chat. Fix the "
                "issue above, then run `whyline` again."
            )
            return True

    exec_fn("whyline", ["whyline", "relay", "chat"])
    return True  # unreachable when exec_fn is the real os.execvp


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _token_budget(value: str) -> int:
    parsed = int(value)
    if parsed < 200:
        raise argparse.ArgumentTypeError("must be at least 200")
    return parsed


def _add_explain(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "explain", help="Why does this code exist?"
    )
    parser.add_argument("target", metavar="<file>[:line]", nargs="?", default=None)
    parser.add_argument(
        "--diff", action="store_true",
        help="Explain every line the working tree changes against HEAD",
    )
    parser.add_argument(
        "--staged", action="store_true", help="Explain every line the index changes against HEAD"
    )
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
    parser.add_argument("--actor", default="", help="Agent or person deciding")
    parser.add_argument("--role", default="", help="Role for this decision")
    parser.add_argument("--task", default="", help="Task identifier")
    parser.add_argument(
        "--commit",
        default=None,
        metavar="SHA",
        help="Bind this decision to the commit it explains (e.g. HEAD after "
        "committing). Never assumed: without it the decision is unbound.",
    )
    parser.add_argument(
        "--supersedes",
        action="append",
        default=[],
        metavar="ID",
        help="A decision this one replaces (id or unique prefix). Repeatable.",
    )
    parser.add_argument("--verdict", default="", help="Review verdict, e.g. approved")
    parser.add_argument(
        "--reviewed-commit", default=None, metavar="SHA", help="The commit that was reviewed"
    )
    parser.add_argument(
        "--test",
        action="append",
        default=[],
        dest="tests",
        metavar='"COMMAND: RESULT"',
        help="A check that was run and its result. Repeatable.",
    )


def _add_retract(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "retract", help="Withdraw a decision that turned out wrong (no replacement)"
    )
    parser.add_argument("decision_id", help="Decision id, or a unique prefix of it")
    parser.add_argument("--because", default=None, help="Why it was wrong (required)")
    parser.add_argument("--actor", default="")
    parser.add_argument("--role", default="")
    parser.add_argument("--task", default="")


def _add_ledger(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "ledger", help="Inspect, prune or change what the local ledger keeps"
    )
    sub = parser.add_subparsers(dest="ledger_command", required=True)
    policy = sub.add_parser(
        "policy",
        help="Show or set prompt capture: metadata (default), redacted or full",
    )
    policy.add_argument("value", nargs="?", choices=("metadata", "redacted", "full"))
    prune = sub.add_parser(
        "prune", help="Remove old prompt, file-touch and session events"
    )
    prune.add_argument("--older-than", type=_positive_float, required=True, metavar="DAYS")
    prune.add_argument("--dry-run", action="store_true")
    scrub = sub.add_parser(
        "scrub-prompts", help="Apply the current capture policy to recorded prompts"
    )
    scrub.add_argument("--dry-run", action="store_true")
    stats = sub.add_parser("stats", help="What the ledger holds")
    stats.add_argument("--json", action="store_true")


def _add_doctor(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "doctor", help="Check everything whyline depends on here, with fixes"
    )
    parser.add_argument("--json", action="store_true")


def _add_decisions(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "decisions", help="List, search or show recorded decisions"
    )
    sub = parser.add_subparsers(dest="decisions_command")
    listing = sub.add_parser("list", help="Current decisions, newest first (default)")
    listing.add_argument("--task", default=None)
    listing.add_argument("--file", default=None)
    for command in (listing, sub.add_parser("search", help="Find decisions by text")):
        if command is not listing:
            command.add_argument("text")
        command.add_argument(
            "--all", action="store_true", dest="all_decisions",
            help="Include superseded and retracted decisions",
        )
        command.add_argument("--limit", type=_positive_int, default=None)
        command.add_argument("--json", action="store_true")
    show = sub.add_parser("show", help="One decision in full")
    show.add_argument("decision_id")
    show.add_argument("--json", action="store_true")


def _add_attach(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "attach",
        help="Bind an earlier decision to the commit that implemented it",
    )
    parser.add_argument("decision_id", help="Decision id, or a unique prefix of it")
    parser.add_argument("--commit", required=True, metavar="SHA")


def _add_handoff(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "handoff",
        help="Record an active-task handoff (or `handoff close` to close it)",
        description="Record an active-task handoff. `whyline handoff close "
        "[--status completed|cancelled] [--summary ...]` closes the active one.",
    )
    parser.add_argument("task", help="Task identifier, or `close`")
    # Required for an ordinary handoff; checked in cmd_handoff, since
    # `handoff close` takes neither.
    parser.add_argument("--from", default=None, dest="from_actor", metavar="ACTOR")
    parser.add_argument("--to", default=None, dest="to_actor", metavar="ACTOR")
    parser.add_argument("--status", default=None)
    parser.add_argument("--summary", default="")
    parser.add_argument("--file", action="append", default=[], dest="files")
    parser.add_argument("--test", action="append", default=[], dest="tests")
    parser.add_argument("--risk", action="append", default=[], dest="risks")
    parser.add_argument("--question", action="append", default=[], dest="questions")
    parser.add_argument("--base", default=None, dest="base_commit")
    parser.add_argument("--current", default=None, dest="current_commit")
    parser.add_argument("--json", action="store_true")


def _add_claim(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("claim", help="Claim advisory task/file ownership")
    parser.add_argument("task")
    parser.add_argument("--actor", required=True)
    parser.add_argument("--role", default="")
    parser.add_argument("--file", action="append", default=[], dest="files")
    parser.add_argument(
        "--ttl",
        type=_positive_float,
        default=None,
        metavar="HOURS",
        help="Lease length; the claim stops counting after this (default 72). "
        "Claiming again renews it.",
    )
    parser.add_argument("--json", action="store_true")


def _add_release(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "release",
        help="Release advisory ownership",
        description="Release claims: TASK --actor A (one claim), TASK (every "
        "actor's claim on TASK), --stale (expired claims) or --all.",
    )
    parser.add_argument("task", nargs="?", default=None)
    parser.add_argument("--actor", default=None)
    parser.add_argument("--stale", action="store_true", help="Release expired claims")
    parser.add_argument("--all", action="store_true", dest="all_claims", help="Release every claim")
    parser.add_argument("--json", action="store_true")


def _add_brief(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("brief", help="Summary for the next agent")
    parser.add_argument("--limit", type=_positive_int, default=10)
    parser.add_argument("--task", default=None)
    parser.add_argument("--file", action="append", default=[], dest="files")
    parser.add_argument("--token-budget", type=_token_budget, default=1200)


def _add_sync(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("sync", help="Compact active-task handoff")
    parser.add_argument("--task", default=None)
    parser.add_argument("--file", action="append", default=[], dest="files")
    parser.add_argument("--token-budget", type=_token_budget, default=1200)
    parser.add_argument("--json", action="store_true")


def _add_run(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "run", help="Launch an agent with active context attached"
    )
    parser.add_argument("agent", choices=tuple(runner.AGENTS))
    parser.add_argument("task")
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--file", action="append", default=[], dest="files")
    parser.add_argument("--token-budget", type=_token_budget, default=1200)


def _add_relay(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "relay",
        help=(
            "Run a plan through Codex and Claude unattended "
            "(needs the whyline-relay package)."
        ),
        add_help=False,
        # Treat every possible command-line token as positional. Without this,
        # argparse rejects an option such as --help before REMAINDER sees it.
        prefix_chars="\0",
    )
    parser.add_argument("args", nargs=argparse.REMAINDER)


def _add_timeline(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("timeline", help="Project event history")
    parser.add_argument("--file", dest="file", default=None)
    parser.add_argument("--since", default=None, metavar="YYYY-MM-DD")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--include-prompts",
        action="store_true",
        help="Include raw prompt text from Instruction events in --json output",
    )


def _add_status(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("status", help="Is whyline healthy here?")
    parser.add_argument("--json", action="store_true")


def _add_init(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("init", help="Set whyline up in this repository")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Accept instruction-file and hook changes without prompting",
    )
    parser.add_argument(
        "--no-instructions",
        action="store_true",
        help="Skip the AGENTS.md and CLAUDE.md instruction block",
    )
    parser.add_argument(
        "--no-hooks",
        action="store_true",
        help="Skip the Claude Code and Codex hook configuration",
    )
    relay = parser.add_mutually_exclusive_group()
    relay.add_argument(
        "--relay",
        action="store_true",
        help="Also set up the automated relay.",
    )
    relay.add_argument(
        "--no-relay",
        action="store_true",
        help="Do not offer the automated relay.",
    )


def _add_account(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "account", help="Detect which plan/tier codex and claude are authenticated under"
    )
    account_sub = parser.add_subparsers(dest="account_command", required=True)
    account_sub.add_parser("status", help="Show the detected/confirmed account")
    account_sub.add_parser("detect", help="Re-run detection and refresh the global cache")
    enable_parser = account_sub.add_parser(
        "enable", help="Manually mark an agent as available"
    )
    enable_parser.add_argument("agent", choices=tuple(runner.AGENTS))
    disable_parser = account_sub.add_parser(
        "disable", help="Manually mark an agent as unavailable"
    )
    disable_parser.add_argument("agent", choices=tuple(runner.AGENTS))



def _add_model(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "model", help="Choose which model each agent uses in this repo"
    )
    model_sub = parser.add_subparsers(dest="model_command")
    set_parser = model_sub.add_parser("set", help="Set one agent's model non-interactively")
    set_parser.add_argument("agent", choices=tuple(runner.AGENTS))
    set_parser.add_argument("model")
    model_sub.add_parser("status", help="Show current selections")


def _add_console(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "console", help="An editable multiline console for whyline and whyline-relay"
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Launch the full-screen, mouse-enabled console instead of the keyboard-only one",
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
    _add_attach(subparsers)
    _add_retract(subparsers)
    _add_decisions(subparsers)
    _add_ledger(subparsers)
    _add_doctor(subparsers)
    _add_handoff(subparsers)
    _add_claim(subparsers)
    _add_release(subparsers)
    _add_brief(subparsers)
    _add_sync(subparsers)
    _add_run(subparsers)
    _add_relay(subparsers)
    _add_timeline(subparsers)
    _add_status(subparsers)
    _add_init(subparsers)
    _add_account(subparsers)
    _add_model(subparsers)
    _add_console(subparsers)
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
    if args.diff or args.staged:
        if args.target is not None or (args.diff and args.staged):
            print("explain takes a <file>[:line], --diff or --staged -- one of them.", file=sys.stderr)
            return EXIT_USAGE
        from whyline import diffexplain

        try:
            report = diffexplain.explain_diff(root, staged=args.staged)
        except gitq.GitUnavailable as error:
            print(f"git is unavailable: {error}", file=sys.stderr)
            return EXIT_ERROR
        if args.json:
            render.emit_json(report)
        else:
            render.emit(diffexplain.text(report))
        return EXIT_OK
    if args.target is None:
        print("explain needs a <file>[:line], or --diff / --staged.", file=sys.stderr)
        return EXIT_USAGE
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
    # C5, 2026-08-17: normalise at the boundary so the ledger and decisions.md
    # hold the same value. Sanitising only at render time would leave the two
    # stores silently disagreeing about what was recorded.
    bound = {}
    if args.commit is not None:
        from whyline import gitq

        sha = gitq.resolve_commit(root, args.commit)
        if sha is None:
            print(f"{args.commit} is not a commit in this repository. Nothing was recorded.", file=sys.stderr)
            return EXIT_ERROR
        bound = {"commit": sha}
    if args.supersedes:
        from whyline import history

        loaded = history.load(root, mechanical=False)
        replaced = []
        for prefix in args.supersedes:
            found, problem = _one_decision(loaded, prefix)
            if problem:
                print(problem + " Nothing was recorded.", file=sys.stderr)
                return EXIT_ERROR
            replaced.append(found)
        bound["supersedes"] = sorted(set(replaced), key=replaced.index)
    if args.reviewed_commit is not None:
        from whyline import gitq

        reviewed = gitq.resolve_commit(root, args.reviewed_commit)
        if reviewed is None:
            print(
                f"{args.reviewed_commit} is not a commit in this repository. Nothing was recorded.",
                file=sys.stderr,
            )
            return EXIT_ERROR
        bound["reviewed_commit"] = reviewed
    if args.verdict:
        bound["verdict"] = decisions.one_line(args.verdict)
    if args.tests:
        from whyline import handoff

        bound["tests"] = [handoff.parse_test(value) for value in args.tests]
    alternatives = [
        {
            "option": decisions.one_line(alt["option"]),
            "why_not": decisions.one_line(alt["why_not"]),
        }
        for alt in events.parse_rejected(args.rejected)
    ]
    event = events.new_event(
        events.NOTE,
        decision=decisions.one_line(args.decision),
        because=decisions.one_line(args.because),
        alternatives=alternatives,
        files=[decisions.one_line(f) for f in args.files],
        actor=decisions.one_line(args.actor),
        role=decisions.one_line(args.role),
        task=decisions.one_line(args.task),
        **bound,
    )
    # decisions.md FIRST, then the ledger. Order matters at the failure
    # boundary, found 2026-08-18: with the ledger written first, a failure on
    # decisions.md left the note in the local ledger only — `brief` and `status`
    # both reported it, but decisions.md is what is committed, so a clone would
    # never see it and the two stores diverged silently. Writing the durable,
    # committed artefact first makes the surviving failure direction the safe
    # one, since `brief` falls back to parsing decisions.md.
    try:
        decisions.append_entry(paths.decisions_path(root), event)
    except OSError as error:
        print(
            f"could not write {paths.decisions_path(root)}: {error.strerror}.\n"
            "Nothing was recorded.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    try:
        ledger.append(paths.ledger_path(root), event)
    except OSError as error:
        # decisions.md already holds it, which is the artefact that travels.
        print(
            f"warning: recorded in {paths.decisions_path(root)} but could not "
            f"write the local ledger: {error.strerror}",
            file=sys.stderr,
        )
    # Echo what was stored, not what was typed — they differ when a multi-line
    # value is normalised, and printing the raw form would misreport the record.
    print(f"Recorded: {event['decision']}")
    return EXIT_OK


def _one_decision(loaded, prefix: str) -> tuple[str, str]:
    """(full id, "") for a unique match, else ("", the problem)."""
    from whyline import history

    matches = history.find(loaded, prefix)
    if not matches:
        return "", f"No decision with id {prefix.strip() or '(empty)'}."
    if len(matches) > 1:
        return "", f"{prefix.strip()} matches {len(matches)} decisions; use more of the id."
    return matches[0], ""


def cmd_retract(args: argparse.Namespace) -> int:
    from whyline import decisions, events, history, ledger, paths

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    if not (args.because or "").strip():
        print("whyline retract: --because is required: say why it was wrong.", file=sys.stderr)
        return EXIT_USAGE
    loaded = history.load(root, mechanical=False)
    target, problem = _one_decision(loaded, args.decision_id)
    if problem:
        print(problem, file=sys.stderr)
        return EXIT_ERROR
    original = next(e.event for e in loaded.notes if e.event.get("id") == target)
    event = events.new_event(
        events.RETRACTION,
        retracts=target,
        # Written as a visible decisions.md entry so a person reading the
        # file sees the withdrawal, not just a changed status elsewhere.
        decision=f"Retracted: {decisions.one_line(original.get('decision', ''))}",
        because=decisions.one_line(args.because),
        alternatives=[],
        files=list(original.get("files") or []),
        actor=decisions.one_line(args.actor),
        role=decisions.one_line(args.role),
        task=decisions.one_line(args.task),
    )
    try:
        decisions.append_entry(paths.decisions_path(root), event)
    except OSError as error:
        print(f"could not write {paths.decisions_path(root)}: {error.strerror}", file=sys.stderr)
        return EXIT_ERROR
    try:
        ledger.append(paths.ledger_path(root), event)
    except OSError:
        pass  # decisions.md already carries it
    print(f"Retracted {target[:8]}: {original.get('decision', '')}")
    return EXIT_OK


def _decision_line(event: dict) -> str:
    status = event.get("lifecycle", "active")
    task = f"  (task {event['task']})" if event.get("task") else ""
    return (
        f"{str(event.get('id', ''))[:8]}  {str(event.get('ts', ''))[:10]}  "
        + (f"[{status}] " if status != "active" else "")
        + f"{event.get('decision', '')}{task}"
    )


def _decision_detail(event: dict) -> str:
    rows = [("Decision", event.get("decision", "")), ("Id", event.get("id", "")),
            ("Recorded", event.get("ts", ""))]
    status = event.get("lifecycle", "active")
    if status == "superseded":
        rows.append(("Status", f"superseded by {str(event.get('superseded_by', ''))[:8]}"))
    elif status == "retracted":
        rows.append(("Status", f"retracted: {event.get('retracted_because', '')}"))
    else:
        rows.append(("Status", "active"))
    if event.get("because"):
        rows.append(("Because", event["because"]))
    for alternative in event.get("alternatives") or []:
        why_not = alternative.get("why_not", "")
        rows.append(("Rejected", alternative.get("option", "") + (f" -- {why_not}" if why_not else "")))
    for label, key in (("Task", "task"), ("Actor", "actor"), ("Role", "role")):
        if event.get(key):
            rows.append((label, event[key]))
    if event.get("files"):
        rows.append(("Files", ", ".join(event["files"])))
    if event.get("commit"):
        rows.append(("Commit", event["commit"]))
    if event.get("supersedes"):
        rows.append(("Supersedes", ", ".join(str(v)[:8] for v in event["supersedes"])))
    if event.get("verdict"):
        rows.append(("Verdict", event["verdict"]))
    if event.get("reviewed_commit"):
        rows.append(("Reviewed", event["reviewed_commit"]))
    for test in event.get("tests") or []:
        rows.append(("Test", f"{test.get('command', '')}: {test.get('result', '')}"))
    return "\n".join(f"{label:<11}{value}" for label, value in rows)


def _searchable(event: dict) -> str:
    parts = [event.get("decision", ""), event.get("because", ""), event.get("task", "")]
    parts += [a.get("option", "") + " " + a.get("why_not", "") for a in event.get("alternatives") or []]
    parts += list(event.get("files") or [])
    return " ".join(str(p) for p in parts).lower()


def cmd_decisions(args: argparse.Namespace) -> int:
    from whyline import history, paths, render

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    loaded = history.load(root, mechanical=False)
    command = args.decisions_command or "list"
    if command == "show":
        found, problem = _one_decision(loaded, args.decision_id)
        if problem:
            print(problem, file=sys.stderr)
            return EXIT_ERROR
        event = next(e.event for e in loaded.notes if e.event.get("id") == found)
        if args.json:
            render.emit_json(event)
        else:
            print(_decision_detail(event))
        return EXIT_OK
    include_all = getattr(args, "all_decisions", False)
    selected = [e.event for e in (loaded.notes if include_all else loaded.active)]
    if command == "search":
        needle = args.text.lower()
        selected = [event for event in selected if needle in _searchable(event)]
    else:
        if getattr(args, "task", None):
            selected = [event for event in selected if event.get("task") == args.task]
        if getattr(args, "file", None):
            from whyline import gitq

            names = set(gitq.historical_paths(root, args.file))
            selected = [
                event for event in selected if names.intersection(event.get("files") or [])
            ]
    limit = getattr(args, "limit", None)
    if limit:
        selected = selected[:limit]
    if getattr(args, "json", False):
        render.emit_json(selected)
        return EXIT_OK
    if not selected:
        print("No matching decisions." + ("" if include_all else " (--all includes superseded and retracted ones)"))
        return EXIT_OK
    for event in selected:
        print(_decision_line(event))
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    from whyline import doctor, render

    root = _require_repo()
    checks = doctor.run(root)
    if args.json:
        render.emit_json({"checks": checks})
    else:
        print(doctor.text(checks))
    return EXIT_ERROR if any(c["status"] == doctor.FAIL for c in checks) else EXIT_OK


def cmd_ledger(args: argparse.Namespace) -> int:
    from whyline import ledgerops, paths, render

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    command = args.ledger_command
    try:
        if command == "policy":
            if args.value:
                ledgerops.set_policy(root, args.value)
                print(f"Prompt capture is now {args.value}.")
                if args.value != "full":
                    print("Prompts already recorded keep their text until: whyline ledger scrub-prompts")
            else:
                print(f"Prompt capture: {ledgerops.policy(root)}")
            return EXIT_OK
        if command == "prune":
            count = ledgerops.prune(root, older_than_days=args.older_than, dry_run=args.dry_run)
            verb = "Would remove" if args.dry_run else "Removed"
            print(f"{verb} {count} event{'s' if count != 1 else ''} older than {args.older_than:g} days "
                  "(decisions, handoffs, attachments and retractions are always kept).")
            return EXIT_OK
        if command == "scrub-prompts":
            count = ledgerops.scrub(root, dry_run=args.dry_run)
            verb = "Would scrub" if args.dry_run else "Scrubbed"
            print(f"{verb} {count} prompt{'s' if count != 1 else ''} to {ledgerops.policy(root)}.")
            return EXIT_OK
        report = ledgerops.stats(root)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    except OSError as error:
        print(f"could not update the ledger: {error}", file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        render.emit_json(report)
        return EXIT_OK
    print(f"{'Ledger':<14}{report['path']} ({report['bytes'] / 1e6:.1f} MB)")
    print(f"{'Events':<14}{report['events']}")
    for kind, count in report["types"].items():
        print(f"  {kind:<18}{count} event{'s' if count != 1 else ''}")
    print(f"{'Prompt text':<14}{report['prompt_text_bytes'] / 1e6:.2f} MB")
    print(f"{'Policy':<14}{report['policy']}")
    return EXIT_OK


def cmd_attach(args: argparse.Namespace) -> int:
    from whyline import decisions, events, gitq, history, ledger, paths

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    prefix = args.decision_id.strip()
    found, problem = _one_decision(history.load(root, mechanical=False), prefix)
    if problem:
        print(problem, file=sys.stderr)
        return EXIT_ERROR
    matches = [found]
    sha = gitq.resolve_commit(root, args.commit)
    if sha is None:
        print(f"{args.commit} is not a commit in this repository.", file=sys.stderr)
        return EXIT_ERROR
    event = events.new_event(events.NOTE_ATTACHED, note=matches[0], commit=sha)
    # Same order as `note`: the committed record first, so a failure never
    # leaves the binding only in the gitignored ledger.
    try:
        decisions.append_attachment(
            paths.decisions_path(root), note=matches[0], commit=sha, ts=event["ts"]
        )
    except OSError as error:
        print(f"could not write {paths.decisions_path(root)}: {error.strerror}", file=sys.stderr)
        return EXIT_ERROR
    try:
        ledger.append(paths.ledger_path(root), event)
    except OSError:
        pass  # decisions.md already carries it
    print(f"Attached {prefix} to {sha[:7]}.")
    return EXIT_OK


def cmd_handoff(args: argparse.Namespace) -> int:
    from whyline import gitq, handoff, paths, render

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    if args.task == "close" and args.from_actor is None and args.to_actor is None:
        return _close_handoff(root, args)
    missing = [
        flag
        for flag, value in (
            ("--from", args.from_actor),
            ("--to", args.to_actor),
            ("--status", args.status),
        )
        if value is None
    ]
    if missing:
        print(
            "whyline handoff: the following arguments are required: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        record = handoff.create(
            root,
            task=args.task,
            from_actor=args.from_actor,
            to_actor=args.to_actor,
            status=args.status,
            summary=args.summary,
            files=args.files or None,
            tests=[handoff.parse_test(value) for value in args.tests],
            risks=args.risks,
            questions=args.questions,
            base_commit=args.base_commit,
            current_commit=args.current_commit,
        )
    except (gitq.GitUnavailable, OSError) as error:
        print(f"could not record handoff: {error}", file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        render.emit_json(record)
    else:
        render.emit(handoff.format_text(record))
    return EXIT_OK


def _close_handoff(root: Path, args: argparse.Namespace) -> int:
    from whyline import handoff, render

    status = args.status or "completed"
    try:
        closed = handoff.close(root, status=status, summary=args.summary)
    except OSError as error:
        print(f"could not close handoff: {error}", file=sys.stderr)
        return EXIT_ERROR
    if closed is None:
        print("No open handoff to close.", file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        render.emit_json(closed)
    else:
        print(f"Closed handoff {closed.get('task', '')} ({closed['closed_status']}).")
    return EXIT_OK


def cmd_claim(args: argparse.Namespace) -> int:
    from whyline import ownership, paths, render

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    try:
        state, found_conflicts = ownership.claim(
            root,
            task=args.task,
            actor=args.actor,
            role=args.role,
            files=args.files,
            **({"ttl_hours": args.ttl} if args.ttl is not None else {}),
        )
    except OSError as error:
        print(f"could not record ownership: {error}", file=sys.stderr)
        return EXIT_ERROR
    payload = {**state, "conflicts": found_conflicts}
    if args.json:
        render.emit_json(payload)
    else:
        print(f"Claimed {args.task} for {args.actor}.")
        if found_conflicts:
            print(
                f"WARNING: {len(found_conflicts)} overlapping claim"
                + ("s" if len(found_conflicts) != 1 else "")
                + "; coordinate before writing."
            )
    return EXIT_OK


def cmd_release(args: argparse.Namespace) -> int:
    from whyline import ownership, paths, render

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    if args.task is None and not (args.stale or args.all_claims):
        print(
            "whyline release: say what to release: TASK, --stale or --all",
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        state, released = ownership.release_matching(
            root,
            task=args.task,
            actor=args.actor,
            stale=args.stale,
            everything=args.all_claims,
        )
    except OSError as error:
        print(f"could not release ownership: {error}", file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        render.emit_json({**state, "released": released})
    else:
        print(f"Released {released} claim{'s' if released != 1 else ''}.")
    return EXIT_OK


def cmd_brief(args: argparse.Namespace) -> int:
    from whyline import brief, paths

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    print(
        brief.compose(
            root,
            limit=args.limit,
            task=args.task,
            files=args.files,
            token_budget=args.token_budget,
        )
    )
    return EXIT_OK


def cmd_sync(args: argparse.Namespace) -> int:
    from whyline import gitq, paths, render, sync

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    try:
        if args.json:
            render.emit_json(sync.payload(root, task=args.task, files=args.files))
        else:
            render.emit(
                sync.compose(
                    root,
                    task=args.task,
                    files=args.files,
                    token_budget=args.token_budget,
                )
            )
    except gitq.GitUnavailable as error:
        print(f"git is unavailable: {error}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


# `*.bak` covers the copy `agentsmd.install` leaves when it replaces an outdated
# instruction block. It lives here rather than in the repository's own .gitignore
# because whyline only ever manages this file — the human owns the other one.
GITIGNORE_LINES = (
    "ledger.jsonl",
    "index.db",
    "active-handoff.json",
    "ownership.json",
    "readside.log",
    "*.lock",
    "*.bak",
    "account.json",
    "model.json",
    "config.json",
    "!decisions.md",
)


def _confirm(question: str, assume_yes: bool) -> bool:
    """Ask, defaulting to yes. Running the command is the consent.

    This defaulted to no until 0.2.1, which made the likeliest first run produce
    a dead install: `whyline init` then Enter twice left `.whyline/` and nothing
    else — no instruction block, so no agent ever recorded or read anything, and
    no hooks, so nothing mechanical was captured either. It printed "Initialised"
    and exited 0, and `status` then advised running the command just run. The
    tool did nothing and looked like it had worked.

    A closed stdin means the same thing rather than the opposite. `EOFError` here
    is a Makefile, devcontainer or CI step, where declining silently and exiting
    0 hands back a broken setup in the one context with nobody watching a prompt.

    Declining is still possible, by answering `n` or passing the explicit skip
    flags — it is just no longer what happens by accident. The safety net for the
    files this touches is the backup `agentsmd.install` writes, not a default
    that quietly produces an inert install.
    """
    if assume_yes:
        return True
    try:
        answer = input(f"{question} [Y/n] ").strip().lower()
    except EOFError:
        return True
    return answer not in ("n", "no")


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


def _confirm_relay() -> bool:
    """Offer the optional relay, defaulting to no even without a terminal."""
    try:
        answer = input(
            "Also set up the automated relay (Codex implements, Claude reviews "
            "and commits, unattended)? [y/N] "
        ).strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def _setup_relay(root: Path, args: argparse.Namespace) -> int:
    config = root / ".whyline" / "relay" / "config.toml"
    if config.exists():
        print("The automated relay is already set up.")
        return EXIT_OK

    explicitly_requested = args.relay
    if args.no_relay or (args.yes and not explicitly_requested):
        return EXIT_OK
    if not explicitly_requested and not _confirm_relay():
        return EXIT_OK

    try:
        from whyline_relay import cli as relay_cli
    except ModuleNotFoundError as error:
        if error.name != "whyline_relay":
            raise
        print(relay_install_hint(), file=sys.stderr)
        return EXIT_ERROR if explicitly_requested else EXIT_OK

    relay_args = ["init", "--repo", str(root)]
    if args.yes:
        relay_args.append("--yes")
    result = relay_cli.main(relay_args, prog="whyline relay")
    if result != EXIT_OK:
        return result
    print(
        "Next: write a plan (whyline relay plan-format shows the format), "
        "commit, then run: whyline relay start"
    )
    return EXIT_OK


def cmd_init(args: argparse.Namespace) -> int:
    from whyline import agentsmd, claudemd, hooks, paths

    root = _require_repo()
    directory = paths.whyline_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(root).touch()
    _merge_gitignore(directory / ".gitignore")
    print(f"Initialised {directory}")

    if not args.no_instructions and _confirm(
        "Install shared instructions in AGENTS.md and CLAUDE.md?", args.yes
    ):
        print(f"AGENTS.md: {agentsmd.install(root / 'AGENTS.md')}")
        print(f"CLAUDE.md: {claudemd.install(root / 'CLAUDE.md')}")

    if not args.no_hooks and _confirm(
        "Install the Claude Code and Codex hooks for this project?", args.yes
    ):
        try:
            claude_outcome = hooks.install_claude(
                root / ".claude" / "settings.json"
            )
            codex_outcome = hooks.install_codex(root / ".codex" / "hooks.json")
            print(f"Claude hook: {claude_outcome}")
            print(f"Codex hook: {codex_outcome}")
            print("Codex trust: open /hooks in Codex and approve this project hook.")
            if hooks.antigravity_in_use(root):
                print(f"Antigravity hook: {hooks.install_antigravity(root)}")
                print(
                    "Antigravity trust: trust this folder in Antigravity (agy) so it "
                    "loads workspace hooks; whyline does not change that setting."
                )
        except hooks.SettingsUnreadable as error:
            print(str(error), file=sys.stderr)
            return EXIT_ERROR
    return _setup_relay(root, args)


def _print_account(data: dict) -> None:
    for agent in ("codex", "claude", "antigravity", "grok"):
        info = data.get(agent) if isinstance(data.get(agent), dict) else {}
        plan = info.get("plan")
        available = info.get("available", False)
        if plan is None and agent in ("codex", "claude"):
            base = "no subscription tier (using an API key)"
        elif plan == "unknown":
            base = f"unknown ({info.get('reason', 'no reason given')})"
        elif plan:
            base = plan
        else:
            base = "installed" if available else "not installed"
        status = "available" if available else "not available"
        note = " (manually set)" if info.get("manual") else ""
        print(f"{agent}: {base} -- {status}{note}")


def cmd_account(args: argparse.Namespace) -> int:
    from whyline import account

    if args.account_command == "detect":
        detected = account.refresh()
        _print_account(detected)
        return EXIT_OK
    if args.account_command == "enable":
        account.set_manual(args.agent, True)
        print(f"{args.agent}: manually marked available.")
        return EXIT_OK
    if args.account_command == "disable":
        account.set_manual(args.agent, False)
        print(f"{args.agent}: manually marked unavailable.")
        return EXIT_OK

    root = _require_repo()
    repo_data = account.load_repo(root)
    if repo_data is not None:
        _print_account(repo_data)
        return EXIT_OK
    global_data = account.load_global()
    if global_data is None:
        print("No detection yet. Run: whyline account detect", file=sys.stderr)
        return EXIT_ERROR
    _print_account(global_data)
    try:
        answer = input("Use this for this repo? [Y/n] ").strip().lower()
    except EOFError:
        answer = "y"
    confirmed = answer not in ("n", "no")
    to_save = dict(global_data)
    to_save["confirmed"] = confirmed
    account.save_repo(root, to_save)
    return EXIT_OK


def cmd_model(args: argparse.Namespace) -> int:
    from whyline import account, model

    root = _require_repo()
    if args.model_command == "set":
        model.set_one(root, args.agent, args.model)
        return EXIT_OK
    if args.model_command == "status":
        current = model.load(root)
        if not current:
            print("Nothing set.")
        else:
            for agent, chosen in current.items():
                print(f"{agent}: {chosen}")
        return EXIT_OK

    account.ensure_detected()
    available = account.available_agents(root)
    if not available:
        print(
            "No agents detected as available. Run: whyline account detect "
            "(or whyline account enable <agent> to add one manually).",
            file=sys.stderr,
        )
        return EXIT_ERROR

    repo_account = account.load_repo(root)
    for agent in ("codex", "claude", "antigravity", "grok"):
        if agent not in available:
            continue
        if repo_account is not None and agent in repo_account:
            plan = repo_account[agent].get("plan")
            if plan:
                print(f"{agent} -- {plan}")
        if agent == "antigravity":
            print(
                "Note: Antigravity is safe here for `whyline run`, but not "
                "currently safe for any unattended whyline-relay role -- see README."
            )
        current_value = model.load(root).get(agent, "(default)")
        print(f"Current: {current_value}")
        try:
            answer = input(f"Model for {agent} (blank to keep default): ").strip()
        except EOFError:
            answer = ""
        if answer:
            model.set_one(root, agent, answer)
    return EXIT_OK


def cmd_console(args: argparse.Namespace) -> int:
    root = _require_repo()
    if getattr(args, "ui", False):
        from whyline.console import tui

        try:
            tui.launch(root)
        except tui.TuiUnavailable as error:
            print(str(error))
            return EXIT_ERROR
        return EXIT_OK
    from whyline.console import repl

    repl.run(root)
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    from whyline import gitq, model as model_module, paths, sync

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    try:
        brief_text = sync.compose(
            root,
            task=args.task_id,
            files=args.files,
            token_budget=args.token_budget,
        )
    except gitq.GitUnavailable as error:
        print(f"git is unavailable: {error}", file=sys.stderr)
        return EXIT_ERROR
    chosen_model = model_module.load(root).get(args.agent)
    try:
        runner.launch(args.agent, args.task, brief_text, model=chosen_model)
    except (runner.UnknownAgent, runner.AgentMissing) as error:
        # The sync packet is still printed, so the handoff is not lost.
        print(str(error), file=sys.stderr)
        print(brief_text)
        return EXIT_ERROR
    return EXIT_OK


def _without_prompt_text(event: dict) -> dict:
    """Redact the prompt body of an Instruction event, keeping its shape."""
    from whyline import events as events_module

    if event.get("type") != events_module.INSTRUCTION or "text" not in event:
        return event
    redacted = dict(event)
    redacted["text"] = "[redacted: pass --include-prompts to show]"
    return redacted


def _prompt_or_why_not(event: dict) -> dict:
    """Asked for prompts: say plainly when one was never stored."""
    from whyline import events as events_module

    if event.get("type") != events_module.INSTRUCTION or "text" in event:
        return event
    return {**event, "text": f"[not captured: prompt_capture={event.get('capture', 'metadata')}]"}


def cmd_timeline(args: argparse.Namespace) -> int:
    from whyline import ledger, paths, render

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    found, skipped = ledger.read_all(paths.ledger_path(root))
    if skipped:
        noun = "line" if skipped == 1 else "lines"
        print(f"warning: skipped {skipped} unreadable ledger {noun}", file=sys.stderr)
    total = len(found)
    filtered = False
    # `is not None`, not truthiness: `--file ""` (an unset shell variable, say)
    # must not be silently ignored — that is the same silent no-op as C4.
    if args.file is not None:
        filtered = True
        found = [
            event
            for event in found
            if event.get("path") == args.file or args.file in (event.get("files") or [])
        ]
    if args.since is not None:
        # C4, 2026-08-17: --since was an unvalidated lexicographic compare, so
        # `--since 2026-8-1` and `--since yesterday` silently matched nothing.
        try:
            since = datetime.date.fromisoformat(args.since).isoformat()
        except ValueError:
            print(
                f"--since expects a date as YYYY-MM-DD, not {args.since!r}",
                file=sys.stderr,
            )
            return EXIT_USAGE
        filtered = True
        found = [event for event in found if str(event.get("ts", "")) >= since]
    found.sort(key=lambda event: str(event.get("ts", "")), reverse=True)
    if args.json:
        # Minor finding 2026-08-17: Instruction events carry raw prompt text —
        # the reason ledger.jsonl is gitignored. Do not spill it into stdout,
        # which is routinely redirected, unless explicitly asked.
        if not args.include_prompts:
            found = [_without_prompt_text(event) for event in found]
        else:
            found = [_prompt_or_why_not(event) for event in found]
        render.emit_json({"events": found})
    elif not found and filtered and total:
        # Never claim the ledger is empty when a filter simply matched nothing.
        noun = "event" if total == 1 else "events"
        render.emit(
            f"No events matched. The ledger holds {total} {noun}; "
            "try widening --file or --since."
        )
    else:
        render.emit(render.timeline_text(found))
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    from whyline import render

    # status deliberately does NOT require initialisation — reporting
    # "not initialised" is its job.
    root = _require_repo()
    payload = render.status_payload(root)
    if args.json:
        render.emit_json(payload)
    else:
        render.emit(render.status_text(payload))
    return EXIT_OK


def relay_install_hint() -> str:
    # whyline-relay is a required dependency, so this only happens in a
    # broken or hand-assembled environment; reinstalling repairs it.
    return (
        "whyline-relay is missing from this whyline install.\n"
        "  uv tool install --reinstall whyline"
    )


def cmd_relay(args: argparse.Namespace) -> int:
    try:
        from whyline_relay import cli as relay_cli
    except ModuleNotFoundError as error:
        if error.name != "whyline_relay":
            raise
        print(relay_install_hint(), file=sys.stderr)
        return EXIT_ERROR
    return relay_cli.main(args.args or [], prog="whyline relay")


COMMANDS = {
    "explain": cmd_explain,
    "note": cmd_note,
    "attach": cmd_attach,
    "retract": cmd_retract,
    "decisions": cmd_decisions,
    "ledger": cmd_ledger,
    "doctor": cmd_doctor,
    "handoff": cmd_handoff,
    "claim": cmd_claim,
    "release": cmd_release,
    "brief": cmd_brief,
    "sync": cmd_sync,
    "run": cmd_run,
    "relay": cmd_relay,
    "timeline": cmd_timeline,
    "status": cmd_status,
    "init": cmd_init,
    "account": cmd_account,
    "model": cmd_model,
    "console": cmd_console,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        if run_entry_menu():
            return EXIT_OK
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    return COMMANDS[args.command](args)


def entry() -> None:
    raise SystemExit(main())
