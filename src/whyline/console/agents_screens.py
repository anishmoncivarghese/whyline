"""Agents mode popups: the list, one agent's detail, its runs, the
new-agent form with its review, and the idea inbox."""
from __future__ import annotations

import json
import re
import webbrowser
from datetime import datetime
from types import SimpleNamespace
from dataclasses import dataclass, replace
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, HorizontalGroup, Vertical, VerticalGroup, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Collapsible, DataTable, Input, Label, Select, Static, TextArea

from whyline.agents import capabilities, definitions as d, deliveries as dl, paths, records, templates
from whyline.agents import schedule, service
from whyline.agents.service import NO_AGENTS


@dataclass(frozen=True)
class AgentForm:
    defn: d.AgentDef
    delivery: dl.Delivery

# The schedule save NewAgentScreen holds for Review's Save: (the defn it was made for, the call).
_pending_schedule: tuple | None = None

_CSS = """
{name} {{ align: center middle; }}
{name} > Vertical {{ width: 110; max-width: 100%; height: auto; max-height: 90%;
    padding: 0 2; border: thick $accent; background: $surface; }}
{name} Horizontal {{ height: auto; margin-top: 1; }}
{name} Button {{ margin-right: 1; }}
"""


def _row_key(table: DataTable) -> str | None:
    if table.row_count == 0:
        return None
    coordinate = (table.cursor_row, 0)
    if not table.is_valid_coordinate(coordinate):
        return None
    return table.coordinate_to_cell_key(coordinate).row_key.value


class AgentsListScreen(ModalScreen):
    DEFAULT_CSS = _CSS.format(name="AgentsListScreen") + "AgentsListScreen DataTable { height: auto; max-height: 20; }"

    def __init__(self, rows) -> None:
        super().__init__()
        self._rows = rows

    @staticmethod
    def _label(defn) -> str:
        if defn.kind == "repo":
            return f"{defn.name} · this repository only"
        return defn.name

    @staticmethod
    def _status_text(row) -> str:
        if row.status == "finished":
            return f"finished: {row.reason}" if row.reason else "finished"
        return row.status

    def compose(self) -> ComposeResult:
        body: list = [Label("Agents" if self._rows else NO_AGENTS)]
        if self._rows:
            body.append(Label("Open an agent to run, edit or delete it.", id="al-hint"))
        if self._rows:
            table = DataTable(id="al-table", cursor_type="row")
            table.add_columns("Agent", "CLI", "When", "Next", "Last", "Status", "Check-in")
            for row in self._rows:
                if isinstance(row.defn, d.Broken):
                    table.add_row(
                        f"{row.defn.path.name} (broken)", "", row.when, "", "", "needs review", "",
                        key=f"broken:{row.defn.path.name}",
                    )
                    continue
                cli = row.defn.runner + (f" → {', '.join(row.defn.backup)}" if row.defn.backup else "")
                table.add_row(
                    self._label(row.defn), cli, row.when, row.next_due or "—",
                    row.last_outcome or "—", self._status_text(row),
                    (_watch_line(row) if getattr(row.defn, "watch", None) is not None
                     else service.checkin_line(row.defn)) or "—",
                    key=f"{row.defn.kind}:{row.defn.name}",
                )
            body.append(table)
        body.append(Static("", id="al-broken", markup=False))
        body.append(Static("", id="al-result", markup=False))
        body.append(
            Horizontal(
                Button("Open", id="al-open", variant="primary"),
                Button("Start again", id="al-start-again"),
                Button("Delete file…", id="al-delete-broken", variant="error"),
                Button("Close", id="al-close"),
            ),
        )
        yield Vertical(*body)

    def on_mount(self) -> None:
        self.query_one("#al-broken", Static).display = False
        self.query_one("#al-delete-broken", Button).display = False
        self.query_one("#al-result", Static).display = False
        self._sync_start_again()

    def _finished_row(self):
        key = self._chosen()
        for row in self._rows:
            if (not isinstance(row.defn, d.Broken) and row.status == "finished"
                    and key == f"{row.defn.kind}:{row.defn.name}"):
                return row
        return None

    def _sync_start_again(self) -> None:
        self.query_one("#al-start-again", Button).display = self._finished_row() is not None

    def on_data_table_row_highlighted(self, event) -> None:
        self._sync_start_again()

    def _start_again(self) -> None:
        row = self._finished_row()
        if row is None:
            return
        result = self.query_one("#al-result", Static)
        root = getattr(getattr(self.app, "session", None), "root", None)
        try:
            service.start_again(f"{row.defn.kind}:{row.defn.name}", root)
        except ValueError as error:
            result.update(str(error))
            result.display = True
            return
        row.status = "active"
        row.reason = ""
        table = self.query_one("#al-table", DataTable)
        table.update_cell_at((table.cursor_row, 5), "active")
        result.update(f"{row.defn.name} will run again.")
        result.display = True
        self._sync_start_again()

    def _key(self) -> str | None:
        if not self._rows:
            return None
        return _row_key(self.query_one("#al-table", DataTable))

    def _broken(self, key: str | None):
        if not key or not key.startswith("broken:"):
            return None
        name = key.removeprefix("broken:")
        for row in self._rows:
            if isinstance(row.defn, d.Broken) and row.defn.path.name == name:
                return row.defn
        return None

    def _chosen(self) -> str | None:
        key = self._key()
        return None if key is None or key.startswith("broken:") else key

    def _open(self) -> None:
        broken = self._broken(self._key())
        if broken is None:
            self.dismiss(self._chosen())
            return
        # A file that isn't a valid agent can't be opened; say why, and offer
        # to remove it (whyline asks before deleting anything).
        self._broken_path = broken.path
        notice = self.query_one("#al-broken", Static)
        notice.update(f"{broken.path.name} isn't a valid agent: {broken.error}. "
                      f"File: {_tilde(broken.path)}. Fix the file, or delete it.")
        notice.display = True
        self.query_one("#al-delete-broken", Button).display = True

    def on_data_table_row_selected(self, event) -> None:
        self._open()

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "al-open":
            self._open()
        elif event.button.id == "al-start-again":
            self._start_again()
        elif event.button.id == "al-delete-broken":
            if getattr(self, "_broken_path", None):
                self.dismiss(f"delete-file:{self._broken_path}")
        elif event.button.id == "al-close":
            self.dismiss(None)


def _mail_rule_text(name: str, path) -> str:
    shown = path.as_posix() if hasattr(path, "as_posix") else str(path)
    return (
        f"Wrote {shown}\n"
        "In Mail → Settings → Rules → Add Rule, set the conditions "
        "(From is the allowed sender), then Run AppleScript → "
        f"choose whyline-{name}.applescript."
    )


def _mail_trigger(defn) -> str | None:
    kind = getattr(getattr(defn, "trigger", None), "kind", None)
    return kind if kind in ("manual", "folder") else None


class AgentDetailScreen(ModalScreen):
    DEFAULT_CSS = _CSS.format(name="AgentDetailScreen") + """
    AgentDetailScreen #ad-mail-result { height: auto; }
    """

    def __init__(self, row, describe: str, *, install=None) -> None:
        super().__init__()
        self._row, self._describe, self._install = row, describe, install

    def compose(self) -> ComposeResult:
        from whyline.agents import mail

        row = self._row
        status = row.status
        buttons = [Button("Run now", id="ad-run", variant="success"), Button("History", id="ad-history")]
        if status == "needs_review":
            buttons.append(Button("Accept changes", id="ad-accept", variant="warning"))
        elif status in ("paused", "needs_attention"):
            buttons.append(Button("Resume", id="ad-resume"))
        else:
            buttons.append(Button("Pause", id="ad-pause"))
        buttons += [
            Button("Edit", id="ad-edit"),
            Button("Delete", id="ad-delete", variant="error"),
            Button("Close", id="ad-close"),
        ]
        mail_widgets: list = []
        if _mail_trigger(row.defn):
            mail_ok = mail.supported()
            mail_btn = Button("Install Mail rule…", id="ad-mail-script")
            mail_btn.disabled = not mail_ok
            mail_widgets = [
                mail_btn,
                Static(
                    mail.NEEDS_MACOS if not mail_ok else "",
                    id="ad-mail-result",
                    markup=False,
                ),
            ]
        yield Vertical(
            Label(row.defn.label),
            Static(self._describe),
            Static(f"Status: {status} · last: {row.last_outcome or '—'} {row.last_run}"),
            *mail_widgets,
            Horizontal(*buttons),
        )

    def _install_mail(self) -> None:
        from whyline.agents import mail

        if not mail.supported():
            self._show_mail(mail.NEEDS_MACOS)
            return
        name = self._row.defn.name
        fn = self._install or mail.install
        try:
            path = fn(name)
        except (RuntimeError, OSError, ValueError) as error:
            self._show_mail(str(error))
            return
        self._show_mail(_mail_rule_text(name, path))

    def _show_mail(self, text: str) -> None:
        self.query_one("#ad-mail-result", Static).update(text)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "ad-mail-script":
            self._install_mail()
            return
        action = (event.button.id or "").removeprefix("ad-")
        self.dismiss(None if action == "close" else action)


def time_left(asked_at: str, now=None, timeout: int | None = None) -> str:
    """How long an approval still waits before it times out: ``8m 12s left``."""
    from datetime import datetime, timezone

    from whyline.tools import approvals

    timeout = approvals.APPROVAL_TIMEOUT if timeout is None else timeout
    try:
        asked = datetime.fromisoformat(asked_at)
    except ValueError:
        return "time left unknown"
    if asked.tzinfo is None:
        asked = asked.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    left = int(timeout - (now - asked).total_seconds())
    if left <= 0:
        return "timing out"
    return f"{left // 60}m {left % 60:02d}s left"


def waiting_text(pending) -> str:
    """The scheduler line while something waits: ``waiting for you: <agent> wants <tool>``."""
    first = pending[0]
    try:
        record = records.load(first.run_id)
    except Exception:
        record = None
    agent = record.agent_name if record is not None else first.run_id
    more = f" (+{len(pending) - 1} more)" if len(pending) > 1 else ""
    return f"waiting for you: {agent} wants {first.tool}{more}"


def tool_call_lines(run_id: str) -> list[str]:
    """One line per call in the run's ``tool-calls.jsonl``:
    ``12:04 gmail__send_email · approved · 1.2s``."""
    from datetime import datetime

    try:
        text = (records.run_folder(run_id) / "tool-calls.jsonl").read_text(encoding="utf-8")
    except OSError:
        return []
    lines = []
    for raw in text.splitlines():
        try:
            item = json.loads(raw)
            when = datetime.fromisoformat(str(item.get("time", ""))).astimezone().strftime("%H:%M")
        except (ValueError, TypeError, AttributeError):
            continue
        seconds = item.get("duration_s")
        took = f"{seconds:.1f}s" if isinstance(seconds, (int, float)) else "?"
        lines.append(f"{when} {item.get('tool', '?')} · {item.get('decision') or 'ok'} · {took}")
    return lines


