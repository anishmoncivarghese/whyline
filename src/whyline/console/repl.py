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
    "/brainstorm",
    "/repo",
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
    "/brainstorm": "/brainstorm             several models research a topic, one writes it up",
    "/repo": "/repo ~/other-project   show or switch the repository (clears this transcript)",
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
        "  Relay    Plan makes plan.md, Set up picks roles and starts; or type\n"
        "           doctor, status, start, resume",
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
    if text == "/brainstorm" and _is_home(session.root):
        return SessionEvent(kind="error", text=_HOME_REFUSAL)
    if text == "/brainstorm":
        # Each console collects topic/models/passes its own way (a form in
        # the TUI, prompts in the REPL), then calls adapters.run_brainstorm.
        return SessionEvent(kind="needs_brainstorm", text="")
    if text == "/repo" or text.startswith("/repo "):
        return _repo_event(session, text)
    return None


def _is_home(root: Path) -> bool:
    try:
        return root.resolve() == Path.home().resolve()
    except OSError:
        return False


_HOME_REFUSAL = (
    "Not running agents here: this console is in your home directory's git "
    "repo, where every agent turn commits, and which is too large for git to "
    "handle quickly. Switch to your project with /repo <path> (a new project "
    "folder needs `git init` and `whyline init` first)."
)


def home_repo_warning(root: Path, started_in: Path) -> str | None:
    """Said once at startup when the console landed on the home-directory
    repo -- typically because the folder it was started in (a new project)
    has no git repo of its own, so the search walked up to ~."""
    if not _is_home(root):
        return None
    where = ""
    try:
        if started_in.resolve() != root.resolve():
            where = (
                f" You started in {started_in}, which has no git repo of its own, "
                "so whyline walked up to the one in your home directory."
            )
    except OSError:
        pass
    return (
        "Warning: this console is working in your home directory's git repo (~)."
        + where
        + f" To work on that folder as its own project: cd {started_in} && git init "
        "&& whyline init, then start whyline there (or /repo it). Chat, Relay and "
        "Brainstorm are disabled in the home repo."
    )


# Commands people bring over from `whyline relay chat`, pointed at their
# console equivalents instead of being sent to the agent as a message.
_RELAY_CHAT_HINTS = {
    "/agents": "here, /model lists every agent and whether it's ready",
    "/default": "here, /model {arg} makes it the chat agent",
    "/history": "here, /history shows this session",
    "/clear": "start a new console session to clear it",
    "/backups": "run `whyline relay chat` for backup overrides",
    "/reset-backup": "run `whyline relay chat` for backup overrides",
    "/claude": "here, /model claude switches to it",
    "/codex": "here, /model codex switches to it",
    "/agy": "here, /model antigravity switches to it",
    "/grok": "here, /model grok switches to it",
}


def unknown_command_text(text: str) -> str:
    head, _, rest = text.strip().partition(" ")
    hint = _RELAY_CHAT_HINTS.get(head)
    if hint:
        arg = rest.strip() or "<agent>"
        return f"Unknown command {head} -- that's a `whyline relay chat` command; {hint.format(arg=arg)}."
    return f"Unknown command {head}. /help lists what this console understands."


def repo_label(root: Path) -> str:
    home = Path.home()
    try:
        shown = "~/" + str(root.relative_to(home))
    except ValueError:
        shown = str(root)
    return f"{root.name}  {shown}"


def context_label(session: ConsoleSession) -> str:
    """"claude · opus" -- who Chat talks to, and with which model."""
    from whyline import model

    agent = session.agent or "claude"
    chosen = model.load(session.root).get(agent) or "default model"
    return f"{agent} · {chosen}"


def _repo_event(session: ConsoleSession, text: str) -> SessionEvent:
    from whyline import paths

    parts = text.split(maxsplit=1)
    if len(parts) == 1:
        return SessionEvent(
            kind="output",
            text=f"Repository: {repo_label(session.root)}. Switch with /repo <path>.",
        )
    target = Path(parts[1].strip()).expanduser()
    if not target.is_absolute():
        target = session.root / target
    if not target.is_dir():
        return SessionEvent(kind="error", text=f"No such directory: {target}")
    root = paths.find_repo_root(target)
    if root is None:
        return SessionEvent(kind="error", text=f"{target} isn't inside a git repository.")
    if root == session.root.resolve():
        return SessionEvent(kind="output", text=f"Already in {root.name}.")
    # Each console asks for confirmation before calling switch_repo().
    return SessionEvent(kind="confirm_repo", text=str(root))


def repo_switch_warning(root: Path) -> str:
    return (
        f"Switch to {root.name}? This clears the transcript on screen and starts a "
        "fresh chat context -- each repository keeps its own chat history and "
        "model settings."
    )


