"""The context bar: agent, model, repo, all-repos, and Save."""
import os
import subprocess
from pathlib import Path

import pytest

from whyline.console import tui

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

# claude and codex available, grok unavailable (and antigravity, so the
# selector never depends on which CLIs happen to be installed).
_STATUS = {
    "claude": {"available": True, "label": "pro", "hint": None},
    "codex": {"available": True, "label": "plus", "hint": None},
    "antigravity": {
        "available": False,
        "label": "not installed",
        "hint": "Install antigravity, then /model refresh",
    },
    "grok": {"available": False, "label": "not signed in", "hint": "Run /login grok"},
}


@pytest.fixture(autouse=True)
def stub_agent_status(monkeypatch):
    from whyline import account

    monkeypatch.setattr(account, "agent_status", lambda root: _STATUS)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """HOME points at tmp. Path.home() ignores HOME on Windows."""
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))

    def _home(*_args):
        return Path(os.environ["HOME"])

    monkeypatch.setattr(Path, "home", _home)
    return folder


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".whyline").mkdir()
    return root


def _lines(app):
    return [str(line) for line in app._main("#transcript", tui.RichLog).lines]


async def test_save_is_greyed_until_something_changes(tmp_path):
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        save = app.query_one("#cb-save", tui.Button)
        assert save.disabled
        app.query_one("#cb-model", tui.Input).value = "gpt-5.6"
        await pilot.pause()
        assert not save.disabled


async def test_save_sets_the_repo_default_and_optionally_global(tmp_path, home):
    from whyline import model

    root = _repo(tmp_path)
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-agent", tui.Select).value = "codex"
        app.query_one("#cb-model", tui.Input).value = "gpt-5.6"
        app.query_one("#cb-global", tui.Checkbox).value = True
        await pilot.click("#cb-save")
        await pilot.pause()
        assert app.session.agent == "codex" and app.query_one("#cb-save", tui.Button).disabled
    assert model.resolve(root) == ("codex", "gpt-5.6")
    assert model.load_global()["default_agent"] == "codex"


async def test_an_unavailable_agent_snaps_back_with_its_hint(tmp_path):
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-agent", tui.Select).value = "!grok"
        await pilot.pause()
        assert app.query_one("#cb-agent", tui.Select).value == "claude"
        assert any("Run /login grok" in line for line in _lines(app))


async def test_switching_repo_is_refused_while_a_job_runs_but_agent_saves(tmp_path, monkeypatch):
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        monkeypatch.setattr(app, "_relay_running", lambda: True)
        app.query_one("#cb-agent", tui.Select).value = "codex"
        app.query_one("#cb-repo", tui.Input).value = str(tmp_path / "other")
        await pilot.click("#cb-save")
        await pilot.pause()
        assert app.session.agent == "codex" and app.session.root == tmp_path / "repo"
        assert any("Finish or stop the current job before switching repo" in line for line in _lines(app))


async def test_a_new_folder_is_set_up_after_one_confirmation(tmp_path, monkeypatch):
    from whyline.console import repo_setup

    ran = []
    monkeypatch.setattr(repo_setup, "setup", lambda insp, agents, progress: ran.append(insp.path) or insp.path)
    monkeypatch.setattr(
        tui, "switch_repo",
        lambda session, root: setattr(session, "root", root) or tui.SessionEvent(kind="output", text=f"Now in {root}"),
    )
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-repo", tui.Input).value = str(tmp_path / "fresh")
        await pilot.click("#cb-save")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        assert "git init" in str(app.screen.query_one("Label").renderable)
        await pilot.click("#confirm")
        for _ in range(50):
            if ran:
                break
            await pilot.pause(0.05)
    assert ran == [(tmp_path / "fresh").resolve()]


async def test_the_bar_fits_80_columns(tmp_path):
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(80, 24)) as pilot:
        assert app.query_one("#cb-save").region.right <= 80


