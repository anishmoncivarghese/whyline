"""The context bar: agent, backup chain, model, repo, all-repos, and Save."""
import os
import subprocess
from pathlib import Path

import pytest

from whyline.console import tui

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

# claude and codex available, grok unavailable (and antigravity, so the
# selector never depends on which CLIs happen to be installed).
_STATUS = {
    "claude": {"available": True, "label": "pro", "hint": None},
    "codex": {"available": True, "label": "plus", "hint": None},
    "antigravity": {
        "available": False,
        "label": "not installed",
        "hint": "Install antigravity, then /model refresh",
    },
    "grok": {"available": False, "label": "not signed in", "hint": "Run /login grok"},
}


@pytest.fixture(autouse=True)
def stub_agent_status(monkeypatch):
    from whyline import account

    monkeypatch.setattr(account, "agent_status", lambda root: _STATUS)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """HOME points at tmp. Path.home() ignores HOME on Windows."""
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))

    def _home(*_args):
        return Path(os.environ["HOME"])

    monkeypatch.setattr(Path, "home", _home)
    return folder


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    (root / ".whyline").mkdir()
    return root


def _backup_closed(select) -> str:
    content = select.query_one("#label").renderable
    return content.plain if hasattr(content, "plain") else str(content)


def _lines(app):
    return [str(line) for line in app._main("#transcript", tui.RichLog).lines]


async def test_save_is_greyed_until_something_changes(tmp_path):
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        save = app.query_one("#cb-save", tui.Button)
        assert save.disabled
        app.query_one("#cb-model", tui.Input).value = "gpt-5.6"
        await pilot.pause()
        assert not save.disabled


async def test_save_sets_the_repo_default_and_optionally_global(tmp_path, home):
    from whyline import model

    root = _repo(tmp_path)
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-agent", tui.Select).value = "codex"
        app.query_one("#cb-model", tui.Input).value = "gpt-5.6"
        app.query_one("#cb-global", tui.Checkbox).value = True
        await pilot.click("#cb-save")
        await pilot.pause()
        assert app.session.agent == "codex" and app.query_one("#cb-save", tui.Button).disabled
    assert model.resolve(root) == ("codex", "gpt-5.6")
    assert model.load_global()["default_agent"] == "codex"


async def test_an_unavailable_agent_snaps_back_with_its_hint(tmp_path):
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-agent", tui.Select).value = "!grok"
        await pilot.pause()
        assert app.query_one("#cb-agent", tui.Select).value == "claude"
        assert any("Run /login grok" in line for line in _lines(app))


async def test_switching_repo_is_refused_while_a_job_runs_but_agent_saves(tmp_path, monkeypatch):
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        monkeypatch.setattr(app, "_relay_running", lambda: True)
        app.query_one("#cb-agent", tui.Select).value = "codex"
        app.query_one("#cb-model", tui.Input).value = "gpt-5"
        app.query_one("#cb-repo", tui.Input).value = str(tmp_path / "other")
        await pilot.click("#cb-save")
        await pilot.pause()
        assert app.session.agent == "codex" and app.session.root == tmp_path / "repo"
        assert any("Finish or stop the current job before switching repo" in line for line in _lines(app))


async def test_a_new_folder_is_set_up_after_one_confirmation(tmp_path, monkeypatch):
    from whyline.console import repo_setup

    ran = []
    monkeypatch.setattr(repo_setup, "setup", lambda insp, agents, progress: ran.append(insp.path) or insp.path)
    monkeypatch.setattr(
        tui, "switch_repo",
        lambda session, root: setattr(session, "root", root) or tui.SessionEvent(kind="output", text=f"Now in {root}"),
    )
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-model", tui.Input).value = "gpt-5"
        app.query_one("#cb-repo", tui.Input).value = str(tmp_path / "fresh")
        await pilot.click("#cb-save")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        assert "git init" in str(app.screen.query_one("Label").renderable)
        await pilot.click("#confirm")
        for _ in range(50):
            if ran:
                break
            await pilot.pause(0.05)
    assert ran == [(tmp_path / "fresh").resolve()]


