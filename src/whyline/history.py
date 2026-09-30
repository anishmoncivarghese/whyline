"""One honest read model over local events and committed decisions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from whyline import decisions, events, ledger, paths

LEDGER = "ledger"
COMMITTED = "committed"

ACTIVE = "active"
SUPERSEDED = "superseded"
RETRACTED = "retracted"


@dataclass(frozen=True)
class HistoryEntry:
    event: dict
    source: str


@dataclass(frozen=True)
class History:
    ledger_events: list[dict]
    notes: list[HistoryEntry]
    skipped_lines: int
    committed_count: int

    @property
    def active(self) -> list[HistoryEntry]:
        """Decisions still standing: neither superseded nor retracted."""
        return [entry for entry in self.notes if entry.event.get("lifecycle") == ACTIVE]

    @property
    def decision_count(self) -> int:
        return len(self.notes)

    @property
    def event_count(self) -> int:
        local_non_notes = sum(
            1 for event in self.ledger_events if event.get("type") != events.NOTE
        )
        return local_non_notes + self.decision_count


def sort_key(note: dict) -> str:
    """Rank a day-precision committed note after same-day local notes."""
    ts = str(note.get("ts", ""))
    if len(ts) == 10 and ts.count("-") == 2:
        return ts + "T23:59:59.999Z"
    return ts


def content_key(note: dict) -> tuple:
    """Identity derived from all durable content, excluding timestamp and id."""
    alternatives = tuple(
        (str(alt.get("option", "")), str(alt.get("why_not", "")))
        for alt in (note.get("alternatives") or [])
    )
    return (
        "content",
        str(note.get("decision", "")),
        str(note.get("because", "")),
        alternatives,
        tuple(str(file) for file in (note.get("files") or [])),
        str(note.get("actor", "")),
        str(note.get("role", "")),
        str(note.get("task", "")),
    )


def _key(note: dict) -> object:
    return note.get("id") or content_key(note)


def merge_notes(
    ledger_notes: list[dict], committed_notes: list[dict]
) -> list[HistoryEntry]:
    """Merge the two stores without collapsing distinct id-bearing events.

    The ledger copy wins because it retains full timestamps and any fields that
    predate their committed Markdown representation. A second pass handles the
    narrow case where a formatter removed the committed copy's id comment.
    """
    merged: dict[object, HistoryEntry] = {}
    for note in committed_notes:
        merged[_key(note)] = HistoryEntry(note, COMMITTED)
    for note in ledger_notes:
        merged[_key(note)] = HistoryEntry(note, LEDGER)

    id_bearing = [entry for entry in merged.values() if entry.event.get("id")]
    id_less = [entry for entry in merged.values() if not entry.event.get("id")]
    known_content = {content_key(entry.event) for entry in id_bearing}
    entries = id_bearing + [
        entry for entry in id_less if content_key(entry.event) not in known_content
    ]
    entries.sort(key=lambda entry: sort_key(entry.event), reverse=True)
    return entries


def _apply_attachments(
    entries: list[HistoryEntry], attachments: list[dict]
) -> list[HistoryEntry]:
    """Bind decisions to commits recorded later with `whyline attach`. The
    same attachment is usually in both decisions.md and the ledger; the
    latest one per decision wins either way."""
    bound: dict[str, tuple[str, str]] = {}
    for item in attachments:
        note, commit, ts = item.get("note"), item.get("commit"), str(item.get("ts", ""))
        if isinstance(note, str) and isinstance(commit, str) and commit:
            if note not in bound or ts >= bound[note][0]:
                bound[note] = (ts, commit)
    if not bound:
        return entries
    return [
        HistoryEntry({**entry.event, "commit": bound[entry.event["id"]][1]}, entry.source)
        if entry.event.get("id") in bound
        else entry
        for entry in entries
    ]


def _apply_lifecycle(
    entries: list[HistoryEntry], retractions: list[dict]
) -> list[HistoryEntry]:
    """Mark each decision active, superseded or retracted.

    A retraction wins over everything, and a retracted decision's own
    `supersedes` stop counting -- a withdrawn replacement doesn't retire
    what it replaced."""
    retracted: dict[str, dict] = {}
    for item in sorted(retractions, key=lambda r: str(r.get("ts", ""))):
        target = item.get("retracts") or item.get("note")
        if isinstance(target, str) and target:
            retracted[target] = item
    superseded_by: dict[str, str] = {}
    for entry in sorted(entries, key=lambda e: sort_key(e.event)):
        event = entry.event
        if event.get("id") in retracted:
            continue
        for target in event.get("supersedes") or []:
            superseded_by[str(target)] = str(event.get("id", ""))
    marked = []
    for entry in entries:
        event = dict(entry.event)
        note_id = event.get("id", "")
        if note_id in retracted:
            item = retracted[note_id]
            event["lifecycle"] = RETRACTED
            event["retracted_because"] = item.get("because", "")
            event["retracted_by"] = item.get("id", "")
        elif note_id in superseded_by:
            event["lifecycle"] = SUPERSEDED
            event["superseded_by"] = superseded_by[note_id]
        else:
            event["lifecycle"] = ACTIVE
        marked.append(HistoryEntry(event, entry.source))
    return marked


def find(loaded: "History", prefix: str) -> list[str]:
    """Ids of every decision whose id starts with `prefix` (empty matches none)."""
    prefix = prefix.strip()
    return sorted(
        {
            str(entry.event["id"])
            for entry in loaded.notes
            if prefix and str(entry.event.get("id", "")).startswith(prefix)
        }
    )


def load(root: Path) -> History:
    """Load local events and the durable decision log as one merged history."""
    local_events, skipped = ledger.read_all(paths.ledger_path(root))
    ledger_notes = [
        event for event in local_events if event.get("type") == events.NOTE
    ]
    committed = decisions.parse_entries(paths.decisions_path(root))
    # Retraction entries are written into decisions.md alongside decisions
    # (so a person reading it sees them) but are not decisions themselves.
    committed_notes = [entry for entry in committed if not entry.get("retracts")]
    retractions = [entry for entry in committed if entry.get("retracts")] + [
        event for event in local_events if event.get("type") == events.RETRACTION
    ]
    notes = _apply_attachments(
        merge_notes(ledger_notes, committed_notes),
        decisions.parse_attachments(paths.decisions_path(root))
        + [event for event in local_events if event.get("type") == events.NOTE_ATTACHED],
    )
    notes = _apply_lifecycle(notes, retractions)
    return History(
        ledger_events=local_events,
        notes=notes,
        skipped_lines=skipped,
        committed_count=len(committed_notes),
    )
