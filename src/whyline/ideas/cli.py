"""`whyline idea`: the local inbox from the command line.

Commands that change the ledger rebuild the workbook afterwards and print
its path. The Excel file is a view of the ledger; the ledger stays the
record. Commands that only change a setting print that setting.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from whyline.ideas import analyse, brief, documents, memory, paths, reminders, store, xlsx

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
        help="Folder, schema, agents, workbook, pdf, and Telegram",
    )

    tg = sub.add_parser("telegram", help="Chats the inbox may read")
    tg_sub = tg.add_subparsers(dest="idea_telegram_command", required=True)
    tg_sub.add_parser(
        "setup",
        help="Connect a bot if needed, allow a private chat, and offer to turn the inbox on",
    )
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

    request = sub.add_parser(
        "request",
        help="Run one assistant request (called by the scheduler)",
    )
    request.add_argument("request_id", type=int)

    remind = sub.add_parser("remind", help="List or cancel reminders")
    remind_sub = remind.add_subparsers(dest="idea_remind_command", required=True)
    remind_sub.add_parser("list", help="List pending reminders")
    cancel_r = remind_sub.add_parser("cancel", help="Cancel a pending reminder")
    cancel_r.add_argument("id", type=int)

    repos = sub.add_parser(
        "repos",
        help="Repositories an idea may be planned into",
    )
    repos_sub = repos.add_subparsers(dest="idea_repos_command", required=True)
    add_r = repos_sub.add_parser("add", help="Allow a repository")
    add_r.add_argument("name", help="Repository short name")
    add_r.add_argument("path", help="Path to git repository with whyline initialised")
    rm_r = repos_sub.add_parser("remove", help="Remove an allowed repository")
    rm_r.add_argument("name", help="Repository short name")
    repos_sub.add_parser("list", help="List allowed repositories")

    email = sub.add_parser("email", help="Allowed senders for email inbox")
    email_sub = email.add_subparsers(dest="idea_email_command", required=True)
    allow_e = email_sub.add_parser("allow", help="Allow an email address")
    allow_e.add_argument("address", help="Email address")
    deny_e = email_sub.add_parser("deny", help="Deny an email address")
    deny_e.add_argument("address", help="Email address")
    list_e = email_sub.add_parser("list", help="List allowed email addresses")
    list_e.add_argument("address", nargs="?", default=None, help=argparse.SUPPRESS)
    authserv_e = email_sub.add_parser(
        "authserv",
        help="Mail provider id in Authentication-Results (authserv-id)",
    )
    authserv_e.add_argument("authserv_id", nargs="?", default=None, metavar="id")
    intake_e = email_sub.add_parser("intake", help="Process incoming email from file or stdin")
    intake_e.add_argument("--file", action="append", default=[], help="Path to email file")
    handle_e = email_sub.add_parser("handle", help="Process incoming email from file or stdin")
    handle_e.add_argument("--file", action="append", default=[], help="Path to email file")
    email_sub.add_parser("mail-script", help="Install Mail.app rule script for email intake")

    actions = sub.add_parser(
        "actions",
        help="Assistant actions and their approval policy",
    )
    actions_sub = actions.add_subparsers(dest="idea_actions_command", required=True)
    actions_sub.add_parser("list", help="List actions, on/off, approval, and summary")
    set_a = actions_sub.add_parser("set", help="Change an action's policy")
    set_a.add_argument("name", help="Action name")
    switch = set_a.add_mutually_exclusive_group()
    switch.add_argument(
        "--on", action="store_const", const=True, dest="enabled", help="Enable the action"
    )
    switch.add_argument(
        "--off", action="store_const", const=False, dest="enabled", help="Disable the action"
    )
    set_a.add_argument(
        "--approval",
        choices=("none", "tap"),
        default=None,
        help="Approval the action needs",
    )
    set_a.set_defaults(enabled=None)

    mem = sub.add_parser("memory", help="Show, add, forget, or clear memory")
    mem_sub = mem.add_subparsers(dest="idea_memory_command", required=True)
    mem_sub.add_parser("show", help="Show memory")
    add_m = mem_sub.add_parser("add", help="Add a fact to memory")
    add_m.add_argument("fact", nargs="+", help="Fact to remember")
    forget_m = mem_sub.add_parser("forget", help="Forget a fact by number")
    forget_m.add_argument("n", type=int, help="Line number to forget")
    mem_sub.add_parser("clear", help="Clear all memory")

    brief_p = sub.add_parser("brief", help="Morning brief files")
    brief_sub = brief_p.add_subparsers(dest="idea_brief_command", required=True)
    cal = brief_sub.add_parser("calendar", help="Write today's calendar to today.md")
    cal.add_argument("--preview", action="store_true", help="Print the file, not just its path")
    for name, text in (("mail", "Write unread and flagged mail to mail.md"),
                       ("tasks", "Write due Reminders, whyline reminders and memory to tasks.md")):
        extra = brief_sub.add_parser(name, help=text)
        extra.add_argument("--preview", action="store_true", help="Print the file, not just its path")
    setup_p = brief_sub.add_parser("setup", help="Create or update the morning brief agent")
    setup_p.add_argument("--at", default="07:00", help="Weekday time, HH:MM (default 07:00)")
    setup_p.add_argument("--runner", help="Provider that writes the brief (default: first available)")
    setup_p.add_argument("--backup", action="append", default=[], help="Backup provider; repeatable")
    setup_p.add_argument("--chat", type=int, help="Allowed Telegram chat id (default: the first)")


def run(args: argparse.Namespace) -> int:
    command = getattr(args, "idea_command", None)
    handler = _COMMANDS.get(command or "")
    if handler is None:
        print(
            "usage: whyline idea add|list|show|score|refine|drop|reopen|"
            "export|documents|agents|assistant|doctor|telegram|service|work|"
            "request|remind|repos|email|actions|memory|brief",
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


def _enable_hint(name: str) -> str:
    return f"Enable {name} in Settings or choose another provider."


def _subscription_enabled(name: str) -> bool:
    """True unless Settings has turned this provider off.

    No global account file means Settings has not been used, so existing
    installs and tests keep the previous unattended-only filter.
    """
    from whyline.agents.runner import _cli_permitted

    return _cli_permitted(name)


def _detected_agents() -> list[str]:
    """Unattended-capable agents that are installed and logged in."""
    from whyline import account
    from whyline.agents import capabilities

    detected = account.detect()
    names: list[str] = []
    for name in ("claude", "codex", "grok"):
        if not capabilities.can_run_unattended(name):
            continue
        if not _subscription_enabled(name):
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
        return [name for name in stored if _subscription_enabled(name)]
    return _detected_agents()


def _require_agents(conn, args: argparse.Namespace) -> tuple[list[str] | None, str | None]:
    chosen = _chosen_agents(args)
    if chosen is not None:
        refused = _reject_agents(chosen)
        if refused:
            return None, refused
        return chosen, None
    agents = _agents_for(conn, args)
    stored = _stored_agents(conn)
    if stored and not agents:
        off = next(
            (name for name in stored if not _subscription_enabled(name)),
            stored[0],
        )
        return None, _enable_hint(off)
    return agents, None


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
            agents, error = _require_agents(conn, args)
            if error:
                print(error, file=sys.stderr)
                return EXIT_ERROR
            return _run_score(conn, idea.id, agents or [])
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
        agents, error = _require_agents(conn, args)
        if error:
            print(error, file=sys.stderr)
            return EXIT_ERROR
        return _run_score(conn, args.id, agents or [])
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
        agents, error = _require_agents(conn, args)
        if error:
            print(error, file=sys.stderr)
            _publish(conn)
            return EXIT_ERROR
        try:
            analysis = analyse.analyse(conn, idea.id, agents=agents or [])
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
        return EXIT_OK
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
    disabled = [name for name in names if not _subscription_enabled(name)]
    if disabled:
        return "; ".join(_enable_hint(name) for name in disabled)
    return None


def cmd_assistant(args: argparse.Namespace) -> int:
    from whyline.ideas import assistant

    names = [str(args.agent).strip()]
    backup = getattr(args, "backup", None)
    if backup is not None and str(backup).strip():
        names.append(str(backup).strip())
    refused = _reject_agents(names)
    if refused:
        print(refused, file=sys.stderr)
        return EXIT_ERROR
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
        return EXIT_OK
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
        return EXIT_OK
    finally:
        conn.close()


class _Check:
    def __init__(self, name: str, ok: bool, detail: str, *, level: str | None = None):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.level = level or ("ok" if ok else "fail")


Check = _Check

# A reminder this far past due was not sent: the Mac was asleep.
_OVERDUE_AFTER = timedelta(minutes=5)


def _no_wait(_seconds: float) -> None:
    """A check reports the failure. It does not pause for the poller's retry."""
    return None


