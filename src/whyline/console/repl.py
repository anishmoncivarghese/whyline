"""whyline console's REPL: ties the session, adapters, and editor together.
The render loop below is the only place in this package that prints --
every adapter returns a SessionEvent instead (see session.py).
"""

from __future__ import annotations

from pathlib import Path

from whyline.console import adapters, editor
from whyline.console.session import ConsoleSession, SessionEvent

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


def run(root: Path, *, print_fn=print, prompt_session=None) -> None:
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
        if text == "/help":
            print_fn("Commands: " + ", ".join(SLASH_COMMANDS))
            continue
        if text == "/status":
            _print_event(session.record(adapters.run_status(session.root)), print_fn)
            continue
        if text == "/handoff":
            _print_event(
                session.record(adapters.run_last_handoff(session.root)), print_fn
            )
            continue
        if text == "/history":
            for event in session.transcript:
                _print_event(event, print_fn)
            continue
        if text.startswith("/route"):
            parts = text.split(maxsplit=1)
            chosen = parts[1].strip() if len(parts) == 2 else ""
            if chosen in ("chat", "relay", "command"):
                session.mode = chosen
                print_fn(f"Mode is now {session.mode}.")
            else:
                print_fn("Usage: /route <chat|relay|command>")
            continue
        if text.startswith("/model"):
            _handle_model(session, text, print_fn)
            continue
        if text == "/stop":
            print_fn("Nothing in flight to stop.")
            continue
        if text.startswith("/"):
            print_fn(f"Unknown command: {text}. Try {', '.join(SLASH_COMMANDS)}.")
            continue
        try:
            event = _dispatch(session, text)
        except KeyboardInterrupt:
            print_fn("Cancelled.")
            continue
        _print_event(session.record(event), print_fn)


def _dispatch(session: ConsoleSession, text: str) -> SessionEvent:
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


def _handle_model(session: ConsoleSession, text: str, print_fn) -> None:
    from whyline import account, model

    available = account.available_agents(session.root)
    if not available:
        print_fn("No agents detected as available. Run: whyline account detect")
        return
    parts = text.split(maxsplit=2)
    if len(parts) == 1:
        print_fn("Available: " + ", ".join(sorted(available)))
        return
    agent = parts[1]
    if agent not in available:
        print_fn(
            f"{agent} is not available here. Available: {', '.join(sorted(available))}"
        )
        return
    if len(parts) == 3:
        model.set_one(session.root, agent, parts[2])
        session.agent = agent
        print_fn(f"{agent} model set; now the active chat agent.")
    else:
        session.agent = agent
        print_fn(f"{agent} is now the active chat agent.")
