"""Review actions on a document of a set: approve, ask for changes, edit, redo, answer, stop."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from whyline.console import relay_ops
from whyline.sdlc import (
    docset as docset_mod, goldfish, guard, lenses, product, runner, templates, workspace,
)
from whyline.sdlc.docset import DocSet, DocSetError, Status
from whyline.sdlc.stages import Stage, next_stage

SECTION_ONLY = "Change only the section '{section}' unless the comments say otherwise."
REDO_FEEDBACK = "Update this to match {upstream} v{version}. Change only what that change needs."


def _check(root: Path) -> None:
    refusal = guard.check(root)
    if refusal:
        raise DocSetError(refusal)


def _load(root: Path, slug: str, kind: str) -> tuple[Path, DocSet, dict]:
    docs = workspace.docs_root(root)
    found = docset_mod.load(docs, slug)
    doc = found.document(kind)
    if doc is None:
        raise DocSetError(f"The document set {slug!r} has no {kind!r} document.")
    return docs, found, doc


def _log_blockers(root: Path, docs: Path, found: DocSet, kind: str, doc: dict, approver: str) -> None:
    """Record approving a version whose fresh review still lists Blockers."""
    latest = goldfish.latest_review(root, found, kind)
    if latest is None or latest.path.name != f"{kind}-v{doc['version']}.md":
        return
    count = sum(1 for item in latest.findings if item.severity == "blocker")
    if count:
        docset_mod.log_review(
            docs, found, kind, actor=approver, action=f"approved with {count} blockers"
        )


def approve(root: Path, slug: str, kind: str, *, approver: str) -> Stage | None:
    """Approve a document, commit it, and return the stage that comes next."""
    _check(root)
    docs, found, doc = _load(root, slug, kind)
    update = found.prd_mode == docset_mod.PrdMode.UPDATE.value
    if kind == "prd" and update and product.moved(docs, found):
        now = product.current(docs)
        raise DocSetError(f"The PRD is now v{now.version}. Redo this update first.")
    _log_blockers(root, docs, found, kind, doc, approver)
    title = "PRD" if kind == "prd" else docset_mod._kind_title(kind)
    label = f"v{doc['version']}"
    if kind == "prd":
        label = "v" + product.publish(
            docs,
            docset_mod._current_text(docs, found, doc),
            set_name=found.name,
            slug=found.slug,
            approver=approver,
            major=found.prd_major and update,
        )
        docset_mod.approve(docs, found, kind, approver=approver)
        message = f"docs: PRD {label} for {found.name}"
    else:
        if kind == "plan":
            runner.approve_plan(root, found, approver=approver)
        else:
            docset_mod.approve(docs, found, kind, approver=approver)
        message = f"docs: approve {title} {label} for {found.name}"
    docset_mod.commit(docs, found, message)
    docset_mod.refresh_out_of_date(docs, found)
    return next_stage(found)


def _revise(
    root: Path,
    slug: str,
    kind: str,
    feedback: str,
    *,
    progress,
    attachments=(),
    log_comment: str = "",
    section: str = "",
) -> list[str]:
    docs, found, doc = _load(root, slug, kind)
    docset_mod.log_review(
        docs, found, kind, actor="human", action="changes requested",
        comment=log_comment or feedback, section=section,
    )
    old = docset_mod._current_text(docs, found, doc)
    with guard.drafting(root, found.slug, kind):
        if kind == "plan":
            result = runner.revise_plan(root, found, feedback, progress=progress)
            if result.error:
                raise DocSetError(result.error)
        else:
            draft = relay_ops.revise_document_text(
                docs,
                kind,
                old,
                feedback,
                template=templates.template_for(docs, kind, found.size),
                attachments=[*runner._attachments(docs, found, kind), *attachments],
                progress=progress,
            )
            relay_ops.discard_document(docs, kind)
            docset_mod.add_version(
                docs, found, kind, draft.text,
                author=runner._author(found), note="revised from feedback",
            )
    new = docset_mod._current_text(docs, found, found.document(kind))
    changed = product.changed_sections(old, new)
    docset_mod.log_review(
        docs, found, kind, actor=runner._author(found), action="revised",
        changed_sections=changed,
    )
    return [name for name in changed if name != section] if section else []


def ask_for_changes(
    root: Path, slug: str, kind: str, comments: str, *, section: str = "", progress
) -> list[str]:
    """Revise a document from comments; returns sections changed beyond `section`."""
    _check(root)
    feedback = comments
    if section:
        feedback += "\n\n" + SECTION_ONLY.format(section=section)
    return _revise(
        root, slug, kind, feedback, progress=progress, log_comment=comments, section=section
    )


def edited(root: Path, slug: str, kind: str, *, editor_name: str) -> int | None:
    """Add the file as a new version when it was edited by hand; None when unchanged."""
    _check(root)
    docs, found, doc = _load(root, slug, kind)
    path = docs / doc["path"]
    if kind == "plan":
        path = docset_mod.plan_file(docs, slug) or path
    if not path.is_file():
        return None
    text = docset_mod.strip_header(path.read_text(encoding="utf-8"))
    last = docset_mod._history_path(docs, slug, kind, int(doc["version"]))
    if last.is_file() and last.read_text(encoding="utf-8").strip() == text.strip():
        return None
    return docset_mod.add_version(
        docs, found, kind, text, author=editor_name, note=f"edited by {editor_name}"
    )


def redo(root: Path, slug: str, kind: str, *, progress) -> list[str]:
    """Revise a document to match the document before it, or the moved product PRD."""
    _check(root)
    docs, found, doc = _load(root, slug, kind)
    extra: list[Path] = []
    now = product.current(docs)
    if kind == "prd" and found.prd_mode == docset_mod.PrdMode.UPDATE.value and now:
        upstream, version = "PRD", now.version
        extra.append(now.path)
    else:
        before = None
        for other in found.documents:
            if other["kind"] == kind:
                break
            before = other
        if before is None:
            raise DocSetError("There is nothing before this document to match.")
        upstream = docset_mod._upstream_label(before["kind"])
        version = (
            now.version if before["kind"] == "prd" and now else int(before["version"])
        )
    feedback = REDO_FEEDBACK.format(upstream=upstream, version=version)
    changed = _revise(root, slug, kind, feedback, progress=progress, attachments=extra)
    if extra:
        again = docset_mod.load(docs, slug)
        again.document(kind)["based_on"] = now.version
        docset_mod.save(docs, again)
    return changed


def answer_questions(
    root: Path, slug: str, kind: str, answers: str, *, progress
) -> list[str]:
    """Answer the questions a stage asked, and revise the document with the answers."""
    _check(root)
    docs, found, _ = _load(root, slug, kind)
    questions = found.pending_questions.get(kind, [])
    feedback = relay_ops.question_feedback(questions, answers)
    changed = ask_for_changes(root, slug, kind, feedback, progress=progress)
    again = docset_mod.load(docs, slug)
    again.pending_questions.pop(kind, None)
    docset_mod.save(docs, again)
    return changed


def stop(root: Path, slug: str) -> None:
    """Stop work on a set: clear the running stage and release its PRD claim."""
    _check(root)
    docs = workspace.docs_root(root)
    found = docset_mod.load(docs, slug)
    found.stage = ""
    found.started_at = ""
    docset_mod.save(docs, found)
    product.release_update(docs, slug)


def set_mode(root: Path, slug: str, mode: str) -> DocSet:
    """Save the set's mode; `runner.run` reads it again between stages."""
    docs = workspace.docs_root(root)
    found = docset_mod.load(docs, slug)
    found.mode = docset_mod.Mode(mode).value
    docset_mod.save(docs, found)
    docset_mod.refresh(docs, found)
    return found


