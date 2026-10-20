"""`whyline idea`: the local inbox from the command line.

Mutating commands rebuild the workbook afterwards and print its path.
The Excel file is a view of the ledger; the ledger stays the record.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from whyline.ideas import analyse, documents, paths, store, xlsx

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

_AGENTS_KEY = "default_agents"
_FORMATS_KEY = "doc_formats"
_AGENT_ORDER = ("claude", "codex", "grok", "antigravity")
_SOURCE = "cli"


def add_parser(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("idea", help="Local idea inbox")
    sub = parser.add_subparsers(dest="idea_command", required=True)

    add = sub.add_parser("add", help="Capture an idea and print its id")
    add.add_argument("text", help="The idea, as one argument")
    add.add_argument(
        "--score",
        action="store_true",
        help="Score the new idea immediately",
    )
    _agent_flag(add)

    listing = sub.add_parser("list", help="List ideas")
    listing.add_argument("--status", choices=store.STATUSES, default=None)

    show = sub.add_parser("show", help="Latest report, document paths, and history")
    show.add_argument("id", type=int)

    score = sub.add_parser("score", help="Score an idea with one read-only turn")
    score.add_argument("id", type=int)
    _agent_flag(score)

    refine = sub.add_parser("refine", help="Add context to a scored idea and score again")
    refine.add_argument("id", type=int)
    refine.add_argument("text", help="Extra context")
    _agent_flag(refine)

    drop = sub.add_parser("drop", help="Drop an idea")
    drop.add_argument("id", type=int)

    reopen = sub.add_parser("reopen", help="Bring a dropped idea back to captured")
    reopen.add_argument("id", type=int)

    sub.add_parser("export", help="Rebuild the workbook and print its path")

    formats = sub.add_parser(
        "documents",
        help="Choose Word, PDF, or both for later idea documents",
    )
    formats.add_argument("format", choices=("word", "pdf", "both"))

    agents = sub.add_parser(
        "agents",
        help="Default agents for score, in fallback order",
    )
    agents.add_argument("names", nargs="+", metavar="agent")

    assistant = sub.add_parser(
        "assistant",
        help="Agent and backup that propose inbox cards",
    )
    assistant.add_argument("agent", help="Primary agent")
    assistant.add_argument("--backup", default=None, help="Backup agent")

    sub.add_parser(
        "doctor",
        help="Folder, schema, unattended agents, workbook, and cupsfilter",
    )

    tg = sub.add_parser("telegram", help="Chats the inbox may read")
    tg_sub = tg.add_subparsers(dest="idea_telegram_command", required=True)
    allow = tg_sub.add_parser("allow", help="Read a private known chat")
    allow.add_argument("chat_id", type=int)
    deny = tg_sub.add_parser("deny", help="Stop reading a chat")
    deny.add_argument("chat_id", type=int)
    tg_sub.add_parser("list", help="Known chats, and which are allowed")

    service = sub.add_parser(
        "service",
        help="Run the inbox from the agents scheduler",
    )
    service_sub = service.add_subparsers(dest="idea_service_command", required=True)
    service_sub.add_parser(
        "on",
        help="Turn the inbox on and make sure the scheduler is on",
    )
    service_sub.add_parser("off", help="Turn the inbox off")
    service_sub.add_parser(
        "status",
        help="Whether the inbox is on, and how catch-up works",
    )

    work = sub.add_parser(
        "work",
        help="Run one inbox job (called by the scheduler)",
    )
    work.add_argument("job_id", type=int)


def run(args: argparse.Namespace) -> int:
    command = getattr(args, "idea_command", None)
    handler = _COMMANDS.get(command or "")
    if handler is None:
        print(
            "usage: whyline idea add|list|show|score|refine|drop|reopen|"
            "export|documents|agents|assistant|doctor|telegram|service|work",
            file=sys.stderr,
        )
        return EXIT_USAGE
    return handler(args)


def _agent_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--agent",
        action="append",
        nargs="+",
        default=None,
        metavar="AGENT",
        help="Agent to score with, in fallback order. Repeat to add more.",
    )


def _connect():
    try:
        return store.connect()
    except store.SchemaError as exc:
        print(str(exc), file=sys.stderr)
        return None


def _missing(idea_id: int) -> int:
    print(f"no idea {idea_id}", file=sys.stderr)
    return EXIT_ERROR


def _publish(conn) -> bool:
    """Rebuild the workbook. Print the path that was written."""
    try:
        print(xlsx.export(conn))
    except OSError as exc:
        print(f"could not write the workbook: {exc}", file=sys.stderr)
        return False
    return True


def _finish(conn) -> int:
    return EXIT_OK if _publish(conn) else EXIT_ERROR


def _kv_set(conn, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _chosen_agents(args: argparse.Namespace) -> list[str] | None:
    given = getattr(args, "agent", None)
    if not given:
        return None
    names: list[str] = []
    for group in given:
        items = group if isinstance(group, list) else [group]
        for item in items:
            text = str(item).strip()
            if text and text not in names:
                names.append(text)
    return names


def _stored_agents(conn) -> list[str] | None:
    row = conn.execute(
        "SELECT value FROM kv WHERE key = ?", (_AGENTS_KEY,)
    ).fetchone()
    if row is None:
        return None
    raw = row["value"]
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw.split()
    if isinstance(parsed, str):
        parsed = parsed.split()
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _detected_agents() -> list[str]:
    """Unattended-capable agents that are installed and logged in."""
    from whyline import account
    from whyline.agents import capabilities

    detected = account.detect()
    names: list[str] = []
    for name in ("claude", "codex", "grok"):
        if not capabilities.can_run_unattended(name):
            continue
        info = detected.get(name)
        if isinstance(info, dict) and info.get("available"):
            names.append(name)
    return names


def _agents_for(conn, args: argparse.Namespace) -> list[str]:
    chosen = _chosen_agents(args)
    if chosen is not None:
        return chosen
    stored = _stored_agents(conn)
    if stored is not None:
        return stored
    return _detected_agents()


def _print_scores(analysis: store.Analysis) -> None:
    print(f"agent: {analysis.agent}")
    print(f"usefulness: {analysis.usefulness}")
    print(f"complexity_mvp: {analysis.complexity_mvp}")
    print(f"complexity_full: {analysis.complexity_full}")
    print(f"verdict: {analysis.verdict}")
    print(f"confidence: {analysis.confidence}")


def _run_score(conn, idea_id: int, agents: list[str]) -> int:
    try:
        analysis = analyse.analyse(conn, idea_id, agents=agents)
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    except (store.IllegalMove, store.StaleRevision) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    except analyse.AnalyseError as exc:
        print(str(exc), file=sys.stderr)
        _publish(conn)
        return EXIT_ERROR
    _print_scores(analysis)
    return _finish(conn)


def _label(idea: store.Idea) -> str:
    title = idea.title.strip()
    if title:
        return title
    flat = " ".join(idea.original_text.split())
    return flat or "(untitled)"


def cmd_add(args: argparse.Namespace) -> int:
    text = args.text
    if not str(text).strip():
        print("add needs the idea text.", file=sys.stderr)
        return EXIT_USAGE
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        idea = store.add(conn, text, source=_SOURCE)
        print(idea.id)
        if args.score:
            return _run_score(conn, idea.id, _agents_for(conn, args))
        return _finish(conn)
    finally:
        conn.close()


def cmd_list(args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        ideas = store.list_ideas(conn, args.status)
        for idea in ideas:
            print(f"{idea.id}  {idea.status}  {_label(idea)}")
        return EXIT_OK
    finally:
        conn.close()


def cmd_show(args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        idea = store.get(conn, args.id)
        if idea is None:
            return _missing(args.id)
        print(f"idea {idea.id}")
        print(f"status: {idea.status}")
        print(f"revision: {idea.revision}")
        print(f"title: {_label(idea)}")
        print(f"source: {idea.source}")
        print()
        print(idea.original_text.rstrip())
        print()
        _print_report(conn, idea.id)
        print()
        print("documents:")
        print(f"brainstorm: {idea.brainstorm_path or '(none)'}")
        print(f"spec: {idea.spec_path or '(none)'}")
        print(f"plan: {idea.plan_path or '(none)'}")
        print()
        _print_history(conn, idea.id)
        return EXIT_OK
    finally:
        conn.close()


def _print_report(conn, idea_id: int) -> None:
    row = conn.execute(
        """
        SELECT * FROM analyses
        WHERE idea_id = ?
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (idea_id,),
    ).fetchone()
    if row is None:
        print("report: (none)")
        return
    print(f"report: {row['report_path']}")
    path = Path(row["report_path"])
    if not path.is_file():
        print("(report file is missing)")
        return
    print(path.read_text(encoding="utf-8", errors="replace").rstrip())


