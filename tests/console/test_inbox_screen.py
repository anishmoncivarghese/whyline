"""Inbox settings in Agents mode: saved values, and the CLI's own writes."""

import json
from pathlib import Path

import pytest

from whyline.agents import launchd, telegram
from whyline.console import tui
from whyline.console.chain_editor import OrderedChain
from whyline.console.inbox_screen import IdeaInboxScreen
from whyline.ideas import documents, store, telegram_in
from whyline.ideas import cli as idea_cli

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


@pytest.fixture(autouse=True)
def _fakes(monkeypatch, ideas_home):
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: None)
    monkeypatch.setattr(telegram, "known_chats", lambda: {})
    monkeypatch.setattr(telegram, "check_token", lambda token, **_kwargs: "@InboxBot")
    monkeypatch.setattr(telegram, "webhook_info", lambda token, **_kwargs: {"url": ""})
    monkeypatch.setattr(launchd, "supported", lambda: True)
    monkeypatch.setattr(launchd, "status", lambda: launchd.Status(False, None, ""))
    monkeypatch.setattr(launchd, "turn_on", lambda: Path("/tmp/whyline-agent.plist"))
    monkeypatch.setattr(
        documents, "probe_pdf", lambda run=None: documents.PdfResult("appkit")
    )
    return ideas_home


def _text(value) -> str:
    if value is None:
        return ""
    return value.plain if hasattr(value, "plain") else str(value)


def _plain(widget) -> str:
    label = getattr(widget, "label", None)
    text = _text(label)
    if text:
        return text
    return _text(getattr(widget, "renderable", None))


def _visible(screen) -> str:
    return "\n".join(_plain(widget) for widget in screen.query("*") if _plain(widget))


def _rows():
    conn = store.connect()
    try:
        return conn.execute("SELECT key, value FROM kv ORDER BY key").fetchall()
    finally:
        conn.close()


