from pathlib import Path

import pytest

from whyline.console import editor, repl
from whyline.console.session import SessionEvent


@pytest.fixture(autouse=True)
def _default_relay_configured(request):
    """Legacy keyboard console tests assume /route relay switches mode
    without handoff unless explicitly testing unconfigured behavior."""
    if "tmp_path" not in request.fixturenames:
        return
    if (
        "no_config" in request.node.name
        or "needs_setup" in request.node.name
        or "configured" in request.node.name
    ):
        return
    tmp_path = request.getfixturevalue("tmp_path")
    config_dir = tmp_path / ".whyline" / "relay"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text("", encoding="utf-8")


class FakePromptSession:
    """A minimal stand-in for prompt_toolkit.PromptSession: replays a fixed
    list of inputs, then raises EOFError (matching Ctrl+D) to end the loop."""

    def __init__(self, inputs):
        self._inputs = iter(inputs)

    def prompt(self, message=""):
        try:
            return next(self._inputs)
        except StopIteration:
            raise EOFError


def test_repl_prints_a_banner_and_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(
        editor, "build_session", lambda root: FakePromptSession(["/exit"])
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("whyline console" in line for line in lines)


def test_repl_shows_the_install_hint_if_the_editor_is_unavailable(
    tmp_path, monkeypatch
):
    def raise_unavailable(root):
        raise editor.EditorUnavailable("pip install 'whyline[console]'")

    monkeypatch.setattr(editor, "build_session", raise_unavailable)
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("whyline[console]" in line for line in lines)


def test_route_switches_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["/route relay", "/exit"]),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("Mode is now relay" in line for line in lines)


def test_route_rejects_an_unknown_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["/route nonsense", "/exit"]),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("Usage: /route" in line for line in lines)


def test_command_mode_dispatches_to_run_whyline_command(tmp_path, monkeypatch):
    """The old command-mode line `model status` is now `/timeline` from chat.

    `/model` stays the console's own command, so this uses a whyline
    subcommand the console does not own.
    """
    from whyline.console import adapters

    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["/timeline --limit 5", "/exit"]),
    )
    monkeypatch.setattr(
        adapters,
        "run_whyline_command",
        lambda argv: SessionEvent(kind="output", text=f"ran {argv}"),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("ran ['timeline', '--limit', '5']" in line for line in lines)


def test_ctrl_c_during_dispatch_is_caught_and_the_session_continues(
    tmp_path, monkeypatch
):
    from whyline.console import adapters

    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["/timeline", "/exit"]),
    )

    def raising(argv):
        raise KeyboardInterrupt

    monkeypatch.setattr(adapters, "run_whyline_command", raising)
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("Cancelled" in line for line in lines)


def test_model_slash_command_lists_available_agents(tmp_path, monkeypatch):
    from whyline import account

    monkeypatch.setattr(account, "available_agents", lambda root: {"claude", "codex"})
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["/model", "/exit"]),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("claude" in line and "codex" in line for line in lines)


def test_model_slash_command_sets_the_active_agent(tmp_path, monkeypatch):
    from whyline import account

    monkeypatch.setattr(account, "available_agents", lambda root: {"claude"})
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["/model claude", "/exit"]),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("claude is now the active chat agent" in line for line in lines)


def test_end_to_end_model_route_relay_doctor_and_chat(tmp_path, monkeypatch):
    """Exercises /model, /route relay -> doctor, /route chat -> a turn,
    /exit -- confirming the console layer disturbs no relay/chat state of
    its own (spec's own end-to-end bar)."""
    from whyline import account
    from whyline.console import adapters

    monkeypatch.setattr(account, "available_agents", lambda root: {"claude"})
    monkeypatch.setattr(
        adapters,
        "run_doctor",
        lambda root: SessionEvent(kind="output", text="All checks passed."),
    )
    monkeypatch.setattr(
        adapters,
        "run_chat_turn",
        lambda root, *, agent, prompt: SessionEvent(
            kind="output", text=f"[{agent}] response to {prompt!r}"
        ),
    )
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(
            ["/model claude", "/route relay", "doctor", "/route chat", "hello", "/exit"]
        ),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("claude is now the active chat agent" in line for line in lines)
    assert any("Mode is now relay" in line for line in lines)
    assert any("All checks passed" in line for line in lines)
    assert any("Mode is now chat" in line for line in lines)
    assert any("response to 'hello'" in line for line in lines)


