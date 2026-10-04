import os
import pytest
from textual import events

from whyline.console import relay_ops, tui

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.setattr(relay_ops, "delivery_for", lambda root, agent, kind: "path")
    return tmp_path


async def _chat(app, pilot):
    app.session.mode = "chat"
    app.session.agent = "claude"
    app._sync_mode_indicator()
    await pilot.pause()


async def test_dropping_two_files_asks_then_attaches(repo, tmp_path_factory):
    folder = tmp_path_factory.mktemp("drop")
    (folder / "My Shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (folder / "PRD.pdf").write_bytes(b"%PDF")
    shot = folder / 'My Shot.png'
    dropped = f'"{shot}"' if os.name == "nt" else str(shot).replace(' ', chr(92) + ' ')
    text = f"{dropped} {folder / 'PRD.pdf'}"
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot)
        app.query_one("#prompt", tui.Input).post_message(events.Paste(text))
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        for _ in range(100):
            if len(app._pending.items) == 2:
                break
            await pilot.pause(0.05)
        assert [a.name for a in app._pending.items] == ["My-Shot.png", "PRD.pdf"]
        assert app.query_one("#prompt", tui.Input).value == ""


async def test_keep_as_text_inserts_the_paste_unchanged(repo, tmp_path_factory):
    shot = tmp_path_factory.mktemp("drop") / "a.png"
    shot.write_bytes(b"\x89PNG")
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot)
        app.query_one("#prompt", tui.Input).post_message(events.Paste(str(shot)))
        await pilot.pause()
        await pilot.click("#cancel")
        await pilot.pause()
        assert app.query_one("#prompt", tui.Input).value == str(shot)
        assert app._pending.items == []


async def test_ordinary_text_is_never_offered_as_files(repo, tmp_path_factory):
    shot = tmp_path_factory.mktemp("drop") / "a.png"
    shot.write_bytes(b"\x89PNG")
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot)
        app.query_one("#prompt", tui.Input).post_message(events.Paste(f"look at {shot} please"))
        await pilot.pause()
        assert not isinstance(app.screen, tui.ConfirmScreen)
        assert app.query_one("#prompt", tui.Input).value == f"look at {shot} please"


async def test_drop_in_command_mode_inserts_unchanged(repo, tmp_path_factory):
    shot = tmp_path_factory.mktemp("drop") / "a.png"
    shot.write_bytes(b"\x89PNG")
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        app.session.mode = "command"
        app._sync_mode_indicator()
        await pilot.pause()
        app.query_one("#prompt", tui.Input).post_message(events.Paste(str(shot)))
        await pilot.pause()
        assert not isinstance(app.screen, tui.ConfirmScreen)
        assert app.query_one("#prompt", tui.Input).value == str(shot)
        assert app._pending.items == []


async def test_drop_staging_error_renders_error_and_keeps_earlier_staged(repo, tmp_path_factory, monkeypatch):
    folder = tmp_path_factory.mktemp("drop")
    f1 = folder / "first.png"
    f1.write_bytes(b"\x89PNG")
    f2 = folder / "second.png"
    f2.write_bytes(b"\x89PNG")
    text = f"{f1} {f2}"

    from whyline.console import attachments as att
    orig_stage = att.stage

    def fail_second(root, path, **kwargs):
        if path.name == "second.png":
            raise att.AttachmentError("second.png failed to stage")
        return orig_stage(root, path, **kwargs)

    monkeypatch.setattr(att, "stage", fail_second)

    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot)
        app.query_one("#prompt", tui.Input).post_message(events.Paste(text))
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        for _ in range(100):
            lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
            if any("second.png failed to stage" in l for l in lines):
                break
            await pilot.pause(0.05)
        assert len(app._pending.items) == 1
        assert app._pending.items[0].name == "first.png"
        assert app.query_one("#tray").display


async def test_drop_focus_is_restored_to_prompt(repo, tmp_path_factory):
    shot = tmp_path_factory.mktemp("drop") / "a.png"
    shot.write_bytes(b"\x89PNG")
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _chat(app, pilot)
        app.query_one("#prompt", tui.Input).post_message(events.Paste(str(shot)))
        await pilot.pause()
        await pilot.click("#confirm")
        for _ in range(100):
            if app._pending.items:
                break
            await pilot.pause(0.05)
        assert app.focused == app.query_one("#prompt")

