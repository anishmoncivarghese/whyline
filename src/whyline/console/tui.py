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
    from textual.screen import ModalScreen, Screen
    from rich.text import Text
    from textual.widgets import (
        Button, Checkbox, DirectoryTree, Footer, Header, Input, Label, RichLog,
        Select, Static, TextArea,
    )
    from textual.widgets._select import SelectOverlay

    TUI_AVAILABLE = True
except ImportError:
    App = ModalScreen = Screen = Input = Message = TextArea = object  # placeholder bases so the classes can still be defined
    NoMatches = LookupError
    ComposeResult = None
    Horizontal = Vertical = VerticalScroll = None
    Button = Checkbox = DirectoryTree = Footer = Header = Label = RichLog = Select = None
    Static = Text = None
    events = None
    TUI_AVAILABLE = False

from whyline.console import (
    adapters,
    attachments as att,
    awake,
    file_follow,
    mac_input,
    plan_job,
    relay_ops,
    repo_setup,
    update,
)
from whyline.console.file_pane import RepoTree, active_plan_file
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
    NO_SUBSCRIPTIONS,
    RESET_BUSY_TEXT,
    _HOME_REFUSAL,
    _RELAY_MISSING,
    _UNSET,
    _accepts_kwarg,
    _agents_command as agents_command_event,
    _is_home,
    _run_login,
    after_login,
    backup_chain_sentence,
    busy_label,
    clear_chat_override,
    dispatch,
    handle_slash_command,
    home_repo_warning,
    login_argv,
    NO_RELEASE_PAUSE,
    provider_enabled,
    strip_relay_prefix,
    named_row,
    repo_switch_warning,
    reset_failover_text,
    run_result_text,
    switch_repo,
    unknown_command_text,
)
from whyline.console.session import ConsoleSession, SessionEvent

_PREFIX = {"error": "⚠ ", "pause": "⏸ ", "input": "› "}

_MODES = ("chat", "relay", "agents", "assistant")
# Agents widgets arrive with the Agents plan. Until then these ids match nothing.
_MODE_BUTTONS = {
    "chat": ("model", "brainstorm", "history"),
    "relay": ("relay-run", "relay-plan", "relay-setup", "relay-resume"),
    "agents": (
        "agents-new",
        "agents-list",
        "agents-runs",
        "agents-scheduler",
    ),
    "assistant": ("assistant-inbox", "assistant-ideas", "assistant-open", "assistant-check"),
}
_SHARED_BUTTONS = ("see-files", "awake", "stop", "help", "copy", "settings")
# Files shows the plan and the files an agent is changing; Agents and
# Assistant work on no checkout, so it has nothing to show there.
_HIDDEN_SHARED = {"agents": {"see-files"}, "assistant": {"see-files"}}
_AWAKE_ON_TEXT = (
    "The Mac stays awake until you turn this off, even after the console closes. "
    "Closing the lid still sleeps it unless it is plugged into a display."
)
_SLASH_HINT = "/status /timeline /note /decisions /handoff /model /timeout /repo /help"

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
# Action row on the agent menu once Backup has left the row.
_CB_BACKUP_MENU = "backup-menu"
_CB_TIMEOUT_OPTIONS: list[tuple[str, int | str]] = [
    ("5m", 300),
    ("15m", 900),
    ("30m", 1800),
    ("45m", 2700),
    ("60m", 3600),
    ("none", "none"),
]


def _cb_options(status: dict) -> list[tuple[str, str]]:
    """Enabled providers only: available first, then unusable ones with `!`."""
    available: list[tuple[str, str]] = []
    unavailable: list[tuple[str, str]] = []
    for agent, info in status.items():
        if not isinstance(info, dict):
            info = {}
        if not provider_enabled(info):
            continue
        detail = info.get("label", "")
        label = f"{agent} · {_CB_SHORT_LABELS.get(detail, detail)}"
        if info.get("available"):
            available.append((label, agent))
        else:
            unavailable.append((label, f"!{agent}"))
    return available + unavailable


def _cb_select_options(status: dict) -> list[tuple[str, str]]:
    """Options for the agent Select; never a silent Claude fallback."""
    return _cb_options(status) or [("No subscriptions", "")]


def _cb_status_key(status: dict) -> tuple[tuple[str, bool, bool, str], ...]:
    """Enablement, availability and labels. The saved agent, model and repo are separate."""
    key = []
    for agent, info in status.items():
        if not isinstance(info, dict):
            info = {}
        key.append((
            str(agent),
            provider_enabled(info),
            bool(info.get("available")),
            str(info.get("label") or ""),
        ))
    return tuple(key)


def _cb_match_option(current: object, options: list[tuple[str, str]]) -> str:
    """The same agent in `options`, keeping or dropping the unavailable `!`."""
    values = [value for _label, value in options]
    if not values:
        return ""
    if isinstance(current, str) and current != _CB_BACKUP_MENU:
        name = current[1:] if current.startswith("!") else current
        for candidate in (name, f"!{name}"):
            if candidate in values:
                return candidate
    return options[0][1]


def _cb_agent_name(value: object) -> str:
    """The agent id, without the unavailable `!` marker."""
    if isinstance(value, str) and value.startswith("!"):
        return value[1:]
    return str(value)


def _model_rejected(value: str) -> bool:
    """Save writes nothing for an empty name, or one with a space or a quote.

    A blank field is not the agent's default on Save. Whitespace alone is
    empty. A name that still has characters is rejected when any character
    is a space or a quote.
    """
    if not value.strip():
        return True
    return any(ch.isspace() or ch in "\"'" for ch in value)


def _cb_dedupe(names) -> tuple[str, ...]:
    """First occurrence of each non-empty name, in order."""
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return tuple(out)


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

    def __init__(self, label: str, awake_on: bool = False) -> None:
        super().__init__()
        self._label = label
        self._awake_on = awake_on
        self.keep_awake = True

    def compose(self) -> ComposeResult:
        rows = [
            Label(f"The relay is still working ({self._label}). Leave it running?"),
            Horizontal(
                Button("Leave it running", id="quit-leave", variant="primary"),
                Button("Stop it, then quit", id="quit-stop", variant="warning"),
                Button("Cancel", id="quit-cancel"),
            ),
        ]
        if self._awake_on:
            # A choice, not an exit: the row above still decides when to quit.
            rows += [
                Label("Keep the Mac awake?"),
                Horizontal(
                    Button("Keep awake", id="quit-keep-awake", variant="primary"),
                    Button("Let it sleep", id="quit-let-sleep"),
                ),
            ]
        yield Vertical(*rows)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id in ("quit-keep-awake", "quit-let-sleep"):
            self.keep_awake = event.button.id == "quit-keep-awake"
            self.query_one("#quit-keep-awake", Button).variant = "primary" if self.keep_awake else "default"
            self.query_one("#quit-let-sleep", Button).variant = "default" if self.keep_awake else "primary"
            return
        choices = {"quit-leave": "leave", "quit-stop": "stop"}
        self.dismiss(choices.get(event.button.id))


