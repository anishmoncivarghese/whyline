import json

import pytest

from whyline import credentials
from whyline.agents import capabilities
from whyline.console import tui
from whyline.console.tools_screens import (
    AddServerScreen, CredentialScreen, ImportServersScreen, PackItemScreen, PackScreen, SkillScreen, ToolsScreen,
)
from whyline.tools import knowledge, mcp_config, skills, users

pytestmark = [pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"), pytest.mark.asyncio]

SECRET = "s3cr3t-value-123"


@pytest.fixture
def stored():
    return {}


@pytest.fixture
def home(tmp_path, monkeypatch, stored):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    def put(name, value, run, which, system):
        stored[name] = value

    monkeypatch.setattr(credentials, "_put", put)
    monkeypatch.setattr(credentials, "remove", lambda name, **kw: _forget(stored, name))
    monkeypatch.setattr(capabilities, "saved_ready", lambda cli: False)
    monkeypatch.setattr("shutil.which", lambda binary: None)
    return home


def _forget(stored, name):
    stored.pop(name, None)
    creds = credentials._load()
    creds.pop(name, None)
    credentials._store(creds)


@pytest.fixture(autouse=True)
def _clean_users():
    yield
    users.unregister("test")


async def open_tools(pilot, app, tab="tl-connectors", **kwargs):
    screen = ToolsScreen(**kwargs)
    app.push_screen(screen)
    await pilot.pause()
    assert isinstance(app.screen, ToolsScreen)
    screen.query_one("#tl-tabs").active = tab
    await pilot.pause()
    return screen


def text(screen, selector):
    return str(screen.query_one(selector).render())


async def test_tools_button_opens_the_screen(home, tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#mode-agents")
        await pilot.pause()
        await pilot.click("#agents-tools")
        await pilot.pause()
        assert isinstance(app.screen, ToolsScreen)


def make_skill(folder, name, description="Does a thing"):
    folder = folder / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\nBody of {name}.\n")


def skill_rows(screen):
    table = screen.query_one("#tl-skill-table")
    return {row.key.value: table.get_row(row.key) for row in table.ordered_rows}


def pick_skill(screen, ref):
    table = screen.query_one("#tl-skill-table")
    table.move_cursor(row=table.get_row_index(ref))


async def test_skills_show_origin_description_size_and_problems(home, tmp_path):
    make_skill(home / ".whyline" / "skills", "mine", "Mine")
    make_skill(tmp_path / ".whyline" / "skills", "shared", "Shared")
    make_skill(home / ".claude" / "skills", "personal", "From Claude")
    make_skill(tmp_path / ".claude" / "skills", "local", "In project")
    (home / ".whyline" / "skills" / "broken").mkdir()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        rows = skill_rows(screen)
        assert [rows[r][0] for r in ("whyline:mine", "whyline-repo:shared", "claude:personal",
                                     "claude-project:local")] == [
            "whyline", "whyline · repo", "Claude", "Claude · project"]
        assert rows["whyline:mine"][3] == "Mine"
        assert rows["whyline:mine"][2].endswith(" B")
        assert "no SKILL.md" in rows["whyline:broken"][3]


async def test_claude_skill_offers_only_copy_and_copy_works(home, tmp_path):
    make_skill(home / ".claude" / "skills", "notes")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        pick_skill(screen, "claude:notes")
        await pilot.pause()
        assert not screen.query_one("#tl-skill-copy").disabled
        assert screen.query_one("#tl-skill-edit").disabled
        assert screen.query_one("#tl-skill-remove").disabled
        screen._skill_edit()
        assert "Copy to whyline" in text(screen, "#tl-skill-status")
        screen._skill_remove()
        assert "Not removed" in text(screen, "#tl-skill-status")
        assert (home / ".claude" / "skills" / "notes").is_dir()
        await pilot.click("#tl-skill-copy")
        await pilot.pause()
        assert "Copied to whyline:notes" in text(screen, "#tl-skill-status")
        assert (home / ".whyline" / "skills" / "notes" / "SKILL.md").is_file()
        pick_skill(screen, "whyline:notes")
        await pilot.pause()
        assert screen.query_one("#tl-skill-copy").disabled
        assert not screen.query_one("#tl-skill-edit").disabled


@pytest.mark.parametrize("ref, label", [
    ("agents:shared", "~/.agents"), ("codex:fromcodex", "Codex")])
async def test_other_tool_folders_show_origin_and_copy(home, tmp_path, ref, label):
    make_skill(home / ".agents" / "skills", "shared", "Agents one")
    make_skill(home / ".codex" / "skills", "fromcodex", "Codex one")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        assert skill_rows(screen)[ref][0] == label
        pick_skill(screen, ref)
        await pilot.pause()
        assert not screen.query_one("#tl-skill-copy").disabled
        assert screen.query_one("#tl-skill-edit").disabled
        await pilot.click("#tl-skill-copy")
        await pilot.pause()
        assert f"Copied to whyline:{ref.split(':')[1]}" in text(screen, "#tl-skill-status")


async def test_new_skill_personal_and_repository(home, tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        for name, where in (("alpha", "personal"), ("beta", "repo")):
            await pilot.click("#tl-skill-new")
            await pilot.pause()
            form = app.screen
            assert isinstance(form, SkillScreen)
            form.query_one("#sk-name").value = name
            form.query_one("#sk-where").value = where
            form.query_one("#sk-description").value = f"About {name}"
            form.query_one("#sk-body").text = f"Steps for {name}"
            await pilot.click("#sk-save")
            await pilot.pause()
            assert app.screen is screen
        rows = skill_rows(screen)
        assert rows["whyline:alpha"][0] == "whyline"
        assert rows["whyline-repo:beta"][0] == "whyline · repo"
    assert "Steps for alpha" in (home / ".whyline" / "skills" / "alpha" / "SKILL.md").read_text(encoding="utf-8")
    assert (tmp_path / ".whyline" / "skills" / "beta" / "SKILL.md").is_file()


async def test_new_skill_refuses_a_bad_name(home, tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        await pilot.click("#tl-skill-new")
        await pilot.pause()
        form = app.screen
        form.query_one("#sk-name").value = "Bad Name"
        form.query_one("#sk-description").value = "x"
        await pilot.click("#sk-save")
        await pilot.pause()
        assert isinstance(app.screen, SkillScreen)
        assert "lowercase" in text(form, "#sk-status")
    assert skills.find(tmp_path) == []


async def test_edit_whyline_skill_in_the_form(home, tmp_path):
    make_skill(home / ".whyline" / "skills", "mine", "Old")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        pick_skill(screen, "whyline:mine")
        await pilot.pause()
        await pilot.click("#tl-skill-edit")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, SkillScreen)
        assert form.query_one("#sk-description").value == "Old"
        assert form.query_one("#sk-body").text == "Body of mine."
        form.query_one("#sk-description").value = "New words"
        form.query_one("#sk-body").text = "New body"
        await pilot.click("#sk-save")
        await pilot.pause()
        assert app.screen is screen
        assert skill_rows(screen)["whyline:mine"][3] == "New words"
    saved = (home / ".whyline" / "skills" / "mine" / "SKILL.md").read_text(encoding="utf-8")
    assert "New body" in saved and "description: New words" in saved


async def test_skill_removal_refused_names_users_then_allowed(home, tmp_path):
    make_skill(home / ".whyline" / "skills", "used")
    make_skill(home / ".whyline" / "skills", "free")
    users.register("test", lambda: [users.Use("skill", "whyline:used", "agent digest")])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        pick_skill(screen, "whyline:used")
        await pilot.pause()
        await pilot.click("#tl-skill-remove")
        await pilot.pause()
        assert "agent digest" in text(screen, "#tl-skill-status")
        assert (home / ".whyline" / "skills" / "used").is_dir()
        pick_skill(screen, "whyline:free")
        await pilot.pause()
        screen.query_one("#tl-skill-remove").press()
        await pilot.pause()
        assert "Removed whyline:free" in text(screen, "#tl-skill-status")
    assert not (home / ".whyline" / "skills" / "free").exists()


async def test_knowledge_pack_new_add_files_page_and_edit(home, tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("hi")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-knowledge")
        await pilot.click("#tl-pack-new")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, PackScreen)
        form.query_one("#pk-name").value = "docs"
        form.query_one("#pk-description").value = "API docs"
        await pilot.click("#pk-save")
        await pilot.pause()
        assert app.screen is screen
        assert screen._pack_selected() == "docs"

        await pilot.click("#tl-pack-files")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, PackItemScreen)
        form.query_one("#pi-value").value = f"{notes} {tmp_path / 'missing.md'}"
        await pilot.click("#pi-add")
        await pilot.pause()
        assert isinstance(app.screen, PackItemScreen)
        assert "Not found" in text(form, "#pi-status")
        form.query_one("#pi-value").value = str(notes)
        form.query_one("#pi-add").press()
        await pilot.pause()
        assert app.screen is screen

        await pilot.click("#tl-pack-page")
        await pilot.pause()
        form = app.screen
        form.query_one("#pi-value").value = "ftp://example.com"
        await pilot.click("#pi-add")
        await pilot.pause()
        assert "http" in text(form, "#pi-status")
        form.query_one("#pi-value").value = "https://example.com/guide"
        form.query_one("#pi-add").press()
        await pilot.pause()
        assert app.screen is screen
        node = screen.query_one("#tl-pack-tree").root.children[0]
        assert [str(c.label) for c in node.children] == [str(notes.resolve()), "https://example.com/guide"]
    assert knowledge.get_pack("docs").items == (str(notes.resolve()), "https://example.com/guide")
    assert knowledge.get_pack("docs").description == "API docs"


async def test_knowledge_pack_removal_refused_then_allowed(home, tmp_path):
    knowledge.save_pack(knowledge.Pack("used"))
    knowledge.save_pack(knowledge.Pack("free"))
    users.register("test", lambda: [users.Use("pack", "used", "agent digest")])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-knowledge")
        tree = screen.query_one("#tl-pack-tree")
        tree.cursor_line = 2  # "free" sorts before "used"
        await pilot.pause()
        assert screen._pack_selected() == "used"
        await pilot.click("#tl-pack-remove")
        await pilot.pause()
        assert "agent digest" in text(screen, "#tl-pack-status")
        assert [p.name for p in knowledge.list_packs()] == ["free", "used"]
        tree.cursor_line = 1
        await pilot.pause()
        assert screen._pack_selected() == "free"
        screen.query_one("#tl-pack-remove").press()
        await pilot.pause()
        assert "Removed knowledge pack free" in text(screen, "#tl-pack-status")
    assert [p.name for p in knowledge.list_packs()] == ["used"]


async def test_add_server_uses_save_server(home, tmp_path):
    credentials.save(credentials.Credential(name="gh", kind="env"), SECRET)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 50)) as pilot:
        screen = await open_tools(pilot, app)
        await pilot.click("#tl-add")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, AddServerScreen)
        form.query_one("#as-name").value = "github"
        form.query_one("#as-command").value = "npx"
        form.query_one("#as-args").value = "-y 'some server'"
        form.query_one("#as-var").value = "GITHUB_TOKEN"
        form.query_one("#as-cred").value = "gh"
        await pilot.click("#as-add")
        await pilot.pause()
        assert app.screen is screen
    server = mcp_config.load()["github"]
    assert server.command == "npx"
    assert server.args == ("-y", "some server")
    assert server.env == {"GITHUB_TOKEN": "gh"}


