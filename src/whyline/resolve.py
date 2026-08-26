"""Resolving a line to recorded reasoning, with honest confidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from whyline import events, gitq, history

HIGH = "high"
MEDIUM = "medium"
LOW = "low"
NONE = "none"

MECHANICAL_TYPES = (events.FILE_TOUCHED, events.INSTRUCTION)


@dataclass
class Explanation:
    path: str
    line: int | None
    confidence: str
    blame: gitq.Blame | None
    notes: list[dict] = field(default_factory=list)
    moved_by: str | None = None
    reason: str = ""
    skipped_ledger_lines: int = 0


def _epoch_of(event: dict) -> float:
    """Parse an event timestamp into an epoch. Unparseable timestamps sort last.

    Ruling 2026-08-10: sorting unparseable timestamps to +inf makes them lose
    every window/earlier comparison, so a malformed ts can only ever
    under-claim (fall through toward LOW/NONE), never over-claim by
    accidentally winning a HIGH/MEDIUM match it didn't earn.
    """
    try:
        value = event["ts"]
        if len(value) == 10:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (KeyError, TypeError, ValueError, AttributeError):
        return float("inf")


def _epoch_end(event: dict) -> float:
    """Latest possible epoch for a timestamp, accounting for day precision."""
    start = _epoch_of(event)
    if start == float("inf"):
        return start
    value = event.get("ts")
    if isinstance(value, str) and len(value) == 10:
        return start + timedelta(days=1).total_seconds() - 0.001
    return start


def _has_day_precision(event: dict) -> bool:
    value = event.get("ts")
    return isinstance(value, str) and len(value) == 10


def _mentions(event: dict, rel_path: str) -> bool:
    if event.get("path") == rel_path:
        return True
    return rel_path in (event.get("files") or [])


def explain(root: Path, rel_path: str, line: int | None) -> Explanation:
    loaded = history.load(root)
    all_events = loaded.ledger_events
    skipped_lines = loaded.skipped_lines
    notes = [
        entry.event for entry in loaded.notes if _mentions(entry.event, rel_path)
    ]
    mechanical = [
        event
        for event in all_events
        if event.get("type") in MECHANICAL_TYPES and _mentions(event, rel_path)
    ]

    blame = gitq.blame_line(root, rel_path, line) if line is not None else None

    if line is None:
        # Ruling 2026-08-10: file-level resolution can never reach "high".
        # HIGH is defined as one note inside a blamed commit's window, and with
        # no line there is no blamed commit — git is not consulted at all here.
        # Returning HIGH would claim a link that was never established.
        confidence = MEDIUM if notes else (LOW if mechanical else NONE)
        return Explanation(
            path=rel_path,
            line=None,
            confidence=confidence,
            blame=None,
            notes=notes,
            reason="file-level explanation; no line requested",
            skipped_ledger_lines=skipped_lines,
        )

    if blame is None:
        return Explanation(
            path=rel_path,
            line=line,
            confidence=NONE,
            blame=None,
            notes=notes,
            reason="line is not tracked by git; cannot attribute it",
            skipped_ledger_lines=skipped_lines,
        )

    if not blame.committed:
        return Explanation(
            path=rel_path,
            line=line,
            confidence=NONE,
            blame=blame,
            notes=notes,
            reason="line is uncommitted, so it has no recorded provenance yet",
            skipped_ledger_lines=skipped_lines,
        )

    lower = gitq.previous_commit_epoch(root, rel_path, blame.sha)
    in_window = [
        note
        for note in notes
        if _epoch_of(note) <= blame.epoch
        and (lower is None or _epoch_end(note) > lower)
    ]

    if len(in_window) == 1:
        if _has_day_precision(in_window[0]):
            return Explanation(
                path=rel_path,
                line=line,
                confidence=MEDIUM,
                blame=blame,
                notes=in_window,
                reason=(
                    "one committed decision overlaps this commit window, but "
                    "its timestamp has only day precision"
                ),
                skipped_ledger_lines=skipped_lines,
            )
        return Explanation(
            path=rel_path,
            line=line,
            confidence=HIGH,
            blame=blame,
            notes=in_window,
            reason="one recorded decision matches the commit that wrote this line",
            skipped_ledger_lines=skipped_lines,
        )
    if len(in_window) > 1:
        return Explanation(
            path=rel_path,
            line=line,
            confidence=MEDIUM,
            blame=blame,
            notes=in_window,
            reason="several decisions match this commit; the link is ambiguous",
            skipped_ledger_lines=skipped_lines,
        )

    earlier = [note for note in notes if _epoch_of(note) <= blame.epoch]
    if earlier:
        latest = max(earlier, key=_epoch_of)
        return Explanation(
            path=rel_path,
            line=line,
            confidence=MEDIUM,
            blame=blame,
            notes=[latest],
            moved_by=blame.sha,
            reason=(
                f"reasoning was recorded earlier; commit {blame.sha[:7]} last moved "
                "this line, so verify it still applies"
            ),
            skipped_ledger_lines=skipped_lines,
        )
    if mechanical:
        return Explanation(
            path=rel_path,
            line=line,
            confidence=LOW,
            blame=blame,
            notes=[],
            reason="an agent touched this file but recorded no reasoning",
            skipped_ledger_lines=skipped_lines,
        )
    if notes:
        # Notes exist for this path but none could be tied to this line.
        # Saying "no reasoning recorded" would be false. Reaching here means
        # every note is either unparseable (+inf) or postdates the blamed
        # commit, since any note at or before it was handled above — so
        # distinguish the two rather than blaming timestamps that are fine.
        unreadable = [note for note in notes if _epoch_of(note) == float("inf")]
        if unreadable:
            reason = (
                "reasoning exists for this file but its timestamps are "
                "unreadable, so it cannot be tied to this line"
            )
        else:
            reason = (
                "reasoning exists for this file but all of it postdates this "
                "line's last change"
            )
        return Explanation(
            path=rel_path,
            line=line,
            confidence=LOW,
            blame=blame,
            notes=[],
            reason=reason,
            skipped_ledger_lines=skipped_lines,
        )
    return Explanation(
        path=rel_path,
        line=line,
        confidence=NONE,
        blame=blame,
        notes=[],
        reason="no reasoning recorded for this line",
        skipped_ledger_lines=skipped_lines,
    )
