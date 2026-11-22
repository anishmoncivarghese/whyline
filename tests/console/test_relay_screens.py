import pytest

from whyline.console import relay_ops, tui
from whyline.console.relay_ops import RunRole
from whyline.console.relay_screens import RelaySetupScreen, RunAgentsScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

async def _until(pilot, condition, what):
    for _ in range(400):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what}")


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


def _models(**over):
    state = {
        "claude": relay_ops.RunModel("claude", "sonnet", "sonnet", False),
        "codex": relay_ops.RunModel("codex", "", "", False),
        "antigravity": relay_ops.RunModel("antigravity", "flash", "flash", False),
    }
    state.update(over)
    return state


OPTIONS = {
    "claude": [("opus", "opus"), ("sonnet", "sonnet")],
    "codex": [("gpt", "gpt")],
    "antigravity": [("flash", "flash")],
}


def _model_screen(tmp_path, model_calls, *, roles=None, models=None, fail=None):
    state = {
        "roles": roles
        if roles is not None
        else [
            RunRole("implementer", "claude", "claude", "", "", False),
            RunRole("tester", "antigravity", "antigravity", "", "", False),
            RunRole("reviewer", "claude", "claude", "", "", False),
        ],
        "models": models if models is not None else _models(),
        "running": "JOB-1",
    }

    def switch_model(agent, model, *, keep):
        model_calls.append((agent, model, keep))
        if fail and agent in fail:
            raise ValueError(fail[agent])
        return f"{agent} model → {model}"

    screen = RunAgentsScreen(
        tmp_path,
        "JOB-1",
        run_roles_fn=lambda: state["roles"],
        switch_fn=lambda role, agent, *, keep: f"{role} → {agent}",
        choices_fn=lambda: CHOICES,
        running_fn=lambda: state["running"],
        summary_fn=lambda: "Plan: p.md",
        models_fn=lambda: state["models"],
        cached_options_fn=lambda agent: OPTIONS.get(agent),
        options_fn=lambda agent: OPTIONS.get(agent),
        switch_model_fn=switch_model,
    )
    return screen, state


async def _save(pilot):
    pilot.app.screen.query_one("#ra-save").scroll_visible(animate=False)
    await pilot.pause()
    await pilot.click("#ra-save")
    await pilot.pause()
    await pilot.pause()


async def test_model_choice_saves_with_keep(tmp_path):
    calls = []
    screen, _ = _model_screen(tmp_path, calls)
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-model-implementer", tui.Select).value = "opus"
        await pilot.pause()
        await _save(pilot)
        assert calls == [("claude", "opus", True)]


async def test_model_choice_saves_without_keep(tmp_path):
    calls = []
    screen, _ = _model_screen(tmp_path, calls)
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-keep", tui.Checkbox).value = False
        screen.query_one("#ra-model-implementer", tui.Select).value = "opus"
        await pilot.pause()
        await _save(pilot)
        assert calls == [("claude", "opus", False)]


async def test_same_agent_rows_share_the_model(tmp_path):
    screen, _ = _model_screen(tmp_path, [])
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert screen.query_one("#ra-model-reviewer", tui.Select).value == "sonnet"
        screen.query_one("#ra-model-implementer", tui.Select).value = "opus"
        await pilot.pause()
        assert screen.query_one("#ra-model-reviewer", tui.Select).value == "opus"


async def test_changing_agent_fills_that_agents_models(tmp_path):
    screen, _ = _model_screen(tmp_path, [])
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert screen.query_one("#ra-model-tester", tui.Select).value == "flash"
        screen.query_one("#ra-tester", tui.Select).value = "claude"
        await pilot.pause()
        model = screen.query_one("#ra-model-tester", tui.Select)
        assert model.value == "sonnet"
        assert set(screen._model_choices("claude")) == {
            ("Default", ""),
            ("opus", "opus"),
            ("sonnet", "sonnet"),
            ("Other…", RunAgentsScreen.OTHER),
        }


async def test_model_choices_keep_provider_labels(tmp_path):
    screen, _ = _model_screen(tmp_path, [])
    labelled = [("Gemini Flash (fast)", "flash"), ("Gemini Pro (deep)", "pro")]
    screen._cached_options_fn = lambda agent: labelled
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        other = [("Other…", RunAgentsScreen.OTHER)]
        assert screen._model_choices("antigravity") == [("Default", "")] + labelled + other
        screen.query_one("#ra-tester", tui.Select).value = "codex"
        await pilot.pause()
        screen.query_one("#ra-tester", tui.Select).value = "antigravity"
        await pilot.pause()
        assert screen._model_choices("antigravity")[1] == ("Gemini Flash (fast)", "flash")


