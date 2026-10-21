"""Updating whyline from the console: the PyPI check, Update…, and Restart."""

import json
from pathlib import Path

import pytest

from whyline import __version__, paths
from whyline.console import relay_ops, repl, tui, update
from whyline.console.session import SessionEvent

# conftest stubs these for every console test; this file tests the real ones.
REAL_CHECK = update.check
REAL_PROBLEM = update.install_problem

NOTES = "https://github.com/anishmoncivarghese/whyline/releases/tag/v{}"


def _pypi(*versions, yanked=(), urls=None) -> bytes:
    if urls is None:
        urls = {"Source": "https://github.com/anishmoncivarghese/whyline"}
    return json.dumps({
        "info": {"version": versions[-1] if versions else "", "project_urls": urls},
        "releases": {
            v: [{"filename": f"whyline-{v}.tar.gz", "yanked": v in yanked}] for v in versions
        },
    }).encode()


class Http:
    def __init__(self, body=None, error=None):
        self.body, self.error, self.calls = body, error, []

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        if self.error is not None:
            raise self.error
        return self.body


# check()

def test_newer_version_is_returned_with_its_notes_link():
    http = Http(_pypi("0.3.46", "0.3.47", "0.3.48"))
    info = REAL_CHECK("0.3.47", http=http)
    assert info == update.UpdateInfo("0.3.47", "0.3.48", NOTES.format("0.3.48"))
    assert http.calls == [("https://pypi.org/pypi/whyline/json", 5)]


def test_same_version_returns_none():
    assert REAL_CHECK("0.3.48", http=Http(_pypi("0.3.47", "0.3.48"))) is None


def test_yanked_and_prerelease_versions_are_skipped():
    http = Http(_pypi("0.3.47", "0.3.48", "0.3.49", "0.4.0rc1", yanked=("0.3.49",)))
    assert REAL_CHECK("0.3.47", http=http).version == "0.3.48"


def test_versions_compare_numerically():
    assert REAL_CHECK("0.3.9", http=Http(_pypi("0.3.9", "0.3.10"))).version == "0.3.10"


@pytest.mark.parametrize("http", [
    Http(error=OSError("no network")),
    Http(error=TimeoutError("timed out")),
    Http(b"<html>not json</html>"),
    Http(b"[1, 2]"),
    Http(json.dumps({"releases": "nonsense"}).encode()),
])
def test_no_network_or_bad_json_returns_none_and_never_raises(http):
    assert REAL_CHECK("0.3.47", http=http) is None


def test_check_runs_at_most_once_a_day():
    http = Http(_pypi("0.3.47", "0.3.48"))
    now = 1_000_000.0
    assert REAL_CHECK("0.3.47", http=http, now=now).version == "0.3.48"
    assert REAL_CHECK("0.3.47", http=http, now=now + 3600).version == "0.3.48"
    assert len(http.calls) == 1
    cache = paths.global_whyline_dir() / "update-check.json"
    assert json.loads(cache.read_text())["latest"] == "0.3.48"
    REAL_CHECK("0.3.47", http=http, now=now + 24 * 3600 + 1)
    assert len(http.calls) == 2


def test_a_failed_check_also_waits_a_day():
    http = Http(error=OSError("offline"))
    assert REAL_CHECK("0.3.47", http=http, now=10.0) is None
    assert REAL_CHECK("0.3.47", http=http, now=20.0) is None
    assert len(http.calls) == 1


def test_no_github_url_means_no_notes_link():
    info = REAL_CHECK("0.3.47", http=Http(_pypi("0.3.48", urls={})))
    assert info.version == "0.3.48" and info.notes_url is None


# install_problem() and install()

def test_uv_tool_install_has_no_problem(tmp_path):
    tools = tmp_path / "uv" / "tools"
    prefix = tools / "whyline"
    prefix.mkdir(parents=True)
    assert REAL_PROBLEM(which=lambda name: "/bin/uv", prefix=str(prefix),
                        tool_dir=lambda uv: tools) is None


def test_missing_uv_offers_no_update(tmp_path):
    problem = REAL_PROBLEM(which=lambda name: None, prefix=str(tmp_path / "venv"),
                           tool_dir=lambda uv: tmp_path)
    assert problem and "pip" in problem


def test_non_uv_install_says_how_it_was_installed(tmp_path):
    prefix = tmp_path / "pipx" / "venvs" / "whyline"
    prefix.mkdir(parents=True)
    problem = REAL_PROBLEM(which=lambda name: "/bin/uv", prefix=str(prefix),
                           tool_dir=lambda uv: tmp_path / "uv-tools")
    assert problem == "whyline was installed with pipx. Run: pipx upgrade whyline"


