import pytest

from whyline.console import relay_ops, tui
from whyline.console.relay_ops import RunRole
from whyline.console.relay_screens import RelaySetupScreen, RunAgentsScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

CHOICES = ["antigravity", "claude", "codex"]


def _roles(reviewer_current="antigravity"):
    return [
        RunRole("implementer", "claude", "claude", "", "", False),
        RunRole("tester", "codex", "codex", "", "", False),
        RunRole(
            "reviewer",
            "codex",
            reviewer_current,
            "" if reviewer_current == "codex" else "usage limit",
            "" if reviewer_current == "codex" else "00:14",
            False,
        ),
    ]


class _Host(tui.App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen
        self.events = []

    def on_mount(self):
        self.push_screen(self._screen)

    def render_event(self, event):
        self.events.append(event.text)


def _screen(tmp_path, calls, *, roles=None, running=lambda: "JOB-1", fail=None):
    state = {"roles": roles if roles is not None else _roles()}

    def switch(role, agent, *, keep):
        calls.append((role, agent, keep))
        if fail:
            raise ValueError(fail)
        return f"{role} → {agent} from its next turn."

    screen = RunAgentsScreen(
        tmp_path,
        "JOB-1",
        run_roles_fn=lambda: state["roles"],
        switch_fn=switch,
        choices_fn=lambda: CHOICES,
        running_fn=running,
        summary_fn=lambda: "Plan: p.md",
    )
    return screen, state


async def test_shows_rows_and_back_only_for_switched_role(tmp_path):
    screen, _ = _screen(tmp_path, [])
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert screen.query_one("#ra-reviewer", tui.Select).value == "antigravity"
        assert screen.query_one("#ra-back-reviewer", tui.Button).display
        assert not screen.query_one("#ra-back-tester", tui.Button).display
        assert str(screen.query_one("#ra-back-reviewer", tui.Button).label) == "Back to codex"
        assert screen.query_one("#ra-keep", tui.Checkbox).value is True


async def test_back_to_configured_calls_switch_with_keep(tmp_path):
    calls = []
    screen, _ = _screen(tmp_path, calls)
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#ra-back-reviewer")
        await pilot.pause()
        await pilot.pause()
        assert calls == [("reviewer", "codex", True)]
        assert "reviewer → codex from its next turn." in app.events
        assert screen.is_attached  # stays open


async def test_save_applies_only_changed_roles(tmp_path):
    calls = []
    screen, _ = _screen(tmp_path, calls)
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-implementer", tui.Select).value = "codex"
        screen.query_one("#ra-tester", tui.Select).value = "claude"
        await pilot.pause()
        await pilot.click("#ra-save")
        await pilot.pause()
        await pilot.pause()
        assert calls == [("implementer", "codex", True), ("tester", "claude", True)]


async def test_unticking_keep_passes_keep_false(tmp_path):
    calls = []
    screen, _ = _screen(tmp_path, calls)
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-keep", tui.Checkbox).value = False
        screen.query_one("#ra-implementer", tui.Select).value = "codex"
        await pilot.pause()
        await pilot.click("#ra-save")
        await pilot.pause()
        await pilot.pause()
        assert calls == [("implementer", "codex", False)]


async def test_error_keeps_the_dialog_open(tmp_path):
    calls = []
    screen, _ = _screen(tmp_path, calls, fail="grok is not set up for this relay")
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-implementer", tui.Select).value = "codex"
        await pilot.pause()
        await pilot.click("#ra-save")
        await pilot.pause()
        await pilot.pause()
        assert screen.is_attached
        assert app.screen is screen
        assert "not set up" in str(screen.query_one("#ra-error", tui.Static).renderable)
        assert not screen.query_one("#ra-save", tui.Button).disabled


async def test_refresh_shows_a_failover_and_stop(tmp_path):
    running = {"value": "JOB-1"}
    screen, state = _screen(
        tmp_path, [], roles=_roles("codex"), running=lambda: running["value"]
    )
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not screen.query_one("#ra-back-reviewer", tui.Button).display
        state["roles"] = _roles("antigravity")
        screen._refresh()
        await pilot.pause(0.3)
        assert screen.query_one("#ra-back-reviewer", tui.Button).display
        assert screen.query_one("#ra-reviewer", tui.Select).value == "antigravity"

        running["value"] = None
        screen._refresh()
        await pilot.pause(0.3)
        assert screen.STOPPED in str(screen.query_one("#ra-status", tui.Static).renderable)
        assert screen.query_one("#ra-save", tui.Button).disabled


async def test_set_up_opens_run_agents_while_running_and_setup_when_idle(
    tmp_path, monkeypatch, installed_agents
):
    interrupted = []
    monkeypatch.setattr(relay_ops, "interrupt_live_run", lambda root: interrupted.append(root))
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)
    monkeypatch.setattr(relay_ops, "run_roles", lambda root: _roles())
    monkeypatch.setattr(relay_ops, "run_agent_choices", lambda root: CHOICES)
    # production contract: live_run returns "<task>, <agent>"
    live = {"value": "JOB-9, claude"}
    monkeypatch.setattr(relay_ops, "live_run", lambda root: live["value"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        app._sync_relay_buttons()
        await pilot.pause()
        assert not app.query_one("#relay-setup", tui.Button).disabled
        await pilot.click("#relay-setup")
        await pilot.pause()
        assert isinstance(app.screen, RunAgentsScreen)
        titles = [str(w.renderable) for w in app.screen.query(tui.Label)]
        assert "Agents for this run · JOB-9" in titles
        app.screen.dismiss(None)
        await pilot.pause()

        live["value"] = None
        await pilot.click("#relay-setup")
        await pilot.pause()
        assert isinstance(app.screen, RelaySetupScreen)
    assert interrupted == []


async def test_default_summary_reads_plan_steps(tmp_path, monkeypatch):
    plan = tmp_path / "p.plan.md"
    plan.write_text(
        "# P\n\n- [x] A-1: first\n  detail\n- [ ] A-2: second\n- [ ] A-3: third\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tui.relay_ops, "configured_plan", lambda root: plan)
    screen = RunAgentsScreen(tmp_path, "A-2")
    summary = screen._read_summary()
    assert "Plan: p.plan.md" in summary
    assert "Steps: 1 of 3 done" in summary
    assert "Stop the relay to change them." in RunAgentsScreen.READ_ONLY