async def test_the_bar_fits_80_columns(tmp_path):
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(80, 24)) as pilot:
        assert app.query_one("#cb-save").region.right <= 80


def _status_grok_unavailable() -> dict:
    return {
        "claude": {"available": True, "label": "pro", "hint": None},
        "codex": {"available": True, "label": "plus", "hint": None},
        "antigravity": {
            "available": False,
            "label": "not installed",
            "hint": "Install antigravity, then /model refresh",
        },
        "grok": {"available": False, "label": "not signed in", "hint": "Run /login grok"},
    }


def _option_map(select) -> dict:
    return {
        value: str(prompt)
        for prompt, value in select._options
        if value is not tui.Select.BLANK
    }


async def test_model_refresh_updates_an_agent_that_becomes_available(tmp_path, monkeypatch):
    """/model refresh rewrites !agent once it is available, and a mode sync does not."""
    from whyline import account, model

    status = _status_grok_unavailable()
    monkeypatch.setattr(account, "agent_status", lambda root: status)

    def refresh():
        status["grok"] = {"available": True, "label": "pro", "hint": None}
        return {}

    monkeypatch.setattr(account, "refresh", refresh)
    root = _repo(tmp_path)
    model.set_default_agent(root, "grok")
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        select = app.query_one("#cb-agent", tui.Select)
        assert select.value == "!grok"
        assert _option_map(select)["!grok"] == "grok · not signed in"
        app.query_one("#cb-model", tui.Input).value = "grok-4"
        app.query_one("#cb-global", tui.Checkbox).value = True
        await pilot.pause()
        app.query_one("#prompt", tui.Input).value = "/route chat"
        await pilot.click("#send")
        await pilot.pause()
        assert select.value == "!grok"
        assert app.query_one("#cb-model", tui.Input).value == "grok-4"
        assert app.query_one("#cb-global", tui.Checkbox).value is True
        assert not app.query_one("#cb-save", tui.Button).disabled

        # A second click during Send's highlight is ignored.
        await pilot.pause(0.3)
        app.query_one("#prompt", tui.Input).value = "/model refresh"
        await pilot.click("#send")
        await pilot.pause()
        options = _option_map(select)
        assert select.value == "grok"
        assert options["grok"] == "grok · pro"
        assert "!grok" not in options
        assert "!antigravity" in options
        assert app.query_one("#cb-model", tui.Input).value == "grok-4"
        assert app.query_one("#cb-global", tui.Checkbox).value is True
        assert not app.query_one("#cb-save", tui.Button).disabled

        await pilot.pause(0.3)
        app.query_one("#prompt", tui.Input).value = "/route chat"
        await pilot.click("#send")
        await pilot.pause()
        assert select.value == "grok"
        assert app.query_one("#cb-model", tui.Input).value == "grok-4"


async def test_login_updates_an_agent_that_becomes_available(tmp_path, monkeypatch):
    """A login rechecks status and updates the same Select, edits included."""
    import contextlib
    import shutil

    from whyline import account, model

    status = _status_grok_unavailable()
    monkeypatch.setattr(account, "agent_status", lambda root: status)

    def refresh():
        status["grok"] = {"available": True, "label": "pro", "hint": None}
        return {}

    monkeypatch.setattr(account, "refresh", refresh)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    root = _repo(tmp_path)
    model.set_default_agent(root, "grok")
    app = tui.WhylineConsoleApp(root=root)

    @contextlib.contextmanager
    def fake_suspend():
        yield

    async with app.run_test(size=(120, 40)) as pilot:
        monkeypatch.setattr(app, "suspend", fake_suspend)
        app._login_fn = lambda argv: 0
        select = app.query_one("#cb-agent", tui.Select)
        assert select.value == "!grok"
        app.query_one("#cb-model", tui.Input).value = "grok-4"
        await pilot.pause()
        app.query_one("#prompt", tui.Input).value = "/login grok"
        await pilot.click("#send")
        await pilot.pause()
        options = _option_map(select)
        assert select.value == "grok"
        assert options["grok"] == "grok · pro"
        assert "!grok" not in options
        assert app.query_one("#cb-model", tui.Input).value == "grok-4"
        assert not app.query_one("#cb-save", tui.Button).disabled


