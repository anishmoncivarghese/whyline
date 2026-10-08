# tests/console/test_agent_deliveries_console.py
from types import SimpleNamespace

import pytest

from whyline.agents import telegram
from whyline.console import tui
from whyline.console.agents_screens import RunsScreen, TelegramSetupScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


async def _until(pilot, condition, what):
    # push_screen makes the screen current before its widgets are mounted.
    for _ in range(400):
        await pilot.pause(0.05)
        if condition():
            return
    raise AssertionError(f"never happened: {what}")


@pytest.fixture
def fake_telegram(monkeypatch):
    state = {"token": None, "chats": {}, "sent": []}
    monkeypatch.setattr(telegram, "token_get", lambda: state["token"])
    monkeypatch.setattr(telegram, "check_token", lambda token: "@JobsBot")
    monkeypatch.setattr(telegram, "token_set", lambda token: state.update(token=token))
    monkeypatch.setattr(telegram, "find_chats", lambda token: {11: "Anish V (private)"})
    monkeypatch.setattr(telegram, "remember_chats", lambda chats: state["chats"].update(chats) or state["chats"])
    monkeypatch.setattr(telegram, "known_chats", lambda: dict(state["chats"]))
    monkeypatch.setattr(telegram, "send_message",
                        lambda token, chat, text, label="": state["sent"].append((chat, text)))
    return state


async def test_telegram_setup_checks_finds_chats_and_tests(tmp_path, fake_telegram):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        result = []
        app.push_screen(TelegramSetupScreen(), result.append)
        await _until(pilot, lambda: isinstance(app.screen, TelegramSetupScreen), "setup shown")
        screen = app.screen
        screen.query_one("#tg-token", tui.Input).value = "123:secret"
        screen.query_one("#tg-check", tui.Button).press()
        await _until(pilot, lambda: "Connected to @JobsBot" in str(screen.query_one("#tg-bot").renderable),
                     "connected")
        assert fake_telegram["token"] == "123:secret"
        await _until(pilot, lambda: "Anish V (private)" in str(screen.query_one("#tg-chats").renderable),
                     "chat found")
        screen.query_one("#tg-test", tui.Button).press()
        await _until(pilot, lambda: fake_telegram["sent"], "test sent")
        assert fake_telegram["sent"][0][0] == 11
        for button in ("#tg-check", "#tg-test", "#tg-done"):
            region = screen.query_one(button).region
            assert region.right <= 80 and region.bottom <= 24
        screen.query_one("#tg-done", tui.Button).press()
        await _until(pilot, lambda: result, "dismissed")
        assert result[0] == {11: "Anish V (private)"}


async def test_a_rejected_token_shows_the_error(tmp_path, fake_telegram, monkeypatch):
    def reject(token):
        raise telegram.TelegramError("the bot token was rejected; run Telegram setup again")

    monkeypatch.setattr(telegram, "check_token", reject)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(TelegramSetupScreen())
        await _until(pilot, lambda: isinstance(app.screen, TelegramSetupScreen), "setup shown")
        app.screen.query_one("#tg-token", tui.Input).value = "bad"
        app.screen.query_one("#tg-check", tui.Button).press()
        await _until(pilot, lambda: "rejected" in str(app.screen.query_one("#tg-bot").renderable),
                     "error shown")
        assert fake_telegram["token"] is None


async def test_runs_show_delivery_status_and_resend(tmp_path, monkeypatch):
    run = SimpleNamespace(run_id="r1", started="2026-10-09T07:00:00", source="schedule", cli="codex",
                          used_backup=None, outcome="succeeded",
                          deliveries=[{"to": "email", "ok": True, "detail": ""},
                                      {"to": "telegram", "ok": False, "detail": "no connection to Telegram"}])
    resent = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(RunsScreen("jobs (personal)", [run], on_resend=resent.append))
        await _until(pilot, lambda: isinstance(app.screen, RunsScreen), "runs shown")
        table = app.screen.query_one("#rs-runs")
        assert "telegram ✗" in str(table.get_row_at(0)[-1])
        app.screen.query_one("#rs-resend", tui.Button).press()
        await _until(pilot, lambda: resent == ["r1"], "resend called")


