from pathlib import Path

import pytest

from whyline.console import plan_job, relay_ops
from whyline.console.session import SessionEvent


class Asked(Exception):
    def __init__(self, questions, agent):
        super().__init__("asked")
        self.questions, self.agent = questions, agent


class InProgress(Exception):
    pass


@pytest.fixture(autouse=True)
def errors(monkeypatch):
    monkeypatch.setattr(relay_ops, "plan_questions_error", lambda: Asked)
    monkeypatch.setattr(relay_ops, "spec_questions_error", lambda: Asked)
    monkeypatch.setattr(relay_ops, "in_progress_error", lambda: InProgress)


def _draft(tmp_path, text="- [ ] T-1: build it\n  do it\n", source="planner", agent=""):
    path = tmp_path / "draft.md"
    path.write_text(text)
    return relay_ops.Draft(path=path, text=text, drafted_by="codex", source=source, agent=agent)


def test_outcome_and_plan_request_new_fields():
    out = plan_job.Outcome("draft")
    assert out.stage == "plan"
    assert out.text == ""
    assert out.topic == ""
    assert out.writer == ""
    req = plan_job.PlanRequest("draft", "p")
    assert req.spec_first is True


def test_a_draft_request_saves_the_agents_then_drafts_plan_when_not_spec_first(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(relay_ops, "save_planner", lambda root, d, r: calls.append(("planner", d, r)))
    monkeypatch.setattr(
        relay_ops,
        "draft_plan",
        lambda root, desc, attachments, progress, spec=None: calls.append(("draft", desc, attachments, spec)) or _draft(tmp_path),
    )
    request = plan_job.PlanRequest(
        "draft",
        "p",
        description="Build",
        attachments=(Path("PRD.md"),),
        drafter="claude",
        reviewer="codex",
        spec_first=False,
    )
    outcome = plan_job.run_request(tmp_path, request, lambda line: None)
    assert calls == [("planner", "claude", "codex"), ("draft", "Build", [Path("PRD.md")], None)]
    assert outcome.kind == "draft"
    assert outcome.stage == "plan"


def test_a_draft_request_with_spec_first_drafts_spec(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(relay_ops, "save_planner", lambda root, d, r: calls.append(("planner", d, r)))
    monkeypatch.setattr(
        relay_ops,
        "draft_spec",
        lambda root, desc, attachments, progress: calls.append(("spec", desc, attachments))
        or _draft(tmp_path, source="spec"),
    )
    request = plan_job.PlanRequest(
        "draft",
        "p",
        description="Build",
        attachments=(Path("PRD.md"),),
        drafter="claude",
        reviewer="codex",
    )
    outcome = plan_job.run_request(tmp_path, request, lambda line: None)
    assert calls == [("planner", "claude", "codex"), ("spec", "Build", [Path("PRD.md")])]
    assert outcome.kind == "draft"
    assert outcome.stage == "spec"


def test_an_unticked_spec_box_plans_directly(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(relay_ops, "save_planner", lambda *a: None)
    monkeypatch.setattr(
        relay_ops,
        "draft_plan",
        lambda root, d, a, progress, spec=None: called.append("plan") or _draft(tmp_path),
    )
    monkeypatch.setattr(relay_ops, "draft_spec", lambda *a, **k: called.append("spec"))
    plan_job.run_request(
        tmp_path,
        plan_job.PlanRequest("draft", "p", description="x", spec_first=False, drafter="codex", reviewer="claude"),
        lambda l: None,
    )
    assert called == ["plan"]


def test_draft_request_raises_runtime_error_if_in_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "save_planner", lambda *a: None)

    def raise_in_progress(*a, **k):
        raise InProgress("already drafting")

    monkeypatch.setattr(relay_ops, "draft_plan", raise_in_progress)
    request = plan_job.PlanRequest(
        "draft", "p", description="Build", drafter="claude", reviewer="codex", spec_first=False
    )
    with pytest.raises(RuntimeError, match="A plan draft is already unfinished"):
        plan_job.run_request(tmp_path, request, lambda line: None)

    monkeypatch.setattr(relay_ops, "draft_spec", raise_in_progress)
    request_spec = plan_job.PlanRequest(
        "draft", "p", description="Build", drafter="claude", reviewer="codex", spec_first=True
    )
    with pytest.raises(RuntimeError, match="A plan draft is already unfinished"):
        plan_job.run_request(tmp_path, request_spec, lambda line: None)


def test_resume_request_resumes_pending_spec_when_present(tmp_path, monkeypatch):
    resumed = []
    monkeypatch.setattr(relay_ops, "pending_spec", lambda root: "Build the spec")
    monkeypatch.setattr(
        relay_ops,
        "resume_spec",
        lambda root, progress: resumed.append(("spec", root)) or _draft(tmp_path, source="spec"),
    )
    request = plan_job.PlanRequest("resume", "p")
    outcome = plan_job.run_request(tmp_path, request, lambda line: None)
    assert resumed == [("spec", tmp_path)]
    assert outcome.kind == "draft"
    assert outcome.stage == "spec"


def test_resume_request_resumes_draft_when_no_pending_spec(tmp_path, monkeypatch):
    resumed = []
    monkeypatch.setattr(relay_ops, "pending_spec", lambda root: None)
    monkeypatch.setattr(
        relay_ops,
        "resume_draft",
        lambda root, progress: resumed.append(("plan", root)) or _draft(tmp_path),
    )
    request = plan_job.PlanRequest("resume", "p")
    outcome = plan_job.run_request(tmp_path, request, lambda line: None)
    assert resumed == [("plan", tmp_path)]
    assert outcome.kind == "draft"
    assert outcome.stage == "plan"


def test_a_brainstorm_returns_its_synthesis_for_review(tmp_path, monkeypatch):
    from whyline.console import adapters

    monkeypatch.setattr(adapters, "run_brainstorm", lambda root, **k: SessionEvent("output", "ok"))
    monkeypatch.setattr(relay_ops, "final_synthesis", lambda root, topic: "Use SQLite.")
    req = plan_job.PlanRequest(
        "brainstorm",
        "p",
        brainstorm={
            "topic": "t",
            "agents": ["claude"],
            "passes": 1,
            "final_agent": "claude",
            "timeout_minutes": 15,
            "attachments": [],
        },
    )
    out = plan_job.run_request(tmp_path, req, lambda l: None)
    assert (out.kind, out.stage, out.text, out.topic, out.writer) == (
        "draft",
        "synthesis",
        "Use SQLite.",
        "t",
        "claude",
    )


def test_a_brainstorm_with_open_questions_returns_questions_outcome(tmp_path, monkeypatch):
    from whyline.console import adapters

    synthesis_text = "Use SQLite.\n\n## Open questions\n1. Which migration tool?\n"
    monkeypatch.setattr(adapters, "run_brainstorm", lambda root, **k: SessionEvent("output", "ok"))
    monkeypatch.setattr(relay_ops, "final_synthesis", lambda root, topic: synthesis_text)
    req = plan_job.PlanRequest(
        "brainstorm",
        "p",
        brainstorm={
            "topic": "t",
            "agents": ["claude"],
            "passes": 1,
            "final_agent": "claude",
            "timeout_minutes": 15,
            "attachments": [],
        },
    )
    out = plan_job.run_request(tmp_path, req, lambda l: None)
    assert out.kind == "questions"
    assert out.stage == "synthesis"
    assert out.text == synthesis_text
    assert out.questions == ("Which migration tool?",)
    assert out.asker == "claude"
    assert out.topic == "t"
    assert out.writer == "claude"


def test_existing_brainstorm_returns_synthesis_without_running_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "final_synthesis", lambda root, topic: "Use Postgres.")
    req = plan_job.PlanRequest("existing", "p", topic="t", writer="claude")
    out = plan_job.run_request(tmp_path, req, lambda l: None)
    assert (out.kind, out.stage, out.text, out.topic, out.writer) == (
        "draft",
        "synthesis",
        "Use Postgres.",
        "t",
        "claude",
    )


def test_open_questions_in_an_existing_brainstorm_are_questions(tmp_path, monkeypatch):
    text = "Use SQLite.\n\n## Open questions\n1. Paper trading?\n"
    monkeypatch.setattr(relay_ops, "final_synthesis", lambda root, topic: text)
    outcome = plan_job.run_request(
        tmp_path, plan_job.PlanRequest("existing", "p", topic="t", writer="codex"), lambda l: None
    )
    assert outcome.kind == "questions"
    assert outcome.stage == "synthesis"
    assert outcome.questions == ("Paper trading?",)
    assert outcome.asker == "codex"
    assert outcome.topic == "t"
    assert outcome.writer == "codex"


def test_brainstorm_request_raises_runtime_error_on_failure(tmp_path, monkeypatch):
    from whyline.console import adapters

    monkeypatch.setattr(
        adapters, "run_brainstorm", lambda *a, **k: SessionEvent("error", "failed to brainstorm")
    )

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
        tmp_path,
        plan_job.PlanRequest("draft", "p", description="x", drafter="codex", reviewer="claude", spec_first=False),
        lambda line: None,
    )
    assert outcome == plan_job.Outcome("questions", None, ("Which broker?",), "claude", stage="plan")


