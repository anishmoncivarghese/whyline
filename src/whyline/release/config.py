"""Load, save and detect `.whyline/release.toml`, and track pending setup files."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from whyline.security import settings as security_settings
from whyline.security.settings import SecuritySettings

MODES = ("ask", "step", "auto")
CONFIG_PATH = Path(".whyline") / "release.toml"
PENDING_PATH = Path(".git") / "whyline-release" / "pending.json"


class ConfigError(ValueError):
    """A bad value in release.toml; the message names the key."""


@dataclass(frozen=True)
class DockerTarget:
    registries: tuple[str, ...] = ("ghcr",)
    image: str = ""


@dataclass(frozen=True)
class HomebrewTarget:
    tap: str = ""
    formula: str = ""


@dataclass(frozen=True)
class CustomTarget:
    name: str
    run: str
    verify: str = ""


@dataclass(frozen=True)
class Targets:
    """The bools are `docker` and `homebrew`; their options are `docker_options`
    and `homebrew_options` because a field cannot be both."""

    github: bool = True
    pypi: bool = False
    npm: bool = False
    docker: bool = False
    homebrew: bool = False
    docker_options: DockerTarget = field(default_factory=DockerTarget)
    homebrew_options: HomebrewTarget = field(default_factory=HomebrewTarget)
    custom: tuple[CustomTarget, ...] = ()


@dataclass(frozen=True)
class ReleaseConfig:
    mode: str = "ask"
    branch: str = "main"
    start_after_plan: bool = False
    bring_in_main: bool = True
    checks: tuple[str, ...] = ()
    ci_ignore: tuple[str, ...] = ()
    notes: str = "docs/releases/v{version}.md"
    version_files: tuple[str, ...] = ()
    after: tuple[str, ...] = ()
    targets: Targets = field(default_factory=Targets)
    security: SecuritySettings = field(default_factory=SecuritySettings)


# --- reading -----------------------------------------------------------------


def _table(data: dict, key: str, label: str) -> dict:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a table")
    return value


def _str(table: dict, key: str, default: str, label: str) -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{label} must be a string")
    return value


def _bool(table: dict, key: str, default: bool, label: str) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{label} must be true or false")
    return value


def _strs(table: dict, key: str, default: tuple[str, ...], label: str) -> tuple[str, ...]:
    value = table.get(key, list(default))
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{label} must be a list of strings")
    return tuple(value)


def _custom(raw: object) -> tuple[CustomTarget, ...]:
    if not isinstance(raw, list):
        raise ConfigError("targets.custom must be a list of tables")
    out: list[CustomTarget] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        label = f"targets.custom[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{label} must be a table")
        for key in ("name", "run"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ConfigError(f"{label}.{key} is required")
        verify = _str(item, "verify", "", f"{label}.verify")
        if item["name"] in seen:
            raise ConfigError(f"targets.custom.name {item['name']!r} is used twice")
        seen.add(item["name"])
        out.append(CustomTarget(item["name"], item["run"], verify))
    return tuple(out)


def parse(data: dict) -> ReleaseConfig:
    base = ReleaseConfig()
    release = _table(data, "release", "release")
    mode = _str(release, "mode", base.mode, "release.mode")
    if mode not in MODES:
        raise ConfigError(f"release.mode must be one of {', '.join(MODES)}, not {mode!r}")
    targets = _table(data, "targets", "targets")
    docker = _table(data, "docker", "docker")
    homebrew = _table(data, "homebrew", "homebrew")
    try:
        security = security_settings.parse(data.get("security", {}))
    except security_settings.SettingsError as exc:
        raise ConfigError(str(exc)) from exc
    flags = {}
    for name in ("github", "pypi", "npm", "docker", "homebrew"):
        value = targets.get(name, getattr(base.targets, name))
        if not isinstance(value, bool):
            raise ConfigError(f"targets.{name} must be true or false")
        flags[name] = value
    return ReleaseConfig(
        mode=mode,
        branch=_str(release, "branch", base.branch, "release.branch"),
        start_after_plan=_bool(release, "start_after_plan", False, "release.start_after_plan"),
        bring_in_main=_bool(release, "bring_in_main", True, "release.bring_in_main"),
        checks=_strs(release, "checks", base.checks, "release.checks"),
        ci_ignore=_strs(release, "ci_ignore", base.ci_ignore, "release.ci_ignore"),
        notes=_str(release, "notes", base.notes, "release.notes"),
        version_files=_strs(release, "version_files", base.version_files, "release.version_files"),
        after=_strs(release, "after", base.after, "release.after"),
        targets=Targets(
            **flags,
            docker_options=DockerTarget(
                registries=_strs(docker, "registries", ("ghcr",), "docker.registries"),
                image=_str(docker, "image", "", "docker.image"),
            ),
            homebrew_options=HomebrewTarget(
                tap=_str(homebrew, "tap", "", "homebrew.tap"),
                formula=_str(homebrew, "formula", "", "homebrew.formula"),
            ),
            custom=_custom(targets.get("custom", [])),
        ),
        security=security,
    )


def load(root: Path) -> ReleaseConfig:
    path = Path(root) / CONFIG_PATH
    if not path.exists():
        return ReleaseConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{CONFIG_PATH.as_posix()} is not valid TOML: {exc}") from exc
    return parse(data)


# --- writing -----------------------------------------------------------------


def _quote(text: str) -> str:
    out = ['"']
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _list(items: tuple[str, ...]) -> str:
    return "[" + ", ".join(_quote(i) for i in items) + "]"


def _flag(value: bool) -> str:
    return "true" if value else "false"


def render(cfg: ReleaseConfig) -> str:
    t = cfg.targets
    lines = [
        "[release]",
        f"mode = {_quote(cfg.mode)}",
        f"branch = {_quote(cfg.branch)}",
        f"start_after_plan = {_flag(cfg.start_after_plan)}",
        f"bring_in_main = {_flag(cfg.bring_in_main)}",
        f"checks = {_list(cfg.checks)}",
        f"ci_ignore = {_list(cfg.ci_ignore)}",
        f"notes = {_quote(cfg.notes)}",
        f"version_files = {_list(cfg.version_files)}",
        f"after = {_list(cfg.after)}",
        "",
        "[targets]",
        f"github = {_flag(t.github)}",
        f"pypi = {_flag(t.pypi)}",
        f"npm = {_flag(t.npm)}",
        f"docker = {_flag(t.docker)}",
        f"homebrew = {_flag(t.homebrew)}",
        "",
        "[docker]",
        f"registries = {_list(t.docker_options.registries)}",
        f"image = {_quote(t.docker_options.image)}",
        "",
        "[homebrew]",
        f"tap = {_quote(t.homebrew_options.tap)}",
        f"formula = {_quote(t.homebrew_options.formula)}",
    ]
    for target in t.custom:
        lines += [
            "",
            "[[targets.custom]]",
            f"name = {_quote(target.name)}",
            f"run = {_quote(target.run)}",
            f"verify = {_quote(target.verify)}",
        ]
    s = cfg.security
    lines += [
        "",
        "[security]",
        f"secrets = {_quote(s.secrets)}",
        f"dependencies = {_quote(s.dependencies)}",
        f"contents = {_quote(s.contents)}",
        f"history_scanned = {_quote(s.history_scanned)}",
        f"pre_commit = {_flag(s.pre_commit)}",
        f"audit = {_quote(s.audit)}",
    ]
    return "\n".join(lines) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def save(root: Path, cfg: ReleaseConfig) -> None:
    if cfg.mode not in MODES:
        raise ConfigError(f"release.mode must be one of {', '.join(MODES)}, not {cfg.mode!r}")
    try:
        security_settings.validate(cfg.security)
    except security_settings.SettingsError as exc:
        raise ConfigError(str(exc)) from exc
    _write_atomic(Path(root) / CONFIG_PATH, render(cfg))


# --- detection ---------------------------------------------------------------


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def detect(root: Path) -> ReleaseConfig:
    root = Path(root)
    pyproject: dict = {}
    if (root / "pyproject.toml").is_file():
        try:
            pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            pyproject = {}
    package = _json(root / "package.json") if (root / "package.json").is_file() else None

    pypi = isinstance(pyproject.get("project"), dict)
    npm = package is not None and package.get("private") is not True
    docker = (root / "Dockerfile").is_file()

    checks: tuple[str, ...] = ()
    uv_project = pypi and ((root / "uv.lock").is_file() or "uv" in pyproject.get("tool", {}))
    scripts = package.get("scripts") if package else None
    if uv_project:
        checks = ("uv run pytest -q",)
    elif isinstance(scripts, dict) and "test" in scripts:
        checks = ("npm test",)

    return normalise(
        replace(
            ReleaseConfig(),
            checks=checks,
            targets=Targets(github=True, pypi=pypi, npm=npm, docker=docker),
        )
    )


def normalise(cfg: ReleaseConfig) -> ReleaseConfig:
    """Any ticked target means GitHub is ticked."""
    t = cfg.targets
    if t.github or not (t.pypi or t.npm or t.docker or t.homebrew or t.custom):
        return cfg
    return replace(cfg, targets=replace(t, github=True))


# --- pending setup files -----------------------------------------------------


def _pending_file(root: Path) -> Path:
    return Path(root) / PENDING_PATH


def _read_pending(root: Path) -> list[str]:
    try:
        data = json.loads(_pending_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, str)]


def _relative(root: Path, path: Path | str) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.relative_to(Path(root))
        except ValueError:
            pass
    return p.as_posix()


def add_pending(root: Path, path: Path | str) -> None:
    entries = _read_pending(root)
    rel = _relative(root, path)
    if rel not in entries:
        entries.append(rel)
    _write_atomic(_pending_file(root), json.dumps(entries, indent=2) + "\n")


def pending(root: Path) -> list[Path]:
    """Recorded setup files that still exist; missing ones are dropped."""
    root = Path(root)
    entries = _read_pending(root)
    kept = [e for e in entries if (root / e).exists()]
    if kept != entries:
        _write_atomic(_pending_file(root), json.dumps(kept, indent=2) + "\n")
    return [Path(e) for e in kept]


def clear_pending(root: Path) -> None:
    _pending_file(root).unlink(missing_ok=True)
