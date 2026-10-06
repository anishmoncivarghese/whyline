from pathlib import Path

import pytest

from whyline.agents import definitions as d

REPO_TOML = '''
name = "research-digest"
instructions = """Summarise what changed."""
runner = "claude"
backup = ["codex"]
sources = ["docs/notes.md"]
report_folder = "~/Reports/digest"
[trigger]
kind = "weekdays"
at = "07:00"
'''


def test_parse_a_repo_agent(repo):
    path = repo / ".whyline/agents/research-digest.toml"
    a = d.parse(REPO_TOML, kind="repo", path=path, repo_root=repo)
    assert (a.name, a.runner, a.backup) == ("research-digest", "claude", ("codex",))
    assert a.trigger == d.Trigger(kind="weekdays", at="07:00")
    assert a.root == repo and a.agent_id == f"repo:{repo.resolve()}:research-digest"
    assert a.label == "research-digest (repo)"


@pytest.mark.parametrize("bad, message", [
    ('name = "Bad Name"\ninstructions="x"\nrunner="claude"', "name"),
    ('name = "ok"\ninstructions=""\nrunner="claude"', "instructions"),
    ('name = "ok"\ninstructions="x"\nrunner="gpt"', "runner"),
    ('name = "ok"\ninstructions="x"\nrunner="claude"\nbackup=["claude"]', "backup"),
    ('name = "ok"\ninstructions="x"\nrunner="claude"\n[trigger]\nkind="daily"\nat="7am"', "at"),
    ('name = "ok"\ninstructions="x"\nrunner="claude"\n[trigger]\nkind="every"\nevery_hours=0', "every_hours"),
    ('name = "ok"\ninstructions="x"\nrunner="claude"\n[trigger]\nkind="folder"', "folder"),
    ('name = "ok"\ninstructions="x"\nrunner="claude"\nsources=["../outside.txt"]', "outside the repository"),
])
def test_invalid_definitions_say_what_is_wrong(repo, bad, message):
    with pytest.raises(d.DefinitionError, match=message):
        d.parse(bad, kind="repo", path=repo / ".whyline/agents/ok.toml", repo_root=repo)


@pytest.mark.parametrize("value", ['"daily"', "1", "0", "false", "true", "[]", '["daily"]', "1.5"])
def test_a_trigger_that_is_not_a_table_is_rejected(repo, value):
    text = f'name = "ok"\ninstructions = "x"\nrunner = "claude"\ntrigger = {value}\n'
    with pytest.raises(d.DefinitionError, match="trigger must be a table"):
        d.parse(text, kind="repo", path=repo / ".whyline/agents/ok.toml", repo_root=repo)


def test_a_trigger_array_of_tables_is_rejected(repo):
    text = 'name = "ok"\ninstructions = "x"\nrunner = "claude"\n[[trigger]]\nkind = "daily"\n'
    with pytest.raises(d.DefinitionError, match="trigger must be a table"):
        d.parse(text, kind="repo", path=repo / ".whyline/agents/ok.toml", repo_root=repo)


def test_omitted_or_empty_trigger_stays_manual(repo):
    base = 'name = "ok"\ninstructions = "x"\nrunner = "claude"\n'
    path = repo / ".whyline/agents/ok.toml"
    for text in (base, base + "trigger = {}\n", base + "[trigger]\n"):
        assert d.parse(text, kind="repo", path=path, repo_root=repo).trigger == d.Trigger()


def test_personal_agents_need_a_workdir(home):
    text = 'name = "p"\ninstructions="x"\nrunner="codex"'
    with pytest.raises(d.DefinitionError, match="workdir"):
        d.parse(text, kind="personal", path=home / ".whyline/agents/p.toml")
    a = d.parse(text + '\nworkdir = "~/work"', kind="personal", path=home / ".whyline/agents/p.toml")
    assert a.root == home / "work" and a.agent_id == "personal:p"