def test_spec_questions_become_a_questions_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "save_planner", lambda *a: None)

    def ask(*a, **k):
        raise Asked(("Which protocol?",), "codex")

    monkeypatch.setattr(relay_ops, "draft_spec", ask)
    outcome = plan_job.run_request(
        tmp_path,
        plan_job.PlanRequest("draft", "p", description="x", drafter="codex", reviewer="claude", spec_first=True),
        lambda line: None,
    )
    assert outcome == plan_job.Outcome("questions", None, ("Which protocol?",), "codex", stage="spec")


def test_run_synthesis_change_revises_synthesis(tmp_path, monkeypatch):
    revised = []
    monkeypatch.setattr(
        relay_ops,
        "revise_synthesis",
        lambda root, topic, writer, agents, feedback, **kw: revised.append((topic, writer, agents, feedback)),
    )
    monkeypatch.setattr(relay_ops, "final_synthesis", lambda root, topic: "Revised synthesis body.")
    req = plan_job.PlanRequest(
        "brainstorm",
        "p",
        brainstorm={"topic": "top", "agents": ["claude", "codex"], "final_agent": "claude"},
    )
    prev_out = plan_job.Outcome("draft", stage="synthesis", text="Old text", topic="top", writer="claude")
    out = plan_job.run_synthesis_change(tmp_path, req, prev_out, "Prefer Postgres", lambda l: None)
    assert revised == [("top", "claude", ["claude", "codex"], "Prefer Postgres")]
    assert out == plan_job.Outcome(
        "draft", stage="synthesis", text="Revised synthesis body.", topic="top", writer="claude"
    )


