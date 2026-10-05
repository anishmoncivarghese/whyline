from pathlib import Path

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
    monkeypatch.setattr(relay_ops, "prepare_agents", lambda root, agents: [])
    saved = []
    monkeypatch.setattr(
        relay_ops,
        "save_roles",
        lambda root, i, t, r, b: saved.append((i, t, r, b)),
    )
    monkeypatch.setattr(
        relay_ops,
        "save_release",
        lambda root, value: saved.append(("release", value)),
    )
    monkeypatch.setattr(relay_ops, "release_role", lambda root: "human")
    plans = [
        relay_ops.PlanInfo(Path("/r/plans/new.plan.md"), "new", "draft", "2026-10-04T10:00:00+05:30", 0, 3),
        relay_ops.PlanInfo(Path("/r/plans/old.plan.md"), "old", "paste", "2026-10-01T10:00:00+05:30", 2, 2),
    ]
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: plans)
    monkeypatch.setattr(relay_ops, "configured_plan", lambda root: None)
    monkeypatch.setattr(relay_ops, "select_plan", lambda root, path: saved.append(("plan", path)))
    return saved


def _checks(*statuses):
    return lambda root, plan=None: [
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
        assert screen.query_one("#rs-committer", tui.Static).renderable == "Committer: whyline (automatic)"
        release = screen.query_one("#rs-release", tui.Select)
        assert release.value == "human"
        assert [prompt for prompt, _ in release._options if _ is not tui.Select.BLANK] == [
            "you", "claude", "codex"
        ]
        assert screen.query_one("#rs-backup-claude", tui.Checkbox).value
        assert not screen.query_one("#rs-backup-codex", tui.Checkbox).value
        assert screen.query_one("#rs-start", tui.Button).disabled


async def test_a_clean_check_saves_roles_and_enables_start(tmp_path, monkeypatch, ops):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok", "warn"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rs-implementer", tui.Select).value = "codex"
        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start"
        )
        assert "warn  warn message" in _checks_text(screen)
        await pilot.click("#rs-start")
        # Slow CI runners need more than one frame for the dismiss to land.
        await _wait_for(pilot, lambda: results, "the popup to close")
    assert ops == [
        ("codex", "codex", "codex", ["claude"]),
        ("release", "human"),
        ("plan", Path("/r/plans/new.plan.md")),
    ]
    assert results == ["start"]


async def test_release_select_saves_chosen_agent(tmp_path, monkeypatch, ops):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rs-release", tui.Select).value = "codex"
        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start"
        )
        await pilot.click("#rs-start")
        await _wait_for(pilot, lambda: results, "the popup to close")
    assert ("release", "codex") in ops


async def test_the_plan_dropdown_lists_plans_newest_first(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        select = screen.query_one("#rs-plan", tui.Select)
        assert select.value == str(Path("/r/plans/new.plan.md"))
        labels = [str(prompt) for prompt, _ in select._options if _ is not tui.Select.BLANK]
        assert labels[0].startswith("new · 0/3 done · draft · 2026-10-04")


async def test_with_no_plan_setup_offers_to_make_one(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: [])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        assert screen.query_one("#rs-check", tui.Button).disabled
        assert "No plan yet" in str(screen.query_one("#rs-no-plan", tui.Static).renderable)
        await pilot.click("#rs-make-plan")
        await pilot.pause()
    assert results == ["plan"]


async def test_changing_the_plan_after_a_check_disables_start(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start"
        )
        screen.query_one("#rs-plan", tui.Select).value = str(Path("/r/plans/old.plan.md"))
        await pilot.pause()
        assert screen.query_one("#rs-start", tui.Button).disabled


async def test_check_runs_against_the_chosen_plan(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(
        relay_ops,
        "run_checks",
        lambda root, plan=None: seen.append(plan) or [relay_ops.CheckLine("ok", "fine")],
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rs-plan", tui.Select).value = str(Path("/r/plans/old.plan.md"))
        await pilot.pause()
        await pilot.click("#rs-check")
        await _wait_for(pilot, lambda: seen, "check")
    assert seen == [Path("/r/plans/old.plan.md")]


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


async def test_check_prepares_the_chosen_agents_before_checking(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(relay_ops, "prepare_agents", lambda root, agents: order.append(("prepare", sorted(set(agents)))) or [])
    monkeypatch.setattr(relay_ops, "run_checks", lambda root, plan=None: order.append(("check",)) or [relay_ops.CheckLine("ok", "fine")])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rs-check")
        await _wait_for(pilot, lambda: ("check",) in order, "check")
    assert order[0] == ("prepare", ["claude", "codex"]) and order[-1] == ("check",)


async def test_a_check_that_ends_after_the_popup_closed_is_ignored(tmp_path, monkeypatch):
    import threading

    release = threading.Event()

    def slow_checks(root, plan=None):
        release.wait(5)
        raise RuntimeError("late failure")

    monkeypatch.setattr(relay_ops, "run_checks", slow_checks)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        await pilot.click("#rs-check")
        await pilot.pause()
        screen.dismiss(None)  # the user cancels while the check is running
        await pilot.pause()
        release.set()
        for _ in range(20):
            await pilot.pause(0.05)
    assert results == [None]  # and nothing crashed
