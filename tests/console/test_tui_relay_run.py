import asyncio
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
        await pilot.click("#quit-leave")
        await pilot.pause()
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
        await pilot.click("#quit-stop")
        await pilot.pause()
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
        await pilot.click(button_id)
        await pilot.pause()


async def test_typed_start_without_any_plan_opens_plan_form(tmp_path, monkeypatch):
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