async def test_the_agent_dropdown_shows_each_agent_on_one_line(tmp_path, monkeypatch):
    from whyline import account

    unchecked = {"available": True, "label": "installed (login not checked)", "hint": None}
    monkeypatch.setattr(account, "agent_status", lambda root: {
        "claude": {"available": True, "label": "pro", "hint": None},
        "codex": {"available": True, "label": "plus", "hint": None},
        "antigravity": dict(unchecked),
        "grok": dict(unchecked),
    })
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        select = app.query_one("#cb-agent", tui.Select)
        labels = list(_option_map(select).values())
        assert "antigravity · login unchecked" in labels
        assert "grok · login unchecked" in labels
        select.expanded = True
        await pilot.pause()
        overlay = select.query_one(tui.SelectOverlay)
        for _ in range(20):
            if overlay.region.width:
                break
            await pilot.pause(0.05)
        longest = max(len(label) for label in labels)
        # Room for the label plus the list's border, padding and scrollbar.
        assert overlay.region.width >= longest + 6
        assert overlay.region.height <= len(labels) + 2  # one line per agent


def _installed(monkeypatch, names):
    from whyline.console import relay_ops

    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: list(names)
    )


def _status_all_in(*names: str) -> dict:
    return {name: {"available": True, "label": "pro", "hint": None} for name in names}


async def test_saved_chain_shows_the_head_until_it_changes(tmp_path, monkeypatch):
    from whyline.console import relay_ops

    _installed(monkeypatch, ["claude", "codex", "grok"])
    root = _repo(tmp_path)
    relay_ops.save_backup(root, ["codex", "grok"])
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        select = app.query_one("#cb-backup", tui.Select)
        prompts = _option_map(select)
        assert list(prompts)[:2] == ["automatic", "none"]
        assert prompts["automatic"] == "Automatic · codex → grok"
        assert prompts["none"] == "None — no fallback"
        assert prompts["codex"] == "codex — available"
        assert prompts["grok"] == "grok — Run /login grok"
        assert prompts["manage"] == "Manage chain…"
        assert "reset" not in prompts
        assert select.value == "codex"
        assert _backup_closed(select) == "codex"
        assert app.query_one("#cb-backup-more", tui.Static).renderable == "+1"
        assert app.query_one("#cb-save", tui.Button).disabled
        assert app.query_one("#cb-backup-label", tui.Label).tooltip == (
            "Shared fallback: chat, brainstorm, and the relay"
        )
        select.value = "none"
        await pilot.pause()
        assert _backup_closed(select) == "None"
        assert not app.query_one("#cb-save", tui.Button).disabled
    assert relay_ops.read_backup(root) == ["codex", "grok"]


async def test_none_then_save_clears_the_chain_and_keeps_the_role_line(tmp_path, monkeypatch):
    from whyline.console import relay_ops

    _installed(monkeypatch, ["claude", "codex", "grok"])
    root = _repo(tmp_path)
    config = root / ".whyline" / "relay" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        '[roles]\nimplementer = "codex"\n\n[backup]\nchain = ["grok", "claude"]\n',
        encoding="utf-8",
    )
    relay = config.parent
    chat_override = relay / "chat-active-agents.json"
    role_override = relay / "active-roles.json"
    chat_override.write_text('{"claude": {"agent": "codex"}}\n', encoding="utf-8")
    role_override.write_text('{"implementer": {"agent": "grok"}}\n', encoding="utf-8")
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-model", tui.Input).value = "opus"
        app.query_one("#cb-backup", tui.Select).value = "none"
        await pilot.pause()
        await pilot.click("#cb-save")
        await pilot.pause()
        assert app.query_one("#cb-save", tui.Button).disabled
    text = config.read_text(encoding="utf-8")
    assert 'implementer = "codex"' in text
    assert "[backup]" not in text
    assert relay_ops.read_backup(root) == []
    assert chat_override.read_text(encoding="utf-8") == '{"claude": {"agent": "codex"}}\n'
    assert role_override.read_text(encoding="utf-8") == '{"implementer": {"agent": "grok"}}\n'


