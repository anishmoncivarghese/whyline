"""Agent definitions: one TOML file per agent, in a repository
(.whyline/agents/) or personal (~/.whyline/agents/). A definition never runs
on its own; see state.py for activations."""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from whyline.agents import before as before_steps, paths, watch as watch_rules

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
CLIS = ("claude", "codex", "grok", "antigravity")
TRIGGER_KINDS = ("manual", "daily", "weekdays", "every", "folder", "once", "weekly")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_TIMES = 6
EVERY_MINUTES_RANGE = (5, 10080)
MAX_RUNS_LIMIT = 10000
TOOL_PERMISSIONS = ("allowed", "ask")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DAY = "(?:mon|tue|wed|thu|fri|sat|sun)"
_HOURS = re.compile(
    rf"^(?P<a>([01]\d|2[0-3]):[0-5]\d)-(?P<b>([01]\d|2[0-3]):[0-5]\d)"
    rf"(?: (?P<days>{_DAY}-{_DAY}|{_DAY}(?:,{_DAY})*))?$")


class DefinitionError(ValueError):
    pass


@dataclass(frozen=True)
class Trigger:
    kind: str = "manual"
    at: str = ""
    every_hours: int = 0
    folder: str = ""
    min_gap_minutes: int = 10
    every_minutes: int = 0
    on: str = ""  # YYYY-MM-DD, for once
    days: tuple[str, ...] = ()  # mon..sun, for weekly
    starts: str = ""  # YYYY-MM-DD
    ends: str = ""  # YYYY-MM-DD
    max_runs: int = 0  # 0 = no limit


@dataclass(frozen=True)
class AgentDef:
    name: str
    kind: str  # "repo" | "personal"
    path: Path
    root: Path
    instructions: str
    runner: str
    backup: tuple[str, ...] = ()
    model: str = ""  # the runner's model; kept in step with models[runner]
    models: dict[str, str] = field(default_factory=dict)  # CLI -> model
    # True when the file spelled the runner's model as the old `model = "x"`.
    model_field: bool = field(default=False, compare=False)
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
    gate: str = ""  # a check-in gate (gates.py); empty runs the agent every time
    gate_args: dict[str, str] = field(default_factory=dict)
    active_hours: str = ""  # HH:MM-HH:MM, then optional days: mon-fri or mon,wed
    silent: bool = False
    watch: watch_rules.Watch | None = None

    def __post_init__(self) -> None:
        models = dict(self.models)
        if self.model and self.runner not in models:
            models[self.runner] = self.model
            object.__setattr__(self, "model_field", True)
        object.__setattr__(self, "models", models)
        object.__setattr__(self, "model", models.get(self.runner, ""))

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


def _models(raw: dict, runner: str, backup: tuple[str, ...]) -> dict[str, str]:
    table = raw.get("models", {})
    if not isinstance(table, dict) or not all(isinstance(v, str) for v in table.values()):
        raise DefinitionError("models must be a table of text")
    unknown = [cli for cli in table if cli not in (runner, *backup)]
    if unknown:
        raise DefinitionError(
            f"models names {', '.join(unknown)}, which is not the runner or a backup")
    return {cli: model for cli, model in table.items() if model.strip()}


def _int(raw: dict, key: str, default: int) -> int:
    value = raw.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise DefinitionError(f"{key} must be a whole number")
    return value


def times(t: Trigger) -> tuple[str, ...]:
    """The times in t.at, sorted, each once. A bad or surplus time is refused."""
    if not t.at.strip():
        return ()
    found = [part.strip() for part in t.at.split(",")]
    if len(found) > MAX_TIMES:
        raise DefinitionError(f'trigger "at" may list at most {MAX_TIMES} times')
    if not all(_TIME.match(part) for part in found):
        raise DefinitionError('trigger "at" must be 24-hour times like 07:00, separated by commas')
    return tuple(sorted(set(found)))


def _date(value: str, label: str) -> None:
    if not value:
        return
    if not _DATE.match(value):
        raise DefinitionError(f"trigger {label} must be a date like 2026-11-17")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise DefinitionError(f"trigger {label} must be a date like 2026-11-17") from None


