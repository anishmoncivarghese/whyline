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
    accepted: bool = True
    launched: bool | None = None

    def __post_init__(self) -> None:
        if self.launched is not None and self.accepted is True:
            object.__setattr__(self, "accepted", self.launched)
        elif self.launched is None:
            object.__setattr__(self, "launched", self.accepted)



@dataclass
class ConsoleSession:
    root: Path
    mode: str = "chat"  # "chat" | "relay" | "agents"
    agent: str | None = None
    transcript: list[SessionEvent] = field(default_factory=list)

    def __setattr__(self, name: str, value: object) -> None:
        # Command mode is gone. A leftover "command" is chat, including one
        # passed in by an old caller after this object already exists.
        if name == "mode" and value == "command":
            value = "chat"
        object.__setattr__(self, name, value)

    def record(self, event: SessionEvent) -> SessionEvent:
        self.transcript.append(event)
        return event
