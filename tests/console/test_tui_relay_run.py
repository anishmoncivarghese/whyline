import asyncio
from pathlib import Path
import pytest
from whyline.console import relay_ops, tui
from whyline.console.relay_screens import RelayPlanScreen, RunChoiceScreen
pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]
class FakeProcess:
    """Stands in for RelayProcess. Its callbacks use call_from_thread, which
    Textual refuses on the app's own thread, so tests drive them through
    asyncio.to_thread, as the real follower thread would."""
    instances = []
    def __init__(self, root, args, *, on_line, on_exit, **kwargs):
        self.root, self.args = root, args
        self.on_line, self.on_exit = on_line, on_exit
        self.alive = False
        self.stopped = self.unfollowed = self.interrupted = False
        FakeProcess.instances.append(self)
    def start(self):
        self.alive = True
    def running(self):
        return self.alive
    def request_stop(self):
        self.stopped = True
    def interrupt(self):
        self.interrupted = True
    def stop_following(self):
        self.unfollowed = True
    def finish(self, code, text):
        self.alive = False
        self.on_exit(code, text)
@pytest.fixture(autouse=True)
def fake_relay(monkeypatch):
    FakeProcess.instances = []
    monkeypatch.setattr(tui, "RelayProcess", FakeProcess)
    monkeypatch.setattr(relay_ops, "live_run", lambda root: None)
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: ["x"])
async def _click_quit(app, pilot, button_id: str) -> None:
    """Press a quit-dialog button and wait until the app has been told to exit.

    Both buttons end in `app.exit()`. Anything that waits for the screen to
    drain after that (`pilot.pause()`, and `pilot.click()`, which pauses after
    each mouse event) races the shutdown: on windows-latest it hung for
    Textual's 30 s timeout in the 0.3.41 and 0.3.42 release runs. So press the
    button directly (the same `Button.Pressed` a click sends) and wait on
    `return_code`, which stays None until `exit()` runs."""
    app.screen.query_one(button_id, tui.Button).press()
    for _ in range(1000):
        if app.return_code is not None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{button_id} did not quit the app")


def _lines(app):
    return [str(line) for line in app._main("#transcript", tui.RichLog).lines]
async def _relay_mode(app, pilot):
    app.session.mode = "relay"
    app._sync_mode_indicator()
    await pilot.pause()
