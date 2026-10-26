from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline import account as account_module
from whyline.account import AGENT_ORDER
from whyline.console import relay_ops, tui
from whyline.console.chain_editor import OrderedChain
from whyline.console.relay_screens import (
    CHECKING_MODELS,
    MODEL_REFRESH_FAILED,
    RelaySetupScreen,
)
from whyline.console.repl import NO_SUBSCRIPTIONS

# Captured before the autouse stub so a regression can restore the real
# `agent_status` and prove Set up does not call it.
_REAL_AGENT_STATUS = account_module.agent_status

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


def _status_map(enabled=None, available=None):
    enabled = set(AGENT_ORDER) if enabled is None else set(enabled)
    available = set(enabled) if available is None else set(available)
    status = {}
    for agent in AGENT_ORDER:
        on = agent in enabled
        ok = agent in available and on
        status[agent] = {
            "enabled": on,
            "installed": ok,
            "available": ok,
            "label": "ready" if ok else ("off in Settings" if not on else "not installed"),
            "hint": None if ok else (
                f"Open Settings or run: whyline account enable {agent}"
                if not on
                else f"Install {agent}, then /model refresh"
            ),
        }
    return status


@pytest.fixture(autouse=True)
def ops(monkeypatch):
    from whyline import account

    relay_ops.clear_antigravity_models_cache()
    relay_ops.antigravity_models(
        runner=lambda *_a, **_k: SimpleNamespace(
            returncode=0, stdout="gemini-3.8-flash-high\tGemini Flash\n"
        )
    )

    def _no_agy(*_args, **_kwargs):
        raise AssertionError("test invoked real agy")

    monkeypatch.setattr(relay_ops, "_agy_runner", _no_agy)
    monkeypatch.setattr(account, "agent_status", lambda root, which=None: _status_map())
    monkeypatch.setattr(account, "enabled_agents", lambda: set(AGENT_ORDER))
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


async def test_changing_the_timeout_and_pressing_cancel_writes_nothing(tmp_path, monkeypatch, ops):
    monkeypatch.setattr(relay_ops, "relay_timeout", lambda root: 30)
    monkeypatch.setattr(
        relay_ops, "save_timeout", lambda root, minutes: ops.append(("timeout", minutes))
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rs-timeout", tui.Select).value = 60
        await pilot.pause()
        screen.query_one("#rs-cancel", tui.Button).press()
        await _wait_for(pilot, lambda: results, "popup to close")
    assert results == [None]
    assert not [op for op in ops if op[0] == "timeout"]


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
    from whyline import account

    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: [])
    monkeypatch.setattr(account, "agent_status", lambda root, which=None: _status_map(enabled=set()))
    monkeypatch.setattr(account, "enabled_agents", lambda: set())

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        assert NO_SUBSCRIPTIONS in str(screen.query_one("#rs-empty").renderable)
        assert str(screen.query_one("#rs-open-settings", tui.Button).label) == "Open Settings"
        assert screen.query_one("#rs-open-settings").display
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





async def test_check_text_with_square_brackets_does_not_crash_set_up(tmp_path, monkeypatch, ops):
    # 2026-10-17: the relay's antigravity hint "set dir_flag in [agents.antigravity]"
    # was parsed as Textual markup and the MarkupError took the whole console down.
    hint = "fix: set dir_flag in [agents.antigravity] or allow that path in its command"
    monkeypatch.setattr(
        relay_ops,
        "run_checks",
        lambda root, plan=None: [
            relay_ops.CheckLine("ok", "codex is logged in"),
            relay_ops.CheckLine("warn", f"antigravity sandbox [/red] may refuse writes\n{hint}"),
        ],
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rs-check")
        await _wait_for(pilot, lambda: "[agents.antigravity]" in _checks_text(screen), "the hint")
        assert "[/red]" in _checks_text(screen)
        screen._error("bad table [agents.grok] in config.toml")
        await pilot.pause()
        assert "[agents.grok]" in str(screen.query_one("#rs-error", tui.Static).renderable)


async def test_backup_line_shows_and_disappears_after_save_clearing_it(tmp_path, monkeypatch):
    from whyline_relay import failover

    failover.write_override(
        tmp_path, "implementer", failover.ActiveOverride("claude", "grok", "rate-limit", "2026-10-21T10:00:00")
    )
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "grok",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["claude"],
        },
    )
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))

    def do_save(root, i, t, r, b):
        return relay_ops.clear_stale_switches(
            root,
            saved={
                "implementer": ("grok", i),
                "tester": ("codex", t),
                "reviewer": ("claude", r),
            },
        )

    monkeypatch.setattr(relay_ops, "save_roles", do_save)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        results = []
        screen = RelaySetupScreen(tmp_path, paused=True)
        app.push_screen(screen, results.append)
        await pilot.pause()

        override_widget = screen.query_one("#rs-implementer-override", tui.Static)
        assert "now on backup claude (grok hit a limit)" in str(override_widget.renderable)
        assert not override_widget.has_class("-empty")

        # Changing implementer to antigravity clears the stale switch when saved
        screen.query_one("#rs-implementer", tui.Select).value = "antigravity"
        await pilot.click("#rs-check")
        await _wait_for(
            pilot,
            lambda: not screen.query_one("#rs-start", tui.Button).disabled,
            "start enabled",
        )

        assert str(override_widget.renderable) == ""
        assert override_widget.has_class("-empty")


async def test_setup_popup_fits_80x24_with_resume_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = RelaySetupScreen(tmp_path, paused=True)
        app.push_screen(screen)
        await pilot.pause()
        resume_btn = screen.query_one("#rs-start", tui.Button)
        assert str(resume_btn.label) == "Resume"
        region = resume_btn.region
        assert region.height > 0 and region.bottom <= 24