async def test_add_server_refuses_a_bad_name(home, tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 50)) as pilot:
        await open_tools(pilot, app)
        await pilot.click("#tl-add")
        await pilot.pause()
        form = app.screen
        form.query_one("#as-name").value = "Bad Name"
        form.query_one("#as-command").value = "npx"
        await pilot.click("#as-add")
        await pilot.pause()
        assert isinstance(app.screen, AddServerScreen)
        assert "server name" in text(form, "#as-status")
    assert mcp_config._load_saved() == {}


async def test_import_adds_only_ticked_servers(home, tmp_path):
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {
        "alpha": {"command": "alpha-cmd", "args": ["a"], "env": {"TOKEN": "x"}},
        "beta": {"command": "beta-cmd"},
        "remote": {"url": "https://example.com/mcp"},
    }}))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 50)) as pilot:
        screen = await open_tools(pilot, app)
        await pilot.click("#tl-import")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, ImportServersScreen)
        names = [c.name for c in form._candidates]
        labels = {c.name: str(form.query_one(f"#im-{i}").label) for i, c in enumerate(form._candidates)}
        assert "needs a credential: TOKEN" in labels["alpha"]
        assert "refused" in labels["remote"]
        assert form.query_one(f"#im-{names.index('remote')}").disabled
        form.query_one(f"#im-{names.index('alpha')}").value = True
        await pilot.click("#im-go")
        await pilot.pause()
        assert app.screen is screen
    assert list(mcp_config._load_saved()) == ["alpha"]