def test_render_round_trips_and_save_writes_the_file(repo):
    a = d.parse(REPO_TOML, kind="repo", path=repo / ".whyline/agents/research-digest.toml", repo_root=repo)
    text = d.render(a)
    assert d.parse(text, kind="repo", path=a.path, repo_root=repo) == a
    assert d.save(a) == a.path and a.path.read_text() == text


def test_hash_ignores_formatting_but_not_content():
    a = 'name = "x"\ninstructions = "y"\nrunner = "claude"\n'
    b = 'runner="claude"\n\nname="x"\ninstructions="y"'
    assert d.definition_hash(a) == d.definition_hash(b)
    assert d.definition_hash(a) != d.definition_hash(a.replace('"y"', '"z"'))


def test_resolve_sources(repo, home):
    a = d.parse(REPO_TOML, kind="repo", path=repo / ".whyline/agents/r.toml", repo_root=repo)
    assert d.resolve_sources(a) == [repo / "docs/notes.md"]


def test_discover_lists_repo_then_personal_and_reports_broken_files(repo, home):
    (repo / ".whyline/agents").mkdir(parents=True)
    (repo / ".whyline/agents/b.toml").write_text('name="b"\ninstructions="x"\nrunner="claude"')
    (repo / ".whyline/agents/a.toml").write_text("not = [valid")
    personal = home / ".whyline/agents"
    personal.mkdir(parents=True)
    (personal / "p.toml").write_text('name="p"\ninstructions="x"\nrunner="codex"\nworkdir="~"')
    found = d.discover(repo)
    assert [type(x).__name__ for x in found] == ["Broken", "AgentDef", "AgentDef"]
    assert [getattr(x, "name", None) for x in found[1:]] == ["b", "p"]
    assert found[0].path.name == "a.toml"


def test_discover_sorts_each_scope_by_agent_name_not_filename(repo, home):
    repo_dir = repo / ".whyline/agents"
    repo_dir.mkdir(parents=True)
    # Filenames sort a, m, z. Declared names sort alpha, mu, and the broken
    # file's filename sits between the two valid filenames.
    (repo_dir / "z-file.toml").write_text(
        'name="alpha"\ninstructions="x"\nrunner="claude"')
    (repo_dir / "a-file.toml").write_text(
        'name="mu"\ninstructions="x"\nrunner="claude"')
    (repo_dir / "m-file.toml").write_text("not = [valid")
    personal = home / ".whyline/agents"
    personal.mkdir(parents=True)
    (personal / "z.toml").write_text(
        'name="ann"\ninstructions="x"\nrunner="codex"\nworkdir="~"')
    (personal / "a.toml").write_text(
        'name="zoe"\ninstructions="x"\nrunner="codex"\nworkdir="~"')
    found = d.discover(repo)
    assert [(type(x).__name__, getattr(x, "name", x.path.name)) for x in found] == [
        ("Broken", "m-file.toml"),
        ("AgentDef", "alpha"),
        ("AgentDef", "mu"),
        ("AgentDef", "ann"),
        ("AgentDef", "zoe"),
    ]


def test_discover_reports_a_non_table_trigger_as_broken(repo, home):
    folder = repo / ".whyline/agents"
    folder.mkdir(parents=True)
    (folder / "a.toml").write_text(
        'name="a"\ninstructions="x"\nrunner="claude"\ntrigger = "daily"\n')
    (folder / "b.toml").write_text(
        'name="b"\ninstructions="x"\nrunner="claude"\ntrigger = 1\n')
    (folder / "c.toml").write_text(
        'name="c"\ninstructions="x"\nrunner="claude"\ntrigger = false\n')
    (folder / "d.toml").write_text(
        'name="d"\ninstructions="x"\nrunner="claude"\ntrigger = []\n')
    (folder / "e.toml").write_text('name="e"\ninstructions="x"\nrunner="claude"\n')
    found = d.discover(repo)
    assert [type(x).__name__ for x in found] == [
        "Broken", "Broken", "Broken", "Broken", "AgentDef"]
    assert [x.error for x in found[:4]] == ["trigger must be a table"] * 4
    assert found[4].name == "e"