async def test_resume_in_setup_dismisses_with_cleared_switches(tmp_path, monkeypatch):
    from whyline_relay import failover

    failover.write_override(
        tmp_path, "implementer", failover.ActiveOverride("claude", "grok", "rate-limit", "2026-10-21T10:00:00")
    )
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "grok",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["claude"],
        },
    )
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))

    def do_save(root, i, t, r, b):
        return relay_ops.clear_stale_switches(
            root,
            saved={
                "implementer": ("grok", i),
                "tester": ("codex", t),
                "reviewer": ("claude", r),
            },
        )

    monkeypatch.setattr(relay_ops, "save_roles", do_save)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        results = []
        screen = RelaySetupScreen(tmp_path, paused=True)
        app.push_screen(screen, results.append)
        await pilot.pause()

        screen.query_one("#rs-implementer", tui.Select).value = "antigravity"
        await pilot.click("#rs-check")
        await _wait_for(
            pilot,
            lambda: not screen.query_one("#rs-start", tui.Button).disabled,
            "start enabled",
        )

        await pilot.click("#rs-start")
        await pilot.pause()
        assert results == [("resume", ["implementer was on backup claude; it now uses antigravity"])]


async def test_setup_screen_saves_model_for_agents(tmp_path, monkeypatch):
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=tmp_path, check=True)

    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"]
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["grok"],
        },
    )
    proc = SimpleNamespace(
        returncode=0, stdout="gemini-3.8-flash-high\tGemini Flash\n"
    )
    relay_ops.antigravity_models(runner=lambda *a, **k: proc)
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rs-model-claude", tui.Select).value = "opus"
        screen.query_one("#rs-model-codex", tui.Select).value = "gpt-5.6-sol"
        screen.query_one("#rs-model-grok", tui.Select).value = "grok-4.6"
        screen.query_one("#rs-model-antigravity", tui.Select).value = "gemini-3.8-flash-high"

        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "check complete"
        )

    assert relay_ops.read_agent_model(tmp_path, "claude") == "opus"
    assert relay_ops.read_agent_model(tmp_path, "codex") == "gpt-5.6-sol"
    assert relay_ops.read_agent_model(tmp_path, "grok") == "grok-4.6"
    assert relay_ops.read_agent_model(tmp_path, "antigravity") == "gemini-3.8-flash-high"

    config_text = (tmp_path / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")
    assert "[agents.claude]" in config_text
    assert 'model = "opus"' in config_text
    assert "[agents.codex]" in config_text
    assert 'model = "gpt-5.6-sol"' in config_text
    assert "[agents.grok]" in config_text
    assert '"--model", "grok-4.6"' in config_text
    assert "[agents.antigravity]" in config_text
    assert '"--model", "gemini-3.8-flash-high"' in config_text


async def test_setup_screen_cli_default_removes_model(tmp_path, monkeypatch):
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=tmp_path, check=True)

    relay_ops.save_agent_model(tmp_path, "claude", "opus")
    relay_ops.save_agent_model(tmp_path, "codex", "gpt-5.6-sol")
    relay_ops.save_agent_model(tmp_path, "grok", "grok-4.6")
    relay_ops.save_agent_model(tmp_path, "antigravity", "gemini-3.8-flash-high")

    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"]
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["grok"],
        },
    )
    proc = SimpleNamespace(
        returncode=0, stdout="gemini-3.8-flash-high\tGemini Flash\n"
    )
    relay_ops.antigravity_models(runner=lambda *a, **k: proc)
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rs-model-claude", tui.Select).value = ""
        screen.query_one("#rs-model-codex", tui.Select).value = ""
        screen.query_one("#rs-model-grok", tui.Select).value = ""
        screen.query_one("#rs-model-antigravity", tui.Select).value = ""

        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "check complete"
        )

    assert relay_ops.read_agent_model(tmp_path, "claude") == ""
    assert relay_ops.read_agent_model(tmp_path, "codex") == ""
    assert relay_ops.read_agent_model(tmp_path, "grok") == ""
    assert relay_ops.read_agent_model(tmp_path, "antigravity") == ""

    config_text = (tmp_path / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")
    assert "opus" not in config_text
    assert "gpt-5.6-sol" not in config_text
    assert "grok-4.6" not in config_text
    assert "gemini-3.8-flash-high" not in config_text


async def test_setup_screen_agy_models_failure_falls_back_to_typing_name(tmp_path, monkeypatch):
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=tmp_path, check=True)

    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["antigravity", "codex"]
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "codex",
            "backup": [],
        },
    )
    relay_ops.clear_antigravity_models_cache()
    relay_ops.antigravity_models(
        runner=lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="no")
    )
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        antigravity_input = screen.query_one("#rs-model-antigravity", tui.Input)
        assert isinstance(antigravity_input, tui.Input)
        assert MODEL_REFRESH_FAILED in str(
            screen.query_one("#rs-model-status-antigravity").renderable
        )
        antigravity_input.value = "claude-opus-5-5-high"

        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "check complete"
        )

    assert relay_ops.read_agent_model(tmp_path, "antigravity") == "claude-opus-5-5-high"
    config_text = (tmp_path / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")
    assert '"--model", "claude-opus-5-5-high"' in config_text


async def test_setup_screen_fits_80x24_with_model_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"]
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["grok"],
        },
    )
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = RelaySetupScreen(tmp_path, paused=False)
        app.push_screen(screen)
        await pilot.pause()
        start_btn = screen.query_one("#rs-start", tui.Button)
        assert start_btn.region.height > 0
        assert start_btn.region.bottom <= 24
        for agent in ("claude", "codex", "grok", "antigravity"):
            assert screen.query_one(f"#rs-model-row-{agent}").display


