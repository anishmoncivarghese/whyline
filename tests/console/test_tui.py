import pytest
from whyline.console import tui


def _clickable(app, selector: str) -> bool:
    """The Resolve row swaps its buttons in place: a new button is in the DOM
    before it has a size, and the ask-agent worker may still be finishing.
    `pilot.click` on it then lands on nothing (seen on windows-latest), so
    wait until it is laid out, enabled, and no Resolve step is running."""
    found = app.query(selector)
    if not found:
        return False
    button = found.first()
    return (
        button.is_mounted
        and button.region.area > 0
        and not button.disabled
        and not getattr(app, "_resolve_running", False)
    )


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

    def fake_run(root, *, progress, cancel_event=None, **choice):
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
        "timeout_unlimited": False,
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
async def test_bottom_bar_run_opens_plan_when_no_plan_exists(tmp_path, monkeypatch, installed_agents):
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
async def test_resolve_closes_setup_and_prints_problem_with_recommended_option_first(tmp_path, monkeypatch, installed_agents):
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

        for _ in range(300):  # 15 s ceiling; Windows git is slow
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
        for _ in range(300):  # 15 s ceiling; Windows git is slow
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
        for _ in range(300):  # 15 s ceiling; Windows git is slow
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
        for _ in range(300):  # 15 s ceiling; Windows git is slow
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
        for _ in range(300):  # 15 s ceiling; Windows git is slow
            await pilot.pause(0.05)
            if _clickable(app, "#resolve-retry-stage"):
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
        for _ in range(300):  # 15 s ceiling; Windows git is slow
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
        for _ in range(300):  # 15 s ceiling; Windows git is slow
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
        for _ in range(300):  # 15 s ceiling; Windows git is slow
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
        for _ in range(300):  # 15 s ceiling; Windows git is slow
            await pilot.pause(0.05)
            if _clickable(app, "#resolve-wait"):
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
        for _ in range(300):  # 15 s ceiling; Windows git is slow
            await pilot.pause(0.05)
            if _clickable(app, "#resolve-resume-keep"):
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
        for _ in range(300):  # 15 s ceiling; Windows git is slow
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
async def test_ask_agent_synthesized_role_option_and_apply_in_tui(tmp_path, monkeypatch, installed_agents):
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
        for _ in range(300):  # 15 s ceiling; Windows CI is slow
            await pilot.pause(0.05)
            if _clickable(app, "#resolve-use-claude"):
                break

        btn_use = app.query_one("#resolve-use-claude", tui.Button)
        assert btn_use.display is True
        assert btn_use.label.plain == "Use claude"
        assert launched == []

        await pilot.click("#resolve-use-claude")
        for _ in range(300):  # 15 s ceiling; Windows CI is slow
            await pilot.pause(0.05)
            if launched:
                break

        assert launched == [["resume"]]
        cfg = relay_config.load(tmp_path)
        assert cfg.roles.implementer == "claude"


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_auto_mode_dirty_log_pause_commits_and_resumes_without_click(tmp_path, monkeypatch):
    import json
    import subprocess
    from whyline.console import relay_ops
    from whyline_relay import gitcheck

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "tester@test.com"], cwd=tmp_path, check=True)
    gitcheck.ensure_relay_ignored(tmp_path)
    (tmp_path / "plan.md").write_text("# Plan\n- [ ] REC-4F: Task\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    relay_ops.save_resolve_mode(tmp_path, "auto")

    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4F",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "dirty",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )
    (tmp_path / ".whyline" / "decisions.md").write_text("# Decisions\n- [2026-10-15] Note\n", encoding="utf-8")

    launched = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_launch_relay", lambda args, **kwargs: launched.append(list(args)))

    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._relay_finished(2, "Paused: dirty")
        await pilot.pause()

        assert launched == [["resume"]]
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("resolve · auto · dirty-log · commit-log" in line for line in lines)
        assert any("Committed decision log for REC-4F." in line for line in lines)

        status = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True).stdout
        assert ".whyline/decisions.md" not in status


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_auto_mode_timeout_pause_raises_timeout_and_resumes(tmp_path, monkeypatch):
    import json
    import subprocess
    from whyline.console import relay_ops
    from whyline_relay import gitcheck

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "tester@test.com"], cwd=tmp_path, check=True)
    gitcheck.ensure_relay_ignored(tmp_path)
    (tmp_path / "plan.md").write_text("# Plan\n- [ ] REC-4F: Task\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    relay_ops.save_resolve_mode(tmp_path, "auto")
    relay_ops.save_timeout(tmp_path, 30)

    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4F",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "agent exceeded 1800s and was terminated",
            "log_path": "round.log",
            "timeout_minutes": 30,
        }),
        encoding="utf-8",
    )

    launched = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_launch_relay", lambda args, **kwargs: launched.append(list(args)))

    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._relay_finished(2, "Paused: agent exceeded 1800s and was terminated")
        await pilot.pause()

        assert launched == [["resume"]]
        assert relay_ops.relay_timeout(tmp_path) == 45
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("resolve · auto · timeout · resume-longer" in line for line in lines)
        assert any("Saved timeout 45 minutes and resumed relay." in line for line in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_auto_mode_foreign_commits_pause_shows_buttons_with_move_aside_first(tmp_path, monkeypatch):
    import json
    import subprocess
    from whyline.console import relay_ops
    from whyline_relay import gitcheck

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "tester@test.com"], cwd=tmp_path, check=True)
    gitcheck.ensure_relay_ignored(tmp_path)
    (tmp_path / "init.txt").write_text("initial", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True)
    base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()

    (tmp_path / "plan.md").write_text("# Plan\n- [ ] REC-4F: Task\n", encoding="utf-8")
    subprocess.run(["git", "add", "plan.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "plan: add plan"], cwd=tmp_path, check=True)

    relay_ops.save_resolve_mode(tmp_path, "auto")

    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4F",
            "round": 1,
            "base_commit": base_commit,
            "paused_reason": f"HEAD moved before commit, reset to {base_commit}",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )

    launched = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_launch_relay", lambda args, **kwargs: launched.append(list(args)))

    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._relay_finished(2, f"Paused: HEAD moved before commit, reset to {base_commit}")
        await pilot.pause()

        assert launched == []
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("Auto stopped:" in line for line in lines)

        row = app.query_one("#resolve-actions", tui.Horizontal)
        assert row.display is True
        buttons = list(row.query(tui.Button))
        assert buttons[0].id == "resolve-move-aside"


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_auto_mode_auth_pause_applies_nothing(tmp_path, monkeypatch):
    import json
    import subprocess
    from whyline.console import relay_ops
    from whyline_relay import gitcheck

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "tester@test.com"], cwd=tmp_path, check=True)
    gitcheck.ensure_relay_ignored(tmp_path)
    (tmp_path / "plan.md").write_text("# Plan\n- [ ] REC-4F: Task\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    relay_ops.save_resolve_mode(tmp_path, "auto")

    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    auth_reason = "codex is no longer logged in; try again once you've signed back in"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4F",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": auth_reason,
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )

    launched = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_launch_relay", lambda args, **kwargs: launched.append(list(args)))

    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._relay_finished(2, f"Paused: {auth_reason}")
        await pilot.pause()

        assert launched == []
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("Auto stopped:" in line for line in lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_auto_mode_second_pause_in_same_round_applies_nothing_and_shows_buttons(tmp_path, monkeypatch):
    import json
    import subprocess
    from whyline.console import relay_ops, recovery
    from whyline_relay import gitcheck

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "tester@test.com"], cwd=tmp_path, check=True)
    gitcheck.ensure_relay_ignored(tmp_path)
    (tmp_path / "plan.md").write_text("# Plan\n- [ ] REC-4F: Task\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    relay_ops.save_resolve_mode(tmp_path, "auto")

    recovery.record_attempt(tmp_path, task="REC-4F", round=1, kind="resolve-auto", verdict="resolved")

    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4F",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "dirty",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )
    (tmp_path / ".whyline" / "decisions.md").write_text("# Decisions\n- [2026-10-15] Note\n", encoding="utf-8")

    launched = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_launch_relay", lambda args, **kwargs: launched.append(list(args)))

    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._relay_finished(2, "Paused: dirty")
        await pilot.pause()

        assert launched == []
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("Auto stopped: recovery already attempted for REC-4F round 1" in line for line in lines)
        assert app.query_one("#resolve-actions", tui.Horizontal).display is True


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_review_mode_applies_nothing_without_click(tmp_path, monkeypatch):
    import json
    import subprocess
    from whyline.console import relay_ops
    from whyline_relay import gitcheck

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "tester@test.com"], cwd=tmp_path, check=True)
    gitcheck.ensure_relay_ignored(tmp_path)
    (tmp_path / "plan.md").write_text("# Plan\n- [ ] REC-4F: Task\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    relay_ops.save_resolve_mode(tmp_path, "review")

    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4F",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "dirty",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )
    (tmp_path / ".whyline" / "decisions.md").write_text("# Decisions\n- [2026-10-15] Note\n", encoding="utf-8")

    launched = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_launch_relay", lambda args, **kwargs: launched.append(list(args)))

    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._relay_finished(2, "Paused: dirty")
        await pilot.pause()

        assert launched == []
        assert app.query_one("#resolve-actions", tui.Horizontal).display is False
        btn_resolve = app.query_one("#relay-resolve", tui.Button)
        assert btn_resolve.display is True
        assert btn_resolve.disabled is False


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_relay_setup_and_plan_with_no_agents_prints_message_and_pushes_no_screen(tmp_path, monkeypatch):
    from whyline.console import relay_ops
    from whyline.console.relay_screens import NO_AGENTS_SETUP, NO_AGENTS_PLAN

    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: [])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()

        btn_setup = app.query_one("#relay-setup", tui.Button)
        btn_plan = app.query_one("#relay-plan", tui.Button)
        assert not btn_setup.disabled
        assert not btn_plan.disabled

        # Press Set up
        await pilot.click("#relay-setup")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert any(NO_AGENTS_SETUP in e.text for e in app.session.transcript)
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("No agent is installed here" in line for line in lines)
        assert any("Set up again" in line for line in lines)
        assert not btn_setup.disabled
        assert not btn_plan.disabled

        # Press Plan
        await pilot.click("#relay-plan")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert any(NO_AGENTS_PLAN in e.text for e in app.session.transcript)
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("No agent is installed here" in line for line in lines)
        assert any("Plan again" in line for line in lines)
        assert not btn_setup.disabled
        assert not btn_plan.disabled


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_relay_setup_and_plan_with_one_agent_opens_screens(tmp_path, monkeypatch):
    from whyline.console import relay_ops
    from whyline.console.relay_screens import RelayPlanScreen, RelaySetupScreen

    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: ["codex"])
    monkeypatch.setattr(relay_ops, "planner_agents", lambda root: ("codex", "codex", ""))
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "codex",
            "tester": "codex",
            "reviewer": "codex",
            "backup": ["codex"],
        },
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()

        # Press Set up
        await pilot.click("#relay-setup")
        await pilot.pause()
        assert isinstance(app.screen, RelaySetupScreen)
        app.screen.dismiss(None)
        await pilot.pause()
        assert len(app.screen_stack) == 1

        # Press Plan
        await pilot.click("#relay-plan")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        app.screen.dismiss(None)
        await pilot.pause()
        assert len(app.screen_stack) == 1


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_send_passes_300_900_1800_2700_3600_and_none_into_chat_run_turn(tmp_path, monkeypatch):
    from whyline_relay import chat

    seen = []

    def fake_run_turn(root, *, agent, prompt, settings, attachments, timeout_seconds=None, **kwargs):
        seen.append((prompt, timeout_seconds))
        return {"agent": agent, "response": f"ok {timeout_seconds}", "ok": True, "rate_limited": False}

    monkeypatch.setattr(chat, "run_turn", fake_run_turn)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        select = app.query_one("#cb-timeout", tui.Select)
        prompt = app.query_one("#prompt", tui.Input)
        for choice in (300, 900, 1800, 2700, 3600, "none", 900):
            select.value = choice
            await pilot.pause()
            if choice == "none":
                closed = select.query_one("#label").renderable
                closed_text = closed.plain if hasattr(closed, "plain") else str(closed)
                assert closed_text == "none"
                assert app.session.chat_timeout_seconds == "none"
            prompt.value = f"turn-{choice}"
            app._send()
            await app.workers.wait_for_complete()
            await pilot.pause()

    assert seen == [
        ("turn-300", 300),
        ("turn-900", 900),
        ("turn-1800", 1800),
        ("turn-2700", 2700),
        ("turn-3600", 3600),
        ("turn-none", chat.NO_LIMIT),
        ("turn-900", 900),
    ]
    assert seen[5][1] is chat.NO_LIMIT


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_timeout_select_disables_while_chat_or_brainstorm_runs_and_stays_enabled_during_relay(
    tmp_path, monkeypatch
):
    import threading
    from whyline.console import adapters, relay_ops
    from whyline.console.session import SessionEvent

    chat_started = threading.Event()
    chat_release = threading.Event()

    def slow_chat_turn(root, *, agent, prompt, timeout_seconds=None, **kwargs):
        chat_started.set()
        chat_release.wait(timeout=2.0)
        return SessionEvent(kind="output", text="chat done")

    bs_started = threading.Event()
    bs_release = threading.Event()

    def slow_brainstorm(root, *, progress, **choice):
        bs_started.set()
        bs_release.wait(timeout=2.0)
        return SessionEvent(kind="output", text="brainstorm done")

    monkeypatch.setattr(adapters, "run_chat_turn", slow_chat_turn)
    monkeypatch.setattr(adapters, "run_brainstorm", slow_brainstorm)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        select = app.query_one("#cb-timeout", tui.Select)
        assert not select.disabled

        # Chat worker disables #cb-timeout while running and re-enables when busy clears.
        app.query_one("#prompt", tui.Input).value = "hello"
        app._send()
        assert select.disabled
        await pilot.pause()
        assert chat_started.wait(timeout=2.0)
        assert select.disabled
        chat_release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not select.disabled

        # Brainstorm worker disables #cb-timeout while running and re-enables when busy clears.
        app._run_brainstorm_choice({
            "topic": "t",
            "agents": ["claude"],
            "passes": 1,
            "final_agent": "claude",
            "timeout_minutes": 15,
            "attachments": [],
        })
        assert select.disabled
        await pilot.pause()
        assert bs_started.wait(timeout=2.0)
        assert select.disabled
        bs_release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not select.disabled

        # Relay run leaves #cb-timeout enabled and does not read session.chat_timeout_seconds.
        class FakeRelay:
            def __init__(self, root, args, *, on_line, on_exit):
                self._running = False

            def start(self):
                self._running = True

            def running(self):
                return self._running

        monkeypatch.setattr(tui, "RelayProcess", FakeRelay)
        monkeypatch.setattr(relay_ops, "list_plans", lambda root: [tmp_path / "plan.md"])
        monkeypatch.setattr(
            relay_ops,
            "current_roles",
            lambda root: {
                "implementer": "claude",
                "tester": "codex",
                "reviewer": "claude",
                "backup": [],
            },
        )
        monkeypatch.setattr(relay_ops, "live_run", lambda root: None)

        app._launch_relay(["start"])
        await pilot.pause()
        assert app._relay_running()
        assert not select.disabled
        # Even if _set_busy(True) runs while _relay_running(), gate keeps #cb-timeout enabled.
        app._set_busy(True, "auto")
        assert not select.disabled
        app._set_busy(False)
        app._relay_finished(0, "Plan complete")
        await pilot.pause()
        assert not select.disabled


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_send_captures_timeout_before_select_changes_mid_run(tmp_path, monkeypatch):
    import threading
    from whyline.console import adapters
    from whyline.console.session import SessionEvent

    started = threading.Event()
    release = threading.Event()
    seen = []

    def slow_chat_turn(root, *, agent, prompt, timeout_seconds=None, **kwargs):
        started.set()
        release.wait(timeout=2.0)
        seen.append((prompt, timeout_seconds))
        return SessionEvent(kind="output", text="done")

    monkeypatch.setattr(adapters, "run_chat_turn", slow_chat_turn)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        select = app.query_one("#cb-timeout", tui.Select)
        select.value = 900
        await pilot.pause()
        assert app.session.chat_timeout_seconds == 900

        app.query_one("#prompt", tui.Input).value = "first"
        app._send()
        select.value = 1800
        await pilot.pause()
        assert started.wait(timeout=2.0)

        # Change the select again before the fake run returns.
        select.value = 2700
        await pilot.pause()
        assert app.session.chat_timeout_seconds == 2700

        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert seen == [("first", 900)]

        # A subsequent Send uses the newly selected value.
        app.query_one("#prompt", tui.Input).value = "second"
        app._send()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert seen == [("first", 900), ("second", 2700)]


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_timeout_slash_command_updates_session_and_select_including_none(
    tmp_path, monkeypatch
):
    from whyline_relay import chat

    assert "/timeout" in tui._SLASH_HINT
    seen_turns = []

    def fake_run_turn(root, *, agent, prompt, settings, attachments, timeout_seconds=None, **kwargs):
        seen_turns.append((prompt, timeout_seconds))
        return {"agent": agent, "response": "ok", "ok": True, "rate_limited": False}

    monkeypatch.setattr(chat, "run_turn", fake_run_turn)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        select = app.query_one("#cb-timeout", tui.Select)
        prompt = app.query_one("#prompt", tui.Input)
        assert app.session.chat_timeout_seconds == 300
        assert select.value == 300

        # /timeout reports the current value.
        prompt.value = "/timeout"
        app._send()
        await pilot.pause()
        assert app.session.transcript[-1].text == "Chat timeout: 5m. Each attempt gets this limit."

        # /timeout none (and unlimited, 0, no limit) sets "none", moves the select, and reports the sentence.
        for token in ("none", "unlimited", "0", "no limit"):
            app.session.chat_timeout_seconds = 300
            select.value = 300
            await pilot.pause()
            prompt.value = f"/timeout {token}"
            app._send()
            await pilot.pause()
            assert app.session.chat_timeout_seconds == "none"
            assert select.value == "none"
            closed = select.query_one("#label").renderable
            closed_text = closed.plain if hasattr(closed, "plain") else str(closed)
            assert closed_text == "none"
            assert app.session.transcript[-1].kind == "output"
            assert (
                app.session.transcript[-1].text
                == "Chat timeout: none. Each attempt has no whyline kill timer."
            )

        # Bare /timeout when stored value is "none" prints the no-limit sentence.
        prompt.value = "/timeout"
        app._send()
        await pilot.pause()
        assert (
            app.session.transcript[-1].text
            == "Chat timeout: none. Each attempt has no whyline kill timer."
        )

        # Sending after /timeout none passes chat.NO_LIMIT into chat.run_turn.
        prompt.value = "after-none"
        app._send()
        await app.workers.wait_for_complete()
        await pilot.pause()

        # /timeout 30 and /timeout 45m update both the session and #cb-timeout, and Send passes seconds again.
        prompt.value = "/timeout 30"
        app._send()
        await pilot.pause()
        assert app.session.chat_timeout_seconds == 1800
        assert select.value == 1800
        assert app.session.transcript[-1].text == "Chat timeout: 30m. Each attempt gets this limit."

        prompt.value = "after-30"
        app._send()
        await app.workers.wait_for_complete()
        await pilot.pause()

        prompt.value = "/timeout 45m"
        app._send()
        await pilot.pause()
        assert app.session.chat_timeout_seconds == 2700
        assert select.value == 2700
        assert app.session.transcript[-1].text == "Chat timeout: 45m. Each attempt gets this limit."

        # Unknown value leaves the previous choice and replies with Usage.
        prompt.value = "/timeout 20"
        app._send()
        await pilot.pause()
        assert app.session.chat_timeout_seconds == 2700
        assert select.value == 2700
        assert app.session.transcript[-1].kind == "error"
        assert app.session.transcript[-1].text == "Usage: /timeout [5|15|30|45|60|none]"

    assert len(seen_turns) == 2
    assert seen_turns[0][0] == "after-none" and seen_turns[0][1] is chat.NO_LIMIT
    assert seen_turns[1] == ("after-30", 1800)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_stop_cancels_the_in_flight_chat_attempt(tmp_path, monkeypatch):
    import threading

    from whyline.console.session import SessionEvent
    from whyline_relay import agents

    _init_test_repo(tmp_path)

    started = threading.Event()
    release = threading.Event()
    seen_cancel = []

    def fake_run(command, prompt, **kwargs):
        cancel_event = kwargs.get("cancel_event")
        seen_cancel.append(cancel_event)
        started.set()
        if cancel_event is not None:
            cancel_event.wait(timeout=2.0)
            release.wait(timeout=2.0)
            if cancel_event.is_set():
                raise agents.AgentCancelled(f"{command[0]} cancelled by user")
        return agents.RunResult(0, '{"type":"result","result":"too late"}\n')

    monkeypatch.setattr(agents, "run", fake_run)
    monkeypatch.setattr(
        "whyline_relay.init.ensure_permission_files", lambda *a, **k: []
    )

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        prompt = app.query_one("#prompt", tui.Input)
        prompt.value = "hello"
        app._send()
        await pilot.pause()
        assert started.wait(timeout=2.0), [
            (e.kind, e.text) for e in app.session.transcript
        ]
        held = seen_cancel[0]
        assert held is app._cancel_event
        assert not held.is_set()

        old_token = app._dispatch_token
        await pilot.click("#stop")
        await pilot.pause()
        assert held.is_set()
        assert app._dispatch_token is not old_token
        assert app._busy_text
        texts = [e.text for e in app.session.transcript]
        assert "Stopping…" in texts

        app._finish_dispatch(
            SessionEvent(kind="output", text="too late"), old_token
        )
        assert not any(e.text == "too late" for e in app.session.transcript)
        assert "Stopped." not in [e.text for e in app.session.transcript]

        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        texts = [e.text for e in app.session.transcript]
        assert texts.count("Stopped.") == 1
        assert not any("too late" in (e.text or "") for e in app.session.transcript)
        assert not app._busy_text


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_newer_brainstorm_ignores_a_late_chat_stop(tmp_path, monkeypatch):
    """A slash-triggered Brainstorm replaces the Chat cancel identity, so
    that worker's late Stopped. neither renders nor clears Brainstorm busy."""
    import threading

    from whyline import account
    from whyline.console import adapters
    from whyline.console.session import SessionEvent
    from whyline_relay import agents

    _init_test_repo(tmp_path)

    started = threading.Event()
    chat_release = threading.Event()
    chat_done = threading.Event()
    bs_started = threading.Event()
    bs_release = threading.Event()
    finished = []

    def fake_run(command, prompt, **kwargs):
        cancel_event = kwargs.get("cancel_event")
        try:
            started.set()
            if cancel_event is not None:
                cancel_event.wait(timeout=2.0)
                chat_release.wait(timeout=10.0)
                if cancel_event.is_set():
                    raise agents.AgentCancelled(f"{command[0]} cancelled by user")
            return agents.RunResult(0, '{"type":"result","result":"too late"}\n')
        finally:
            chat_done.set()

    def slow_brainstorm(root, *, progress, **choice):
        bs_started.set()
        progress("Researching independently: Claude")
        bs_release.wait(timeout=10.0)
        return SessionEvent(kind="output", text="brainstorm done")

    monkeypatch.setattr(agents, "run", fake_run)
    monkeypatch.setattr(adapters, "run_brainstorm", slow_brainstorm)
    monkeypatch.setattr(account, "available_agents", lambda root: {"claude"})
    monkeypatch.setattr(
        "whyline_relay.init.ensure_permission_files", lambda *a, **k: []
    )

    app = tui.WhylineConsoleApp(root=tmp_path)

    def record_finish(result, token, launched=True, cancel_event=None):
        finished.append(getattr(result, "text", None))
        return tui.WhylineConsoleApp._finish_dispatch(
            app, result, token, launched, cancel_event
        )

    app._finish_dispatch = record_finish

    async with app.run_test(size=(110, 40)) as pilot:
        try:
            prompt = app.query_one("#prompt", tui.Input)
            prompt.value = "hello"
            app._send()
            await pilot.pause()
            assert started.wait(timeout=2.0), [
                (e.kind, e.text) for e in app.session.transcript
            ]
            held = app._cancel_event
            assert held is not None and not held.is_set()

            await pilot.click("#stop")
            await pilot.pause()
            assert held.is_set()
            assert app._cancel_event is held

            app._handle_slash("/brainstorm")
            await pilot.pause()
            assert isinstance(app.screen, tui.BrainstormScreen)
            app.screen.query_one("#bs-topic", tui.Input).value = "late cancel"
            await pilot.click("#bs-start")
            for _ in range(50):
                if bs_started.is_set():
                    break
                await pilot.pause(0.05)
            assert bs_started.is_set(), "brainstorm dispatch never started"
            assert app._cancel_event is not held
            assert "brainstorm" in app._busy_text

            chat_release.set()
            for _ in range(50):
                if "Stopped." in finished:
                    break
                await pilot.pause(0.05)
            assert chat_done.is_set()
            assert "Stopped." in finished
            texts = [e.text for e in app.session.transcript]
            assert texts.count("Stopped.") == 0
            assert "brainstorm" in app._busy_text
        finally:
            chat_release.set()
            bs_release.set()
            await app.workers.wait_for_complete()
        await pilot.pause()
        texts = [e.text for e in app.session.transcript]
        assert texts.count("Stopped.") == 0
        assert any(text == "brainstorm done" for text in texts)
        assert not app._busy_text


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_approved_plan_with_test_plan_prints_both_paths(tmp_path):
    from whyline.console import plan_job, relay_ops

    _init_test_repo(tmp_path)
    relay_ops.save_planner(tmp_path, "codex", "claude", "codex")
    draft_path = tmp_path / ".whyline" / "relay" / "draft-plan.md"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text("- [ ] T-1: build it\n", encoding="utf-8")
    tests_draft = tmp_path / ".whyline" / "relay" / "draft-plan.tests.md"
    tests_draft.write_text(
        "- [ ] S-1: check T-1\n"
        "  covers: T-1\n"
        "  kind: auto\n"
        "  steps:\n"
        "  - run pytest\n"
        "  expected:\n"
        "  - passes\n",
        encoding="utf-8",
    )

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app.session.mode = "relay"
        draft = relay_ops.Draft(
            path=draft_path,
            text="- [ ] T-1: build it\n",
            drafted_by="codex (reviewed by claude)",
            source="planner",
        )
        app._plan_outcome = plan_job.Outcome("draft", draft, stage="plan")
        app._plan_request = plan_job.PlanRequest("draft", "My Plan", spec_first=False)
        app._approve_plan()
        await app.workers.wait_for_complete()
        await pilot.pause()

        texts = [e.text for e in app.session.transcript]
        assert any(
            "plans/my-plan.plan.md" in text and "plans/my-plan.tests.md" in text
            for text in texts
        ), texts
        assert (tmp_path / "plans" / "my-plan.plan.md").is_file()
        assert (tmp_path / "plans" / "my-plan.tests.md").is_file()


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_brainstorm_screen_saves_and_restores_test_planner_and_shows_tip(
    tmp_path, monkeypatch
):
    from whyline import account
    from whyline.console import adapters, relay_ops
    from whyline.console.session import SessionEvent

    _init_test_repo(tmp_path)
    monkeypatch.setattr(account, "available_agents", lambda root: {"claude", "codex"})
    monkeypatch.setattr(
        adapters,
        "run_brainstorm",
        lambda root, *, progress, cancel_event=None, **choice: SessionEvent(
            kind="output", text="done"
        ),
    )

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.click("#brainstorm")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, tui.BrainstormScreen)
        select = form.query_one("#bs-test-planner", tui.Select)
        tip = form.query_one("#bs-test-planner-tip", tui.Static)
        assert select.value == ""
        assert not tip.display

        select.value = "codex"
        await pilot.pause()
        assert tip.display
        assert str(tip.renderable) == "Tip: a different agent from the Drafter catches more."

        form.query_one("#bs-topic", tui.Input).value = "retry policy"
        await pilot.click("#bs-start")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert relay_ops.planner_agents(tmp_path) == ("codex", "claude", "codex")

        await pilot.click("#brainstorm")
        await pilot.pause()
        reopened = app.screen
        assert isinstance(reopened, tui.BrainstormScreen)
        assert reopened.query_one("#bs-test-planner", tui.Select).value == "codex"
        assert reopened.query_one("#bs-test-planner-tip", tui.Static).display


