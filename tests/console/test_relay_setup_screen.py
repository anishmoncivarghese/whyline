from pathlib import Path

import pytest

from whyline.console import relay_ops, tui
from whyline.console.chain_editor import OrderedChain
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
        chain = screen.query_one("#rs-backup", OrderedChain)
        assert chain.order() == ["claude"]
        assert screen.query_one("#chain-check-claude", tui.Checkbox).value
        assert not screen.query_one("#chain-check-codex", tui.Checkbox).value
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
        await pilot.pause()  # shown buttons need a layout pass before a click
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


def _roles(backup, **roles):
    return {
        "implementer": roles.get("implementer", "codex"),
        "tester": roles.get("tester", "claude"),
        "reviewer": roles.get("reviewer", "grok"),
        "backup": backup,
    }


def _install(monkeypatch, agents, backup, **roles):
    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: list(agents))
    monkeypatch.setattr(relay_ops, "current_roles", lambda root: _roles(backup, **roles))


async def test_the_editor_round_trips_grok_then_claude(tmp_path, monkeypatch):
    agents = ["claude", "codex", "grok"]
    _install(monkeypatch, agents, ["grok", "claude"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        chain = screen.query_one("#rs-backup", OrderedChain)
        assert chain.order() == ["grok", "claude"]
        assert chain.order() != sorted(agents)
        assert screen.query_one("#chain-check-grok", tui.Checkbox).value
        assert screen.query_one("#chain-check-claude", tui.Checkbox).value
        assert not screen.query_one("#chain-check-codex", tui.Checkbox).value


async def test_check_writes_roles_and_the_editor_chain(tmp_path, monkeypatch, ops):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    _install(monkeypatch, ["claude", "codex", "grok"], ["grok", "claude"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start"
        )
    assert ops[0] == ("codex", "claude", "grok", ["grok", "claude"])
    assert ops[0][3] != sorted(["claude", "codex", "grok"])
    assert ("release", "human") in ops


async def test_guided_summary_shows_backup_grok_then_claude(tmp_path, monkeypatch):
    from whyline import account

    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {a: {"available": True, "label": "ok"} for a in ("claude", "codex", "grok")},
    )
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: True)
    _install(monkeypatch, ["claude", "codex", "grok"], ["grok", "claude"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(RelaySetupScreen(tmp_path, guided=True))
        await pilot.pause()
        summary = str(app.screen.query_one("#rs-summary", tui.Static).renderable)
    assert summary == (
        "Implementer: codex · Tester: claude · Reviewer: grok · "
        "Backup: grok → claude · Release: you"
    )


async def test_automatic_fills_only_an_empty_editor_from_staged_backup(tmp_path, monkeypatch, ops):
    from whyline import account, model

    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    _install(monkeypatch, ["claude", "codex", "grok"], [])
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {a: {"available": True, "label": "ok"} for a in ("claude", "codex", "grok")},
    )
    model.set_default_agent(tmp_path, "codex")
    backup_writes = []
    monkeypatch.setattr(relay_ops, "save_backup", lambda *args: backup_writes.append(args))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 60)) as pilot:
        screen, _ = await _open(app, pilot)
        chain = screen.query_one("#rs-backup", OrderedChain)
        # Nothing saved, so the editor opens on Automatic already.
        assert chain.order() == ["claude", "grok"]
        screen.query_one("#chain-none", tui.Button).press()
        await pilot.pause()
        assert chain.order() == []
        screen.query_one("#chain-automatic", tui.Button).press()
        await pilot.pause()
        assert chain.order() == ["claude", "grok"]
        assert "automatic" not in chain.order()
        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start"
        )
    assert ops[0] == ("codex", "claude", "grok", ["claude", "grok"])
    assert backup_writes == []


async def test_automatic_leaves_a_chain_the_editor_already_has(tmp_path, monkeypatch):
    _install(monkeypatch, ["claude", "codex", "grok"], ["grok", "claude"])
    calls = []
    real = relay_ops.staged_backup

    def spy(*args):
        calls.append(args)
        return real(*args)

    monkeypatch.setattr(relay_ops, "staged_backup", spy)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 60)) as pilot:
        screen, _ = await _open(app, pilot)
        calls.clear()  # the bar may stage its own empty chain while the app mounts
        screen.query_one("#chain-automatic", tui.Button).press()
        await pilot.pause()
        assert calls == []
        assert screen.query_one("#rs-backup", OrderedChain).order() == ["grok", "claude"]


