from pathlib import Path

import pytest

from whyline.console import plan_job, relay_ops, tui
from whyline.console.relay_screens import PlanDraftScreen, RelayPlanScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

STATUS = {
    agent: {"available": agent in ("claude", "codex"), "label": "ok"}
    for agent in ("claude", "codex", "antigravity", "grok")
}


class PlanExists(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def quiet_ops(monkeypatch):
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: None)
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: [])
    monkeypatch.setattr(relay_ops, "plan_exists_error", lambda: PlanExists)
    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok"]
    )
    monkeypatch.setattr(relay_ops, "planner_agents", lambda root: ("codex", "claude"))


async def _open(app, pilot):
    results = []
    app.push_screen(RelayPlanScreen(app.session.root, STATUS, "claude"), results.append)
    await pilot.pause()
    return app.screen, results


def _error_text(screen):
    return str(screen.query_one("#rp-error", tui.Static).renderable)


async def test_paste_saves_a_valid_plan(tmp_path, monkeypatch):
    saved = []
    monkeypatch.setattr(
        relay_ops,
        "save_pasted_plan",
        lambda root, text, name, replace=False: saved.append((text, replace))
        or (root / "plans" / "plan.plan.md"),
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        screen.query_one("#rp-paste").load_text("- [ ] T-1: build it\n")
        await pilot.click("#rp-go")
        await pilot.pause()
    assert saved == [("- [ ] T-1: build it\n", False)]
    assert results == [tmp_path / "plans" / "plan.plan.md"]


async def test_paste_shows_why_an_invalid_plan_is_refused(tmp_path, monkeypatch):
    def refuse(root, text, name, replace=False):
        raise ValueError("no tasks found -- write each task as `- [ ] ID: title`")

    monkeypatch.setattr(relay_ops, "save_pasted_plan", refuse)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        screen.query_one("#rp-paste").load_text("just prose")
        await pilot.click("#rp-go")
        await pilot.pause()
        assert "no tasks found" in _error_text(screen)
        assert results == []


async def test_paste_over_an_existing_plan_asks_first(tmp_path, monkeypatch):
    calls = []

    def save(root, text, name, replace=False):
        calls.append(replace)
        if not replace:
            raise PlanExists("plan.plan.md already exists")
        return root / "plans" / "plan.plan.md"

    monkeypatch.setattr(relay_ops, "save_pasted_plan", save)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        screen.query_one("#rp-paste").load_text("- [ ] T-1: x\n")
        await pilot.click("#rp-go")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
    assert calls == [False, True]
    assert results == [tmp_path / "plans" / "plan.plan.md"]


async def test_only_the_chosen_sources_fields_show(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        assert screen.query_one("#rp-source", tui.Select).value == "draft"
        assert screen.query_one("#rp-draft-group").display
        assert not screen.query_one("#rp-paste-group").display
        screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        assert screen.query_one("#rp-paste-group").display
        assert not screen.query_one("#rp-draft-group").display


async def test_plan_button_opens_the_popup_and_reports_the_saved_plan(tmp_path, monkeypatch):
    from whyline import account

    monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
    monkeypatch.setattr(
        relay_ops,
        "save_pasted_plan",
        lambda root, text, name, replace=False: root / "plans" / "plan.plan.md",
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.click("#relay-plan")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        app.screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        app.screen.query_one("#rp-paste").load_text("- [ ] T-1: x\n")
        await pilot.click("#rp-go")
        await pilot.pause()
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any(
            ("Saved plans/" in line or "Saved plan" in line) and "Set up" in line for line in lines
        )




async def test_draft_needs_a_description(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rp-go")
        await pilot.pause()
        assert "Describe what the plan should build" in _error_text(screen)


async def test_an_unfinished_draft_can_be_discarded(tmp_path, monkeypatch):
    discarded = []
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: "Build it")
    monkeypatch.setattr(relay_ops, "discard_draft", lambda root, draft: discarded.append(draft))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rp-discard-draft")
        await pilot.pause()
        assert discarded == [None]
        assert _error_text(screen) == ""
        assert not screen.query_one("#rp-resume-draft").display


async def test_draft_dismisses_with_a_request_carrying_the_agents(tmp_path, monkeypatch):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-name", tui.Input).value = "Trading v1"
        screen.query_one("#rp-description").load_text("Build the PRD")
        screen.query_one("#rp-drafter", tui.Select).value = "grok"
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results == [
        plan_job.PlanRequest(
            "draft", "Trading v1", description="Build the PRD", drafter="grok", reviewer="claude"
        )
    ]


async def test_an_empty_name_comes_from_the_description(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-description").load_text("Build the trading platform")
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results[0].name == "Build the trading platform"


async def test_an_existing_plan_name_asks_before_replacing(tmp_path):
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "p.plan.md").write_text("x")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-name", tui.Input).value = "p"
        screen.query_one("#rp-description").load_text("x")
        await pilot.click("#rp-go")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
    assert results[0].replace is True


async def test_an_existing_brainstorm_becomes_a_request(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: ["topic-a"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "brainstorm"
        await pilot.pause()
        screen.query_one("#rp-from", tui.Select).value = "topic-a"
        await pilot.pause()
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results == [
        plan_job.PlanRequest("existing", "topic-a", topic="topic-a", writer="claude")
    ]


async def test_resume_dismisses_with_a_resume_request(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: "Build the PRD")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        await pilot.click("#rp-resume-draft")
        await pilot.pause()
    assert results == [plan_job.PlanRequest("resume", "Build the PRD")]


async def test_plan_draft_screen_closes(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        results = []
        app.push_screen(PlanDraftScreen("Draft text here"), results.append)
        await pilot.pause()
        assert isinstance(app.screen, PlanDraftScreen)
        await pilot.click("#pd-close")
        await pilot.pause()
        assert results == [None]
