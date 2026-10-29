"""Built-in personal agent templates (`templates/<name>/`)."""
from __future__ import annotations

import datetime
import errno
import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from whyline.agents import definitions as d, paths, service, state

TEMPLATES_DIR = Path(__file__).with_name("templates")


@dataclass(frozen=True)
class TemplateInfo:
    name: str
    title: str
    about: str

    @property
    def description(self) -> str:
        return self.about

    def __iter__(self):
        yield self.name
        yield self.title
        yield self.about


Template = TemplateInfo


def default_workdir(name: str) -> str:
    return f"~/.whyline/{name}"


def _templates_root(templates_dir: Path | None = None) -> Path:
    return Path(templates_dir) if templates_dir is not None else TEMPLATES_DIR


def _template_folder(name: str, templates_dir: Path | None = None) -> Path:
    root = _templates_root(templates_dir)
    if (
        not isinstance(name, str)
        or not name
        or "/" in name
        or "\\" in name
        or name in (".", "..")
        or name.startswith(".")
    ):
        raise d.DefinitionError(f"unknown template: {name}")
    folder = root / name
    try:
        inside = folder.resolve().is_relative_to(root.resolve())
    except OSError:
        inside = False
    if not inside or not folder.is_dir():
        raise d.DefinitionError(f"unknown template: {name}")
    return folder


def _read_agent_toml(folder: Path, name: str) -> dict:
    agent_toml = folder / "agent.toml"
    if not agent_toml.is_file():
        raise d.DefinitionError(f"template {name} is missing agent.toml")
    try:
        raw = tomllib.loads(agent_toml.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        raise d.DefinitionError(f"could not read {agent_toml}: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise d.DefinitionError(f"not valid TOML: {error}") from error
    d._str(raw, "title")
    d._str(raw, "about")
    if "workdir" in raw:
        raise d.DefinitionError("template agent.toml must not set workdir")
    if "name" in raw:
        raw_name = d._str(raw, "name")
        if not d.NAME.match(raw_name):
            raise d.DefinitionError("name must be lower-case letters, digits and -, at most 40")
    if "instructions" in raw:
        d._str(raw, "instructions")
    return raw


def _read_instructions(folder: Path, name: str) -> str:
    instructions_path = folder / "instructions.md"
    if not instructions_path.is_file():
        raise d.DefinitionError(f"template {name} is missing instructions.md")
    try:
        return instructions_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise d.DefinitionError(f"could not read {instructions_path}: {error}") from error


def _toml_key(key: str) -> str:
    return json.dumps(key, ensure_ascii=False).replace("\x7f", "\\u007f")


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        items = ", ".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items())
        return "{" + items + "}"
    raise d.DefinitionError(f"unsupported TOML value: {type(value).__name__}")


def _dump_toml(data: dict) -> str:
    return "\n".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in data.items()) + "\n"


def _normalise_workdir(name: str, workdir: str | Path | None) -> str:
    if workdir is None:
        return default_workdir(name)
    if not isinstance(workdir, (str, Path)):
        raise d.DefinitionError("workdir must be text")
    raw = str(workdir).strip()
    if not raw:
        return ""
    expanded = Path(raw).expanduser()
    if expanded.is_absolute():
        return raw
    return os.path.abspath(expanded)


def list_templates(*, templates_dir: Path | None = None) -> list[TemplateInfo]:
    root = _templates_root(templates_dir)
    if not root.is_dir():
        return []
    found: list[TemplateInfo] = []
    for folder in sorted(root.iterdir(), key=lambda item: item.name):
        if (
            not folder.is_dir()
            or folder.name.startswith((".", "__"))
            or not (folder / "agent.toml").is_file()
        ):
            continue
        raw = _read_agent_toml(folder, folder.name)
        title = " ".join(d._str(raw, "title").split())
        about = " ".join(d._str(raw, "about").split())
        found.append(TemplateInfo(name=folder.name, title=title, about=about))
    return found


