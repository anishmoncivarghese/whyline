"""The provider-neutral session and event model for `whyline console`.
Every command adapter returns a SessionEvent instead of printing directly,
so the render loop (repl.py) is the only place that ever touches the
terminal -- this is what lets a later full-screen UI reuse this exact
model without rewriting the adapters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SessionEvent:
    kind: str  # "output" | "handoff" | "pause" | "error" | "exit"
    text: str


@dataclass
class ConsoleSession:
    root: Path
    mode: str = "command"  # "command" | "relay" | "chat"
    agent: str | None = None
    transcript: list[SessionEvent] = field(default_factory=list)

    def record(self, event: SessionEvent) -> SessionEvent:
        self.transcript.append(event)
        return event
