"""Transactional Settings modal: which AI subscriptions Whyline may use.

The constructor takes cached account records plus two injected callables:
one provider check, and one atomic write of the four staged booleans plus
any completed staged results. This module does not import the main console
app, and it never calls a provider from ``__init__``, ``compose``, or
synchronously from ``on_mount``.
"""

from __future__ import annotations

from typing import Callable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from whyline import relaysafety

PROVIDERS = ("claude", "codex", "grok", "antigravity")
_PATH_ONLY = frozenset({"grok", "antigravity"})
_DISPLAY = {
    "claude": "Claude",
    "codex": "Codex",
    "grok": "Grok",
    "antigravity": "Antigravity",
}
_HINT = "Disabled providers are not checked or shown in agent choices."
_NOT_USED = "Not used by Whyline"
_NOT_CHECKED = "Not checked yet"
_CHECKING = "Checking…"
_NOT_INSTALLED = "Not installed"
_PATH_READY = "Installed · login not automatically verified"


def _one_line(text: object) -> str:
    return " ".join(str(text).split())


def _is_enabled(record: dict) -> bool:
    if "enabled" in record:
        return bool(record["enabled"])
    return bool(record.get("available"))


def _has_detection(result: dict) -> bool:
    return any(
        key in result for key in ("available", "plan", "reason", "auth_mode", "auth_method")
    )


def _looks_missing(reason: str) -> bool:
    lowered = reason.lower()
    return (
        "not found" in lowered
        or "could not run" in lowered
        or "no such file" in lowered
    )


def format_provider_status(agent: str, result: object) -> str:
    """Plain-text row label for a cached record or a completed check."""
    if not isinstance(result, dict) or not _has_detection(result):
        return _NOT_CHECKED
    if agent in _PATH_ONLY:
        if result.get("available"):
            return _PATH_READY
        return _NOT_INSTALLED
    plan = result.get("plan")
    reason = _one_line(result.get("reason") or "")
    available = result.get("available")
    if available is False or plan == "unknown":
        if not reason or _looks_missing(reason):
            return _NOT_INSTALLED
        return reason
    if plan is None:
        return "API key"
    pretty = _one_line(plan)
    if not pretty:
        return "Ready"
    pretty = pretty[:1].upper() + pretty[1:]
    return f"{pretty} · Ready"


