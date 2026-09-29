import pytest
from whyline.console import tui


def test_tui_available_flag_exists():
    assert isinstance(tui.TUI_AVAILABLE, bool)


def test_launch_raises_a_clear_error_without_textual(monkeypatch, tmp_path):
    monkeypatch.setattr(tui, "TUI_AVAILABLE", False)
    with pytest.raises(tui.TuiUnavailable, match=r"whyline\[ui\]"):
        tui.launch(tmp_path)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_app_composes_header_transcript_prompt_and_controls(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        assert app.query_one("#transcript") is not None
        assert app.query_one("#prompt") is not None
        for button_id in ("send", "model", "mode-command", "mode-chat", "mode-relay", "history", "stop", "help", "copy"):
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
        assert any(
            "claude" in str(line) and "codex" in str(line) for line in transcript.lines
        )


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_route_relay_with_no_config_defers_exec_until_after_exit(
    tmp_path, monkeypatch
):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#mode-relay")
        await pilot.pause()
        assert app._exec_after == ("whyline", ["whyline", "relay", "setup"])
    # app.run_test()'s own context manager has now exited (app.run() returned)
    # -- confirm launch() is what actually performs the exec, not the app itself.


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_typing_route_relay_with_no_config_defers_exec_until_after_exit(
    tmp_path, monkeypatch
):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", tui.Input)
        prompt.value = "/route relay"
        await pilot.click("#send")
        await pilot.pause()
        assert app._exec_after == ("whyline", ["whyline", "relay", "setup"])


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
        monkeypatch.setattr(app, "copy_to_clipboard", lambda text: copied.append(text))
        await pilot.click("#copy")
        await pilot.pause()
        assert copied == ["earlier output"]
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
