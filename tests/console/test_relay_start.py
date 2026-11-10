"""Start on the New plan form: the guard, the set, the busy line, and Docs opening."""

import threading

import pytest

from whyline.console import relay_ops, tui
from whyline.console.relay_screens import DocsStart, RelayPlanScreen
from whyline.sdlc import docset, guard, runner, workspace

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

STATUS = {
    agent: {"available": agent in ("claude", "codex"), "label": "ok"}
    for agent in ("claude", "codex", "antigravity", "grok")
}


@pytest.fixture(autouse=True)
def quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: None)
    monkeypatch.setattr(relay_ops, "pending_spec", lambda root: None)
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: [])
    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok"]
    )
    monkeypatch.setattr(relay_ops, "planner_agents", lambda root: ("codex", "claude", ""))
    monkeypatch.setattr(workspace, "docs_root", lambda root: tmp_path)
    monkeypatch.setattr(guard, "check", lambda root: None)


async def _wait_for(pilot, condition, what):
    for _ in range(200):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what}")


async def _open(app, pilot):
    screen = RelayPlanScreen(app.session.root, STATUS, "claude", sdlc=True)
    app.push_screen(screen, app._plan_chosen)
    await pilot.pause()
    return screen


def _fill(screen, name="Job search 5", description="Find jobs"):
    screen.query_one("#rp-name", tui.Input).value = name
    screen.query_one("#rp-description").load_text(description)


def _error(screen):
    return str(screen.query_one("#rp-error", tui.Static).renderable)


async def test_a_refusal_shows_in_the_error_line_and_creates_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "check", lambda root: "A relay is running in the documents checkout.")
    ran = []
    monkeypatch.setattr(runner, "run", lambda *a, **k: ran.append(a))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        _fill(screen)
        screen.query_one("#rp-go", tui.Button).press()
        await pilot.pause()
        assert "relay is running" in _error(screen)
        assert app.screen is screen
    assert docset.all_sets(tmp_path) == []
    assert ran == []


async def test_start_creates_the_set_closes_and_shows_progress_then_opens_docs(
    tmp_path, monkeypatch
):
    release = threading.Event()
    progressed = threading.Event()

    def fake_run(root, slug, *, progress=None, cancel_event=None, launcher=None):
        progress("writing PRD")
        progressed.set()
        release.wait(10)
        return runner.RunOutcome("waiting", "prd")

    monkeypatch.setattr(runner, "run", fake_run)
    opened = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_open_docs", lambda slug, kind: opened.append((slug, kind)))
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        _fill(screen)
        screen.query_one("#rp-go", tui.Button).press()
        await _wait_for(pilot, progressed.is_set, "the runner reported progress")
        await _wait_for(pilot, lambda: app._busy_text.endswith("writing PRD"), "busy text")
        assert app.screen is not screen
        app._tick()
        line = str(app._main("#thinking", tui.Static).renderable)
        assert "docs: Job search 5 · writing PRD · " in line
        assert line.rstrip().endswith("0s")
        release.set()
        await _wait_for(pilot, lambda: opened, "Docs opened")
        assert app._busy_text == ""
    [found] = docset.all_sets(tmp_path)
    assert found.name == "Job search 5"
    assert found.description == "Find jobs"
    assert opened == [(found.slug, "prd")]


async def test_questions_open_docs_on_the_asking_document(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner, "run", lambda *a, **k: runner.RunOutcome("questions", "spec", questions=("Why?",))
    )
    opened = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_open_docs", lambda slug, kind: opened.append((slug, kind)))
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        _fill(screen)
        screen.query_one("#rp-go", tui.Button).press()
        await _wait_for(pilot, lambda: opened, "Docs opened")
    assert opened[0][1] == "spec"