async def test_agent_error_still_applies_the_other_model(tmp_path):
    calls = []
    screen, _ = _model_screen(tmp_path, calls, fail={"claude": "claude is busy"})
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-model-implementer", tui.Select).value = "opus"
        screen.query_one("#ra-model-tester", tui.Select).value = "flash"
        screen._models["antigravity"] = relay_ops.RunModel("antigravity", "x", "x", False)
        await pilot.pause()
        await _save(pilot)
        assert ("claude", "opus", True) in calls
        assert ("antigravity", "flash", True) in calls
        assert "claude is busy" in str(screen.query_one("#ra-error", tui.Static).renderable)


async def test_pending_model_line_follows_the_refresh(tmp_path):
    screen, state = _model_screen(
        tmp_path,
        [],
        models=_models(claude=relay_ops.RunModel("claude", "opus", "sonnet", True)),
    )
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        text = str(screen.query_one("#ra-reason-implementer", tui.Static).renderable)
        assert "model now opus · applies from its next turn" in text
        state["models"] = _models(claude=relay_ops.RunModel("claude", "opus", "sonnet", False))
        screen._refresh()
        await pilot.pause(0.3)
        text = str(screen.query_one("#ra-reason-implementer", tui.Static).renderable)
        assert "applies from its next turn" not in text


async def test_screen_fits_80x24(tmp_path):
    roles = [
        RunRole("implementer", "claude", "claude", "", "", False),
        RunRole("tester", "antigravity", "claude", "usage limit", "00:14", True),
        RunRole("reviewer", "antigravity", "claude", "usage limit", "00:14", False),
    ]
    screen, _ = _model_screen(tmp_path, [], roles=roles)
    app = _Host(screen)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        for widget_id in (
            "#ra-save",
            "#ra-model-reviewer",
            "#ra-tester",
            "#ra-back-tester",
            "#ra-back-reviewer",
        ):
            widget = screen.query_one(widget_id)
            assert widget.display, widget_id
            widget.scroll_visible(animate=False)  # the window scrolls when taller than the screen
            await pilot.pause()
            region = widget.region
            assert region.right <= 80 and region.bottom <= 24, (widget_id, region)


async def test_summary_shows_switched_model(tmp_path, monkeypatch):
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "claude",
            "tester": "antigravity",
            "reviewer": "claude",
            "backup": [],
        },
    )
    monkeypatch.setattr(
        relay_ops, "read_agent_model", lambda root, agent: "sonnet" if agent == "claude" else ""
    )
    screen = RunAgentsScreen(
        tmp_path,
        "JOB-1",
        models_fn=lambda: {"claude": relay_ops.RunModel("claude", "opus", "sonnet", False)},
    )
    summary = screen._read_summary()
    assert "claude opus (was sonnet)" in summary


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
        await _until(pilot, lambda: isinstance(app.screen, RunAgentsScreen), "run agents open")
        titles = [str(w.renderable) for w in app.screen.query(tui.Label)]
        assert "Agents for this run · JOB-9" in titles
        app.screen.dismiss(None)
        await _until(pilot, lambda: not isinstance(app.screen, RunAgentsScreen), "run agents closed")
        # A click sent while the dismissed screen is still leaving can be lost.
        await _until(pilot, lambda: len(app.screen_stack) == 1, "back on the main screen")
        await pilot.pause()

        live["value"] = None
        await pilot.click("#relay-setup")
        await _until(pilot, lambda: isinstance(app.screen, RelaySetupScreen), "setup open")
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
    assert RunAgentsScreen.READ_ONLY == "The plan stays as it is while the relay runs."


# --- Set up labels agents that cannot run (SWP-2) ---

from types import SimpleNamespace  # noqa: E402

from whyline.console.chain_editor import OrderedChain, _ChainCheck  # noqa: E402

from .test_relay_setup_screen import _checks, _checks_text, _open, _wait_for, ops  # noqa: E402,F401

LIMITED = "out of quota until 2026-11-04 18:30"


def _readiness(monkeypatch):
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "agent_readiness",
        lambda root: [
            SimpleNamespace(agent="claude", ready=True, why=""),
            SimpleNamespace(agent="codex", ready=True, why=""),
            SimpleNamespace(agent="antigravity", ready=False, why=LIMITED),
        ],
    )


def _option_labels(select):
    return [str(prompt) for prompt, value in select._options if value is not tui.Select.BLANK]