_WEBHOOK_BLOCKED = (
    "this bot has a webhook, so Telegram refuses polling; "
    "use a separate bot for whyline, or remove the webhook if nothing else uses it"
)


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


def _stored_disabled_names() -> list[str]:
    """Saved inbox agent names that Settings has turned off."""
    from whyline.ideas import assistant as assistant_mod

    folder = paths.configured_home()
    database = folder / "ideas.sqlite3"
    if not database.is_file():
        return []
    try:
        conn = sqlite3.connect(
            f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=10
        )
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return []
    try:
        names: list[str] = []
        stored = _stored_agents(conn) or []
        names.extend(stored)
        for key in (assistant_mod.ASSISTANT_KEY, assistant_mod.BACKUP_KEY):
            row = conn.execute(
                "SELECT value FROM kv WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                continue
            value = row["value"]
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
        off: list[str] = []
        for name in names:
            if name and name not in off and not _subscription_enabled(name):
                off.append(name)
        return off
    finally:
        conn.close()


def _agents_check() -> _Check:
    from whyline.agents import capabilities

    capable = [
        name
        for name in _AGENT_ORDER
        if capabilities.can_run_unattended(name) and _subscription_enabled(name)
    ]
    blocked = [name for name in _AGENT_ORDER if name not in capable]
    stored_off = _stored_disabled_names()
    if not capable:
        if stored_off:
            return _Check(
                "agents", False, "; ".join(_enable_hint(name) for name in stored_off)
            )
        disabled = [
            name
            for name in _AGENT_ORDER
            if capabilities.can_run_unattended(name) and not _subscription_enabled(name)
        ]
        if disabled:
            return _Check(
                "agents", False, "; ".join(_enable_hint(name) for name in disabled)
            )
        return _Check("agents", False, "no agent can run unattended")
    detail = f"{', '.join(capable)} can run unattended"
    if blocked:
        unattended_blocked = [
            name for name in blocked if not capabilities.can_run_unattended(name)
        ]
        disabled = [name for name in blocked if name not in unattended_blocked]
        if unattended_blocked:
            detail += f"; {', '.join(unattended_blocked)} cannot"
        if disabled:
            detail += f"; {'; '.join(_enable_hint(name) for name in disabled)}"
    if stored_off:
        extra = "; ".join(_enable_hint(name) for name in stored_off)
        if extra not in detail:
            detail += f"; {extra}"
        return _Check("agents", False, detail)
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


def _pdf_check() -> _Check:
    """Prove a PDF can be rendered, and say which route did it."""
    try:
        result = documents.probe_pdf()
    except (OSError, subprocess.SubprocessError) as exc:
        return _Check("pdf", False, " ".join(str(exc).split())[:300])
    if result.route == "appkit":
        return _Check("pdf", True, "AppKit")
    if result.route == "plain":
        return _Check("pdf", True, "plain text only", level="warn")
    return _Check("pdf", False, result.reason or "PDF could not be written")


def _report_allowed(conn, private: list[tuple[int, str]]) -> bool:
    """Say which private chats are already allowed. True means leave them."""
    from whyline.ideas import telegram_in

    current = telegram_in.allowed_chats(conn)
    if not current:
        return False
    labels = {cid: label for cid, label in private}
    for cid in current:
        label = labels.get(cid)
        if label:
            print(f"Already allowed: {label}  ({cid})")
        else:
            print(f"Already allowed: {cid}")
    return True


_SKIP_CHAT = object()
_BAD_CHAT = object()


def _ask_chat(private: list[tuple[int, str]], input_fn):
    """The private chat to allow, ``_SKIP_CHAT``, or ``_BAD_CHAT``."""
    print("Private chats:")
    for cid, label in private:
        print(f"{label}  ({cid})")
    if len(private) == 1:
        cid, label = private[0]
        answer = input_fn(f"Allow {label} ({cid})? [Y/n] ").strip().lower()
        if answer in ("", "y", "yes"):
            return cid
        if answer in ("n", "no"):
            print(f"Left {label}  ({cid}) not allowed.")
            return _SKIP_CHAT
    else:
        answer = input_fn("Which private chat id should the inbox read? ").strip()
    try:
        return int(answer)
    except ValueError:
        print("Enter a private chat id.", file=sys.stderr)
        return _BAD_CHAT


def _agents_telegram_setup(input_fn, getpass_fn) -> int:
    """The existing bot prompts: hidden token, Keychain on macOS, then chats."""
    from whyline.cli import _cmd_agents_telegram

    setup_args = argparse.Namespace(telegram_command="setup")
    return _cmd_agents_telegram(
        setup_args, input_fn=input_fn, getpass_fn=getpass_fn
    )


def _telegram_setup(conn, *, input_fn, getpass_fn) -> int:
    from whyline.agents import telegram
    from whyline.ideas import telegram_in, worker

    token = telegram.token_get()
    if not token:
        code = _agents_telegram_setup(input_fn, getpass_fn)
        if code != 0:
            return code
    else:
        try:
            bot = telegram.check_token(token, sleep=_no_wait)
        except telegram.TelegramError as exc:
            print(
                f"error: {telegram.redact(str(exc), token)}",
                file=sys.stderr,
            )
            return EXIT_ERROR
        print(f"Bot {bot} is already saved. Keeping it.")

    private = telegram_in.private_chats(telegram.known_chats())
    if _report_allowed(conn, private):
        pass
    elif not private:
        print(
            "No private chats yet. Send a direct message to the bot, "
            "then run whyline idea telegram setup again."
        )
    else:
        chosen = _ask_chat(private, input_fn)
        if chosen is _BAD_CHAT:
            return EXIT_ERROR
        if chosen is not _SKIP_CHAT:
            try:
                label = telegram_in.allow(conn, chosen)
            except telegram_in.AllowError as exc:
                print(str(exc), file=sys.stderr)
                return EXIT_ERROR
            print(f"{label}  ({chosen})  allowed")

    # Same call as turning the service on. A failure stays in kv for doctor.
    telegram_in.publish_description(conn)

    if worker.enabled(conn):
        print("Inbox already on.")
        return EXIT_OK
    answer = input_fn("Turn the inbox on now? [y/N] ").strip().lower()
    if answer in ("y", "yes"):
        return _service_on()
    print("Inbox left off. Turn it on with: whyline idea service on")
    return EXIT_OK


def cmd_telegram(args: argparse.Namespace) -> int:
    import getpass

    from whyline.agents import telegram
    from whyline.ideas import telegram_in

    action = getattr(args, "idea_telegram_command", None)
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        if action == "setup":
            return _telegram_setup(
                conn, input_fn=input, getpass_fn=getpass.getpass
            )
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
            "usage: whyline idea telegram setup|allow|deny|list",
            file=sys.stderr,
        )
        return EXIT_USAGE
    finally:
        conn.close()