async def test_setup_screen_refreshes_model_rows_on_backup_chain_actions(tmp_path, monkeypatch):
    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"]
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["grok"],
        },
    )
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    monkeypatch.setattr(RelaySetupScreen, "_fill_backup", lambda self: ["grok"])

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        # All 4 agents are initially in use: antigravity, codex, claude in roles; grok in backup.
        assert screen.query_one("#rs-model-row-grok").display
        assert not screen.query_one("#rs-model-row-grok").has_class("-empty")
        assert screen.query_one("#rs-model-row-antigravity").display

        # None button clears the backup chain. grok is not in any role, so its row hides.
        screen.query_one("#chain-none", tui.Button).press()
        await pilot.pause()
        chain = screen.query_one("#rs-backup", OrderedChain)
        assert chain.order() == []
        assert not screen.query_one("#rs-model-row-grok").display
        assert screen.query_one("#rs-model-row-grok").has_class("-empty")
        assert screen.query_one("#rs-model-row-antigravity").display

        # Automatic button restores grok to the backup chain.
        screen.query_one("#chain-automatic", tui.Button).press()
        await pilot.pause()
        assert chain.order() == ["grok"]
        assert screen.query_one("#rs-model-row-grok").display
        assert not screen.query_one("#rs-model-row-grok").has_class("-empty")

        # Unchecking grok in the backup chain hides its row.
        screen.query_one("#chain-check-grok", tui.Checkbox).value = False
        await pilot.pause()
        assert chain.order() == []
        assert not screen.query_one("#rs-model-row-grok").display
        assert screen.query_one("#rs-model-row-grok").has_class("-empty")

        # Re-checking grok in the backup chain restores its row.
        screen.query_one("#chain-check-grok", tui.Checkbox).value = True
        await pilot.pause()
        assert chain.order() == ["grok"]
        assert screen.query_one("#rs-model-row-grok").display
        assert not screen.query_one("#rs-model-row-grok").has_class("-empty")


async def test_setup_screen_initial_visibility_for_release_only_agent(tmp_path, monkeypatch):
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=tmp_path, check=True)

    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"]
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": [],
        },
    )
    monkeypatch.setattr(RelaySetupScreen, "_fill_backup", lambda self: [])
    monkeypatch.setattr(relay_ops, "release_role", lambda root: "grok")
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        # grok is used only in release, not in implementer, tester, reviewer, or backup.
        assert screen.query_one("#rs-model-row-grok").display
        assert not screen.query_one("#rs-model-row-grok").has_class("-empty")
        assert screen.query_one("#rs-model-row-claude").display
        assert screen.query_one("#rs-model-row-codex").display
        assert screen.query_one("#rs-model-row-antigravity").display

        screen.query_one("#rs-model-grok", tui.Select).value = "grok-4.6"
        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "check complete"
        )

    assert relay_ops.read_agent_model(tmp_path, "grok") == "grok-4.6"
    config_text = (tmp_path / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")
    assert "[agents.grok]" in config_text
    assert '"--model", "grok-4.6"' in config_text


async def test_setup_screen_refreshes_model_rows_on_release_selector_changes(tmp_path, monkeypatch):
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=tmp_path, check=True)

    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"]
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": [],
        },
    )
    monkeypatch.setattr(RelaySetupScreen, "_fill_backup", lambda self: [])
    monkeypatch.setattr(relay_ops, "release_role", lambda root: "human")
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        # grok is initially unused (release is human).
        assert not screen.query_one("#rs-model-row-grok").display
        assert screen.query_one("#rs-model-row-grok").has_class("-empty")

        # Switching release to grok reveals grok's model row.
        screen.query_one("#rs-release", tui.Select).value = "grok"
        await pilot.pause()
        assert screen.query_one("#rs-model-row-grok").display
        assert not screen.query_one("#rs-model-row-grok").has_class("-empty")

        # Choosing a model for grok and saving persists it.
        screen.query_one("#rs-model-grok", tui.Select).value = "grok-4.6"
        await pilot.click("#rs-check")
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "check complete"
        )
        assert relay_ops.read_agent_model(tmp_path, "grok") == "grok-4.6"

        # Switching release back to human hides grok's model row again.
        screen.query_one("#rs-release", tui.Select).value = "human"
        await pilot.pause()
        assert not screen.query_one("#rs-model-row-grok").display
        assert screen.query_one("#rs-model-row-grok").has_class("-empty")


async def test_setup_screen_shows_out_until_line_beside_model_row(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from whyline.console import recovery
    from whyline_relay import failover

    now = datetime(2026, 10, 19, 1, 12, 29, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", now, raising=False)

    logs_dir = tmp_path / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "T1-1-antigravity.log"
    log_file.write_text(
        'AGY_ERROR: {"modelName":"gemini-4-argon-medium","error":"Individual quota reached. Resets in 154h42m31s."}\n',
        encoding="utf-8",
    )

    failover.write_override(
        tmp_path,
        "implementer",
        failover.ActiveOverride(
            agent="claude",
            backup_for="antigravity",
            reason="rate-limit",
            since="2026-10-19T01:12:29",
            resets_at="2026-10-25T11:55:00+00:00",
        ),
    )

    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["claude"],
        },
    )
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = RelaySetupScreen(tmp_path, paused=True, focus_agent="antigravity")
        app.push_screen(screen)
        await pilot.pause()

        expected_line = "antigravity · gemini-4-argon-medium out until 25 Oct 11:55"
        row = screen.query_one("#rs-model-row-antigravity")
        assert row.display is True
        assert not row.has_class("-empty")

        out_widget = screen.query_one("#rs-model-out-antigravity", tui.Static)
        assert str(out_widget.renderable) == expected_line
        assert not out_widget.has_class("-empty")