class ApprovalsScreen(ModalScreen):
    """Calls an agent is waiting to make, each with Approve and Deny. Both call
    ``approvals.answer``, the function ``whyline approvals`` calls."""

    DEFAULT_CSS = _CSS.format(name="ApprovalsScreen") + "ApprovalsScreen VerticalScroll { height: 8; }"

    def __init__(self) -> None:
        super().__init__()
        self._items: list = []

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Approvals: calls waiting for your yes"),
            DataTable(id="ap-table", cursor_type="row"),
            VerticalScroll(Static("", id="ap-text", markup=False)),
            Horizontal(
                Button("Approve", id="ap-approve", variant="success"),
                Button("Deny", id="ap-deny", variant="warning"),
                Button("Close", id="ap-close"),
            ),
        )

    def on_mount(self) -> None:
        table = self.query_one("#ap-table", DataTable)
        table.add_columns("Agent", "Tool", "Arguments", "Time left")
        self._reload()
        self.set_interval(2.0, self._reload)

    def _reload(self, say: bool = True) -> None:
        from whyline.tools import approvals

        table = self.query_one("#ap-table", DataTable)
        key = _row_key(table)
        try:
            self._items = approvals.pending()
        except Exception:
            self._items = []
        table.clear()
        for item in self._items:
            try:
                record = records.load(item.run_id)
            except Exception:
                record = None
            agent = record.agent_name if record is not None else item.run_id
            table.add_row(agent, item.tool, item.arguments[:40], time_left(item.asked_at),
                          key=f"{item.run_id}/{item.n}")
        if key is not None:
            try:
                table.move_cursor(row=table.get_row_index(key))
            except Exception:
                pass
        if say:
            self._say("" if self._items else "Nothing is waiting.")

    def _say(self, text: str) -> None:
        try:
            self.query_one("#ap-text", Static).update(text)
        except NoMatches:
            return

    def _answer(self, approve: bool) -> None:
        from whyline.tools import approvals

        key = _row_key(self.query_one("#ap-table", DataTable))
        if not key:
            return
        run_id, _, n = key.rpartition("/")
        try:
            approvals.answer(run_id, int(n), approve)
        except approvals.ApprovalError as error:
            self._say(str(error))
        else:
            self._say("Approved." if approve else "Denied.")
        self._reload(say=False)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "ap-approve":
            self._answer(True)
        elif event.button.id == "ap-deny":
            self._answer(False)
        else:
            self.dismiss(None)


class RunsScreen(ModalScreen):
    DEFAULT_CSS = _CSS.format(name="RunsScreen") + "RunsScreen VerticalScroll { height: 20; }"

    def __init__(self, label: str, runs, on_resend=None) -> None:
        super().__init__()
        self._label, self._runs, self._on_resend = label, runs, on_resend

    def compose(self) -> ComposeResult:
        from whyline.agents import deliver

        table = DataTable(id="rs-runs", cursor_type="row")
        self._columns = table.add_columns("When", "Trigger", "CLI", "Outcome", "Delivered")
        for run in self._runs:
            cli = run.cli + (" (backup)" if run.used_backup else "")
            table.add_row(run.started[:16].replace("T", " "), run.source, cli, run.outcome,
                          deliver.status_text(run), key=run.run_id)
        buttons = [Button("Show log", id="rs-log")]
        if self._on_resend is not None:
            buttons.append(Button("Resend", id="rs-resend"))
        buttons.append(Button("Close", id="rs-close"))
        yield Vertical(
            Label(f"Runs of {self._label}" if self._runs else f"{self._label} has not run yet."),
            table,
            VerticalScroll(Static("", id="rs-text", markup=False)),
            Horizontal(*buttons),
        )

    def _selected(self) -> str | None:
        if not self._runs:
            return None
        return _row_key(self.query_one("#rs-runs", DataTable))

    def _show(self, text: str) -> None:
        try:
            self.query_one("#rs-text", Static).update(text)
        except NoMatches:
            return

    def resend_done(self, run_id: str, text: str, status: str) -> None:
        """Called on the app thread when a resend finishes: show the result
        here and refresh that run's Delivered cell."""
        self._show(f"Resent: {text}")
        try:
            self.query_one("#rs-runs", DataTable).update_cell(run_id, self._columns[-1], status)
        except Exception:
            pass  # the row or screen is gone; the transcript still has the result

    def on_data_table_row_highlighted(self, event) -> None:
        run_id = self._selected()
        if not run_id:
            return
        try:
            text = records.read_final(run_id) or "(no answer)"
        except OSError:
            text = "(no answer)"
        calls = tool_call_lines(run_id)
        if calls:
            text += "\n\nTool calls:\n" + "\n".join(calls)
        self._show(text)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "rs-resend":
            run_id = self._selected()
            if run_id and self._on_resend is not None:
                self._show("Resending…")
                # A fast delivery can report back immediately.  Put the
                # progress state on screen before starting it so the stale
                # text cannot overwrite the completed result.
                self._on_resend(run_id)
            return
        if event.button.id == "rs-log":
            run_id = self._selected()
            if run_id:
                try:
                    text = records.read_log(run_id) or "(no log)"
                except OSError:
                    text = "(no log)"
                self._show(text)
            return
        self.dismiss(None)


def _chat_options(chats: dict[int, str]) -> list[tuple[str, int]]:
    """The agent form's Telegram list. With no chats yet, the empty choice
    says why, since whyline only lists chats the bot has had a message in."""
    none = "None" if chats else "None (no chats yet; use Set up Telegram…)"
    return [(none, 0)] + [(label, cid) for cid, label in chats.items()]


class TelegramSetupScreen(ModalScreen):
    """One-time Telegram set-up (deliveries spec 9). Dismisses with the
    chats known afterwards. Network calls run in worker threads; their
    results are dropped once the screen has closed."""

    DEFAULT_CSS = _CSS.format(name="TelegramSetupScreen") + """
    TelegramSetupScreen Static { height: auto; }
    TelegramSetupScreen Input { width: 1fr; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._token: str | None = None
        self._bot = ""
        self._poller = None
        self._closed = False

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Set up Telegram (once per Mac)"),
            Static("1. In Telegram, open @BotFather, send /newbot, choose a name, copy the token. "
                   "No Telegram app on this Mac? Use your phone, or web.telegram.org/k/#@BotFather.",
                   markup=False),
            Horizontal(Button("Open BotFather", id="tg-open"),
                       Button("Open my bot", id="tg-open-bot")),
            Horizontal(Input(placeholder="2. Paste the bot token", password=True, id="tg-token"),
                       Button("Check", id="tg-check")),
            Static("", id="tg-bot", markup=False),
            Static("3. Send any message to your bot, or add it to a group and send a message there.",
                   markup=False),
            Static("", id="tg-chats", markup=False),
            Horizontal(Select([], prompt="Chat to test", id="tg-chat"),
                       Button("Send test message", id="tg-test"),
                       Button("Done", id="tg-done", variant="primary")),
        )

    def on_mount(self) -> None:
        from whyline.agents import telegram

        self.query_one("#tg-open-bot", Button).display = False
        self._token = telegram.token_get()
        if self._token:
            self.query_one("#tg-bot", Static).update(
                "A bot is already set up on this Mac. Paste a new token only to replace it.")
            self._name_bot(self._token)
            self._start_polling()
        self._show_chats(telegram.known_chats())

    def on_unmount(self) -> None:
        self._closed = True
        if self._poller is not None:
            self._poller.stop()

    # Worker threads report back through here, on the app's thread. A late
    # result for a closed screen is dropped instead of touching dead widgets.
    def _later(self, app, callback, *args) -> None:
        def apply() -> None:
            if self._closed:
                return
            try:
                callback(*args)
            except NoMatches:
                pass

        try:
            app.call_from_thread(apply)
        except RuntimeError:
            pass  # the app itself has stopped

    def _status_later(self, app, text: str) -> None:
        """Set the status line from a worker thread. The widget is looked up
        on the app's thread, and only while this screen is still open."""
        self._later(app, lambda: self.query_one("#tg-bot", Static).update(text))

    def _work(self, app, body, token: str | None):
        """Wrap a worker so nothing it raises reaches Textual: an uncaught
        worker error stops the console and its report prints local variables,
        including the bot token."""
        def run() -> None:
            from whyline.agents import telegram

            try:
                body()
            except Exception as error:
                self._status_later(app, telegram.redact(str(error), token) or "Something went wrong.")

        return run

    def _set_bot(self, bot: str, text: str) -> None:
        self._bot = bot
        self.query_one("#tg-bot", Static).update(text)
        self.query_one("#tg-open-bot", Button).display = bool(bot)
        self._show_chats(self._known())

    def _known(self) -> dict[int, str]:
        from whyline.agents import telegram

        return telegram.known_chats()

    def _waiting_text(self) -> str:
        if not self._bot:
            return "Waiting for a message…"
        name = self._bot.lstrip("@")
        return (f"No messages yet. In Telegram, open {self._bot} (https://t.me/{name}) and tap "
                "Start or send hi, or add it to a group and send a message there. "
                "Chats appear here within a few seconds.")

    def _show_chats(self, chats: dict[int, str]) -> None:
        self.query_one("#tg-chats", Static).update(
            "Found: " + ", ".join(chats.values()) if chats else self._waiting_text())
        select = self.query_one("#tg-chat", Select)
        current = select.value
        select.set_options([(label, cid) for cid, label in chats.items()])
        if chats:
            select.value = current if current in chats else next(iter(chats))

    def _name_bot(self, token: str) -> None:
        app = self.app

        def work() -> None:
            from whyline.agents import telegram

            try:
                bot = telegram.check_token(token)
            except Exception as error:
                self._status_later(app,
                            telegram.redact(str(error), token))
                return
            self._later(app, self._set_bot, bot, f"Connected to {bot}.")

        app.run_worker(self._work(app, work, token), thread=True)

    def _start_polling(self) -> None:
        if self._poller is None:
            self._poll()
            self._poller = self.set_interval(3, self._poll)

    def _poll(self) -> None:
        token = self._token
        if not token or self._closed:
            return
        app = self.app

        def work() -> None:
            from whyline.agents import telegram

            try:
                chats = telegram.remember_chats(telegram.find_chats(token))
            except Exception:
                return
            self._later(app, self._show_chats, chats)

        app.run_worker(self._work(app, work, token), thread=True, exclusive=True, group="tg-poll")

    def _check(self) -> None:
        token = self.query_one("#tg-token", Input).value.strip()
        if not token:
            self.query_one("#tg-bot", Static).update("Paste the token BotFather gave you first.")
            return
        self.query_one("#tg-bot", Static).update("Checking…")
        app = self.app

        def work() -> None:
            from whyline.agents import telegram

            try:
                bot = telegram.check_token(token)
                telegram.token_set(token)
            except Exception as error:
                self._status_later(app,
                            telegram.redact(str(error), token))
                return

            def done() -> None:
                self._token = token
                self._set_bot(bot, f"Connected to {bot}. Saved on this Mac.")
                self._start_polling()

            self._later(app, done)

        app.run_worker(self._work(app, work, token), thread=True)

    def _test(self) -> None:
        chat = self.query_one("#tg-chat", Select).value
        token = self._token
        status = self.query_one("#tg-bot", Static)
        if not token:
            status.update("Connect a bot first: paste its token and press Check.")
            return
        if not isinstance(chat, int):
            bot = self._bot or "your bot"
            status.update(f"No chat yet: send a message to {bot} first; it appears here "
                          "within a few seconds.")
            return
        status.update("Sending…")
        app = self.app

        def work() -> None:
            from whyline.agents import telegram

            try:
                telegram.send_message(token, chat, "Test from whyline: Telegram is set up.")
                text = "Test message sent. Check Telegram."
            except Exception as error:
                text = telegram.redact(str(error), token)
            self._status_later(app, text)

        app.run_worker(self._work(app, work, token), thread=True)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        button_id = event.button.id
        if button_id == "tg-open":
            webbrowser.open("https://t.me/BotFather")
        elif button_id == "tg-open-bot" and self._bot:
            webbrowser.open(f"https://t.me/{self._bot.lstrip('@')}")
        elif button_id == "tg-check":
            self._check()
        elif button_id == "tg-test":
            self._test()
        elif button_id == "tg-done":
            self._closed = True
            if self._poller is not None:
                self._poller.stop()
            self.dismiss(self._known())


