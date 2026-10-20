"""Ideas in Agents mode: the CLI's own writes, and Telegram's jobs."""

from pathlib import Path

import pytest
from rich.text import Text
from textual.widgets import DataTable

from whyline.console import tui
from whyline.console.ideas_screen import IdeasScreen
from whyline.ideas import store

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

_ACTIONS = (
    "#id-score",
    "#id-brainstorm",
    "#id-refine",
    "#id-drop",
    "#id-reopen",
    "#id-report",
    "#id-documents",
    "#id-excel",
    "#id-open",
)


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


def _text(value) -> str:
    if value is None:
        return ""
    return value.plain if hasattr(value, "plain") else str(value)


def _plain(widget) -> str:
    label = getattr(widget, "label", None)
    text = _text(label)
    if text:
        return text
    return _text(getattr(widget, "renderable", None))


def _capture(text: str, *, source: str = "cli", status: str | None = None) -> store.Idea:
    conn = store.connect()
    try:
        idea = store.add(conn, text, source=source)
        if status == "dropped":
            idea = store.transition(
                conn,
                idea.id,
                "dropped",
                expected_revision=idea.revision,
                actor="cli",
            )
        return idea
    finally:
        conn.close()


def _jobs():
    conn = store.connect()
    try:
        return [
            (row["kind"], row["state"], int(row["idea_id"]))
            for row in conn.execute(
                "SELECT kind, state, idea_id FROM jobs ORDER BY id"
            )
        ]
    finally:
        conn.close()


def _land_score(idea_id: int, report: Path, *, usefulness: int, complexity_mvp: int, verdict: str) -> None:
    """Stand in for the worker: the queued job finishes and the row can refresh."""
    conn = store.connect()
    try:
        idea = store.get(conn, idea_id)
        assert idea is not None
        current = idea
        if idea.status == "captured":
            current = store.transition(
                conn,
                idea.id,
                "scoring",
                expected_revision=idea.revision,
                actor="analyse",
            )
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("landed score\n", encoding="utf-8")
        store.add_analysis(
            conn,
            idea_id,
            agent="claude",
            report_path=str(report),
            usefulness=usefulness,
            complexity_mvp=complexity_mvp,
            verdict=verdict,
        )
        store.transition(
            conn,
            idea_id,
            "scored",
            expected_revision=current.revision,
            actor="analyse",
        )
        conn.execute(
            """
            UPDATE jobs SET state = 'done'
            WHERE idea_id = ? AND kind = 'score'
            """,
            (idea_id,),
        )
    finally:
        conn.close()


def _cell(screen, idea_id: int, column: str) -> str:
    table = screen.query_one("#id-table", DataTable)
    cell = table.get_cell(str(idea_id), column)
    return cell.plain if isinstance(cell, Text) else str(cell)


def _selected(screen) -> int | None:
    table = screen.query_one("#id-table", DataTable)
    if table.row_count == 0:
        return None
    key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
    return int(key)


def _rendered(widget) -> str:
    return "\n".join(widget.render_line(y).text for y in range(widget.size.height))


async def _until(pilot, condition, what):
    for _ in range(400):
        await pilot.pause(0.05)
        if condition():
            return
    raise AssertionError(f"never happened: {what}")


async def _open(pilot, app):
    app.push_screen(IdeasScreen())
    await _until(pilot, lambda: isinstance(app.screen, IdeasScreen), "ideas shown")
    return app.screen


async def test_add_creates_an_idea_and_selects_it(ideas_home):
    older = _capture("Older idea")
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        screen.query_one("#id-text", tui.Input).value = "A brand new idea"
        await pilot.click("#id-add")
        await pilot.pause()
        conn = store.connect()
        try:
            ideas = store.list_ideas(conn)
        finally:
            conn.close()
        assert [idea.title for idea in ideas] == ["Older idea", "A brand new idea"]
        added = ideas[-1]
        assert added.id != older.id
        assert added.status == "captured"
        assert added.source == "cli"
        assert _selected(screen) == added.id
        assert _cell(screen, added.id, "title") == "A brand new idea"
        assert _cell(screen, added.id, "status") == "captured"
        assert _cell(screen, added.id, "source") == "CLI"


async def test_filter_shows_only_matching_rows(ideas_home):
    _capture("Keep this one")
    _capture("Drop this one", status="dropped")
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        table = screen.query_one("#id-table", DataTable)
        assert table.row_count == 2
        screen.query_one("#id-filter", tui.Select).value = "dropped"
        await pilot.pause()
        assert table.row_count == 1
        assert _cell(screen, 2, "status") == "dropped"
        assert _cell(screen, 2, "title") == "Drop this one"
        screen.query_one("#id-filter", tui.Select).value = "captured"
        await pilot.pause()
        assert table.row_count == 1
        assert _cell(screen, 1, "status") == "captured"
        assert _cell(screen, 1, "title") == "Keep this one"


