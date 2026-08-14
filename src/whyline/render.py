"""Output formatting. Plain text only — no dependencies, no import cost."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from whyline import resolve

CONFIDENCE_NOTE = {
    resolve.HIGH: "High — a recorded decision matches the commit for this line.",
    resolve.MEDIUM: "Medium — see the reason below before relying on this.",
    resolve.LOW: "Low — recorded evidence cannot be tied to this line.",
    resolve.NONE: "None — nothing is recorded for this line.",
}


def emit(text: str) -> None:
    print(text)


def _date(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d")


def _attributed_notes(result: resolve.Explanation) -> list[dict]:
    """Return only notes that the confidence level attributes to this target."""
    if result.confidence == resolve.NONE:
        return []
    return result.notes


def explanation_text(result: resolve.Explanation) -> str:
    target = result.path if result.line is None else f"{result.path}:{result.line}"
    lines = [f"{target}", ""]
    if result.blame is not None:
        lines.append(f"Last touched by   {result.blame.author}")
        if result.blame.committed:
            lines.append(
                f"Commit            {result.blame.sha[:7]}  ·  "
                f"{_date(result.blame.epoch)}"
            )
    # Carried-forward constraint from Task 5's review: resolve.explain can
    # populate `notes` on branches where confidence == NONE (the
    # uncommitted-line and untracked-file branches forward the file's notes
    # unfiltered, since no line-level attribution was ever established for
    # them). Printing those notes here — even under a "Confidence: None"
    # heading — would tell the user whyline knows why the line exists while
    # simultaneously admitting it does not. So what gets printed is decided
    # by confidence, never by whether `notes` happens to be non-empty.
    for note in _attributed_notes(result):
        lines.append("")
        lines.append(f"Decision          {note.get('decision', '')}")
        if note.get("because"):
            lines.append(f"Because           {note['because']}")
        for alternative in note.get("alternatives") or []:
            option = alternative.get("option", "")
            why_not = alternative.get("why_not", "")
            lines.append(f"Rejected          {option}")
            if why_not:
                lines.append(f"                  {why_not}")
    if result.moved_by:
        lines.append("")
        lines.append(f"Line moved by     {result.moved_by[:7]}")
    lines.append("")
    lines.append(f"Confidence        {CONFIDENCE_NOTE[result.confidence]}")
    if result.reason:
        lines.append(f"                  {result.reason}")
    return "\n".join(lines)


def explanation_json(result: resolve.Explanation) -> dict:
    blame = None
    if result.blame is not None:
        blame = {
            "sha": result.blame.sha,
            "author": result.blame.author,
            "epoch": result.blame.epoch,
            "committed": result.blame.committed,
        }
    return {
        "path": result.path,
        "line": result.line,
        "confidence": result.confidence,
        "reason": result.reason,
        "blame": blame,
        "notes": _attributed_notes(result),
        "moved_by": result.moved_by,
    }


def emit_json(payload: dict) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
