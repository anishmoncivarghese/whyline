import asyncio
import pytest

from whyline.console import relay_ops, tui

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


class FakeProcess:
    instances = []

    def __init__(self, root, args, *, on_line, on_exit, **kwargs):
        self.root, self.args = root, args
        self.on_line, self.on_exit = on_line, on_exit
        self.alive = False
        FakeProcess.instances.append(self)

    def start(self):
        self.alive = True

    def running(self):
        return self.alive

    def request_stop(self):
        pass

    def stop_following(self):
        pass

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


RELEASE_PAUSE_TEXT = (
    "release task for you: T-2\n"
    "1. Bump the version to 0.3.35 …\n"
    "2. Tag v0.3.35 and push …\n"
)


async def test_release_task_pause_shows_checklist_and_subtitle(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        proc = FakeProcess.instances[-1]
        await asyncio.to_thread(proc.finish, 3, RELEASE_PAUSE_TEXT)
        await pilot.pause()

        lines = _lines(app)
        assert any("⏸ T-2 is a release task for you:" in line for line in lines)
        assert any("1. Bump the version to 0.3.35 …" in line for line in lines)
        assert any("2. Tag v0.3.35 and push …" in line for line in lines)
        assert any('Type "done" when finished, or "skip".' in line for line in lines)
        assert "· release" in app.sub_title
        resume = app.query_one("#relay-resume", tui.Button)
        assert str(resume.label) == "Release done…"
        assert not resume.disabled


async def test_typing_done_launches_relay_done(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        proc = FakeProcess.instances[-1]
        await asyncio.to_thread(proc.finish, 3, RELEASE_PAUSE_TEXT)
        await pilot.pause()

        prompt = app.query_one("#prompt", tui.Input)
        prompt.value = "done"
        await pilot.press("enter")
        await pilot.pause()

        proc2 = FakeProcess.instances[-1]
        assert proc2.args == ["done", "T-2"]
        assert "· release" not in app.sub_title


async def test_typing_skip_launches_relay_skip(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        proc = FakeProcess.instances[-1]
        await asyncio.to_thread(proc.finish, 3, RELEASE_PAUSE_TEXT)
        await pilot.pause()

        prompt = app.query_one("#prompt", tui.Input)
        prompt.value = "skip"
        await pilot.press("enter")
        await pilot.pause()

        proc2 = FakeProcess.instances[-1]
        assert proc2.args == ["skip", "T-2"]
        assert "· release" not in app.sub_title


async def test_pressing_resume_behaves_like_typing_done(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        proc = FakeProcess.instances[-1]
        await asyncio.to_thread(proc.finish, 3, RELEASE_PAUSE_TEXT)
        await pilot.pause()

        await pilot.click("#relay-resume")
        await pilot.pause()

        proc2 = FakeProcess.instances[-1]
        assert proc2.args == ["done", "T-2"]
        assert any("done" in line for line in _lines(app))


# An agent that prints tui.py or a plan echoes the release marker into the
# run's output; only the relay's own final pause may start a release task.
ECHOED_MARKER = (
    'codex\n        if "release task for you: " in text:\n'
    '            pause_text = text[text.find("release task for you: "):]\n'
)


async def test_a_completed_run_that_echoed_the_marker_is_not_a_release(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        proc = FakeProcess.instances[-1]
        text = ECHOED_MARKER + "==> relay: ticked CB-5 in the plan\nPlan complete.\n"
        await asyncio.to_thread(proc.finish, 0, text)
        await pilot.pause()

        lines = _lines(app)
        assert not any('Type "done" when finished' in line for line in lines)
        assert "· release" not in app.sub_title
        assert app._release_task is None


async def test_a_pause_after_an_echoed_marker_is_an_ordinary_pause(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        proc = FakeProcess.instances[-1]
        text = ECHOED_MARKER + "\nPaused: CB-2 hit the 6-round cap\n"
        await asyncio.to_thread(proc.finish, 3, text)
        await pilot.pause()

        assert app._release_task is None
        assert "· release" not in app.sub_title


async def test_the_relays_own_release_pause_still_starts_a_release(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app._launch_relay(["start"])
        await pilot.pause()
        proc = FakeProcess.instances[-1]
        text = ECHOED_MARKER + "\nPaused: " + RELEASE_PAUSE_TEXT
        await asyncio.to_thread(proc.finish, 3, text)
        await pilot.pause()

        assert app._release_task is not None and app._release_task[0] == "T-2"
        assert "· release" in app.sub_title
