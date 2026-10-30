"""The `jobs-fetch` before step: fetch, clean, filter and de-duplicate postings (JOB-12)."""
from __future__ import annotations

import dataclasses
import json
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import alerts, ats, companies, fetch, guard, paths, profile, seen

MAX_POSTINGS = 40
MANIFEST = "manifest.json"
PREVIEW_DIR = "preview"

_ALERT_NOTE = "Only the alert summary is available for this job."
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class CompanyCount:
    new: int = 0
    dropped: int = 0
    errors: int = 0


@dataclass
class Report:
    """What one fetch did, per company; filled in by `jobs_fetch` when passed in."""

    written: int = 0
    dry_run: bool = False
    folder: Path | None = None
    companies: dict[str, CompanyCount] = field(default_factory=dict)
    errors: list[tuple[str, str]] = field(default_factory=list)
    dropped: list[tuple[str, str, str]] = field(default_factory=list)  # (company, title, reason)

    def count(self, name: str) -> CompanyCount:
        return self.companies.setdefault(name, CompanyCount())

    def lines(self) -> list[str]:
        rows = [
            f"{name}: {c.new} new, {c.dropped} dropped, {c.errors} errors"
            for name, c in self.companies.items()
        ]
        rows.extend(f"{name}: error: {message}" for name, message in self.errors)
        return rows

    def summary(self) -> str:
        noun = "posting" if self.written == 1 else "postings"
        mode = " (dry run, nothing marked seen)" if self.dry_run else ""
        return f"{self.written} new {noun}{mode}."


def _slug(value: str, limit: int = 40) -> str:
    return _SLUG_RE.sub("-", value.lower()).strip("-")[:limit].strip("-") or "x"


def _filename(index: int, posting: fetch.Posting) -> str:
    return f"{index:02d}-{_slug(posting.company)}-{_slug(posting.title)}.md"


def _fetchable(entries: list[companies.Company]) -> list[companies.Company]:
    return [e for e in entries if e.slug and e.ats in fetch.LIST_URLS]


def _enrich(
    waiting: list[fetch.Posting],
    entries: list[companies.Company],
    board_postings: tuple[fetch.Posting, ...],
    client: Callable[..., Any],
) -> tuple[list[fetch.Posting], dict[str, list[fetch.Posting]]]:
    """Give alert cards their full board description where the company's own board has the job.

    Returns the postings to use and, for each swapped-in board posting, the alert cards it replaced.
    """
    by_company: dict[str, list[fetch.Posting]] = {}
    for entry in entries:
        by_company[fetch.company_key(entry.name)] = [
            p for p in board_postings if p.company == entry.name
        ]
    out: dict[str, fetch.Posting] = {}
    origin: dict[str, list[fetch.Posting]] = {}
    for card in waiting:
        job = fetch.best_title_match(card.title, by_company.get(fetch.company_key(card.company), []))
        if job is None:
            job = fetch.board_job_for_link(card.url, card.company, client)
        if job is None:
            if _ALERT_NOTE not in card.text:
                card = dataclasses.replace(card, text=f"{card.text}\n\n{_ALERT_NOTE}")
            out.setdefault(card.uid, card)
            continue
        out.setdefault(job.uid, job)
        origin.setdefault(job.uid, []).append(card)
    return list(out.values()), origin


def _fresh_uids(postings: list[fetch.Posting], db: Path | None) -> set[str]:
    """Which uids are new, without recording anything: checked against a throwaway copy."""
    source = db if db is not None else seen.db_path()
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / seen.DB_NAME
        if source.exists():
            shutil.copyfile(source, copy)
        return set(seen.new_only(postings, path=copy))


