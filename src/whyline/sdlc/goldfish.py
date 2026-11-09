"""A fresh-eyes review: each lens reads one document in a new read-only agent process.

A reviewer sees the lens, the document's path and version, and the paths of the
approved documents before it. Never the request, the drafting conversation,
the review log or earlier reviews.
"""

from __future__ import annotations

import difflib
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from whyline.sdlc import docset as docset_mod, guard, lenses, product, runner, workspace
from whyline.sdlc.docset import DocSet, DocSetError, PrdMode, Status

TIMEOUT_SECONDS = 900
ATTEMPTS = 2
REVIEWS_DIR = "reviews"
ACTION = "fresh review"
CODE_LINE = "Read code in this repository when the document names it."
PRD_DIFF_LINE = "Judge the changed sections, and whether the rest of the PRD still agrees with them."
WRITER_NOTE = "Reviewed by the writer (no other read-only agent installed)."
STOPPED = "Stopped."

_SEVERITIES = (("blocker", "Blockers"), ("major", "Major"), ("nit", "Nits"))
_FIRST = re.compile(
    r"^Blockers: (\d+) · Major: (\d+) · Nits: (\d+) · Not run: (.+?) · Reviewer: (.+?)\s*$"
)
_LENSES_SUFFIX = re.compile(r"\s\(lenses: ([^)]*)\)\s*$")
_ITEM = re.compile(r"^- (.+?) — (.+?) — (.+?)\s*$")
_REPORT = re.compile(r"^(.+)-v(\d+)\.md$")


@dataclass(frozen=True)
class Review:
    path: Path
    findings: list[lenses.Finding] = field(default_factory=list)
    not_run: list[str] = field(default_factory=list)
    agent: str = ""


def _reviews_dir(docs: Path, slug: str) -> Path:
    return docset_mod._folder(docs, slug) / REVIEWS_DIR


def _reviewer(root: Path, agent: str, writer: str) -> tuple[str, bool]:
    """(agent to use, True when it is the writer for lack of any other)."""
    from whyline.relaychat import agent_choice

    available = agent_choice.choices(root)
    if agent not in available:
        raise DocSetError(f"{agent} has no read-only mode, so it can't review.")
    if agent != writer:
        return agent, False
    others = [name for name in available if name != writer]
    if others:
        return others[0], False
    return agent, True


def _approved_before(docset: DocSet, kind: str) -> list[str]:
    paths: list[str] = []
    for other in docset.documents:
        if other["kind"] == kind:
            break
        if other["status"] == Status.APPROVED.value:
            paths.append(other["path"])
    return paths


def _prd_diff(docs: Path, docset: DocSet, kind: str, text: str) -> str:
    if kind != "prd" or docset.prd_mode != PrdMode.UPDATE.value:
        return ""
    now = product.current(docs)
    if now is None:
        return ""
    diff = difflib.unified_diff(
        product.body(now.text).splitlines(),
        text.splitlines(),
        fromfile=f"product PRD v{now.version}",
        tofile="this PRD",
        lineterm="",
    )
    return "\n".join(diff)


def build_prompt(lens_body: str, doc: dict, before: list[str], diff: str = "") -> str:
    parts = [lens_body.strip(), f"Document: {doc['path']} (version {doc['version']})"]
    if before:
        parts.append("Approved documents before it:\n" + "\n".join(f"- {path}" for path in before))
    parts.append(CODE_LINE)
    if diff:
        parts.append(f"Changes against the current product PRD:\n\n{diff}\n\n{PRD_DIFF_LINE}")
    return "\n\n".join(parts)


def _without_resume(argv: list[str]) -> list[str]:
    """Drop any session-resume option so every lens starts with no earlier context."""
    out: list[str] = []
    skip = False
    for part in argv:
        if skip:
            skip = False
            continue
        if part == "--resume":
            skip = True
            continue
        if part.startswith("--resume=") or part in ("--continue", "resume"):
            continue
        out.append(part)
    return out


def _attempt(root: Path, docs: Path, agent: str, argv: list[str], lens: str, prompt: str,
             run: Callable, cancel_event) -> list[lenses.Finding] | None:
    """One new process for one lens: its findings, or None when it did not answer."""
    from whyline.agents import runner as agent_runner
    from whyline.relaychat import ask

    extra = {} if cancel_event is None else {"cancel_event": cancel_event}
    with tempfile.TemporaryDirectory(prefix="whyline-review-") as tmp:
        folder = Path(tmp)
        command, answer_file = argv, None
        try:
            adapter = agent_runner._adapter(SimpleNamespace(root=root), agent)
            if adapter is not None and adapter.uses_output_file:
                answer_file = folder / "answer.txt"
                command = [*argv, "-o", str(answer_file)]
        except Exception:
            command, answer_file = argv, None
        try:
            result = run(command, prompt, cwd=docs, log_path=folder / "output.log",
                         timeout_seconds=TIMEOUT_SECONDS, capture=True, echo=False,
                         agent_name=agent, env={"GIT_OPTIONAL_LOCKS": "0"}, **extra)
        except Exception:  # AgentTimeout, AgentMissing, AgentCancelled, OSError
            return None
        out = result.output or ""
        if result.exit_code != 0 or not out.strip() or ask.cancelled_turn(agent, out):
            return None
        text = ask.extract(root, agent, out, answer_file).strip()
        return lenses.parse_findings(lens, text)


