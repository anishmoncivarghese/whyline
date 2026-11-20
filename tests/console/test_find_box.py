import pytest

from whyline.console import tui
from whyline.console.tools_screens import CatalogueEntryScreen, PreviewScreen, ToolsScreen
from whyline.tools import catalogue, find, mcp_config, registry, skill_install, skill_sources, skills
from whyline.tools.mcp_config import Server, Tool

pytestmark = [pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"), pytest.mark.asyncio]


def _entry(name, title, about):
    return catalogue.Entry(name=name, title=title, about=about, command="npx", args=("-y", name),
                           credentials=(), tools=(), source="https://e.com", checked="")


CATALOGUE_ENTRY = _entry("mail", "Mail", "send email from a mailbox")
REGISTRY_ENTRY = _entry("regmail", "Registry Mail", "email from the registry")


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr("shutil.which", lambda binary: None)
    monkeypatch.setattr(catalogue, "load", lambda: [CATALOGUE_ENTRY])
    mcp_config.save_server(Server(name="mailbox", command="x", tools=(
        Tool("send_message", "Send an email", read_only=False),)))
    skills.create("email-style", "how to write an email", "Be brief.")
    source = skill_sources.add("mine", "https://example.com/o/r", "skills")
    folder = home / ".whyline" / "skill-sources" / "mine" / "skills" / "email-triage"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: email-triage\ndescription: sort an email inbox\n---\nDo it.\n")
    skill_sources._stamp(source).write_text("2026-11-20T00:00:00Z")
    monkeypatch.setattr(skill_install, "_commit", lambda source, run: "abc123def456")


@pytest.fixture
def registry_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(registry, "search", lambda text, **kw: calls.append(text) or [REGISTRY_ENTRY])
    return calls


async def _search(pilot, screen, words, *, registry_too=False):
    screen.query_one("#tl-find-q").value = words
    screen.query_one("#tl-find-reg" if registry_too else "#tl-find-find").press()
    await pilot.pause()
    await screen.workers.wait_for_complete()
    await pilot.pause()


def _buttons(screen):
    return [b for b in screen.query("Button") if (b.id or "").startswith("tl-find-hit-")]


async def test_library_lists_hits_by_kind_and_asks_the_network_only_on_the_button(tmp_path, registry_calls):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        app.push_screen(ToolsScreen())
        await pilot.pause()
        screen = app.screen
        assert "What should the agent be able to do?" in str(screen.query_one("FindBox Label").render())
        await _search(pilot, screen, "email")
        assert [str(b.label) for b in _buttons(screen)] == ["Tick its tools", "Add…", "Add skill", "Preview…"]
        assert registry_calls == []
        await _search(pilot, screen, "email", registry_too=True)
        assert registry_calls == ["email"]
        assert [str(b.label) for b in _buttons(screen)] == [
            "Tick its tools", "Add…", "Add skill", "Preview…", "Add…"]


async def test_library_hit_buttons_do_their_action(tmp_path, registry_calls):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        app.push_screen(ToolsScreen())
        await pilot.pause()
        screen = app.screen
        await _search(pilot, screen, "email")
        buttons = _buttons(screen)
        buttons[2].press()
        await pilot.pause()
        assert screen.query_one("#tl-tabs").active == "tl-skills"
        assert screen._skill_selected() == "whyline:email-style"
        buttons[0].press()
        await pilot.pause()
        await pilot.pause(0.5)
        assert screen.query_one("#tl-tabs").active == "tl-connectors"
        assert screen._selected() == "mailbox"
        buttons[1].press()
        await pilot.pause()
        assert isinstance(app.screen, CatalogueEntryScreen)
        app.screen.dismiss(None)
        await pilot.pause()
        buttons[3].press()
        await pilot.pause()
        assert isinstance(app.screen, PreviewScreen)


async def test_nothing_found_offers_make_a_tool_with_the_search_text(tmp_path, registry_calls):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 70)) as pilot:
        app.push_screen(ToolsScreen())
        await pilot.pause()
        screen = app.screen
        await _search(pilot, screen, "zzzzz")
        assert str(screen.query_one("#tl-find-none").render()) == find.NOTHING
        make = screen.query_one("#tl-find-make")
        assert not make.disabled and str(make.label) == "Make a tool…"
        make.press()
        await pilot.pause()
        from whyline.console.tools_screens import MakeToolScreen

        assert isinstance(app.screen, MakeToolScreen)
        assert app.screen.query_one("#mk-desc").text == "zzzzz"


async def test_add_tools_screen_ticks_adds_and_gives_skills(tmp_path, registry_calls):
    from whyline.console.agents_screens import ToolPickScreen

    given = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 90)) as pilot:
        app.push_screen(ToolPickScreen({}, on_skill=given.append))
        await pilot.pause()
        screen = app.screen
        await _search(pilot, screen, "email")
        buttons = _buttons(screen)
        buttons[0].press()
        await pilot.pause()
        assert screen.query_one("#tl-c-0", tui.Checkbox).value is True
        buttons[2].press()
        await pilot.pause()
        assert given == ["whyline:email-style"]
        buttons[3].press()
        await pilot.pause()
        assert isinstance(app.screen, PreviewScreen)
        app.screen.dismiss(None)
        await pilot.pause()
        buttons[1].press()
        await pilot.pause()
        assert isinstance(app.screen, CatalogueEntryScreen)


async def test_add_tools_screen_never_searches_the_registry_unasked(tmp_path, registry_calls):
    from whyline.console.agents_screens import ToolPickScreen

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 90)) as pilot:
        app.push_screen(ToolPickScreen({}))
        await pilot.pause()
        screen = app.screen
        screen.query_one("#tl-find-q").value = "email"
        await screen.query_one("#tl-find-q").action_submit()
        await pilot.pause()
        assert registry_calls == []
        await _search(pilot, screen, "email", registry_too=True)
        assert registry_calls == ["email"]