async def test_drop_is_disabled_for_a_dropped_idea_and_reopen_enabled(ideas_home):
    _capture("Put away", status="dropped")
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        assert _selected(screen) == 1
        assert screen.query_one("#id-drop", tui.Button).disabled
        assert not screen.query_one("#id-reopen", tui.Button).disabled
        assert screen.query_one("#id-score", tui.Button).disabled
        assert screen.query_one("#id-brainstorm", tui.Button).disabled


async def test_score_queues_one_job_and_the_row_updates_when_a_fake_job_lands(ideas_home):
    idea = _capture("Score me")
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        await pilot.click("#id-score")
        await pilot.pause()
        assert _jobs() == [("score", "queued", idea.id)]
        assert "Scoring" in _plain(screen.query_one("#id-thinking"))
        assert _cell(screen, idea.id, "status") == "captured"
        report = ideas_home / "reports" / f"{idea.id}.md"
        _land_score(idea.id, report, usefulness=8, complexity_mvp=2, verdict="YES")
        await _until(
            pilot,
            lambda: _cell(screen, idea.id, "status") == "scored"
            and _cell(screen, idea.id, "usefulness") == "8",
            "row updated",
        )
        assert _cell(screen, idea.id, "mvp") == "2"
        assert _cell(screen, idea.id, "verdict") == "YES"
        assert _plain(screen.query_one("#id-thinking")) == ""


async def test_report_opens_the_report_in_the_files_pane(ideas_home):
    idea = _capture("Has a report")
    report = ideas_home / "reports" / "score.md"
    report.parent.mkdir(parents=True)
    report.write_text("Unique report sentence.\n", encoding="utf-8")
    conn = store.connect()
    try:
        current = store.transition(
            conn, idea.id, "scoring", expected_revision=idea.revision, actor="analyse"
        )
        store.add_analysis(
            conn,
            idea.id,
            agent="claude",
            report_path=str(report),
            usefulness=6,
            complexity_mvp=4,
            verdict="NOT YET",
        )
        store.transition(
            conn, idea.id, "scored", expected_revision=current.revision, actor="analyse"
        )
    finally:
        conn.close()
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await _open(pilot, app)
        assert not app._files_on
        await pilot.click("#id-report")
        await pilot.pause()
        assert app._files_on
        assert app._main("#file-pane").display
        view = app._main("#file-view", tui.FollowView)
        assert view.read_only
        assert "Unique report sentence." in view.text
        assert str(report) in _plain(app._main("#file-path"))
        assert str(report) in _plain(screen.query_one("#id-message"))


async def test_excel_names_the_workbook_path(ideas_home):
    _capture("Export me")
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        await pilot.click("#id-excel")
        await pilot.pause()
        named = _plain(screen.query_one("#id-message")).strip()
        path = Path(named)
        assert path.is_file()
        assert path.suffix == ".xlsx"
        assert path == ideas_home / "ideas.xlsx"
        assert not screen.query_one("#id-open", tui.Button).disabled


async def test_a_title_containing_markup_renders_literally(ideas_home):
    idea = _capture("[bold] stays")
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await _open(pilot, app)
        cell = screen.query_one("#id-table", DataTable).get_cell(str(idea.id), "title")
        assert isinstance(cell, Text)
        assert cell.plain == "[bold] stays"
        rendered = _rendered(screen.query_one("#id-table"))
        assert "[bold]" in rendered
        assert "[bold] stays" in rendered


async def test_action_buttons_are_on_screen_at_80x24(ideas_home):
    for number in range(12):
        _capture(f"Idea {number} with a title long enough to fill a row")
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        table = screen.query_one("#id-table", DataTable)
        assert table.virtual_size.height > table.size.height
        for button_id in _ACTIONS:
            region = screen.query_one(button_id).region
            assert region.height > 0, button_id
            assert region.bottom <= 24, button_id
            assert region.right <= 80, button_id
            assert region.x >= 0, button_id


async def test_agents_mode_ideas_button_opens_the_screen(tmp_path, ideas_home):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#mode-agents")
        await pilot.pause()
        assert "agents-ideas" in tui._MODE_BUTTONS["agents"]
        ids = [button.id for button in app.query("#controls Button")]
        assert ids.index("agents-ideas") == ids.index("agents-inbox") + 1
        button = app.query_one("#agents-ideas")
        assert str(button.label) == "Ideas"
        assert button.display
        await pilot.click("#agents-ideas")
        await _until(pilot, lambda: isinstance(app.screen, IdeasScreen), "ideas shown")
