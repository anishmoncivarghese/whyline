"""The build record: what the build produced, and the decisions behind a document set."""

from __future__ import annotations

import re
from pathlib import Path

from whyline import decisions, worktrees
from whyline.sdlc import docset as docset_mod
from whyline.sdlc import runner, templates, workspace
from whyline.sdlc.docset import DocSet, Status

INPUTS = "build-inputs.md"
DECISIONS = "decisions.md"
DRIFT = "drift.md"
DRIFT_LINE = (
    "Compare what the document promised with what was built. A finding is something "
    "promised and not built, or built and not in the document."
)
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$")


def _folder(docs: Path, docset: DocSet) -> Path:
    return docs / docset_mod.SDLC_DIR / docset.slug


def _task_ids(docs: Path, docset: DocSet) -> list[str]:
    from whyline_relay import plan

    path = docset_mod.plan_file(docs, docset.slug)
    if path is None:
        return []
    try:
        return [task.task_id for task in plan.parse(path.read_text(encoding="utf-8"))]
    except plan.PlanError:
        return []


def _git_log(root: Path, base: str | None) -> str:
    if not base:
        return "No build base was recorded."
    try:
        out = worktrees._git(root, "log", "--oneline", f"{base}..HEAD").strip()
    except Exception as error:
        return f"The commits could not be read: {error}"
    return out or "No commits since the build base."


def _scenarios(docs: Path, docset: DocSet) -> str:
    from whyline_relay import testplan

    path = docset_mod.plan_file(docs, docset.slug, tests=True)
    if path is None:
        return "There is no test plan."
    found = testplan.parse(path.read_text(encoding="utf-8"))
    if not found:
        return "The test plan has no scenarios."
    return "\n".join(
        f"- {s.id}: {s.title} — {'passed' if s.checked else 'failed'}" for s in found
    )


def _release_tag(root: Path, base: str | None) -> str:
    if not base:
        return ""
    try:
        tags = worktrees._git(root, "tag", "--merged", "HEAD", "--contains", base, "--sort=creatordate").split()
        at_base = set(worktrees._git(root, "tag", "--points-at", base).split())
    except Exception:
        return ""
    later = [tag for tag in tags if tag not in at_base]
    return later[-1] if later else ""


def _history(root: Path) -> list[dict]:
    from whyline import history, paths

    if not paths.is_initialised(Path(root)):
        return []
    return [entry.event for entry in history.load(Path(root), mechanical=False).active]


def _entries(root: Path, docs: Path, docset: DocSet) -> list[dict]:
    """Decisions for the set's slug or its plan's task ids, oldest first."""
    wanted = {docset.slug, *_task_ids(docs, docset)}
    chosen = [event for event in _history(root) if event.get("task") in wanted]
    return sorted(chosen, key=lambda event: str(event.get("ts", "")))


def _section(text: str, title: str) -> str:
    """The body under a heading called `title`, up to the next heading of the same or higher level."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if match and match.group(2).strip().lower() == title.lower():
            level = len(match.group(1))
            body: list[str] = []
            for following in lines[index + 1:]:
                other = _HEADING.match(following)
                if other and len(other.group(1)) <= level:
                    break
                body.append(following)
            return "\n".join(body).strip()
    return ""


def build_inputs(root: Path, docset: DocSet) -> Path:
    """Write `build-inputs.md` beside the set's documents and return its path."""
    root = Path(root)
    docs = workspace.docs_root(root)
    parts = [
        f"# Build inputs: {docset.name}",
        "",
        "## Commits",
        "",
        _git_log(root, docset.build_base),
        "",
        "## Test scenarios",
        "",
        _scenarios(root, docset),
        "",
        "## Decisions",
        "",
    ]
    ids = set(_task_ids(docs, docset))
    entries = [event for event in _entries(root, docs, docset) if event.get("task") in ids]
    parts.append(
        "\n".join(decisions.render_entry(event).replace("## ", "### ", 1) for event in entries)
        if entries
        else "No decisions were recorded for the plan's tasks."
    )
    tag = _release_tag(root, docset.build_base)
    if tag:
        parts += ["", "## Release", "", f"Tagged {tag}."]
    path = _folder(docs, docset) / INPUTS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return path


def _diff_stat(root: Path, base: str | None) -> str:
    if not base:
        raise docset_mod.DocSetError("no build base was recorded")
    try:
        out = worktrees._git(root, "diff", "--stat", f"{base}..HEAD").strip()
    except Exception as error:
        raise docset_mod.DocSetError(f"the diff could not be read: {error}") from error
    return out or "No files changed since the build base."