def switch_repo(session: ConsoleSession, root: Path) -> SessionEvent:
    """Moves the whole console to `root`: command mode runs `whyline ...`
    against the working directory, so that changes too."""
    os.chdir(root)
    session.root = root
    session.transcript.clear()
    note = ""
    if session.mode == "relay" and not adapters.relay_is_configured(root):
        session.mode = "command"
        note = " The relay isn't set up here, so you're in command mode."
    return SessionEvent(kind="output", text=f"Now working in {repo_label(root)}.{note}")


BRAINSTORM_AGENTS = ("claude", "codex", "antigravity", "grok")


def parse_brainstorm_agents(raw: str) -> list[str] | None:
    """"1,2,4", "claude, grok" or "all" -> agent names in the canonical
    order; None if nothing valid was named."""
    raw = raw.strip().lower()
    if raw in ("all", "5"):
        return list(BRAINSTORM_AGENTS)
    chosen = set()
    for token in (t.strip() for t in raw.split(",")):
        if token.isdigit() and 1 <= int(token) <= len(BRAINSTORM_AGENTS):
            chosen.add(BRAINSTORM_AGENTS[int(token) - 1])
        elif token in BRAINSTORM_AGENTS:
            chosen.add(token)
        elif token:
            return None
    return [a for a in BRAINSTORM_AGENTS if a in chosen] or None


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
    if agent == "antigravity":
        from whyline.console import relay_ops

        relay_ops.forget_antigravity_decline(session.root)
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
    warning = home_repo_warning(root, Path.cwd())
    if warning:
        print_fn(warning)
    while True:
        try:
            label = session.mode
            if session.mode == "chat":
                label = f"chat · {context_label(session)}"
            text = prompt_session.prompt(f"({label}) > ")
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
            if slash_event.kind == "confirm_repo":
                target = Path(slash_event.text)
                answer = _ask(prompt_session, repo_switch_warning(target) + " [y/N] ")
                if answer is None or answer.lower() not in ("y", "yes"):
                    print_fn("Staying put.")
                    continue
                _print_event(session.record(switch_repo(session, target)), print_fn)
                continue
            if slash_event.kind == "needs_brainstorm":
                _brainstorm_prompts(session, prompt_session, print_fn)
                continue
            _print_event(session.record(slash_event), print_fn)
            continue
        if text.startswith("/"):
            print_fn(unknown_command_text(text))
            continue
        print_fn(busy_label(session) + "...")
        try:
            event = dispatch(session, text)
        except KeyboardInterrupt:
            print_fn("Cancelled.")
            continue
        _print_event(session.record(event), print_fn)


def busy_label(session: ConsoleSession) -> str:
    """What the console says while a reply is pending."""
    if session.mode == "chat":
        return f"{session.agent or 'claude'} is thinking"
    if session.mode == "relay":
        return "relay is working"
    return "running"


def _ask(prompt_session, question: str) -> str | None:
    try:
        return prompt_session.prompt(question).strip()
    except (EOFError, KeyboardInterrupt):
        return None


def _brainstorm_prompts(session: ConsoleSession, prompt_session, print_fn) -> None:
    """The keyboard console's version of the TUI's brainstorm form."""
    from whyline import account

    topic = _ask(prompt_session, "What should we brainstorm? ")
    if not topic:
        print_fn("Brainstorm cancelled.")
        return
    status = account.agent_status(session.root)
    menu = ", ".join(
        f"{n} {a}" + ("" if status[a]["available"] else " (unavailable)")
        for n, a in enumerate(BRAINSTORM_AGENTS, start=1)
    )
    agents = None
    while agents is None:
        raw = _ask(prompt_session, f"Which models? ({menu}, or all): ")
        if raw is None:
            print_fn("Brainstorm cancelled.")
            return
        agents = parse_brainstorm_agents(raw)
        if agents is None:
            print_fn("Use numbers or names separated by commas, e.g. 1,2 or claude,grok.")
    raw = _ask(prompt_session, "How many review passes? [1] ") or "1"
    passes = int(raw) if raw.isdigit() else 1
    raw = (_ask(prompt_session, f"Who writes the final synthesis? [{agents[0]}] ") or agents[0]).lower()
    final_agent = raw if raw in agents else agents[0]
    print_fn("Brainstorming -- this runs several full agent turns, so it takes a while.")
    try:
        event = adapters.run_brainstorm(
            session.root, topic=topic, agents=agents, passes=passes,
            final_agent=final_agent, progress=print_fn,
        )
    except KeyboardInterrupt:
        event = SessionEvent(kind="error", text="Brainstorm cancelled.")
    except Exception as error:  # an agent failure mid-run must not end the console
        event = SessionEvent(kind="error", text=f"Brainstorm stopped: {error}")
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
    if session.mode in ("chat", "relay") and _is_home(session.root):
        return SessionEvent(kind="error", text=_HOME_REFUSAL)
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