class QuitAwakeScreen(ModalScreen):
    """Asked on quit while Awake is on and no relay is running."""

    DEFAULT_CSS = """
    QuitAwakeScreen { align: center middle; }
    QuitAwakeScreen > Vertical {
        width: 70; height: auto; padding: 1 2; border: thick $warning; background: $surface;
    }
    QuitAwakeScreen Horizontal { height: auto; margin-top: 1; }
    QuitAwakeScreen Button { margin-right: 2; }
    """

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Keep the Mac awake?"),
            Horizontal(
                Button("Keep awake", id="quit-keep-awake", variant="primary"),
                Button("Let it sleep", id="quit-let-sleep"),
                Button("Cancel", id="quit-cancel"),
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#quit-keep-awake", Button).focus()

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        choices = {"quit-keep-awake": "keep", "quit-let-sleep": "sleep"}
        self.dismiss(choices.get(event.button.id))


_TEST_PLANNER_TIP = "Tip: a different agent from the Drafter catches more."


class _BrainstormChoice(dict):
    """Brainstorm form dict with `.test_planner` attribute so `**choice` unpacks
    only the kwargs `adapters.run_brainstorm` accepts."""

    test_planner: str = ""


def brainstorm_field_widgets(
    status: dict,
    default_final: str,
    root: Path | None = None,
    session: str | None = None,
    *,
    keep_disabled_ids: bool = True,
) -> list:
    """Topic, models, passes, final writer, timeout, and attachments -- shared by the
    Brainstorm popup and the Plan popup's brainstorm source.

    Disabled providers are not shown. `keep_disabled_ids` (the default) still
    mounts hidden, unchecked boxes so Plan's existing per-id `#bs-*` queries
    resolve without this task editing relay_screens.py. BrainstormScreen
    passes False and omits those ids entirely.
    """
    enabled = [
        agent for agent in BRAINSTORM_AGENTS if provider_enabled(status.get(agent))
    ]
    boxes = []
    if not enabled:
        boxes.append(Static(NO_SUBSCRIPTIONS, id="bs-empty", markup=False))
    for agent in BRAINSTORM_AGENTS:
        info = status.get(agent) or {}
        if provider_enabled(info):
            boxes.append(
                Checkbox(
                    f"{agent:<12} {info.get('label', '')}",
                    value=bool(info.get("available")),
                    disabled=not info.get("available"),
                    id=f"bs-{agent}",
                )
            )
            continue
        if keep_disabled_ids:
            box = Checkbox(
                f"{agent:<12} {info.get('label', '')}",
                value=False,
                disabled=True,
                id=f"bs-{agent}",
            )
            box.display = False
            boxes.append(box)
    default_test = ""
    if root is not None:
        try:
            planner_cfg = relay_ops.planner_agents(root)
            if len(planner_cfg) >= 3 and planner_cfg[2]:
                default_test = str(planner_cfg[2])
        except Exception:
            default_test = ""
    test_options: list[tuple[str, str]] = [("None", ""), *((a, a) for a in enabled)]
    final_value = default_final if default_final in enabled else (enabled[0] if enabled else "")
    fields = [
        Input(placeholder="Topic, e.g. how the relay should handle a failed Codex run",
              id="bs-topic"),
        Label("Models:", classes="field-label"),
        *boxes,
        Horizontal(Label("Review passes:", classes="field-label"), Input("1", id="bs-passes")),
    ]
    if enabled:
        fields.extend([
            Horizontal(
                Label("Final write-up:", classes="field-label"),
                Select([(a, a) for a in enabled], value=final_value,
                       allow_blank=False, id="bs-final"),
            ),
            Horizontal(
                Label("Test planner:", classes="field-label"),
                Select(
                    test_options,
                    value=default_test if any(v == default_test for _, v in test_options) else "",
                    allow_blank=False,
                    id="bs-test-planner",
                ),
                id="bs-test-planner-row",
            ),
            Static(_TEST_PLANNER_TIP, id="bs-test-planner-tip", markup=False),
        ])
    fields.extend([
        Horizontal(
            Label("Per-agent timeout:", classes="field-label"),
            Select(
                [(f"{m} minutes", m) for m in BRAINSTORM_TIMEOUT_OPTIONS]
                + [("none", "none")],
                value=15, allow_blank=False, id="bs-timeout",
            ),
        ),
        AttachmentsField(root or Path("."), session or "", id="bs-attachments"),
    ])
    return fields


def _bound_query(query_one):
    """The owner's `query` when `query_one` is a bound method, else None."""
    owner = getattr(query_one, "__self__", None)
    query = getattr(owner, "query", None) if owner is not None else None
    return query if callable(query) else None


def _rendered_brainstorm_checkboxes(query_one) -> list[tuple[str, object]] | None:
    """Provider checkboxes that were actually composed, or None if unknown.

    Bound screens list Checkbox widgets so disabled (unrendered) ids are
    never queried. An unbound `query_one(selector)` callable has no owner
    `query`; callers then use the original per-id lookups.
    """
    query = _bound_query(query_one)
    if query is None or Checkbox is None:
        return None
    by_agent = {}
    for widget in query(Checkbox):
        if getattr(widget, "display", True) is False:
            continue
        ident = getattr(widget, "id", None) or ""
        if not ident.startswith("bs-"):
            continue
        agent = ident[3:]
        if agent in BRAINSTORM_AGENTS:
            by_agent[agent] = widget
    return [(agent, by_agent[agent]) for agent in BRAINSTORM_AGENTS if agent in by_agent]


def _brainstorm_checkbox_values(query_one) -> list[tuple[str, object]]:
    """Visible provider checkboxes from a bound owner, else per-id lookups."""
    rendered = _rendered_brainstorm_checkboxes(query_one)
    if rendered is not None:
        return rendered
    return [
        (agent, query_one(f"#bs-{agent}", Checkbox)) for agent in BRAINSTORM_AGENTS
    ]


def brainstorm_checked_agents(query_one) -> list[str]:
    """Ids of composed #bs-* checkboxes that are on.

    Bound owners never probe unrendered ids. Unbound query_one callables
    keep the original per-id BRAINSTORM_AGENTS lookups.
    """
    boxes = _brainstorm_checkbox_values(query_one)
    if not boxes:
        return []
    return [agent for agent, box in boxes if box.value]


def collect_brainstorm(query_one) -> "dict | str":
    """The brainstorm fields' values, or a message saying what's missing.
    `query_one` is the owning screen's query_one."""
    topic = query_one("#bs-topic", Input).value.strip()
    if not topic:
        return "Enter a topic."
    rendered = _brainstorm_checkbox_values(query_one)
    if not rendered:
        return NO_SUBSCRIPTIONS
    agents = [agent for agent, box in rendered if box.value]
    if not agents:
        return "Pick at least one model."
    raw = query_one("#bs-passes", Input).value.strip() or "0"
    if not raw.isdigit():
        return "Review passes must be a whole number (0 or more)."
    final = query_one("#bs-final", Select).value
    timeout = query_one("#bs-timeout", Select).value
    attachments = query_one("#bs-attachments", AttachmentsField).pending.paths()
    test_planner = ""
    try:
        raw_test = query_one("#bs-test-planner", Select).value
        if isinstance(raw_test, str):
            test_planner = raw_test
    except Exception:
        test_planner = ""
    choice = _BrainstormChoice(
        {
            "topic": topic,
            "agents": agents,
            "passes": int(raw),
            "final_agent": final if final in agents else agents[0],
            "attachments": attachments,
        }
    )
    choice.test_planner = test_planner
    if timeout == "none":
        choice["timeout_unlimited"] = True
        return choice
    if timeout not in BRAINSTORM_TIMEOUT_OPTIONS:
        return "Choose a timeout of 15, 30, 45, or 60 minutes, or none."
    choice["timeout_minutes"] = timeout
    choice["timeout_unlimited"] = False
    return choice


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
    BrainstormScreen #bs-test-planner { width: 30; }
    BrainstormScreen #bs-test-planner-tip { color: $text-muted; height: auto; display: none; }
    BrainstormScreen #bs-timeout { width: 30; }
    BrainstormScreen #bs-error { color: $error; height: auto; }
    BrainstormScreen #bs-error.-empty { display: none; }
    BrainstormScreen #bs-buttons { margin-top: 1; }
    BrainstormScreen #bs-buttons Button { margin-right: 2; }
    """

    def __init__(self, status: dict, active: str) -> None:
        super().__init__()
        self._status = status
        self._enabled = [
            agent for agent in BRAINSTORM_AGENTS if provider_enabled(status.get(agent))
        ]
        self._usable = [
            agent for agent in self._enabled if (status.get(agent) or {}).get("available")
        ]
        self._default_final = active if active in self._usable else (
            self._usable[0] if self._usable else (self._enabled[0] if self._enabled else "")
        )

    def compose(self) -> ComposeResult:
        # Only the fields scroll; the error line and buttons stay pinned
        # below them, so Start can never be pushed out of view.
        fields = VerticalScroll(
            Label("Brainstorm: each model researches on its own, reviews the others, "
                  "then one writes it up in docs/brainstorm/."),
            *brainstorm_field_widgets(
                self._status,
                self._default_final,
                self.app.session.root,
                self.app._attach_session,
                keep_disabled_ids=False,
            ),
            id="bs-fields",
        )
        if self._enabled:
            buttons = [
                Button("Start", id="bs-start", variant="success"),
                Button("Cancel", id="bs-cancel"),
            ]
        else:
            buttons = [
                Button("Open Settings", id="bs-open-settings", variant="primary"),
                Button("Cancel", id="bs-cancel"),
            ]
        yield Vertical(
            fields,
            Static("", id="bs-error", classes="-empty", markup=False),
            Horizontal(*buttons, id="bs-buttons"),
        )

    def on_mount(self) -> None:
        self.query_one("#bs-topic", Input).focus()
        self._sync_attachment_agents()
        self._sync_test_planner_tip()

    def _sync_test_planner_tip(self) -> None:
        try:
            tip = self.query_one("#bs-test-planner-tip", Static)
            test_val = self.query_one("#bs-test-planner", Select).value
        except Exception:
            return
        drafter = "codex"
        if getattr(self, "app", None) is not None and getattr(self.app, "session", None) is not None:
            try:
                drafter = relay_ops.planner_agents(self.app.session.root)[0]
            except Exception:
                drafter = "codex"
        tip.display = bool(test_val) and test_val == drafter

    def _save_test_planner(self, chosen: dict) -> None:
        test_val = getattr(chosen, "test_planner", "")
        try:
            raw_val = self.query_one("#bs-test-planner", Select).value
            if isinstance(raw_val, str):
                test_val = raw_val
        except Exception:
            pass
        if getattr(self, "app", None) is None or getattr(self.app, "session", None) is None:
            return
        root = self.app.session.root
        try:
            planner_cfg = relay_ops.planner_agents(root)
            draft, review = planner_cfg[0], planner_cfg[1]
        except Exception:
            draft, review = "codex", "claude"
        try:
            relay_ops.save_planner(root, draft, review, test_val)
        except TypeError:
            try:
                relay_ops.save_planner(root, draft, review)
            except Exception:
                pass
        except Exception:
            pass

    def _sync_attachment_agents(self) -> None:
        try:
            field = self.query_one("#bs-attachments", AttachmentsField)
        except Exception:
            return
        agents = brainstorm_checked_agents(self.query_one)
        field.set_agents(agents)
        try:
            test_val = self.query_one("#bs-test-planner", Select).value
            if isinstance(test_val, str) and test_val and test_val not in agents:
                field.set_agents([*agents, test_val])
        except Exception:
            pass

    def on_select_changed(self, event: "Select.Changed") -> None:
        if event.select.id in ("bs-test-planner", "bs-final"):
            self._sync_test_planner_tip()
            self._sync_attachment_agents()

    def on_checkbox_changed(self, event: "Checkbox.Changed") -> None:
        if event.checkbox.id and event.checkbox.id.startswith("bs-"):
            self._sync_attachment_agents()

    def on_input_submitted(self, event: "Input.Submitted") -> None:
        event.stop()  # handled here; must not reach the console behind
        try:
            self.query_one("#bs-start", Button).press()
        except NoMatches:
            return

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "bs-cancel":
            self.dismiss(None)
            return
        if event.button.id == "bs-open-settings":
            self.dismiss("open-settings")
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
                    self._save_test_planner(chosen)
                    self.dismiss(chosen)

            self.app.push_screen(
                ConfirmScreen(
                    f"{', '.join(risky)} get images as file paths only and may not see them.",
                    "Continue",
                ),
                answered,
            )
            return
        self._save_test_planner(chosen)
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


class FollowView(TextArea):
    """File viewer that notifies the app when the user scrolls."""

    def watch_scroll_x(self, old_value: float = 0.0, new_value: float = 0.0) -> None:
        if hasattr(super(), "watch_scroll_x"):
            super().watch_scroll_x(old_value, new_value)
        if hasattr(self, "app") and hasattr(self.app, "_note_file_scroll"):
            self.app._note_file_scroll()

    def watch_scroll_y(self, old_value: float = 0.0, new_value: float = 0.0) -> None:
        if hasattr(super(), "watch_scroll_y"):
            super().watch_scroll_y(old_value, new_value)
        if hasattr(self, "app") and hasattr(self.app, "_note_file_scroll"):
            self.app._note_file_scroll()


class _FileTree(RepoTree):
    """RepoTree without DirectoryTree's perpetual loader worker.

    DirectoryTree._loader waits on an empty queue forever. Existing
    console tests await ``app.workers.wait_for_complete()``, which
    would never return. ``reload_node`` already lists a directory on a
    short-lived thread worker.
    """

    def reload(self):
        from asyncio import Queue

        self._load_queue = Queue()
        return self.reload_node(self.root)

    async def _on_tree_node_expanded(self, event) -> None:
        event.stop()
        dir_entry = event.node.data
        if dir_entry is None:
            return
        if self._safe_is_dir(dir_entry.path):
            if dir_entry.loaded:
                return
            await self.reload_node(event.node)
        else:
            self.post_message(self.FileSelected(event.node, dir_entry.path))


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
    #modes, #input-row, #controls { height: auto; }
    /* Dense mode bars wrap so every control
       stays inside 80 columns. Chat and Relay still fit on one row. */
    #controls.wrap {
      layout: grid;
      grid-size: 6;
    }
    /* Only a bar wider than the window wraps; see _fit_controls. */
    /* One row. A wrapped prompt would push Save onto a second line. */
    #context-bar { height: 1; text-wrap: nowrap; }
    #modes-label { width: auto; padding: 1 1 0 1; }
    #cb-agent { width: 24; }
    /* The open list may be wider than the box, so no agent wraps. */
    #cb-agent > SelectOverlay { width: 36; }
    /* Hidden until a chat override differs from the saved primary. */
    #cb-failover { width: auto; height: 1; display: none; }
    #cb-backup { width: 18; }
    #cb-backup > SelectOverlay { width: 56; }
    #cb-backup-more { width: auto; height: 1; min-width: 2; }
    #cb-model { width: 18; }
    #cb-timeout { width: 10; }
    #cb-timeout > SelectOverlay { width: 14; }
    #cb-repo { width: 1fr; }
    #context-bar Label { padding: 0 0 0 1; height: 1; }
    #context-bar SelectCurrent { height: 1; text-wrap: nowrap; }
    /* Select, Input, Checkbox and Button draw a tall border (2-3 rows). In a
       one-row bar that clips them to their top edge, hiding every value, so
       flatten them to one row and mark each field with a background. */
    #context-bar Select, #context-bar Input, #context-bar Checkbox,
    #context-bar Button { height: 1; min-height: 1; border: none; }
    #context-bar SelectCurrent { border: none; padding: 0 1; background: $boost; }
    #context-bar Input { padding: 0 1; background: $boost; }
    #context-bar Input:focus, #context-bar Select:focus > SelectCurrent { background: $primary 30%; }
    #context-bar Checkbox { padding: 0 1; background: transparent; }
    #context-bar Button { padding: 0 1; min-width: 6; }
    #thinking { height: 1; padding: 0 1; color: $accent; display: none; }
    /* Scheduler status. Inbox is an Agents-mode button on #controls. */
    #agents-bar { height: auto; display: none; }
    #agents-status { height: auto; width: 1fr; padding: 0 1; color: $text-muted; }
    #slash-hint { height: 1; padding: 0 1; color: $text-muted; display: none; }
    Input#prompt { width: 1fr; }
    #plan-actions { height: auto; display: none; }
    #manual-actions { height: auto; display: none; }
    #pause-actions { height: auto; display: none; }
    #resolve-actions { height: auto; display: none; }
    #relay-resolve { display: none; }
    #relay-retry-stage { display: none; }
    /* Shown only once there is something to update to. */
    #update, #update-restart { display: none; }
    #split { height: 1fr; }
    #split.stacked { layout: vertical; }
    #console-column { width: 1fr; height: 1fr; }
    #file-pane { width: 1fr; height: 1fr; display: none; }
    #file-path { width: 1fr; height: 1; padding: 0 1; }
    #file-view { height: 1fr; min-height: 0; }
    #file-tree { height: 1fr; min-height: 0; display: none; }
    #file-pane Horizontal { height: auto; }
    #file-choices { width: 1fr; height: auto; }
    /* One row at 80x24: default 3-row buttons would push #file-view off. */
    #file-choices Button { height: 1; min-height: 1; border: none; padding: 0 1; }
    #file-working, #file-plan, #file-all { display: none; }
    """

    def __init__(self, *, root: Path, runner: Any = None) -> None:
        from whyline import model

        super().__init__()
        self.session = ConsoleSession(root=root)
        self.session.agent = model.resolve(root)[0]
        self.session._sync_timeout = self._cb_sync_timeout
        self._files_on: bool = False
        self._file_choice: str = "working"
        self._plan_shown_path: str | None = None
        self._plan_snap: file_follow.Snap | None = None
        self._plan_last_error: str | None = None
        # Shared with every other console through ~/.whyline/awake.json.
        self._awake: awake.Awake | None = awake.status()
        self._follow_base: dict[str, file_follow.Snap] = {}
        self._follow_order: list[str] = []
        self._follow_index: int | None = None
        self._follow_hold: bool = False
        self._follow_shown: dict[str, str] = {}
        self._follow_offset: int = 0
        self._follow_flying: bool = False
        self._follow_user_scrolled: bool = False
        self._follow_moving: bool = False
        self._follow_timer: Any = None
        self._follow_last_error: str | None = None
        self._dispatch_token: object | None = None
        self._cancel_event = None
        self._exec_after: tuple[str, list[str]] | None = None
        self._update_check = update.check
        self._update_problem = update.install_problem
        self._update_install = update.install
        self._update_offer: tuple[str, str | None, bool] | None = None  # version, notes, reinstall
        self._update_note: str | None = None
        self._update_running = False
        self._update_installed = False
        self._update_problem_text: Any = _UNSET
        self._update_timer: Any = None
        self._login_fn = _run_login
        self._busy_text = ""
        self._busy_since = 0.0
        self._spin = 0
        self._auto_cancel_event = None
        self._relay = None  # the RelayProcess started by Start/Resume, if any
        self._relay_label = ""
        self._external_relay: str | None = None  # a relay another console started
        self._antigravity_ok = False
        self._release_task: tuple[str, list[str]] | None = None
        self._manual_task_id: str | None = None
        self._manual_checks: list[Any] = []
        self._manual_check: Any = None
        self._manual_fail_id: str | None = None
        self._manual_passed: bool = False
        self._passed_manual_ids: set[str] = set()
        self._failed_manual_ids: set[str] = set()
        self._manual_exited: bool = False
        self._relay_launch_aborted: bool = False
        self._plan_state = ""  # "", "working", "review", "answering"
        self._plan_request: plan_job.PlanRequest | None = None
        self._plan_outcome: plan_job.Outcome | None = None
        self._approved_spec: Path | None = None
        self._setup_plan_hint: Path | None = None
        self._transcript: RichLog | None = None
        self._stale_pause: str | None = None
        self._run_flow = False
        self._pending = att.PendingAttachments()
        self._attach_session = att.session_name()
        self._sent_attachments: list = []
        self._cb_saved: tuple[str, str, str, tuple[str, ...]] | None = None
        self._cb_chain: tuple[str, ...] = ()
        self._cb_backup_real = "none"
        self._cb_backup_unreadable: str | None = None
        self._cb_agent_shown: str | None = None
        self._cb_status_seen: tuple[tuple[str, bool, str], ...] | None = None
        self._cb_refreshing = False
        self._agents_name: str | None = None
        self._editing_agent_id: str | None = None
        self._recovering_pause = False
        self._runner = runner
        self._auto_relay = False
        self._auto_request: plan_job.AutoRunRequest | None = None
        self._resolve_source: str = ""
        self._resolve_source_fail_lines: list[str] = []
        self._resolve_problems: list = []
        self._resolve_problem: Any = None
        self._resolve_running: bool = False
        self._resume_fail_lines: list[str] = []
        self._last_relay_args: list[str] = []

    def __setattr__(self, name: str, value: Any) -> None:
        if (
            name == "_launch_relay"
            and callable(value)
            and not getattr(value, "_is_launch_relay_wrapper", False)
        ):
            orig = value

            def _wrapped(args: list[str], *a: Any, **kw: Any) -> Any:
                self._last_relay_args = list(args)
                return orig(args, *a, **kw)

            _wrapped._is_launch_relay_wrapper = True  # type: ignore[attr-defined]
            value = _wrapped
        super().__setattr__(name, value)

    def _main_widget(self, selector: str, expect_type=None):
        try:
            return self._main(selector, expect_type)
        except Exception:
            try:
                return self.query_one(selector, expect_type)
            except Exception:
                return None

    def _set_file_path(self, text: str) -> None:
        label = self._main_widget("#file-path", Static)
        if label is not None:
            label.update(text)

    def _sync_follow_buttons(self) -> None:
        earlier = self._main_widget("#file-earlier", Button)
        later = self._main_widget("#file-later", Button)
        if earlier is None or later is None:
            return
        if not self._follow_order or self._follow_index is None:
            earlier.disabled = True
            later.disabled = True
            return
        earlier.disabled = (self._follow_index <= 0)
        later.disabled = (self._follow_index >= len(self._follow_order) - 1)

    def _effective_file_choice(self) -> str:
        if self.session.mode == "relay":
            return self._file_choice
        return "working"

    def _sync_file_choice_widgets(self) -> None:
        in_relay_files = bool(self._files_on) and self.session.mode == "relay"
        if self.session.mode != "relay" and self._file_choice != "working":
            self._file_choice = "working"
            self._hide_file_tree()
            self._show_newest_working_file()
        for name in ("working", "plan", "all"):
            button = self._main_widget(f"#file-{name}", Button)
            if button is None:
                continue
            button.display = in_relay_files
            button.variant = "success" if self._file_choice == name else "default"
        show_nav = self._effective_file_choice() == "working"
        for selector in ("#file-earlier", "#file-later"):
            button = self._main_widget(selector, Button)
            if button is not None:
                button.display = show_nav

    def _hide_file_tree(self) -> None:
        tree = self._main_widget("#file-tree")
        if tree is not None:
            tree.display = False
        view = self._main_widget("#file-view")
        if view is not None:
            view.display = True

    def _show_file_tree(self) -> None:
        tree = self._main_widget("#file-tree")
        if tree is not None:
            tree.display = True
        view = self._main_widget("#file-view")
        if view is not None:
            view.display = False

    def _select_file_choice(self, choice: str) -> None:
        if choice == "all":
            tree = self._main_widget("#file-tree")
            already_showing = tree is not None and tree.display
            self._file_choice = "all"
            self._sync_file_choice_widgets()
            if already_showing:
                return
            self._show_file_tree()
            return
        self._file_choice = choice
        self._sync_file_choice_widgets()
        if choice == "plan":
            self._hide_file_tree()
            self._load_plan()
        elif choice == "working":
            self._hide_file_tree()
            self._show_newest_working_file()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        control = getattr(event, "control", None)
        if getattr(control, "id", None) != "file-tree":
            return
        if self._effective_file_choice() != "all":
            return
        self._open_tree_file(Path(event.path))

    def _open_tree_file(self, path: Path) -> None:
        self._hide_file_tree()
        view = self._main_widget("#file-view", FollowView)
        relative = self._plan_relative(path)
        try:
            raw = Path(path).read_bytes()
        except FileNotFoundError:
            if view is not None:
                self._follow_moving = True
                try:
                    view.load_text("")
                    view.scroll_x = 0
                    view.scroll_y = 0
                finally:
                    self._follow_moving = False
            self._set_file_path("Deleted")
            return
        except OSError as exc:
            self._set_file_path(f"{relative}: {exc}")
            return
        notice = file_follow.classify(raw)
        if view is None:
            if notice is not None:
                self._set_file_path(f"{relative} — {notice}")
            else:
                self._set_file_path(relative)
            return
        self._follow_moving = True
        try:
            if notice is not None:
                view.load_text("")
                self._set_file_path(f"{relative} — {notice}")
            else:
                view.load_text(raw.decode("utf-8"))
                self._set_file_path(relative)
            view.scroll_x = 0
            view.scroll_y = 0
        finally:
            self._follow_moving = False

    def _show_newest_working_file(self) -> None:
        self._plan_shown_path = None
        self._follow_hold = False
        self._follow_user_scrolled = False
        if not self._follow_order:
            self._follow_index = None
            self._set_file_path(
                "No file yet. A file opens here when an agent writes one."
            )
            view = self._main_widget("#file-view", FollowView)
            if view is not None:
                self._follow_moving = True
                try:
                    view.load_text("")
                    view.scroll_x = 0
                    view.scroll_y = 0
                finally:
                    self._follow_moving = False
            self._sync_follow_buttons()
            return
        path = self._follow_order[-1]
        self._follow_index = len(self._follow_order) - 1
        text = self._follow_shown.get(path, "")
        self._set_file_path(path)
        view = self._main_widget("#file-view", FollowView)
        if view is not None:
            self._follow_moving = True
            try:
                view.load_text(text)
                view.move_cursor((0, 0))
                view.scroll_cursor_visible()
            finally:
                self._follow_moving = False
        self._sync_follow_buttons()

    def _plan_relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.session.root).as_posix()
        except ValueError:
            try:
                return path.resolve().relative_to(self.session.root.resolve()).as_posix()
            except Exception:
                return path.as_posix()

    def _show_plan_error(self, reason: str) -> None:
        if reason == self._plan_last_error:
            return
        self._set_file_path(reason)
        self._plan_last_error = reason

    def _poll_plan(self) -> None:
        path = active_plan_file(self.session.root)
        if path is None:
            if self._plan_shown_path is not None:
                self._load_plan()
            return
        try:
            st = path.stat()
        except OSError as exc:
            self._show_plan_error(f"{self._plan_relative(path)}: {exc}")
            return
        snap = file_follow.Snap(st.st_mtime_ns, st.st_size)
        if snap == self._plan_snap and self._plan_relative(path) == self._plan_shown_path:
            return
        self._load_plan()

    def _load_plan(self) -> None:
        view = self._main_widget("#file-view", FollowView)
        if view is None:
            return
        path = active_plan_file(self.session.root)
        if path is None:
            self._follow_moving = True
            try:
                view.load_text("")
                view.scroll_x = 0
                view.scroll_y = 0
            finally:
                self._follow_moving = False
            self._set_file_path("No plan yet.")
            self._plan_shown_path = None
            self._plan_snap = None
            self._plan_last_error = None
            return
        relative = self._plan_relative(path)
        try:
            raw = path.read_bytes()
            st = path.stat()
        except OSError as exc:
            self._show_plan_error(f"{relative}: {exc}")
            return
        snap = file_follow.Snap(st.st_mtime_ns, st.st_size)
        keep_scroll = (
            self._effective_file_choice() == "plan"
            and self._plan_shown_path == relative
        )
        sx, sy = view.scroll_x, view.scroll_y
        notice = file_follow.classify(raw)
        self._follow_moving = True
        try:
            if notice is not None:
                view.load_text("")
                self._set_file_path(f"{relative} — {notice}")
            else:
                view.load_text(raw.decode("utf-8"))
                self._set_file_path(relative)
            if keep_scroll:
                view.scroll_x = sx
                view.scroll_y = sy
            else:
                view.scroll_x = 0
                view.scroll_y = 0
        finally:
            self._follow_moving = False
        self._plan_shown_path = relative
        self._plan_snap = snap
        self._plan_last_error = None

    def _note_file_scroll(self) -> None:
        """Called by FollowView on scroll."""
        if not getattr(self, "_follow_moving", False):
            self._follow_user_scrolled = True

    def _on_file_earlier(self) -> None:
        if self._effective_file_choice() != "working":
            return
        if not self._follow_order:
            return
        if self._follow_index is None:
            self._follow_index = len(self._follow_order) - 1
        if self._follow_index > 0:
            self._follow_index -= 1
            self._follow_hold = True
            self._follow_user_scrolled = False
            path = self._follow_order[self._follow_index]
            newer = len(self._follow_order) - 1 - self._follow_index
            self._set_file_path(f"{path} · held · {newer} newer" if newer > 0 else path)
            text = self._follow_shown.get(path, "")
            view = self._main_widget("#file-view", FollowView)
            if view is not None:
                self._follow_moving = True
                try:
                    view.load_text(text)
                    view.move_cursor((0, 0))
                    view.scroll_cursor_visible()
                finally:
                    self._follow_moving = False
            self._sync_follow_buttons()

    def _on_file_later(self) -> None:
        if self._effective_file_choice() != "working":
            return
        if not self._follow_order or self._follow_index is None:
            return
        if self._follow_index < len(self._follow_order) - 1:
            self._follow_index += 1
            self._follow_user_scrolled = False
            path = self._follow_order[self._follow_index]
            if self._follow_index == len(self._follow_order) - 1:
                self._follow_hold = False
                self._set_file_path(path)
            else:
                newer = len(self._follow_order) - 1 - self._follow_index
                self._set_file_path(f"{path} · held · {newer} newer")
            text = self._follow_shown.get(path, "")
            view = self._main_widget("#file-view", FollowView)
            if view is not None:
                self._follow_moving = True
                try:
                    view.load_text(text)
                    view.move_cursor((0, 0))
                    view.scroll_cursor_visible()
                finally:
                    self._follow_moving = False
            self._sync_follow_buttons()

    def _watched_repos(self) -> list[Path]:
        root = self.session.root
        repos = [root]
        if self._relay_running() or (self._live_relay() is not None) or bool(getattr(self, "_external_relay", None)):
            try:
                from whyline_relay import loop as relay_loop, plan as relay_plan, state as relay_state

                st = relay_state.load(root)
                if st and st.plan and st.task_id:
                    plan_path = Path(st.plan)
                    if not plan_path.is_absolute():
                        plan_path = root / plan_path
                    if plan_path.is_file():
                        tasks = relay_plan.parse(plan_path.read_text(encoding="utf-8"))
                        task = relay_plan.find(tasks, st.task_id)
                        if task is not None:
                            t_repo = relay_loop.task_repo(root, task)
                            if t_repo:
                                t_res = t_repo.resolve()
                                if t_res != root.resolve() and t_res not in [r.resolve() for r in repos]:
                                    repos.append(t_repo)
            except Exception:
                pass
        return repos

    def _arm_follow(self) -> None:
        if self._follow_timer is not None:
            return
        self._follow_base = {}
        for repo in self._watched_repos():
            try:
                res = subprocess.run(
                    ["git", "-C", str(repo), *file_follow.porcelain_argv()],
                    capture_output=True,
                    check=True,
                )
                paths = file_follow.parse_porcelain_z(res.stdout)
                repo_res = repo.resolve()
                for rel in paths:
                    if file_follow.is_ignored(rel):
                        continue
                    cand = (repo / rel).resolve()
                    if not cand.is_relative_to(repo_res):
                        continue
                    try:
                        st = cand.stat()
                    except OSError:
                        continue
                    disp = file_follow.display_path(self.session.root, repo, rel)
                    self._follow_base[disp] = file_follow.Snap(st.st_mtime_ns, st.st_size)
            except Exception:
                pass
        # Files turned on mid-run: the agent's earlier writes are all in the
        # baseline, so the pane would wait for the next write. Leave the
        # newest one out and the first tick opens it.
        if self._follow_base:
            newest = max(self._follow_base, key=lambda p: self._follow_base[p].mtime_ns)
            del self._follow_base[newest]
        ledger = self.session.root / ".whyline" / "ledger.jsonl"
        try:
            self._follow_offset = ledger.stat().st_size if ledger.is_file() else 0
        except OSError:
            self._follow_offset = 0
        self._follow_flying = False
        try:
            self._follow_timer = self.set_interval(0.4, self._follow_tick)
        except RuntimeError:
            self._follow_timer = "active"

    def _disarm_follow(self) -> None:
        if self._follow_timer is not None:
            if hasattr(self._follow_timer, "stop"):
                self._follow_timer.stop()
            self._follow_timer = None
        self._follow_flying = False

    def _follow_tick(self) -> None:
        if self._effective_file_choice() == "plan":
            self._poll_plan()
        if self._follow_flying:
            return
        self._follow_flying = True
        self.run_worker(self._run_gather_follow, thread=True)

    def _run_gather_follow(self) -> None:
        try:
            baseline, offset, update = self._gather_follow()
        except Exception as exc:
            self.call_from_thread(self._on_gather_error, str(exc))
        else:
            self.call_from_thread(self._on_gather_result, baseline, offset, update)

    def _on_gather_error(self, reason: str) -> None:
        self._follow_flying = False
        if reason and reason != getattr(self, "_follow_last_error", None):
            self._follow_last_error = reason
            if self._effective_file_choice() not in ("plan", "all"):
                self._set_file_path(reason)

    def _on_gather_result(
        self,
        baseline: dict[str, file_follow.Snap],
        offset: int,
        update: file_follow.FollowUpdate | None,
    ) -> None:
        self._follow_flying = False
        self._follow_base = baseline
        self._follow_offset = offset
        self._follow_last_error = None
        if update is not None:
            self._apply_follow(update)

    def _gather_follow(self) -> tuple[dict[str, file_follow.Snap], int, file_follow.FollowUpdate | None]:
        import json

        root = self.session.root
        baseline = dict(self._follow_base)
        offset = self._follow_offset
        watched_repos = self._watched_repos()

        found_snaps: dict[str, tuple[Path, str, file_follow.Snap]] = {}
        for repo in watched_repos:
            argv = ["git", "-C", str(repo), *file_follow.porcelain_argv()]
            res = subprocess.run(argv, capture_output=True)
            if res.returncode != 0:
                err = res.stderr.decode("utf-8", errors="replace").strip() or f"git exit code {res.returncode}"
                raise RuntimeError(err)
            paths = file_follow.parse_porcelain_z(res.stdout)
            repo_res = repo.resolve()
            for rel in paths:
                if file_follow.is_ignored(rel):
                    continue
                try:
                    cand = (repo / rel).resolve()
                except OSError as exc:
                    raise RuntimeError(f"{rel}: {exc}")
                if not cand.is_relative_to(repo_res):
                    continue
                try:
                    st = cand.stat()
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise RuntimeError(f"{rel}: {exc}")
                disp = file_follow.display_path(root, repo, rel)
                found_snaps[disp] = (repo, rel, file_follow.Snap(st.st_mtime_ns, st.st_size))

        ledger_path = root / ".whyline" / "ledger.jsonl"
        hints: list[str] = []
        new_offset = offset
        if ledger_path.is_file():
            try:
                sz = ledger_path.stat().st_size
                read_offset = offset if offset <= sz else 0
                with open(ledger_path, "rb") as f:
                    f.seek(read_offset)
                    blob = f.read()
                if blob:
                    last_nl = blob.rfind(b"\n")
                    if last_nl != -1:
                        complete = blob[:last_nl + 1]
                        new_offset = read_offset + len(complete)
                        for line in complete.splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                record = json.loads(line.decode("utf-8", errors="replace"))
                                if record.get("type") == "FileTouched" and record.get("path"):
                                    raw_p = record["path"]
                                    p = Path(raw_p)
                                    resolved_p = p if p.is_absolute() else (root / p).resolve()
                                    disp = None
                                    for repo in watched_repos:
                                        try:
                                            repo_res = repo.resolve()
                                            if resolved_p.is_relative_to(repo_res):
                                                rel_p = str(resolved_p.relative_to(repo_res))
                                                disp = file_follow.display_path(root, repo, rel_p)
                                                break
                                        except Exception:
                                            pass
                                    if disp is None:
                                        try:
                                            if resolved_p.is_relative_to(root.resolve()):
                                                disp = str(resolved_p.relative_to(root.resolve()))
                                            else:
                                                disp = raw_p
                                        except Exception:
                                            disp = raw_p
                                    hints.append(disp)
                            except Exception:
                                pass
            except OSError as exc:
                raise RuntimeError(f"ledger: {exc}")

        found: dict[str, tuple[file_follow.Snap, bytes]] = {}
        head: dict[str, str] = {}
        for disp, (repo, rel, snap) in found_snaps.items():
            if disp not in baseline or baseline[disp] != snap:
                full_path = repo / rel
                try:
                    raw = full_path.read_bytes()
                except OSError as exc:
                    raise RuntimeError(f"{disp}: {exc}")
                found[disp] = (snap, raw)
                try:
                    show_res = subprocess.run(
                        ["git", "-C", str(repo), "show", f"HEAD:{rel}"],
                        capture_output=True,
                        text=True,
                    )
                    head[disp] = show_res.stdout if show_res.returncode == 0 else ""
                except OSError:
                    head[disp] = ""

        new_baseline, update = file_follow.poll(baseline, found, hints, head)
        return new_baseline, new_offset, update

    def _apply_follow(self, update: file_follow.FollowUpdate) -> None:
        divert = self._effective_file_choice() in ("plan", "all")
        if update.notice is not None:
            if divert:
                return
            self._set_file_path(f"{update.path} — {update.notice}")
            view = self._main_widget("#file-view", FollowView)
            if view is not None:
                self._follow_moving = True
                try:
                    view.load_text("")
                finally:
                    self._follow_moving = False
            return

        if update.text is None:
            return

        if update.path not in self._follow_order:
            self._follow_order.append(update.path)

        if divert:
            self._follow_shown[update.path] = update.text
            return

        held_path = (
            self._follow_order[self._follow_index]
            if (
                self._follow_hold
                and self._follow_index is not None
                and 0 <= self._follow_index < len(self._follow_order)
            )
            else None
        )

        if self._follow_hold and held_path and held_path != update.path:
            self._follow_shown[update.path] = update.text
            newer = len(self._follow_order) - 1 - self._follow_index
            self._set_file_path(f"{held_path} · held · {newer} newer")
            self._sync_follow_buttons()
            return

        current_path = (
            self._follow_order[self._follow_index]
            if (self._follow_index is not None and 0 <= self._follow_index < len(self._follow_order))
            else None
        )

        if current_path != update.path:
            self._follow_user_scrolled = False

        self._follow_index = self._follow_order.index(update.path)
        if self._follow_index == len(self._follow_order) - 1:
            self._follow_hold = False

        is_same = (current_path == update.path)
        previous = self._follow_shown.get(update.path)
        self._follow_shown[update.path] = update.text

        if is_same and self._follow_user_scrolled:
            self._set_file_path(f"{update.path} — updated")
            view = self._main_widget("#file-view", FollowView)
            if view is not None:
                sx = view.scroll_x
                sy = view.scroll_y
                self._follow_moving = True
                try:
                    view.load_text(update.text)
                    view.scroll_x = sx
                    view.scroll_y = sy
                finally:
                    self._follow_moving = False
        else:
            if previous is None:
                target_line = update.changed_line
            else:
                target_line = file_follow.first_changed_line(previous, update.text)
            self._set_file_path(update.path)
            view = self._main_widget("#file-view", FollowView)
            if view is not None:
                self._follow_moving = True
                try:
                    view.load_text(update.text)
                    row = max(0, target_line - 1)
                    view.move_cursor((row, 0))
                    view.scroll_cursor_visible()
                finally:
                    self._follow_moving = False

        self._sync_follow_buttons()

    def _sync_split(self) -> None:
        try:
            split = self._main("#split")
            pane = self._main("#file-pane")
            col = self._main("#console-column")
        except (NoMatches, IndexError):
            return
        pane.display = self._files_on
        self._sync_file_choice_widgets()
        stacked = self.size.width < 120
        split.set_class(stacked, "stacked")
        if stacked:
            if split.children and split.children[0] is not pane:
                split.move_child(pane, before=col)
        else:
            if split.children and split.children[0] is not col:
                split.move_child(col, before=pane)

    def on_mount(self) -> None:
        """Mirrors the plain REPL's own onboarding line (repl.py's `run`).
        The subtitle and the highlighted mode button say which mode is
        active; the console opens in Chat."""
        self.run_worker(lambda: att.clean_old(self.session.root), thread=True)
        self._sync_mode_indicator()
        self._sync_split()
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
        self.run_worker(self._look_for_update, thread=True)

    def _look_for_update(self) -> None:
        """Runs in a worker thread: both the PyPI request and `uv tool dir`
        can take seconds, and the console must not wait on either."""
        from whyline import __version__

        info = self._update_check(__version__)
        if info is not None:
            self._install_problem()
            self.call_from_thread(self._update_found, info)

    def _install_problem(self) -> str | None:
        """How whyline was installed when the console can't update it; None
        when it can. Asked once: the answer can't change while it runs."""
        if self._update_problem_text is _UNSET:
            try:
                self._update_problem_text = self._update_problem()
            except Exception as error:
                self._update_problem_text = (
                    f"The console could not tell how whyline was installed ({error})."
                )
        return self._update_problem_text

    def _update_found(self, info: "update.UpdateInfo") -> None:
        self.title = f"whyline {info.version} is available"
        self._offer_update(info.version, info.notes_url, reinstall=False)

    def _offer_update(self, version: str, notes_url: str | None, *, reinstall: bool) -> None:
        """Shows Update… when the console can install it itself. Otherwise
        Help says how whyline was installed, and nothing is offered."""
        if self._update_running or self._update_installed:
            return
        if self._update_offer is not None and not self._update_offer[2]:
            return  # a newer release already on offer also restores what's missing
        problem = self._install_problem()
        if problem is not None:
            self._update_note = problem
            return
        self._update_offer = (version, notes_url, reinstall)
        try:
            button = self._main("#update", Button)
        except (NoMatches, IndexError):
            return
        if reinstall and not button.display:
            self.render_event(SessionEvent(
                kind="output", text=f"Update… below reinstalls whyline {version} to restore it."))
        button.display = True
        self._sync_update_button()
        if self._update_timer is None:
            self._update_timer = self.set_interval(1.0, self._sync_update_button)

    def _update_blocked(self) -> bool:
        return self._relay_running() or self._live_relay() is not None

    def _sync_update_button(self) -> None:
        try:
            button = self._main("#update", Button)
        except (NoMatches, IndexError):
            return
        blocked = self._update_blocked()
        button.disabled = blocked or self._update_running
        button.tooltip = update.RELAY_RUNNING if blocked else None

    def _open_update(self) -> None:
        if self._update_offer is None or self._update_running:
            return
        if self._update_blocked():
            self._sync_update_button()
            self.render_event(SessionEvent(kind="error", text=update.RELAY_RUNNING))
            return
        from whyline import __version__

        version, notes_url, reinstall = self._update_offer
        text = update.confirm_text(__version__, version, notes_url, reinstall=reinstall)
        self.push_screen(ConfirmScreen(text, "Update"), self._update_confirmed)

    def _update_confirmed(self, confirmed: bool) -> None:
        if not confirmed or self._update_offer is None:
            return
        if self._update_blocked():
            self.render_event(SessionEvent(kind="error", text=update.RELAY_RUNNING))
            return
        version, _notes, reinstall = self._update_offer
        self._update_running = True
        self._sync_update_button()
        self.render_event(SessionEvent(
            kind="output",
            text="Running: " + " ".join(update.install_argv(version, reinstall=reinstall)),
        ))

        def work() -> None:
            def line(text: str) -> None:
                self.call_from_thread(self.render_event, SessionEvent(kind="output", text=text))

            try:
                code = self._update_install(version, on_line=line, reinstall=reinstall)
            except Exception as error:
                self.call_from_thread(self.render_event, SessionEvent(kind="error", text=str(error)))
                code = 1
            self.call_from_thread(self._update_finished, version, code)

        self.run_worker(work, thread=True)

    def _update_finished(self, version: str, code: int) -> None:
        from whyline import __version__

        self._update_running = False
        if code != 0:
            self.render_event(SessionEvent(kind="error", text=update.failed_text(code, __version__)))
            self._sync_update_button()
            return
        self._update_offer = None
        self._update_installed = True
        self._main("#update", Button).display = False
        self._main("#update-restart", Button).display = True
        self.render_event(SessionEvent(kind="output", text=update.done_text(version)))

    def _restart_console(self) -> None:
        binary, argv = update.RESTART
        self._exec_after = (binary, list(argv))
        self.exit()

    def _restore_release_task(self) -> bool:
        """Picks the release task back up from the relay's saved pause. The
        in-memory one is lost when the console restarts, which made `done`
        an unknown command. Never while a relay process is running."""
        if getattr(self, "_release_task", None):
            return True
        if self.session.mode != "relay" or (self._relay is not None and self._relay.running()):
            return False
        try:
            info = relay_ops.release_task(self.session.root)
        except Exception:
            info = None
        if info is None:
            return False
        self._release_task = info
        return True

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
        elif getattr(self, "_manual_checks", None):
            suffix = f" · manual {self._manual_checks[0].id}"
        else:
            suffix = ""
        if self._awake is not None:
            suffix += f" · Mac kept awake since {self._awake.started:%H:%M}"
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
        elif getattr(self, "_manual_fail_id", None):
            placeholder = f"Failure note for {self._manual_fail_id} (Enter to send)"
        elif getattr(self, "_manual_checks", None):
            placeholder = (
                f"Manual check {self._manual_checks[0].id}: Pass or Fail, "
                f"or type manual {self._manual_checks[0].id} pass / fail <note>"
            )
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
        self._cb_sync_timeout()
        self._main("#attach", Button).disabled = self.session.mode != "chat"
        self._refresh_tray()
        if mode == "agents":
            self._refresh_agents_status()
        self._sync_relay_buttons()
        self._sync_mode_buttons()
        self._sync_file_choice_widgets()

    def _cb_sync_timeout(self) -> None:
        try:
            select = self._main("#cb-timeout", Select)
        except (NoMatches, IndexError):
            return
        if not getattr(select, "is_mounted", False):
            return
        legal = set(getattr(select, "_legal_values", ()))
        target = self.session.chat_timeout_seconds
        if (not legal or target in legal) and select.value != target:
            with self.prevent(Select.Changed):
                select.value = target

    def _sync_mode_buttons(self) -> None:
        """One place decides which bottom-bar buttons are on screen.
        Enable and disable stay in _sync_relay_buttons and the stop path."""
        wanted = set(_MODE_BUTTONS.get(self.session.mode, ())) | set(_SHARED_BUTTONS)
        wanted -= _HIDDEN_SHARED.get(self.session.mode, set())
        if not awake.available():
            wanted.discard("awake")
        self._main("#awake", Button).label = "Awake ●" if self._awake else "Awake"
        controls = self._main("#controls")
        for button in controls.query(Button):
            if button.id in ("relay-resolve", "relay-retry-stage", "update", "update-restart"):
                continue
            button.display = button.id in wanted
        self._fit_controls()
        self._main("#attach").display = self.session.mode == "chat"
        try:
            self._main("#agents-bar").display = self.session.mode == "agents"
        except (NoMatches, IndexError):
            return

    def _fit_controls(self) -> None:
        """One row when the bar's buttons fit the window, a grid when not.

        A fixed grid spread the buttons across a wide window."""
        try:
            controls = self._main("#controls")
        except (NoMatches, IndexError):
            return
        needed = sum(
            max(6, len(str(button.label)) + 4)
            for button in controls.query(Button)
            if button.display
        )
        available = controls.size.width or self.size.width
        controls.set_class(needed > available, "wrap")

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
        elif getattr(self, "_manual_checks", None):
            resume.label = "Resume"
            resume.disabled = True
            self._stale_pause = None
        elif getattr(self, "_manual_passed", False):
            resume.label = "Resume"
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

        try:
            self._main("#pause-actions").display = (
                in_relay
                and bool(paused)
                and not running
                and not getattr(self, "_release_task", None)
                and not getattr(self, "_manual_checks", None)
            )
        except (NoMatches, IndexError):
            pass

        try:
            resolve = self._main("#relay-resolve", Button)
        except (NoMatches, IndexError):
            resolve = None

        try:
            retry_stage = self._main("#relay-retry-stage", Button)
        except (NoMatches, IndexError):
            retry_stage = None

        show_resolve = False
        show_retry_stage = False
        if in_relay and not getattr(self, "_release_task", None):
            has_preflight_fails = bool(getattr(self, "_resume_fail_lines", None))
            has_diagnosed_pause = False
            if paused and not stale:
                try:
                    from whyline_relay import state as relay_state
                    from whyline.console import recovery

                    st = None
                    try:
                        st = relay_state.load(self.session.root)
                    except Exception:
                        pass
                    reason = st.paused_reason if st and st.paused_reason else ""
                    diag = recovery.diagnose(
                        self.session.root,
                        fail_lines=getattr(self, "_resume_fail_lines", []),
                        pause_reason=reason,
                    )
                    if diag:
                        has_diagnosed_pause = True
                except Exception:
                    pass
            show_resolve = has_preflight_fails or has_diagnosed_pause

            if paused and not running:
                try:
                    from whyline_relay import state as relay_state
                    from whyline.console import adapters

                    st = relay_state.load(self.session.root)
                    if st is not None and st.paused_reason:
                        if adapters.failure_kind(st.paused_reason) == "visit-cap":
                            show_retry_stage = True
                except Exception:
                    pass

        if resolve is not None:
            resolve.display = show_resolve
            resolve.disabled = not show_resolve or running or getattr(self, "_resolve_running", False)

        if retry_stage is not None:
            retry_stage.display = show_retry_stage
            retry_stage.disabled = not show_retry_stage or running or self._recovering_pause

    def _placeholder(self, mode: str) -> str:
        if mode == "relay":
            return "Relay: run (guided), doctor, status, start, resume (Enter to run)"
        if mode == "agents":
            return "Agents: list, run <name>, edit <name>, delete <name>, history <name>, pause/resume/accept <name>"
        if mode == "assistant":
            return "Use the buttons above, or message the bot on Telegram."
        agent = self.session.agent or "claude"
        return f"Message {agent}... (Enter to send)"

    def _refresh_agents_status(self) -> None:
        from whyline.agents import launchd, service

        mac = launchd.supported()
        try:
            self._main("#agents-scheduler", Button).disabled = not mac
        except (NoMatches, IndexError):
            pass
        on = mac and self._scheduler_on()
        try:
            # Short so Agents' row fits 80 columns with Awake; the status bar spells it out.
            self._main("#agents-scheduler", Button).label = "Schedule ●" if on else "Schedule"
        except (NoMatches, IndexError):
            pass
        if not mac:
            text = launchd.NEEDS_MACOS
        elif on:
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

    def _open_inbox(self) -> None:
        from whyline.console.inbox_screen import IdeaInboxScreen

        self.push_screen(IdeaInboxScreen())

    def _open_ideas(self) -> None:
        from whyline.console.ideas_screen import IdeasScreen

        self.push_screen(IdeasScreen())

    def _open_assistant(self) -> None:
        from whyline.console.assistant_screen import AssistantScreen

        self.push_screen(AssistantScreen())

    def _check_inbox(self) -> None:
        from whyline.console.inbox_screen import _doctor_text

        self.render_event(SessionEvent(kind="output", text=_doctor_text()))

    def _open_new_agent(self, existing=None, delivery=None, *, editing_id=None,
                        lock_name: bool = False) -> None:
        from whyline.console import relay_ops
        from whyline.console.agents_screens import NewAgentScreen

        if editing_id is None:
            editing_id = existing.agent_id if existing is not None else None
        self._editing_agent_id = editing_id
        self.push_screen(
            NewAgentScreen(
                self.session.root,
                relay_ops.cached_agent_status(self.session.root),
                existing=existing, delivery=delivery, lock_name=lock_name,
            ),
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
        self._scheduler_said(on=True)
        self._refresh_agents_status()

    def _scheduler_said(self, *, on: bool) -> None:
        """Say plainly what the switch just did, for every agent on this Mac."""
        from whyline.agents import service

        try:
            text = service.scheduler_summary(service.rows(self.session.root), on=on)
        except Exception:
            text = service.scheduler_summary([], on=on) if not on else "Scheduler on."
        self.render_event(SessionEvent(kind="output", text=text))

    def _scheduler_turned_off(self, yes: bool) -> None:
        if not yes:
            return
        from whyline.agents import launchd

        try:
            launchd.turn_off()
        except Exception as error:
            self.render_event(SessionEvent(kind="error", text=str(error)))
            return
        self._scheduler_said(on=False)
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
        if name.startswith("delete-file:"):
            self._confirm_delete_file(Path(name.removeprefix("delete-file:")))
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
        holder: dict = {}
        screen = RunsScreen(
            row.defn.label, runs,
            on_resend=lambda run_id: self._agent_resend(name, run_id, holder.get("screen")))
        holder["screen"] = screen
        self.push_screen(screen)

    def _agent_resend(self, name: str, run_id: str, screen=None) -> None:
        from whyline.agents import deliver, records, service

        root = self.session.root

        def work() -> None:
            status = ""
            try:
                label = service.find(name, root).label
            except Exception:
                label = name
            try:
                results = service.resend(name, root, run_id)
                text = "  ".join(
                    f"{r['to']} {'✓' if r['ok'] else '✗'}" + ("" if r["ok"] else f" {r['detail']}")
                    for r in results) or "Nothing was sent: no deliveries set."
                record = records.load(run_id)
                if record is not None:
                    status = deliver.status_text(record)
                elif results:
                    status = "delivered: " + text
                event = SessionEvent(kind="output", text=f"{label}: resent — {text}")
            except Exception as error:
                text = str(error)
                event = SessionEvent(kind="error", text=f"{label}: resend failed — {text}")

            def apply() -> None:
                self.render_event(event)
                if screen is not None and screen.is_attached:
                    screen.resend_done(run_id, text, status)

            self.call_from_thread(apply)

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

    def _confirm_delete_file(self, path: Path) -> None:
        """A broken agent file: not a valid agent, so delete_agent can't
        find it. Ask, then remove only that file."""
        shown = path.as_posix().replace(Path.home().as_posix(), "~", 1)

        def confirmed(yes: bool) -> None:
            if not yes:
                return
            try:
                path.unlink()
            except OSError as error:
                self.render_event(SessionEvent(kind="error", text=str(error)))
                return
            self.render_event(SessionEvent(kind="output", text=f"Deleted {shown}."))
            self._refresh_agents_status()

        self.push_screen(
            ConfirmScreen(f"Delete {shown}? It isn't a valid agent, so nothing runs from it.", "Delete"),
            confirmed,
        )

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

    def _cb_load_chain(self) -> tuple[str, ...]:
        """The saved chain, unfiltered. A bad config is not an empty chain."""
        from whyline_relay import config as relay_config

        try:
            chain = tuple(relay_ops.read_backup(self.session.root))
        except (relay_config.ConfigError, OSError) as error:
            self._cb_backup_unreadable = str(error)
            return ()
        self._cb_backup_unreadable = None
        return chain

    def _cb_saved_tuple(self) -> tuple[str, str, str, tuple[str, ...]]:
        from whyline import model

        agent, model_name = model.resolve(self.session.root)
        return (agent, model_name, _short_path(self.session.root), self._cb_load_chain())

    def _cb_current(self) -> tuple[str, str, str, tuple[str, ...]]:
        raw = self._main("#cb-agent", Select).value
        if raw == _CB_BACKUP_MENU:
            raw = self._cb_agent_shown or ""
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
            self._cb_chain,
        )

    def _cb_backup_detail(self, name: str, status: dict) -> str:
        info = status.get(name) or {}
        if info.get("available"):
            return "available"
        return str(info.get("hint") or info.get("label") or "unavailable")

    def _cb_backup_options(self, saved_chain: tuple[str, ...], primary: str) -> list[tuple[str, str]]:
        """Automatic, None, installed agents, then Manage and maybe Reset.

        A saved name `relay_agents` does not list is appended before Manage
        so the closed control can still show that head.
        """
        from whyline import account
        from whyline_relay import failover

        root = self.session.root
        status = account.agent_status(root)
        if saved_chain:
            resolved = " → ".join(saved_chain)
        else:
            usable = relay_ops.usable_agents(root, status)
            staged = relay_ops.staged_backup(primary, usable)
            resolved = " → ".join(staged) if staged else "none"
        options: list[tuple[str, str]] = [
            (f"Automatic · {resolved}", "automatic"),
            ("None — no fallback", "none"),
        ]
        installed = [
            name
            for name in relay_ops.relay_agents(root)
            if provider_enabled(status.get(name))
        ]
        names = installed + [name for name in saved_chain if name not in installed]
        for name in names:
            options.append((f"{name} — {self._cb_backup_detail(name, status)}", name))
        options.append(("Manage chain…", "manage"))
        try:
            effective = failover.resolve_chat_agent(root, primary)
        except (OSError, ValueError):
            effective = primary
        if effective != primary:
            options.append((f"Reset failover (back to {primary})", "reset"))
        return options

    def _cb_set_backup_closed(self, select: Select, text: str) -> None:
        try:
            select.query_one("#label", Static).update(Text(text))
        except (NoMatches, IndexError):
            return

    def _cb_sync_backup_closed(self) -> None:
        """Head (and +N) for a saved chain. Automatic keeps its own row."""
        try:
            select = self._main("#cb-backup", Select)
            more = self._main("#cb-backup-more", Static)
        except (NoMatches, IndexError):
            return
        if self._cb_backup_unreadable:
            self._cb_set_backup_closed(select, self._cb_backup_unreadable)
            more.update("")
            more.display = False
            self._cb_after_backup_sync()
            return
        value = self._cb_backup_real
        chain = self._cb_chain
        if value == "automatic":
            prompt = "Automatic"
            for option, option_value in select._options:
                if option_value == "automatic":
                    prompt = str(option)
                    break
            self._cb_set_backup_closed(select, prompt)
            extra = 0
        elif not chain or value == "none":
            self._cb_set_backup_closed(select, "None")
            extra = 0
        else:
            self._cb_set_backup_closed(select, chain[0])
            extra = len(chain) - 1
        if extra:
            more.update(f"+{extra}")
            more.display = True
        else:
            more.update("")
            more.display = False
        self._cb_after_backup_sync()

    def _cb_bak_head(self) -> str:
        """What the narrow agent row says after `bak`.

        An empty chain is `none`. Automatic, while it is still the unsaved
        selection, prefixes that head with `auto`.
        """
        head = self._cb_chain[0] if self._cb_chain else "none"
        if self._cb_backup_real == "automatic":
            return f"auto {head}"
        return head

    def _cb_after_backup_sync(self) -> None:
        """Keep Backup off the row below 80, and refresh the agent menu."""
        if self.size.width < 80:
            try:
                self._main("#cb-backup-label", Label).display = False
                self._main("#cb-backup", Select).display = False
                self._main("#cb-backup-more", Static).display = False
            except (NoMatches, IndexError):
                pass
        self._cb_sync_agent_menu()

    def _cb_sync_agent_menu(self) -> None:
        """Below 80 each agent row names the backup head and offers Backup…"""
        try:
            select = self._main("#cb-agent", Select)
        except (NoMatches, IndexError):
            return
        from whyline import account

        status = account.agent_status(self.session.root)
        base = _cb_select_options(status)
        if self.size.width < 80:
            head = self._cb_bak_head()
            options = [
                (f"{_cb_agent_name(value)} · bak {head}", value)
                for _prompt, value in base
            ]
            options.append(("Backup…", _CB_BACKUP_MENU))
        else:
            options = list(base)
        listed = [
            (str(prompt), value)
            for prompt, value in select._options
            if value is not Select.BLANK
        ]
        if listed == options:
            return
        shown = select.value
        if shown == _CB_BACKUP_MENU:
            shown = self._cb_agent_shown
        chosen = _cb_match_option(shown, base)
        with self.prevent(Select.Changed):
            select.set_options(options)
            if select.value != chosen:
                select.value = chosen

    def _cb_restore_agent_select(self) -> None:
        """Put the agent menu back on the real agent after Backup…"""
        select = self._main("#cb-agent", Select)
        name = self._cb_agent_shown
        if not isinstance(name, str) or not name or name == _CB_BACKUP_MENU:
            name = self._cb_saved[0] if self._cb_saved else "claude"
        legal = set(getattr(select, "_legal_values", ()))
        target = name if name in legal else f"!{name}"
        if target not in legal:
            for _prompt, value in select._options:
                if value != _CB_BACKUP_MENU and value is not Select.BLANK:
                    target = value
                    break
            else:
                return
        with self.prevent(Select.Changed):
            if select.value != target:
                select.value = target

    def _cb_show_backup(self, chain: tuple[str, ...], real: str | None = None) -> None:
        """Show `chain` on the backup control. Does not post Select.Changed."""
        self._cb_chain = tuple(chain)
        select = self._main("#cb-backup", Select)
        legal = set(getattr(select, "_legal_values", ()))
        if real is None:
            real = chain[0] if chain else "none"
        self._cb_backup_real = real
        shown = real if real in legal else ("none" if "none" in legal else None)
        if shown is not None and select.value != shown:
            select.value = shown
        self._cb_sync_backup_closed()

    def _cb_choose_backup(self, value: str) -> None:
        """The chain this value would write. Manage and Reset never get here."""
        saved_chain = self._cb_saved[3] if self._cb_saved else ()
        primary = self._cb_saved[0] if self._cb_saved else "claude"
        if value == "automatic":
            if saved_chain:
                self._cb_chain = tuple(saved_chain)
            else:
                from whyline import account

                status = account.agent_status(self.session.root)
                usable = relay_ops.usable_agents(self.session.root, status)
                self._cb_chain = tuple(
                    relay_ops.staged_backup(primary, usable)
                )
        elif value == "none":
            self._cb_chain = ()
        else:
            self._cb_chain = _cb_dedupe((value, *self._cb_chain))
        self._cb_backup_real = value
        self._cb_sync_backup_closed()

    def _cb_restore_backup_select(self) -> None:
        select = self._main("#cb-backup", Select)
        previous = self._cb_backup_real
        legal = set(getattr(select, "_legal_values", ()))
        if previous not in legal:
            previous = "none" if "none" in legal else select._options[0][1]
        with self.prevent(Select.Changed):
            if select.value != previous:
                select.value = previous
        self._cb_sync_backup_closed()

    def _cb_reload_backup_options(self) -> None:
        """Rebuild Backup rows from the saved chain. Keep the real value.

        `set_options` snaps to the first row. The real value goes back
        afterwards, and the closed prompt is the head, not that row.
        """
        try:
            select = self._main("#cb-backup", Select)
        except (NoMatches, IndexError):
            return
        saved_chain = self._cb_saved[3] if self._cb_saved else ()
        primary = self._cb_saved[0] if self._cb_saved else "claude"
        shown = self._cb_backup_real
        self._cb_refreshing = True
        try:
            with self.prevent(Select.Changed):
                select.set_options(self._cb_backup_options(saved_chain, primary))
                legal = set(getattr(select, "_legal_values", ()))
                if shown not in legal:
                    shown = "none" if "none" in legal else select._options[0][1]
                    self._cb_backup_real = shown
                if select.value != shown:
                    select.value = shown
        finally:
            self._cb_refreshing = False
        self._cb_sync_backup_closed()

    def _cb_sync_failover(self) -> None:
        """`using {effective}` when chat has switched. Hidden on the primary."""
        from whyline_relay import failover

        try:
            label = self._main("#cb-failover", Label)
        except (NoMatches, IndexError):
            return
        primary = self._cb_saved[0] if self._cb_saved else ""
        effective = primary
        if primary:
            try:
                effective = failover.resolve_chat_agent(self.session.root, primary)
            except (OSError, ValueError):
                effective = primary
        if not primary or effective == primary:
            label.update("")
            label.display = False
        else:
            label.update(f"using {effective}")
            label.display = True
        # The label is about twelve columns. Give them back before the next paint.
        self._cb_fit()

    def _cb_reset_failover(self) -> None:
        """Clear the saved primary's chat override. Leave the chain and roles.

        The primary is the saved agent. An unsaved Agent edit is not the
        chat that failover switched. A live job does not clear.
        """
        if self._cb_chain_busy():
            self.render_event(SessionEvent(kind="error", text=RESET_BUSY_TEXT))
            return
        root = self.session.root
        primary = self._cb_saved[0] if self._cb_saved else "claude"
        chain = self._cb_saved[3] if self._cb_saved else ()
        try:
            clear_chat_override(root, primary)
        except OSError as error:
            self.render_event(SessionEvent(kind="error", text=str(error)))
            return
        self._cb_reload_backup_options()
        self._cb_sync_failover()
        self.render_event(SessionEvent(
            kind="output", text=reset_failover_text(primary, chain),
        ))

    def _cb_chain_busy(self) -> bool:
        if self._busy_text or self._plan_state or self._relay_running():
            return True
        try:
            return relay_ops.live_run(self.session.root) is not None
        except (OSError, ValueError):
            return False

    def _cb_open_chain_editor(self) -> None:
        from whyline import account
        from whyline.console.chain_editor import BackupChainScreen

        root = self.session.root
        try:
            installed = relay_ops.relay_agents(root)
        except (OSError, ValueError):
            installed = []
        status = account.agent_status(root)
        agents = [
            name for name in installed if provider_enabled(status.get(name))
        ]
        # Saved names stay unfiltered so a disabled head remains a stale row.
        chain = list(self._cb_chain)
        primary = self._cb_saved[0] if self._cb_saved else "claude"

        def fill() -> list[str]:
            current = account.agent_status(root)
            usable = [
                name
                for name in relay_ops.usable_agents(root, current)
                if provider_enabled(current.get(name))
            ]
            return relay_ops.staged_backup(primary, usable)

        screen = BackupChainScreen(
            agents,
            chain,
            fill,
            busy=self._cb_chain_busy(),
            on_reset=self._cb_reset_failover,
        )
        self.push_screen(screen, self._cb_backup_editor_done)
        # compose() loads the chain before the widget is mounted, and the
        # editor's own on_mount sync returns while is_mounted is still false.
        # Reload after the screen is up so the rows actually appear.
        self.call_after_refresh(lambda: self._cb_kick_editor(screen, chain, 8))

    def _cb_kick_editor(self, screen, chain: list[str], tries: int) -> None:
        if tries <= 0 or screen not in self.screen_stack:
            return
        if not screen.is_mounted:
            self.call_after_refresh(lambda: self._cb_kick_editor(screen, chain, tries - 1))
            return
        try:
            editor = screen.query_one("#bc-chain")
        except (NoMatches, IndexError):
            self.call_after_refresh(lambda: self._cb_kick_editor(screen, chain, tries - 1))
            return
        editor.load(list(chain))

    def _cb_backup_editor_done(self, order: list[str] | None) -> None:
        if order is None:
            self._cb_sync_backup_closed()
            return
        chain = _cb_dedupe(order)
        real = chain[0] if chain else "none"
        with self.prevent(Select.Changed):
            self._cb_show_backup(chain, real)
        self._cb_mark_save()

    def _cb_on_backup_changed(self, event: "Select.Changed") -> None:
        if self._cb_refreshing:
            return
        select = event.select
        if event.value != select.value:
            return
        value = event.value
        if not isinstance(value, str):
            return
        if value in ("manage", "reset"):
            self._cb_restore_backup_select()
            if value == "manage":
                self._cb_open_chain_editor()
            elif value == "reset":
                self._cb_reset_failover()
            return
        self._cb_choose_backup(value)
        self._cb_mark_save()

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
            options = _cb_select_options(status)
            agent, model_name, repo_text, chain = self._cb_saved_tuple()
            chosen = _cb_match_option(agent, options)
            backup_options = self._cb_backup_options(chain, agent)
            self._cb_chain = chain
            with self.prevent(Select.Changed, Input.Changed):
                select.set_options(options)
                if select.value != chosen:
                    select.value = chosen
                model_input.value = model_name
                repo_input.value = repo_text
                try:
                    backup = self._main("#cb-backup", Select)
                except (NoMatches, IndexError):
                    backup = None
                if backup is not None:
                    backup.set_options(backup_options)
                    self._cb_show_backup(chain)
            self._cb_agent_shown = agent
            self._cb_saved = (agent, model_name, repo_text, self._cb_chain)
            self._cb_status_seen = _cb_status_key(status)
            self._cb_sync_backup_closed()
            self._cb_sync_failover()
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
        options = _cb_select_options(status)
        current = self._cb_agent_shown if select.value == _CB_BACKUP_MENU else select.value
        chosen = _cb_match_option(current, options)
        saved_chain = self._cb_saved[3] if self._cb_saved else ()
        primary = self._cb_saved[0] if self._cb_saved else "claude"
        self._cb_refreshing = True
        try:
            with self.prevent(Select.Changed):
                select.set_options(options)
                if select.value != chosen:
                    select.value = chosen
                try:
                    backup = self._main("#cb-backup", Select)
                except (NoMatches, IndexError):
                    backup = None
                if backup is not None:
                    backup.set_options(self._cb_backup_options(saved_chain, primary))
                    shown = self._cb_backup_real
                    legal = set(getattr(backup, "_legal_values", ()))
                    if shown not in legal:
                        shown = "none" if "none" in legal else backup._options[0][1]
                    if backup.value != shown:
                        backup.value = shown
            self._cb_status_seen = key
            self._cb_sync_backup_closed()
            self._cb_mark_save()
        finally:
            self._cb_refreshing = False

    def _cb_fit(self) -> None:
        """Below 100 columns the labels shrink so Save stays on screen."""
        try:
            width = self.size.width
            try:
                col = self._main("#console-column")
                if self._files_on and self.size.width >= 120:
                    if 0 < col.size.width < self.size.width:
                        width = col.size.width
                    else:
                        width = self.size.width // 2
                elif col.size.width > 0:
                    width = col.size.width
            except (NoMatches, IndexError):
                pass
            narrow = width < 100
            compact = width < 80
            self._main("#cb-agent-label", Label).update("A" if narrow else "Agent")
            self._main("#cb-model-label", Label).update("M" if narrow else "Model")
            self._main("#cb-timeout-label", Label).update("T" if narrow else "Timeout")
            self._main("#cb-repo-label", Label).update("R" if narrow else "Repo")
            try:
                failover_on = bool(self._main("#cb-failover", Label).display)
            except (NoMatches, IndexError):
                failover_on = False
            # Wide agent box is 24. A visible failover label needs those columns
            # back or Save leaves a 120-column row. Narrow rows are already 14.
            self._main("#cb-agent", Select).styles.width = 14 if narrow or failover_on else 24
            self._main("#cb-timeout", Select).styles.width = 8 if narrow else 10
            backup_label = self._main("#cb-backup-label", Label)
            backup_label.update("Bak" if narrow else "Backup")
            backup_label.display = not compact
            backup = self._main("#cb-backup", Select)
            backup.styles.width = 18 if width >= 110 else 14
            backup.display = not compact
            if compact:
                self._main("#cb-backup-more", Static).display = False
            # Backup at 18 plus the full labels and Timeout passes column 110;
            # the checkbox returns once the row has room for all of them.
            self._main("#cb-global", Checkbox).display = width >= 130
        except (NoMatches, IndexError):
            return
        if compact:
            self._cb_sync_agent_menu()
        else:
            self._cb_sync_backup_closed()

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
        from whyline_relay import config as relay_config, gitcheck

        if self._cb_saved is None:
            return
        agent, model_name, repo_text, chain = self._cb_current()
        saved_agent, saved_model, saved_repo, saved_chain = self._cb_saved
        # Before the chain, the agent, the model, or the repo.
        if _model_rejected(model_name):
            text = (
                "A model name is required"
                if not model_name.strip()
                else "A model name has no spaces"
            )
            self.render_event(SessionEvent(kind="error", text=text))
            return
        agent_changed = (agent, model_name) != (saved_agent, saved_model)
        repo_changed = repo_text != saved_repo
        global_too = bool(self._main("#cb-global", Checkbox).value)
        chain_changed = chain != saved_chain
        # "all repos" writes the global agent and model only.
        if chain_changed and not global_too:
            if self._cb_backup_unreadable:
                self.render_event(SessionEvent(
                    kind="error", text=self._cb_backup_unreadable))
                return
            if self._cb_chain_busy():
                self.render_event(SessionEvent(kind="error", text=RESET_BUSY_TEXT))
                return
            try:
                relay_ops.save_backup(self.session.root, list(chain))
            except (gitcheck.GitError, relay_config.ConfigError) as error:
                self.render_event(SessionEvent(kind="error", text=str(error)))
                return
            self.render_event(SessionEvent(
                kind="output", text=backup_chain_sentence(chain),
            ))
            saved_chain = chain
            with self.prevent(Select.Changed):
                self._cb_show_backup(chain)
        if agent_changed or global_too:
            if not agent:
                self._cb_saved = (saved_agent, saved_model, saved_repo, saved_chain)
                self._cb_mark_save()
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
            self._cb_saved = (agent, model_name, saved_repo, saved_chain)
            self._cb_sync_failover()
        elif chain_changed and not global_too:
            self._cb_saved = (saved_agent, saved_model, saved_repo, saved_chain)
            self._cb_sync_failover()
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
        from whyline import account

        options = _cb_select_options(account.agent_status(self.session.root))
        self._transcript = RichLog(id="transcript", wrap=True)
        console_column = Vertical(
            Horizontal(
                Static("Mode:", id="modes-label"),
                Button("Chat", id="mode-chat"),
                Button("Relay", id="mode-relay"),
                Button("Agents", id="mode-agents"),
                Button("Assistant", id="mode-assistant"),
                id="modes",
            ),
            Horizontal(
                Label("Agent", id="cb-agent-label"),
                Select(options, allow_blank=False, id="cb-agent"),
                Label("", id="cb-failover"),
                Label("Backup", id="cb-backup-label").with_tooltip(
                    "Shared fallback: chat, brainstorm, and the relay"
                ),
                Select(
                    [("None — no fallback", "none")],
                    allow_blank=False,
                    id="cb-backup",
                ),
                Static("", id="cb-backup-more"),
                Label("Model", id="cb-model-label"),
                Input(placeholder="default", id="cb-model"),
                Label("Timeout", id="cb-timeout-label"),
                Select(
                    _CB_TIMEOUT_OPTIONS,
                    value=self.session.chat_timeout_seconds,
                    allow_blank=False,
                    id="cb-timeout",
                ),
                Label("Repo", id="cb-repo-label"),
                Input(id="cb-repo"),
                Checkbox("all repos", id="cb-global"),
                Button("Save", id="cb-save", disabled=True),
                id="context-bar",
            ),
            self._transcript,
            # Plain text: progress labels contain brackets ("[1/3] Codex ...")
            # that Textual would otherwise parse as markup and crash on.
            Static("", id="thinking", markup=False),
            Horizontal(
                Static("", id="agents-status"),
                id="agents-bar",
            ),
            Horizontal(
                Button("Approve", id="plan-approve", variant="success"),
                Button("View draft", id="plan-view"),
                Button("Discard", id="plan-discard", variant="warning"),
                id="plan-actions",
            ),
            Horizontal(
                Button("Pass", id="manual-pass", variant="success"),
                Button("Fail", id="manual-fail", variant="warning"),
                id="manual-actions",
            ),
            Horizontal(
                Button("Change agents", id="pause-change-agents", variant="primary"),
                id="pause-actions",
            ),
            Horizontal(id="resolve-actions"),
            AttachmentTray(id="tray"),
            Static("", id="slash-hint"),
            Horizontal(
                PromptInput(id="prompt"),
                Button("Attach", id="attach"),
                Button("Send", id="send", variant="success"),
                id="input-row",
            ),
            # Shared buttons stay last so each mode's own buttons lead the row.
            Horizontal(
                Button("Model", id="model"),
                Button("Brainstorm", id="brainstorm"),
                Button("History", id="history"),
                Button("Run", id="relay-run", disabled=True),
                Button("Plan", id="relay-plan", disabled=True),
                Button("Set up", id="relay-setup", disabled=True),
                Button("Resume", id="relay-resume", disabled=True),
                Button("Retry stage", id="relay-retry-stage", disabled=True),
                Button("Resolve", id="relay-resolve", disabled=True),
                Button("New", id="agents-new"),
                Button("Agents", id="agents-list"),
                Button("Runs", id="agents-runs"),
                Button("Schedule", id="agents-scheduler"),
                Button("Inbox", id="assistant-inbox"),
                Button("Ideas", id="assistant-ideas"),
                Button("Assistant…", id="assistant-open"),
                Button("Check", id="assistant-check"),
                Button("Settings", id="settings"),
                Button("Files", id="see-files"),
                Button("Awake", id="awake"),
                Button("Stop", id="stop", disabled=True),
                Button("Help", id="help"),
                Button("Update…", id="update"),
                Button("Restart", id="update-restart", variant="success"),
                Button("Copy", id="copy"),
                id="controls",
            ),
            id="console-column",
        )
        file_pane = Vertical(
            Horizontal(
                Button("Working file", id="file-working", variant="success"),
                Button("Plan", id="file-plan"),
                Button("All files", id="file-all"),
                id="file-choices",
            ),
            Horizontal(
                # Plain text: OSError reasons contain "[Errno N]" which
                # Textual would otherwise parse as markup and crash on.
                Static(
                    "No file yet. A file opens here when an agent writes one.",
                    id="file-path",
                    markup=False,
                ),
                Button("Earlier", id="file-earlier", disabled=True),
                Button("Later", id="file-later", disabled=True),
            ),
            FollowView(id="file-view", read_only=True, soft_wrap=False, show_line_numbers=True),
            _FileTree(self.session.root, id="file-tree"),
            id="file-pane",
        )
        yield Header()
        yield Horizontal(console_column, file_pane, id="split")
        yield Footer()

    def render_event(self, event: SessionEvent) -> None:
        self.session.record(event)
        if event.kind == "error" and event.text == _RELAY_MISSING:
            from whyline import __version__

            self._offer_update(__version__, None, reinstall=True)
        try:
            transcript = self._main("#transcript", RichLog)
        except (NoMatches, IndexError):  # the console is closing; the event is still recorded
            return
        if event.kind == "pause" and not getattr(self, "_manual_checks", None):
            try:
                self._main("#pause-actions").display = True
            except (NoMatches, IndexError):
                pass
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
        elif button_id == "see-files":
            self._files_on = not self._files_on
            if self._files_on:
                if self.session.mode == "relay":
                    self._select_file_choice("working")
                if bool(self._busy_text) or self._relay_running() or (self._live_relay() is not None):
                    self._arm_follow()
            else:
                self._disarm_follow()
            self._sync_split()
            self._cb_fit()
            self.call_after_refresh(self._cb_fit)
        elif button_id in ("file-working", "file-plan", "file-all"):
            self._select_file_choice(button_id.removeprefix("file-"))
        elif button_id == "file-earlier":
            self._on_file_earlier()
        elif button_id == "file-later":
            self._on_file_later()
        elif button_id == "stop":
            self._disarm_follow()
            other = None if self._relay_running() else self._live_relay()
            if self._relay_running():
                self._auto_relay = False
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
            chosen = button_id.removeprefix("mode-")
            if chosen == "assistant":
                if self.session.mode != chosen:
                    self.session.mode = chosen
                    self.render_event(SessionEvent(kind="output", text="Mode is now assistant."))
                    self._sync_mode_indicator()
            else:
                self._handle_slash(f"/route {chosen}")
            if self.session.mode == "relay" and not getattr(self, "_release_task", None):
                if self._restore_release_task():
                    task_id, _ = self._release_task
                    self.render_event(SessionEvent(
                        kind="pause",
                        text=f'{task_id} is a release task waiting for you. '
                        'Type "done" when finished, or "skip".',
                    ))
                    self._sync_mode_indicator()
                    self._sync_relay_buttons()
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
        elif button_id == "assistant-inbox":
            self._open_inbox()
        elif button_id == "assistant-ideas":
            self._open_ideas()
        elif button_id == "assistant-open":
            self._open_assistant()
        elif button_id == "assistant-check":
            self._check_inbox()
        elif button_id == "awake":
            self._set_awake(None)
        elif button_id == "copy":
            self._copy_transcript()
        elif button_id == "settings":
            self._open_settings()
        elif button_id == "update":
            self._open_update()
        elif button_id == "update-restart":
            self._restart_console()
        elif button_id == "relay-run":
            self._run_flow_start()
        elif button_id == "relay-plan":
            self._open_relay_plan()
        elif button_id == "relay-setup":
            self._open_relay_setup(plan=self._setup_plan_hint)
        elif button_id in ("pause-change-agents", "change-agents"):
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
                self._manual_passed = False
                self._launch_relay(["resume"])
        elif button_id == "relay-retry-stage":
            from whyline.console import recovery

            retry_args, unrelated = recovery.retry_stage_args(self.session.root)
            if unrelated:
                self.render_event(SessionEvent(
                    kind="output",
                    text="Retry stage cannot keep the draft; unrelated uncommitted files block it: "
                    + ", ".join(unrelated),
                ))
            self._launch_relay(retry_args)
        elif button_id == "relay-resolve":
            self._start_resolve_flow(source="resume")
        elif button_id and button_id.startswith("resolve-"):
            if button_id == "resolve-setup":
                self._main("#resolve-actions").display = False
                self._open_relay_setup()
            else:
                opt_id = button_id.removeprefix("resolve-")
                if opt_id.startswith("opt-"):
                    opt_id = opt_id.removeprefix("opt-")
                self._on_resolve_button_pressed(opt_id)
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
        elif button_id == "manual-pass":
            self._pass_manual_check()
        elif button_id == "manual-fail":
            self._start_fail_manual_check()
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
        if select.id == "cb-backup":
            self._cb_on_backup_changed(event)
            return
        if select.id == "cb-timeout":
            if event.value is not Select.BLANK and event.value is not None:
                self.session.chat_timeout_seconds = (
                    "none" if event.value == "none" else int(event.value)
                )
            return
        if select.id != "cb-agent":
            return
        # Textual queues Changed, so a refresh can move the value again
        # before this message runs. Ignore that stale value.
        if event.value != select.value:
            return
        value = event.value
        if value == _CB_BACKUP_MENU:
            self._cb_restore_agent_select()
            self._cb_open_chain_editor()
            return
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
        self._sync_split()
        self._cb_fit()
        self._fit_controls()

    def query_one(self, selector: Any = None, *args: Any, **kwargs: Any) -> Any:
        if selector == "#change-agents":
            try:
                return super().query_one("#pause-change-agents", *args, **kwargs)
            except Exception:
                pass
        return super().query_one(selector, *args, **kwargs)

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
        cancel_event = getattr(self, "_cancel_event", None)
        if cancel_event is not None:
            cancel_event.set()
            self.render_event(SessionEvent(kind="output", text="Stopping…"))
        self._dispatch_token = object()
        self._sent_attachments = []
        if getattr(self, "_release_task", None):
            self._release_task = None
            self._sync_mode_indicator()
        if self._plan_state == "working":
            self._leave_plan()
            self._end_run_flow("Run stopped: no plan was saved.")
        if getattr(self, "_auto_cancel_event", None) is not None:
            self._auto_cancel_event.set()
            self._auto_cancel_event = None
            self._end_run_flow("Run stopped.")
        if getattr(self, "_auto_relay", False):
            self._auto_relay = False
        for worker in self.workers:
            worker.cancel()
        self._disarm_follow()
        if cancel_event is None:
            self._set_busy(False)

    def _set_busy(self, busy: bool, label: str | None = None) -> None:
        """Enables Stop and shows the thinking line ("⠋ claude is thinking…
        12s") while a reply is pending, so a slow agent doesn't look like a
        frozen console."""
        self._main("#stop", Button).disabled = (
            not busy and not self._relay_running() and not self._external_relay
        )
        try:
            self._main("#cb-timeout", Select).disabled = (
                busy and not self._relay_running()
            )
        except (NoMatches, IndexError):
            pass
        thinking = self._main("#thinking", Static)
        if busy:
            self._busy_text = label or busy_label(self.session)
            self._busy_since = time.monotonic()
            thinking.display = True
            self._tick()
            if self._files_on:
                self._arm_follow()
        else:
            self._busy_text = ""
            if not self._relay_running():
                thinking.display = False
                self._disarm_follow()

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
            if getattr(self, "_manual_fail_id", None):
                self.render_event(
                    SessionEvent(
                        kind="error",
                        text=f"A failure note is required for {self._manual_fail_id} (fail needs a note).",
                    )
                )
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
        stripped_relay = strip_relay_prefix(text) or text
        first_word = stripped_relay.split(maxsplit=1)[0] if stripped_relay.strip() else ""
        if (
            getattr(self, "_manual_fail_id", None)
            and not text.startswith("/")
            and first_word != "manual"
        ):
            fail_id = self._manual_fail_id
            self._manual_fail_id = None
            self._sync_mode_indicator()
            self._run_manual_command(["manual", fail_id, "fail", text.strip()])
            return
        if (
            self.session.mode == "relay"
            and text.strip().lower() in ("done", "skip")
            and not getattr(self, "_release_task", None)
            and not self._restore_release_task()
        ):
            self.render_event(SessionEvent(kind="error", text=NO_RELEASE_PAUSE))
            return
        if getattr(self, "_release_task", None) and text.strip().lower() in ("done", "skip"):
            cmd = text.strip().lower()
            task_id, _ = self._release_task
            self._release_task = None
            self._sync_mode_indicator()
            self._launch_relay([cmd, task_id])
            return
        if (
            getattr(self, "_resolve_problem", None) is not None
            and self._main("#resolve-actions").display
            and not getattr(self, "_resolve_running", False)
            and not text.startswith("/")
        ):
            if text.strip().isdigit():
                idx = int(text.strip())
                if 1 <= idx <= len(self._resolve_problem.options):
                    opt = self._resolve_problem.options[idx - 1]
                    self._pick_resolve_option(opt)
                    return
        if self._plan_state in ("review", "answering") and not text.startswith("/"):
            self._plan_reply(text)
            return
        if self.session.mode == "relay":
            text = strip_relay_prefix(text) or text
            hint = self._relay_flag_hint(text.split())
            if hint is not None:
                self.render_event(SessionEvent(kind="error", text=hint))
                return
        if (self.session.mode == "relay" or getattr(self, "_manual_checks", None)) and first_word == "manual":
            self._handle_manual_input(stripped_relay)
            return
        if self.session.mode == "relay" and (text.strip() == "run" or text.split() == ["start"]):
            self._run_flow_start()
            return
        first = text.split(maxsplit=1)[0]
        if self.session.mode == "relay" and first in ("start", "resume"):
            self._manual_passed = False
            self._launch_relay(text.split())
            return
        # Slash commands stay available in every mode, including Agents.
        if self.session.mode == "assistant" and not text.startswith("/"):
            self.render_event(SessionEvent(
                kind="output",
                text="Use the buttons above, or message the bot on Telegram.",
            ))
            return
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
        command = text.strip()
        if command.split()[:1] == ["/awake"]:
            arg = command.removeprefix("/awake").strip().lower()
            if arg in ("", "on", "off"):
                self._set_awake({"": None, "on": True, "off": False}[arg])
            else:
                self.render_event(SessionEvent(kind="error", text="Use /awake, /awake on, or /awake off."))
            return True
        if command == "/reset-backup" and self._cb_chain_busy():
            self.render_event(SessionEvent(kind="error", text=RESET_BUSY_TEXT))
            return True
        if self.session.mode == "chat" and command == "/paste":
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
                                 self.session.agent or ""),
                self._start_brainstorm,
            )
            return True
        self.render_event(event)
        if command == "/help" and self._update_note:
            self.render_event(SessionEvent(kind="output", text=self._update_note))
        if command == "/reset-backup" and event.kind == "output":
            self._cb_reload_backup_options()
            self._cb_sync_failover()
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
        if choice == "open-settings":
            self._open_settings()
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
        # Replace the Chat cancel identity before this dispatch is current.
        # Stop leaves that event in place so the Chat worker can still report
        # Stopped.; once Brainstorm owns the turn, a late report must not
        # match and clear this busy state. A fresh Event: Brainstorm now
        # observes cancel between phases, and Stop waits for Stopped.
        import threading

        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        names = ", ".join(choice["agents"])
        self.render_event(SessionEvent(
            kind="output",
            text=f"Brainstorming \"{choice['topic']}\" with {names} -- several full "
                 "agent turns, so this takes a while.",
        ))
        token = object()
        self._dispatch_token = token
        self._set_busy(True, "brainstorming")
        self.run_worker(
            lambda: self._brainstorm_in_thread(choice, token, cancel_event),
            thread=True,
        )

    def _brainstorm_in_thread(self, choice: dict, token: object, cancel_event=None) -> None:
        def progress(line: str) -> None:
            self.call_from_thread(self._brainstorm_progress, line, token)

        try:
            result = adapters.run_brainstorm(
                self.session.root,
                progress=progress,
                cancel_event=cancel_event,
                **choice,
            )
        except Exception as error:  # an agent failure mid-run must not end the console
            result = SessionEvent(kind="error", text=f"Brainstorm stopped: {error}")
        self.call_from_thread(self._finish_dispatch, result, token, True, cancel_event)

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

    def _open_settings(self) -> None:
        from whyline import account
        from whyline.console.settings_screen import ProviderSettingsScreen

        self.push_screen(
            ProviderSettingsScreen(
                account.load_global() or {},
                account.check_provider,
                account.set_enabled_many,
            ),
            self._settings_closed,
        )

    def _settings_closed(self, enabled: object) -> None:
        if enabled is None:
            return
        self._apply_settings()

    def _apply_settings(self) -> None:
        """Refresh pickers after a Settings Save; do not change mode or persist defaults."""
        from whyline import account, model

        status = account.agent_status(self.session.root)
        saved = model.resolve(self.session.root)[0]
        usable = [
            agent
            for agent in account.AGENT_ORDER
            if provider_enabled(status.get(agent))
            and (status.get(agent) or {}).get("available")
        ]
        any_enabled = any(
            provider_enabled(status.get(agent)) for agent in account.AGENT_ORDER
        )
        saved_enabled = provider_enabled(status.get(saved))
        saved_usable = saved_enabled and bool((status.get(saved) or {}).get("available"))
        current = self.session.agent or saved
        if not provider_enabled(status.get(current)):
            if saved_usable:
                self.session.agent = saved
            elif usable:
                self.session.agent = usable[0]
                if not saved_enabled:
                    self.render_event(SessionEvent(
                        kind="output",
                        text=(
                            "The saved agent is off in Settings; "
                            f"using {usable[0]} for this session."
                        ),
                    ))
            elif not any_enabled:
                self.render_event(SessionEvent(kind="error", text=NO_SUBSCRIPTIONS))
        elif current and (status.get(current) or {}).get("available"):
            self.session.agent = current
        self._cb_agent_shown = self.session.agent
        self._cb_status_seen = None
        self._cb_refresh_status()
        self._cb_reload_backup_options()
        self._sync_mode_indicator()

    def _dispatch_text(self, text: str, attachments=()) -> None:
        in_chat = self.session.mode == "chat"
        uses = in_chat and self.session.agent == "antigravity"
        timeout_seconds = (
            self.session.chat_timeout_seconds if in_chat else _UNSET
        )

        def proceed(allowed: bool) -> None:
            if not allowed:
                self.render_event(SessionEvent(
                    kind="error", text="Antigravity can't run here until this repo is trusted."))
                return
            import threading

            cancel_event = threading.Event() if in_chat else None
            self._cancel_event = cancel_event
            token = object()
            self._dispatch_token = token
            self._set_busy(True)
            def work(timeout=timeout_seconds, cancel_event=cancel_event) -> None:
                kwargs = {}
                if attachments:
                    kwargs["attachments"] = attachments
                if (
                    timeout is not _UNSET
                    and _accepts_kwarg(self._dispatch_in_thread, "timeout_seconds")
                ):
                    kwargs["timeout_seconds"] = timeout
                if _accepts_kwarg(self._dispatch_in_thread, "cancel_event"):
                    kwargs["cancel_event"] = cancel_event
                self._dispatch_in_thread(text, token, **kwargs)

            self.run_worker(work, thread=True)

        self._with_antigravity(uses, proceed)

    def _dispatch_in_thread(
        self,
        text: str,
        token: object,
        attachments=(),
        *,
        timeout_seconds: object = _UNSET,
        cancel_event=None,
    ) -> None:
        launched = True
        try:
            kwargs = {}
            if attachments:
                kwargs["attachments"] = attachments
            if (
                timeout_seconds is not _UNSET
                and _accepts_kwarg(dispatch, "timeout_seconds")
            ):
                kwargs["timeout_seconds"] = timeout_seconds
            if _accepts_kwarg(dispatch, "cancel_event"):
                kwargs["cancel_event"] = cancel_event
            result = dispatch(self.session, text, **kwargs)
        except Exception as error:  # a safety net beyond adapters.py's own handling
            result = SessionEvent(kind="error", text=str(error), accepted=False)
            launched = False
        else:
            launched = getattr(result, "accepted", True) and getattr(result, "launched", True)
        self.call_from_thread(
            self._finish_dispatch, result, token, launched, cancel_event
        )

    def _finish_dispatch(
        self,
        result: SessionEvent,
        token: object,
        launched: bool = True,
        cancel_event=None,
    ) -> None:
        # Checked here, on the main thread, rather than in the worker: a
        # Stop or newer dispatch that lands between the worker's check and
        # this call would otherwise still let a stale result through.
        text = getattr(result, "text", None)
        if (
            getattr(result, "kind", None) == "error"
            and isinstance(text, str)
            and text.startswith("Stopped.")
        ):
            if cancel_event is not getattr(self, "_cancel_event", None):
                return
            self._cancel_event = None
            self._set_busy(False)
            self.render_event(result)
            return
        if token is not self._dispatch_token:
            return
        if (
            cancel_event is not None
            and cancel_event is getattr(self, "_cancel_event", None)
        ):
            self._cancel_event = None
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

    def _doctor_agent_lines(self) -> list[str]:
        root = self.session.root
        try:
            from whyline_relay import config, preflight

            agent_kw = ("on PATH", "logged in", "login", "generic agent", "permission-bypass")
            checks = []
            try:
                all_checks = preflight.run(root)
                checks = [
                    c for c in all_checks
                    if any(kw in c.message for kw in agent_kw)
                ]
            except Exception:
                checks = []

            if not checks:
                settings = None
                try:
                    _, settings = preflight._relay_setup(root)
                except Exception:
                    settings = None
                if settings is None:
                    try:
                        settings = config.load(root)
                    except Exception:
                        settings = None
                if settings is not None:
                    try:
                        pchecks, _ = preflight._programs(settings)
                        checks.extend(pchecks)
                    except Exception:
                        pass
                    try:
                        runner = getattr(self, "runner", None)
                        lchecks = preflight._logins(
                            root,
                            settings,
                            runner=runner if callable(runner) else subprocess.run,
                        )
                        checks.extend(lchecks)
                    except Exception:
                        pass
                    try:
                        rchecks = preflight._role_checks(root, settings)
                        checks.extend(rchecks)
                    except Exception:
                        pass

            lines = []
            for check in checks:
                line = f"  {check.status:<4}  {check.message}"
                if check.status != "ok" and check.hint:
                    line += f"\n        fix: {check.hint}"
                lines.append(line)
            return lines
        except Exception:
            return []

    def _open_relay_plan(self) -> None:
        if self._refuse_in_home():
            return
        if not relay_ops.relay_agents(self.session.root):
            self._run_flow = False
            from whyline.console.relay_screens import NO_AGENTS_PLAN

            msg = NO_AGENTS_PLAN
            doctor_lines = self._doctor_agent_lines()
            if doctor_lines:
                msg = f"{msg}\n" + "\n".join(doctor_lines)
            self.render_event(SessionEvent(kind="output", text=msg))
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
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], plan_job.AutoRunRequest):
            request, fingerprint = result
            self._start_auto_job(request, fingerprint)
            return
        if isinstance(result, plan_job.PlanRequest):
            self._start_plan_job(result)
        else:
            self._plan_saved(result)

    def _start_auto_job(self, request: plan_job.AutoRunRequest, fingerprint: str) -> None:
        import threading

        cancel_event = threading.Event()
        self._auto_cancel_event = cancel_event
        self._auto_relay = True
        self._auto_request = request
        token = object()
        self._dispatch_token = token
        self._set_busy(True, "auto")
        root = self.session.root

        def in_thread() -> None:
            def progress(line: str) -> None:
                self.call_from_thread(self._auto_progress, line, token)

            result = None
            error = None
            try:
                result = plan_job.run_auto(
                    root,
                    request,
                    fingerprint,
                    progress=progress,
                    cancel_event=cancel_event,
                    launcher=lambda args: self.call_from_thread(self._launch_relay, args, auto=True),
                    runner=getattr(self, "_runner", None),
                )
            except Exception as caught:
                error = caught
            if error is not None:
                self.call_from_thread(self._auto_failed, error, token)
                return
            self.call_from_thread(self._auto_done, result, token)

        self.run_worker(in_thread, thread=True)

    def _auto_progress(self, line: str, token: object) -> None:
        if token is not self._dispatch_token:
            return
        self.render_event(SessionEvent(kind="output", text=line))
        self._busy_text = line

    def _auto_failed(self, error: Exception, token: object) -> None:
        if token is not self._dispatch_token:
            return
        self._set_busy(False)
        self._auto_cancel_event = None
        self._auto_relay = False
        self.render_event(
            SessionEvent(
                kind="error",
                text=f"Auto run stopped: {error or error.__class__.__name__}.",
            )
        )
        self._end_run_flow("Run stopped.")

    def _auto_done(self, result: dict | None, token: object) -> None:
        if token is not self._dispatch_token:
            return
        self._set_busy(False)
        self._auto_cancel_event = None
        if isinstance(result, dict):
            if "pause" in result:
                reason = result["pause"].get("reason", "")
                self.render_event(SessionEvent(kind="pause", text=reason))
                self._auto_relay = False
            elif result.get("phase") == "stopped":
                self.render_event(SessionEvent(kind="output", text="Auto run stopped."))
                self._auto_relay = False
        if not self._relay_running():
            self._end_run_flow("Auto run finished.")

    def _plan_saved(self, path: Path | None, *, has_test_plan: bool = False) -> None:
        if path is None:
            return
        from whyline_relay import testplan

        self._setup_plan_hint = path
        shown = (path.relative_to(self.session.root) if path.is_relative_to(self.session.root) else path).as_posix()
        test_path = testplan.path_for(path)
        if has_test_plan or test_path.is_file():
            shown_test = (
                test_path.relative_to(self.session.root)
                if test_path.is_relative_to(self.session.root)
                else test_path
            ).as_posix()
            text = (
                f"Saved {shown} and {shown_test} and committed them. Next: Set up, to pick the plan and who "
                "implements, tests and reviews."
            )
        else:
            text = (
                f"Saved {shown} and committed it. Next: Set up, to pick the plan and who "
                "implements, tests and reviews."
            )
        self.render_event(SessionEvent(kind="output", text=text))
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

        test_planner = getattr(request, "test_planner", "") or getattr(
            getattr(request, "drafter", ""), "_test_planner", ""
        )
        agents = {str(request.drafter), str(request.reviewer), str(request.writer)}
        if test_planner:
            agents.add(str(test_planner))
        if request.brainstorm:
            agents |= set(request.brainstorm["agents"])
        self._with_antigravity("antigravity" in agents, proceed)

    def _run_plan(self, work) -> None:
        root = self.session.root
        token = object()
        self._dispatch_token = token
        self._set_plan_state("working")
        self._set_busy(True, "planning")

        def in_thread() -> None:
            def progress(line: str) -> None:
                self.call_from_thread(self._plan_progress, line, token)

            outcome = None
            error = None
            try:
                outcome = work(progress)
            except Exception as caught:  # agent missing, timeout, relay pause...
                error = caught
            try:
                relay_ops.clear_live_run(root)
            except Exception as cleanup_error:
                if error is None:
                    error = cleanup_error
            if error is not None:
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

        from whyline_relay import testplan

        draft = outcome.draft
        had_draft_testplan = (
            bool(relay_ops.planner_agents(root)[2])
            and draft is not None
            and getattr(draft, "path", None) is not None
            and testplan.path_for(draft.path).is_file()
        )
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
        self._plan_saved(path, has_test_plan=had_draft_testplan)

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

    def _resume_should_allow_dirty(self) -> bool:
        try:
            from whyline_relay import gitcheck, state as relay_state

            saved = relay_state.load(self.session.root)
            if not saved or not saved.task_id:
                return False
            dirty = [
                p
                for p in gitcheck.dirty_paths(self.session.root)
                if not p.startswith(".whyline/relay/")
            ]
            return bool([p for p in dirty if p != ".whyline/decisions.md"])
        except Exception:
            return False

    def _open_relay_setup(self, guided: bool = False, plan: Path | None = None) -> None:
        if self._refuse_in_home():
            return
        from whyline.console.relay_screens import RelaySetupScreen

        try:
            paused = bool(relay_ops.paused_run(self.session.root))
        except Exception:
            paused = False

        self.push_screen(
            RelaySetupScreen(self.session.root, guided=guided, plan=plan, paused=paused),
            self._setup_done,
        )

    def _setup_done(self, choice: Any) -> None:
        if choice == "open-settings":
            self._run_flow = False
            self._open_settings()
            return
        if choice == "start":
            self._run_flow = False
            self._launch_relay(["start"])
        elif choice == "resume" or (isinstance(choice, tuple) and choice and choice[0] == "resume"):
            self._run_flow = False
            cleared_lines = choice[1] if isinstance(choice, tuple) and len(choice) > 1 else []
            for line in cleared_lines:
                self.render_event(SessionEvent(kind="output", text=line))
            self._manual_passed = False
            args = ["resume"]
            if self._resume_should_allow_dirty():
                args.append("--allow-dirty")
            self._launch_relay(args)
        elif choice == "plan":
            self._run_flow = True
            self._open_relay_plan()
        elif isinstance(choice, tuple) and len(choice) == 2 and choice[0] == "resolve":
            self._run_flow = False
            self._start_resolve_flow(source="setup", fail_lines=choice[1])
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
        was_live = self._external_relay
        if live == self._external_relay or not self.screen_stack:
            return
        self._external_relay = live
        try:
            stop = self._main("#stop", Button)
        except NoMatches:
            return
        stop.disabled = not (self._busy_text or self._relay_running() or live)
        if live and not was_live:
            if self._files_on:
                self._arm_follow()
        elif not live and was_live:
            if not self._busy_text and not self._relay_running():
                self._disarm_follow()

    def _current_fail_lines(self) -> list[str]:
        fails = list(getattr(self, "_resolve_source_fail_lines", []))
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.session.root,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if not status:
                fails = [l for l in fails if "uncommitted changes" not in l]
        except Exception:
            pass
        try:
            from whyline_relay import running

            if running.live(self.session.root) is None:
                fails = [l for l in fails if "another relay is running here" not in l]
        except Exception:
            pass
        self._resolve_source_fail_lines = fails
        return fails

    def _start_resolve_flow(self, source: str, fail_lines: list[str] | None = None) -> None:
        from whyline.console import recovery
        from whyline_relay import state as relay_state

        if getattr(self, "_resolve_running", False):
            return

        self._resolve_source = source
        if fail_lines is not None:
            self._resolve_source_fail_lines = list(fail_lines)
        elif source == "resume":
            self._resolve_source_fail_lines = list(getattr(self, "_resume_fail_lines", []))
        else:
            self._resolve_source_fail_lines = []

        reason = ""
        if source == "resume":
            try:
                st = relay_state.load(self.session.root)
                if st and st.paused_reason:
                    reason = st.paused_reason
            except Exception:
                pass
            if not reason:
                reason = getattr(self, "_last_pause_text", "")

        fails = (
            list(self._resolve_source_fail_lines)
            if fail_lines is not None
            else self._current_fail_lines()
        )
        problems = recovery.diagnose(
            self.session.root,
            fail_lines=fails,
            pause_reason=reason,
        )
        self._resolve_problems = problems

        if not problems:
            if source == "setup":
                self.render_event(SessionEvent(kind="output", text="Resolved. Open Set up again and press Check."))
                self._show_resolve_setup_button()
            else:
                self.render_event(SessionEvent(kind="output", text="Resolved. Press Resume."))
                self._resume_fail_lines = []
                self._sync_relay_buttons()
            return

        self._resolve_problem = problems[0]
        self._show_resolve_problem(problems[0], is_first=True, count=len(problems))
        self._mount_resolve_buttons(problems[0])

    def _has_recognised_resume_problem(
        self, fail_lines: list[str], pause_text: str, text: str, code: int
    ) -> bool:
        from whyline.console import recovery
        from whyline_relay import state as relay_state

        saved_reason = ""
        try:
            st = relay_state.load(self.session.root)
            if st and st.paused_reason:
                saved_reason = st.paused_reason
        except Exception:
            pass

        reason = pause_text or saved_reason
        if fail_lines:
            diag = recovery.diagnose(
                self.session.root,
                fail_lines=fail_lines,
                pause_reason="",
            )
            has_dirty_line = any("uncommitted changes" in l for l in fail_lines)
            return any(
                p.id != "unknown"
                and (not p.id.startswith("dirty-") or has_dirty_line)
                for p in diag
            )

        if not reason:
            return False

        diag = recovery.diagnose(
            self.session.root,
            fail_lines=[],
            pause_reason=reason,
        )
        has_unrecognised_text = (
            bool(text.strip())
            and not pause_text
            and code != 2
            and "uncommitted changes" not in text.lower()
        )
        has_dirty_reason = (
            "dirty" in reason.lower() or "uncommitted changes" in reason.lower()
        )
        return any(
            p.id != "unknown"
            and (
                not p.id.startswith("dirty-")
                or not has_unrecognised_text
                or has_dirty_reason
            )
            for p in diag
        )

    def _show_resolve_problem(self, problem: Any, *, is_first: bool = False, count: int = 1) -> None:
        lines: list[str] = []
        if is_first:
            lines.append(f"Resolve: {count} problem(s)")
        lines.append(problem.summary)
        for ev in problem.evidence:
            lines.append(f"  {ev}")
        ordered_opts = sorted(problem.options, key=lambda o: not o.recommended)
        for idx, opt in enumerate(ordered_opts, 1):
            rec_str = " (recommended)" if opt.recommended else ""
            lines.append(f"  {idx}. {opt.label}{rec_str}")
        for line in lines:
            self.render_event(SessionEvent(kind="output", text=line))

    def _mount_resolve_buttons(self, problem: Any) -> None:
        try:
            row = self._main("#resolve-actions", Horizontal)
        except (NoMatches, IndexError):
            return
        row.remove_children()
        for child in list(row.children):
            row._nodes._remove(child)
        ordered_opts = sorted(problem.options, key=lambda o: not o.recommended)
        for opt in ordered_opts:
            variant = "success" if opt.recommended else "default"
            row.mount(Button(opt.label, id=f"resolve-{opt.id}", variant=variant))
        row.display = True

    def _show_resolve_setup_button(self) -> None:
        try:
            row = self._main("#resolve-actions", Horizontal)
        except (NoMatches, IndexError):
            return
        row.remove_children()
        for child in list(row.children):
            row._nodes._remove(child)
        row.mount(Button("Set up", id="resolve-setup", variant="primary"))
        row.display = True

    def _on_resolve_button_pressed(self, opt_id: str) -> None:
        if self._resolve_problem is None or getattr(self, "_resolve_running", False):
            return
        matched = next((opt for opt in self._resolve_problem.options if opt.id == opt_id), None)
        if matched is not None:
            self._pick_resolve_option(matched)

    def _pick_resolve_option(self, opt: Any) -> None:
        if getattr(self, "_resolve_running", False):
            return
        if opt.id == "cancel":
            self._close_resolve_flow()
            self.render_event(SessionEvent(kind="output", text="Resolve cancelled; nothing else was changed."))
            return
        if opt.confirm:
            def confirmed(yes: bool) -> None:
                if yes:
                    self._execute_resolve_option(opt)

            self.push_screen(
                ConfirmScreen(f"Run {opt.detail}?", confirm_label=opt.label),
                confirmed,
            )
            return
        self._execute_resolve_option(opt)

    def _close_resolve_flow(self) -> None:
        self._resolve_problem = None
        self._resolve_problems = []
        self._resolve_running = False
        try:
            self._main("#resolve-actions").display = False
        except (NoMatches, IndexError):
            pass
        self._sync_relay_buttons()

    def _execute_resolve_option(self, opt: Any) -> None:
        from whyline.console import recovery

        if getattr(self, "_resolve_running", False):
            return
        self._resolve_running = True
        try:
            for btn in self._main("#resolve-actions").query(Button):
                btn.disabled = True
        except (NoMatches, IndexError):
            pass
        self._sync_relay_buttons()

        if opt.id == "ask-agent":
            def passed_over(agent: str, why: str, following: str | None) -> None:
                self.call_from_thread(self._ask_agent_passed_over, agent, why, following)

            def ask_thread() -> None:
                ask_res = None
                try:
                    ask_res = recovery.ask_agent(
                        self.session.root,
                        session=self.session,
                        runner=self._runner,
                        fail_lines=self._current_fail_lines(),
                        problem=self._resolve_problem,
                        on_fallback=passed_over,
                    )
                except Exception:
                    pass
                finally:
                    self.call_from_thread(self._ask_agent_finished, ask_res)

            # The turn can take minutes; without the thinking line the
            # disabled buttons look like a frozen console.
            agent = self.session.agent or "the agent"
            self.render_event(
                SessionEvent(kind="output", text=f"Asking {agent} to analyse the problem…")
            )
            self._set_busy(True, f"{agent} is analysing the problem")
            self.run_worker(ask_thread, thread=True)
            return

        def in_thread() -> None:
            res = ""
            did_resume = False
            try:
                def launcher(args: list[str]) -> None:
                    nonlocal did_resume
                    did_resume = True
                    self.call_from_thread(self._launch_relay, args)

                res = recovery.apply(
                    self.session.root,
                    self._resolve_problem,
                    opt.id,
                    launch=launcher,
                )
            except Exception as exc:
                res = f"Resolve error: {exc}"
            finally:
                self.call_from_thread(self._resolve_option_finished, opt, res, did_resume)

        self.run_worker(in_thread, thread=True)

    def _resolve_option_finished(self, opt: Any, res: Any, did_resume: bool) -> None:
        from whyline.console import recovery
        from whyline_relay import state as relay_state

        self._resolve_running = False
        login_agent = ""
        if isinstance(res, recovery.LoginRequest):
            login_agent = res.agent
            self._login(res.agent)
            res = ""
        if isinstance(res, Screen):
            self._close_resolve_flow()
            self.push_screen(res, self._setup_done)
            return
        if res:
            self.render_event(SessionEvent(kind="output", text=res))

        if did_resume:
            self._close_resolve_flow()
            return

        if opt.id == "cancel":
            self._close_resolve_flow()
            return

        if opt.id == "show" and self._resolve_problem is not None:
            for ev in self._resolve_problem.evidence:
                self.render_event(SessionEvent(kind="output", text=f"  {ev}"))

        # Re-run recovery.diagnose for the same source
        fails = self._current_fail_lines()
        reason = ""
        if self._resolve_source == "resume":
            try:
                st = relay_state.load(self.session.root)
                if st and st.paused_reason:
                    reason = st.paused_reason
            except Exception:
                pass

        new_problems = recovery.diagnose(
            self.session.root,
            fail_lines=fails,
            pause_reason=reason,
        )
        if login_agent:
            from whyline import account

            info = account.agent_status(self.session.root).get(login_agent) or {}
            if info.get("available"):
                new_problems = [
                    p
                    for p in new_problems
                    if p.id != "logged-out" or login_agent not in p.summary
                ]

        prev_id = self._resolve_problem.id if self._resolve_problem else None
        problem_gone = not any(p.id == prev_id for p in new_problems)

        if problem_gone:
            if not new_problems:
                self._resolve_problem = None
                self._resolve_problems = []
                if self._resolve_source == "setup":
                    self.render_event(SessionEvent(kind="output", text="Resolved. Open Set up again and press Check."))
                    self._show_resolve_setup_button()
                else:
                    self.render_event(SessionEvent(kind="output", text="Resolved. Press Resume."))
                    self._resume_fail_lines = []
                    try:
                        self._main("#resolve-actions").display = False
                    except (NoMatches, IndexError):
                        pass
                    self._sync_relay_buttons()
                    try:
                        self._main("#relay-resume", Button).disabled = False
                    except (NoMatches, IndexError):
                        pass
            else:
                next_prob = new_problems[0]
                self._resolve_problems = new_problems
                self._resolve_problem = next_prob
                self._show_resolve_problem(next_prob, is_first=False, count=len(new_problems))
                self._mount_resolve_buttons(next_prob)
        else:
            try:
                for btn in self._main("#resolve-actions").query(Button):
                    btn.disabled = False
            except (NoMatches, IndexError):
                pass
            self._sync_relay_buttons()

    def _ask_agent_passed_over(self, agent: str, why: str, following: str | None) -> None:
        if following:
            text = f"{agent} {why}; asking {following}…"
            self._set_busy(True, f"{following} is analysing the problem")
        else:
            text = f"{agent} {why}; no backup agent left to ask."
        self.render_event(SessionEvent(kind="output", text=text))

    def _ask_agent_finished(self, res: Any) -> None:
        from whyline.console import recovery

        self._resolve_running = False
        self._set_busy(False)
        # With no usable answer, the rule-based fixes stay on offer.
        kept = [
            recovery.Option(o.id, o.label, o.detail, recommended=False, confirm=o.confirm)
            for o in (self._resolve_problem.options if self._resolve_problem else [])
            if o.id not in ("show", "cancel", "ask-agent")
        ]

        if res is None:
            self.render_event(SessionEvent(kind="output", text="Agent inquiry failed."))
            self.render_event(
                SessionEvent(
                    kind="output",
                    text="Check by hand: inspect problem details and logs.",
                )
            )
            show_opt = recovery.Option(
                "show", "Show evidence", "print the evidence again", recommended=False, confirm=False
            )
            cancel_opt = recovery.Option(
                "cancel", "Cancel", "cancel resolve", recommended=False, confirm=False
            )
            self._resolve_problem = recovery.Problem(
                id=self._resolve_problem.id if self._resolve_problem else "unknown",
                summary=self._resolve_problem.summary if self._resolve_problem else "Unknown problem",
                evidence=self._resolve_problem.evidence if self._resolve_problem else [],
                options=[*kept, show_opt, cancel_opt],
            )
            self._mount_resolve_buttons(self._resolve_problem)
            self._sync_relay_buttons()
            return

        if res.status == "recommended" and res.option is not None:
            if res.explanation:
                self.render_event(SessionEvent(kind="output", text=res.explanation))
            show_opt = recovery.Option(
                "show", "Show evidence", "print the evidence again", recommended=False, confirm=False
            )
            cancel_opt = recovery.Option(
                "cancel", "Cancel", "cancel resolve", recommended=False, confirm=False
            )
            new_opts = [res.option, show_opt, cancel_opt]
            self._resolve_problem = recovery.Problem(
                id=self._resolve_problem.id if self._resolve_problem else "unknown",
                summary=self._resolve_problem.summary if self._resolve_problem else "Unknown problem",
                evidence=self._resolve_problem.evidence if self._resolve_problem else [],
                options=new_opts,
            )
            for idx, opt in enumerate(new_opts, 1):
                rec_str = " (recommended)" if opt.recommended else ""
                self.render_event(SessionEvent(kind="output", text=f"  {idx}. {opt.label}{rec_str}"))
            self._mount_resolve_buttons(self._resolve_problem)
            self._sync_relay_buttons()
            return

        if res.status == "unlisted":
            if res.explanation:
                self.render_event(SessionEvent(kind="output", text=res.explanation))
            self.render_event(
                SessionEvent(
                    kind="output",
                    text=f"Agent recommended unlisted option '{res.recommendation}'; ignored.",
                )
            )
            self.render_event(
                SessionEvent(
                    kind="output",
                    text="Check by hand: inspect problem details and logs.",
                )
            )
            show_opt = recovery.Option(
                "show", "Show evidence", "print the evidence again", recommended=False, confirm=False
            )
            cancel_opt = recovery.Option(
                "cancel", "Cancel", "cancel resolve", recommended=False, confirm=False
            )
            self._resolve_problem = recovery.Problem(
                id=self._resolve_problem.id if self._resolve_problem else "unknown",
                summary=self._resolve_problem.summary if self._resolve_problem else "Unknown problem",
                evidence=self._resolve_problem.evidence if self._resolve_problem else [],
                options=[*kept, show_opt, cancel_opt],
            )
            self._mount_resolve_buttons(self._resolve_problem)
            self._sync_relay_buttons()
            return

        if res.status == "modified":
            paths_str = ", ".join(res.changed_paths)
            self.render_event(
                SessionEvent(
                    kind="output",
                    text=f"Agent turn modified files: {paths_str}. Recommendation discarded.",
                )
            )
            self.render_event(
                SessionEvent(
                    kind="output",
                    text="Check by hand: inspect modified files and repository status.",
                )
            )
            show_opt = recovery.Option(
                "show", "Show evidence", "print the evidence again", recommended=False, confirm=False
            )
            cancel_opt = recovery.Option(
                "cancel", "Cancel", "cancel resolve", recommended=False, confirm=False
            )
            self._resolve_problem = recovery.Problem(
                id=self._resolve_problem.id if self._resolve_problem else "unknown",
                summary=self._resolve_problem.summary if self._resolve_problem else "Unknown problem",
                evidence=self._resolve_problem.evidence if self._resolve_problem else [],
                options=[*kept, show_opt, cancel_opt],
            )
            self._mount_resolve_buttons(self._resolve_problem)
            self._sync_relay_buttons()
            return

        if res.status == "human":
            if res.explanation:
                self.render_event(SessionEvent(kind="output", text=res.explanation))
            self.render_event(
                SessionEvent(
                    kind="output",
                    text="Check by hand: manual intervention required.",
                )
            )
            show_opt = recovery.Option(
                "show", "Show evidence", "print the evidence again", recommended=False, confirm=False
            )
            cancel_opt = recovery.Option(
                "cancel", "Cancel", "cancel resolve", recommended=False, confirm=False
            )
            self._resolve_problem = recovery.Problem(
                id=self._resolve_problem.id if self._resolve_problem else "unknown",
                summary=self._resolve_problem.summary if self._resolve_problem else "Unknown problem",
                evidence=self._resolve_problem.evidence if self._resolve_problem else [],
                options=[*kept, show_opt, cancel_opt],
            )
            self._mount_resolve_buttons(self._resolve_problem)
            self._sync_relay_buttons()
            return

        if res.status == "exhausted":
            why = dict(getattr(res, "fallbacks", []) or [])
            agents_str = (
                ", ".join(
                    f"{a} ({why[a]})" if a in why else a for a in res.agents_tried
                )
                if res.agents_tried
                else "none"
            )
            self.render_event(
                SessionEvent(
                    kind="output",
                    text=f"Exhausted recovery chain. Agents tried: {agents_str}.",
                )
            )
            self.render_event(
                SessionEvent(
                    kind="output",
                    text="Check by hand: inspect failure reason and logs.",
                )
            )
            show_opt = recovery.Option(
                "show", "Show evidence", "print the evidence again", recommended=False, confirm=False
            )
            cancel_opt = recovery.Option(
                "cancel", "Cancel", "cancel resolve", recommended=False, confirm=False
            )
            self._resolve_problem = recovery.Problem(
                id=self._resolve_problem.id if self._resolve_problem else "unknown",
                summary=self._resolve_problem.summary if self._resolve_problem else "Unknown problem",
                evidence=self._resolve_problem.evidence if self._resolve_problem else [],
                options=[*kept, show_opt, cancel_opt],
            )
            self._mount_resolve_buttons(self._resolve_problem)
            self._sync_relay_buttons()
            return

    def _resolve_relay_pause(self) -> None:
        self._start_resolve_flow(source="resume")

    def _auto_resolve(self, pause_reason: str = "", fail_lines: list[str] | None = None) -> None:
        from whyline.console import recovery
        from whyline_relay import state as relay_state

        st = None
        try:
            st = relay_state.load(self.session.root)
        except Exception:
            pass

        task_id = (st.task_id if st and st.task_id else "") or "REC"
        round_num = (st.round if st and hasattr(st, "round") and st.round is not None else 1) or 1
        reason = pause_reason or (st.paused_reason if st and st.paused_reason else "")

        fails = list(fail_lines) if fail_lines is not None else list(getattr(self, "_resume_fail_lines", []))
        problems = recovery.diagnose(self.session.root, fail_lines=fails, pause_reason=reason)

        if not problems:
            self._sync_relay_buttons()
            return

        is_auto = getattr(self, "_auto_relay", False)

        if not recovery.allowed(self.session.root, task_id, round_num):
            stop_reason = f"recovery already attempted for {task_id} round {round_num}"
            self.render_event(SessionEvent(kind="output", text=f"Auto stopped: {stop_reason}"))
            self._resolve_problem = problems[0]
            self._resolve_problems = problems
            self._resolve_source = "resume"
            self._show_resolve_problem(problems[0], is_first=True, count=len(problems))
            self._mount_resolve_buttons(problems[0])
            if is_auto:
                self._auto_relay = False
                self._end_run_flow("Auto run stopped.")
            self._sync_relay_buttons()
            return

        for problem in problems:
            opt = recovery.auto_option(problem)
            if opt is None:
                stop_reason = problem.summary
                self.render_event(SessionEvent(kind="output", text=f"Auto stopped: {stop_reason}"))
                self._resolve_problem = problem
                self._resolve_problems = problems
                self._resolve_source = "resume"
                self._show_resolve_problem(problem, is_first=True, count=len(problems))
                self._mount_resolve_buttons(problem)
                if is_auto:
                    self._auto_relay = False
                    self._end_run_flow("Auto run stopped.")
                self._sync_relay_buttons()
                return

            self.render_event(
                SessionEvent(kind="output", text=f"resolve · auto · {problem.id} · {opt.id}")
            )
            did_resume = False

            def launcher(args: list[str]) -> None:
                nonlocal did_resume
                did_resume = True
                self._launch_relay(args, auto=is_auto)

            res_line = recovery.apply(
                self.session.root,
                problem,
                opt.id,
                launch=launcher,
            )
            if isinstance(res_line, recovery.LoginRequest):
                # Auto never starts a login; a login always needs a click.
                self.render_event(
                    SessionEvent(kind="output", text=f"Auto stopped: {problem.summary}")
                )
                self._resolve_problem = problem
                self._resolve_problems = problems
                self._resolve_source = "resume"
                self._show_resolve_problem(problem, is_first=True, count=len(problems))
                self._mount_resolve_buttons(problem)
                if is_auto:
                    self._auto_relay = False
                    self._end_run_flow("Auto run stopped.")
                self._sync_relay_buttons()
                return
            if res_line:
                self.render_event(SessionEvent(kind="output", text=res_line))

            # The option lets diagnose tell the fix already ran for this pause.
            recovery.record_attempt(
                self.session.root,
                task=task_id,
                round=round_num,
                kind="resolve-auto",
                agent="",
                verdict="resolved",
                option=opt.id,
            )

            self._resume_fail_lines = []
            if not did_resume and opt.id != "wait":
                self._launch_relay(["resume"], auto=is_auto)

            return

    def _recover_auto_relay(self, pause_reason: str = "") -> None:
        if self._recovering_pause:
            return
        self._recovering_pause = True
        self._set_busy(True, "auto")

        def in_thread() -> None:
            res = None
            try:
                def progress(line: str) -> None:
                    self.call_from_thread(self.render_event, SessionEvent(kind="output", text=line))

                launcher = lambda args: self.call_from_thread(self._launch_relay, args, auto=True)
                res = adapters.recover_pause(
                    self.session.root,
                    session=self.session,
                    progress=progress,
                    launcher=launcher,
                    pause_reason=pause_reason,
                    request=getattr(self, "_auto_request", None),
                    runner=getattr(self, "_runner", None),
                )
            except Exception as exc:
                res = exc
            finally:
                def done() -> None:
                    self._recovering_pause = False
                    self._set_busy(False)
                    is_resolved = (
                        res == "resolved"
                        or getattr(res, "verdict", None) == "resolved"
                    )
                    if not is_resolved:
                        self._auto_relay = False
                        try:
                            from whyline_relay import state as relay_state
                            st = relay_state.load(self.session.root)
                            reason = (st.paused_reason if st and st.paused_reason else "") or str(res)
                            task_id = (st.task_id if st and st.task_id else "") or "REC"
                            log_path = st.log_path if st and st.log_path else ""
                        except Exception:
                            reason = str(res)
                            task_id = "REC"
                            log_path = ""
                        pause_text = adapters.format_pause_text(
                            self.session.root,
                            task_id,
                            reason,
                            log_path,
                        )
                        self.render_event(SessionEvent(kind="pause", text=pause_text))
                        self._end_run_flow("Auto run stopped.")
                    self._sync_relay_buttons()

                self.call_from_thread(done)

        self.run_worker(in_thread, thread=True)

    def _parse_manual_pause(self, text: str) -> tuple[str, list[Any]] | None:
        from whyline_relay import testplan

        lines = text.strip().splitlines()
        start_idx = None
        task_id = ""
        for idx, raw in enumerate(lines):
            cleaned = raw.strip()
            if cleaned.startswith("Paused:"):
                cleaned = cleaned.removeprefix("Paused:").strip()
            if cleaned.startswith(testplan.MANUAL_PREFIX):
                task_id = cleaned.removeprefix(testplan.MANUAL_PREFIX).rstrip(":").strip()
                start_idx = idx + 1
                break
        if start_idx is None:
            return None
        scenarios: list[Any] = []
        for raw in lines[start_idx:]:
            line = raw.strip()
            if not line or line.startswith("Check ") or line.startswith("Resume with:"):
                continue
            head, sep, rest = line.partition(":")
            if not sep or " " in head.strip():
                continue
            scenario_id = head.strip()
            title_part, sep_steps, after_steps = rest.partition("| steps:")
            if sep_steps:
                steps_part, _sep_exp, exp_part = after_steps.partition("| expected:")
                steps = tuple(s.strip() for s in steps_part.split(";") if s.strip())
                expected = tuple(e.strip() for e in exp_part.split(";") if e.strip())
            else:
                steps = ()
                expected = ()
            scenarios.append(
                testplan.Scenario(
                    id=scenario_id,
                    title=title_part.strip(),
                    covers=(task_id,) if task_id else (),
                    kind="manual",
                    steps=steps,
                    expected=expected,
                    checked=False,
                )
            )
        return task_id, scenarios

    def _load_open_manual_checks(self, pause_text: str = "") -> tuple[str, list[Any]] | None:
        try:
            from whyline_relay import loop as relay_loop, testplan

            is_patched = getattr(relay_loop.manual_checks, "__module__", "") != "whyline_relay.loop"
            found = relay_loop.manual_checks(self.session.root)
            if found is not None:
                saved, pending = found
                task_id = getattr(saved, "task_id", "") or self._manual_task_id or "release"
                has_disk_tests = False
                try:
                    plan_path = relay_loop._plan_file(self.session.root, saved)
                    has_disk_tests = testplan.path_for(plan_path).is_file()
                except Exception:
                    has_disk_tests = True
                if pending or has_disk_tests or is_patched:
                    return task_id, list(pending)
        except Exception:
            pass
        if pause_text:
            return self._parse_manual_pause(pause_text)
        return None

    def _order_manual_checks(self, checks: list[Any]) -> list[Any]:
        remaining = [c for c in checks if c.id not in self._passed_manual_ids]
        unfailed = [
            c
            for c in remaining
            if c.id not in self._failed_manual_ids
            and not (getattr(c, "note", None) or "").startswith("FAILED ")
        ]
        failed = [
            c
            for c in remaining
            if c.id in self._failed_manual_ids
            or (getattr(c, "note", None) or "").startswith("FAILED ")
        ]
        return unfailed + failed

    def _format_manual_pause(self, task_id: str, checks: list[Any]) -> str:
        from whyline_relay import testplan

        base = testplan.pause_reason(task_id or "release", checks)
        if checks:
            return f"{base}\nCheck {checks[0].id}: Pass or Fail."
        return base

    def _show_manual_checks(self, task_id: str, checks: list[Any]) -> None:
        ordered = self._order_manual_checks(checks)
        self._manual_fail_id = None
        if ordered:
            self._manual_task_id = task_id or self._manual_task_id or "release"
            self._manual_checks = ordered
            self._manual_check = ordered[0]
            self._manual_passed = False
            self.render_event(
                SessionEvent(
                    kind="pause",
                    text=self._format_manual_pause(self._manual_task_id, ordered),
                )
            )
            try:
                row = self._main("#manual-actions")
                row.display = True
                for btn in row.query(Button):
                    btn.active_effect_duration = 0
                    btn.remove_class("-active")
            except (NoMatches, IndexError):
                pass
        else:
            self._manual_task_id = None
            self._manual_checks = []
            self._manual_check = None
            self._manual_passed = True
            try:
                self._main("#manual-actions").display = False
            except (NoMatches, IndexError):
                pass
            self.render_event(
                SessionEvent(
                    kind="output",
                    text="All manual checks passed. Press Resume to release.",
                )
            )
        self._sync_mode_indicator()
        self._sync_relay_buttons()

    def _clear_manual_checks(self) -> None:
        self._manual_task_id = None
        self._manual_checks = []
        self._manual_check = None
        self._manual_fail_id = None
        self._manual_passed = False
        self._passed_manual_ids.clear()
        self._failed_manual_ids.clear()
        try:
            self._main("#manual-actions").display = False
        except (NoMatches, IndexError):
            pass

    def _pass_manual_check(self) -> None:
        if not self._manual_checks or self._relay_running():
            return
        check = self._manual_checks[0]
        self._manual_fail_id = None
        self._sync_mode_indicator()
        self._run_manual_command(["manual", check.id, "pass"])

    def _start_fail_manual_check(self) -> None:
        if not self._manual_checks or self._relay_running():
            return
        check = self._manual_checks[0]
        self._manual_fail_id = check.id
        self.render_event(
            SessionEvent(
                kind="output",
                text=f"Why did {check.id} fail? Type a note in the prompt.",
            )
        )
        self._sync_mode_indicator()
        try:
            self._main("#prompt", Input).focus()
        except (NoMatches, IndexError):
            pass

    def _handle_manual_input(self, text: str) -> None:
        self._manual_fail_id = None
        parts = text.split(maxsplit=3)
        if len(parts) == 1:
            self._run_manual_command(["manual"])
            return
        if len(parts) == 2:
            self.render_event(
                SessionEvent(
                    kind="error",
                    text=f"say pass or fail, for example: whyline relay manual {parts[1]} pass",
                )
            )
            self._sync_mode_indicator()
            return
        scenario_id, action = parts[1], parts[2].lower()
        note = parts[3].strip() if len(parts) > 3 else ""
        if action == "pass":
            args = ["manual", scenario_id, "pass"] + ([note] if note else [])
            self._run_manual_command(args)
            return
        if action == "fail":
            if not note:
                self._manual_fail_id = scenario_id
                self.render_event(
                    SessionEvent(
                        kind="error",
                        text=f"A failure note is required for {scenario_id} (fail needs a note).",
                    )
                )
                self._sync_mode_indicator()
                return
            self._run_manual_command(["manual", scenario_id, "fail", note])
            return
        self.render_event(
            SessionEvent(
                kind="error",
                text=f"say pass or fail, for example: whyline relay manual {scenario_id} pass",
            )
        )
        self._sync_mode_indicator()

    def _run_manual_command(self, args: list[str]) -> None:
        self._manual_exited = False
        self._relay_launch_aborted = False
        self._launch_relay(args)
        if (
            not self._relay_running()
            and not self._manual_exited
            and not self._relay_launch_aborted
        ):
            self._refresh_manual_after_command(args, code=0, text="")

    def _refresh_manual_after_command(
        self, args: list[str], *, code: int, text: str
    ) -> None:
        if code != 0:
            err = text.strip() or f"The relay stopped with exit code {code}."
            self.render_event(SessionEvent(kind="error", text=err))
            self._sync_relay_buttons()
            return
        if len(args) >= 3 and args[0] == "manual":
            scenario_id, action = args[1], args[2].lower()
            if action == "pass":
                self._passed_manual_ids.add(scenario_id)
                self._failed_manual_ids.discard(scenario_id)
            elif action == "fail":
                self._failed_manual_ids.add(scenario_id)
        loaded = self._load_open_manual_checks(pause_text=text)
        if loaded is not None:
            task_id, checks = loaded
        elif "All manual checks passed" in text or "No open manual checks" in text:
            task_id = self._manual_task_id or "release"
            checks = []
        else:
            task_id = self._manual_task_id or "release"
            checks = list(self._manual_checks)
        self._show_manual_checks(task_id, checks)

    @staticmethod
    def _relay_flag_hint(args: list[str]) -> str | None:
        KNOWN_FLAGS = {
            "--allow-dirty",
            "--retry-stage",
            "--skip-checks",
            "--dry-run",
            "--allow-main",
            "--max-rounds",
            "--plan-format",
        }
        for i in range(len(args) - 1):
            if args[i].startswith("--") and not args[i + 1].startswith("-"):
                combined = f"{args[i]}-{args[i + 1]}"
                if combined in KNOWN_FLAGS:
                    return f"Did you mean {combined}?"
        return None

    def _launch_relay(self, args: list[str], *, auto: bool = False) -> None:
        """Start/Resume, from a button or typed. One relay at a time: ours,
        or one started elsewhere (a terminal) that running.live still sees."""
        hint = self._relay_flag_hint(args)
        if hint is not None:
            self.render_event(SessionEvent(kind="error", text=hint))
            return
        try:
            self._main("#pause-actions").display = False
        except (NoMatches, IndexError):
            pass
        self._auto_relay = auto
        self._last_relay_args = list(args)
        self._relay_launch_aborted = True
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
                    self._launch_relay(args, auto=auto)
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
        self._relay_launch_aborted = False
        if self._files_on:
            self._arm_follow()
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
        self._manual_exited = True
        if not self._busy_text:
            self._main("#thinking", Static).display = False
            self._main("#stop", Button).disabled = True
            self._disarm_follow()
        last_args = list(getattr(self, "_last_relay_args", ()))
        self._last_relay_args = []
        if last_args and last_args[0] == "manual":
            self._refresh_manual_after_command(last_args, code=code, text=text)
            return
        if not getattr(self, "_resolve_running", False):
            self._resolve_problem = None
            self._resolve_problems = []
            try:
                self._main("#resolve-actions").display = False
            except (NoMatches, IndexError):
                pass
        fail_lines = adapters.preflight_fail_lines(text)
        if fail_lines:
            self._resume_fail_lines = fail_lines
        elif code == 0:
            self._resume_fail_lines = []
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
        if not pause_text and text.strip().startswith(("release task for you: ", "Manual checks before ")):
            pause_text = text.strip()
        if not pause_text and code != 0:
            try:
                from whyline_relay import state as relay_state
                saved = relay_state.load(self.session.root)
                if saved and saved.paused_reason and (
                    saved.paused_reason.startswith(("release task for you: ", "Manual checks before "))
                    or code == 2
                ):
                    pause_text = saved.paused_reason
            except Exception:
                pass
        self._last_pause_text = pause_text

        if pause_text.startswith("Manual checks before "):
            self._auto_relay = False
            self._release_task = None
            self._passed_manual_ids.clear()
            self._failed_manual_ids.clear()
            loaded = self._load_open_manual_checks(pause_text=pause_text)
            if loaded is not None:
                task_id, checks = loaded
            else:
                task_id, checks = "release", []
            self._show_manual_checks(task_id, checks)
            return

        self._clear_manual_checks()

        if pause_text.startswith("release task for you: "):
            self._auto_relay = False
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

        mode = relay_ops.resolve_mode(self.session.root)
        is_auto = getattr(self, "_auto_relay", False)
        event = adapters.classify_relay_output(self.session.root, text, code)
        is_pause = bool(pause_text) or event.kind == "pause"

        is_dirty_fail = code != 0 and (
            "working tree has uncommitted changes" in text
            or "uncommitted changes" in text
        )
        is_preflight_fail = bool(fail_lines) or is_dirty_fail

        if mode == "auto" and (is_pause or is_preflight_fail):
            self._auto_resolve(pause_reason=pause_text or text, fail_lines=fail_lines)
            return

        if is_auto and (is_pause or is_dirty_fail):
            self._recover_auto_relay(pause_reason=pause_text or text)
            return

        if is_auto:
            self._auto_relay = False
            if event.kind == "output":
                self.render_event(SessionEvent(kind="output", text="Relay finished."))
                self._end_run_flow("Auto run finished.")
            else:
                self.render_event(SessionEvent(
                    kind="error",
                    text=f"The relay stopped with exit code {code}. Its full output is in "
                         ".whyline/relay/logs/console-run.log.",
                ))
                self._end_run_flow("Run stopped.")
            self._sync_relay_buttons()
            return

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

        is_resume_launch = bool(last_args) and last_args[0] in ("resume", "done")
        if (
            is_resume_launch
            and code != 0
            and mode != "auto"
            and self._has_recognised_resume_problem(fail_lines, pause_text, text, code)
        ):
            self.render_event(
                SessionEvent(
                    kind="output",
                    text="Resume could not start; here is what Resolve found.",
                )
            )
            self._start_resolve_flow(source="resume", fail_lines=fail_lines)

    async def action_quit(self) -> None:
        # Another console may have turned it off since this one last looked.
        self._awake = awake.status()
        if self._relay_running():
            screen = QuitRelayScreen(self._relay_label or "relay", awake_on=self._awake is not None)
            self.push_screen(screen, lambda choice: self._quit_choice(choice, screen.keep_awake))
            return
        if self._awake is not None:
            self.push_screen(QuitAwakeScreen(), self._quit_awake_choice)
            return
        self._quit_now()

    def _quit_awake_choice(self, choice: "str | None") -> None:
        if choice is None:
            return
        if choice == "sleep":
            awake.stop()
        self._quit_now()

    def _quit_now(self) -> None:
        if getattr(self, "_auto_cancel_event", None) is not None:
            from whyline.console import auto_run

            auto_run.close_console(self.session.root, self._auto_cancel_event)
        self.exit()

    def _quit_choice(self, choice: "str | None", keep_awake: bool = True) -> None:
        if choice is None:
            return
        if not keep_awake:
            awake.stop()
        if self._relay is not None:
            if choice == "stop":
                self._relay.interrupt()
            self._relay.stop_following()
        self.exit()

    def _set_awake(self, want: "bool | None") -> None:
        """None toggles. Reads the shared record first, so a console that
        is out of date never starts a second caffeinate or misses one."""
        if not awake.available():
            self.render_event(SessionEvent(
                kind="error", text="Keeping the Mac awake needs macOS's caffeinate."))
            return
        self._awake = awake.status()
        if want is None:
            want = self._awake is None
        if want and self._awake is None:
            self._awake = awake.start()
            if self._awake is None:
                self.render_event(SessionEvent(kind="error", text="caffeinate did not start."))
            else:
                self.render_event(SessionEvent(kind="output", text=_AWAKE_ON_TEXT))
        elif want:
            self.render_event(SessionEvent(
                kind="output", text=f"The Mac is already kept awake (since {self._awake.started:%H:%M})."))
        else:
            stopped = awake.stop()
            self._awake = None
            self.render_event(SessionEvent(
                kind="output",
                text="The Mac can sleep again." if stopped else "The Mac was not being kept awake.",
            ))
        self._sync_mode_indicator()