def drift_review(root: Path, docset: DocSet, *, agent: str, progress=None, run_fn=None) -> Path:
    """Run the codebase-fit lens once on the approved design (else spec) against the build's diff.

    Writes `reviews/drift.md` and returns its path; raises DocSetError when the lens didn't run.
    """
    from whyline.relaychat import ask
    from whyline.sdlc import goldfish, guard, lenses

    root = Path(root)
    refusal = guard.check(root)
    if refusal:
        raise docset_mod.DocSetError(refusal)
    docs = workspace.docs_root(root)
    doc = next((d for d in (docset.document("design"), docset.document("spec")) if d), None)
    if doc is None:
        raise docset_mod.DocSetError("the set has no spec or design")
    stat = _diff_stat(root, docset.build_base)
    chosen, _ = goldfish._reviewer(root, agent, runner._author(docset))
    argv = ask.command(root, chosen)
    if argv is None:
        raise docset_mod.DocSetError(f"{chosen} has no verified read-only mode, so it can't review.")
    argv = goldfish._without_resume(argv)
    if run_fn is None:
        from whyline_relay import agents

        run_fn = agents.run
    prompt = "\n\n".join(
        [
            goldfish.build_prompt(
                lenses.lens_text(root, "codebase-fit"), doc, goldfish._approved_before(docset, doc["kind"])
            ),
            f"git diff --stat {docset.build_base}..HEAD:\n\n{stat}",
            DRIFT_LINE,
        ]
    )
    found = None
    with guard.drafting(root, docset.slug, doc["kind"]):
        for _ in range(goldfish.ATTEMPTS):
            if progress is not None:
                progress(f"drift check · {chosen} compares the {doc['kind']} with the build")
            found = goldfish._attempt(root, docs, chosen, argv, "codebase-fit", prompt, run_fn, None)
            if found is not None:
                break
    if found is None:
        raise docset_mod.DocSetError(f"{chosen} gave no usable answer")
    lines = [f"- [{f.severity}] {f.section} — {f.problem} — {f.fix}" for f in found]
    path = goldfish._reviews_dir(docs, docset.slug) / DRIFT
    docset_mod._write(path, "\n".join(["# Drift from the spec", "", *(lines or ["No findings."])]) + "\n")
    return path


def _drift(root: Path, found: DocSet, *, progress, cancel_event) -> Path:
    """`drift.md` for the build record: the findings, or why the check didn't run."""
    from whyline.sdlc import goldfish, review

    try:
        return drift_review(root, found, agent=review.reviewer_for(found, "build-record"), progress=progress)
    except Exception as error:
        if cancel_event is not None and cancel_event.is_set():
            raise
        path = goldfish._reviews_dir(workspace.docs_root(root), found.slug) / DRIFT
        docset_mod._write(path, f"Drift check didn't run: {error}\n")
        return path


def render_decisions(root: Path, docset: DocSet) -> str:
    """The text of `decisions.md`: the design's Decision records, then every recorded decision."""
    root = Path(root)
    docs = workspace.docs_root(root)
    parts = [f"# Decisions: {docset.name}", ""]
    design = docset.document("design")
    records = _section(docset_mod._current_text(docs, docset, design), "Decision records") if design else ""
    if records:
        parts += ["## Decision records", "", records, ""]
    entries = _entries(root, docs, docset)
    parts += ["## Recorded decisions", ""]
    if entries:
        parts += [decisions.render_entry(event).replace("## ", "### ", 1) for event in entries]
    else:
        parts += ["No decisions have been recorded yet.", ""]
    return "\n".join(parts).rstrip() + "\n"


def write_decisions(root: Path, docset: DocSet) -> Path:
    docs = workspace.docs_root(Path(root))
    path = _folder(docs, docset) / DECISIONS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_decisions(root, docset), encoding="utf-8")
    return path


def set_for_plan(root: Path, plan_path: Path | None) -> DocSet | None:
    """The built set whose plan file is `plan_path`, if its build record is still to do."""
    if plan_path is None:
        return None
    slug = Path(plan_path).name.removesuffix(".plan.md")
    docs = workspace.docs_root(Path(root))
    try:
        found = docset_mod.load(docs, slug)
    except docset_mod.DocSetError:
        return None
    if not found.build_base:
        return None
    record = found.document("build-record")
    if record is None or record["status"] != Status.DRAFT.value:
        return None
    return found


def run_build_record(root: Path, slug: str, *, progress=None, cancel_event=None) -> str:
    """Draft the build record with `build-inputs.md` attached; Auto has the reviewer approve it.

    Returns the stage's outcome: `approved` (Auto) or `waiting` (Human, in Docs).
    """
    from whyline.console import relay_ops
    from whyline.sdlc import review

    root = Path(root)
    docs = workspace.docs_root(root)
    found = docset_mod.load(docs, slug)
    inputs = build_inputs(root, found)
    drift = _drift(root, found, progress=progress, cancel_event=cancel_event)
    attachments = [*runner._attachments(docs, found, "build-record"), inputs, drift]
    draft = relay_ops.draft_document(
        docs,
        "build-record",
        runner._request(found),
        template=templates.template_for(docs, "build-record", found.size),
        attachments=attachments,
        progress=progress,
    )
    relay_ops.discard_document(docs, "build-record")
    runner._finish(
        docs, found, "build-record", draft.text, note=f"drafted by {runner._author(found)}"
    )
    found = docset_mod.load(docs, slug)
    if found.mode == docset_mod.Mode.AUTO.value:
        review.auto_approve(root, slug, "build-record", progress=progress, cancel_event=cancel_event)
        outcome = "approved"
    else:
        outcome = "waiting"
    found = docset_mod.load(docs, slug)
    write_decisions(root, found)
    docset_mod.commit(docs, found, f"docs: decisions for {found.name}")
    return outcome
