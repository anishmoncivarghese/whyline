import json
import os
from pathlib import Path

import pytest

from whyline import model, paths


@pytest.fixture(autouse=True)
def _home_honors_home_env(monkeypatch):
    """The plan points HOME at a temp directory. Path.home() ignores HOME
    on Windows, so the helper whyline uses has to follow the env var."""

    def home() -> Path:
        return Path(os.environ["HOME"])

    monkeypatch.setattr(paths.Path, "home", home)


def test_repo_default_agent_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".whyline").mkdir()
    assert model.default_agent(tmp_path) is None
    model.set_default_agent(tmp_path, "codex")
    model.set_one(tmp_path, "codex", "gpt-5.6")
    assert model.resolve(tmp_path) == ("codex", "gpt-5.6")
    assert json.loads((tmp_path / ".whyline/model.json").read_text())["default_agent"] == "codex"


def test_global_default_applies_without_a_repo_choice(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / ".whyline").mkdir()
    model.save_global("grok", "")
    assert model.resolve(tmp_path) == ("grok", "")
    assert json.loads((home / ".whyline/console.json").read_text())["default_agent"] == "grok"
    model.set_default_agent(tmp_path, "claude")
    assert model.resolve(tmp_path)[0] == "claude"  # the repo wins


def test_global_model_is_used_until_the_repo_sets_one(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / ".whyline").mkdir()
    model.save_global("grok", "grok-4")
    assert model.resolve(tmp_path) == ("grok", "grok-4")
    model.set_one(tmp_path, "grok", "grok-4.6")
    assert model.resolve(tmp_path) == ("grok", "grok-4.6")


def test_load_does_not_treat_default_agent_as_a_model(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".whyline").mkdir()
    model.set_default_agent(tmp_path, "codex")
    model.set_one(tmp_path, "codex", "gpt-5.6")
    assert model.load(tmp_path) == {"codex": "gpt-5.6"}


def test_nothing_saved_means_claude(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".whyline").mkdir()
    assert model.resolve(tmp_path) == ("claude", "")


def test_an_unreadable_global_file_is_ignored(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".whyline").mkdir(parents=True)
    (home / ".whyline/console.json").write_text("{nope")
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / ".whyline").mkdir()
    assert model.resolve(tmp_path) == ("claude", "")


def test_model_command_saves_the_default_agent(tmp_path, monkeypatch):
    from whyline import account
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(account, "available_agents", lambda root: {"codex", "claude"})
    (tmp_path / ".whyline").mkdir()
    session = ConsoleSession(root=tmp_path)
    event = handle_slash_command(session, "/model codex gpt-5.6")
    assert event.kind == "output"
    assert session.agent == "codex"
    saved = json.loads((tmp_path / ".whyline" / "model.json").read_text(encoding="utf-8"))
    assert saved["default_agent"] == "codex"
    assert saved["codex"] == "gpt-5.6"


def test_console_starts_on_the_saved_agent(tmp_path, monkeypatch):
    pytest.importorskip("textual")
    from whyline.console.tui import WhylineConsoleApp

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".whyline").mkdir()
    (tmp_path / ".whyline" / "model.json").write_text(
        json.dumps({"default_agent": "codex", "codex": "gpt-5.6"}),
        encoding="utf-8",
    )
    app = WhylineConsoleApp(root=tmp_path)
    assert app.session.agent == "codex"


def test_switch_repo_starts_on_that_repos_default(tmp_path, monkeypatch):
    from whyline.console.repl import switch_repo
    from whyline.console.session import ConsoleSession

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (second / ".whyline").mkdir()
    (second / ".whyline" / "model.json").write_text(
        json.dumps({"default_agent": "grok"}),
        encoding="utf-8",
    )
    session = ConsoleSession(root=first, agent="claude")
    switch_repo(session, second)
    assert session.root == second
    assert session.agent == "grok"