def _service_on() -> int:
    """Turn the inbox on and make sure the scheduler is on.

    ``whyline idea service on`` and the last step of telegram setup both
    call this. The console calls ``worker.turn_on`` directly, which is the
    save underneath, so the flag cannot be written a second way.
    """
    from whyline.ideas import worker

    try:
        worker.turn_on()
    except worker.ServiceError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    print("Inbox on.")
    return EXIT_OK


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
        return _service_on()
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
    line = worker.telegram_error_line()
    if line:
        print(line)


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


def cmd_request(args: argparse.Namespace) -> int:
    from whyline.ideas import worker

    return worker.request(int(args.request_id))


def _id_count(raw: str | None) -> int:
    if not raw:
        return 0
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    if not isinstance(parsed, list):
        return 0
    count = 0
    for item in parsed:
        try:
            int(item)
        except (TypeError, ValueError):
            continue
        count += 1
    return count


def _telegram_token_check() -> _Check:
    from whyline.agents import telegram

    token = telegram.token_get()
    if not token:
        return _Check(
            "telegram token", False, "run whyline idea telegram setup"
        )
    try:
        name = telegram.check_token(token, sleep=_no_wait)
    except telegram.TelegramError as exc:
        return _Check(
            "telegram token", False, telegram.redact(str(exc), token)
        )
    return _Check("telegram token", True, telegram.redact(name, token))


