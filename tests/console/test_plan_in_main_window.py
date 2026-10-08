import pytest

from whyline.console import plan_job, relay_ops, tui

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

REQUEST = plan_job.PlanRequest("draft", "My Plan", description="x", drafter="codex", reviewer="claude")


def _lines(app):
    try:
        log = app.query_one("#transcript", tui.RichLog)
    except Exception:
        log = getattr(app, "_transcript", None)
        if log is None:
            raise
    return [str(line) for line in log.lines]


async def _wait_for(pilot, condition, what):
    # Up to 20 s: slow CI machines (Windows) took longer than 5 s to approve.
    # A passing condition returns at once, so this costs nothing when fast.
    for _ in range(400):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what}")


def _draft(tmp_path, text="- [ ] T-1: build it\n  do it\n"):
    path = tmp_path / "draft.md"
    path.write_text(text)
    return relay_ops.Draft(path=path, text=text, drafted_by="codex", source="planner")


def _git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    return path.resolve()


@pytest.fixture(autouse=True)
def no_trust_question(monkeypatch):
    monkeypatch.setattr(relay_ops, "antigravity_state", lambda root: "trusted")


async def _type(app, pilot, text):
    app.query_one("#prompt", tui.Input).value = text
    await pilot.press("enter")
    await pilot.pause()


async def test_progress_streams_then_review_then_approve(tmp_path, monkeypatch):
    def run(root, request, progress):
        progress("codex is drafting the plan")
        return plan_job.Outcome("draft", _draft(tmp_path))

    monkeypatch.setattr(plan_job, "run_request", run)
    approved = []
    monkeypatch.setattr(relay_ops, "approve_plan",
                        lambda root, d, name, replace=False: approved.append(name)
                        or root / "plans" / "my-plan.plan.md")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        assert any("plan · codex is drafting the plan" in l for l in _lines(app))
        assert any("1 tasks" in l or "T-1: build it" in l for l in _lines(app))
        assert app.query_one("#plan-actions").display
        await _type(app, pilot, "approve")
        assert approved == ["My Plan"] and app._plan_state == ""
        assert any("Saved plans/my-plan.plan.md" in l for l in _lines(app))


async def test_other_text_in_review_requests_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", _draft(tmp_path)))
    revised = []
    monkeypatch.setattr(plan_job, "run_revision",
                        lambda root, d, feedback, progress: revised.append(feedback)
                        or plan_job.Outcome("draft", _draft(tmp_path)))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        await _type(app, pilot, "split T-1 into two tasks")
        await _wait_for(pilot, lambda: revised, "revision")
    assert revised == ["split T-1 into two tasks"]


async def test_questions_are_numbered_and_answers_reach_the_job(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, progress: plan_job.Outcome(
        "questions", None, ("Which broker? (a) Kite (b) Upstox", "Paper trading?"), "claude"))
    answered = []
    monkeypatch.setattr(plan_job, "run_answer",
                        lambda root, outcome, answers, progress: answered.append(answers)
                        or plan_job.Outcome("draft", _draft(tmp_path)))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "answering", "answering state")
        assert any("1. Which broker? (a) Kite (b) Upstox" in l for l in _lines(app))
        assert "answering" in app.sub_title
        await _type(app, pilot, "1a, 2: yes but only for the pilot")
        await _wait_for(pilot, lambda: app._plan_state == "review", "review after answers")
    assert answered == ["1a, 2: yes but only for the pilot"]


async def test_slash_commands_still_work_while_reviewing(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", _draft(tmp_path)))
    revised = []
    monkeypatch.setattr(plan_job, "run_revision", lambda *a: revised.append(a))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        await _type(app, pilot, "/help")
        assert revised == [] and app._plan_state == "review"


async def test_a_failure_is_reported_and_leaves_the_state(tmp_path, monkeypatch):
    def fail(root, req, progress):
        raise RuntimeError("codex timed out")

    monkeypatch.setattr(plan_job, "run_request", fail)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: any("codex timed out" in l for l in _lines(app)), "error")
        assert app._plan_state == ""


