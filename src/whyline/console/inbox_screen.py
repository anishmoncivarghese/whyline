"""Inbox settings for Agents mode.

The same writes as ``whyline idea``: allow and deny a chat, the default
agents, the assistant pair, document format, and service on or off.
Check prints the same lines as ``whyline idea doctor``.
"""

from __future__ import annotations

import argparse
import io
import sqlite3
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, Select, Static

from whyline.console.chain_editor import OrderedChain

_FORMATS = ("word", "pdf", "both")


@dataclass(frozen=True)
class _Saved:
    """What is stored. ``None`` means the key is absent, which is not the
    same as a default the screen displays for an absent key."""

    allowed: tuple[int, ...]
    agents: tuple[str, ...] | None
    assistant: str | None
    backup: str | None
    documents: str | None
    service_on: bool


def _db_path():
    from whyline.ideas import paths

    path = paths.configured_home() / "ideas.sqlite3"
    return path if path.is_file() else None


def _kv(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    value = row["value"]
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _read_saved() -> _Saved:
    """Saved settings. Does not create the inbox database."""
    path = _db_path()
    if path is None:
        return _Saved((), None, None, None, None, False)
    from whyline.ideas import assistant, cli, telegram_in, worker

    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        agents = cli._stored_agents(conn)
        return _Saved(
            allowed=tuple(telegram_in.allowed_chats(conn)),
            agents=None if agents is None else tuple(agents),
            assistant=_kv(conn, assistant.ASSISTANT_KEY),
            backup=_kv(conn, assistant.BACKUP_KEY),
            documents=_kv(conn, "doc_formats"),
            service_on=worker.enabled(conn),
        )
    finally:
        conn.close()


def _offered() -> list[str]:
    from whyline.agents import capabilities, definitions

    return [name for name in definitions.CLIS if capabilities.can_run_unattended(name)]


def _blocked(offered: list[str]) -> list[tuple[str, str]]:
    """Agents the chain must not offer, with the CLI's own reason."""
    from whyline.agents import definitions
    from whyline.ideas import cli

    rows = []
    for name in definitions.CLIS:
        if name in offered:
            continue
        reason = cli._reject_agents([name]) or f"{name}: not cleared for unattended runs"
        rows.append((name, reason))
    return rows


def _status_text() -> str:
    """The same lines as ``whyline idea service status``."""
    from whyline.agents import launchd
    from whyline.ideas import cli

    buf = io.StringIO()
    with redirect_stdout(buf):
        cli._print_service_status(launchd)
    return buf.getvalue().rstrip("\n")


def _doctor_text() -> str:
    """The same lines as ``whyline idea doctor``."""
    from whyline.ideas import cli

    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.cmd_doctor(argparse.Namespace())
    return buf.getvalue().rstrip("\n")


def _run(fn, args) -> str:
    """Run one CLI command. The text is its error, or empty on success."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fn(args)
    if code == 0:
        return ""
    return err.getvalue().strip() or out.getvalue().strip()


def _choice(select: Select) -> str | None:
    value = select.value
    blank = getattr(Select, "BLANK", None)
    if value is blank or value is None or not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _plain(text: str) -> Text:
    """Bracketed doctor lines are literal. Textual must not parse them."""
    return Text(text)


class IdeaInboxScreen(ModalScreen):
    """Settings for the idea inbox. Cancel writes nothing.

    OrderedChain enables every agent it is given, so an agent that cannot
    run unattended is a disabled row under the chain instead of a member.
    """

    DEFAULT_CSS = """
    IdeaInboxScreen { align: center middle; }
    IdeaInboxScreen Vertical, IdeaInboxScreen Horizontal { height: auto; }
    IdeaInboxScreen > Vertical {
        width: 100%; max-width: 100%; height: auto; max-height: 100%;
        padding: 0 1; border: thick $accent; background: $surface;
    }
    /* 1fr does nothing while the popup sizes to its content, which pushes
       the buttons off a 24-row terminal. Cap the body; the buttons follow it. */
    IdeaInboxScreen #ib-body { height: auto; max-height: 16; }
    IdeaInboxScreen #ib-buttons { height: auto; margin-top: 1; }
    IdeaInboxScreen #ib-buttons Button { margin-right: 1; }
    IdeaInboxScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; width: 1fr; }
    IdeaInboxScreen Checkbox:focus { border: none; }
    IdeaInboxScreen Select { width: 1fr; }
    IdeaInboxScreen #ib-bot, IdeaInboxScreen #ib-status, IdeaInboxScreen #ib-checks,
    IdeaInboxScreen #ib-chats-empty, IdeaInboxScreen #ib-message { height: auto; }
    IdeaInboxScreen #ib-message { color: $error; }
    IdeaInboxScreen #ib-message.-empty { display: none; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._token: str | None = None
        self._private: list[tuple[int, str]] = []
        self._offered: list[str] = []
        self._loaded_agents: list[str] = []
        self._generation = 0
        self._closed = False

    def compose(self) -> ComposeResult:
        from whyline.agents import telegram
        from whyline.ideas import telegram_in

        saved = _read_saved()
        self._token = telegram.token_get()
        self._private = telegram_in.private_chats(telegram.known_chats())
        self._offered = _offered()
        names = list(self._offered)
        for extra in (saved.assistant, saved.backup):
            if extra and extra not in names:
                names.append(extra)
        agent_options = [(name, name) for name in names] or [("None", "none")]
        assistant_value = saved.assistant if saved.assistant in names else None
        backup_value = saved.backup if saved.backup in names else "none"
        documents = saved.documents if saved.documents in _FORMATS else "both"
        chain = OrderedChain(self._offered, id="ib-agents")
        self._loaded_agents = list(saved.agents or ())
        # load() before the chain is mounted only stores the order. OrderedChain
        # skips drawing while ``is_mounted`` is false, including during its own
        # on_mount, so the screen draws the rows once the chain is up.
        chain.load(self._loaded_agents)
        allowed = set(saved.allowed)
        setup = Button("Set up Telegram…", id="ib-telegram")
        setup.display = not self._token
        empty = Static(
            "" if self._private else "No private chats yet.",
            id="ib-chats-empty",
            markup=False,
        )
        empty.display = not self._private
        yield Vertical(
            VerticalScroll(
                Label("Telegram"),
                Static(
                    "No bot yet" if not self._token else "Checking the saved bot…",
                    id="ib-bot",
                    markup=False,
                ),
                setup,
                Label("Allowed chats"),
                empty,
                Vertical(
                    *[
                        Checkbox(
                            Text(f"{label}  ({cid})"),
                            value=cid in allowed,
                            id=f"ib-chat-{cid}",
                        )
                        for cid, label in self._private
                    ],
                    id="ib-chats",
                ),
                Label("Score and brainstorm agents"),
                chain,
                *[
                    Checkbox(Text(reason), value=False, disabled=True, id=f"ib-blocked-{name}")
                    for name, reason in _blocked(self._offered)
                ],
                Label("Assistant"),
                Select(
                    agent_options,
                    value=assistant_value if assistant_value is not None else Select.BLANK,
                    allow_blank=assistant_value is None,
                    prompt="Assistant",
                    id="ib-assistant",
                ),
                Label("Assistant backup"),
                Select(
                    [("None", "none"), *agent_options],
                    value=backup_value,
                    allow_blank=False,
                    id="ib-backup",
                ),
                Label("Documents"),
                Select(
                    [("Word", "word"), ("PDF", "pdf"), ("Both", "both")],
                    value=documents,
                    allow_blank=False,
                    id="ib-documents",
                ),
                Label("Service"),
                Select(
                    [("On", "on"), ("Off", "off")],
                    value="on" if saved.service_on else "off",
                    allow_blank=False,
                    id="ib-service",
                ),
                Static("", id="ib-status", markup=False),
                Label("Check"),
                Static("", id="ib-checks", markup=False),
                id="ib-body",
            ),
            Static("", id="ib-message", markup=False, classes="-empty"),
            Horizontal(
                Button("Check", id="ib-check"),
                Button("Save", id="ib-save", variant="success"),
                Button("Cancel", id="ib-cancel"),
                id="ib-buttons",
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#ib-status", Static).update(_plain(_status_text()))
        self.call_after_refresh(self._show_chain)
        if self._token:
            self._name_bot()

    def _show_chain(self) -> None:
        if self._closed:
            return
        try:
            chain = self.query_one("#ib-agents", OrderedChain)
        except NoMatches:
            return
        # A click on None or Automatic may already have drawn the rows.
        if chain.query("#chain-rows Checkbox"):
            return
        chain.load(self._loaded_agents)

    def on_unmount(self) -> None:
        self._closed = True

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        button_id = event.button.id
        if button_id == "ib-check":
            event.stop()
            self._show_checks(_doctor_text())
        elif button_id == "ib-save":
            event.stop()
            self._save()
        elif button_id == "ib-cancel":
            event.stop()
            self._closed = True
            self.dismiss(None)
        elif button_id == "ib-telegram":
            event.stop()
            self._setup()

    def _save(self) -> None:
        saved = _read_saved()
        assistant = _choice(self.query_one("#ib-assistant", Select))
        backup = _choice(self.query_one("#ib-backup", Select))
        if backup == "none":
            backup = None
        if assistant and backup and assistant == backup:
            self._show_message(f"{backup}: backup is the same agent")
            return
        if (assistant != saved.assistant or backup != saved.backup) and not assistant:
            self._show_message("assistant needs an agent")
            return
        error = self._apply(saved, assistant, backup)
        self.query_one("#ib-status", Static).update(_plain(_status_text()))
        self._show_checks(_doctor_text())
        self._show_message(error)

    def _apply(self, saved: _Saved, assistant: str | None, backup: str | None) -> str:
        errors: list[str] = []
        errors.extend(self._save_chats(saved))
        errors.extend(self._save_agents(saved))
        message = self._save_assistant(saved, assistant, backup)
        if message:
            errors.append(message)
        message = self._save_documents(saved)
        if message:
            errors.append(message)
        message = self._save_service(saved)
        if message:
            errors.append(message)
        return " ".join(errors)

    def _checked_chats(self) -> list[int]:
        checked = []
        for cid, _label in self._private:
            if self.query_one(f"#ib-chat-{cid}", Checkbox).value:
                checked.append(cid)
        return checked

    def _save_chats(self, saved: _Saved) -> list[str]:
        from whyline.ideas import store, telegram_in

        shown = {cid for cid, _label in self._private}
        ui = self._checked_chats()
        allow_ids = [cid for cid in ui if cid not in saved.allowed]
        deny_ids = [cid for cid in saved.allowed if cid in shown and cid not in ui]
        if not allow_ids and not deny_ids:
            return []
        conn = store.connect()
        try:
            for cid in allow_ids:
                telegram_in.allow(conn, cid)
            for cid in deny_ids:
                telegram_in.deny(conn, cid)
        except telegram_in.AllowError as exc:
            return [str(exc)]
        finally:
            conn.close()
        return []

    def _save_agents(self, saved: _Saved) -> list[str]:
        from whyline.ideas import cli

        offered = set(self._offered)
        current = self.query_one("#ib-agents", OrderedChain).order()
        # Unknown stored names stay disabled on the chain and are not part of
        # order(). Leaving them out of this comparison keeps an untouched
        # chain from rewriting the key.
        known = [name for name in (saved.agents or ()) if name in offered]
        if current == known:
            return []
        message = _run(cli.cmd_agents, argparse.Namespace(names=current))
        return [message] if message else []

    def _save_assistant(
        self, saved: _Saved, assistant: str | None, backup: str | None
    ) -> str:
        if assistant == saved.assistant and backup == saved.backup:
            return ""
        if not assistant:
            return "assistant needs an agent"
        from whyline.ideas import assistant as assistant_mod
        from whyline.ideas import store

        conn = store.connect()
        try:
            try:
                if backup is None:
                    # save() with no backup leaves the stored backup in place.
                    assistant_mod.save(conn, assistant)
                    if saved.backup:
                        conn.execute(
                            "DELETE FROM kv WHERE key = ?",
                            (assistant_mod.BACKUP_KEY,),
                        )
                else:
                    assistant_mod.save(conn, assistant, backup)
            except assistant_mod.AssistantError as exc:
                return str(exc)
        finally:
            conn.close()
        return ""

    def _save_documents(self, saved: _Saved) -> str:
        from whyline.ideas import cli

        chosen = _choice(self.query_one("#ib-documents", Select)) or "both"
        effective = saved.documents if saved.documents in _FORMATS else "both"
        if chosen == effective:
            return ""
        message = _run(cli.cmd_documents, argparse.Namespace(format=chosen))
        return message

    def _save_service(self, saved: _Saved) -> str:
        from whyline.ideas import cli

        on = _choice(self.query_one("#ib-service", Select)) == "on"
        if on == saved.service_on:
            return ""
        return _run(
            cli.cmd_service,
            argparse.Namespace(idea_service_command="on" if on else "off"),
        )

    def _show_message(self, text: str) -> None:
        widget = self.query_one("#ib-message", Static)
        widget.update(_plain(text) if text else "")
        widget.set_class(not text, "-empty")

    def _show_checks(self, text: str) -> None:
        self.query_one("#ib-checks", Static).update(_plain(text))

    def _name_bot(self) -> None:
        token = self._token
        if not token:
            return
        generation = self._generation
        app = self.app

        def work() -> None:
            from whyline.agents import telegram
            from whyline.ideas.cli import _no_wait

            try:
                text = telegram.redact(str(telegram.check_token(token, sleep=_no_wait)), token)
            except Exception as exc:
                text = telegram.redact(str(exc), token) or "Something went wrong."
            self._later(app, generation, text)

        app.run_worker(work, thread=True)

    def _later(self, app, generation: int, text: str) -> None:
        def apply() -> None:
            if self._closed or generation != self._generation:
                return
            try:
                self.query_one("#ib-bot", Static).update(_plain(text))
            except NoMatches:
                return

        try:
            app.call_from_thread(apply)
        except RuntimeError:
            pass

    def _setup(self) -> None:
        from whyline.console.agents_screens import TelegramSetupScreen

        self.app.push_screen(TelegramSetupScreen(), self._telegram_done)

    def _telegram_done(self, _chats) -> None:
        if self._closed:
            return
        from whyline.agents import telegram

        self._generation += 1
        self._token = telegram.token_get()
        button = self.query_one("#ib-telegram", Button)
        button.display = not self._token
        if not self._token:
            self.query_one("#ib-bot", Static).update(_plain("No bot yet"))
            return
        self.query_one("#ib-bot", Static).update(_plain("Checking the saved bot…"))
        self._name_bot()