async def test_setup_screen_shows_out_until_line_with_display_time_later_than_failure_time(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from whyline.console import recovery
    from whyline_relay import failover

    failure_time = datetime(2026, 10, 19, 1, 12, 29, tzinfo=timezone.utc)
    # Display time is 2.5 days after failure
    display_time = datetime(2026, 10, 21, 18, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", display_time, raising=False)

    logs_dir = tmp_path / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "T1-1-antigravity.log"
    log_file.write_text(
        'AGY_ERROR: {"modelName":"gemini-4-argon-medium","error":"Individual quota reached. Resets in 154h42m31s."}\n',
        encoding="utf-8",
    )

    failover.write_override(
        tmp_path,
        "implementer",
        failover.ActiveOverride(
            agent="claude",
            backup_for="antigravity",
            reason="rate-limit",
            since=failure_time.isoformat(),
            resets_at="2026-10-25T11:55:00+00:00",
        ),
    )

    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["claude"],
        },
    )
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = RelaySetupScreen(tmp_path, paused=True, focus_agent="antigravity")
        app.push_screen(screen)
        await pilot.pause()

        # Must honor the override's absolute resets_at (25 Oct 11:55), NOT recompute from display_time (which would be 28 Oct)
        expected_line = "antigravity · gemini-4-argon-medium out until 25 Oct 11:55"
        row = screen.query_one("#rs-model-row-antigravity")
        assert row.display is True
        assert not row.has_class("-empty")

        out_widget = screen.query_one("#rs-model-out-antigravity", tui.Static)
        assert str(out_widget.renderable) == expected_line
        assert not out_widget.has_class("-empty")


async def test_setup_screen_does_not_show_out_until_for_old_quota_logs_or_non_quota_state(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone
    from whyline.console import recovery

    now = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", now, raising=False)

    logs_dir = tmp_path / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    old_log = logs_dir / "T0-1-antigravity.log"
    old_log.write_text(
        'AGY_ERROR: {"modelName":"gemini-4-argon-medium","error":"Individual quota reached. Resets in 154h42m31s."}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["claude"],
        },
    )
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))

    # 1. No override and no state: old quota log must not produce out-until in Set up
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = RelaySetupScreen(tmp_path, paused=False, focus_agent="antigravity")
        app.push_screen(screen)
        await pilot.pause()

        out_widget = screen.query_one("#rs-model-out-antigravity", tui.Static)
        assert str(out_widget.renderable) == ""
        assert out_widget.has_class("-empty")

    # 2. Non-quota state (e.g. sandbox failure): old quota log must not produce out-until in Set up
    (tmp_path / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "antigravity could not run a required command",
            "log_path": str(old_log),
        }),
        encoding="utf-8",
    )
    app2 = tui.WhylineConsoleApp(root=tmp_path)
    async with app2.run_test(size=(110, 50)) as pilot:
        screen2 = RelaySetupScreen(tmp_path, paused=True, focus_agent="antigravity")
        app2.push_screen(screen2)
        await pilot.pause()

        out_widget2 = screen2.query_one("#rs-model-out-antigravity", tui.Static)
        assert str(out_widget2.renderable) == ""
        assert out_widget2.has_class("-empty")


async def test_setup_screen_honors_direct_pause_resets_at_when_display_time_is_later(tmp_path, monkeypatch):
    import json
    import os
    from datetime import datetime, timezone
    from whyline.console import recovery
    from whyline_relay import failover

    failure_time = datetime(2026, 10, 19, 1, 12, 29, tzinfo=timezone.utc)
    # Display time is 2.5 days after failure
    display_time = datetime(2026, 10, 21, 18, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", display_time, raising=False)

    logs_dir = tmp_path / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "T1-1-antigravity.log"
    log_file.write_text(
        'AGY_ERROR: {"modelName":"gemini-4-argon-medium","error":"Individual quota reached. Resets in 154h42m31s."}\n',
        encoding="utf-8",
    )
    os.utime(log_file, (failure_time.timestamp(), failure_time.timestamp()))

    # Direct pause without override:
    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "antigravity hit a usage or rate limit; try again when it resets",
            "log_path": str(log_file),
        }),
        encoding="utf-8",
    )
    os.utime(state_file, (failure_time.timestamp(), failure_time.timestamp()))

    assert failover.read_overrides(tmp_path) == {}

    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": [],
        },
    )
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))

    # 1. At display_time: shows 25 Oct 11:55, not 28 Oct
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = RelaySetupScreen(tmp_path, paused=True, focus_agent="antigravity")
        app.push_screen(screen)
        await pilot.pause()

        expected_line = "antigravity · gemini-4-argon-medium out until 25 Oct 11:55"
        row = screen.query_one("#rs-model-row-antigravity")
        assert row.display is True
        assert not row.has_class("-empty")

        out_widget = screen.query_one("#rs-model-out-antigravity", tui.Static)
        assert str(out_widget.renderable) == expected_line
        assert not out_widget.has_class("-empty")

    # 2. At expired_time (after 25 Oct 11:55): suppresses out-until
    expired_time = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", expired_time, raising=False)

    app2 = tui.WhylineConsoleApp(root=tmp_path)
    async with app2.run_test(size=(110, 50)) as pilot:
        screen2 = RelaySetupScreen(tmp_path, paused=True, focus_agent="antigravity")
        app2.push_screen(screen2)
        await pilot.pause()

        out_widget2 = screen2.query_one("#rs-model-out-antigravity", tui.Static)
        assert str(out_widget2.renderable) == ""
        assert out_widget2.has_class("-empty")


