import subprocess
from pathlib import Path
from types import SimpleNamespace

from whyline.relaychat import agent_choice
from whyline.relaychat import ask as relay_ask
from whyline.release import plan as release_plan


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout


def make_repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
        "--allow-empty", "-m", "first")
    return tmp_path


def test_notes_agent_cannot_commit(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    status = git(repo, "status", "--porcelain")
    seen = {}

    monkeypatch.setattr(agent_choice, "pick", lambda r, a=None: SimpleNamespace(agent="claude"))
    monkeypatch.setattr(relay_ask, "command", lambda r, cli: ["claude", "--read-only", "-p"])

    def fake_run(argv, text, **kwargs):
        seen.update(argv=argv, text=text, cwd=Path(kwargs["cwd"]))
        return SimpleNamespace(exit_code=0, output="<notes>\n- hi\n</notes>")

    monkeypatch.setattr("whyline_relay.agents.run", fake_run)
    monkeypatch.setattr(relay_ask, "extract", lambda r, cli, raw, f: raw)

    answer = release_plan.default_ask_agent(repo)("the prompt")

    assert answer == "<notes>\n- hi\n</notes>"
    assert seen["argv"][:2] == ["claude", "--read-only"] and seen["text"] == "the prompt"
    assert seen["cwd"] != repo and repo not in seen["cwd"].parents
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "status", "--porcelain") == status


def test_notes_agent_without_read_only_mode_raises(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(agent_choice, "pick", lambda r, a=None: SimpleNamespace(agent="x"))
    monkeypatch.setattr(relay_ask, "command", lambda r, cli: None)
    with pytest.raises(RuntimeError):
        release_plan.default_ask_agent(tmp_path)("p")


def test_notes_agent_settings_path_exists_from_temp_cwd(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    settings = repo / ".whyline" / "relay" / "claude-settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}")
    seen = {}

    monkeypatch.setattr(agent_choice, "pick", lambda r, a=None: SimpleNamespace(agent="claude"))
    monkeypatch.setattr(
        relay_ask, "command",
        lambda r, cli: ["claude", "--settings", ".whyline/relay/claude-settings.json", "-p"],
    )

    def fake_run(argv, text, **kwargs):
        seen.update(argv=argv, cwd=Path(kwargs["cwd"]))
        return SimpleNamespace(exit_code=0, output="<notes>\n- hi\n</notes>")

    monkeypatch.setattr("whyline_relay.agents.run", fake_run)
    monkeypatch.setattr(relay_ask, "extract", lambda r, cli, raw, f: raw)

    release_plan.default_ask_agent(repo)("p")

    value = seen["argv"][seen["argv"].index("--settings") + 1]
    assert (seen["cwd"] / value).is_file() and Path(value).is_absolute()