async def test_all_repos_saves_the_global_default_and_leaves_the_chain(tmp_path, home, monkeypatch):
    from whyline import model
    from whyline.console import relay_ops

    _installed(monkeypatch, ["claude", "codex", "grok"])
    root = _repo(tmp_path)
    relay_ops.save_backup(root, ["codex", "grok"])
    calls = []
    real = relay_ops.save_backup

    def spy(repo, chain):
        calls.append(list(chain))
        return real(repo, chain)

    monkeypatch.setattr(relay_ops, "save_backup", spy)
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-agent", tui.Select).value = "codex"
        app.query_one("#cb-model", tui.Input).value = "gpt-5.6"
        app.query_one("#cb-global", tui.Checkbox).value = True
        await pilot.pause()
        await pilot.click("#cb-save")
        await pilot.pause()
    assert calls == []
    assert model.resolve(root) == ("codex", "gpt-5.6")
    assert model.load_global()["default_agent"] == "codex"
    assert relay_ops.read_backup(root) == ["codex", "grok"]


async def test_automatic_on_a_saved_chain_does_not_reorder_or_enable_save(tmp_path, monkeypatch):
    from whyline.console import relay_ops

    _installed(monkeypatch, ["claude", "codex", "grok"])
    root = _repo(tmp_path)
    relay_ops.save_backup(root, ["grok", "claude"])
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        select = app.query_one("#cb-backup", tui.Select)
        assert _option_map(select)["automatic"] == "Automatic · grok → claude"
        select.value = "automatic"
        await pilot.pause()
        assert _backup_closed(select) == "Automatic · grok → claude"
        assert app.query_one("#cb-save", tui.Button).disabled
    assert relay_ops.read_backup(root) == ["grok", "claude"]


async def test_automatic_on_an_empty_chain_stages_the_other_usable_agents(tmp_path, monkeypatch):
    from whyline import account, model
    from whyline.console import relay_ops

    _installed(monkeypatch, ["claude", "codex", "grok"])
    monkeypatch.setattr(
        account, "agent_status", lambda root: _status_all_in("claude", "codex", "grok")
    )
    root = _repo(tmp_path)
    model.set_default_agent(root, "codex")
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        select = app.query_one("#cb-backup", tui.Select)
        assert _option_map(select)["automatic"] == "Automatic · claude → grok"
        select.value = "automatic"
        await pilot.pause()
        assert _backup_closed(select) == "Automatic · claude → grok"
        assert not app.query_one("#cb-save", tui.Button).disabled
        app.query_one("#cb-model", tui.Input).value = "gpt-5"
        await pilot.click("#cb-save")
        await pilot.pause()
        assert app.query_one("#cb-save", tui.Button).disabled
    assert relay_ops.read_backup(root) == ["claude", "grok"]


async def test_selecting_an_agent_moves_it_to_the_front(tmp_path, monkeypatch):
    from whyline.console import relay_ops

    _installed(monkeypatch, ["claude", "codex", "grok"])
    root = _repo(tmp_path)
    relay_ops.save_backup(root, ["grok", "claude"])
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        select = app.query_one("#cb-backup", tui.Select)
        app.query_one("#cb-model", tui.Input).value = "opus"
        select.value = "claude"
        await pilot.pause()
        assert _backup_closed(select) == "claude"
        assert app.query_one("#cb-backup-more", tui.Static).renderable == "+1"
        await pilot.click("#cb-save")
        await pilot.pause()
    assert relay_ops.read_backup(root) == ["claude", "grok"]


async def test_save_while_a_relay_is_live_writes_nothing_and_stays_dirty(tmp_path, monkeypatch):
    from whyline.console import relay_ops

    _installed(monkeypatch, ["claude", "codex", "grok"])
    root = _repo(tmp_path)
    relay_ops.save_backup(root, ["codex", "grok"])
    monkeypatch.setattr(relay_ops, "live_run", lambda repo: "BAR-3, codex")
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        select = app.query_one("#cb-backup", tui.Select)
        app.query_one("#cb-model", tui.Input).value = "opus"
        select.value = "none"
        await pilot.pause()
        await pilot.click("#cb-save")
        await pilot.pause()
        assert not app.query_one("#cb-save", tui.Button).disabled
        assert select.value == "none"
        assert any(
            "Finish or stop the current job before changing the backup chain." in line
            for line in _lines(app)
        )
    assert relay_ops.read_backup(root) == ["codex", "grok"]