async def test_setup_screen_out_until_widget_visible_within_80_columns(tmp_path, monkeypatch):
    """Ensure at 80 columns the status widget does not overflow the model row and is fully visible."""
    import json
    from datetime import datetime, timezone
    from whyline.console import recovery
    from whyline_relay import failover

    failure_time = datetime(2026, 10, 19, 1, 12, 29, tzinfo=timezone.utc)
    display_time = datetime(2026, 10, 21, 18, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", display_time, raising=False)

    logs_dir = tmp_path / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "T1-1-antigravity.log"
    log_file.write_text(
        'AGY_ERROR: {"modelName":"gemini-4-argon-medium","error":"Individual quota reached. Resets in 154h42m31s."}\n',
        encoding="utf-8",
    )

    failover.write_override(
        tmp_path,
        "implementer",
        failover.ActiveOverride(
            agent="codex",
            backup_for="antigravity",
            reason="rate-limit",
            since=failure_time.isoformat(),
            resets_at="2026-10-25T11:55:00+00:00",
        ),
    )

    # Current state is Codex running in round 2 with its own log
    codex_log = logs_dir / "T1-2-codex.log"
    codex_log.write_text('codex --model gpt-5\n', encoding="utf-8")
    (tmp_path / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T1",
            "round": 2,
            "base_commit": "abc",
            "paused_reason": "codex could not run a required command",
            "log_path": str(codex_log),
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["codex"],
        },
    )
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = RelaySetupScreen(tmp_path, paused=True, focus_agent="antigravity")
        app.push_screen(screen)
        await pilot.pause()

        expected_line = "antigravity · gemini-4-argon-medium out until 25 Oct 11:55"
        row = screen.query_one("#rs-model-row-antigravity")
        assert row.display is True
        assert not row.has_class("-empty")

        out_widget = screen.query_one("#rs-model-out-antigravity", tui.Static)
        assert str(out_widget.renderable) == expected_line
        assert not out_widget.has_class("-empty")

        # Layout checks: widget must not overflow model row or screen bounds at 80 columns
        assert out_widget.region.x >= row.region.x
        assert out_widget.region.x + out_widget.region.width <= row.region.x + row.region.width
        assert out_widget.region.x + out_widget.region.width <= 80
        # The whole line, reset time included, fits on one row of the widget's content area
        assert out_widget.content_region.width >= len(expected_line)
        assert out_widget.region.height >= 1

        # And it is what the terminal actually shows: the full line on one screen row
        await pilot.pause()
        screen_rows = [strip.text for strip in screen._compositor.render_strips()]
        assert any(expected_line in text for text in screen_rows), "\n".join(screen_rows)


def _plain(widget) -> str:
    renderable = getattr(widget, "renderable", None)
    if renderable is None:
        return str(getattr(widget, "label", ""))
    return renderable.plain if hasattr(renderable, "plain") else str(renderable)


def _enable(monkeypatch, enabled, available=None):
    from whyline import account

    status = _status_map(enabled=enabled, available=available)
    monkeypatch.setattr(account, "agent_status", lambda root, which=None: status)
    monkeypatch.setattr(account, "enabled_agents", lambda: set(enabled))
    return status


async def test_setup_shows_checking_models_before_agy_returns(tmp_path, monkeypatch):
    import threading
    from whyline.console.settings_screen import ProviderSettingsScreen

    started = threading.Event()
    release = threading.Event()

    def blocked_agy(*_args, **_kwargs):
        started.set()
        release.wait(timeout=2)
        return SimpleNamespace(
            returncode=0,
            stdout="gemini-4-argon-high\tGemini 4 Argon (High)\n",
        )

    monkeypatch.setattr(relay_ops, "_agy_runner", blocked_agy)
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": [],
        },
    )
    _enable(monkeypatch, {"claude", "codex", "antigravity"})
    relay_ops.clear_antigravity_models_cache()

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()
        await pilot.click("#relay-setup")
        await pilot.pause()
        assert started.wait(timeout=2.0)
        screen = app.screen
        assert isinstance(screen, RelaySetupScreen)
        assert not isinstance(screen, ProviderSettingsScreen)
        assert CHECKING_MODELS in _plain(screen.query_one("#rs-model-status-antigravity"))
        assert isinstance(screen.query_one("#rs-model-antigravity"), tui.Input)
        release.set()
        await _wait_for(
            pilot,
            lambda: isinstance(screen.query_one("#rs-model-antigravity"), tui.Select),
            "antigravity dropdown",
        )
        values = [
            value
            for _label, value in screen.query_one("#rs-model-antigravity", tui.Select)._options
            if value is not tui.Select.BLANK
        ]
        assert "gemini-4-argon-high" in values


async def test_disabled_antigravity_starts_no_agy_worker(tmp_path, monkeypatch):
    called = []

    def spy(*_args, **_kwargs):
        called.append("agy")
        raise AssertionError("disabled antigravity launched agy")

    monkeypatch.setattr(relay_ops, "_agy_runner", spy)
    monkeypatch.setattr(relay_ops, "antigravity_models", spy)
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "antigravity"],
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
    _enable(monkeypatch, {"claude", "codex"})

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert called == []
        assert not screen.query("#rs-model-row-antigravity")
        assert "antigravity" not in [
            value
            for _label, value in screen.query_one("#rs-implementer", tui.Select)._options
            if value is not tui.Select.BLANK
        ]