def test_model_slash_command_sets_model_and_active_agent(tmp_path, monkeypatch):
    from whyline import account, model

    recorded = []
    monkeypatch.setattr(account, "available_agents", lambda root: {"claude"})
    monkeypatch.setattr(
        model, "set_one", lambda root, agent, m: recorded.append((agent, m))
    )
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["/model claude sonnet-3.7", "/exit"]),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert recorded == [("claude", "sonnet-3.7")]
    assert any("claude is now the active chat agent" in line for line in lines)


def test_model_slash_command_with_no_available_agents_or_unknown_agent(
    tmp_path, monkeypatch
):
    from whyline import account

    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(account, "available_agents", lambda root: set())
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["/model", "/model cluade", "/exit"]),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    # every agent is still listed, each with why it's missing
    table = next(line for line in lines if line.startswith("Agents:"))
    for agent in ("claude", "codex", "antigravity", "grok"):
        assert f"{agent}" in table
    assert table.count("✗ not installed") == 4
    assert any("Unknown agent 'cluade'" in line for line in lines)

    monkeypatch.setattr(account, "available_agents", lambda root: {"codex"})
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["/model claude", "/exit"]),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("claude isn't available: not installed" in line for line in lines)


def test_slash_help_and_stop_and_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["  ", "/help", "/stop", "/unknown", "/exit"]),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("/model" in line and "Commands:" in line for line in lines)
    assert any("Nothing in flight to stop." in line for line in lines)
    assert any("Unknown command /unknown." in line for line in lines)


def test_slash_status_and_history(tmp_path, monkeypatch):
    from whyline.console import adapters

    monkeypatch.setattr(
        adapters,
        "run_status",
        lambda root: SessionEvent(kind="pause", text="Paused: waiting on review"),
    )
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["/status", "/history", "/exit"]),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    # _PREFIX has "pause": "⏸ "
    assert any("⏸ Paused: waiting on review" in line for line in lines)


def test_relay_mode_subcommands(tmp_path, monkeypatch):
    from whyline.console import adapters

    monkeypatch.setattr(
        adapters,
        "run_status",
        lambda root: SessionEvent(kind="output", text="status ok"),
    )
    monkeypatch.setattr(
        adapters,
        "run_relay_oneshot",
        lambda root, argv: SessionEvent(kind="output", text=f"oneshot {argv}"),
    )
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(
            ["/route relay", "status", "start --plan P", "resume", "invalid", "/exit"]
        ),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("status ok" in line for line in lines)
    assert any("oneshot ['start', '--plan', 'P']" in line for line in lines)
    assert any("oneshot ['resume']" in line for line in lines)
    assert any("⚠ Unknown relay command: 'invalid'" in line for line in lines)


def test_run_with_direct_prompt_session_argument(tmp_path):
    lines = []
    repl.run(tmp_path, print_fn=lines.append, prompt_session=FakePromptSession(["/exit"]))
    assert any("whyline console" in line for line in lines)