async def test_typed_start_streams_lines_and_reports_completion(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        prompt = app.query_one("#prompt", tui.Input)
        prompt.value = "start --only T3"
        await pilot.press("enter")
        await pilot.pause()
        proc = FakeProcess.instances[-1]
        assert proc.args == ["start", "--only", "T3"]
        await asyncio.to_thread(proc.on_line, "T3: codex implementing")
        await pilot.pause()
        assert any("relay · T3: codex implementing" in line for line in _lines(app))
        assert not app.query_one("#stop", tui.Button).disabled
        await asyncio.to_thread(proc.finish, 0, "Plan complete: 1 task(s)\n")
        await pilot.pause()
        assert any("Relay finished." in line for line in _lines(app))
        assert app.query_one("#stop", tui.Button).disabled
async def test_stop_interrupts_our_relay_now(tmp_path):
    # Stop means stop: the relay is interrupted like Ctrl+C, which cuts the
    # agent's turn off and saves a paused state that Resume carries on from.
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        await pilot.click("#stop")
        await pilot.pause()
        proc = FakeProcess.instances[-1]
        assert proc.interrupted and not proc.stopped
        assert any("Stopping the relay" in line for line in _lines(app))


async def test_stop_works_for_a_relay_another_console_started(tmp_path, monkeypatch):
    # A relay outlives the console that started it. The next console must
    # still see it and be able to stop it.
    live = {"run": "AG-2, grok"}
    interrupted = []
    monkeypatch.setattr(relay_ops, "live_run", lambda root: live["run"])
    monkeypatch.setattr(
        relay_ops, "interrupt_live_run", lambda root: interrupted.append(root) or True
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        stop = app.query_one("#stop", tui.Button)
        for _ in range(50):
            if not stop.disabled:
                break
            await pilot.pause(0.05)
        assert not stop.disabled
        await pilot.click("#stop")
        await pilot.pause()
        assert interrupted == [tmp_path]
        assert any("Stopping the relay (AG-2, grok)" in line for line in _lines(app))
        live["run"] = None
        for _ in range(50):
            if stop.disabled:
                break
            await pilot.pause(0.05)
        assert stop.disabled


async def test_start_is_refused_while_another_relay_runs_here(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "live_run", lambda root: "T3, codex")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        assert FakeProcess.instances == []
        assert any("already running here (T3, codex)" in line for line in _lines(app))
async def test_a_second_start_is_refused_while_ours_runs(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        app._launch_relay(["start"])
        await pilot.pause()
        assert len(FakeProcess.instances) == 1
async def test_a_pause_enables_resume(tmp_path, monkeypatch):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)
        await asyncio.to_thread(FakeProcess.instances[-1].finish, 3, "Paused: tests failed\n")
        await pilot.pause()
        assert not app.query_one("#relay-resume", tui.Button).disabled
async def test_quitting_while_the_relay_runs_asks_first(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        await app.action_quit()
        await pilot.pause()
        assert isinstance(app.screen, tui.QuitRelayScreen)
        await _click_quit(app, pilot, "#quit-leave")
    proc = FakeProcess.instances[-1]
    assert proc.unfollowed and not proc.stopped
async def test_quitting_while_the_relay_runs_stop_choice(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        await app.action_quit()
        await pilot.pause()
        assert isinstance(app.screen, tui.QuitRelayScreen)
        await _click_quit(app, pilot, "#quit-stop")
    proc = FakeProcess.instances[-1]
    assert proc.interrupted and proc.unfollowed
@pytest.mark.parametrize("button_id", ["#quit-leave", "#quit-stop"])
async def test_quitting_after_relay_finishes_while_modal_open_exits_safely(tmp_path, button_id):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        await app.action_quit()
        await pilot.pause()
        assert isinstance(app.screen, tui.QuitRelayScreen)
        proc = FakeProcess.instances[-1]
        await asyncio.to_thread(proc.finish, 0, "Plan complete: 1 task(s)\n")
        await pilot.pause()
        assert app._relay is None
        await _click_quit(app, pilot, button_id)


async def test_typed_start_without_any_plan_opens_plan_form(tmp_path, monkeypatch, installed_agents):
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: [])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app.query_one("#prompt", tui.Input).value = "start"
        await pilot.press("enter")
        await pilot.pause()
        assert FakeProcess.instances == []
        assert isinstance(app.screen, RelayPlanScreen)
        assert any("No plan yet -- let's make one." in line for line in _lines(app))


async def test_typed_start_with_plans_opens_run_choice_screen(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app.query_one("#prompt", tui.Input).value = "start"
        await pilot.press("enter")
        await pilot.pause()
        assert FakeProcess.instances == []
        assert isinstance(app.screen, RunChoiceScreen)


async def test_typed_start_with_plan_flag_launches_directly(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app.query_one("#prompt", tui.Input).value = "start --plan myplan.plan.md"
        await pilot.press("enter")
        await pilot.pause()
        proc = FakeProcess.instances[-1]
        assert proc.args == ["start", "--plan", "myplan.plan.md"]


async def test_a_stale_paused_run_offers_clear_instead_of_resume(tmp_path, monkeypatch):
    cleared = []
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)
    monkeypatch.setattr(relay_ops, "stale_pause", lambda root: "CRS-4")
    monkeypatch.setattr(relay_ops, "clear_pause", lambda root: cleared.append(root))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        button = app.query_one("#relay-resume", tui.Button)
        assert str(button.label) == "Clear old run" and not button.disabled
        await pilot.click("#relay-resume")
        await pilot.pause()
        assert cleared == [tmp_path] and FakeProcess.instances == []
        assert any("Cleared the finished run CRS-4." in line for line in _lines(app))


async def test_change_agents_opens_setup_from_a_pause(
    tmp_path, monkeypatch, installed_agents
):
    from whyline.console.relay_screens import RelaySetupScreen

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)
        await asyncio.to_thread(FakeProcess.instances[-1].finish, 3, "Paused: tests failed\n")
        await pilot.pause()

        change_btn = app.query_one("#pause-change-agents", tui.Button)
        assert change_btn.display
        await pilot.click("#pause-change-agents")
        for _ in range(100):
            await pilot.pause(0.05)
            if isinstance(app.screen, RelaySetupScreen):
                break

        assert isinstance(app.screen, RelaySetupScreen)
        assert app.screen._paused


async def test_resume_in_setup_saves_and_then_resumes(tmp_path, monkeypatch):
    import subprocess
    from whyline.console.relay_screens import RelaySetupScreen
    from whyline_relay import failover

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    plan_file = tmp_path / "plans" / "myplan.plan.md"
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text("- [ ] AGS-3: Test task\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

    failover.write_override(
        tmp_path, "implementer", failover.ActiveOverride("claude", "grok", "rate-limit", "2026-10-21T10:00:00")
    )
    plans = [
        relay_ops.PlanInfo(Path(tmp_path / "plans/myplan.plan.md"), "myplan", "draft", "2026-10-21T10:00:00", 0, 1)
    ]
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: plans)
    monkeypatch.setattr(relay_ops, "select_plan", lambda *a: None)
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "grok",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["claude"],
        },
    )
    monkeypatch.setattr(
        relay_ops,
        "run_checks",
        lambda root, plan=None: [relay_ops.CheckLine("ok", "ok message")],
    )

    def do_save(root, i, t, r, b):
        return relay_ops.clear_stale_switches(
            root,
            saved={
                "implementer": ("grok", i),
                "tester": ("codex", t),
                "reviewer": ("claude", r),
            },
        )

    monkeypatch.setattr(relay_ops, "save_roles", do_save)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)
        await asyncio.to_thread(FakeProcess.instances[-1].finish, 3, "Paused: limit hit\n")
        await pilot.pause()

        app.query_one("#pause-change-agents", tui.Button).press()
        await pilot.pause()
        assert isinstance(app.screen, RelaySetupScreen)
        screen = app.screen

        screen.query_one("#rs-implementer", tui.Select).value = "antigravity"
        await pilot.pause()
        await pilot.click("#rs-check")
        for _ in range(50):
            if not screen.query_one("#rs-start", tui.Button).disabled:
                break
            await pilot.pause(0.05)
        assert not screen.query_one("#rs-start", tui.Button).disabled
        assert str(screen.query_one("#rs-start", tui.Button).label) == "Resume"

        await pilot.click("#rs-start")
        await pilot.pause()

        assert not isinstance(app.screen, RelaySetupScreen)
        lines = _lines(app)
        assert any("implementer was on backup claude; it now uses antigravity" in l for l in lines)
        assert FakeProcess.instances[-1].args[0] == "resume"


