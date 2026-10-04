"""The Attach menu and the tray of pending attachments, shared by Chat and
the Brainstorm and Plan forms (console attachments spec, section 3)."""
from __future__ import annotations

try:
    from textual.app import ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.message import Message
    from textual.screen import ModalScreen
    from textual.widgets import Button, Label, Static
except ImportError:
    ComposeResult = None
    Horizontal = Vertical = object
    Message = ModalScreen = object
    Button = Label = Static = None

from whyline.console import mac_input

_STATUS = {
    "native": "✓ {agent} sees it",
    "path": "✓ {agent} reads it",
    "path-unverified": "⚠ {agent} gets the path only",
}


def status_text(agent: str, delivery: str) -> str:
    return _STATUS.get(delivery, _STATUS["path-unverified"]).format(agent=agent)


def needs_warning(delivery: str) -> bool:
    return delivery == "path-unverified"


def size_text(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


class AttachMenuScreen(ModalScreen):
    DEFAULT_CSS = """
    AttachMenuScreen { align: center middle; }
    AttachMenuScreen > Vertical { width: 50; height: auto; padding: 1 2;
        border: thick $accent; background: $surface; }
    AttachMenuScreen Button { width: 100%; margin-top: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Attach"),
            Button("Choose files…", id="attach-pick", variant="primary",
                   disabled=not mac_input.available()),
            Button("Paste screenshot", id="attach-paste", disabled=not mac_input.available()),
            Button("Cancel", id="attach-cancel"),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        self.dismiss({"attach-pick": "pick", "attach-paste": "paste"}.get(event.button.id))


class AttachmentTray(Horizontal):
    """One line per pending attachment: name, size, status, remove."""

    DEFAULT_CSS = """
    AttachmentTray { height: auto; display: none; }
    AttachmentTray Static { width: auto; padding: 1 1 0 0; }
    AttachmentTray Button { min-width: 3; width: auto; margin-right: 2; }
    """

    if Message is not object:
        class Removed(Message):
            def __init__(self, attachment_id: str) -> None:
                super().__init__()
                self.attachment_id = attachment_id
    else:
        class Removed:
            def __init__(self, attachment_id: str) -> None:
                self.attachment_id = attachment_id

    def show(self, items, statuses: dict[str, str]) -> None:
        self.remove_children()
        for child in list(self.children):
            self._nodes._remove(child)
        for item in items:
            extra = f"  ⚠ {item.warning}" if item.warning else ""
            self.mount(Static(f"📎 {item.name}  {size_text(item.size)}  {statuses.get(item.id, '')}{extra}"))
            self.mount(Button("✕", id=f"remove-{item.id}"))
        self.display = bool(items)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        if event.button.id and event.button.id.startswith("remove-"):
            event.stop()
            self.post_message(self.Removed(event.button.id.removeprefix("remove-")))
