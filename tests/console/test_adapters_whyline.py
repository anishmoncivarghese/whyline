import os
from pathlib import Path

from whyline import paths
from whyline.console import adapters


def _chdir(path: Path):
    previous = os.getcwd()
    os.chdir(path)
    return previous


def test_run_whyline_command_captures_output_and_succeeds(repo):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    previous = _chdir(repo.path)
    try:
        event = adapters.run_whyline_command(["note", "a decision", "--because", "testing"])
    finally:
        os.chdir(previous)
    assert event.kind == "output"


def test_run_whyline_command_reports_a_nonzero_exit_as_an_error(repo, monkeypatch):
    previous = _chdir(repo.path)
    try:
        # "explain" with no whyline init here fails with EXIT_UNINITIALISED or
        # similar -- any real non-init'd repo already exercises a failure path
        # without needing to fake anything.
        event = adapters.run_whyline_command(["sync"])
    finally:
        os.chdir(previous)
    assert event.kind == "error"


def test_run_whyline_command_refuses_bare_account():
    event = adapters.run_whyline_command(["account"])
    assert event.kind == "error"
    assert "/model" in event.text


def test_run_whyline_command_refuses_bare_model():
    event = adapters.run_whyline_command(["model"])
    assert event.kind == "error"
    assert "/model" in event.text


def test_run_whyline_command_allows_account_status(repo, monkeypatch, tmp_path):
    from whyline import account

    home = tmp_path / "home"
    monkeypatch.setattr(account.paths.Path, "home", lambda: home)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    account.save_global({
        agent: {"plan": None, "available": True}
        for agent in ("codex", "claude", "antigravity", "grok")
    })
    previous = _chdir(repo.path)
    try:
        event = adapters.run_whyline_command(["account", "status"])
    finally:
        os.chdir(previous)
    assert event.kind == "output"


def test_run_whyline_command_allows_model_status(repo):
    previous = _chdir(repo.path)
    try:
        event = adapters.run_whyline_command(["model", "status"])
    finally:
        os.chdir(previous)
    assert event.kind == "output"
    assert "nothing set" in event.text.lower()


def test_relay_is_configured_true_when_config_toml_exists(tmp_path):
    from whyline.console import adapters
    config_dir = tmp_path / ".whyline" / "relay"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("", encoding="utf-8")
    assert adapters.relay_is_configured(tmp_path) is True


def test_relay_is_configured_false_when_absent(tmp_path):
    from whyline.console import adapters
    assert adapters.relay_is_configured(tmp_path) is False
