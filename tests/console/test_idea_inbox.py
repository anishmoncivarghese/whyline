"""The console counterpart of `whyline idea telegram setup`.

Allowing a chat and turning the inbox on go through the same functions as
the command. A second visit does not write either setting again.
"""
import pytest

from whyline.agents import launchd, telegram
from whyline.console import tui
from whyline.console.agents_screens import IdeaInboxScreen, TelegramSetupScreen
from whyline.ideas import store, telegram_in, worker

TOKEN = "123456:secret-token"

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


def _visible(screen) -> str:
    parts = [str(widget.renderable) for widget in screen.query(tui.Static)]
    parts.extend(str(widget.renderable) for widget in screen.query(tui.Label))
    select = screen.query_one("#ib-chat", tui.Select)
    parts.extend(str(prompt) for prompt, _value in select._options)
    return "\n".join(parts)


def _values(screen) -> list:
    select = screen.query_one("#ib-chat", tui.Select)
    return [value for _prompt, value in select._options if value is not tui.Select.BLANK]


async def _until(pilot, condition, what):
    for _ in range(400):
        await pilot.pause(0.05)
        if condition():
            return
    raise AssertionError(f"never happened: {what}")


def _known(monkeypatch, chats, token=TOKEN):
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: token)
    monkeypatch.setattr(telegram, "known_chats", lambda: dict(chats))


def _bot(monkeypatch, name="@InboxBot", sleep_seen=None):
    def check(token, *, http=None, sleep=None):
        if sleep_seen is not None:
            sleep_seen.append(sleep)
        return name

    monkeypatch.setattr(telegram, "check_token", check)


async def test_agents_mode_opens_inbox_within_80_columns(tmp_path, ideas_home, monkeypatch):
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: None)
    monkeypatch.setattr(telegram, "known_chats", lambda: {})
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#mode-agents")
        await pilot.pause()
        button = app.query_one("#agents-inbox")
        assert button.display and button.region.right <= 80 and button.region.height > 0
        await pilot.click("#agents-inbox")
        await _until(pilot, lambda: isinstance(app.screen, IdeaInboxScreen), "inbox shown")
        assert "No bot token yet" in _visible(app.screen)
        assert not (ideas_home / "ideas.sqlite3").exists()


async def test_inbox_allows_only_the_chosen_private_chat_and_turns_the_service_on(
    tmp_path, ideas_home, monkeypatch
):
    import time

    chats = {
        11: "Anish V (private)",
        22: "Sam Q (private)",
        -100: "Family (group)",
    }
    _known(monkeypatch, chats)
    sleeps = []
    _bot(monkeypatch, sleep_seen=sleeps)
    turned = []
    monkeypatch.setattr(launchd, "supported", lambda: True)
    monkeypatch.setattr(
        launchd, "turn_on", lambda: turned.append("on") or ideas_home / "agent.plist"
    )
    allowed = []
    real_allow = telegram_in.allow

    def spy(conn, chat_id):
        allowed.append(chat_id)
        return real_allow(conn, chat_id)

    monkeypatch.setattr(telegram_in, "allow", spy)
    workbook = ideas_home / "ideas.xlsx"
    ideas_home.mkdir()
    workbook.write_bytes(b"locked")
    before = workbook.stat().st_mtime_ns

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(IdeaInboxScreen())
        await _until(pilot, lambda: isinstance(app.screen, IdeaInboxScreen), "inbox shown")
        screen = app.screen
        await _until(
            pilot,
            lambda: "Keeping it" in str(screen.query_one("#ib-bot").renderable),
            "bot kept",
        )
        assert sleeps and sleeps[0] is not time.sleep
        assert _values(screen) == [11, 22]
        assert "Family" not in _visible(screen) and "-100" not in _visible(screen)
        assert TOKEN not in _visible(screen)
        assert screen.query_one("#ib-chat", tui.Select).value == 11
        screen.query_one("#ib-chat", tui.Select).value = 22
        screen.query_one("#ib-allow", tui.Button).press()
        await pilot.pause()
        assert allowed == [22]
        assert "Sam Q (private)  (22)  allowed" in _visible(screen)
        for button in ("#ib-allow", "#ib-on", "#ib-close"):
            region = screen.query_one(button).region
            assert region.height > 0 and region.right <= 80 and region.bottom <= 24
        screen.query_one("#ib-on", tui.Button).press()
        await _until(
            pilot,
            lambda: str(screen.query_one("#ib-service").renderable) == "Inbox on.",
            "inbox on",
        )
        assert TOKEN not in _visible(screen)

    assert turned == ["on"]
    assert workbook.stat().st_mtime_ns == before
    assert workbook.read_bytes() == b"locked"
    conn = store.connect()
    try:
        assert telegram_in.allowed_chats(conn) == [22]
        assert conn.execute(
            "SELECT value FROM kv WHERE key = 'enabled'"
        ).fetchone()[0] == "on"
    finally:
        conn.close()


