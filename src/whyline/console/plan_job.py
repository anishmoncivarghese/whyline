"""The plan job the main window runs. It turns what the Plan popup collected
(a PlanRequest) into a draft or a set of questions, and carries answers and
change requests back. No widgets here; tui.py owns presentation."""
from __future__ import annotations

import re
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
    spec_first: bool = True


@dataclass(frozen=True)
class Outcome:
    kind: str  # "draft" | "questions"
    draft: relay_ops.Draft | None = None
    questions: tuple[str, ...] = ()
    asker: str = ""
    stage: str = "plan"  # "synthesis" | "spec" | "plan"
    text: str = ""
    topic: str = ""
    writer: str = ""


def _from_draft(draft: relay_ops.Draft, stage: str = "plan") -> Outcome:
    asked = relay_ops.open_questions(draft.text)
    if asked:
        return Outcome(
            "questions",
            draft,
            tuple(asked),
            draft.agent or draft.drafted_by,
            stage=stage,
        )
    return Outcome("draft", draft, stage=stage)


def _guarded(work, stage: str = "plan") -> Outcome:
    try:
        return _from_draft(work(), stage=stage)
    except (relay_ops.plan_questions_error(), relay_ops.spec_questions_error()) as asked:
        return Outcome("questions", None, tuple(asked.questions), asked.agent, stage=stage)


def run_request(root: Path, request: PlanRequest, progress) -> Outcome:
    if request.source == "draft":
        relay_ops.save_planner(root, request.drafter, request.reviewer)

        if not request.spec_first:
            def draft_plan():
                try:
                    return relay_ops.draft_plan(
                        root, request.description, list(request.attachments), progress=progress
                    )
                except relay_ops.in_progress_error() as error:
                    raise RuntimeError(
                        "A plan draft is already unfinished -- open Plan to resume or discard it."
                    ) from error

            return _guarded(draft_plan, stage="plan")

        def draft_spec():
            try:
                return relay_ops.draft_spec(
                    root, request.description, list(request.attachments), progress=progress
                )
            except relay_ops.in_progress_error() as error:
                raise RuntimeError(
                    "A plan draft is already unfinished -- open Plan to resume or discard it."
                ) from error

        return _guarded(draft_spec, stage="spec")

    if request.source == "resume":
        if relay_ops.pending_spec(root):
            return _guarded(lambda: relay_ops.resume_spec(root, progress=progress), stage="spec")
        return _guarded(lambda: relay_ops.resume_draft(root, progress=progress), stage="plan")

    if request.source == "existing":
        topic = request.topic
        writer = request.writer
        text = relay_ops.final_synthesis(root, topic)
        open_qs = relay_ops.open_questions(text)
        if open_qs:
            return Outcome(
                "questions",
                stage="synthesis",
                text=text,
                questions=tuple(open_qs),
                asker=writer,
                topic=topic,
                writer=writer,
            )
        return Outcome("draft", stage="synthesis", text=text, topic=topic, writer=writer)

    choice = request.brainstorm or {}
    from whyline.console import adapters

    result = adapters.run_brainstorm(root, progress=progress, **choice)
    if result.kind == "error":
        raise RuntimeError(result.text)
    topic = choice.get("topic", request.topic)
    writer = choice.get("final_agent", request.writer)
    text = relay_ops.final_synthesis(root, topic)
    open_qs = relay_ops.open_questions(text)
    if open_qs:
        return Outcome(
            "questions",
            stage="synthesis",
            text=text,
            questions=tuple(open_qs),
            asker=writer,
            topic=topic,
            writer=writer,
        )
    return Outcome("draft", stage="synthesis", text=text, topic=topic, writer=writer)


def run_synthesis_change(
    root: Path,
    request: PlanRequest,
    outcome: Outcome,
    feedback: str,
    progress,
) -> Outcome:
    topic = outcome.topic or request.topic or ((request.brainstorm or {}).get("topic", ""))
    writer = outcome.writer or request.writer or ((request.brainstorm or {}).get("final_agent", ""))
    agents = (request.brainstorm or {}).get("agents") or ([writer] if writer else [])
    timeout_minutes = (request.brainstorm or {}).get("timeout_minutes")
    attachments = list(request.attachments) or list((request.brainstorm or {}).get("attachments", ()))

    relay_ops.revise_synthesis(
        root,
        topic,
        writer,
        agents,
        feedback,
        progress=progress,
        timeout_minutes=timeout_minutes,
        attachments=attachments,
    )
    text = relay_ops.final_synthesis(root, topic)
    open_qs = relay_ops.open_questions(text)
    if open_qs:
        return Outcome(
            "questions",
            stage="synthesis",
            text=text,
            questions=tuple(open_qs),
            asker=writer,
            topic=topic,
            writer=writer,
        )
    return Outcome("draft", stage="synthesis", text=text, topic=topic, writer=writer)