async def test_reordering_the_chain_after_a_check_disables_start(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    _install(monkeypatch, ["claude", "codex", "grok"], ["grok", "claude"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 60)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start"
        )
        screen.query_one("#chain-up-claude", tui.Button).press()
        await pilot.pause()
        assert screen.query_one("#rs-backup", OrderedChain).order() == ["claude", "grok"]
        assert screen.query_one("#rs-start", tui.Button).disabled
        assert _checks_text(screen) == ""


def _timeout_rows(select) -> list:
    return [value for _prompt, value in select._options if value is not tui.Select.BLANK]


async def test_timeout_offers_30_45_60_and_none_and_shows_the_saved_one(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "relay_timeout", lambda root: 45)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        select = screen.query_one("#rs-timeout", tui.Select)
        assert _timeout_rows(select) == [30, 45, 60, 0]
        assert select.value == 45


async def test_an_unlisted_saved_timeout_stays_selected_instead_of_snapping(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "relay_timeout", lambda root: 20)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        select = screen.query_one("#rs-timeout", tui.Select)
        assert _timeout_rows(select) == [20, 30, 45, 60, 0]
        assert select.value == 20


async def test_check_saves_a_changed_timeout_and_not_an_unchanged_one(tmp_path, monkeypatch, ops):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    monkeypatch.setattr(relay_ops, "relay_timeout", lambda root: 30)
    monkeypatch.setattr(
        relay_ops, "save_timeout", lambda root, minutes: ops.append(("timeout", minutes))
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        start = screen.query_one("#rs-start", tui.Button)
        screen.query_one("#rs-check", tui.Button).press()
        await _wait_for(pilot, lambda: not start.disabled, "first check")
        assert not [op for op in ops if op[0] == "timeout"]
        screen.query_one("#rs-timeout", tui.Select).value = 60
        await pilot.pause()
        assert start.disabled  # a changed timeout needs a fresh check
        screen.query_one("#rs-check", tui.Button).press()
        await _wait_for(pilot, lambda: not start.disabled, "second check")
    assert ("timeout", 60) in ops


async def test_none_is_saved_as_zero(tmp_path, monkeypatch, ops):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    monkeypatch.setattr(relay_ops, "relay_timeout", lambda root: 30)
    monkeypatch.setattr(
        relay_ops, "save_timeout", lambda root, minutes: ops.append(("timeout", minutes))
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rs-timeout", tui.Select).value = 0
        await pilot.pause()
        screen.query_one("#rs-check", tui.Button).press()
        start = screen.query_one("#rs-start", tui.Button)
        await _wait_for(pilot, lambda: not start.disabled, "check")
    assert ("timeout", 0) in ops


async def test_relay_timeout_reads_the_config_and_falls_back_to_30(tmp_path):
    assert relay_ops.relay_timeout(tmp_path) == 30
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True)
    (relay / "config.toml").write_text('plan = "plan.md"\ntimeout_minutes = 45\n', encoding="utf-8")
    assert relay_ops.relay_timeout(tmp_path) == 45


async def test_check_with_fail_enables_resolve_and_clean_check_disables_it(tmp_path, monkeypatch, ops):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("FAIL"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        assert screen.query_one("#rs-resolve", tui.Button).disabled is True
        screen.query_one("#rs-check", tui.Button).press()
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-resolve", tui.Button).disabled, "resolve enabled"
        )
        assert screen.query_one("#rs-resolve", tui.Button).disabled is False

        # Invalidate by changing release or role
        screen.query_one("#rs-implementer", tui.Select).value = "codex"
        await pilot.pause()
        assert screen.query_one("#rs-resolve", tui.Button).disabled is True

        # Clean check disables it
        monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
        screen.query_one("#rs-check", tui.Button).press()
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start enabled"
        )
        assert screen.query_one("#rs-resolve", tui.Button).disabled is True


async def test_resolve_closes_setup_with_resolve_tuple(tmp_path, monkeypatch, ops):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("FAIL"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rs-check", tui.Button).press()
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-resolve", tui.Button).disabled, "resolve enabled"
        )
        await pilot.click("#rs-resolve")
        await _wait_for(pilot, lambda: results, "popup to close")
        assert len(results) == 1
        assert results[0][0] == "resolve"
        assert any("FAIL" in line for line in results[0][1])


async def test_missing_resolve_mode_file_reads_review(tmp_path):
    assert relay_ops.resolve_mode(tmp_path) == "review"
    mode_file = tmp_path / ".whyline" / "relay" / "resolve-mode.json"
    mode_file.parent.mkdir(parents=True, exist_ok=True)
    mode_file.write_text("corrupted json {", encoding="utf-8")
    assert relay_ops.resolve_mode(tmp_path) == "review"
    mode_file.write_text('{"schema": 1, "mode": "invalid"}', encoding="utf-8")
    assert relay_ops.resolve_mode(tmp_path) == "review"


async def test_save_writes_auto_and_reopening_setup_shows_it(tmp_path, monkeypatch, ops):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    save_calls = []
    real_save_mode = relay_ops.save_resolve_mode

    def tracking_save(root, mode):
        save_calls.append((root, mode))
        real_save_mode(root, mode)

    monkeypatch.setattr(relay_ops, "save_resolve_mode", tracking_save)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        mode_select = screen.query_one("#rs-resolve-mode", tui.Select)
        assert mode_select.value == "review"
        assert [prompt for prompt, _ in mode_select._options if _ is not tui.Select.BLANK] == [
            "Review: show the fix, wait for my click",
            "Auto: apply the recommended fix and continue",
        ]

        # 1. First check untouched: does not write resolve_mode
        start = screen.query_one("#rs-start", tui.Button)
        screen.query_one("#rs-check", tui.Button).press()
        await _wait_for(pilot, lambda: not start.disabled, "first check")
        assert len(save_calls) == 0

        # 2. Change to auto and check: saves auto
        mode_select.value = "auto"
        await pilot.pause()
        assert start.disabled
        screen.query_one("#rs-check", tui.Button).press()
        await _wait_for(pilot, lambda: not start.disabled, "second check")
        assert len(save_calls) == 1
        assert save_calls[-1][1] == "auto"
        assert relay_ops.resolve_mode(tmp_path) == "auto"

        # 3. Dismiss popup
        screen.dismiss(None)
        await pilot.pause()

        # 4. Reopen Set up: shows auto
        screen2, _ = await _open(app, pilot)
        assert screen2.query_one("#rs-resolve-mode", tui.Select).value == "auto"

        # 5. Untouched check on reopening: does not write again
        save_calls.clear()
        start2 = screen2.query_one("#rs-start", tui.Button)
        screen2.query_one("#rs-check", tui.Button).press()
        await _wait_for(pilot, lambda: not start2.disabled, "third check")
        assert len(save_calls) == 0


async def test_relay_setup_screen_with_no_agents(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: [])
    from whyline.console.relay_screens import NO_AGENTS_SETUP

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        # mounts without raising and shows the message
        assert any(NO_AGENTS_SETUP in str(label.renderable) for label in screen.query(tui.Label))
        assert screen.query_one("#rs-check", tui.Button).disabled
        assert screen.query_one("#rs-start", tui.Button).disabled
        assert screen.query_one("#rs-make-plan", tui.Button).disabled
        assert not screen.query_one("#rs-cancel", tui.Button).disabled
        screen.query_one("#rs-cancel", tui.Button).press()
        await pilot.pause()
        assert results == [None]


async def test_relay_setup_screen_with_one_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: ["codex"])
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "codex",
            "tester": "codex",
            "reviewer": "codex",
            "backup": ["codex"],
        },
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        assert screen.query_one("#rs-implementer", tui.Select).value == "codex"
        assert not screen.query_one("#rs-check", tui.Button).disabled



