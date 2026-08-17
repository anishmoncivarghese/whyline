"""Launching an agent by handing over the terminal.

We exec, we do not supervise. There is no PTY, no output capture and no
parsing, so a vendor changing its output format cannot break us. The
environment is passed through untouched and is never inspected.
"""

from __future__ import annotations

import os
import shutil

AGENTS = {"claude": "claude", "codex": "codex"}


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
    which=shutil.which,
    exec_fn=os.execvp,
) -> int:
    argv = build_argv(agent, task, brief_text)
    if which(argv[0]) is None:
        raise AgentMissing(f"{argv[0]} is not installed or not on PATH")
    exec_fn(argv[0], argv)
    return 0  # unreachable when exec_fn is the real os.execvp