async def test_antigravity_success_is_cached_for_the_session(tmp_path, monkeypatch):
    calls = []

    def fake_agy(*_args, **_kwargs):
        calls.append("agy")
        return SimpleNamespace(returncode=0, stdout="flash\tGemini Flash\n")

    monkeypatch.setattr(relay_ops, "_agy_runner", fake_agy)
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "claude",
            "reviewer": "claude",
            "backup": [],
        },
    )
    _enable(monkeypatch, {"claude", "antigravity"})
    relay_ops.clear_antigravity_models_cache()

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        await _wait_for(
            pilot,
            lambda: isinstance(screen.query_one("#rs-model-antigravity"), tui.Select),
            "first fetch",
        )
        assert calls == ["agy"]
        screen.dismiss(None)
        await _wait_for(pilot, lambda: results == [None], "closed")
        screen2, _ = await _open(app, pilot)
        await pilot.pause()
        assert isinstance(screen2.query_one("#rs-model-antigravity"), tui.Select)
        assert calls == ["agy"]


async def test_antigravity_negative_cache_skips_rerun_until_clock_expires(
    tmp_path, monkeypatch
):
    calls = []
    clock = {"t": 0.0}

    def fail_agy(*_args, **_kwargs):
        calls.append(clock["t"])
        return SimpleNamespace(returncode=1, stdout="", stderr="no")

    monkeypatch.setattr(relay_ops, "_agy_runner", fail_agy)
    monkeypatch.setattr(relay_ops, "_clock", lambda: clock["t"])
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["codex", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "codex",
            "backup": [],
        },
    )
    _enable(monkeypatch, {"codex", "antigravity"})
    relay_ops.clear_antigravity_models_cache()

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        await _wait_for(
            pilot,
            lambda: MODEL_REFRESH_FAILED in _plain(
                screen.query_one("#rs-model-status-antigravity")
            ),
            "first failure",
        )
        assert isinstance(screen.query_one("#rs-model-antigravity"), tui.Input)
        assert calls == [0.0]
        screen.dismiss(None)
        await _wait_for(pilot, lambda: results == [None], "closed")
        clock["t"] = 30.0
        screen2, results2 = await _open(app, pilot)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert MODEL_REFRESH_FAILED in _plain(
            screen2.query_one("#rs-model-status-antigravity")
        )
        assert calls == [0.0]
        screen2.dismiss(None)
        await _wait_for(pilot, lambda: results2 == [None], "closed again")
        clock["t"] = 60.0
        screen3, _ = await _open(app, pilot)
        await _wait_for(
            pilot,
            lambda: MODEL_REFRESH_FAILED in _plain(
                screen3.query_one("#rs-model-status-antigravity")
            )
            and len(calls) == 2,
            "retry after ttl",
        )
        assert calls == [0.0, 60.0]


async def test_late_agy_result_after_close_does_not_touch_widgets(tmp_path, monkeypatch):
    import threading

    started = threading.Event()
    release = threading.Event()

    def blocked_agy(*_args, **_kwargs):
        started.set()
        release.wait(timeout=2)
        return SimpleNamespace(returncode=0, stdout="flash\tGemini Flash\n")

    monkeypatch.setattr(relay_ops, "_agy_runner", blocked_agy)
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "claude",
            "reviewer": "claude",
            "backup": [],
        },
    )
    _enable(monkeypatch, {"claude", "antigravity"})
    relay_ops.clear_antigravity_models_cache()

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        assert started.wait(timeout=2.0)
        screen.dismiss(None)
        await _wait_for(pilot, lambda: results == [None], "closed")
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert results == [None]
        assert relay_ops.antigravity_models_status() == "ok"


async def test_stale_disabled_role_warns_and_check_fails_without_saving(
    tmp_path, monkeypatch, ops
):
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "grok",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["grok"],
        },
    )
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: True)
    monkeypatch.setattr(relay_ops, "release_role", lambda root: "human")
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    _enable(monkeypatch, {"claude", "codex"})

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        warning = _plain(screen.query_one("#rs-stale"))
        assert "grok" in warning
        assert "off in Settings" in warning
        implementer = screen.query_one("#rs-implementer", tui.Select)
        impl_values = [
            value
            for _label, value in implementer._options
            if value is not tui.Select.BLANK
        ]
        assert "grok" not in impl_values
        assert implementer.value is tui.Select.BLANK
        release_values = [
            value
            for _label, value in screen.query_one("#rs-release", tui.Select)._options
            if value is not tui.Select.BLANK
        ]
        assert "grok" not in release_values
        assert not screen.query("#chain-check-grok")
        screen.query_one("#rs-check", tui.Button).press()
        await pilot.pause()
        checks = _checks_text(screen)
        assert "FAIL" in checks
        assert "Open Settings" in checks
        assert screen.query_one("#rs-start", tui.Button).disabled
        assert ops == []
        implementer.value = "claude"
        await pilot.pause()
        assert screen.query_one("#rs-implementer", tui.Select).value == "claude"
        screen.query_one("#rs-check", tui.Button).press()
        await pilot.pause()
        still_stale = _checks_text(screen)
        assert "FAIL" in still_stale
        assert "grok" in still_stale
        assert screen.query_one("#rs-start", tui.Button).disabled
        assert ops == []
        screen.query_one("#chain-none", tui.Button).press()
        await pilot.pause()
        assert not screen.query("#chain-check-grok")
        screen.query_one("#rs-check", tui.Button).press()
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start"
        )
        assert ops[0][0] == "claude"
        screen.dismiss(None)
        await _wait_for(pilot, lambda: results == [None], "closed")