async def test_discard_drops_the_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", _draft(tmp_path)))
    dropped = []
    monkeypatch.setattr(relay_ops, "discard_draft", lambda root, d: dropped.append(d))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        await pilot.click("#plan-discard")
        await pilot.pause()
        assert app._plan_state == "" and len(dropped) == 1


async def test_approving_over_an_existing_plan_asks_first(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", _draft(tmp_path)))
    calls = []

    class Exists(RuntimeError):
        pass

    def approve(root, d, name, replace=False):
        calls.append(replace)
        if not replace:
            raise Exists()
        return root / "plans" / "my-plan.plan.md"

    monkeypatch.setattr(relay_ops, "plan_exists_error", lambda: Exists)
    monkeypatch.setattr(relay_ops, "approve_plan", approve)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        await pilot.click("#plan-approve")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
    assert calls == [False, True]


async def test_view_draft_opens_the_full_text(tmp_path, monkeypatch):
    from whyline.console.relay_screens import PlanDraftScreen

    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", _draft(tmp_path)))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        await pilot.click("#plan-view")
        await pilot.pause()
        assert isinstance(app.screen, PlanDraftScreen)


async def test_escape_leaves_plan_review(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", _draft(tmp_path)))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        await pilot.press("escape")
        await pilot.pause()
        assert app._plan_state == ""
        assert any("Left the plan" in l for l in _lines(app))


async def test_open_relay_plan_refused_while_plan_in_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", _draft(tmp_path)))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        app._open_relay_plan()
        assert any("A plan is already in progress" in l for l in _lines(app))


async def test_repo_switch_cancelled_during_plan_review_retains_review(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo_a = _git_repo(tmp_path / "repo_a")
    repo_b = _git_repo(tmp_path / "repo_b")
    draft = _draft(repo_a)
    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", draft))
    approved = []
    monkeypatch.setattr(relay_ops, "approve_plan",
                        lambda root, d, name, replace=False: approved.append((root, name))
                        or root / "plans" / "my-plan.plan.md")

    app = tui.WhylineConsoleApp(root=repo_a)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        assert app.query_one("#plan-actions").display
        assert app._plan_request is not None
        assert app._plan_outcome is not None

        await _type(app, pilot, f"/repo {repo_b}")
        await _wait_for(pilot, lambda: isinstance(app.screen, tui.ConfirmScreen), "confirm screen")
        await pilot.click("#cancel")
        await pilot.pause()

        assert app.session.root == repo_a
        assert app._plan_state == "review"
        assert app._plan_request is not None
        assert app._plan_outcome is not None
        assert app.query_one("#plan-actions").display
        assert draft.path.exists()
        assert any("Staying put." in l for l in _lines(app))

        await _type(app, pilot, "approve")
        assert approved == [(repo_a, "My Plan")]
        assert app._plan_state == ""


async def test_repo_switch_confirmed_during_plan_review_clears_plan_state_and_preserves_draft(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo_a = _git_repo(tmp_path / "repo_a")
    repo_b = _git_repo(tmp_path / "repo_b")
    draft = _draft(repo_a)
    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", draft))
    approved = []
    monkeypatch.setattr(relay_ops, "approve_plan",
                        lambda root, d, name, replace=False: approved.append((root, name))
                        or root / "plans" / "my-plan.plan.md")

    app = tui.WhylineConsoleApp(root=repo_a)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        assert app.query_one("#plan-actions").display
        assert app._plan_request is not None
        assert app._plan_outcome is not None

        await _type(app, pilot, f"/repo {repo_b}")
        await _wait_for(pilot, lambda: isinstance(app.screen, tui.ConfirmScreen), "confirm screen")
        await pilot.click("#confirm")
        await pilot.pause()

        assert app.session.root == repo_b
        assert app._plan_state == ""
        assert app._plan_request is None
        assert app._plan_outcome is None
        assert not app.query_one("#plan-actions").display
        assert draft.path.exists()
        assert any("Now working in repo_b" in l for l in _lines(app))

        await _type(app, pilot, "approve")
        assert approved == []


async def test_repo_switch_confirmed_during_answering_clears_plan_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo_a = _git_repo(tmp_path / "repo_a")
    repo_b = _git_repo(tmp_path / "repo_b")
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, progress: plan_job.Outcome(
        "questions", None, ("Which broker?",), "claude"))

    app = tui.WhylineConsoleApp(root=repo_a)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "answering", "answering state")
        assert app._plan_request is not None
        assert app._plan_outcome is not None

        await _type(app, pilot, f"/repo {repo_b}")
        await _wait_for(pilot, lambda: isinstance(app.screen, tui.ConfirmScreen), "confirm screen")
        await pilot.click("#confirm")
        await pilot.pause()

        assert app.session.root == repo_b
        assert app._plan_state == ""
        assert app._plan_request is None
        assert app._plan_outcome is None
        assert not app.query_one("#plan-actions").display


async def test_synthesis_approve_starts_the_spec_job(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome(
        "draft", stage="synthesis", text="Use SQLite.", topic="t", writer="claude"))
    started = []
    monkeypatch.setattr(plan_job, "run_spec_from_synthesis",
                        lambda root, req, out, p: started.append(out.topic) or plan_job.Outcome(
                            "draft", _draft(tmp_path, "# Spec\n## Why\n"), stage="spec"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "synthesis review")
        assert "synthesis review" in app.sub_title
        assert any("Use SQLite." in l for l in _lines(app))
        await _type(app, pilot, "approve")
        await _wait_for(pilot, lambda: started == ["t"], "spec job")
        await _wait_for(pilot, lambda: "spec review" in app.sub_title, "spec review")


async def test_spec_approve_commits_then_plans_from_it(tmp_path, monkeypatch):
    spec_draft = _draft(tmp_path, "# Spec\n")
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome("draft", spec_draft, stage="spec"))
    monkeypatch.setattr(relay_ops, "approve_spec", lambda root, d, name, replace=False: root / "docs/specs/my-plan.md")
    planned = []
    monkeypatch.setattr(plan_job, "run_plan_from_spec",
                        lambda root, req, spec, p: planned.append(spec) or plan_job.Outcome("draft", _draft(tmp_path)))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: "spec review" in app.sub_title, "spec review")
        await _type(app, pilot, "approve")
        await _wait_for(pilot, lambda: "plan review" in app.sub_title, "plan review")
    assert planned == [tmp_path / "docs/specs/my-plan.md"]
    assert any("Saved docs/specs/my-plan.md" in l for l in _lines(app))


async def test_plan_failure_after_spec_approval_keeps_the_spec(tmp_path, monkeypatch):
    spec_draft = _draft(tmp_path, "# Spec\n")
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome("draft", spec_draft, stage="spec"))
    monkeypatch.setattr(relay_ops, "approve_spec", lambda root, d, name, replace=False: root / "docs/specs/my-plan.md")

    def boom(root, req, spec, p):
        raise RuntimeError("codex timed out")

    monkeypatch.setattr(plan_job, "run_plan_from_spec", boom)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: "spec review" in app.sub_title, "spec review")
        await _type(app, pilot, "approve")
        await _wait_for(pilot, lambda: any("codex timed out" in l for l in _lines(app)), "failure")
        failure = next(l for l in _lines(app) if "codex timed out" in l)
    assert "docs/specs/my-plan.md is saved" in failure and "Resume draft" in failure