def run_spec_from_synthesis(
    root: Path,
    request: PlanRequest,
    outcome: Outcome,
    progress,
) -> Outcome:
    from whyline_relay import brainstorm

    topic = outcome.topic or request.topic or ((request.brainstorm or {}).get("topic", ""))
    shared = brainstorm.shared_path(root, topic)
    try:
        doc = shared.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        doc = shared.as_posix()
    text = f"Write the spec from the brainstorm in {doc} (its Final Synthesis is the agreed direction)."
    attachments = list(request.attachments) or list((request.brainstorm or {}).get("attachments", ()))
    if request.drafter and request.reviewer:
        relay_ops.save_planner(root, request.drafter, request.reviewer)

    def draft():
        try:
            return relay_ops.draft_spec(root, text, attachments, progress=progress)
        except relay_ops.in_progress_error() as error:
            raise RuntimeError(
                "A plan draft is already unfinished -- open Plan to resume or discard it."
            ) from error

    return _guarded(draft, stage="spec")


def run_plan_from_spec(
    root: Path,
    request: PlanRequest,
    spec_path: Path,
    progress,
) -> Outcome:
    if request.drafter and request.reviewer:
        relay_ops.save_planner(root, request.drafter, request.reviewer)
    attachments = list(request.attachments) or list((request.brainstorm or {}).get("attachments", ()))

    def draft():
        try:
            return relay_ops.draft_plan(
                root, request.description, attachments, progress=progress, spec=spec_path
            )
        except relay_ops.in_progress_error() as error:
            raise RuntimeError(
                "A plan draft is already unfinished -- open Plan to resume or discard it."
            ) from error

    return _guarded(draft, stage="plan")


def run_revision(
    root: Path,
    target: relay_ops.Draft | Outcome,
    feedback: str,
    progress,
    stage: str | None = None,
) -> Outcome:
    if isinstance(target, Outcome):
        stage = stage or target.stage
        draft = target.draft
    else:
        draft = target
        if stage is None:
            stage = "spec" if getattr(draft, "source", "") == "spec" else "plan"

    if stage == "spec":
        return _guarded(
            lambda: relay_ops.revise_spec(root, draft, feedback, progress=progress),
            stage="spec",
        )
    return _guarded(
        lambda: relay_ops.revise_plan(root, draft, feedback, progress=progress),
        stage="plan",
    )


def run_answer(root: Path, outcome: Outcome, answers: str, progress) -> Outcome:
    if outcome.stage == "spec":
        if outcome.draft is None:
            return _guarded(
                lambda: relay_ops.answer_spec(root, answers, progress=progress),
                stage="spec",
            )
        feedback = relay_ops.question_feedback(outcome.questions, answers)
        return run_revision(root, outcome.draft, feedback, progress, stage="spec")

    if outcome.draft is None:  # the planner stopped mid-pipeline to ask
        return _guarded(
            lambda: relay_ops.answer_plan(root, answers, progress=progress),
            stage="plan",
        )
    feedback = relay_ops.question_feedback(outcome.questions, answers)
    return run_revision(root, outcome.draft, feedback, progress, stage="plan")


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


def spec_summary(draft: relay_ops.Draft, name: str) -> str:
    lines = draft.text.splitlines()
    line_count = len(lines)
    title = name
    headings: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## ") and title == name:
            title = stripped[2:].strip()
        elif stripped.startswith("## "):
            headings.append(stripped)
    listing = "\n".join(f"  {h}" for h in headings) if headings else "  (no section headings)"
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].rstrip("-") or "spec"
    by = f", by {draft.drafted_by}" if draft.drafted_by else ""
    return (
        f'Draft spec "{title}" is ready: {line_count} lines{by}.\n'
        f"{listing}\nFull draft: {draft.path}\n"
        f'Type "approve" to save it as docs/specs/{slug}.md and write the plan, '
        "or say what to change."
    )


def synthesis_text(outcome: Outcome) -> str:
    lines = outcome.text.splitlines()
    if len(lines) > 40:
        body = "\n".join(lines[:40]) + "\n… (View full for the rest)"
    else:
        body = "\n".join(lines)
    prompt = 'Type "approve" to write the spec from this, or say what to change.'
    return f"{body}\n\n{prompt}" if body else prompt


def questions_text(outcome: Outcome) -> str:
    lines = [f"{outcome.asker or 'The agent'} needs answers before the plan can continue:"]
    lines += [f"  {number}. {q}" for number, q in enumerate(outcome.questions, 1)]
    lines.append('Answer in the prompt below, e.g. "1a, 2: yes but only for the pilot".')
    return "\n".join(lines)
