from pathlib import Path

import pytest

from whyline.console import relay_ops, tui
from whyline.console.relay_screens import RelayPlanScreen

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
        lambda root, text, replace=False: saved.append((text, replace)) or root / "plan.md",
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
    assert results == [tmp_path / "plan.md"]


async def test_paste_shows_why_an_invalid_plan_is_refused(tmp_path, monkeypatch):
    def refuse(root, text, replace=False):
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

    def save(root, text, replace=False):
        calls.append(replace)
        if not replace:
            raise PlanExists("plan.md already exists")
        return root / "plan.md"

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
    assert results == [tmp_path / "plan.md"]


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
        relay_ops, "save_pasted_plan", lambda root, text, replace=False: root / "plan.md"
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
        assert any("Saved plan.md" in line and "Set up" in line for line in lines)