async def test_view_buttons_and_screens_by_stage(tmp_path, monkeypatch):
    from whyline.console.relay_screens import PlanDraftScreen

    # Synthesis stage
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome(
        "draft", stage="synthesis", text="Use SQLite.", topic="t", writer="claude"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "synthesis review")
        view_button = app.query_one("#plan-view", tui.Button)
        assert str(view_button.label) == "View full"
        await pilot.click("#plan-view")
        await pilot.pause()
        assert isinstance(app.screen, PlanDraftScreen)
        assert app.screen._text == "Use SQLite."
        await pilot.click("#pd-close")
        await pilot.pause()

    # Spec stage
    spec_draft = _draft(tmp_path, "# Spec\n## Decisions\n")
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome("draft", spec_draft, stage="spec"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "spec review")
        view_button = app.query_one("#plan-view", tui.Button)
        assert str(view_button.label) == "View spec"
        await pilot.click("#plan-view")
        await pilot.pause()
        assert isinstance(app.screen, PlanDraftScreen)
        assert app.screen._text == "# Spec\n## Decisions\n"


async def test_synthesis_change_request_calls_run_synthesis_change(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome(
        "draft", stage="synthesis", text="Use SQLite.", topic="t", writer="claude"))
    changed = []
    monkeypatch.setattr(plan_job, "run_synthesis_change",
                        lambda root, req, out, fb, p: changed.append(fb) or out)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "synthesis review")
        await _type(app, pilot, "prefer postgres")
        await _wait_for(pilot, lambda: changed == ["prefer postgres"], "synthesis change")


