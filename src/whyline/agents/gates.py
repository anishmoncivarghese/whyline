"""Check-in gates: fixed checks that read Mail, Calendar, GitHub or files without a model."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from whyline.ideas import guard

MAX_SEEN = 500
MAX_FILES = 200
MAX_LINE = 300
MAX_TEXT = 200
MAX_MINUTES = 1440
GH_TIMEOUT = 30
KINDS = ("text", "minutes", "repo", "path")


class GateError(ValueError):
    """A gate or one of its arguments is not usable; the message says why."""


@dataclass(frozen=True)
class Arg:
    key: str
    label: str
    kind: str
    default: str = ""


@dataclass(frozen=True)
class Item:
    key: str
    line: str


@dataclass(frozen=True)
class Found:
    items: list[Item]
    state: dict


@dataclass(frozen=True)
class Gate:
    name: str
    label: str
    args: tuple[Arg, ...]
    run: Callable[..., list[Item]]


def unread_mail_script() -> str:
    """The brief's Mail script, narrowed to unread mail (it also returns flagged read mail)."""
    from whyline.ideas import brief

    wide = "(read status is false or flagged status is true)"
    if wide not in brief.MAIL_SCRIPT:
        raise GateError("the Mail script changed; mail-from cannot limit itself to unread mail")
    return brief.MAIL_SCRIPT.replace(wide, "(read status is false)")


def calendar_script() -> str:
    """The brief's calendar script, widened from today to today and tomorrow."""
    from whyline.ideas import brief

    source = brief.SCRIPT.read_text(encoding="utf-8")
    today_end = "now.getDate() + 1)"
    if today_end not in source:
        raise GateError("the calendar script changed; event-soon cannot look past midnight")
    return source.replace(today_end, "now.getDate() + 2)")


def read_mail(mailboxes: list[str], run) -> list:
    from whyline.ideas import brief

    if not mailboxes:
        return []
    answer = brief._osascript(
        "Mail", "Automation > Mail", unread_mail_script(), ["24", "40", *mailboxes], run
    )
    if answer.strip() == "not-running":
        return []
    return brief._parse_mail(answer)[1]


