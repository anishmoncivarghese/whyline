"""Output formatting. Plain text only — no dependencies, no import cost."""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone

from whyline import resolve
from whyline.textbudget import clipped

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
    from whyline import handoff, history, ownership, paths

    loaded = history.load(root)
    hook_installed, hook_detail = _hook_state(root)
    hook_reports = {
        "claude": _agent_hook_report(root, loaded.ledger_events, "claude"),
        "codex": _agent_hook_report(root, loaded.ledger_events, "codex"),
    }
    active = handoff.load(root)
    ownership_state = ownership.load(root)
    ownership_conflicts = ownership.conflicts(ownership_state["claims"])
    return {
        "root": str(root),
        "initialised": paths.is_initialised(root),
        "events": loaded.event_count,
        "notes": loaded.decision_count,
        "local_events": len(loaded.ledger_events),
        "committed_decisions": loaded.committed_count,
        "skipped_lines": loaded.skipped_lines,
        "hook_installed": hook_installed,
        "hook_detail": hook_detail,
        "hooks": hook_reports,
        "active_handoff": active,
        "ownership_claims": len(ownership_state["claims"]),
        "ownership_conflicts": len(ownership_conflicts),
        "decisions_md": paths.decisions_path(root).exists(),
    }


def _hook_state(root) -> tuple[bool, str]:
    """Legacy Claude configuration fields retained for one release."""
    from whyline import hooks

    return _config_state(
        root / ".claude" / "settings.json",
        hooks.CLAUDE_HOOK_COMMAND,
        check_claude_denies=True,
    )


def _config_state(
    settings, command: str, *, check_claude_denies: bool = False
) -> tuple[bool, str]:
    """Report the hook honestly, by parsing the config rather than grepping it.

    C3, 2026-08-17: a raw substring search over settings.json produced false
    positives in both directions. A `permissions.deny` entry naming the hook read
    as "installed" while the hook was in fact blocked, and wiring only one of the
    four event types also read as "installed" — so three quarters of recording
    was silently dead while status said all was well.
    """
    import json

    from whyline import hooks

    if not settings.exists():
        return False, f"no {settings} in this repository"
    try:
        raw = settings.read_text(encoding="utf-8")
    except OSError as error:
        # hooks.install tolerates this; status must not traceback either.
        return False, f"cannot read {settings} ({error.strerror})"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False, f"{settings} is not valid JSON"
    if not isinstance(data, dict):
        return False, f"{settings} is not a JSON object"

    # Fixed 2026-08-18: every traversal step is shape-checked. The first attempt
    # wrote `(data.get("hooks") or {}).get(event)`, which raises AttributeError on
    # valid JSON of the wrong shape — `{"hooks": [...]}`, `{"hooks": "yes"}`,
    # `{"permissions": ["deny"]}` all crashed `whyline status` with a traceback.
    # A settings file is user-editable input, so it must be parsed defensively.
    hook_block = _as_dict(data.get("hooks"))
    configured = {
        event
        for event in hooks.EVENTS
        if command in _commands_for(hook_block.get(event))
    }
    missing = [event for event in hooks.EVENTS if event not in configured]

    blocking = []
    if check_claude_denies:
        blocking = [
            rule
            for rule in _as_list(_as_dict(data.get("permissions")).get("deny"))
            if _rule_blocks(rule, command)
        ]
    if blocking:
        return False, f"blocked by a permissions deny rule: {blocking[0]}"
    if missing:
        if not configured:
            return False, "not wired to any hook event"
        return (
            False,
            "wired to "
            + ", ".join(sorted(configured))
            + "; missing "
            + ", ".join(missing),
        )
    mentions = [
        rule
        for rule in _as_list(_as_dict(data.get("permissions")).get("deny"))
        if isinstance(rule, str) and command in rule
    ]
    detail = f"wired to all {len(hooks.EVENTS)} events"
    if mentions:
        # A rule that merely names the hook without matching it as a command is
        # not a block. Say so rather than asserting either way.
        detail += f" (note: a deny rule mentions it: {mentions[0]})"
    return True, detail


def _last_agent_event(found: list[dict], aliases: set[str]) -> dict | None:
    from whyline import events

    mechanical = {
        events.SESSION_STARTED,
        events.SESSION_ENDED,
        events.INSTRUCTION,
        events.FILE_TOUCHED,
    }
    matching = [
        event
        for event in found
        if event.get("type") in mechanical and event.get("agent") in aliases
    ]
    if not matching:
        return None
    return max(matching, key=lambda event: str(event.get("ts", "")))