async def test_test_runs_in_a_worker_and_shows_tools(home, tmp_path):
    mcp_config.save_server(mcp_config.Server(name="demo", command="demo-cmd"))
    calls = []

    def fake_test(name):
        calls.append(name)
        server = mcp_config.load()[name]
        from dataclasses import replace

        servers = {name: replace(server, tools=(
            mcp_config.Tool("read_it", read_only=True), mcp_config.Tool("write_it")))}
        mcp_config._write({**mcp_config._load_saved(), **servers})
        return "2 tools: read_it, write_it"

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 50)) as pilot:
        screen = await open_tools(pilot, app, test_fn=fake_test)
        screen.query_one("#tl-tree").move_cursor(screen.query_one("#tl-tree").root.children[0])
        await pilot.click("#tl-test")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert calls == ["demo"]
        assert "2 tools: read_it, write_it" in text(screen, "#tl-status")
        node = screen.query_one("#tl-tree").root.children[0]
        assert "2 tools" in str(node.label)
        node.expand()
        assert [str(c.label) for c in node.children] == ["read_it  reads", "write_it  not stated"]


async def test_remove_server_and_refusal_names_users(home, tmp_path):
    mcp_config.save_server(mcp_config.Server(name="used", command="x"))
    mcp_config.save_server(mcp_config.Server(name="free", command="x"))
    users.register("test", lambda: [users.Use("server", "used", "agent research-digest")])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 50)) as pilot:
        screen = await open_tools(pilot, app)
        tree = screen.query_one("#tl-tree")
        by_name = {n.data: n for n in tree.root.children}
        tree.move_cursor(by_name["used"])
        await pilot.pause()
        await pilot.click("#tl-remove")
        await pilot.pause()
        assert "agent research-digest" in text(screen, "#tl-status")
        assert "used" in mcp_config.load()
        tree.cursor_line = 1  # "free" sorts before "used"
        await pilot.pause()
        assert screen._selected() == "free"
        screen.query_one("#tl-remove").press()
        await pilot.pause()
        assert "Removed MCP server free" in text(screen, "#tl-status")
    assert list(mcp_config._load_saved()) == ["used"]


