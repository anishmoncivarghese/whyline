import pytest
from textual.widgets import DataTable

from whyline.agents import definitions as d, service, telegram
from whyline.console import tui
from whyline.console.agents_screens import (
    _KIND, AgentsListScreen, NewAgentScreen, ReviewScreen, SkillPickScreen,
)

pytestmark = pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")

STATUS = {a: {"available": True, "label": "ok"} for a in ("claude", "codex", "grok", "antigravity")}
LINE = (
    "Removed 1 skills that are only in this repository: whyline-repo:local. "
    "A personal agent can use skills from ~/.whyline/skills and ~/.claude/skills."
)


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


def _skills(root):
    from whyline.tools import skills

    skills.create("mine", "Personal one", "Be brief.")
    skills.create("local", "Repo one", "Be brief.", repo_root=root)


def test_scope_choices_order_and_labels():
    assert _KIND == (
        ("Personal (this Mac, every repository)", "personal"),
        ("Only in this repository", "repo"),
    )


@pytest.mark.asyncio
async def test_new_agent_starts_personal(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(NewAgentScreen(root, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        assert s.query_one("#na-kind", tui.Select).value == "personal"
        s.query_one("#na-name", tui.Input).value = "solo"
        s.query_one("#na-instructions").load_text("Do it.")
        assert s._toml()[1] == "personal"
        await pilot.click("#na-next")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)
        await pilot.click("#rv-save")
        await pilot.pause()
    assert (tmp_path / "home" / ".whyline" / "agents" / "solo.toml").is_file()
    assert not (root / ".whyline" / "agents" / "solo.toml").exists()


@pytest.mark.asyncio
async def test_save_fallback_is_personal(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        real = s._choice
        s._choice = lambda widget_id: "" if widget_id == "#na-kind" else real(widget_id)
        s.query_one("#na-name", tui.Input).value = "solo"
        assert s._toml()[1] == "personal"


@pytest.mark.asyncio
async def test_existing_repo_agent_keeps_its_scope(tmp_path):
    root = tmp_path / "repo"
    (root / ".whyline" / "agents").mkdir(parents=True)
    path = root / ".whyline" / "agents" / "keep.toml"
    path.write_text("x", encoding="utf-8")
    defn = d.AgentDef(name="keep", kind="repo", path=path, root=root,
                      instructions="x", runner="claude")
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(NewAgentScreen(root, STATUS, defn), app._new_agent_done)
        await pilot.pause()
        assert app.screen.query_one("#na-kind", tui.Select).value == "repo"


@pytest.mark.asyncio
async def test_personal_agent_gets_no_repo_skill(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _skills(root)
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 100)) as pilot:
        for scope, expected in (("personal", {"whyline:mine"}),
                                ("repo", {"whyline:mine", "whyline-repo:local"})):
            app.push_screen(SkillPickScreen(root, [], scope))
            await pilot.pause()
            assert {s.ref for s in app.screen._skills} == expected
            app.pop_screen()
            await pilot.pause()

        app.push_screen(NewAgentScreen(root, STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        s.query_one("#na-kind", tui.Select).value = "repo"
        await pilot.pause()
        s._skills_done(["whyline:mine", "whyline-repo:local"])
        s.query_one("#na-kind", tui.Select).value = "personal"
        await pilot.pause()
        assert s._skills == ["whyline:mine"]
        assert str(s.query_one("#na-error").renderable) == LINE
        s.query_one("#na-kind", tui.Select).value = "repo"
        await pilot.pause()
        assert s._skills == ["whyline:mine"]

        # Save refuses a personal agent that still names a repository skill.
        s.query_one("#na-kind", tui.Select).value = "personal"
        await pilot.pause()
        s.query_one("#na-name", tui.Input).value = "solo"
        s.query_one("#na-instructions").load_text("Do it.")
        s._skills.append("whyline-repo:local")
        await pilot.click("#na-next")
        await pilot.pause()
        assert app.screen is s
        assert str(s.query_one("#na-error").renderable) == LINE
    assert not (tmp_path / "home" / ".whyline" / "agents" / "solo.toml").exists()


@pytest.mark.asyncio
async def test_list_row_marks_repository_agents(tmp_path):
    rows = []
    for kind in ("repo", "personal"):
        defn = d.AgentDef(name=kind + "x", kind=kind, path=tmp_path / f"{kind}.toml",
                          root=tmp_path, instructions="x", runner="claude")
        rows.append(service.Row(defn, "active", "", "", "", "manual"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        app.push_screen(AgentsListScreen(rows))
        await pilot.pause()
        table = app.screen.query_one("#al-table", DataTable)
        first = [str(table.get_row_at(i)[0]) for i in range(2)]
    assert first == ["repox · this repository only", "personalx"]
