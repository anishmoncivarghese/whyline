import pytest
from pathlib import Path
from unittest.mock import MagicMock

from whyline.console import relay_ops, tui
from whyline.console.repl import handle_slash_command
from whyline.console.relay_screens import RelaySetupScreen
from whyline.console.session import ConsoleSession

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


@pytest.fixture
def trust(monkeypatch):
    calls = {"state": "ask", "trusted": 0, "declined": 0, "forgot": 0}
    monkeypatch.setattr(relay_ops, "antigravity_state", lambda root: calls["state"])

    def do_trust(root):
        calls["trusted"] += 1
        calls["state"] = "trusted"

    def do_decline(root):
        calls["declined"] += 1
        calls["state"] = "declined"

    def do_forget(root):
        calls["forgot"] += 1

    monkeypatch.setattr(relay_ops, "trust_antigravity", do_trust)
    monkeypatch.setattr(relay_ops, "decline_antigravity", do_decline)
    monkeypatch.setattr(relay_ops, "forget_antigravity_decline", do_forget)
    monkeypatch.setattr(
        relay_ops,
        "list_plans",
        lambda root: [
            relay_ops.PlanInfo(
                Path("/r/plans/p.plan.md"), "p", "draft", "2026-10-04", 0, 1
            )
        ],
    )
    return calls


def _lines(app):
    return [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]


async def test_trust_it_trusts_and_proceeds_with_antigravity(tmp_path, trust):
    seen = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._with_antigravity(True, seen.append)
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
    assert trust["trusted"] == 1 and seen == [True]


async def test_not_now_declines_proceeds_without_and_never_asks_again(tmp_path, trust):
    seen = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._with_antigravity(True, seen.append)
        await pilot.pause()
        await pilot.click("#cancel")
        await pilot.pause()
        app._with_antigravity(True, seen.append)
        await pilot.pause()
        assert not isinstance(app.screen, tui.ConfirmScreen)
        assert any("isn't trusted" in line for line in _lines(app))
    assert trust["declined"] == 1 and seen == [False, False]


async def test_nothing_is_asked_when_antigravity_is_not_used(tmp_path, trust):
    seen = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._with_antigravity(False, seen.append)
        await pilot.pause()
        assert not isinstance(app.screen, tui.ConfirmScreen)
    assert seen == [True]


async def test_a_brainstorm_drops_antigravity_when_declined(tmp_path, trust, monkeypatch):
    trust["state"] = "declined"
    started = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_run_brainstorm_choice", lambda choice: started.append(choice))
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_brainstorm({
            "topic": "t", "agents": ["claude", "antigravity"], "passes": 1,
            "final_agent": "antigravity", "timeout_minutes": 15,
        })
        await pilot.pause()
    assert started[0]["agents"] == ["claude"]
    assert started[0]["final_agent"] == "claude"


async def test_brainstorm_with_only_antigravity_aborts_when_declined(tmp_path, trust, monkeypatch):
    trust["state"] = "declined"
    started = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_run_brainstorm_choice", lambda choice: started.append(choice))
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_brainstorm({
            "topic": "t", "agents": ["antigravity"], "passes": 1,
            "final_agent": "antigravity", "timeout_minutes": 15,
        })
        await pilot.pause()
        assert not started
        assert any("No model is left to brainstorm with" in line for line in _lines(app))


async def test_chat_dispatch_blocks_antigravity_when_declined(tmp_path, trust, monkeypatch):
    trust["state"] = "declined"
    dispatched = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    app.session.mode = "chat"
    app.session.agent = "antigravity"
    monkeypatch.setattr(app, "_dispatch_in_thread", lambda text, token: dispatched.append(text))
    async with app.run_test(size=(110, 40)) as pilot:
        app._dispatch_text("hello")
        await pilot.pause()
        assert not dispatched
        assert any("Antigravity can't run here until this repo is trusted" in line for line in _lines(app))


async def test_chat_dispatch_proceeds_when_trusted(tmp_path, trust, monkeypatch):
    trust["state"] = "trusted"
    dispatched = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    app.session.mode = "chat"
    app.session.agent = "antigravity"
    monkeypatch.setattr(app, "_dispatch_in_thread", lambda text, token: dispatched.append(text))
    async with app.run_test(size=(110, 40)) as pilot:
        app._dispatch_text("hello")
        await pilot.pause()
        assert dispatched == ["hello"]