def _allowed_chats_check() -> _Check:
    from whyline.ideas import telegram_in, worker

    count = _id_count(worker.read_kv(telegram_in.ALLOW_KEY))
    if count == 0:
        return _Check("allowed chats", False, "none")
    return _Check("allowed chats", True, str(count))


def _service_check() -> _Check:
    from whyline.ideas import worker

    # A recorded poll failure outranks "off": the inbox is not healthy
    # while Telegram is refusing it, whether or not the flag is on.
    line = worker.telegram_error_line()
    if line:
        return _Check("service", False, line)
    if worker.is_on(worker.read_kv(worker.ENABLED_KEY)):
        return _Check("service", True, "on")
    return _Check(
        "service",
        True,
        "off; run whyline idea service on",
        level="warn",
    )


def _description_check() -> _Check:
    """The last failed setMyDescription, if setup or service on recorded one."""
    from whyline.ideas import telegram_in, worker

    message = worker.read_kv(telegram_in.DESCRIPTION_ERROR_KEY)
    if message:
        return _Check("bot description", False, message)
    if worker.read_kv(telegram_in.DESCRIPTION_KEY):
        return _Check("bot description", True, "set")
    return _Check("bot description", True, "not set")


def _webhook_check() -> _Check:
    from whyline.agents import telegram

    token = telegram.token_get()
    if not token:
        # The token check already fails. There is no bot to ask.
        return _Check("webhook", True, "no bot token", level="warn")
    try:
        info = telegram.webhook_info(token, sleep=_no_wait)
    except telegram.TelegramError as exc:
        return _Check(
            "webhook",
            True,
            telegram.redact(str(exc), token),
            level="warn",
        )
    url = info.get("url") if isinstance(info, dict) else ""
    if isinstance(url, str) and url.strip():
        return _Check("webhook", False, _WEBHOOK_BLOCKED)
    return _Check("webhook", True, "none")


