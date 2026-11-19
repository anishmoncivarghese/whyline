import re
from pathlib import Path

import pytest

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