class IdeaInboxScreen(ModalScreen):
    """``whyline idea telegram setup`` in the console.

    Allowing a chat calls ``telegram_in.allow``. Turning the inbox on calls
    ``worker.turn_on``, the same function ``whyline idea service on`` uses.
    When a private chat is already allowed, or the inbox is already on,
    this screen says so and does not write that setting again.
    """

    DEFAULT_CSS = _CSS.format(name="IdeaInboxScreen") + """
    IdeaInboxScreen Static { height: auto; }
    IdeaInboxScreen Select { width: 1fr; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._token: str | None = None
        self._private: list[tuple[int, str]] = []
        self._allowed_ids: list[int] = []
        self._inbox_on = False
        self._closed = False
        self._generation = 0

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Idea inbox"),
            Static("", id="ib-bot", markup=False),
            Static("", id="ib-empty", markup=False),
            Select([], prompt="Private chat", id="ib-chat"),
            Static("", id="ib-allow-status", markup=False),
            Static("", id="ib-service", markup=False),
            Horizontal(
                Button("Allow", id="ib-allow", disabled=True),
                Button("Turn inbox on", id="ib-on", variant="success", disabled=True),
                Button("Set up Telegram…", id="ib-telegram"),
                Button("Close", id="ib-close"),
            ),
        )

    def on_mount(self) -> None:
        self._refresh()

    def on_unmount(self) -> None:
        self._closed = True

    def _later(self, app, callback, *args) -> None:
        def apply() -> None:
            if self._closed:
                return
            try:
                callback(*args)
            except NoMatches:
                pass

        try:
            app.call_from_thread(apply)
        except RuntimeError:
            pass

    def _guard(self, app, body, token: str | None):
        """An uncaught worker error stops the console and prints locals,
        including the bot token."""
        def run() -> None:
            from whyline.agents import telegram

            try:
                body()
            except Exception as error:
                text = telegram.redact(str(error), token) or "Something went wrong."
                self._later(app, self._show_bot, text)

        return run

    def _show_bot(self, text: str) -> None:
        self.query_one("#ib-bot", Static).update(text)

    def _read_allowed(self) -> list[int]:
        from whyline.ideas import paths, store, telegram_in

        # Opening the screen is not a save. ``store.connect`` creates the
        # database; a check must not.
        if not (paths.configured_home() / "ideas.sqlite3").is_file():
            return []
        conn = store.connect()
        try:
            return telegram_in.allowed_chats(conn)
        finally:
            conn.close()

    def _refresh(self) -> None:
        if self._closed:
            return
        self._generation += 1
        generation = self._generation
        try:
            self._load(generation)
        except Exception as error:
            from whyline.agents import telegram

            self._show_bot(telegram.redact(str(error), self._token) or "Something went wrong.")

    def _load(self, generation: int) -> None:
        from whyline.agents import telegram
        from whyline.ideas import telegram_in, worker

        self._token = telegram.token_get()
        self._private = telegram_in.private_chats(telegram.known_chats())
        self._allowed_ids = self._read_allowed()
        self._inbox_on = worker.enabled()
        # Finding chats is the existing Telegram screen, which polls. This
        # one does not call getUpdates. Offer that screen only when there
        # is nothing private to allow yet.
        self.query_one("#ib-telegram", Button).display = not self._token or (
            not self._private and not self._allowed_ids
        )
        self.query_one("#ib-allow", Button).disabled = True
        self.query_one("#ib-on", Button).disabled = True
        self._show_private()
        self._show_allowed()
        self._show_service()
        if not self._token:
            self._show_bot("No bot token yet. Set up Telegram, then allow a private chat.")
            return
        self._show_bot("Checking the saved bot…")
        self._name_bot(generation, self._token)

    def _show_private(self) -> None:
        empty = self.query_one("#ib-empty", Static)
        select = self.query_one("#ib-chat", Select)
        if not self._private:
            select.display = False
            empty.display = True
            empty.update(
                "No private chats yet. Send a direct message to the bot, "
                "then open Inbox again."
            )
            return
        empty.display = False
        select.display = True
        select.set_options([(f"{label}  ({cid})", cid) for cid, label in self._private])
        select.value = self._private[0][0]

    def _show_allowed(self) -> None:
        status = self.query_one("#ib-allow-status", Static)
        if not self._allowed_ids:
            status.update("")
            return
        labels = {cid: label for cid, label in self._private}
        lines = []
        for cid in self._allowed_ids:
            label = labels.get(cid)
            if label:
                lines.append(f"Already allowed: {label}  ({cid})")
            else:
                lines.append(f"Already allowed: {cid}")
        status.update("\n".join(lines))

    def _show_service(self) -> None:
        text = "Inbox already on." if self._inbox_on else "Inbox off."
        self.query_one("#ib-service", Static).update(text)

    def _name_bot(self, generation: int, token: str) -> None:
        app = self.app

        def work() -> None:
            from whyline.agents import telegram
            from whyline.ideas.cli import _no_wait

            try:
                bot = telegram.check_token(token, sleep=_no_wait)
            except Exception as error:
                text = telegram.redact(str(error), token) or "Something went wrong."
                self._later(app, self._apply_bot, generation, text, False)
                return
            text = telegram.redact(
                f"Bot {bot} is already saved. Keeping it.", token
            )
            self._later(app, self._apply_bot, generation, text, True)

        app.run_worker(self._guard(app, work, token), thread=True)

    def _apply_bot(self, generation: int, text: str, ok: bool) -> None:
        if generation != self._generation:
            return
        self._show_bot(text)
        if not ok:
            return
        self.query_one("#ib-allow", Button).disabled = bool(self._allowed_ids) or not self._private
        self.query_one("#ib-on", Button).disabled = self._inbox_on

    def _allow(self) -> None:
        if self._allowed_ids:
            self._show_allowed()
            return
        chat = self.query_one("#ib-chat", Select).value
        status = self.query_one("#ib-allow-status", Static)
        if not isinstance(chat, int):
            status.update("Choose a private chat.")
            return
        from whyline.agents import telegram
        from whyline.ideas import store, telegram_in

        try:
            conn = store.connect()
            try:
                label = telegram_in.allow(conn, chat)
            finally:
                conn.close()
        except telegram_in.AllowError as exc:
            status.update(telegram.redact(str(exc), self._token))
            return
        except Exception as exc:
            status.update(telegram.redact(str(exc), self._token) or "Something went wrong.")
            return
        self._allowed_ids = [chat]
        self.query_one("#ib-allow", Button).disabled = True
        status.update(f"{label}  ({chat})  allowed")

    def _turn_on(self) -> None:
        if self._inbox_on:
            self._show_service()
            return
        self.query_one("#ib-on", Button).disabled = True
        app = self.app
        token = self._token

        def work() -> None:
            from whyline.ideas import worker

            try:
                worker.turn_on()
            except worker.ServiceError as exc:
                self._later(app, self._service_failed, str(exc))
                return
            self._later(app, self._service_started)

        app.run_worker(self._guard(app, work, token), thread=True)

    def _service_failed(self, text: str) -> None:
        from whyline.agents import telegram

        self.query_one("#ib-service", Static).update(telegram.redact(text, self._token))
        if not self._inbox_on:
            self.query_one("#ib-on", Button).disabled = False

    def _service_started(self) -> None:
        self._inbox_on = True
        self.query_one("#ib-service", Static).update("Inbox on.")
        self.query_one("#ib-on", Button).disabled = True

    def _open_telegram(self) -> None:
        self.app.push_screen(TelegramSetupScreen(), lambda _chats: self._refresh())

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        button_id = event.button.id
        if button_id == "ib-allow":
            self._allow()
        elif button_id == "ib-on":
            self._turn_on()
        elif button_id == "ib-telegram":
            self._open_telegram()
        elif button_id == "ib-close":
            self._closed = True
            self.dismiss(None)


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _tilde(path: Path) -> str:
    """`~/x` when `path` is under the home directory, else a posix path."""
    try:
        resolved = path.expanduser().resolve()
        home = Path.home().resolve()
    except OSError:
        return Path(path).as_posix()
    shown = resolved.as_posix()
    home_s = home.as_posix()
    if shown == home_s:
        return "~"
    prefix = home_s + "/"
    if shown.startswith(prefix):
        return "~/" + shown[len(prefix):]
    return shown


def _first_folder(picked: list[Path]) -> Path | None:
    """The first directory in `picked`.

    `mac_input.pick_files` is `choose file`, so it returns files. The folder
    is then the directory that contains the first file.
    """
    for path in picked:
        if path.is_dir():
            return path
    for path in picked:
        parent = path.parent
        if str(parent) not in ("", ".") and parent.is_dir():
            return parent
    return None


_KIND = (
    ("Personal (this Mac, every repository)", "personal"),
    ("Only in this repository", "repo"),
)
_REPO_SKILL_ORIGINS = ("whyline-repo", "claude-project")
_WHEN = (
    ("Manual", "manual"),
    ("Once", "once"),
    ("Daily", "daily"),
    ("Weekdays", "weekdays"),
    ("Weekly", "weekly"),
    ("Every", "every"),
    ("When a folder changes", "folder"),
)
_EVERY_UNITS = (("minutes", "minutes"), ("hours", "hours"), ("days", "days"))
_UNIT_MINUTES = {"minutes": 1, "hours": 60, "days": 1440}
_EVERY_HELP = "Every N hours starts at midnight: 00:00, 05:00, 10:00, …"
_WATCH_HINT = "Leave this empty and whyline sends the message itself. No agent runs."
_WATCH_RULES = [("the page changes", "changed"), ("this text appears", "appears"),
                ("this text is gone", "gone"), ("let the agent decide", "always")]
_WATCH_DIRECTIONS = [("—", ""), ("below", "below"), ("above", "above")]
_WATCH_SLOW_PAGE = "This page shows almost nothing to a plain fetch. It may need a browser."
_WATCH_URLS = 3
_WATCH_IDS = frozenset(("na-w-on", "na-w-rule", "na-w-dir"))


def _cached_page_state(url: str, cache_dir=None) -> str:
    """The last fetch state whyline cached for an address ('' when unknown), fresh or not."""
    import json
    from pathlib import Path

    from whyline.agents import pagefetch

    directory = cache_dir if cache_dir is not None else Path.home() / ".whyline" / "agents" / "pages"
    try:
        data = json.loads(pagefetch._cache_file(Path(directory), url).read_text(encoding="utf-8"))
        return str(data["page"]["state"])
    except Exception:
        return ""


def watch_last_text(defn, run, gate_state: dict, memory, cache_dir=None) -> str:
    """The last check of a watch: 'no change', 'sent', 'blocked', "couldn't read", the last
    number it read, or 'not yet'."""
    from whyline.agents import pagefetch, watch as watch_rules

    pages = gate_state.get("pages") or {}
    failing = [url for url, page in pages.items() if int(page.get("failures", 0) or 0) > 0]
    if failing:
        if any(_cached_page_state(url, cache_dir) == "blocked" for url in failing):
            return "blocked"
        said = " ".join(((run.reason if run else ""), str((gate_state.get("_out") or {}).get("notice", ""))))
        return "blocked" if any(why in said for why in pagefetch.REASONS.values()) else "couldn't read"
    if defn.watch.value and memory.values:
        return watch_rules._fmt(memory.values[-1][1])
    if run is None and not pages:
        return "not yet"
    if run is not None and any(item.get("ok") and item.get("to") != "held" for item in run.deliveries or []):
        return "sent"
    return "no change"


def _watch_kwargs(watch) -> dict:
    return {"stop": watch.stop, "value": watch.value, "urgent": watch.urgent,
            "daily_cap": watch.daily_cap}


def _watch_line(row) -> str:
    from whyline.agents import state

    defn = row.defn
    conn = state.connect()
    try:
        gate_state = state.get_gate_state(conn, defn.agent_id)
        memory = state.watch_memory(conn, defn.agent_id)
    finally:
        conn.close()
    runs = records.list_runs(defn.agent_id, limit=1)
    last = watch_last_text(defn, runs[0] if runs else None, gate_state, memory)
    return f"next check {row.next_due or '—'} · last check {last}"


def watch_test_text(result) -> str:
    """What Test shows: each address, what whyline read, whether it would fire, the message."""
    lines = []
    for page in result.pages:
        shown = {"ok": "read"}.get(page.state, page.state)
        lines.append(f"{page.address}: {shown}" + (f" ({page.reason})" if page.reason else ""))
        if page.text.strip():
            lines.append(f"Text: {' '.join(page.text.split())[:300]}")
        if page.state == "ok" and len(page.text.strip()) < 200:
            lines.append(_WATCH_SLOW_PAGE)
    lines.append(f"Would send: {'yes' if result.would_fire else 'no'}. {result.why}")
    if result.message:
        lines.append(f"Message: {result.message}")
    return "\n".join(lines)


_SCHEDULE_IDS = frozenset((
    "na-when", "na-at", "na-on", "na-every", "na-every-unit", "na-from", "na-until",
    "na-max-runs", "na-folder",
))


def _every_fields(trigger: d.Trigger | None) -> tuple[str, str]:
    """The number and unit an Every trigger opens with, an old every_hours included."""
    if trigger is None or trigger.kind != "every":
        return "", "hours"
    minutes = trigger.every_minutes or trigger.every_hours * 60
    if not minutes:
        return "", "hours"
    for unit in ("days", "hours"):
        if minutes % _UNIT_MINUTES[unit] == 0:
            return str(minutes // _UNIT_MINUTES[unit]), unit
    return str(minutes), "minutes"


def _next_text(due: datetime, now: datetime) -> str:
    gap = (due.date() - now.date()).days
    day = "today" if gap == 0 else "tomorrow" if gap == 1 else f"{due:%a} {due.day} {due:%b}"
    return f"{day} {due:%H:%M}"


def _cell(value: object) -> Text:
    return Text("" if value is None else str(value), no_wrap=True, end="")


class AgentTemplateScreen(ModalScreen):
    """First step of New agent: Blank agent or one row per template."""

    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    DEFAULT_CSS = """
    AgentTemplateScreen { align: center middle; }
    AgentTemplateScreen > Vertical {
        width: 88; max-width: 100%; height: auto; max-height: 100%;
        padding: 0 2; border: thick $accent; background: $surface;
    }
    AgentTemplateScreen DataTable { height: auto; max-height: 55vh; }
    AgentTemplateScreen Horizontal { height: auto; margin-top: 1; }
    AgentTemplateScreen Button { margin-right: 1; }
    """

    def __init__(self, items=None) -> None:
        super().__init__()
        self._templates = list(templates.list_templates() if items is None else items)

    def compose(self) -> ComposeResult:
        table = DataTable(id="nt-table", cursor_type="row")
        table.add_columns("Template", "Name", "About")
        table.add_row(
            _cell("Blank agent"),
            _cell(""),
            _cell("Start from an empty form."),
            key="blank",
        )
        for item in self._templates:
            table.add_row(
                _cell(item.title),
                _cell(item.name),
                _cell(item.about),
                key=f"template:{item.name}",
            )
        yield Vertical(
            Label("New agent"),
            table,
            Horizontal(
                Button("Continue", id="nt-continue", variant="primary"),
                Button("Cancel", id="nt-cancel"),
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#nt-table", DataTable).focus()

    def _choose(self) -> None:
        key = _row_key(self.query_one("#nt-table", DataTable))
        if key is None or key == "blank":
            self.dismiss("blank")
            return
        name = key.removeprefix("template:")
        self.dismiss(f"template:{name}" if name == "blank" else name)

    def on_data_table_row_selected(self, event) -> None:
        event.stop()
        self._choose()

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "nt-continue":
            self._choose()
        elif event.button.id == "nt-cancel":
            self.dismiss(None)


class _TextPromptScreen(ModalScreen):
    """One web address. Dismisses with the text, or None."""

    DEFAULT_CSS = _CSS.format(name="_TextPromptScreen") + (
        "_TextPromptScreen Static { height: auto; color: $error; }"
    )

    def __init__(self, title: str, placeholder: str = "") -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self._title),
            Input("", id="tp-input", placeholder=self._placeholder),
            Static("", id="tp-error", markup=False),
            Horizontal(
                Button("Add", id="tp-add", variant="primary"),
                Button("Cancel", id="tp-cancel"),
            ),
        )

    def on_input_submitted(self, event) -> None:
        event.stop()
        self._add()

    def _add(self) -> None:
        text = self.query_one("#tp-input", Input).value.strip()
        if not re.match(r"https?://\S+$", text):
            self.query_one("#tp-error", Static).update(
                "Enter a web address starting with http:// or https://")
            return
        self.dismiss(text)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "tp-add":
            self._add()
        else:
            self.dismiss(None)


def _open_tools_tab(screen, tab: str, done) -> None:
    """Open ToolsScreen on one tab; ``done`` runs when it closes."""
    from whyline.console.tools_screens import ToolsScreen

    class _OnTab(ToolsScreen):
        def on_mount(self) -> None:
            self.call_after_refresh(self._show_tab)

        def _checked(self, cli: str, ready: bool) -> None:
            # A background readiness check can land while this screen closes.
            from textual.css.query import NoMatches

            try:
                super()._checked(cli, ready)
            except NoMatches:
                pass

        def _show_tab(self) -> None:
            from textual.widgets import TabbedContent

            self.query_one("#tl-tabs", TabbedContent).active = tab

    screen.app.push_screen(_OnTab(), done)


class PackPickScreen(ModalScreen):
    """Checklist of knowledge packs. Dismisses with the chosen "pack:<name>" items."""

    DEFAULT_CSS = _CSS.format(name="PackPickScreen") + (
        "PackPickScreen VerticalScroll { height: auto; max-height: 20; }"
        " PackPickScreen Checkbox { border: none; height: 1; padding: 0 1; width: auto; }"
        " PackPickScreen Checkbox:focus { border: none; }"
    )

    def __init__(self, chosen: list[str]) -> None:
        super().__init__()
        self._chosen = set(chosen)
        self._names: list[str] = []

    def _widgets(self) -> list:
        from whyline.tools import knowledge

        packs = knowledge.list_packs()
        self._names = [pack.name for pack in packs]
        boxes = [
            Checkbox(
                f"{pack.name} · {pack.description}" if pack.description else pack.name,
                value=f"{knowledge.PACK_PREFIX}{pack.name}" in self._chosen,
                id=f"pp-{i}",
            )
            for i, pack in enumerate(packs)
        ]
        return [VerticalScroll(*boxes) if boxes else Static(
            "No packs yet. Make one in Tools.", id="pp-none")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Add pack"),
            Static("Packs come from your library.", id="pp-hint", markup=False),
            Vertical(*self._widgets(), id="pp-body"),
            Horizontal(
                Button("Done", id="pp-done", variant="primary"),
                Button("Open Tools…", id="pp-open"),
                Button("Cancel", id="pp-cancel"),
            ),
        )

    def _picked(self) -> list[str]:
        from whyline.tools import knowledge

        return [
            f"{knowledge.PACK_PREFIX}{name}" for i, name in enumerate(self._names)
            if self.query(f"#pp-{i}") and self.query_one(f"#pp-{i}", Checkbox).value
        ]

    async def _rebuild(self, _result=None) -> None:
        body = self.query_one("#pp-body")
        await body.remove_children()
        await body.mount(*self._widgets())

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "pp-open":
            self._chosen = set(self._picked())
            _open_tools_tab(self, "tl-knowledge", self._rebuild)
            return
        if event.button.id != "pp-done":
            self.dismiss(None)
            return
        self.dismiss(self._picked())


class SkillPickScreen(ModalScreen):
    """Checklist of skills with origin and description, and the total size against
    the limit. Dismisses with the chosen "origin:name" refs, or None."""

    DEFAULT_CSS = _CSS.format(name="SkillPickScreen") + (
        "SkillPickScreen VerticalScroll { height: auto; max-height: 20; }"
        " SkillPickScreen Checkbox { border: none; height: 1; padding: 0 1; width: auto; }"
        " SkillPickScreen Checkbox:focus { border: none; }"
        " SkillPickScreen #sp-size { height: auto; }"
        " SkillPickScreen #sp-error { height: auto; color: $error; }"
    )

    def __init__(self, root, chosen: list[str], scope: str = "repo") -> None:
        super().__init__()
        self._root = Path(root)
        self._scope = scope
        self._chosen = set(chosen)
        self._skills: list = []

    def _widgets(self) -> list:
        from whyline.tools import skills

        self._skills = skills.find(None if self._scope == "personal" else self._root)
        boxes = []
        for i, skill in enumerate(self._skills):
            label = f"{skill.name} ({skill.origin})"
            if skill.description:
                label += f" · {skill.description}"
            if skill.broken:
                label += f" · broken: {skill.problem}"
            boxes.append(Checkbox(
                label, value=skill.ref in self._chosen and not skill.broken,
                id=f"sk-{i}", disabled=skill.broken,
            ))
        return [VerticalScroll(*boxes) if boxes else Static(
            "No skills found. Make one in Tools.", id="sk-none")]

    def compose(self) -> ComposeResult:
        widgets = self._widgets()
        initial = sum(
            s.size for s in self._skills if s.ref in self._chosen and not s.broken)
        yield Vertical(
            Label("Add skills"),
            Static("Skills come from your library.", id="sk-hint", markup=False),
            Vertical(*widgets, id="sk-body"),
            Static(self._size_text(initial), id="sp-size", markup=False),
            Static("", id="sp-error", markup=False),
            Horizontal(
                Button("Done", id="sk-done", variant="primary"),
                Button("Open Tools…", id="sk-open"),
                Button("Cancel", id="sk-cancel"),
            ),
        )

    async def _rebuild(self, _result=None) -> None:
        body = self.query_one("#sk-body")
        await body.remove_children()
        await body.mount(*self._widgets())
        self._show_size()

    def _show_size(self) -> None:
        self.query_one("#sp-size", Static).update(
            self._size_text(sum(s.size for s in self._picked())))

    def _picked(self) -> list:
        return [
            skill for i, skill in enumerate(self._skills)
            if self.query(f"#sk-{i}") and self.query_one(f"#sk-{i}", Checkbox).value
        ]

    @staticmethod
    def _size_text(total: int) -> str:
        from whyline.tools import skills

        return f"Total size {total} of {skills.AGENT_SKILLS_LIMIT} bytes"

    def on_checkbox_changed(self, event) -> None:
        event.stop()
        self._show_size()

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        from whyline.tools import skills

        event.stop()
        if event.button.id == "sk-open":
            self._chosen = {s.ref for s in self._picked()}
            _open_tools_tab(self, "tl-skills", self._rebuild)
            return
        if event.button.id != "sk-done":
            self.dismiss(None)
            return
        picked = self._picked()
        if sum(s.size for s in picked) > skills.AGENT_SKILLS_LIMIT:
            self.query_one("#sp-error", Static).update(
                f"These skills are over the {skills.AGENT_SKILLS_LIMIT} byte limit. Untick one."
            )
            return
        self.dismiss([s.ref for s in picked])


_WRITE_WARNING = "This tool can change things without asking you."
_PERMISSION_OPTIONS = [("Allowed", "allowed"), ("Ask first", "ask")]


def default_permission(tool) -> str:
    return "allowed" if tool.read_only is True else "ask"


def tool_kind(tool) -> str:
    """``reads``, ``writes`` or ``not stated``. A tool that is not stated is
    treated as a writing tool everywhere else."""
    if tool.read_only is None:
        return "not stated"
    return "reads" if tool.read_only else "writes"


class ToolPickScreen(ModalScreen):
    """The enabled, tested servers, each expandable to its tools with a checkbox and
    a permission. Dismisses with {"<server>.<tool>": "allowed" | "ask"}, or None."""

    DEFAULT_CSS = _CSS.format(name="ToolPickScreen") + (
        "ToolPickScreen VerticalScroll { height: auto; max-height: 24; }"
        " ToolPickScreen Checkbox { border: none; height: 1; padding: 0 1; width: auto; }"
        " ToolPickScreen Checkbox:focus { border: none; }"
        " ToolPickScreen HorizontalGroup { height: auto; }"
        " ToolPickScreen .tp-warning { height: auto; color: $warning; }"
    )

    def __init__(self, chosen: dict[str, str]) -> None:
        super().__init__()
        self._chosen = dict(chosen)
        self._perms = dict(chosen)  # permission of every tool seen, ticked or not
        self._keys: list[tuple[str, object]] = []  # index -> (key, Tool)
        self._empty = False

    def _widgets(self) -> list:
        from whyline.tools import mcp_config

        self._keys = []
        sections = []
        unusable = []
        for server in mcp_config.load().values():
            if not server.enabled:
                unusable.append(f"{server.name} · turned off")
                continue
            if not server.tools:
                unusable.append(f"{server.name} · not tested yet")
                continue
            rows = []
            for tool in server.tools:
                i = len(self._keys)
                key = f"{server.name}.{tool.name}"
                self._keys.append((key, tool))
                permission = self._perms.get(key, default_permission(tool))
                warning = Static(
                    _WRITE_WARNING, id=f"tl-w-{i}", classes="tp-warning", markup=False)
                warning.display = permission == "allowed" and tool.read_only is not True
                kind = tool_kind(tool)
                rows += [
                    HorizontalGroup(
                        Checkbox(f"{tool.name} · {kind}", value=key in self._chosen,
                                 id=f"tl-c-{i}"),
                        Select(_PERMISSION_OPTIONS, value=permission, allow_blank=False,
                               id=f"tl-s-{i}"),
                    ),
                    warning,
                ]
            sections.append(Collapsible(*rows, title=server.name, collapsed=False))
        self._empty = not sections
        lines = [Static(text, classes="tp-unusable", markup=False) for text in unusable]
        if self._empty:
            return [Static(
                "No connectors yet. Add one in Tools, test it, then choose its tools here.",
                id="tl-none", markup=False), *lines]
        return [VerticalScroll(*sections), *lines]

    def compose(self) -> ComposeResult:
        widgets = self._widgets()
        yield Vertical(
            Label("Add tools"),
            Static(
                "Tools come from your connectors. Tick the ones this agent may use, "
                "and choose Allowed or Ask first for each.", id="tl-hint", markup=False),
            Vertical(*widgets, id="tl-body"),
            Horizontal(
                Button("Done", id="tl-done", variant="default" if self._empty else "primary"),
                Button("Open Tools…", id="tl-open",
                       variant="primary" if self._empty else "default"),
                Button("Cancel", id="tl-cancel"),
            ),
        )

    def _collect(self) -> dict[str, str]:
        """Ticks and permissions on screen; remembers both for the next rebuild."""
        picked: dict[str, str] = {}
        for i, (key, _tool) in enumerate(self._keys):
            if not self.query(f"#tl-c-{i}"):
                continue
            value = self.query_one(f"#tl-s-{i}", Select).value
            permission = value if value in ("allowed", "ask") else "ask"
            self._perms[key] = permission
            if self.query_one(f"#tl-c-{i}", Checkbox).value:
                picked[key] = permission
        return picked

    async def _rebuild(self, _result=None) -> None:
        body = self.query_one("#tl-body")
        await body.remove_children()
        await body.mount(*self._widgets())
        self.query_one("#tl-done", Button).variant = "default" if self._empty else "primary"
        self.query_one("#tl-open", Button).variant = "primary" if self._empty else "default"

    def on_select_changed(self, event: "Select.Changed") -> None:
        select_id = event.select.id or ""
        if not select_id.startswith("tl-s-"):
            return
        event.stop()
        i = int(select_id.rsplit("-", 1)[1])
        tool = self._keys[i][1]
        self.query_one(f"#tl-w-{i}", Static).display = (
            event.value == "allowed" and not tool.read_only
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "tl-open":
            self._chosen = self._collect()
            _open_tools_tab(self, "tl-connectors", self._rebuild)
            return
        if event.button.id != "tl-done":
            self.dismiss(None)
            return
        self.dismiss(self._collect())


def tools_summary(defn: d.AgentDef) -> str:
    """One line: what the agent can read, what it can write and how, its skills
    with origins, and its knowledge."""
    parts: list[str] = []
    if defn.tools:
        from whyline.tools import mcp_config

        servers = mcp_config.load()
        reads: list[str] = []
        writes: list[str] = []
        for key, permission in sorted(defn.tools.items()):
            server_name, _, tool_name = key.partition(".")
            server = servers.get(server_name)
            tool = next((t for t in server.tools if t.name == tool_name), None) if server else None
            if tool is not None and tool.read_only:
                reads.append(key)
            else:
                writes.append(f"{key} ({'ask first' if permission == 'ask' else 'allowed'})")
        if reads:
            parts.append("Can read: " + ", ".join(reads))
        if writes:
            parts.append("Can write: " + ", ".join(writes))
    if defn.skills:
        shown = [f"{ref.partition(':')[2]} ({ref.partition(':')[0]})" for ref in defn.skills]
        parts.append("Skills: " + ", ".join(shown))
    items = list(dict.fromkeys((*defn.knowledge, *defn.sources)))
    packs = [i[len("pack:"):] for i in items if i.startswith("pack:")]
    pages = [i for i in items if "://" in i]
    local = [i for i in items if not i.startswith("pack:") and "://" not in i]
    bits = []
    if local:
        bits.append(f"{len(local)} file{'' if len(local) == 1 else 's'} or folder"
                    f"{'' if len(local) == 1 else 's'}")
    if pages:
        bits.append(f"{len(pages)} web page{'' if len(pages) == 1 else 's'}")
    bits += [f'pack "{name}"' for name in packs]
    if bits:
        parts.append("Knowledge: " + ", ".join(bits))
    return " · ".join(parts)


class NewAgentScreen(ModalScreen):
    """Collects one agent. Dismisses with an AgentForm, "back", or None."""

    DEFAULT_CSS = """
    NewAgentScreen { align: center middle; }
    NewAgentScreen > Vertical {
        width: 100; max-width: 100%; height: auto; max-height: 100%;
        padding: 0 2; border: thick $accent; background: $surface;
    }
    NewAgentScreen #na-fields { height: auto; max-height: 65vh; }
    NewAgentScreen HorizontalGroup { height: auto; }
    NewAgentScreen .field-label { width: 16; padding: 1 1 0 0; }
    NewAgentScreen TextArea { height: 6; }
    NewAgentScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; width: auto; }
    NewAgentScreen Checkbox:focus { border: none; }
    NewAgentScreen #na-error { color: $error; height: auto; }
    NewAgentScreen #na-telegram { width: 1fr; }
    NewAgentScreen #na-test-result { height: auto; width: 1fr; }
    NewAgentScreen #na-every { width: 12; }
    NewAgentScreen #na-every-unit { width: 20; }
    NewAgentScreen #na-sources-list, NewAgentScreen #na-every-help,
    NewAgentScreen #na-schedule-line,
    NewAgentScreen #na-skills-list, NewAgentScreen #na-tools-list,
    NewAgentScreen #na-left-out {
        height: auto; color: $text-muted;
    }
    NewAgentScreen #na-buttons { height: auto; margin-top: 1; }
    NewAgentScreen Button { margin-right: 1; }
    """

    def __init__(self, root, status, existing: d.AgentDef | None = None,
                 delivery: dl.Delivery | None = None, *,
                 lock_name: bool | None = None,
                 template: str | None = None,
                 allow_back: bool = False,
                 is_edit: bool | None = None) -> None:
        super().__init__()
        self._root = Path(root)
        self._status = status if isinstance(status, dict) else {}
        self._existing = existing
        self._delivery_in = delivery
        self._template = template
        self._allow_back = allow_back
        if is_edit is None:
            self._is_edit = (
                existing is not None
                and template is None
                and existing.path.is_file()
            )
        else:
            self._is_edit = is_edit
        # Edit passes False. Review's Back passes True so the reviewed name
        # stays put. Callers that omit it keep the name read-only on an edit,
        # and editable when prefilling a new agent from a template.
        self._lock_name = self._is_edit if lock_name is None else lock_name
        self._sources: list[str] = (
            list(dict.fromkeys((*existing.knowledge, *existing.sources))) if existing else []
        )
        self._skills: list[str] = list(existing.skills) if existing else []
        self._tools: dict[str, str] = dict(existing.tools) if existing else {}
        self._picking = False

    def _provider_enabled(self, cli: str) -> bool:
        from whyline.console.repl import provider_enabled

        return provider_enabled(self._status.get(cli))

    def _provider_usable(self, cli: str) -> bool:
        info = self._status.get(cli)
        return (
            self._provider_enabled(cli)
            and isinstance(info, dict)
            and bool(info.get("available"))
        )

    def _runnable(self) -> list[str]:
        return [
            cli for cli in d.CLIS
            if capabilities.can_run(cli) and self._provider_usable(cli)
        ]

    def _all_clis(self) -> list[str]:
        """Enabled usable CLIs, plus a saved disabled or unusable runner or backup."""
        names = list(self._runnable())
        existing = self._existing
        if existing is None or not self._is_edit:
            return names
        for cli in (existing.runner, *existing.backup):
            if cli and cli not in names:
                names.append(cli)
        return names

    def _left_out(self) -> dict[str, str]:
        """Why each CLI can't run the chosen tools; empty with no tools."""
        from whyline.agents import runner

        names = self._all_clis()
        if not self._tools or not names:
            return {}
        probe = SimpleNamespace(runner=names[0], backup=tuple(names[1:]), tools=self._tools)
        return runner._tools_blockers(probe)

    def _choice_clis(self) -> list[str]:
        """The CLIs that can run this agent, tools included (runner.usable_clis)."""
        names = self._all_clis()
        if not self._tools or not names:
            return names
        from whyline.agents import runner

        probe = SimpleNamespace(runner=names[0], backup=tuple(names[1:]), tools=self._tools)
        return runner.usable_clis(probe)

    def _left_out_text(self) -> str:
        return "\n".join(
            f"{cli} is left out: {why}" for cli, why in self._left_out().items())

    def _cli_label(self, cli: str) -> str:
        info = self._status.get(cli)
        status = str(info.get("label") or "") if isinstance(info, dict) else ""
        text = f"{cli} · {status}" if status else cli
        if not self._provider_enabled(cli):
            text += " · unavailable"
        elif not capabilities.can_run_unattended(cli):
            text += " · on demand only"
        return text

    def _choice(self, widget_id: str) -> str:
        value = self.query_one(widget_id, Select).value
        return value if isinstance(value, str) else ""

    def compose(self) -> ComposeResult:
        existing = self._existing
        try:
            existing_delivery = self._delivery_in or (
                dl.get(existing.agent_id) if (existing and self._is_edit) else None
            ) or dl.Delivery()
        except dl.DeliveryError:
            existing_delivery = dl.Delivery()
        from whyline.agents import telegram

        chats = telegram.known_chats()
        chat_options = _chat_options(chats)
        chat_value = existing_delivery.telegram_chat if existing_delivery.telegram_chat in chats else 0
        kind = existing.kind if existing else "personal"
        when = existing.trigger.kind if existing else "manual"
        runnable = self._runnable()
        offered = self._choice_clis()
        if existing and (self._is_edit or existing.runner in offered):
            runner = existing.runner
        else:
            runner = runnable[0] if runnable else None
        if runner not in offered:
            runner = offered[0] if offered else None
        backups = (
            {cli for cli in existing.backup if cli in offered}
            if existing else set()
        )
        boxes = []
        for cli in self._all_clis():
            box = Checkbox(
                self._cli_label(cli),
                value=cli in backups and cli != runner,
                id=f"na-backup-{cli}",
            )
            box.display = cli != runner and cli in offered
            boxes.append(box)
        workdir = HorizontalGroup(
            Label("Runs in", classes="field-label"),
            Input(
                existing.workdir if existing and existing.workdir else "~",
                id="na-workdir",
                placeholder="~",
            ),
            id="na-workdir-row",
        )
        workdir.display = kind == "personal"
        trigger = existing.trigger if existing else d.Trigger()
        on_row = HorizontalGroup(
            Label("On", classes="field-label"),
            Input(trigger.on, id="na-on", placeholder="2026-11-20"),
            id="na-on-row",
        )
        at_row = HorizontalGroup(
            Label("At", classes="field-label"),
            Input(trigger.at, id="na-at", placeholder="07:00, 13:00"),
            id="na-at-row",
        )
        days_row = HorizontalGroup(
            Label("Days", classes="field-label"),
            *(Checkbox(day.capitalize(), value=day in trigger.days, id=f"na-day-{day}")
              for day in d.DAYS),
            id="na-days-row",
        )
        every_number, every_unit = _every_fields(existing.trigger if existing else None)
        every_row = HorizontalGroup(
            Label("Every", classes="field-label"),
            Input(every_number, id="na-every", placeholder="30"),
            Select(_EVERY_UNITS, value=every_unit, allow_blank=False, id="na-every-unit"),
            id="na-every-row",
        )
        every_help = Static(_EVERY_HELP, id="na-every-help")
        folder_row = HorizontalGroup(
            Label("Folder", classes="field-label"),
            Input(trigger.folder, id="na-folder", placeholder="~/Downloads"),
            Button("Choose", id="na-pick-folder"),
            id="na-folder-row",
        )
        range_row = VerticalGroup(
            HorizontalGroup(
                Label("From", classes="field-label"),
                Input(trigger.starts, id="na-from", placeholder="optional, 2026-11-17"),
            ),
            HorizontalGroup(
                Label("Until", classes="field-label"),
                Input(trigger.ends, id="na-until", placeholder="optional, 2026-11-20"),
            ),
            HorizontalGroup(
                Label("Stop after (runs)", classes="field-label"),
                Input(str(trigger.max_runs) if trigger.max_runs else "", id="na-max-runs",
                      placeholder="optional"),
            ),
            id="na-range-rows",
        )
        title = f"Edit {existing.name}" if (existing and self._is_edit) else "New agent"
        buttons = [Button("Review", id="na-next", variant="primary")]
        if self._allow_back:
            buttons.append(Button("Back", id="na-back"))
        buttons.append(Button("Cancel", id="na-cancel"))
        fields = VerticalScroll(
            Label(title),
            HorizontalGroup(
                Label("Where", classes="field-label"),
                Select(_KIND, value=kind, allow_blank=False, id="na-kind"),
            ),
            workdir,
            HorizontalGroup(
                Label("Name", classes="field-label"),
                Input(
                    existing.name if existing else "",
                    placeholder="research-digest",
                    id="na-name",
                    disabled=self._lock_name,
                ),
            ),
            Label("Instructions"),
            TextArea(existing.instructions if existing else "", id="na-instructions"),
            Static(_WATCH_HINT, id="na-w-hint", markup=False),
            HorizontalGroup(
                Label("Main CLI", classes="field-label"),
                Select(
                    [(self._cli_label(cli), cli) for cli in offered],
                    value=runner if runner is not None else Select.BLANK,
                    allow_blank=not offered,
                    prompt="No CLI can run an agent",
                    id="na-runner",
                ),
            ),
            Label("Backup CLIs"),
            *boxes,
            Static(self._left_out_text(), id="na-left-out", markup=False),
            HorizontalGroup(
                Label("Model", classes="field-label"),
                Input(existing.model if existing else "", id="na-model", placeholder="optional"),
            ),
            Label("Knowledge"),
            HorizontalGroup(
                Button("Add files", id="na-add-sources"),
                Button("Add web page", id="na-add-page"),
                Button("Add pack", id="na-add-pack"),
                Button("Clear", id="na-clear-sources"),
            ),
            Static(self._sources_text(), id="na-sources-list", markup=False),
            Label("Skills"),
            HorizontalGroup(
                Button("Add skills…", id="na-add-skills"),
                Button("Clear", id="na-clear-skills"),
            ),
            Static(self._skills_text(), id="na-skills-list", markup=False),
            Label("Tools"),
            HorizontalGroup(
                Button("Add tools…", id="na-add-tools"),
                Button("Clear", id="na-clear-tools"),
            ),
            Static(self._tools_text(), id="na-tools-list", markup=False),
            HorizontalGroup(
                Label("When", classes="field-label"),
                Select(_WHEN, value=when, allow_blank=False, id="na-when"),
            ),
            on_row,
            at_row,
            days_row,
            every_row,
            every_help,
            folder_row,
            range_row,
            Static("", id="na-schedule-line", markup=False),
            Label("Check-in"),
            HorizontalGroup(
                Label("Gate", classes="field-label"),
                Select(self._gate_options(), value=existing.gate if existing else "",
                       allow_blank=False, id="na-gate"),
            ),
            *self._gate_arg_rows(),
            HorizontalGroup(
                Label("Every (minutes)", classes="field-label"),
                Input(self._ck_every_text(), id="na-ck-every", placeholder="60"),
            ),
            HorizontalGroup(
                Label("Active hours", classes="field-label"),
                Input(existing.active_hours if existing else "", id="na-ck-hours",
                      placeholder="optional, e.g. 09:00-17:00 mon-fri"),
            ),
            Checkbox("Stay silent when there's nothing", value=bool(existing and existing.silent),
                     id="na-ck-silent"),
            HorizontalGroup(
                Button("Test gate now", id="na-ck-test"),
                Static("", id="na-ck-result", markup=False),
            ),
            *self._watch_rows(),
            HorizontalGroup(
                Label("Report", classes="field-label"),
                Input(
                    existing.report_folder if existing else "",
                    id="na-report",
                    placeholder="optional folder",
                ),
            ),
            HorizontalGroup(
                Label("Timeout", classes="field-label"),
                Input(
                    str(existing.timeout_minutes) if existing else "15",
                    id="na-timeout",
                    placeholder="15",
                ),
            ),
            Label("Deliver to"),
            HorizontalGroup(
                Label("Email to", classes="field-label"),
                Input(", ".join(existing_delivery.email), id="na-email",
                      placeholder="optional, e.g. you@example.com, other@example.com"),
            ),
            HorizontalGroup(
                Label("Subject", classes="field-label"),
                Input(existing_delivery.subject, id="na-subject", placeholder="the agent's name"),
            ),
            HorizontalGroup(
                Label("Telegram", classes="field-label"),
                Select(chat_options, value=chat_value, allow_blank=False, id="na-telegram"),
                Button("Set up Telegram…", id="na-telegram-setup"),
            ),
            HorizontalGroup(
                Label("Attach as", classes="field-label"),
                Select([("Word (.docx)", "docx"), ("Markdown (.md)", "md")],
                       value=existing_delivery.attach, allow_blank=False, id="na-attach"),
            ),
            HorizontalGroup(
                Label("If a run fails", classes="field-label"),
                Select([("Send a short alert", "alert"), ("Stay silent", "silent")],
                       value=existing_delivery.on_failure, allow_blank=False, id="na-on-failure"),
            ),
            HorizontalGroup(
                Label("After each run", classes="field-label"),
                Input(existing_delivery.command, id="na-command",
                      placeholder="advanced: a command; runs on this Mac only"),
            ),
            HorizontalGroup(
                Button("Send test", id="na-send-test"),
                Static("", id="na-test-result", markup=False),
            ),
            id="na-fields",
        )
        yield Vertical(
            fields,
            Static("", id="na-error", markup=False),
            HorizontalGroup(*buttons, id="na-buttons"),
        )

    @staticmethod
    def _gate_options() -> list[tuple[str, str]]:
        from whyline.agents import gates

        return [("No check-in", ""), *((g.label, g.name) for g in gates.GATES.values())]

    def _gate_arg_rows(self) -> list:
        from whyline.agents import gates

        saved = self._existing.gate_args if self._existing else {}
        rows = []
        for gate in gates.GATES.values():
            for arg in gate.args:
                rows.append(HorizontalGroup(
                    Label(arg.label, classes="field-label"),
                    Input(saved.get(arg.key, arg.default), id=f"na-ck-{arg.key}"),
                    id=f"na-ck-row-{arg.key}", classes="na-ck-arg",
                ))
        return rows

    def _watch_rows(self) -> list:
        saved = self._existing
        watch = saved.watch if saved is not None else None
        args = saved.gate_args if watch is not None else {}
        urls = (args.get("url") or "").split()[:_WATCH_URLS]
        direction, _, limit = (watch.value if watch else "").partition(" ")
        address_rows = [
            HorizontalGroup(
                Label("Address" if n == 0 else "", classes="field-label"),
                Input(urls[n] if n < len(urls) else "", id=f"na-w-url-{n}",
                      placeholder="https://example.com/page" if n == 0 else "optional"),
            )
            for n in range(_WATCH_URLS)
        ]
        body = VerticalGroup(
            *address_rows,
            HorizontalGroup(
                Label("Tell me when", classes="field-label"),
                Select(_WATCH_RULES, value=args.get("rule", "changed"), allow_blank=False,
                       id="na-w-rule"),
            ),
            HorizontalGroup(
                Label("Text", classes="field-label"),
                Input(args.get("text", ""), id="na-w-text"),
                id="na-w-text-row",
            ),
            HorizontalGroup(
                Label("Only between", classes="field-label"),
                Input(args.get("start", ""), id="na-w-start", placeholder="start text"),
                Input(args.get("end", ""), id="na-w-end", placeholder="end text"),
            ),
            HorizontalGroup(
                Label("A number goes", classes="field-label"),
                Select(_WATCH_DIRECTIONS, value=direction, allow_blank=False, id="na-w-dir"),
                Input(limit, id="na-w-limit", placeholder="limit"),
                id="na-w-number-row",
            ),
            Checkbox("Stop after the first time", value=bool(watch and watch.stop == "first"),
                     id="na-w-first"),
            Checkbox("Tell me even outside active hours", value=bool(watch and watch.urgent),
                     id="na-w-urgent"),
            HorizontalGroup(
                Label("Agent runs per day, at most", classes="field-label"),
                Input(str(watch.daily_cap) if watch else "24", id="na-w-cap"),
            ),
            HorizontalGroup(
                Button("Test", id="na-w-test"),
                Static("", id="na-w-result", markup=False),
            ),
            id="na-w-body",
        )
        return [Label("Watch"),
                Checkbox("Watch a web page", value=watch is not None, id="na-w-on"), body]

    def _watch_on(self) -> bool:
        return self.query_one("#na-w-on", Checkbox).value

    def _sync_watch(self) -> None:
        try:
            on = self._watch_on()
            rule = self._choice("#na-w-rule")
            direction = self._choice("#na-w-dir")
        except NoMatches:
            return
        self.query_one("#na-w-body").display = on
        self.query_one("#na-w-text-row").display = rule in ("appears", "gone")
        self.query_one("#na-w-number-row").display = rule != "gone"
        # The hint shows only while whyline can send the message itself.
        self.query_one("#na-w-hint").display = (
            on and rule in ("changed", "appears", "gone")
            and (rule == "gone" or not direction))

    def _watch_values(self) -> dict:
        """The Watch fields as {gate_args, watch}; ValueError says what is wrong."""
        from whyline.agents import watch as watch_rules

        text = lambda widget_id: self.query_one(widget_id, Input).value.strip()  # noqa: E731
        urls = [u for u in (text(f"#na-w-url-{n}") for n in range(_WATCH_URLS)) if u]
        if not urls:
            raise ValueError("Give at least one address to watch")
        rule = self._choice("#na-w-rule") or "changed"
        start, end = text("#na-w-start"), text("#na-w-end")
        if bool(start) != bool(end):
            raise ValueError("Only between needs both the start and the end text")
        direction, limit = self._choice("#na-w-dir"), text("#na-w-limit")
        value = ""
        if direction and rule != "gone":
            if not limit:
                raise ValueError(f"A number goes {direction}: give the limit")
            value = f"{direction} {limit}"
        cap = text("#na-w-cap")
        if not re.fullmatch(r"\d{1,6}", cap):
            raise ValueError("Agent runs per day, at most must be a whole number")
        watch = watch_rules.Watch(
            stop="first" if self.query_one("#na-w-first", Checkbox).value else "never",
            value=value, urgent=self.query_one("#na-w-urgent", Checkbox).value, daily_cap=int(cap))
        return {
            "gate_args": {"url": " ".join(urls), "rule": rule,
                          "text": text("#na-w-text") if rule in ("appears", "gone") else "",
                          "start": start, "end": end},
            "watch": watch,
        }

    def _test_watch(self) -> None:
        result = self.query_one("#na-w-result", Static)
        saved = self._existing
        try:
            values = self._watch_values()
            if saved is None or not self._is_edit or saved.watch is None:
                raise ValueError("Save the agent first, then open it to Test the watch.")
            if values["watch"] != saved.watch or values["gate_args"] != {
                    k: saved.gate_args.get(k, "") for k in values["gate_args"]}:
                raise ValueError("Test checks the saved watch. Save your changes first.")
        except ValueError as error:
            result.update(str(error))
            return
        name, root = f"{saved.kind}:{saved.name}", self._root
        result.update("Checking…")

        def work() -> None:
            try:
                text = watch_test_text(service.test_watch(name, root))
            except Exception as error:
                text = str(error)
            self.app.call_from_thread(result.update, text)

        self.app.run_worker(work, thread=True)

    def _ck_every_text(self) -> str:
        trigger = self._existing.trigger if self._existing else None
        if trigger is not None and trigger.kind == "every" and trigger.every_minutes:
            return str(trigger.every_minutes)
        return str(service.DEFAULT_CHECKIN_MINUTES)

    def _sync_gate(self) -> None:
        from whyline.agents import gates

        try:
            chosen = self._choice("#na-gate")
        except NoMatches:
            return
        wanted = {a.key for a in gates.GATES[chosen].args} if chosen in gates.GATES else set()
        for gate in gates.GATES.values():
            for arg in gate.args:
                self.query_one(f"#na-ck-row-{arg.key}").display = arg.key in wanted

    def _checkin_values(self) -> dict:
        """The Check-in fields as service.save_checkin takes them."""
        from whyline.agents import gates

        gate = self._choice("#na-gate")
        args = {a.key: self.query_one(f"#na-ck-{a.key}", Input).value
                for a in (gates.GATES[gate].args if gate in gates.GATES else ())}
        if self._watch_on():  # a watch is the page gate; its own fields say which page
            gate, args = "page", self._watch_values()["gate_args"]
        elif self._existing is not None and self._existing.watch is not None:
            gate, args = "", {}  # unticked: a plain agent again, watch_off clears the gate
        raw = self.query_one("#na-ck-every", Input).value.strip()
        if raw and not re.fullmatch(r"\d{1,6}", raw):
            raise ValueError("Every (minutes) must be a whole number")
        return {
            "gate": gate, "gate_args": args,
            "every_minutes": int(raw) if raw else None,
            "active_hours": self.query_one("#na-ck-hours", Input).value,
            "silent": self.query_one("#na-ck-silent", Checkbox).value,
        }

    def _test_gate(self) -> None:
        result = self.query_one("#na-ck-result", Static)
        try:
            values = self._checkin_values()
            if not values["gate"]:
                raise ValueError("Choose a gate first")
            from whyline.agents import gates

            try:
                args = gates.validate(values["gate"], values["gate_args"])
            except gates.GateError as error:
                raise ValueError(str(error)) from error
        except ValueError as error:
            result.update(str(error))
            return
        agent_id = self._existing.agent_id if (self._existing and self._is_edit) else None
        result.update("Checking…")

        def work() -> None:
            try:
                found = service.test_gate(agent_id, values["gate"], args)
                lines = [item.line for item in found.items[:5]]
                text = (f"{len(found.items)} found: " + "; ".join(lines)) if lines else "Nothing new."
            except Exception as error:
                text = str(error)
            self.app.call_from_thread(result.update, text)

        self.app.run_worker(work, thread=True)

    def on_mount(self) -> None:
        self._sync_kind()
        self._sync_when()
        self._sync_gate()
        self._sync_watch()
        self._sync_backups()
        self.query_one("#na-error", Static).display = False
        if self._existing is None:
            self.query_one("#na-name", Input).focus()

    def on_select_changed(self, event: "Select.Changed") -> None:
        select_id = event.select.id
        if select_id == "na-gate":
            self._sync_gate()
        elif select_id == "na-kind":
            self._sync_kind()
            self._drop_repo_skills()
        elif select_id == "na-runner":
            self._sync_backups()
        elif select_id == "na-when":
            self._sync_when()
        elif select_id == "na-every-unit":
            self._sync_when()
        if select_id in _WATCH_IDS:
            self._sync_watch()
        if select_id in _SCHEDULE_IDS:
            self._refresh_schedule_line()

    def on_input_changed(self, event: "Input.Changed") -> None:
        if event.input.id in _SCHEDULE_IDS:
            self._refresh_schedule_line()

    def on_checkbox_changed(self, event: "Checkbox.Changed") -> None:
        if event.checkbox.id in _WATCH_IDS:
            self._sync_watch()
        if (event.checkbox.id or "").startswith("na-day-"):
            self._refresh_schedule_line()

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        button_id = event.button.id
        if button_id == "na-cancel":
            self.dismiss(None)
        elif button_id == "na-back":
            self.dismiss("back")
        elif button_id == "na-next":
            self._submit()
        elif button_id == "na-send-test":
            self._send_test()
        elif button_id == "na-ck-test":
            self._test_gate()
        elif button_id == "na-w-test":
            self._test_watch()
        elif button_id == "na-telegram-setup":
            self._telegram_setup()
        elif button_id == "na-add-sources":
            self._pick("sources")
        elif button_id == "na-clear-sources":
            self._sources.clear()
            self._refresh_sources()
        elif button_id == "na-add-page":
            self.app.push_screen(
                _TextPromptScreen("Add web page", "https://example.com/page"), self._page_done)
        elif button_id == "na-add-pack":
            packs = [s for s in self._sources if s.startswith("pack:")]
            self.app.push_screen(PackPickScreen(packs), self._packs_done)
        elif button_id == "na-add-skills":
            self.app.push_screen(SkillPickScreen(self._root, self._skills, self._choice("#na-kind") or "personal"),
                self._skills_done,
            )
        elif button_id == "na-clear-skills":
            self._skills.clear()
            self._refresh_list("#na-skills-list", self._skills_text())
        elif button_id == "na-add-tools":
            self.app.push_screen(ToolPickScreen(self._tools), self._tools_done)
        elif button_id == "na-clear-tools":
            self._tools.clear()
            self._tools_changed()
        elif button_id == "na-pick-folder":
            self._pick("folder")

    def _sync_kind(self) -> None:
        try:
            self.query_one("#na-workdir-row").display = self._choice("#na-kind") == "personal"
        except NoMatches:
            return

    def _repo_skills(self) -> list[str]:
        return [ref for ref in self._skills if ref.partition(":")[0] in _REPO_SKILL_ORIGINS]

    @staticmethod
    def _repo_skill_text(refs: list[str]) -> str:
        return (
            f"Removed {len(refs)} skills that are only in this repository: "
            f"{', '.join(refs)}. A personal agent can use skills from "
            "~/.whyline/skills and ~/.claude/skills."
        )

    def _drop_repo_skills(self) -> None:
        try:
            if self._choice("#na-kind") != "personal":
                return
        except NoMatches:
            return
        refs = self._repo_skills()
        if not refs:
            return
        self._skills[:] = [ref for ref in self._skills if ref not in refs]
        self._refresh_list("#na-skills-list", self._skills_text())
        self._show_error(self._repo_skill_text(refs))

    def _sync_when(self) -> None:
        try:
            when = self._choice("#na-when")
            unit = self._choice("#na-every-unit")
        except NoMatches:
            return
        self.query_one("#na-on-row").display = when == "once"
        self.query_one("#na-at-row").display = when in ("once", "daily", "weekdays", "weekly")
        self.query_one("#na-days-row").display = when == "weekly"
        every = when == "every"
        self.query_one("#na-every-row").display = every
        self.query_one("#na-every-help").display = every and unit == "hours"
        self.query_one("#na-folder-row").display = when == "folder"
        self.query_one("#na-range-rows").display = when not in ("manual", "once")
        self._refresh_schedule_line()

    def _schedule_values(self) -> dict:
        """The Schedule block as service.save_schedule takes it; ValueError says what is wrong."""
        when = self._choice("#na-when") or "manual"
        text = lambda widget_id: self.query_one(widget_id, Input).value.strip()  # noqa: E731
        values: dict = {"kind": when, "at": "", "on": "", "days": (), "every_minutes": 0,
                        "starts": "", "ends": "", "max_runs": 0}
        if when in ("once", "daily", "weekdays", "weekly"):
            values["at"] = text("#na-at")
        if when == "once":
            values["on"] = text("#na-on")
        if when == "weekly":
            values["days"] = tuple(
                day for day in d.DAYS if self.query_one(f"#na-day-{day}", Checkbox).value)
        if when == "every":
            raw = text("#na-every")
            if not re.fullmatch(r"\d{1,6}", raw):
                raise ValueError("Every needs a whole number")
            values["every_minutes"] = int(raw) * _UNIT_MINUTES[self._choice("#na-every-unit")]
        if when not in ("manual", "once"):
            values["starts"], values["ends"] = text("#na-from"), text("#na-until")
            runs = text("#na-max-runs")
            if runs and not re.fullmatch(r"\d{1,6}", runs):
                raise ValueError("Stop after (runs) must be a whole number")
            values["max_runs"] = int(runs) if runs else 0
        return values

    def _schedule_trigger(self, values: dict) -> d.Trigger:
        old = self._existing.trigger if self._existing else d.Trigger()
        raw = {**values, "days": list(values["days"]), "min_gap_minutes": old.min_gap_minutes,
               "folder": self.query_one("#na-folder", Input).value.strip()
               if values["kind"] == "folder" else ""}
        return d._trigger(raw)  # the checks a saved file gets

    def _schedule_text(self) -> str:
        trigger = self._schedule_trigger(self._schedule_values())
        words = service.when_text(trigger)
        text = words[0].upper() + words[1:] + "."
        now = datetime.now()
        due = schedule.next_due(trigger, now=now)
        return f"{text} Next: {_next_text(due, now)}." if due else text

    def _refresh_schedule_line(self) -> None:
        try:
            line = self.query_one("#na-schedule-line", Static)
            try:
                text = self._schedule_text()
            except ValueError as error:
                text = str(error)
        except NoMatches:
            return
        line.update(text)

    def _sync_backups(self) -> None:
        try:
            runner = self._choice("#na-runner")
        except NoMatches:
            return
        offered = self._choice_clis()
        for cli in self._all_clis():
            try:
                box = self.query_one(f"#na-backup-{cli}", Checkbox)
            except NoMatches:
                return
            show = cli != runner and cli in offered
            box.display = show
            if not show:
                box.value = False

    def _sources_text(self) -> str:
        return "\n".join(self._sources) if self._sources else "(none)"

    def _skills_text(self) -> str:
        return "\n".join(self._skills) if self._skills else "(none)"

    def _tools_text(self) -> str:
        if not self._tools:
            return "(none)"
        words = {"allowed": "allowed", "ask": "ask first"}
        return "\n".join(f"{key} · {words.get(p, p)}" for key, p in sorted(self._tools.items()))

    def _refresh_list(self, widget_id: str, text: str) -> None:
        try:
            self.query_one(widget_id, Static).update(text)
        except NoMatches:
            return

    def _refresh_sources(self) -> None:
        self._refresh_list("#na-sources-list", self._sources_text())

    def _page_done(self, url) -> None:
        if isinstance(url, str) and url not in self._sources:
            self._sources.append(url)
            self._refresh_sources()

    def _packs_done(self, packs) -> None:
        if not isinstance(packs, list):
            return
        self._sources[:] = [s for s in self._sources if not s.startswith("pack:")] + packs
        self._refresh_sources()

    def _skills_done(self, refs) -> None:
        if not isinstance(refs, list):
            return
        self._skills[:] = refs
        self._refresh_list("#na-skills-list", self._skills_text())

    def _tools_done(self, picked) -> None:
        if not isinstance(picked, dict):
            return
        self._tools = dict(picked)
        self._tools_changed()

    def _tools_changed(self) -> None:
        """Tools narrow the CLIs that can run the agent: redo both lists."""
        self._refresh_list("#na-tools-list", self._tools_text())
        try:
            select = self.query_one("#na-runner", Select)
        except NoMatches:
            return
        offered = self._choice_clis()
        current = select.value
        select.set_options([(self._cli_label(cli), cli) for cli in offered])
        if current in offered:
            select.value = current
        elif offered:
            select.value = offered[0]
        self._refresh_list("#na-left-out", self._left_out_text())
        self._sync_backups()

    def _show_error(self, message: str) -> None:
        try:
            widget = self.query_one("#na-error", Static)
        except NoMatches:
            return
        widget.update(message)
        widget.display = bool(message)

    def _pick(self, target: str) -> None:
        from whyline.console import mac_input

        if self._picking:
            return
        if not mac_input.available():
            self._show_error("The file picker is only available on macOS.")
            return
        self._picking = True

        def work() -> None:
            try:
                picked = mac_input.pick_files()
            except Exception as error:
                self.app.call_from_thread(self._pick_failed, str(error) or "the file picker failed")
                return
            self.app.call_from_thread(self._pick_done, target, list(picked))

        self.run_worker(work, thread=True, exclusive=True, group="agent-pick")

    def _pick_failed(self, message: str) -> None:
        self._picking = False
        self._show_error(message)

    def _pick_done(self, target: str, picked: list[Path]) -> None:
        self._picking = False
        if not self.is_attached:
            return
        if target == "folder":
            folder = _first_folder(picked)
            if folder is None:
                if picked:
                    self._show_error("Pick a folder.")
                return
            stored = self._stored_path(folder, allow_outside=True)
            if stored:
                self.query_one("#na-folder", Input).value = stored
            return
        added = False
        for path in picked:
            stored = self._stored_path(path, allow_outside=False)
            if stored and stored not in self._sources:
                self._sources.append(stored)
                added = True
        if added:
            self._show_error("")
        self._refresh_sources()

    def _stored_path(self, path: Path, *, allow_outside: bool) -> str:
        try:
            resolved = Path(path).expanduser().resolve()
        except OSError:
            resolved = Path(path)
        if self._choice("#na-kind") == "repo":
            try:
                return resolved.relative_to(self._root.resolve()).as_posix()
            except ValueError:
                if not allow_outside:
                    self._show_error(f"{resolved.as_posix()} is outside the repository")
                    return ""
        return _tilde(resolved)

    def _int_token(self, widget_id: str, default: int | None) -> str:
        raw = self.query_one(widget_id, Input).value.strip()
        if not raw:
            return "0" if default is None else str(default)
        if re.fullmatch(r"[1-9]\d*|0", raw):
            return raw
        return _q(raw)

    def _toml(self) -> tuple[str, str, Path]:
        kind = self._choice("#na-kind") or "personal"
        name = self.query_one("#na-name", Input).value.strip()
        runner = self._choice("#na-runner")
        when = self._choice("#na-when") or "manual"
        backups = [
            cli for cli in self._choice_clis()
            if cli != runner and self.query_one(f"#na-backup-{cli}", Checkbox).value
        ]
        lines = [
            f"name = {_q(name)}",
            f"instructions = {_q(self.query_one('#na-instructions', TextArea).text)}",
            f"runner = {_q(runner)}",
            "backup = [" + ", ".join(_q(cli) for cli in backups) + "]",
        ]
        model = self.query_one("#na-model", Input).value.strip()
        if model:
            lines.append(f"model = {_q(model)}")
        lines.append("knowledge = [" + ", ".join(_q(source) for source in self._sources) + "]")
        if self._skills:
            lines.append("skills = [" + ", ".join(_q(ref) for ref in self._skills) + "]")
        if kind == "personal":
            workdir = self.query_one("#na-workdir", Input).value.strip() or "~"
            lines.append(f"workdir = {_q(workdir)}")
        report = self.query_one("#na-report", Input).value.strip()
        if report:
            lines.append(f"report_folder = {_q(report)}")
        lines.append(f"timeout_minutes = {self._int_token('#na-timeout', 15)}")
        if self._existing and self._existing.before:
            lines.append(f"before = {_q(self._existing.before)}")
        values = self._schedule_values()
        trigger = self._schedule_trigger(values)
        lines += ["", "[trigger]", f"kind = {_q(when)}"]
        if trigger.at:
            lines.append(f"at = {_q(trigger.at)}")
        if trigger.on:
            lines.append(f"on = {_q(trigger.on)}")
        if trigger.days:
            lines.append("days = [" + ", ".join(_q(day) for day in trigger.days) + "]")
        if trigger.every_minutes:
            lines.append(f"every_minutes = {trigger.every_minutes}")
        if trigger.starts:
            lines.append(f"starts = {_q(trigger.starts)}")
        if trigger.ends:
            lines.append(f"ends = {_q(trigger.ends)}")
        if trigger.max_runs:
            lines.append(f"max_runs = {trigger.max_runs}")
        if trigger.folder:
            lines.append(f"folder = {_q(trigger.folder)}")
        lines.append(f"min_gap_minutes = {trigger.min_gap_minutes}")
        if self._tools:
            lines += ["", "[tools]"]
            lines += [f"{_q(key)} = {_q(value)}" for key, value in sorted(self._tools.items())]
        if self._watch_on():
            # The tables a watch needs to load; _submit's checkin_defn then adds hours and silence.
            found = self._watch_values()
            watch = found["watch"]
            lines += ["", "[checkin]", 'gate = "page"', "", "[checkin.gate_args]"]
            lines += [f"{_q(k)} = {_q(v)}" for k, v in sorted(found["gate_args"].items())]
            lines += ["", "[watch]", f"stop = {_q(watch.stop)}"]
            if watch.value:
                lines.append(f"value = {_q(watch.value)}")
            if watch.urgent:
                lines.append("urgent = true")
            lines.append(f"daily_cap = {watch.daily_cap}")
        # Edit writes back to the file that was opened. A new agent, or an
        # edit that changed kind, uses <name>.toml in that kind's directory.
        same = (
            self._existing is not None
            and self._existing.kind == kind
            and self._existing.name == name
        )
        if same:
            path = self._existing.path
        elif kind == "repo":
            path = paths.repo_dir(self._root) / f"{name}.toml"
        else:
            path = Path.home() / ".whyline" / "agents" / f"{name}.toml"
        return "\n".join(lines) + "\n", kind, path

    def _name_taken(self, defn: d.AgentDef) -> bool:
        for item in d.discover(self._root):
            if not isinstance(item, d.AgentDef):
                continue
            if item.kind != defn.kind or item.name != defn.name:
                continue
            if self._is_edit and self._existing is not None and item.path == self._existing.path:
                continue
            return True
        return False

    def _submit(self) -> None:
        try:
            text, kind, path = self._toml()
            if kind == "personal" and self._repo_skills():
                self._show_error(self._repo_skill_text(self._repo_skills()))
                return
            defn = d.parse(
                text,
                kind=kind,
                path=path,
                repo_root=self._root if kind == "repo" else None,
            )
            values = self._checkin_values()
            if values["gate"]:
                defn = service.checkin_defn(defn, **values)
        except ValueError as error:  # DefinitionError is one; so is a gate's reason
            self._show_error(str(error))
            return
        if self._name_taken(defn):
            self._show_error(f"an agent named {defn.name} already exists")
            return
        for cli in (defn.runner, *defn.backup):
            if cli and not self._provider_enabled(cli):
                self._show_error(
                    f"Enable {cli} in Settings or choose another provider."
                )
                return
        try:
            delivery = self._delivery()
            from whyline.agents import telegram

            dl.validate(delivery, set(telegram.known_chats()))
        except dl.DeliveryError as error:
            self._show_error(str(error))
            return
        global _pending_schedule
        _pending_schedule = None
        saved = self._existing
        steps: list = []
        watch_on = defn.watch is not None
        if watch_on and defn.kind == "repo":
            self._show_error("A watch must be a personal agent")
            return
        stored = (
            self._is_edit and saved is not None and saved.path.is_file()
            and (defn.kind, defn.name) == (saved.kind, saved.name)
        )
        if stored and watch_on and (defn.watch, defn.gate_args) != (saved.watch, saved.gate_args):
            # The same call `agents watch` makes, run when Review's Save is pressed.
            watch_values = self._watch_values()
            name, root = f"{defn.kind}:{defn.name}", self._root

            def save_the_watch() -> None:
                service.save_watch(name, **watch_values["gate_args"], **_watch_kwargs(defn.watch),
                                   repo_root=root)

            steps.append(save_the_watch)
        elif stored and not watch_on and saved.watch is not None:
            name, root, words = f"{defn.kind}:{defn.name}", self._root, defn.instructions

            def stop_watching() -> None:
                before = service.find(name, root)
                if before.instructions != words:
                    # A watch may have none; a plain agent needs them before watch_off checks it.
                    service._write_changed(before, replace(before, instructions=words))
                service.watch_off(name, root)

            steps.append(stop_watching)
        if stored and not watch_on and defn.trigger != saved.trigger:
            # The same call `agents schedule` makes, run when Review's Save is pressed (a new
            # agent has no file to save to yet). Back or cancel writes nothing.
            values, root, folder = self._schedule_values(), self._root, defn.trigger.folder

            def save_trigger() -> None:
                name = f"{defn.kind}:{defn.name}"
                if values["kind"] == "folder":
                    # save_schedule keeps the stored folder, so a newly typed one goes in first.
                    before = service.find(name, root)
                    if before.trigger.folder != folder:
                        service._write_changed(before, replace(
                            before, trigger=replace(before.trigger, folder=folder)))
                service.save_schedule(name, **values, repo_root=root)

            steps.insert(0, save_trigger)
        if steps:
            def run_steps() -> None:
                for step in steps:
                    step()

            _pending_schedule = (defn, run_steps)
        self.dismiss(AgentForm(defn, delivery))

    def _delivery(self) -> dl.Delivery:
        from whyline.agents import telegram

        chat = self.query_one("#na-telegram", Select).value
        chat = chat if isinstance(chat, int) else 0
        return dl.Delivery(
            email=dl.parse_emails(self.query_one("#na-email", Input).value),
            subject=self.query_one("#na-subject", Input).value.strip(),
            telegram_chat=chat,
            telegram_label=telegram.known_chats().get(chat, "") if chat else "",
            attach=self._choice("#na-attach") or "docx",
            on_failure=self._choice("#na-on-failure") or "alert",
            command=self.query_one("#na-command", Input).value.strip(),
        )

    def _send_test(self) -> None:
        from whyline.agents import deliver

        try:
            delivery = self._delivery()
            dl.validate(delivery)
        except dl.DeliveryError as error:
            self.query_one("#na-test-result", Static).update(str(error))
            return
        label = (self.query_one("#na-name", Input).value.strip() or "this agent")
        self.query_one("#na-test-result", Static).update("Sending…")

        def work() -> None:
            try:
                results = deliver.send_test(label, delivery)
                text = "  ".join(f"{r['to']} {'✓' if r['ok'] else '✗'}"
                                 + ("" if r["ok"] else f" {r['detail']}") for r in results)
                text = text or "Nothing to test: choose an email, Telegram chat or command."
            except Exception as error:
                text = str(error)
            self.app.call_from_thread(self.query_one("#na-test-result", Static).update, text)

        self.app.run_worker(work, thread=True)

    def _telegram_setup(self) -> None:
        def done(chats) -> None:
            if not isinstance(chats, dict):
                return
            select = self.query_one("#na-telegram", Select)
            current = select.value
            select.set_options(_chat_options(chats))
            select.value = current if current in chats else (next(iter(chats)) if chats else 0)

        self.app.push_screen(TelegramSetupScreen(), done)


