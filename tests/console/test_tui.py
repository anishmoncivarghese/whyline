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
            "send", "model", "mode-chat", "mode-relay", "mode-agents",
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
        await pilot.pause()  # shown buttons need a layout pass before a click
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
        assert app.session.mode == "chat"
        assert app.sub_title == "mode: chat"
        transcript = app.query_one("#transcript", tui.RichLog)
        assert any("Chat talks" in str(line) for line in transcript.lines)


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
        assert "Message claude" in prompt.placeholder
        await pilot.click("#mode-relay")
        await pilot.pause()
        assert "relay" in prompt.placeholder.lower()
        await pilot.click("#mode-chat")
        await pilot.pause()
        assert "Message claude" in prompt.placeholder


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_active_mode_button_is_highlighted(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        assert app.query_one("#mode-chat", tui.Button).variant == "primary"
        assert app.query_one("#mode-relay", tui.Button).variant == "default"
        assert app.query_one("#mode-agents", tui.Button).variant == "default"
        await pilot.click("#mode-relay")
        await pilot.pause()
        assert app.query_one("#mode-relay", tui.Button).variant == "primary"
        assert app.query_one("#mode-chat", tui.Button).variant == "default"
        assert app.sub_title == "mode: relay"


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
        # The context bar replaced the old #context text. claude has no
        # saved model yet, and this test leaves it unavailable.
        assert app.query_one("#cb-agent", tui.Select).value == "!claude"
        assert app.query_one("#cb-model", tui.Input).value == ""
        assert tmp_path.name in app.query_one("#cb-repo", tui.Input).value
        app.query_one("#prompt", tui.Input).value = "/model codex"
        await pilot.click("#send")
        await pilot.pause()
        assert app.query_one("#cb-agent", tui.Select).value == "codex"
        assert app.query_one("#cb-model", tui.Input).value == "gpt-5"


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
        assert "other" in app.query_one("#cb-repo", tui.Input).value


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


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_thinking_line_shows_brackets_literally(tmp_path):
    # Brainstorm progress reads "[1/3] Codex starting pass-zero"; as markup
    # that was a style tag and crashed the console with MarkupError.
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        label = "brainstorming: [1/3] Codex starting pass-zero (0s) [bold]x[/]"
        app._set_busy(True, label)
        await pilot.pause()
        app._tick()
        await pilot.pause()
        shown = str(app.query_one("#thinking", tui.Static).renderable)
        assert "[1/3] Codex starting pass-zero" in shown
        assert "[bold]x[/]" in shown


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_bottom_bar_run_opens_plan_when_no_plan_exists(tmp_path, monkeypatch):
    from whyline.console import relay_ops
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: [])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()
        await pilot.click("#relay-run")
        await pilot.pause()
        from whyline.console.relay_screens import RelayPlanScreen
        assert isinstance(app.screen, RelayPlanScreen)


