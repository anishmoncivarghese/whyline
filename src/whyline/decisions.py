"""The committed, human-readable decision log.

This file is the durable artefact. If whyline is deleted, the reasoning must
still be readable here with no tooling at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HEADING = "# Decisions\n\nAppend-only. Written by whyline; readable without it.\n"

_HEADING_RE = re.compile(r"^## (?P<day>\S+) — (?P<decision>.*)$")
_BECAUSE_RE = re.compile(r"^\*\*Because:\*\* (?P<value>.*)$", re.MULTILINE)
_FILES_RE = re.compile(r"^\*\*Files:\*\* (?P<value>.*)$", re.MULTILINE)
_ACTOR_RE = re.compile(r"^\*\*Actor:\*\* (?P<value>.*)$", re.MULTILINE)
_ROLE_RE = re.compile(r"^\*\*Role:\*\* (?P<value>.*)$", re.MULTILINE)
_TASK_RE = re.compile(r"^\*\*Task:\*\* (?P<value>.*)$", re.MULTILINE)
_ID_RE = re.compile(r"<!-- whyline-event: (?P<value>.*?) -->")
# Exact time and bound commit, since 0.3.21. A comment of its own rather than
# more text in the whyline-event comment: older versions read that whole
# comment as the id, so extending it would corrupt ids -- and duplicate every
# entry -- for anyone who hasn't upgraded yet.
_META_RE = re.compile(r"<!-- whyline-meta: (?P<value>\{.*?\}) -->")
_ATTACH_RE = re.compile(r"<!-- whyline-attach: (?P<value>\{.*?\}) -->")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_FULL_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
_CONFLICT_RE = re.compile(r"(?m)^(<{7}|={7}|>{7})")


def one_line(text: object) -> str:
    """Collapse a value to a single line for the Markdown log.

    C5, 2026-08-17: `render_entry` emitted field values verbatim, so a newline
    inside a decision or rationale could open a second `## <date> — ...` block.
    That forged a backdated entry in the *committed* record, which `brief` then
    presented to the next agent as genuine history. Every field written here is
    structurally single-line, so collapsing whitespace removes the injection
    without discarding what the author wrote.
    """
    return " ".join(str(text).split())


def render_entry(event: dict) -> str:
    day = one_line(event.get("ts", ""))[:10]
    lines = [f"## {day} — {one_line(event.get('decision', ''))}", ""]
    for label, field in (("Actor", "actor"), ("Role", "role"), ("Task", "task")):
        if event.get(field):
            lines.append(f"**{label}:** {one_line(event[field])}")
    if any(event.get(field) for field in ("actor", "role", "task")):
        lines.append("")
    if event.get("because"):
        lines.append(f"**Because:** {one_line(event['because'])}")
        lines.append("")
    alternatives = event.get("alternatives") or []
    if alternatives:
        lines.append("**Rejected:**")
        lines.append("")
        for alternative in alternatives:
            option = one_line(alternative.get("option", ""))
            why_not = one_line(alternative.get("why_not", ""))
            lines.append(f"- {option}" + (f" — {why_not}" if why_not else ""))
        lines.append("")
    files = event.get("files") or []
    if files:
        lines.append(f"**Files:** {', '.join(one_line(f) for f in files)}")
        lines.append("")
    lines.append(f"<!-- whyline-event: {event.get('id', '')} -->")
    meta = _meta(event)
    if meta:
        lines.append(f"<!-- whyline-meta: {json.dumps(meta, separators=(',', ':'))} -->")
    lines.append("")
    return "\n".join(lines)


def _meta(event: dict) -> dict:
    meta: dict = {}
    ts = one_line(event.get("ts", ""))
    if _FULL_TS_RE.match(ts):
        meta["ts"] = ts
    commit = str(event.get("commit") or "")
    if _SHA_RE.match(commit):
        meta["commit"] = commit
    return {"v": 1, **meta} if meta else {}


def _load_json(raw: str) -> dict | None:
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) and value.get("v") == 1 else None


def append_attachment(path: Path, *, note: str, commit: str, ts: str) -> None:
    """Record, append-only, that decision `note` is about `commit`."""
    payload = {"v": 1, "note": note, "commit": commit, "ts": ts}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n<!-- whyline-attach: {json.dumps(payload, separators=(',', ':'))} -->\n")


def parse_attachments(path: Path) -> list[dict]:
    """Every well-formed attachment in decisions.md, in file order."""
    if not path.exists():
        return []
    found = []
    for match in _ATTACH_RE.finditer(path.read_text(encoding="utf-8")):
        payload = _load_json(match.group("value"))
        if (
            payload
            and isinstance(payload.get("note"), str)
            and payload["note"]
            and _SHA_RE.match(str(payload.get("commit", "")))
        ):
            found.append(payload)
    return found


def append_entry(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(HEADING, encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + render_entry(event))


def _parse_alternatives(body: str) -> list[dict]:
    if "**Rejected:**" not in body:
        return []
    section = body.split("**Rejected:**", 1)[1]
    alternatives = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("**"):
            break
        if not stripped.startswith("- "):
            continue
        option, separator, why_not = stripped[2:].partition(" — ")
        alternatives.append(
            {"option": option.strip(), "why_not": why_not.strip() if separator else ""}
        )
    return alternatives


def _parse_block(block: str) -> dict | None:
    heading_match = _HEADING_RE.match(block.splitlines()[0]) if block.strip() else None
    if not heading_match:
        return None
    because_match = _BECAUSE_RE.search(block)
    files_match = _FILES_RE.search(block)
    actor_match = _ACTOR_RE.search(block)
    role_match = _ROLE_RE.search(block)
    task_match = _TASK_RE.search(block)
    id_match = _ID_RE.search(block)
    meta_match = _META_RE.search(block)
    meta = _load_json(meta_match.group("value")) if meta_match else None
    ts = heading_match.group("day").strip()
    if meta and _FULL_TS_RE.match(str(meta.get("ts", ""))) and meta["ts"][:10] == ts:
        ts = meta["ts"]  # exact time; the heading still says the same day
    parsed = {
        "ts": ts,
        "decision": heading_match.group("decision").strip(),
        "because": because_match.group("value").strip() if because_match else "",
        "alternatives": _parse_alternatives(block),
        "files": (
            [item.strip() for item in files_match.group("value").split(",") if item.strip()]
            if files_match
            else []
        ),
        "actor": actor_match.group("value").strip() if actor_match else "",
        "role": role_match.group("value").strip() if role_match else "",
        "task": task_match.group("value").strip() if task_match else "",
        "id": id_match.group("value").strip() if id_match else "",
    }
    if meta and _SHA_RE.match(str(meta.get("commit", ""))):
        parsed["commit"] = meta["commit"]
    return parsed


def parse_entries(path: Path) -> list[dict]:
    """Parse decisions.md back into note-shaped dicts. The inverse of
    `render_entry`, so `brief.compose` can fall back to it on a fresh clone
    where the gitignored ledger is absent but decisions.md is committed.

    A hand-edited or malformed file must never raise: unexpected prose
    between entries is skipped, and missing sections yield empty values.
    """
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    entries = []
    for block in re.split(r"(?m)^(?=## )", text):
        if _CONFLICT_RE.search(block):
            # Important finding 2026-08-17: an unresolved merge conflict used to
            # yield BOTH sides as accepted decisions with the markers swallowed,
            # so a brief presented contradictory history as settled. Refuse the
            # block instead — a conflicted record is not a record.
            continue
        parsed = _parse_block(block)
        if parsed is not None:
            entries.append(parsed)
    return entries


def has_conflict_markers(path: Path) -> bool:
    """True if decisions.md holds an unresolved merge conflict."""
    if not path.exists():
        return False
    return bool(_CONFLICT_RE.search(path.read_text(encoding="utf-8")))
