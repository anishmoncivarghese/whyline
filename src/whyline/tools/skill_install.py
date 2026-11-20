"""Check, install and update a skill found in a skill source.

Nothing here runs git except to read a clone's commit; the clone is made by
``skill_sources.fetch``. A skill installs to ~/.whyline/skills/<name> with a
``source.toml`` saying where it came from, so it can be diffed and updated."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from whyline.tools import skill_sources, skills
from whyline.tools.skill_sources import Entry, Source

MAX_TOTAL = 2 * 1024 * 1024
NO_LICENCE = "no licence stated"
SCRIPT_SUFFIXES = (".py", ".sh", ".js", ".rb", ".ps1")

_IGNORE = re.compile(
    r"ignore (all )?(previous|prior|above) instructions|disregard your|you are now", re.IGNORECASE)
_DOWNLOADS = re.compile(
    r"(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba|z)?sh\b|\bpip3? install\b|\bnpx |bash -c\s+[\"']?\$\(",
    re.IGNORECASE)
_ENCODED = re.compile(r"[A-Za-z0-9+/=]{400,}")


@dataclass(frozen=True)
class Preview:
    skill_md: str
    files: tuple[tuple[str, int], ...]
    size: int
    licence: str
    commit: str
    warnings: tuple[str, ...]


def _dir() -> Path:
    return Path.home() / ".whyline" / "skills"


def _files(folder: Path) -> list[Path]:
    found: list[Path] = []
    for here, dirs, names in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        found.extend(Path(here) / n for n in sorted(names))
    return found


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def check(folder: Path) -> list[str]:
    """Plain warnings about a skill folder. None of them blocks an install."""
    from whyline.security import secrets
    from whyline.security.rules import load_rules

    folder = Path(folder)
    scripts: list[str] = []
    ignore = downloads = encoded = False
    rules_found: list[str] = []
    rules = load_rules()
    for path in _files(folder):
        if path.is_symlink():
            continue
        rel = path.relative_to(folder).as_posix()
        try:
            executable = bool(path.stat().st_mode & 0o111)
        except OSError:
            continue
        if executable or path.suffix.lower() in SCRIPT_SUFFIXES:
            scripts.append(rel)
        text = _text(path)
        if text is None:
            continue
        ignore = ignore or bool(_IGNORE.search(text))
        downloads = downloads or bool(_DOWNLOADS.search(text))
        encoded = encoded or bool(_ENCODED.search(text))
        for finding in secrets.scan_text(text, rel, rules):
            if finding.rule not in rules_found:
                rules_found.append(finding.rule)
    warnings: list[str] = []
    if scripts:
        warnings.append(f"contains scripts: {', '.join(scripts)}")
    if ignore:
        warnings.append("tells the agent to ignore its instructions")
    if downloads:
        warnings.append("downloads and runs something")
    if encoded:
        warnings.append("long encoded text")
    warnings.extend(f"looks like a secret: {rule}" for rule in rules_found)
    return warnings


def _source(entry: Entry) -> Source:
    for source in skill_sources.load():
        if source.name == entry.source:
            return source
    raise ValueError(f"There is no source called {entry.source}.")


def _folder(source: Source, path: str) -> Path:
    base = skill_sources.clone_dir(source)
    folder = base / path
    if not path or folder.is_symlink() or not folder.is_dir():
        raise ValueError(f"{path or 'that skill'} is not in the fetched copy of {source.name}. Fetch it first.")
    if not folder.resolve().is_relative_to(base.resolve()):
        raise ValueError("That skill is outside its source.")
    return folder


def _commit(source: Source, run: Callable) -> str:
    return skill_sources._git(run, ["-C", str(skill_sources.clone_dir(source)), "rev-parse", "HEAD"]).strip()


def _verify(folder: Path) -> None:
    """Refuse what must not be copied: links, escaping paths, big folders."""
    root = folder.resolve()
    total = 0
    for here, dirs, names in os.walk(folder, followlinks=False):
        for n in [*dirs, *names]:
            p = Path(here) / n
            if p.is_symlink():
                raise ValueError(f"{p.relative_to(folder).as_posix()} is a symlink; a skill with links is refused.")
            if not p.resolve().is_relative_to(root):
                raise ValueError(f"{p.relative_to(folder).as_posix()} leaves the skill folder.")
        for n in names:
            total += (Path(here) / n).stat().st_size
    if total > MAX_TOTAL:
        raise ValueError(f"The skill is {total} bytes; the limit is {MAX_TOTAL}.")
    manifest = folder / "SKILL.md"
    if not manifest.is_file():
        raise ValueError("The folder has no SKILL.md.")
    if manifest.stat().st_size > skills.SKILL_LIMIT:
        raise ValueError(f"SKILL.md is over {skills.SKILL_LIMIT} bytes.")


def _rename(text: str, name: str) -> str:
    """``text`` with the front matter's name set to ``name``."""
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                break
            if line.partition(":")[0].strip() == "name":
                lines[i] = f"name: {name}"
                return "\n".join(lines)
        else:
            return text
        lines.insert(1, f"name: {name}")
        return "\n".join(lines)
    return f"---\nname: {name}\n---\n{text}"


