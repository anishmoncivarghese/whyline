from pathlib import Path

import pytest

from whyline.console import plan_job, relay_ops


class Asked(Exception):
    def __init__(self, questions, agent):
        super().__init__("asked")
        self.questions, self.agent = questions, agent


class InProgress(Exception):
    pass


@pytest.fixture(autouse=True)
def errors(monkeypatch):
    monkeypatch.setattr(relay_ops, "plan_questions_error", lambda: Asked)
    monkeypatch.setattr(relay_ops, "in_progress_error", lambda: InProgress)


def _draft(tmp_path, text="- [ ] T-1: build it\n  do it\n", source="planner", agent=""):
    path = tmp_path / "draft.md"
    path.write_text(text)
    return relay_ops.Draft(path=path, text=text, drafted_by="codex", source=source, agent=agent)


def test_a_draft_request_saves_the_agents_then_drafts(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(relay_ops, "save_planner", lambda root, d, r: calls.append(("planner", d, r)))
    monkeypatch.setattr(relay_ops, "draft_plan",
                        lambda root, desc, refs, progress: calls.append(("draft", desc, refs)) or _draft(tmp_path))
    request = plan_job.PlanRequest("draft", "p", description="Build", refs=("PRD.md",),
                                   drafter="claude", reviewer="codex")
    outcome = plan_job.run_request(tmp_path, request, lambda line: None)
    assert calls == [("planner", "claude", "codex"), ("draft", "Build", ["PRD.md"])]
    assert outcome.kind == "draft"


def test_draft_request_raises_runtime_error_if_in_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "save_planner", lambda *a: None)

    def raise_in_progress(*a, **k):
        raise InProgress("already drafting")

    monkeypatch.setattr(relay_ops, "draft_plan", raise_in_progress)
    request = plan_job.PlanRequest("draft", "p", description="Build", drafter="claude", reviewer="codex")
    with pytest.raises(RuntimeError, match="A plan draft is already unfinished"):
        plan_job.run_request(tmp_path, request, lambda line: None)


def test_resume_request_resumes_draft(tmp_path, monkeypatch):
    resumed = []
    monkeypatch.setattr(relay_ops, "resume_draft",
                        lambda root, progress: resumed.append(root) or _draft(tmp_path))
    request = plan_job.PlanRequest("resume", "p")
    outcome = plan_job.run_request(tmp_path, request, lambda line: None)
    assert resumed == [tmp_path]
    assert outcome.kind == "draft"


def test_brainstorm_request_runs_brainstorm_then_plans(tmp_path, monkeypatch):
    from whyline.console import adapters
    from collections import namedtuple

    BrainstormResult = namedtuple("BrainstormResult", ["kind", "text"])
    calls = []

    def mock_brainstorm(root, progress=None, **choice):
        calls.append(("brainstorm", choice))
        return BrainstormResult(kind="ok", text="done")

    def mock_plan(root, topic, agent, progress=None, timeout_minutes=None):
        calls.append(("plan", topic, agent, timeout_minutes))
        return _draft(tmp_path, source="brainstorm", agent=agent)

    monkeypatch.setattr(adapters, "run_brainstorm", mock_brainstorm)
    monkeypatch.setattr(relay_ops, "plan_from_brainstorm", mock_plan)

    choice = {"topic": "idea", "final_agent": "claude", "timeout_minutes": 10}
    request = plan_job.PlanRequest("brainstorm", "p", brainstorm=choice)
    outcome = plan_job.run_request(tmp_path, request, lambda line: None)
    assert calls == [
        ("brainstorm", choice),
        ("plan", "idea", "claude", 10),
    ]
    assert outcome.kind == "draft"


def test_brainstorm_request_raises_runtime_error_on_failure(tmp_path, monkeypatch):
    from whyline.console import adapters
    from collections import namedtuple

    BrainstormResult = namedtuple("BrainstormResult", ["kind", "text"])
    monkeypatch.setattr(adapters, "run_brainstorm", lambda *a, **k: BrainstormResult(kind="error", text="failed to brainstorm"))

    choice = {"topic": "idea", "final_agent": "claude", "timeout_minutes": 10}
    request = plan_job.PlanRequest("brainstorm", "p", brainstorm=choice)
    with pytest.raises(RuntimeError, match="failed to brainstorm"):
        plan_job.run_request(tmp_path, request, lambda line: None)