async def test_a_model_name_with_a_space_writes_neither_chain_nor_agent(tmp_path, monkeypatch):
    from whyline import model
    from whyline.console import relay_ops

    _installed(monkeypatch, ["claude", "codex", "grok"])
    root = _repo(tmp_path)
    relay_ops.save_backup(root, ["grok", "claude"])
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-agent", tui.Select).value = "codex"
        app.query_one("#cb-model", tui.Input).value = "gpt 5"
        app.query_one("#cb-backup", tui.Select).value = "none"
        await pilot.pause()
        await pilot.click("#cb-save")
        await pilot.pause()
        assert not app.query_one("#cb-save", tui.Button).disabled
        assert any("A model name has no spaces" in line for line in _lines(app))
    assert relay_ops.read_backup(root) == ["grok", "claude"]
    assert model.resolve(root)[0] == "claude"
    assert app.session.agent == "claude"


async def test_an_empty_model_writes_neither_chain_nor_agent(tmp_path, monkeypatch):
    from whyline import model
    from whyline.console import relay_ops

    _installed(monkeypatch, ["claude", "codex", "grok"])
    root = _repo(tmp_path)
    relay_ops.save_backup(root, ["grok", "claude"])
    model.set_one(root, "claude", "opus")
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-agent", tui.Select).value = "codex"
        app.query_one("#cb-model", tui.Input).value = ""
        app.query_one("#cb-backup", tui.Select).value = "none"
        app.query_one("#cb-repo", tui.Input).value = str(tmp_path / "other")
        await pilot.pause()
        await pilot.click("#cb-save")
        await pilot.pause()
        assert not app.query_one("#cb-save", tui.Button).disabled
        assert any("A model name is required" in line for line in _lines(app))
        assert not isinstance(app.screen, tui.ConfirmScreen)
    assert relay_ops.read_backup(root) == ["grok", "claude"]
    assert model.resolve(root) == ("claude", "opus")
    assert app.session.agent == "claude"
    assert app.session.root == root


