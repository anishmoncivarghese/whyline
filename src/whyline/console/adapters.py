"""Bridging whyline console to whyline's own commands and whyline-relay's
already-structured functions. Every function here returns a SessionEvent
instead of printing -- see session.py's own docstring for why.
"""
from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path

from whyline.console.session import SessionEvent

_INTERACTIVE_ONLY = {"account", "model"}

_FAILURE_PHRASES = (
    ("rate-limit", "hit a usage or rate limit"),
    ("auth", "is no longer logged in"),
    ("no-handoff", "exited without handing off"),
    ("round-cap", "round cap"),
    ("blocked", "reported blocked:"),
)


def failure_kind(reason: str) -> str:
    """Classifies a pause's reason text into a coarse kind, using this
    project's own stable, existing pause-message phrasing -- never a new
    invented pattern."""
    for kind, phrase in _FAILURE_PHRASES:
        if phrase in reason:
            return kind
    return "other"


def run_whyline_command(argv: list[str]) -> SessionEvent:
    """Runs a non-interactive whyline command in-process, capturing its
    output. Bare "account"/"model" are interactive (real input() calls);
    redirecting stdout does nothing about stdin, so both are refused here
    rather than risking a hang on the wrong input source."""
    if len(argv) == 1 and argv[0] in _INTERACTIVE_ONLY:
        return SessionEvent(
            kind="error",
            text=(
                f"'{argv[0]}' needs a subcommand here (e.g. "
                f"'{argv[0]} status'), or use /model instead of the "
                "interactive wizard."
            ),
        )

    from whyline import cli

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = cli.main(argv)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else cli.EXIT_ERROR
    text = buf.getvalue()
    return SessionEvent(kind="output" if code == 0 else "error", text=text)


def run_chat_turn(
    root: Path, *, agent: str, prompt: str, run_fn=None, runner=None
) -> SessionEvent:
    """Calls whyline-relay's chat.run_turn directly -- already the exact
    structured, reusable core chat's own REPL is built on. run_fn/runner
    are accepted only so tests can inject fakes the same way
    whyline-relay's own test suite does; real use never passes them."""
    from whyline_relay import agents, chat
    from whyline_relay import config as relay_config

    settings = relay_config.load(root)
    kwargs = {}
    if run_fn is not None:
        kwargs["run_fn"] = run_fn
    if runner is not None:
        kwargs["runner"] = runner
    try:
        record = chat.run_turn(
            root, agent=agent, prompt=prompt, settings=settings, **kwargs
        )
    except chat.AgentUnavailable as error:
        return SessionEvent(kind="error", text=str(error))
    except agents.AgentMissing as error:
        return SessionEvent(kind="error", text=str(error))
    except agents.AgentTimeout as error:
        return SessionEvent(
            kind="error", text=f"{error} -- try again, or /model another agent."
        )
    lines = []
    if record.get("failover_notice"):
        lines.append(record["failover_notice"])
    lines.append(f"[{record['agent']}] {record['response']}")
    if record["rate_limited"]:
        lines.append(
            f"{record['agent']} looks rate-limited -- /model another agent, or wait."
        )
    if record.get("diff_stat"):
        prefix = "" if record["ok"] else "⚠ "
        lines.append(f"{prefix}{record['diff_stat'].strip()}")
    return SessionEvent(
        kind="output" if record["ok"] else "error", text="\n".join(lines)
    )


def run_doctor(root: Path, plan_path: Path | None = None) -> SessionEvent:
    """Calls whyline-relay's preflight.run directly -- already a clean,
    side-effect-free function returning structured Check objects."""
    from whyline_relay import preflight

    checks = preflight.run(root, plan_path)
    lines = []
    for check in checks:
        line = f"  {check.status:<4}  {check.message}"
        if check.status != "ok" and check.hint:
            line += f"\n        fix: {check.hint}"
        lines.append(line)
    failures = sum(check.status == "FAIL" for check in checks)
    lines.append(
        "All checks passed." if failures == 0 else f"{failures} problem(s) found."
    )
    return SessionEvent(
        kind="output" if failures == 0 else "error", text="\n".join(lines)
    )


