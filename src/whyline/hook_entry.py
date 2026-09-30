"""Hook entrypoint. Fast, silent, and incapable of failing a session.

Every path returns 0. Any exception is swallowed. Nothing is printed. This runs
in the critical path of every tool call, so it imports only what it needs.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from whyline import events, ledger, paths


def _relative(root: Path, raw: str) -> str | None:
    try:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / candidate
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return None


_PATCH_PATH = re.compile(
    r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (?P<path>.+)$", re.M
)


def _touched_paths(root: Path, payload: dict) -> list[str]:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    candidates = []
    raw = tool_input.get("file_path")
    if raw:
        candidates.append(str(raw))
    if str(payload.get("tool_name", "")).lower() == "apply_patch":
        command = tool_input.get("command")
        if isinstance(command, str):
            candidates.extend(
                match.group("path") for match in _PATCH_PATH.finditer(command)
            )
    relative = {_relative(root, candidate) for candidate in candidates}
    return sorted(path for path in relative if path is not None)


def _antigravity(payload: dict, root: Path, event: str | None) -> None:
    """agy hook payloads: camelCase, no hook_event_name (the event comes
    from the command line), and -- verified, though undocumented -- the tool
    call on PostToolUse. Only writes are recorded: agy's file-writing tools
    name their file `TargetFile`; reads use `AbsolutePath`."""
    target = paths.ledger_path(root)
    session = str(payload.get("conversationId", ""))
    if event == "PreInvocation":
        if payload.get("invocationNum") == 0:
            ledger.append(
                target,
                events.new_event(events.SESSION_STARTED, session=session, agent="antigravity"),
            )
    elif event == "PostToolUse":
        call = payload.get("toolCall")
        args = call.get("args") if isinstance(call, dict) else None
        if payload.get("error") or not isinstance(args, dict):
            return
        raw = args.get("TargetFile")
        relative = _relative(root, str(raw)) if isinstance(raw, str) and raw else None
        if relative:
            ledger.append(
                target,
                events.new_event(
                    events.FILE_TOUCHED,
                    session=session,
                    path=relative,
                    tool=str(call.get("name", "")),
                    agent="antigravity",
                ),
            )
    elif event == "Stop":
        ledger.append(
            target,
            events.new_event(
                events.SESSION_ENDED,
                session=session,
                status=str(payload.get("terminationReason", "")) or "ended",
                agent="antigravity",
            ),
        )


def main(
    stdin_text: str, root: Path, agent: str = "claude-code", event: str | None = None
) -> int:
    try:
        payload = json.loads(stdin_text)
        if agent == "antigravity":
            if isinstance(payload, dict):
                _antigravity(payload, root, event)
            return 0
        name = payload.get("hook_event_name")
        session = payload.get("session_id", "")
        target = paths.ledger_path(root)

        if name == "SessionStart":
            ledger.append(
                target,
                events.new_event(
                    events.SESSION_STARTED, session=session, agent=agent
                ),
            )
        elif name == "SessionEnd":
            ledger.append(
                target,
                events.new_event(
                    events.SESSION_ENDED,
                    session=session,
                    status="ended",
                    agent=agent,
                ),
            )
        elif name == "UserPromptSubmit":
            from whyline import ledgerops

            ledger.append(
                target,
                events.new_event(
                    events.INSTRUCTION,
                    session=session,
                    agent=agent,
                    **ledgerops.capture_fields(
                        str(payload.get("prompt", "")), ledgerops.policy(root)
                    ),
                ),
            )
        elif name == "PostToolUse":
            for relative in _touched_paths(root, payload):
                ledger.append(
                    target,
                    events.new_event(
                        events.FILE_TOUCHED,
                        session=session,
                        path=relative,
                        tool=payload.get("tool_name", ""),
                        agent=agent,
                    ),
                )
    except Exception:  # noqa: BLE001 — never fail the user's session
        pass
    return 0


def entry() -> None:
    try:
        agent = "claude-code"
        event = None
        for flag in ("--agent", "--event"):
            if flag in sys.argv[1:]:
                index = sys.argv.index(flag)
                if index + 1 < len(sys.argv):
                    if flag == "--agent":
                        agent = sys.argv[index + 1]
                    else:
                        event = sys.argv[index + 1]
        text = sys.stdin.read()
        root = paths.find_repo_root() or Path.cwd()
        main(text, root, agent=agent, event=event)
    except Exception:  # noqa: BLE001 — the console entrypoint has the same contract
        pass
    if agent == "antigravity":
        # agy expects a JSON object on stdout from every hook; {} means
        # "no opinion" for all three events whyline uses (verified).
        sys.stdout.write("{}\n")
    raise SystemExit(0)
