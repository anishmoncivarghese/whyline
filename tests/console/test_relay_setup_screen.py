import pytest

from whyline.console import relay_ops, tui
from whyline.console.relay_screens import RelaySetupScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


@pytest.fixture(autouse=True)
def ops(monkeypatch):
    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex"]
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "claude",
            "tester": "codex",
            "reviewer": "codex",
            "backup": ["claude"],
        },
    )
    monkeypatch.setattr(relay_ops, "live_run", lambda root: None)
    saved = []
    monkeypatch.setattr(
        relay_ops,
        "save_roles",
        lambda root, i, t, r, b: saved.append((i, t, r, b)),
    )
    return saved


def _checks(*statuses):
    return lambda root: [
        relay_ops.CheckLine(s, f"{s} message", "the fix" if s == "FAIL" else None)
        for s in statuses
    ]


async def _open(app, pilot):
    results = []
    app.push_screen(RelaySetupScreen(app.session.root), results.append)
    await pilot.pause()
    return app.screen, results


async def _wait_for(pilot, condition, what):
    for _ in range(100):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what}")


def _checks_text(screen):
    return str(screen.query_one("#rs-checks", tui.Static).renderable)


async def test_fields_are_prefilled_from_the_current_config(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        assert screen.query_one("#rs-implementer", tui.Select).value == "claude"
        assert screen.query_one("#rs-tester", tui.Select).value == "codex"
        assert screen.query_one("#rs-backup-claude", tui.Checkbox).value
        assert not screen.query_one("#rs-backup-codex", tui.Checkbox).value
        assert screen.query_one("#rs-start", tui.Button).disabled


async def test_a_clean_check_saves_roles_and_enables_start(tmp_path, monkeypatch, ops):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok", "warn"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rs-implementer", tui.Select).value = "codex"
        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start"
        )
        assert "warn  warn message" in _checks_text(screen)
        await pilot.click("#rs-start")
        await pilot.pause()
    assert ops == [("codex", "codex", "codex", ["claude"])]
    assert results == ["start"]


async def test_a_failing_check_keeps_start_disabled_and_shows_the_fix(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok", "FAIL"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rs-check")
        await _wait_for(pilot, lambda: "FAIL" in _checks_text(screen), "checks")
        assert "fix: the fix" in _checks_text(screen)
        assert screen.query_one("#rs-start", tui.Button).disabled


async def test_changing_a_field_after_a_check_disables_start_again(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start"
        )
        screen.query_one("#rs-reviewer", tui.Select).value = "claude"
        await pilot.pause()
        assert screen.query_one("#rs-start", tui.Button).disabled
        assert _checks_text(screen) == ""


async def test_start_stays_disabled_while_a_relay_runs_here(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    monkeypatch.setattr(relay_ops, "live_run", lambda root: "T3, codex")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rs-check")
        await _wait_for(pilot, lambda: "ok" in _checks_text(screen), "checks")
        assert screen.query_one("#rs-start", tui.Button).disabled
        assert "already running here (T3, codex)" in str(
            screen.query_one("#rs-error", tui.Static).renderable
        )


async def test_saving_roles_can_fail_visibly(tmp_path, monkeypatch):
    def boom(*a):
        raise RuntimeError("not a git repository")

    monkeypatch.setattr(relay_ops, "save_roles", boom)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rs-check")
        await _wait_for(
            pilot,
            lambda: "not a git repository"
            in str(screen.query_one("#rs-error", tui.Static).renderable),
            "error",
        )


async def test_setup_button_starts_the_relay(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)
    launched = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_launch_relay", launched.append)
    async with app.run_test(size=(110, 40)) as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.click("#relay-setup")
        await pilot.pause()
        screen = app.screen
        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start"
        )
        await pilot.click("#rs-start")
        await pilot.pause()
    assert launched == [["start"]]