def _exec(binary: str, argv: list[str]) -> None:
    os.execvp(binary, argv)


_TEXTUAL_MISSING = (
    "The mouse TUI needs textual, which is missing from this "
    "install. Run: uv tool install --reinstall whyline"
)


def _offer_reinstall(ask, print_fn, install, problem) -> bool:
    """Without textual there is no screen to click, so the same Reinstall is
    a terminal question. True once the reinstall succeeded."""
    from whyline import __version__

    try:
        if problem() is not None:
            return False
        answer = ask(f"{_TEXTUAL_MISSING}\nReinstall whyline {__version__} now? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        return False
    if answer.strip().lower() not in ("y", "yes"):
        return False
    print_fn("Running: " + " ".join(update.install_argv(__version__, reinstall=True)))
    code = install(__version__, on_line=print_fn, reinstall=True)
    if code != 0:
        print_fn(update.failed_text(code, __version__))
        return False
    return True


def launch(root: Path, *, exec_fn=None, ask=None, print_fn=print,
           install=None, problem=None) -> None:
    if exec_fn is None:
        exec_fn = _exec
    if not TUI_AVAILABLE:
        import sys

        if ask is None and sys.stdin.isatty():
            ask = input
        if ask is not None and _offer_reinstall(
            ask, print_fn, install or update.install, problem or update.install_problem
        ):
            exec_fn(*update.RESTART)
            return
        raise TuiUnavailable(_TEXTUAL_MISSING)
    app = WhylineConsoleApp(root=root)
    app.run()
    if app._exec_after is not None:
        binary, argv = app._exec_after
        exec_fn(binary, argv)
