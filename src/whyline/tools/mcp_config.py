"""MCP servers whyline may start for agents, kept in ~/.whyline/mcp.toml (0600).

A server's ``env`` maps a variable name to a credential name, never to a
value. ``import_candidates`` reads other tools' configs and changes none of
them."""
from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from whyline.tools import users

_NAME = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_VAR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    read_only: bool = False


@dataclass(frozen=True)
class Server:
    name: str
    command: str
    args: tuple[str, ...] = ()
    cwd: str = ""
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    tools_hash: str = ""
    tools: tuple[Tool, ...] = ()


@dataclass(frozen=True)
class Candidate:
    name: str
    source: str
    command: str = ""
    args: tuple[str, ...] = ()
    cwd: str = ""
    needs_credential: tuple[str, ...] = ()
    refused: str = ""

    def notes(self) -> list[str]:
        notes = [f"needs a credential: {var}" for var in self.needs_credential]
        if self.refused:
            notes.append(f"refused: {self.refused}")
        return notes


def _file() -> Path:
    return Path.home() / ".whyline" / "mcp.toml"


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name))


def _validate(server: Server) -> None:
    if not valid_name(server.name):
        raise ValueError("a server name is lowercase letters, digits and hyphens, starting with a letter")
    if not server.command.strip():
        raise ValueError("a server needs a command")
    for var, cred in server.env.items():
        if not _VAR.match(var):
            raise ValueError(f"{var!r} is not an environment variable name")
        if not valid_name(cred):
            raise ValueError(f"{var} must name a credential, not hold a value")


def load() -> dict[str, Server]:
    try:
        raw = tomllib.loads(_file().read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}
    found: dict[str, Server] = {}
    for name, entry in raw.get("servers", {}).items():
        tools = []
        for item in entry.get("tools", []):
            try:
                schema = json.loads(item.get("input_schema", "{}"))
            except (TypeError, ValueError):
                schema = {}
            tools.append(Tool(
                name=str(item.get("name", "")),
                description=str(item.get("description", "")),
                input_schema=schema if isinstance(schema, dict) else {},
                read_only=bool(item.get("read_only", False)),
            ))
        found[name] = Server(
            name=name,
            command=str(entry.get("command", "")),
            args=tuple(str(a) for a in entry.get("args", [])),
            cwd=str(entry.get("cwd", "")),
            env={str(k): str(v) for k, v in entry.get("env", {}).items()},
            enabled=bool(entry.get("enabled", True)),
            tools_hash=str(entry.get("tools_hash", "")),
            tools=tuple(tools),
        )
    return found


def _q(value: object) -> str:
    return json.dumps(value)


def _write(servers: dict[str, Server]) -> None:
    lines: list[str] = []
    for name in sorted(servers):
        server = servers[name]
        lines.append(f"[servers.{name}]")
        lines.append(f"command = {_q(server.command)}")
        lines.append(f"args = {_q(list(server.args))}")
        if server.cwd:
            lines.append(f"cwd = {_q(server.cwd)}")
        lines.append(f"enabled = {'true' if server.enabled else 'false'}")
        lines.append(f"tools_hash = {_q(server.tools_hash)}")
        if server.env:
            lines.append(f"[servers.{name}.env]")
            for var in sorted(server.env):
                lines.append(f"{_q(var)} = {_q(server.env[var])}")
        for tool in server.tools:
            lines.append(f"[[servers.{name}.tools]]")
            lines.append(f"name = {_q(tool.name)}")
            lines.append(f"description = {_q(tool.description)}")
            lines.append(f"input_schema = {_q(json.dumps(tool.input_schema, sort_keys=True))}")
            lines.append(f"read_only = {'true' if tool.read_only else 'false'}")
        lines.append("")
    target = _file()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    if os.name != "nt":
        os.chmod(target, 0o600)


def save_server(server: Server) -> None:
    _validate(server)
    servers = load()
    servers[server.name] = server
    _write(servers)


def remove_server(name: str) -> None:
    """Delete a server. Refused, naming the users, while anything uses it."""
    servers = load()
    if name not in servers:
        raise KeyError(name)
    in_use = users.of("server", name)
    if in_use:
        raise ValueError(f"{name} is used by {', '.join(in_use)}")
    del servers[name]
    _write(servers)


def _sources() -> list[tuple[str, Path]]:
    home = Path.home()
    return [
        ("~/.claude.json", home / ".claude.json"),
        ("Claude Desktop", home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"),
        ("~/.codex/config.toml", home / ".codex" / "config.toml"),
    ]


def _read(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
        data = tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _entries(label: str, data: dict) -> list[tuple[str, dict]]:
    if label.endswith("config.toml"):
        table = data.get("mcp_servers", {})
        found = list(table.items()) if isinstance(table, dict) else []
    else:
        found = []
        tables = [data.get("mcpServers")]
        projects = data.get("projects")
        if isinstance(projects, dict):
            tables += [p.get("mcpServers") for p in projects.values() if isinstance(p, dict)]
        for table in tables:
            if isinstance(table, dict):
                found += list(table.items())
    return [(str(n), e) for n, e in found if isinstance(e, dict)]


def _clean_name(raw: str) -> str:
    name = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")
    if not name or not name[0].isalpha():
        name = f"mcp-{name}".strip("-")
    return name[:40].rstrip("-")


def _candidate(name: str, source: str, entry: dict) -> Candidate:
    name = _clean_name(name)
    kind = str(entry.get("type", "")).lower()
    if entry.get("url") or entry.get("serverUrl") or kind in ("http", "sse", "streamable-http"):
        return Candidate(name, source, refused="remote servers are not supported; only local commands run")
    command = entry.get("command")
    if not isinstance(command, str) or not command.strip():
        return Candidate(name, source, refused="no command to run")
    args = entry.get("args", [])
    env = entry.get("env", {})
    return Candidate(
        name=name, source=source, command=command,
        args=tuple(str(a) for a in args) if isinstance(args, list) else (),
        cwd=str(entry.get("cwd", "")) if entry.get("cwd") else "",
        needs_credential=tuple(sorted(str(v) for v in env)) if isinstance(env, dict) else (),
    )


def import_candidates() -> list[Candidate]:
    """Servers found in other tools' configs. Nothing is changed, and an env
    value is never copied: it is only reported as a variable needing a credential."""
    found: list[Candidate] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for label, path in _sources():
        for name, entry in _entries(label, _read(path)):
            candidate = _candidate(name, label, entry)
            key = (candidate.name, candidate.command, candidate.args)
            if key not in seen:
                seen.add(key)
                found.append(candidate)
    return found