async def test_synthesis_questions_routed_as_change_request(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome(
        "questions", stage="synthesis", text="Body", questions=("Postgres or SQLite?",), asker="claude", topic="t", writer="claude"))
    changed = []
    monkeypatch.setattr(plan_job, "run_synthesis_change",
                        lambda root, req, out, fb, p: changed.append(fb) or plan_job.Outcome("draft", stage="synthesis", text="Use SQLite.", topic="t", writer="claude"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "answering", "synthesis answering")
        await _type(app, pilot, "SQLite")
        await _wait_for(pilot, lambda: changed, "synthesis answered")
    assert "SQLite" in changed[0]


async def test_spec_approval_passes_spec_to_approve_plan(tmp_path, monkeypatch):
    spec_draft = _draft(tmp_path, "# Spec\n")
    plan_draft = _draft(tmp_path, "- [ ] T-1: task\n")
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome("draft", spec_draft, stage="spec"))
    monkeypatch.setattr(relay_ops, "approve_spec", lambda root, d, name, replace=False: root / "docs/specs/my-plan.md")
    monkeypatch.setattr(plan_job, "run_plan_from_spec",
                        lambda root, req, spec, p: plan_job.Outcome("draft", plan_draft, stage="plan"))
    passed_spec = []
    monkeypatch.setattr(relay_ops, "approve_plan",
                        lambda root, d, name, replace=False, spec="": passed_spec.append(spec) or root / "plans/my-plan.plan.md")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: "spec review" in app.sub_title, "spec review")
        await _type(app, pilot, "approve")
        await _wait_for(pilot, lambda: "plan review" in app.sub_title, "plan review")
        await _type(app, pilot, "approve")
        await _wait_for(pilot, lambda: app._plan_state == "", "plan approved")
    assert passed_spec == ["docs/specs/my-plan.md"]


async def test_spec_exists_asks_for_confirmation(tmp_path, monkeypatch):
    spec_draft = _draft(tmp_path, "# Spec\n")
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome("draft", spec_draft, stage="spec"))
    calls = []

    class Exists(RuntimeError):
        pass

    def approve(root, d, name, replace=False):
        calls.append(replace)
        if not replace:
            raise Exists()
        return root / "docs/specs/my-plan.md"

    monkeypatch.setattr(relay_ops, "plan_exists_error", lambda: Exists)
    monkeypatch.setattr(relay_ops, "approve_spec", approve)
    monkeypatch.setattr(plan_job, "run_plan_from_spec", lambda root, req, s, p: plan_job.Outcome("draft", _draft(tmp_path)))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: "spec review" in app.sub_title, "spec review")
        await pilot.click("#plan-approve")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
        await _wait_for(pilot, lambda: "plan review" in app.sub_title, "plan review")
    assert calls == [False, True]


async def test_spec_discard_drops_spec_draft(tmp_path, monkeypatch):
    spec_draft = _draft(tmp_path, "# Spec\n")
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome("draft", spec_draft, stage="spec"))
    dropped = []
    monkeypatch.setattr(relay_ops, "discard_spec", lambda root: dropped.append(root))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: "spec review" in app.sub_title, "spec review")
        await pilot.click("#plan-discard")
        await pilot.pause()
        assert app._plan_state == ""
    assert len(dropped) == 1


