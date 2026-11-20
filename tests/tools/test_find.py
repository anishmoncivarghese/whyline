import json
from pathlib import Path

import pytest

from whyline import cli
from whyline.tools import catalogue, find, mcp_config, registry, skill_sources, skills
from whyline.tools.mcp_config import Server, Tool

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "registry_search.json").read_text())


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _skill_folder(base: Path, name: str, description: str) -> None:
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\nDo it.\n")


def _remote(home, name: str, description: str) -> None:
    source = skill_sources.add("mine", "https://example.com/o/r", "skills")
    _skill_folder(home / ".whyline" / "skill-sources" / "mine" / "skills", name, description)
    skill_sources._stamp(source).write_text("2026-11-20T00:00:00Z")


def _everything(home):
    mcp_config.save_server(Server(name="mailbox", command="x", tools=(
        Tool("send_message", "Send an email message"),)))
    _skill_folder(home / ".whyline" / "skills", "email-style", "how to write an email")
    _remote(home, "email-triage", "sort an email inbox")


def test_hits_come_in_the_order_connector_catalogue_skill_remote_registry(home):
    _everything(home)
    entry = catalogue.Entry(name="mail", title="Mail", about="send email", command="npx", args=(),
                            credentials=(), tools=(), source="https://e.com", checked="")
    found = find.match("email", registry_search=lambda text: [entry], root=None)
    kinds = [h.kind for h in found]
    assert kinds == sorted(kinds, key=find.KINDS.index)
    by_kind = {h.kind: h for h in found}
    assert by_kind["connector"].ref == "mailbox"
    assert by_kind["skill"].ref == "whyline:email-style"
    assert by_kind["remote-skill"].ref == "mine:email-triage"
    assert by_kind["registry"].ref == "mail"


def test_catalogue_hits_sit_between_connectors_and_skills(home, monkeypatch):
    _everything(home)
    monkeypatch.setattr(catalogue, "load", lambda: [catalogue.Entry(
        name="mail", title="Mail", about="send an email", command="npx", args=(), credentials=(),
        tools=(), source="https://e.com", checked="")])
    assert [h.kind for h in find.match("email")] == ["connector", "catalogue", "skill", "remote-skill"]


def test_connector_matches_tool_name_and_description(home):
    mcp_config.save_server(Server(name="notion", command="x", tools=(
        Tool("create_page", "Make a page in a workspace"),)))
    assert [h.ref for h in find.match("create_page")] == ["notion"]
    assert [h.ref for h in find.match("workspace page")] == ["notion"]
    assert find.match("workspace spreadsheet") == []


def test_at_most_five_of_each_kind(home):
    for i in range(8):
        mcp_config.save_server(Server(name=f"mail{i}", command="x"))
        _skill_folder(home / ".whyline" / "skills", f"mail-{i}", "mail")
    found = find.match("mail")
    assert [h.kind for h in found].count("connector") == 5
    assert [h.kind for h in found].count("skill") == 5


def test_registry_is_not_called_without_asking_and_refused_are_dropped(home):
    calls = []
    assert find.match("weather") == []
    entries = registry.search("weather", get=lambda url, *, timeout: FIXTURE)
    found = find.match("weather", registry_search=lambda t: calls.append(t) or entries)
    assert calls == ["weather"]
    assert all(h.kind == "registry" for h in found)
    assert len(found) == len([e for e in entries if not e.refused]) < len(entries)


def test_no_registry_call_from_the_cli_without_the_flag(home, monkeypatch, capsys):
    monkeypatch.setattr(registry, "search", lambda *a, **k: pytest.fail("network"))
    assert cli.main(["tools", "find", "zzzz"]) == 0
    assert find.NOTHING in capsys.readouterr().out


def test_cli_find_lists_hits_and_registry_flag_searches(home, monkeypatch, capsys):
    _everything(home)
    assert cli.main(["tools", "find", "email"]) == 0
    out = capsys.readouterr().out
    assert "connector  mailbox" in out and "skill  whyline:email-style" in out
    monkeypatch.setattr(registry, "search", lambda text, **kw: [])
    assert cli.main(["tools", "find", "--registry", "weather"]) == 0
    assert find.NOTHING in capsys.readouterr().out


def test_empty_text_finds_nothing(home):
    assert find.match("   ") == []
