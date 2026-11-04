"""The Chat tab: ask a read-only agent about the running relay.

Independent of the relay itself: it never touches `#stop`, the relay process
or the relay input. Its own Stop sets only the cancel event of the question
it started.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, RichLog, Select, Static

from whyline.relaychat import agent_choice, ask, history, settings, snapshot

AUTO = ""

QUICK = {
    "chat-q-doing": "What's it doing?",
    "chat-q-stopped": "Why did it stop?",
    "chat-q-plan": "Plan progress",
    "chat-q-changed": "What's changed?",
}
STOPPED_STATES = ("paused", "stopped", "failed")
_PATH = re.compile(r"[\w./-]+(?::\d+)?")


def link_paths(repo: Path, text: str) -> Text:
    """Text with `path` and `path:line` references to repo files as links."""
    out = Text(text)
    root = Path(repo).resolve()
    for match in _PATH.finditer(text):
        token = match.group(0).rstrip(".,")
        name, _, number = token.partition(":")
        if not name or name.startswith("/") or not (number or "/" in name or "." in name):
            continue
        try:
            target = (root / name).resolve()
            target.relative_to(root)
            if not target.is_file():
                continue
        except (OSError, ValueError):
            continue
        line = int(number) if number else 1
        action = f"app.open_chat_file({str(target)!r}, {line})"
        begin = match.span()[0]
        out.stylize(Style(meta={"@click": action}, underline=True, color="cyan"),
                    begin, begin + len(token))
    return out


class RelayChatPanel(Vertical):
    def __init__(self, repo: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._repo = Path(repo)
        self._cancel: threading.Event | None = None
        self._run_id = self._current_run_id()
        self._shares_quota = False
        self._state = "none"

    def _current_run_id(self) -> str | None:
        try:
            return snapshot.build(self._repo, max_chars=1).run_id
        except Exception:
            return None

    def compose(self) -> ComposeResult:
        yield Static("", id="chat-header", markup=False)
        yield Select(self._options(), value=self._selected(), allow_blank=False,
                     id="chat-agent")
        yield RichLog(id="chat-log", wrap=True, markup=False)
        yield Input(placeholder="Ask about this relay", id="chat-input")
        yield Horizontal(
            *[Button(label, id=bid, classes="chat-quick") for bid, label in QUICK.items()],
            id="chat-quick",
        )
        yield Horizontal(
            Button("Send", id="chat-send"),
            Button("Stop", id="chat-stop"),
            Button("Clear", id="chat-clear"),
            id="chat-actions",
        )

    def on_mount(self) -> None:
        self.query_one("#chat-stop", Button).display = False
        self.query_one("#chat-quick").styles.height = 1
        self.query_one("#chat-actions").styles.height = 1
        chat_input = self.query_one("#chat-input", Input)
        chat_input.styles.height = 1
        chat_input.styles.border = ("none", "black")
        # Compact rows: the pane is short, so both button rows are one line high.
        for button in self.query("#chat-quick Button, #chat-actions Button"):
            button.styles.height = 1
            button.styles.min_width = 0
            button.styles.border = ("none", "black")
        self.query_one("#chat-log", RichLog).styles.height = "1fr"
        self._refresh_header()
        self._load_log()

    def _options(self) -> list[tuple[str, str]]:
        return [("auto", AUTO), *[(name, name) for name in agent_choice.choices(self._repo)]]

    def _selected(self) -> str:
        saved = settings.load(self._repo).agent
        return saved if saved and saved in agent_choice.choices(self._repo) else AUTO

    def _refresh_header(self) -> None:
        pick = agent_choice.pick(self._repo)
        self._shares_quota = pick.shares_quota
        name = pick.agent or "none"
        text = f"Ask about this relay · agent {name} ▾ · read-only"
        if pick.shares_quota:
            text += " · shares quota with the relay"
        self.query_one("#chat-header", Static).update(text)
        try:
            self._state = getattr(snapshot.build(self._repo, max_chars=1), "state", "none")
        except Exception:
            self._state = "none"
        self.query_one("#chat-q-stopped", Button).display = self._state in STOPPED_STATES

    def _load_log(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        for item in history.load(self._repo, self._run_id):
            self._write(item.get("role"), str(item.get("text", "")))

    def _write(self, role: object, text: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        if role == "user":
            log.write(Text(f"You: {text}", style="bold cyan"))
        else:
            log.write(link_paths(self._repo, f"Agent: {text}"))

    @property
    def asking(self) -> bool:
        return self._cancel is not None

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "chat-agent":
            return
        value = event.value
        chosen = value if isinstance(value, str) and value else None
        if chosen != settings.load(self._repo).agent:
            settings.save(self._repo, agent=chosen)
        self._refresh_header()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "chat-input":
            return
        self._send()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id in QUICK:
            self._send(QUICK[button_id])
            return
        if button_id not in ("chat-send", "chat-stop", "chat-clear"):
            return
        if button_id == "chat-send":
            self._send()
        elif button_id == "chat-stop":
            if self._cancel is not None:
                self._cancel.set()
        else:
            self._clear()

    def _send(self, question: str | None = None) -> None:
        box = self.query_one("#chat-input", Input)
        typed = question is None
        question = box.value.strip() if typed else question
        if not question or self._cancel is not None:
            return
        if typed:
            box.value = ""
        self._write("user", question)
        cancel = threading.Event()
        self._cancel = cancel
        self.query_one("#chat-stop", Button).display = True
        self.run_worker(lambda: self._ask(question, cancel), thread=True, exclusive=False)

    def _ask(self, question: str, cancel: threading.Event) -> None:
        try:
            answer = ask.ask(self._repo, question, cancel_event=cancel)
            text = answer.text
        except Exception as caught:
            text = f"Chat could not answer. {caught}"
        try:
            self.app.call_from_thread(self._answered, text, cancel)
        except Exception:
            pass  # the console closed while the question ran

    def _answered(self, text: str, cancel: threading.Event) -> None:
        self._write("assistant", text)
        if self._cancel is cancel:
            self._cancel = None
        self.query_one("#chat-stop", Button).display = False
        self._refresh_header()

    def _clear(self) -> None:
        if self._cancel is not None:
            return
        try:
            history.clear(self._repo, self._run_id)
        except ValueError:
            pass
        self.query_one("#chat-log", RichLog).clear()
