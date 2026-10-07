"""Agents mode popups: the list, one agent's detail, and its runs."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label, Static

from whyline.agents import definitions as d, records

_CSS = """
{name} {{ align: center middle; }}
{name} > Vertical {{ width: 110; max-width: 100%; height: auto; max-height: 90%;
    padding: 0 2; border: thick $accent; background: $surface; }}
{name} Horizontal {{ height: auto; margin-top: 1; }}
{name} Button {{ margin-right: 1; }}
"""


def _row_key(table: DataTable) -> str | None:
    if table.row_count == 0:
        return None
    coordinate = (table.cursor_row, 0)
    if not table.is_valid_coordinate(coordinate):
        return None
    return table.coordinate_to_cell_key(coordinate).row_key.value


class AgentsListScreen(ModalScreen):
    DEFAULT_CSS = _CSS.format(name="AgentsListScreen") + "AgentsListScreen DataTable { height: auto; max-height: 20; }"

    def __init__(self, rows) -> None:
        super().__init__()
        self._rows = rows

    def compose(self) -> ComposeResult:
        table = DataTable(id="al-table", cursor_type="row")
        table.add_columns("Agent", "CLI", "When", "Next", "Last", "Status")
        for row in self._rows:
            if isinstance(row.defn, d.Broken):
                table.add_row(
                    f"{row.defn.path.name} (broken)", "", row.when, "", "", "needs review",
                    key=f"broken:{row.defn.path.name}",
                )
                continue
            cli = row.defn.runner + (f" → {', '.join(row.defn.backup)}" if row.defn.backup else "")
            table.add_row(
                row.defn.label, cli, row.when, row.next_due or "—",
                row.last_outcome or "—", row.status, key=f"{row.defn.kind}:{row.defn.name}",
            )
        yield Vertical(
            Label("Agents" if self._rows else "No agents yet. Press New to make one."),
            table,
            Horizontal(Button("Open", id="al-open", variant="primary"), Button("Close", id="al-close")),
        )

    def _chosen(self) -> str | None:
        if not self._rows:
            return None
        key = _row_key(self.query_one("#al-table", DataTable))
        if key is None or key.startswith("broken:"):
            return None
        return key

    def on_data_table_row_selected(self, event) -> None:
        self.dismiss(self._chosen())

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        self.dismiss(self._chosen() if event.button.id == "al-open" else None)


class AgentDetailScreen(ModalScreen):
    DEFAULT_CSS = _CSS.format(name="AgentDetailScreen")

    def __init__(self, row, describe: str) -> None:
        super().__init__()
        self._row, self._describe = row, describe

    def compose(self) -> ComposeResult:
        row = self._row
        status = row.status
        buttons = [Button("Run now", id="ad-run", variant="success"), Button("History", id="ad-history")]
        if status == "needs_review":
            buttons.append(Button("Accept changes", id="ad-accept", variant="warning"))
        elif status in ("paused", "needs_attention"):
            buttons.append(Button("Resume", id="ad-resume"))
        else:
            buttons.append(Button("Pause", id="ad-pause"))
        buttons += [
            Button("Edit", id="ad-edit"),
            Button("Delete", id="ad-delete", variant="error"),
            Button("Close", id="ad-close"),
        ]
        yield Vertical(
            Label(row.defn.label),
            Static(self._describe),
            Static(f"Status: {status} · last: {row.last_outcome or '—'} {row.last_run}"),
            Horizontal(*buttons),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        action = (event.button.id or "").removeprefix("ad-")
        self.dismiss(None if action == "close" else action)


class RunsScreen(ModalScreen):
    DEFAULT_CSS = _CSS.format(name="RunsScreen") + "RunsScreen VerticalScroll { height: 20; }"

    def __init__(self, label: str, runs) -> None:
        super().__init__()
        self._label, self._runs = label, runs

    def compose(self) -> ComposeResult:
        table = DataTable(id="rs-runs", cursor_type="row")
        table.add_columns("When", "Trigger", "CLI", "Outcome")
        for run in self._runs:
            cli = run.cli + (" (backup)" if run.used_backup else "")
            table.add_row(run.started[:16].replace("T", " "), run.source, cli, run.outcome, key=run.run_id)
        yield Vertical(
            Label(f"Runs of {self._label}" if self._runs else f"{self._label} has not run yet."),
            table,
            VerticalScroll(Static("", id="rs-text", markup=False)),
            Horizontal(Button("Show log", id="rs-log"), Button("Close", id="rs-close")),
        )

    def _selected(self) -> str | None:
        if not self._runs:
            return None
        return _row_key(self.query_one("#rs-runs", DataTable))

    def _show(self, text: str) -> None:
        try:
            self.query_one("#rs-text", Static).update(text)
        except NoMatches:
            return

    def on_data_table_row_highlighted(self, event) -> None:
        run_id = self._selected()
        if not run_id:
            return
        try:
            text = records.read_final(run_id) or "(no answer)"
        except OSError:
            text = "(no answer)"
        self._show(text)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "rs-log":
            run_id = self._selected()
            if run_id:
                try:
                    text = records.read_log(run_id) or "(no log)"
                except OSError:
                    text = "(no log)"
                self._show(text)
            return
        self.dismiss(None)
