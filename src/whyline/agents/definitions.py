"""Agent definitions: one TOML file per agent, in a repository
(.whyline/agents/) or personal (~/.whyline/agents/). A definition never runs
on its own; see state.py for activations."""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from whyline.agents import before as before_steps, paths

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
CLIS = ("claude", "codex", "grok", "antigravity")
TRIGGER_KINDS = ("manual", "daily", "weekdays", "every", "folder")
TOOL_PERMISSIONS = ("allowed", "ask")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class DefinitionError(ValueError):
    pass


@dataclass(frozen=True)
class Trigger:
    kind: str = "manual"
    at: str = ""
    every_hours: int = 0
    folder: str = ""
    min_gap_minutes: int = 10


@dataclass(frozen=True)
class AgentDef:
    name: str
    kind: str  # "repo" | "personal"
    path: Path
    root: Path
    instructions: str
    runner: str
    backup: tuple[str, ...] = ()
    model: str = ""
    # Old files only; loaded into knowledge too, so it is not part of equality.
    sources: tuple[str, ...] = field(default=(), compare=False)
    skills: tuple[str, ...] = ()  # "origin:name"
    knowledge: tuple[str, ...] = ()  # paths, URLs and "pack:<name>"
    tools: dict[str, str] = field(default_factory=dict)  # "<server>.<tool>" -> allowed | ask
    workdir: str = ""
    report_folder: str = ""
    timeout_minutes: int = 15
    before: str = ""
    trigger: Trigger = field(default_factory=Trigger)

    @property
    def agent_id(self) -> str:
        if self.kind == "repo":
            return f"repo:{self.root.resolve()}:{self.name}"
        return f"personal:{self.name}"

    @property
    def label(self) -> str:
        return f"{self.name} ({self.kind})"


@dataclass(frozen=True)
class Broken:
    path: Path
    kind: str
    error: str


def _str(raw: dict, key: str, default: str = "") -> str:
    value = raw.get(key, default)
    if not isinstance(value, str):
        raise DefinitionError(f"{key} must be text")
    return value