def _trigger(raw: object) -> Trigger:
    if not isinstance(raw, dict):
        raise DefinitionError("trigger must be a table")
    t = Trigger(
        kind=_str(raw, "kind", "manual"),
        at=_str(raw, "at"),
        every_hours=_int(raw, "every_hours", 0),
        folder=_str(raw, "folder"),
        min_gap_minutes=_int(raw, "min_gap_minutes", 10),
        every_minutes=_int(raw, "every_minutes", 0),
        on=_str(raw, "on"),
        days=_strs(raw, "days"),
        starts=_str(raw, "starts"),
        ends=_str(raw, "ends"),
        max_runs=_int(raw, "max_runs", 0),
    )
    if t.kind not in TRIGGER_KINDS:
        raise DefinitionError(f"trigger kind must be one of {', '.join(TRIGGER_KINDS)}")
    listed = times(t)
    if t.kind in ("daily", "weekdays", "weekly", "once") and not listed:
        raise DefinitionError('trigger "at" must be a 24-hour time like 07:00')
    if t.kind == "once":
        if not t.on:
            raise DefinitionError("a once trigger needs a date (on)")
        if len(listed) != 1:
            raise DefinitionError("a once trigger needs exactly one time")
    if t.kind == "weekly":
        if not t.days:
            raise DefinitionError("a weekly trigger needs at least one day")
        if not set(t.days) <= set(DAYS) or len(set(t.days)) != len(t.days):
            raise DefinitionError(f"trigger days must be from {', '.join(DAYS)}, each once")
    _date(t.on, "on")
    _date(t.starts, "starts")
    _date(t.ends, "ends")
    if t.starts and t.ends and t.ends < t.starts:
        raise DefinitionError("trigger ends is before starts")
    if not 0 <= t.max_runs <= MAX_RUNS_LIMIT:
        raise DefinitionError(f"trigger max_runs must be between 1 and {MAX_RUNS_LIMIT}")
    if t.kind == "every":
        low, high = EVERY_MINUTES_RANGE
        if t.every_minutes:
            if not low <= t.every_minutes <= high:
                raise DefinitionError(f"trigger every_minutes must be between {low} and {high}")
        elif not 1 <= t.every_hours <= 168:
            raise DefinitionError("trigger every_hours must be between 1 and 168")
    if t.kind == "folder" and not t.folder:
        raise DefinitionError("a folder trigger needs a folder")
    if t.min_gap_minutes < 1:
        raise DefinitionError("trigger min_gap_minutes must be at least 1")
    return t


def _checkin(raw: object) -> tuple[str, dict[str, str], str, bool]:
    from whyline.agents import gates

    if not isinstance(raw, dict):
        raise DefinitionError("checkin must be a table")
    gate = _str(raw, "gate")
    args = raw.get("gate_args", {})
    if not isinstance(args, dict) or not all(isinstance(v, str) for v in args.values()):
        raise DefinitionError("checkin gate_args must be a table of text")
    hours = _str(raw, "active_hours").strip()
    silent = raw.get("silent", False)
    if not isinstance(silent, bool):
        raise DefinitionError("checkin silent must be true or false")
    if gate:
        try:
            args = gates.validate(gate, args)
        except gates.GateError as error:
            raise DefinitionError(f"checkin gate: {error}") from error
    elif args:
        raise DefinitionError("checkin gate_args need a gate")
    if hours:
        found = _HOURS.match(hours)
        if not found or found["a"] == found["b"]:
            raise DefinitionError(
                "checkin active_hours must look like 09:00-17:00 or 09:00-17:00 mon-fri")
    return gate, dict(args), hours, silent