def _email_authserv_check() -> _Check:
    from whyline.ideas import email_in, worker

    value = worker.read_kv(email_in.AUTHSERV_KEY)
    if not value or not str(value).strip():
        return _Check(
            "email authserv",
            True,
            email_in.AUTHSERV_UNSET_NOTE,
            level="warn",
        )
    return _Check("email authserv", True, str(value).strip())


def _mail_script_check(conn) -> _Check:
    from whyline.agents import mail
    from whyline.ideas import email_in

    path = (
        Path.home()
        / "Library"
        / "Application Scripts"
        / "com.apple.mail"
        / "whyline-idea.applescript"
    )
    if not mail.supported():
        return _Check("mail rule script", True, mail.NEEDS_MACOS, level="warn")
    if path.is_file():
        return _Check("mail rule script", True, str(path))
    detail = "missing; run whyline idea email mail-script"
    # Only an inbox that takes email needs the rule.
    in_use = False
    if conn is not None:
        try:
            in_use = bool(email_in.allowed_senders(conn))
        except sqlite3.Error:
            in_use = False
    if in_use:
        return _Check("mail rule script", False, detail)
    return _Check("mail rule script", True, detail, level="warn")


def _last_email_check(conn) -> _Check:
    row = None
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT at FROM inbound WHERE kind = 'email' "
                "ORDER BY at DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            row = None
    if row is None:
        return _Check("last email", True, "none seen", level="warn")
    return _Check("last email", True, str(row[0]))


