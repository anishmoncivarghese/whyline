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