async def test_resume_allow_dirty_with_space_gets_hint(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        prompt = app.query_one("#prompt", tui.Input)
        prompt.value = "resume --allow dirty"
        await pilot.press("enter")
        await pilot.pause()
        lines = _lines(app)
        assert any("Did you mean --allow-dirty?" in l for l in lines)
        assert len(FakeProcess.instances) == 0


async def test_resume_passes_allow_dirty_when_task_draft_in_tree(tmp_path, monkeypatch):
    from whyline_relay import gitcheck, state as relay_state
    from whyline_relay.state import RelayState

    plan_file = tmp_path / "plans" / "myplan.plan.md"
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text("- [ ] AGS-3: Test task\n")

    state = RelayState(
        task_id="AGS-3",
        branch="relay/myplan",
        plan="plans/myplan.plan.md",
        paused_reason="Paused: fail",
        round=1,
        log_path="",
        base_commit="abc",
    )
    relay_state.save(tmp_path, state)
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)
    monkeypatch.setattr(gitcheck, "dirty_paths", lambda root: ["src/code.py"])

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._setup_done(("resume", []))
        await pilot.pause()
        assert FakeProcess.instances[-1].args == ["resume", "--allow-dirty"]




def _paused_at_visit_cap(root, monkeypatch, dirty, handoff_files):
    from whyline import events, ledger, paths
    from whyline_relay import gitcheck, state as relay_state
    from whyline_relay.state import RelayState

    relay_state.save(root, RelayState(
        task_id="RSV-2",
        branch="relay/myplan",
        plan="plans/myplan.plan.md",
        paused_reason="RSV-2 hit stage 'draft''s 3-visit cap without reaching \"@complete\"",
        round=1,
        log_path="",
        base_commit="abc",
    ))
    ledger.append(paths.ledger_path(root), events.new_event(
        events.HANDOFF, task="RSV-2", from_actor="claude", to_actor="codex",
        status="ready", files=handoff_files,
    ))
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)
    monkeypatch.setattr(gitcheck, "dirty_paths", lambda root: list(dirty))


async def _press_retry_stage(app, pilot):
    app.on_button_pressed(tui.Button.Pressed(app._main("#relay-retry-stage", tui.Button)))
    await pilot.pause()