def _overdue_reminders_check(conn, now: datetime | None = None) -> _Check:
    if conn is None:
        return _Check("reminders", True, "no ideas database", level="warn")
    moment = now or datetime.now().astimezone().replace(tzinfo=None)
    try:
        pending = reminders.pending(conn)
    except sqlite3.Error:
        return _Check("reminders", True, "no ideas database", level="warn")
    late = []
    for item in pending:
        try:
            due = reminders._parse_stamp(item.due_at)
        except ValueError:
            continue
        if due.tzinfo is not None:
            due = due.astimezone().replace(tzinfo=None)
        if moment - due > _OVERDUE_AFTER:
            late.append(item)
    if late:
        return _Check(
            "reminders",
            False,
            f"{len(late)} overdue (the Mac may have slept); oldest due "
            f"{late[0].due_at}",
        )
    return _Check("reminders", True, f"{len(pending)} pending, none overdue")


def _memory_check() -> _Check:
    # configured_home only. memory.memory_path calls paths.home, which
    # creates the folder.
    path = paths.configured_home() / "memory.md"
    if not path.exists():
        return _Check("memory", True, "no memory file yet")
    if os.name == "nt":
        return _Check("memory", True, str(path))
    mode = path.stat().st_mode & 0o777
    if mode != 0o600:
        return _Check("memory", False, f"{path} mode is {mode:04o}, expected 0600")
    return _Check("memory", True, f"{path} mode 0600")


def assistant_doctor(conn, *, now: datetime | None = None) -> list[Check]:
    """The assistant checks. ``whyline idea doctor`` and the console share this.

    ``conn`` may be None when no ledger exists yet; the checks that need it
    then warn instead of creating one.
    """
    return [
        _telegram_token_check(),
        _webhook_check(),
        _service_check(),
        _agents_check(),
        _email_authserv_check(),
        _mail_script_check(conn),
        _last_email_check(conn),
        _overdue_reminders_check(conn, now),
        _memory_check(),
        *brief.check(),
    ]


def _read_only_conn():
    database = paths.configured_home() / "ideas.sqlite3"
    if not database.is_file():
        return None
    try:
        conn = sqlite3.connect(
            f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=10
        )
    except sqlite3.Error:
        return None
    conn.row_factory = sqlite3.Row
    return conn


def cmd_doctor(_args: argparse.Namespace) -> int:
    conn = _read_only_conn()
    try:
        checks = [
            _folder_check(),
            _schema_check(),
            _workbook_check(),
            _pdf_check(),
            _allowed_chats_check(),
            _description_check(),
            *assistant_doctor(conn),
        ]
    finally:
        if conn is not None:
            conn.close()
    for check in checks:
        print(f"{check.level:<6} {check.name}: {check.detail}")
    return EXIT_OK if all(check.ok for check in checks) else EXIT_ERROR


