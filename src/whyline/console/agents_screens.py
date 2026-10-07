"""Agents mode popups: the list, one agent's detail, its runs, and the
new-agent form with its review."""
from __future__ import annotations

import json
import re
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, HorizontalGroup, Vertical, VerticalGroup, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Select, Static, TextArea

from whyline.agents import capabilities, definitions as d, paths, records
from whyline.agents.service import NO_AGENTS

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
        body: list = [Label("Agents" if self._rows else NO_AGENTS)]
        if self._rows:
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
            body.append(table)
        body.append(
            Horizontal(Button("Open", id="al-open", variant="primary"), Button("Close", id="al-close")),
        )
        yield Vertical(*body)

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


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _tilde(path: Path) -> str:
    """`~/x` when `path` is under the home directory, else a posix path."""
    try:
        resolved = path.expanduser().resolve()
        home = Path.home().resolve()
    except OSError:
        return Path(path).as_posix()
    shown = resolved.as_posix()
    home_s = home.as_posix()
    if shown == home_s:
        return "~"
    prefix = home_s + "/"
    if shown.startswith(prefix):
        return "~/" + shown[len(prefix):]
    return shown


def _first_folder(picked: list[Path]) -> Path | None:
    """The first directory in `picked`.

    `mac_input.pick_files` is `choose file`, so it returns files. The folder
    is then the directory that contains the first file.
    """
    for path in picked:
        if path.is_dir():
            return path
    for path in picked:
        parent = path.parent
        if str(parent) not in ("", ".") and parent.is_dir():
            return parent
    return None


_KIND = (
    ("In this repository", "repo"),
    ("Personal (runs in a folder you choose)", "personal"),
)
_WHEN = (
    ("When I run it", "manual"),
    ("Every day", "daily"),
    ("Weekdays", "weekdays"),
    ("Every N hours", "every"),
    ("When files appear in a folder", "folder"),
)
_EVERY_HELP = "Every N hours starts at midnight: 00:00, 05:00, 10:00, …"