def reviewer_for(found: DocSet, kind: str) -> str:
    roles = found.roles
    return str(
        roles.get(f"{kind}_reviewer") or roles.get("reviewer") or roles.get("writer") or "claude"
    )


def auto_approve(
    root: Path, slug: str, kind: str, *, progress=None, cancel_event=None
) -> tuple[str, Stage | None]:
    """Have the reviewer agent review a finished document, log it, and approve it.

    Returns the reviewer's review text and the stage that comes next.
    """
    from whyline.console import adapters

    _check(root)
    docs, found, doc = _load(root, slug, kind)
    agent = reviewer_for(found, kind)
    text = docset_mod._current_text(docs, found, doc)
    prompt = (
        f"Review this {docset_mod._kind_title(kind)} for {found.name}. "
        "Say briefly what is good and what is weak.\n\n" + text
    )
    if progress is not None:
        progress(f"auto · {agent} reviews the {kind}")
    event = adapters.run_chat_turn(
        root, agent=agent, prompt=prompt, timeout_seconds="none", cancel_event=cancel_event
    )
    if event.kind == "error":
        raise DocSetError(event.text)
    review = event.text.removeprefix(f"[{agent}] ").strip()
    docset_mod.log_review(docs, found, kind, actor=agent, action="reviewed", comment=review)
    return review, approve(root, slug, kind, approver=f"{agent} (Auto)")


