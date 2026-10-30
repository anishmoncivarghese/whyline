"""Draft an application for one tracked job with the `job-apply` agent (JOB-19).

The posting is written to ~/.whyline/jobs/applications/<company>_<title>/posting.md, the agent
reads it next to cv.md, profile.md and preferences.toml, and its answer is saved there as
draft.md and draft.docx. A run that fails writes no draft.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from whyline.agents import capabilities, convert, definitions as d, runner, templates
from whyline.jobs import fetch, guard, paths, review, step, tracker

TEMPLATE_NAME = "job-apply"
AGENT_NAME = "job-apply"
APPLICATIONS_DIR = "applications"
POSTING_FILE = "posting.md"
DRAFT_FILE = "draft.md"
DOCX_FILE = "draft.docx"
REVIEW_FILE = "review.md"
FINAL_FILE = "final.md"
FINAL_DOCX_FILE = "final.docx"
REVIEW_INSTRUCTIONS = "review.md"
NO_REVIEWER_NOTE = "No second provider for review"
DRAFT_NOTE = "draft ready"
GAPS_HEADING = "gaps (not added)"
INTERVIEW_TEMPLATE = "job-interview"
INTERVIEW_AGENT = "job-interview"
INTERVIEW_STATUS = "interview"
INTERVIEW_FILE = "interview.md"
INTERVIEW_DOCX_FILE = "interview.docx"
INTERVIEW_HEADINGS = ("likely questions", "questions to ask", "gaps to prepare")
RUNNABLE_CLIS = review.RUNNABLE_CLIS
_REPORTED_OUTCOMES = ("succeeded", "succeeded_with_denials")


class ApplyError(Exception):
    """A draft request that cannot be done (unknown job, unwritable folder, bad agent)."""


@dataclass(frozen=True)
class DraftResult:
    ok: bool
    outcome: str
    reason: str = ""
    cli: str = ""
    run_id: str = ""
    folder: Path | None = None
    draft_path: Path | None = None
    docx_path: Path | None = None
    review_path: Path | None = None
    final_path: Path | None = None
    final_docx_path: Path | None = None
    reviewer: str = ""
    review_note: str = ""


def applications_dir() -> Path:
    return paths.configured_home() / APPLICATIONS_DIR


def folder_for(row: dict) -> Path:
    name = f"{step._slug(str(row.get('company') or ''))}_{step._slug(str(row.get('title') or ''))}"
    return applications_dir() / name


def _find_row(ref: str) -> dict:
    ref = str(ref).strip()
    for row in tracker.list_rows():
        if row["uid"] == ref or (ref.isdigit() and row["row"] == int(ref)):
            return row
    raise ApplyError(f"No tracked job '{ref}'.")


def _posting_markdown(row: dict, http: Callable[..., Any] | None) -> str:
    """The full posting from the company's board; the tracked row's own facts when it has gone."""
    found: fetch.Posting | None = None
    try:
        for posting in fetch.board_jobs(row["company"], http):
            if posting.uid == row["uid"]:
                found = posting
                break
    except Exception:  # no board, offline or gone: fall back to what the tracker holds
        found = None
    if found is None:
        reason = str(row.get("reason") or "").strip()
        found = fetch.Posting(
            uid=row["uid"], company=row["company"], title=row["title"], url=row["url"],
            text=(reason + "\n\n" if reason else "")
            + "Only the tracker's summary is available for this job.",
        )
    text, _flagged = guard.clean(found.text)
    return replace(found, text=text).to_markdown()


def _write_private(target: Path, text: str) -> None:
    if target.is_symlink():
        raise ApplyError(f"Refusing to overwrite symlink: {target}")
    fd, raw = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    tmp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _find_or_create_agent(template: str = TEMPLATE_NAME, name: str = AGENT_NAME) -> d.AgentDef:
    configured = paths.configured_home()
    default_jobs = Path.home() / ".whyline" / "jobs"
    workdir = "~/.whyline/jobs" if configured == default_jobs else str(configured)
    for item in d.discover(None):
        if isinstance(item, d.AgentDef) and item.kind == "personal" and item.name == name:
            return item
        if isinstance(item, d.Broken) and item.kind == "personal" and item.path.stem == name:
            raise ApplyError(f"Agent definition {item.path.name} is invalid: {item.error}")
    return templates.create(template, name, workdir)


def draft(
    uid: str,
    cli: str | None = None,
    *,
    progress: Callable[[str], None] | None = None,
    run_fn: Any = None,
    http: Callable[..., Any] | None = None,
    unattended_fn: Callable[[str], bool] | None = None,
) -> DraftResult:
    """Draft the application for the tracked job `uid` (or row number)."""
    row = _find_row(uid)
    enabled = review.enabled_providers()
    chosen: str | None = None
    if cli is not None:
        chosen = str(cli).strip()
        if chosen not in d.CLIS or not capabilities.can_run(chosen):
            raise ApplyError(
                f"Unsupported provider '{chosen}'. Choose one of: {', '.join(RUNNABLE_CLIS)}."
            )
        if chosen not in enabled:
            return DraftResult(
                ok=False, outcome="all_unavailable",
                reason=f"{chosen}: Enable {chosen} in Settings or choose another provider.",
            )
    elif not enabled:
        return DraftResult(
            ok=False, outcome="all_unavailable",
            reason="No enabled AI provider can run agents. Enable Claude, Codex, or Grok in Settings.",
        )

    try:
        jobs_dir = paths.home()
        folder = folder_for(row)
        folder.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            folder.chmod(0o700)
        _write_private(folder / POSTING_FILE, _posting_markdown(row, http))
        defn = _find_or_create_agent()
    except (ApplyError, d.DefinitionError, OSError) as error:
        return DraftResult(ok=False, outcome="failed", reason=str(error))

    sources = (*defn.sources, (folder / POSTING_FILE).relative_to(jobs_dir).as_posix())
    if chosen is not None:
        run_defn = replace(defn, root=jobs_dir, sources=sources, runner=chosen, backup=())
    else:
        preferred = [c for c in (defn.runner, *defn.backup) if c in enabled]
        order = preferred if preferred else list(enabled)
        run_defn = replace(
            defn, root=jobs_dir, sources=sources, runner=order[0], backup=tuple(order[1:])
        )

    kwargs: dict[str, Any] = {"source": "manual"}
    if progress is not None:
        kwargs["progress"] = progress
    if run_fn is not None:
        kwargs["run_fn"] = run_fn
    record = runner.execute_once(run_defn, **kwargs)
    outcome = getattr(record, "outcome", "") or "failed"
    reason = getattr(record, "reason", "") or ""
    base = {
        "cli": getattr(record, "cli", "") or "",
        "run_id": getattr(record, "run_id", "") or "",
        "folder": folder,
    }
    if outcome not in _REPORTED_OUTCOMES:
        return DraftResult(ok=False, outcome=outcome, reason=reason, **base)

    answer = review._read_run_answer(record).replace("\r\n", "\n").strip()
    if GAPS_HEADING not in answer.lower():
        return DraftResult(
            ok=False, outcome="malformed_answer",
            reason="The agent's answer has no 'Gaps (not added)' section.", **base,
        )

    draft_path = folder / DRAFT_FILE
    try:
        _write_private(draft_path, answer + "\n")
        docx_path = convert.to_docx(draft_path, folder / DOCX_FILE)
        if docx_path is not None and os.name != "nt":
            os.chmod(docx_path, 0o600)
        tracker.set_status(row["uid"], row["status"], DRAFT_NOTE)
    except (ApplyError, tracker.TrackerError, OSError) as error:
        return DraftResult(ok=False, outcome="failed", reason=str(error), **base)

    result = DraftResult(
        ok=True, outcome=outcome, reason=reason, draft_path=draft_path,
        docx_path=docx_path, **base,
    )
    reviewer = pick_reviewer(
        [defn.runner, *defn.backup], base["cli"], enabled, unattended_fn
    )
    if reviewer is None:
        return replace(result, review_note=NO_REVIEWER_NOTE)
    try:
        return _review_and_revise(
            result, run_defn, reviewer, folder, jobs_dir, kwargs, answer
        )
    except (ApplyError, OSError) as error:
        return replace(result, review_note=f"Review failed: {error}")


def interview(
    uid: str,
    cli: str | None = None,
    *,
    progress: Callable[[str], None] | None = None,
    run_fn: Any = None,
    http: Callable[..., Any] | None = None,
) -> DraftResult:
    """Prepare for the interview of the tracked job `uid` (or row number).

    Writes interview.md and interview.docx beside the posting in the application folder.
    """
    row = _find_row(uid)
    if row["status"] != INTERVIEW_STATUS:
        raise ApplyError(
            f"'{row['company']} — {row['title']}' is {row['status']}, not {INTERVIEW_STATUS}. "
            f"Set it to {INTERVIEW_STATUS} before preparing for an interview."
        )
    enabled = review.enabled_providers()
    chosen = str(cli).strip() if cli is not None else None
    if chosen is not None:
        if chosen not in d.CLIS or not capabilities.can_run(chosen):
            raise ApplyError(
                f"Unsupported provider '{chosen}'. Choose one of: {', '.join(RUNNABLE_CLIS)}."
            )
        if chosen not in enabled:
            return DraftResult(
                ok=False, outcome="all_unavailable",
                reason=f"{chosen}: Enable {chosen} in Settings or choose another provider.",
            )
    elif not enabled:
        return DraftResult(
            ok=False, outcome="all_unavailable",
            reason="No enabled AI provider can run agents. Enable Claude, Codex, or Grok in Settings.",
        )

    try:
        jobs_dir = paths.home()
        folder = folder_for(row)
        folder.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            folder.chmod(0o700)
        _write_private(folder / POSTING_FILE, _posting_markdown(row, http))
        defn = _find_or_create_agent(INTERVIEW_TEMPLATE, INTERVIEW_AGENT)
    except (ApplyError, d.DefinitionError, OSError) as error:
        return DraftResult(ok=False, outcome="failed", reason=str(error))

    sources = (*defn.sources, (folder / POSTING_FILE).relative_to(jobs_dir).as_posix())
    if chosen is not None:
        run_defn = replace(defn, root=jobs_dir, sources=sources, runner=chosen, backup=())
    else:
        preferred = [c for c in (defn.runner, *defn.backup) if c in enabled]
        order = preferred if preferred else list(enabled)
        run_defn = replace(
            defn, root=jobs_dir, sources=sources, runner=order[0], backup=tuple(order[1:])
        )

    kwargs: dict[str, Any] = {"source": "manual"}
    if progress is not None:
        kwargs["progress"] = progress
    if run_fn is not None:
        kwargs["run_fn"] = run_fn
    record = runner.execute_once(run_defn, **kwargs)
    outcome = getattr(record, "outcome", "") or "failed"
    reason = getattr(record, "reason", "") or ""
    base = {
        "cli": getattr(record, "cli", "") or "",
        "run_id": getattr(record, "run_id", "") or "",
        "folder": folder,
    }
    if outcome not in _REPORTED_OUTCOMES:
        return DraftResult(ok=False, outcome=outcome, reason=reason, **base)

    answer = review._read_run_answer(record).replace("\r\n", "\n").strip()
    if not all(h in answer.lower() for h in INTERVIEW_HEADINGS):
        return DraftResult(
            ok=False, outcome="malformed_answer",
            reason="The agent's answer is missing 'Likely questions', 'Questions to ask' or "
            "'Gaps to prepare'.", **base,
        )

    md_path = folder / INTERVIEW_FILE
    try:
        _write_private(md_path, answer + "\n")
        docx_path = convert.to_docx(md_path, folder / INTERVIEW_DOCX_FILE)
        if docx_path is not None and os.name != "nt":
            os.chmod(docx_path, 0o600)
    except (ApplyError, OSError) as error:
        return DraftResult(ok=False, outcome="failed", reason=str(error), **base)
    return DraftResult(
        ok=True, outcome=outcome, reason=reason, draft_path=md_path, docx_path=docx_path, **base
    )


def pick_reviewer(
    chain: list[str],
    drafter: str,
    enabled: list[str],
    unattended_fn: Callable[[str], bool] | None = None,
) -> str | None:
    """The first enabled, unattended-cleared provider in the chain that is not the drafter."""
    unattended_fn = unattended_fn or capabilities.can_run_unattended
    for cli in chain:
        if cli != drafter and cli in enabled and unattended_fn(cli):
            return cli
    return None


def _review_instructions() -> str:
    path = templates._template_folder(TEMPLATE_NAME) / REVIEW_INSTRUCTIONS
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ApplyError(f"Could not read {path.name}: {error}") from error


def _run_turn(defn: d.AgentDef, kwargs: dict[str, Any]) -> tuple[Any, str]:
    record = runner.execute_once(defn, **kwargs)
    if (getattr(record, "outcome", "") or "failed") not in _REPORTED_OUTCOMES:
        reason = getattr(record, "reason", "") or getattr(record, "outcome", "") or "failed"
        raise ApplyError(str(reason))
    answer = review._read_run_answer(record).replace("\r\n", "\n").strip()
    if not answer:
        raise ApplyError("The agent returned no answer.")
    return record, answer


def _review_and_revise(
    result: DraftResult,
    run_defn: d.AgentDef,
    reviewer: str,
    folder: Path,
    jobs_dir: Path,
    kwargs: dict[str, Any],
    draft_text: str,
) -> DraftResult:
    rel = lambda name: (folder / name).relative_to(jobs_dir).as_posix()  # noqa: E731
    cv_and_posting = tuple(
        s for s in run_defn.sources if s == "cv.md" or s == rel(POSTING_FILE)
    )
    review_defn = replace(
        run_defn, instructions=_review_instructions(), runner=reviewer, backup=(),
        sources=(*cv_and_posting, rel(DRAFT_FILE)),
    )
    _record, critiques = _run_turn(review_defn, kwargs)
    review_path = folder / REVIEW_FILE
    _write_private(review_path, critiques + "\n")

    revise_defn = replace(
        run_defn,
        instructions=(
            run_defn.instructions
            + "\n\nA second reviewer critiqued your earlier draft. Revise it to address the"
            " critiques that are right, keeping every rule above, and answer with the complete"
            " revised four sections.\n\nCritiques:\n" + critiques
            + "\n\nEarlier draft:\n" + draft_text
        ),
        runner=result.cli or run_defn.runner, backup=(),
    )
    _record, final = _run_turn(revise_defn, kwargs)
    if GAPS_HEADING not in final.lower():
        raise ApplyError("The revised draft has no 'Gaps (not added)' section.")
    final_path = folder / FINAL_FILE
    _write_private(final_path, final + "\n")
    final_docx = convert.to_docx(final_path, folder / FINAL_DOCX_FILE)
    if final_docx is not None and os.name != "nt":
        os.chmod(final_docx, 0o600)
    return replace(
        result, review_path=review_path, final_path=final_path, final_docx_path=final_docx,
        reviewer=reviewer, review_note=f"Reviewed by {reviewer}",
    )
