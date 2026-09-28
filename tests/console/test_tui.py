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
        for button_id in ("send", "model", "route", "history", "stop", "help"):
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
        prompt = app.query_one("#prompt", tui.TextArea)
        prompt.text = "hello"
        await pilot.click("#send")
        await app.workers.wait_for_complete()
        await pilot.pause()  # let the call_from_thread land
        transcript = app.query_one("#transcript", tui.RichLog)
        assert any("ran 'hello'" in str(line) for line in transcript.lines)
        assert prompt.text == ""


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_send_ignores_empty_or_whitespace_prompt(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(tui, "dispatch", lambda session, text: called.append(text))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", tui.TextArea)
        prompt.text = "   \n  "
        await pilot.click("#send")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert called == []
        transcript = app.query_one("#transcript", tui.RichLog)
        assert transcript.lines == []


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_dispatch_error_renders_as_error_event(tmp_path, monkeypatch):
    def failing_dispatch(session, text):
        raise RuntimeError("boom")

    monkeypatch.setattr(tui, "dispatch", failing_dispatch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", tui.TextArea)
        prompt.text = "fail"
        await pilot.click("#send")
        await app.workers.wait_for_complete()
        await pilot.pause()
        transcript = app.query_one("#transcript", tui.RichLog)
        assert any("⚠ boom" in str(line) for line in transcript.lines)


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_superseded_dispatch_token_discards_result(tmp_path, monkeypatch):
    import threading
    import time
    from whyline.console.session import SessionEvent

    slow_started = threading.Event()

    def slow_dispatch(session, text):
        slow_started.set()
        time.sleep(0.05)
        return SessionEvent(kind="output", text="slow output")

    monkeypatch.setattr(tui, "dispatch", slow_dispatch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", tui.TextArea)
        prompt.text = "slow"
        await pilot.click("#send")
        # Wait for slow dispatch to begin running in worker thread
        assert slow_started.wait(timeout=2.0)
        # Supersede the token
        app._dispatch_token = object()
        # Wait for worker to finish
        await app.workers.wait_for_complete()
        await pilot.pause()
        transcript = app.query_one("#transcript", tui.RichLog)
        assert transcript.lines == []


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_model_button_dispatches_the_same_text_as_typing_it(tmp_path, monkeypatch):
    from whyline.console.session import SessionEvent

    seen = []
    monkeypatch.setattr(
        tui, "dispatch",
        lambda session, text: seen.append(text) or SessionEvent(kind="output", text="ok"),
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#model")
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert seen == ["/model"]


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_route_history_help_buttons_dispatch_their_slash_commands(tmp_path, monkeypatch):
    from whyline.console.session import SessionEvent

    seen = []
    monkeypatch.setattr(
        tui, "dispatch",
        lambda session, text: seen.append(text) or SessionEvent(kind="output", text="ok"),
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#route")
        await pilot.click("#history")
        await pilot.click("#help")
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert seen == ["/route", "/history", "/help"]


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_stop_cancels_the_active_worker(tmp_path, monkeypatch):
    import threading
    from whyline.console.session import SessionEvent

    release = threading.Event()

    def slow_dispatch(session, text):
        release.wait(timeout=2)  # held open until the test itself lets go
        return SessionEvent(kind="output", text="too late")

    monkeypatch.setattr(tui, "dispatch", slow_dispatch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", tui.TextArea)
        prompt.text = "long running"
        await pilot.click("#send")
        await pilot.pause()  # let the worker actually start and block on release
        await pilot.click("#stop")  # invalidates the token while still blocked
        release.set()  # now let the blocked dispatch finish, "too late"
        await pilot.pause()
        await pilot.pause()  # give call_from_thread a beat to have run, if it were going to
        transcript = app.query_one("#transcript", tui.RichLog)
        assert not any("too late" in str(line) for line in transcript.lines)

