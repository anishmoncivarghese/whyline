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
from textual.widgets import Button, Checkbox, Label, Static

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
    """

    def __init__(
        self,
        records: dict | None,
        check_provider: Callable[[str], dict],
        save_enabled: Callable[[dict, dict | None], None],
    ) -> None:
        super().__init__()
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
        try:
            self._save_enabled(values, completed)
        except Exception as error:
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


def _checkbox_agent(widget_id: str | None) -> str | None:
    if widget_id is None or not widget_id.startswith("ss-"):
        return None
    agent = widget_id[3:]
    return agent if agent in PROVIDERS else None
