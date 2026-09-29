"""whyline console's mouse-enabled TUI, built on Textual.

Import-guarded exactly like editor.py guards prompt_toolkit, so the rest
of the console package stays importable and testable without the [ui]
extra installed. Reuses ConsoleSession/SessionEvent/adapters.py and
repl.py's dispatch() completely unchanged -- this module is a rendering
layer, not a second implementation of the console's logic.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal
    from rich.text import Text
    from textual.widgets import Button, Footer, Header, Input, RichLog, Static

    TUI_AVAILABLE = True
except ImportError:
    App = object  # placeholder base so WhylineConsoleApp can still be defined
    ComposeResult = None
    Horizontal = None
    Button = Footer = Header = Input = RichLog = Static = Text = None
    TUI_AVAILABLE = False

from whyline.console.repl import RELAY_SETUP, dispatch, handle_slash_command
from whyline.console.session import ConsoleSession, SessionEvent

_PREFIX = {"error": "⚠ ", "pause": "⏸ ", "input": "› "}

_MODES = ("command", "chat", "relay")


class TuiUnavailable(RuntimeError):
    """textual is not installed."""


class WhylineConsoleApp(App):
    """The mouse-enabled console. Every widget dispatches through the same
    ConsoleSession/dispatch() path the keyboard REPL already uses."""

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
    #modes-label { width: auto; padding: 1 1 0 1; }
    Input#prompt { width: 1fr; }
    """

    def __init__(self, *, root: Path) -> None:
        super().__init__()
        self.session = ConsoleSession(root=root)
        self._dispatch_token: object | None = None
        self._exec_after: tuple[str, list[str]] | None = None

    def on_mount(self) -> None:
        """Mirrors the plain REPL's own onboarding line (repl.py's `run`),
        plus the mode it's silently defaulting to: unlike the REPL prompt
        (which prints "(mode) > " before every line), the TUI had no
        indicator at all, so typing ordinary conversation in the default
        "command" mode looked like the console was just broken instead of
        interpreting free text as a `whyline` CLI invocation."""
        self._sync_mode_indicator()
        self.query_one("#prompt", Input).focus()
        self.render_event(
            SessionEvent(
                kind="output",
                text=(
                    "whyline console -- pick a mode above. Command runs what "
                    "you type as `whyline ...`, Chat talks to an agent, Relay "
                    "drives whyline-relay. Help explains the rest."
                ),
            )
        )

    def _sync_mode_indicator(self) -> None:
        """The subtitle alone was easy to miss, so the current mode is also
        the highlighted mode button and shapes the prompt's placeholder."""
        mode = self.session.mode
        self.sub_title = f"mode: {mode}"
        for name in _MODES:
            button = self.query_one(f"#mode-{name}", Button)
            button.variant = "primary" if name == mode else "default"
        self.query_one("#prompt", Input).placeholder = self._placeholder(mode)

    def _placeholder(self, mode: str) -> str:
        if mode == "chat":
            agent = self.session.agent or "claude"
            return f"Message {agent}... (Enter to send)"
        if mode == "relay":
            return "Relay command: doctor, status, start, resume (Enter to run)"
        return "whyline command, e.g. status or log (Enter to run)"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Static("Mode:", id="modes-label"),
            Button("Command", id="mode-command"),
            Button("Chat", id="mode-chat"),
            Button("Relay", id="mode-relay"),
            id="modes",
        )
        yield RichLog(id="transcript", wrap=True)
        yield Horizontal(
            Input(id="prompt"),
            Button("Send", id="send", variant="success"),
            id="input-row",
        )
        yield Horizontal(
            Button("Model", id="model"),
            Button("History", id="history"),
            Button("Stop", id="stop", disabled=True),
            Button("Help", id="help"),
            Button("Copy", id="copy"),
            id="controls",
        )
        yield Footer()

    def render_event(self, event: SessionEvent) -> None:
        self.session.record(event)
        transcript = self.query_one("#transcript", RichLog)
        line = f"{_PREFIX.get(event.kind, '')}{event.text}"
        # What you typed is set apart from replies, so the transcript reads
        # as a conversation rather than an unattributed log.
        transcript.write(Text(line, style="bold cyan") if event.kind == "input" else line)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        button_id = event.button.id
        if button_id == "send":
            self._send()
        elif button_id == "stop":
            self._stop()
        elif button_id and button_id.startswith("mode-"):
            self._handle_slash(f"/route {button_id.removeprefix('mode-')}")
        elif button_id == "copy":
            self._copy_transcript()
        elif button_id in ("model", "history", "help"):
            self._handle_slash(f"/{button_id}")

    def on_input_submitted(self, event: "Input.Submitted") -> None:
        self._send()

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
        self.copy_to_clipboard(text)
        self.render_event(SessionEvent(kind="output", text="Transcript copied to clipboard."))

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
        for worker in self.workers:
            worker.cancel()
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self.query_one("#stop", Button).disabled = not busy

    def _send(self) -> None:
        prompt = self.query_one("#prompt", Input)
        text = prompt.value.strip()
        if not text:
            return
        prompt.value = ""
        self.render_event(SessionEvent(kind="input", text=text))
        if not self._handle_slash(text):
            self._dispatch_text(text)

    def _handle_slash(self, text: str) -> bool:
        """Handles a slash command synchronously on the main thread -- no
        worker needed, these are fast, local operations. Returns True if
        `text` was a recognized slash command (whether or not it also
        triggered a setup handoff), False otherwise, so _send() knows
        whether to fall through to an ordinary (possibly slow) dispatch()
        call in a worker."""
        event = handle_slash_command(self.session, text)
        if event is None:
            return False
        if event.kind == "needs_setup":
            self._exec_after = RELAY_SETUP
            self.exit()
            return True
        self.render_event(event)
        self._sync_mode_indicator()
        return True

    def _dispatch_text(self, text: str) -> None:
        """Launches one dispatch in a background thread. `token` is a
        unique, unguessable object identifying *this specific* dispatch --
        _stop() (Task 4) replaces self._dispatch_token with a new one,
        which is how a cancelled dispatch's late-arriving result is
        recognized and discarded (via `is`, not equality) once it finally
        returns, regardless of whatever Textual's own worker.cancel() does
        or doesn't guarantee about a thread already running Python code."""
        token = object()
        self._dispatch_token = token
        self._set_busy(True)
        self.run_worker(lambda: self._dispatch_in_thread(text, token), thread=True)

    def _dispatch_in_thread(self, text: str, token: object) -> None:
        try:
            result = dispatch(self.session, text)
        except Exception as error:  # a safety net beyond adapters.py's own handling
            result = SessionEvent(kind="error", text=str(error))
        self.call_from_thread(self._finish_dispatch, result, token)

    def _finish_dispatch(self, result: SessionEvent, token: object) -> None:
        # Checked here, on the main thread, rather than in the worker: a
        # Stop or newer dispatch that lands between the worker's check and
        # this call would otherwise still let a stale result through.
        if token is not self._dispatch_token:
            return
        self._set_busy(False)
        self.render_event(result)


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
