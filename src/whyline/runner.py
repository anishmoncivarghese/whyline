"""Launching an agent by handing over the terminal.

We exec, we do not supervise. There is no PTY, no output capture and no
parsing, so a vendor changing its output format cannot break us. The
environment is passed through untouched and is never inspected.
"""

from __future__ import annotations

import os
import shutil

AGENTS = {"claude": "claude", "codex": "codex"}

# Indirection so a test can neutralise these without mutating shutil or os
# globally. These MUST be functions that look their target up at call time.
# Caching the function objects here (`_which = shutil.which`) recreates the very
# late-binding defect this module already suffered once: the cached reference
# ignores any later patch, and `launch` then execs the real agent — which hung a
# test run on 2026-08-18 by replacing pytest with Claude Code.
def _which(name: str) -> str | None:
    return shutil.which(name)


def _exec(binary: str, argv: list[str]) -> None:
    os.execvp(binary, argv)


class UnknownAgent(ValueError):
    """Agent is not one whyline knows how to launch."""


class AgentMissing(RuntimeError):
    """The agent's binary is not installed."""


def build_argv(agent: str, task: str, brief_text: str) -> list[str]:
    if agent not in AGENTS:
        known = ", ".join(sorted(AGENTS))
        raise UnknownAgent(f"Unknown agent {agent!r}. Known agents: {known}")
    prompt = f"{brief_text}\n\n{task}" if brief_text else task
    return [AGENTS[agent], prompt]


def launch(
    agent: str,
    task: str,
    brief_text: str,
    which=None,
    exec_fn=None,
) -> int:
    """Replace this process with the agent's own CLI.

    `which` and `exec_fn` are resolved here, not as default arguments. Binding
    them in the signature would capture the function objects at import time, so
    `monkeypatch.setattr(runner.shutil, "which", ...)` would silently have no
    effect and a test would exec the real agent — replacing the test process and
    spending real vendor quota. That actually happened on 2026-08-17.
    """
    argv = build_argv(agent, task, brief_text)
    which = which if which is not None else _which
    exec_fn = exec_fn if exec_fn is not None else _exec
    if which(argv[0]) is None:
        raise AgentMissing(f"{argv[0]} is not installed or not on PATH")
    exec_fn(argv[0], argv)
    return 0  # unreachable when exec_fn is the real os.execvp
