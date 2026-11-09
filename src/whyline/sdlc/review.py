"""Review actions on a document of a set: approve, ask for changes, edit, redo, answer, stop."""

from __future__ import annotations

from pathlib import Path

from whyline.console import relay_ops
from whyline.sdlc import docset as docset_mod, guard, product, runner, templates, workspace
from whyline.sdlc.docset import DocSet, DocSetError
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


def approve(root: Path, slug: str, kind: str, *, approver: str) -> Stage | None:
    """Approve a document, commit it, and return the stage that comes next."""
    _check(root)
    docs, found, doc = _load(root, slug, kind)
    update = found.prd_mode == docset_mod.PrdMode.UPDATE.value
    if kind == "prd" and update and product.moved(docs, found):
        now = product.current(docs)
        raise DocSetError(f"The PRD is now v{now.version}. Redo this update first.")
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
