"""The committed, human-readable decision log.

This file is the durable artefact. If whyline is deleted, the reasoning must
still be readable here with no tooling at all.
"""

from __future__ import annotations

from pathlib import Path

HEADING = "# Decisions\n\nAppend-only. Written by whyline; readable without it.\n"


def render_entry(event: dict) -> str:
    day = str(event.get("ts", ""))[:10]
    lines = [f"## {day} — {event.get('decision', '')}", ""]
    if event.get("because"):
        lines.append(f"**Because:** {event['because']}")
        lines.append("")
    alternatives = event.get("alternatives") or []
    if alternatives:
        lines.append("**Rejected:**")
        lines.append("")
        for alternative in alternatives:
            option = alternative.get("option", "")
            why_not = alternative.get("why_not", "")
            lines.append(f"- {option}" + (f" — {why_not}" if why_not else ""))
        lines.append("")
    files = event.get("files") or []
    if files:
        lines.append(f"**Files:** {', '.join(files)}")
        lines.append("")
    lines.append(f"<!-- whyline-event: {event.get('id', '')} -->")
    lines.append("")
    return "\n".join(lines)


def append_entry(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(HEADING, encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + render_entry(event))
