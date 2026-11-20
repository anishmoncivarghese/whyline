"""The packaged connector catalogue: what a person can add to an agent."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

NOT_CHECKED = "not checked by whyline yet"

_PROGRAM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_VAR = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_DATA = Path(__file__).with_name("connectors.toml")


class CatalogueError(ValueError):
    """An entry in the catalogue breaks a rule."""


@dataclass(frozen=True)
class Credential:
    var: str
    label: str
    where: str


@dataclass(frozen=True)
class Tool:
    name: str
    risk: str


@dataclass(frozen=True)
class Entry:
    name: str
    title: str
    about: str
    command: str
    args: tuple[str, ...]
    credentials: tuple[Credential, ...]
    tools: tuple[Tool, ...]
    source: str
    checked: str

    @property
    def status(self) -> str:
        return f"checked {self.checked}" if self.checked else NOT_CHECKED


def _entry(raw: dict) -> Entry:
    name = str(raw.get("name", ""))
    if not name:
        raise CatalogueError("an entry has no name")
    source = str(raw.get("source", "")).strip()
    if not source:
        raise CatalogueError(f"{name}: no source")
    command = str(raw.get("command", ""))
    if not _PROGRAM.match(command):
        raise CatalogueError(f"{name}: command {command!r} is not a bare program name")
    creds = []
    for c in raw.get("credentials", []):
        var = str(c.get("var", ""))
        if not _VAR.match(var):
            raise CatalogueError(f"{name}: credential var is not a variable name")
        creds.append(Credential(var, str(c.get("label", var)), str(c.get("where", ""))))
    tools = tuple(Tool(str(t["name"]), str(t.get("risk", ""))) for t in raw.get("tools", []))
    return Entry(
        name=name,
        title=str(raw.get("title", name)),
        about=str(raw.get("about", "")),
        command=command,
        args=tuple(str(a) for a in raw.get("args", [])),
        credentials=tuple(creds),
        tools=tools,
        source=source,
        checked=str(raw.get("checked", "")),
    )


def parse(text: str) -> list[Entry]:
    return [_entry(r) for r in tomllib.loads(text).get("connector", [])]


def load() -> list[Entry]:
    return parse(_DATA.read_text(encoding="utf-8"))


def search(text: str, entries: list[Entry] | None = None) -> list[Entry]:
    """Entries whose title, about line and tool names contain every word."""
    words = text.lower().split()
    found = []
    for e in load() if entries is None else entries:
        hay = " ".join([e.title, e.about, *(t.name for t in e.tools)]).lower()
        if all(w in hay for w in words):
            found.append(e)
    return found