def _seed(values: dict[str, str]) -> None:
    conn = store.connect()
    try:
        for key, value in values.items():
            conn.execute(
                """
                INSERT INTO kv (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
    finally:
        conn.close()


async def _until(pilot, condition, what):
    for _ in range(400):
        await pilot.pause(0.05)
        if condition():
            return
    raise AssertionError(f"never happened: {what}")


def _saved_screen_chats(monkeypatch):
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: TOKEN)
    monkeypatch.setattr(
        telegram,
        "known_chats",
        lambda: {
            11: "Anish V (private)",
            22: "Sam Q (private)",
            -100: "Family (group)",
        },
    )


async def _open(pilot, app):
    app.push_screen(IdeaInboxScreen())
    await _until(pilot, lambda: isinstance(app.screen, IdeaInboxScreen), "inbox shown")
    return app.screen


async def test_opening_shows_the_saved_values(ideas_home, monkeypatch):
    _saved_screen_chats(monkeypatch)
    _seed({
        "telegram_allow": "[11]",
        "default_agents": json.dumps(["grok", "claude"]),
        "assistant": "codex",
        "assistant_backup": "grok",
        "doc_formats": "pdf",
        "enabled": "off",
        "telegram_last_error": json.dumps({
            "at": "2026-10-20T15:04:00Z",
            "code": 409,
            "message": "another program is reading this bot's messages, or it has a webhook",
        }),
    })
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        await _until(
            pilot,
            lambda: "@InboxBot" in _plain(screen.query_one("#ib-bot")),
            "bot name",
        )
        assert screen.query_one("#ib-chat-11", tui.Checkbox).value is True
        assert screen.query_one("#ib-chat-22", tui.Checkbox).value is False
        assert "Family" not in _visible(screen) and "-100" not in _visible(screen)
        assert TOKEN not in _visible(screen)
        assert screen.query_one("#ib-agents", OrderedChain).order() == ["grok", "claude"]
        assert screen.query_one("#ib-assistant", tui.Select).value == "codex"
        assert screen.query_one("#ib-backup", tui.Select).value == "grok"
        assert screen.query_one("#ib-documents", tui.Select).value == "pdf"
        assert screen.query_one("#ib-service", tui.Select).value == "off"
        status = _plain(screen.query_one("#ib-status"))
        assert "Inbox off." in status
        assert "Last Telegram error at 2026-10-20T15:04:00Z:" in status
        assert "another program is reading this bot's messages" in status
        assert not screen.query_one("#ib-telegram", tui.Button).display


async def test_toggling_a_chat_saves_only_that_chat(ideas_home, monkeypatch):
    _saved_screen_chats(monkeypatch)
    _seed({"telegram_allow": "[11, 22]"})
    allowed, denied = [], []
    real_allow, real_deny = telegram_in.allow, telegram_in.deny

    def spy_allow(conn, chat_id):
        allowed.append(chat_id)
        return real_allow(conn, chat_id)

    def spy_deny(conn, chat_id):
        denied.append(chat_id)
        return real_deny(conn, chat_id)

    monkeypatch.setattr(telegram_in, "allow", spy_allow)
    monkeypatch.setattr(telegram_in, "deny", spy_deny)
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        screen.query_one("#ib-chat-22", tui.Checkbox).value = False
        await pilot.click("#ib-save")
        await pilot.pause()
    assert allowed == []
    assert denied == [22]
    conn = store.connect()
    try:
        assert telegram_in.allowed_chats(conn) == [11]
    finally:
        conn.close()


async def test_reordering_agents_stores_the_new_default(ideas_home, monkeypatch):
    _seed({"default_agents": json.dumps(["claude", "grok"])})
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        assert screen.query_one("#ib-agents", OrderedChain).order() == ["claude", "grok"]
        await _until(pilot, lambda: screen.query("#chain-down-claude"), "down button")
        screen.query_one("#chain-down-claude", tui.Button).press()
        await pilot.pause()
        assert screen.query_one("#ib-agents", OrderedChain).order() == ["grok", "claude"]
        await pilot.click("#ib-save")
        await pilot.pause()
    conn = store.connect()
    try:
        raw = conn.execute(
            "SELECT value FROM kv WHERE key = 'default_agents'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert json.loads(raw) == ["grok", "claude"]


async def test_assistant_equal_to_backup_is_refused(ideas_home, monkeypatch):
    _seed({"assistant": "grok", "assistant_backup": "codex"})
    before = _rows()

    def refuse(*_args, **_kwargs):
        raise AssertionError("save wrote after a refused assistant")

    monkeypatch.setattr(telegram_in, "allow", refuse)
    monkeypatch.setattr(telegram_in, "deny", refuse)
    monkeypatch.setattr(idea_cli, "cmd_agents", refuse)
    monkeypatch.setattr(idea_cli, "cmd_documents", refuse)
    monkeypatch.setattr(idea_cli, "cmd_service", refuse)
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        screen.query_one("#ib-assistant", tui.Select).value = "claude"
        screen.query_one("#ib-backup", tui.Select).value = "claude"
        await pilot.click("#ib-save")
        await pilot.pause()
        assert "backup is the same agent" in _plain(screen.query_one("#ib-message"))
        assert isinstance(app.screen, IdeaInboxScreen)
    assert _rows() == before


async def test_cancel_after_changes_writes_nothing(ideas_home, monkeypatch):
    _saved_screen_chats(monkeypatch)
    _seed({
        "telegram_allow": "[11]",
        "default_agents": json.dumps(["claude"]),
        "assistant": "codex",
        "doc_formats": "pdf",
        "enabled": "off",
    })
    before = _rows()

    def refuse(*_args, **_kwargs):
        raise AssertionError("cancel wrote")

    monkeypatch.setattr(telegram_in, "allow", refuse)
    monkeypatch.setattr(telegram_in, "deny", refuse)
    monkeypatch.setattr(idea_cli, "_service_on", refuse)
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        screen.query_one("#ib-chat-22", tui.Checkbox).value = True
        screen.query_one("#ib-documents", tui.Select).value = "word"
        screen.query_one("#ib-service", tui.Select).value = "on"
        await _until(pilot, lambda: screen.query("#chain-down-claude"), "down button")
        screen.query_one("#chain-down-claude", tui.Button).press()
        await pilot.click("#ib-cancel")
        await _until(pilot, lambda: not isinstance(app.screen, IdeaInboxScreen), "closed")
    assert _rows() == before


async def test_service_on_uses_the_idea_service_path(ideas_home, monkeypatch):
    called = []
    real = idea_cli._service_on

    def spy():
        called.append("on")
        return real()

    monkeypatch.setattr(idea_cli, "_service_on", spy)
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        screen.query_one("#ib-service", tui.Select).value = "on"
        await pilot.click("#ib-save")
        await pilot.pause()
    assert called == ["on"]
    conn = store.connect()
    try:
        assert conn.execute(
            "SELECT value FROM kv WHERE key = 'enabled'"
        ).fetchone()[0] == "on"
    finally:
        conn.close()


async def test_check_shows_a_failing_webhook_line_without_markup(ideas_home, monkeypatch):
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: TOKEN)
    monkeypatch.setattr(
        telegram, "check_token", lambda token, **_kwargs: "[red]InboxBot[/]"
    )
    monkeypatch.setattr(
        telegram,
        "webhook_info",
        lambda token, **_kwargs: {"url": "https://hooks.example/bot"},
    )
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        await pilot.click("#ib-check")
        await pilot.pause()
        text = _plain(screen.query_one("#ib-checks"))
    assert "fail" in text and "webhook:" in text
    assert "this bot has a webhook" in text
    assert "[red]InboxBot[/]" in text
    assert TOKEN not in text


async def test_antigravity_is_listed_disabled(ideas_home):
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        box = screen.query_one("#ib-blocked-antigravity", tui.Checkbox)
        assert box.disabled
        assert "antigravity" in _plain(box)
        assert "not cleared for unattended runs" in _plain(box)
        assert "antigravity" not in screen.query_one("#ib-agents", OrderedChain).order()
        with pytest.raises(tui.NoMatches):
            screen.query_one("#chain-check-antigravity")


async def test_save_and_cancel_fit_on_80x24(ideas_home, monkeypatch):
    chats = {i: f"Person {i} (private)" for i in range(1, 31)}
    chats[-100] = "Family (group)"
    monkeypatch.setattr(telegram, "known_chats", lambda: chats)
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        for button_id in ("#ib-check", "#ib-save", "#ib-cancel"):
            region = screen.query_one(button_id).region
            assert region.height > 0 and region.bottom <= 24


async def test_open_then_save_leaves_every_key_unchanged(ideas_home, monkeypatch):
    _saved_screen_chats(monkeypatch)
    _seed({
        "telegram_allow": "[11]",
        "default_agents": json.dumps(["grok", "claude"]),
        "assistant": "codex",
        "assistant_backup": "grok",
        "doc_formats": "pdf",
        "enabled": "off",
        "note": "leave me",
    })
    before = _rows()
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        await _until(
            pilot,
            lambda: "@InboxBot" in _plain(screen.query_one("#ib-bot")),
            "bot name",
        )
        await pilot.click("#ib-save")
        await pilot.pause()
        assert _plain(screen.query_one("#ib-checks"))
    assert _rows() == before


async def test_agents_mode_inbox_button_opens_the_screen(tmp_path, ideas_home):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#mode-agents")
        await pilot.pause()
        assert "agents-inbox" in tui._MODE_BUTTONS["agents"]
        button = app.query_one("#agents-inbox")
        assert str(button.label) == "Inbox"
        assert button.display
        await pilot.click("#agents-inbox")
        await _until(pilot, lambda: isinstance(app.screen, IdeaInboxScreen), "inbox shown")
        assert "No bot yet" in _plain(app.screen.query_one("#ib-bot"))
        assert not (ideas_home / "ideas.sqlite3").exists()


async def test_a_rejected_token_is_not_shown(ideas_home, monkeypatch):
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: TOKEN)

    def reject(token, **_kwargs):
        raise telegram.TelegramError(f"rejected {token}")

    monkeypatch.setattr(telegram, "check_token", reject)
    app = tui.WhylineConsoleApp(root=ideas_home.parent)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(pilot, app)
        await _until(
            pilot,
            lambda: "rejected" in _plain(screen.query_one("#ib-bot")),
            "rejection shown",
        )
        assert TOKEN not in _visible(screen)
        assert not (ideas_home / "ideas.sqlite3").exists()
