"""whyline console's mouse-enabled TUI, built on Textual.

Import-guarded exactly like editor.py guards prompt_toolkit, so the rest
of the console package stays importable and testable without the [ui]
extra installed. Reuses ConsoleSession/SessionEvent/adapters.py and
repl.py's dispatch() completely unchanged -- this module is a rendering
layer, not a second implementation of the console's logic.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

try:
    from textual import events
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.css.query import NoMatches
    from textual.message import Message
    from textual.screen import ModalScreen
    from rich.text import Text
    from textual.widgets import (
        Button, Checkbox, Footer, Header, Input, Label, RichLog, Select, Static,
    )
    from textual.widgets._select import SelectOverlay

    TUI_AVAILABLE = True
except ImportError:
    App = ModalScreen = Input = Message = object  # placeholder bases so the classes can still be defined
    NoMatches = LookupError
    ComposeResult = None
    Horizontal = Vertical = VerticalScroll = None
    Button = Checkbox = Footer = Header = Label = RichLog = Select = None
    Static = Text = None
    events = None
    TUI_AVAILABLE = False

from whyline.console import (
    adapters,
    attachments as att,
    mac_input,
    plan_job,
    relay_ops,
    repo_setup,
)
from whyline.console.attachments_ui import (
    AttachMenuScreen,
    AttachmentTray,
    AttachmentsField,
    needs_warning,
    status_text,
)
from whyline.console.relay_process import RelayProcess
from whyline.console.repl import (
    BRAINSTORM_AGENTS,
    _HOME_REFUSAL,
    _agents_command as agents_command_event,
    _is_home,
    _run_login,
    after_login,
    busy_label,
    dispatch,
    handle_slash_command,
    home_repo_warning,
    login_argv,
    named_row,
    repo_switch_warning,
    run_result_text,
    switch_repo,
    unknown_command_text,
)
from whyline.console.session import ConsoleSession, SessionEvent

_PREFIX = {"error": "⚠ ", "pause": "⏸ ", "input": "› "}

_MODES = ("chat", "relay", "agents")
# Agents widgets arrive with the Agents plan. Until then these ids match nothing.
_MODE_BUTTONS = {
    "chat": ("model", "brainstorm", "history"),
    "relay": ("relay-run", "relay-plan", "relay-setup", "relay-resume"),
    "agents": ("agents-new", "agents-list", "agents-runs", "agents-scheduler"),
}
_SHARED_BUTTONS = ("stop", "help", "copy")
_SLASH_HINT = "/status /timeline /note /decisions /handoff /model /repo /help"

# Brainstorming makes one full agent turn per selected model and phase. Keep
# the bound explicit in the UI so a single stalled provider cannot hold the
# whole console indefinitely.
BRAINSTORM_TIMEOUT_OPTIONS = (15, 30, 45, 60)

# Native clipboard commands, tried in order. OSC 52 (what Textual's
# copy_to_clipboard sends) is ignored by several terminals -- macOS Terminal
# among them, and iTerm2 unless enabled -- so it said "copied" while nothing
# reached the clipboard.
_CLIPBOARD_COMMANDS = (
    ["pbcopy"],
    ["wl-copy"],
    ["xclip", "-selection", "clipboard"],
    ["xsel", "--clipboard", "--input"],
    ["clip"],
)


def _system_copy(text: str) -> bool:
    """Put `text` on the system clipboard with the platform's own command;
    False when none is available or it failed."""
    for argv in _CLIPBOARD_COMMANDS:
        if shutil.which(argv[0]) is None:
            continue
        try:
            result = subprocess.run(argv, input=text, text=True, capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return True
    return False
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _short_path(path: Path) -> str:
    """`~/proj` when `path` is under the home directory, else a posix path."""
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        resolved = Path(path)
    try:
        home = Path.home().resolve()
    except OSError:
        return resolved.as_posix()
    shown = resolved.as_posix()
    home_s = home.as_posix()
    if shown == home_s:
        return "~"
    prefix = home_s + "/"
    if shown.startswith(prefix):
        return "~/" + shown[len(prefix):]
    return shown


# The dropdown is narrow; /model keeps the full wording.
_CB_SHORT_LABELS = {"installed (login not checked)": "login unchecked"}


def _cb_options(status: dict) -> list[tuple[str, str]]:
    """Available agents first, then unavailable ones with a `!` value."""
    available: list[tuple[str, str]] = []
    unavailable: list[tuple[str, str]] = []
    for agent, info in status.items():
        detail = info.get("label", "")
        label = f"{agent} · {_CB_SHORT_LABELS.get(detail, detail)}"
        if info.get("available"):
            available.append((label, agent))
        else:
            unavailable.append((label, f"!{agent}"))
    return available + unavailable


def _cb_status_key(status: dict) -> tuple[tuple[str, bool, str], ...]:
    """Availability and labels. The saved agent, model and repo are separate."""
    key = []
    for agent, info in status.items():
        if not isinstance(info, dict):
            info = {}
        key.append((str(agent), bool(info.get("available")), str(info.get("label") or "")))
    return tuple(key)


def _cb_match_option(current: object, options: list[tuple[str, str]]) -> str:
    """The same agent in `options`, keeping or dropping the unavailable `!`."""
    values = [value for _label, value in options]
    if isinstance(current, str):
        name = current[1:] if current.startswith("!") else current
        for candidate in (name, f"!{name}"):
            if candidate in values:
                return candidate
    return options[0][1]


def _model_rejected(value: str) -> bool:
    """A model name has no spaces or quotes, the same rule the bar enforces."""
    return any(ch.isspace() or ch in "\"'" for ch in value)


class ConfirmScreen(ModalScreen):
    """A yes/no dialog; dismisses with True only for the confirm button."""

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical {
        width: 70; height: auto; padding: 1 2;
        border: thick $warning; background: $surface;
    }
    ConfirmScreen Label { width: 100%; }
    ConfirmScreen Horizontal { height: auto; margin-top: 1; }
    ConfirmScreen Button { margin-right: 2; }
    """

    def __init__(self, message: str, confirm_label: str, cancel_label: str = "Cancel") -> None:
        super().__init__()
        self._message = message
        self._confirm_label = confirm_label
        self._cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self._message),
            Horizontal(
                Button(self._confirm_label, id="confirm", variant="warning"),
                Button(self._cancel_label, id="cancel"),
            ),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm")


class QuitRelayScreen(ModalScreen):
    """Asked on quit while the relay is running: leave it running, stop it
    after the current agent, or stay."""

    DEFAULT_CSS = """
    QuitRelayScreen { align: center middle; }
    QuitRelayScreen > Vertical {
        width: 70; height: auto; padding: 1 2; border: thick $warning; background: $surface;
    }
    QuitRelayScreen Horizontal { height: auto; margin-top: 1; }
    QuitRelayScreen Button { margin-right: 2; }
    """

    def __init__(self, label: str) -> None:
        super().__init__()
        self._label = label

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(f"The relay is still working ({self._label}). Leave it running?"),
            Horizontal(
                Button("Leave it running", id="quit-leave", variant="primary"),
                Button("Stop it, then quit", id="quit-stop", variant="warning"),
                Button("Cancel", id="quit-cancel"),
            ),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        choices = {"quit-leave": "leave", "quit-stop": "stop"}
        self.dismiss(choices.get(event.button.id))


def brainstorm_field_widgets(
    status: dict, default_final: str, root: Path | None = None, session: str | None = None
) -> list:
    """Topic, models, passes, final writer, timeout, and attachments -- shared by the
    Brainstorm popup and the Plan popup's brainstorm source."""
    boxes = []
    for agent in BRAINSTORM_AGENTS:
        info = status[agent]
        boxes.append(
            Checkbox(f"{agent:<12} {info['label']}", value=info["available"],
                     disabled=not info["available"], id=f"bs-{agent}")
        )
    return [
        Input(placeholder="Topic, e.g. how the relay should handle a failed Codex run",
              id="bs-topic"),
        Label("Models:", classes="field-label"),
        *boxes,
        Horizontal(Label("Review passes:", classes="field-label"), Input("1", id="bs-passes")),
        Horizontal(
            Label("Final write-up:", classes="field-label"),
            Select([(a, a) for a in BRAINSTORM_AGENTS], value=default_final,
                   allow_blank=False, id="bs-final"),
        ),
        Horizontal(
            Label("Per-agent timeout:", classes="field-label"),
            Select([(f"{m} minutes", m) for m in BRAINSTORM_TIMEOUT_OPTIONS],
                   value=15, allow_blank=False, id="bs-timeout"),
        ),
        AttachmentsField(root or Path("."), session or "", id="bs-attachments"),
    ]


def collect_brainstorm(query_one) -> "dict | str":
    """The brainstorm fields' values, or a message saying what's missing.
    `query_one` is the owning screen's query_one."""
    topic = query_one("#bs-topic", Input).value.strip()
    if not topic:
        return "Enter a topic."
    agents = [a for a in BRAINSTORM_AGENTS if query_one(f"#bs-{a}", Checkbox).value]
    if not agents:
        return "Pick at least one model."
    raw = query_one("#bs-passes", Input).value.strip() or "0"
    if not raw.isdigit():
        return "Review passes must be a whole number (0 or more)."
    final = query_one("#bs-final", Select).value
    timeout = query_one("#bs-timeout", Select).value
    if timeout not in BRAINSTORM_TIMEOUT_OPTIONS:
        return "Choose a timeout of 15, 30, 45, or 60 minutes."
    return {
        "topic": topic,
        "agents": agents,
        "passes": int(raw),
        "final_agent": final if final in agents else agents[0],
        "timeout_minutes": timeout,
        "attachments": query_one("#bs-attachments", AttachmentsField).pending.paths(),
    }


