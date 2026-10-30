"""Console parity for the job tracker: list, set status and notes, export (JOB-14)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("textual")
from textual.widgets import DataTable  # noqa: E402

from whyline.console import tui
from whyline.console.jobs_screens import JobsHomeScreen, TrackedJobsScreen
from whyline.jobs import tracker

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


class _Host(tui.App):
    def compose(self):
        yield tui.Static("host")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    return home_dir


def _plain(value: object) -> str:
    return value.plain if hasattr(value, "plain") else str(value)


def _tracked(row, uid, company, score, status="new", notes=""):
    return {
        "row": row, "uid": uid, "company": company, "title": "Engineer",
        "score": score, "status": status, "notes": notes,
    }


async def test_jobs_home_has_a_tracked_jobs_button() -> None:
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(JobsHomeScreen(companies_list_fn=lambda: []))
        await pilot.pause()
        app.screen.query_one("#jh-tracked", tui.Button).press()
        await pilot.pause()
        assert isinstance(app.screen, TrackedJobsScreen)


async def test_tracked_screen_lists_sets_and_exports_through_the_given_functions() -> None:
    rows = [_tracked(1, "u1", "Acme", 82), _tracked(2, "u2", "Beta", 40)]
    sets: list[tuple[Any, ...]] = []
    exports: list[bool] = []

    def fake_set(ref, status, note=None):
        sets.append((ref, status, note))
        rows[1] = _tracked(2, "u2", "Beta", 40, status, note or "")

    def fake_export():
        exports.append(True)
        return Path("/tmp/jobs.xlsx")

    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = TrackedJobsScreen(
            list_fn=lambda: list(rows), set_fn=fake_set, export_fn=fake_export
        )
        app.push_screen(screen)
        await pilot.pause()
        table = screen.query_one("#tj-table", DataTable)
        assert [_plain(table.get_row_at(i)[3]) for i in range(2)] == ["Acme", "Beta"]
        table.move_cursor(row=1)
        screen.query_one("#tj-status-select").value = "applied"
        screen.query_one("#tj-note").value = "sent CV"
        screen.query_one("#tj-set", tui.Button).press()
        await pilot.pause()
        assert sets == [("u2", "applied", "sent CV")]
        assert _plain(table.get_row_at(1)[2]) == "applied"
        screen.query_one("#tj-export", tui.Button).press()
        await pilot.pause()
        assert exports == [True]
        assert "jobs.xlsx" in _plain(screen.query_one("#tj-status", tui.Static).render())


async def test_tracked_screen_defaults_to_the_tracker_functions() -> None:
    conn = tracker.connect()
    conn.execute(
        "INSERT INTO tracked (uid, company, title, url, score, verdict, reason,"
        " status, notes, updated_at)"
        " VALUES ('u1','Acme','Engineer','https://a',80,'shortlist','fits','new','','now')"
    )
    conn.commit()
    conn.close()
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = TrackedJobsScreen()
        app.push_screen(screen)
        await pilot.pause()
        screen.query_one("#tj-status-select").value = "interview"
        screen.query_one("#tj-set", tui.Button).press()
        await pilot.pause()
        assert tracker.list_rows()[0]["status"] == "interview"
        screen.query_one("#tj-export", tui.Button).press()
        await pilot.pause()
        assert tracker.xlsx_path().exists()


async def test_tracked_screen_set_without_selection_shows_an_error() -> None:
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = TrackedJobsScreen(list_fn=lambda: [], set_fn=lambda *a: None)
        app.push_screen(screen)
        await pilot.pause()
        screen.query_one("#tj-set", tui.Button).press()
        await pilot.pause()
        assert "Select a job first" in _plain(screen.query_one("#tj-error", tui.Static).render())


async def test_clear_note_button_passes_an_empty_note() -> None:
    rows = [_tracked(1, "u1", "Acme", 82, "applied", "sent CV")]
    sets: list[tuple[Any, ...]] = []

    def fake_set(ref, status, note=None):
        sets.append((ref, status, note))
        rows[0] = _tracked(1, "u1", "Acme", 82, status, note or "")

    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = TrackedJobsScreen(list_fn=lambda: list(rows), set_fn=fake_set)
        app.push_screen(screen)
        await pilot.pause()
        screen.query_one("#tj-status-select").value = "applied"
        screen.query_one("#tj-clear-note", tui.Button).press()
        await pilot.pause()
        assert sets == [("u1", "applied", "")]
        table = screen.query_one("#tj-table", DataTable)
        assert _plain(table.get_row_at(0)[5]) == ""
