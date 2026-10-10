from pathlib import Path

import pytest

from whyline.console import relay_ops, tui
from whyline.console.relay_screens import RelayPlanScreen, RelaySetupScreen, RunChoiceScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

STATUS = {a: {"available": True, "label": "ok"} for a in ("claude", "codex", "antigravity", "grok")}
PLAN = relay_ops.PlanInfo(Path("/r/plans/a.plan.md"), "a", "draft", "2026-10-04T10:00:00+05:30", 0, 3)


@pytest.fixture(autouse=True)
def ops(monkeypatch):
    from whyline import account

    calls = {"checks": 0}
    monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: [PLAN])
    monkeypatch.setattr(relay_ops, "configured_plan", lambda root: None)
    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: ["antigravity", "claude", "codex"])
    monkeypatch.setattr(relay_ops, "planner_agents", lambda root: ("codex", "claude"))
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: None)
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: [])
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: True)
    monkeypatch.setattr(relay_ops, "current_roles", lambda root: {
        "implementer": "antigravity", "tester": "claude", "reviewer": "codex",
        "backup": ["claude", "codex"],
    })
    monkeypatch.setattr(relay_ops, "live_run", lambda root: None)
    monkeypatch.setattr(relay_ops, "prepare_agents", lambda root, agents: [])
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)
    monkeypatch.setattr(relay_ops, "save_roles", lambda *a: None)
    monkeypatch.setattr(relay_ops, "save_release", lambda *a: None)
    monkeypatch.setattr(relay_ops, "select_plan", lambda *a: None)
    monkeypatch.setattr(relay_ops, "antigravity_state", lambda root: "trusted")

    def checks(root, plan=None):
        calls["checks"] += 1
        return [relay_ops.CheckLine("ok", "fine")]

    monkeypatch.setattr(relay_ops, "run_checks", checks)
    return calls


def _lines(app):
    return [str(line) for line in app.screen_stack[0].query_one("#transcript", tui.RichLog).lines]



async def _relay(app, pilot):
    app.session.mode = "relay"
    app._sync_mode_indicator()
    await pilot.pause()


async def test_run_with_no_plan_opens_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: [])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        await _relay(app, pilot)
        await pilot.click("#relay-run")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        assert any("No plan yet -- let's make one." in l for l in _lines(app))


async def test_typed_run_offers_new_or_existing_and_existing_opens_guided_setup(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        await _relay(app, pilot)
        app.query_one("#prompt", tui.Input).value = "run"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, RunChoiceScreen)
        await pilot.click("#run-existing")
        await pilot.pause()
        assert isinstance(app.screen, RelaySetupScreen) and app.screen._guided


async def test_a_saved_plan_continues_to_guided_setup_with_it_selected(tmp_path, monkeypatch):
    saved = relay_ops.PlanInfo(tmp_path / "plans" / "new.plan.md", "new", "paste", "2026-10-05T00:00:00+05:30", 0, 1)
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: [saved, PLAN])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        await _relay(app, pilot)
        await pilot.click("#relay-run")
        await pilot.pause()
        await pilot.click("#run-new")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        app.screen.dismiss(saved.path)  # what a pasted plan does
        await pilot.pause()
        assert isinstance(app.screen, RelaySetupScreen)
        assert app.screen.query_one("#rs-plan", tui.Select).value == str(saved.path)


async def test_standalone_plan_save_hints_manual_setup_to_the_new_plan(tmp_path, monkeypatch):
    saved = relay_ops.PlanInfo(
        tmp_path / "plans" / "new.plan.md",
        "new",
        "draft",
        "2026-10-10T18:00:00+05:30",
        0,
        2,
    )
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: [saved, PLAN])
    monkeypatch.setattr(relay_ops, "configured_plan", lambda root: PLAN.path)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        await _relay(app, pilot)
        app._plan_saved(saved.path)
        await pilot.pause()
        assert not isinstance(app.screen, RelaySetupScreen)

        await pilot.click("#relay-setup")
        await pilot.pause()
        assert isinstance(app.screen, RelaySetupScreen)
        assert app.screen.query_one("#rs-plan", tui.Select).value == str(saved.path)