class ReviewScreen(ModalScreen):
    """Plain-language check before an agent is written. Dismisses with
    "save" or None (back to the form)."""

    DEFAULT_CSS = _CSS.format(name="ReviewScreen") + "ReviewScreen Static { height: auto; }"

    def __init__(self, defn: d.AgentDef, text: str, scheduler_on: bool) -> None:
        super().__init__()
        self._defn = defn
        self._text = text
        self._scheduler_on = scheduler_on

    def _body(self) -> str:
        text = self._text
        if self._defn.trigger.kind != "manual" and not self._scheduler_on:
            text = text.rstrip() + "\nTurn the scheduler on to run it automatically."
        summary = tools_summary(self._defn)
        if summary:
            text = text.rstrip() + "\n" + summary
        return text

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(f"Review {self._defn.label}"),
            Static(self._body(), id="rv-text", markup=False),
            Horizontal(
                Button("Save", id="rv-save", variant="primary"),
                Button("Back", id="rv-back"),
            ),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        global _pending_schedule
        if event.button.id != "rv-save":
            self.dismiss(None)
            return
        pending = _pending_schedule
        if pending is not None and pending[0] is self._defn:
            try:
                pending[1]()
            except ValueError as error:
                self.query_one("#rv-text", Static).update(str(error))
                return
            _pending_schedule = None
        self.dismiss("save")
