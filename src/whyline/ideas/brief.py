"""The morning brief: today's calendar as a Markdown file.

`calendar` is the one function both `whyline idea brief calendar` and the
console call. It runs a JXA script through osascript, so macOS asks for
Calendar access the first time it runs with the user present.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from whyline.ideas import paths

CALENDARS_KEY = "brief_calendars"
TIMEOUT_SECONDS = 30
OSASCRIPT = "/usr/bin/osascript"
SCRIPT = Path(__file__).with_name("calendar_today.js")
DAY_START = time(8, 0)
DAY_END = time(19, 0)
MIN_FREE = timedelta(minutes=30)

DENIED_HELP = (
    "Calendar access is denied. Open System Settings > Privacy & Security > "
    "Calendars, allow the app that runs whyline (Terminal, or your editor), "
    "then try again."
)


class CalendarError(Exception):
    """The calendar could not be read."""


class AccessDenied(CalendarError):
    """macOS refused Calendar access."""

    def __init__(self) -> None:
        super().__init__(DENIED_HELP)


@dataclass(frozen=True)
class Event:
    title: str
    start: datetime
    end: datetime
    location: str
    all_day: bool
    calendar: str


@dataclass(frozen=True)
class Brief:
    path: Path
    text: str
    calendars: tuple[str, ...]  # every calendar the Mac has, for the picker


def default_dir() -> Path:
    return paths.home() / "brief"


def selected(conn: sqlite3.Connection) -> list[str]:
    """Chosen calendar names. Empty means all calendars."""
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (CALENDARS_KEY,)).fetchone()
    if row is None or not row[0]:
        return []
    try:
        names = json.loads(row[0])
    except ValueError:
        return []
    if not isinstance(names, list):
        return []
    return [name for name in names if isinstance(name, str) and name]


def select(conn: sqlite3.Connection, names: list[str]) -> None:
    value = json.dumps(names) if names else ""
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (CALENDARS_KEY, value),
    )


def calendar(out_dir: Path, *, calendars: list[str], run=subprocess.run) -> Brief:
    """Write ``today.md`` in ``out_dir`` and return what was written.

    ``calendars`` empty means all calendars. Raises ``AccessDenied`` when
    macOS refuses, and ``CalendarError`` for any other failure.
    """
    day, available, events = _fetch(calendars, run)
    text = render(day, events)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "today.md"
    path.write_text(text, encoding="utf-8")
    return Brief(path, text, tuple(available))


def _fetch(calendars: list[str], run) -> tuple[date, list[str], list[Event]]:
    command = [OSASCRIPT, "-l", "JavaScript", str(SCRIPT), json.dumps(calendars)]
    try:
        done = run(command, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise CalendarError(
            f"The calendar did not answer within {TIMEOUT_SECONDS} seconds. "
            "If a permission prompt is waiting, answer it and try again."
        ) from None
    except OSError as exc:
        raise CalendarError(f"Could not run osascript: {exc}") from exc
    output = (done.stdout or "").strip() or (done.stderr or "").strip()
    try:
        data = json.loads(output)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        detail = " ".join((done.stderr or output).split())[:300]
        raise CalendarError(f"The calendar script failed: {detail or 'no output'}")
    if data.get("status") == "denied":
        raise AccessDenied()
    if done.returncode != 0 or data.get("status") != "ok":
        raise CalendarError("The calendar script failed: unexpected answer")
    try:
        day = date.fromisoformat(data["date"])
        available = [str(name) for name in data.get("calendars", [])]
        events = [_event(item) for item in data.get("events", [])]
    except (KeyError, TypeError, ValueError) as exc:
        raise CalendarError(f"The calendar script gave unreadable data: {exc}") from exc
    if calendars:
        events = [e for e in events if e.calendar in calendars]
    return day, available, events


def _event(item: dict) -> Event:
    return Event(
        title=" ".join(str(item.get("title", "")).split()) or "(no title)",
        start=datetime.fromisoformat(item["start"]),
        end=datetime.fromisoformat(item["end"]),
        location=" ".join(str(item.get("location", "")).split()),
        all_day=bool(item.get("allDay")),
        calendar=" ".join(str(item.get("calendar", "")).split()),
    )


def render(day: date, events: list[Event]) -> str:
    all_day = sorted((e for e in events if e.all_day), key=lambda e: e.title)
    timed = sorted((e for e in events if not e.all_day), key=lambda e: (e.start, e.end))
    lines = [f"# Today, {day.isoformat()}", "", "## Events", ""]
    if not events:
        lines.append("No events.")
    lines += [f"- All day: {_describe(e)}" for e in all_day]
    lines += [f"- {_clock(e.start)}-{_clock(e.end)} {_describe(e)}" for e in timed]
    lines += [
        "",
        f"## Free blocks ({_clock(DAY_START)}-{_clock(DAY_END)}, 30 minutes or more)",
        "",
    ]
    free = _free_blocks(day, timed)
    lines += [f"- {_clock(a)}-{_clock(b)} ({_length(b - a)})" for a, b in free] or ["None."]
    lines += ["", "## Clashes", ""]
    clashes = _clashes(timed)
    lines += [
        f"- {a.title} ({_clock(a.start)}-{_clock(a.end)}) overlaps "
        f"{b.title} ({_clock(b.start)}-{_clock(b.end)})"
        for a, b in clashes
    ] or ["None."]
    return "\n".join(lines) + "\n"


def _describe(event: Event) -> str:
    text = event.title
    if event.location:
        text += f" @ {event.location}"
    if event.calendar:
        text += f" ({event.calendar})"
    return text


def _clock(value: datetime | time) -> str:
    return value.strftime("%H:%M")


def _length(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours}h {rest}m"
    return f"{hours}h" if hours else f"{rest}m"


def _free_blocks(day: date, timed: list[Event]) -> list[tuple[datetime, datetime]]:
    start = datetime.combine(day, DAY_START)
    end = datetime.combine(day, DAY_END)
    blocks = []
    cursor = start
    for event in timed:  # sorted by start
        if event.start > cursor and event.start - cursor >= MIN_FREE:
            blocks.append((cursor, min(event.start, end)))
        cursor = max(cursor, event.end)
        if cursor >= end:
            break
    if end - cursor >= MIN_FREE:
        blocks.append((cursor, end))
    return [(a, b) for a, b in blocks if b - a >= MIN_FREE]


def _clashes(timed: list[Event]) -> list[tuple[Event, Event]]:
    found = []
    for i, first in enumerate(timed):
        for second in timed[i + 1 :]:  # sorted by start, so only the start matters
            if second.start < first.end:
                found.append((first, second))
    return found


MAILBOXES_KEY = "brief_mailboxes"
BODY_LINES = 40
FIELD = "\x1f"
RECORD = "\x1e"

MAIL_SCRIPT = """
on run argv
	set hoursBack to (item 1 of argv) as integer
	set maxCount to (item 2 of argv) as integer
	set wanted to {}
	if (count of argv) > 2 then set wanted to items 3 thru -1 of argv
	if application "Mail" is not running then return "not-running"
	set fs to character id 31
	set rs to character id 30
	set cutoff to (current date) - (hoursBack * hours)
	set out to "ok" & rs
	tell application "Mail"
		set names to {}
		repeat with mb in mailboxes
			set end of names to (name of mb)
		end repeat
		set AppleScript's text item delimiters to fs
		set out to out & (names as text) & rs
		set AppleScript's text item delimiters to ""
		set total to 0
		repeat with mb in mailboxes
			if wanted contains (name of mb) then
				set found to (messages of mb whose (read status is false or flagged status is true) and date received > cutoff)
				repeat with m in found
					if total >= maxCount then exit repeat
					set when to (date received of m) as «class isot» as string
					set out to out & (sender of m) & fs & (subject of m) & fs & when & fs & (content of m) & rs
					set total to total + 1
				end repeat
			end if
		end repeat
	end tell
	return out
