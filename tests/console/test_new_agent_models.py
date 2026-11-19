import pytest
from textual.widgets import Button, Checkbox, Input, Select

from whyline import models
from whyline.agents import definitions as d, telegram
from whyline.console import tui
from whyline.console.agents_screens import (
    _DEFAULT_MODEL, _NO_MODEL, _OTHER_MODEL, _OTHER_VALUE,
    NewAgentScreen, ReviewScreen, _TextPromptScreen,
)

pytestmark = pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")

STATUS = {a: {"available": True, "label": "ok"} for a in ("claude", "codex", "grok", "antigravity")}
BASE = 'name="w"\ninstructions="x"\nrunner="claude"\nbackup=["codex"]\nworkdir="~"\n'


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    from whyline import account
    monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
    monkeypatch.setattr(telegram, "known_chats", lambda: {})
    return home


def _options(select: Select) -> list[tuple[str, str]]:
    return [(str(label), value) for label, value in select._options if value is not Select.BLANK]


async def _open(app, pilot, root, existing=None):
    app.push_screen(
        NewAgentScreen(root, STATUS, existing, is_edit=existing is not None),
        app._new_agent_done)
    await pilot.pause()
    return app.screen


@pytest.mark.asyncio
async def test_main_dropdown_options_and_order(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        s = await _open(app, pilot, tmp_path)
        cli = s.query_one("#na-runner", Select).value
        found = _options(s.query_one("#na-model", Select))
        assert found[0] == (_DEFAULT_MODEL, "")
        assert found[1:-1] == models.cached(cli)
        assert found[-1] == (_OTHER_MODEL, _OTHER_VALUE)
        assert s.query_one("#na-model", Select).value == ""


@pytest.mark.asyncio
async def test_backup_dropdown_follows_its_tick(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        s = await _open(app, pilot, tmp_path)
        assert s.query_one("#na-runner", Select).value == "claude"
        row = s.query_one("#na-model-row-codex")
        assert row.display is False
        s.query_one("#na-backup-codex", Checkbox).value = True
        await pilot.pause()
        assert row.display is True
        assert _options(s.query_one("#na-model-codex", Select))[1:-1] == models.cached("codex")
        s.query_one("#na-backup-codex", Checkbox).value = False
        await pilot.pause()
        assert row.display is False


@pytest.mark.asyncio
async def test_other_adds_and_selects(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        s = await _open(app, pilot, tmp_path)
        s.query_one("#na-model", Select).value = _OTHER_VALUE
        await pilot.pause()
        assert isinstance(app.screen, _TextPromptScreen)
        app.screen.query_one("#tp-input", Input).value = "bad id!"
        app.screen.query_one("#tp-add", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, _TextPromptScreen)
        app.screen.query_one("#tp-input", Input).value = "my-model-1"
        app.screen.query_one("#tp-add", Button).press()
        await pilot.pause()
        await pilot.pause()
        assert app.screen is s
        assert ("my-model-1", "my-model-1") in models.cached("claude")
        assert s.query_one("#na-model", Select).value == "my-model-1"
        assert '"claude" = "my-model-1"' in s._toml()[0]


@pytest.mark.asyncio
async def test_other_cancelled_goes_back(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        s = await _open(app, pilot, tmp_path)
        s.query_one("#na-model", Select).value = "sonnet"
        await pilot.pause()
        s.query_one("#na-model", Select).value = _OTHER_VALUE
        await pilot.pause()
        await pilot.click("#tp-cancel")
        await pilot.pause()
        assert s.query_one("#na-model", Select).value == "sonnet"


@pytest.mark.asyncio
async def test_main_cli_change_refills_with_its_saved_model(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        s = await _open(app, pilot, tmp_path)
        model = s.query_one("#na-model", Select)
        model.value = "sonnet"
        await pilot.pause()
        s.query_one("#na-runner", Select).value = "codex"
        await pilot.pause()
        assert _options(model)[1:-1] == models.cached("codex")
        assert model.value == ""
        model.value = "gpt-5.6"
        await pilot.pause()
        s.query_one("#na-runner", Select).value = "claude"
        await pilot.pause()
        assert _options(model)[1:-1] == models.cached("claude")
        assert model.value == "sonnet"
        s.query_one("#na-runner", Select).value = "codex"
        await pilot.pause()
        assert model.value == "gpt-5.6"


@pytest.mark.asyncio
async def test_refresh_keeps_the_selection(tmp_path, monkeypatch):
    calls = []

    def fake(cli, *, refresh=False, **kw):
        calls.append((cli, refresh))
        models.add(cli, f"{cli}-fresh")
        return models.cached(cli)

    monkeypatch.setattr(models, "options", fake)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        s = await _open(app, pilot, tmp_path)
        s.query_one("#na-backup-codex", Checkbox).value = True
        await pilot.pause()
        s.query_one("#na-model", Select).value = "haiku"
        s.query_one("#na-model-codex", Select).value = "gpt-5.6"
        await pilot.pause()
        s.query_one("#na-refresh-models", Button).press()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert sorted(calls) == [("claude", True), ("codex", True)]
        main = s.query_one("#na-model", Select)
        assert ("claude-fresh", "claude-fresh") in _options(main)
        assert main.value == "haiku"
        assert s.query_one("#na-model-codex", Select).value == "gpt-5.6"
        assert s.query_one("#na-refresh-models", Button).disabled is False


@pytest.mark.asyncio
async def test_cli_without_a_model_flag_is_disabled(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        s = await _open(app, pilot, tmp_path)
        s.query_one("#na-backup-grok", Checkbox).value = True
        await pilot.pause()
        grok = s.query_one("#na-model-grok", Select)
        assert grok.disabled is True
        assert _options(grok) == [(_NO_MODEL, "")]
        s.query_one("#na-runner", Select).value = "grok"
        await pilot.pause()
        assert s.query_one("#na-model", Select).disabled is True
        s.query_one("#na-runner", Select).value = "claude"
        await pilot.pause()
        assert s.query_one("#na-model", Select).disabled is False
        assert "[models]" not in s._toml()[0]


@pytest.mark.asyncio
async def test_edit_keeps_a_model_that_is_not_listed(tmp_path):
    path = tmp_path / "w.toml"
    defn = d.parse(
        BASE + '\n[models]\nclaude = "old-private-model"\ncodex = "gpt-5.6"\n',
        kind="personal", path=path)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        s = await _open(app, pilot, tmp_path, defn)
        main = s.query_one("#na-model", Select)
        assert main.value == "old-private-model"
        assert ("old-private-model", "old-private-model") in _options(main)
        assert s.query_one("#na-model-row-codex").display is True
        assert s.query_one("#na-model-codex", Select).value == "gpt-5.6"
        text = s._toml()[0]
        assert '"claude" = "old-private-model"' in text
        assert '"codex" = "gpt-5.6"' in text


@pytest.mark.asyncio
async def test_edit_of_an_old_model_line_is_written_back_as_it_was(tmp_path):
    path = tmp_path / "w.toml"
    defn = d.parse(
        'name="w"\ninstructions="x"\nrunner="claude"\nmodel="sonnet"\nworkdir="~"\n',
        kind="personal", path=path)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        s = await _open(app, pilot, tmp_path, defn)
        text = s._toml()[0]
        assert 'model = "sonnet"' in text
        assert "[models]" not in text


@pytest.mark.asyncio
async def test_review_lists_models_and_warns_about_an_unlisted_one(tmp_path):
    defn = d.parse(
        BASE + '\n[models]\nclaude = "sonnet"\n', kind="personal", path=tmp_path / "w.toml")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(ReviewScreen(defn, "Plain text.", True))
        await pilot.pause()
        body = app.screen._body()
        assert "Models: claude sonnet · codex default" in body
        assert "Warning" not in body

    odd = d.parse(
        BASE + '\n[models]\nclaude = "mystery-9"\n', kind="personal", path=tmp_path / "w.toml")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        screen = ReviewScreen(odd, "Plain text.", True)
        app.push_screen(screen)
        await pilot.pause()
        body = screen._body()
        assert "Models: claude mystery-9 · codex default" in body
        assert "Warning: mystery-9 is not in the list of claude models" in body
        assert screen.query_one("#rv-save")  # not blocked