def _merge(found: list[lenses.Finding]) -> list[tuple[lenses.Finding, list[str]]]:
    """Exact duplicates (same section and problem, ignoring case) become one entry,
    at the highest severity any lens gave it, with every lens that reported it."""
    order = [name for name, _ in _SEVERITIES]
    merged: dict[tuple[str, str], tuple[lenses.Finding, list[str]]] = {}
    for item in found:
        key = (item.section.strip().lower(), item.problem.strip().lower())
        if key not in merged:
            merged[key] = (item, [item.lens])
            continue
        first, names = merged[key]
        if item.lens not in names:
            names.append(item.lens)
        if order.index(item.severity) < order.index(first.severity):
            merged[key] = (
                lenses.Finding(first.lens, item.severity, first.section, first.problem, first.fix),
                names,
            )
    return list(merged.values())


def _render(merged, not_run: list[str], agent: str, writer_only: bool) -> tuple[str, str]:
    counts = {name: 0 for name, _ in _SEVERITIES}
    for item, _ in merged:
        counts[item.severity] += 1
    first = (
        f"Blockers: {counts['blocker']} · Major: {counts['major']} · Nits: {counts['nit']}"
        f" · Not run: {', '.join(not_run) or 'none'} · Reviewer: {agent}"
    )
    lines = [first, ""]
    if writer_only:
        lines += [WRITER_NOTE, ""]
    for name, title in _SEVERITIES:
        group = [(item, names) for item, names in merged if item.severity == name]
        if not group:
            continue
        lines += [f"## {title}", ""]
        for item, names in group:
            lines.append(
                f"- {item.section} — {item.problem} — {item.fix} (lenses: {', '.join(names)})"
            )
        lines.append("")
    return first, "\n".join(lines)


def review_document(root: Path, docset: DocSet, kind: str, *, agent: str,
                    progress: Callable[[str], None] | None = None,
                    cancel_event: threading.Event | None = None,
                    run_fn: Callable | None = None) -> Review:
    """Run every lens that applies to the document and write the report."""
    from whyline.relaychat import ask

    root = Path(root)
    refusal = guard.check(root)
    if refusal:
        raise DocSetError(refusal)
    doc = docset.document(kind)
    if doc is None:
        raise DocSetError(f"The document set {docset.slug!r} has no {kind!r} document.")
    names = lenses.lenses_for(docset.size, kind)
    if not names:
        raise DocSetError("No review lenses apply to this document.")
    docs = workspace.docs_root(root)
    chosen, writer_only = _reviewer(root, agent, runner._author(docset))
    argv = ask.command(root, chosen)
    if argv is None:
        raise DocSetError(f"{chosen} has no verified read-only mode, so it can't review.")
    argv = _without_resume(argv)
    if run_fn is None:
        from whyline_relay import agents

        run_fn = agents.run

    text = docset_mod._current_text(docs, docset, doc)
    before = _approved_before(docset, kind)
    diff = _prd_diff(docs, docset, kind, text)

    found: list[lenses.Finding] = []
    not_run: list[str] = []
    with guard.drafting(root, docset.slug, kind):
        for lens in names:
            prompt = build_prompt(lenses.lens_text(root, lens), doc, before, diff)
            result = None
            for _ in range(ATTEMPTS):
                if cancel_event is not None and cancel_event.is_set():
                    raise DocSetError(STOPPED)
                if progress is not None:
                    progress(f"fresh review · {chosen} reads the {kind} through the {lens} lens")
                result = _attempt(root, docs, chosen, argv, lens, prompt, run_fn, cancel_event)
                if result is not None:
                    break
            if result is None:
                if cancel_event is not None and cancel_event.is_set():
                    raise DocSetError(STOPPED)
                not_run.append(lens)
            else:
                found.extend(result)
        merged = _merge(found)
        first, body = _render(merged, not_run, chosen, writer_only)
        path = _reviews_dir(docs, docset.slug) / f"{kind}-v{doc['version']}.md"
        docset_mod._write(path, body)
        docset_mod.log_review(docs, docset, kind, actor=chosen, action=ACTION, comment=first)
    return Review(path, [item for item, _ in merged], not_run, chosen)


def latest_review(root: Path, docset: DocSet, kind: str) -> Review | None:
    """The report for the highest version of the document that has one."""
    docs = workspace.docs_root(Path(root))
    folder = _reviews_dir(docs, docset.slug)
    best: tuple[int, Path] | None = None
    if folder.is_dir():
        for path in folder.iterdir():
            m = _REPORT.match(path.name)
            if m and m.group(1) == kind and path.is_file():
                number = int(m.group(2))
                if best is None or number > best[0]:
                    best = (number, path)
    if best is None:
        return None
    try:
        lines = best[1].read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    head = _FIRST.match(lines[0]) if lines else None
    if head is None:
        return None
    not_run = [] if head.group(4) == "none" else [n.strip() for n in head.group(4).split(",")]
    titles = {title: name for name, title in _SEVERITIES}
    found: list[lenses.Finding] = []
    severity = ""
    for line in lines[1:]:
        if line.startswith("## "):
            severity = titles.get(line[3:].strip(), "")
            continue
        if not severity:
            continue
        suffix = _LENSES_SUFFIX.search(line)
        item = _ITEM.match(_LENSES_SUFFIX.sub("", line))
        if suffix and item:
            found.append(lenses.Finding(
                suffix.group(1), severity, item.group(1), item.group(2), item.group(3)))
    return Review(best[1], found, not_run, head.group(5))
