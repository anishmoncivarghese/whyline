import re
from pathlib import Path

import pytest
from textual.widgets import TabbedContent

from whyline.agents import telegram
from whyline.console import mac_input, tui
from whyline.console.agents_screens import PackPickScreen, SkillPickScreen, ToolPickScreen

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
    # No host agy/grok binaries, so Tools starts no background readiness checks.
    monkeypatch.setattr("whyline.console.tools_screens.shutil.which", lambda _b: None)
    return home


def _seed():
    from whyline.tools import knowledge, mcp_config, skills
    from whyline.tools.mcp_config import Server, Tool

    knowledge.save_pack(knowledge.Pack(name="docs", description="Notes"))
    skills.create("notes", "Take notes", "Be brief.")
    mcp_config.save_server(Server(name="notion", command="x", enabled=True,
                                  tools=(Tool("search", read_only=True),)))


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
@pytest.mark.parametrize("make, first", [
    (lambda root: PackPickScreen([]), "#pp-0"),
    (lambda root: SkillPickScreen(root, []), "#sk-0"),
    (lambda root: ToolPickScreen({}), "#tl-c-0"),
])
async def test_focused_picker_checkbox_keeps_its_label(tmp_path, make, first):
    # Textual's `:focus` border ate the only line of a one-line checkbox.
    _seed()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 60)) as pilot:
        app.push_screen(make(tmp_path))
        await pilot.pause()
        box = app.screen.query_one(first, tui.Checkbox)
        box.focus()
        await pilot.pause()
        assert box.has_focus
        assert box.content_region.height == 1


def test_every_one_line_checkbox_has_a_focus_rule():
    import whyline.console as console

    rule = re.compile(r"((?:[#.\w-]+\s+)*)Checkbox\s*\{([^}]*)\}")
    missing = []
    for path in sorted(Path(console.__file__).parent.glob("*.py")):
        text = path.read_text()
        for match in rule.finditer(text):
            prefix, body = match.group(1).strip(), match.group(2)
            if not re.search(r"height:\s*1\s*;", body):
                continue
            selector = f"{prefix} Checkbox".strip()
            focus = re.compile(re.escape(selector) + r":focus\s*\{\s*border:\s*none;\s*\}")
            if not focus.search(text):
                missing.append(f"{path.name}: {selector}")
    assert not missing


def _server(name, enabled=True, tools=("search",)):
    from whyline.tools import mcp_config
    from whyline.tools.mcp_config import Server, Tool

    mcp_config.save_server(Server(
        name=name, command="x", enabled=enabled,
        tools=tuple(Tool(t, read_only=True) for t in tools)))


def _texts(screen):
    return [str(w.render()) for w in screen.query(tui.Static)]


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_open_tools_keeps_the_picks(tmp_path):
    from whyline.console.tools_screens import ToolsScreen

    _server("notion", tools=("search", "write"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 60)) as pilot:
        app.push_screen(ToolPickScreen({}))
        await pilot.pause()
        picker = app.screen
        assert any("Tools come from your connectors" in t for t in _texts(picker))
        picker.query_one("#tl-c-1", tui.Checkbox).value = True
        picker.query_one("#tl-s-1", tui.Select).value = "allowed"
        await pilot.click("#tl-open")
        await pilot.pause()
        assert isinstance(app.screen, ToolsScreen)
        _server("github", tools=("issues",))
        app.screen.dismiss(None)
        await pilot.pause()
        await pilot.pause()
        assert app.screen is picker
        assert len(picker._keys) == 3
        keys = [k for k, _ in picker._keys]
        i = keys.index("notion.write")
        assert picker.query_one(f"#tl-c-{i}", tui.Checkbox).value is True
        assert picker.query_one(f"#tl-s-{i}", tui.Select).value == "allowed"
        assert picker.query_one(f"#tl-c-{keys.index('notion.search')}", tui.Checkbox).value is False


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_empty_tool_picker_says_so_and_open_tools_is_primary(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 60)) as pilot:
        app.push_screen(ToolPickScreen({}))
        await pilot.pause()
        texts = _texts(app.screen)
        assert ("No connectors yet. Add one in Tools, test it, "
                "then choose its tools here.") in texts
        assert app.screen.query_one("#tl-open", tui.Button).variant == "primary"
        assert app.screen.query_one("#tl-done", tui.Button).variant == "default"


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_untested_and_turned_off_connectors_are_one_line(tmp_path):
    _server("github", tools=())
    _server("slack", enabled=False)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 60)) as pilot:
        app.push_screen(ToolPickScreen({}))
        await pilot.pause()
        texts = _texts(app.screen)
        assert "github · not tested yet" in texts
        assert "slack · turned off" in texts
        assert not app.screen.query(tui.Checkbox)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
@pytest.mark.parametrize("make, hint, button, tab", [
    (lambda root: PackPickScreen([]), "Packs come from your library.", "#pp-open", "tl-knowledge"),
    (lambda root: SkillPickScreen(root, []), "Skills come from your library.", "#sk-open", "tl-skills"),
    (lambda root: ToolPickScreen({}), "Tools come from your connectors.", "#tl-open", "tl-connectors"),
])
async def test_each_picker_opens_its_own_tools_tab(tmp_path, make, hint, button, tab):
    from whyline.console.tools_screens import ToolsScreen

    _seed()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 60)) as pilot:
        app.push_screen(make(tmp_path))
        await pilot.pause()
        assert any(hint in t for t in _texts(app.screen))
        await pilot.click(button)
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, ToolsScreen)
        assert app.screen.query_one("#tl-tabs", TabbedContent).active == tab
