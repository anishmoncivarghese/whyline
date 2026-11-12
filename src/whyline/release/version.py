"""Read the project version, bump it, and write it to the files that hold it."""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable
from pathlib import Path

from whyline.release.config import ReleaseConfig

BUMPS = ("patch", "minor", "major")
_PLAIN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_VALID = re.compile(r"^\d+\.\d+\.\d+(?:rc\d+|-rc\.\d+)?$")
_DUNDER = re.compile(r"""^(__version__\s*=\s*)(["'])(?P<v>[^"']*)\2""")
_JSON_VERSION = re.compile(r'^(\s*"version"\s*:\s*")(?P<v>[^"]*)(")')
_TOML_VERSION = re.compile(r"""^(version\s*=\s*)(["'])(?P<v>[^"']*)\2""")

Run = Callable[..., object]


class VersionError(ValueError):
    """No version could be read, or a version string is not acceptable."""


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _pyproject_version(root: Path) -> str:
    project = _read_toml(root / "pyproject.toml").get("project", {})
    value = project.get("version") if isinstance(project, dict) else None
    return value if isinstance(value, str) else ""


def _package_json_version(root: Path) -> str:
    value = _read_json(root / "package.json").get("version")
    return value if isinstance(value, str) else ""


def current(root: Path, cfg: ReleaseConfig) -> str:
    version = _pyproject_version(root) or _package_json_version(root)
    if not version:
        raise VersionError(
            "No version found; add one to pyproject.toml or package.json, "
            "or list a file in version_files"
        )
    return version


def released(root: Path, version: str, *, run: Run) -> bool:
    """Whether tag v<version> exists locally or on origin.

    When git cannot say (no repository, no network) the version counts as released,
    so callers fall back to offering the next bump.
    """
    tag = f"refs/tags/v{version}"
    try:
        local = run(["git", "rev-parse", "-q", "--verify", tag], cwd=root)
        if local.returncode == 0:
            return True
        remote = run(["git", "ls-remote", "--tags", "origin", tag], cwd=root)
    except Exception:  # noqa: BLE001 - git missing or timed out: assume released
        return True
    if remote.returncode != 0:
        return True
    return bool(remote.stdout.strip())


def validate(text: str) -> str:
    if not _VALID.match(text):
        raise VersionError(f"{text!r} is not a version; use X.Y.Z or X.Y.ZrcN")
    return text


def bump(version: str, kind: str) -> str:
    if kind not in BUMPS:
        raise VersionError(f"Unknown bump {kind!r}; use patch, minor or major")
    match = _PLAIN.match(version)
    if not match:
        raise VersionError(
            f"Cannot bump {version!r}: it has a pre-release suffix; "
            "give the new version explicitly"
        )
    major, minor, patch = (int(part) for part in match.groups())
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _package_init(root: Path) -> Path | None:
    project = _read_toml(root / "pyproject.toml").get("project", {})
    name = project.get("name") if isinstance(project, dict) else None
    if not isinstance(name, str) or not name:
        return None
    package = name.replace("-", "_")
    for base in (root / "src", root):
        init = base / package / "__init__.py"
        if init.is_file() and any(
            _DUNDER.match(line) for line in init.read_text(encoding="utf-8").splitlines()
        ):
            return init
    return None


def files_to_change(root: Path, cfg: ReleaseConfig) -> list[Path]:
    found: list[Path] = []
    if _pyproject_version(root):
        found.append(root / "pyproject.toml")
    init = _package_init(root)
    if init is not None:
        found.append(init)
    if _package_json_version(root):
        found.append(root / "package.json")
    found.extend(root / name for name in cfg.version_files)
    unique: list[Path] = []
    for path in found:
        if path not in unique:
            unique.append(path)
    return unique


def _replace_line(path: Path, text: str, old: str, new: str, root: Path) -> str:
    """Swap `old` for `new` on the one line that holds the version, nothing else."""
    lines = text.splitlines(keepends=True)
    name = path.name
    in_project = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if name == "pyproject.toml":
            if stripped.startswith("["):
                in_project = stripped == "[project]"
                continue
            match = _TOML_VERSION.match(line) if in_project else None
        elif name == "package.json":
            match = _JSON_VERSION.match(line)
        elif name == "__init__.py":
            match = _DUNDER.match(line)
        else:
            if old in line:
                lines[index] = line.replace(old, new, 1)
                return "".join(lines)
            continue
        if match and match.group("v") == old:
            start, end = match.span("v")
            lines[index] = line[:start] + new + line[end:]
            return "".join(lines)
    raise VersionError(f"{path.relative_to(root)} has no line with version {old}")


def write(root: Path, cfg: ReleaseConfig, new: str, *, run: Run) -> list[Path]:
    old = current(root, cfg)
    updates: dict[Path, str] = {}
    for path in files_to_change(root, cfg):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise VersionError(f"Cannot read {path.relative_to(root)}: {exc}") from exc
        updates[path] = _replace_line(path, text, old, new, root)
    for path, text in updates.items():
        path.write_text(text, encoding="utf-8")
    changed = list(updates)
    if (root / "uv.lock").is_file():
        run(["uv", "lock"], cwd=root)
        changed.append(root / "uv.lock")
    if (root / "package-lock.json").is_file():
        run(["npm", "install", "--package-lock-only"], cwd=root)
        changed.append(root / "package-lock.json")
    return changed