def _event_age_seconds(event: dict | None) -> int | None:
    if event is None:
        return None
    try:
        stamp = datetime.fromisoformat(str(event["ts"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    return max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))


def _agent_hook_report(root, found: list[dict], agent: str) -> dict:
    from whyline import hooks

    if agent == "claude":
        configured, config_detail = _config_state(
            root / ".claude" / "settings.json",
            hooks.CLAUDE_HOOK_COMMAND,
            check_claude_denies=True,
        )
        aliases = {"claude", "claude-code"}
    else:
        configured, config_detail = _config_state(
            root / ".codex" / "hooks.json", hooks.CODEX_HOOK_COMMAND
        )
        aliases = {"codex"}
    binary_path = shutil.which(hooks.HOOK_COMMAND)
    binary_available = binary_path is not None
    last = _last_agent_event(found, aliases)
    observed = last is not None
    age = _event_age_seconds(last)
    healthy = configured and binary_available and observed
    if not configured:
        detail = config_detail
    elif not binary_available:
        detail = "configured, but whyline-hook was not found as an executable on PATH"
    elif not observed and agent == "codex":
        detail = "configured but never observed; open /hooks in Codex and review trust"
    elif not observed:
        detail = "configured but never observed; start a new Claude Code session"
    else:
        detail = "configured, executable, and observed"
    return {
        "configured": configured,
        "config_detail": config_detail,
        "binary_available": binary_available,
        "binary_path": binary_path,
        "observed": observed,
        "last_event": last.get("ts") if last else None,
        "last_event_type": last.get("type") if last else None,
        "last_event_age_seconds": age,
        "healthy": healthy,
        "detail": detail,
    }


_BASH_RULE = re.compile(
    r"^\s*bash\s*(?:\(\s*(?P<target>.*)\s*\))?\s*$", re.IGNORECASE | re.DOTALL
)


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    # A single rule written as a bare string, not a list, is still a rule.
    return [value] if isinstance(value, str) else []


def _commands_for(groups) -> list[str]:
    """Every hook command configured for one event, tolerating any junk shape."""
    found = []
    for group in _as_list(groups):
        for entry in _as_list(_as_dict(group).get("hooks")):
            command = _as_dict(entry).get("command")
            if isinstance(command, str):
                found.append(command)
    return found


def _rule_blocks(rule, command: str) -> bool:
    """Whether a permissions deny rule could stop `command` from running.

    Rewritten 2026-08-18, conservatively. The first attempt matched Bash targets
    "precisely" and thereby lost cases the crude substring check had caught:
    `Bash(whyline-hook*)` — Claude Code's idiomatic prefix-glob form — plus
    `Bash(**)` and a bare `Bash` all reported a fully wired hook as installed
    while recording was in fact dead. That is the dangerous direction for a status
    command, so the rule is now: assert "not blocked" only when the rule
    demonstrably cannot reach this command.

    Still excluded, deliberately: a Bash rule naming a *different* concrete
    command, such as `Bash(whyline-hook-notes)`. Token comparison on the path
    basename distinguishes that from `env whyline-hook` and
    `/usr/local/bin/whyline-hook`, both of which do block.
    """
    if not isinstance(rule, str):
        return False
    match = _BASH_RULE.match(rule)
    if match is None:
        return False
    target = match.group("target")
    if target is None:
        return True  # a bare `Bash` denies every Bash invocation
    target = target.strip().strip("\"'")
    if not target:
        return True
    if any(character in target for character in "*?["):
        # A glob could match this command; never claim otherwise.
        return True
    for token in target.split():
        basename = token.rsplit("/", 1)[-1].strip("\"'")
        if basename == command or basename.startswith(command + ":"):
            return True
    return False


def status_text(payload: dict) -> str:
    lines = [
        f"Repository     {payload['root']}",
        f"Initialised    {'yes' if payload['initialised'] else 'no'}",
        f"Events         {payload['events']}",
        f"Decisions      {payload['notes']}",
    ]
    for label, key in (("Claude hook", "claude"), ("Codex hook", "codex")):
        report = payload["hooks"][key]
        lines.append(f"{label:<14} {report['detail']}")
        if report["last_event"]:
            age = report["last_event_age_seconds"]
            age_text = f"{age}s ago" if age is not None else "age unknown"
            lines.append(
                f"{'Last observed':<14} {report['last_event_type']} at "
                f"{report['last_event']} ({age_text})"
            )
    active = payload.get("active_handoff")
    if active:
        # Clipped and fence-sanitised like every other display path. A handoff is
        # written by the *other* agent, and `status` is an agent-facing surface,
        # so these values are untrusted input: unclipped they let a 20,000-character
        # task id flood the output, and unsanitised they carry fence tokens into a
        # packet another agent reads. Imported rather than reimplemented so the
        # fence pattern has one definition.
        lines.append(
            f"Active handoff {clipped(active.get('task', ''), 60)}: "
            f"{clipped(active.get('status', ''), 40)} "
            f"({clipped(active.get('from_actor', ''), 40)} -> "
            f"{clipped(active.get('to_actor', ''), 40)})"
        )
    else:
        lines.append("Active handoff none")
    lines.append(f"Ownership      {payload.get('ownership_claims', 0)} active claims")
    if payload.get("ownership_conflicts"):
        lines.append(
            f"WARNING        {payload['ownership_conflicts']} ownership conflicts"
        )
    if payload["skipped_lines"]:
        count = payload["skipped_lines"]
        noun = "line" if count == 1 else "lines"
        lines.append(f"Warning        {count} unreadable ledger {noun} skipped")
    if not all(report["configured"] for report in payload["hooks"].values()):
        lines.append("")
        lines.append("Run `whyline init` to install missing hook configuration.")
    return "\n".join(lines)