async def test_credentials_add_rotate_remove_with_masked_value(home, stored, tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-credentials")
        await pilot.click("#tl-cred-add")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, CredentialScreen)
        assert form.query_one("#cr-value").password is True
        form.query_one("#cr-name").value = "gh"
        form.query_one("#cr-value").value = SECRET
        await pilot.click("#cr-save")
        await pilot.pause()
        assert app.screen is screen
        assert stored["gh"] == SECRET
        assert [c.name for c in credentials.list_all()] == ["gh"]
        assert SECRET not in screen.query_one("#tl-creds").get_row_at(0).__repr__()
        assert SECRET not in text(screen, "#tl-cred-status")

        screen.query_one("#tl-creds").move_cursor(row=0)
        await pilot.click("#tl-cred-rotate")
        await pilot.pause()
        form = app.screen
        assert form.query_one("#cr-value").password is True
        form.query_one("#cr-value").value = "rotated-value-456"
        await pilot.click("#cr-save")
        await pilot.pause()
        assert stored["gh"] == "rotated-value-456"
        assert "rotated-value-456" not in text(screen, "#tl-cred-status")

        await pilot.click("#tl-cred-remove")
        await pilot.pause()
        assert credentials.list_all() == []


async def test_credential_removal_refused_names_users(home, tmp_path):
    credentials.save(credentials.Credential(name="gh", kind="env"), SECRET)
    users.register("test", lambda: [users.Use("credential", "gh", "server github")])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-credentials")
        screen.query_one("#tl-creds").move_cursor(row=0)
        await pilot.click("#tl-cred-remove")
        await pilot.pause()
        assert "server github" in text(screen, "#tl-cred-status")
    assert [c.name for c in credentials.list_all()] == ["gh"]


async def test_setup_buttons_disabled_when_cli_missing(home, tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 50)) as pilot:
        screen = await open_tools(pilot, app)
        assert screen.query_one("#tl-setup-grok").disabled
        assert screen.query_one("#tl-setup-antigravity").disabled
        note = text(screen, "#tl-setup-note")
        assert "grok is not installed" in note
        assert "agy is not installed" in note
        assert "Agents can't run on Antigravity yet" in note


async def test_both_setup_buttons_ask_first(home, tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda binary: f"/bin/{binary}")
    done = []
    monkeypatch.setattr(capabilities, "saved_setup", lambda cli: done.append(cli) or f"saved {cli}")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 50)) as pilot:
        screen = await open_tools(pilot, app)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "grok: whyline's tools are not saved yet" in text(screen, "#tl-setup-note")
        for cli in ("grok", "antigravity"):
            await pilot.click(f"#tl-setup-{cli}")
            await pilot.pause()
            assert isinstance(app.screen, tui.ConfirmScreen)
            assert done == []
            await pilot.click("#cancel")
            await pilot.pause()
            assert app.screen is screen
        assert done == []
        await pilot.click("#tl-setup-antigravity")
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert done == ["antigravity"]
        assert "saved antigravity" in text(screen, "#tl-status")


# Skill sources, Browse, preview and update -------------------------------------

import threading

from whyline.console import tools_screens
from whyline.console.tools_screens import BrowseScreen, LinkScreen, PreviewScreen, SourcesScreen, UpdateScreen
from whyline.tools import skill_install, skill_sources


@pytest.fixture(autouse=True)
def _no_git(monkeypatch):
    monkeypatch.setattr(skill_install, "_commit", lambda source, run: "abc123")


def put_clone(source, skill_name, body="Body.", description="Does a thing", extra=None):
    folder = skill_sources.clone_dir(source) / source.path / skill_name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: {skill_name}\ndescription: {description}\n---\n\n{body}\n")
    for rel, content in (extra or {}).items():
        (folder / rel).write_text(content)
    stamp = skill_sources._stamp(source)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text("2026-11-20T10:00:00Z")


def mine(path="skills"):
    return skill_sources.add("mine", "https://github.com/o/r", path)


def only_mine(monkeypatch):
    """Only the user's own source is on, so Browse has one source to fetch."""
    for builtin in skill_sources.BUILTIN:
        skill_sources.set_enabled(builtin.name, False)


async def open_browse(pilot, app):
    screen = await open_tools(pilot, app, "tl-skills")
    await pilot.click("#tl-skill-browse")
    await pilot.pause()
    assert isinstance(app.screen, BrowseScreen)
    return app.screen


