"""Inbox settings for Agents mode.

The same writes as ``whyline idea``: allow and deny a chat, the default
agents, the assistant pair, document format, and service on or off.
Check prints the same lines as ``whyline idea doctor``.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sqlite3
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from whyline.console.chain_editor import OrderedChain

_FORMATS = ("word", "pdf", "both")
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


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
    repos: dict[str, str] = field(default_factory=dict)
    email_allow: tuple[str, ...] = field(default_factory=tuple)
    email_authserv: str | None = None


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
        return _Saved((), None, None, None, None, False, {}, (), None)
    from whyline.ideas import assistant, cli, email_in, setup, telegram_in, worker

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
            repos=setup.list_repos(conn),
            email_allow=tuple(email_in.allowed_senders(conn)),
            email_authserv=email_in.configured_authserv(conn),
        )
    finally:
        conn.close()


def _offered() -> list[str]:
    from whyline.agents import capabilities, definitions
    from whyline.ideas import cli

    return [
        name
        for name in definitions.CLIS
        if capabilities.can_run_unattended(name) and cli._subscription_enabled(name)
    ]


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


def _mail_rule_text(name: str, path) -> str:
    shown = path.as_posix() if hasattr(path, "as_posix") else str(path)
    return (
        f"Wrote {shown}\n"
        "In Mail → Settings → Rules → Add Rule, set the conditions "
        "(From is the allowed sender), then Run AppleScript → "
        f"choose whyline-{name}.applescript."
    )


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
    IdeaInboxScreen #ib-repos { height: auto; }
    IdeaInboxScreen #ib-repo-add-row { height: auto; }
    IdeaInboxScreen #ib-repo-name { width: 20; }
    IdeaInboxScreen #ib-repo-path { width: 1fr; }
    IdeaInboxScreen .ib-repo-row { height: auto; }
    IdeaInboxScreen .ib-repo-label { width: 1fr; padding: 1 0; }
    IdeaInboxScreen #ib-emails { height: auto; }
    IdeaInboxScreen #ib-email-add-row { height: auto; }
    IdeaInboxScreen #ib-email-address { width: 1fr; }
    IdeaInboxScreen .ib-email-row { height: auto; }
    IdeaInboxScreen .ib-email-label { width: 1fr; padding: 1 0; }
    IdeaInboxScreen #ib-email-authserv { width: 1fr; }
    IdeaInboxScreen #ib-mail-result { height: auto; }
    """

    def __init__(self, *, install=None) -> None:
        super().__init__()
        self._install = install
        self._token: str | None = None
        self._private: list[tuple[int, str]] = []
        self._offered: list[str] = []
        self._loaded_agents: list[str] = []
        self._generation = 0
        self._closed = False
        self._repo_remove_buttons: dict[str, str] = {}
        self._email_remove_buttons: dict[str, str] = {}

    @staticmethod
    def _repo_remove_id(name: str) -> str:
        if _SAFE_ID_RE.match(name):
            return f"ib-repo-remove-{name}"
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
        return f"ib-repo-remove-safe-{digest}"

    def _make_repo_remove_button(self, name: str) -> Button:
        btn_id = self._repo_remove_id(name)
        self._repo_remove_buttons[btn_id] = name
        return Button("Remove", id=btn_id, name=name, classes="ib-repo-remove")

    def repo_remove_button(self, name: str) -> Button:
        btn_id = self._repo_remove_id(name)
        return self.query_one(f"#{btn_id}", Button)

    @staticmethod
    def _email_remove_id(address: str) -> str:
        if _SAFE_ID_RE.match(address):
            return f"ib-email-remove-{address}"
        digest = hashlib.sha256(address.encode("utf-8")).hexdigest()[:12]
        return f"ib-email-remove-safe-{digest}"

    def _make_email_remove_button(self, address: str) -> Button:
        btn_id = self._email_remove_id(address)
        self._email_remove_buttons[btn_id] = address
        return Button("Remove", id=btn_id, name=address, classes="ib-email-remove")

    def email_remove_button(self, address: str) -> Button:
        btn_id = self._email_remove_id(address)
        return self.query_one(f"#{btn_id}", Button)

    def compose(self) -> ComposeResult:
        from whyline.agents import mail, telegram
        from whyline.ideas import email_in, telegram_in

        saved = _read_saved()
        mail_ok = mail.supported()
        mail_btn = Button("Install Mail rule…", id="ib-mail-script")
        mail_btn.disabled = not mail_ok
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
                Label("Repositories"),
                Vertical(
                    *[
                        Horizontal(
                            Label(f"{name}: {path}", classes="ib-repo-label"),
                            self._make_repo_remove_button(name),
                            classes="ib-repo-row",
                        )
                        for name, path in sorted(saved.repos.items())
                    ],
                    id="ib-repos",
                ),
                Horizontal(
                    Input(placeholder="Name", id="ib-repo-name"),
                    Input(placeholder="Path", id="ib-repo-path"),
                    Button("Add", id="ib-repo-add"),
                    id="ib-repo-add-row",
                ),
                Label("Email"),
                Vertical(
                    *[
                        Horizontal(
                            Label(address, classes="ib-email-label"),
                            self._make_email_remove_button(address),
                            classes="ib-email-row",
                        )
                        for address in sorted(saved.email_allow)
                    ],
                    id="ib-emails",
                ),
                Horizontal(
                    Input(placeholder="user@example.com", id="ib-email-address"),
                    Button("Add", id="ib-email-add"),
                    id="ib-email-add-row",
                ),
                mail_btn,
                Static(
                    mail.NEEDS_MACOS if not mail_ok else "",
                    id="ib-mail-result",
                    markup=False,
                ),
                Label("Email provider check"),
                Input(
                    saved.email_authserv or "",
                    placeholder=", ".join(email_in.AUTHSERV_HINTS),
                    id="ib-email-authserv",
                ),
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
        elif button_id == "ib-repo-add":
            event.stop()
            self._add_repo()
        elif button_id and (
            button_id in self._repo_remove_buttons
            or button_id.startswith("ib-repo-remove-")
        ):
            event.stop()
            repo_name = self._repo_remove_buttons.get(button_id)
            if repo_name is None and getattr(event.button, "name", None):
                repo_name = event.button.name
            if repo_name is None and button_id.startswith("ib-repo-remove-"):
                repo_name = button_id[len("ib-repo-remove-"):]
            if repo_name:
                self._remove_repo(repo_name)
        elif button_id == "ib-mail-script":
            event.stop()
            self._install_mail()
        elif button_id == "ib-email-add":
            event.stop()
            self._add_email()
        elif button_id and (
            button_id in self._email_remove_buttons
            or button_id.startswith("ib-email-remove-")
        ):
            event.stop()
            email_addr = self._email_remove_buttons.get(button_id)
            if email_addr is None and getattr(event.button, "name", None):
                email_addr = event.button.name
            if email_addr is None and button_id.startswith("ib-email-remove-"):
                email_addr = button_id[len("ib-email-remove-"):]
            if email_addr:
                self._remove_email(email_addr)

    def _install_mail(self) -> None:
        from whyline.agents import mail

        if not mail.supported():
            self._show_mail(mail.NEEDS_MACOS)
            return
        fn = self._install or mail.install
        try:
            path = fn("idea")
        except (RuntimeError, OSError, ValueError) as error:
            self._show_mail(str(error))
            return
        self._show_mail(_mail_rule_text("idea", path))

    def _show_mail(self, text: str) -> None:
        self.query_one("#ib-mail-result", Static).update(_plain(text) if text else "")

    def _add_email(self) -> None:
        from whyline.ideas import email_in, store

        address = self.query_one("#ib-email-address", Input).value.strip()
        if not address:
            self._show_message("email address is required")
            return
        conn = store.connect()
        try:
            try:
                email_in.allow(conn, address)
            except email_in.AllowError as exc:
                self._show_message(str(exc))
                return
        finally:
            conn.close()
        self.query_one("#ib-email-address", Input).value = ""
        self._show_message("")
        self._refresh_emails()

    def _remove_email(self, address: str) -> None:
        from whyline.ideas import email_in, store

        conn = store.connect()
        try:
            email_in.deny(conn, address)
        finally:
            conn.close()
        self._show_message("")
        self._refresh_emails()

    def _refresh_emails(self) -> None:
        from whyline.ideas import email_in, store

        conn = store.connect()
        try:
            senders = email_in.allowed_senders(conn)
        finally:
            conn.close()
        container = self.query_one("#ib-emails", Vertical)
        container.remove_children()
        self._email_remove_buttons.clear()
        for address in sorted(senders):
            container.mount(
                Horizontal(
                    Label(address, classes="ib-email-label"),
                    self._make_email_remove_button(address),
                    classes="ib-email-row",
                )
            )

    def _add_repo(self) -> None:
        from whyline.ideas import setup, store

        name = self.query_one("#ib-repo-name", Input).value.strip()
        path = self.query_one("#ib-repo-path", Input).value.strip()
        if not name or not path:
            self._show_message("repository name and path are required")
            return
        conn = store.connect()
        try:
            try:
                setup.add_repo(conn, name, path)
            except setup.SetupError as exc:
                self._show_message(str(exc))
                return
        finally:
            conn.close()
        self.query_one("#ib-repo-name", Input).value = ""
        self.query_one("#ib-repo-path", Input).value = ""
        self._show_message("")
        self._refresh_repos()

    def _remove_repo(self, name: str) -> None:
        from whyline.ideas import setup, store

        conn = store.connect()
        try:
            try:
                setup.remove_repo(conn, name)
            except setup.SetupError as exc:
                self._show_message(str(exc))
                return
        finally:
            conn.close()
        self._show_message("")
        self._refresh_repos()

    def _refresh_repos(self) -> None:
        from whyline.ideas import setup, store

        conn = store.connect()
        try:
            repos = setup.list_repos(conn)
        finally:
            conn.close()
        container = self.query_one("#ib-repos", Vertical)
        container.remove_children()
        self._repo_remove_buttons.clear()
        for name, path in sorted(repos.items()):
            container.mount(
                Horizontal(
                    Label(f"{name}: {path}", classes="ib-repo-label"),
                    self._make_repo_remove_button(name),
                    classes="ib-repo-row",
                )
            )

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
        message = self._save_authserv(saved)
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
        from whyline.ideas import cli as idea_cli

        if assistant and not idea_cli._subscription_enabled(assistant):
            return idea_cli._enable_hint(assistant)
        if backup and not idea_cli._subscription_enabled(backup):
            return idea_cli._enable_hint(backup)
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

    def _save_authserv(self, saved: _Saved) -> str:
        from whyline.ideas import email_in, store

        value = self.query_one("#ib-email-authserv", Input).value.strip()
        current = (saved.email_authserv or "").strip()
        if value == current or not value:
            return ""
        conn = store.connect()
        try:
            try:
                email_in.set_authserv(conn, value)
            except ValueError as exc:
                return str(exc)
        finally:
            conn.close()
        return ""

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
