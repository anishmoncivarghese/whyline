import pytest

from whyline.console import plan_job, relay_ops, tui

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

REQUEST = plan_job.PlanRequest("draft", "My Plan", description="x", drafter="codex", reviewer="claude")


def _lines(app):
    return [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]


async def _wait_for(pilot, condition, what):
    for _ in range(100):
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