end run
"""

REMINDERS_SCRIPT = """
on run argv
	set fs to character id 31
	set rs to character id 30
	set endOfDay to (current date)
	set time of endOfDay to 86399
	set out to "ok" & rs
	tell application "Reminders"
		repeat with r in (reminders whose completed is false and due date is not missing value and due date <= endOfDay)
			set when to (due date of r) as «class isot» as string
			set out to out & (name of r) & fs & when & fs & (name of container of r) & rs
		end repeat
	end tell
	return out
end run
"""


class Message:
    """One mail message as read from Mail.app."""

    __slots__ = ("sender", "subject", "received", "body")

    def __init__(self, sender: str, subject: str, received: datetime, body: str) -> None:
        self.sender = sender
        self.subject = subject
        self.received = received
        self.body = body


def _app_denied(app: str, where: str) -> AccessDenied:
    err = AccessDenied()
    err.args = (
        f"{app} access is denied. Open System Settings > Privacy & Security > "
        f"{where}, allow the app that runs whyline (Terminal, or your editor), "
        "then try again.",
    )
    return err


def _osascript(app: str, where: str, source: str, args: list[str], run) -> str:
    command = [OSASCRIPT, "-e", source, *args]
    try:
        done = run(command, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise CalendarError(
            f"{app} did not answer within {TIMEOUT_SECONDS} seconds. "
            "If a permission prompt is waiting, answer it and try again."
        ) from None
    except OSError as exc:
        raise CalendarError(f"Could not run osascript: {exc}") from exc
    stderr = done.stderr or ""
    if done.returncode != 0:
        if "-1743" in stderr or "not authorized" in stderr.lower():
            raise _app_denied(app, where)
        detail = " ".join(stderr.split())[:300]
        raise CalendarError(f"The {app} script failed: {detail or 'no output'}")
    return (done.stdout or "").strip("\n")


def mailboxes_selected(conn: sqlite3.Connection) -> list[str]:
    """Chosen mailbox names. Empty means none: no mail is read."""
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (MAILBOXES_KEY,)).fetchone()
    if row is None or not row[0]:
        return []
    try:
        names = json.loads(row[0])
    except ValueError:
        return []
    if not isinstance(names, list):
        return []
    return [name for name in names if isinstance(name, str) and name]


def select_mailboxes(conn: sqlite3.Connection, names: list[str]) -> None:
    value = json.dumps(names) if names else ""
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (MAILBOXES_KEY, value),
    )


def mail(
    out_dir: Path,
    *,
    mailboxes: list[str],
    hours: int = 24,
    limit: int = 40,
    run=subprocess.run,
    now: datetime | None = None,
) -> Brief:
    """Write ``mail.md`` in ``out_dir``: unread and flagged mail from ``mailboxes``.

    Mailboxes not in ``mailboxes`` are never asked for their messages. When
    Mail is not running, the file says so and Mail is not launched.
    """
    out_dir = Path(out_dir)
    available: list[str] = []
    # With no mailboxes chosen the script still lists names for the picker,
    # but reads no messages.
    answer = _osascript(
        "Mail", "Automation > Mail", MAIL_SCRIPT, [str(hours), str(limit), *mailboxes], run
    )
    if answer.strip() == "not-running":
        text = "# Mail\n\nMail is not running, so no mail was read.\n"
    else:
        available, messages = _parse_mail(answer)
        if not mailboxes:
            text = "# Mail\n\nNo mailboxes are chosen, so no mail was read.\n"
        else:
            moment = now or datetime.now()
            cutoff = moment - timedelta(hours=hours)
            messages = [m for m in messages if m.received >= cutoff]
            messages.sort(key=lambda m: m.received, reverse=True)
            text = _render_mail(messages[:limit])
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "mail.md"
    path.write_text(text, encoding="utf-8")
    return Brief(path, text, tuple(available))


def _parse_mail(answer: str) -> tuple[list[str], list[Message]]:
    records = answer.split(RECORD)
    if not records or records[0] != "ok":
        raise CalendarError("The Mail script failed: unexpected answer")
    available = [n for n in (records[1].split(FIELD) if len(records) > 1 else []) if n]
    messages: list[Message] = []
    for record in records[2:]:
        if not record.strip():
            continue
        parts = record.split(FIELD, 3)
        if len(parts) != 4:
            continue
        try:
            received = datetime.fromisoformat(parts[2])
        except ValueError:
            continue
        messages.append(Message(parts[0], parts[1], received, parts[3]))
    return available, messages


def _render_mail(messages: list[Message]) -> str:
    from whyline.ideas import guard

    if not messages:
        return "# Mail\n\nNo unread or flagged mail.\n"
    lines = ["# Mail", ""]
    for m in messages:
        body = "\n".join(m.body.splitlines()[:BODY_LINES])
        body, _ = guard.clean(body)
        sender, _ = guard.clean(m.sender)
        subject, _ = guard.clean(m.subject)
        lines.append(f"## {subject or '(no subject)'}")
        lines.append(f"From: {sender}")
        lines.append(f"Date: {m.received.strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        lines.append(body or "(no body)")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def reminders(out_dir: Path, *, run=subprocess.run, now: datetime | None = None) -> Brief:
    """Write ``tasks.md`` in ``out_dir``: Reminders.app items due, whyline's, memory."""
    from whyline.ideas import guard, memory, store
    from whyline.ideas import reminders as ledger

    answer = _osascript(
        "Reminders", "Automation > Reminders", REMINDERS_SCRIPT, [], run
    )
    records = answer.split(RECORD)
    if not records or records[0] != "ok":
        raise CalendarError("The Reminders script failed: unexpected answer")
    items: list[tuple[str, str, str]] = []
    for record in records[1:]:
        parts = record.split(FIELD)
        if len(parts) == 3:
            title, _ = guard.clean(parts[0])
            items.append((title or "(no title)", parts[1], " ".join(parts[2].split())))
    items.sort(key=lambda item: item[1])

    today = (now or datetime.now()).date()
    own: list[str] = []
    status = "whyline: nothing to report"
    try:
        conn = store.connect()
    except (sqlite3.Error, OSError):
        conn = None
    if conn is not None:
        try:
            for r in ledger.pending(conn):
                if r.due_at[:10] <= today.isoformat():
                    own.append(f"- {r.due_at.replace('T', ' ')[:16]} {r.text}")
            status = _status_line(conn)
        finally:
            conn.close()

    lines = ["# Tasks", "", "## Reminders (due today or overdue)", ""]
    lines += [f"- {t} ({d.replace('T', ' ')[:16]}, {c})" for t, d, c in items] or ["- none"]
    lines += ["", "## whyline reminders due today", ""]
    lines += own or ["- none"]
    notes = memory.for_prompt()
    if notes:
        lines += ["", "## Memory", "", notes]
    lines += ["", "## Status", "", status]
    text = "\n".join(lines) + "\n"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "tasks.md"
    path.write_text(text, encoding="utf-8")
    return Brief(path, text, ())