class ProviderSettingsScreen(ModalScreen):
    """Choose which providers Whyline may use; Save writes, Cancel does not."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ProviderSettingsScreen { align: center middle; }
    ProviderSettingsScreen > Vertical {
        width: 78; max-width: 100%; height: auto; max-height: 100%;
        padding: 0 1; border: thick $accent; background: $surface;
    }
    /* 1fr does nothing in an auto-height popup and once pushed the
       buttons off a 24-row terminal. Cap the provider body; the title,
       error line, and buttons stay after it. */
    ProviderSettingsScreen #ss-body { height: auto; max-height: 10; }
    ProviderSettingsScreen #ss-error { height: auto; color: $error; }
    ProviderSettingsScreen #ss-hint { height: auto; color: $text-muted; }
    ProviderSettingsScreen #ss-buttons { height: auto; margin-top: 1; }
    ProviderSettingsScreen #ss-buttons Button { margin-right: 1; min-width: 8; width: auto; }
    ProviderSettingsScreen Horizontal { height: auto; }
    ProviderSettingsScreen .ss-row { height: auto; }
    ProviderSettingsScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; width: 16; }
    ProviderSettingsScreen Checkbox:focus { border: none; }
    ProviderSettingsScreen .ss-status { width: 1fr; height: auto; padding: 0 1; }
    ProviderSettingsScreen Select { width: 1fr; }
    ProviderSettingsScreen Input { width: 12; }
    ProviderSettingsScreen .ss-chat-label { width: 36; padding: 0 1; }
    """

    def __init__(
        self,
        records: dict | None,
        check_provider: Callable[[str], dict],
        save_enabled: Callable[[dict, dict | None], None],
        chat: dict | None = None,
        save_chat: Callable[[dict], object] | None = None,
        safety: dict | None = None,
        save_safety: Callable[..., object] | None = None,
    ) -> None:
        """``chat`` shows the Relay chat section: ``choices`` (agent names),
        ``agent`` (str | None), ``timeout_seconds`` and ``snapshot_chars``.
        ``save_chat`` receives only the values changed, as ``relaychat.settings.save``
        keyword names. ``safety`` shows the Relay safety section: ``battery_percent``
        (int | None), ``on_wake`` and ``on_quit``; ``save_safety`` takes
        ``relaysafety.save`` keywords."""
        super().__init__()
        self._chat = dict(chat) if chat is not None and save_chat is not None else None
        self._save_chat = save_chat
        self._safety = dict(safety) if safety is not None and save_safety is not None else None
        self._save_safety = save_safety
        raw = records or {}
        self._records = {
            agent: dict(raw[agent]) if isinstance(raw.get(agent), dict) else {}
            for agent in PROVIDERS
        }
        self._check_provider = check_provider
        self._save_enabled = save_enabled
        self._staged = {agent: _is_enabled(self._records[agent]) for agent in PROVIDERS}
        self._completed: dict[str, dict] = {}
        self._token: object = object()

    def compose(self) -> ComposeResult:
        rows = []
        for agent in PROVIDERS:
            enabled = self._staged[agent]
            status = _NOT_USED if not enabled else format_provider_status(
                agent, self._records[agent]
            )
            rows.append(
                Horizontal(
                    Checkbox(_DISPLAY[agent], value=enabled, id=f"ss-{agent}"),
                    Static(status, id=f"ss-status-{agent}", markup=False, classes="ss-status"),
                    classes="ss-row",
                    id=f"ss-row-{agent}",
                )
            )
        yield Vertical(
            Label("Settings", id="ss-title"),
            VerticalScroll(
                Label("AI subscriptions", id="ss-section"),
                Label("Choose only the subscriptions Whyline may use."),
                *rows,
                *self._chat_widgets(),
                *self._safety_widgets(),
                id="ss-body",
            ),
            Static(_HINT, id="ss-hint", markup=False),
            Static("", id="ss-error", markup=False),
            Horizontal(
                Button("Check selected", id="ss-check-selected"),
                Button("Save", id="ss-save", variant="success"),
                Button("Cancel", id="ss-cancel"),
                id="ss-buttons",
            ),
        )

    def _chat_widgets(self) -> list:
        if self._chat is None:
            return []
        chat = self._chat
        choices = [str(name) for name in chat.get("choices") or []]
        agent = chat.get("agent")
        options = [("Automatic", "")] + [(name, name) for name in choices]
        timeout = int(chat.get("timeout_seconds", 0))
        return [
            Label("Relay chat", id="ss-chat-section"),
            Label("Answers questions about a running relay, read-only."),
            Horizontal(
                Label("Agent", classes="ss-chat-label"),
                Select(options, value=agent if agent in choices else "",
                       allow_blank=False, id="ss-chat-agent"),
                classes="ss-row",
            ),
            Horizontal(
                Label("Time limit (minutes, 0 = none)", classes="ss-chat-label"),
                Input(value=_minutes_text(timeout), id="ss-chat-minutes"),
                classes="ss-row",
            ),
            Horizontal(
                Label("Snapshot size (characters)", classes="ss-chat-label"),
                Input(value=str(chat.get("snapshot_chars", "")), id="ss-chat-snapshot"),
                classes="ss-row",
            ),
        ]

    def _chat_changes(self) -> dict:
        """Values that differ from what the section opened with; raises ValueError."""
        if self._chat is None:
            return {}
        changes: dict = {}
        picked = self.query_one("#ss-chat-agent", Select).value
        picked = picked if isinstance(picked, str) and picked else None
        shown = self._chat.get("agent")
        if shown not in (self._chat.get("choices") or []):
            shown = None  # the saved agent isn't installed, so Automatic was shown
        if picked != shown:
            changes["agent"] = picked
        text = self.query_one("#ss-chat-minutes", Input).value.strip()
        if text != _minutes_text(int(self._chat.get("timeout_seconds", 0))):
            if not text.isdecimal():
                raise ValueError("Time limit must be a whole number of minutes (0 means none).")
            changes["timeout_seconds"] = int(text) * 60
        text = self.query_one("#ss-chat-snapshot", Input).value.strip()
        if text != str(self._chat.get("snapshot_chars", "")):
            if not text.isdecimal():
                raise ValueError("Snapshot size must be a whole number of characters.")
            changes["snapshot_chars"] = int(text)
        return changes

    def _safety_widgets(self) -> list:
        if self._safety is None:
            return []
        safety = self._safety
        return [
            Label("Relay safety", id="ss-safety-section"),
            Label("Safeguards that pause a running relay. See docs/safe-pause.md."),
            Horizontal(
                Label("Battery limit (off, 10, 15, 20, 25 or a number)", classes="ss-chat-label"),
                Input(value=_battery_text(safety.get("battery_percent")), id="ss-safety-battery"),
                classes="ss-row",
            ),
            Horizontal(
                Label("When the Mac wakes", classes="ss-chat-label"),
                Select([(name, name) for name in relaysafety.ON_WAKE_CHOICES],
                       value=safety.get("on_wake", "ask"), allow_blank=False,
                       id="ss-safety-wake"),
                classes="ss-row",
            ),
            Horizontal(
                Label("When quitting", classes="ss-chat-label"),
                Select([(name, name) for name in relaysafety.ON_QUIT_CHOICES],
                       value=safety.get("on_quit", "ask"), allow_blank=False,
                       id="ss-safety-quit"),
                classes="ss-row",
            ),
        ]

    def _safety_changes(self) -> dict:
        """Values that differ from what the section opened with; raises ValueError."""
        if self._safety is None:
            return {}
        changes: dict = {}
        text = self.query_one("#ss-safety-battery", Input).value.strip()
        if text != _battery_text(self._safety.get("battery_percent")):
            if text.lower() == "off":
                changes["battery_percent"] = None
            elif text.isdecimal() and 1 <= int(text) <= 99:
                changes["battery_percent"] = int(text)
            else:
                raise ValueError("Battery limit must be off or a whole number from 1 to 99.")
        for key, widget in (("on_wake", "#ss-safety-wake"), ("on_quit", "#ss-safety-quit")):
            picked = self.query_one(widget, Select).value
            if picked != self._safety.get(key):
                changes[key] = picked
        return changes

    def on_mount(self) -> None:
        self.call_after_refresh(self._check_currently_staged)

    def action_cancel(self) -> None:
        self._abandon()
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "ss-cancel":
            self.action_cancel()
        elif event.button.id == "ss-save":
            self._save()
        elif event.button.id == "ss-check-selected":
            self._check_selected()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        agent = _checkbox_agent(event.checkbox.id)
        if agent is None:
            return
        event.stop()
        now = bool(event.value)
        if self._staged[agent] == now:
            return
        self._staged[agent] = now
        if now:
            self._set_status(agent, _NOT_CHECKED)
            self._start_check(agent)
        else:
            self._set_status(agent, _NOT_USED)

    def _check_currently_staged(self) -> None:
        if not self.is_attached:
            return
        for agent in PROVIDERS:
            if self._staged[agent]:
                self._set_status(agent, _CHECKING)
                self._start_check(agent)

    def _check_selected(self) -> None:
        self._token = object()
        self._set_error("")
        for agent in PROVIDERS:
            if self._staged[agent]:
                self._set_status(agent, _CHECKING)
                self._start_check(agent)
            else:
                self._set_status(agent, _NOT_USED)

    def _start_check(self, agent: str) -> None:
        token = self._token
        def work() -> None:
            if token is not self._token or not self._staged.get(agent):
                return
            try:
                result = self._check_provider(agent)
            except Exception as error:
                result = {
                    "available": False,
                    "plan": "unknown",
                    "reason": str(error) or error.__class__.__name__,
                }
            try:
                self.app.call_from_thread(self._apply_result, agent, result, token)
            except Exception:
                return

        self.run_worker(work, thread=True, group=f"settings-{agent}")

    def _apply_result(self, agent: str, result: object, token: object) -> None:
        if token is not self._token:
            return
        payload = dict(result) if isinstance(result, dict) else {"reason": str(result)}
        self._completed[agent] = payload
        if not self._staged.get(agent) or not self.is_attached:
            return
        try:
            self._set_status(agent, format_provider_status(agent, payload))
        except NoMatches:
            return

    def _save(self) -> None:
        values = {agent: bool(self._staged[agent]) for agent in PROVIDERS}
        completed = {agent: dict(result) for agent, result in self._completed.items()}
        button = self.query_one("#ss-save", Button)
        button.disabled = True
        saved_chat = saved_safety = False
        try:
            changes = self._chat_changes()
            safety_changes = self._safety_changes()
            if changes:
                self._save_chat(changes)
                saved_chat = True
            if safety_changes:
                self._save_safety(**safety_changes)
                saved_safety = True
            self._save_enabled(values, completed)
        except Exception as error:
            if saved_chat:
                before = {name: self._chat.get(name) for name in changes}
                try:
                    self._save_chat(before)
                except Exception:
                    pass
            if saved_safety:
                before = {name: self._safety.get(name) for name in safety_changes}
                try:
                    self._save_safety(**before)
                except Exception:
                    pass
            button.disabled = False
            self._set_error(str(error) or error.__class__.__name__)
            return
        enabled = {agent for agent, on in values.items() if on}
        self._abandon()
        self.dismiss(enabled)

    def _abandon(self) -> None:
        self._token = object()

    def _set_status(self, agent: str, text: str) -> None:
        if not self.is_attached:
            return
        try:
            self.query_one(f"#ss-status-{agent}", Static).update(text)
        except NoMatches:
            return

    def _set_error(self, text: str) -> None:
        if not self.is_attached:
            return
        try:
            self.query_one("#ss-error", Static).update(_one_line(text) if text else "")
        except NoMatches:
            return


def _battery_text(value: object) -> str:
    return "off" if value is None else str(value)


def _minutes_text(seconds: int) -> str:
    return str(seconds // 60) if seconds % 60 == 0 else f"{seconds / 60:g}"


def _checkbox_agent(widget_id: str | None) -> str | None:
    if widget_id is None or not widget_id.startswith("ss-"):
        return None
    agent = widget_id[3:]
    return agent if agent in PROVIDERS else None
