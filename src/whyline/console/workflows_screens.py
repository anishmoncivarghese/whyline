"""Workflows mode screens: the Library of workflows and the New dialog."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.coordinate import Coordinate
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from whyline import account
from whyline.ledgerops import redact
from whyline.workflows import definitions, service, state
from whyline.agents.definitions import CLIS
from whyline.workflows.steps import STEP_TYPES

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
                Button("Edit", id="wl-edit"),
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
        for button_id in ("wl-run", "wl-toggle", "wl-accept", "wl-edit", "wl-runs"):
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
        elif button_id == "wl-edit":
            self._edit()
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

    def _edit(self) -> None:
        name = self._current_name()
        if name is None:
            return
        try:
            workflow = service.load(name, self._root)
        except Exception as error:
            self._say(str(error))
            return
        self.app.push_screen(BuilderScreen(workflow), lambda _result: self._reload())

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


_STEP_DEFAULTS = {
    "set": {"values": {}},
    "condition": {"left": "", "op": "eq", "right": ""},
    "switch": {"value": ""},
    "wait": {"minutes": 1},
    "approval": {"message": ""},
    "agent": {"runner": STEP_TYPES["agent"].field("runner").choices[0], "instructions": ""},
    "deliver": {"to": "file", "text": ""},
}


def _one_line(step: definitions.Step) -> str:
    text = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in step.fields.items())
    return text if len(text) <= 40 else text[:39] + "…"


def _step_of(message: str) -> str | None:
    """The step id a validation message names, if any."""
    if message.startswith('step "'):
        return message[6:].split('"', 1)[0]
    return None


class DryRunScreen(ModalScreen):
    """Ask for the declared inputs, then show the lines of a dry run."""

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    DryRunScreen { align: center middle; }
    DryRunScreen > Vertical {
        width: 100%; height: 100%; padding: 0 1; border: round $accent; background: $surface;
    }
    DryRunScreen #wd-scroll { height: 1fr; }
    DryRunScreen #wd-inputs, DryRunScreen #wd-output { height: auto; }
    DryRunScreen .wd-row { height: 3; }
    """

    def __init__(self, workflow: definitions.Workflow) -> None:
        super().__init__()
        self._workflow = workflow

    def compose(self) -> ComposeResult:
        fields: list = []
        for spec in self._workflow.inputs:
            fields.append(Label(f"{spec.name} ({spec.type})"))
            fields.append(Input("" if spec.default is None else str(spec.default),
                                id=f"wd-in-{spec.name}"))
        if not fields:
            fields.append(Label("No inputs."))
        yield Vertical(
            Label(f"Dry run {self._workflow.label}", id="wd-title"),
            VerticalScroll(Vertical(*fields, id="wd-inputs"), Static("", id="wd-output"),
                           id="wd-scroll"),
            Horizontal(Button("Run", id="wd-run", variant="primary"),
                       Button("Close", id="wd-close"), classes="wd-row"),
        )

    def _values(self) -> dict[str, object]:
        found: dict[str, object] = {}
        for spec in self._workflow.inputs:
            text = self.query_one(f"#wd-in-{spec.name}", Input).value.strip()
            if text:
                found[spec.name] = text
        return found

    def _run(self) -> None:
        w = self._workflow
        try:
            lines = service.dry_run(f"{w.kind}:{w.name}", self._values(),
                                    w.root if w.kind == "repo" else None)
        except Exception as error:
            lines = [str(error)]
        self.query_one("#wd-output", Static).update(Text("\n".join(lines)))

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "wd-run":
            self._run()
        else:
            self.dismiss(None)