def read_events(run) -> list:
    """Events from today and tomorrow, from every calendar."""
    import json

    from whyline.ideas import brief

    command = [brief.OSASCRIPT, "-l", "JavaScript", "-e", calendar_script(), "[]"]
    try:
        done = run(command, capture_output=True, text=True, timeout=brief.TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise GateError("the calendar did not answer in time") from None
    except OSError as exc:
        raise GateError(f"could not run osascript: {exc}") from exc
    try:
        data = json.loads((done.stdout or "").strip())
    except ValueError:
        data = None
    if not isinstance(data, dict):
        detail = " ".join((done.stderr or "").split())[:200]
        raise GateError(f"the calendar script failed: {detail or 'no output'}")
    if data.get("status") == "denied":
        raise GateError("Calendar access was refused")
    if done.returncode != 0 or data.get("status") != "ok":
        raise GateError("the calendar script failed: unexpected answer")
    try:
        return [brief._event(item) for item in data.get("events", [])]
    except (KeyError, TypeError, ValueError) as exc:
        raise GateError(f"the calendar script gave unreadable data: {exc}") from exc


def _default_mail():
    from whyline.ideas import brief, store

    conn = store.connect()
    try:
        mailboxes = brief.mailboxes_selected(conn)
    finally:
        conn.close()
    return read_mail(mailboxes, subprocess.run)


def _default_events():
    return read_events(subprocess.run)


def _default_reminders():
    from whyline.ideas import brief

    return brief._fetch_reminders(subprocess.run)


def _default_repos() -> dict[str, str]:
    from whyline.ideas import setup, store

    conn = store.connect()
    try:
        return setup.list_repos(conn)
    finally:
        conn.close()


@dataclass(frozen=True)
class Readers:
    """Where a gate gets its data. Each one is a plain function so tests can fake it."""

    mail: Callable[[], list] = field(default=_default_mail)  # Message objects
    events: Callable[[], list] = field(default=_default_events)  # brief.Event objects
    reminders: Callable[[], list] = field(default=_default_reminders)  # (title, due, list)
    repos: Callable[[], dict] = field(default=_default_repos)  # name -> path


def _naive(moment: datetime, now: datetime) -> datetime:
    if moment.tzinfo is not None and now.tzinfo is None:
        return moment.astimezone().replace(tzinfo=None)
    if moment.tzinfo is None and now.tzinfo is not None:
        return moment.replace(tzinfo=now.tzinfo)
    return moment


def _clean(text: str) -> str:
    cleaned, _ = guard.clean(str(text))
    return " ".join(cleaned.split())


def _mail_from(args, state, now, run, readers):
    needle = args["sender"].lower()
    items = []
    for m in readers.mail():
        if needle in m.sender.lower():
            key = f"mail|{m.sender}|{m.subject}|{m.received.isoformat()}"
            items.append(
                Item(key, f"Mail from {_clean(m.sender)}: {_clean(m.subject) or '(no subject)'}")
            )
    return items


def _event_soon(args, state, now, run, readers):
    limit = now + timedelta(minutes=int(args["minutes"]))
    items = []
    for e in readers.events():
        if e.all_day:
            continue
        start = _naive(e.start, now)
        if now <= start <= limit:
            where = f" at {_clean(e.location)}" if e.location else ""
            items.append(
                Item(
                    f"event|{e.title}|{e.start.isoformat()}",
                    f"Event at {start.strftime('%H:%M')}: {_clean(e.title)}{where}",
                )
            )
    return items


def _ci_failed(args, state, now, run, readers):
    repo = args["repo"]
    path = readers.repos().get(repo)
    if not path:
        raise GateError(f"{repo} is not a repository whyline knows")
    default = _gh(
        run,
        ["gh", "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
        path,
    ).strip()
    if not default:
        raise GateError(f"could not find the default branch of {repo}")
    out = _gh(
        run,
        [
            "gh", "run", "list", "--branch", default, "--status", "failure",
            "--limit", "5", "--json", "databaseId,displayTitle,url,createdAt",
        ],
        path,
    )
    import json

    try:
        runs = json.loads(out or "[]")
    except ValueError as exc:
        raise GateError("gh gave an answer that could not be read") from exc
    items = []
    for r in runs if isinstance(runs, list) else []:
        if not isinstance(r, dict):
            continue
        items.append(
            Item(
                f"ci|{repo}|{r.get('databaseId', '')}",
                f"CI failed on {repo} {default}: {_clean(r.get('displayTitle', ''))} "
                f"{_clean(r.get('url', ''))}",
            )
        )
    return items


def _gh(run, argv: list[str], cwd: str) -> str:
    try:
        done = run(argv, capture_output=True, text=True, timeout=GH_TIMEOUT, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise GateError("gh did not answer in time") from None
    except OSError as exc:
        raise GateError(f"could not run gh: {exc}") from exc
    if done.returncode != 0:
        detail = " ".join((done.stderr or "").split())[:200]
        raise GateError(f"gh failed: {detail or 'no output'}")
    return done.stdout or ""


def _reminder_overdue(args, state, now, run, readers):
    items = []
    for title, due, where in readers.reminders():
        try:
            moment = _naive(datetime.fromisoformat(due), now)
        except ValueError:
            continue
        if moment < now:
            items.append(
                Item(
                    f"reminder|{title}|{due}",
                    f"Overdue since {moment.strftime('%Y-%m-%d %H:%M')}: {_clean(title)}",
                )
            )
    return items


def _changed(args, state, now, run, readers):
    root = _home_path(args["path"])
    since = state.get("checked")
    state["checked"] = now.timestamp()
    if since is None:
        return []  # the first look only sets the baseline
    found: list[tuple[float, Path]] = []
    examined = 0
    if root.is_file():
        files = [root]
    else:
        files = _walk(root)
    for f in files:
        if examined >= MAX_FILES:
            break
        examined += 1
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if mtime > since:
            found.append((mtime, f))
    return [
        Item(f"file|{f}|{mtime}", f"Changed: {_clean(str(f))}")
        for mtime, f in sorted(found, key=lambda p: str(p[1]))
    ]


def _walk(root: Path):
    for base, dirs, names in os.walk(root):
        dirs.sort()
        for name in sorted(names):
            yield Path(base) / name


GATES: dict[str, Gate] = {
    g.name: g
    for g in (
        Gate(
            "mail-from",
            "New mail from a sender",
            (Arg("sender", "Sender contains", "text"),),
            _mail_from,
        ),
        Gate(
            "event-soon",
            "A calendar event starting soon",
            (Arg("minutes", "Minutes ahead", "minutes", "15"),),
            _event_soon,
        ),
        Gate("ci-failed", "Failed CI on a repo", (Arg("repo", "Repository", "repo"),), _ci_failed),
        Gate("reminder-overdue", "An overdue reminder", (), _reminder_overdue),
        Gate("changed", "A file or folder changed", (Arg("path", "Path", "path"),), _changed),
    )
}


def _home_path(value: str) -> Path:
    try:
        path = Path(value).expanduser().resolve()
        home = Path.home().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise GateError(f"{value} is not a usable path") from exc
    if path != home and home not in path.parents:
        raise GateError("the path must be inside your home folder")
    return path


def validate(name: str, args: dict, readers: Readers | None = None) -> dict:
    gate = GATES.get(name)
    if gate is None:
        raise GateError(f"{name or '(none)'} is not a gate; choose one of {', '.join(GATES)}")
    args = args or {}
    known = {a.key for a in gate.args}
    for key in args:
        if key not in known:
            raise GateError(f"{name} has no argument {key}")
    cleaned: dict[str, str] = {}
    for arg in gate.args:
        raw = args.get(arg.key, arg.default)
        value = str(raw if raw is not None else "").strip()
        if not value:
            raise GateError(f"{arg.label} is needed")
        if arg.kind == "text":
            if len(value) > MAX_TEXT or re.search(r"[\x00-\x1f\x7f]", value):
                raise GateError(f"{arg.label} must be plain text of at most {MAX_TEXT} characters")
        elif arg.kind == "minutes":
            if not re.fullmatch(r"\d{1,4}", value) or not 1 <= int(value) <= MAX_MINUTES:
                raise GateError(f"{arg.label} must be a whole number from 1 to {MAX_MINUTES}")
            value = str(int(value))
        elif arg.kind == "repo":
            if not re.fullmatch(r"[^\s:]+", value):
                raise GateError(f"{arg.label} cannot contain spaces or colons")
            if readers is not None and value not in readers.repos():
                raise GateError(f"{value} is not a repository whyline knows")
        elif arg.kind == "path":
            path = _home_path(value)
            if not path.exists():
                raise GateError(f"{value} does not exist")
            value = str(path)
        cleaned[arg.key] = value
    return cleaned


def check(
    name: str,
    args: dict,
    state: dict,
    *,
    now: datetime,
    run=subprocess.run,
    readers: Readers | None = None,
) -> Found:
    readers = readers or Readers()
    cleaned = validate(name, args, readers if name == "ci-failed" else None)
    new_state = dict(state or {})
    seen = [str(k) for k in new_state.get("seen", [])]
    seen_set = set(seen)
    items: list[Item] = []
    for item in GATES[name].run(cleaned, new_state, now, run, readers):
        if item.key in seen_set:
            continue
        seen_set.add(item.key)
        seen.append(item.key)
        items.append(item)
    new_state["seen"] = seen[-MAX_SEEN:]
    return Found(items, new_state)


def write(found: Found, run_dir: Path) -> int:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = [" ".join(i.line.split())[:MAX_LINE] for i in found.items]
    (run_dir / "found.md").write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return len(lines)