async def test_relay_launch_blocked_when_antigravity_role_declined(tmp_path, trust, monkeypatch):
    trust["state"] = "declined"
    monkeypatch.setattr(
        relay_ops, "current_roles",
        lambda root: {"implementer": "antigravity", "tester": "claude", "reviewer": "claude", "backup": []},
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_relay_running", lambda: False)
    monkeypatch.setattr(relay_ops, "live_run", lambda root: None)
    async with app.run_test(size=(110, 40)) as pilot:
        app._launch_relay(["start"])
        await pilot.pause()
        assert any("The relay gives Antigravity a role, but this repo isn't trusted" in line for line in _lines(app))


async def test_relay_launch_proceeds_when_antigravity_role_confirmed(tmp_path, trust, monkeypatch):
    monkeypatch.setattr(
        relay_ops, "current_roles",
        lambda root: {"implementer": "antigravity", "tester": "claude", "reviewer": "claude", "backup": []},
    )
    started_args = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_relay_running", lambda: False)
    monkeypatch.setattr(relay_ops, "live_run", lambda root: None)

    class DummyProcess:
        def __init__(self, root, args, on_line, on_exit):
            self.args = args
        def start(self):
            started_args.append(self.args)
        def running(self):
            return True

    monkeypatch.setattr(tui, "RelayProcess", DummyProcess)

    async with app.run_test(size=(110, 40)) as pilot:
        app._launch_relay(["start"])
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
    assert started_args == [["start"]]


async def test_model_slash_command_forgets_antigravity_decline(tmp_path, trust, monkeypatch):
    from whyline import account, model
    monkeypatch.setattr(account, "AGENT_ORDER", ["antigravity", "claude"])
    monkeypatch.setattr(account, "agent_status", lambda root: {
        "antigravity": {"available": True, "label": "ready", "hint": ""},
        "claude": {"available": True, "label": "ready", "hint": ""},
    })
    session = ConsoleSession(root=tmp_path)
    handle_slash_command(session, "/model antigravity")
    assert trust["forgot"] == 1
    assert session.agent == "antigravity"


async def test_setup_screen_forgets_antigravity_decline_when_antigravity_saved(tmp_path, trust, monkeypatch):
    saved_roles = []
    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: ["antigravity", "claude"])
    monkeypatch.setattr(
        relay_ops, "current_roles",
        lambda root: {"implementer": "antigravity", "tester": "claude", "reviewer": "claude", "backup": []},
    )
    monkeypatch.setattr(relay_ops, "save_roles", lambda root, *roles: saved_roles.append(roles))
    monkeypatch.setattr(relay_ops, "run_checks", lambda root, plan=None: [])
    monkeypatch.setattr(relay_ops, "live_run", lambda root: None)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen = RelaySetupScreen(tmp_path)
        app.push_screen(screen)
        await pilot.pause()
        await pilot.click("#rs-check")
        for _ in range(50):
            if saved_roles:
                break
            await pilot.pause(0.05)
    assert trust["forgot"] == 1
    assert len(saved_roles) == 1


async def test_confirm_screen_cancel_label():
    cs_default = tui.ConfirmScreen("Are you sure?", "Yes")
    assert cs_default._cancel_label == "Cancel"
    cs_custom = tui.ConfirmScreen("Are you sure?", "Yes", "Not now")
    assert cs_custom._cancel_label == "Not now"


async def test_relay_ops_antigravity_wrappers(monkeypatch, tmp_path):
    import whyline_relay
    stub = MagicMock()
    stub.is_trusted.side_effect = lambda root: root == tmp_path / "trusted"
    stub.is_declined.side_effect = lambda root: root == tmp_path / "declined"
    monkeypatch.setattr(whyline_relay, "antigravity", stub)

    assert relay_ops.antigravity_state(tmp_path / "trusted") == "trusted"
    assert relay_ops.antigravity_state(tmp_path / "declined") == "declined"
    assert relay_ops.antigravity_state(tmp_path / "other") == "ask"

    relay_ops.trust_antigravity(tmp_path / "foo")
    stub.trust.assert_called_once_with(tmp_path / "foo")
    stub.forget_decline.assert_called_once_with(tmp_path / "foo")

    stub.reset_mock()
    relay_ops.decline_antigravity(tmp_path / "bar")
    stub.decline.assert_called_once_with(tmp_path / "bar")

    stub.reset_mock()
    relay_ops.forget_antigravity_decline(tmp_path / "baz")
    stub.forget_decline.assert_called_once_with(tmp_path / "baz")


async def test_trust_fails_renders_error_and_proceeds_without(tmp_path, trust, monkeypatch):
    seen = []
    def fail_trust(root):
        raise RuntimeError("settings.json is broken")
    monkeypatch.setattr(relay_ops, "trust_antigravity", fail_trust)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._with_antigravity(True, seen.append)
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
        assert seen == [False]
        assert any("settings.json is broken" in line for line in _lines(app))