def open_option(browse, index=0):
    results = browse.query_one("#br-results")
    results.highlighted = index
    results.action_select()


async def test_first_use_fetch_runs_in_a_worker_and_lists_results(home, tmp_path, monkeypatch):
    only_mine(monkeypatch)
    source = mine()
    release = threading.Event()
    seen = []

    def fake_fetch(s, **kw):
        seen.append(s.name)
        release.wait(5)
        put_clone(s, "notes", description="Takes notes")
        return "abc"

    monkeypatch.setattr(skill_sources, "fetch", fake_fetch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        browse = await open_browse(pilot, app)
        await pilot.pause()
        assert "Fetching mine…" in text(browse, "#br-status")
        assert browse.query_one("#br-cancel").display
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert seen == ["mine"]
        assert not browse.query_one("#br-cancel").display
        assert browse.query_one("#br-results").option_count == 1
        prompt = str(browse.query_one("#br-results").get_option_at_index(0).prompt)
        assert prompt.splitlines() == ["notes · mine · no licence stated", "Takes notes"]


async def test_cancel_stops_waiting_for_the_fetch(home, tmp_path, monkeypatch):
    only_mine(monkeypatch)
    mine()
    release = threading.Event()

    def slow(s, **kw):
        release.wait(5)
        put_clone(s, "late")

    monkeypatch.setattr(skill_sources, "fetch", slow)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        browse = await open_browse(pilot, app)
        await pilot.pause()
        await pilot.click("#br-cancel")
        await pilot.pause()
        assert "Cancelled" in text(browse, "#br-status")
        assert not browse.query_one("#br-cancel").display
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "Cancelled" in text(browse, "#br-status")
        assert browse.query_one("#br-results").option_count == 0


async def test_offline_says_so_and_lists_what_is_already_there(home, tmp_path, monkeypatch):
    for builtin in skill_sources.BUILTIN:
        skill_sources.set_enabled(builtin.name, False)
    have = mine()
    put_clone(have, "kept", description="Already here")
    skill_sources.add("fresh", "https://github.com/o/fresh")

    def offline(s, **kw):
        raise RuntimeError("git clone failed: could not resolve host")

    monkeypatch.setattr(skill_sources, "fetch", offline)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        browse = await open_browse(pilot, app)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "Couldn't fetch fresh: git clone failed: could not resolve host" in text(browse, "#br-status")
        assert browse.query_one("#br-results").option_count == 1
        assert "kept · mine" in str(browse.query_one("#br-results").get_option_at_index(0).prompt)


async def test_search_filters_results(home, tmp_path, monkeypatch):
    only_mine(monkeypatch)
    source = mine()
    put_clone(source, "alpha", description="First")
    put_clone(source, "beta", description="Second")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        browse = await open_browse(pilot, app)
        assert browse.query_one("#br-results").option_count == 2
        browse.query_one("#br-search").value = "bet"
        await pilot.pause()
        assert browse.query_one("#br-results").option_count == 1


async def test_preview_shows_warnings_first_then_licence_size_files_and_text(home, tmp_path, monkeypatch):
    only_mine(monkeypatch)
    source = mine()
    put_clone(source, "risky", body="Whole body text.", extra={"run.sh": "echo hi\n"})
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 60)) as pilot:
        browse = await open_browse(pilot, app)
        open_option(browse)
        await pilot.pause()
        preview = app.screen
        assert isinstance(preview, PreviewScreen)
        order = [w.id for w in preview.query("Static") if w.id and w.id.startswith("pv-")]
        assert order[:5] == ["pv-warnings", "pv-licence", "pv-size", "pv-files", "pv-text"]
        assert "Warning: contains scripts: run.sh" in text(preview, "#pv-warnings")
        assert "Licence: no licence stated" in text(preview, "#pv-licence")
        assert "SKILL.md" in text(preview, "#pv-files") and "run.sh" in text(preview, "#pv-files")
        assert "Whole body text." in text(preview, "#pv-text")
        for button in ("#pv-install", "#pv-as", "#pv-close"):
            assert preview.query_one(button)
        await pilot.click("#pv-close")
        await pilot.pause()
        assert app.screen is browse
        assert not (home / ".whyline" / "skills" / "risky").exists()


async def test_install_adds_the_skill_and_says_where_to_use_it(home, tmp_path, monkeypatch):
    only_mine(monkeypatch)
    put_clone(mine(), "notes")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 60)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        await pilot.click("#tl-skill-browse")
        await pilot.pause()
        open_option(app.screen)
        await pilot.pause()
        await pilot.click("#pv-install")
        await pilot.pause()
        assert app.screen is screen
        assert "Installed notes. Add it to an agent in New agent → Add skills." in text(screen, "#tl-skill-status")
        assert (home / ".whyline" / "skills" / "notes" / "SKILL.md").is_file()
        row = skill_rows(screen)["whyline:notes"]
        assert row[3].startswith("from mine")


