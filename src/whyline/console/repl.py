"""whyline console's REPL: ties the session, adapters, and editor together.
The render loop below is the only place in this package that prints --
every adapter returns a SessionEvent instead (see session.py).
"""

from __future__ import annotations

import os
from pathlib import Path

from whyline.console import adapters, editor
from whyline.console.session import ConsoleSession, SessionEvent


def _exec(binary: str, argv: list[str]) -> None:
    os.execvp(binary, argv)


SLASH_COMMANDS = (
    "/model",
    "/route",
    "/status",
    "/handoff",
    "/stop",
    "/history",
    "/help",
    "/exit",
)
_PREFIX = {"error": "⚠ ", "pause": "⏸ "}


def _print_event(event: SessionEvent, print_fn) -> None:
    print_fn(f"{_PREFIX.get(event.kind, '')}{event.text}")


def handle_slash_command(session: ConsoleSession, text: str) -> SessionEvent | None:
    """Handles /help, /status, /handoff, /history, /route, /model
    uniformly for both console flavors. Returns the event to render, or
    None if `text` isn't one of these at all -- the caller should fall
    through to ordinary dispatch() in that case. /exit and /stop stay
    outside this function on purpose: each means something different per
    console (see the final-cutover design's FC4)."""
    if text == "/help":
        return SessionEvent(kind="output", text="Commands: " + ", ".join(SLASH_COMMANDS))
    if text == "/status":
        return adapters.run_status(session.root)
    if text == "/handoff":
        return adapters.run_last_handoff(session.root)
    if text == "/history":
        if not session.transcript:
            return SessionEvent(kind="output", text="(nothing yet)")
        lines = [f"{_PREFIX.get(e.kind, '')}{e.text}" for e in session.transcript]
        return SessionEvent(kind="output", text="\n".join(lines))
    if text.startswith("/route"):
        parts = text.split(maxsplit=1)
        chosen = parts[1].strip() if len(parts) == 2 else ""
        if chosen not in ("chat", "relay", "command"):
            return SessionEvent(kind="error", text="Usage: /route <chat|relay|command>")
        if chosen == "relay" and not adapters.relay_is_configured(session.root):
            return SessionEvent(
                kind="needs_setup",
                text="No relay setup found here. Running whyline-relay setup...",
            )
        session.mode = chosen
        return SessionEvent(kind="output", text=f"Mode is now {session.mode}.")
    if text.startswith("/model"):
        return _model_event(session, text)
    return None


def _model_event(session: ConsoleSession, text: str) -> SessionEvent:
    from whyline import account, model

    available = account.available_agents(session.root)
    if not available:
        return SessionEvent(
            kind="error",
            text="No agents detected as available. Run: whyline account detect",
        )
    parts = text.split(maxsplit=2)
    if len(parts) == 1:
        return SessionEvent(kind="output", text="Available: " + ", ".join(sorted(available)))
    agent = parts[1]
    if agent not in available:
        return SessionEvent(
            kind="error",
            text=f"{agent} is not available here. Available: {', '.join(sorted(available))}",
        )
    if len(parts) == 3:
        model.set_one(session.root, agent, parts[2])
        session.agent = agent
        return SessionEvent(kind="output", text=f"{agent} model set; now the active chat agent.")
    session.agent = agent
    return SessionEvent(kind="output", text=f"{agent} is now the active chat agent.")


def run(root: Path, *, print_fn=print, prompt_session=None, exec_fn=None) -> None:
    if exec_fn is None:
        exec_fn = _exec
    if prompt_session is None:
        try:
            prompt_session = editor.build_session(root)
        except editor.EditorUnavailable as error:
            print_fn(str(error))
            return
    session = ConsoleSession(root=root)
    print_fn("whyline console -- /help for commands, /exit to quit.")
    while True:
        try:
            text = prompt_session.prompt(f"({session.mode}) > ")
        except (EOFError, KeyboardInterrupt):
            break
        text = text.strip()
        if not text:
            continue
        if text == "/exit":
            break
        if text == "/stop":
            print_fn("Nothing in flight to stop.")
            continue
        slash_event = handle_slash_command(session, text)
        if slash_event is not None:
            if slash_event.kind == "needs_setup":
                print_fn(slash_event.text)
                exec_fn("whyline-relay", ["whyline-relay", "setup"])
                return
            _print_event(session.record(slash_event), print_fn)
            continue
        if text.startswith("/"):
            print_fn(f"Unknown command: {text}. Try {', '.join(SLASH_COMMANDS)}.")
            continue
        try:
            event = dispatch(session, text)
        except KeyboardInterrupt:
            print_fn("Cancelled.")
            continue
        _print_event(session.record(event), print_fn)


def dispatch(session: ConsoleSession, text: str) -> SessionEvent:
    if session.mode == "command":
        return adapters.run_whyline_command(text.split())
    if session.mode == "chat":
        agent = session.agent or "claude"
        return adapters.run_chat_turn(session.root, agent=agent, prompt=text)
    # relay mode
    first = text.split(maxsplit=1)[0]
    if first == "doctor":
        return adapters.run_doctor(session.root)
    if first == "status":
        return adapters.run_status(session.root)
    if first in ("start", "resume"):
        return adapters.run_relay_oneshot(session.root, text.split())
    return SessionEvent(
        kind="error",
        text=f"Unknown relay command: {first!r}. Try doctor, status, start, resume.",
    )