async def test_closing_setup_while_a_check_is_running_does_not_crash(tmp_path, fake_telegram, monkeypatch):
    # Reported: Done while the 3-second chat check was in flight crashed the
    # console (NoActiveAppError) when the check finished after the screen closed.
    import threading

    release, started = threading.Event(), threading.Event()

    def slow_find(token):
        started.set()
        release.wait(5)
        return {}

    monkeypatch.setattr(telegram, "find_chats", slow_find)
    fake_telegram["token"] = "123:secret"
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        result = []
        app.push_screen(TelegramSetupScreen(), result.append)
        await _until(pilot, lambda: started.is_set(), "check running")
        app.screen.query_one("#tg-done", tui.Button).press()
        await _until(pilot, lambda: result, "dismissed")
        release.set()
        for _ in range(20):
            await pilot.pause(0.05)
        assert app.is_running  # the late result is dropped, not applied to a closed screen


async def test_connected_with_no_chats_says_how_to_reach_the_bot(tmp_path, fake_telegram, monkeypatch):
    monkeypatch.setattr(telegram, "find_chats", lambda token: {})
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(TelegramSetupScreen())
        await _until(pilot, lambda: isinstance(app.screen, TelegramSetupScreen), "setup shown")
        screen = app.screen
        screen.query_one("#tg-token", tui.Input).value = "123:secret"
        screen.query_one("#tg-check", tui.Button).press()
        await _until(pilot, lambda: "t.me/JobsBot" in str(screen.query_one("#tg-chats").renderable),
                     "guidance shown")
        text = str(screen.query_one("#tg-chats").renderable)
        assert "@JobsBot" in text and "Start" in text
        screen.query_one("#tg-test", tui.Button).press()
        await _until(pilot, lambda: "No chat yet" in str(screen.query_one("#tg-bot").renderable),
                     "test explains")
        assert screen.query_one("#tg-open-bot", tui.Button).display


async def test_an_existing_bot_is_named_when_the_screen_opens(tmp_path, fake_telegram, monkeypatch):
    monkeypatch.setattr(telegram, "find_chats", lambda token: {})
    fake_telegram["token"] = "123:secret"
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(TelegramSetupScreen())
        await _until(pilot, lambda: isinstance(app.screen, TelegramSetupScreen), "setup shown")
        await _until(pilot, lambda: "@JobsBot" in str(app.screen.query_one("#tg-bot").renderable),
                     "bot named")


@pytest.mark.parametrize("action", ["test", "check"])
async def test_closing_setup_while_sending_or_checking_does_not_crash(tmp_path, fake_telegram, monkeypatch, action):
    # Reported: Send test message, then Done before the reply came back,
    # crashed the console (NoMatches '#tg-bot') and the crash report printed
    # the bot token. Every background action must report back safely.
    import threading

    release, started = threading.Event(), threading.Event()

    def slow(*args, **kwargs):
        started.set()
        release.wait(5)
        return "@JobsBot"

    fake_telegram["token"] = "123:secret"
    fake_telegram["chats"].update({11: "Anish V (private)"})
    if action == "test":
        monkeypatch.setattr(telegram, "send_message", slow)
    else:
        monkeypatch.setattr(telegram, "check_token", slow)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        result = []
        app.push_screen(TelegramSetupScreen(), result.append)
        await _until(pilot, lambda: isinstance(app.screen, TelegramSetupScreen), "setup shown")
        screen = app.screen
        if action == "test":
            await _until(pilot, lambda: isinstance(screen.query_one("#tg-chat", tui.Select).value, int),
                         "chat listed")
            screen.query_one("#tg-test", tui.Button).press()
        else:
            screen.query_one("#tg-token", tui.Input).value = "456:other"
            screen.query_one("#tg-check", tui.Button).press()
        await _until(pilot, lambda: started.is_set(), "running")
        screen.query_one("#tg-done", tui.Button).press()
        await _until(pilot, lambda: result, "dismissed")
        release.set()
        for _ in range(20):
            await pilot.pause(0.05)
        assert app.is_running


async def test_a_failing_background_action_never_crashes_the_console(tmp_path, fake_telegram, monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("unexpected")

    fake_telegram["token"] = "123:secret"
    monkeypatch.setattr(telegram, "find_chats", boom)
    monkeypatch.setattr(telegram, "remember_chats", boom)
    monkeypatch.setattr(telegram, "check_token", boom)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(TelegramSetupScreen())
        await _until(pilot, lambda: isinstance(app.screen, TelegramSetupScreen), "setup shown")
        for _ in range(40):
            await pilot.pause(0.05)
        assert app.is_running