class BrainstormScreen(ModalScreen):
    """Collects topic, models, passes and the final model, then dismisses
    with them as a dict (or None when cancelled). Models the user can't use
    are shown, disabled, with the reason -- the same labels /model uses."""

    DEFAULT_CSS = """
    BrainstormScreen { align: center middle; }
    BrainstormScreen > Vertical {
        width: 84; max-width: 100%; height: auto; max-height: 100%; padding: 0 2;
        border: thick $accent; background: $surface;
    }
    BrainstormScreen #bs-fields { height: auto; max-height: 70vh; }  /* 1fr has no effect in an auto-height popup */
    BrainstormScreen Label { width: 100%; }
    BrainstormScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; }
    /* Textual's own :focus rule adds a tall border, which on a one-line
       checkbox covers the label entirely; its label highlight is enough. */
    BrainstormScreen Checkbox:focus { border: none; }
    BrainstormScreen Horizontal { height: auto; }
    BrainstormScreen .field-label { width: 18; padding: 1 1 0 0; }
    BrainstormScreen #bs-passes { width: 10; }
    BrainstormScreen #bs-final { width: 30; }
    BrainstormScreen #bs-timeout { width: 30; }
    BrainstormScreen #bs-error { color: $error; height: auto; }
    BrainstormScreen #bs-error.-empty { display: none; }
    BrainstormScreen #bs-buttons { margin-top: 1; }
    BrainstormScreen #bs-buttons Button { margin-right: 2; }
    """

    def __init__(self, status: dict, active: str) -> None:
        super().__init__()
        self._status = status
        self._usable = [a for a in BRAINSTORM_AGENTS if status[a]["available"]]
        self._default_final = active if active in self._usable else (
            self._usable[0] if self._usable else BRAINSTORM_AGENTS[0]
        )

    def compose(self) -> ComposeResult:
        # Only the fields scroll; the error line and buttons stay pinned
        # below them, so Start can never be pushed out of view.
        fields = VerticalScroll(
            Label("Brainstorm: each model researches on its own, reviews the others, "
                  "then one writes it up in docs/brainstorm/."),
            *brainstorm_field_widgets(
                self._status, self._default_final, self.app.session.root, self.app._attach_session
            ),
            id="bs-fields",
        )
        yield Vertical(
            fields,
            Static("", id="bs-error", classes="-empty"),
            Horizontal(
                Button("Start", id="bs-start", variant="success"),
                Button("Cancel", id="bs-cancel"),
                id="bs-buttons",
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#bs-topic", Input).focus()
        self._sync_attachment_agents()

    def _sync_attachment_agents(self) -> None:
        try:
            field = self.query_one("#bs-attachments", AttachmentsField)
        except Exception:
            return
        agents = [a for a in BRAINSTORM_AGENTS if self.query_one(f"#bs-{a}", Checkbox).value]
        field.set_agents(agents)

    def on_checkbox_changed(self, event: "Checkbox.Changed") -> None:
        if event.checkbox.id and event.checkbox.id.startswith("bs-"):
            self._sync_attachment_agents()

    def on_input_submitted(self, event: "Input.Submitted") -> None:
        event.stop()  # handled here; must not reach the console behind
        self.query_one("#bs-start", Button).press()

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "bs-cancel":
            self.dismiss(None)
            return
        chosen = self.collect()
        if isinstance(chosen, str):
            error = self.query_one("#bs-error", Static)
            error.update(chosen)
            error.remove_class("-empty")
            return
        field = self.query_one("#bs-attachments", AttachmentsField)
        risky = field.needs_confirmation()
        if risky:
            def answered(ok: bool) -> None:
                if ok:
                    self.dismiss(chosen)

            self.app.push_screen(
                ConfirmScreen(
                    f"{', '.join(risky)} get images as file paths only and may not see them.",
                    "Continue",
                ),
                answered,
            )
            return
        self.dismiss(chosen)

    def collect(self) -> "dict | str":
        """The form's values, or a message saying what's missing."""
        return collect_brainstorm(self.query_one)


class TuiUnavailable(RuntimeError):
    """textual is not installed."""


class PromptInput(Input):
    """The console's prompt. A paste that is only dropped files goes to the
    app instead of into the text (console attachments spec, section 2)."""

    class Dropped(Message):
        def __init__(self, text: str, paths: list[Path]) -> None:
            super().__init__()
            self.text, self.paths = text, paths

    def _on_paste(self, event: events.Paste) -> None:
        mode = getattr(getattr(self.app, "session", None), "mode", None)
        paths = att.dropped_paths(event.text) if mode == "chat" else None
        if paths:
            event.stop()
            event.prevent_default()
            self.post_message(self.Dropped(event.text, paths))


def _retire_replaced_agent(repo_root: Path | None, agent_id: str, keep: Path) -> None:
    """Drop the definition and activation a rename left behind.

    Run folders stay under the old id. They are history, not a second agent.
    """
    from whyline.agents import definitions as d, state

    try:
        keep_resolved = keep.resolve()
    except OSError:
        keep_resolved = keep
    for item in d.discover(repo_root):
        if not isinstance(item, d.AgentDef) or item.agent_id != agent_id:
            continue
        try:
            same = item.path.resolve() == keep_resolved
        except OSError:
            same = item.path == keep
        if not same:
            item.path.unlink(missing_ok=True)
    state.remove(state.connect(), agent_id)


def _next_scheduled(rows) -> str:
    """The earliest active agent's next run, for the scheduler status line.

    `next_due` is already `YYYY-MM-DD HH:MM` from service.rows, so the
    string order is the time order. Paused and manual agents are not next.
    """
    chosen: tuple[str, str] | None = None
    for row in rows:
        if row.status != "active" or not row.next_due:
            continue
        label = getattr(row.defn, "label", "")
        if not label:
            continue
        candidate = (row.next_due, label)
        if chosen is None or candidate < chosen:
            chosen = candidate
    if chosen is None:
        return ""
    when, label = chosen
    return f"{label} {when}"


class WhylineConsoleApp(App):
    """The mouse-enabled console. Every widget dispatches through the same
    ConsoleSession/dispatch() path the keyboard REPL already uses."""

    BINDINGS = [("escape", "leave_plan", "Leave plan")]

    # Textual's default Button width is 16 columns; seven of them (Send,
    # Model, Route, History, Stop, Help, Copy) at that width would be
    # wider than an 80-column terminal -- the standard default, and what
    # Textual's own test harness uses. Without this, later buttons are
    # genuinely off-screen, not just visually cramped: real mouse clicks
    # (and Pilot.click in tests) can't reach them at all. Sizing buttons to
    # their label instead of a fixed width keeps the whole row within 80
    # columns comfortably.
    #
    # RichLog, TextArea and Horizontal all default to `height: 1fr` (see
    # Textual's own DEFAULT_CSS for each), so left alone they split the
    # screen into three equal bands: the transcript gets only a third of
    # the space, the prompt box gets a whole band for what is usually one
    # line of text, and the button row -- three rows tall by content --
    # sits inside a band just as tall as the transcript's, leaving a dead
    # strip of empty space beneath the buttons. Pinning every row but the
    # transcript to `auto` gives the transcript the rest of the screen and
    # puts the buttons flush above the footer.
    #
    # The prompt is an Input, not a TextArea: this project's pinned Textual
    # has no TextArea placeholder, and TextArea's Enter inserts a newline,
    # so there was neither a hint that the box was for typing nor a way to
    # send without reaching for the mouse.
    DEFAULT_CSS = """
    Horizontal > Button { min-width: 6; width: auto; }
    RichLog#transcript { height: 1fr; }
    #modes, #input-row, #controls, #context-bar { height: auto; }
    #modes-label { width: auto; padding: 1 1 0 1; }
    #cb-agent { width: 24; }
    /* The open list may be wider than the box, so no agent wraps. */
    #cb-agent > SelectOverlay { width: 36; }
    #cb-model { width: 18; }
    #cb-repo { width: 1fr; }
    #context-bar Label { padding: 1 0 0 1; }
    #thinking { height: 1; padding: 0 1; color: $accent; display: none; }
    #agents-status { height: auto; padding: 0 1; color: $text-muted; display: none; }
    #slash-hint { height: 1; padding: 0 1; color: $text-muted; display: none; }
    Input#prompt { width: 1fr; }
    #plan-actions { height: auto; display: none; }
    """

    def __init__(self, *, root: Path) -> None:
        from whyline import model

        super().__init__()
        self.session = ConsoleSession(root=root)
        self.session.agent = model.resolve(root)[0]
        self._dispatch_token: object | None = None
        self._exec_after: tuple[str, list[str]] | None = None
        self._login_fn = _run_login
        self._busy_text = ""
        self._busy_since = 0.0
        self._spin = 0
        self._relay = None  # the RelayProcess started by Start/Resume, if any
        self._relay_label = ""
        self._external_relay: str | None = None  # a relay another console started
        self._antigravity_ok = False
        self._release_task: tuple[str, list[str]] | None = None
        self._plan_state = ""  # "", "working", "review", "answering"
        self._plan_request: plan_job.PlanRequest | None = None
        self._plan_outcome: plan_job.Outcome | None = None
        self._approved_spec: Path | None = None
        self._transcript: RichLog | None = None
        self._stale_pause: str | None = None
        self._run_flow = False
        self._pending = att.PendingAttachments()
        self._attach_session = att.session_name()
        self._sent_attachments: list = []
        self._cb_saved: tuple[str, str, str] | None = None
        self._cb_agent_shown: str | None = None
        self._cb_status_seen: tuple[tuple[str, bool, str], ...] | None = None
        self._cb_refreshing = False
        self._agents_name: str | None = None
        self._editing_agent_id: str | None = None

    def on_mount(self) -> None:
        """Mirrors the plain REPL's own onboarding line (repl.py's `run`).
        The subtitle and the highlighted mode button say which mode is
        active; the console opens in Chat."""
        self.run_worker(lambda: att.clean_old(self.session.root), thread=True)
        self._sync_mode_indicator()
        self._cb_fit()
        self.set_interval(0.1, self._tick)
        self.set_interval(1.0, self._watch_external_relay)
        self._main("#prompt", Input).focus()
        self.render_event(
            SessionEvent(
                kind="output",
                text=(
                    "whyline console -- pick a mode above. Chat talks to an "
                    "agent, Relay drives whyline-relay, and /timeline (or "
                    "another whyline command after /) runs it from any mode. "
                    "Help explains the rest."
                ),
            )
        )
        warning = home_repo_warning(self.session.root, Path.cwd())
        if warning:
            self.render_event(SessionEvent(kind="error", text=warning))

    def _sync_mode_indicator(self) -> None:
        """The subtitle alone was easy to miss, so the current mode is also
        the highlighted mode button and shapes the prompt's placeholder."""
        mode = self.session.mode
        stage = getattr(self._plan_outcome, "stage", "plan") if self._plan_outcome else "plan"
        if self._plan_state == "review":
            suffix = f" · {stage} review"
        elif self._plan_state == "answering":
            suffix = " · answering"
        elif getattr(self, "_release_task", None):
            suffix = " · release"
        else:
            suffix = ""
        self.sub_title = f"mode: {mode}{suffix}"
        for name in _MODES:
            button = self._main(f"#mode-{name}", Button)
            button.variant = "primary" if name == mode else "default"
        if self._plan_state == "review":
            if stage == "synthesis":
                placeholder = 'Type "approve" to write the spec, or say what to change'
            elif stage == "spec":
                placeholder = 'Type "approve" to save the spec and write the plan, or say what to change'
            else:
                placeholder = 'Type "approve", or say what to change (Enter to send)'
        elif self._plan_state == "answering":
            placeholder = "Type your answers (Enter to send)"
        elif getattr(self, "_release_task", None):
            placeholder = 'Type "done" when finished, or "skip"'
        else:
            placeholder = self._placeholder(mode)
        self._main("#prompt", Input).placeholder = placeholder
        self._main("#plan-view", Button).label = {
            "synthesis": "View full",
            "spec": "View spec",
            "plan": "View draft",
        }.get(stage, "View draft")
        # A new saved agent or repo (/model, a switch, Run's setup) reloads
        # the whole bar. Availability alone (/model refresh, a login) rewrites
        # the agent list and leaves an unsaved edit where the user put it.
        if not self._cb_refreshing:
            if self._cb_saved != self._cb_saved_tuple():
                self._cb_refresh()
            else:
                self._cb_refresh_status()
        self._main("#attach", Button).disabled = self.session.mode != "chat"
        self._refresh_tray()
        if mode == "agents":
            self._refresh_agents_status()
        self._sync_relay_buttons()
        self._sync_mode_buttons()

    def _sync_mode_buttons(self) -> None:
        """One place decides which bottom-bar buttons are on screen.
        Enable and disable stay in _sync_relay_buttons and the stop path."""
        wanted = set(_MODE_BUTTONS.get(self.session.mode, ())) | set(_SHARED_BUTTONS)
        for button in self._main("#controls").query(Button):
            button.display = button.id in wanted
        self._main("#attach").display = self.session.mode == "chat"
        try:
            self._main("#agents-status").display = self.session.mode == "agents"
        except (NoMatches, IndexError):
            return

    def _sync_relay_buttons(self) -> None:
        """Plan and Set up only make sense in Relay mode; Resume only when a
        run is paused and nothing is running."""
        in_relay = self.session.mode == "relay"
        running = self._relay is not None and self._relay.running()
        self._main("#relay-run", Button).disabled = not in_relay or running
        self._main("#relay-plan", Button).disabled = not in_relay
        self._main("#relay-setup", Button).disabled = not in_relay or running
        try:
            paused = in_relay and relay_ops.paused_run(self.session.root)
        except Exception:  # no relay installed, unreadable state: not resumable
            paused = False
        try:
            stale = relay_ops.stale_pause(self.session.root) if paused else None
        except Exception:
            stale = None
        resume = self._main("#relay-resume", Button)
        if getattr(self, "_release_task", None):
            resume.label = "Release done…"
            resume.disabled = running
            self._stale_pause = None
        elif stale:
            resume.label = "Clear old run"
            self._stale_pause = stale
            resume.disabled = not paused or running
        else:
            resume.label = "Resume"
            self._stale_pause = None
            resume.disabled = not paused or running

    def _placeholder(self, mode: str) -> str:
        if mode == "relay":
            return "Relay: run (guided), doctor, status, start, resume (Enter to run)"
        if mode == "agents":
            return "Agents: list, run <name>, edit <name>, delete <name>, history <name>, pause/resume/accept <name>"
        agent = self.session.agent or "claude"
        return f"Message {agent}... (Enter to send)"

    def _refresh_agents_status(self) -> None:
        from whyline.agents import launchd, service

        mac = launchd.supported()
        try:
            self._main("#agents-scheduler", Button).disabled = not mac
        except (NoMatches, IndexError):
            pass
        if not mac:
            text = launchd.NEEDS_MACOS
        elif self._scheduler_on():
            try:
                nxt = _next_scheduled(service.rows(self.session.root))
            except Exception as error:
                text = f"Scheduler: on · {error}"
            else:
                text = f"Scheduler: on · next: {nxt}" if nxt else "Scheduler: on"
        else:
            text = "Scheduler: off — turn it on to run agents on a schedule"
        try:
            self._main("#agents-status", Static).update(text)
        except (NoMatches, IndexError):
            return

    def _open_new_agent(self, existing=None, delivery=None, *, editing_id=None,
                        lock_name: bool = False) -> None:
        from whyline import account
        from whyline.console.agents_screens import NewAgentScreen

        if editing_id is None:
            editing_id = existing.agent_id if existing is not None else None
        self._editing_agent_id = editing_id
        self.push_screen(
            NewAgentScreen(self.session.root, account.agent_status(self.session.root),
                           existing=existing, delivery=delivery, lock_name=lock_name),
            self._new_agent_done,
        )

    def _new_agent_done(self, form) -> None:
        if form is None:
            return
        from whyline.agents import deliver, deliveries, service, telegram
        from whyline.console import agents_screens

        defn, delivery = form.defn, form.delivery
        old_id = getattr(self, "_editing_agent_id", None)

        def decided(choice) -> None:
            if choice != "save":
                # Back: reopen the form with everything that was typed,
                # still editing the agent that was opened.
                self._open_new_agent(
                    existing=defn, delivery=delivery, editing_id=old_id, lock_name=True,
                )
                return
            try:
                service.save_new(defn)
                deliveries.save(defn.agent_id, delivery, known_chats=set(telegram.known_chats()))
                if old_id and old_id != defn.agent_id:
                    # The new name is a new file. Retire the original so it
                    # does not stay accepted and runnable beside the new one.
                    _retire_replaced_agent(self.session.root, old_id, defn.path)
                    deliveries.remove(old_id)
            except Exception as error:
                self.render_event(SessionEvent(kind="error", text=str(error)))
                return
            shown = defn.path.as_posix().replace(str(Path.home()), "~")
            self.render_event(SessionEvent(
                kind="output",
                text=f"Saved {defn.label} ({shown}) and accepted it on this Mac.",
            ))
            self._editing_agent_id = None
            self._refresh_agents_status()

        text = service.describe(defn)
        extra = deliver.describe(delivery)
        if extra:
            text = text.rstrip() + " " + extra
        self.push_screen(
            agents_screens.ReviewScreen(defn, text, self._scheduler_on()),
            decided,
        )

    def _scheduler_on(self) -> bool:
        from whyline.agents import launchd

        if not launchd.supported():
            return False
        try:
            return bool(launchd.status().loaded)
        except Exception:
            return False

    def _toggle_scheduler(self) -> None:
        from whyline.agents import launchd

        if not launchd.supported():
            return
        if self._scheduler_on():
            self.push_screen(
                ConfirmScreen(
                    "Turn the scheduler off? Scheduled and folder agents stop until you turn it on again.",
                    "Turn off",
                ),
                self._scheduler_turned_off,
            )
            return
        try:
            launchd.turn_on()
        except Exception as error:
            self.render_event(SessionEvent(kind="error", text=str(error)))
            return
        self._refresh_agents_status()

    def _scheduler_turned_off(self, yes: bool) -> None:
        if not yes:
            return
        from whyline.agents import launchd

        try:
            launchd.turn_off()
        except Exception as error:
            self.render_event(SessionEvent(kind="error", text=str(error)))
            return
        self._refresh_agents_status()

    def _open_agents_list(self, follow: str = "detail") -> None:
        from whyline.agents import service
        from whyline.console.agents_screens import AgentsListScreen

        try:
            rows = service.rows(self.session.root)
        except Exception as error:
            self.render_event(SessionEvent(kind="error", text=str(error)))
            return
        self.push_screen(AgentsListScreen(rows), lambda name: self._agent_picked(name, follow))

    def _agent_picked(self, name: str | None, follow: str) -> None:
        if not name:
            return
        self._agents_name = name
        if follow == "history":
            self._open_runs(name)
        else:
            self._open_detail(name)

    def _open_agents_runs(self) -> None:
        if self._agents_name:
            self._open_runs(self._agents_name)
        else:
            self._open_agents_list(follow="history")

    def _open_detail(self, name: str) -> None:
        from whyline.agents import service
        from whyline.console.agents_screens import AgentDetailScreen

        try:
            row = named_row(name, self.session.root)
            text = service.describe(row.defn)
        except Exception as error:
            self.render_event(SessionEvent(kind="error", text=str(error)))
            return
        self._agents_name = name
        self.push_screen(
            AgentDetailScreen(row, text),
            lambda action: self._agent_action(name, action),
        )

    def _open_runs(self, name: str) -> None:
        from whyline.agents import service
        from whyline.console.agents_screens import RunsScreen

        try:
            row = named_row(name, self.session.root)
            runs = service.history(name, self.session.root)
        except Exception as error:
            self.render_event(SessionEvent(kind="error", text=str(error)))
            return
        self._agents_name = name
        self.push_screen(RunsScreen(
            row.defn.label, runs, on_resend=lambda run_id: self._agent_resend(name, run_id)))

    def _agent_resend(self, name: str, run_id: str) -> None:
        from whyline.agents import service

        root = self.session.root

        def work() -> None:
            try:
                results = service.resend(name, root, run_id)
                text = "  ".join(
                    f"{r['to']} {'✓' if r['ok'] else '✗'}" + ("" if r["ok"] else f" {r['detail']}")
                    for r in results) or "Nothing was sent: no deliveries set."
                event = SessionEvent(kind="output", text=f"{name}: resent — {text}")
            except Exception as error:
                event = SessionEvent(kind="error", text=str(error))
            self.call_from_thread(self.render_event, event)

        self.run_worker(work, thread=True)

    def _agent_action(self, name: str, action: str | None) -> None:
        from whyline.agents import service

        if not action:
            return
        if action == "run":
            self._agent_run(name)
            return
        if action == "history":
            self._open_runs(name)
            return
        if action == "edit":
            try:
                existing = service.find(name, self.session.root)
            except Exception as error:
                self.render_event(SessionEvent(kind="error", text=str(error)))
                return
            self._open_new_agent(existing=existing)
            return
        if action == "delete":
            self._confirm_delete_agent(name)
            return
        if action in ("pause", "resume", "accept"):
            self.render_event(agents_command_event(self.session, f"{action} {name}"))
            self._refresh_agents_status()

    def _confirm_delete_agent(self, name: str) -> None:
        from whyline.agents import service

        try:
            label = named_row(name, self.session.root).defn.label
        except Exception as error:
            self.render_event(SessionEvent(kind="error", text=str(error)))
            return

        def confirmed(yes: bool) -> None:
            if not yes:
                return
            try:
                service.delete(name, self.session.root)
            except Exception as error:
                self.render_event(SessionEvent(kind="error", text=str(error)))
                return
            if self._agents_name == name:
                self._agents_name = None
            self.render_event(SessionEvent(kind="output", text=f"Deleted {label}."))
            self._refresh_agents_status()

        self.push_screen(
            ConfirmScreen(
                f"Delete {label}? Its schedule stops and its file is removed.",
                "Delete",
            ),
            confirmed,
        )

    def _agents_command(self, text: str) -> None:
        parts = text.split()
        if len(parts) == 2 and parts[0] == "run":
            self._agent_run(parts[1])
            return
        if len(parts) == 2 and parts[0] == "history":
            self._open_runs(parts[1])
            return
        if len(parts) == 2 and parts[0] == "edit":
            self._agent_action(parts[1], "edit")
            return
        if len(parts) == 2 and parts[0] == "delete":
            self._confirm_delete_agent(parts[1])  # always asks first
            return
        self.render_event(agents_command_event(self.session, text))
        if parts and parts[0] in ("list", "pause", "resume", "accept"):
            self._refresh_agents_status()

    def _agent_run(self, name: str) -> None:
        from whyline.agents import records, service

        token = object()
        self._dispatch_token = token
        self._set_busy(True, f"agent {name}")
        root = self.session.root

        def in_thread() -> None:
            def progress(line: str) -> None:
                self.call_from_thread(self._agent_progress, line, token)

            try:
                rec = service.run_now(name, root, progress=progress)
            except Exception as error:
                self.call_from_thread(self._agent_failed, error, token)
                return
            final = ""
            try:
                final = records.read_final(rec.run_id)
            except OSError:
                final = ""
            self.call_from_thread(self._agent_done, name, rec, final, token)

        self.run_worker(in_thread, thread=True)

    def _agent_progress(self, line: str, token: object) -> None:
        if token is not self._dispatch_token:
            return
        self.render_event(SessionEvent(kind="output", text=f"agent · {line}"))
        self._busy_text = f"agent: {line}"

    def _agent_failed(self, error: BaseException, token: object) -> None:
        if token is not self._dispatch_token:
            return
        self._set_busy(False)
        self.render_event(SessionEvent(kind="error", text=str(error)))

    def _agent_done(self, name: str, rec, final: str, token: object) -> None:
        if token is not self._dispatch_token:
            return
        self._set_busy(False)
        self.render_event(SessionEvent(kind="output", text=run_result_text(name, rec)))
        shown = (final or "").strip()
        if shown:
            self.render_event(SessionEvent(kind="output", text=shown))
        self._refresh_agents_status()

    def _cb_saved_tuple(self) -> tuple[str, str, str]:
        from whyline import model

        agent, model_name = model.resolve(self.session.root)
        return (agent, model_name, _short_path(self.session.root))

    def _cb_current(self) -> tuple[str, str, str]:
        raw = self._main("#cb-agent", Select).value
        if isinstance(raw, str) and raw.startswith("!"):
            agent = raw[1:]
        elif isinstance(raw, str):
            agent = raw
        else:
            agent = ""
        return (
            agent,
            self._main("#cb-model", Input).value,
            self._main("#cb-repo", Input).value,
        )

    def _cb_dirty(self) -> bool:
        if self._cb_saved is None:
            return False
        if self._cb_current() != self._cb_saved:
            return True
        # Ticked "all repos" is itself unsaved: otherwise the global default
        # cannot be written while agent, model and repo already match.
        try:
            return bool(self._main("#cb-global", Checkbox).value)
        except (NoMatches, IndexError):
            return False

    def _cb_mark_save(self) -> None:
        try:
            self._main("#cb-save", Button).disabled = not self._cb_dirty()
        except (NoMatches, IndexError):
            return

    def _model_for(self, agent: str) -> str:
        """This agent's model: the repo file, then the global file, then blank."""
        from whyline import model

        chosen = model.load(self.session.root).get(agent) or ""
        if isinstance(chosen, str) and chosen:
            return chosen
        glob = model.load_global()
        models = glob.get("models")
        if isinstance(models, dict):
            value = models.get(agent) or ""
            if isinstance(value, str):
                return value
        return ""

    def _cb_refresh(self) -> None:
        from whyline import account

        if self._cb_refreshing:
            return
        try:
            select = self._main("#cb-agent", Select)
            model_input = self._main("#cb-model", Input)
            repo_input = self._main("#cb-repo", Input)
        except (NoMatches, IndexError):
            return
        self._cb_refreshing = True
        try:
            status = account.agent_status(self.session.root)
            options = _cb_options(status) or [("claude", "claude")]
            agent, model_name, repo_text = self._cb_saved_tuple()
            chosen = _cb_match_option(agent, options)
            with self.prevent(Select.Changed, Input.Changed):
                select.set_options(options)
                if select.value != chosen:
                    select.value = chosen
                model_input.value = model_name
                repo_input.value = repo_text
            self._cb_agent_shown = agent
            self._cb_saved = (agent, model_name, repo_text)
            self._cb_status_seen = _cb_status_key(status)
            self._cb_mark_save()
        finally:
            self._cb_refreshing = False

    def _cb_refresh_status(self) -> None:
        """Rewrite agent options after a status change, keeping unsaved edits."""
        from whyline import account

        if self._cb_refreshing:
            return
        try:
            select = self._main("#cb-agent", Select)
        except (NoMatches, IndexError):
            return
        status = account.agent_status(self.session.root)
        key = _cb_status_key(status)
        if key == self._cb_status_seen:
            return
        options = _cb_options(status) or [("claude", "claude")]
        chosen = _cb_match_option(select.value, options)
        self._cb_refreshing = True
        try:
            with self.prevent(Select.Changed):
                select.set_options(options)
                if select.value != chosen:
                    select.value = chosen
            self._cb_status_seen = key
            self._cb_mark_save()
        finally:
            self._cb_refreshing = False

    def _cb_fit(self) -> None:
        """Below 100 columns the labels shrink so Save stays on screen."""
        try:
            narrow = self.size.width < 100
            self._main("#cb-agent-label", Label).update("A" if narrow else "Agent")
            self._main("#cb-model-label", Label).update("M" if narrow else "Model")
            self._main("#cb-repo-label", Label).update("R" if narrow else "Repo")
            self._main("#cb-agent", Select).styles.width = 14 if narrow else 24
        except (NoMatches, IndexError):
            return

    def _cb_snap_back(self, name: str) -> None:
        from whyline import account

        info = account.agent_status(self.session.root).get(name) or {}
        hint = info.get("hint") or ""
        if hint:
            self.render_event(SessionEvent(kind="output", text=hint))
        select = self._main("#cb-agent", Select)
        saved = self._cb_saved[0] if self._cb_saved else "claude"
        legal = getattr(select, "_legal_values", ())
        target = saved if saved in legal else f"!{saved}"
        if target not in legal:
            target = saved
        if select.value != target:
            with self.prevent(Select.Changed):
                try:
                    select.value = target
                except Exception:
                    return
        self._cb_mark_save()

    def _cb_save(self) -> None:
        from whyline import model

        if self._cb_saved is None:
            return
        agent, model_name, repo_text = self._cb_current()
        saved_agent, saved_model, saved_repo = self._cb_saved
        agent_changed = (agent, model_name) != (saved_agent, saved_model)
        repo_changed = repo_text != saved_repo
        global_too = bool(self._main("#cb-global", Checkbox).value)
        if agent_changed or global_too:
            if _model_rejected(model_name):
                self.render_event(SessionEvent(
                    kind="error", text="A model name has no spaces"))
                return
            if not agent:
                return
            model.set_default_agent(self.session.root, agent)
            model.set_one(self.session.root, agent, model_name)
            if global_too:
                model.save_global(agent, model_name)
            self.session.agent = agent
            shown = model_name or "default model"
            text = f"Default for this repo: {agent} · {shown}"
            if global_too:
                text += " (also for every repo without its own)"
            self.render_event(SessionEvent(kind="output", text=text))
            box = self._main("#cb-global", Checkbox)
            if box.value:
                box.value = False
            self._cb_agent_shown = agent
            self._cb_saved = (agent, model_name, saved_repo)
        if not repo_text.strip():
            # An empty path does nothing: put the current repo back.
            self._cb_refresh()
            return
        if not repo_changed:
            self._cb_mark_save()
            self._sync_mode_indicator()
            return
        if self._relay_running() or self._plan_state or self._busy_text:
            self.render_event(SessionEvent(
                kind="error",
                text="Finish or stop the current job before switching repo.",
            ))
            self._cb_refresh()
            self._sync_mode_indicator()
            return
        try:
            insp = repo_setup.inspect(Path(repo_text.strip()))
        except OSError as error:
            self.render_event(SessionEvent(kind="error", text=str(error)))
            return
        if insp.kind == "home":
            self.render_event(SessionEvent(kind="error", text=_HOME_REFUSAL))
            self._cb_refresh()
            return
        if insp.kind == "nested":
            outer = _short_path(insp.outer) if insp.outer is not None else ""
            shown_path = _short_path(insp.path)
            self.render_event(SessionEvent(
                kind="error",
                text=(
                    f"{shown_path} is inside the repository {outer}. "
                    f"Use {outer}, or pick a folder outside it."
                ),
            ))
            return
        if insp.kind == "ready" and insp.path == Path(self.session.root).resolve():
            self._cb_refresh()
            return
        if insp.kind == "ready":
            path = insp.path
            self.push_screen(
                ConfirmScreen(repo_switch_warning(path), f"Switch to {path.name}"),
                lambda confirmed, target=path: self._switch_repo(target, confirmed),
            )
            return
        self.push_screen(
            ConfirmScreen(repo_setup.describe(insp), "Set up"),
            lambda confirmed, inspection=insp: self._cb_setup_answered(inspection, confirmed),
        )

    def _cb_setup_answered(self, insp, confirmed: bool) -> None:
        if not confirmed:
            self._cb_refresh()
            return
        self._cb_run_setup(insp)

    def _cb_run_setup(self, insp) -> None:
        def work() -> None:
            def progress(step: str) -> None:
                self.call_from_thread(
                    self.render_event,
                    SessionEvent(kind="output", text=f"setup · {step}"),
                )

            try:
                root = repo_setup.setup(
                    insp,
                    agents=relay_ops.relay_agents(root=None, which=shutil.which),
                    progress=progress,
                )
            except repo_setup.SetupError as error:
                self.call_from_thread(
                    self.render_event,
                    SessionEvent(kind="error", text=str(error)),
                )
                return
            self.call_from_thread(self._cb_setup_finished, root, insp)

        self.run_worker(work, thread=True)

    def _cb_setup_finished(self, root: Path, insp) -> None:
        # switch_repo directly: the user already confirmed. Don't cancel
        # workers here; this callback runs on the setup worker's thread bridge.
        self._pending.clear()
        self._sent_attachments = []
        self._attach_session = att.session_name()
        self._warned_once = False
        result = switch_repo(self.session, root)
        try:
            self._main("#transcript", RichLog).clear()
        except (NoMatches, IndexError):
            return
        self.render_event(result)
        self._sync_mode_indicator()
        self.run_worker(lambda: att.clean_old(root), thread=True)
        try:
            installed = relay_ops.relay_agents(insp.path)
        except Exception:
            installed = []
        self._with_antigravity("antigravity" in installed, lambda ok: None)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Static("Mode:", id="modes-label"),
            Button("Chat", id="mode-chat"),
            Button("Relay", id="mode-relay"),
            Button("Agents", id="mode-agents"),
            id="modes",
        )
        from whyline import account

        options = _cb_options(account.agent_status(self.session.root)) or [("claude", "claude")]
        yield Horizontal(
            Label("Agent", id="cb-agent-label"),
            Select(options, allow_blank=False, id="cb-agent"),
            Label("Model", id="cb-model-label"),
            Input(placeholder="default", id="cb-model"),
            Label("Repo", id="cb-repo-label"),
            Input(id="cb-repo"),
            Checkbox("all repos", id="cb-global"),
            Button("Save", id="cb-save", disabled=True),
            id="context-bar",
        )
        self._transcript = RichLog(id="transcript", wrap=True)
        yield self._transcript
        yield Static("", id="thinking")
        yield Static("", id="agents-status")
        yield Horizontal(
            Button("Approve", id="plan-approve", variant="success"),
            Button("View draft", id="plan-view"),
            Button("Discard", id="plan-discard", variant="warning"),
            id="plan-actions",
        )
        yield AttachmentTray(id="tray")
        yield Static("", id="slash-hint")
        yield Horizontal(
            PromptInput(id="prompt"),
            Button("Attach", id="attach"),
            Button("Send", id="send", variant="success"),
            id="input-row",
        )
        # Shared buttons stay last so each mode's own buttons lead the row.
        yield Horizontal(
            Button("Model", id="model"),
            Button("Brainstorm", id="brainstorm"),
            Button("History", id="history"),
            Button("Run", id="relay-run", disabled=True),
            Button("Plan", id="relay-plan", disabled=True),
            Button("Set up", id="relay-setup", disabled=True),
            Button("Resume", id="relay-resume", disabled=True),
            Button("New", id="agents-new"),
            Button("Agents", id="agents-list"),
            Button("Runs", id="agents-runs"),
            Button("Scheduler", id="agents-scheduler"),
            Button("Stop", id="stop", disabled=True),
            Button("Help", id="help"),
            Button("Copy", id="copy"),
            id="controls",
        )
        yield Footer()

    def render_event(self, event: SessionEvent) -> None:
        self.session.record(event)
        try:
            transcript = self._main("#transcript", RichLog)
        except (NoMatches, IndexError):  # the console is closing; the event is still recorded
            return
        line = f"{_PREFIX.get(event.kind, '')}{event.text}"
        # What you typed is set apart from replies, so the transcript reads
        # as a conversation rather than an unattributed log.
        transcript.write(
            Text(line, style="bold cyan") if event.kind == "input" else line,
            expand=True,
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        button_id = event.button.id
        if button_id == "cb-save":
            self._cb_save()
        elif button_id == "send":
            self._send()
        elif button_id == "attach":
            self._open_attach_menu()
        elif button_id == "stop":
            other = None if self._relay_running() else self._live_relay()
            if self._relay_running():
                self._relay.interrupt()
                shown = f" ({self._relay_label.removeprefix('relay: ')})" if self._relay_label else ""
            elif other and relay_ops.interrupt_live_run(self.session.root):
                shown = f" ({other})"
            else:
                self._stop()
                return
            self.render_event(SessionEvent(
                kind="output",
                text=f"Stopping the relay{shown}: the current agent's turn is cut off "
                     "and the run pauses. Resume carries on from there.",
            ))
        elif button_id and button_id.startswith("mode-"):
            self._handle_slash(f"/route {button_id.removeprefix('mode-')}")
            # Enter submits the prompt. A click would otherwise leave focus on the button.
            try:
                self._main("#prompt", Input).focus()
            except (NoMatches, IndexError):
                return
        elif button_id == "agents-new":
            self._open_new_agent()
        elif button_id == "agents-list":
            self._open_agents_list()
        elif button_id == "agents-runs":
            self._open_agents_runs()
        elif button_id == "agents-scheduler":
            self._toggle_scheduler()
        elif button_id == "copy":
            self._copy_transcript()
        elif button_id == "relay-run":
            self._run_flow_start()
        elif button_id == "relay-plan":
            self._open_relay_plan()
        elif button_id == "relay-setup":
            self._open_relay_setup()

        elif button_id == "relay-resume":
            if getattr(self, "_release_task", None):
                self._send_with("done")
            elif getattr(self, "_stale_pause", None):
                task = self._stale_pause
                relay_ops.clear_pause(self.session.root)
                self.render_event(SessionEvent(
                    kind="output", text=f"Cleared the finished run {task}."))
                self._sync_relay_buttons()
            else:
                self._launch_relay(["resume"])
        elif button_id == "plan-approve":
            self._approve_plan()
        elif button_id == "plan-view":
            from whyline.console.relay_screens import PlanDraftScreen

            if self._plan_outcome:
                text = (
                    self._plan_outcome.text
                    if self._plan_outcome.stage == "synthesis"
                    else (
                        self._plan_outcome.draft.text
                        if self._plan_outcome.draft
                        else ""
                    )
                )
                if text:
                    self.push_screen(PlanDraftScreen(text))
        elif button_id == "plan-discard":
            self._discard_plan()
        elif button_id in ("model", "history", "help", "brainstorm"):
            self._handle_slash(f"/{button_id}")

    def on_input_submitted(self, event: "Input.Submitted") -> None:
        # Only the console's own message box sends; Enter in a dialog's
        # input (the brainstorm topic) is that dialog's business.
        if event.input.id == "prompt":
            self._send()
        elif event.input.id in ("cb-model", "cb-repo"):
            self._cb_save()

    def on_input_changed(self, event: "Input.Changed") -> None:
        if event.input.id in ("cb-model", "cb-repo"):
            self._cb_mark_save()
            return
        if event.input.id != "prompt":
            return
        hint = self._main("#slash-hint", Static)
        if event.value == "/":
            hint.update(_SLASH_HINT)
            hint.display = True
        else:
            hint.display = False

    def on_checkbox_changed(self, event: "Checkbox.Changed") -> None:
        if event.checkbox.id == "cb-global":
            self._cb_mark_save()

    def on_select_changed(self, event: "Select.Changed") -> None:
        select = event.select
        if select.id != "cb-agent":
            return
        # Textual queues Changed, so a refresh can move the value again
        # before this message runs. Ignore that stale value.
        if event.value != select.value:
            return
        value = event.value
        if isinstance(value, str) and value.startswith("!"):
            self._cb_snap_back(value[1:])
            return
        if isinstance(value, str):
            shown = self._cb_agent_shown
            field = self._main("#cb-model", Input)
            # Keep a model the user already typed. Replace the field only
            # when it still shows the previous agent's saved model, which is
            # what a click on the selector does before the next keystroke.
            if shown != value and (shown is None or field.value == self._model_for(shown)):
                with self.prevent(Input.Changed):
                    field.value = self._model_for(value)
            self._cb_agent_shown = value
        self._cb_mark_save()

    def on_resize(self, event) -> None:
        self._cb_fit()

    def _main(self, selector: str, expect_type=None):
        """Query the console's own screen, never whichever dialog is on top.
        App.query_one searches the *active* screen, so with the brainstorm
        form or a confirmation open, looking up #prompt or #transcript
        crashed the console with NoMatches."""
        screen = self.screen_stack[0]
        if expect_type is None:
            return screen.query_one(selector)
        return screen.query_one(selector, expect_type)

    def _statuses(self) -> dict[str, str]:
        agent = self.session.agent or "claude"
        out = {}
        for item in self._pending.items:
            try:
                delivery = relay_ops.delivery_for(self.session.root, agent, item.kind)
            except Exception:
                delivery = "path-unverified"
            out[item.id] = status_text(agent, delivery)
        return out

    def _tray_text(self) -> str:
        statuses = self._statuses()
        return "  ".join(f"{i.name} {statuses[i.id]}" for i in self._pending.items)

    def _refresh_tray(self) -> None:
        try:
            tray = self._main("#tray", AttachmentTray)
        except (NoMatches, IndexError):  # the console is closing; a late worker has nothing to update
            return
        tray.show(self._pending.items, self._statuses())

    def on_attachment_tray_removed(self, message: AttachmentTray.Removed) -> None:
        self._pending.remove(message.attachment_id)
        self._refresh_tray()

    def on_prompt_input_dropped(self, message: PromptInput.Dropped) -> None:
        names = ", ".join(p.name for p in message.paths)

        def answered(attach: bool) -> None:
            prompt = self._main("#prompt", Input)
            if not attach:
                prompt.insert_text_at_cursor(message.text)
                prompt.focus()
                return
            root, session, pending = self.session.root, self._attach_session, self._pending

            def in_thread():
                staged = []
                try:
                    for path in message.paths:
                        item = att.stage(root, path, session=session, source="drop", pending=pending)
                        pending.add(item)
                        staged.append(item)
                except Exception as error:
                    self.call_from_thread(self.render_event, SessionEvent(kind="error", text=str(error)))
                self.call_from_thread(self._attached, staged)

            self.run_worker(in_thread, thread=True)

        count = len(message.paths)
        self.push_screen(ConfirmScreen(
            f"Attach {count} file{'s' if count > 1 else ''}? {names}", "Attach", "Keep as text"),
            answered)

    def _open_attach_menu(self) -> None:
        self.push_screen(AttachMenuScreen(), self._attach_chosen)

    def _attach_chosen(self, choice: str | None) -> None:
        self._main("#prompt", Input).focus()
        if choice is None:
            return
        self.attach_into(self._pending, choice, lambda: self._attached([]))

    def attach_into(self, pending, choice: str, on_done=None) -> None:
        root, session = self.session.root, self._attach_session

        def work():
            if choice == "pick":
                staged = []
                for p in mac_input.pick_files():
                    item = att.stage(root, p, session=session, source="picker", pending=pending)
                    pending.add(item)  # now, so the limits count it for the next file
                    staged.append(item)
                return staged
            target = root / ".whyline" / "attachments" / session / f"screenshot-{att.session_name()}.png"
            att.ensure_ignored(root)
            if not mac_input.paste_image(target):
                raise att.AttachmentError(
                    "The clipboard has no image. Take a screenshot to the clipboard "
                    "first (Cmd+Ctrl+Shift+4).")
            try:
                item = att.stage(root, target, session=session, source="clipboard", pending=pending)
                pending.add(item)
                return [item]
            finally:
                target.unlink(missing_ok=True)

        def in_thread():
            try:
                staged = work()
            except Exception as error:  # AttachmentError, PickerError
                self.call_from_thread(self.render_event, SessionEvent(kind="error", text=str(error)))
                if on_done:
                    self.call_from_thread(on_done)
                return
            if on_done:
                self.call_from_thread(on_done)

        self.run_worker(in_thread, thread=True)

    def _attached(self, staged: list) -> None:
        self._refresh_tray()
        self._main("#prompt", Input).focus()

    def _copy_transcript(self) -> None:
        """Pushes the whole transcript onto the system clipboard via OSC 52
        (App.copy_to_clipboard), since a mouse-driven click-drag selection
        is captured by the app itself here, not the terminal -- there is no
        text-selection support to fall back on in this project's pinned
        Textual version (see tui.py's own module docstring situation:
        RichLog predates Textual's text-selection feature). This works
        without the user needing to know their terminal's own
        bypass-selection modifier key."""
        if not self.session.transcript:
            self.render_event(SessionEvent(kind="output", text="(nothing to copy yet)"))
            return
        text = "\n".join(
            f"{_PREFIX.get(e.kind, '')}{e.text}" for e in self.session.transcript
        )
        if _system_copy(text):
            self.render_event(SessionEvent(kind="output", text="Transcript copied to clipboard."))
            return
        self.copy_to_clipboard(text)
        self.render_event(SessionEvent(
            kind="output",
            text="Sent the transcript to your terminal's clipboard (OSC 52). It may not "
            "have arrived: no system clipboard command was found, and some terminals "
            "ignore OSC 52 unless it's enabled in their settings.",
        ))

    def _stop(self) -> None:
        """Invalidates the current dispatch token (MTU6): whatever
        _dispatch_in_thread is running right now will still run to
        completion -- Python cannot forcibly interrupt it -- but its result
        will no longer match self._dispatch_token when it finally returns,
        so render_event is never called for it. This guarantee holds
        regardless of what worker.cancel() itself does or doesn't stop.
        worker.cancel() is still called below as a best-effort signal to
        Textual's own scheduler; verify its exact call shape (iterating
        self.workers vs. a single self.workers.cancel_all()) against your
        installed version."""
        self._dispatch_token = object()
        self._sent_attachments = []
        if getattr(self, "_release_task", None):
            self._release_task = None
            self._sync_mode_indicator()
        if self._plan_state == "working":
            self._leave_plan()
            self._end_run_flow("Run stopped: no plan was saved.")
        for worker in self.workers:
            worker.cancel()
        self._set_busy(False)

    def _set_busy(self, busy: bool, label: str | None = None) -> None:
        """Enables Stop and shows the thinking line ("⠋ claude is thinking…
        12s") while a reply is pending, so a slow agent doesn't look like a
        frozen console."""
        self._main("#stop", Button).disabled = (
            not busy and not self._relay_running() and not self._external_relay
        )
        thinking = self._main("#thinking", Static)
        if busy:
            self._busy_text = label or busy_label(self.session)
            self._busy_since = time.monotonic()
            thinking.display = True
            self._tick()
        else:
            self._busy_text = ""
            if not self._relay_running():
                thinking.display = False

    def _tick(self) -> None:
        label = self._busy_text or self._relay_label
        if not label or not self.screen_stack:
            return  # idle, or the app is shutting down
        self._spin = (self._spin + 1) % len(_SPINNER)
        elapsed = int(time.monotonic() - self._busy_since)
        try:
            thinking = self._main("#thinking", Static)
        except NoMatches:
            # Quitting while a reply is still pending: the timer can fire
            # once more after the widgets are gone.
            return
        thinking.update(f"{_SPINNER[self._spin]} {label}… {elapsed}s")

    def _send(self) -> None:
        prompt = self._main("#prompt", Input)
        text = prompt.value.strip()
        if not text:
            return
        if self._busy_text and not text.startswith("/"):
            # A new dispatch would replace the pending one's token, silently
            # discarding its result -- a whole brainstorm, possibly. The text
            # stays in the box so it can be sent once this finishes.
            self.render_event(SessionEvent(
                kind="output",
                text="Still working on the last request -- wait for it, or press Stop.",
            ))
            return
        if self.session.mode == "chat" and self._pending.items and not text.startswith("/"):
            missing = [a for a in self._pending.items if not a.path.exists()]
            if missing:
                self.render_event(SessionEvent(kind="error", text=(
                    f"{missing[0].name} is no longer available; remove it and attach it again.")))
                return
            agent = self.session.agent or "claude"
            secret_items = [a for a in self._pending.items if a.warning]
            unverified_items = [a for a in self._pending.items
                                if needs_warning(self._delivery_for(agent, a.kind))]
            if (secret_items or unverified_items) and not getattr(self, "_warned_once", False):
                parts = []
                if secret_items:
                    s_names = ", ".join(a.name for a in secret_items)
                    parts.append(f"{s_names} looks like a secret.")
                if unverified_items:
                    u_names = ", ".join(a.name for a in unverified_items)
                    parts.append(f"{agent} gets {u_names} as a file path and may not be able to view images.")
                message = " ".join(parts)
                def answered(ok: bool) -> None:
                    if ok:
                        self._warned_once = True
                        self._send_with(text)
                self.push_screen(ConfirmScreen(message, "Send anyway"), answered)
                return
        self._send_with(text)

    def _delivery_for(self, agent: str, kind: str) -> str:
        try:
            return relay_ops.delivery_for(self.session.root, agent, kind)
        except Exception:
            return "path-unverified"

    def _send_with(self, text: str) -> None:
        prompt = self._main("#prompt", Input)
        prompt.value = ""
        if self.session.mode == "chat" and self._pending.items and not text.startswith("/"):
            input_text = f"{text}\n📎 {', '.join(a.name for a in self._pending.items)}"
            self._sent_attachments = list(self._pending.items)
            attachments = [a.path for a in self._sent_attachments]
        else:
            input_text = text
            attachments = ()
        self.render_event(SessionEvent(kind="input", text=input_text))
        if getattr(self, "_release_task", None) and text.strip().lower() in ("done", "skip"):
            cmd = text.strip().lower()
            task_id, _ = self._release_task
            self._release_task = None
            self._sync_mode_indicator()
            self._launch_relay([cmd, task_id])
            return
        if self._plan_state in ("review", "answering") and not text.startswith("/"):
            self._plan_reply(text)
            return
        if self.session.mode == "relay" and (text.strip() == "run" or text.split() == ["start"]):
            self._run_flow_start()
            return
        first = text.split(maxsplit=1)[0]
        if self.session.mode == "relay" and first in ("start", "resume"):
            self._launch_relay(text.split())
            return
        # Slash commands stay available in every mode, including Agents.
        if self.session.mode == "agents" and not text.startswith("/"):
            self._agents_command(text)
            return

        if not self._handle_slash(text):
            if text.startswith("/"):
                # Never send an unrecognized command to the agent as a
                # message -- and never let it start a turn mid-brainstorm.
                self.render_event(SessionEvent(kind="error", text=unknown_command_text(text)))
                return
            self._dispatch_text(text, attachments=attachments)
            self._warned_once = False

    def _handle_slash(self, text: str) -> bool:
        """Handles a slash command synchronously on the main thread -- no
        worker needed, these are fast, local operations. Returns True if
        `text` was a recognized slash command (whether or not it also
        triggered a setup handoff), False otherwise, so _send() knows
        whether to fall through to an ordinary (possibly slow) dispatch()
        call in a worker."""
        if self.session.mode == "chat" and text.strip() == "/paste":
            self._attach_chosen("paste")
            return True
        event = handle_slash_command(self.session, text)
        if event is None:
            return False
        if event.kind == "needs_setup":
            # Setup happens here now (Plan, then Set up), not in the
            # terminal wizard, so the console stays open.
            self.session.mode = "relay"
            self.render_event(SessionEvent(
                kind="output",
                text="Mode is now relay. No relay setup here yet -- use Plan, then Set up.",
            ))
            self._sync_mode_indicator()
            return True
        if event.kind == "needs_login":
            self._login(event.text)
            return True
        if event.kind == "confirm_repo":
            target = Path(event.text)
            self.push_screen(
                ConfirmScreen(repo_switch_warning(target), f"Switch to {target.name}"),
                lambda confirmed: self._switch_repo(target, confirmed),
            )
            return True
        if event.kind == "needs_brainstorm":
            from whyline import account

            self.push_screen(
                BrainstormScreen(account.agent_status(self.session.root),
                                 self.session.agent or "claude"),
                self._start_brainstorm,
            )
            return True
        self.render_event(event)
        self._sync_mode_indicator()
        return True

    def _switch_repo(self, target: Path, confirmed: bool) -> None:
        if not confirmed:
            self.render_event(SessionEvent(kind="output", text="Staying put."))
            self._cb_refresh()
            return
        self._leave_plan()
        self._stop()  # a reply still pending belongs to the old repository
        self._pending.clear()
        self._sent_attachments = []
        self._attach_session = att.session_name()
        self._warned_once = False
        result = switch_repo(self.session, target)
        self._main("#transcript", RichLog).clear()
        self.render_event(result)
        self._sync_mode_indicator()
        self.run_worker(lambda: att.clean_old(target), thread=True)

    _ANTIGRAVITY_SKIP = (
        "Skipping Antigravity: this repo isn't trusted in its settings "
        "(Model → Antigravity to ask again)."
    )

    def _with_antigravity(self, uses: bool, proceed) -> None:
        """Before anything runs antigravity: trusted, go; declined for this
        repo, go without it; otherwise ask once (spec section 8)."""
        if not uses:
            proceed(True)
            return
        try:
            state = relay_ops.antigravity_state(self.session.root)
        except Exception:  # relay missing: let the run report it
            state = "trusted"
        if state == "trusted":
            proceed(True)
            return
        if state == "declined":
            self.render_event(SessionEvent(kind="output", text=self._ANTIGRAVITY_SKIP))
            proceed(False)
            return
        from whyline_relay import antigravity

        message = (
            "Antigravity can only read and edit files in folders listed in "
            f"{antigravity.settings_path()}, a setting for the whole machine. Add "
            f"{self.session.root} to it, and allow Antigravity's file and command tools?"
        )

        def answered(trusted: bool) -> None:
            if trusted:
                try:
                    relay_ops.trust_antigravity(self.session.root)
                except Exception as error:  # e.g. SettingsUnreadable
                    self.render_event(SessionEvent(kind="error", text=str(error)))
                    proceed(False)
                    return
                proceed(True)
                return
            relay_ops.decline_antigravity(self.session.root)
            self.render_event(SessionEvent(kind="output", text=self._ANTIGRAVITY_SKIP))
            proceed(False)

        self.push_screen(ConfirmScreen(message, "Trust it", "Not now"), answered)

    def _start_brainstorm(self, choice: "dict | None") -> None:
        if choice is None:
            return

        def proceed(allowed: bool) -> None:
            if not allowed:
                agents = [a for a in choice["agents"] if a != "antigravity"]
                if not agents:
                    self.render_event(SessionEvent(
                        kind="error", text="No model is left to brainstorm with."))
                    return
                final = choice["final_agent"]
                choice.update(agents=agents, final_agent=final if final in agents else agents[0])
            self._run_brainstorm_choice(choice)

        self._with_antigravity("antigravity" in choice["agents"], proceed)

    def _run_brainstorm_choice(self, choice: dict) -> None:
        names = ", ".join(choice["agents"])
        self.render_event(SessionEvent(
            kind="output",
            text=f"Brainstorming \"{choice['topic']}\" with {names} -- several full "
                 "agent turns, so this takes a while.",
        ))
        token = object()
        self._dispatch_token = token
        self._set_busy(True, "brainstorming")
        self.run_worker(lambda: self._brainstorm_in_thread(choice, token), thread=True)

    def _brainstorm_in_thread(self, choice: dict, token: object) -> None:
        def progress(line: str) -> None:
            self.call_from_thread(self._brainstorm_progress, line, token)

        try:
            result = adapters.run_brainstorm(self.session.root, progress=progress, **choice)
        except Exception as error:  # an agent failure mid-run must not end the console
            result = SessionEvent(kind="error", text=f"Brainstorm stopped: {error}")
        self.call_from_thread(self._finish_dispatch, result, token)

    def _brainstorm_progress(self, line: str, token: object) -> None:
        if token is not self._dispatch_token:
            return
        self.render_event(SessionEvent(kind="output", text=f"· {line}"))
        self._busy_text = f"brainstorming: {line}"

    def _login(self, agent: str) -> None:
        """Steps the full-screen app aside so the agent's own login can use
        the real terminal (it may open a browser or ask for a code), then
        comes back and re-checks."""
        with self.suspend():
            code = self._login_fn(login_argv(agent))
        self.render_event(after_login(self.session, agent, code))
        # Login rechecks every agent without changing the saved tuple.
        self._sync_mode_indicator()

    def _dispatch_text(self, text: str, attachments=()) -> None:
        uses = self.session.mode == "chat" and (self.session.agent or "claude") == "antigravity"

        def proceed(allowed: bool) -> None:
            if not allowed:
                self.render_event(SessionEvent(
                    kind="error", text="Antigravity can't run here until this repo is trusted."))
                return
            token = object()
            self._dispatch_token = token
            self._set_busy(True)
            if attachments:
                work = lambda: self._dispatch_in_thread(text, token, attachments=attachments)
            else:
                work = lambda: self._dispatch_in_thread(text, token)
            self.run_worker(work, thread=True)

        self._with_antigravity(uses, proceed)

    def _dispatch_in_thread(self, text: str, token: object, attachments=()) -> None:
        launched = True
        try:
            if attachments:
                result = dispatch(self.session, text, attachments=attachments)
            else:
                result = dispatch(self.session, text)
        except Exception as error:  # a safety net beyond adapters.py's own handling
            result = SessionEvent(kind="error", text=str(error), accepted=False)
            launched = False
        else:
            launched = getattr(result, "accepted", True) and getattr(result, "launched", True)
        self.call_from_thread(self._finish_dispatch, result, token, launched)

    def _finish_dispatch(self, result: SessionEvent, token: object, launched: bool = True) -> None:
        # Checked here, on the main thread, rather than in the worker: a
        # Stop or newer dispatch that lands between the worker's check and
        # this call would otherwise still let a stale result through.
        if token is not self._dispatch_token:
            return
        self._set_busy(False)
        self.render_event(result)
        if launched and self._sent_attachments:
            for item in self._sent_attachments:
                self._pending.remove(item.id)
            self._refresh_tray()
        self._sent_attachments = []

    def _refuse_in_home(self) -> bool:
        if _is_home(self.session.root):
            self.render_event(SessionEvent(kind="error", text=_HOME_REFUSAL))
            return True
        return False

    def _open_relay_plan(self) -> None:
        if self._refuse_in_home():
            return
        if self._plan_state:
            self.render_event(SessionEvent(
                kind="error",
                text="A plan is already in progress: approve it, Discard it, or press Esc."))
            return
        from whyline import account
        from whyline.console.relay_screens import RelayPlanScreen

        self.push_screen(
            RelayPlanScreen(
                self.session.root,
                account.agent_status(self.session.root),
                self.session.agent or "claude",
            ),
            self._plan_chosen,
        )

    def _plan_chosen(self, result) -> None:
        if result is None:
            self._end_run_flow("Run cancelled.")
            return
        if isinstance(result, plan_job.PlanRequest):
            self._start_plan_job(result)
        else:
            self._plan_saved(result)

    def _plan_saved(self, path: Path | None) -> None:
        if path is None:
            return
        shown = (path.relative_to(self.session.root) if path.is_relative_to(self.session.root) else path).as_posix()
        self.render_event(
            SessionEvent(
                kind="output",
                text=f"Saved {shown} and committed it. Next: Set up, to pick the plan and who "
                     "implements, tests and reviews.",
            )
        )
        self._sync_relay_buttons()
        if self._run_flow:
            self._open_relay_setup(guided=True, plan=path)


    # -- the plan job (spec section 4) ------------------------------------
    def _set_plan_state(self, state: str) -> None:
        self._plan_state = state
        self._main("#plan-actions").display = state == "review"
        self._sync_mode_indicator()

    def _start_plan_job(self, request: plan_job.PlanRequest) -> None:
        def proceed(allowed: bool) -> None:
            if not allowed:
                self.render_event(SessionEvent(
                    kind="error",
                    text="This plan needs Antigravity, which isn't trusted here. "
                         "Pick other agents in Plan."))
                return
            self._plan_request = request
            self._plan_outcome = None
            self._approved_spec = None
            self.render_event(SessionEvent(
                kind="output", text=f'Planning "{request.name}". Progress follows.'))
            root = self.session.root
            self._run_plan(lambda progress: plan_job.run_request(root, request, progress))

        agents = {request.drafter, request.reviewer, request.writer}
        if request.brainstorm:
            agents |= set(request.brainstorm["agents"])
        self._with_antigravity("antigravity" in agents, proceed)

    def _run_plan(self, work) -> None:
        token = object()
        self._dispatch_token = token
        self._set_plan_state("working")
        self._set_busy(True, "planning")

        def in_thread() -> None:
            def progress(line: str) -> None:
                self.call_from_thread(self._plan_progress, line, token)

            try:
                outcome = work(progress)
            except Exception as error:  # agent missing, timeout, relay pause...
                self.call_from_thread(self._plan_failed, error, token)
                return
            self.call_from_thread(self._plan_done, outcome, token)

        self.run_worker(in_thread, thread=True)

    def _plan_progress(self, line: str, token: object) -> None:
        if token is not self._dispatch_token:
            return
        self.render_event(SessionEvent(kind="output", text=f"plan · {line}"))
        self._busy_text = f"planning: {line}"

    def _plan_failed(self, error: Exception, token: object) -> None:
        if token is not self._dispatch_token:
            return
        self._set_busy(False)
        self._set_plan_state("")
        if self._approved_spec:
            root = self.session.root
            shown = (
                self._approved_spec.relative_to(root)
                if self._approved_spec.is_relative_to(root)
                else self._approved_spec
            ).as_posix()
            kept = f"{shown} is saved; open Plan → Resume draft to continue the plan."
        else:
            kept = "Anything drafted so far is kept -- open Plan and choose Resume draft to try again."
        self._leave_plan()
        self.render_event(SessionEvent(
            kind="error",
            text=f"Planning stopped: {error or error.__class__.__name__}. {kept}",
        ))
        self._end_run_flow("Run stopped: no plan was saved.")


    def _plan_done(self, outcome: plan_job.Outcome, token: object) -> None:
        if token is not self._dispatch_token:
            return
        self._set_busy(False)
        self._plan_outcome = outcome
        if outcome.kind == "questions":
            self.render_event(SessionEvent(kind="output", text=plan_job.questions_text(outcome)))
            self._set_plan_state("answering")
        else:
            name = self._plan_request.name if self._plan_request else "plan"
            if outcome.stage == "synthesis":
                text = plan_job.synthesis_text(outcome)
            elif outcome.stage == "spec":
                text = plan_job.spec_summary(outcome.draft, name)
            else:
                text = plan_job.summary(outcome.draft, name)
            self.render_event(SessionEvent(kind="output", text=text))
            self._set_plan_state("review")
        self._main("#prompt", Input).focus()

    def _plan_reply(self, text: str) -> None:
        root, outcome = self.session.root, self._plan_outcome
        if outcome is None:
            return
        if self._plan_state == "review":
            if text.strip().lower() == "approve":
                self._approve_plan()
                return
            if outcome.stage == "synthesis":
                self._run_plan(
                    lambda progress: plan_job.run_synthesis_change(
                        root, self._plan_request, outcome, text, progress
                    )
                )
                return
            self._run_plan(
                lambda progress: plan_job.run_revision(
                    root, outcome, text, progress
                )
            )
            return
        if outcome.stage == "synthesis":
            feedback = relay_ops.question_feedback(outcome.questions, text)
            self._run_plan(
                lambda progress: plan_job.run_synthesis_change(
                    root, self._plan_request, outcome, feedback, progress
                )
            )
            return
        self._run_plan(lambda progress: plan_job.run_answer(root, outcome, text, progress))

    def _approve_plan(self, replace: bool = False) -> None:
        root, request = self.session.root, self._plan_request
        outcome = self._plan_outcome
        if outcome is None or request is None:
            return

        if outcome.stage == "synthesis":
            self._run_plan(
                lambda progress: plan_job.run_spec_from_synthesis(
                    root, request, outcome, progress
                )
            )
            return

        if outcome.stage == "spec":
            draft = outcome.draft
            try:
                spec_path = relay_ops.approve_spec(
                    root, draft, request.name, replace=replace
                )
            except relay_ops.plan_exists_error():
                from whyline_relay import specs

                target = root / "docs" / "specs" / f"{specs._slug(request.name)}.md"
                shown = (
                    target.relative_to(root) if target.is_relative_to(root) else target
                ).as_posix()
                self.push_screen(
                    ConfirmScreen(f"{shown} already exists. Replace it?", "Replace"),
                    lambda confirmed: confirmed and self._approve_plan(replace=True),
                )
                return
            except ValueError as error:
                where = f" The draft is still at {draft.path}." if draft else ""
                self.render_event(
                    SessionEvent(kind="error", text=f"{error}.{where}")
                )
                return
            self._approved_spec = spec_path
            shown = (
                spec_path.relative_to(root)
                if spec_path.is_relative_to(root)
                else spec_path
            ).as_posix()
            self.render_event(
                SessionEvent(
                    kind="output",
                    text=f"Saved {shown} and committed it. Writing the plan from it…",
                )
            )
            self._run_plan(
                lambda progress: plan_job.run_plan_from_spec(
                    root, request, spec_path, progress
                )
            )
            return

        draft = outcome.draft
        spec_str = ""
        if self._approved_spec:
            spec_str = (
                self._approved_spec.relative_to(root)
                if self._approved_spec.is_relative_to(root)
                else self._approved_spec
            ).as_posix()
        try:
            kwargs = {"spec": spec_str} if spec_str else {}
            path = relay_ops.approve_plan(
                root,
                draft,
                request.name,
                replace=replace or request.replace,
                **kwargs,
            )
        except relay_ops.plan_exists_error():
            shown = relay_ops.plan_path(root, request.name).relative_to(root).as_posix()
            self.push_screen(
                ConfirmScreen(f"{shown} already exists. Replace it?", "Replace"),
                lambda confirmed: confirmed and self._approve_plan(replace=True),
            )
            return
        except ValueError as error:  # plan.PlanError: the draft isn't usable yet
            self.render_event(
                SessionEvent(
                    kind="error",
                    text=f"{error}. The draft is still at {draft.path}.",
                )
            )
            return
        self._leave_plan()
        self._plan_saved(path)

    def _discard_plan(self) -> None:
        if self._plan_outcome is not None:
            if self._plan_outcome.stage == "synthesis":
                pass
            elif self._plan_outcome.stage == "spec" or getattr(self._plan_outcome.draft, "source", "") == "spec":
                relay_ops.discard_spec(self.session.root)
            else:
                relay_ops.discard_draft(self.session.root, self._plan_outcome.draft)
        self._leave_plan()
        self.render_event(SessionEvent(kind="output", text="Draft discarded."))
        self._end_run_flow("Run stopped: no plan was saved.")

    def _leave_plan(self) -> None:
        self._plan_request = None
        self._plan_outcome = None
        self._approved_spec = None
        self._set_plan_state("")

    def action_leave_plan(self) -> None:
        if self._plan_state not in ("review", "answering"):
            return
        draft = self._plan_outcome.draft if self._plan_outcome else None
        self._leave_plan()
        where = f"It is still at {draft.path}." if draft else "Open Plan and choose Resume draft to come back."
        self.render_event(SessionEvent(kind="output", text=f"Left the plan. {where}"))
        self._end_run_flow("Run stopped: no plan was saved.")

    def _run_flow_start(self) -> None:
        """Run (spec 6a): which plan, then who does what, then check and start."""
        if self._refuse_in_home():
            return
        if self._relay_running():
            self.render_event(SessionEvent(kind="error", text="The relay is already running."))
            return
        if self._plan_state:
            self.render_event(SessionEvent(
                kind="error",
                text="A plan is already in progress: approve it, Discard it, or press Esc."))
            return
        self._run_flow = True
        if not relay_ops.list_plans(self.session.root):
            self.render_event(SessionEvent(kind="output", text="No plan yet -- let's make one."))
            self._open_relay_plan()
            return
        from whyline.console.relay_screens import RunChoiceScreen

        self.push_screen(RunChoiceScreen(), self._run_choice)

    def _run_choice(self, choice: str | None) -> None:
        if choice == "new":
            self._open_relay_plan()
        elif choice == "existing":
            self._open_relay_setup(guided=True)
        else:
            self._end_run_flow("Run cancelled.")

    def _end_run_flow(self, text: str) -> None:
        if self._run_flow:
            self._run_flow = False
            self.render_event(SessionEvent(kind="output", text=text))

    def _open_relay_setup(self, guided: bool = False, plan: Path | None = None) -> None:
        if self._refuse_in_home():
            return
        from whyline.console.relay_screens import RelaySetupScreen

        self.push_screen(
            RelaySetupScreen(self.session.root, guided=guided, plan=plan),
            self._setup_done,
        )

    def _setup_done(self, choice: str | None) -> None:
        if choice == "start":
            self._run_flow = False
            self._launch_relay(["start"])
        elif choice == "plan":
            self._run_flow = True
            self._open_relay_plan()
        else:
            self._run_flow = False


    def _relay_running(self) -> bool:
        return self._relay is not None and self._relay.running()

    def _live_relay(self) -> str | None:
        try:
            return relay_ops.live_run(self.session.root)
        except Exception:
            return None

    def _watch_external_relay(self) -> None:
        """A relay outlives the console that started it. Keep Stop usable for
        one started by another console or a terminal."""
        live = None if self._relay_running() else self._live_relay()
        if live == self._external_relay or not self.screen_stack:
            return
        self._external_relay = live
        try:
            stop = self._main("#stop", Button)
        except NoMatches:
            return
        stop.disabled = not (self._busy_text or self._relay_running() or live)

    def _launch_relay(self, args: list[str]) -> None:
        """Start/Resume, from a button or typed. One relay at a time: ours,
        or one started elsewhere (a terminal) that running.live still sees."""
        if self._refuse_in_home():
            return
        if args and args[0] == "start" and "--plan" not in args:
            try:
                has_plan = bool(relay_ops.list_plans(self.session.root))
            except Exception:
                has_plan = True  # let the relay itself report the problem
            if not has_plan:
                self.render_event(SessionEvent(kind="error", text="No plan yet. Use Plan first."))
                return
        roles = relay_ops.current_roles(self.session.root)
        uses = "antigravity" in (
            roles["implementer"], roles["tester"], roles["reviewer"], *roles["backup"]
        )
        if uses and not getattr(self, "_antigravity_ok", False):
            def proceed(allowed: bool) -> None:
                if allowed:
                    self._antigravity_ok = True
                    self._launch_relay(args)
                else:
                    self.render_event(SessionEvent(
                        kind="error",
                        text="The relay gives Antigravity a role, but this repo isn't "
                             "trusted for it. Change the role in Set up, or choose it "
                             "there again to be asked."))

            self._with_antigravity(True, proceed)
            return
        self._antigravity_ok = False
        if self._relay_running():
            self.render_event(SessionEvent(kind="error", text="The relay is already running."))
            return
        other = relay_ops.live_run(self.session.root)
        if other:
            self.render_event(SessionEvent(
                kind="error", text=f"A relay is already running here ({other})."))
            return
        self._relay = RelayProcess(
            self.session.root, args,
            on_line=lambda line: self.call_from_thread(self._relay_line, line),
            on_exit=lambda code, text: self.call_from_thread(self._relay_finished, code, text),
        )
        try:
            self._relay.start()
        except OSError as error:
            self._relay = None
            self.render_event(SessionEvent(
                kind="error", text=f"Could not start the relay ({' '.join(args)}): {error}"))
            return
        self._relay_label = f"relay: {' '.join(args)}"
        self._busy_since = time.monotonic()
        self.render_event(SessionEvent(
            kind="output", text=f"Running `whyline relay {' '.join(args)}`. Progress follows."))
        self._main("#thinking", Static).display = True
        self._main("#stop", Button).disabled = False
        self._sync_relay_buttons()

    def _relay_line(self, line: str) -> None:
        self.render_event(SessionEvent(kind="output", text=f"relay · {line}"))
        live = relay_ops.live_run(self.session.root)
        if live:
            self._relay_label = f"relay: {live}"

    def _relay_finished(self, code: int, text: str) -> None:
        self._relay = None
        self._relay_label = ""
        if not self._busy_text:
            self._main("#thinking", Static).display = False
            self._main("#stop", Button).disabled = True
        # Only the relay's own final pause counts. Agents that print tui.py or
        # a plan echo "release task for you: " into the run's output, so the
        # marker anywhere else must never start a release task.
        pause_text = ""
        lines = text.strip().splitlines()
        for index in range(len(lines) - 1, -1, -1):
            if lines[index].startswith("Paused:"):
                pause_text = "\n".join(
                    [lines[index].removeprefix("Paused:").strip(), *lines[index + 1:]]
                ).strip()
                break
        if not pause_text and text.strip().startswith("release task for you: "):
            pause_text = text.strip()
        if not pause_text and code != 0:
            try:
                from whyline_relay import state as relay_state
                saved = relay_state.load(self.session.root)
                if saved and saved.paused_reason:
                    pause_text = saved.paused_reason
            except Exception:
                pass

        if pause_text.startswith("release task for you: "):
            task_info = relay_ops.release_task(self.session.root)
            if task_info is None:
                lines = pause_text.splitlines()
                task_id = lines[0].removeprefix("release task for you:").strip()
                checklist = [l.strip() for l in lines[1:] if l.strip()]
                task_info = (task_id, checklist)
            self._release_task = task_info
            task_id, checklist = task_info
            checklist_lines = [f"{task_id} is a release task for you:"]
            for i, item in enumerate(checklist, 1):
                clean = re.sub(r"^(\d+\.|\*|-)\s*", "", item)
                checklist_lines.append(f"   {i}. {clean}")
            checklist_lines.append('Type "done" when finished, or "skip".')
            self.render_event(SessionEvent(kind="pause", text="\n".join(checklist_lines)))
            self._sync_mode_indicator()
            self._sync_relay_buttons()
            return

        event = adapters.classify_relay_output(self.session.root, text, code)
        if event.kind == "pause":
            self.render_event(event)
        elif event.kind == "output":
            self.render_event(SessionEvent(kind="output", text="Relay finished."))
        else:
            self.render_event(SessionEvent(
                kind="error",
                text=f"The relay stopped with exit code {code}. Its full output is in "
                     ".whyline/relay/logs/console-run.log.",
            ))
        self._sync_relay_buttons()

    async def action_quit(self) -> None:
        if self._relay_running():
            self.push_screen(QuitRelayScreen(self._relay_label or "relay"), self._quit_choice)
            return
        self.exit()

    def _quit_choice(self, choice: "str | None") -> None:
        if choice is None:
            return
        if self._relay is not None:
            if choice == "stop":
                self._relay.interrupt()
            self._relay.stop_following()
        self.exit()



def _exec(binary: str, argv: list[str]) -> None:
    os.execvp(binary, argv)


def launch(root: Path, *, exec_fn=None) -> None:
    if not TUI_AVAILABLE:
        raise TuiUnavailable(
            "The mouse TUI needs textual, which is missing from this "
            "install. Run: uv tool install --reinstall whyline"
        )
    if exec_fn is None:
        exec_fn = _exec
    app = WhylineConsoleApp(root=root)
    app.run()
    if app._exec_after is not None:
        binary, argv = app._exec_after
        exec_fn(binary, argv)