_OK_OUTCOMES = ("", "succeeded", "succeeded_with_denials")


def _failed_agents() -> list[str]:
    """Names of saved agents whose latest recorded run did not succeed."""
    from whyline.agents import service

    try:
        found = service.rows(None)
    except Exception:  # the agents store is optional here; never block the brief
        return []
    names: list[str] = []
    for item in found:
        if item.last_outcome in _OK_OUTCOMES:
            continue
        name = getattr(item.defn, "name", None) or getattr(
            getattr(item.defn, "path", None), "stem", "unknown"
        )
        names.append(name)
    return names


AGENT_NAME = "morning-brief"
TIMEOUT_MINUTES = 15

INSTRUCTIONS = """You write my morning brief.
Today's files are in the working folder: today.md (calendar), mail.md (unread
and flagged mail) and tasks.md (reminders, whyline reminders, memory and
status). Use only what those files say.

Write these sections, in this order:
1. Today's schedule: every event in time order.
2. The top 3 priorities for today.
3. Emails that need a reply. For each, give who it is from, what it asks, and
   a suggested reply as text I can copy.
4. Clashes and preparation needed: overlapping events, and anything I should
   prepare before an event.
5. End with one fenced block tagged brief-actions that lists at most 5
   suggested reminders, one per line, as `remind <when> <text>`.

Never act: do not send, reply, accept, create or change anything.
Never invent events, emails or people that are not in the files.
If a file says it has nothing, say so plainly.
"""

