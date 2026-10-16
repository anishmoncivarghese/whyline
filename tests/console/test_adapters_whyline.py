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


def test_run_whyline_command_gives_a_friendly_error_for_conversational_text(repo):
    # Command mode runs everything typed as `whyline <argv>` -- plain
    # conversation ("let's talk about X") used to hit argparse's own
    # "invalid choice" usage dump, which is accurate but doesn't explain
    # why ordinary text just failed. This checks the friendlier message
    # replaces it and points to /help and /route chat.
    previous = _chdir(repo.path)
    try:
        event = adapters.run_whyline_command(["let's", "talk"])
    finally:
        os.chdir(previous)
    assert event.kind == "error"
    assert "isn't a whyline command" in event.text
    assert "/route chat" in event.text
    assert "usage: whyline" not in event.text


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


def test_run_chat_turn_maps_none_to_no_limit_forwards_int_and_defaults_other_values_to_300(tmp_path, monkeypatch):
    from whyline_relay import chat

    seen = []

    def fake_run_turn(root, *, agent, prompt, settings, attachments, timeout_seconds=None, **kwargs):
        seen.append(timeout_seconds)
        return {"agent": agent, "response": "ok", "ok": True, "rate_limited": False}

    monkeypatch.setattr(chat, "run_turn", fake_run_turn)

    for value in (300, 900, 1800, 2700, 3600):
        event = adapters.run_chat_turn(
            tmp_path, agent="claude", prompt="ping", timeout_seconds=value
        )
        assert event.kind == "output"

    event = adapters.run_chat_turn(
        tmp_path, agent="claude", prompt="ping", timeout_seconds="none"
    )
    assert event.kind == "output"

    event = adapters.run_chat_turn(
        tmp_path, agent="claude", prompt="ping", timeout_seconds=900
    )
    assert event.kind == "output"

    for non_int in (None, "15m", "unlimited", True, False):
        event = adapters.run_chat_turn(
            tmp_path, agent="claude", prompt="ping", timeout_seconds=non_int
        )
        assert event.kind == "output"

    event = adapters.run_chat_turn(tmp_path, agent="claude", prompt="ping")
    assert event.kind == "output"

    assert seen == [
        300,
        900,
        1800,
        2700,
        3600,
        chat.NO_LIMIT,
        900,
        300,
        300,
        300,
        300,
        300,
        300,
    ]
    assert seen[5] is chat.NO_LIMIT


def test_repl_dispatch_passes_session_chat_timeout_seconds(tmp_path, monkeypatch):
    from whyline.console import repl
    from whyline.console.session import ConsoleSession, SessionEvent

    seen = []

    def fake_run_chat_turn(root, *, agent, prompt, timeout_seconds=None, **kwargs):
        seen.append((prompt, timeout_seconds))
        return SessionEvent(kind="output", text="ok")

    monkeypatch.setattr(adapters, "run_chat_turn", fake_run_chat_turn)

    session = ConsoleSession(root=tmp_path)
    for seconds in (300, 900, 1800, 2700, 3600, "none", 900):
        session.chat_timeout_seconds = seconds
        repl.dispatch(session, f"msg-{seconds}")

    assert seen == [
        ("msg-300", 300),
        ("msg-900", 900),
        ("msg-1800", 1800),
        ("msg-2700", 2700),
        ("msg-3600", 3600),
        ("msg-none", "none"),
        ("msg-900", 900),
    ]

