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


def timeline_text(events_: list[dict]) -> str:
    if not events_:
        return "No events recorded."
    lines = []
    for event in events_:
        stamp = str(event.get("ts", ""))[:16].replace("T", " ")
        kind = event.get("type", "?")
        detail = (
            event.get("decision") or event.get("path") or event.get("session") or ""
        )
        lines.append(f"{stamp}  {kind:<15} {detail}")
    return "\n".join(lines)


def status_payload(root) -> dict:
    from whyline import events as events_module
    from whyline import hooks, ledger, paths

    found, skipped = ledger.read_all(paths.ledger_path(root))
    hook_installed, hook_detail = _hook_state(root)
    return {
        "root": str(root),
        "initialised": paths.is_initialised(root),
        "events": len(found),
        "notes": sum(1 for event in found if event.get("type") == events_module.NOTE),
        "skipped_lines": skipped,
        "hook_installed": hook_installed,
        "hook_detail": hook_detail,
        "decisions_md": paths.decisions_path(root).exists(),
    }


def _hook_state(root) -> tuple[bool, str]:
    """Report the hook honestly, by parsing the config rather than grepping it.

    C3, 2026-08-17: a raw substring search over settings.json produced false
    positives in both directions. A `permissions.deny` entry naming the hook read
    as "installed" while the hook was in fact blocked, and wiring only one of the
    four event types also read as "installed" — so three quarters of recording
    was silently dead while status said all was well.
    """
    import json

    from whyline import hooks

    settings = root / ".claude" / "settings.json"
    if not settings.exists():
        return False, "no .claude/settings.json in this repository"
    try:
        raw = settings.read_text(encoding="utf-8")
    except OSError as error:
        # hooks.install tolerates this; status must not traceback either.
        return False, f"cannot read .claude/settings.json ({error.strerror})"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False, ".claude/settings.json is not valid JSON"
    if not isinstance(data, dict):
        return False, ".claude/settings.json is not a JSON object"

    configured = {
        event
        for event in hooks.EVENTS
        if hooks.HOOK_COMMAND
        in [
            entry.get("command", "")
            for group in ((data.get("hooks") or {}).get(event) or [])
            if isinstance(group, dict)
            for entry in (group.get("hooks") or [])
            if isinstance(entry, dict)
        ]
    }
    missing = [event for event in hooks.EVENTS if event not in configured]

    # A deny rule naming the hook means it cannot run, whatever the hooks block says.
    denied = [
        rule
        for rule in ((data.get("permissions") or {}).get("deny") or [])
        if isinstance(rule, str) and hooks.HOOK_COMMAND in rule
    ]
    if denied:
        return False, f"blocked by a permissions deny rule: {denied[0]}"
    if missing:
        if not configured:
            return False, "not wired to any hook event"
        return False, "wired to " + ", ".join(sorted(configured)) + "; missing " + ", ".join(missing)
    return True, "wired to all " + str(len(hooks.EVENTS)) + " events"


def status_text(payload: dict) -> str:
    hook = "installed" if payload["hook_installed"] else "NOT recording"
    lines = [
        f"Repository     {payload['root']}",
        f"Initialised    {'yes' if payload['initialised'] else 'no'}",
        f"Events         {payload['events']}",
        f"Decisions      {payload['notes']}",
        f"Hook           {hook} — {payload['hook_detail']}",
    ]
    if payload["skipped_lines"]:
        count = payload["skipped_lines"]
        noun = "line" if count == 1 else "lines"
        lines.append(f"Warning        {count} unreadable ledger {noun} skipped")
    if not payload["hook_installed"]:
        lines.append("")
        lines.append("Run `whyline init` to install the hook.")
    return "\n".join(lines)