class BuilderScreen(ModalScreen):
    """Outline editor: the trigger and steps on the left, the trigger form and inputs on the right."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    BuilderScreen { align: center middle; }
    BuilderScreen > Vertical {
        width: 100%; height: 100%; padding: 0 1; border: round $accent; background: $surface;
    }
    BuilderScreen #wb-main { height: 1fr; }
    BuilderScreen #wb-outline { width: 1fr; height: 100%; }
    BuilderScreen #wb-form { width: 36; height: 100%; padding-left: 1; }
    BuilderScreen #wb-inputs, BuilderScreen #wb-status { height: auto; }
    BuilderScreen #wb-inspector, BuilderScreen #wb-problems { height: auto; }
    BuilderScreen #wb-problems { color: $error; }
    BuilderScreen .wb-case { height: 3; }
    BuilderScreen .wb-case Input { width: 1fr; }
    BuilderScreen .wb-case Button { min-width: 6; }
    BuilderScreen .wb-row { height: 3; }
    BuilderScreen .wb-row Button { min-width: 8; margin-right: 1; }
    """

    def __init__(self, workflow: definitions.Workflow) -> None:
        super().__init__()
        self._workflow = workflow
        self._steps: list[definitions.Step] = list(workflow.steps)
        self._baseline = self._signature(self._trigger_values(workflow.trigger))
        self._problems: dict[str | None, list[str]] = {}
        self._shown: tuple[int, str] | None = None
        self._runners = [a for a in CLIS if a in account.enabled_agents()]
        self._lock = asyncio.Lock()

    @staticmethod
    def _trigger_values(t: definitions.TriggerSpec) -> tuple[str, str, str, str]:
        return (t.kind, t.at, str(t.every_hours) if t.every_hours else "", t.folder)

    def _signature(self, trigger: tuple[str, str, str, str]) -> tuple:
        return (trigger, tuple(self._steps))

    def compose(self) -> ComposeResult:
        t = self._workflow.trigger
        yield Vertical(
            Label(f"Edit {self._workflow.label}", id="wb-title"),
            Horizontal(
                DataTable(id="wb-outline", cursor_type="row"),
                VerticalScroll(
                    Select([(k, k) for k in definitions.TRIGGER_KINDS], allow_blank=False,
                           value=t.kind, id="wb-kind"),
                    Input(t.at, placeholder="at, e.g. 08:00", id="wb-at"),
                    Input(str(t.every_hours) if t.every_hours else "",
                          placeholder="every_hours", id="wb-hours"),
                    Input(t.folder, placeholder="folder", id="wb-folder"),
                    Static("", id="wb-inputs"),
                    Vertical(id="wb-inspector"),
                    Select([(k, k) for k in STEP_TYPES], allow_blank=False,
                           value=next(iter(STEP_TYPES)), id="wb-type"),
                    id="wb-form",
                ),
                id="wb-main",
            ),
            Horizontal(
                Button("Add step", id="wb-add"),
                Button("Move up", id="wb-up"),
                Button("Move down", id="wb-down"),
                Button("Delete", id="wb-delete"),
                Button("Save", id="wb-save", variant="primary"),
                Button("Cancel", id="wb-cancel"),
                classes="wb-row",
            ),
            Horizontal(
                Button("Validate", id="wb-validate"),
                Button("Dry run", id="wb-dryrun"),
                classes="wb-row",
            ),
            Static("", id="wb-status"),
        )

    def on_mount(self) -> None:
        self.query_one("#wb-outline", DataTable).add_columns("ID", "Type", "Summary")
        lines = [f"[[input]] {i.name} ({i.type})" + ("" if i.default is None else f" = {i.default}")
                 for i in self._workflow.inputs]
        self.query_one("#wb-inputs", Static).update(Text("\n".join(lines or ["No inputs."])))
        self._refresh()

    # ---- state ---------------------------------------------------------

    def _form(self) -> tuple[str, str, str, str]:
        return (str(self.query_one("#wb-kind", Select).value),
                self.query_one("#wb-at", Input).value.strip(),
                self.query_one("#wb-hours", Input).value.strip(),
                self.query_one("#wb-folder", Input).value.strip())

    def _trigger(self, strict: bool) -> definitions.TriggerSpec:
        kind, at, hours, folder = self._form()
        if hours and not hours.isdigit():
            if strict:
                raise ValueError("every_hours is a whole number")
            hours = ""
        return definitions.TriggerSpec(
            kind=kind,
            at=at if kind in ("daily", "weekdays") else "",
            every_hours=int(hours) if hours and kind == "every" else 0,
            folder=folder if kind == "folder" else "",
        )

    def _dirty(self) -> bool:
        return self._signature(self._trigger_values(self._trigger(False))) != self._baseline

    def _say(self, text: str) -> None:
        self.query_one("#wb-status", Static).update(Text(text))

    def _refresh(self, row: int | None = None) -> None:
        table = self.query_one("#wb-outline", DataTable)
        row = table.cursor_row if row is None else row
        table.clear()
        when = service.when_text(self._trigger(False))
        table.add_row(*(_cell(v) for v in ("trigger", self.query_one("#wb-kind", Select).value,
                                           when)))
        for step in self._steps:
            table.add_row(*(_cell(v) for v in (step.id, step.type, self._summary(step))))
        table.move_cursor(row=max(0, min(row, len(self._steps))))

    def _summary(self, step: definitions.Step) -> str:
        return ("! " if step.id in self._problems else "") + _one_line(step)

    def _touch(self, index: int) -> None:
        self.query_one("#wb-outline", DataTable).update_cell_at(
            Coordinate(index + 1, 2), _cell(self._summary(self._steps[index])))

    def _selected(self) -> int | None:
        index = self.query_one("#wb-outline", DataTable).cursor_row - 1
        return index if 0 <= index < len(self._steps) else None

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        select_id = event.select.id or ""
        if select_id == "wb-kind":
            self._refresh()
        elif select_id.startswith("wf-"):
            value = event.value
            self._set_field(select_id[3:], None if value is Select.BLANK else value)
        elif select_id.startswith("wc-go-"):
            self._set_case(int(select_id[6:]), "goto", str(event.value))

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        input_id = event.input.id or ""
        if input_id.startswith("wf-"):
            self._type_field(input_id[3:], event.value)
        elif input_id.startswith("wc-eq-"):
            self._set_case(int(input_id[6:]), "equals", event.value)
        else:
            self._refresh()

    async def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        await self._inspect()

    # ---- inspector -----------------------------------------------------

    def _later(self, index: int) -> list[str]:
        return [s.id for s in self._steps[index + 1:]]

    def _field_widgets(self, index: int, step: definitions.Step) -> list:
        widgets: list = []
        for spec in STEP_TYPES[step.type].fields:
            if spec.name == "cases":
                continue
            value = step.fields.get(spec.name)
            note = " (templates allowed)" if spec.templated and spec.kind != "step_ref" else ""
            widgets.append(Label(f"{spec.name}{' *' if spec.required else ''}{note}"))
            widget_id = f"wf-{spec.name}"
            if spec.kind == "step_ref":
                later = self._later(index)
                widgets.append(Select([(i, i) for i in later], prompt="(next step)",
                                      value=value if value in later else Select.BLANK,
                                      id=widget_id))
            elif spec.choices and spec.kind == "str":
                options = self._runners if spec.name == "runner" else list(spec.choices)
                widgets.append(Select([(o, o) for o in options], prompt="(choose)",
                                      value=value if value in options else Select.BLANK,
                                      id=widget_id))
            else:
                widgets.append(Input(self._show_value(spec.kind, value), id=widget_id))
        if step.type == "switch":
            widgets.append(Label("cases"))
            later = self._later(index)
            cases = step.fields.get("cases")
            for n, (key, body) in enumerate(cases.items() if isinstance(cases, dict) else ()):
                body = body if isinstance(body, dict) else {}
                goto = body.get("goto")
                widgets.append(Horizontal(
                    Input(str(body.get("equals", "")), placeholder=f"{key} equals", id=f"wc-eq-{n}"),
                    Select([(i, i) for i in later], prompt="(goto)",
                           value=goto if goto in later else Select.BLANK, id=f"wc-go-{n}"),
                    Button("X", id=f"wc-rm-{n}"), classes="wb-case"))
            widgets.append(Button("Add case", id="wc-add"))
        return widgets

    @staticmethod
    def _show_value(kind: str, value: object) -> str:
        if value is None:
            return ""
        if kind == "table":
            return json.dumps(value, ensure_ascii=False)
        if kind == "list[str]" and isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return str(value)

    async def _inspect(self, force: bool = False) -> None:
        async with self._lock:
            index = self._selected()
            key = None if index is None else (index, self._steps[index].id)
            if key == self._shown and not force:
                return
            self._shown = key
            box = self.query_one("#wb-inspector", Vertical)
            await box.remove_children()
            if index is None:
                return
            step = self._steps[index]
            await box.mount(Static("", id="wb-problems"), Label(f"{step.id} ({step.type})"),
                            *self._field_widgets(index, step))
            self._show_problems()

    def _show_problems(self) -> None:
        index = self._selected()
        found = self.query("#wb-problems")
        if found and index is not None:
            found.first(Static).update(Text("\n".join(self._problems.get(self._steps[index].id, []))))

    def _set_field(self, name: str, value: object) -> None:
        index = self._selected()
        if index is None:
            return
        step = self._steps[index]
        fields = dict(step.fields)
        if value is None:
            fields.pop(name, None)
        else:
            fields[name] = value
        if fields == dict(step.fields):
            return
        self._steps[index] = definitions.Step(step.id, step.type, fields)
        self._touch(index)

    def _type_field(self, name: str, text: str) -> None:
        index = self._selected()
        spec = STEP_TYPES[self._steps[index].type].field(name) if index is not None else None
        if spec is None:
            return
        text = text.strip() if spec.kind != "str" else text
        value: object = text
        if not text:
            value = "" if spec.required and spec.kind == "str" else None
        elif spec.kind == "int":
            value = int(text) if text.isdigit() else text
        elif spec.kind == "list[str]":
            value = [part.strip() for part in text.split(",") if part.strip()]
        elif spec.kind == "table":
            try:
                value = json.loads(text)
            except ValueError:
                self._say(f"{name} is not valid JSON; keeping the last good value.")
                return
            if not isinstance(value, dict):
                self._say(f"{name} must be a JSON object; keeping the last good value.")
                return
        self._set_field(name, value)

    def _cases(self, index: int) -> dict:
        cases = self._steps[index].fields.get("cases")
        return {k: dict(v) if isinstance(v, dict) else {} for k, v in
                (cases.items() if isinstance(cases, dict) else ())}

    def _set_case(self, n: int, part: str, value: str) -> None:
        index = self._selected()
        if index is None:
            return
        cases = self._cases(index)
        keys = list(cases)
        if not 0 <= n < len(keys) or cases[keys[n]].get(part) == value:
            return
        cases[keys[n]][part] = value
        self._set_field("cases", cases)

    async def _add_case(self) -> None:
        index = self._selected()
        later = self._later(index) if index is not None else []
        if not later:
            self._say("Add a later step first: a case needs somewhere to go.")
            return
        cases = self._cases(index)
        n = len(cases) + 1
        while f"case_{n}" in cases:
            n += 1
        cases[f"case_{n}"] = {"equals": "", "goto": later[0]}
        self._set_field("cases", cases)
        await self._inspect(force=True)

    async def _remove_case(self, n: int) -> None:
        index = self._selected()
        if index is None:
            return
        cases = self._cases(index)
        keys = list(cases)
        if 0 <= n < len(keys):
            del cases[keys[n]]
            self._set_field("cases", cases or None)
            await self._inspect(force=True)

    # ---- validation and dry run ----------------------------------------

    def _validate(self) -> bool:
        found: dict[str | None, list[str]] = {}
        try:
            wanted = replace(self._workflow, trigger=self._trigger(True), steps=tuple(self._steps))
            for message in service.validate(definitions.render(wanted)):
                found.setdefault(_step_of(message), []).append(message)
        except Exception as error:
            found[None] = [str(error)]
        self._problems = found
        for index in range(len(self._steps)):
            self._touch(index)
        self._show_problems()
        return not found

    def _check(self) -> None:
        if self._validate():
            self._say("Valid.")
            return
        count = sum(len(v) for v in self._problems.values())
        loose = self._problems.get(None, [])
        self._say(f"{count} problem(s); marked steps show them. " + " ".join(loose))

    def _dry_run(self) -> None:
        if self._dirty():
            self._say("Save first: a dry run uses the saved workflow.")
            return
        self.app.push_screen(DryRunScreen(self._workflow))

    # ---- actions -------------------------------------------------------

    def _add(self) -> None:
        kind = str(self.query_one("#wb-type", Select).value)
        taken = {s.id for s in self._steps}
        n = 1
        while f"{kind}_{n}" in taken:
            n += 1
        self._steps.append(definitions.Step(f"{kind}_{n}", kind, dict(_STEP_DEFAULTS.get(kind, {}))))
        self._refresh(len(self._steps))
        self._say(f"Added {kind}_{n}.")

    def _move(self, delta: int) -> None:
        index = self._selected()
        if index is None:
            self._say("Select a step first.")
            return
        other = index + delta
        if not 0 <= other < len(self._steps):
            return
        self._steps[index], self._steps[other] = self._steps[other], self._steps[index]
        self._refresh(other + 1)

    def _routed_from(self, step_id: str) -> str | None:
        for other in self._steps:
            if other.id == step_id:
                continue
            for _where, target in definitions._targets(other.type, dict(other.fields), "", []):
                if target == step_id:
                    return other.id
        return None

    def _delete(self) -> None:
        index = self._selected()
        if index is None:
            self._say("Select a step first.")
            return
        step = self._steps[index]
        router = self._routed_from(step.id)
        if router is not None:
            self._say(f"Cannot delete {step.id}: step {router} routes to it.")
            return
        del self._steps[index]
        self._refresh(index)
        self._say(f"Deleted {step.id}.")

    def _save(self) -> None:
        if not self._validate():
            count = sum(len(v) for v in self._problems.values())
            first = next(m for v in self._problems.values() for m in v)
            self._say(f"Not saved: {count} problem(s). {first}")
            return
        try:
            trigger = self._trigger(True)
            wanted = replace(self._workflow, trigger=trigger, steps=tuple(self._steps))
            saved = definitions.parse(definitions.render(wanted), kind=wanted.kind,
                                      path=wanted.path, repo_root=wanted.root)
            service.save(saved)
        except Exception as error:
            self._say(str(error))
            return
        old = self._workflow
        self._workflow = saved
        self._baseline = self._signature(self._trigger_values(saved.trigger))
        if definitions.semantic_hash(old.raw) != definitions.semantic_hash(saved.raw):
            self._say("Saved. Review & accept to run the new version.")
        elif definitions.layout_hash(old.raw) != definitions.layout_hash(saved.raw):
            self._say("Saved layout.")
        else:
            self._say("Saved.")

    def action_cancel(self) -> None:
        from whyline.console.tui import ConfirmScreen

        if not self._dirty():
            self.dismiss(None)
            return

        def decided(confirmed: bool | None) -> None:
            if confirmed:
                self.dismiss(None)

        self.app.push_screen(ConfirmScreen("Discard unsaved changes?", "Discard"), decided)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id or ""
        if button_id == "wc-add":
            await self._add_case()
        elif button_id.startswith("wc-rm-"):
            await self._remove_case(int(button_id[6:]))
        else:
            {"wb-add": self._add, "wb-up": lambda: self._move(-1), "wb-down": lambda: self._move(1),
             "wb-delete": self._delete, "wb-save": self._save, "wb-validate": self._check,
             "wb-dryrun": self._dry_run, "wb-cancel": self.action_cancel}[button_id]()
