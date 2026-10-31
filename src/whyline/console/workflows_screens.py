"""Workflows mode screens: the Library of workflows and the New dialog."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select, Static

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
        for button_id in ("wl-run", "wl-toggle", "wl-accept"):
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
