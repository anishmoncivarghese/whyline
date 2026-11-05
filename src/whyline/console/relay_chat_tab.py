"""The Chat tab: ask a read-only agent about the running relay.

Independent of the relay itself: it never touches `#stop`, the relay process
or the relay input. Its own Stop sets only the cancel event of the question
it started.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from rich.style import Style
from rich.text import Span, Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual import events
from textual.strip import Strip
from textual.message import Message
from textual.widgets import Button, RichLog, Select, Static, TextArea

from whyline.console.tui import _SPINNER
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


_INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`\n]+)`")
_HEADING = re.compile(r"#{1,3} ")


def render_answer(repo: Path, text: str) -> Text:
    """An agent answer with light markdown styled and repo paths as links.

    Handles **bold**, `code`, `#`..`###` headings and `-`/`*` bullets; markers
    that do not pair up stay as typed.
    """
    plain: list[str] = []
    spans: list[tuple[int, int, Style]] = []
    size = 0

    def emit(piece: str, style: Style | None = None) -> None:
        nonlocal size
        plain.append(piece)
        if style is not None and piece:
            spans.append((size, size + len(piece), style))
        size += len(piece)

    for number, line in enumerate(text.split("\n")):
        if number:
            emit("\n")
        start = size
        heading = _HEADING.match(line)
        if heading:
            line = line[heading.end():]
        elif line.startswith(("- ", "* ")):
            emit("• ")
            line = line[2:]
        last = 0
        for match in _INLINE.finditer(line):
            emit(line[last:match.span()[0]])
            if match.group(1) is not None:
                emit(match.group(1), Style(bold=True))
            else:
                emit(match.group(2), Style(color="cyan"))
            last = match.end()
        emit(line[last:])
        if heading:
            spans.append((start, size, Style(bold=True)))
    shown = "".join(plain)
    out = link_paths(repo, shown)
    for begin, end, style in spans:
        out.spans.insert(0, Span(begin, end, style))
    return out


MIN_ROWS = 3
MAX_ROWS = 6


class ChatQuestion(TextArea):
    """The question box: wraps, grows from 3 to 6 rows, Enter sends."""

    class Submitted(Message):
        pass

    def __init__(self, **kwargs) -> None:
        super().__init__(soft_wrap=True, show_line_numbers=False, **kwargs)
        # Textual 2.x TextArea has no placeholder option, so draw it here.
        self.placeholder = "Ask about this relay"

    def render_line(self, y: int) -> Strip:
        line = super().render_line(y)
        if y == 0 and not self.text:
            width = self.scrollable_content_region.width
            hint = Text(self.placeholder, style="dim")
            hint.truncate(width, pad=True)
            return Strip(hint.render(self.app.console), width)
        return line

    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, text: str) -> None:
        self.text = text

    def on_mount(self) -> None:
        self._fit()

    def on_resize(self) -> None:
        self._fit()

    def on_text_area_changed(self) -> None:
        self._fit()

    def _fit(self) -> None:
        try:
            lines = self.wrapped_document.height
        except Exception:
            lines = 1
        rows = max(MIN_ROWS, min(MAX_ROWS, lines))
        self.styles.height = rows + 2  # plus the border

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            self.post_message(self.Submitted())


class RelayChatPanel(Vertical):
    def __init__(self, repo: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._repo = Path(repo)
        self._cancel: threading.Event | None = None
        self._run_id = self._current_run_id()
        self._shares_quota = False
        self._state = "none"
        self._clock = time.monotonic  # tests replace this
        self._timer = None
        self._started = 0.0
        self._frame = 0
        self._agent = "agent"
        self._stopping = False

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
        yield Static("", id="chat-working", markup=False)
        yield ChatQuestion(id="chat-input")
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
        working = self.query_one("#chat-working", Static)
        working.display = False
        working.styles.height = 1
        self.query_one("#chat-quick").styles.height = 1
        self.query_one("#chat-actions").styles.height = 1
        self.query_one("#chat-input", ChatQuestion).styles.border = ("round", "grey")
        # On a short pane the box yields, so the log and buttons stay on screen.
        self.query_one("#chat-input").styles.max_height = "40%"
        # Compact rows: the pane is short, so both button rows are one line high.
        for button in self.query("#chat-quick Button, #chat-actions Button"):
            button.styles.height = 1
            button.styles.min_width = 0
            button.styles.border = ("none", "black")
        log = self.query_one("#chat-log", RichLog)
        log.styles.height = "1fr"
        log.styles.min_height = 1  # a log with no rows never shows what it was given
        # The question box takes rows from the log; the agent menu is one line too.
        picker = self.query_one("#chat-agent", Select)
        picker.styles.height = 1
        picker.query_one("SelectCurrent").styles.height = 1
        picker.query_one("SelectCurrent").styles.border = ("none", "black")
        picker.query_one("SelectCurrent").styles.padding = (0, 1)
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
            log.write(Text("Agent: ").append_text(render_answer(self._repo, text)))

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

    def on_chat_question_submitted(self, event: ChatQuestion.Submitted) -> None:
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
                self._stopping = True
                self._tick()
        else:
            self._clear()

    def _send(self, question: str | None = None) -> None:
        box = self.query_one("#chat-input", ChatQuestion)
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
        self._start_working()
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
            self._stop_working()
        self.query_one("#chat-stop", Button).display = False
        self._refresh_header()

    def _start_working(self) -> None:
        try:
            self._agent = agent_choice.pick(self._repo).agent or "agent"
        except Exception:
            self._agent = "agent"
        self._started = self._clock()
        self._frame = 0
        self._stopping = False
        self.query_one("#chat-working", Static).display = True
        self._tick(advance=False)
        if self._timer is not None:
            self._timer.pause()
        self._timer = self.set_interval(0.2, self._tick)

    def _stop_working(self) -> None:
        if self._timer is not None:
            self._timer.pause()  # pause, not stop: the never-disturbs guard bans .stop()
            self._timer = None
        self._stopping = False
        self.query_one("#chat-working", Static).display = False

    def _tick(self, advance: bool = True) -> None:
        if self._cancel is None:
            return
        if advance:
            self._frame = (self._frame + 1) % len(_SPINNER)
        if self._stopping:
            text = "Stopping…"
        else:
            secs = int(self._clock() - self._started)
            text = f"{_SPINNER[self._frame]} {self._agent} is working on your question… {secs}s"
        self.query_one("#chat-working", Static).update(text)

    def _clear(self) -> None:
        if self._cancel is not None:
            return
        try:
            history.clear(self._repo, self._run_id)
        except ValueError:
            pass
        self.query_one("#chat-log", RichLog).clear()