async def test_install_as_uses_the_new_name(home, tmp_path, monkeypatch):
    only_mine(monkeypatch)
    put_clone(mine(), "notes")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 60)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        await pilot.click("#tl-skill-browse")
        await pilot.pause()
        open_option(app.screen)
        await pilot.pause()
        preview = app.screen
        assert not preview.query_one("#pv-name").display
        await pilot.click("#pv-as")
        await pilot.pause()
        assert preview.query_one("#pv-name").display
        preview.query_one("#pv-name").value = "my-notes"
        preview.query_one("#pv-as").press()
        await pilot.pause()
        assert app.screen is screen
        assert "Installed my-notes." in text(screen, "#tl-skill-status")
        assert (home / ".whyline" / "skills" / "my-notes").is_dir()
        assert not (home / ".whyline" / "skills" / "notes").exists()


async def test_install_refused_keeps_the_preview_open(home, tmp_path, monkeypatch):
    only_mine(monkeypatch)
    put_clone(mine(), "notes")
    make_skill(home / ".whyline" / "skills", "notes")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 60)) as pilot:
        browse = await open_browse(pilot, app)
        open_option(browse)
        await pilot.pause()
        await pilot.click("#pv-install")
        await pilot.pause()
        assert isinstance(app.screen, PreviewScreen)
        assert "already installed" in text(app.screen, "#pv-status")


async def test_parse_link_takes_one_skill_folder_and_refuses_the_rest():
    assert tools_screens.parse_link("https://github.com/Own/repo/tree/main/skills/pdf") == (
        "Own", "repo", "main", "skills/pdf")
    assert tools_screens.parse_link(" https://github.com/o/r/tree/dev/a/b/ ")[2:] == ("dev", "a/b")
    for bad in ("https://github.com/o/r", "https://github.com/o/r/tree/main", "http://github.com/o/r/tree/main/x",
                "https://gitlab.com/o/r/tree/main/x", "https://github.com/o/r/blob/main/x/SKILL.md",
                "https://github.com/o/r/tree/main/../x", "not a link"):
        with pytest.raises(ValueError, match="Expected a link like https://github.com/<owner>/<repo>/tree/"):
            tools_screens.parse_link(bad)


async def test_link_screen_refuses_a_bad_link(home, tmp_path, monkeypatch):
    only_mine(monkeypatch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        await pilot.click("#tl-skill-browse")
        await pilot.pause()
        await app.workers.wait_for_complete()
        browse = app.screen
        await pilot.click("#br-link")
        await pilot.pause()
        link = app.screen
        assert isinstance(link, LinkScreen)
        link.query_one("#lk-link").value = "https://example.com/x"
        await pilot.click("#lk-add")
        await pilot.pause()
        assert app.screen is link
        assert "Expected a link like https://github.com/<owner>/<repo>/tree/<branch>/" in text(link, "#lk-status")


async def test_link_adds_its_repository_fetches_it_and_opens_the_preview(home, tmp_path, monkeypatch):
    only_mine(monkeypatch)
    fetched = []

    def fake_fetch(s, **kw):
        fetched.append((s.name, s.url, s.path, s.branch))
        put_clone(s, "pdf", body="PDF text.")
        return "abc"

    monkeypatch.setattr(skill_sources, "fetch", fake_fetch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 60)) as pilot:
        browse = await open_browse(pilot, app)
        await pilot.click("#br-link")
        await pilot.pause()
        app.screen.query_one("#lk-link").value = "https://github.com/Acme/tools/tree/main/skills/pdf"
        await pilot.click("#lk-add")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert ("acme-tools", "https://github.com/Acme/tools", "skills", "main") in fetched
        assert any(s.name == "acme-tools" and not s.builtin for s in skill_sources.load())
        assert isinstance(app.screen, PreviewScreen)
        assert "PDF text." in text(app.screen, "#pv-text")


async def test_update_shows_the_diff_then_applies_it(home, tmp_path, monkeypatch):
    only_mine(monkeypatch)
    source = mine()
    put_clone(source, "notes", body="Old.")
    entry = skill_sources.index(source)[0]
    skill_install.install(entry)
    put_clone(source, "notes", body="New and better.")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 60)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        pick_skill(screen, "whyline:notes")
        await pilot.pause()
        assert not screen.query_one("#tl-skill-update").disabled
        await pilot.click("#tl-skill-update")
        await pilot.pause()
        update = app.screen
        assert isinstance(update, UpdateScreen)
        assert "+New and better." in text(update, "#up-diff")
        assert "-Old." in text(update, "#up-diff")
        await pilot.click("#up-update")
        await pilot.pause()
        assert app.screen is screen
        assert "Updated notes." in text(screen, "#tl-skill-status")
        assert "New and better." in (home / ".whyline" / "skills" / "notes" / "SKILL.md").read_text(encoding="utf-8")