def _watch(raw: object) -> watch_rules.Watch | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DefinitionError("watch must be a table")
    stop = _str(raw, "stop", "never")
    if stop not in watch_rules.STOPS:
        raise DefinitionError(f"watch stop must be one of {', '.join(watch_rules.STOPS)}")
    value = _str(raw, "value").strip()
    try:
        watch_rules.check_value_rule(value)
    except ValueError as error:
        raise DefinitionError(str(error)) from error
    urgent = raw.get("urgent", False)
    if not isinstance(urgent, bool):
        raise DefinitionError("watch urgent must be true or false")
    low, high = watch_rules.DAILY_CAP_RANGE
    cap = _int(raw, "daily_cap", 24)
    if not low <= cap <= high:
        raise DefinitionError(f"watch daily_cap must be between {low} and {high}")
    return watch_rules.Watch(stop=stop, value=value, urgent=urgent, daily_cap=cap)


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
    gate, gate_args, active_hours, silent = _checkin(raw.get("checkin", {}))
    watch = _watch(raw.get("watch"))
    if watch is not None and gate != "page":
        raise DefinitionError("a watch needs the page gate")
    if watch is not None and watch.value:
        if not instructions:
            raise DefinitionError("a watch value needs instructions")
        if gate_args.get("rule") == "gone":
            raise DefinitionError("a watch value cannot go with the gone rule")
    if not instructions and not (
            watch is not None and not watch.value
            and gate_args.get("rule") in ("changed", "appears", "gone")):
        raise DefinitionError("instructions are empty")
    runner = _str(raw, "runner")
    if runner not in CLIS:
        raise DefinitionError(f"runner must be one of {', '.join(CLIS)}")
    backup = _strs(raw, "backup")
    if runner in backup or len(set(backup)) != len(backup) or not set(backup) <= set(CLIS):
        raise DefinitionError("backup must list other CLIs, each once")
    models = _models(raw, runner, backup)
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
        runner=runner, backup=backup, model=_str(raw, "model"), models=models, sources=sources,
        skills=_strs(raw, "skills"), knowledge=knowledge, tools=_tools(raw.get("tools", {})),
        workdir=workdir, report_folder=_str(raw, "report_folder"),
        timeout_minutes=timeout, before=before, trigger=_trigger(raw.get("trigger", {})),
        gate=gate, gate_args=gate_args, active_hours=active_hours, silent=silent,
        watch=watch,
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
        # A made tool that is not accepted is refused when it is called, not here.
        if server_name != mcp_config.MADE and tool_name not in {t.name for t in server.tools}:
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
    only_runner = defn.models == {defn.runner: defn.model}
    if defn.model and only_runner and defn.model_field:
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
    if defn.models and not (only_runner and defn.model_field):
        lines += ["", "[models]"] + [f"{_q(k)} = {_q(v)}" for k, v in sorted(defn.models.items())]
    if defn.tools:
        lines += ["", "[tools]"] + [f"{_q(k)} = {_q(v)}" for k, v in sorted(defn.tools.items())]
    t = defn.trigger
    lines += ["", "[trigger]", f"kind = {_q(t.kind)}"]
    if t.at:
        lines.append(f"at = {_q(t.at)}")
    if t.every_hours:
        lines.append(f"every_hours = {t.every_hours}")
    if t.every_minutes:
        lines.append(f"every_minutes = {t.every_minutes}")
    if t.on:
        lines.append(f"on = {_q(t.on)}")
    if t.days:
        lines.append("days = [" + ", ".join(_q(day) for day in t.days) + "]")
    if t.starts:
        lines.append(f"starts = {_q(t.starts)}")
    if t.ends:
        lines.append(f"ends = {_q(t.ends)}")
    if t.max_runs:
        lines.append(f"max_runs = {t.max_runs}")
    if t.folder:
        lines.append(f"folder = {_q(t.folder)}")
    lines.append(f"min_gap_minutes = {t.min_gap_minutes}")
    if defn.gate or defn.active_hours or defn.silent:
        lines += ["", "[checkin]"]
        if defn.gate:
            lines.append(f"gate = {_q(defn.gate)}")
        if defn.active_hours:
            lines.append(f"active_hours = {_q(defn.active_hours)}")
        if defn.silent:
            lines.append("silent = true")
        if defn.gate_args:
            lines += ["", "[checkin.gate_args]"]
            lines += [f"{_q(k)} = {_q(v)}" for k, v in sorted(defn.gate_args.items())]
    if defn.watch is not None:
        w = defn.watch
        lines += ["", "[watch]", f"stop = {_q(w.stop)}"]
        if w.value:
            lines.append(f"value = {_q(w.value)}")
        if w.urgent:
            lines.append("urgent = true")
        lines.append(f"daily_cap = {w.daily_cap}")
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
        used = sorted({key.partition(".")[0] for key in tools} - {mcp_config.MADE})
        raw = {**raw, "_tools_hash": {
            name: servers[name].tools_hash if name in servers else "" for name in used}}
        # A made tool that was edited or removed is a different agent until accepted again.
        from whyline.tools import made

        held = {}
        for key in sorted(tools):
            server_name, _, tool_name = key.partition(".")
            if server_name == mcp_config.MADE:
                tool = made.load(tool_name)
                held[tool_name] = tool.accepted_hash if tool else ""
        if held:
            raw["_made_hash"] = held
    named = raw.get("skills")
    if isinstance(named, list) and named:
        # An installed skill whose files changed is a different agent until accepted again.
        from whyline.tools import skill_install

        held = {}
        for ref in sorted({str(r) for r in named}):
            origin, _, skill = ref.partition(":")
            digest = skill_install.files_hash(skill) if origin == "whyline" and skill else None
            if digest is not None:
                held[ref] = digest
        if held:
            raw = {**raw, "_skills_hash": held}
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