def test_handoff_slash_command_dispatches_to_run_last_handoff(tmp_path, monkeypatch):
    from whyline.console import adapters

    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["/handoff", "/exit"]),
    )
    monkeypatch.setattr(
        adapters,
        "run_last_handoff",
        lambda root: SessionEvent(kind="output", text="the last handoff"),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("the last handoff" in line for line in lines)


def test_dispatch_is_public_and_routes_by_mode(tmp_path, monkeypatch):
    """Whyline commands run from chat as /<command>, not via a command mode."""
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession
    from whyline.console import adapters
    session = ConsoleSession(root=tmp_path)
    called = []
    monkeypatch.setattr(
        adapters,
        "run_whyline_command",
        lambda argv: called.append(argv) or SessionEvent(kind="output", text="ok"),
    )
    event = handle_slash_command(session, "/timeline --limit 5")
    assert session.mode == "chat"
    assert called == [["timeline", "--limit", "5"]]
    assert event is not None and event.text == "ok"


def test_handle_slash_command_help(tmp_path):
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession
    session = ConsoleSession(root=tmp_path)
    event = handle_slash_command(session, "/help")
    assert event is not None
    assert "Commands:" in event.text


def test_help_explains_modes_and_what_each_command_does(tmp_path):
    from whyline.console.repl import SLASH_COMMANDS, handle_slash_command
    from whyline.console.session import ConsoleSession
    event = handle_slash_command(ConsoleSession(root=tmp_path), "/help")
    for mode in ("Chat", "Relay", "Agents"):
        assert mode in event.text
    assert "Command  what you type" not in event.text
    # every command gets its own line with a description, not a bare list
    for command in SLASH_COMMANDS:
        line = next(l for l in event.text.splitlines() if l.strip().startswith(command))
        assert len(line.strip()) > len(command) + 5


def test_route_to_the_current_mode_says_so_instead_of_repeating(tmp_path):
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession
    session = ConsoleSession(root=tmp_path, mode="chat")
    event = handle_slash_command(session, "/route chat")
    assert event.text == "Already in chat mode."


def test_route_to_current_relay_mode_does_not_rerun_setup(tmp_path):
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession
    session = ConsoleSession(root=tmp_path, mode="relay")
    event = handle_slash_command(session, "/route relay")
    assert event.kind == "output"


def test_model_lists_agents_and_marks_the_active_one(tmp_path, monkeypatch):
    from whyline import account
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession
    monkeypatch.setattr(account, "available_agents", lambda root: {"claude", "codex"})
    session = ConsoleSession(root=tmp_path, agent="codex")
    event = handle_slash_command(session, "/model")
    lines = event.text.splitlines()
    codex_line = next(line for line in lines if line.strip().startswith("codex"))
    claude_line = next(line for line in lines if line.strip().startswith("claude"))
    assert "(active)" in codex_line and "(active)" not in claude_line
    assert "/model <agent>" in event.text


def test_handle_slash_command_returns_none_for_ordinary_text(tmp_path):
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession
    session = ConsoleSession(root=tmp_path)
    assert handle_slash_command(session, "hello there") is None


def test_handle_slash_command_route_relay_needs_setup(tmp_path):
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession
    session = ConsoleSession(root=tmp_path, mode="chat")
    event = handle_slash_command(session, "/route relay")
    assert event is not None
    assert event.kind == "needs_setup"
    assert session.mode == "chat"  # unchanged -- the handoff hasn't happened yet


def test_handle_slash_command_route_relay_switches_when_configured(tmp_path):
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession
    config_dir = tmp_path / ".whyline" / "relay"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("", encoding="utf-8")
    session = ConsoleSession(root=tmp_path, mode="chat")
    event = handle_slash_command(session, "/route relay")
    assert event is not None
    assert event.kind != "needs_setup"
    assert session.mode == "relay"


def test_handle_slash_command_route_invalid_mode(tmp_path):
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession
    session = ConsoleSession(root=tmp_path)
    event = handle_slash_command(session, "/route nonsense")
    assert event is not None
    assert "Usage: /route" in event.text


def test_route_relay_with_no_config_execs_into_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(
        editor, "build_session",
        lambda root: FakePromptSession(["/route relay", "/exit"]),
    )
    calls = []
    lines = []
    repl.run(
        tmp_path, print_fn=lines.append,
        exec_fn=lambda binary, argv: calls.append((binary, argv)),
    )
    assert calls == [("whyline", ["whyline", "relay", "setup"])]
    # The user sees why they're being handed off, before it happens --
    # unlike today's plain entry menu (which execs silently), this is a
    # deliberate small improvement, not a parity requirement.
    assert any("No relay setup found" in line for line in lines)



def test_model_agent_name_is_case_insensitive(tmp_path, monkeypatch):
    from whyline import account
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession
    monkeypatch.setattr(account, "available_agents", lambda root: {"claude", "codex"})
    session = ConsoleSession(root=tmp_path)
    event = handle_slash_command(session, "/model Claude")
    assert event.kind == "output"
    assert session.agent == "claude"


def test_help_shows_a_real_model_example_not_bracket_notation(tmp_path):
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession
    event = handle_slash_command(ConsoleSession(root=tmp_path), "/help")
    assert "/model claude opus" in event.text
    assert "[agent" not in event.text


def test_dispatch_turns_a_missing_relay_into_a_fix_it_message(tmp_path, monkeypatch):
    from whyline.console import adapters
    from whyline.console.repl import dispatch
    from whyline.console.session import ConsoleSession

    def missing(*args, **kwargs):
        raise ModuleNotFoundError("No module named 'whyline_relay'", name="whyline_relay")

    monkeypatch.setattr(adapters, "run_chat_turn", missing)
    event = dispatch(ConsoleSession(root=tmp_path, mode="chat"), "hello")
    assert event.kind == "error"
    assert "uv tool install --reinstall whyline" in event.text


def test_dispatch_does_not_swallow_other_missing_modules(tmp_path, monkeypatch):
    import pytest
    from whyline.console import adapters
    from whyline.console.repl import dispatch
    from whyline.console.session import ConsoleSession

    def missing(*args, **kwargs):
        raise ModuleNotFoundError("No module named 'yaml'", name="yaml")

    monkeypatch.setattr(adapters, "run_chat_turn", missing)
    with pytest.raises(ModuleNotFoundError):
        dispatch(ConsoleSession(root=tmp_path, mode="chat"), "hello")


# --- agent status, /model refresh and /login --------------------------------


def _fake_which(installed):
    binaries = {"claude": "claude", "codex": "codex", "antigravity": "agy", "grok": "grok"}
    wanted = {binaries[a] for a in installed}
    return lambda name: f"/usr/bin/{name}" if name in wanted else None


def test_agent_status_explains_each_unavailable_agent(tmp_path, monkeypatch):
    from whyline import account

    account.save_global({
        "claude": {"plan": "max", "available": True},
        "codex": {"plan": "unknown", "available": False, "reason": "no auth.json"},
        "antigravity": {"available": False, "manual": True},
        "grok": {"plan": None, "available": False},
    })
    monkeypatch.setattr(account, "available_agents", lambda root: {"claude"})
    status = account.agent_status(
        tmp_path, which=_fake_which({"claude", "codex", "antigravity"})
    )
    assert status["claude"] == {"available": True, "label": "max", "hint": None}
    assert status["codex"]["label"] == "not logged in"
    assert status["codex"]["hint"] == "Run /login codex"
    assert status["antigravity"]["label"] == "turned off"
    assert "whyline account enable antigravity" in status["antigravity"]["hint"]
    assert status["grok"]["label"] == "not installed"


def test_agent_status_labels_api_key_and_unchecked_logins(tmp_path, monkeypatch):
    from whyline import account

    account.save_global({
        "claude": {"plan": None, "available": True},
        "codex": {"plan": "plus", "available": True},
        "antigravity": {"plan": None, "available": True},
        "grok": {"plan": None, "available": True},
    })
    monkeypatch.setattr(
        account, "available_agents", lambda root: {"claude", "codex", "antigravity", "grok"}
    )
    status = account.agent_status(tmp_path, which=_fake_which(set()))
    assert status["claude"]["label"] == "API key"
    assert status["codex"]["label"] == "plus"
    assert status["grok"]["label"] == "installed (login not checked)"


def test_model_rechecks_before_refusing_and_accepts_a_newly_available_agent(
    tmp_path, monkeypatch
):
    from whyline import account
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession

    available = {"claude"}
    refreshed = []

    def refresh():
        refreshed.append(1)
        available.add("codex")  # e.g. the user logged into codex meanwhile
        return {}

    monkeypatch.setattr(account, "available_agents", lambda root: set(available))
    monkeypatch.setattr(account, "refresh", refresh)
    session = ConsoleSession(root=tmp_path)
    event = handle_slash_command(session, "/model codex")
    assert refreshed == [1]
    assert event.kind == "output"
    assert session.agent == "codex"


def test_model_on_an_available_agent_does_not_recheck(tmp_path, monkeypatch):
    from whyline import account
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession

    monkeypatch.setattr(account, "available_agents", lambda root: {"claude"})
    monkeypatch.setattr(account, "refresh", lambda: (_ for _ in ()).throw(AssertionError))
    event = handle_slash_command(ConsoleSession(root=tmp_path), "/model claude")
    assert "fable | opus | sonnet" in event.text
    assert "model: its default" in event.text


def test_model_refresh_rechecks_and_shows_the_table(tmp_path, monkeypatch):
    from whyline import account
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession

    calls = []
    monkeypatch.setattr(account, "refresh", lambda: calls.append(1) or {})
    monkeypatch.setattr(account, "available_agents", lambda root: {"claude"})
    event = handle_slash_command(ConsoleSession(root=tmp_path), "/model refresh")
    assert calls == [1]
    assert event.text.startswith("Re-checked every agent.")
    assert "Agents:" in event.text


def test_model_table_shows_each_agents_configured_model(tmp_path, monkeypatch):
    from whyline import account, model
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession

    monkeypatch.setattr(account, "available_agents", lambda root: {"claude"})
    model.set_one(tmp_path, "claude", "opus")
    event = handle_slash_command(ConsoleSession(root=tmp_path), "/model")
    claude_line = next(l for l in event.text.splitlines() if l.strip().startswith("claude"))
    assert "model: opus" in claude_line and "(active)" in claude_line


def test_login_validates_the_agent(tmp_path, monkeypatch):
    import shutil
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession

    session = ConsoleSession(root=tmp_path)
    assert "Usage: /login" in handle_slash_command(session, "/login").text
    assert "Unknown agent 'cluade'" in handle_slash_command(session, "/login cluade").text
    antigravity = handle_slash_command(session, "/login antigravity")
    assert antigravity.kind == "output" and "Run `agy` in a terminal" in antigravity.text
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert "isn't installed" in handle_slash_command(session, "/login grok").text


def test_login_on_an_installed_agent_asks_the_console_to_run_it(tmp_path, monkeypatch):
    import shutil
    from whyline.console.repl import handle_slash_command, login_argv
    from whyline.console.session import ConsoleSession

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    event = handle_slash_command(ConsoleSession(root=tmp_path), "/login Claude")
    assert (event.kind, event.text) == ("needs_login", "claude")
    assert login_argv("claude") == ["claude", "auth", "login"]
    assert login_argv("codex") == ["codex", "login"]
    assert login_argv("grok") == ["grok", "login"]


def test_repl_login_runs_the_agents_own_login_then_rechecks(tmp_path, monkeypatch):
    import shutil
    from whyline import account

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    available = set()
    monkeypatch.setattr(account, "available_agents", lambda root: set(available))
    monkeypatch.setattr(account, "refresh", lambda: available.add("codex") or {})
    monkeypatch.setattr(
        editor, "build_session", lambda root: FakePromptSession(["/login codex", "/exit"])
    )
    ran = []
    lines = []
    repl.run(tmp_path, print_fn=lines.append, login_fn=lambda argv: ran.append(argv) or 0)
    assert ran == [["codex", "login"]]
    assert any("codex is ready" in line for line in lines)


def test_repl_login_that_does_not_take_says_so(tmp_path, monkeypatch):
    import shutil
    from whyline import account

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(account, "available_agents", lambda root: set())
    monkeypatch.setattr(
        editor, "build_session", lambda root: FakePromptSession(["/login claude", "/exit"])
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append, login_fn=lambda argv: 1)
    assert any(
        "claude still isn't available: not logged in (login exited with 1)" in line
        for line in lines
    )


# --- /repo, /brainstorm, context and busy labels ------------------------------


def _git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    return path.resolve()


def test_repo_shows_the_current_repository(tmp_path):
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession

    root = _git_repo(tmp_path / "proj")
    event = handle_slash_command(ConsoleSession(root=root), "/repo")
    assert "Repository: proj" in event.text and "/repo <path>" in event.text


def test_repo_rejects_missing_and_non_git_paths_and_notices_the_same_repo(tmp_path):
    from whyline.console.repl import handle_slash_command
    from whyline.console.session import ConsoleSession

    root = _git_repo(tmp_path / "proj")
    plain = tmp_path / "plain"
    plain.mkdir()
    session = ConsoleSession(root=root)
    assert "No such directory" in handle_slash_command(session, "/repo /nope/not/here").text
    assert "isn't inside a git repository" in handle_slash_command(session, f"/repo {plain}").text
    (root / "sub").mkdir()
    same = handle_slash_command(session, f"/repo {root / 'sub'}")
    assert same.text == "Already in proj."


def test_repo_to_another_repository_asks_for_confirmation(tmp_path):
    from whyline.console.repl import handle_slash_command, repo_switch_warning
    from whyline.console.session import ConsoleSession

    root = _git_repo(tmp_path / "proj")
    other = _git_repo(tmp_path / "other")
    session = ConsoleSession(root=root)
    event = handle_slash_command(session, f"/repo {other}")
    assert (event.kind, event.text) == ("confirm_repo", str(other))
    assert session.root == root  # nothing changes until confirmed
    assert "clears the transcript" in repo_switch_warning(other)


def test_switch_repo_moves_root_and_cwd_and_clears_the_transcript(tmp_path, monkeypatch):
    import os
    from whyline.console.repl import switch_repo
    from whyline.console.session import ConsoleSession, SessionEvent

    monkeypatch.chdir(tmp_path)
    root = _git_repo(tmp_path / "proj")
    other = _git_repo(tmp_path / "other")
    session = ConsoleSession(root=root, mode="relay")
    session.record(SessionEvent(kind="output", text="old text"))
    event = switch_repo(session, other)
    assert session.root == other
    assert Path(os.getcwd()).resolve() == other
    assert session.transcript == []
    # the relay isn't set up in the new repo, so relay mode would only fail
    assert session.mode == "chat"
    assert "Now working in other" in event.text and "you're in chat" in event.text


def test_parse_brainstorm_agents():
    from whyline.console.repl import parse_brainstorm_agents

    assert parse_brainstorm_agents("1,2,4") == ["claude", "codex", "grok"]
    assert parse_brainstorm_agents("grok, Claude") == ["claude", "grok"]
    assert parse_brainstorm_agents("all") == ["claude", "codex", "antigravity", "grok"]
    assert parse_brainstorm_agents("9") is None
    assert parse_brainstorm_agents("") is None


def test_context_and_busy_labels(tmp_path):
    from whyline import model
    from whyline.console.repl import busy_label, context_label
    from whyline.console.session import ConsoleSession

    session = ConsoleSession(root=tmp_path, mode="chat")
    assert context_label(session) == "claude · default model"
    model.set_one(tmp_path, "codex", "gpt-5")
    session.agent = "codex"
    assert context_label(session) == "codex · gpt-5"
    assert busy_label(session) == "codex is thinking"
    session.mode = "relay"
    assert busy_label(session) == "relay is working"


def test_repl_repo_switch_needs_a_yes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = _git_repo(tmp_path / "proj")
    other = _git_repo(tmp_path / "other")
    monkeypatch.setattr(
        editor, "build_session",
        lambda r: FakePromptSession([f"/repo {other}", "n", f"/repo {other}", "y", "/repo", "/exit"]),
    )
    lines = []
    repl.run(root, print_fn=lines.append)
    assert "Staying put." in lines
    assert any("Now working in other" in line for line in lines)
    assert any(line.startswith("Repository: other") for line in lines)


def test_repl_brainstorm_asks_then_runs(tmp_path, monkeypatch):
    from whyline import account
    from whyline.console import adapters
    from whyline.console.session import SessionEvent

    monkeypatch.setattr(account, "available_agents", lambda root: {"claude", "codex"})
    calls = []
    monkeypatch.setattr(
        adapters, "run_brainstorm",
        lambda root, **kw: calls.append(kw) or SessionEvent(kind="output", text="synthesis"),
    )
    monkeypatch.setattr(
        editor, "build_session",
        lambda r: FakePromptSession(
            ["/brainstorm", "retry policy", "bogus", "1,2", "2", "codex", "/exit"]
        ),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert calls[0]["topic"] == "retry policy"
    assert calls[0]["agents"] == ["claude", "codex"]
    assert calls[0]["passes"] == 2 and calls[0]["final_agent"] == "codex"
    assert any("Use numbers or names" in line for line in lines)  # "bogus" re-asked
    assert "synthesis" in lines


def test_repl_brainstorm_failure_does_not_end_the_console(tmp_path, monkeypatch):
    from whyline import account
    from whyline.console import adapters

    monkeypatch.setattr(account, "available_agents", lambda root: {"claude"})

    def boom(root, **kw):
        raise RuntimeError("agent crashed")

    monkeypatch.setattr(adapters, "run_brainstorm", boom)
    monkeypatch.setattr(
        editor, "build_session",
        lambda r: FakePromptSession(["/brainstorm", "t", "1", "", "", "/help", "/exit"]),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("Brainstorm stopped: agent crashed" in line for line in lines)
    assert any("Commands:" in line for line in lines)  # still running afterwards


# --- home-directory repo guard and unknown commands ------------------------------------


def test_chat_relay_and_brainstorm_refuse_to_run_in_the_home_directory_repo(tmp_path, monkeypatch):
    from whyline.console import adapters
    from whyline.console.repl import dispatch, handle_slash_command
    from whyline.console.session import ConsoleSession

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(adapters, "run_chat_turn", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    session = ConsoleSession(root=tmp_path, mode="chat")
    event = dispatch(session, "hello")
    assert event.kind == "error" and "home directory" in event.text and "/repo" in event.text
    session.mode = "relay"
    assert "home directory" in dispatch(session, "status").text
    assert "home directory" in handle_slash_command(session, "/brainstorm").text
    # a whyline command still runs there, typed as /<command>
    seen = []
    monkeypatch.setattr(
        adapters,
        "run_whyline_command",
        lambda argv: seen.append(argv) or SessionEvent(kind="output", text="timeline ok"),
    )
    event = handle_slash_command(session, "/timeline")
    assert seen == [["timeline"]]
    assert "home directory" not in event.text


def test_home_repo_warning_names_the_folder_you_started_in(tmp_path, monkeypatch):
    from whyline.console.repl import home_repo_warning

    project = tmp_path / "TradingPlatform"
    project.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    text = home_repo_warning(tmp_path, project)
    assert "TradingPlatform" in text and "git init" in text and "whyline init" in text
    assert home_repo_warning(tmp_path / "elsewhere", project) is None


def test_unknown_commands_are_explained_not_sent_to_the_agent():
    from whyline.console.repl import unknown_command_text

    assert "/model" in unknown_command_text("/agents")
    assert "/model codex" in unknown_command_text("/default codex")
    assert "/help" in unknown_command_text("/frobnicate")