def test_planner_questions_become_a_questions_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "save_planner", lambda *a: None)

    def ask(*a, **k):
        raise Asked(("Which broker?",), "claude")

    monkeypatch.setattr(relay_ops, "draft_plan", ask)
    outcome = plan_job.run_request(
        tmp_path, plan_job.PlanRequest("draft", "p", description="x", drafter="codex", reviewer="claude"),
        lambda line: None)
    assert outcome == plan_job.Outcome("questions", None, ("Which broker?",), "claude")


def test_open_questions_in_a_brainstorm_draft_are_questions(tmp_path, monkeypatch):
    text = "## Open questions\n1. Paper trading?\n\n- [ ] T-1: x\n"
    monkeypatch.setattr(relay_ops, "plan_from_brainstorm",
                        lambda root, topic, agent, progress: _draft(tmp_path, text, "brainstorm", "codex"))
    outcome = plan_job.run_request(
        tmp_path, plan_job.PlanRequest("existing", "p", topic="t", writer="codex"), lambda l: None)
    assert outcome.kind == "questions" and outcome.questions == ("Paper trading?",)
    assert outcome.draft is not None and outcome.asker == "codex"


def test_answers_go_to_the_planner_when_it_stopped_to_ask(tmp_path, monkeypatch):
    got = []
    monkeypatch.setattr(relay_ops, "answer_plan",
                        lambda root, answers, progress: got.append(answers) or _draft(tmp_path))
    outcome = plan_job.run_answer(
        tmp_path, plan_job.Outcome("questions", None, ("Q?",), "claude"), "1a", lambda l: None)
    assert got == ["1a"] and outcome.kind == "draft"


def test_answers_to_open_questions_revise_the_draft(tmp_path, monkeypatch):
    got = []
    draft = _draft(tmp_path, source="brainstorm", agent="codex")
    monkeypatch.setattr(relay_ops, "revise_plan",
                        lambda root, d, feedback, progress: got.append(feedback) or _draft(tmp_path))
    plan_job.run_answer(tmp_path, plan_job.Outcome("questions", draft, ("Q?",), "codex"),
                        "yes", lambda l: None)
    assert got == [relay_ops.question_feedback(("Q?",), "yes")]


def test_run_revision_delegates_to_revise_plan(tmp_path, monkeypatch):
    revised = []
    draft = _draft(tmp_path, source="planner")
    monkeypatch.setattr(relay_ops, "revise_plan",
                        lambda root, d, feedback, progress: revised.append((d, feedback)) or _draft(tmp_path))
    outcome = plan_job.run_revision(tmp_path, draft, "make it faster", lambda l: None)
    assert revised == [(draft, "make it faster")]
    assert outcome.kind == "draft"


def test_summary_lists_tasks_and_how_to_approve(tmp_path):
    text = "".join(f"- [ ] T-{n}: task {n}\n  do it\n" for n in range(1, 18))
    shown = plan_job.summary(_draft(tmp_path, text), "My Plan")
    assert "17 tasks" in shown and "T-15: task 15" in shown and "T-16" not in shown
    assert "and 2 more" in shown and "plans/my-plan.plan.md" in shown and '"approve"' in shown


def test_summary_with_few_tasks_has_no_more_line(tmp_path):
    text = "- [ ] T-1: task 1\n  do it\n"
    shown = plan_job.summary(_draft(tmp_path, text), "My Plan")
    assert "1 tasks" in shown and "T-1: task 1" in shown
    assert "more" not in shown


def test_summary_of_an_unusable_draft_says_so(tmp_path):
    assert "no usable tasks" in plan_job.summary(_draft(tmp_path, "prose\n"), "p")


def test_questions_text_numbers_them():
    text = plan_job.questions_text(plan_job.Outcome("questions", None, ("A?", "B?"), "claude"))
    assert text.splitlines()[:3] == [
        "claude needs answers before the plan can continue:", "  1. A?", "  2. B?",
    ]


def test_questions_text_without_asker_defaults():
    text = plan_job.questions_text(plan_job.Outcome("questions", None, ("A?",), ""))
    assert text.splitlines()[0] == "The agent needs answers before the plan can continue:"