async def test_guided_stale_disabled_role_warns_and_check_fails(tmp_path, monkeypatch, ops):
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "grok",
            "tester": "codex",
            "reviewer": "claude",
            "backup": [],
        },
    )
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: True)
    monkeypatch.setattr(relay_ops, "release_role", lambda root: "human")
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    _enable(monkeypatch, {"claude", "codex"})

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        results = []
        app.push_screen(RelaySetupScreen(app.session.root, guided=True), results.append)
        await pilot.pause()
        screen = app.screen
        warning = _plain(screen.query_one("#rs-stale"))
        assert "grok" in warning
        assert "off in Settings" in warning
        implementer = screen.query_one("#rs-implementer", tui.Select)
        impl_values = [
            value
            for _label, value in implementer._options
            if value is not tui.Select.BLANK
        ]
        assert "grok" not in impl_values
        assert implementer.value is tui.Select.BLANK
        screen.query_one("#rs-check", tui.Button).press()
        await pilot.pause()
        checks = _checks_text(screen)
        assert "FAIL" in checks
        assert "Open Settings" in checks
        assert "grok" in checks
        assert screen.query_one("#rs-start", tui.Button).disabled
        assert ops == []
        implementer.value = "claude"
        await pilot.pause()
        screen.query_one("#rs-check", tui.Button).press()
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start"
        )
        assert ops[0][0] == "claude"
        screen.dismiss(None)
        await _wait_for(pilot, lambda: results == [None], "closed")


async def test_guided_first_run_does_not_treat_unsaved_defaults_as_stale(
    tmp_path, monkeypatch, ops
):
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "codex",
            "tester": "claude",
            "reviewer": "claude",
            "backup": [],
        },
    )
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: False)
    monkeypatch.setattr(relay_ops, "release_role", lambda root: "human")
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    _enable(monkeypatch, {"grok"})

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        results = []
        app.push_screen(RelaySetupScreen(app.session.root, guided=True), results.append)
        await pilot.pause()
        screen = app.screen
        assert "Recommended for the agents you have" in str(
            screen.query_one("#rs-recommended", tui.Static).renderable
        )
        assert screen.query_one("#rs-implementer", tui.Select).value == "grok"
        assert screen.query_one("#rs-tester", tui.Select).value == "grok"
        assert screen.query_one("#rs-reviewer", tui.Select).value == "grok"
        warning = _plain(screen.query_one("#rs-stale"))
        assert "Saved configuration" not in warning
        assert "codex" not in warning
        assert "claude" not in warning
        assert "off in Settings" not in warning
        screen.query_one("#rs-check", tui.Button).press()
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start"
        )
        assert ops[0][0] == "grok"
        screen.dismiss(None)
        await _wait_for(pilot, lambda: results == [None], "closed")


async def test_guided_substitutes_enabled_not_logged_in_antigravity(tmp_path, monkeypatch):
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": [],
        },
    )
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: True)
    monkeypatch.setattr(relay_ops, "release_role", lambda root: "human")
    _enable(
        monkeypatch,
        {"claude", "codex", "antigravity"},
        available={"claude", "codex"},
    )

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        app.push_screen(RelaySetupScreen(app.session.root, guided=True))
        await pilot.pause()
        screen = app.screen
        assert screen.query_one("#rs-implementer", tui.Select).value == "codex"
        assert "⚠ antigravity isn't logged in" in str(
            screen.query_one("#rs-summary", tui.Static).renderable
        )
        warning = _plain(screen.query_one("#rs-stale"))
        assert "antigravity" not in warning
        assert "off in Settings" not in warning


async def test_disabled_backup_chain_member_blocks_check_until_removed(
    tmp_path, monkeypatch, ops
):
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "claude",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["grok"],
        },
    )
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: True)
    monkeypatch.setattr(relay_ops, "release_role", lambda root: "human")
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    _enable(monkeypatch, {"claude", "codex"})

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        warning = _plain(screen.query_one("#rs-stale"))
        assert "grok" in warning
        assert "off in Settings" in warning
        assert screen.query_one("#rs-implementer", tui.Select).value == "claude"
        assert not screen.query("#chain-check-grok")
        assert screen.query_one("#rs-backup", OrderedChain).order() == []
        screen.query_one("#rs-check", tui.Button).press()
        await pilot.pause()
        checks = _checks_text(screen)
        assert "FAIL" in checks
        assert "grok" in checks
        assert "Open Settings" in checks
        assert screen.query_one("#rs-start", tui.Button).disabled
        assert ops == []

        screen.query_one("#chain-none", tui.Button).press()
        await pilot.pause()
        assert not screen.query("#chain-check-grok")
        assert "grok" not in _plain(screen.query_one("#rs-stale"))
        screen.query_one("#rs-check", tui.Button).press()
        await _wait_for(
            pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start"
        )
        assert ops[0] == ("claude", "codex", "claude", [])
        screen.dismiss(None)
        await _wait_for(pilot, lambda: results == [None], "closed")


async def test_opening_and_cancelling_does_not_rewrite_config(tmp_path, monkeypatch, ops):
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "grok",
            "tester": "codex",
            "reviewer": "claude",
            "backup": ["grok"],
        },
    )
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: True)
    _enable(monkeypatch, {"claude", "codex"})
    before = list(ops)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        assert "grok" in _plain(screen.query_one("#rs-stale"))
        await pilot.click("#rs-cancel")
        await _wait_for(pilot, lambda: results == [None], "cancelled")
    assert ops == before