async def test_one_private_chat_is_selected(tmp_path, ideas_home, monkeypatch):
    _known(monkeypatch, {11: "Anish V (private)", -100: "Family (group)"})
    _bot(monkeypatch)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(IdeaInboxScreen())
        await _until(pilot, lambda: isinstance(app.screen, IdeaInboxScreen), "inbox shown")
        await _until(
            pilot,
            lambda: "Keeping it" in str(app.screen.query_one("#ib-bot").renderable),
            "bot kept",
        )
        assert _values(app.screen) == [11]
        assert app.screen.query_one("#ib-chat", tui.Select).value == 11
        assert "Family" not in _visible(app.screen)


async def test_opening_inbox_again_changes_nothing(tmp_path, ideas_home, monkeypatch):
    _known(monkeypatch, {
        11: "Anish V (private)",
        22: "Sam Q (private)",
        -100: "Family (group)",
    })
    _bot(monkeypatch)
    ideas_home.mkdir()
    conn = store.connect()
    try:
        telegram_in.allow(conn, 22)
        conn.execute(
            "INSERT INTO kv (key, value) VALUES ('enabled', 'on')"
        )
        before_allow = conn.execute(
            "SELECT value FROM kv WHERE key = 'telegram_allow'"
        ).fetchone()[0]
    finally:
        conn.close()

    wrote = []

    def refuse(*_args, **_kwargs):
        wrote.append("write")

    monkeypatch.setattr(telegram_in, "allow", refuse)
    monkeypatch.setattr(worker, "turn_on", refuse)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(IdeaInboxScreen())
        await _until(pilot, lambda: isinstance(app.screen, IdeaInboxScreen), "inbox shown")
        screen = app.screen
        await _until(
            pilot,
            lambda: "Keeping it" in str(screen.query_one("#ib-bot").renderable),
            "bot kept",
        )
        text = _visible(screen)
        assert "Already allowed: Sam Q (private)  (22)" in text
        assert "Inbox already on." in text
        assert "Family" not in text and "-100" not in text
        assert TOKEN not in text
        assert screen.query_one("#ib-allow", tui.Button).disabled
        assert screen.query_one("#ib-on", tui.Button).disabled
        assert not screen.query_one("#ib-telegram", tui.Button).display
        screen.query_one("#ib-allow", tui.Button).press()
        screen.query_one("#ib-on", tui.Button).press()
        await pilot.pause()
        assert wrote == []

    conn = store.connect()
    try:
        assert conn.execute(
            "SELECT value FROM kv WHERE key = 'telegram_allow'"
        ).fetchone()[0] == before_allow
        assert conn.execute(
            "SELECT value FROM kv WHERE key = 'enabled'"
        ).fetchone()[0] == "on"
    finally:
        conn.close()


async def test_no_token_opens_telegram_setup_and_saves_nothing(
    tmp_path, ideas_home, monkeypatch
):
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: None)
    monkeypatch.setattr(telegram, "known_chats", lambda: {-100: "Family (group)"})

    def refuse(*_args, **_kwargs):
        raise AssertionError("inbox setup saved without a bot")

    monkeypatch.setattr(telegram_in, "allow", refuse)
    monkeypatch.setattr(worker, "turn_on", refuse)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(IdeaInboxScreen())
        await _until(pilot, lambda: isinstance(app.screen, IdeaInboxScreen), "inbox shown")
        screen = app.screen
        assert "No bot token yet" in _visible(screen)
        assert "Family" not in _visible(screen)
        assert screen.query_one("#ib-allow", tui.Button).disabled
        assert screen.query_one("#ib-on", tui.Button).disabled
        assert not (ideas_home / "ideas.sqlite3").exists()
        screen.query_one("#ib-telegram", tui.Button).press()
        await _until(pilot, lambda: isinstance(app.screen, TelegramSetupScreen), "telegram setup")
        assert not (ideas_home / "ideas.sqlite3").exists()


async def test_a_rejected_token_is_not_shown_and_saves_nothing(
    tmp_path, ideas_home, monkeypatch
):
    _known(monkeypatch, {11: "Anish V (private)"})

    def reject(token, *, http=None, sleep=None):
        raise telegram.TelegramError(f"rejected {token}")

    monkeypatch.setattr(telegram, "check_token", reject)

    def refuse(*_args, **_kwargs):
        raise AssertionError("inbox setup saved after a rejected token")

    monkeypatch.setattr(telegram_in, "allow", refuse)
    monkeypatch.setattr(worker, "turn_on", refuse)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(IdeaInboxScreen())
        await _until(pilot, lambda: isinstance(app.screen, IdeaInboxScreen), "inbox shown")
        screen = app.screen
        await _until(
            pilot,
            lambda: "rejected" in str(screen.query_one("#ib-bot").renderable),
            "rejection shown",
        )
        assert TOKEN not in _visible(screen)
        assert screen.query_one("#ib-allow", tui.Button).disabled
        assert screen.query_one("#ib-on", tui.Button).disabled
        await pilot.pause()
    assert not (ideas_home / "ideas.sqlite3").exists()