def cmd_repos(args: argparse.Namespace) -> int:
    from whyline.ideas import setup

    action = getattr(args, "idea_repos_command", None)
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        if action == "add":
            try:
                resolved = setup.add_repo(conn, args.name, args.path)
            except setup.SetupError as exc:
                print(str(exc), file=sys.stderr)
                return EXIT_ERROR
            print(f"{args.name}  {resolved}")
            return EXIT_OK
        if action == "remove":
            try:
                removed = setup.remove_repo(conn, args.name)
            except setup.SetupError as exc:
                print(str(exc), file=sys.stderr)
                return EXIT_ERROR
            if not removed:
                print(f"Unknown repository: {args.name}", file=sys.stderr)
                return EXIT_ERROR
            print(f"{args.name}  removed")
            return EXIT_OK
        if action == "list":
            repos = setup.list_repos(conn)
            if not repos:
                print("No repositories configured.")
                return EXIT_OK
            for name, path in sorted(repos.items()):
                print(f"{name}  {path}")
            return EXIT_OK
        print("usage: whyline idea repos add|remove|list", file=sys.stderr)
        return EXIT_USAGE
    finally:
        conn.close()


def cmd_email(args: argparse.Namespace) -> int:
    from whyline.ideas import email_in

    action = getattr(args, "idea_email_command", None)
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        if action == "allow":
            try:
                addr = email_in.allow(conn, args.address)
            except email_in.AllowError as exc:
                print(str(exc), file=sys.stderr)
                return EXIT_ERROR
            print(f"{addr}  allowed")
            return EXIT_OK
        if action == "deny":
            email_in.deny(conn, args.address)
            print(f"{args.address.strip().lower()}  denied")
            return EXIT_OK
        if action == "list":
            senders = email_in.allowed_senders(conn)
            if not senders:
                print("No allowed senders configured.")
                return EXIT_OK
            for addr in sorted(senders):
                print(addr)
            return EXIT_OK
        if action == "authserv":
            given = getattr(args, "authserv_id", None)
            if given is None or not str(given).strip():
                current = email_in.configured_authserv(conn)
                if current:
                    print(current)
                else:
                    print(email_in.AUTHSERV_UNSET_NOTE)
                return EXIT_OK
            try:
                saved = email_in.set_authserv(conn, given)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return EXIT_ERROR
            print(saved)
            return EXIT_OK
        if action in ("intake", "handle"):
            files = getattr(args, "file", []) or []
            if not files:
                if not sys.stdin.isatty():
                    content = sys.stdin.read()
                    email_in.handle(conn, content)
                return EXIT_OK
            for f in files:
                p = Path(f)
                if p.is_file():
                    email_in.handle(conn, p)
            return EXIT_OK
        if action == "mail-script":
            from whyline.agents import mail

            if not mail.supported():
                print(mail.NEEDS_MACOS, file=sys.stderr)
                return EXIT_ERROR
            try:
                path = mail.install("idea")
            except (RuntimeError, OSError, ValueError) as error:
                print(str(error), file=sys.stderr)
                return EXIT_ERROR
            print(path.as_posix())
            return EXIT_OK
        print(
            "usage: whyline idea email allow|deny|list|authserv [<id>]",
            file=sys.stderr,
        )
        return EXIT_USAGE
    finally:
        conn.close()


def cmd_remind(args: argparse.Namespace) -> int:
    action = getattr(args, "idea_remind_command", None)
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        if action == "list":
            rows = reminders.pending(conn)
            if not rows:
                print("No reminders.")
                return EXIT_OK
            for row in rows:
                due = row.due_at.replace("T", " ")[:16]
                print(f"{row.id}  {due}  {row.text}")
            return EXIT_OK
        if action == "cancel":
            if not reminders.cancel(conn, args.id):
                print(f"no pending reminder {args.id}", file=sys.stderr)
                return EXIT_ERROR
            print(f"reminder {args.id} cancelled")
            return EXIT_OK
        print("usage: whyline idea remind list|cancel <id>", file=sys.stderr)
        return EXIT_USAGE
    finally:
        conn.close()


