"""Ideas list for Agents mode.

Add, drop, reopen, and export call the same functions as ``whyline idea``.
Score and brainstorm queue the jobs Telegram queues, so a job started
here shows up there, and a job started there shows up here.
"""

from __future__ import annotations

import argparse
import io
import sqlite3
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select, Static
from textual.widgets.data_table import RowDoesNotExist

from whyline.ideas import brainstorm, cli, documents, store, worker

# Reopen is the dropped-idea command. scoring and brainstorming can also
# move to captured, and that move is Cancel, not Reopen.
_REOPEN_FROM = "dropped"
_REFINE_FROM = "scored"


@dataclass(frozen=True)
class _Outcome:
    code: int
    out: str
    err: str


def _invoke(fn, args: argparse.Namespace) -> _Outcome:
    """Run one ``whyline idea`` command and keep what it printed."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fn(args)
    return _Outcome(code, out.getvalue(), err.getvalue())


def _cell(value: object) -> Text:
    """A table cell. A string would be parsed as Rich markup."""
    shown = "" if value is None else str(value)
    return Text(shown, no_wrap=True, end="")


def _title(idea: store.Idea) -> str:
    title = idea.title.strip()
    if title:
        return title
    for line in idea.original_text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "(untitled)"


def _source(source: str) -> str:
    if source == "cli":
        return "CLI"
    if source == "telegram":
        return "Telegram"
    return source


def _blank(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _visible(conn: sqlite3.Connection, status: str | None) -> list[store.Idea]:
    """Newest first. ``list_ideas`` is oldest first."""
    ideas = store.list_ideas(conn, status)
    ideas.reverse()
    return ideas


def _latest_map(conn: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    found: dict[int, sqlite3.Row] = {}
    rows = conn.execute(
        "SELECT * FROM analyses ORDER BY idea_id, version, id"
    ).fetchall()
    for row in rows:
        found[int(row["idea_id"])] = row
    return found


def _latest(conn: sqlite3.Connection, idea_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM analyses
        WHERE idea_id = ?
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (idea_id,),
    ).fetchone()


def _fingerprint(conn: sqlite3.Connection) -> tuple:
    ideas = tuple(
        (idea.id, idea.status, idea.revision, idea.title, idea.original_text)
        for idea in store.list_ideas(conn)
    )
    analyses = tuple(
        (
            int(row["idea_id"]),
            int(row["version"]),
            row["usefulness"],
            row["complexity_mvp"],
            row["verdict"],
            row["report_path"],
        )
        for row in conn.execute(
            "SELECT * FROM analyses ORDER BY idea_id, version, id"
        )
    )
    try:
        jobs = tuple(
            (int(row["id"]), int(row["idea_id"]), row["kind"], row["state"])
            for row in conn.execute("SELECT id, idea_id, kind, state FROM jobs ORDER BY id")
        )
    except sqlite3.OperationalError:
        jobs = ()
    return (ideas, analyses, jobs)


def _thinking(conn: sqlite3.Connection) -> str:
    """One line while a score or brainstorm job is queued or running."""
    try:
        rows = conn.execute(
            """
            SELECT idea_id, kind FROM jobs
            WHERE state IN ('queued', 'running')
            ORDER BY id
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return ""
    parts = []
    for row in rows:
        if row["kind"] == "score":
            label = "Scoring"
        elif row["kind"] == "brainstorm":
            label = "Brainstorming"
        else:
            label = str(row["kind"])
        parts.append(f"{label} idea {row['idea_id']}…")
    return " ".join(parts)


def _allowed(status: str) -> frozenset[str]:
    return store.ALLOWED.get(status, frozenset())


def _workbook_on_disk() -> Path | None:
    from whyline.ideas import paths

    path = paths.configured_home() / "ideas.xlsx"
    return path if path.is_file() else None


def _open_with_macos(path: Path) -> str:
    """Hand ``path`` to macOS ``open``. The text is the error, or empty."""
    try:
        completed = subprocess.run(["open", str(path)], check=False)
    except OSError as exc:
        return str(exc)
    if completed.returncode != 0:
        return f"open exited {completed.returncode}"
    return ""


