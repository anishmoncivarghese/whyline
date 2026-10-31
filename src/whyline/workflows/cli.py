"""`whyline workflow`: a thin command line over `workflows.service`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from whyline.workflows import service

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def add_parser(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("workflow", help="Workflows: list, run, approve, history")
    sub = parser.add_subparsers(dest="workflow_command", required=True)
    sub.add_parser("list", help="Every repo and personal workflow")
    for name, text in (
        ("show", "One workflow's status, what it may do, and its file"),
        ("pause", "Stop its schedule and triggers"),
        ("resume", "Start them again"),
    ):
        sub.add_parser(name, help=text).add_argument("name")
    sub.add_parser("validate", help="Check a workflow file").add_argument("file")
    new = sub.add_parser("new", help="Create a manual workflow with one step")
    new.add_argument("name")
    new.add_argument("--repo", action="store_true", help="save it in this repository")
    accept = sub.add_parser("accept", help="Accept its current definition on this Mac")
    accept.add_argument("name")
    accept.add_argument("--yes", action="store_true", help="do not ask")
    for name, text in (("run", "Run a workflow now"),
                       ("dry-run", "Walk a workflow without running or sending anything")):
        item = sub.add_parser(name, help=text)
        item.add_argument("name")
        item.add_argument("--input", action="append", default=[], metavar="KEY=VALUE")
    runs = sub.add_parser("runs", help="Its recent runs")
    runs.add_argument("name")
    runs.add_argument("-n", type=int, default=20)
    for name, text in (("run-show", "One run, step by step"),
                       ("cancel", "Cancel a run"),
                       ("retry", "Run a failed or cancelled run again")):
        sub.add_parser(name, help=text).add_argument("run_id", type=int)
    for name, text in (("approve", "Approve a waiting approval step"),
                       ("deny", "Deny a waiting approval step")):
        item = sub.add_parser(name, help=text)
        item.add_argument("approval_id", type=int)
        item.add_argument("nonce")
    resolve = sub.add_parser("resolve", help="Settle a run whose outcome is unknown")
    resolve.add_argument("run_id", type=int)
    resolve.add_argument("choice", choices=("done", "failed", "retry"))
    cap = sub.add_parser("cap", help="Show or set the daily limit on agent steps")
    cap.add_argument("count", nargs="?", type=int)
    sub.add_parser("_execute", help="(internal) run one queued run").add_argument(
        "run_id", type=int)


def _root() -> Path | None:
    from whyline import paths

    return paths.find_repo_root()


def _inputs(pairs: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator or not key:
            raise ValueError(f"--input needs key=value, not {pair!r}")
        found[key] = value
    return found


def _table(rows: list[list[str]]) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip())


def _list(args) -> int:
    found = service.rows(_root())
    if not found:
        print(service.NO_WORKFLOWS)
        return EXIT_OK
    _table([["NAME", "KIND", "STATUS", "TRIGGER", "NEXT", "LAST"],
            *[[r.name, r.kind, r.status, r.trigger, r.next, r.last] for r in found]])
    return EXIT_OK


def _show(args) -> int:
    print("\n".join(service.show(args.name, _root())))
    return EXIT_OK


def _validate(args) -> int:
    errors = service.validate(Path(args.file).read_text(encoding="utf-8"))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return EXIT_ERROR
    print("OK")
    return EXIT_OK


def _new(args) -> int:
    print(f"Created {service.new(args.name, 'repo' if args.repo else 'personal', _root())}")
    print(f"Review it, then: whyline workflow accept {args.name}")
    return EXIT_OK


def _accept(args) -> int:
    root = _root()
    changes = service.review(args.name, root)
    print("\n".join(changes) if changes else "Nothing it may do has changed.")
    if not args.yes:
        if not sys.stdin.isatty():
            print("Accept it with --yes after reading the above.", file=sys.stderr)
            return EXIT_ERROR
        if input("Accept? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Not accepted.")
            return EXIT_ERROR
    service.accept(args.name, root)
    print(f"Accepted {args.name}")
    return EXIT_OK


def _pause(args) -> int:
    service.pause(args.name, _root())
    print(f"Paused {args.name}")
    return EXIT_OK


def _resume(args) -> int:
    service.resume(args.name, _root())
    print(f"Resumed {args.name}")
    return EXIT_OK


def _run(args) -> int:
    run_id = service.run_now(args.name, _inputs(args.input), source="manual",
                             repo_root=_root())
    print(f"Started run {run_id}")
    return EXIT_OK


def _dry_run(args) -> int:
    print("\n".join(service.dry_run(args.name, _inputs(args.input), _root())))
    return EXIT_OK


def _runs(args) -> int:
    found = service.runs(args.name, _root(), args.n)
    if not found:
        print(f"{args.name} has not run yet.")
        return EXIT_OK
    _table([["RUN", "STATUS", "SOURCE", "STARTED", "REASON"],
            *[[str(r["id"]), r["status"], r["source"] or "", (r["created"] or "")[:16],
               r["reason"] or ""] for r in found]])
    return EXIT_OK


def _run_show(args) -> int:
    detail = service.run_detail(args.run_id)
    run = detail.run
    print(f"Run {run['id']} of {run['workflow_id']}: {run['status']}"
          + (f" ({run['reason']})" if run["reason"] else ""))
    print(f"Source: {run['source']}  Created: {run['created']}")
    for step in detail.steps:
        print(f"  {step['step_id']}: {step['status']}"
              + (f" ({step['reason']})" if step["reason"] else ""))
    for item in detail.approvals:
        print(f"Approval {item['id']} for {item['step_id']}: {item['status']}")
        if item["status"] == "pending":
            print(f"  {item['message']}")
            print(f"  whyline workflow approve {item['id']} {item['nonce']}")
    return EXIT_OK


def _cancel(args) -> int:
    print(f"Run {args.run_id} is {service.cancel(args.run_id)}")
    return EXIT_OK


def _decide(args) -> int:
    choice = args.workflow_command
    verdict = service.decide(args.approval_id, args.nonce, choice, "cli")
    if verdict == "out_of_date":
        print("That approval is out of date: already answered, expired or the code is wrong.",
              file=sys.stderr)
        return EXIT_ERROR
    print(f"Approval {args.approval_id} {verdict}")
    return EXIT_OK


def _resolve(args) -> int:
    print(f"Run {args.run_id} is {service.resolve(args.run_id, args.choice)}")
    return EXIT_OK


def _retry(args) -> int:
    print(f"Started run {service.retry(args.run_id)}")
    return EXIT_OK


def _cap(args) -> int:
    if args.count is not None:
        service.set_cap(args.count)
    cap = service.get_cap()
    print(f"Daily agent step cap: {cap if cap else 'none'}")
    return EXIT_OK


def _execute(args) -> int:
    from whyline.workflows import engine

    engine.execute(args.run_id)
    return EXIT_OK


_COMMANDS = {
    "list": _list, "show": _show, "validate": _validate, "new": _new, "accept": _accept,
    "pause": _pause, "resume": _resume, "run": _run, "runs": _runs, "run-show": _run_show,
    "cancel": _cancel, "approve": _decide, "deny": _decide, "resolve": _resolve,
    "retry": _retry, "dry-run": _dry_run, "cap": _cap, "_execute": _execute,
}


def run(args: argparse.Namespace) -> int:
    handler = _COMMANDS.get(getattr(args, "workflow_command", "") or "")
    if handler is None:
        print("usage: whyline workflow " + "|".join(_COMMANDS), file=sys.stderr)
        return EXIT_USAGE
    try:
        return handler(args)
    except KeyError as error:
        print(f"error: {error.args[0] if error.args else error}", file=sys.stderr)
    except (LookupError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
    return EXIT_ERROR
