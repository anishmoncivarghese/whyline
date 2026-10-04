"""Every popup's main button must be reachable on a standard 80x24 terminal.
The fields scroll; the buttons stay pinned (a 1fr max-height does nothing in
an auto-height popup, which once pushed Start off-screen)."""
from pathlib import Path

import pytest

from whyline.console import mac_input, relay_ops, tui
from whyline.console.relay_screens import RelayPlanScreen, RelaySetupScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

STATUS = {a: {"available": True, "label": "ok"} for a in ("claude", "codex", "antigravity", "grok")}


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    from whyline import account

    monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
    monkeypatch.setattr(mac_input, "available", lambda: True)
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: None)
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: [])
    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok"])
    monkeypatch.setattr(relay_ops, "planner_agents", lambda root: ("codex", "claude"))
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: [
        relay_ops.PlanInfo(Path("/r/plans/a.plan.md"), "a", "draft", "2026-10-04T10:00:00+05:30", 0, 3)])
    monkeypatch.setattr(relay_ops, "configured_plan", lambda root: None)
    monkeypatch.setattr(relay_ops, "current_roles", lambda root: {
        "implementer": "codex", "tester": "claude", "reviewer": "claude", "backup": ["grok"]})
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: False)


async def _visible(make, button, source=None):
    app = tui.WhylineConsoleApp(root=Path.cwd())
    async with app.run_test(size=(80, 24)) as pilot:
        screen = make()
        app.push_screen(screen)
        await pilot.pause()
        if source:
            screen.query_one("#rp-source").value = source
            await pilot.pause()
        region = screen.query_one(button).region
        return region.height > 0 and region.bottom <= 24


async def test_brainstorm_start_fits():
    assert await _visible(lambda: tui.BrainstormScreen(STATUS, "claude"), "#bs-start")


@pytest.mark.parametrize("source", ["brainstorm", "draft", "paste"])
async def test_plan_go_fits(source):
    assert await _visible(lambda: RelayPlanScreen(Path.cwd(), STATUS, "claude"), "#rp-go", source)


@pytest.mark.parametrize("guided", [False, True])
async def test_setup_check_and_start_fit(guided):
    make = lambda: RelaySetupScreen(Path.cwd(), guided=guided)
    assert await _visible(make, "#rs-check")
    assert await _visible(make, "#rs-start")
