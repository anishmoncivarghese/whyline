"""whyline console's REPL: ties the session, adapters, and editor together.
The render loop below is the only place in this package that prints --
every adapter returns a SessionEvent instead (see session.py).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from whyline.console import adapters, editor
from whyline.console.session import ConsoleSession, SessionEvent


def _exec(binary: str, argv: list[str]) -> None:
    os.execvp(binary, argv)


# `whyline relay setup`, not `whyline-relay setup`: installed as whyline's
# dependency, the relay's own executable isn't on PATH.
RELAY_SETUP = ("whyline", ["whyline", "relay", "setup"])
_RELAY_MISSING = (
    "Chat and Relay need whyline-relay, which is missing from this install. "
    "Run: uv tool install --reinstall whyline"
)


SLASH_COMMANDS = (
    "/model",
    "/login",
    "/route",
    "/status",
    "/handoff",
    "/stop",
    "/history",
    "/help",
    "/exit",
)
_PREFIX = {"error": "⚠ ", "pause": "⏸ ", "input": "› "}

# One line per command in /help -- a bare list of names told the user
# what exists but not what any of it was for.
_COMMAND_HELP = {
    "/model": "/model claude opus      pick the chat agent (and model); /model alone lists them,\n"
    "                          /model refresh re-checks what's installed and logged in",
    "/login": "/login claude           sign in with the agent's own login, then re-check",
    "/route": "/route <mode>           switch to command, chat or relay",
    "/status": "/status                 repo and relay status",
    "/handoff": "/handoff                the most recent handoff",
    "/stop": "/stop                   cancel the reply in flight",
    "/history": "/history                everything shown this session",
    "/help": "/help                   this help",
    "/exit": "/exit                   quit the console",
}
_HELP_TEXT = "\n".join(
    [
        "Modes:",
        "  Command  what you type runs as `whyline ...` (e.g. status, log)",
        "  Chat     talk to the active agent (see /model)",
        "  Relay    drive whyline-relay: doctor, status, start, resume",
        "Commands:",
        *(f"  {_COMMAND_HELP[name]}" for name in SLASH_COMMANDS),
    ]
)


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
        return SessionEvent(kind="output", text=_HELP_TEXT)
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
        if chosen == session.mode:
            return SessionEvent(kind="output", text=f"Already in {chosen} mode.")
        if chosen == "relay" and not adapters.relay_is_configured(session.root):
            return SessionEvent(
                kind="needs_setup",
                text="No relay setup found here. Running whyline relay setup...",
            )
        session.mode = chosen
        return SessionEvent(kind="output", text=f"Mode is now {session.mode}.")
    if text.startswith("/model"):
        return _model_event(session, text)
    if text.startswith("/login"):
        return _login_event(text)
    return None


_AGENTS_LINE = "Agents: claude, codex, antigravity, grok."

# What to suggest after picking an agent. Never a validated list (see
# model.py): claude's aliases are the ones its own `--help` names, agy can
# list its models itself, and codex/grok have no listing command at all.
_MODEL_HINTS = {
    "claude": "Models: /model claude fable | opus | sonnet, or a full model ID.",
    "codex": "Models: /model codex <model ID>, any model your account accepts.",
    "antigravity": "Models: run `agy models` to list them, then /model antigravity <id>.",
    "grok": "Models: /model grok <model ID>, any model your account accepts.",
}


def _agent_table(session: ConsoleSession) -> str:
    from whyline import account, model

    status = account.agent_status(session.root)
    chosen = model.load(session.root)
    active = session.agent or "claude"  # dispatch()'s own chat default
    lines = []
    for agent in account.AGENT_ORDER:
        info = status[agent]
        mark = "✓" if info["available"] else "✗"
        line = f"  {agent:<12} {mark} {info['label']:<30}"
        if info["available"]:
            line += f"model: {chosen.get(agent) or 'default'}"
            if agent == active:
                line += "  (active)"
        else:
            line += f"-> {info['hint']}"
        lines.append(line)
    return "\n".join(
        ["Agents:", *lines, "Switch with /model <agent> [model]; /model refresh re-checks."]
    )


def _unknown_agent(agent: str) -> SessionEvent:
    return SessionEvent(kind="error", text=f"Unknown agent {agent!r}. {_AGENTS_LINE}")


def _login_event(text: str) -> SessionEvent:
    from whyline import account

    parts = text.split()
    if len(parts) != 2:
        return SessionEvent(kind="error", text=f"Usage: /login <agent>. {_AGENTS_LINE}")
    agent = parts[1].lower()
    if agent not in account.AGENT_ORDER:
        return _unknown_agent(agent)
    if agent not in account.LOGIN_COMMANDS:
        return SessionEvent(kind="output", text=f"{agent} has no separate login command. "
                            + account.login_hint(agent) + ".")
    if shutil.which(account.BINARIES[agent]) is None:
        return SessionEvent(
            kind="error", text=f"{agent} isn't installed. Install it, then /model refresh."
        )
    # The console runs the command itself (each console suspends its own
    # screen differently); `text` carries the agent name.
    return SessionEvent(kind="needs_login", text=agent)


def login_argv(agent: str) -> list[str]:
    from whyline import account

    return account.LOGIN_COMMANDS[agent]


def after_login(session: ConsoleSession, agent: str, returncode: int) -> SessionEvent:
    """Re-checks every agent after a login attempt and reports this one."""
    from whyline import account

    account.refresh()
    info = account.agent_status(session.root)[agent]
    if info["available"]:
        return SessionEvent(kind="output", text=f"{agent} is ready ({info['label']}). /model {agent} to use it.")
    note = "" if returncode == 0 else f" (login exited with {returncode})"
    return SessionEvent(
        kind="error", text=f"{agent} still isn't available: {info['label']}{note}. {info['hint']}"
    )


def _model_event(session: ConsoleSession, text: str) -> SessionEvent:
    from whyline import account, model

    parts = text.split(maxsplit=2)
    if len(parts) > 1:
        parts[1] = parts[1].lower()  # "/model Claude" means claude
    if len(parts) == 1:
        return SessionEvent(kind="output", text=_agent_table(session))
    if parts[1] == "refresh":
        account.refresh()
        return SessionEvent(kind="output", text="Re-checked every agent.\n" + _agent_table(session))
    agent = parts[1]
    if agent not in account.AGENT_ORDER:
        return _unknown_agent(agent)
    status = account.agent_status(session.root)
    if not status[agent]["available"]:
        # Re-check before refusing: detection otherwise runs only once, so
        # an agent installed or logged into since then would stay refused.
        account.refresh()
        status = account.agent_status(session.root)
    info = status[agent]
    if not info["available"]:
        return SessionEvent(
            kind="error", text=f"{agent} isn't available: {info['label']}. {info['hint']}."
        )
    if len(parts) == 3:
        model.set_one(session.root, agent, parts[2])
    session.agent = agent
    current = model.load(session.root).get(agent) or "its default"
    return SessionEvent(
        kind="output",
        text=f"{agent} is now the active chat agent (model: {current}).\n{_MODEL_HINTS[agent]}",
    )


def _run_login(argv: list[str]) -> int:
    """Hands the terminal to the agent's own login; whyline never sees the
    credentials. A missing binary between the check and here is reported
    as a failed login rather than crashing the console."""
    import subprocess

    try:
        return subprocess.run(argv).returncode
    except OSError:
        return 127


def run(
    root: Path, *, print_fn=print, prompt_session=None, exec_fn=None, login_fn=None
) -> None:
    if exec_fn is None:
        exec_fn = _exec
    if login_fn is None:
        login_fn = _run_login
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
                exec_fn(*RELAY_SETUP)
                return
            if slash_event.kind == "needs_login":
                agent = slash_event.text
                print_fn(f"Opening {agent}'s own login...")
                code = login_fn(login_argv(agent))
                _print_event(session.record(after_login(session, agent, code)), print_fn)
                continue
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
    try:
        return _dispatch(session, text)
    except ModuleNotFoundError as error:
        # A raw "No module named 'whyline_relay'" told the user nothing
        # about how to fix it.
        if error.name != "whyline_relay":
            raise
        return SessionEvent(kind="error", text=_RELAY_MISSING)


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