def _copy(folder: Path, target: Path, name: str) -> None:
    shutil.copytree(folder, target, ignore=shutil.ignore_patterns(".git"), symlinks=True)
    manifest = target / "SKILL.md"
    manifest.write_text(_rename(manifest.read_text(encoding="utf-8"), name), encoding="utf-8")


def preview(entry: Entry, *, run: Callable = subprocess.run) -> Preview:
    source = _source(entry)
    folder = _folder(source, entry.path)
    files = [(p.relative_to(folder).as_posix(), p.stat().st_size) for p in _files(folder)]
    return Preview(
        skill_md=_text(folder / "SKILL.md") or "",
        files=tuple(files),
        size=sum(s for _, s in files),
        licence=source.licence or NO_LICENCE,
        commit=_commit(source, run),
        warnings=tuple(check(folder)),
    )


def _write_source(target: Path, source: Source, path: str, commit: str, installed: str) -> None:
    lines = [
        f"source = {json.dumps(source.name)}",
        f"url = {json.dumps(source.url)}",
        f"path = {json.dumps(path)}",
        f"commit = {json.dumps(commit)}",
        f"licence = {json.dumps(source.licence or NO_LICENCE)}",
        f"installed = {json.dumps(installed)}",
    ]
    (target / "source.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def install(entry: Entry, *, name: str | None = None, run: Callable = subprocess.run) -> skills.Skill:
    name = name or entry.name
    if not skills.valid_name(name):
        raise ValueError("A skill name is lowercase letters, digits, - and _.")
    source = _source(entry)
    folder = _folder(source, entry.path)
    _verify(folder)
    target = _dir() / name
    if target.exists() or target.is_symlink():
        raise ValueError(f"A skill named {name} is already installed. Choose another name.")
    commit = _commit(source, run)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{name}.installing")
    shutil.rmtree(temp, ignore_errors=True)
    try:
        _copy(folder, temp, name)
        _write_source(temp, source, entry.path, commit, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        os.replace(temp, target)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return skills._load("whyline", target)


def source_of(name: str) -> dict | None:
    """What ``source.toml`` says about an installed skill, or None when it has none."""
    try:
        return tomllib.loads((_dir() / name / "source.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None


def _origin(name: str) -> tuple[Path, dict, Source, Path]:
    installed = _dir() / name
    info = source_of(name)
    if info is None:
        raise ValueError(f"{name} was not installed from a source, so it has no update.")
    for source in skill_sources.load():
        if source.name == info.get("source"):
            return installed, info, source, _folder(source, str(info.get("path", "")))
    raise ValueError(f"The source {info.get('source')} is gone.")


def update_diff(name: str) -> str:
    """A unified diff of every text file, installed against the fetched copy ("" when the same)."""
    installed, _, _, fresh = _origin(name)
    old = {p.relative_to(installed).as_posix(): p for p in _files(installed)}
    new = {p.relative_to(fresh).as_posix(): p for p in _files(fresh)}
    old.pop("source.toml", None)
    out: list[str] = []
    for rel in sorted(set(old) | set(new)):
        a = _text(old[rel]) if rel in old else ""
        b = _text(new[rel]) if rel in new else ""
        if a is None or b is None:
            if rel in old and rel in new and old[rel].read_bytes() == new[rel].read_bytes():
                continue
            out.append(f"Binary file {rel} differs\n")
            continue
        if rel == "SKILL.md":
            b = _rename(b, name)
        out.extend(difflib.unified_diff(
            a.splitlines(keepends=True), b.splitlines(keepends=True),
            fromfile=f"installed/{rel}" if rel in old else "/dev/null",
            tofile=f"source/{rel}" if rel in new else "/dev/null"))
    return "".join(out)


def update(name: str, *, run: Callable = subprocess.run) -> skills.Skill:
    """Replace the installed folder with the fetched copy and record its commit."""
    installed, info, source, fresh = _origin(name)
    _verify(fresh)
    commit = _commit(source, run)
    temp = installed.with_name(f".{name}.updating")
    shutil.rmtree(temp, ignore_errors=True)
    try:
        _copy(fresh, temp, name)
        _write_source(temp, source, str(info.get("path", "")), commit, str(info.get("installed", "")))
        shutil.rmtree(installed)
        os.replace(temp, installed)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return skills._load("whyline", installed)


def files_hash(name: str) -> str | None:
    """sha256 of an installed skill's files, or None when it has no ``source.toml``."""
    folder = _dir() / name
    if not (folder / "source.toml").is_file():
        return None
    digest = hashlib.sha256()
    for path in _files(folder):
        digest.update(path.relative_to(folder).as_posix().encode("utf-8") + b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            pass
        digest.update(b"\0")
    return digest.hexdigest()
