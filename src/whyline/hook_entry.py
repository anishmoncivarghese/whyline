"""Hook entrypoint. Fast, silent, and incapable of failing a session.

Every path returns 0. Any exception is swallowed. Nothing is printed. This runs
in the critical path of every tool call, so it imports only what it needs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from whyline import events, ledger, paths


def _relative(root: Path, raw: str) -> str | None:
    try:
        return str(Path(raw).resolve().relative_to(root.resolve()))
    except (ValueError, OSError):
        return None


def main(stdin_text: str, root: Path) -> int:
    try:
        payload = json.loads(stdin_text)
        name = payload.get("hook_event_name")
        session = payload.get("session_id", "")
        target = paths.ledger_path(root)

        if name == "SessionStart":
            ledger.append(
                target,
                events.new_event(
                    events.SESSION_STARTED, session=session, agent="claude-code"
                ),
            )
        elif name == "SessionEnd":
            ledger.append(
                target,
                events.new_event(events.SESSION_ENDED, session=session, status="ended"),
            )
        elif name == "UserPromptSubmit":
            ledger.append(
                target,
                events.new_event(
                    events.INSTRUCTION, session=session, text=payload.get("prompt", "")
                ),
            )
        elif name == "PostToolUse":
            raw = (payload.get("tool_input") or {}).get("file_path")
            if raw:
                relative = _relative(root, str(raw))
                if relative is not None:
                    ledger.append(
                        target,
                        events.new_event(
                            events.FILE_TOUCHED,
                            session=session,
                            path=relative,
                            tool=payload.get("tool_name", ""),
                        ),
                    )
    except Exception:  # noqa: BLE001 — never fail the user's session
        pass
    return 0


def entry() -> None:
    try:
        text = sys.stdin.read()
        root = paths.find_repo_root() or Path.cwd()
        main(text, root)
    except Exception:  # noqa: BLE001 — the console entrypoint has the same contract
        pass
    raise SystemExit(0)