async def test_limited_agent_label_carries_its_reason_and_ready_label_is_unchanged(
    tmp_path, monkeypatch, ops
):
    _readiness(monkeypatch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        for role in ("implementer", "tester", "reviewer"):
            labels = _option_labels(screen.query_one(f"#rs-{role}", tui.Select))
            assert f"antigravity — {LIMITED}" in labels
            assert "claude" in labels and "codex" in labels
        await pilot.pause()
        chain = screen.query_one("#rs-backup", OrderedChain)
        boxes = {b.agent_name: str(b.label) for b in chain.query(_ChainCheck)}
        assert boxes["antigravity"] == f"antigravity — {LIMITED}"
        assert boxes["claude"] == "claude"


async def test_saving_a_limited_implementer_makes_check_warn(tmp_path, monkeypatch, ops):
    _readiness(monkeypatch)
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    monkeypatch.setattr(relay_ops, "forget_antigravity_decline", lambda root: None)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rs-implementer", tui.Select).value = "antigravity"
        await pilot.click("#rs-check")
        await _wait_for(pilot, lambda: "warn" in _checks_text(screen), "the warning")
        text = _checks_text(screen)
        assert f"warn  implementer is antigravity, which is {LIMITED}" in text
        assert "tester is" not in text
    assert ops[0][0] == "antigravity"


# --- Timeout, round cap and backups in "Agents for this run" (LRV-2) ---

from whyline.console.chain_editor import OrderedChain  # noqa: E402


def _settings(**over):
    state = {
        "timeout": relay_ops.RunSetting("timeout", 30, 30, False),
        "rounds": relay_ops.RunSetting("rounds", 8, 8, False),
        "backup": relay_ops.RunSetting("backup", (), (), False),
    }
    state.update(over)
    return state


def _full_screen(tmp_path, log, *, settings=None, fail=None, refresh=None):
    fail = fail or {}
    state = {
        "roles": [
            RunRole("implementer", "claude", "claude", "", "", False),
            RunRole("tester", "antigravity", "antigravity", "", "", False),
            RunRole("reviewer", "claude", "claude", "", "", False),
        ],
        "models": _models(),
        "settings": settings if settings is not None else _settings(),
        "running": "JOB-1",
    }

    def call(name):
        def run(*args, keep):
            log.append((name, *args, keep))
            if name in fail:
                raise ValueError(fail[name])
            return f"{name} done"

        return run

    screen = RunAgentsScreen(
        tmp_path,
        "JOB-1",
        run_roles_fn=lambda: state["roles"],
        switch_fn=call("role"),
        choices_fn=lambda: CHOICES,
        running_fn=lambda: state["running"],
        summary_fn=lambda: "Plan: p.md",
        models_fn=lambda: state["models"],
        cached_options_fn=lambda agent: OPTIONS.get(agent),
        options_fn=lambda agent: OPTIONS.get(agent),
        switch_model_fn=call("model"),
        settings_fn=lambda: state["settings"],
        timeout_fn=call("timeout"),
        rounds_fn=call("rounds"),
        backup_fn=call("backup"),
        add_model_fn=lambda agent, model: log.append(("add", agent, model)),
        refresh_models_fn=refresh or (lambda agent: None),
    )
    return screen, state


def _text(screen, widget_id):
    return str(screen.query_one(widget_id, tui.Static).renderable)


async def test_save_applies_only_what_changed(tmp_path):
    log = []
    screen, _ = _full_screen(tmp_path, log)
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-timeout", tui.Input).value = "45"
        await pilot.pause()
        await _save(pilot)
        assert log == [("timeout", 45, True)]
        assert _text(screen, "#ra-timeout-was") == "was 30"

    log.clear()
    screen, _ = _full_screen(tmp_path, log, fail={"rounds": "round 6 is already running"})
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-model-implementer", tui.Select).value = "opus"
        screen.query_one("#ra-timeout", tui.Input).value = "45"
        screen.query_one("#ra-rounds", tui.Input).value = "5"
        await pilot.pause()
        await _save(pilot)
        assert log == [("model", "claude", "opus", True), ("timeout", 45, True), ("rounds", 5, True)]
        assert "round 6 is already running" in _text(screen, "#ra-error")


async def test_backup_order_and_a_backups_model_are_saved(tmp_path):
    log = []
    screen, _ = _full_screen(tmp_path, log)
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        chain = screen.query_one("#ra-chain", OrderedChain)
        chain.load(["codex", "antigravity"])
        await pilot.pause(0.5)
        chain._move("antigravity", -1)
        await pilot.pause(0.5)
        assert chain.order() == ["antigravity", "codex"]
        assert screen.query_one("#ra-brow-codex").display
        screen.query_one("#ra-bmodel-codex", tui.Select).value = "gpt"
        await pilot.pause()
        assert "Backups antigravity, codex from the next time one is needed" in _text(
            screen, "#ra-changes"
        )
        await _save(pilot)
        assert log == [("model", "codex", "gpt", True), ("backup", ["antigravity", "codex"], True)]


async def test_a_backup_holding_a_role_shows_its_roles_model(tmp_path):
    screen, _ = _full_screen(tmp_path, [])
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-chain", OrderedChain).load(["claude", "codex"])
        await pilot.pause(0.5)
        select = screen.query_one("#ra-bmodel-claude", tui.Select)
        assert select.value == "sonnet" and select.disabled
        assert _text(screen, "#ra-bnote-claude") == "same as its role"
        assert _text(screen, "#ra-bnote-codex") == ""


async def test_other_adds_the_model_and_selects_it(tmp_path):
    log = []
    screen, _ = _full_screen(tmp_path, log)
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-model-implementer", tui.Select).value = screen.OTHER
        await pilot.pause()
        box = screen.query_one("#ra-other", tui.Input)
        assert not box.has_class("-empty")
        box.value = "claude-opus-5-5"
        await box.action_submit()
        await pilot.pause()
        assert log == [("add", "claude", "claude-opus-5-5")]
        assert screen.query_one("#ra-model-implementer", tui.Select).value == "claude-opus-5-5"
        assert screen.query_one("#ra-model-reviewer", tui.Select).value == "claude-opus-5-5"
        await _save(pilot)
        assert log[-1] == ("model", "claude", "claude-opus-5-5", True)


async def test_refresh_models_keeps_each_selection(tmp_path):
    asked = []
    newer = [("newer", "newer"), ("opus", "opus"), ("sonnet", "sonnet")]

    def refresh(agent):
        asked.append(agent)
        return newer if agent == "claude" else None

    screen, _ = _full_screen(tmp_path, [], refresh=refresh)
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-model-implementer", tui.Select).value = "opus"
        await pilot.pause()
        screen._refresh_models()
        await _until(pilot, lambda: ("newer", "newer") in screen._model_choices("claude"), "list")
        assert sorted(asked) == ["antigravity", "claude", "codex"]
        assert screen.query_one("#ra-model-implementer", tui.Select).value == "opus"
        assert screen.query_one("#ra-model-tester", tui.Select).value == "flash"


async def test_summary_says_what_changes_and_when(tmp_path):
    screen, _ = _full_screen(tmp_path, [])
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-timeout", tui.Input).value = "45"
        screen.query_one("#ra-rounds", tui.Input).value = "5"
        screen.query_one("#ra-chain", OrderedChain).load(["codex", "antigravity"])
        await pilot.pause(0.5)
        assert _text(screen, "#ra-changes") == (
            "Timeout 45m from the next turn · Round cap 5 from the next check · "
            "Backups codex, antigravity from the next time one is needed"
        )


async def test_keep_unticked_passes_keep_false_everywhere(tmp_path):
    log = []
    screen, _ = _full_screen(tmp_path, log)
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-keep", tui.Checkbox).value = False
        screen.query_one("#ra-implementer", tui.Select).value = "codex"
        screen.query_one("#ra-model-tester", tui.Select).value = ""
        screen.query_one("#ra-chain", OrderedChain).load(["codex"])
        screen.query_one("#ra-timeout", tui.Input).value = "0"
        screen.query_one("#ra-rounds", tui.Input).value = "9"
        await pilot.pause(0.5)
        await _save(pilot)
        assert [entry[0] for entry in log] == ["role", "model", "backup", "timeout", "rounds"]
        assert all(entry[-1] is False for entry in log)


async def test_invalid_numbers_are_refused_and_the_rest_applies(tmp_path):
    log = []
    screen, _ = _full_screen(tmp_path, log)
    app = _Host(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen.query_one("#ra-timeout", tui.Input).value = "45"
        screen.query_one("#ra-rounds", tui.Input).value = "100"
        await pilot.pause()
        await _save(pilot)
        assert log == [("timeout", 45, True)]
        assert "Round cap must be" in _text(screen, "#ra-error")


async def test_full_screen_is_usable_at_80x24_by_scrolling(tmp_path):
    log = []
    screen, _ = _full_screen(tmp_path, log)
    app = _Host(screen)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        for widget_id in ("#ra-timeout", "#ra-rounds", "#ra-save"):
            widget = screen.query_one(widget_id)
            widget.scroll_visible(animate=False)
            await pilot.pause()
            region = widget.region
            assert region.right <= 80 and region.bottom <= 24, (widget_id, region)
        screen.query_one("#ra-rounds", tui.Input).value = "7"
        await pilot.pause()
        await _save(pilot)
        assert log == [("rounds", 7, True)]