def cmd_brief(args: argparse.Namespace) -> int:
    which = getattr(args, "idea_brief_command", None)
    if which == "setup":
        return _brief_setup(args)
    if which not in ("calendar", "mail", "tasks"):
        print("usage: whyline idea brief calendar|mail|tasks [--preview] | setup", file=sys.stderr)
        return EXIT_USAGE
    names: list[str] = []
    if which != "tasks":
        conn = _connect()
        if conn is None:
            return EXIT_ERROR
        try:
            names = brief.selected(conn) if which == "calendar" else brief.mailboxes_selected(conn)
        finally:
            conn.close()
    try:
        if which == "calendar":
            result = brief.calendar(brief.default_dir(), calendars=names)
        elif which == "mail":
            result = brief.mail(brief.default_dir(), mailboxes=names)
        else:
            result = brief.reminders(brief.default_dir())
    except brief.CalendarError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"could not write the brief: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(result.text.rstrip("\n") if args.preview else result.path)
    return EXIT_OK


def _brief_setup(args: argparse.Namespace) -> int:
    from whyline.ideas import telegram_in

    runner = args.runner
    if not runner:
        found = brief.eligible_providers()
        runner = found[0] if found else ""
    chat_id = args.chat
    if chat_id is None:
        conn = _connect()
        if conn is None:
            return EXIT_ERROR
        try:
            chats = telegram_in.allowed_chats(conn)
        finally:
            conn.close()
        chat_id = chats[0] if chats else 0
    try:
        defn = brief.setup(at=args.at, runner=runner, backup=args.backup, chat_id=chat_id)
    except (brief.SetupError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"morning-brief: weekdays at {defn.trigger.at}, {defn.runner}, Telegram chat {chat_id}")
    print(brief.SEND_WARNING)
    return EXIT_OK


def cmd_actions(args: argparse.Namespace) -> int:
    from whyline.ideas import actions

    action = getattr(args, "idea_actions_command", None)
    conn = _connect()
    if conn is None:
        return EXIT_ERROR
    try:
        if action == "list":
            policy = actions.policy(conn)
            for name, spec in actions.REGISTRY.items():
                row = policy[name]
                state = "on" if row["enabled"] else "off"
                print(f"{name}  {state}  {row['approval']}  {spec.summary}")
            return EXIT_OK
        if action == "set":
            try:
                actions.set_policy(
                    conn,
                    args.name,
                    enabled=getattr(args, "enabled", None),
                    approval=getattr(args, "approval", None),
                )
            except actions.PolicyError as exc:
                print(str(exc), file=sys.stderr)
                return EXIT_ERROR
            row = actions.policy(conn)[args.name]
            state = "on" if row["enabled"] else "off"
            spec = actions.REGISTRY[args.name]
            print(f"{args.name}  {state}  {row['approval']}  {spec.summary}")
            return EXIT_OK
        print("usage: whyline idea actions list|set", file=sys.stderr)
        return EXIT_USAGE
    finally:
        conn.close()


def cmd_memory(args: argparse.Namespace) -> int:
    action = getattr(args, "idea_memory_command", None)
    if action == "show":
        facts = memory.show()
        if not facts:
            print("No memory.")
            return EXIT_OK
        for i, fact in enumerate(facts, 1):
            print(f"{i}. {fact}")
        return EXIT_OK
    if action == "add":
        fact = " ".join(args.fact).strip()
        if not fact:
            print("add needs a fact.", file=sys.stderr)
            return EXIT_ERROR
        try:
            count = memory.add(fact)
        except memory.MemoryFullError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_ERROR
        print(f"remembered ({count})")
        return EXIT_OK
    if action == "forget":
        try:
            count = memory.forget(args.n)
        except (IndexError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_ERROR
        print(f"forgot ({count})")
        return EXIT_OK
    if action == "clear":
        memory.clear()
        print("memory cleared")
        return EXIT_OK
    print("usage: whyline idea memory show|add|forget <n>|clear", file=sys.stderr)
    return EXIT_USAGE


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
    "request": cmd_request,
    "remind": cmd_remind,
    "repos": cmd_repos,
    "email": cmd_email,
    "actions": cmd_actions,
    "memory": cmd_memory,
    "brief": cmd_brief,
}