SEND_WARNING = (
    "Each brief sends your calendar and email excerpts to the chosen provider "
    "and through Telegram."
)


class SetupError(ValueError):
    """The morning brief agent could not be set up."""


def eligible_providers() -> list[str]:
    """Providers that are enabled in Settings and cleared to run unattended."""
    from whyline import account
    from whyline.agents import capabilities
    from whyline.agents import definitions as d

    enabled = account.enabled_agents()
    return [c for c in d.CLIS if c in enabled and capabilities.can_run_unattended(c)]


def current():
    """The saved personal morning-brief agent, or None."""
    from whyline.agents import definitions as d

    for item in d.discover(None):
        if isinstance(item, d.AgentDef) and item.kind == "personal" and item.name == AGENT_NAME:
            return item
    return None


def current_chat() -> int | None:
    """The Telegram chat the saved morning-brief agent delivers to, or None."""
    from whyline.agents import deliveries

    agent = current()
    if agent is None:
        return None
    sent = deliveries.get(agent.agent_id)
    return (sent.telegram_chat or None) if sent else None


def setup(*, at: str = "07:00", runner: str, backup=(), chat_id: int):
    """Create or update the personal `morning-brief` agent and accept it.

    `whyline idea brief setup` and the console both call this. It rewrites the
    same file each time, so the agent is never duplicated.
    """
    from dataclasses import replace

    from whyline.agents import deliveries, service, telegram
    from whyline.agents import definitions as d
    from whyline.agents import paths as agent_paths
    from whyline.ideas import store, telegram_in

    backup = tuple(backup)
    ok = eligible_providers()
    for cli in (runner, *backup):
        if cli not in ok:
            raise SetupError(
                f"{cli} is not enabled in Settings and cleared for unattended runs; "
                f"choose one of: {', '.join(ok) or 'none available'}"
            )
    conn = store.connect()
    try:
        allowed = telegram_in.allowed_chats(conn)
    finally:
        conn.close()
    if chat_id not in allowed:
        raise SetupError(f"Telegram chat {chat_id} is not an allowed inbox chat")
    path = agent_paths.home() / f"{AGENT_NAME}.toml"
    defn = d.AgentDef(
        name=AGENT_NAME, kind="personal", path=path, root=default_dir(),
        instructions=INSTRUCTIONS, runner=runner, backup=backup,
        workdir=str(default_dir()), timeout_minutes=TIMEOUT_MINUTES,
        before="brief-collect", trigger=d.Trigger(kind="weekdays", at=at),
    )
    try:
        defn = d.parse(d.render(defn), kind="personal", path=path)
    except d.DefinitionError as exc:
        raise SetupError(str(exc)) from exc
    service.save_new(defn)
    service.accept(AGENT_NAME, None)
    delivery = replace(
        deliveries.get(defn.agent_id) or deliveries.Delivery(),
        telegram_chat=chat_id,
        telegram_label=telegram.known_chats().get(chat_id, ""),
        attach="md",
    )
    deliveries.save(defn.agent_id, delivery)
    return defn


