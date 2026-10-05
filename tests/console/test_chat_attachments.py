import pytest

from whyline.console import adapters, attachments as att, mac_input, relay_ops, tui
from whyline.console.attachments_ui import AttachMenuScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


@pytest.fixture
def repo(tmp_path, monkeypatch):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.setattr(mac_input, "available", lambda: True)
    monkeypatch.setattr(relay_ops, "antigravity_state", lambda root: "trusted")
    monkeypatch.setattr(relay_ops, "delivery_for",
                        lambda root, agent, kind: "path-unverified" if (agent, kind) == ("grok", "image") else "native" if agent == "codex" and kind == "image" else "path")
    return tmp_path


def _lines(app):
    return [str(line) for line in app._main("#transcript", tui.RichLog).lines]


async def _chat(app, pilot, agent="codex"):
    app.session.mode = "chat"
    app.session.agent = agent
    app._sync_mode_indicator()
    await pilot.pause()


async def _open_attach_menu(app, pilot):
    app._main("#attach", tui.Button).press()  # by widget, not screen position
    for _ in range(100):  # slow CI runners need more than one frame
        if isinstance(app.screen, AttachMenuScreen):
            return
        await pilot.pause(0.05)
    raise AssertionError("the Attach menu never opened")


async def _attach_picked(app, pilot, paths, monkeypatch):
    monkeypatch.setattr(mac_input, "pick_files", lambda run=None: paths)
    await _open_attach_menu(app, pilot)
    app.screen.query_one("#attach-pick", tui.Button).press()
    for _ in range(100):
        if app._pending.items:
            break
        await pilot.pause(0.05)


async def test_picked_files_show_in_the_tray_with_status(repo, monkeypatch, tmp_path_factory):
    shot = tmp_path_factory.mktemp("in") / "shot.png"
    shot.write_bytes(PNG)
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot)
        await _attach_picked(app, pilot, [shot], monkeypatch)
        assert app.query_one("#tray").display
        assert "shot.png" in app._tray_text() and "✓ codex sees it" in app._tray_text()
        app.session.agent = "grok"
        app._sync_mode_indicator()
        await pilot.pause()
        assert "⚠ grok gets the path only" in app._tray_text()


async def test_send_with_a_warning_asks_once_then_sends_with_attachments(repo, monkeypatch, tmp_path_factory):
    shot = tmp_path_factory.mktemp("in") / "shot.png"
    shot.write_bytes(PNG)
    sent = []
    monkeypatch.setattr(adapters, "run_chat_turn",
                        lambda root, agent, prompt, attachments=(), **kw: sent.append((prompt, list(attachments)))
                        or tui.SessionEvent(kind="output", text="[grok] ok"))
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot, agent="grok")
        await _attach_picked(app, pilot, [shot], monkeypatch)
        app.query_one("#prompt", tui.Input).value = "why is this off?"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        app.screen.query_one("#confirm", tui.Button).press()  # by widget: no click geometry on slow runners
        await pilot.pause()
        for _ in range(100):
            if sent and not app._pending.items:
                break
            await pilot.pause(0.05)
        assert sent[0][0] == "why is this off?" and sent[0][1][0].name == "shot.png"
        assert any("📎 shot.png" in line for line in _lines(app))
        assert not app.query_one("#tray").display


async def test_a_launch_failure_keeps_the_attachments(repo, monkeypatch, tmp_path_factory):
    shot = tmp_path_factory.mktemp("in") / "shot.png"
    shot.write_bytes(PNG)

    def boom(*a, **k):
        raise RuntimeError("could not start codex")

    monkeypatch.setattr(adapters, "run_chat_turn", boom)
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot)
        await _attach_picked(app, pilot, [shot], monkeypatch)
        app.query_one("#prompt", tui.Input).value = "look"
        await pilot.press("enter")
        for _ in range(100):
            if any("could not start codex" in l for l in _lines(app)):
                break
            await pilot.pause(0.05)
        assert len(app._pending.items) == 1


async def test_paste_screenshot_without_an_image_says_so(repo, monkeypatch):
    monkeypatch.setattr(mac_input, "paste_image", lambda target, run=None: False)
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot)
        await _open_attach_menu(app, pilot)
        app.screen.query_one("#attach-paste", tui.Button).press()
        for _ in range(100):
            if any("The clipboard has no image" in l for l in _lines(app)):
                break
            await pilot.pause(0.05)
        assert any("Cmd+Ctrl+Shift+4" in l for l in _lines(app))


async def test_attach_is_only_enabled_in_chat(repo):
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(80, 24)) as pilot:
        assert app.query_one("#attach", tui.Button).disabled
        await _chat(app, pilot)
        assert not app.query_one("#attach", tui.Button).disabled
        assert app.query_one("#attach", tui.Button).region.right <= 80


