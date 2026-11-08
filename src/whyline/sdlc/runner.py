"""Run one document stage of a set: draft, revise or brainstorm, and record the result."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from whyline.console import adapters, relay_ops
from whyline.sdlc import docset as docset_mod, guard, product, templates, workspace
from whyline.sdlc.docset import DocSet, Status

NO_PRD_CHANGE = "No PRD change:"
PRD_UPDATE_FEEDBACK = (
    "Update this PRD for the feature below. Change only the sections this feature "
    "affects, and keep every other section word for word. If no section needs to "
    "change, reply with only `No PRD change: <reason>`."
)
EXISTING_PROJECT_REQUEST = (
    "Write the product PRD for this existing project from its README and code, "
    "then cover the feature below."
)
_NOT_CODE = ("docs/", "plans/", ".whyline/")
_NOT_CODE_FILES = {"README.md", ".gitignore", "LICENSE"}


@dataclass
class StageResult:
    done: bool = False
    questions: tuple[str, ...] = ()
    error: str = ""
    skipped: bool = False
    reason: str = ""
    version: int = 0


def _error(message: str) -> StageResult:
    return StageResult(error=message)


def _author(docset: DocSet) -> str:
    return str(docset.roles.get("writer") or "claude")


def _request(docset: DocSet) -> str:
    return docset.description or docset.name


def _roles_list(value) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(part) for part in (value or [])]


def _attachments(docs: Path, docset: DocSet, kind: str) -> list[Path]:
    """The approved documents before `kind`, plus the brainstorm when there is one."""
    found: list[Path] = []
    for doc in docset.documents:
        if doc["kind"] == kind:
            break
        path = docs / doc["path"]
        if doc["kind"] == "plan":
            path = docset_mod.plan_file(docs, docset.slug) or path
        if path.is_file() and (
            doc["status"] == Status.APPROVED.value or doc["kind"] == "brainstorm"
        ):
            found.append(path)
    brainstorm = docset.document("brainstorm")
    if brainstorm is not None and kind != "brainstorm":
        path = docs / brainstorm["path"]
        if path.is_file() and path not in found:
            found.append(path)
    return found


def _has_code(docs: Path) -> bool:
    from whyline import worktrees

    try:
        listing = worktrees._git(docs, "ls-files")
    except Exception:
        return False
    for name in listing.splitlines():
        if name and name not in _NOT_CODE_FILES and not name.startswith(_NOT_CODE):
            return True
    return False


def _mark_running(docs: Path, docset: DocSet, kind: str) -> None:
    docset.stage = kind
    docset.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    docset_mod.save(docs, docset)


def _clear_running(docs: Path, docset: DocSet) -> None:
    docset.stage = ""
    docset.started_at = ""
    docset_mod.save(docs, docset)


def _ask(docs: Path, docset: DocSet, kind: str, questions) -> StageResult:
    asked = tuple(str(q) for q in questions)
    doc = docset.document(kind)
    if doc is not None:
        doc["status"] = Status.IN_REVIEW.value
    docset.pending_questions[kind] = list(asked)
    _clear_running(docs, docset)
    return StageResult(questions=asked)


def _finish(
    docs: Path, docset: DocSet, kind: str, text: str, *, note: str, based_on: str = ""
) -> StageResult:
    number = docset_mod.add_version(
        docs, docset, kind, text, author=_author(docset), note=note
    )
    doc = docset.document(kind)
    if based_on:
        doc["based_on"] = based_on
    docset.pending_questions.pop(kind, None)
    _clear_running(docs, docset)
    return StageResult(done=True, version=number)


def _run_brainstorm(docs: Path, docset: DocSet, progress) -> StageResult:
    from whyline_relay import brainstorm

    agents = _roles_list(docset.roles.get("brainstorm")) or [_author(docset)]
    final = str(docset.roles.get("brainstorm_final") or agents[0])
    event = adapters.run_brainstorm(
        docs,
        topic=docset.slug,
        agents=agents,
        passes=int(docset.roles.get("brainstorm_passes", 1)),
        final_agent=final,
        progress=progress,
        attachments=_attachments(docs, docset, "brainstorm"),
    )
    if event.kind == "error":
        return _error(event.text)
    path = brainstorm.shared_path(docs, docset.slug)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return _error("The brainstorm finished but its write-up could not be read.")
    return _finish(docs, docset, "brainstorm", text, note="brainstorm synthesis")


def _run_prd_update(docs: Path, docset: DocSet, progress) -> StageResult:
    if not product.claim_update(docs, docset.slug):
        holder = product.claim_holder(docs) or "another set"
        return _error(f"Another feature is updating the PRD ({holder})")
    now = product.current(docs)
    if now is None:
        product.release_update(docs, docset.slug)
        return _error("There is no product PRD to update.")
    template = templates.template_for(docs, "prd", docset.size)
    draft = relay_ops.revise_document_text(
        docs,
        "prd",
        product.body(now.text),
        f"{PRD_UPDATE_FEEDBACK}\n\nFeature:\n{_request(docset)}",
        template=template,
        attachments=_attachments(docs, docset, "prd"),
        progress=progress,
    )
    relay_ops.discard_document(docs, "prd")
    text = draft.text.strip()
    if text.startswith(NO_PRD_CHANGE):
        reason = text[len(NO_PRD_CHANGE) :].strip()
        product.release_update(docs, docset.slug)
        docset.prd_mode = docset_mod.PrdMode.NONE.value
        docset.documents = [d for d in docset.documents if d["kind"] != "prd"]
        docset.skipped["prd"] = reason
        _clear_running(docs, docset)
        return StageResult(done=True, skipped=True, reason=reason)
    return _finish(
        docs, docset, "prd", draft.text, note=f"based on PRD v{now.version}", based_on=now.version
    )


def _run_draft(docs: Path, docset: DocSet, kind: str, progress) -> StageResult:
    request = _request(docset)
    attachments = _attachments(docs, docset, kind)
    if kind == "prd" and product.current(docs) is None and _has_code(docs):
        readme = docs / "README.md"
        if readme.is_file():
            attachments.append(readme)
        request = f"{EXISTING_PROJECT_REQUEST}\n\n{request}"
    draft = relay_ops.draft_document(
        docs,
        kind,
        request,
        template=templates.template_for(docs, kind, docset.size),
        attachments=attachments,
        progress=progress,
    )
    relay_ops.discard_document(docs, kind)
    return _finish(docs, docset, kind, draft.text, note=f"drafted by {_author(docset)}")


def run_stage(root: Path, docset: DocSet, stage, *, progress) -> StageResult:
    """Run one stage. Open questions come back in the result and are saved on the set."""
    kind = getattr(stage, "kind", stage)
    if kind == "design-review":
        return StageResult(done=True)  # GFR-3 gives this stage its fresh-eyes review
    refusal = guard.check(root)
    if refusal:
        return _error(refusal)
    docs = workspace.docs_root(root)
    try:
        with guard.drafting(root, docset.slug, kind):
            _mark_running(docs, docset, kind)
            try:
                result = _dispatch(docs, docset, kind, progress)
            except relay_ops.document_questions_error() as asked:
                return _ask(docs, docset, kind, asked.questions)
            if result.error:
                _clear_running(docs, docset)
            return result
    except guard.DraftingBusy as busy:
        return _error(str(busy))


def _dispatch(docs: Path, docset: DocSet, kind: str, progress) -> StageResult:
    if kind == "brainstorm":
        return _run_brainstorm(docs, docset, progress)
    if kind == "prd" and docset.prd_mode == docset_mod.PrdMode.UPDATE.value:
        return _run_prd_update(docs, docset, progress)
    if kind in ("prd", "spec", "design", "build-record"):
        return _run_draft(docs, docset, kind, progress)
    return _error(f"Stage {kind!r} is not a document stage.")