MAX_SUGGESTIONS = 5
_ACTIONS_BLOCK = re.compile(r"^```[ \t]*brief-actions[ \t]*\n(.*?)^```[ \t]*$\n?", re.S | re.M)


def split_actions(text: str) -> tuple[str, list[str]]:
    """Return ``text`` without its brief-actions blocks, and the lines they held."""
    lines: list[str] = []

    def take(match: re.Match) -> str:
        lines.extend(line.strip() for line in match.group(1).splitlines() if line.strip())
        return ""

    return _ACTIONS_BLOCK.sub(take, text).rstrip() + "\n", lines


def after_delivery(record, *, chat_id: int | None = None, now: datetime | None = None) -> dict | None:
    """Turn the brief's suggested reminders into Confirm/Cancel cards.

    Only `remind <when> <text>` lines count, at most 5. Any other line is
    ignored, and no other action can come from brief output. Returns a
    delivery-style result for the run history, or None when there is no block.
    """
    from whyline.agents import records
    from whyline.ideas import actions, bot, reminders, requests, store

    try:
        text = records.read_final(record.run_id)
    except OSError:
        return None
    _, lines = split_actions(text)
    if not lines:
        return None
    moment = now or datetime.now().astimezone().replace(tzinfo=None)
    chat = chat_id if chat_id is not None else current_chat()
    made = ignored = 0
    conn = store.connect()
    try:
        for line in lines:
            head, _, rest = line.partition(" ")
            when = body = ""
            if head == "remind" and made < MAX_SUGGESTIONS and chat is not None:
                try:
                    _, body = reminders.parse_when(rest, moment)
                    when = rest.strip()[: len(rest.strip()) - len(body)].strip() if body else ""
                except reminders.TimeParseError:
                    pass
            if not when or not body:
                ignored += 1
                continue
            try:
                request = requests.create(
                    conn, channel="telegram", actor=None, chat_id=chat, action="remind",
                    args={"when": when, "text": body}, proposed_by="assistant",
                )
            except actions.PolicyError:
                ignored += 1
                continue
            bot.offer_request(conn, request)
            made += 1
    finally:
        conn.close()
    detail = f"{made} reminder card{'s' if made != 1 else ''}"
    if ignored:
        detail += f"; ignored {ignored} other line{'s' if ignored != 1 else ''}"
    return {"to": "brief-actions", "ok": True, "detail": detail}


def _status_line(conn: sqlite3.Connection) -> str:
    parts: list[str] = []
    paused = conn.execute("SELECT COUNT(*) FROM ideas WHERE status = 'paused'").fetchone()[0]
    if paused:
        parts.append(f"{paused} relay run{'s' if paused != 1 else ''} paused")
    failed = _failed_agents()
    if failed:
        parts.append("agents failed last run: " + ", ".join(failed))
    return "whyline: " + ("; ".join(parts) if parts else "nothing to report")