def _auto_request(**overrides):
    from whyline.console import plan_job

    fields = dict(
        name="test",
        topic="t",
        replace=False,
        continue_paths=False,
        agents=("codex",),
        passes=1,
        final_agent="codex",
        timeout_minutes=15,
        attachments=(),
        drafter="claude",
        reviewer="codex",
        implementer="grok",
        tester="claude",
        reviewer_role="codex",
        release="human",
        chain=("codex",),
    )
    fields.update(overrides)
    return plan_job.AutoRunRequest(**fields)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_fake_end_to_end_dismiss_calls_run_auto_once(tmp_path, monkeypatch):
    from whyline.console import plan_job
    called = []

    def fake_run_auto(root, request, fingerprint, progress=None, cancel_event=None, launcher=None, **kwargs):
        called.append((root, request, fingerprint))
        if progress:
            progress("auto step 1")
        return {"phase": "relay"}

    monkeypatch.setattr(plan_job, "run_auto", fake_run_auto)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        req = _auto_request()
        app._plan_chosen((req, "fp123"))
        for _ in range(20):
            await pilot.pause(0.05)
            if called:
                break
        assert len(called) == 1
        assert called[0][0] == tmp_path
        assert called[0][1] == req
        assert called[0][2] == "fp123"
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("auto step 1" in line for line in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_stop_sets_auto_cancel_event(tmp_path, monkeypatch):
    import threading
    from whyline.console import plan_job
    started = threading.Event()
    cancelled = threading.Event()

    def fake_run_auto(root, request, fingerprint, progress=None, cancel_event=None, launcher=None, **kwargs):
        started.set()
        if cancel_event:
            cancel_event.wait(timeout=5)
            if cancel_event.is_set():
                cancelled.set()
        return {"phase": "stopped"}

    monkeypatch.setattr(plan_job, "run_auto", fake_run_auto)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        req = _auto_request()
        app._plan_chosen((req, "fp123"))
        for _ in range(20):
            await pilot.pause(0.05)
            if started.is_set():
                break
        assert started.is_set()
        assert not app.query_one("#stop", tui.Button).disabled
        await pilot.click("#stop")
        for _ in range(20):
            await pilot.pause(0.05)
            if cancelled.is_set():
                break
        assert cancelled.is_set()


def _init_test_repo(path):
    import subprocess
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=path, check=True, capture_output=True)
    (path / ".gitkeep").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_resolve_closes_setup_and_prints_problem_with_recommended_option_first(tmp_path, monkeypatch):
    from textual.containers import Horizontal
    from whyline.console import relay_screens
    _init_test_repo(tmp_path)
    (tmp_path / ".whyline").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".whyline" / "decisions.md").write_text("- decision 1\n", encoding="utf-8")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        app._open_relay_setup()
        await pilot.pause()
        assert isinstance(app.screen, relay_screens.RelaySetupScreen)

        app.screen.dismiss(("resolve", ["FAIL  working tree has uncommitted changes"]))
        await pilot.pause()
        assert not isinstance(app.screen, relay_screens.RelaySetupScreen)

        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("Resolve: 1 problem(s)" in l for l in lines)
        assert any("Uncommitted paths are exactly .whyline/decisions.md" in l for l in lines)
        assert any("1. Commit decision log (recommended)" in l for l in lines)

        actions = app.query_one("#resolve-actions", Horizontal)
        assert actions.display is True
        buttons = list(actions.query(tui.Button))
        assert len(buttons) >= 1
        assert buttons[0].id == "resolve-commit-log"
        assert buttons[0].variant == "success"


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_clicking_recommended_option_of_dirty_log_commits_and_prints_setup_hint(tmp_path, monkeypatch):
    import subprocess
    _init_test_repo(tmp_path)
    (tmp_path / ".whyline").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".whyline" / "decisions.md").write_text("- decision 1\n", encoding="utf-8")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="setup", fail_lines=["FAIL  working tree has uncommitted changes"])
        await pilot.pause()

        btn = app.query_one("#resolve-commit-log", tui.Button)
        assert btn.variant == "success"
        await pilot.click("#resolve-commit-log")

        for _ in range(30):
            await pilot.pause(0.05)
            if not getattr(app, "_resolve_running", False):
                break

        status = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True).stdout
        assert status.strip() == ""

        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("Committed decision log" in l for l in lines)
        assert any("Resolved. Open Set up again and press Check." in l for l in lines)

        setup_btn = app.query_one("#resolve-setup", tui.Button)
        assert setup_btn.display is True


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_confirm_option_shows_confirm_screen_and_cancel_there_changes_nothing(tmp_path, monkeypatch):
    import json
    from textual.containers import Horizontal
    from whyline.console import relay_ops
    _init_test_repo(tmp_path)
    (tmp_path / "extra.txt").write_text("extra", encoding="utf-8")
    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({
        "plan": "plan.md", "branch": "main", "task_id": "TASK-1", "round": 1, "base_commit": "abc",
        "paused_reason": "paused", "log_path": "round.log"
    }), encoding="utf-8")
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="resume")
        await pilot.pause()

        await pilot.click("#resolve-stash")
        await pilot.pause()

        assert isinstance(app.screen, tui.ConfirmScreen)
        assert "git stash" in app.screen._message

        await pilot.click("#cancel")
        await pilot.pause()

        assert not isinstance(app.screen, tui.ConfirmScreen)
        assert (tmp_path / "extra.txt").exists()
        assert app.query_one("#resolve-actions", Horizontal).display is True


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_typing_2_picks_second_option(tmp_path, monkeypatch):
    import json
    from whyline.console import relay_ops
    _init_test_repo(tmp_path)
    (tmp_path / "extra.txt").write_text("extra", encoding="utf-8")
    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({
        "plan": "plan.md", "branch": "main", "task_id": "TASK-1", "round": 1, "base_commit": "abc",
        "paused_reason": "paused", "log_path": "round.log"
    }), encoding="utf-8")
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="resume")
        await pilot.pause()

        app._send_with("2")
        await pilot.pause()

        assert isinstance(app.screen, tui.ConfirmScreen)
        assert "git stash" in app.screen._message


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_resume_that_fails_preflight_enables_relay_resolve(tmp_path, monkeypatch):
    _init_test_repo(tmp_path)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()

        assert app.query_one("#relay-resolve", tui.Button).display is False

        app._relay_finished(1, "FAIL  working tree has uncommitted changes\n")
        await pilot.pause()

        btn = app.query_one("#relay-resolve", tui.Button)
        assert btn.display is True
        assert btn.disabled is False

        app._relay_finished(0, "Relay finished.\n")
        await pilot.pause()

        assert app.query_one("#relay-resolve", tui.Button).disabled is True


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_choosing_resume_keep_calls_launcher_once(tmp_path, monkeypatch):
    import json
    from textual.containers import Horizontal
    from whyline.console import relay_ops
    _init_test_repo(tmp_path)
    (tmp_path / "extra.txt").write_text("extra", encoding="utf-8")
    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({
        "plan": "plan.md", "branch": "main", "task_id": "TASK-1", "round": 1, "base_commit": "abc",
        "paused_reason": "paused", "log_path": "round.log"
    }), encoding="utf-8")
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)

    app = tui.WhylineConsoleApp(root=tmp_path)
    launched: list[list[str]] = []
    monkeypatch.setattr(app, "_launch_relay", lambda args: launched.append(list(args)))

    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="resume")
        await pilot.pause()

        await pilot.click("#resolve-resume-keep")
        for _ in range(30):
            await pilot.pause(0.05)
            if launched:
                break

        assert launched == [["resume", "--allow-dirty"]]
        assert app.query_one("#resolve-actions", Horizontal).display is False


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_two_problems_are_handled_one_after_the_other(tmp_path, monkeypatch):
    from whyline_relay import failover
    from whyline import account
    _init_test_repo(tmp_path)
    (tmp_path / ".whyline").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".whyline" / "decisions.md").write_text("- decision 1\n", encoding="utf-8")
    failover.write_override(
        tmp_path,
        "implementer",
        failover.ActiveOverride("claude", "codex", "rate-limit", "2026-10-14", []),
    )
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"codex": {"available": True}},
    )

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="setup", fail_lines=["FAIL  working tree has uncommitted changes"])
        await pilot.pause()

        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("Resolve: 2 problem(s)" in l for l in lines)

        # First problem is sticky-switch
        assert app.query_one("#resolve-reset-role", tui.Button).display is True
        await pilot.click("#resolve-reset-role")
        for _ in range(30):
            await pilot.pause(0.05)
            if not getattr(app, "_resolve_running", False):
                break

        # Problem 1 is gone, now Problem 2 (dirty-log) is displayed
        lines2 = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("Reset role implementer" in l or "Reset implementer" in l for l in lines2)
        assert any("Uncommitted paths are exactly .whyline/decisions.md" in l for l in lines2)

        # Button for Problem 2 is commit-log
        assert app.query_one("#resolve-commit-log", tui.Button).display is True
        await pilot.click("#resolve-commit-log")
        for _ in range(30):
            await pilot.pause(0.05)
            if not getattr(app, "_resolve_running", False):
                break

        # Both problems resolved!
        lines3 = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("Resolved. Open Set up again and press Check." in l for l in lines3)
        assert app.query_one("#resolve-setup", tui.Button).display is True


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_resolve_cancel_hides_row_and_prints_message(tmp_path, monkeypatch):
    from textual.containers import Horizontal
    _init_test_repo(tmp_path)
    (tmp_path / ".whyline").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".whyline" / "decisions.md").write_text("- decision 1\n", encoding="utf-8")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="setup", fail_lines=["FAIL  working tree has uncommitted changes"])
        await pilot.pause()

        assert app.query_one("#resolve-actions", Horizontal).display is True
        await pilot.click("#resolve-cancel")
        await pilot.pause()

        assert app.query_one("#resolve-actions", Horizontal).display is False
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("Resolve cancelled; nothing else was changed." in l for l in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_auto_launched_relay_pause_automatically_recovers_without_resolve_click(tmp_path, monkeypatch):
    import json
    from whyline.console import adapters, plan_job, recovery, relay_ops

    (tmp_path / "plan.md").write_text("# Plan\n- [ ] TASK-1: Do task\n", encoding="utf-8")
    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "TASK-1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "codex exited without handing off",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)

    launched: list[list[str]] = []

    def fake_run_auto(root, request, fingerprint, progress=None, cancel_event=None, launcher=None, **kwargs):
        if launcher:
            launcher(["start"])
        return {"phase": "relay"}

    monkeypatch.setattr(plan_job, "run_auto", fake_run_auto)

    recovery_calls = []

    def fake_recover_pause(root, session=None, progress=None, launcher=None, **kwargs):
        recovery_calls.append(kwargs)
        if progress:
            progress("auto · recover no-handoff · codex")
        if launcher:
            launcher(["resume"])
        return recovery.RecoveryResult("resolved", [])

    monkeypatch.setattr(adapters, "recover_pause", fake_recover_pause)

    app = tui.WhylineConsoleApp(root=tmp_path)

    def fake_launch_relay(args, **kwargs):
        launched.append(list(args))
        app._auto_relay = kwargs.get("auto", True)

    monkeypatch.setattr(app, "_launch_relay", fake_launch_relay)

    async with app.run_test() as pilot:
        req = _auto_request()
        # 1. Start Auto run which calls launcher(["start"])
        app._plan_chosen((req, "fp123"))
        for _ in range(20):
            await pilot.pause(0.05)
            if launched:
                break

        assert launched == [["start"]]
        assert getattr(app, "_auto_relay", False) is True

        # 2. Relay finishes with pause
        app._relay_finished(2, "Paused: codex exited without handing off")

        # 3. Recovery must execute automatically without clicking Resolve
        for _ in range(20):
            await pilot.pause(0.05)
            if len(launched) > 1:
                break

        assert len(recovery_calls) == 1
        assert launched == [["start"], ["resume"]]
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("auto · recover no-handoff · codex" in line for line in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_auto_launched_dirty_tree_fail_automatically_recovers_without_resolve_click(tmp_path, monkeypatch):
    import json
    from whyline.console import adapters, plan_job, recovery, relay_ops

    (tmp_path / "plan.md").write_text("# Plan\n- [ ] TASK-1: Do task\n", encoding="utf-8")
    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "TASK-1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "dirty",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)

    launched: list[list[str]] = []

    def fake_run_auto(root, request, fingerprint, progress=None, cancel_event=None, launcher=None, **kwargs):
        if launcher:
            launcher(["start"])
        return {"phase": "relay"}

    monkeypatch.setattr(plan_job, "run_auto", fake_run_auto)

    recovery_calls = []

    def fake_recover_pause(root, session=None, progress=None, launcher=None, **kwargs):
        recovery_calls.append(kwargs)
        if progress:
            progress("auto · recover decision-log")
        if launcher:
            launcher(["resume"])
        return recovery.RecoveryResult("resolved", [])

    monkeypatch.setattr(adapters, "recover_pause", fake_recover_pause)

    app = tui.WhylineConsoleApp(root=tmp_path)

    def fake_launch_relay(args, **kwargs):
        launched.append(list(args))
        app._auto_relay = kwargs.get("auto", True)

    monkeypatch.setattr(app, "_launch_relay", fake_launch_relay)

    async with app.run_test() as pilot:
        req = _auto_request()
        # 1. Start Auto run
        app._plan_chosen((req, "fp123"))
        for _ in range(20):
            await pilot.pause(0.05)
            if launched:
                break

        assert launched == [["start"]]
        assert getattr(app, "_auto_relay", False) is True

        # 2. Relay exits with dirty-tree FAIL
        app._relay_finished(1, "FAIL  working tree has uncommitted changes")

        # 3. Recovery must execute automatically without clicking Resolve
        for _ in range(20):
            await pilot.pause(0.05)
            if len(launched) > 1:
                break

        assert len(recovery_calls) == 1
        assert launched == [["start"], ["resume"]]
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("auto · recover decision-log" in line for line in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_auto_launched_unrelated_nonzero_fail_exit_does_not_call_recovery(tmp_path, monkeypatch):
    from whyline.console import adapters, plan_job, recovery, relay_ops

    (tmp_path / "plan.md").write_text("# Plan\n- [ ] TASK-1: Do task\n", encoding="utf-8")
    decisions = tmp_path / ".whyline" / "decisions.md"
    decisions.parent.mkdir(parents=True, exist_ok=True)
    decisions.write_text("# Decisions\n- [2026-10-14] Some decision\n", encoding="utf-8")
    (tmp_path / "other.txt").write_text("uncommitted file\n", encoding="utf-8")

    monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)

    launched: list[list[str]] = []

    def fake_run_auto(root, request, fingerprint, progress=None, cancel_event=None, launcher=None, **kwargs):
        if launcher:
            launcher(["start"])
        return {"phase": "relay"}

    monkeypatch.setattr(plan_job, "run_auto", fake_run_auto)

    recovery_calls = []

    def fake_recover_pause(root, session=None, progress=None, launcher=None, **kwargs):
        recovery_calls.append(kwargs)
        if launcher:
            launcher(["resume"])
        return recovery.RecoveryResult("resolved", [])

    monkeypatch.setattr(adapters, "recover_pause", fake_recover_pause)

    app = tui.WhylineConsoleApp(root=tmp_path)

    def fake_launch_relay(args, **kwargs):
        launched.append(list(args))
        app._auto_relay = kwargs.get("auto", True)

    monkeypatch.setattr(app, "_launch_relay", fake_launch_relay)

    async with app.run_test() as pilot:
        req = _auto_request()
        # 1. Start Auto run
        app._plan_chosen((req, "fp123"))
        for _ in range(20):
            await pilot.pause(0.05)
            if launched:
                break

        assert launched == [["start"]]
        assert getattr(app, "_auto_relay", False) is True

        # 2. Relay exits with unrelated FAIL / nonzero exit code
        app._relay_finished(1, "FAIL  no unchecked tasks in plan.md")

        for _ in range(10):
            await pilot.pause(0.05)

        # 3. Recovery must NOT be called, no resume launched, and auto run stopped
        assert len(recovery_calls) == 0
        assert launched == [["start"]]
        assert getattr(app, "_auto_relay", False) is False
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("The relay stopped with exit code 1" in line for line in lines)
        assert not any("auto · recover" in line for line in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_visit_cap_pause_shows_retry_stage_and_pressing_launches_resume_retry_stage(tmp_path, monkeypatch):
    import json
    from whyline.console import relay_ops

    (tmp_path / "plan.md").write_text("# Plan\n- [ ] TASK-1: Do task\n", encoding="utf-8")
    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "TASK-1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "TASK-1 hit stage 'review''s 3-visit cap without reaching \"@complete\"",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)

    launched: list[list[str]] = []

    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_launch_relay", lambda args, **kwargs: launched.append(list(args)))

    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()

        btn = app.query_one("#relay-retry-stage", tui.Button)
        assert btn.display is True
        assert btn.disabled is False

        await pilot.click("#relay-retry-stage")
        for _ in range(20):
            await pilot.pause(0.05)
            if launched:
                break

        assert launched == [["resume", "--retry-stage"]]


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_other_pauses_do_not_show_retry_stage(tmp_path, monkeypatch):
    import json
    from whyline.console import relay_ops

    (tmp_path / "plan.md").write_text("# Plan\n- [ ] TASK-1: Do task\n", encoding="utf-8")
    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "TASK-1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "codex exited without handing off",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)

    app = tui.WhylineConsoleApp(root=tmp_path)

    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()

        # 1. no-handoff pause does not show Retry stage
        assert app.query_one("#relay-retry-stage", tui.Button).display is False

        # 2. sandbox pause does not show Retry stage
        state_file.write_text(
            json.dumps({
                "plan": "plan.md",
                "branch": "main",
                "task_id": "TASK-1",
                "round": 1,
                "base_commit": "abc",
                "paused_reason": "codex could not run a required command: pytest: permission denied",
                "log_path": "round.log",
            }),
            encoding="utf-8",
        )
        app._sync_relay_buttons()
        await pilot.pause()
        assert app.query_one("#relay-retry-stage", tui.Button).display is False

        # 3. blocked pause does not show Retry stage
        state_file.write_text(
            json.dumps({
                "plan": "plan.md",
                "branch": "main",
                "task_id": "TASK-1",
                "round": 1,
                "base_commit": "abc",
                "paused_reason": "codex reported blocked: permission denied",
                "log_path": "round.log",
            }),
            encoding="utf-8",
        )
        app._sync_relay_buttons()
        await pilot.pause()
        assert app.query_one("#relay-retry-stage", tui.Button).display is False

        # 4. auth pause does not show Retry stage
        state_file.write_text(
            json.dumps({
                "plan": "plan.md",
                "branch": "main",
                "task_id": "TASK-1",
                "round": 1,
                "base_commit": "abc",
                "paused_reason": "codex is no longer logged in",
                "log_path": "round.log",
            }),
            encoding="utf-8",
        )
        app._sync_relay_buttons()
        await pilot.pause()
        assert app.query_one("#relay-retry-stage", tui.Button).display is False


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_sandbox_pause_in_tui_shows_command_and_changes_no_file(tmp_path, monkeypatch):
    import json
    from whyline.console import relay_ops

    (tmp_path / "plan.md").write_text("# Plan\n- [ ] TASK-1: Do task\n", encoding="utf-8")
    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "TASK-1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "codex could not run a required command: uv run pytest -q tests/test_foo.py: permission denied",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )
    config_file = tmp_path / ".whyline" / "relay" / "config.toml"
    config_file.write_text('[agents.codex]\ncommand = ["codex", "exec"]\n', encoding="utf-8")
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)

    files_before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    app = tui.WhylineConsoleApp(root=tmp_path)

    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._relay_finished(
            2,
            "Paused: codex could not run a required command: uv run pytest -q tests/test_foo.py: permission denied",
        )
        await pilot.pause()

        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("[sandbox]" in line for line in lines)
        assert any("uv run pytest -q tests/test_foo.py" in line for line in lines)
        assert any("Command uv run pytest -q tests/test_foo.py" in line for line in lines)
        assert any("Config change:" in line for line in lines)

        files_after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        assert files_after == files_before


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_auto_never_presses_retry_stage_on_visit_cap(tmp_path, monkeypatch):
    import json
    from whyline.console import plan_job, recovery, relay_ops

    (tmp_path / "plan.md").write_text("# Plan\n- [ ] TASK-1: Do task\n", encoding="utf-8")
    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "TASK-1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "TASK-1 hit stage 'review''s 3-visit cap without reaching \"@complete\"",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)

    launched: list[list[str]] = []

    def fake_run_auto(root, request, fingerprint, progress=None, cancel_event=None, launcher=None, **kwargs):
        if launcher:
            launcher(["start"])
        return {"phase": "relay"}

    monkeypatch.setattr(plan_job, "run_auto", fake_run_auto)

    app = tui.WhylineConsoleApp(root=tmp_path)

    def fake_launch_relay(args, **kwargs):
        launched.append(list(args))
        app._auto_relay = kwargs.get("auto", True)

    monkeypatch.setattr(app, "_launch_relay", fake_launch_relay)

    async with app.run_test() as pilot:
        req = _auto_request()
        app._plan_chosen((req, "fp123"))
        for _ in range(20):
            await pilot.pause(0.05)
            if launched:
                break

        assert launched == [["start"]]
        assert getattr(app, "_auto_relay", False) is True

        # Relay pauses on visit-cap
        app._relay_finished(
            2,
            "Paused: TASK-1 hit stage 'review''s 3-visit cap without reaching \"@complete\"",
        )

        for _ in range(10):
            await pilot.pause(0.05)

        # Auto must NOT have launched resume --retry-stage
        assert launched == [["start"]]
        assert getattr(app, "_auto_relay", False) is False


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_ask_agent_recommendation_of_listed_id_is_offered_and_applies_only_on_click(tmp_path, monkeypatch):
    _init_test_repo(tmp_path)

    def fake_runner(command, prompt, **kwargs):
        return (
            "EXPLANATION: Retry the failed stage.\n"
            "RECOMMEND: retry-stage\n"
        )

    launched: list[list[str]] = []
    app = tui.WhylineConsoleApp(root=tmp_path, runner=fake_runner)
    monkeypatch.setattr(app, "_launch_relay", lambda args: launched.append(list(args)))

    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="resume", fail_lines=["FAIL unclassified preflight check"])
        await pilot.pause()

        btn_ask = app.query_one("#resolve-ask-agent", tui.Button)
        assert btn_ask.display is True
        assert btn_ask.variant == "success"

        await pilot.click("#resolve-ask-agent")
        for _ in range(30):
            await pilot.pause(0.05)
            if app.query("#resolve-retry-stage"):
                break

        btn_retry = app.query_one("#resolve-retry-stage", tui.Button)
        assert btn_retry.display is True
        assert btn_retry.variant == "success"
        assert app.query_one("#resolve-show", tui.Button).display is True
        assert app.query_one("#resolve-cancel", tui.Button).display is True

        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("Retry the failed stage." in l for l in lines)

        # Not applied yet!
        assert launched == []

        await pilot.click("#resolve-retry-stage")
        for _ in range(30):
            await pilot.pause(0.05)
            if launched:
                break

        # Applied on click!
        assert launched == [["resume", "--retry-stage"]]


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_ask_agent_unlisted_id_ignored_and_reported(tmp_path, monkeypatch):
    _init_test_repo(tmp_path)

    def fake_runner(command, prompt, **kwargs):
        return (
            "EXPLANATION: Run unknown custom procedure.\n"
            "RECOMMEND: custom-reboot\n"
        )

    app = tui.WhylineConsoleApp(root=tmp_path, runner=fake_runner)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="resume", fail_lines=["FAIL unknown weird error"])
        await pilot.pause()

        await pilot.click("#resolve-ask-agent")
        for _ in range(30):
            await pilot.pause(0.05)
            if not getattr(app, "_resolve_running", False):
                break

        assert not app.query("#resolve-custom-reboot")
        assert app.query_one("#resolve-show", tui.Button).display is True
        assert app.query_one("#resolve-cancel", tui.Button).display is True

        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("custom-reboot" in l for l in lines)
        assert any("Check" in l and "hand" in l for l in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_ask_agent_turn_that_edits_file_discarded_and_names_file(tmp_path, monkeypatch):
    _init_test_repo(tmp_path)

    def fake_runner(command, prompt, **kwargs):
        (tmp_path / "sneaky_mutation.txt").write_text("evil\n", encoding="utf-8")
        return (
            "EXPLANATION: Recommendation should be discarded.\n"
            "RECOMMEND: stash\n"
        )

    app = tui.WhylineConsoleApp(root=tmp_path, runner=fake_runner)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="resume", fail_lines=["FAIL mystery failure"])
        await pilot.pause()

        await pilot.click("#resolve-ask-agent")
        for _ in range(30):
            await pilot.pause(0.05)
            if not getattr(app, "_resolve_running", False):
                break

        assert not app.query("#resolve-stash")
        assert app.query_one("#resolve-show", tui.Button).display is True
        assert app.query_one("#resolve-cancel", tui.Button).display is True

        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("sneaky_mutation.txt" in l for l in lines)
        assert any("discarded" in l.lower() for l in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_ask_agent_failing_selected_agent_falls_through_to_first_backup(tmp_path, monkeypatch):
    import subprocess
    from whyline_relay import agents as relay_agents

    _init_test_repo(tmp_path)
    relay_cfg = tmp_path / ".whyline" / "relay" / "config.toml"
    relay_cfg.parent.mkdir(parents=True, exist_ok=True)
    relay_cfg.write_text(
        'plan = "plan.md"\n[backup]\nchain = ["claude"]\n[roles]\nimplementer = "grok"\nreviewer = "claude"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "config"], cwd=tmp_path, check=True, capture_output=True)

    called: list[str] = []

    def fake_runner(command, prompt, **kwargs):
        agent_name = kwargs.get("agent_name") or command[0]
        called.append(agent_name)
        if agent_name == "grok":
            raise relay_agents.AgentMissing("grok missing")
        if agent_name == "claude":
            return (
                "EXPLANATION: Claude resolved the issue.\n"
                "RECOMMEND: wait\n"
            )
        raise RuntimeError(f"unexpected agent {agent_name}")

    app = tui.WhylineConsoleApp(root=tmp_path, runner=fake_runner)
    app.session.agent = "grok"
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="resume", fail_lines=["FAIL unknown problem"])
        await pilot.pause()

        await pilot.click("#resolve-ask-agent")
        for _ in range(30):
            await pilot.pause(0.05)
            if app.query("#resolve-wait"):
                break

        assert called == ["grok", "claude"]
        assert app.query_one("#resolve-wait", tui.Button).display is True
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("Claude resolved the issue." in l for l in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_ask_agent_no_option_applied_without_click(tmp_path, monkeypatch):
    _init_test_repo(tmp_path)

    def fake_runner(command, prompt, **kwargs):
        return (
            "EXPLANATION: Keep the changes and resume.\n"
            "RECOMMEND: resume-keep\n"
        )

    launched: list[list[str]] = []
    app = tui.WhylineConsoleApp(root=tmp_path, runner=fake_runner)
    monkeypatch.setattr(app, "_launch_relay", lambda args: launched.append(list(args)))

    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="resume", fail_lines=["FAIL unexplained error"])
        await pilot.pause()

        await pilot.click("#resolve-ask-agent")
        for _ in range(30):
            await pilot.pause(0.05)
            if app.query("#resolve-resume-keep"):
                break

        assert app.query_one("#resolve-resume-keep", tui.Button).display is True
        assert launched == []


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_ask_agent_opt_prefixed_recommendation_in_tui(tmp_path, monkeypatch):
    _init_test_repo(tmp_path)

    def fake_runner(command, prompt, **kwargs):
        return (
            "EXPLANATION: Stash uncommitted changes.\n"
            "RECOMMEND: opt-stash\n"
        )

    app = tui.WhylineConsoleApp(root=tmp_path, runner=fake_runner)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="resume", fail_lines=["FAIL unexplained error"])
        await pilot.pause()

        await pilot.click("#resolve-ask-agent")
        for _ in range(30):
            await pilot.pause(0.05)
            if not getattr(app, "_resolve_running", False):
                break

        assert not app.query("#resolve-opt-stash")
        assert not app.query("#resolve-stash")
        assert app.query_one("#resolve-show", tui.Button).display is True
        assert app.query_one("#resolve-cancel", tui.Button).display is True

        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("opt-stash" in l and "ignored" in l for l in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_ask_agent_synthesized_role_option_and_apply_in_tui(tmp_path, monkeypatch):
    import subprocess
    from whyline_relay import config as relay_config

    _init_test_repo(tmp_path)
    relay_cfg = tmp_path / ".whyline" / "relay" / "config.toml"
    relay_cfg.parent.mkdir(parents=True, exist_ok=True)
    relay_cfg.write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "codex"\nreviewer = "claude"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "cfg"], cwd=tmp_path, check=True, capture_output=True)

    def fake_runner(command, prompt, **kwargs):
        return (
            "EXPLANATION: Switch implementer to claude.\n"
            "RECOMMEND: use-claude\n"
        )

    monkeypatch.setattr(
        "whyline.account.agent_status",
        lambda root: {"claude": {"available": True}, "codex": {"available": True}},
    )

    launched: list[list[str]] = []
    app = tui.WhylineConsoleApp(root=tmp_path, runner=fake_runner)
    monkeypatch.setattr(app, "_launch_relay", lambda args: launched.append(list(args)))

    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="resume", fail_lines=["FAIL unknown failure"])
        await pilot.pause()

        await pilot.click("#resolve-ask-agent")
        for _ in range(80):
            await pilot.pause(0.05)
            if app.query("#resolve-use-claude"):
                break

        btn_use = app.query_one("#resolve-use-claude", tui.Button)
        assert btn_use.display is True
        assert btn_use.label.plain == "Use claude"
        assert launched == []

        await pilot.click("#resolve-use-claude")
        for _ in range(80):
            await pilot.pause(0.05)
            if launched:
                break

        assert launched == [["resume"]]
        cfg = relay_config.load(tmp_path)
        assert cfg.roles.implementer == "claude"