async def test_set_up_with_empty_relay_agents_opens_no_subscriptions_screen(
    tmp_path, monkeypatch
):
    from whyline.console.relay_screens import NO_AGENTS_SETUP
    from whyline.console.settings_screen import ProviderSettingsScreen

    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: [])

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()
        await pilot.click("#relay-setup")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, RelaySetupScreen)
        assert len(app.screen_stack) == 2
        assert NO_SUBSCRIPTIONS in _plain(screen.query_one("#rs-empty"))
        assert screen.query_one("#rs-open-settings").display
        assert str(screen.query_one("#rs-open-settings", tui.Button).label) == "Open Settings"
        assert not screen.query("#rs-implementer")
        assert not any(
            NO_AGENTS_SETUP in getattr(event, "text", "")
            for event in app.session.transcript
        )
        await pilot.click("#rs-open-settings")
        await _wait_for(
            pilot, lambda: isinstance(app.screen, ProviderSettingsScreen), "settings"
        )


async def test_no_enabled_provider_opens_settings_action(tmp_path, monkeypatch):
    from whyline.console.settings_screen import ProviderSettingsScreen

    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex"],
    )
    _enable(monkeypatch, set())

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()
        await pilot.click("#relay-setup")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, RelaySetupScreen)
        assert NO_SUBSCRIPTIONS in _plain(screen.query_one("#rs-empty"))
        assert screen.query_one("#rs-open-settings").display
        assert str(screen.query_one("#rs-open-settings", tui.Button).label) == "Open Settings"
        assert not screen.query("#rs-implementer")
        await pilot.click("#rs-open-settings")
        await _wait_for(
            pilot, lambda: isinstance(app.screen, ProviderSettingsScreen), "settings"
        )


async def test_setup_fits_80x24_and_120x40_with_checking_and_empty_states(
    tmp_path, monkeypatch
):
    import threading

    started = threading.Event()
    release = threading.Event()

    def blocked_agy(*_args, **_kwargs):
        started.set()
        release.wait(timeout=5)
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(relay_ops, "_agy_runner", blocked_agy)
    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "antigravity"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "antigravity",
            "tester": "codex",
            "reviewer": "claude",
            "backup": [],
        },
    )
    _enable(monkeypatch, {"claude", "codex", "antigravity"})

    for size in ((80, 24), (120, 40)):
        relay_ops.clear_antigravity_models_cache()
        started.clear()
        release.clear()
        app = tui.WhylineConsoleApp(root=tmp_path)
        async with app.run_test(size=size) as pilot:
            screen, _ = await _open(app, pilot)
            await _wait_for(pilot, started.is_set, "agy started")
            for button_id in ("#rs-check", "#rs-cancel", "#rs-start"):
                region = screen.query_one(button_id).region
                assert region.height > 0
                assert region.bottom <= size[1]
            assert CHECKING_MODELS in _plain(
                screen.query_one("#rs-model-status-antigravity")
            )
            screen.dismiss(None)
            await pilot.pause()
            release.set()
            await app.workers.wait_for_complete()
            # Dismissing cancels the screen's worker, so wait_for_complete can
            # return while its thread is still running. Wait until that thread
            # records its miss; otherwise it can land after the next pass
            # clears the cache and stop that pass's fetch from starting.
            await _wait_for(
                pilot,
                lambda: relay_ops.antigravity_models_status() == "failed",
                "agy fetch recorded",
            )

    _enable(monkeypatch, set())
    for size in ((80, 24), (120, 40)):
        app = tui.WhylineConsoleApp(root=tmp_path)
        async with app.run_test(size=size) as pilot:
            screen, _ = await _open(app, pilot)
            settings = screen.query_one("#rs-open-settings")
            cancel = screen.query_one("#rs-cancel")
            assert settings.display
            assert settings.region.height > 0
            assert settings.region.bottom <= size[1]
            assert cancel.region.height > 0
            assert cancel.region.bottom <= size[1]
            assert NO_SUBSCRIPTIONS in _plain(screen.query_one("#rs-empty"))
            screen.dismiss(None)
            await pilot.pause()


async def test_construct_on_mount_and_automatic_do_not_probe_providers(
    tmp_path, monkeypatch
):
    from whyline import account, model

    probes = []

    def boom(*_args, **_kwargs):
        probes.append("probed")
        raise AssertionError("Relay Set up launched provider detection")

    monkeypatch.setattr(
        relay_ops,
        "relay_agents",
        lambda root=None, which=None: ["claude", "codex", "grok"],
    )
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "codex",
            "tester": "claude",
            "reviewer": "grok",
            "backup": [],
        },
    )
    model.set_default_agent(tmp_path, "codex")
    account.set_enabled_many(
        {"claude": True, "codex": True, "grok": True, "antigravity": False}
    )

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        # Restore the real agent_status only after the app has composed, so
        # this pins Relay Set up rather than the context bar.
        monkeypatch.setattr(account, "agent_status", _REAL_AGENT_STATUS)
        monkeypatch.setattr(account, "ensure_detected", boom)
        monkeypatch.setattr(account, "refresh", boom)
        monkeypatch.setattr(account, "detect_claude", boom)
        monkeypatch.setattr(account, "check_provider", boom)
        screen, _ = await _open(app, pilot)
        assert probes == []
        assert screen.query("#rs-implementer")
        chain = screen.query_one("#rs-backup", OrderedChain)
        screen.query_one("#chain-none", tui.Button).press()
        await pilot.pause()
        assert chain.order() == []
        screen.query_one("#chain-automatic", tui.Button).press()
        await pilot.pause()
        assert probes == []
        assert screen.query("#rs-implementer")