def _status_grok_unavailable() -> dict:
    return {
        "claude": {"available": True, "label": "pro", "hint": None},
        "codex": {"available": True, "label": "plus", "hint": None},
        "antigravity": {
            "available": False,
            "label": "not installed",
            "hint": "Install antigravity, then /model refresh",
        },
        "grok": {"available": False, "label": "not signed in", "hint": "Run /login grok"},
    }


def _option_map(select) -> dict:
    return {
        value: str(prompt)
        for prompt, value in select._options
        if value is not tui.Select.BLANK
    }


async def test_model_refresh_updates_an_agent_that_becomes_available(tmp_path, monkeypatch):
    """/model refresh rewrites !agent once it is available, and a mode sync does not."""
    from whyline import account, model

    status = _status_grok_unavailable()
    monkeypatch.setattr(account, "agent_status", lambda root: status)

    def refresh():
        status["grok"] = {"available": True, "label": "pro", "hint": None}
        return {}

    monkeypatch.setattr(account, "refresh", refresh)
    root = _repo(tmp_path)
    model.set_default_agent(root, "grok")
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        select = app.query_one("#cb-agent", tui.Select)
        assert select.value == "!grok"
        assert _option_map(select)["!grok"] == "grok · not signed in"
        app.query_one("#cb-model", tui.Input).value = "grok-4"
        app.query_one("#cb-global", tui.Checkbox).value = True
        await pilot.pause()
        app.query_one("#prompt", tui.Input).value = "/route chat"
        await pilot.click("#send")
        await pilot.pause()
        assert select.value == "!grok"
        assert app.query_one("#cb-model", tui.Input).value == "grok-4"
        assert app.query_one("#cb-global", tui.Checkbox).value is True
        assert not app.query_one("#cb-save", tui.Button).disabled

        # A second click during Send's highlight is ignored.
        await pilot.pause(0.3)
        app.query_one("#prompt", tui.Input).value = "/model refresh"
        await pilot.click("#send")
        await pilot.pause()
        options = _option_map(select)
        assert select.value == "grok"
        assert options["grok"] == "grok · pro"
        assert "!grok" not in options
        assert "!antigravity" in options
        assert app.query_one("#cb-model", tui.Input).value == "grok-4"
        assert app.query_one("#cb-global", tui.Checkbox).value is True
        assert not app.query_one("#cb-save", tui.Button).disabled

        await pilot.pause(0.3)
        app.query_one("#prompt", tui.Input).value = "/route chat"
        await pilot.click("#send")
        await pilot.pause()
        assert select.value == "grok"
        assert app.query_one("#cb-model", tui.Input).value == "grok-4"


async def test_login_updates_an_agent_that_becomes_available(tmp_path, monkeypatch):
    """A login rechecks status and updates the same Select, edits included."""
    import contextlib
    import shutil

    from whyline import account, model

    status = _status_grok_unavailable()
    monkeypatch.setattr(account, "agent_status", lambda root: status)

    def refresh():
        status["grok"] = {"available": True, "label": "pro", "hint": None}
        return {}

    monkeypatch.setattr(account, "refresh", refresh)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    root = _repo(tmp_path)
    model.set_default_agent(root, "grok")
    app = tui.WhylineConsoleApp(root=root)

    @contextlib.contextmanager
    def fake_suspend():
        yield

    async with app.run_test(size=(120, 40)) as pilot:
        monkeypatch.setattr(app, "suspend", fake_suspend)
        app._login_fn = lambda argv: 0
        select = app.query_one("#cb-agent", tui.Select)
        assert select.value == "!grok"
        app.query_one("#cb-model", tui.Input).value = "grok-4"
        await pilot.pause()
        app.query_one("#prompt", tui.Input).value = "/login grok"
        await pilot.click("#send")
        await pilot.pause()
        options = _option_map(select)
        assert select.value == "grok"
        assert options["grok"] == "grok · pro"
        assert "!grok" not in options
        assert app.query_one("#cb-model", tui.Input).value == "grok-4"
        assert not app.query_one("#cb-save", tui.Button).disabled