def jobs_fetch(
    defn: object,
    run_dir: Path,
    now: datetime,
    *,
    dry_run: bool = False,
    http: Callable[..., Any] | None = None,
    seen_path: Path | None = None,
    report: Report | None = None,
) -> int:
    """Write today's new postings into `run_dir` and return how many."""
    report = report if report is not None else Report()
    report.dry_run, report.folder = dry_run, run_dir
    entries = _fetchable(companies.list("accepted"))
    for entry in entries:
        report.count(entry.name)
    result = fetch.fetch_all(entries, http, sleep=(lambda _s: None) if http else None)
    for name, message in result.errors:
        report.errors.append((name, message))
        report.count(name).errors += 1

    # Alert-email cards were recorded as seen when they were read, so they bypass the seen
    # check below; their inbox files go only once chosen or dropped (never on a dry run).
    waiting = alerts.pending()
    client = ats.make_http(http, sleep=(lambda _s: None) if http else None)
    cards, origin = _enrich(waiting, entries, result.postings, client)
    alert_uids = {p.uid for p in cards}
    prefs = profile.load_preferences()
    kept: list[fetch.Posting] = []
    dropped: list[tuple[fetch.Posting, str]] = []
    # A swapped-in board posting replaces the plain board copy of itself, so it is not listed twice.
    plain = [p for p in result.postings if p.uid not in alert_uids]
    for posting in [*plain, *cards]:
        text, _flagged = guard.clean(posting.text)
        posting = dataclasses.replace(posting, text=text)
        decision = guard.match(posting, prefs)
        if decision.keep:
            kept.append(posting)
        else:
            dropped.append((posting, decision.reason))
            report.count(posting.company).dropped += 1
            report.dropped.append((posting.company, posting.title, decision.reason))
    kept.sort(key=lambda p: p.posted_at, reverse=True)  # newest first; undated last

    fresh = _fresh_uids(kept, seen_path) | alert_uids
    chosen = [p for p in kept if p.uid in fresh]
    chosen.sort(key=lambda p: p.uid not in alert_uids)  # alert cards first, order kept
    chosen = chosen[:MAX_POSTINGS]
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, str]] = {}
    for index, posting in enumerate(chosen, start=1):
        name = _filename(index, posting)
        (run_dir / name).write_text(posting.to_markdown(), encoding="utf-8")
        manifest[name] = {
            "uid": posting.uid,
            "company": posting.company,
            "title": posting.title,
            "url": posting.url,
        }
        report.count(posting.company).new += 1
    if manifest:
        (run_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if not dry_run:
        # Dropped state first, then chosen postings last: a failure while recording drops leaves
        # the chosen postings new for retry. Reasons are re-applied every run (not only for newly
        # inserted rows) so a partially recorded drop is repaired. Only what is written is marked
        # seen: the overflow past the cap shows up next run.
        seen.new_only([p for p, _ in dropped], path=seen_path)
        for posting, reason in dropped:
            seen.mark_dropped(posting.uid, reason, path=seen_path)
        seen.new_only(chosen, path=seen_path)
        # A swapped posting keeps the uid of the alert card it replaced in the seen store too.
        taken = [p.uid for p in chosen] + [p.uid for p, _ in dropped]
        swapped = [card for uid in taken for card in origin.get(uid, ())]
        seen.new_only(swapped, path=seen_path)
        alerts.discard(
            {uid for uid in taken if uid in alert_uids and uid not in origin}
            | {card.uid for card in swapped}
        )
    report.written = len(manifest)
    return report.written


def preview(
    *,
    dry_run: bool,
    http: Callable[..., Any] | None = None,
    seen_path: Path | None = None,
    now: datetime | None = None,
) -> Report:
    """Run `jobs_fetch` into a fresh preview folder (used by the CLI and the console)."""
    folder = paths.home() / PREVIEW_DIR
    if folder.is_symlink():
        raise OSError(f"refusing symlinked preview folder: {folder}")
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(mode=0o700)
    report = Report()
    jobs_fetch(None, folder, now or datetime.now(), dry_run=dry_run, http=http,
               seen_path=seen_path, report=report)
    return report