MAX_FIX_ROUNDS = 2
STILL_BLOCKED = f"Still has blockers after {MAX_FIX_ROUNDS} rounds of changes"
COVERAGE_LENS = "coverage"


def gate(review: goldfish.Review) -> str:
    """`pass` with no Blocker and nothing not run, `fix` with Blockers, `stop` when a lens did not run."""
    if review.not_run:
        return "stop"
    if any(item.severity == "blocker" for item in review.findings):
        return "fix"
    return "pass"


def _coverage_findings(docs: Path, found: DocSet) -> list[lenses.Finding]:
    from whyline.sdlc import trace

    gaps = trace.coverage(docs, found)

    def blocker(section: str, problem: str, fix: str) -> lenses.Finding:
        return lenses.Finding(COVERAGE_LENS, "blocker", section, problem, fix)

    out = [
        blocker(n, f"{n} has no task", f"Add a task with `covers: {n}`")
        for n in gaps.unbuilt
    ]
    out += [
        blocker(n, f"{n} has no test", f"Add a test case titled `[{n}]`") for n in gaps.untested
    ]
    for item in gaps.out_of_scope:
        task, _, number = item.partition(":")
        out.append(blocker(
            task, f"{task} covers {number}, not in scope",
            f"Remove {number} from its covers line, or add it to the requirements",
        ))
    out += [
        blocker(task, f"{task} has no covers line",
                "Add `covers: R<n>, …` or `covers: none (<reason>)`")
        for task in gaps.uncovered_tasks
    ]
    return out


def _with_coverage(docs: Path, found: DocSet, result: goldfish.Review) -> goldfish.Review:
    """Add the plan's coverage gaps to the report as Blockers from the coverage lens."""
    extra = _coverage_findings(docs, found)
    if not extra:
        return result
    try:
        writer_only = goldfish.WRITER_NOTE in result.path.read_text(encoding="utf-8")
    except OSError:
        writer_only = False
    merged = goldfish._merge([*result.findings, *extra])
    _, body = goldfish._render(merged, result.not_run, result.agent, writer_only)
    docset_mod._write(result.path, body)
    return replace(result, findings=[item for item, _ in merged])


def review_again(
    root: Path, slug: str, kind: str, *, progress=None, cancel_event=None, agent: str = "",
    run_fn=None,
) -> goldfish.Review:
    """Run the fresh-eyes review on the document's current version."""
    docs, found, _ = _load(root, slug, kind)
    result = goldfish.review_document(
        root, found, kind, agent=agent or reviewer_for(found, kind), progress=progress,
        cancel_event=cancel_event, run_fn=run_fn,
    )
    if kind == "plan":
        result = _with_coverage(docs, found, result)
    return result


def has_lenses(found: DocSet, kind: str) -> bool:
    return bool(lenses.lenses_for(found.size, kind))


def summary(result: goldfish.Review, kind: str) -> str:
    try:
        first = result.path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        first = ""
    return f"{result.agent} reviewed the {kind} with fresh eyes. {first}".strip()


def _fix_comments(result: goldfish.Review) -> str:
    return "\n".join(
        f"{item.section}: {item.problem} — {item.fix}"
        for item in result.findings
        if item.severity in ("blocker", "major")
    )


def auto_review(
    root: Path, slug: str, kind: str, *, agent: str = "", progress=None, cancel_event=None,
    run_fn=None,
) -> tuple[str, str]:
    """Review, ask for changes on Blockers (at most MAX_FIX_ROUNDS times), approve on a pass.

    Returns (summary, stop message); the stop message is empty when the document was approved.
    """
    rounds = 0
    while True:
        result = review_again(root, slug, kind, progress=progress, cancel_event=cancel_event,
                              agent=agent, run_fn=run_fn)
        text = summary(result, kind)
        verdict = gate(result)
        if verdict == "stop":
            return text, f"A reviewer didn't run: {', '.join(result.not_run)}"
        if verdict == "pass":
            doc = _load(root, slug, kind)[2]
            if doc["status"] != Status.APPROVED.value:
                approve(root, slug, kind, approver=f"{result.agent} (Auto, fresh review)")
            return text, ""
        if rounds >= MAX_FIX_ROUNDS:
            return text, STILL_BLOCKED
        ask_for_changes(root, slug, kind, _fix_comments(result), progress=progress)
        rounds += 1
