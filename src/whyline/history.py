"""One honest read model over local events and committed decisions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from whyline import decisions, events, ledger, paths

LEDGER = "ledger"
COMMITTED = "committed"


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


def load(root: Path) -> History:
    """Load local events and the durable decision log as one merged history."""
    local_events, skipped = ledger.read_all(paths.ledger_path(root))
    ledger_notes = [
        event for event in local_events if event.get("type") == events.NOTE
    ]
    committed_notes = decisions.parse_entries(paths.decisions_path(root))
    return History(
        ledger_events=local_events,
        notes=merge_notes(ledger_notes, committed_notes),
        skipped_lines=skipped,
        committed_count=len(committed_notes),
    )