def test_source_checkout_says_so(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    problem = REAL_PROBLEM(which=lambda name: "/bin/uv", prefix=str(tmp_path / ".venv"),
                           tool_dir=lambda uv: tmp_path / "uv-tools")
    assert "source checkout" in problem


class FakeProcess:
    def __init__(self, lines, code):
        self.stdout = iter(lines)
        self._code = code

    def wait(self):
        return self._code


def test_install_runs_exactly_uv_tool_install_and_streams_output():
    seen, lines = [], []

    def popen(argv, **kwargs):
        seen.append((argv, kwargs))
        return FakeProcess(["Resolved 12 packages\n", "Installed whyline 0.3.48\n"], 0)

    assert update.install("0.3.48", on_line=lines.append, popen=popen) == 0
    argv, kwargs = seen[0]
    assert argv == ["uv", "tool", "install", "whyline@0.3.48"]
    assert "shell" not in kwargs
    assert lines == ["Resolved 12 packages", "Installed whyline 0.3.48"]


def test_install_without_uv_reports_and_returns_127():
    lines = []

    def popen(argv, **kwargs):
        raise FileNotFoundError("uv")

    assert update.install("0.3.48", on_line=lines.append, popen=popen) == 127
    assert lines and "Could not start uv" in lines[0]


# The console

tui_only = pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
INFO = update.UpdateInfo(__version__, "99.0.0", NOTES.format("99.0.0"))


class FakeInstall:
    def __init__(self, code=0, lines=("Resolved 3 packages", "Installed whyline")):
        self.code, self.lines, self.calls = code, lines, []

    def __call__(self, version, *, on_line, reinstall=False):
        self.calls.append((version, reinstall))
        for line in self.lines:
            on_line(line)
        return self.code


class Running:
    def running(self):
        return True


@pytest.fixture
def console(monkeypatch, tmp_path):
    """An app with a fake check, install and uv install method."""
    monkeypatch.setattr(relay_ops, "live_run", lambda root: None)

    def make(info=INFO, problem=None, install=None):
        monkeypatch.setattr(update, "check", lambda current, **_kw: info)
        monkeypatch.setattr(update, "install_problem", lambda **_kw: problem)
        app = tui.WhylineConsoleApp(root=tmp_path)
        app._update_install = install or FakeInstall()
        return app

    return make


def _transcript(app) -> str:
    return "\n".join(event.text for event in app.session.transcript)


async def _settle(pilot, app, until, tries=50):
    for _ in range(tries):
        await pilot.pause()
        if until():
            return
    raise AssertionError("never settled:\n" + _transcript(app))


@tui_only
@pytest.mark.asyncio
async def test_newer_version_shows_header_line_and_update_button(console):
    app = console()
    async with app.run_test(size=(140, 40)) as pilot:
        await _settle(pilot, app, lambda: app.query_one("#update").display)
        assert app.title == "whyline 99.0.0 is available"
        assert str(app.query_one("#update").label) == "Update…"
        assert not app.query_one("#update").disabled


@tui_only
@pytest.mark.asyncio
async def test_same_version_or_no_network_shows_nothing(console):
    app = console(info=None)
    async with app.run_test(size=(140, 40)) as pilot:
        for _ in range(5):
            await pilot.pause()
        assert "available" not in app.title
        assert not app.query_one("#update").display


@tui_only
@pytest.mark.asyncio
async def test_update_confirms_runs_install_streams_and_offers_restart(console):
    install = FakeInstall()
    app = console(install=install)
    async with app.run_test(size=(140, 40)) as pilot:
        await _settle(pilot, app, lambda: app.query_one("#update").display)
        assert install.calls == []  # nothing updates without the click
        await pilot.click("#update")
        await pilot.pause()
        confirm = app.screen
        text = str(confirm._message)
        assert __version__ in text and "99.0.0" in text and NOTES.format("99.0.0") in text
        await pilot.click("#confirm")
        await _settle(pilot, app, lambda: "Restart the console" in _transcript(app))
        assert install.calls == [("99.0.0", False)]
        shown = _transcript(app)
        assert "Running: uv tool install whyline@99.0.0" in shown
        assert "Resolved 3 packages" in shown and "Installed whyline" in shown
        assert "Restart the console to use 99.0.0." in shown
        assert app.query_one("#update-restart").display
        await pilot.click("#update-restart")
        await pilot.pause()
    assert app._exec_after == ("whyline", ["whyline", "console", "--ui"])


@tui_only
@pytest.mark.asyncio
async def test_cancel_installs_nothing(console):
    install = FakeInstall()
    app = console(install=install)
    async with app.run_test(size=(140, 40)) as pilot:
        await _settle(pilot, app, lambda: app.query_one("#update").display)
        await pilot.click("#update")
        await pilot.pause()
        await pilot.click("#cancel")
        await pilot.pause()
        assert install.calls == []


@tui_only
@pytest.mark.asyncio
async def test_failing_install_says_so_and_keeps_the_old_version(console):
    app = console(install=FakeInstall(code=2, lines=("error: no network",)))
    async with app.run_test(size=(140, 40)) as pilot:
        await _settle(pilot, app, lambda: app.query_one("#update").display)
        await pilot.click("#update")
        await pilot.pause()
        await pilot.click("#confirm")
        await _settle(pilot, app, lambda: "update failed" in _transcript(app))
        shown = _transcript(app)
        assert "error: no network" in shown
        assert f"whyline {__version__} is still installed" in shown
        assert "Restart the console" not in shown
        assert not app.query_one("#update-restart").display
        assert app.query_one("#update").display
    assert app._exec_after is None


@tui_only
@pytest.mark.asyncio
async def test_non_uv_install_offers_no_update_and_help_says_how(console):
    note = "whyline was installed with pipx. Run: pipx upgrade whyline"
    app = console(problem=note)
    async with app.run_test(size=(140, 40)) as pilot:
        await _settle(pilot, app, lambda: app._update_note is not None)
        assert app.title == "whyline 99.0.0 is available"
        assert not app.query_one("#update").display
        await pilot.click("#help")
        await pilot.pause()
        assert note in _transcript(app)


@tui_only
@pytest.mark.asyncio
async def test_running_relay_disables_update(console, monkeypatch):
    install = FakeInstall()
    app = console(install=install)
    async with app.run_test(size=(140, 40)) as pilot:
        await _settle(pilot, app, lambda: app.query_one("#update").display)
        app._relay = Running()
        app._sync_update_button()
        await pilot.pause()
        button = app.query_one("#update")
        assert button.disabled
        assert button.tooltip == "Stop or finish the relay first"
        app._open_update()
        await pilot.pause()
        assert "Stop or finish the relay first" in _transcript(app)
        assert install.calls == []


@tui_only
@pytest.mark.asyncio
async def test_relay_started_elsewhere_also_disables_update(console, monkeypatch):
    app = console()
    async with app.run_test(size=(140, 40)) as pilot:
        await _settle(pilot, app, lambda: app.query_one("#update").display)
        monkeypatch.setattr(relay_ops, "live_run", lambda root: "TGS-4")
        app._sync_update_button()
        assert app.query_one("#update").disabled


@tui_only
@pytest.mark.asyncio
async def test_missing_relay_offers_reinstall_of_the_current_version(console):
    install = FakeInstall()
    app = console(info=None, install=install)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.render_event(SessionEvent(kind="error", text=repl._RELAY_MISSING))
        await pilot.pause()
        button = app.query_one("#update")
        assert button.display and str(button.label) == "Update…"
        await pilot.click("#update")
        await pilot.pause()
        await pilot.click("#confirm")
        await _settle(pilot, app, lambda: "Restart the console" in _transcript(app))
        assert install.calls == [(__version__, True)]
        assert f"uv tool install --reinstall whyline@{__version__}" in _transcript(app)


def test_missing_textual_offers_reinstall_then_restarts(monkeypatch, tmp_path):
    monkeypatch.setattr(tui, "TUI_AVAILABLE", False)
    install, printed, execs = FakeInstall(), [], []
    tui.launch(tmp_path, ask=lambda q: "y", print_fn=printed.append,
               install=install, problem=lambda: None,
               exec_fn=lambda binary, argv: execs.append((binary, argv)))
    assert install.calls == [(__version__, True)]
    assert execs == [("whyline", ["whyline", "console", "--ui"])]


def test_missing_textual_declined_or_non_uv_still_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(tui, "TUI_AVAILABLE", False)
    install = FakeInstall()
    with pytest.raises(tui.TuiUnavailable, match="reinstall whyline"):
        tui.launch(tmp_path, ask=lambda q: "n", install=install, problem=lambda: None)
    with pytest.raises(tui.TuiUnavailable):
        tui.launch(tmp_path, ask=lambda q: "y", install=install, problem=lambda: "pipx")
    assert install.calls == []


class Prompts:
    def __init__(self, *answers):
        self.answers = list(answers)

    def prompt(self, _text):
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)


