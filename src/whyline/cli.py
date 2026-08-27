"""Command dispatch. Keep imports light — cold start budget is 200 ms."""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from whyline import __version__

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_UNINITIALISED = 3


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
    parser.add_argument("--actor", default="", help="Agent or person deciding")
    parser.add_argument("--role", default="", help="Role for this decision")
    parser.add_argument("--task", default="", help="Task identifier")


def _add_handoff(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("handoff", help="Record an active-task handoff")
    parser.add_argument("task", help="Task identifier")
    parser.add_argument("--from", required=True, dest="from_actor", metavar="ACTOR")
    parser.add_argument("--to", required=True, dest="to_actor", metavar="ACTOR")
    parser.add_argument("--status", required=True)
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
    parser.add_argument("--json", action="store_true")


def _add_release(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("release", help="Release advisory ownership")
    parser.add_argument("task")
    parser.add_argument("--actor", required=True)
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
    parser.add_argument("agent", choices=("claude", "codex"))
    parser.add_argument("task")
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--file", action="append", default=[], dest="files")
    parser.add_argument("--token-budget", type=_token_budget, default=1200)


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="whyline",
        description="Records why your code exists, and tells the next agent.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    _add_explain(subparsers)
    _add_note(subparsers)
    _add_handoff(subparsers)
    _add_claim(subparsers)
    _add_release(subparsers)
    _add_brief(subparsers)
    _add_sync(subparsers)
    _add_run(subparsers)
    _add_timeline(subparsers)
    _add_status(subparsers)
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
    # C5, 2026-08-17: normalise at the boundary so the ledger and decisions.md
    # hold the same value. Sanitising only at render time would leave the two
    # stores silently disagreeing about what was recorded.
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


def cmd_handoff(args: argparse.Namespace) -> int:
    from whyline import gitq, handoff, paths, render

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
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
    try:
        state = ownership.release(root, task=args.task, actor=args.actor)
    except OSError as error:
        print(f"could not release ownership: {error}", file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        render.emit_json(state)
    else:
        print(f"Released {args.task} for {args.actor}.")
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
        except hooks.SettingsUnreadable as error:
            print(str(error), file=sys.stderr)
            return EXIT_ERROR
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    from whyline import gitq, paths, runner, sync

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
    try:
        runner.launch(args.agent, args.task, brief_text)
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


COMMANDS = {
    "explain": cmd_explain,
    "note": cmd_note,
    "handoff": cmd_handoff,
    "claim": cmd_claim,
    "release": cmd_release,
    "brief": cmd_brief,
    "sync": cmd_sync,
    "run": cmd_run,
    "timeline": cmd_timeline,
    "status": cmd_status,
    "init": cmd_init,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    return COMMANDS[args.command](args)


def entry() -> None:
    raise SystemExit(main())