async def test_retry_stage_keeps_the_capped_task_s_own_changes(tmp_path, monkeypatch):
    _paused_at_visit_cap(
        tmp_path, monkeypatch, ["src/a.py", ".whyline/relay/state.json"], ["src/a.py"]
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        await _press_retry_stage(app, pilot)
        assert FakeProcess.instances[-1].args == ["resume", "--retry-stage", "--allow-dirty"]


async def test_retry_stage_names_an_unrelated_dirty_file_and_leaves_the_flag_off(
    tmp_path, monkeypatch
):
    _paused_at_visit_cap(tmp_path, monkeypatch, ["src/a.py", "notes.txt"], ["src/a.py"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        await _press_retry_stage(app, pilot)
        assert FakeProcess.instances[-1].args == ["resume", "--retry-stage"]
        transcript = " ".join(
            line.text.strip() for line in app._main("#transcript", tui.RichLog).lines
        )
        assert "unrelated uncommitted files block it: notes.txt" in transcript


async def test_retry_stage_on_a_clean_tree_has_no_flag(tmp_path, monkeypatch):
    _paused_at_visit_cap(tmp_path, monkeypatch, [], ["src/a.py"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        await _press_retry_stage(app, pilot)
        assert FakeProcess.instances[-1].args == ["resume", "--retry-stage"]
        assert not any("unrelated uncommitted" in line for line in _lines(app))


# ASK-1: Ask agent at every pause.


def _git_repo(path: Path, config: str) -> None:
    import subprocess

    for args in (
        ["init", "-q"],
        ["config", "user.name", "Test"],
        ["config", "user.email", "test@test.local"],
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    relay = path / ".whyline" / "relay"
    relay.mkdir(parents=True)
    (relay / "config.toml").write_text(config, encoding="utf-8")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True, capture_output=True)


def _sticky_switch(monkeypatch) -> None:
    """A sticky-switch pause whose only rule-based fix is not recommended."""
    from whyline.console import recovery

    problem = recovery.Problem(
        id="sticky-switch",
        summary="implementer is still switched to claude",
        evidence=["implementer: antigravity -> claude"],
        options=[
            recovery.Option("switch-back", "Switch back anyway", "roles reset implementer",
                            recommended=False, confirm=False),
            recovery.Option("show", "Show evidence", "print the evidence again",
                            recommended=False, confirm=False),
            recovery.Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
        ],
    )
    monkeypatch.setattr(recovery, "_rule_problems", lambda root, fails, reason: [problem])


async def _ask_and_wait(app, pilot) -> None:
    await pilot.click("#resolve-ask-agent")
    await pilot.pause()
    for _ in range(300):  # 15 s ceiling; Windows git is slow
        if not getattr(app, "_resolve_running", False):
            break
        await pilot.pause(0.05)
    await pilot.pause()


async def test_ask_agent_is_offered_at_a_sticky_switch_pause(tmp_path, monkeypatch):
    _git_repo(tmp_path, 'plan = "plan.md"\n[roles]\nimplementer = "codex"\n')
    _sticky_switch(monkeypatch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._start_resolve_flow(source="resume", fail_lines=[])
        await pilot.pause()
        ids = [b.id for b in app._main("#resolve-actions").query(tui.Button)]
        # Recommended first; with no recommended fix, that is Ask agent.
        assert ids == ["resolve-ask-agent", "resolve-switch-back", "resolve-show", "resolve-cancel"]
        assert any("Ask agent (recommended)" in line for line in _lines(app))


async def test_ask_agent_limit_on_first_agent_falls_to_backup_and_says_so(tmp_path, monkeypatch):
    _git_repo(
        tmp_path,
        'plan = "plan.md"\n[backup]\nchain = ["claude"]\n'
        '[roles]\nimplementer = "codex"\nreviewer = "claude"\n',
    )
    _sticky_switch(monkeypatch)
    called = []

    def fake_runner(command, prompt, **kwargs):
        called.append(kwargs["agent_name"])
        if kwargs["agent_name"] == "codex":
            return "ERROR: You've hit your usage limit.\n"
        return "EXPLANATION: Claude looked.\nRECOMMEND: wait\n"

    app = tui.WhylineConsoleApp(root=tmp_path, runner=fake_runner)
    app.session.agent = "codex"
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._start_resolve_flow(source="resume", fail_lines=[])
        await pilot.pause()
        await _ask_and_wait(app, pilot)
        assert called == ["codex", "claude"]
        lines = _lines(app)
        assert any("Asking codex to analyse the problem" in line for line in lines)
        assert any("codex hit a usage limit; asking claude" in line for line in lines)
        assert any("Claude looked." in line for line in lines)
        assert app.query("#resolve-wait")


async def test_ask_agent_that_edits_a_file_is_refused_and_the_edit_reported(tmp_path, monkeypatch):
    _git_repo(tmp_path, 'plan = "plan.md"\n[roles]\nimplementer = "codex"\n')
    _sticky_switch(monkeypatch)

    def fake_runner(command, prompt, **kwargs):
        (tmp_path / "README.md").write_text("edited\n", encoding="utf-8")
        return "EXPLANATION: Done.\nRECOMMEND: wait\n"

    app = tui.WhylineConsoleApp(root=tmp_path, runner=fake_runner)
    app.session.agent = "codex"
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._start_resolve_flow(source="resume", fail_lines=[])
        await pilot.pause()
        await _ask_and_wait(app, pilot)
        lines = _lines(app)
        assert any("modified files: README.md" in line for line in lines)
        assert not app.query("#resolve-wait")
        # The rule-based fix is still there to press.
        assert app.query("#resolve-switch-back")
        assert app.query("#resolve-cancel")