async def test_update_cancel_leaves_the_skill_and_same_files_say_up_to_date(home, tmp_path, monkeypatch):
    only_mine(monkeypatch)
    source = mine()
    put_clone(source, "notes", body="Old.")
    skill_install.install(skill_sources.index(source)[0])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 60)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        pick_skill(screen, "whyline:notes")
        await pilot.pause()
        await pilot.click("#tl-skill-update")
        await pilot.pause()
        assert app.screen is screen
        assert text(screen, "#tl-skill-status") == "Already up to date"
        put_clone(source, "notes", body="Changed.")
        screen.query_one("#tl-skill-update").press()
        await pilot.pause()
        await pilot.click("#up-cancel")
        await pilot.pause()
        assert app.screen is screen
        assert "Old." in (home / ".whyline" / "skills" / "notes" / "SKILL.md").read_text(encoding="utf-8")


async def test_update_is_off_for_a_skill_with_no_source(home, tmp_path):
    make_skill(home / ".whyline" / "skills", "plain")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        pick_skill(screen, "whyline:plain")
        await pilot.pause()
        assert screen.query_one("#tl-skill-update").disabled


async def test_sources_list_add_toggle_remove_refresh_and_open(home, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(tools_screens.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(skill_sources, "fetch", lambda s, **kw: put_clone(s, "x") or "abc")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        await pilot.click("#tl-skill-sources")
        await pilot.pause()
        sources = app.screen
        assert isinstance(sources, SourcesScreen)
        table = sources.query_one("#so-table")
        rows = {r.key.value: table.get_row(r.key) for r in table.ordered_rows}
        assert set(rows) == {b.name for b in skill_sources.BUILTIN}
        assert rows["agentic"][2] == "MIT, text CC BY 4.0"
        assert rows["anthropic"][3] == "never"
        assert rows["voltagent"][1].startswith("directory")

        def cursor(name):
            table.move_cursor(row=table.get_row_index(name))

        # Add…
        await pilot.click("#so-add")
        await pilot.pause()
        app.screen.query_one("#ss-name").value = "bad name"
        app.screen.query_one("#ss-url").value = "https://github.com/o/r"
        app.screen.query_one("#ss-add").press()
        await pilot.pause()
        assert isinstance(app.screen, tools_screens.AddSourceScreen)
        app.screen.query_one("#ss-name").value = "extra"
        app.screen.query_one("#ss-path").value = "skills"
        app.screen.query_one("#ss-add").press()
        await pilot.pause()
        assert app.screen is sources
        assert "extra" in {r.key.value for r in table.ordered_rows}
        # a user's source cannot be turned off; a built-in cannot be removed
        cursor("extra")
        await pilot.pause()
        assert sources.query_one("#so-toggle").disabled
        assert not sources.query_one("#so-remove").disabled
        cursor("anthropic")
        await pilot.pause()
        assert sources.query_one("#so-remove").disabled
        assert sources.query_one("#so-open").disabled
        # Turn off / on
        await pilot.click("#so-toggle")
        await pilot.pause()
        assert table.get_row("anthropic")[4] == "off"
        assert str(sources.query_one("#so-toggle").label) == "Turn on"
        sources.query_one("#so-toggle").press()
        await pilot.pause()
        assert table.get_row("anthropic")[4] == "on"
        # Refresh
        cursor("extra")
        await pilot.pause()
        await pilot.click("#so-refresh")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "Fetched extra." in text(sources, "#so-status")
        assert table.get_row("extra")[3].startswith("2026-")
        # Open in browser (directories only)
        cursor("voltagent")
        await pilot.pause()
        assert sources.query_one("#so-refresh").disabled
        await pilot.click("#so-open")
        await pilot.pause()
        assert opened == ["https://github.com/VoltAgent/awesome-agent-skills"]
        # Remove
        cursor("extra")
        await pilot.pause()
        await pilot.click("#so-remove")
        await pilot.pause()
        assert "extra" not in {r.key.value for r in table.ordered_rows}
        assert not skill_sources.clone_dir(skill_sources.Source("extra", "https://x/y")).exists()


async def test_new_skill_draft_fills_the_form_and_saves_nothing_until_save(home, tmp_path, monkeypatch):
    from whyline.console.tools_screens import DraftScreen
    from whyline.tools import skill_draft

    seen = []

    def fake_draft(description, *, ask_agent):
        seen.append(description)
        return "from-draft", "Drafted one", "Do the thing."

    monkeypatch.setattr(skill_draft, "draft", fake_draft)
    monkeypatch.setattr("whyline.release.plan.default_ask_agent", lambda root, **kw: (lambda prompt: ""))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        screen = await open_tools(pilot, app, "tl-skills")
        await pilot.click("#tl-skill-new")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, SkillScreen)
        await pilot.click("#sk-draft")
        await pilot.pause()
        box = app.screen
        assert isinstance(box, DraftScreen)
        box.query_one("#dr-text").text = "make release notes"
        await pilot.click("#dr-go")
        await pilot.pause(0.5)
        assert app.screen is form
        assert seen == ["make release notes"]
        assert form.query_one("#sk-name").value == "from-draft"
        assert form.query_one("#sk-description").value == "Drafted one"
        assert form.query_one("#sk-body").text == "Do the thing."
        assert skills.find(tmp_path) == []
        await pilot.click("#sk-save")
        await pilot.pause()
        assert app.screen is screen
    assert "Do the thing." in (home / ".whyline" / "skills" / "from-draft" / "SKILL.md").read_text(encoding="utf-8")


async def test_draft_failure_is_shown_and_keeps_the_box(home, tmp_path, monkeypatch):
    from whyline.console.tools_screens import DraftScreen
    from whyline.tools import skill_draft

    def broken(description, *, ask_agent):
        raise skill_draft.DraftError("The answer has no front matter between --- lines.")

    monkeypatch.setattr(skill_draft, "draft", broken)
    monkeypatch.setattr("whyline.release.plan.default_ask_agent", lambda root, **kw: (lambda prompt: ""))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 50)) as pilot:
        await open_tools(pilot, app, "tl-skills")
        await pilot.click("#tl-skill-new")
        await pilot.pause()
        await pilot.click("#sk-draft")
        await pilot.pause()
        box = app.screen
        box.query_one("#dr-text").text = "x"
        await pilot.click("#dr-go")
        await pilot.pause(0.5)
        assert isinstance(app.screen, DraftScreen)
        assert "front matter" in text(box, "#dr-status")
    assert skills.find(tmp_path) == []


