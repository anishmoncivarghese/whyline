import pytest

from whyline.agents import capabilities, telegram
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
    monkeypatch.setenv("USERPROFILE", str(home))
    from whyline import account
    monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
    monkeypatch.setattr(mac_input, "available", lambda: True)
    monkeypatch.setattr(telegram, "known_chats", lambda: {})
    return home


def _server(name="notion", *, enabled=True, tested=True):
    from whyline.tools import mcp_config
    from whyline.tools.mcp_config import Server, Tool

    tools = (Tool("search", read_only=True), Tool("create_page", read_only=False)) if tested else ()
    mcp_config.save_server(Server(name=name, command="x", enabled=enabled, tools=tools))


async def test_tool_picker_defaults_and_warning(tmp_path):
    from whyline.console.agents_screens import ToolPickScreen

    _server()
    _server("off", enabled=False)
    _server("fresh", tested=False)
    app = tui.WhylineConsoleApp(root=tmp_path)
    results = []
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(ToolPickScreen({}), results.append)
        await pilot.pause()
        s = app.screen
        assert len(s.query("Collapsible")) == 1  # only the enabled, tested server
        assert s.query_one("#tl-s-0", tui.Select).value == "allowed"  # search reads
        assert s.query_one("#tl-s-1", tui.Select).value == "ask"  # create_page writes
        assert not s.query_one("#tl-w-1").display
        s.query_one("#tl-s-1", tui.Select).value = "allowed"
        await pilot.pause()
        warning = s.query_one("#tl-w-1")
        assert warning.display
        assert "This tool can change things without asking you." in str(warning.renderable)
        s.query_one("#tl-c-0", tui.Checkbox).value = True
        s.query_one("#tl-c-1", tui.Checkbox).value = True
        await pilot.click("#tl-done")
        await pilot.pause()
    assert results == [{"notion.search": "allowed", "notion.create_page": "allowed"}]


async def test_skill_picker_shows_origin_and_size(tmp_path):
    from whyline.console.agents_screens import SkillPickScreen
    from whyline.tools import skills

    skills.create("notes", "Take notes", "Be brief.")
    app = tui.WhylineConsoleApp(root=tmp_path)
    results = []
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(SkillPickScreen(tmp_path, []), results.append)
        await pilot.pause()
        s = app.screen
        label = str(s.query_one("#sk-0", tui.Checkbox).label)
        assert "notes (whyline)" in label and "Take notes" in label
        assert str(skills.AGENT_SKILLS_LIMIT) in str(s.query_one("#sp-size").renderable)
        s.query_one("#sk-0", tui.Checkbox).value = True
        await pilot.pause()
        assert "Total size 0 " not in str(s.query_one("#sp-size").renderable)
        await pilot.click("#sk-done")
        await pilot.pause()
    assert results == [["whyline:notes"]]


async def test_each_section_saves_through_definitions(tmp_path):
    from whyline.agents import definitions as d
    from whyline.tools import knowledge, skills

    _server()
    skills.create("notes", "Take notes", "Be brief.")
    knowledge.save_pack(knowledge.Pack("company", "About us", ()))
    root = tmp_path / "repo"
    root.mkdir()
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(NewAgentScreen(root, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        s.query_one("#na-name", tui.Input).value = "helper"
        s.query_one("#na-instructions").load_text("Help.")
        s._page_done("https://example.com/a")
        s._packs_done(["pack:company"])
        s._skills_done(["whyline:notes"])
        s._tools_done({"notion.search": "allowed", "notion.create_page": "ask"})
        await pilot.pause()
        await pilot.click("#na-next")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)
        text = str(app.screen.query_one("#rv-text").renderable)
        assert "Can read: notion.search" in text
        assert "Can write: notion.create_page (ask first)" in text
        assert "Skills: notes (whyline)" in text
        assert 'Knowledge: 1 web page, pack "company"' in text
        await pilot.click("#rv-save")
        await pilot.pause()
    saved = d.load(root / ".whyline/agents/helper.toml", kind="repo", repo_root=root)
    assert saved.knowledge == ("https://example.com/a", "pack:company")
    assert saved.skills == ("whyline:notes",)
    assert saved.tools == {"notion.search": "allowed", "notion.create_page": "ask"}


async def test_web_page_must_be_an_address(tmp_path):
    from whyline.console.agents_screens import _TextPromptScreen

    app = tui.WhylineConsoleApp(root=tmp_path)
    results = []
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(_TextPromptScreen("Add web page"), results.append)
        await pilot.pause()
        app.screen.query_one("#tp-input", tui.Input).value = "not a url"
        await pilot.click("#tp-add")
        await pilot.pause()
        assert results == [] and "http" in str(app.screen.query_one("#tp-error").renderable)
        app.screen.query_one("#tp-input", tui.Input).value = "https://example.com/x"
        app.screen.query_one("#tp-add", tui.Button).press()
        await pilot.pause()
        await pilot.pause()
    assert results == ["https://example.com/x"]


async def test_cli_lists_narrow_when_tools_are_chosen(tmp_path, monkeypatch):
    _server()
    monkeypatch.setattr(capabilities, "can_run", lambda cli: True)
    monkeypatch.setattr(
        capabilities, "tools_support", lambda cli: "none" if cli == "grok" else "per-run")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        runner = s.query_one("#na-runner", tui.Select)
        assert "grok" in [v for _l, v in runner._options]
        assert s.query_one("#na-backup-grok", tui.Checkbox).display
        s._tools_done({"notion.search": "allowed"})
        await pilot.pause()
        assert "grok" not in [v for _l, v in runner._options]
        assert not s.query_one("#na-backup-grok", tui.Checkbox).display
        assert "grok is left out: cannot use tools" in str(s.query_one("#na-left-out").renderable)
        s.query_one("#na-clear-tools", tui.Button).press()
        await pilot.pause()
        assert "grok" in [v for _l, v in runner._options]
        assert str(s.query_one("#na-left-out").renderable) == ""
