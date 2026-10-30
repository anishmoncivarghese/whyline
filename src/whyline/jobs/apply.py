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
DRAFT_NOTE = "draft ready"
GAPS_HEADING = "gaps (not added)"
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


def _find_or_create_agent() -> d.AgentDef:
    configured = paths.configured_home()
    default_jobs = Path.home() / ".whyline" / "jobs"
    workdir = "~/.whyline/jobs" if configured == default_jobs else str(configured)
    for item in d.discover(None):
        if isinstance(item, d.AgentDef) and item.kind == "personal" and item.name == AGENT_NAME:
            return item
        if isinstance(item, d.Broken) and item.kind == "personal" and item.path.stem == AGENT_NAME:
            raise ApplyError(f"Agent definition {item.path.name} is invalid: {item.error}")
    return templates.create(TEMPLATE_NAME, AGENT_NAME, workdir)


def draft(
    uid: str,
    cli: str | None = None,
    *,
    progress: Callable[[str], None] | None = None,
    run_fn: Any = None,
    http: Callable[..., Any] | None = None,
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
    return DraftResult(
        ok=True, outcome=outcome, reason=reason, draft_path=draft_path,
        docx_path=docx_path, **base,
    )