async def test_spec_change_request_calls_run_revision(tmp_path, monkeypatch):
    spec_draft = _draft(tmp_path, "# Spec\n")
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome("draft", spec_draft, stage="spec"))
    revised = []
    monkeypatch.setattr(plan_job, "run_revision",
                        lambda root, out, fb, p: revised.append((getattr(out, "stage", None), fb)) or out)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: "spec review" in app.sub_title, "spec review")
        await _type(app, pilot, "add section on testing")
        await _wait_for(pilot, lambda: revised, "spec revision")
    assert revised == [("spec", "add section on testing")]


async def test_placeholders_by_stage(tmp_path, monkeypatch):
    # Synthesis placeholder
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome(
        "draft", stage="synthesis", text="Use SQLite.", topic="t", writer="claude"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: "synthesis review" in app.sub_title, "synthesis review")
        assert app.query_one("#prompt", tui.Input).placeholder == 'Type "approve" to write the spec, or say what to change'

    # Spec placeholder
    spec_draft = _draft(tmp_path, "# Spec\n")
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome("draft", spec_draft, stage="spec"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: "spec review" in app.sub_title, "spec review")
        assert app.query_one("#prompt", tui.Input).placeholder == 'Type "approve" to save the spec and write the plan, or say what to change'

    # Plan placeholder
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome("draft", _draft(tmp_path), stage="plan"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: "plan review" in app.sub_title, "plan review")
        assert app.query_one("#prompt", tui.Input).placeholder == 'Type "approve", or say what to change (Enter to send)'


async def test_synthesis_discard_leaves_flow_and_preserves_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome(
        "draft", stage="synthesis", text="Use SQLite.", topic="t", writer="claude"))
    checkpoint = tmp_path / ".whyline" / "relay" / "plan-state.json"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text('{"description": "pending plan"}', encoding="utf-8")

    discard_calls = []
    monkeypatch.setattr(relay_ops, "discard_draft", lambda root, d: discard_calls.append(("draft", d)))
    monkeypatch.setattr(relay_ops, "discard_spec", lambda root: discard_calls.append("spec"))

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: "synthesis review" in app.sub_title, "synthesis review")
        await pilot.click("#plan-discard")
        await pilot.pause()
        assert app._plan_state == ""
    assert discard_calls == []
    assert checkpoint.exists()
    assert checkpoint.read_text(encoding="utf-8") == '{"description": "pending plan"}'


async def test_spec_exists_with_plan_request_replace_still_asks_for_confirmation(tmp_path, monkeypatch):
    from dataclasses import replace as dc_replace

    request_with_replace = dc_replace(REQUEST, replace=True)
    spec_draft = _draft(tmp_path, "# Spec\n")
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome("draft", spec_draft, stage="spec"))
    calls = []

    class Exists(RuntimeError):
        pass

    def approve(root, d, name, replace=False):
        calls.append(replace)
        if not replace:
            raise Exists()
        return root / "docs/specs/my-plan.md"

    monkeypatch.setattr(relay_ops, "plan_exists_error", lambda: Exists)
    monkeypatch.setattr(relay_ops, "approve_spec", approve)
    monkeypatch.setattr(plan_job, "run_plan_from_spec", lambda root, req, s, p: plan_job.Outcome("draft", _draft(tmp_path)))
    plan_calls = []
    monkeypatch.setattr(
        relay_ops,
        "approve_plan",
        lambda root, d, name, replace=False, spec="": plan_calls.append(replace) or root / "plans/my-plan.plan.md",
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(request_with_replace)
        await _wait_for(pilot, lambda: "spec review" in app.sub_title, "spec review")
        await pilot.click("#plan-approve")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
        await _wait_for(pilot, lambda: "plan review" in app.sub_title, "plan review")
        await pilot.click("#plan-approve")
        await _wait_for(pilot, lambda: app._plan_state == "", "plan approved")
    assert calls == [False, True]
    assert plan_calls == [True]
