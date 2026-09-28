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
    from textual.widgets import Button, Footer, Header, RichLog, TextArea

    TUI_AVAILABLE = True
except ImportError:
    App = object  # placeholder base so WhylineConsoleApp can still be defined
    ComposeResult = None
    Horizontal = None
    Button = Footer = Header = RichLog = TextArea = None
    TUI_AVAILABLE = False

from whyline.console.repl import dispatch, handle_slash_command
from whyline.console.session import ConsoleSession, SessionEvent

_PREFIX = {"error": "⚠ ", "pause": "⏸ "}


class TuiUnavailable(RuntimeError):
    """textual is not installed."""


class WhylineConsoleApp(App):
    """The mouse-enabled console. Every widget dispatches through the same
    ConsoleSession/dispatch() path the keyboard REPL already uses."""

    # Textual's default Button width is 16 columns; six of them (Send,
    # Model, Route, History, Stop, Help) at that width total 96 columns,
    # wider than an 80-column terminal -- the standard default, and what
    # Textual's own test harness uses. Without this, "Stop" and "Help" are
    # genuinely off-screen, not just visually cramped: real mouse clicks
    # (and Pilot.click in tests) can't reach them at all. Sizing buttons to
    # their label instead of a fixed width keeps the whole row within 80
    # columns comfortably (measured: ~41 columns total for these six).
    DEFAULT_CSS = """
    Horizontal > Button { min-width: 6; width: auto; }
    """

    def __init__(self, *, root: Path) -> None:
        super().__init__()
        self.session = ConsoleSession(root=root)
        self._dispatch_token: object | None = None
        self._exec_after: tuple[str, list[str]] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="transcript")
        yield TextArea(id="prompt")
        yield Horizontal(
            Button("Send", id="send"),
            Button("Model", id="model"),
            Button("Route", id="route"),
            Button("History", id="history"),
            Button("Stop", id="stop"),
            Button("Help", id="help"),
        )
        yield Footer()

    def render_event(self, event: SessionEvent) -> None:
        self.session.record(event)
        transcript = self.query_one("#transcript", RichLog)
        transcript.write(f"{_PREFIX.get(event.kind, '')}{event.text}")

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        button_id = event.button.id
        if button_id == "send":
            self._send()
        elif button_id == "stop":
            self._stop()
        elif button_id == "route":
            self._handle_slash("/route relay")
        elif button_id in ("model", "history", "help"):
            self._handle_slash(f"/{button_id}")

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

    def _send(self) -> None:
        prompt = self.query_one("#prompt", TextArea)
        text = prompt.text.strip()
        if not text:
            return
        prompt.text = ""
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
            self._exec_after = ("whyline-relay", ["whyline-relay", "setup"])
            self.exit()
            return True
        self.render_event(event)
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
        self.run_worker(lambda: self._dispatch_in_thread(text, token), thread=True)

    def _dispatch_in_thread(self, text: str, token: object) -> None:
        try:
            result = dispatch(self.session, text)
        except Exception as error:  # a safety net beyond adapters.py's own handling
            result = SessionEvent(kind="error", text=str(error))
        if token is self._dispatch_token:
            self.call_from_thread(self.render_event, result)


def _exec(binary: str, argv: list[str]) -> None:
    os.execvp(binary, argv)


def launch(root: Path, *, exec_fn=None) -> None:
    if not TUI_AVAILABLE:
        raise TuiUnavailable(
            "The mouse TUI needs textual. Run: pip install 'whyline[ui]'"
        )
    if exec_fn is None:
        exec_fn = _exec
    app = WhylineConsoleApp(root=root)
    app.run()
    if app._exec_after is not None:
        binary, argv = app._exec_after
        exec_fn(binary, argv)
