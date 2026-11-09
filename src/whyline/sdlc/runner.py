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
    "change, reply with only `No PRD change: <reason>`. Never renumber requirements: "
    "a new one takes the next free R-number, and a removed one stays as "
    "`R<n> — removed in v<version>`."
)
PLAN_COVERS_REQUEST = (
    "Give every task a `covers: R<n>, …` detail line naming the requirements it builds, "
    "or `covers: none (<reason>)`. Give every test case the same requirements in its "
    "title as `[R<n>]`, for example `TP-1: [R3] Login works`."
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


def _spec_source(docs: Path, docset: DocSet) -> Path | None:
    """The approved spec, or for a large set the approved design."""
    for kind in ("spec", "design"):
        doc = docset.document(kind)
        if doc is not None and doc["status"] == Status.APPROVED.value:
            path = docs / doc["path"]
            if path.is_file():
                return path
    return None


def _sync_test_planner(docs: Path, docset: DocSet) -> str:
    """Make the config's Test planner the set's; returns the agent, empty for none."""
    test = str(docset.roles.get("test_planner") or "")
    draft, review, current = relay_ops.planner_agents(docs)
    if test != current:
        relay_ops.save_planner(docs, draft, review, test)
    return test


def _tests_history(docs: Path, docset: DocSet, number: int) -> Path:
    path = docset_mod._history_path(docs, docset.slug, "plan", number)
    return path.with_name(f"plan-v{number}.tests.md")


def _finish_plan(
    docs: Path, docset: DocSet, draft, tests: str, *, note: str
) -> StageResult:
    result = _finish(docs, docset, "plan", draft.text, note=note)
    if tests:
        docset_mod._write(_tests_history(docs, docset, result.version), tests)
    return result


def _draft_tests(draft, test_planner: str) -> str:
    from whyline_relay import testplan

    path = testplan.path_for(draft.path)
    if test_planner and path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def _run_plan(docs: Path, docset: DocSet, progress) -> StageResult:
    test_planner = _sync_test_planner(docs, docset)
    draft = relay_ops.draft_plan(
        docs,
        f"{_request(docset)}\n\n{PLAN_COVERS_REQUEST}",
        _attachments(docs, docset, "plan"),
        progress=progress,
        spec=_spec_source(docs, docset),
    )
    tests = _draft_tests(draft, test_planner)
    relay_ops.discard_draft(docs, draft)
    return _finish_plan(
        docs, docset, draft, tests, note=f"drafted by {_author(docset)}"
    )


def revise_plan(
    root: Path, docset: DocSet, feedback: str, *, progress
) -> StageResult:
    """Revise the current plan text; the tests stage keeps the test plan in step."""
    docs = workspace.docs_root(root)
    doc = docset.document("plan")
    if doc is None:
        return _error("This set has no plan to revise.")
    test_planner = _sync_test_planner(docs, docset)
    text = docset_mod._current_text(docs, docset, doc)
    # relay_ops only maps the document kinds it ships; the plan kind is the relay's own.
    relay_ops._DOC_KIND_NAMES.setdefault("plan", "PLAN_KIND")
    draft = relay_ops.revise_document_text(
        docs,
        "plan",
        text,
        feedback,
        attachments=_attachments(docs, docset, "plan"),
        progress=progress,
    )
    tests = _draft_tests(draft, test_planner)
    relay_ops.discard_document(docs, "plan")
    return _finish_plan(docs, docset, draft, tests, note="revised from feedback")


def approve_plan(root: Path, docset: DocSet, *, approver: str) -> Path:
    """Write plans/<slug>.plan.md and .tests.md from the current version and approve it."""
    from whyline_relay import config, testplan

    docs = workspace.docs_root(root)
    doc = docset.document("plan")
    number = int(doc["version"])
    staged = config.relay_dir(docs) / "sdlc-plan-draft.md"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(
        docset_mod._history_path(docs, docset.slug, "plan", number).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    tests = _tests_history(docs, docset, number)
    tests_staged = testplan.path_for(staged)
    if tests.is_file():
        tests_staged.write_text(tests.read_text(encoding="utf-8"), encoding="utf-8")
    source = _spec_source(docs, docset)
    try:
        target = relay_ops._approve_marked(
            docs,
            staged.read_text(encoding="utf-8"),
            name=docset.slug,
            source="draft",
            drafted_by=str(doc.get("written_by") or _author(docset)),
            replace=True,
            spec=source.relative_to(docs).as_posix() if source else "",
            draft_path=staged,
        )
    finally:
        staged.unlink(missing_ok=True)
        tests_staged.unlink(missing_ok=True)
    docset_mod.approve(docs, docset, "plan", approver=approver)
    return target


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
    if kind == "plan":
        return _run_plan(docs, docset, progress)
    if kind in ("prd", "spec", "design", "build-record"):
        return _run_draft(docs, docset, kind, progress)
    return _error(f"Stage {kind!r} is not a document stage.")


@dataclass
class RunOutcome:
    """Why `run` returned: waiting, waiting_for_home, questions, paused, launched, cancelled, error or done."""

    state: str
    stage: str = ""
    questions: tuple[str, ...] = ()
    message: str = ""
    reviews: tuple[str, ...] = ()
    build_base: str = ""


def _launch_build(root: Path, docs: Path, found: DocSet, *, progress, launcher) -> RunOutcome:
    """Copy the plan to the project, run Auto's final preflight and launcher, store build_base."""
    from whyline import worktrees
    from whyline.console import auto_run

    if root.resolve() != docs.resolve():
        workspace.copy_plan_to(root, docs, found.slug)
    plan = root / "plans" / f"{found.slug}.plan.md"
    current = {"name": found.slug, "plan": {"path": str(plan)}}
    current = auto_run._preflight_phase(root, current, progress=progress)
    if "pause" in current:
        return RunOutcome("paused", "implement", message=current["pause"]["reason"])
    # sampled before the launcher: a fast relay may commit while it starts
    base = worktrees._git(root, "rev-parse", "HEAD").strip()
    auto_run._launch(current, launcher=launcher, saved_phase=None)
    found = docset_mod.load(docs, found.slug)
    found.build_base = base
    docset_mod.save(docs, found)
    return RunOutcome("launched", "implement", build_base=base)


def choose_home(root, slug: str, *, choice: str, parent=None, folder=None, name=None,
                agents, progress) -> Path:
    """Apply the user's project home choice, mark the stage approved, return the root to continue in."""
    from whyline.sdlc import home

    root = Path(root)
    if choice not in ("new", "here"):
        raise ValueError(f"Unknown home choice {choice!r}: expected new or here.")
    docs = workspace.docs_root(root)
    found = docset_mod.load(docs, slug)
    # Saved first: the helper copies and commits the manifest, so it carries both records.
    # A helper failure rolls the record back so the home stage stays pending.
    had = "home" in found.skipped
    previous = found.skipped.get("home")
    found.skipped["home"] = f"chosen by the user: {choice}"
    docset_mod.save(docs, found)
    try:
        if choice == "new":
            target = home.create_home(
                root, slug, Path(parent) if parent else home.last_parent(),
                folder or home.folder_name(name or found.name), name=name or found.name,
                agents=agents, progress=progress,
            )
        else:
            target = home.use_here(root, slug)
    except BaseException:
        reverted = docset_mod.load(docs, slug)
        if had:
            reverted.skipped["home"] = previous
        else:
            reverted.skipped.pop("home", None)
        docset_mod.save(docs, reverted)
        raise
    return Path(target)


def run(root: Path, slug: str, *, progress=None, cancel_event=None, launcher=None) -> RunOutcome:
    """Run the set's stages in turn; the mode is read again before each one.

    Auto approves each finished document through its reviewer. Human stops after
    the first finished stage. Questions stop either. A set whose plan is approved
    is launched through Auto's preflight and launcher.
    """
    from whyline.sdlc import review
    from whyline.sdlc.stages import next_stage

    docs = workspace.docs_root(root)
    reviews: list[str] = []
    design_reviewed = False
    ran = False

    def outcome(state: str, stage: str = "", **kw) -> RunOutcome:
        return RunOutcome(state, stage, reviews=tuple(reviews), **kw)

    def cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    while True:
        if cancelled():
            return outcome("cancelled")
        found = docset_mod.load(docs, slug)
        found.design_reviewed = design_reviewed  # not stored: GFR-3 owns this marker
        stage = next_stage(found)
        if stage is None:
            return outcome("done")
        kind = stage.kind
        if kind in ("implement", "test", "review", "release"):
            if not found.build:
                return outcome("done")
            result = _launch_build(root, docs, found, progress=progress, launcher=launcher)
            result.reviews = tuple(reviews)
            return result
        if kind in ("build-record", "done"):
            return outcome("launched", kind, build_base=found.build_base or "")
        if kind == "home":
            return outcome("waiting_for_home", kind)  # only the user picks the name and folder
        if found.pending_questions.get(kind):
            return outcome("questions", kind, questions=tuple(found.pending_questions[kind]))
        if kind == "design-review":
            # the approved design, read by the Architect reviewer through all five lenses
            architect = str(found.roles.get("architect_reviewer") or "")
            try:
                if found.mode == docset_mod.Mode.AUTO.value:
                    text, stopped = review.auto_review(
                        root, slug, "design", agent=architect, progress=progress,
                        cancel_event=cancel_event,
                    )
                    reviews.append(text)
                    if stopped:
                        return outcome("waiting", kind, message=stopped)
                else:
                    review.review_again(
                        root, slug, "design", progress=progress, cancel_event=cancel_event,
                        agent=architect,
                    )
            except docset_mod.DocSetError as error:
                if cancelled():
                    return outcome("cancelled", kind)
                return outcome("error", kind, message=str(error))
            design_reviewed = True
            continue
        doc = found.document(kind)
        finished = doc is not None and doc["status"] == Status.IN_REVIEW.value
        if not finished:
            if ran and found.mode == docset_mod.Mode.HUMAN.value:
                return outcome("waiting", kind)
            result = run_stage(root, found, stage, progress=progress)
            ran = True
            if cancelled():
                return outcome("cancelled", kind)
            if result.error:
                return outcome("error", kind, message=result.error)
            if result.questions:
                return outcome("questions", kind, questions=result.questions)
            if result.skipped:
                continue
        fresh = review.has_lenses(found, kind)
        auto = docset_mod.load(docs, slug).mode == docset_mod.Mode.AUTO.value
        try:
            if not auto:
                if fresh and not finished:
                    # run before returning, so the findings are there when Docs opens
                    review.review_again(
                        root, slug, kind, progress=progress, cancel_event=cancel_event
                    )
                return outcome("waiting", kind)
            if fresh:
                text, stopped = review.auto_review(
                    root, slug, kind, progress=progress, cancel_event=cancel_event
                )
                if stopped:
                    reviews.append(text)
                    return outcome("waiting", kind, message=stopped)
            else:
                text, _ = review.auto_approve(
                    root, slug, kind, progress=progress, cancel_event=cancel_event
                )
        except docset_mod.DocSetError as error:
            if cancelled():
                return outcome("cancelled", kind)
            return outcome("error", kind, message=str(error))
        reviews.append(text)
        if progress is not None:
            progress(text)