MANUAL_PAUSE_TWO_CHECKS = (
    "Paused: Manual checks before REL-1:\n"
    "TP-1: Check login flow | steps: open /login; submit credentials | expected: dashboard loads\n"
    "TP-2: Check logout flow | steps: click logout | expected: redirected to /login\n"
)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_manual_check_pause_shows_checks_and_pass_advances_to_next_and_last_enables_resume(
    tmp_path, monkeypatch
):
    from whyline.console import relay_ops

    launched: list[list[str]] = []
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_launch_relay", lambda args, **kwargs: launched.append(list(args)))

    async with app.run_test(size=(110, 40)) as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()

        manual_row = app.query_one("#manual-actions", tui.Horizontal)
        resume_btn = app.query_one("#relay-resume", tui.Button)
        assert not manual_row.display

        # Relay pauses with Manual checks before reason
        app._relay_finished(3, MANUAL_PAUSE_TWO_CHECKS)
        await pilot.pause()

        assert manual_row.display
        buttons = [str(b.label) for b in manual_row.query(tui.Button)]
        assert buttons == ["Pass", "Fail"]
        assert resume_btn.disabled
        assert app._manual_check is not None and app._manual_check.id == "TP-1"

        texts = [e.text for e in app.session.transcript]
        assert any(
            "TP-1: Check login flow | steps: open /login; submit credentials | expected: dashboard loads" in t
            and "TP-2: Check logout flow | steps: click logout | expected: redirected to /login" in t
            and "Check TP-1: Pass or Fail." in t
            for t in texts
        )

        # Clicking Pass launches `manual TP-1 pass` and moves to TP-2
        await pilot.click("#manual-pass")
        await pilot.pause()

        assert launched == [["manual", "TP-1", "pass"]]
        assert manual_row.display
        assert resume_btn.disabled
        assert app._manual_check is not None and app._manual_check.id == "TP-2"
        assert "Check TP-2: Pass or Fail." in app.session.transcript[-1].text

        # Clicking Pass on the last check launches `manual TP-2 pass`, prints hint, and enables Resume
        await pilot.click("#manual-pass")
        await pilot.pause()

        assert launched == [
            ["manual", "TP-1", "pass"],
            ["manual", "TP-2", "pass"],
        ]
        assert not manual_row.display
        assert not resume_btn.disabled
        assert str(resume_btn.label) == "Resume"
        assert app.session.transcript[-1].text == "All manual checks passed. Press Resume to release."


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_manual_check_fail_requires_a_note_and_runs_manual_fail_with_note(
    tmp_path, monkeypatch
):
    from whyline.console import relay_ops

    launched: list[list[str]] = []
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_launch_relay", lambda args, **kwargs: launched.append(list(args)))

    async with app.run_test(size=(110, 40)) as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        app._relay_finished(3, MANUAL_PAUSE_TWO_CHECKS)
        await pilot.pause()

        # Click Fail: asks for a note in the prompt and does not launch yet
        await pilot.click("#manual-fail")
        await pilot.pause()

        assert launched == []
        assert app._manual_fail_id == "TP-1"
        assert any("Why did TP-1 fail?" in e.text for e in app.session.transcript)

        # Submitting an empty prompt requires a note and still does not launch
        prompt = app.query_one("#prompt", tui.Input)
        prompt.value = "   "
        app._send()
        await pilot.pause()

        assert launched == []
        assert app.session.transcript[-1].kind == "error"
        assert "fail needs a note" in app.session.transcript[-1].text

        # Typing a note and sending runs `manual TP-1 fail <note>` and moves to next check
        prompt.value = "login button misaligned"
        app._send()
        await pilot.pause()

        assert launched == [["manual", "TP-1", "fail", "login button misaligned"]]
        assert app._manual_fail_id is None
        assert app._manual_check is not None and app._manual_check.id == "TP-2"


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_typing_manual_commands_in_relay_prompt_and_release_pause_without_manual_checks(
    tmp_path, monkeypatch
):
    from whyline.console import relay_ops

    launched: list[list[str]] = []
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_launch_relay", lambda args, **kwargs: launched.append(list(args)))

    async with app.run_test(size=(110, 40)) as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()

        # A release pause with no manual checks shows no #manual-actions row
        app._relay_finished(
            3,
            "Paused: release task for you: REL-1\n1. Bump version\n2. Tag release\n",
        )
        await pilot.pause()
        manual_row = app.query_one("#manual-actions", tui.Horizontal)
        assert not manual_row.display

        # Now pause with manual check TP-3
        app._relay_finished(
            3,
            "Paused: Manual checks before REL-1:\n"
            "TP-3: Verify banner | steps: open home | expected: banner visible\n",
        )
        await pilot.pause()
        assert manual_row.display

        prompt = app.query_one("#prompt", tui.Input)

        # Typing `manual` lists checks
        prompt.value = "manual"
        app._send()
        await pilot.pause()
        assert launched[-1] == ["manual"]
        assert manual_row.display

        # Typing `manual TP-3 fail <note>` runs fail with note
        prompt.value = "manual TP-3 fail banner missing"
        app._send()
        await pilot.pause()
        assert launched[-1] == ["manual", "TP-3", "fail", "banner missing"]
        assert manual_row.display

        # Typing `manual TP-3 pass` passes the last check, prints hint, and enables Resume
        prompt.value = "manual TP-3 pass"
        app._send()
        await pilot.pause()
        assert launched[-1] == ["manual", "TP-3", "pass"]
        assert not manual_row.display
        assert not app.query_one("#relay-resume", tui.Button).disabled
        assert app.session.transcript[-1].text == "All manual checks passed. Press Resume to release."


