"""The plan job the main window runs. It turns what the Plan popup collected
(a PlanRequest) into a draft or a set of questions, and carries answers and
change requests back. No widgets here; tui.py owns presentation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from whyline.console import relay_ops


@dataclass(frozen=True)
class PlanRequest:
    source: str  # "draft" | "brainstorm" | "existing" | "resume"
    name: str
    replace: bool = False
    description: str = ""
    attachments: tuple[Path, ...] = ()
    drafter: str = ""
    reviewer: str = ""
    brainstorm: dict | None = None  # collect_brainstorm()'s choice, for a new one
    topic: str = ""  # an existing brainstorm doc's stem
    writer: str = ""


@dataclass(frozen=True)
class Outcome:
    kind: str  # "draft" | "questions"
    draft: relay_ops.Draft | None = None
    questions: tuple[str, ...] = ()
    asker: str = ""


def _from_draft(draft: relay_ops.Draft) -> Outcome:
    asked = relay_ops.open_questions(draft.text)
    if asked:
        return Outcome("questions", draft, tuple(asked), draft.agent or draft.drafted_by)
    return Outcome("draft", draft)


def _guarded(work) -> Outcome:
    try:
        return _from_draft(work())
    except relay_ops.plan_questions_error() as asked:
        return Outcome("questions", None, tuple(asked.questions), asked.agent)


def run_request(root: Path, request: PlanRequest, progress) -> Outcome:
    if request.source == "draft":
        relay_ops.save_planner(root, request.drafter, request.reviewer)

        def draft():
            try:
                return relay_ops.draft_plan(
                    root, request.description, list(request.attachments), progress=progress
                )
            except relay_ops.in_progress_error() as error:
                raise RuntimeError(
                    "A plan draft is already unfinished -- open Plan to resume or discard it."
                ) from error

        return _guarded(draft)
    if request.source == "resume":
        return _guarded(lambda: relay_ops.resume_draft(root, progress=progress))
    if request.source == "existing":
        return _guarded(lambda: relay_ops.plan_from_brainstorm(
            root, request.topic, request.writer, progress=progress, attachments=list(request.attachments)
        ))
    choice = request.brainstorm

    def brainstorm_then_plan():
        from whyline.console import adapters

        result = adapters.run_brainstorm(root, progress=progress, **choice)
        if result.kind == "error":
            raise RuntimeError(result.text)
        return relay_ops.plan_from_brainstorm(
            root, choice["topic"], choice["final_agent"], progress=progress,
            timeout_minutes=choice["timeout_minutes"],
            attachments=list(choice.get("attachments", ())),
        )

    return _guarded(brainstorm_then_plan)


def run_revision(root: Path, draft: relay_ops.Draft, feedback: str, progress) -> Outcome:
    return _guarded(lambda: relay_ops.revise_plan(root, draft, feedback, progress=progress))


def run_answer(root: Path, outcome: Outcome, answers: str, progress) -> Outcome:
    if outcome.draft is None:  # the planner stopped mid-pipeline to ask
        return _guarded(lambda: relay_ops.answer_plan(root, answers, progress=progress))
    feedback = relay_ops.question_feedback(outcome.questions, answers)
    return run_revision(root, outcome.draft, feedback, progress)


def summary(draft: relay_ops.Draft, name: str) -> str:
    from whyline_relay import plan

    try:
        tasks = plan.parse(draft.text)
    except plan.PlanError as error:
        tasks, problem = [], str(error)
    else:
        problem = "" if tasks else "no tasks found"
    if problem:
        return (
            f'The draft for "{name}" has no usable tasks yet ({problem}). '
            f"It is at {draft.path}. Say what to change."
        )
    listing = "\n".join(f"  {task.text.splitlines()[0]}" for task in tasks[:15])
    more = f"\n  … and {len(tasks) - 15} more" if len(tasks) > 15 else ""
    return (
        f'Draft plan "{name}" is ready: {len(tasks)} tasks, by {draft.drafted_by}.\n'
        f"{listing}{more}\nFull draft: {draft.path}\n"
        f'Type "approve" to save it as {relay_ops.PLANS_DIR}/{relay_ops.plan_slug(name)}.plan.md, '
        "or say what to change."
    )


def questions_text(outcome: Outcome) -> str:
    lines = [f"{outcome.asker or 'The agent'} needs answers before the plan can continue:"]
    lines += [f"  {number}. {q}" for number, q in enumerate(outcome.questions, 1)]
    lines.append('Answer in the prompt below, e.g. "1a, 2: yes but only for the pilot".')
    return "\n".join(lines)
