"""Workflows mode screens: the Library of workflows and the New dialog."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from whyline.ledgerops import redact
from whyline.workflows import service, state

_COLUMNS = ("Name", "Kind", "Status", "When", "Next", "Last")


def _cell(value: object) -> Text:
    """Render values literally rather than as Rich markup."""
    return Text("" if value is None else str(value), no_wrap=True, end="")


def cap_text(n: int) -> str:
    return "off" if n == 0 else str(n)


def parse_cap(text: str) -> int:
    value = text.strip().lower()
    if value in ("", "off"):
        return 0
    if not value.isdigit():
        raise ValueError("the daily agent cap is a whole number, or off")
    return int(value)


class LibraryScreen(ModalScreen):
    """Every workflow with the actions that apply to the selected one."""

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    LibraryScreen { align: center middle; }
    LibraryScreen > Vertical {
        width: 110; max-width: 100%; height: 100%; max-height: 100%;
        padding: 0 1; border: thick $accent; background: $surface;
    }
    LibraryScreen #wl-table { height: 1fr; }
    LibraryScreen #wl-detail, LibraryScreen #wl-status { height: auto; }
    LibraryScreen .wl-row { height: 3; }
    LibraryScreen #wl-cap { width: 12; }
    LibraryScreen .wl-label { padding: 1 1 0 0; width: auto; }
    """

    def __init__(self, root: Path | None, select: str | None = None) -> None:
        super().__init__()
        self._root = root
        self._select = select
        self._rows: list[service.Row] = []

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Workflows", id="wl-title"),
            DataTable(id="wl-table", cursor_type="row"),
            Static("", id="wl-detail"),
            Horizontal(
                Button("Run now", id="wl-run"),
                Button("Pause", id="wl-toggle"),
                Button("Review & accept", id="wl-accept"),
                Button("Edit", id="wl-edit", disabled=True),
                Button("Runs", id="wl-runs"),
                classes="wl-row",
            ),
            Horizontal(
                Label("Daily agent cap", classes="wl-label"),
                Input(cap_text(service.get_cap()), id="wl-cap"),
                Button("Save cap", id="wl-cap-save"),
                Button("Close", id="wl-close"),
                classes="wl-row",
            ),
            Static("", id="wl-status"),
        )

    def on_mount(self) -> None:
        table = self.query_one("#wl-table", DataTable)
        table.add_columns(*_COLUMNS)
        self._reload(self._select)

    def _reload(self, keep: str | None = None) -> None:
        table = self.query_one("#wl-table", DataTable)
        if keep is None:
            keep = self._current_name()
        table.clear()
        try:
            self._rows = service.rows(self._root)
        except Exception as error:
            self._rows = []
            self._say(str(error))
        for row in self._rows:
            table.add_row(*(_cell(v) for v in (row.name, row.kind, row.status, row.trigger,
                                               row.next, row.last)), key=row.name)
        if not self._rows:
            self._say(service.NO_WORKFLOWS)
        names = [r.name for r in self._rows]
        if keep in names:
            table.move_cursor(row=names.index(keep))
        self._sync()

    def _current(self) -> service.Row | None:
        table = self.query_one("#wl-table", DataTable)
        if not self._rows or not 0 <= table.cursor_row < len(self._rows):
            return None
        return self._rows[table.cursor_row]

    def _current_name(self) -> str | None:
        row = self._current()
        return row.name if row else None

    def _say(self, text: str) -> None:
        self.query_one("#wl-status", Static).update(Text(text))

    def _sync(self) -> None:
        row = self._current()
        toggle = self.query_one("#wl-toggle", Button)
        toggle.label = "Resume" if row and row.status == state.PAUSED else "Pause"
        for button_id in ("wl-run", "wl-toggle", "wl-accept", "wl-runs"):
            self.query_one(f"#{button_id}", Button).disabled = row is None
        detail = ""
        if row is not None and row.status == state.NEEDS_REVIEW and not row.next:
            detail = f"{row.name}: {row.trigger}"
        self.query_one("#wl-detail", Static).update(Text(detail))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        self._sync()

    def action_close(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if event.input.id == "wl-cap":
            self._save_cap()

    def _save_cap(self) -> None:
        box = self.query_one("#wl-cap", Input)
        try:
            service.set_cap(parse_cap(box.value))
        except ValueError as error:
            self._say(str(error))
            return
        box.value = cap_text(service.get_cap())
        self._say(f"Daily agent cap: {box.value}.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id
        if button_id == "wl-close":
            self.dismiss(None)
        elif button_id == "wl-cap-save":
            self._save_cap()
        elif button_id == "wl-run":
            self._run()
        elif button_id == "wl-toggle":
            self._toggle()
        elif button_id == "wl-accept":
            self._review()
        elif button_id == "wl-runs":
            name = self._current_name()
            if name is not None:
                self.app.push_screen(RunsScreen(name, self._root))

    def _run(self) -> None:
        name = self._current_name()
        if name is None:
            return
        try:
            run_id = service.run_now(name, {}, source="console", repo_root=self._root)
        except Exception as error:
            self._say(str(error))
            return
        self._say(f"Started {name} (run {run_id}).")
        self._reload()

    def _toggle(self) -> None:
        row = self._current()
        if row is None:
            return
        try:
            if row.status == state.PAUSED:
                service.resume(row.name, self._root)
                self._say(f"Resumed {row.name}.")
            else:
                service.pause(row.name, self._root)
                self._say(f"Paused {row.name}.")
        except Exception as error:
            self._say(str(error))
        self._reload()

    def _review(self) -> None:
        from whyline.console.tui import ConfirmScreen

        name = self._current_name()
        if name is None:
            return
        try:
            lines = service.review(name, self._root)
        except Exception as error:
            self._say(str(error))
            return
        message = f"Accept {name}?\n" + "\n".join(lines or ["Nothing has changed."])

        def decided(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                service.accept(name, self._root)
            except Exception as error:
                self._say(str(error))
                return
            self._say(f"Accepted {name}.")
            self._reload()

        self.app.push_screen(ConfirmScreen(message, "Accept"), decided)


class NewWorkflowScreen(ModalScreen):
    """Asks for a name and scope, creates the workflow, and dismisses with its name."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    NewWorkflowScreen { align: center middle; }
    NewWorkflowScreen > Vertical {
        width: 70; height: auto; padding: 1 2;
        border: thick $accent; background: $surface;
    }
    NewWorkflowScreen Horizontal { height: auto; margin-top: 1; }
    NewWorkflowScreen Button { margin-right: 2; }
    """

    def __init__(self, root: Path | None) -> None:
        super().__init__()
        self._root = root

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("New workflow"),
            Input(placeholder="name, e.g. morning-brief", id="wn-name"),
            Select([("Personal (this Mac)", "personal"), ("Repo (this checkout)", "repo")],
                   allow_blank=False, value="personal", id="wn-scope"),
            Static("", id="wn-error"),
            Horizontal(
                Button("Create", id="wn-create", variant="primary"),
                Button("Cancel", id="wn-cancel"),
            ),
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "wn-create":
            self._create()
        else:
            self.dismiss(None)

    def _create(self) -> None:
        name = self.query_one("#wn-name", Input).value.strip()
        kind = str(self.query_one("#wn-scope", Select).value)
        try:
            service.new(name, kind, self._root)
        except Exception as error:
            self.query_one("#wn-error", Static).update(Text(str(error)))
            return
        self.dismiss(name)


_RUN_COLUMNS = ("Workflow", "Source", "State", "Started", "Duration")
_STEP_COLUMNS = ("Step", "State", "Provider", "Duration", "Reason")
_OPEN = ("queued", "running", "waiting")
_REDO = ("failed", "cancelled")
_UNKNOWN = "unknown_outcome"
_RUN_LIMIT = 200


def _moment(stamp: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        return None


def _duration(start: str | None, end: str | None) -> str:
    began, finished = _moment(start), _moment(end)
    if began is None or finished is None:
        return ""
    seconds = max(0, int((finished - began).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _run_name(row) -> str:
    try:
        name = json.loads(row["definition_json"] or "{}").get("name")
    except ValueError:
        name = None
    return str(name or row["workflow_id"])


def _read_output(path: str | None) -> str:
    """A step's saved output, redacted again so a secret never reaches the screen."""
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8")
        text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except (OSError, ValueError):
        return ""
    return redact(text)


class RunsScreen(ModalScreen):
    """Runs newest first, the steps of the selected run and its actions."""

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    RunsScreen { align: center middle; }
    RunsScreen > Vertical {
        width: 110; max-width: 100%; height: 100%; max-height: 100%;
        padding: 0 1; border: thick $accent; background: $surface;
    }
    RunsScreen #wr-runs, RunsScreen #wr-steps { height: 1fr; }
    RunsScreen #wr-scroll { height: 1fr; border: round $primary; }
    RunsScreen #wr-status { height: auto; }
    RunsScreen #wr-buttons { height: 3; }
    """

    def __init__(self, workflow: str | None = None, root: Path | None = None) -> None:
        super().__init__()
        self._workflow = workflow
        self._root = root
        self._runs: list = []
        self._detail: service.RunDetail | None = None
        self._busy = False

    def compose(self) -> ComposeResult:
        title = "Runs" if self._workflow is None else f"Runs of {self._workflow}"
        yield Vertical(
            Label(title, id="wr-title"),
            DataTable(id="wr-runs", cursor_type="row"),
            DataTable(id="wr-steps", cursor_type="row"),
            VerticalScroll(Static("", id="wr-output"), id="wr-scroll"),
            Static("", id="wr-status"),
            Horizontal(
                Button("Cancel", id="wr-cancel"),
                Button("Approve", id="wr-approve", variant="primary"),
                Button("Deny", id="wr-deny"),
                Button("Mark done", id="wr-done"),
                Button("Mark failed", id="wr-failed"),
                Button("Retry step", id="wr-retry-step"),
                Button("Retry run", id="wr-retry-run"),
                Button("Close", id="wr-close"),
                id="wr-buttons",
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#wr-runs", DataTable).add_columns(*_RUN_COLUMNS)
        self.query_one("#wr-steps", DataTable).add_columns(*_STEP_COLUMNS)
        self._reload()

    def _say(self, text: str) -> None:
        self.query_one("#wr-status", Static).update(Text(text))

    def _current_id(self) -> int | None:
        table = self.query_one("#wr-runs", DataTable)
        if not self._runs or not 0 <= table.cursor_row < len(self._runs):
            return None
        return self._runs[table.cursor_row]["id"]

    def _reload(self, keep: int | None = None) -> None:
        table = self.query_one("#wr-runs", DataTable)
        if keep is None:
            keep = self._current_id()
        table.clear()
        try:
            if self._workflow is None:
                self._runs = state.connect().execute(
                    "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (_RUN_LIMIT,)).fetchall()
            else:
                self._runs = service.runs(self._workflow, self._root, _RUN_LIMIT)
        except Exception as error:
            self._runs = []
            self._say(str(error))
        for run in self._runs:
            started = (run["started"] or run["created"] or "")[:16].replace("T", " ")
            table.add_row(*(_cell(v) for v in (
                _run_name(run), run["source"], run["status"], started,
                _duration(run["started"], run["ended"]))), key=str(run["id"]))
        if not self._runs:
            self._say("No runs yet.")
        ids = [r["id"] for r in self._runs]
        if keep in ids:
            table.move_cursor(row=ids.index(keep))
        self._show_run()

    def _show_run(self) -> None:
        steps = self.query_one("#wr-steps", DataTable)
        steps.clear()
        run_id = self._current_id()
        self._detail = None
        if run_id is not None:
            try:
                self._detail = service.run_detail(run_id)
            except Exception as error:
                self._say(str(error))
        detail = self._detail
        if detail is not None:
            for step in detail.steps:
                steps.add_row(*(_cell(v) for v in (
                    step["step_id"], step["status"], step["provider"],
                    _duration(step["started"], step["ended"]), step["reason"])),
                    key=step["step_id"])
        self._show_output()
        self._sync()

    def _current_step(self):
        steps = self.query_one("#wr-steps", DataTable)
        if self._detail is None or not 0 <= steps.cursor_row < len(self._detail.steps):
            return None
        return self._detail.steps[steps.cursor_row]

    def _show_output(self) -> None:
        step = self._current_step()
        text = _read_output(step["output_path"]) if step is not None else ""
        self.query_one("#wr-output", Static).update(Text(text or "(no output)"))

    def _pending(self):
        if self._detail is None or self._detail.run["status"] != "waiting":
            return None
        pending = [a for a in self._detail.approvals if a["status"] == "pending"]
        return pending[-1] if pending else None

    def _sync(self) -> None:
        status = self._detail.run["status"] if self._detail is not None else ""
        shown = {
            "wr-cancel": status in _OPEN,
            "wr-approve": self._pending() is not None,
            "wr-deny": self._pending() is not None,
            "wr-done": status == _UNKNOWN,
            "wr-failed": status == _UNKNOWN,
            "wr-retry-step": status == _UNKNOWN,
            "wr-retry-run": status in _REDO,
        }
        for button_id, show in shown.items():
            self.query_one(f"#{button_id}", Button).display = show

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        if event.data_table.id == "wr-runs":
            self._show_run()
        else:
            self._show_output()

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id
        run_id = self._current_id()
        if button_id == "wr-close":
            self.dismiss(None)
            return
        if run_id is None or self._busy:
            return
        pending = self._pending()
        actions = {
            "wr-cancel": ("Cancelled", lambda: service.cancel(run_id)),
            "wr-done": ("Marked done", lambda: service.resolve(run_id, "done")),
            "wr-failed": ("Marked failed", lambda: service.resolve(run_id, "failed")),
            "wr-retry-step": ("Retried the step", lambda: service.resolve(run_id, "retry")),
            "wr-retry-run": ("Retried", lambda: service.retry(run_id)),
        }
        if pending is not None:
            actions["wr-approve"] = ("Approval", lambda: service.decide(
                pending["id"], pending["nonce"], "approve", "console"))
            actions["wr-deny"] = ("Approval", lambda: service.decide(
                pending["id"], pending["nonce"], "deny", "console"))
        if button_id in actions:
            self._act(run_id, *actions[button_id])

    def _act(self, run_id: int, label: str, call) -> None:
        self._busy = True
        self._say(f"{label}...")

        def work() -> None:
            try:
                result = f"{label}: {call()}"
            except Exception as error:
                result = str(error)
            self.app.call_from_thread(self._done, run_id, result)

        self.run_worker(work, thread=True, group="wr-action")

    def _done(self, run_id: int, result: str) -> None:
        self._busy = False
        self._reload(run_id)
        self._say(result)