async def test_a_large_start_persists_architect_reviewer(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "run", lambda *a, **k: runner.RunOutcome("done"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        _fill(screen)
        screen.query_one("#rp-size", tui.Select).value = "large"
        await pilot.pause()
        screen.query_one("#rp-architect", tui.Select).value = "grok"
        await pilot.pause()
        screen.query_one("#rp-go", tui.Button).press()
        await pilot.pause(0.3)
        assert app.screen is not screen
    [found] = docset.all_sets(tmp_path)
    assert found.roles.get("architect_reviewer") == "grok"
    assert "architect" not in found.roles


async def test_a_chosen_file_is_imported_as_its_kind(tmp_path, monkeypatch):
    source = tmp_path / "idea.md"
    source.write_text("# The PRD\nBuild it.\n")
    monkeypatch.setattr(runner, "run", lambda *a, **k: runner.RunOutcome("done"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        screen.query_one("#rp-start", tui.Select).value = "document"
        await pilot.pause()
        screen.query_one("#rp-document-kind", tui.Select).value = "prd"
        screen._picked["document"] = source
        screen.query_one("#rp-name", tui.Input).value = "From file"
        screen.query_one("#rp-go", tui.Button).press()
        await pilot.pause(0.3)
        assert app.screen is not screen
    [found] = docset.all_sets(tmp_path)
    prd = found.document("prd")
    assert prd is not None and prd["written_by"] == "user"


async def test_without_the_flag_the_form_still_makes_a_plan_request(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    results = []
    async with app.run_test(size=(110, 50)) as pilot:
        screen = RelayPlanScreen(tmp_path, STATUS, "claude")
        app.push_screen(screen, results.append)
        await pilot.pause()
        _fill(screen)
        screen.query_one("#rp-go", tui.Button).press()
        await _wait_for(pilot, lambda: results, "the form closed")
    assert not isinstance(results[0], DocsStart)


async def test_pause_after_this_stage_saves_human_mode_and_shows_on_the_line(
    tmp_path, monkeypatch
):
    release = threading.Event()
    progressed = threading.Event()

    def fake_run(root, slug, *, progress=None, cancel_event=None, launcher=None):
        found = docset.load(tmp_path, slug)
        found.stage = "prd"
        docset.save(tmp_path, found)
        progress("writing PRD")
        progressed.set()
        release.wait(10)
        return runner.RunOutcome("done")

    monkeypatch.setattr(runner, "run", fake_run)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        assert not app._main("#docs-pause-after", tui.Button).display
        screen = await _open(app, pilot)
        _fill(screen)
        screen.query_one("#rp-mode", tui.Select).value = "auto"
        await pilot.pause()
        screen.query_one("#rp-go", tui.Button).press()
        await _wait_for(pilot, progressed.is_set, "the runner reported progress")
        button = app._main("#docs-pause-after", tui.Button)
        await _wait_for(pilot, lambda: button.display, "the button shown")
        button.press()
        await pilot.pause(0.2)
        [found] = docset.all_sets(tmp_path)
        assert found.mode == "human"
        assert not button.display
        app._tick()
        line = str(app._main("#thinking", tui.Static).renderable)
        assert "will pause after PRD" in line
        release.set()
        await pilot.pause(0.3)


async def test_pause_after_this_stage_stays_hidden_for_a_human_mode_run(tmp_path, monkeypatch):
    release = threading.Event()
    progressed = threading.Event()

    def fake_run(root, slug, *, progress=None, cancel_event=None, launcher=None):
        progress("writing PRD")
        progressed.set()
        release.wait(10)
        return runner.RunOutcome("done")

    monkeypatch.setattr(runner, "run", fake_run)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        _fill(screen)
        screen.query_one("#rp-go", tui.Button).press()
        await _wait_for(pilot, progressed.is_set, "the runner reported progress")
        [found] = docset.all_sets(tmp_path)
        assert found.mode == "human"
        assert not app._main("#docs-pause-after", tui.Button).display
        release.set()
        await pilot.pause(0.3)