def _strs(raw: dict, key: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise DefinitionError(f"{key} must be a list of text")
    return tuple(value)


def _int(raw: dict, key: str, default: int) -> int:
    value = raw.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise DefinitionError(f"{key} must be a whole number")
    return value


def _trigger(raw: object) -> Trigger:
    if not isinstance(raw, dict):
        raise DefinitionError("trigger must be a table")
    t = Trigger(
        kind=_str(raw, "kind", "manual"),
        at=_str(raw, "at"),
        every_hours=_int(raw, "every_hours", 0),
        folder=_str(raw, "folder"),
        min_gap_minutes=_int(raw, "min_gap_minutes", 10),
    )
    if t.kind not in TRIGGER_KINDS:
        raise DefinitionError(f"trigger kind must be one of {', '.join(TRIGGER_KINDS)}")
    if t.kind in ("daily", "weekdays") and not _TIME.match(t.at):
        raise DefinitionError('trigger "at" must be a 24-hour time like 07:00')
    if t.kind == "every" and not 1 <= t.every_hours <= 168:
        raise DefinitionError("trigger every_hours must be between 1 and 168")
    if t.kind == "folder" and not t.folder:
        raise DefinitionError("a folder trigger needs a folder")
    if t.min_gap_minutes < 1:
        raise DefinitionError("trigger min_gap_minutes must be at least 1")
    return t


def _expand(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def parse(text: str, *, kind: str, path: Path, repo_root: Path | None = None) -> AgentDef:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise DefinitionError(f"not valid TOML: {error}") from error
    name = _str(raw, "name")
    if not NAME.match(name):
        raise DefinitionError("name must be lower-case letters, digits and -, at most 40")
    instructions = _str(raw, "instructions").strip()
    if not instructions:
        raise DefinitionError("instructions are empty")
    runner = _str(raw, "runner")
    if runner not in CLIS:
        raise DefinitionError(f"runner must be one of {', '.join(CLIS)}")
    backup = _strs(raw, "backup")
    if runner in backup or len(set(backup)) != len(backup) or not set(backup) <= set(CLIS):
        raise DefinitionError("backup must list other CLIs, each once")
    workdir = _str(raw, "workdir")
    if kind == "repo":
        if repo_root is None:
            raise DefinitionError("a repo agent needs its repository")
        root = repo_root
    else:
        if not workdir:
            raise DefinitionError("a personal agent needs a workdir")
        root = Path(workdir).expanduser()
    timeout = _int(raw, "timeout_minutes", 15)
    if not 1 <= timeout <= 240:
        raise DefinitionError("timeout_minutes must be between 1 and 240")
    before = _str(raw, "before")
    if before not in before_steps.names():
        allowed = ", ".join(f'"{n}"' for n in before_steps.names())
        raise DefinitionError(f"before must be one of {allowed}")
    sources = _strs(raw, "sources")
    knowledge = tuple(dict.fromkeys((*_strs(raw, "knowledge"), *sources)))
    defn = AgentDef(
        name=name, kind=kind, path=path, root=root, instructions=instructions,
        runner=runner, backup=backup, model=_str(raw, "model"), sources=sources,
        skills=_strs(raw, "skills"), knowledge=knowledge, tools=_tools(raw.get("tools", {})),
        workdir=workdir, report_folder=_str(raw, "report_folder"),
        timeout_minutes=timeout, before=before, trigger=_trigger(raw.get("trigger", {})),
    )
    resolve_sources(defn)  # validates repo containment
    _check_tools(defn)
    return defn


def _tools(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict) or not all(isinstance(v, str) for v in raw.values()):
        raise DefinitionError("tools must be a table of allowed or ask")
    return dict(raw)


def _check_tools(defn: AgentDef) -> None:
    from whyline.tools import knowledge, mcp_config, skills

    repo = defn.root if defn.kind == "repo" else None
    total = 0
    for ref in defn.skills:
        try:
            skill = skills.get(ref, repo)
        except ValueError as error:
            raise DefinitionError(str(error)) from error
        except KeyError:
            raise DefinitionError(f"unknown skill {ref}") from None
        if skill.broken:
            raise DefinitionError(f"skill {ref} is broken: {skill.problem}")
        total += skill.size
    if total > skills.AGENT_SKILLS_LIMIT:
        raise DefinitionError(
            f"skills are {total} bytes; an agent may have at most {skills.AGENT_SKILLS_LIMIT}")
    for item in defn.knowledge:
        if item.startswith(knowledge.PACK_PREFIX):
            pack = item[len(knowledge.PACK_PREFIX):]
            try:
                knowledge.get_pack(pack)
            except KeyError:
                raise DefinitionError(f"unknown knowledge pack {pack}") from None
    if not defn.tools:
        return
    servers = mcp_config.load()
    for key, permission in defn.tools.items():
        server_name, _, tool_name = key.partition(".")
        server = servers.get(server_name)
        if server is None:
            raise DefinitionError(f"unknown server {server_name} in tool {key}")
        if tool_name not in {t.name for t in server.tools}:
            raise DefinitionError(f"unknown tool {tool_name} on server {server_name}")
        if permission not in TOOL_PERMISSIONS:
            raise DefinitionError(
                f"tool {key} must be {' or '.join(TOOL_PERMISSIONS)}, not {permission!r}")


def resolve_sources(defn: AgentDef) -> list[Path]:
    # Old files list sources; new ones list the same things under knowledge.
    plain = [k for k in defn.knowledge if not k.startswith("pack:") and "://" not in k]
    resolved = []
    for source in dict.fromkeys((*defn.sources, *plain)):
        path = _expand(source, defn.root)
        if defn.kind == "repo":
            real = path.resolve()
            if not real.is_relative_to(defn.root.resolve()):
                raise DefinitionError(f"source {source} is outside the repository")
        resolved.append(path)
    return resolved


def load(path: Path, *, kind: str, repo_root: Path | None = None) -> AgentDef:
    return parse(path.read_text(encoding="utf-8"), kind=kind, path=path, repo_root=repo_root)


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # a valid TOML basic string


def render(defn: AgentDef) -> str:
    lines = [f"name = {_q(defn.name)}", f"instructions = {_q(defn.instructions)}",
             f"runner = {_q(defn.runner)}"]
    lines.append("backup = [" + ", ".join(_q(b) for b in defn.backup) + "]")
    if defn.model:
        lines.append(f"model = {_q(defn.model)}")
    # knowledge already holds what an old file called sources
    knowledge = dict.fromkeys((*defn.knowledge, *defn.sources))
    lines.append("knowledge = [" + ", ".join(_q(k) for k in knowledge) + "]")
    if defn.skills:
        lines.append("skills = [" + ", ".join(_q(s) for s in defn.skills) + "]")
    if defn.workdir:
        lines.append(f"workdir = {_q(defn.workdir)}")
    if defn.report_folder:
        lines.append(f"report_folder = {_q(defn.report_folder)}")
    lines.append(f"timeout_minutes = {defn.timeout_minutes}")
    if defn.before:
        lines.append(f"before = {_q(defn.before)}")
    if defn.tools:
        lines += ["", "[tools]"] + [f"{_q(k)} = {_q(v)}" for k, v in sorted(defn.tools.items())]
    t = defn.trigger
    lines += ["", "[trigger]", f"kind = {_q(t.kind)}"]
    if t.at:
        lines.append(f"at = {_q(t.at)}")
    if t.every_hours:
        lines.append(f"every_hours = {t.every_hours}")
    if t.folder:
        lines.append(f"folder = {_q(t.folder)}")
    lines.append(f"min_gap_minutes = {t.min_gap_minutes}")
    return "\n".join(lines) + "\n"


def save(defn: AgentDef) -> Path:
    defn.path.parent.mkdir(parents=True, exist_ok=True)
    defn.path.write_text(render(defn), encoding="utf-8")
    return defn.path


def definition_hash(text: str) -> str:
    raw = tomllib.loads(text)
    tools = raw.get("tools")
    if isinstance(tools, dict) and tools:
        # A server whose tools changed is a different agent until accepted again.
        from whyline.tools import mcp_config

        servers = mcp_config.load()
        used = sorted({key.partition(".")[0] for key in tools})
        raw = {**raw, "_tools_hash": {
            name: servers[name].tools_hash if name in servers else "" for name in used}}
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def uses(repo_root: Path | None = None) -> list:
    """What each agent uses, for the removal guard."""
    from whyline.tools import mcp_config, users

    servers = mcp_config.load()
    found = []
    for item in discover(repo_root):
        if isinstance(item, Broken):
            continue
        who = f"agent {item.name}"
        for ref in item.skills:
            found.append(users.Use("skill", ref, who))
        for entry in item.knowledge:
            if entry.startswith("pack:"):
                found.append(users.Use("pack", entry[len("pack:"):], who))
        for server_name in sorted({key.partition(".")[0] for key in item.tools}):
            found.append(users.Use("server", server_name, who))
            server = servers.get(server_name)
            for credential in sorted(server.env.values()) if server else ():
                found.append(users.Use("credential", credential, who))
    return found


def register_users() -> None:
    from whyline.tools import users

    users.register("agents", lambda: uses(Path.cwd()))


register_users()


def _scan(folder: Path, kind: str, repo_root: Path | None) -> list[AgentDef | Broken]:
    valid: list[AgentDef] = []
    broken: list[Broken] = []
    if not folder.is_dir():
        return []
    for path in folder.glob("*.toml"):
        try:
            valid.append(load(path, kind=kind, repo_root=repo_root))
        except (DefinitionError, OSError) as error:
            broken.append(Broken(path, kind, str(error)))
    # A broken file has no agent name. It leads its scope, by filename.
    # Valid agents follow, by parsed name, with the filename as a tie-break.
    broken.sort(key=lambda item: item.path.name)
    valid.sort(key=lambda agent: (agent.name, agent.path.name))
    return broken + valid


def discover(repo_root: Path | None) -> list[AgentDef | Broken]:
    found = _scan(paths.repo_dir(repo_root), "repo", repo_root) if repo_root else []
    return found + _scan(Path.home() / ".whyline" / "agents", "personal", None)