async def test_adapter_caught_launch_failure_keeps_the_attachments(repo, monkeypatch, tmp_path_factory):
    shot = tmp_path_factory.mktemp("in") / "shot.png"
    shot.write_bytes(PNG)

    from whyline_relay import agents, chat

    def unavailable(*a, **k):
        raise chat.AgentUnavailable("codex has no command configured for chat in this repo")

    monkeypatch.setattr(chat, "run_turn", unavailable)
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot)
        await _attach_picked(app, pilot, [shot], monkeypatch)
        app.query_one("#prompt", tui.Input).value = "look"
        await pilot.press("enter")
        for _ in range(100):
            if any("no command configured" in l for l in _lines(app)):
                break
            await pilot.pause(0.05)
        assert len(app._pending.items) == 1
        assert app.query_one("#tray").display


async def test_send_with_secret_warning_asks_before_sending(repo, monkeypatch, tmp_path_factory):
    env_file = tmp_path_factory.mktemp("secrets") / ".env.local"
    env_file.write_text("API_KEY=secret_val")
    sent = []
    monkeypatch.setattr(adapters, "run_chat_turn",
                        lambda root, agent, prompt, attachments=(), **kw: sent.append((prompt, list(attachments)))
                        or tui.SessionEvent(kind="output", text="[codex] ok"))
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot, agent="codex")
        await _attach_picked(app, pilot, [env_file], monkeypatch)
        assert app._pending.items[0].warning == "looks like a secret"
        name = app._pending.items[0].name
        app.query_one("#prompt", tui.Input).value = "use secret"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        label_text = str(app.screen.query_one(tui.Label).renderable)
        assert f"{name} looks like a secret" in label_text
        app.screen.query_one("#confirm", tui.Button).press()  # by widget: no click geometry on slow runners
        await pilot.pause()
        for _ in range(100):
            if sent and not app._pending.items:
                break
            await pilot.pause(0.05)
        assert sent[0][0] == "use secret" and sent[0][1][0].name == name
        assert any(f"📎 {name}" in line for line in _lines(app))
        assert not app.query_one("#tray").display


async def test_repo_switch_clears_pending_attachments(repo, monkeypatch, tmp_path_factory):
    import subprocess
    repo2 = tmp_path_factory.mktemp("repo2")
    subprocess.run(["git", "init", "-q"], cwd=repo2, check=True)

    shot = tmp_path_factory.mktemp("in") / "shot.png"
    shot.write_bytes(PNG)
    sent = []
    monkeypatch.setattr(adapters, "run_chat_turn",
                        lambda root, agent, prompt, attachments=(), **kw: sent.append((prompt, list(attachments)))
                        or tui.SessionEvent(kind="output", text="ok"))

    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot)
        await _attach_picked(app, pilot, [shot], monkeypatch)
        assert len(app._pending.items) == 1
        assert app.query_one("#tray").display

        # Switch repo via /repo command
        app.query_one("#prompt", tui.Input).value = f"/repo {repo2}"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        app.screen.query_one("#confirm", tui.Button).press()  # by widget: no click geometry on slow runners
        await pilot.pause()
        await pilot.pause()

        # In new repo, pending attachments must be cleared and tray hidden
        assert len(app._pending.items) == 0
        assert not app.query_one("#tray").display
        assert app.session.root == repo2

        # Sending in new repo must not dispatch attachments from old repo
        app.query_one("#prompt", tui.Input).value = "hello new repo"
        await pilot.press("enter")
        for _ in range(100):
            if sent:
                break
            await pilot.pause(0.05)
        assert sent[0][0] == "hello new repo"
        assert sent[0][1] == []


async def test_agent_missing_launch_failure_keeps_the_attachments(repo, monkeypatch, tmp_path_factory):
    shot = tmp_path_factory.mktemp("in") / "shot.png"
    shot.write_bytes(PNG)

    from whyline_relay import agents, chat

    def missing(*a, **k):
        raise agents.AgentMissing("codex is not installed or not on PATH")

    monkeypatch.setattr(chat, "run_turn", missing)
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot)
        await _attach_picked(app, pilot, [shot], monkeypatch)
        app.query_one("#prompt", tui.Input).value = "look"
        await pilot.press("enter")
        for _ in range(100):
            if any("not installed or not on PATH" in l for l in _lines(app)):
                break
            await pilot.pause(0.05)
        assert len(app._pending.items) == 1
        assert app.query_one("#tray").display


async def test_repo_switch_cancelled_keeps_pending_attachments(repo, monkeypatch, tmp_path_factory):
    import subprocess
    repo2 = tmp_path_factory.mktemp("repo2")
    subprocess.run(["git", "init", "-q"], cwd=repo2, check=True)

    shot = tmp_path_factory.mktemp("in") / "shot.png"
    shot.write_bytes(PNG)

    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot)
        await _attach_picked(app, pilot, [shot], monkeypatch)
        assert len(app._pending.items) == 1

        # Initiate switch repo via /repo command
        app.query_one("#prompt", tui.Input).value = f"/repo {repo2}"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        app.screen.query_one("#cancel", tui.Button).press()
        await pilot.pause()
        await pilot.pause()

        # Switch cancelled: pending attachments must remain
        assert len(app._pending.items) == 1
        assert app.query_one("#tray").display
        assert app.session.root == repo
