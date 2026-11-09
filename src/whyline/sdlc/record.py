"""The build record: what the build produced, and the decisions behind a document set."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


@dataclass
class Amendments:
    """Task and scenario ids the code checkout's plan files changed since approval."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def summary(self) -> str:
        return "; ".join(
            f"{label} {_ranges(ids)}"
            for label, ids in (("added", self.added), ("removed", self.removed), ("changed", self.changed))
            if ids
        )


_NUMBERED = re.compile(r"(.*?)(\d+)")


def _ranges(ids: list[str]) -> str:
    """`GFR-1..6` for three or more consecutive numbers under one prefix; other ids as listed."""
    parts = [_NUMBERED.fullmatch(i) for i in ids]
    out: list[str] = []
    at = 0
    while at < len(ids):
        end = at
        while (
            parts[at] is not None
            and end + 1 < len(ids)
            and parts[end + 1] is not None
            and parts[end + 1].group(1) == parts[at].group(1)
            and int(parts[end + 1].group(2)) == int(parts[end].group(2)) + 1
        ):
            end += 1
        if end - at >= 2:
            out.append(f"{ids[at]}..{parts[end].group(2)}")
            at = end + 1
        else:
            out.append(ids[at])
            at += 1
    return ", ".join(out)


def _approved_plan_text(docs: Path, docset: DocSet) -> str | None:
    """The approved plan: its newest stored version, else the plan file in the docs checkout."""
    doc = docset.document("plan")
    if doc is None:
        return None
    stored = docset_mod._history_path(docs, docset.slug, "plan", int(doc["version"]))
    if stored.is_file():
        return stored.read_text(encoding="utf-8")
    return _read(docs, docset.slug, tests=False)


def _read(folder: Path, slug: str, *, tests: bool) -> str | None:
    path = docset_mod.plan_file(folder, slug, tests=tests)
    return path.read_text(encoding="utf-8") if path else None


def _compare(before: dict, after: dict, found: Amendments) -> None:
    found.added += [i for i in after if i not in before]
    found.removed += [i for i in before if i not in after]
    found.changed += [i for i in after if i in before and after[i] != before[i]]


def _plan_tasks(text: str | None) -> dict[str, str]:
    from whyline_relay import plan

    if not text:
        return {}
    try:
        return {task.task_id: task.text for task in plan.parse(text)}
    except plan.PlanError:
        return {}


def _scenario_map(text: str | None) -> dict[str, tuple]:
    from whyline_relay import testplan

    if not text:
        return {}
    return {s.id: (s.title, s.covers, s.kind, s.steps, s.expected) for s in testplan.parse(text)}


def plan_amendments(root: Path, docs: Path, docset: DocSet) -> Amendments:
    """Compare the approved plan and test plan with the files in the code checkout `root`.

    Ticked boxes and scenario notes don't count. Ids are plan tasks, then test scenarios.
    """
    root, docs = Path(root), Path(docs)
    found = Amendments()
    approved, built = _approved_plan_text(docs, docset), _read(root, docset.slug, tests=False)
    if approved is not None and built is not None and (
        docset_mod.content_hash("plan", approved) != docset_mod.content_hash("plan", built)
    ):
        _compare(_plan_tasks(approved), _plan_tasks(built), found)
    approved_tests, built_tests = _read(docs, docset.slug, tests=True), _read(root, docset.slug, tests=True)
    if approved_tests is not None and built_tests is not None:
        _compare(_scenario_map(approved_tests), _scenario_map(built_tests), found)
    return found


def _git_user(root: Path) -> str:
    try:
        return worktrees._git(root, "config", "user.name").strip() or "whyline"
    except Exception:
        return "whyline"


def record_amendments(root: Path, docs: Path, docset: DocSet) -> Amendments:
    """Store the code checkout's plan as a new approved version when the build changed it."""
    root, docs = Path(root), Path(docs)
    found = plan_amendments(root, docs, docset)
    if not found:
        return found
    who = f"{_git_user(root)} (during build)"
    note = f"amended during build: {found.summary()}"
    built = _read(root, docset.slug, tests=False)
    approved = _approved_plan_text(docs, docset)
    if built is not None:
        old = int(docset_mod._doc(docset, "plan")["version"])
        stored = docset_mod._history_path(docs, docset.slug, "plan", old)
        if approved is not None and not stored.is_file():
            docset_mod._write(stored, approved)  # keep the approved text as its own version
        approved_tests = _read(docs, docset.slug, tests=True)
        old_tests = stored.with_name(f"plan-v{old}.tests.md")
        if approved_tests is not None and not old_tests.is_file():
            docset_mod._write(old_tests, approved_tests)
        number = docset_mod.add_version(docs, docset, "plan", built, author=who, note=note)
        built_tests = _read(root, docset.slug, tests=True)
        if built_tests is not None:
            docset_mod._write(stored.with_name(f"plan-v{number}.tests.md"), built_tests)
    doc = docset_mod._doc(docset, "plan")
    doc["status"] = Status.APPROVED.value
    doc["approved_by"] = who
    doc["approved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    doc["amended_during_build"] = True
    doc["amendments"] = {"added": found.added, "removed": found.removed, "changed": found.changed}
    doc["note"] = note
    doc.pop("out_of_date_reason", None)
    docset_mod.log_review(docs, docset, "plan", actor=who, action="amended during build", comment=note)
    docset_mod.save(docs, docset)
    docset_mod.refresh(docs, docset)
    for tests in (False, True):
        text = _read(root, docset.slug, tests=tests)
        target = docset_mod.plan_file(docs, docset.slug, tests=tests)
        if text is not None and target is not None and target.read_text(encoding="utf-8") != text:
            target.write_text(text, encoding="utf-8")
    return found


def _recorded_amendments(docset: DocSet) -> Amendments:
    doc = docset.document("plan") or {}
    return Amendments(**{k: list(v) for k, v in (doc.get("amendments") or {}).items()})


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
    amended = plan_amendments(root, docs, docset) or _recorded_amendments(docset)
    if amended:
        parts += ["", "## Plan changes during the build", ""]
        for label, ids in (("Added", amended.added), ("Removed", amended.removed), ("Changed", amended.changed)):
            if ids:
                parts.append(f"- {label}: {', '.join(ids)}")
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
