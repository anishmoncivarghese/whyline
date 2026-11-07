import time
import tomllib
from types import SimpleNamespace

import pytest
from textual.app import App
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Select, Static, TextArea

from whyline.console import tui
from whyline.console.release_screens import ReleaseChoice, ReleaseScreen, next_versions
from whyline.release import config as release_config
from whyline.release.config import ReleaseConfig
from whyline.release.ready import ReadyItem

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

GOOD = [ReadyItem("git", True, "git is installed"), ReadyItem("clean", True, "Working tree is clean")]
BAD = [ReadyItem("git", True, "git is installed"),
       ReadyItem("clean", False, "Working tree has changes", "Commit or stash them")]
STEPS = [("Check ready", False), ("Publish to PyPI", True)]


class Host(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen
        self.results = []

    def on_mount(self):
        self.push_screen(self._screen, self.results.append)


def _screen(items=GOOD, started=None, cfg=None, current="0.3.64"):
    started = [] if started is None else started
    return ReleaseScreen(
        "/tmp/none",
        start_release=started.append,
        config=cfg or ReleaseConfig(),
        current_version=current,
        ready_check=lambda version: items,
        steps=lambda version: STEPS,
    )


async def _wait_check(pilot):
    for _ in range(100):
        await pilot.pause()
        if not pilot.app.screen.query_one("#release-check", Button).disabled:
            return


def _text(app, widget_id):
    return str(app.screen.query_one(widget_id, Static).renderable)


async def test_next_versions():
    assert next_versions("0.3.64") == {
        "current": "0.3.64", "patch": "0.3.65", "minor": "0.4.0", "major": "1.0.0"}
    assert next_versions("1.0.0rc1") == {"current": "1.0.0rc1"}


async def test_version_choices_show_next_versions():
    app = Host(_screen())
    async with app.run_test() as pilot:
        await pilot.pause()
        text = _text(app, "#release-versions")
        assert "0.3.64" in text and "0.3.65" in text
        labels = [str(label) for label, _ in app.screen.query_one("#release-kind", Select)._options]
        assert any("0.3.65" in label for label in labels)
        assert any("0.4.0" in label for label in labels)
        assert any("1.0.0" in label for label in labels)
        assert "custom" in labels


async def test_mode_defaults_to_config():
    app = Host(_screen(cfg=ReleaseConfig(mode="auto")))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.query_one("#release-mode", Select).value == "auto"


async def test_check_lists_items_and_enables_start_when_all_pass():
    app = Host(_screen(GOOD))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.query_one("#release-start", Button).disabled
        app.screen.query_one("#release-check", Button).press()
        await _wait_check(pilot)
        text = _text(app, "#release-check-result")
        assert "✓ git is installed" in text and "✓ Working tree is clean" in text
        assert not app.screen.query_one("#release-start", Button).disabled


async def test_start_disabled_with_a_failed_item():
    app = Host(_screen(BAD))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one("#release-check", Button).press()
        await _wait_check(pilot)
        text = _text(app, "#release-check-result")
        assert "✗ Working tree has changes" in text and "Commit or stash them" in text
        assert app.screen.query_one("#release-start", Button).disabled


async def test_planned_steps_mark_irreversible_ones():
    app = Host(_screen())
    async with app.run_test() as pilot:
        await pilot.pause()
        lines = _text(app, "#release-steps").splitlines()
        publish = next(line for line in lines if "Publish to PyPI" in line)
        check = next(line for line in lines if "Check ready" in line)
        assert "⚠" in publish
        assert "⚠" not in check


async def test_start_passes_chosen_version_and_mode():
    started = []
    app = Host(_screen(GOOD, started))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one("#release-kind", Select).value = "minor"
        app.screen.query_one("#release-mode", Select).value = "step"
        await pilot.pause()
        app.screen.query_one("#release-check", Button).press()
        await _wait_check(pilot)
        app.screen.query_one("#release-start", Button).press()
        await pilot.pause()
        assert started == [ReleaseChoice("0.4.0", "step")]
        assert not isinstance(app.screen, ReleaseScreen)


async def test_changing_the_version_needs_a_new_check():
    app = Host(_screen(GOOD))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one("#release-check", Button).press()
        await _wait_check(pilot)
        app.screen.query_one("#release-kind", Select).value = "custom"
        await pilot.pause()
        app.screen.query_one("#release-custom", Input).value = "2.0.0"
        await pilot.pause()
        assert app.screen.query_one("#release-start", Button).disabled


# -- the Set up tab -----------------------------------------------------------


def _setup_screen(root, **kwargs):
    return ReleaseScreen(root, start_release=lambda choice: None,
                         current_version="0.3.64", steps=lambda v: STEPS, **kwargs)


def _proc(code=0, out="", err=""):
    return SimpleNamespace(returncode=code, stdout=out, stderr=err)


def _gh_run(calls, *, installed=True, auth=True, origin=""):
    def run(args, **kwargs):
        calls.append(list(args))
        if args[:3] == ["git", "remote", "get-url"]:
            return _proc(0, origin) if origin else _proc(2, "", "no origin")
        if args[:2] == ["gh", "--version"]:
            if not installed:
                raise FileNotFoundError("gh")
            return _proc(0, "gh 2.0")
        if args[:3] == ["gh", "auth", "status"]:
            return _proc(0 if auth else 1)
        if args[:2] == ["gh", "api"]:
            return _proc(0, "octocat")
        if args[:3] == ["gh", "repo", "create"]:
            return _proc(0, "https://github.com/octocat/x")
        return _proc(0)
    return run


async def _until(pilot, done):
    for _ in range(300):
        await pilot.pause()
        if done():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def _q(app, selector, kind):
    return app.screen.query_one(selector, kind)


def _shown(app, selector):
    return not app.screen.query_one(selector).has_class("-hidden")


async def test_set_up_prefills_from_detection_when_no_file(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1"\n')
    (tmp_path / "uv.lock").write_text("")
    app = Host(_setup_screen(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Suggested; press Save to keep" in _text(app, "#rs-source")
        assert _q(app, "#rs-t-github", Checkbox).value
        assert _q(app, "#rs-t-pypi", Checkbox).value
        assert not _q(app, "#rs-t-npm", Checkbox).value
        assert _q(app, "#rs-checks", TextArea).text == "uv run pytest -q"


async def test_set_up_loads_the_saved_file(tmp_path):
    release_config.save(tmp_path, ReleaseConfig(mode="auto", branch="dev"))
    app = Host(_setup_screen(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _text(app, "#rs-source") == ""
        assert _q(app, "#rs-mode", Select).value == "auto"
        assert _q(app, "#rs-branch", Input).value == "dev"


async def test_save_round_trips_through_config_save(tmp_path):
    app = Host(_setup_screen(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        _q(app, "#rs-mode", Select).value = "step"
        _q(app, "#rs-branch", Input).value = "trunk"
        _q(app, "#rs-after-plan", Checkbox).value = True
        _q(app, "#rs-checks", TextArea).text = "make test\n\n make lint \n"
        _q(app, "#rs-ci-ignore", TextArea).text = "docs"
        _q(app, "#rs-notes", Input).value = "notes/{version}.md"
        _q(app, "#rs-after", TextArea).text = "echo done"
        await pilot.pause()
        _q(app, "#rs-save", Button).press()
        await pilot.pause()
    assert release_config.load(tmp_path) == ReleaseConfig(
        mode="step", branch="trunk", start_after_plan=True,
        checks=("make test", "make lint"), ci_ignore=("docs",),
        notes="notes/{version}.md", after=("echo done",))
    assert tomllib.loads((tmp_path / ".whyline" / "release.toml").read_text())


async def test_ticking_a_target_ticks_github_and_says_why(tmp_path):
    release_config.save(tmp_path, ReleaseConfig(targets=release_config.Targets(github=False)))
    app = Host(_setup_screen(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not _q(app, "#rs-t-github", Checkbox).value
        _q(app, "#rs-t-pypi", Checkbox).value = True
        await pilot.pause()
        assert _q(app, "#rs-t-github", Checkbox).value
        assert "GitHub is ticked" in _text(app, "#rs-why")
        _q(app, "#rs-save", Button).press()
        await pilot.pause()
    targets = release_config.load(tmp_path).targets
    assert targets.github and targets.pypi


async def test_other_targets_say_part_2(tmp_path):
    app = Host(_setup_screen(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        _q(app, "#rs-setup-npm", Button).press()
        await pilot.pause()
        assert _text(app, "#rs-s-npm") == "Comes with release part 2"


async def test_closing_without_changes_does_not_ask(tmp_path):
    app = Host(_setup_screen(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        _q(app, "#release-close", Button).press()
        await pilot.pause()
        assert app.results == [None]


async def test_leaving_with_unsaved_changes_asks(tmp_path):
    app = Host(_setup_screen(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        _q(app, "#rs-branch", Input).value = "dev"
        await pilot.pause()
        _q(app, "#release-close", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, ReleaseScreen) and app.results == []
        assert _q(app, "#rs-confirm", Horizontal).display
        _q(app, "#rs-confirm-keep", Button).press()
        await pilot.pause()
        assert not _q(app, "#rs-confirm", Horizontal).display
        _q(app, "#release-close", Button).press()
        await pilot.pause()
        _q(app, "#rs-confirm-discard", Button).press()
        await pilot.pause()
        assert app.results == [None]
    assert not (tmp_path / ".whyline" / "release.toml").exists()


async def test_unsaved_guard_save_and_leave(tmp_path):
    app = Host(_setup_screen(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        _q(app, "#rs-branch", Input).value = "dev"
        await pilot.pause()
        _q(app, "#release-close", Button).press()
        await pilot.pause()
        _q(app, "#rs-confirm-save", Button).press()
        await pilot.pause()
        assert app.results == [None]
    assert release_config.load(tmp_path).branch == "dev"


async def test_sign_in_shows_the_one_time_code(tmp_path):
    go = []

    def streaming(args, stdin, on_line):
        assert args[:3] == ["gh", "auth", "login"]
        on_line("! First copy your one-time code: ABCD-1234")
        for _ in range(500):
            if go:
                break
            time.sleep(0.01)
        return 1

    app = Host(_setup_screen(tmp_path, gh_run=_gh_run([], auth=False),
                             gh_run_streaming=streaming))
    async with app.run_test() as pilot:
        await pilot.pause()
        _q(app, "#rs-setup-github", Button).press()
        await _until(pilot, lambda: _shown(app, "#rs-gh-signin"))
        _q(app, "#rs-gh-signin", Button).press()
        await _until(pilot, lambda: _shown(app, "#rs-gh-code"))
        assert "ABCD-1234" in _text(app, "#rs-gh-code")
        go.append(True)
        await _until(pilot, lambda: not _shown(app, "#rs-gh-code"))
        assert "Sign in failed" in _text(app, "#rs-gh-status")


async def test_missing_gh_shows_brew_hint_with_copy(tmp_path):
    app = Host(_setup_screen(tmp_path, gh_run=_gh_run([], installed=False)))
    async with app.run_test() as pilot:
        await pilot.pause()
        _q(app, "#rs-setup-github", Button).press()
        await _until(pilot, lambda: _shown(app, "#rs-gh-copy"))
        assert "brew install gh" in _text(app, "#rs-gh-install")
        copied = []
        app.copy_to_clipboard = copied.append
        _q(app, "#rs-gh-copy", Button).press()
        await pilot.pause()
        assert copied == ["brew install gh"]


async def test_create_choices_reach_create_repo(tmp_path):
    calls = []
    app = Host(_setup_screen(tmp_path, gh_run=_gh_run(calls)))
    async with app.run_test() as pilot:
        await pilot.pause()
        _q(app, "#rs-setup-github", Button).press()
        await _until(pilot, lambda: _shown(app, "#rs-gh-create-box"))
        assert _q(app, "#rs-gh-name", Input).value == tmp_path.name
        assert _q(app, "#rs-gh-visibility", Select).value == "private"
        _q(app, "#rs-gh-name", Input).value = "my-repo"
        _q(app, "#rs-gh-visibility", Select).value = "public"
        _q(app, "#rs-gh-description", Input).value = "A thing"
        await pilot.pause()
        _q(app, "#rs-gh-create", Button).press()
        await _until(pilot, lambda: any(c[:3] == ["gh", "repo", "create"] for c in calls))
    create = next(c for c in calls if c[:3] == ["gh", "repo", "create"])
    assert create[3] == "my-repo"
    assert "--public" in create and "--private" not in create
    assert create[create.index("--description") + 1] == "A thing"


async def test_ask_agent_shows_the_reply(tmp_path):
    prompts = []

    def chat(root, *, agent, prompt):
        prompts.append((agent, prompt))
        return SimpleNamespace(kind="output", text="[claude] Run gh auth login.")

    app = Host(_setup_screen(tmp_path, gh_run=_gh_run([], auth=False), chat_turn=chat,
                             agent="claude"))
    async with app.run_test() as pilot:
        await pilot.pause()
        _q(app, "#rs-setup-github", Button).press()
        await _until(pilot, lambda: _shown(app, "#rs-gh-signin"))
        _q(app, "#rs-gh-ask", Button).press()
        await _until(pilot, lambda: "Run gh auth login" in _text(app, "#rs-gh-reply"))
    assert prompts[0][0] == "claude"
    assert "signed in: False" in prompts[0][1]
    assert "do not run commands" in prompts[0][1]


async def test_refused_foreign_hook_shows_line_with_copy(tmp_path):
    import subprocess

    from whyline.security import hook

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / ".git" / "hooks" / "pre-commit"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho mine\n")
    app = Host(_setup_screen(tmp_path))
    copied = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app.copy_to_clipboard = copied.append
        assert "-hidden" in _q(app, "#rs-sec-hook-copy", Button).classes
        _q(app, "#rs-sec-pre-commit", Checkbox).value = True
        await pilot.pause()
        _q(app, "#rs-save", Button).press()
        await pilot.pause()
        assert hook.COMMAND in _text(app, "#rs-sec-hook-line")
        assert "-hidden" not in _q(app, "#rs-sec-hook-copy", Button).classes
        _q(app, "#rs-sec-hook-copy", Button).press()
        await pilot.pause()
    assert copied == [hook.COMMAND]
    assert path.read_text() == "#!/bin/sh\necho mine\n"


async def test_protection_rows_and_turn_on(tmp_path):
    calls = []
    state = {"on": False}
    base = _gh_run(calls, origin="git@github.com:o/r.git")

    def run(args, **kwargs):
        if args[:3] == ["gh", "api", "repos/o/r"] and "--jq" in args:
            status = "enabled" if state["on"] else "disabled"
            return _proc(0, '{"secret_scanning":{"status":"' + status + '"},'
                            '"secret_scanning_push_protection":{"status":"disabled"}}')
        if args[:3] == ["gh", "api", "repos/o/r/vulnerability-alerts"]:
            return _proc(0)
        if args[:4] == ["gh", "api", "-X", "PATCH"]:
            calls.append(list(args))
            state["on"] = True
            return _proc(0)
        return base(args, **kwargs)

    app = Host(_setup_screen(tmp_path, gh_run=run))
    async with app.run_test() as pilot:
        await pilot.pause()
        _q(app, "#rs-setup-github", Button).press()
        await _until(pilot, lambda: "Dependabot alerts: on" in
                     _text(app, "#rs-gh-prot-dependabot_alerts"))
        assert "second net" in _text(app, "#rs-gh-prot-note")
        assert "Secret scanning: off" in _text(app, "#rs-gh-prot-secret_scanning")
        assert _shown(app, "#rs-gh-prot-on-secret_scanning")
        assert not _shown(app, "#rs-gh-prot-on-dependabot_alerts")
        _q(app, "#rs-gh-prot-on-secret_scanning", Button).press()
        await _until(pilot, lambda: "Secret scanning: on" in
                     _text(app, "#rs-gh-prot-secret_scanning"))
    assert calls[-1][-1] == "security_and_analysis[secret_scanning][status]=enabled"


def _pypi_screen(tmp_path, statuses, opened=None, **kwargs):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "1.0.0"\n')

    def get(url):
        return statuses["project"]

    return _setup_screen(
        tmp_path, gh_run=_gh_run([], origin="git@github.com:octo/demo.git"),
        pypi_get=get, open_url=(opened.append if opened is not None else (lambda url: None)),
        **kwargs)


async def test_pypi_panel_lists_values_and_adds_workflow(tmp_path):
    app = Host(_pypi_screen(tmp_path, {"project": 404}))
    async with app.run_test() as pilot:
        await pilot.pause()
        _q(app, "#rs-setup-pypi", Button).press()
        await _until(pilot, lambda: "Owner" in _text(app, "#rs-pypi-status"))
        text = _text(app, "#rs-pypi-status")
        assert "Workflow: none yet" in text and "Project demo: not on PyPI yet" in text
        assert "Owner: octo" in text and "Repository: demo" in text
        assert "Workflow file name: release-pypi.yml" in text
        assert "Environment: pypi" in text and "Add a pending publisher" in text
        assert _shown(app, "#rs-pypi-add") and _shown(app, "#rs-pypi-open")
        _q(app, "#rs-pypi-add", Button).press()
        await _until(pilot, lambda: not _shown(app, "#rs-pypi-add"))
        assert "Workflow: .github/workflows/release-pypi.yml" in _text(app, "#rs-pypi-status")
        assert "Add a pending publisher" in _text(app, "#rs-pypi-status")
    assert (tmp_path / ".github" / "workflows" / "release-pypi.yml").is_file()


async def test_pypi_open_and_ask(tmp_path):
    opened, prompts = [], []

    def chat(root, *, agent, prompt):
        prompts.append(prompt)
        return SimpleNamespace(kind="output", text="Add a pending publisher.")

    app = Host(_pypi_screen(tmp_path, {"project": 200}, opened, chat_turn=chat, agent="claude"))
    async with app.run_test() as pilot:
        await pilot.pause()
        _q(app, "#rs-setup-pypi", Button).press()
        await _until(pilot, lambda: "Owner" in _text(app, "#rs-pypi-status"))
        assert "Project demo: on PyPI" in _text(app, "#rs-pypi-status")
        assert "pending publisher" not in _text(app, "#rs-pypi-status")
        _q(app, "#rs-pypi-open", Button).press()
        await pilot.pause()
        _q(app, "#rs-pypi-ask", Button).press()
        await _until(pilot, lambda: "pending publisher" in _text(app, "#rs-pypi-reply"))
    assert opened == ["https://pypi.org/manage/account/publishing/"]
    assert "Owner: octo" in prompts[0] and "do not run commands" in prompts[0]