async def test_search_more_shows_registry_results_under_the_heading(home, stored, tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from whyline.console.tools_screens import CatalogueEntryScreen, RegistrySearchScreen
    from whyline.tools import registry

    data = json.loads((Path(__file__).parents[1] / "tools" / "fixtures" / "registry_search.json").read_text(encoding="utf-8"))
    real = registry.search
    monkeypatch.setattr(registry, "search", lambda text, **kw: real(text, get=lambda url, *, timeout: data))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 60)) as pilot:
        await open_tools(pilot, app)
        await pilot.click("#tl-catalogue")
        await pilot.pause()
        await pilot.click("#cp-more")
        await pilot.pause()
        results = app.screen
        assert isinstance(results, RegistrySearchScreen)
        assert text(results, "#rs-heading") == "From the public registry · not checked by whyline"
        results.query_one("#rs-search").value = "weather"
        await results.query_one("#rs-search").action_submit()
        await pilot.pause(0.5)
        listing = results.query_one("#rs-list")
        assert listing.option_count == 3
        assert "needs a browser sign-in" in str(listing.get_option_at_index(2).prompt)
        assert listing.get_option_at_index(2).disabled
        listing.highlighted = 0
        listing.action_select()
        await pilot.pause()
        assert isinstance(app.screen, CatalogueEntryScreen)
        assert "npx -y @example/weather-mcp" in text(app.screen, "#ce-about")


async def test_catalogue_add_needs_a_passing_test_then_enables(home, stored, tmp_path):
    from whyline.console.tools_screens import CatalogueEntryScreen, CataloguePickScreen
    from whyline.tools import catalogue

    results = iter([RuntimeError("no luck"), "1 tools: a"])

    def fake_test(name):
        value = next(results)
        if isinstance(value, Exception):
            raise value
        return value

    entry = next(e for e in catalogue.load() if e.credentials)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 60)) as pilot:
        screen = await open_tools(pilot, app, test_fn=fake_test)
        await pilot.click("#tl-catalogue")
        await pilot.pause()
        assert isinstance(app.screen, CataloguePickScreen)
        app.screen.dismiss(entry.name)
        await pilot.pause()
        form = app.screen
        assert isinstance(form, CatalogueEntryScreen)
        assert form.query_one("#ce-add").disabled
        for index, c in enumerate(entry.credentials):
            form.query_one(f"#ce-cred-{index}").value = SECRET
        form.query_one("#ce-test").press()
        await pilot.pause(0.5)
        assert "no luck" in text(form, "#ce-result")
        assert form.query_one("#ce-add").disabled
        assert mcp_config.load()[entry.name].enabled is False
        form.query_one("#ce-test").press()
        await pilot.pause(0.5)
        assert not form.query_one("#ce-add").disabled
        form.query_one("#ce-add").press()
        await pilot.pause()
        assert app.screen is screen
        assert mcp_config.load()[entry.name].enabled is True
        assert set(stored.values()) == {SECRET}
        await pilot.click("#tl-catalogue")
        await pilot.pause()
        app.screen.dismiss(entry.name)
        await pilot.pause()
        assert app.screen is screen
        assert "already added" in text(screen, "#tl-status")
