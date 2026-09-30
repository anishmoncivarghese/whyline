from pathlib import Path

import pytest

from whyline.console import relay_ops, tui
from whyline.console.relay_screens import RelayPlanScreen

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
        lambda root, text, replace=False: saved.append((text, replace)) or root / "plan.md",
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
    assert results == [tmp_path / "plan.md"]


async def test_paste_shows_why_an_invalid_plan_is_refused(tmp_path, monkeypatch):
    def refuse(root, text, replace=False):
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

    def save(root, text, replace=False):
        calls.append(replace)
        if not replace:
            raise PlanExists("plan.md already exists")
        return root / "plan.md"

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
    assert results == [tmp_path / "plan.md"]

async def test_only_the_chosen_sources_fields_show(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        assert screen.query_one("#rp-source", tui.Select).value == "draft"
        assert screen.query_one("#rp-draft-group").display
        assert not screen.query_one("#rp-paste-group").display
        screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        assert screen.query_one("#rp-paste-group").display
        assert not screen.query_one("#rp-draft-group").display


async def test_plan_button_opens_the_popup_and_reports_the_saved_plan(tmp_path, monkeypatch):
    from whyline import account

    monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
    monkeypatch.setattr(
        relay_ops, "save_pasted_plan", lambda root, text, replace=False: root / "plan.md"
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.click("#relay-plan")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        app.screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        app.screen.query_one("#rp-paste").load_text("- [ ] T-1: x\n")
        await pilot.click("#rp-go")
        await pilot.pause()
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any("Saved plan.md" in line and "Set up" in line for line in lines)


def _draft(tmp_path, text="- [ ] T-1: build it\n", source="planner"):
    path = tmp_path / "draft.md"
    path.write_text(text)
    return relay_ops.Draft(path=path, text=text, drafted_by="codex", source=source)


async def _wait_for(pilot, condition, what):
    for _ in range(100):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what}")


async def test_draft_reviews_then_approves(tmp_path, monkeypatch):
    calls = []

    def draft_plan(root, description, refs, *, progress):
        calls.append((description, refs))
        progress("codex is drafting the plan")
        return _draft(tmp_path)

    monkeypatch.setattr(relay_ops, "missing_references", lambda root, refs: [])
    monkeypatch.setattr(relay_ops, "draft_plan", draft_plan)
    monkeypatch.setattr(
        relay_ops,
        "approve_plan",
        lambda root, draft, replace=False: root / "plan.md",
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-description").load_text("Build what PRD.md describes")
        screen.query_one("#rp-refs").load_text("PRD.md\n\n  docs/b.md  \n")
        await pilot.click("#rp-go")
        await _wait_for(pilot, lambda: screen.query_one("#rp-review").display, "review")
        assert "T-1: build it" in str(screen.query_one("#rp-draft", tui.Static).renderable)
        await pilot.click("#rp-approve")
        await pilot.pause()
    assert calls == [("Build what PRD.md describes", ["PRD.md", "docs/b.md"])]
    assert results == [tmp_path / "plan.md"]


async def test_draft_reports_missing_reference_files_before_running(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "missing_references", lambda root, refs: ["nope.md"])
    monkeypatch.setattr(
        relay_ops,
        "draft_plan",
        lambda *a, **k: pytest.fail("must not draft"),
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-description").load_text("Build it")
        screen.query_one("#rp-refs").load_text("nope.md")
        await pilot.click("#rp-go")
        await pilot.pause()
        assert "nope.md" in _error_text(screen)


async def test_draft_needs_a_description(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rp-go")
        await pilot.pause()
        assert "Describe what the plan should build" in _error_text(screen)


async def test_an_agent_failure_returns_to_the_form_with_inputs_kept(tmp_path, monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("codex is not logged in")

    monkeypatch.setattr(relay_ops, "missing_references", lambda root, refs: [])
    monkeypatch.setattr(relay_ops, "draft_plan", fail)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-description").load_text("Build it")
        await pilot.click("#rp-go")
        await _wait_for(pilot, lambda: "not logged in" in _error_text(screen), "error")
        assert screen.query_one("#rp-form").display
        assert screen.query_one("#rp-description").text == "Build it"


async def test_request_changes_sends_feedback_and_shows_the_new_draft(tmp_path, monkeypatch):
    revised = []
    monkeypatch.setattr(relay_ops, "missing_references", lambda root, refs: [])
    monkeypatch.setattr(relay_ops, "draft_plan", lambda *a, **k: _draft(tmp_path))

    def revise(root, draft, feedback, *, progress):
        revised.append(feedback)
        return _draft(tmp_path, "- [ ] T-1: a\n- [ ] T-2: b\n")

    monkeypatch.setattr(relay_ops, "revise_plan", revise)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-description").load_text("Build it")
        await pilot.click("#rp-go")
        await _wait_for(pilot, lambda: screen.query_one("#rp-review").display, "review")
        await pilot.click("#rp-changes")
        await pilot.pause()
        screen.query_one("#rp-feedback", tui.Input).value = "split it in two"
        await pilot.click("#rp-send-changes")
        await _wait_for(
            pilot,
            lambda: "T-2: b" in str(screen.query_one("#rp-draft", tui.Static).renderable),
            "revised draft",
        )
    assert revised == ["split it in two"]


async def test_an_unfinished_draft_can_be_resumed(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: "Build it")
    monkeypatch.setattr(relay_ops, "resume_draft", lambda root, *, progress: _draft(tmp_path))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        assert "left unfinished" in _error_text(screen)
        await pilot.click("#rp-resume-draft")
        await _wait_for(pilot, lambda: screen.query_one("#rp-review").display, "review")


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


async def test_approving_over_an_existing_plan_asks_first(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(relay_ops, "missing_references", lambda root, refs: [])
    monkeypatch.setattr(relay_ops, "draft_plan", lambda *a, **k: _draft(tmp_path))

    def approve(root, draft, replace=False):
        calls.append(replace)
        if not replace:
            raise PlanExists("exists")
        return root / "plan.md"

    monkeypatch.setattr(relay_ops, "approve_plan", approve)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-description").load_text("Build it")
        await pilot.click("#rp-go")
        await _wait_for(pilot, lambda: screen.query_one("#rp-review").display, "review")
        await pilot.click("#rp-approve")
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
    assert calls == [False, True]
    assert results == [tmp_path / "plan.md"]


async def test_an_existing_brainstorm_doc_becomes_a_plan(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: ["trading-prd"])

    def plan_from(root, topic, agent, *, progress, timeout_minutes=None):
        calls.append((topic, agent))
        return _draft(tmp_path, source="brainstorm")

    monkeypatch.setattr(relay_ops, "plan_from_brainstorm", plan_from)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "brainstorm"
        await pilot.pause()
        assert screen.query_one("#rp-new-group").display
        assert not screen.query_one("#rp-writer-row").display
        screen.query_one("#rp-from", tui.Select).value = "trading-prd"
        await pilot.pause()
        assert not screen.query_one("#rp-new-group").display
        assert screen.query_one("#rp-writer-row").display
        screen.query_one("#rp-from", tui.Select).value = "new"
        await pilot.pause()
        assert screen.query_one("#rp-new-group").display
        assert not screen.query_one("#rp-writer-row").display
        screen.query_one("#rp-from", tui.Select).value = "trading-prd"
        await pilot.pause()
        screen.query_one("#rp-writer", tui.Select).value = "codex"
        await pilot.click("#rp-go")
        await _wait_for(pilot, lambda: screen.query_one("#rp-review").display, "review")
    assert calls == [("trading-prd", "codex")]


async def test_a_new_brainstorm_runs_then_becomes_a_plan(tmp_path, monkeypatch):
    from whyline.console import adapters
    from whyline.console.session import SessionEvent

    ran, planned = [], []

    def run_brainstorm(root, *, progress, **choice):
        ran.append(choice)
        progress("Researching independently: Claude, Codex")
        return SessionEvent(kind="output", text="done")

    def plan_from(root, topic, agent, *, progress, timeout_minutes=None):
        planned.append((topic, agent, timeout_minutes))
        return _draft(tmp_path, source="brainstorm")

    monkeypatch.setattr(adapters, "run_brainstorm", run_brainstorm)
    monkeypatch.setattr(relay_ops, "plan_from_brainstorm", plan_from)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "brainstorm"
        await pilot.pause()
        assert screen.query_one("#rp-from", tui.Select).value == "new"
        screen.query_one("#bs-topic", tui.Input).value = "trading platform"
        screen.query_one("#bs-timeout", tui.Select).value = 30
        await pilot.click("#rp-go")
        await _wait_for(pilot, lambda: screen.query_one("#rp-review").display, "review")
    assert ran[0]["topic"] == "trading platform"
    assert ran[0]["agents"] == ["claude", "codex"]
    assert planned == [("trading platform", "claude", 30)]


async def test_a_failed_brainstorm_is_shown_and_no_plan_is_made(tmp_path, monkeypatch):
    from whyline.console import adapters
    from whyline.console.session import SessionEvent

    monkeypatch.setattr(
        adapters,
        "run_brainstorm",
        lambda root, *, progress, **c: SessionEvent(
            kind="error", text="No selected agent succeeded"
        ),
    )
    monkeypatch.setattr(
        relay_ops, "plan_from_brainstorm", lambda *a, **k: pytest.fail("no plan")
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "brainstorm"
        await pilot.pause()
        screen.query_one("#bs-topic", tui.Input).value = "x"
        await pilot.click("#rp-go")
        await _wait_for(
            pilot,
            lambda: "No selected agent succeeded" in _error_text(screen),
            "error",
        )
