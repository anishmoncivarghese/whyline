from whyline.console import editor, repl
from whyline.console.session import SessionEvent


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
    from whyline.console import adapters

    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["model status", "/exit"]),
    )
    monkeypatch.setattr(
        adapters,
        "run_whyline_command",
        lambda argv: SessionEvent(kind="output", text=f"ran {argv}"),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("ran ['model', 'status']" in line for line in lines)


def test_ctrl_c_during_dispatch_is_caught_and_the_session_continues(
    tmp_path, monkeypatch
):
    from whyline.console import adapters

    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["model status", "/exit"]),
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
    assert any("claude model set; now the active chat agent." in line for line in lines)


def test_model_slash_command_with_no_available_agents_or_unknown_agent(
    tmp_path, monkeypatch
):
    from whyline import account

    monkeypatch.setattr(account, "available_agents", lambda root: set())
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["/model", "/exit"]),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("No agents detected as available" in line for line in lines)

    monkeypatch.setattr(account, "available_agents", lambda root: {"codex"})
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["/model claude", "/exit"]),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("claude is not available here" in line for line in lines)


def test_slash_help_and_stop_and_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(
        editor,
        "build_session",
        lambda root: FakePromptSession(["  ", "/help", "/stop", "/unknown", "/exit"]),
    )
    lines = []
    repl.run(tmp_path, print_fn=lines.append)
    assert any("Commands: /model" in line for line in lines)
    assert any("Nothing in flight to stop." in line for line in lines)
    assert any("Unknown command: /unknown." in line for line in lines)


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


def test_dispatch_is_public_and_routes_by_mode(tmp_path):
    from whyline.console.repl import dispatch
    from whyline.console.session import ConsoleSession
    from whyline.console import adapters
    session = ConsoleSession(root=tmp_path, mode="command")
    called = []
    original = adapters.run_whyline_command
    adapters.run_whyline_command = lambda argv: called.append(argv) or original(argv)
    try:
        dispatch(session, "model status")
    finally:
        adapters.run_whyline_command = original
    assert called == [["model", "status"]]