async def test_unreadable_config_is_shown_on_the_backup_select(tmp_path, monkeypatch):
    _installed(monkeypatch, ["claude", "codex", "grok"])
    root = _repo(tmp_path)
    path = root / ".whyline" / "relay" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text("[backup]\nchain = [\n", encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        select = app.query_one("#cb-backup", tui.Select)
        assert "could not read" in _backup_closed(select)
        app.query_one("#cb-model", tui.Input).value = "opus"
        select.value = "claude"
        await pilot.pause()
        await pilot.click("#cb-save")
        await pilot.pause()
        assert not app.query_one("#cb-save", tui.Button).disabled
    assert path.read_text(encoding="utf-8") == before


async def test_manage_save_dirties_the_bar_and_does_not_write(tmp_path, monkeypatch):
    from whyline.console import relay_ops
    from whyline.console.chain_editor import BackupChainScreen

    _installed(monkeypatch, ["claude", "codex", "grok"])
    root = _repo(tmp_path)
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-backup", tui.Select).value = "manage"
        await pilot.pause()
        assert isinstance(app.screen, BackupChainScreen)
        for _ in range(20):
            if app.screen.query("#chain-check-claude"):
                break
            await pilot.pause()
        await pilot.click("#chain-check-claude")
        await pilot.pause()
        await pilot.click("#bc-save")
        await pilot.pause()
        assert not isinstance(app.screen, BackupChainScreen)
        assert not app.query_one("#cb-save", tui.Button).disabled
        assert _backup_closed(app.query_one("#cb-backup", tui.Select)) == "claude"
    assert relay_ops.read_backup(root) == []


def _chat_override(root, role: str, agent: str) -> None:
    from whyline_relay import failover

    failover.write_override(
        root,
        role,
        failover.ActiveOverride(agent, role, "rate-limit", "2026-10-11T00:00:00Z"),
        storage_path=failover.chat_path(root),
    )


def _role_line(root) -> Path:
    path = root / ".whyline" / "relay" / "active-roles.json"
    path.write_text('{"implementer": {"agent": "grok"}}\n', encoding="utf-8")
    return path


async def test_reset_restores_the_selection_and_clears_the_chat_override(tmp_path, monkeypatch):
    from whyline_relay import failover
    from whyline.console import relay_ops

    _installed(monkeypatch, ["claude", "codex", "grok"])
    root = _repo(tmp_path)
    relay_ops.save_backup(root, ["codex", "grok"])
    _chat_override(root, "claude", "codex")
    _chat_override(root, "codex", "grok")
    role = _role_line(root)
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        select = app.query_one("#cb-backup", tui.Select)
        prompts = _option_map(select)
        assert prompts["reset"] == "Reset failover (back to claude)"
        assert select.value == "codex"
        select.value = "reset"
        await pilot.pause()
        assert select.value == "codex"
        assert "reset" not in _option_map(select)
        assert _backup_closed(select) == "codex"
        assert app.query_one("#cb-backup-more", tui.Static).renderable == "+1"
        assert app.query_one("#cb-save", tui.Button).disabled
        assert any(
            "Back to claude. The chain is still codex → grok." in line
            for line in _lines(app)
        )
    assert failover.resolve_chat_agent(root, "claude") == "claude"
    assert failover.resolve_chat_agent(root, "codex") == "grok"
    assert role.read_text(encoding="utf-8") == '{"implementer": {"agent": "grok"}}\n'
    assert relay_ops.read_backup(root) == ["codex", "grok"]


async def test_editor_reset_clears_the_chat_override_and_stays_open(tmp_path, monkeypatch):
    from whyline_relay import failover
    from whyline.console import relay_ops
    from whyline.console.chain_editor import BackupChainScreen

    _installed(monkeypatch, ["claude", "codex", "grok"])
    root = _repo(tmp_path)
    relay_ops.save_backup(root, ["codex", "grok"])
    _chat_override(root, "claude", "codex")
    role = _role_line(root)
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-backup", tui.Select).value = "manage"
        await pilot.pause()
        assert isinstance(app.screen, BackupChainScreen)
        await pilot.click("#bc-reset")
        await pilot.pause()
        assert isinstance(app.screen, BackupChainScreen)
        assert failover.resolve_chat_agent(root, "claude") == "claude"
        assert any(
            "Back to claude. The chain is still codex → grok." in line
            for line in _lines(app)
        )
        await pilot.click("#bc-cancel")
        await pilot.pause()
        select = app.query_one("#cb-backup", tui.Select)
        assert not isinstance(app.screen, BackupChainScreen)
        assert "reset" not in _option_map(select)
        assert select.value == "codex"
        assert _backup_closed(select) == "codex"
        assert app.query_one("#cb-save", tui.Button).disabled
    assert role.read_text(encoding="utf-8") == '{"implementer": {"agent": "grok"}}\n'
    assert relay_ops.read_backup(root) == ["codex", "grok"]


async def test_reset_while_a_relay_is_live_leaves_the_override(tmp_path, monkeypatch):
    from whyline_relay import failover
    from whyline.console import relay_ops

    _installed(monkeypatch, ["claude", "codex", "grok"])
    root = _repo(tmp_path)
    relay_ops.save_backup(root, ["codex", "grok"])
    _chat_override(root, "claude", "codex")
    monkeypatch.setattr(relay_ops, "live_run", lambda repo: "BAR-3, codex")
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        select = app.query_one("#cb-backup", tui.Select)
        assert "reset" in _option_map(select)
        select.value = "reset"
        await pilot.pause()
        assert select.value == "codex"
        assert "reset" in _option_map(select)
        assert app.query_one("#cb-save", tui.Button).disabled
        assert any(
            "Finish or stop the current job before resetting failover." in line
            for line in _lines(app)
        )
    assert failover.resolve_chat_agent(root, "claude") == "codex"
    assert relay_ops.read_backup(root) == ["codex", "grok"]
