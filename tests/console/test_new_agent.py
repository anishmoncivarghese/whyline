import pytest

from whyline.agents import capabilities, state
from whyline.console import mac_input, tui
from whyline.console.agents_screens import NewAgentScreen, ReviewScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

STATUS = {a: {"available": True, "label": "ok"} for a in ("claude", "codex", "grok", "antigravity")}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    from whyline import account
    monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
    monkeypatch.setattr(mac_input, "available", lambda: True)
    return home


async def test_fill_review_and_save_a_repo_agent(tmp_path, monkeypatch):
    src = tmp_path / "repo" / "docs"
    src.mkdir(parents=True)
    monkeypatch.setattr(mac_input, "pick_files", lambda run=None: [src])
    app = tui.WhylineConsoleApp(root=tmp_path / "repo")
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path / "repo", STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        s.query_one("#na-name", tui.Input).value = "digest"
        s.query_one("#na-instructions").load_text("Summarise what changed.")
        s.query_one("#na-runner", tui.Select).value = "claude"
        s.query_one("#na-backup-codex", tui.Checkbox).value = True
        s.query_one("#na-when", tui.Select).value = "weekdays"
        await pilot.pause()
        s.query_one("#na-at", tui.Input).value = "07:00"
        await pilot.click("#na-add-sources")
        for _ in range(50):
            if "docs" in str(s.query_one("#na-sources-list").renderable):
                break
            await pilot.pause(0.05)
        await pilot.click("#na-next")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)
        assert "Every weekday at 07:00" in str(app.screen.query_one("#rv-text").renderable)
        await pilot.click("#rv-save")
        await pilot.pause()
    saved = tmp_path / "repo/.whyline/agents/digest.toml"
    text = saved.read_text()
    assert saved.exists() and 'backup = ["codex"]' in text
    assert 'sources = ["docs"]' in text
    assert state.all_activations(state.connect())[0].status == "active"


async def test_invalid_input_shows_the_reason_and_stays(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        app.screen.query_one("#na-name", tui.Input).value = "Bad Name"
        await pilot.click("#na-next")
        await pilot.pause()
        assert isinstance(app.screen, NewAgentScreen)
        assert "name" in str(app.screen.query_one("#na-error").renderable)


async def test_clis_not_cleared_for_unattended_are_marked(tmp_path, monkeypatch):
    monkeypatch.setattr(capabilities, "UNATTENDED_OK", frozenset({"claude"}))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 60)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        labels = dict(app.screen.query_one("#na-runner", tui.Select)._options)
        assert any("codex" in str(k) and "on demand only" in str(k) for k in labels)
