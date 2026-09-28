"""whyline console's mouse-enabled TUI, built on Textual.

Import-guarded exactly like editor.py guards prompt_toolkit, so the rest
of the console package stays importable and testable without the [ui]
extra installed. Reuses ConsoleSession/SessionEvent/adapters.py and
repl.py's dispatch() completely unchanged -- this module is a rendering
layer, not a second implementation of the console's logic.
"""

from __future__ import annotations

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

from whyline.console.session import ConsoleSession, SessionEvent

_PREFIX = {"error": "⚠ ", "pause": "⏸ "}


class TuiUnavailable(RuntimeError):
    """textual is not installed."""


class WhylineConsoleApp(App):
    """The mouse-enabled console. Every widget dispatches through the same
    ConsoleSession/dispatch() path the keyboard REPL already uses."""

    def __init__(self, *, root: Path) -> None:
        super().__init__()
        self.session = ConsoleSession(root=root)

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


def launch(root: Path) -> None:
    if not TUI_AVAILABLE:
        raise TuiUnavailable(
            "The mouse TUI needs textual. Run: pip install 'whyline[ui]'"
        )
    WhylineConsoleApp(root=root).run()