async def test_cancelling_the_plan_form_ends_the_run(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        await _relay(app, pilot)
        await pilot.click("#relay-run")
        await pilot.pause()
        await pilot.click("#run-new")
        await pilot.pause()
        await pilot.click("#rp-cancel")
        await pilot.pause()
        assert app._run_flow is False
        assert any("Run cancelled" in l for l in _lines(app))


async def test_stopping_plan_generation_during_run_ends_the_run(tmp_path, monkeypatch):
    import threading
    from whyline.console import plan_job

    started = threading.Event()
    release = threading.Event()

    def block_request(root, req, progress):
        started.set()
        release.wait(5.0)
        return plan_job.Outcome("draft", tmp_path / "dummy.draft.md")

    monkeypatch.setattr(plan_job, "run_request", block_request)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        await _relay(app, pilot)
        await pilot.click("#relay-run")
        await pilot.pause()
        await pilot.click("#run-new")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)

        req = plan_job.PlanRequest("draft", "dummy-plan", description="build something", drafter="codex", reviewer="claude")
        app.screen.dismiss(req)
        await pilot.pause()

        for _ in range(100):
            if started.is_set() and app._plan_state == "working":
                break
            await pilot.pause(0.02)
        assert app._run_flow is True
        assert app._plan_state == "working"

        await pilot.click("#stop")
        await pilot.pause()

        release.set()
        await pilot.pause()

        assert app._run_flow is False
        assert app._plan_state == ""
        assert any("Run stopped: no plan was saved." in l for l in _lines(app))

        # A later standalone plan save must not reopen guided Set up
        saved_plan = tmp_path / "plans" / "saved.plan.md"
        app._plan_saved(saved_plan)
        await pilot.pause()
        assert not isinstance(app.screen, RelaySetupScreen)



async def test_guided_setup_summarises_roles_and_looks_good_runs_the_check(tmp_path, ops):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        app.push_screen(RelaySetupScreen(tmp_path, guided=True))
        await pilot.pause()
        screen = app.screen
        summary = str(screen.query_one("#rs-summary", tui.Static).renderable)
        assert summary == (
            "Implementer: antigravity · Tester: claude · Reviewer: codex · Backup: claude → codex · Release: you"
        )
        assert not screen.query_one("#rs-roles").display
        await pilot.click("#rs-looks-good")
        for _ in range(100):
            if not screen.query_one("#rs-start", tui.Button).disabled:
                break
            await pilot.pause(0.05)
        assert ops["checks"] == 1
        assert not screen.query_one("#rs-start", tui.Button).disabled


async def test_change_reveals_the_role_pickers(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        app.push_screen(RelaySetupScreen(tmp_path, guided=True))
        await pilot.pause()
        await pilot.click("#rs-change")
        await pilot.pause()
        assert app.screen.query_one("#rs-roles").display
        assert not app.screen.query_one("#rs-summary-row").display


async def test_with_no_roles_yet_guided_setup_shows_the_pickers(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: False)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        app.push_screen(RelaySetupScreen(tmp_path, guided=True))
        await pilot.pause()
        assert app.screen.query_one("#rs-roles").display
        assert not app.screen.query("#rs-summary-row")


async def test_the_run_button_fits_an_80_column_terminal(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        assert app.query_one("#relay-run", tui.Button).region.right <= 80


async def test_with_no_roles_the_pickers_hold_the_recommendation(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: False)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        app.push_screen(RelaySetupScreen(tmp_path, guided=True))
        await pilot.pause()
        screen = app.screen
        assert screen.query_one("#rs-implementer", tui.Select).value == "codex"
        assert screen.query_one("#rs-reviewer", tui.Select).value == "antigravity"
        assert "Recommended for the agents you have" in str(
            screen.query_one("#rs-recommended", tui.Static).renderable)
        assert str(screen.query_one("#rs-meaning", tui.Static).renderable) == (
            "codex writes the code → claude runs the tests → antigravity reviews; whyline commits; you do the release steps."
        )


async def test_a_configured_agent_that_is_not_usable_is_flagged(tmp_path, monkeypatch):
    from whyline import account

    status = {a: {"available": a != "antigravity", "label": "x"} for a in STATUS}
    monkeypatch.setattr(account, "agent_status", lambda root: status)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        app.push_screen(RelaySetupScreen(tmp_path, guided=True))
        await pilot.pause()
        screen = app.screen
        assert "⚠ antigravity isn't logged in" in str(
            screen.query_one("#rs-summary", tui.Static).renderable)
        assert screen.query_one("#rs-roles").display
        assert screen.query_one("#rs-implementer", tui.Select).value == "codex"
