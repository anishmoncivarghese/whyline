import pytest
from whyline.console import tui


def test_tui_available_flag_exists():
    assert isinstance(tui.TUI_AVAILABLE, bool)


def test_launch_raises_a_clear_error_without_textual(monkeypatch, tmp_path):
    monkeypatch.setattr(tui, "TUI_AVAILABLE", False)
    with pytest.raises(tui.TuiUnavailable, match=r"reinstall whyline"):
        tui.launch(tmp_path)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_app_composes_header_transcript_prompt_and_controls(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        assert app.query_one("#transcript") is not None
        assert app.query_one("#prompt") is not None
        for button_id in (
            "send", "model", "mode-command", "mode-chat", "mode-relay",
            "history", "stop", "help", "copy",
            "relay-plan", "relay-setup", "relay-resume",
        ):
            assert app.query_one(f"#{button_id}") is not None


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_send_dispatches_in_a_worker_and_renders_the_result(tmp_path, monkeypatch):
    from whyline.console.session import SessionEvent

    monkeypatch.setattr(
        tui, "dispatch",
        lambda session, text: SessionEvent(kind="output", text=f"ran {text!r}"),
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", tui.Input)
        prompt.value = "hello"
        await pilot.click("#send")
        await app.workers.wait_for_complete()
        await pilot.pause()  # let the call_from_thread land
        transcript = app.query_one("#transcript", tui.RichLog)
        assert any("ran 'hello'" in str(line) for line in transcript.lines)
        assert prompt.value == ""


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_send_ignores_empty_or_whitespace_prompt(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(tui, "dispatch", lambda session, text: called.append(text))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        transcript = app.query_one("#transcript", tui.RichLog)
        baseline = len(app.session.transcript)  # the on_mount onboarding banner
        prompt = app.query_one("#prompt", tui.Input)
        prompt.value = "   \n  "
        await pilot.click("#send")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert called == []
        assert len(app.session.transcript) == baseline


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_dispatch_error_renders_as_error_event(tmp_path, monkeypatch):
    def failing_dispatch(session, text):
        raise RuntimeError("boom")

    monkeypatch.setattr(tui, "dispatch", failing_dispatch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", tui.Input)
        prompt.value = "fail"
        await pilot.click("#send")
        await app.workers.wait_for_complete()
        await pilot.pause()
        transcript = app.query_one("#transcript", tui.RichLog)
        assert any("⚠ boom" in str(line) for line in transcript.lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_superseded_dispatch_token_discards_result(tmp_path, monkeypatch):
    import threading
    from whyline.console.session import SessionEvent

    slow_started = threading.Event()
    release = threading.Event()

    def slow_dispatch(session, text):
        slow_started.set()
        # Held open until the token is superseded. A fixed sleep here raced
        # on slow CI runners: it could elapse while pilot.click was still
        # running, so the reply legitimately landed before the supersede.
        release.wait(timeout=2)
        return SessionEvent(kind="output", text="slow output")

    monkeypatch.setattr(tui, "dispatch", slow_dispatch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        transcript = app.query_one("#transcript", tui.RichLog)
        baseline = len(app.session.transcript)  # the on_mount onboarding banner
        prompt = app.query_one("#prompt", tui.Input)
        prompt.value = "slow"
        await pilot.click("#send")
        # Wait for slow dispatch to begin running in worker thread
        assert slow_started.wait(timeout=2.0)
        # Supersede the token, then let the dispatch finish
        app._dispatch_token = object()
        release.set()
        # Wait for worker to finish
        await app.workers.wait_for_complete()
        await pilot.pause()
        # only the echoed "› slow" was added -- never the stale reply
        added = app.session.transcript[baseline:]
        assert [(e.kind, e.text) for e in added] == [("input", "slow")]
        assert not any("slow output" in str(line) for line in transcript.lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_model_button_dispatches_the_same_text_as_typing_it(tmp_path, monkeypatch):
    from whyline.console.session import SessionEvent

    seen = []
    monkeypatch.setattr(
        tui, "handle_slash_command",
        lambda session, text: seen.append(text) or SessionEvent(kind="output", text="ok"),
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#model")
        await pilot.pause()
    assert seen == ["/model"]


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_mode_history_help_buttons_dispatch_their_slash_commands(tmp_path, monkeypatch):
    from whyline.console.session import SessionEvent

    seen = []
    monkeypatch.setattr(
        tui, "handle_slash_command",
        lambda session, text: seen.append(text) or SessionEvent(kind="output", text="ok"),
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#mode-relay")
        await pilot.click("#mode-chat")
        await pilot.click("#history")
        await pilot.click("#help")
        await pilot.pause()
    assert seen == ["/route relay", "/route chat", "/history", "/help"]


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_stop_cancels_the_active_worker(tmp_path, monkeypatch):
    import threading
    from whyline.console.session import SessionEvent

    started = threading.Event()
    release = threading.Event()

    def slow_dispatch(session, text):
        started.set()
        release.wait(timeout=2)  # held open until the test itself lets go
        return SessionEvent(kind="output", text="too late")

    monkeypatch.setattr(tui, "dispatch", slow_dispatch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", tui.Input)
        prompt.value = "long running"
        await pilot.click("#send")
        assert started.wait(timeout=2.0)  # let the worker actually start and block on release
        await pilot.click("#stop")  # invalidates the token while still blocked
        release.set()  # now let the blocked dispatch finish, "too late"
        await pilot.pause()
        await pilot.pause()  # give call_from_thread a beat to have run, if it were going to
        transcript = app.query_one("#transcript", tui.RichLog)
        assert not any("too late" in str(line) for line in transcript.lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_model_button_actually_lists_available_agents(tmp_path, monkeypatch):
    from whyline import account

    monkeypatch.setattr(account, "available_agents", lambda root: {"claude", "codex"})
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#model")
        await pilot.pause()
        transcript = app.query_one("#transcript", tui.RichLog)
        lines = [str(line) for line in transcript.lines]
        assert any("claude" in line and "✓" in line for line in lines)
        assert any("codex" in line and "✓" in line for line in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_relay_mode_without_config_stays_in_the_console(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#mode-relay")
        await pilot.pause()
        assert app._exec_after is None
        assert app.session.mode == "relay"
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("use Plan, then Set up" in line for line in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_plan_and_setup_are_only_enabled_in_relay_mode(tmp_path, monkeypatch):
    from whyline.console import relay_ops
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        for button_id in ("relay-plan", "relay-setup", "relay-resume"):
            assert app.query_one(f"#{button_id}", tui.Button).disabled
        await pilot.click("#mode-relay")
        await pilot.pause()
        assert not app.query_one("#relay-plan", tui.Button).disabled
        assert not app.query_one("#relay-setup", tui.Button).disabled
        assert app.query_one("#relay-resume", tui.Button).disabled  # nothing paused
        await pilot.click("#mode-chat")
        await pilot.pause()
        assert app.query_one("#relay-plan", tui.Button).disabled


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_resume_is_enabled_when_a_run_is_paused(tmp_path, monkeypatch):
    from whyline.console import relay_ops
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#mode-relay")
        await pilot.pause()
        assert not app.query_one("#relay-resume", tui.Button).disabled


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_all_bottom_buttons_fit_in_80_columns(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)):
        for button in app.query("#controls Button"):
            assert button.region.right <= 80, button.id


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_plan_refuses_in_the_home_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(tui.Path, "home", classmethod(lambda cls: tmp_path))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.click("#relay-plan")
        await pilot.pause()
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        # "Not running agents here" is the refusal itself; the startup warning
        # also mentions the home directory, so it can't be the check.
        assert any("Not running agents here" in line for line in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
def test_launch_performs_the_deferred_exec_after_app_run_returns(tmp_path, monkeypatch):
    calls = []

    class FakeApp:
        def __init__(self, *, root):
            self._exec_after = None

        def run(self):
            self._exec_after = ("whyline", ["whyline", "relay", "setup"])

    monkeypatch.setattr(tui, "WhylineConsoleApp", FakeApp)
    tui.launch(tmp_path, exec_fn=lambda binary, argv: calls.append((binary, argv)))
    assert calls == [("whyline", ["whyline", "relay", "setup"])]


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_copy_button_pushes_transcript_to_clipboard(tmp_path, monkeypatch):
    from whyline.console.session import SessionEvent

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.transcript.clear()  # drop the on_mount onboarding banner
        app.session.record(SessionEvent(kind="output", text="earlier output"))
        copied = []
        monkeypatch.setattr(tui, "_system_copy", lambda text: copied.append(text) or True)
        monkeypatch.setattr(app, "copy_to_clipboard", lambda text: copied.append(("osc52", text)))
        await pilot.click("#copy")
        await pilot.pause()
        assert copied == ["earlier output"]  # the system clipboard, not the escape code
        transcript = app.query_one("#transcript", tui.RichLog)
        assert any("copied to clipboard" in str(line) for line in transcript.lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_copy_button_with_no_transcript_does_not_touch_the_clipboard(tmp_path, monkeypatch):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.transcript.clear()  # drop the on_mount onboarding banner
        copied = []
        monkeypatch.setattr(app, "copy_to_clipboard", lambda text: copied.append(text))
        await pilot.click("#copy")
        await pilot.pause()
        assert copied == []
        transcript = app.query_one("#transcript", tui.RichLog)
        assert any("nothing to copy" in str(line) for line in transcript.lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_mount_shows_the_default_mode_and_an_onboarding_banner(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        assert app.sub_title == "mode: command"
        transcript = app.query_one("#transcript", tui.RichLog)
        assert any("Command runs" in str(line) for line in transcript.lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_route_button_updates_the_mode_indicator(tmp_path, monkeypatch):
    from whyline.console import adapters

    monkeypatch.setattr(adapters, "relay_is_configured", lambda root: True)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#mode-relay")
        await pilot.pause()
        assert app.sub_title == "mode: relay"


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_transcript_gets_most_of_the_screen_not_an_equal_three_way_split(tmp_path):
    # Regression test: RichLog, TextArea and Horizontal all default to
    # `height: 1fr` in Textual, which used to split the screen into three
    # equal bands -- the transcript only got a third of it, and the button
    # row's band was taller than its buttons, leaving dead space beneath
    # them. The transcript should now get the lion's share.
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        transcript = app.query_one("#transcript", tui.RichLog)
        prompt = app.query_one("#prompt", tui.Input)
        buttons_row = app.query_one("#controls")
        assert transcript.region.height > prompt.region.height
        assert transcript.region.height > buttons_row.region.height
        # The button row should hug its buttons, not leave dead space
        # beneath them.
        model_button = app.query_one("#model", tui.Button)
        assert buttons_row.region.height == model_button.region.height


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
def test_launch_does_not_exec_when_nothing_was_requested(tmp_path, monkeypatch):
    calls = []

    class FakeApp:
        def __init__(self, *, root):
            self._exec_after = None

        def run(self):
            pass  # ordinary exit, no setup requested

    monkeypatch.setattr(tui, "WhylineConsoleApp", FakeApp)
    tui.launch(tmp_path, exec_fn=lambda binary, argv: calls.append((binary, argv)))
    assert calls == []


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_send_sits_to_the_right_of_the_prompt_on_the_same_row(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        prompt = app.query_one("#prompt", tui.Input)
        send = app.query_one("#send", tui.Button)
        assert send.region.x > prompt.region.x + prompt.region.width - 1
        assert prompt.region.y <= send.region.y < prompt.region.y + prompt.region.height + 1
        assert prompt.region.width > 40  # the prompt takes the rest of the row


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_placeholder_tells_you_what_to_type_for_the_current_mode(tmp_path, monkeypatch):
    from whyline.console import adapters

    monkeypatch.setattr(adapters, "relay_is_configured", lambda root: True)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", tui.Input)
        assert "whyline" in prompt.placeholder
        await pilot.click("#mode-chat")
        await pilot.pause()
        assert "Message claude" in prompt.placeholder
        await pilot.click("#mode-relay")
        await pilot.pause()
        assert "relay" in prompt.placeholder.lower()


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_active_mode_button_is_highlighted(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        assert app.query_one("#mode-command", tui.Button).variant == "primary"
        assert app.query_one("#mode-chat", tui.Button).variant == "default"
        await pilot.click("#mode-chat")
        await pilot.pause()
        assert app.query_one("#mode-chat", tui.Button).variant == "primary"
        assert app.query_one("#mode-command", tui.Button).variant == "default"
        assert app.sub_title == "mode: chat"


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_enter_submits_and_echoes_what_you_typed(tmp_path, monkeypatch):
    from whyline.console.session import SessionEvent

    monkeypatch.setattr(
        tui, "dispatch", lambda session, text: SessionEvent(kind="output", text="reply")
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#prompt")
        await pilot.press(*"hi there", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("› hi there" in line for line in lines)
        assert any("reply" in line for line in lines)
        assert app.query_one("#prompt", tui.Input).value == ""


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_stop_is_only_enabled_while_a_reply_is_running(tmp_path, monkeypatch):
    import threading
    from whyline.console.session import SessionEvent

    release = threading.Event()

    def slow_dispatch(session, text):
        release.wait(timeout=2)
        return SessionEvent(kind="output", text="done")

    monkeypatch.setattr(tui, "dispatch", slow_dispatch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        stop = app.query_one("#stop", tui.Button)
        assert stop.disabled
        app.query_one("#prompt", tui.Input).value = "go"
        await pilot.click("#send")
        await pilot.pause()
        assert not stop.disabled
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert stop.disabled


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_login_suspends_the_app_runs_the_login_and_reports(tmp_path, monkeypatch):
    import contextlib
    import shutil
    from whyline import account

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    available = set()
    monkeypatch.setattr(account, "available_agents", lambda root: set(available))
    monkeypatch.setattr(account, "refresh", lambda: available.add("claude") or {})
    app = tui.WhylineConsoleApp(root=tmp_path)
    suspended = []

    @contextlib.contextmanager
    def fake_suspend():
        suspended.append("in")
        yield
        suspended.append("out")

    ran = []
    async with app.run_test() as pilot:
        monkeypatch.setattr(app, "suspend", fake_suspend)
        app._login_fn = lambda argv: ran.append((list(suspended), argv)) or 0
        app.query_one("#prompt", tui.Input).value = "/login claude"
        await pilot.click("#send")
        await pilot.pause()
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
    # the login ran while the app was suspended, not before or after
    assert ran == [(["in"], ["claude", "auth", "login"])]
    assert suspended == ["in", "out"]
    assert any("claude is ready" in line for line in lines)


# --- thinking line, context label, brainstorm form, repo switch ---------------


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_thinking_line_shows_while_a_reply_is_pending(tmp_path, monkeypatch):
    import threading
    from whyline.console.session import SessionEvent

    release = threading.Event()

    def slow(session, text):
        release.wait(timeout=2)
        return SessionEvent(kind="output", text="done")

    monkeypatch.setattr(tui, "dispatch", slow)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#mode-chat")
        thinking = app.query_one("#thinking", tui.Static)
        assert not thinking.display
        app.query_one("#prompt", tui.Input).value = "hi"
        await pilot.click("#send")
        await pilot.pause(0.3)
        assert thinking.display
        assert "claude is thinking" in str(thinking.renderable)
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not thinking.display


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_context_label_shows_agent_model_and_repo(tmp_path, monkeypatch):
    from whyline import account, model

    monkeypatch.setattr(account, "available_agents", lambda root: {"codex"})
    model.set_one(tmp_path, "codex", "gpt-5")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 30)) as pilot:
        context = app.query_one("#context", tui.Static)
        assert "claude · default model" in str(context.renderable)
        assert f"repo: {tmp_path.name}" in str(context.renderable)
        app.query_one("#prompt", tui.Input).value = "/model codex"
        await pilot.click("#send")
        await pilot.pause()
        assert "codex · gpt-5" in str(context.renderable)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_brainstorm_form_validates_then_runs_with_progress(tmp_path, monkeypatch):
    from whyline import account
    from whyline.console import adapters
    from whyline.console.session import SessionEvent

    monkeypatch.setattr(account, "available_agents", lambda root: {"claude", "codex"})
    calls = []

    def fake_run(root, *, progress, **choice):
        calls.append(choice)
        progress("Researching independently: Claude, Codex")
        return SessionEvent(kind="output", text="final synthesis")

    monkeypatch.setattr(adapters, "run_brainstorm", fake_run)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.click("#brainstorm")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, tui.BrainstormScreen)
        # unavailable agents are shown but can't be ticked
        assert form.query_one("#bs-grok", tui.Checkbox).disabled
        assert not form.query_one("#bs-claude", tui.Checkbox).disabled
        await pilot.click("#bs-start")  # no topic yet
        await pilot.pause()
        assert "Enter a topic" in str(form.query_one("#bs-error", tui.Static).renderable)
        # Textual ignores a second press while the first press's 0.2s
        # highlight is still showing; a person never clicks that fast.
        await pilot.pause(0.3)
        form.query_one("#bs-topic", tui.Input).value = "retry policy"
        form.query_one("#bs-passes", tui.Input).value = "2"
        assert form.query_one("#bs-timeout", tui.Select).value == 15
        form.query_one("#bs-timeout", tui.Select).value = 45
        await pilot.click("#bs-start")
        await app.workers.wait_for_complete()
        await pilot.pause()
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
    assert calls == [{
        "topic": "retry policy", "agents": ["claude", "codex"],
        "passes": 2, "final_agent": "claude", "timeout_minutes": 45,
        "attachments": [],
    }]
    assert any("· Researching independently" in line for line in lines)
    assert any("final synthesis" in line for line in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_repo_switch_asks_first_and_clears_the_transcript(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    other = tmp_path / "other"
    for repo in (root, other):
        (repo / ".git").mkdir(parents=True)
    root, other = root.resolve(), other.resolve()
    app = tui.WhylineConsoleApp(root=root)

    async def ask_to_switch(pilot):
        # Enter in the input rather than clicking Send twice: Textual ignores
        # a second press of the same button within its 0.2s highlight, which
        # on a slow CI runner swallowed the second /repo entirely.
        prompt = app.query_one("#prompt", tui.Input)
        prompt.focus()
        prompt.value = f"/repo {other}"
        await pilot.press("enter")
        for _ in range(50):  # until the dialog is actually up
            if isinstance(app.screen, tui.ConfirmScreen):
                return
            await pilot.pause(0.05)
        raise AssertionError("confirmation dialog never appeared")

    async with app.run_test(size=(100, 30)) as pilot:
        await ask_to_switch(pilot)
        await pilot.click("#cancel")
        await pilot.pause()
        assert app.session.root == root
        await ask_to_switch(pilot)
        await pilot.click("#confirm")
        await pilot.pause()
        assert app.session.root == other
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert not any("Staying put" in line for line in lines)  # old text is gone
        assert any("Now working in other" in line for line in lines)
        assert "repo: other" in str(app.query_one("#context", tui.Static).renderable)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_a_focused_brainstorm_checkbox_keeps_its_label_visible(tmp_path, monkeypatch):
    # Textual's own `:focus` style adds a tall border; on a one-line
    # checkbox that border ate the only line, so the focused model turned
    # into what looked like an empty text box.
    from whyline import account

    monkeypatch.setattr(account, "available_agents", lambda root: {"claude", "codex"})
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.click("#brainstorm")
        await pilot.pause()
        box = app.screen.query_one("#bs-claude", tui.Checkbox)
        box.focus()
        await pilot.pause()
        assert box.has_focus
        assert box.content_region.height == 1


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_sending_while_busy_is_refused_so_the_pending_result_is_not_lost(
    tmp_path, monkeypatch
):
    import threading
    from whyline.console.session import SessionEvent

    release = threading.Event()
    calls = []

    def slow(session, text):
        calls.append(text)
        release.wait(timeout=2)
        return SessionEvent(kind="output", text=f"reply to {text}")

    monkeypatch.setattr(tui, "dispatch", slow)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", tui.Input)
        prompt.focus()
        prompt.value = "first"
        await pilot.press("enter")
        await pilot.pause()
        prompt.value = "second"
        await pilot.press("enter")
        await pilot.pause()
        assert prompt.value == "second"  # kept, so it can be sent afterwards
        # slash commands still work while busy
        prompt.value = "/help"
        await pilot.press("enter")
        await pilot.pause()
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
    assert calls == ["first"]
    assert any("Still working" in line for line in lines)
    assert any("Commands:" in line for line in lines)
    assert any("reply to first" in line for line in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_enter_in_the_brainstorm_topic_starts_it_instead_of_crashing(tmp_path, monkeypatch):
    # Regression: Enter in the form's topic box bubbled Input.Submitted up
    # to the app, whose handler looked for #prompt on the (modal) active
    # screen and crashed the console with NoMatches.
    from whyline import account
    from whyline.console import adapters
    from whyline.console.session import SessionEvent

    monkeypatch.setattr(account, "available_agents", lambda root: {"claude"})
    calls = []
    monkeypatch.setattr(
        adapters, "run_brainstorm",
        lambda root, *, progress, **choice: calls.append(choice)
        or SessionEvent(kind="output", text="done"),
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.click("#brainstorm")
        await pilot.pause()
        await pilot.press(*"retry policy", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not isinstance(app.screen, tui.BrainstormScreen)
    assert calls and calls[0]["topic"] == "retry policy"


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_progress_and_spinner_keep_working_while_a_dialog_is_open(tmp_path, monkeypatch):
    # Anything the app renders while a dialog is on top (a brainstorm
    # progress line, the spinner tick) must reach the main screen's
    # widgets, not search the dialog for them.
    from whyline.console.session import SessionEvent

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        app._set_busy(True, "working")
        app.push_screen(tui.ConfirmScreen("Sure?", "Yes"))
        await pilot.pause(0.3)  # several spinner ticks with the dialog up
        app.render_event(SessionEvent(kind="output", text="progress while dialog open"))
        app._set_busy(False)
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
    assert any(e.text == "progress while dialog open" for e in app.session.transcript)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_unknown_slash_commands_never_reach_the_agent(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(tui, "dispatch", lambda session, text: sent.append(text))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#mode-chat")
        prompt = app.query_one("#prompt", tui.Input)
        prompt.focus()
        for text in ("/agents", "/default codex"):
            prompt.value = text
            await pilot.press("enter")
            await pilot.pause()
        await app.workers.wait_for_complete()
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
    assert sent == []
    assert any("Unknown command /agents" in line for line in lines)
    assert any("/model codex" in line for line in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_console_in_the_home_repo_says_so_at_start(tmp_path, monkeypatch):
    from pathlib import Path

    project = tmp_path / "TradingPlatform"
    project.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(project)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
    text = " ".join(lines)
    assert "home directory" in text and "TradingPlatform" in text



@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_copy_without_a_system_clipboard_is_honest_about_it(tmp_path, monkeypatch):
    from whyline.console.session import SessionEvent

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.record(SessionEvent(kind="output", text="x"))
        sent = []
        monkeypatch.setattr(tui, "_system_copy", lambda text: False)
        monkeypatch.setattr(app, "copy_to_clipboard", lambda text: sent.append(text))
        await pilot.click("#copy")
        await pilot.pause()
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
    assert sent  # the terminal escape code is still tried
    assert any("may not" in line and "OSC 52" in line for line in lines)
    assert not any("Transcript copied to clipboard." in line for line in lines)


def test_system_copy_uses_the_platform_command(monkeypatch):
    calls = []

    class Done:
        returncode = 0

    monkeypatch.setattr(tui.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "pbcopy" else None)
    monkeypatch.setattr(tui.subprocess, "run", lambda argv, **kw: calls.append((argv, kw["input"])) or Done())
    assert tui._system_copy("hello") is True
    assert calls == [(["pbcopy"], "hello")]
    monkeypatch.setattr(tui.shutil, "which", lambda name: None)
    assert tui._system_copy("hello") is False