def run_status(root: Path) -> SessionEvent:
    """Calls whyline-relay's running.live/state.load directly -- both
    already side-effect-free, structured data access; builds its own text
    from the fields rather than reusing cmd_status's print statements."""
    from datetime import datetime
    from whyline_relay import agents as relay_agents
    from whyline_relay import running, state

    lines = []
    active = running.live(root)
    if active is not None:
        try:
            started = datetime.fromisoformat(active.started)
            elapsed = datetime.now(started.tzinfo) - started
            since = started.strftime("%H:%M:%S")
            ago = relay_agents.format_duration(elapsed.total_seconds())
        except ValueError:
            since, ago = active.started, "unknown"
        action = "reviewing" if active.role == "reviewer" else "implementing"
        lines.append(
            f"Running: {active.agent} {action} {active.task}, round "
            f"{active.round}, since {since} ({ago} ago)"
        )
    saved = state.load(root)
    if saved is None:
        if active is None:
            lines.append("No relay run in progress.")
        return SessionEvent(kind="output", text="\n".join(lines))
    lines.append(f"Task      {saved.task_id}")
    lines.append(f"Branch    {saved.branch}")
    lines.append(f"Plan      {saved.plan}")
    lines.append(f"Paused    {saved.paused_reason}")
    if saved.log_path:
        lines.append(f"Log       {saved.log_path}")
    return SessionEvent(kind="pause", text="\n".join(lines))


_PAUSE_PATTERN = re.compile(r"^Paused:", re.M)
_COMPLETE_PATTERN = re.compile(r"^Plan complete", re.M)


def run_relay_oneshot(root: Path | str, argv: list[str]) -> SessionEvent:
    """Calls whyline-relay's cli.main in-process (the same shallow level
    cmd_relay already uses) for start/resume, whose real orchestration
    (branch setup, guards) is not factored into a reusable function --
    reimplementing it here would itself be duplication. Output is captured
    and lightly classified with the same text patterns relay-auto-resume.sh
    already parses; an unrecognized line is still shown verbatim, never
    dropped."""
    try:
        from whyline_relay import cli as relay_cli
    except ModuleNotFoundError as error:
        name = error.name or str(error)
        if name != "whyline_relay":
            raise
        from whyline.cli import relay_install_hint
        return SessionEvent(kind="error", text=relay_install_hint())
    full_argv = [*argv, "--repo", str(root)]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = relay_cli.main(full_argv, prog="whyline-relay")
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 1
    text = buf.getvalue()
    if _PAUSE_PATTERN.search(text):
        from whyline_relay import state as relay_state

        saved = relay_state.load(Path(root))
        if saved is not None:
            kind_label = failure_kind(saved.paused_reason)
            structured = (
                f"[{kind_label}] Task {saved.task_id}\n"
                f"Reason {saved.paused_reason}\n"
                f"Log {saved.log_path}\n"
                "Resume: whyline-relay resume"
            )
            return SessionEvent(kind="pause", text=structured)
        return SessionEvent(kind="pause", text=text)
    if _COMPLETE_PATTERN.search(text) or code == 0:
        kind = "output"
    else:
        kind = "error"
    return SessionEvent(kind=kind, text=text)


def run_last_handoff(root: Path) -> SessionEvent:
    """Renders whyline-relay's current handoff record directly -- already
    exactly the structured function needed, no new parsing."""
    from whyline_relay import handoff as relay_handoff

    record = relay_handoff.read(root)
    if record is None:
        return SessionEvent(kind="output", text="No handoff recorded yet.")
    lines = [
        f"{record.task}: {record.from_actor} -> {record.to_actor} "
        f"({record.status})",
        record.summary,
    ]
    for question in record.questions:
        lines.append(f"Question: {question}")
    return SessionEvent(kind="output", text="\n".join(lines))


def relay_is_configured(root: Path) -> bool:
    """No import of whyline_relay needed just to check this -- the path is
    stable and simple enough to check directly."""
    return (root / ".whyline" / "relay" / "config.toml").exists()
