"""Skills, knowledge and tools on an agent definition (TLS-7)."""
import pytest

from whyline.agents import definitions as d, state
from whyline.tools import knowledge as kn, mcp_config, skills as sk, users

BASE = 'name = "ok"\ninstructions = "x"\nrunner = "claude"\n'


def _server(home, tools_hash="h1", env=None):
    mcp_config.save_server(mcp_config.Server(
        "files", "cmd", env=env or {}, tools_hash=tools_hash,
        tools=(mcp_config.Tool("read"), mcp_config.Tool("write"))))


def _skill(home, name="notes", body="hello"):
    folder = home / ".whyline" / "skills" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n{body}\n")


def _parse(repo, extra):
    return d.parse(BASE + extra, kind="repo", path=repo / ".whyline/agents/ok.toml", repo_root=repo)


def test_old_sources_load_into_knowledge_and_save_as_knowledge(repo):
    a = _parse(repo, 'sources = ["docs/notes.md"]\nknowledge = ["docs/other.md"]\n')
    assert a.knowledge == ("docs/other.md", "docs/notes.md")
    text = d.render(a)
    assert "sources" not in text
    again = d.parse(text, kind="repo", path=a.path, repo_root=repo)
    assert again.knowledge == a.knowledge
    assert [p.name for p in d.resolve_sources(again)] == ["other.md", "notes.md"]


def test_round_trip_with_skills_knowledge_and_tools(repo, home):
    _server(home)
    _skill(home)
    kn.save_pack(kn.Pack("docs", items=("~/x",)))
    tools = '[tools]\n"files.read" = "allowed"\n"files.write" = "ask"\n'
    a = _parse(repo, 'skills = ["whyline:notes"]\nknowledge = ["pack:docs"]\n' + tools)
    again = d.parse(d.render(a), kind="repo", path=a.path, repo_root=repo)
    assert (again.skills, again.knowledge, again.tools) == (
        ("whyline:notes",), ("pack:docs",), {"files.read": "allowed", "files.write": "ask"})


@pytest.mark.parametrize("extra, message", [
    ('skills = ["whyline:missing"]', "unknown skill"),
    ('knowledge = ["pack:nope"]', "unknown knowledge pack nope"),
    ('[tools]\n"nosuch.read" = "ask"', "unknown server nosuch"),
    ('[tools]\n"files.delete" = "ask"', "unknown tool delete"),
    ('[tools]\n"files.read" = "always"', "must be allowed or ask"),
])
def test_unknown_things_make_the_agent_broken(repo, home, extra, message):
    _server(home)
    with pytest.raises(d.DefinitionError, match=message):
        _parse(repo, extra)


def test_skills_over_the_limit_are_refused(repo, home, monkeypatch):
    _skill(home, "a", "x" * 100)
    monkeypatch.setattr(sk, "AGENT_SKILLS_LIMIT", 50)
    with pytest.raises(d.DefinitionError, match="at most 50"):
        _parse(repo, 'skills = ["whyline:a"]')


def test_a_bad_agent_is_listed_broken_with_the_reason(repo, home):
    path = repo / ".whyline/agents/ok.toml"
    path.parent.mkdir(parents=True)
    path.write_text(BASE + 'skills = ["whyline:missing"]\n')
    (found,) = [i for i in d.discover(repo) if i.path == path]
    assert isinstance(found, d.Broken) and "unknown skill" in found.error


def test_changed_tools_need_review(repo, home):
    _server(home, "h1")
    path = repo / ".whyline/agents/ok.toml"
    path.parent.mkdir(parents=True)
    path.write_text(BASE + '[tools]\n"files.read" = "allowed"\n')
    agent = d.load(path, kind="repo", repo_root=repo)
    conn = state.connect()
    state.accept(conn, agent)
    assert state.check_hash(conn, agent) == "active"
    _server(home, "h2")  # the server's tools changed
    assert state.check_hash(conn, agent) == "needs_review"
    state.accept(conn, agent)
    assert state.check_hash(conn, agent) == "active"


def test_hash_without_tools_ignores_servers(repo, home):
    before = d.definition_hash(BASE)
    _server(home)
    assert d.definition_hash(BASE) == before


def _made(name="weather", url="https://api.example.com/{city}", accept=True):
    from whyline.tools import made

    made.save(made.MadeTool(name=name, url=url, inputs=[made.ToolInput("city")]))
    if accept:
        made.accept(name)


def test_agent_may_name_a_made_tool_and_its_hash_follows_the_tool(repo, home):
    from whyline.tools import made

    _made()
    a = _parse(repo, '[tools]\n"made.weather" = "ask"\n')
    assert a.tools == {"made.weather": "ask"}
    first = d.definition_hash(d.render(a))
    _made(url="https://api.example.org/{city}", accept=False)
    edited = d.definition_hash(d.render(a))
    assert edited != first
    made.accept("weather")
    assert d.definition_hash(d.render(a)) not in (first, edited)


def test_unaccepted_or_removed_made_tool_keeps_the_agent_loading(repo, home):
    from whyline.tools import made

    _made(accept=False)
    assert _parse(repo, '[tools]\n"made.weather" = "allowed"\n').tools == {"made.weather": "allowed"}
    made.remove("weather")
    assert _parse(repo, '[tools]\n"made.weather" = "allowed"\n').tools == {"made.weather": "allowed"}


def test_agents_register_as_users(repo, home, monkeypatch):
    _server(home, env={"TOKEN": "gh-token"})
    _skill(home)
    kn.save_pack(kn.Pack("docs", items=("~/x",)))
    path = repo / ".whyline/agents/ok.toml"
    path.parent.mkdir(parents=True)
    path.write_text(BASE + 'skills = ["whyline:notes"]\nknowledge = ["pack:docs"]\n'
                    '[tools]\n"files.read" = "allowed"\n')
    monkeypatch.chdir(repo)
    assert users.of("skill", "whyline:notes") == ["agent ok"]
    with pytest.raises(ValueError, match="agent ok"):
        sk.remove("whyline:notes", repo)
    assert users.of("pack", "docs") == ["agent ok"]
    assert users.of("server", "files") == ["agent ok"]
    assert users.of("credential", "gh-token") == ["agent ok"]
    with pytest.raises(ValueError, match="agent ok"):
        kn.remove_pack("docs")
