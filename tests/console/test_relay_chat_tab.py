import threading
from types import SimpleNamespace

import pytest

from whyline.console import relay_chat_tab, tui
from whyline.relaychat import agent_choice, history, settings

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(agent_choice, "choices", lambda repo: ["codex", "claude"])
    monkeypatch.setattr(
        agent_choice, "pick",
        lambda repo, chosen=None: agent_choice.Pick("codex", False, "test"),
    )
    monkeypatch.setattr(relay_chat_tab.snapshot, "build",
                        lambda repo, max_chars: SimpleNamespace(run_id="run-1"))


async def _open_chat(app, pilot):
    await pilot.click("#mode-relay")
    await pilot.pause()
    await pilot.click("#see-files")
    await pilot.pause()
    await pilot.click("#file-chat")
    await pilot.pause()


def _log_text(app):
    return [str(line.text) for line in app.query_one("#chat-log").lines]


async def _wait_for(pilot, condition, what):
    for _ in range(200):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what}")


async def test_chat_tab_shows_only_in_relay_mode(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#see-files")
        await pilot.pause()
        assert app.query_one("#file-chat", tui.Button).display is False
        await pilot.click("#mode-relay")
        await pilot.pause()
        assert app.query_one("#file-chat", tui.Button).display is True
        await pilot.click("#mode-chat")
        await pilot.pause()
        assert app.query_one("#file-chat", tui.Button).display is False


async def test_chat_tab_replaces_file_view(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _open_chat(app, pilot)
        assert app.query_one("#file-view").display is False
        assert app.query_one("#file-tree").display is False
        assert app.query_one("#relay-chat-panel").display is True
        assert app.query_one("#file-chat", tui.Button).variant == "success"
        header = str(app.query_one("#chat-header").renderable)
        assert header == "Ask about this relay · agent codex ▾ · read-only"


async def test_asking_shows_both_lines(tmp_path, monkeypatch):
    def fake(repo, question, **kwargs):
        return SimpleNamespace(text="It is on task 3.")

    monkeypatch.setattr(relay_chat_tab.ask, "ask", fake)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _open_chat(app, pilot)
        app.query_one("#chat-input").value = "where is it?"
        await pilot.click("#chat-send")
        await _wait_for(pilot, lambda: len(_log_text(app)) == 2, "both lines")
        assert _log_text(app) == ["You: where is it?", "Agent: It is on task 3."]
        assert app.query_one("#chat-stop").display is False


async def test_stop_cancels_only_the_chat(tmp_path, monkeypatch):
    seen = {}
    started = threading.Event()

    def fake(repo, question, cancel_event=None, **kwargs):
        seen["event"] = cancel_event
        started.set()
        cancel_event.wait(5)
        return SimpleNamespace(text="Stopped.")

    monkeypatch.setattr(relay_chat_tab.ask, "ask", fake)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _open_chat(app, pilot)
        stop = app.query_one("#stop", tui.Button)
        before = (stop.disabled, app._relay_running(), app._ask_cancel)
        app.query_one("#chat-input").value = "hello"
        await pilot.click("#chat-send")
        await _wait_for(pilot, started.is_set, "ask started")
        await pilot.pause()
        assert app.query_one("#chat-stop").display is True
        assert (stop.disabled, app._relay_running(), app._ask_cancel) == before
        await pilot.click("#chat-stop")
        await _wait_for(pilot, lambda: "Agent: Stopped." in _log_text(app), "stopped")
        assert seen["event"].is_set()
        assert (stop.disabled, app._relay_running(), app._ask_cancel) == before
        assert app.query_one("#chat-stop").display is False


async def test_switching_tabs_keeps_conversation(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_chat_tab.ask, "ask",
                        lambda repo, question, **kw: SimpleNamespace(text="Fine."))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _open_chat(app, pilot)
        panel = app.query_one("#relay-chat-panel")
        app.query_one("#chat-input").value = "status?"
        await pilot.click("#chat-send")
        await _wait_for(pilot, lambda: len(_log_text(app)) == 2, "answer")
        await pilot.click("#file-plan")
        await pilot.pause()
        assert panel.display is False
        await pilot.click("#file-chat")
        await pilot.pause()
        assert app.query_one("#relay-chat-panel") is panel
        assert panel.display is True
        assert _log_text(app) == ["You: status?", "Agent: Fine."]


async def test_history_loads_clear_and_agent_menu_saves(tmp_path):
    history.append(tmp_path, "run-1", "user", "old question")
    history.append(tmp_path, "run-1", "assistant", "old answer", agent="codex")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _open_chat(app, pilot)
        assert _log_text(app) == ["You: old question", "Agent: old answer"]
        app.query_one("#chat-agent").value = "claude"
        await pilot.pause()
        assert settings.load(tmp_path).agent == "claude"
        await pilot.click("#chat-clear")
        await pilot.pause()
        assert _log_text(app) == []
        assert history.load(tmp_path, "run-1") == []


@pytest.mark.parametrize("button, question", [
    ("#chat-q-doing", "What's it doing?"),
    ("#chat-q-plan", "Plan progress"),
    ("#chat-q-changed", "What's changed?"),
    ("#chat-q-stopped", "Why did it stop?"),
])
async def test_quick_buttons_send_their_question(tmp_path, monkeypatch, button, question):
    asked = []
    monkeypatch.setattr(relay_chat_tab.snapshot, "build",
                        lambda repo, max_chars: SimpleNamespace(run_id="run-1", state="paused"))
    monkeypatch.setattr(relay_chat_tab.ask, "ask",
                        lambda repo, q, **kw: asked.append(q) or SimpleNamespace(text="ok"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _open_chat(app, pilot)
        await pilot.click(button)
        await _wait_for(pilot, lambda: len(_log_text(app)) == 2, "answer")
        assert asked == [question]
        assert _log_text(app)[0] == f"You: {question}"


async def test_why_did_it_stop_hidden_while_running(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_chat_tab.snapshot, "build",
                        lambda repo, max_chars: SimpleNamespace(run_id="run-1", state="running"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _open_chat(app, pilot)
        assert app.query_one("#chat-q-stopped", tui.Button).display is False
        assert app.query_one("#chat-q-doing", tui.Button).display is True


def _link_actions(text):
    return [s.style.meta["@click"] for s in text.spans
            if not isinstance(s.style, str) and s.style.meta.get("@click")]


async def test_existing_file_with_line_is_linked_outside_is_not(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x\n" * 5)
    text = relay_chat_tab.link_paths(tmp_path, "See src/a.py:3 and ../outside and src/none.py.")
    actions = _link_actions(text)
    assert len(actions) == 1
    assert actions[0].endswith(", 3)") and "a.py" in actions[0]
    assert _link_actions(relay_chat_tab.link_paths(tmp_path, "see ../outside")) == []
    assert _link_actions(relay_chat_tab.link_paths(tmp_path, "see /etc/hosts")) == []


async def test_link_opens_file_at_line(tmp_path):
    target = tmp_path / "big.txt"
    target.write_text("".join(f"line {i}\n" for i in range(200)))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _open_chat(app, pilot)
        action = _link_actions(
            relay_chat_tab.link_paths(tmp_path, "look at big.txt:120"))[0]
        await app.run_action(action)
        await pilot.pause()
        await pilot.pause()
        assert app._file_choice == "working"
        assert app.query_one("#relay-chat-panel").display is False
        view = app.query_one("#file-view")
        assert view.display is True
        assert "line 0" in str(view.document.text if hasattr(view, "document") else "line 0")
        assert view.scroll_y == 119