def _print_history(conn, idea_id: int) -> None:
    rows = conn.execute(
        "SELECT * FROM events WHERE idea_id = ? ORDER BY id",
        (idea_id,),
    ).fetchall()
    print("history:")
    if not rows:
        print("(none)")
        return
    for row in rows:
        note = " ".join(str(row["note"]).split())
        line = (
            f"{row['at']}  {row['from_status']} -> {row['to_status']}  {row['actor']}"
        )
        if note:
            line += f"  {note}"
        print(line)


def cmd_score(args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        if store.get(conn, args.id) is None:
            return _missing(args.id)
        return _run_score(conn, args.id, _agents_for(conn, args))
    finally:
        conn.close()


def _remember_context(conn, idea: store.Idea, extra: str) -> None:
    """Keep the refinement where the next score can read it, and in history.

    ``analyse`` scores ``original_text`` and records its own status move
    with an empty note. Events are append-only, so the context is a
    separate event. ``analyse`` then moves scored to scoring and scores.
    """
    base = idea.original_text.rstrip()
    text = f"{base}\n\n{extra}" if base else extra
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE ideas SET original_text = ? WHERE id = ?",
            (text, idea.id),
        )
        conn.execute(
            """
            INSERT INTO events (idea_id, at, from_status, to_status, actor, note)
            VALUES (?, ?, ?, ?, 'cli', ?)
            """,
            (idea.id, store._now(), idea.status, idea.status, extra),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def cmd_refine(args: argparse.Namespace) -> int:
    extra = str(args.text).strip()
    if not extra:
        print("refine needs the extra context.", file=sys.stderr)
        return EXIT_USAGE
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        idea = store.get(conn, args.id)
        if idea is None:
            return _missing(args.id)
        if idea.status != "scored":
            print(
                f"cannot refine idea {idea.id} from {idea.status}; it has to be scored",
                file=sys.stderr,
            )
            return EXIT_ERROR
        _remember_context(conn, idea, extra)
        try:
            analysis = analyse.analyse(conn, idea.id, agents=_agents_for(conn, args))
        except LookupError as exc:
            print(str(exc), file=sys.stderr)
            _publish(conn)
            return EXIT_ERROR
        except (store.IllegalMove, store.StaleRevision) as exc:
            print(str(exc), file=sys.stderr)
            _publish(conn)
            return EXIT_ERROR
        except analyse.AnalyseError as exc:
            print(str(exc), file=sys.stderr)
            _publish(conn)
            return EXIT_ERROR
        _print_scores(analysis)
        return _finish(conn)
    finally:
        conn.close()


def _move(args: argparse.Namespace, to: str) -> int:
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        idea = store.get(conn, args.id)
        if idea is None:
            return _missing(args.id)
        try:
            moved = store.transition(
                conn,
                idea.id,
                to,
                expected_revision=idea.revision,
                actor=_SOURCE,
            )
        except (store.IllegalMove, store.StaleRevision) as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_ERROR
        print(f"idea {moved.id}  {moved.status}")
        return _finish(conn)
    finally:
        conn.close()


def cmd_drop(args: argparse.Namespace) -> int:
    return _move(args, "dropped")


def cmd_reopen(args: argparse.Namespace) -> int:
    return _move(args, "captured")


def cmd_export(_args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        return _finish(conn)
    finally:
        conn.close()


def cmd_documents(args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        _kv_set(conn, _FORMATS_KEY, args.format)
        print(args.format)
        return _finish(conn)
    finally:
        conn.close()


def _reject_agents(names: list[str]) -> str | None:
    from whyline.agents import capabilities

    unknown = [name for name in names if name not in _AGENT_ORDER]
    if unknown:
        return "unknown agent " + ", ".join(unknown)
    blocked = [name for name in names if not capabilities.can_run_unattended(name)]
    if blocked:
        return "; ".join(
            f"{name}: not cleared for unattended runs" for name in blocked
        )
    return None


def cmd_assistant(args: argparse.Namespace) -> int:
    from whyline.ideas import assistant

    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        try:
            assistant.save(conn, str(args.agent), getattr(args, "backup", None))
        except assistant.AssistantError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_ERROR
        backup = getattr(args, "backup", None)
        if backup is not None and str(backup).strip():
            print(f"{str(args.agent).strip()} {str(backup).strip()}")
        else:
            print(str(args.agent).strip())
        return _finish(conn)
    finally:
        conn.close()


def cmd_agents(args: argparse.Namespace) -> int:
    names: list[str] = []
    for name in args.names:
        text = str(name).strip()
        if text and text not in names:
            names.append(text)
    if not names:
        print("agents needs at least one name.", file=sys.stderr)
        return EXIT_USAGE
    refused = _reject_agents(names)
    if refused:
        print(refused, file=sys.stderr)
        return EXIT_ERROR
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        _kv_set(conn, _AGENTS_KEY, json.dumps(names))
        print(" ".join(names))
        return _finish(conn)
    finally:
        conn.close()


class _Check:
    def __init__(self, name: str, ok: bool, detail: str):
        self.name = name
        self.ok = ok
        self.detail = detail


def _folder_check() -> _Check:
    # configured_home only. paths.home creates the folder and chmods it to 0700.
    folder = paths.configured_home()
    if not folder.is_dir():
        return _Check("folder", False, f"{folder} is not a directory")
    try:
        mode = folder.stat().st_mode & 0o777
    except OSError as exc:
        return _Check("folder", False, f"could not read the ideas folder: {exc}")
    if os.name != "nt":
        if mode != 0o700:
            return _Check("folder", False, f"{folder} mode is {mode:04o}, expected 0700")
        if not os.access(folder, os.W_OK | os.X_OK):
            return _Check("folder", False, f"{folder} is not writable")
        return _Check("folder", True, f"{folder} mode 0700")
    if not os.access(folder, os.W_OK | os.X_OK):
        return _Check("folder", False, f"{folder} is not writable")
    return _Check("folder", True, f"{folder} is writable")


def _schema_check() -> _Check:
    # Read a database that already exists. store.connect creates one and
    # writes schema 1, which would report a missing ledger as healthy.
    path = paths.configured_home() / "ideas.sqlite3"
    if not path.is_file():
        return _Check("schema", False, f"ideas database is missing ({path})")
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error as exc:
        return _Check("schema", False, f"could not open the ideas database: {exc}")
    try:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT value FROM kv WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.Error as exc:
            return _Check("schema", False, f"could not read the ideas schema: {exc}")
    finally:
        conn.close()
    if row is None:
        return _Check("schema", False, "schema_version is missing")
    version = row["value"]
    if str(version) != str(store.SCHEMA_VERSION):
        return _Check(
            "schema",
            False,
            f"schema version {version}; this whyline supports version {store.SCHEMA_VERSION}",
        )
    return _Check("schema", True, f"schema version {version}")


def _agents_check() -> _Check:
    from whyline.agents import capabilities

    capable = [name for name in _AGENT_ORDER if capabilities.can_run_unattended(name)]
    blocked = [name for name in _AGENT_ORDER if name not in capable]
    if not capable:
        return _Check("agents", False, "no agent can run unattended")
    detail = f"{', '.join(capable)} can run unattended"
    if blocked:
        detail += f"; {', '.join(blocked)} cannot"
    return _Check("agents", True, detail)


def _can_write(path: Path) -> bool:
    if not os.access(path, os.W_OK):
        return False
    if os.name == "nt":
        return True
    return bool(path.stat().st_mode & 0o200)


def _workbook_check() -> _Check:
    # workbook() calls home(), which would create and chmod the folder.
    target = paths.configured_home() / "ideas.xlsx"
    if target.exists():
        if target.is_file() and _can_write(target):
            return _Check("workbook", True, f"{target} is writable")
        return _Check("workbook", False, f"workbook is not writable ({target})")
    parent = target.parent
    if parent.is_dir() and os.access(parent, os.W_OK):
        return _Check("workbook", True, f"{target} can be created")
    return _Check("workbook", False, f"workbook is not writable ({target})")


def _cupsfilter_check() -> _Check:
    location = Path(documents.CUPSFILTER)
    if location.is_file():
        return _Check("cupsfilter", True, f"{location} is present")
    return _Check("cupsfilter", False, f"cupsfilter is missing ({location})")


def cmd_telegram(args: argparse.Namespace) -> int:
    from whyline.agents import telegram
    from whyline.ideas import telegram_in

    action = getattr(args, "idea_telegram_command", None)
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        if action == "list":
            chats = telegram.known_chats()
            if not chats:
                print("No Telegram chats yet. Run: whyline agents telegram setup")
                return EXIT_OK
            allowed = set(telegram_in.allowed_chats(conn))
            for cid, label in chats.items():
                mark = "  allowed" if cid in allowed else ""
                print(f"{label}  ({cid}){mark}")
            return EXIT_OK
        if action == "allow":
            try:
                label = telegram_in.allow(conn, args.chat_id)
            except telegram_in.AllowError as exc:
                print(str(exc), file=sys.stderr)
                return EXIT_ERROR
            print(f"{label}  ({args.chat_id})  allowed")
            return EXIT_OK
        if action == "deny":
            telegram_in.deny(conn, args.chat_id)
            print(f"{args.chat_id}  denied")
            return EXIT_OK
        print(
            "usage: whyline idea telegram allow|deny|list",
            file=sys.stderr,
        )
        return EXIT_USAGE
    finally:
        conn.close()


def cmd_service(args: argparse.Namespace) -> int:
    """``on`` sets kv ``enabled`` and starts the existing scheduler.

    ``off`` clears the flag and leaves the scheduler alone: other agents
    still use it. ``status`` always says that Telegram keeps about a day of
    undelivered updates, which is how a tick catches up after the Mac was off.
    """
    from whyline.agents import launchd
    from whyline.ideas import worker

    action = getattr(args, "idea_service_command", None)
    if action == "on":
        if not launchd.supported():
            print(launchd.NEEDS_MACOS, file=sys.stderr)
            return EXIT_ERROR
        try:
            launchd.turn_on()
        except (RuntimeError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_ERROR
        conn = _connect()
        if conn is None:
            return EXIT_ERROR
        try:
            _kv_set(conn, worker.ENABLED_KEY, "on")
            print("Inbox on.")
            return EXIT_OK
        finally:
            conn.close()
    if action == "off":
        conn = _connect()
        if conn is None:
            return EXIT_ERROR
        try:
            _kv_set(conn, worker.ENABLED_KEY, "off")
            print("Inbox off.")
            return EXIT_OK
        finally:
            conn.close()
    if action == "status":
        _print_service_status(launchd)
        return EXIT_OK
    print("usage: whyline idea service on|off|status", file=sys.stderr)
    return EXIT_USAGE


def _print_service_status(launchd) -> None:
    from whyline.ideas import worker

    print(f"Inbox {'on' if _inbox_enabled() else 'off'}.")
    if not launchd.supported():
        print(launchd.NEEDS_MACOS)
    else:
        try:
            info = launchd.status()
        except (RuntimeError, OSError) as exc:
            print(f"Scheduler: {exc}")
        else:
            state = "loaded" if info.loaded else "not loaded"
            print(f"Scheduler {state}.")
    print(worker.CATCH_UP)


def _inbox_enabled() -> bool:
    from whyline.ideas import worker

    path = paths.configured_home() / "ideas.sqlite3"
    if not path.is_file():
        return False
    conn = _connect()
    if conn is None:
        return False
    try:
        return worker.enabled(conn)
    finally:
        conn.close()


def cmd_work(args: argparse.Namespace) -> int:
    from whyline.ideas import worker

    return worker.work(int(args.job_id))


def cmd_doctor(_args: argparse.Namespace) -> int:
    checks = (
        _folder_check(),
        _schema_check(),
        _agents_check(),
        _workbook_check(),
        _cupsfilter_check(),
    )
    for check in checks:
        state = "ok" if check.ok else "fail"
        print(f"{state:<6} {check.name}: {check.detail}")
    return EXIT_OK if all(check.ok for check in checks) else EXIT_ERROR


_COMMANDS = {
    "add": cmd_add,
    "list": cmd_list,
    "show": cmd_show,
    "score": cmd_score,
    "refine": cmd_refine,
    "drop": cmd_drop,
    "reopen": cmd_reopen,
    "export": cmd_export,
    "documents": cmd_documents,
    "agents": cmd_agents,
    "assistant": cmd_assistant,
    "doctor": cmd_doctor,
    "telegram": cmd_telegram,
    "service": cmd_service,
    "work": cmd_work,
}