class RefineScreen(ModalScreen):
    """The extra context ``whyline idea refine`` takes as an argument."""

    DEFAULT_CSS = """
    RefineScreen { align: center middle; }
    RefineScreen > Vertical {
        width: 70; max-width: 100%; height: auto;
        padding: 1 2; border: thick $accent; background: $surface;
    }
    RefineScreen Input { width: 100%; }
    RefineScreen Horizontal { height: auto; margin-top: 1; }
    RefineScreen Button { margin-right: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("What should I add?"),
            Input(placeholder="Extra context", id="ida-text"),
            Horizontal(
                Button("Refine", id="ida-refine", variant="success"),
                Button("Cancel", id="ida-cancel"),
            ),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "ida-cancel":
            self.dismiss(None)
            return
        self.dismiss(self.query_one("#ida-text", Input).value)

    def on_input_submitted(self, event: "Input.Submitted") -> None:
        event.stop()
        self.dismiss(event.value)


class BrainstormSettingsScreen(ModalScreen):
    """IDEA-12's settings, filled the way the Telegram card is filled."""

    DEFAULT_CSS = """
    BrainstormSettingsScreen { align: center middle; }
    BrainstormSettingsScreen > Vertical {
        width: 100%; max-width: 100%; height: auto; max-height: 100%;
        padding: 0 1; border: thick $accent; background: $surface;
    }
    BrainstormSettingsScreen #idb-body { height: auto; max-height: 16; }
    BrainstormSettingsScreen #idb-buttons { height: auto; margin-top: 1; }
    BrainstormSettingsScreen #idb-buttons Button { margin-right: 1; }
    BrainstormSettingsScreen Input, BrainstormSettingsScreen Select { width: 1fr; }
    BrainstormSettingsScreen #idb-error { height: auto; color: $error; }
    BrainstormSettingsScreen #idb-error.-empty { display: none; }
    BrainstormSettingsScreen #idb-preview { height: auto; }
    """

    def __init__(self, idea_id: int) -> None:
        super().__init__()
        self._idea_id = idea_id
        self._base = brainstorm.Request((), 1, "", (), 15)

    def compose(self) -> ComposeResult:
        conn = store.connect()
        try:
            request, notes = brainstorm.defaults(conn)
        finally:
            conn.close()
        self._base = request
        passes = str(request.passes) if str(request.passes) in {"1", "2", "3"} else "1"
        timeout = str(request.timeout)
        if timeout not in {"15", "30", "45", "60", "none"}:
            timeout = "15"
        yield Vertical(
            VerticalScroll(
                Label("Start brainstorm will use:"),
                Static(brainstorm.render(request, notes), id="idb-preview", markup=False),
                Label("Models"),
                Input(", ".join(request.models), id="idb-models"),
                Label("Passes"),
                Select(
                    [("1", "1"), ("2", "2"), ("3", "3")],
                    value=passes,
                    allow_blank=False,
                    id="idb-passes",
                ),
                Label("Final writer"),
                Input(request.final, id="idb-final"),
                Label("Backup"),
                Input(", ".join(request.backup) if request.backup else "none", id="idb-backup"),
                Label("Timeout"),
                Select(
                    [("15", "15"), ("30", "30"), ("45", "45"), ("60", "60"), ("none", "none")],
                    value=timeout,
                    allow_blank=False,
                    id="idb-timeout",
                ),
                id="idb-body",
            ),
            Static("", id="idb-error", markup=False, classes="-empty"),
            Horizontal(
                Button("Start", id="idb-start", variant="success"),
                Button("Cancel", id="idb-cancel"),
                id="idb-buttons",
            ),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "idb-cancel":
            self.dismiss(None)
            return
        if event.button.id == "idb-start":
            self._start()

    def _error(self, text: str) -> None:
        widget = self.query_one("#idb-error", Static)
        widget.update(text)
        widget.set_class(not text, "-empty")

    def _start(self) -> None:
        passes = self.query_one("#idb-passes", Select).value
        timeout = self.query_one("#idb-timeout", Select).value
        fields = {
            "models": self.query_one("#idb-models", Input).value,
            "passes": int(passes) if str(passes).isdigit() else passes,
            "final": self.query_one("#idb-final", Input).value,
            "backup": self.query_one("#idb-backup", Input).value,
            "timeout": int(timeout) if str(timeout).isdigit() else timeout,
        }
        try:
            request, notes = brainstorm.apply(self._base, fields)
        except brainstorm.SettingsError as exc:
            self._error(str(exc))
            return
        if not request.models or not request.final:
            extra = "\n".join(notes)
            self._error(
                "No agent can brainstorm unattended."
                + (f"\n{extra}" if extra else "")
            )
            return
        conn = store.connect()
        try:
            idea = store.get(conn, self._idea_id)
            if idea is None:
                self._error(f"no idea {self._idea_id}")
                return
            allowed = _allowed(idea.status)
            if "brainstorm_configuring" not in allowed and idea.status != "brainstorm_configuring":
                self._error(f"This idea can't be brainstormed from {idea.status}.")
                return
            queued = worker.enqueue_brainstorm(conn, idea.id, request)
        finally:
            conn.close()
        if not queued:
            self._error("Already brainstorming.")
            return
        self.dismiss(tuple(notes))


class IdeasScreen(ModalScreen):
    """The idea ledger. The table scrolls; the actions stay on screen."""

    DEFAULT_CSS = """
    IdeasScreen { align: center middle; }
    IdeasScreen > Vertical {
        width: 100%; height: 1fr; max-height: 100%;
        padding: 0 1; border: thick $accent; background: $surface;
    }
    IdeasScreen #id-table { height: 1fr; min-height: 3; }
    IdeasScreen #id-add-row, IdeasScreen #id-filter-row,
    IdeasScreen #id-actions, IdeasScreen #id-more, IdeasScreen #id-open-row {
        height: auto;
    }
    IdeasScreen #id-add-row Input { width: 1fr; }
    IdeasScreen #id-filter-row Select { width: 1fr; }
    IdeasScreen #id-filter-row Label { width: auto; height: 3; padding: 1 1 0 0; }
    IdeasScreen Button { margin: 0 1 0 0; min-width: 8; }
    IdeasScreen #id-thinking { height: 1; color: $accent; }
    IdeasScreen #id-thinking.-idle { display: none; }
    IdeasScreen #id-message { height: auto; max-height: 3; }
    IdeasScreen #id-message.-empty { display: none; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._finger: tuple | None = None
        self._closed = False
        self._ready = False
        self._workbook: Path | None = None
        self._select_after: int | None = None

    def compose(self) -> ComposeResult:
        table = DataTable(id="id-table", cursor_type="row")
        table.add_column("id", key="id")
        table.add_column("title", key="title")
        table.add_column("status", key="status")
        table.add_column("usefulness", key="usefulness")
        table.add_column("MVP complexity", key="mvp")
        table.add_column("verdict", key="verdict")
        table.add_column("source", key="source")
        yield Vertical(
            Horizontal(
                Input(placeholder="New idea", id="id-text"),
                Button("Add", id="id-add", variant="success"),
                id="id-add-row",
            ),
            Horizontal(
                Label("Status"),
                Select(
                    [("All", "all"), *[(status, status) for status in store.STATUSES]],
                    value="all",
                    allow_blank=False,
                    id="id-filter",
                ),
                id="id-filter-row",
            ),
            table,
            Static("", id="id-thinking", markup=False, classes="-idle"),
            Static("", id="id-message", markup=False, classes="-empty"),
            Horizontal(
                Button("Score", id="id-score"),
                Button("Brainstorm", id="id-brainstorm"),
                Button("Refine", id="id-refine"),
                Button("Drop", id="id-drop", variant="warning"),
                id="id-actions",
            ),
            Horizontal(
                Button("Reopen", id="id-reopen"),
                Button("Report", id="id-report"),
                Button("Documents", id="id-documents"),
                Button("Excel", id="id-excel"),
                id="id-more",
            ),
            Horizontal(
                Button("Open", id="id-open"),
                Button("Close", id="id-close"),
                id="id-open-row",
            ),
        )

    def on_mount(self) -> None:
        self._ready = True
        self._reload()
        self.set_interval(0.25, self._watch)

    def on_unmount(self) -> None:
        self._closed = True

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        action = {
            "id-add": self._add,
            "id-score": self._score,
            "id-brainstorm": self._brainstorm,
            "id-refine": self._refine,
            "id-drop": self._drop,
            "id-reopen": self._reopen,
            "id-report": self._report,
            "id-documents": self._documents,
            "id-excel": self._excel,
            "id-open": self._open_workbook,
            "id-close": self.dismiss,
        }.get(event.button.id or "")
        if action is not None:
            action()

    def on_input_submitted(self, event: "Input.Submitted") -> None:
        if event.input.id == "id-text":
            event.stop()
            self._add()

    def on_select_changed(self, event: "Select.Changed") -> None:
        if not self._ready or event.select.id != "id-filter":
            return
        chosen = self._select_after
        self._select_after = None
        self._reload(select=chosen)

    def on_data_table_row_highlighted(self, event: "DataTable.RowHighlighted") -> None:
        self._sync_actions()

    def _watch(self) -> None:
        """A job started in Telegram lands here too. Refresh when it does."""
        if self._closed:
            return
        try:
            conn = store.connect()
        except store.SchemaError as exc:
            self._show(str(exc))
            return
        try:
            finger = _fingerprint(conn)
        finally:
            conn.close()
        if finger == self._finger:
            return
        try:
            self._reload()
        except NoMatches:
            return

    def _filter_status(self) -> str | None:
        value = self.query_one("#id-filter", Select).value
        if not isinstance(value, str) or value == "all":
            return None
        return value

    def _selected_id(self) -> int | None:
        table = self.query_one("#id-table", DataTable)
        if table.row_count == 0:
            return None
        coordinate = (table.cursor_row, 0)
        if not table.is_valid_coordinate(coordinate):
            return None
        key = table.coordinate_to_cell_key(coordinate).row_key.value
        try:
            return int(key)
        except (TypeError, ValueError):
            return None

    def _selected(self) -> store.Idea | None:
        idea_id = self._selected_id()
        if idea_id is None:
            return None
        conn = store.connect()
        try:
            return store.get(conn, idea_id)
        finally:
            conn.close()

    def _move_to(self, idea_id: int) -> None:
        table = self.query_one("#id-table", DataTable)
        try:
            row = table.get_row_index(str(idea_id))
        except RowDoesNotExist:
            return
        table.move_cursor(row=row)

    def _reload(self, *, select: int | None = None) -> None:
        table = self.query_one("#id-table", DataTable)
        if select is None:
            select = self._selected_id()
        status = self._filter_status()
        conn = store.connect()
        try:
            ideas = _visible(conn, status)
            analyses = _latest_map(conn)
            self._finger = _fingerprint(conn)
            thinking = _thinking(conn)
        finally:
            conn.close()
        table.clear()
        for idea in ideas:
            analysis = analyses.get(idea.id)
            table.add_row(
                _cell(idea.id),
                _cell(_title(idea)),
                _cell(idea.status),
                _cell("" if analysis is None else _blank(analysis["usefulness"])),
                _cell("" if analysis is None else _blank(analysis["complexity_mvp"])),
                _cell("" if analysis is None else _blank(analysis["verdict"])),
                _cell(_source(idea.source)),
                key=str(idea.id),
            )
        if select is not None:
            self._move_to(select)
        self._set_thinking(thinking)
        self._sync_actions()
        self._sync_open()

    def _show(self, text: str) -> None:
        widget = self.query_one("#id-message", Static)
        widget.update(text)
        widget.set_class(not text, "-empty")

    def _set_thinking(self, text: str) -> None:
        widget = self.query_one("#id-thinking", Static)
        widget.update(text)
        widget.set_class(not text, "-idle")

    def _sync_open(self) -> None:
        path = self._workbook or _workbook_on_disk()
        if path is not None:
            self._workbook = path
        try:
            self.query_one("#id-open", Button).disabled = path is None
        except NoMatches:
            return

    def _sync_actions(self) -> None:
        idea = self._selected()
        status = None if idea is None else idea.status
        allowed = _allowed(status) if status is not None else frozenset()
        enabled = {
            "id-score": "scoring" in allowed,
            "id-brainstorm": "brainstorm_configuring" in allowed,
            "id-refine": status == _REFINE_FROM and "scoring" in allowed,
            "id-drop": "dropped" in allowed,
            "id-reopen": status == _REOPEN_FROM and "captured" in allowed,
            "id-report": idea is not None,
            "id-documents": idea is not None,
        }
        for button_id, on in enabled.items():
            try:
                self.query_one(f"#{button_id}", Button).disabled = not on
            except NoMatches:
                return

    def _add(self) -> None:
        text = self.query_one("#id-text", Input).value
        if not str(text).strip():
            self._show("add needs the idea text.")
            return
        result = _invoke(
            cli.cmd_add, argparse.Namespace(text=text, score=False, agent=None)
        )
        lines = [line.strip() for line in result.out.splitlines() if line.strip()]
        if not lines or not lines[0].isdigit():
            self._show((result.err or result.out).strip() or "could not add the idea")
            return
        idea_id = int(lines[0])
        self.query_one("#id-text", Input).value = ""
        if result.code != 0:
            self._show((result.err or result.out).strip())
        else:
            self._show("")
        filt = self.query_one("#id-filter", Select)
        if filt.value != "all":
            self._select_after = idea_id
            filt.value = "all"
            return
        self._reload(select=idea_id)

    def _score(self) -> None:
        """Queue the same score job Telegram's Quick score queues.

        ``whyline idea score`` runs the analysis in this process.
        ``bot.enqueue_score`` is the insert Telegram uses; the worker
        module only exposes the brainstorm queue.
        """
        from whyline.ideas import bot

        idea = self._selected()
        if idea is None or "scoring" not in _allowed(idea.status):
            return
        conn = store.connect()
        try:
            fresh = store.get(conn, idea.id)
            if fresh is None:
                self._show(f"no idea {idea.id}")
                return
            queued = bot.enqueue_score(conn, fresh.id)
        finally:
            conn.close()
        if not queued:
            self._show("Already scoring.")
        else:
            self._show("")
        self._reload(select=idea.id)

    def _brainstorm(self) -> None:
        idea = self._selected()
        if idea is None or "brainstorm_configuring" not in _allowed(idea.status):
            return
        idea_id = idea.id

        def started(notes) -> None:
            if self._closed or notes is None:
                return
            if notes:
                self._show("\n".join(notes))
            self._reload(select=idea_id)

        self.app.push_screen(BrainstormSettingsScreen(idea_id), started)

    def _refine(self) -> None:
        idea = self._selected()
        if idea is None or idea.status != _REFINE_FROM:
            return
        idea_id = idea.id

        def answered(extra) -> None:
            if self._closed or extra is None:
                return
            text = str(extra).strip()
            if not text:
                self._show("refine needs the extra context.")
                return
            self._remember_and_score(idea_id, text)

        self.app.push_screen(RefineScreen(), answered)

    def _remember_and_score(self, idea_id: int, extra: str) -> None:
        from whyline.ideas import bot

        conn = store.connect()
        try:
            current = store.get(conn, idea_id)
            if current is None:
                self._show(f"no idea {idea_id}")
                return
            if current.status != _REFINE_FROM:
                self._show(
                    f"cannot refine idea {current.id} from {current.status}; it has to be scored"
                )
                return
            cli._remember_context(conn, current, extra)
            queued = bot.enqueue_score(conn, current.id)
        finally:
            conn.close()
        if not queued:
            self._show("Already scoring.")
        else:
            self._show("")
        self._reload(select=idea_id)

    def _drop(self) -> None:
        idea = self._selected()
        if idea is None or "dropped" not in _allowed(idea.status):
            return
        idea_id = idea.id

        def confirmed(yes: bool) -> None:
            if self._closed or not yes:
                return
            result = _invoke(cli.cmd_drop, argparse.Namespace(id=idea_id))
            if result.code != 0:
                self._show((result.err or result.out).strip())
            else:
                self._show("")
            self._reload(select=idea_id)

        from whyline.console.tui import ConfirmScreen

        self.app.push_screen(ConfirmScreen(f"Drop idea {idea_id}?", "Drop"), confirmed)

    def _reopen(self) -> None:
        idea = self._selected()
        if idea is None or idea.status != _REOPEN_FROM:
            return
        result = _invoke(cli.cmd_reopen, argparse.Namespace(id=idea.id))
        if result.code != 0:
            self._show((result.err or result.out).strip())
        else:
            self._show("")
        self._reload(select=idea.id)

    def _report(self) -> None:
        idea = self._selected()
        if idea is None:
            return
        conn = store.connect()
        try:
            row = _latest(conn, idea.id)
        finally:
            conn.close()
        if row is None:
            self._show("No report yet.")
            return
        path = Path(row["report_path"])
        if not path.is_file():
            self._show("(report file is missing)")
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        self._open_in_files(path, text)

    def _open_in_files(self, path: Path, text: str) -> None:
        """The console's Files pane, the same widgets a followed write uses."""
        app = self.app
        shown = str(path)
        if not hasattr(app, "_files_on"):
            self._show(shown)
            return
        app._files_on = True
        app._set_file_path(shown)
        view = app._main_widget("#file-view")
        if view is not None:
            view.read_only = True
            moving = getattr(app, "_follow_moving", False)
            app._follow_moving = True
            try:
                view.load_text(text)
                view.move_cursor((0, 0))
                view.scroll_cursor_visible()
            finally:
                app._follow_moving = moving
        if hasattr(app, "_follow_order"):
            if shown not in app._follow_order:
                app._follow_order.append(shown)
            app._follow_shown[shown] = text
            app._follow_index = app._follow_order.index(shown)
            app._follow_hold = True
            app._follow_user_scrolled = False
            app._sync_follow_buttons()
        app._sync_split()
        self._show(shown)

    def _documents(self) -> None:
        idea = self._selected()
        if idea is None:
            return
        conn = store.connect()
        try:
            row = _latest(conn, idea.id)
        finally:
            conn.close()
        if row is None:
            self._show("No report yet.")
            return
        md = Path(row["report_path"])
        if not md.is_file():
            self._show("(report file is missing)")
            return
        try:
            exported = documents.export(md)
        except (OSError, ValueError) as exc:
            self._show(str(exc))
            return
        lines = []
        if exported.docx is not None:
            lines.append(f"Word: {exported.docx}")
        if exported.pdf is not None:
            lines.append(f"PDF: {exported.pdf}")
        note = " ".join(item for item in exported.notes if item)
        if note:
            lines.append(note)
        self._show("\n".join(lines) if lines else "No Word or PDF path.")

    def _excel(self) -> None:
        result = _invoke(cli.cmd_export, argparse.Namespace())
        text = (result.out if result.code == 0 else result.err or result.out).strip()
        if result.code != 0 or not text:
            self._show(text or "could not write the workbook")
            return
        path = Path(text.splitlines()[-1].strip())
        if path.is_file():
            self._workbook = path
            self._sync_open()
        self._show(str(path))

    def _open_workbook(self) -> None:
        path = self._workbook or _workbook_on_disk()
        if path is None:
            self._show("No workbook yet.")
            return
        message = _open_with_macos(path)
        if message:
            self._show(message)
            return
        self._show(str(path))