def test_run_synthesis_change_with_open_questions(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "revise_synthesis", lambda *a, **k: None)
    monkeypatch.setattr(
        relay_ops,
        "final_synthesis",
        lambda root, topic: "Body.\n\n## Open questions\n1. Question 1?\n",
    )
    req = plan_job.PlanRequest("existing", "p", topic="top", writer="claude")
    prev_out = plan_job.Outcome("draft", stage="synthesis", text="Old", topic="top", writer="claude")
    out = plan_job.run_synthesis_change(tmp_path, req, prev_out, "changes", lambda l: None)
    assert out.kind == "questions"
    assert out.stage == "synthesis"
    assert out.questions == ("Question 1?",)


def test_run_spec_from_synthesis_drafts_spec(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(relay_ops, "save_planner", lambda root, d, r: calls.append(("planner", d, r)))
    monkeypatch.setattr(
        relay_ops,
        "draft_spec",
        lambda root, text, attachments, progress: calls.append(("draft_spec", text, attachments))
        or _draft(tmp_path, source="spec"),
    )
    req = plan_job.PlanRequest(
        "brainstorm",
        "p",
        drafter="codex",
        reviewer="claude",
        attachments=(Path("ref.png"),),
        brainstorm={"topic": "my-topic"},
    )
    out = plan_job.Outcome("draft", stage="synthesis", topic="my-topic", writer="claude")
    result = plan_job.run_spec_from_synthesis(tmp_path, req, out, lambda l: None)
    assert calls[0] == ("planner", "codex", "claude")
    assert calls[1][0] == "draft_spec"
    assert calls[1][1] == "Write the spec from the brainstorm in docs/brainstorm/my-topic.md (its Final Synthesis is the agreed direction)."
    assert calls[1][2] == [Path("ref.png")]
    assert result.kind == "draft"
    assert result.stage == "spec"


def test_run_plan_from_spec_drafts_plan_with_spec_arg(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(relay_ops, "save_planner", lambda root, d, r: calls.append(("planner", d, r)))
    monkeypatch.setattr(
        relay_ops,
        "draft_plan",
        lambda root, desc, attachments, progress, spec=None: calls.append(("draft_plan", desc, attachments, spec))
        or _draft(tmp_path),
    )
    spec_path = tmp_path / "docs/specs/my-spec.md"
    req = plan_job.PlanRequest(
        "draft",
        "p",
        description="Plan desc",
        drafter="codex",
        reviewer="claude",
        attachments=(Path("shot.png"),),
    )
    result = plan_job.run_plan_from_spec(tmp_path, req, spec_path, lambda l: None)
    assert calls == [
        ("planner", "codex", "claude"),
        ("draft_plan", "Plan desc", [Path("shot.png")], spec_path),
    ]
    assert result.kind == "draft"
    assert result.stage == "plan"


def test_run_revision_delegates_by_stage(tmp_path, monkeypatch):
    revised = []
    monkeypatch.setattr(
        relay_ops,
        "revise_spec",
        lambda root, d, feedback, progress: revised.append(("spec", d, feedback)) or _draft(tmp_path, source="spec"),
    )
    monkeypatch.setattr(
        relay_ops,
        "revise_plan",
        lambda root, d, feedback, progress: revised.append(("plan", d, feedback)) or _draft(tmp_path, source="planner"),
    )
    spec_draft = _draft(tmp_path, source="spec")
    out_spec = plan_job.run_revision(tmp_path, spec_draft, "spec feedback", lambda l: None)
    assert revised[-1] == ("spec", spec_draft, "spec feedback")
    assert out_spec.stage == "spec"

    plan_draft = _draft(tmp_path, source="planner")
    out_plan = plan_job.run_revision(tmp_path, plan_draft, "plan feedback", lambda l: None)
    assert revised[-1] == ("plan", plan_draft, "plan feedback")
    assert out_plan.stage == "plan"


def test_run_answer_for_spec_when_stopped_to_ask(tmp_path, monkeypatch):
    got = []
    monkeypatch.setattr(
        relay_ops,
        "answer_spec",
        lambda root, answers, progress: got.append(answers) or _draft(tmp_path, source="spec"),
    )
    outcome = plan_job.run_answer(
        tmp_path, plan_job.Outcome("questions", None, ("Spec Q?",), "claude", stage="spec"), "answer 1", lambda l: None
    )
    assert got == ["answer 1"]
    assert outcome.kind == "draft"
    assert outcome.stage == "spec"


def test_run_answer_for_spec_with_open_questions(tmp_path, monkeypatch):
    got = []
    draft = _draft(tmp_path, source="spec", agent="codex")
    monkeypatch.setattr(
        relay_ops,
        "revise_spec",
        lambda root, d, feedback, progress: got.append(feedback) or _draft(tmp_path, source="spec"),
    )
    outcome = plan_job.run_answer(
        tmp_path,
        plan_job.Outcome("questions", draft, ("Spec Q?",), "codex", stage="spec"),
        "yes",
        lambda l: None,
    )
    assert got == [relay_ops.question_feedback(("Spec Q?",), "yes")]
    assert outcome.stage == "spec"


def test_run_answer_for_plan_when_stopped_to_ask(tmp_path, monkeypatch):
    got = []
    monkeypatch.setattr(
        relay_ops,
        "answer_plan",
        lambda root, answers, progress: got.append(answers) or _draft(tmp_path),
    )
    outcome = plan_job.run_answer(
        tmp_path, plan_job.Outcome("questions", None, ("Q?",), "claude", stage="plan"), "1a", lambda l: None
    )
    assert got == ["1a"]
    assert outcome.kind == "draft"
    assert outcome.stage == "plan"


def test_run_answer_for_plan_with_open_questions(tmp_path, monkeypatch):
    got = []
    draft = _draft(tmp_path, source="brainstorm", agent="codex")
    monkeypatch.setattr(
        relay_ops,
        "revise_plan",
        lambda root, d, feedback, progress: got.append(feedback) or _draft(tmp_path),
    )
    outcome = plan_job.run_answer(
        tmp_path, plan_job.Outcome("questions", draft, ("Q?",), "codex", stage="plan"), "yes", lambda l: None
    )
    assert got == [relay_ops.question_feedback(("Q?",), "yes")]
    assert outcome.stage == "plan"


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


def test_spec_summary(tmp_path):
    text = "# My Awesome Feature\n\n## Why\nTo make it better.\n\n## Design\nUse SQLite.\n\n## Testing\nAdd tests.\n"
    draft = _draft(tmp_path, text, source="spec")
    shown = plan_job.spec_summary(draft, "My Awesome Feature")
    assert "My Awesome Feature" in shown
    assert "## Why" in shown or "Why" in shown
    assert "## Design" in shown or "Design" in shown
    assert "## Testing" in shown or "Testing" in shown
    assert f"{len(text.splitlines())} lines" in shown
    assert 'Type "approve" to save it as docs/specs/my-awesome-feature.md and write the plan, or say what to change.' in shown


def test_synthesis_text_short():
    out = plan_job.Outcome("draft", stage="synthesis", text="Use SQLite.\nSimple and robust.")
    shown = plan_job.synthesis_text(out)
    assert "Use SQLite.\nSimple and robust." in shown
    assert "View full" not in shown
    assert 'Type "approve" to write the spec from this, or say what to change.' in shown


def test_synthesis_text_truncates_after_40_lines():
    fifty_lines = "\n".join(f"Line {n}" for n in range(1, 51))
    out = plan_job.Outcome("draft", stage="synthesis", text=fifty_lines)
    shown = plan_job.synthesis_text(out)
    assert "Line 40" in shown
    assert "Line 41" not in shown
    assert "… (View full for the rest)" in shown
    assert 'Type "approve" to write the spec from this, or say what to change.' in shown


def test_questions_text_numbers_them():
    text = plan_job.questions_text(plan_job.Outcome("questions", None, ("A?", "B?"), "claude"))
    assert text.splitlines()[:3] == [
        "claude needs answers before the plan can continue:",
        "  1. A?",
        "  2. B?",
    ]


def test_questions_text_without_asker_defaults():
    text = plan_job.questions_text(plan_job.Outcome("questions", None, ("A?",), ""))
    assert text.splitlines()[0] == "The agent needs answers before the plan can continue:"
