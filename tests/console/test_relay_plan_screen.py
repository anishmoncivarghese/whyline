from pathlib import Path

import pytest

from whyline.console import plan_job, relay_ops, tui
from whyline.console.chain_editor import OrderedChain
from whyline.console.relay_screens import PlanDraftScreen, RelayPlanScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

STATUS = {
    agent: {"available": agent in ("claude", "codex"), "label": "ok"}
    for agent in ("claude", "codex", "antigravity", "grok")
}


class PlanExists(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def quiet_ops(monkeypatch):
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: None)
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: [])
    monkeypatch.setattr(relay_ops, "plan_exists_error", lambda: PlanExists)
    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok"]
    )
    monkeypatch.setattr(relay_ops, "planner_agents", lambda root: ("codex", "claude"))


async def _open(app, pilot):
    results = []
    app.push_screen(RelayPlanScreen(app.session.root, STATUS, "claude"), results.append)
    await pilot.pause()
    return app.screen, results


def _error_text(screen):
    return str(screen.query_one("#rp-error", tui.Static).renderable)


async def test_paste_saves_a_valid_plan(tmp_path, monkeypatch):
    saved = []
    monkeypatch.setattr(
        relay_ops,
        "save_pasted_plan",
        lambda root, text, name, replace=False: saved.append((text, replace))
        or (root / "plans" / "plan.plan.md"),
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        screen.query_one("#rp-paste").load_text("- [ ] T-1: build it\n")
        await pilot.click("#rp-go")
        await pilot.pause()
    assert saved == [("- [ ] T-1: build it\n", False)]
    assert results == [tmp_path / "plans" / "plan.plan.md"]


async def test_paste_shows_why_an_invalid_plan_is_refused(tmp_path, monkeypatch):
    def refuse(root, text, name, replace=False):
        raise ValueError("no tasks found -- write each task as `- [ ] ID: title`")

    monkeypatch.setattr(relay_ops, "save_pasted_plan", refuse)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        screen.query_one("#rp-paste").load_text("just prose")
        await pilot.click("#rp-go")
        await pilot.pause()
        assert "no tasks found" in _error_text(screen)
        assert results == []


async def test_paste_over_an_existing_plan_asks_first(tmp_path, monkeypatch):
    calls = []

    def save(root, text, name, replace=False):
        calls.append(replace)
        if not replace:
            raise PlanExists("plan.plan.md already exists")
        return root / "plans" / "plan.plan.md"

    monkeypatch.setattr(relay_ops, "save_pasted_plan", save)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        screen.query_one("#rp-paste").load_text("- [ ] T-1: x\n")
        await pilot.click("#rp-go")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
    assert calls == [False, True]
    assert results == [tmp_path / "plans" / "plan.plan.md"]


async def test_only_the_chosen_sources_fields_show(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        source_select = screen.query_one("#rp-source", tui.Select)
        assert source_select.value == "brainstorm"
        expected_options = [
            ("Brainstorm it", "brainstorm"),
            ("I'll describe it", "draft"),
            ("I have a plan already", "paste"),
            ("Auto — brainstorm to implementation", "auto"),
        ]
        assert source_select._options == expected_options
        assert screen.query_one("#rp-brainstorm-group").display
        assert screen.query_one("#rp-new-group").display
        assert not screen.query_one("#rp-draft-group").display
        assert not screen.query_one("#rp-paste-group").display
        assert not screen.query_one("#rp-auto-group").display
        assert screen.query_one("#rp-drafter").display
        assert screen.query_one("#rp-reviewer").display
        assert screen.query_one("#rp-go").display
        assert not screen.query_one("#rp-check").display

        source_select.value = "draft"
        await pilot.pause()
        assert screen.query_one("#rp-draft-group").display
        assert not screen.query_one("#rp-brainstorm-group").display
        assert not screen.query_one("#rp-new-group").display
        assert not screen.query_one("#rp-paste-group").display
        assert not screen.query_one("#rp-auto-group").display
        assert screen.query_one("#rp-spec-first", tui.Checkbox).value is True
        assert screen.query_one("#rp-drafter").display
        assert screen.query_one("#rp-reviewer").display

        source_select.value = "paste"
        await pilot.pause()
        assert screen.query_one("#rp-paste-group").display
        assert not screen.query_one("#rp-draft-group").display
        assert not screen.query_one("#rp-brainstorm-group").display
        assert not screen.query_one("#rp-new-group").display
        assert not screen.query_one("#rp-auto-group").display
        assert not screen.query_one("#rp-drafter").display
        assert not screen.query_one("#rp-reviewer").display

        source_select.value = "auto"
        await pilot.pause()
        assert screen.query_one("#rp-auto-group").display
        assert screen.query_one("#rp-new-group").display
        assert not screen.query_one("#rp-brainstorm-group").display
        assert not screen.query_one("#rp-draft-group").display
        assert not screen.query_one("#rp-paste-group").display
        assert screen.query_one("#rp-drafter").display
        assert screen.query_one("#rp-reviewer").display
        assert not screen.query_one("#rp-go").display
        assert screen.query_one("#rp-check").display
        assert str(screen.query_one("#rp-check", tui.Button).label) == "Check"


async def test_plan_button_opens_the_popup_and_reports_the_saved_plan(tmp_path, monkeypatch):
    from whyline import account

    monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
    monkeypatch.setattr(
        relay_ops,
        "save_pasted_plan",
        lambda root, text, name, replace=False: root / "plans" / "plan.plan.md",
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()  # shown buttons need a layout pass before a click
        await pilot.click("#relay-plan")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        app.screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        app.screen.query_one("#rp-paste").load_text("- [ ] T-1: x\n")
        await pilot.click("#rp-go")
        await pilot.pause()
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any(
            ("Saved plans/" in line or "Saved plan" in line) and "Set up" in line for line in lines
        )




async def test_draft_needs_a_description(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "draft"
        await pilot.pause()
        await pilot.click("#rp-go")
        await pilot.pause()
        assert "Describe what the plan should build" in _error_text(screen)


async def test_an_unfinished_draft_can_be_discarded(tmp_path, monkeypatch):
    discarded = []
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: "Build it")
    monkeypatch.setattr(relay_ops, "discard_draft", lambda root, draft: discarded.append(draft))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rp-discard-draft")
        await pilot.pause()
        assert discarded == [None]
        assert _error_text(screen) == ""
        assert not screen.query_one("#rp-resume-draft").display


async def test_draft_dismisses_with_a_request_carrying_the_agents(tmp_path, monkeypatch):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "draft"
        await pilot.pause()
        screen.query_one("#rp-name", tui.Input).value = "Trading v1"
        screen.query_one("#rp-description").load_text("Build the PRD")
        screen.query_one("#rp-drafter", tui.Select).value = "grok"
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results == [
        plan_job.PlanRequest(
            "draft", "Trading v1", description="Build the PRD", drafter="grok", reviewer="claude", spec_first=True
        )
    ]


async def test_draft_spec_first_checkbox_controls_request(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "draft"
        await pilot.pause()
        checkbox = screen.query_one("#rp-spec-first", tui.Checkbox)
        assert checkbox.value is True
        checkbox.value = False
        screen.query_one("#rp-name", tui.Input).value = "Trading v1"
        screen.query_one("#rp-description").load_text("Build the PRD")
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results == [
        plan_job.PlanRequest(
            "draft", "Trading v1", description="Build the PRD", drafter="codex", reviewer="claude", spec_first=False
        )
    ]


async def test_an_empty_name_comes_from_the_description(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "draft"
        await pilot.pause()
        screen.query_one("#rp-description").load_text("Build the trading platform")
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results[0].name == "Build the trading platform"


async def test_an_existing_plan_name_asks_before_replacing(tmp_path):
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "p.plan.md").write_text("x")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "draft"
        await pilot.pause()
        screen.query_one("#rp-name", tui.Input).value = "p"
        screen.query_one("#rp-description").load_text("x")
        await pilot.click("#rp-go")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
    assert results[0].replace is True


async def test_an_existing_brainstorm_becomes_a_request(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: ["topic-a"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "brainstorm"
        await pilot.pause()
        screen.query_one("#rp-from", tui.Select).value = "topic-a"
        await pilot.pause()
        screen.query_one("#rp-drafter", tui.Select).value = "grok"
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results == [
        plan_job.PlanRequest("existing", "topic-a", topic="topic-a", writer="claude", drafter="grok", reviewer="claude")
    ]


async def test_new_brainstorm_request_carries_drafter_and_reviewer(tmp_path, monkeypatch):
    from whyline.console import tui as console_tui

    choice = {
        "topic": "Search indexing",
        "models": ["claude"],
        "writer": "claude",
        "passes": 1,
        "timeout": 30,
        "attachments": (),
    }
    monkeypatch.setattr(console_tui, "collect_brainstorm", lambda query_fn: choice)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        assert screen.query_one("#rp-source", tui.Select).value == "brainstorm"
        screen.query_one("#rp-drafter", tui.Select).value = "grok"
        screen.query_one("#rp-reviewer", tui.Select).value = "codex"
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results == [
        plan_job.PlanRequest(
            "brainstorm", "Search indexing", brainstorm=choice, drafter="grok", reviewer="codex"
        )
    ]


async def test_resume_dismisses_with_a_resume_request(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: "Build the PRD")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        await pilot.click("#rp-resume-draft")
        await pilot.pause()
    assert results == [plan_job.PlanRequest("resume", "Build the PRD")]


async def test_plan_draft_screen_closes(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        results = []
        app.push_screen(PlanDraftScreen("Draft text here"), results.append)
        await pilot.pause()
        assert isinstance(app.screen, PlanDraftScreen)
        await pilot.click("#pd-close")
        await pilot.pause()
        assert results == [None]


_EXECUTION = (
    "#rp-implementer",
    "#rp-tester",
    "#rp-exec-reviewer",
    "#rp-release",
    "#rp-chain",
    "#rp-committer",
    "#rp-replace",
    "#rp-continue-paths",
    "#rp-auto-summary",
)


async def test_other_sources_do_not_show_auto_execution_fields(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        auto = screen.query_one("#rp-auto-group")
        for widget_id in _EXECUTION:
            assert auto.query_one(widget_id)
        assert screen.query_one("#rp-replace", tui.Checkbox).value is False
        assert screen.query_one("#rp-continue-paths", tui.Checkbox).value is False
        assert str(screen.query_one("#rp-committer", tui.Static).renderable) == (
            "Committer: whyline (automatic)"
        )
        timeout = screen.query_one("#bs-timeout", tui.Select)
        assert timeout.value == 15
        assert [value for _label, value in timeout._options] == list(tui.BRAINSTORM_TIMEOUT_OPTIONS)
        assert not screen.query("#rp-run")
        assert not screen.query("#cb-timeout")
        for source in ("brainstorm", "draft", "paste"):
            screen.query_one("#rp-source", tui.Select).value = source
            await pilot.pause()
            assert not screen.query_one("#rp-auto-group").display
            for group in ("#rp-brainstorm-group", "#rp-draft-group", "#rp-paste-group"):
                assert not screen.query_one(group).query("#rp-replace")
                assert not screen.query_one(group).query("#rp-continue-paths")
                assert not screen.query_one(group).query("#rp-implementer")


async def test_pending_spec_keeps_resume_on_every_source(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "pending_spec", lambda root: "Write the spec")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        for source in ("brainstorm", "draft", "paste", "auto"):
            screen.query_one("#rp-source", tui.Select).value = source
            await pilot.pause()
            assert screen.query_one("#rp-resume-draft").display
            assert screen.query_one("#rp-discard-draft").display


async def test_auto_recommends_roles_and_reads_the_chain_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: False)
    monkeypatch.setattr(relay_ops, "usable_agents", lambda root, status: ["claude", "codex"])
    monkeypatch.setattr(relay_ops, "read_backup", lambda root: ["grok"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "auto"
        await pilot.pause()
        assert screen.query_one("#rp-implementer", tui.Select).value == "codex"
        assert screen.query_one("#rp-tester", tui.Select).value == "claude"
        assert screen.query_one("#rp-exec-reviewer", tui.Select).value == "claude"
        assert screen.query_one("#rp-release", tui.Select).value == "human"
        assert screen.query_one("#rp-chain", OrderedChain).order() == ["grok"]


async def test_configured_roles_still_take_the_chain_from_read_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: True)
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "grok",
            "tester": "claude",
            "reviewer": "codex",
            "backup": ["grok"],
        },
    )
    monkeypatch.setattr(relay_ops, "release_role", lambda root: "codex")
    monkeypatch.setattr(relay_ops, "read_backup", lambda root: ["claude"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        assert screen.query_one("#rp-implementer", tui.Select).value == "grok"
        assert screen.query_one("#rp-tester", tui.Select).value == "claude"
        assert screen.query_one("#rp-exec-reviewer", tui.Select).value == "codex"
        assert screen.query_one("#rp-release", tui.Select).value == "codex"
        assert screen.query_one("#rp-chain", OrderedChain).order() == ["claude"]


async def test_drafter_follows_the_final_writer_only_while_it_still_matches(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "auto"
        await pilot.pause()
        final = screen.query_one("#bs-final", tui.Select)
        drafter = screen.query_one("#rp-drafter", tui.Select)
        assert final.value == "claude"
        assert drafter.value == "codex"

        final.value = "grok"
        await pilot.pause()
        assert drafter.value == "codex"

        drafter.value = "grok"
        await pilot.pause()
        final.value = "claude"
        await pilot.pause()
        assert drafter.value == "claude"

        drafter.value = "codex"
        await pilot.pause()
        final.value = "grok"
        await pilot.pause()
        assert drafter.value == "codex"

        drafter.value = "grok"
        await pilot.pause()
        screen.query_one("#rp-source", tui.Select).value = "brainstorm"
        await pilot.pause()
        final.value = "claude"
        await pilot.pause()
        assert drafter.value == "grok"


async def test_auto_summary_matches_the_form_and_a_custom_pipeline(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from whyline_relay import config

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "auto"
        await pilot.pause()
        summary = str(screen.query_one("#rp-auto-summary", tui.Static).renderable)
        assert summary == relay_ops.auto_summary(screen._auto_view())
        assert "Backup: none." in summary
        await pilot.click("#rp-check")
        await pilot.pause()
        assert results == []
        assert isinstance(app.screen, RelayPlanScreen)

    request = SimpleNamespace(
        root=tmp_path,
        agents=("claude", "codex"),
        final_agent="claude",
        drafter="grok",
        reviewer="codex",
        implementer="grok",
        tester="claude",
        reviewer_role="codex",
        release="human",
        chain=("claude",),
    )
    assert relay_ops.auto_summary(request) == (
        "Claude + Codex research → Claude synthesizes → Grok drafts, Codex reviews → "
        "Grok implements, Claude tests, Codex reviews → whyline commits → you release. "
        "Backup: Claude."
    )
    assert "Backup: Claude → Codex." in relay_ops.auto_summary(
        SimpleNamespace(**{**request.__dict__, "chain": ("claude", "codex")})
    )
    assert relay_ops.auto_summary(SimpleNamespace(**{**request.__dict__, "chain": ()})) == (
        "Claude + Codex research → Claude synthesizes → Grok drafts, Codex reviews → "
        "Grok implements, Claude tests, Codex reviews → whyline commits → you release. "
        "Backup: none."
    )
    monkeypatch.setattr(config, "load", lambda root: SimpleNamespace(pipeline=object()))
    text = relay_ops.auto_summary(request)
    assert text.endswith(
        " This repo has a custom pipeline; Run updates the three role agents"
        " and leaves the other stages."
    )


def _fits(widget) -> bool:
    region = widget.region
    return region.height > 0 and region.bottom <= 24


async def test_auto_check_and_cancel_fit_on_80x24(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "auto"
        await pilot.pause()
        assert _fits(screen.query_one("#rp-check"))
        assert _fits(screen.query_one("#rp-cancel"))
        assert not screen.query("#rp-run")