def build(
    name: str,
    agent_name: str | None = None,
    workdir: str | Path | None = None,
    *,
    templates_dir: Path | None = None,
) -> d.AgentDef:
    """Build and validate a template's AgentDef in memory without writing files."""
    folder = _template_folder(name, templates_dir)
    raw = _read_agent_toml(folder, name)
    instructions = _read_instructions(folder, name)
    chosen_name = (raw.get("name") or name) if agent_name is None else agent_name
    if not isinstance(chosen_name, str):
        raise d.DefinitionError("name must be text")
    chosen_workdir = _normalise_workdir(name, workdir)
    merged = dict(raw)
    merged["name"] = chosen_name
    merged["instructions"] = instructions
    merged["workdir"] = chosen_workdir
    def_path = Path.home() / ".whyline" / "agents" / f"{chosen_name}.toml"
    return d.parse(_dump_toml(merged), kind="personal", path=def_path)


def _name_taken(defn: d.AgentDef) -> bool:
    if defn.path.exists():
        return True
    repo_root = defn.root if defn.kind == "repo" else None
    for item in d.discover(repo_root):
        if isinstance(item, d.AgentDef) and item.kind == defn.kind and item.name == defn.name:
            return True
    return False


def _has_symlink_component(base: Path, parts: tuple[str, ...]) -> bool:
    current = base
    for part in parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _ensure_target_dir(root: Path, root_resolved: Path, parts: tuple[str, ...]) -> Path | None:
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            return None
        if os.path.lexists(current):
            if not current.is_dir():
                return None
        else:
            try:
                current.mkdir()
            except FileExistsError:
                if current.is_symlink() or not current.is_dir():
                    return None
        try:
            if current.is_symlink() or not current.resolve().is_relative_to(root_resolved):
                return None
        except OSError:
            return None
    return current


def _copy_files_keep_existing(files_dir: Path, workdir_path: Path) -> None:
    if files_dir.is_symlink() or workdir_path.is_symlink():
        return
    if os.path.lexists(workdir_path):
        if not workdir_path.is_dir():
            return
    else:
        workdir_path.mkdir(parents=True, exist_ok=True)
    if workdir_path.is_symlink() or not workdir_path.is_dir():
        return
    src_root = files_dir.resolve()
    dst_root = workdir_path.resolve()
    for item in sorted(files_dir.rglob("*")):
        rel = item.relative_to(files_dir)
        if (
            not rel.parts
            or any(part in ("", ".", "..", ".DS_Store", "__pycache__") for part in rel.parts)
            or _has_symlink_component(files_dir, rel.parts)
        ):
            continue
        try:
            if not item.resolve().is_relative_to(src_root):
                continue
        except OSError:
            continue
        if item.is_dir():
            _ensure_target_dir(workdir_path, dst_root, rel.parts)
        elif item.is_file():
            parent = _ensure_target_dir(workdir_path, dst_root, rel.parts[:-1])
            if parent is None:
                continue
            target = parent / rel.parts[-1]
            if target.is_symlink() or os.path.lexists(target):
                continue
            try:
                if not parent.resolve().is_relative_to(dst_root):
                    continue
            except OSError:
                continue
            data = item.read_bytes()
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(target, flags, 0o666)
            except OSError as error:
                if error.errno in (errno.EEXIST, errno.ELOOP):
                    continue
                raise
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)


def create(
    name: str,
    agent_name: str | None = None,
    workdir: str | Path | None = None,
    *,
    defn: d.AgentDef | None = None,
    templates_dir: Path | None = None,
) -> d.AgentDef:
    """Create a personal agent from template `name`, leaving it not accepted yet."""
    folder = _template_folder(name, templates_dir)
    if defn is None:
        built = build(name, agent_name, workdir, templates_dir=templates_dir)
    else:
        _read_agent_toml(folder, name)
        _read_instructions(folder, name)
        repo_root = defn.root if defn.kind == "repo" else None
        built = d.parse(d.render(defn), kind=defn.kind, path=defn.path, repo_root=repo_root)
    if _name_taken(built):
        raise d.DefinitionError(f"an agent named {built.name} already exists")
    target_dir = Path(built.workdir).expanduser() if built.kind == "personal" else built.root
    if not os.path.lexists(target_dir):
        target_dir.mkdir(parents=True, exist_ok=True)
    files_dir = folder / "files"
    if files_dir.is_dir() and not files_dir.is_symlink():
        _copy_files_keep_existing(files_dir, target_dir)
    if built.kind == "personal":
        paths.home()
    service.save_new(built)
    conn = state.connect()
    try:
        state.remove(conn, built.agent_id)
    finally:
        conn.close()
    return built