def test_repl_missing_relay_offers_reinstall(monkeypatch, tmp_path):
    monkeypatch.setattr(
        repl, "dispatch",
        lambda session, text: SessionEvent(kind="error", text=repl._RELAY_MISSING, accepted=False),
    )
    install, printed, execs = FakeInstall(), [], []
    repl.run(tmp_path, print_fn=printed.append, prompt_session=Prompts("hello", "y"),
             exec_fn=lambda binary, argv: execs.append((binary, argv)),
             install_fn=install, problem_fn=lambda: None)
    assert install.calls == [(__version__, True)]
    assert "Installed whyline" in printed
    assert execs == [("whyline", ["whyline", "console"])]


def test_repl_failed_reinstall_keeps_the_console(monkeypatch, tmp_path):
    monkeypatch.setattr(
        repl, "dispatch",
        lambda session, text: SessionEvent(kind="error", text=repl._RELAY_MISSING, accepted=False),
    )
    printed, execs = [], []
    repl.run(tmp_path, print_fn=printed.append, prompt_session=Prompts("hello", "y"),
             exec_fn=lambda binary, argv: execs.append((binary, argv)),
             install_fn=FakeInstall(code=1), problem_fn=lambda: None)
    assert execs == []
    assert any("update failed" in line for line in printed)