class NewAgentScreen(ModalScreen):
    """Collects one agent. Dismisses with a validated AgentDef, or None."""

    DEFAULT_CSS = """
    NewAgentScreen { align: center middle; }
    NewAgentScreen > VerticalGroup {
        width: 100; max-width: 100%; height: auto; max-height: 100%;
        padding: 0 2; border: thick $accent; background: $surface;
        overflow-x: hidden; overflow-y: auto;
    }
    NewAgentScreen HorizontalGroup { height: auto; }
    NewAgentScreen .field-label { width: 16; padding: 1 1 0 0; }
    NewAgentScreen TextArea { height: 6; }
    NewAgentScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; width: auto; }
    NewAgentScreen Checkbox:focus { border: none; }
    NewAgentScreen #na-error { color: $error; height: auto; }
    NewAgentScreen #na-sources-list, NewAgentScreen #na-every-help {
        height: auto; color: $text-muted;
    }
    NewAgentScreen #na-buttons { height: auto; margin-top: 1; }
    NewAgentScreen Button { margin-right: 1; }
    """

    def __init__(self, root, status, existing: d.AgentDef | None = None) -> None:
        super().__init__()
        self._root = Path(root)
        self._status = status if isinstance(status, dict) else {}
        self._existing = existing
        self._sources: list[str] = list(existing.sources) if existing else []
        self._picking = False

    def _runnable(self) -> list[str]:
        return [cli for cli in d.CLIS if capabilities.can_run(cli)]

    def _cli_label(self, cli: str) -> str:
        info = self._status.get(cli)
        status = str(info.get("label") or "") if isinstance(info, dict) else ""
        text = f"{cli} · {status}" if status else cli
        if not capabilities.can_run_unattended(cli):
            text += " · on demand only"
        return text

    def _choice(self, widget_id: str) -> str:
        value = self.query_one(widget_id, Select).value
        return value if isinstance(value, str) else ""

    def compose(self) -> ComposeResult:
        existing = self._existing
        kind = existing.kind if existing else "repo"
        when = existing.trigger.kind if existing else "manual"
        runnable = self._runnable()
        runner = existing.runner if existing and existing.runner in runnable else (
            runnable[0] if runnable else None
        )
        backups = set(existing.backup) if existing else set()
        boxes = []
        for cli in runnable:
            box = Checkbox(
                self._cli_label(cli),
                value=cli in backups and cli != runner,
                id=f"na-backup-{cli}",
            )
            box.display = cli != runner
            boxes.append(box)
        workdir = HorizontalGroup(
            Label("Runs in", classes="field-label"),
            Input(
                existing.workdir if existing and existing.workdir else "~",
                id="na-workdir",
                placeholder="~",
            ),
            id="na-workdir-row",
        )
        workdir.display = kind == "personal"
        at_row = HorizontalGroup(
            Label("At", classes="field-label"),
            Input(existing.trigger.at if existing else "", id="na-at", placeholder="07:00"),
            id="na-at-row",
        )
        at_row.display = when in ("daily", "weekdays")
        every_row = HorizontalGroup(
            Label("Hours", classes="field-label"),
            Input(
                str(existing.trigger.every_hours) if existing and existing.trigger.every_hours else "",
                id="na-every",
                placeholder="4",
            ),
            id="na-every-row",
        )
        every_row.display = when == "every"
        every_help = Static(_EVERY_HELP, id="na-every-help")
        every_help.display = when == "every"
        folder_row = HorizontalGroup(
            Label("Folder", classes="field-label"),
            Input(
                existing.trigger.folder if existing else "",
                id="na-folder",
                placeholder="~/Downloads",
            ),
            Button("Choose", id="na-pick-folder"),
            id="na-folder-row",
        )
        folder_row.display = when == "folder"
        title = f"Edit {existing.name}" if existing else "New agent"
        yield VerticalGroup(
            Label(title),
            HorizontalGroup(
                Label("Where", classes="field-label"),
                Select(_KIND, value=kind, allow_blank=False, id="na-kind"),
            ),
            workdir,
            HorizontalGroup(
                Label("Name", classes="field-label"),
                Input(
                    existing.name if existing else "",
                    placeholder="research-digest",
                    id="na-name",
                    disabled=existing is not None,
                ),
            ),
            Label("Instructions"),
            TextArea(existing.instructions if existing else "", id="na-instructions"),
            HorizontalGroup(
                Label("Main CLI", classes="field-label"),
                Select(
                    [(self._cli_label(cli), cli) for cli in runnable],
                    value=runner if runner is not None else Select.BLANK,
                    allow_blank=not runnable,
                    prompt="No CLI can run an agent",
                    id="na-runner",
                ),
            ),
            Label("Backup CLIs"),
            *boxes,
            HorizontalGroup(
                Label("Model", classes="field-label"),
                Input(existing.model if existing else "", id="na-model", placeholder="optional"),
            ),
            Label("Sources"),
            HorizontalGroup(
                Button("Add sources", id="na-add-sources"),
                Button("Clear", id="na-clear-sources"),
            ),
            Static(self._sources_text(), id="na-sources-list", markup=False),
            HorizontalGroup(
                Label("When", classes="field-label"),
                Select(_WHEN, value=when, allow_blank=False, id="na-when"),
            ),
            at_row,
            every_row,
            every_help,
            folder_row,
            HorizontalGroup(
                Label("Report", classes="field-label"),
                Input(
                    existing.report_folder if existing else "",
                    id="na-report",
                    placeholder="optional folder",
                ),
            ),
            HorizontalGroup(
                Label("Timeout", classes="field-label"),
                Input(
                    str(existing.timeout_minutes) if existing else "15",
                    id="na-timeout",
                    placeholder="15",
                ),
            ),
            Static("", id="na-error", markup=False),
            HorizontalGroup(
                Button("Review", id="na-next", variant="primary"),
                Button("Cancel", id="na-cancel"),
                id="na-buttons",
            ),
        )

    def on_mount(self) -> None:
        self._sync_kind()
        self._sync_when()
        self._sync_backups()
        self.query_one("#na-error", Static).display = False
        if self._existing is None:
            self.query_one("#na-name", Input).focus()

    def on_select_changed(self, event: "Select.Changed") -> None:
        select_id = event.select.id
        if select_id == "na-kind":
            self._sync_kind()
        elif select_id == "na-runner":
            self._sync_backups()
        elif select_id == "na-when":
            self._sync_when()

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        button_id = event.button.id
        if button_id == "na-cancel":
            self.dismiss(None)
        elif button_id == "na-next":
            self._submit()
        elif button_id == "na-add-sources":
            self._pick("sources")
        elif button_id == "na-clear-sources":
            self._sources.clear()
            self._refresh_sources()
        elif button_id == "na-pick-folder":
            self._pick("folder")

    def _sync_kind(self) -> None:
        try:
            self.query_one("#na-workdir-row").display = self._choice("#na-kind") == "personal"
        except NoMatches:
            return

    def _sync_when(self) -> None:
        try:
            when = self._choice("#na-when")
        except NoMatches:
            return
        self.query_one("#na-at-row").display = when in ("daily", "weekdays")
        every = when == "every"
        self.query_one("#na-every-row").display = every
        self.query_one("#na-every-help").display = every
        self.query_one("#na-folder-row").display = when == "folder"

    def _sync_backups(self) -> None:
        try:
            runner = self._choice("#na-runner")
        except NoMatches:
            return
        for cli in self._runnable():
            try:
                box = self.query_one(f"#na-backup-{cli}", Checkbox)
            except NoMatches:
                return
            show = cli != runner
            box.display = show
            if not show:
                box.value = False

    def _sources_text(self) -> str:
        return "\n".join(self._sources) if self._sources else "(none)"

    def _refresh_sources(self) -> None:
        try:
            self.query_one("#na-sources-list", Static).update(self._sources_text())
        except NoMatches:
            return

    def _show_error(self, message: str) -> None:
        try:
            widget = self.query_one("#na-error", Static)
        except NoMatches:
            return
        widget.update(message)
        widget.display = bool(message)

    def _pick(self, target: str) -> None:
        from whyline.console import mac_input

        if self._picking:
            return
        if not mac_input.available():
            self._show_error("The file picker is only available on macOS.")
            return
        self._picking = True

        def work() -> None:
            try:
                picked = mac_input.pick_files()
            except Exception as error:
                self.app.call_from_thread(self._pick_failed, str(error) or "the file picker failed")
                return
            self.app.call_from_thread(self._pick_done, target, list(picked))

        self.run_worker(work, thread=True, exclusive=True, group="agent-pick")

    def _pick_failed(self, message: str) -> None:
        self._picking = False
        self._show_error(message)

    def _pick_done(self, target: str, picked: list[Path]) -> None:
        self._picking = False
        if not self.is_attached:
            return
        if target == "folder":
            folder = _first_folder(picked)
            if folder is None:
                if picked:
                    self._show_error("Pick a folder.")
                return
            stored = self._stored_path(folder, allow_outside=True)
            if stored:
                self.query_one("#na-folder", Input).value = stored
            return
        added = False
        for path in picked:
            stored = self._stored_path(path, allow_outside=False)
            if stored and stored not in self._sources:
                self._sources.append(stored)
                added = True
        if added:
            self._show_error("")
        self._refresh_sources()

    def _stored_path(self, path: Path, *, allow_outside: bool) -> str:
        try:
            resolved = Path(path).expanduser().resolve()
        except OSError:
            resolved = Path(path)
        if self._choice("#na-kind") == "repo":
            try:
                return resolved.relative_to(self._root.resolve()).as_posix()
            except ValueError:
                if not allow_outside:
                    self._show_error(f"{resolved.as_posix()} is outside the repository")
                    return ""
        return _tilde(resolved)

    def _int_token(self, widget_id: str, default: int | None) -> str:
        raw = self.query_one(widget_id, Input).value.strip()
        if not raw:
            return "0" if default is None else str(default)
        if re.fullmatch(r"[1-9]\d*|0", raw):
            return raw
        return _q(raw)

    def _toml(self) -> tuple[str, str, Path]:
        kind = self._choice("#na-kind") or "repo"
        name = self.query_one("#na-name", Input).value.strip()
        runner = self._choice("#na-runner")
        when = self._choice("#na-when") or "manual"
        backups = [
            cli for cli in self._runnable()
            if cli != runner and self.query_one(f"#na-backup-{cli}", Checkbox).value
        ]
        lines = [
            f"name = {_q(name)}",
            f"instructions = {_q(self.query_one('#na-instructions', TextArea).text)}",
            f"runner = {_q(runner)}",
            "backup = [" + ", ".join(_q(cli) for cli in backups) + "]",
        ]
        model = self.query_one("#na-model", Input).value.strip()
        if model:
            lines.append(f"model = {_q(model)}")
        lines.append("sources = [" + ", ".join(_q(source) for source in self._sources) + "]")
        if kind == "personal":
            workdir = self.query_one("#na-workdir", Input).value.strip() or "~"
            lines.append(f"workdir = {_q(workdir)}")
        report = self.query_one("#na-report", Input).value.strip()
        if report:
            lines.append(f"report_folder = {_q(report)}")
        lines.append(f"timeout_minutes = {self._int_token('#na-timeout', 15)}")
        lines += ["", "[trigger]", f"kind = {_q(when)}"]
        at = self.query_one("#na-at", Input).value.strip()
        if when in ("daily", "weekdays") or at:
            lines.append(f"at = {_q(at)}")
        if when == "every":
            lines.append(f"every_hours = {self._int_token('#na-every', None)}")
        folder = self.query_one("#na-folder", Input).value.strip()
        if when == "folder" or folder:
            lines.append(f"folder = {_q(folder)}")
        gap = self._existing.trigger.min_gap_minutes if self._existing else 10
        lines.append(f"min_gap_minutes = {gap}")
        # Edit writes back to the file that was opened. A new agent, or an
        # edit that changed kind, uses <name>.toml in that kind's directory.
        same = (
            self._existing is not None
            and self._existing.kind == kind
            and self._existing.name == name
        )
        if same:
            path = self._existing.path
        elif kind == "repo":
            path = paths.repo_dir(self._root) / f"{name}.toml"
        else:
            path = Path.home() / ".whyline" / "agents" / f"{name}.toml"
        return "\n".join(lines) + "\n", kind, path

    def _name_taken(self, defn: d.AgentDef) -> bool:
        for item in d.discover(self._root):
            if not isinstance(item, d.AgentDef):
                continue
            if item.kind != defn.kind or item.name != defn.name:
                continue
            if self._existing is not None and item.path == self._existing.path:
                continue
            return True
        return False

    def _submit(self) -> None:
        try:
            text, kind, path = self._toml()
            defn = d.parse(
                text,
                kind=kind,
                path=path,
                repo_root=self._root if kind == "repo" else None,
            )
        except d.DefinitionError as error:
            self._show_error(str(error))
            return
        if self._name_taken(defn):
            self._show_error(f"an agent named {defn.name} already exists")
            return
        self.dismiss(defn)


class ReviewScreen(ModalScreen):
    """Plain-language check before an agent is written. Dismisses with
    "save" or None (back to the form)."""

    DEFAULT_CSS = _CSS.format(name="ReviewScreen") + "ReviewScreen Static { height: auto; }"

    def __init__(self, defn: d.AgentDef, text: str, scheduler_on: bool) -> None:
        super().__init__()
        self._defn = defn
        self._text = text
        self._scheduler_on = scheduler_on

    def _body(self) -> str:
        text = self._text
        if self._defn.trigger.kind != "manual" and not self._scheduler_on:
            text = text.rstrip() + "\nTurn the scheduler on to run it automatically."
        return text

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(f"Review {self._defn.label}"),
            Static(self._body(), id="rv-text", markup=False),
            Horizontal(
                Button("Save", id="rv-save", variant="primary"),
                Button("Back", id="rv-back"),
            ),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        self.dismiss("save" if event.button.id == "rv-save" else None)
