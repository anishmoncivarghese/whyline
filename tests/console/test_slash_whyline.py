"""Slash commands run whyline subcommands from any mode. Command mode is gone."""
import pytest

from whyline.console import adapters, repl, tui
from whyline.console.session import ConsoleSession, SessionEvent


def test_whyline_subcommands_come_from_the_parser():
    subs = repl.whyline_subcommands()
    assert "timeline" in subs and "note" in subs and subs["note"]


def test_bare_agents_stays_the_relay_chat_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        adapters, "run_whyline_command",
        lambda argv: (_ for _ in ()).throw(AssertionError("bare /agents must not run")),
    )
    assert repl.handle_slash_command(ConsoleSession(root=tmp_path), "/agents") is None


def test_agents_with_a_subcommand_runs(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(
        adapters, "run_whyline_command",
        lambda argv: ran.append(argv) or SessionEvent(kind="output", text="ok"),
    )
    event = repl.handle_slash_command(ConsoleSession(root=tmp_path), "/agents list")
    assert ran == [["agents", "list"]] and event.text == "ok"


def test_slash_runs_a_whyline_command(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(
        adapters, "run_whyline_command",
        lambda argv: ran.append(argv) or SessionEvent(kind="output", text="ok"),
    )
    session = ConsoleSession(root=tmp_path)
    assert session.mode == "chat"
    event = repl.handle_slash_command(session, "/timeline --limit 5")
    assert ran == [["timeline", "--limit", "5"]] and event.text == "ok"


def test_console_commands_win_over_whyline_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(
        adapters, "run_whyline_command",
        lambda argv: (_ for _ in ()).throw(AssertionError),
    )
    event = repl.handle_slash_command(ConsoleSession(root=tmp_path), "/status")
    assert event is not None  # the console's own /status


def test_route_command_explains(tmp_path):
    event = repl.handle_slash_command(ConsoleSession(root=tmp_path), "/route command")
    assert "Command mode is gone" in event.text and "/timeline" in event.text


def test_help_lists_whyline_commands(tmp_path):
    text = repl.handle_slash_command(ConsoleSession(root=tmp_path), "/help").text
    assert "whyline commands" in text and "/timeline" in text


def test_route_agents_switches_mode(tmp_path, monkeypatch):
    from whyline.agents import definitions as d
    from whyline.agents import service

    session = ConsoleSession(root=tmp_path, mode="relay")
    event = repl.handle_slash_command(session, "/route agents")
    assert event.text == "Mode is now agents."
    assert session.mode == "agents"

    defn = d.AgentDef(
        name="digest", kind="repo", path=tmp_path / "digest.toml", root=tmp_path,
        instructions="x", runner="claude",
    )
    row = service.Row(defn, "active", "succeeded", "", "", "weekdays at 07:00")
    monkeypatch.setattr(service, "rows", lambda root: [row])
    paused = []
    monkeypatch.setattr(service, "pause", lambda name, root: paused.append(name) or None)
    listed = repl.dispatch(session, "list")
    assert "digest (repo)" in listed.text and "weekdays at 07:00" in listed.text
    paused_event = repl.dispatch(session, "pause digest")
    assert paused == ["digest"] and "paused" in paused_event.text
    usage = repl.dispatch(session, "nope")
    assert usage.kind == "error" and usage.text.startswith("Usage:")


def test_a_stored_command_mode_is_chat(tmp_path):
    session = ConsoleSession(root=tmp_path, mode="command")
    assert session.mode == "chat"
    session.mode = "command"
    assert session.mode == "chat"


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_mode_buttons_are_chat_relay_and_agents_and_chat_is_the_default(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        ids = {button.id for button in app.query("#modes Button")}
        assert ids == {"mode-chat", "mode-relay", "mode-agents"}
        assert app.session.mode == "chat"
        await pilot.pause()


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_a_lone_slash_shows_the_hint_and_the_next_key_hides_it(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        hint = app.query_one("#slash-hint", tui.Static)
        assert hint.display is False
        await pilot.click("#prompt")
        await pilot.press("/")
        await pilot.pause()
        assert hint.display is True
        assert "/timeline" in str(hint.render())
        await pilot.press("t")
        await pilot.pause()
        assert hint.display is False
