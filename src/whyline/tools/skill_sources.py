"""Places to find skills: shallow clones of git repositories under ~/.whyline/skill-sources.

The user's own sources, and which built-ins are turned off, live in
~/.whyline/skill-sources.toml. ``fetch`` is the only function that runs git, and
only when asked; ``load``, ``index`` and ``search`` read what is already on disk."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

from whyline.tools import skills

_NAME = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
MAX_MANIFEST = 1_000_000
MAX_RESULTS = 200
FETCH_TIMEOUT = 120


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    path: str = ""  # folder inside the repository holding the skill folders
    branch: str = ""
    licence: str = ""
    kind: str = "skills"  # "skills" or "directory" (only opened in the browser)
    builtin: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class Entry:
    source: str
    name: str
    description: str
    path: str  # the skill folder, relative to the repository
    size: int
    files: tuple[str, ...]


BUILTIN: tuple[Source, ...] = (
    Source("anthropic", "https://github.com/anthropics/skills", "skills", builtin=True),
    Source("agentic", "https://github.com/sickn33/agentic-awesome-skills", "skills",
           licence="MIT, text CC BY 4.0", builtin=True),
    Source("composio", "https://github.com/ComposioHQ/awesome-claude-skills", "", builtin=True),
    Source("voltagent", "https://github.com/VoltAgent/awesome-agent-skills", "",
           kind="directory", builtin=True),
    Source("heilcheng", "https://github.com/heilcheng/awesome-agent-skills", "",
           kind="directory", builtin=True),
)


def _home() -> Path:
    return Path.home() / ".whyline"


def _file() -> Path:
    return _home() / "skill-sources.toml"


def _root() -> Path:
    return _home() / "skill-sources"


def clone_dir(source: Source) -> Path:
    return _root() / source.name


def _read() -> dict:
    try:
        return tomllib.loads(_file().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


def load() -> list[Source]:
    """Built-ins (with any turned off marked) followed by the user's sources."""
    raw = _read()
    off = {str(n) for n in raw.get("disabled", [])}
    found = [replace(b, enabled=b.name not in off) for b in BUILTIN]
    taken = {b.name for b in BUILTIN}
    for name, entry in raw.get("sources", {}).items():
        if name in taken or not isinstance(entry, dict):
            continue
        try:
            _check(name, str(entry.get("url", "")), str(entry.get("path", "")),
                   str(entry.get("branch", "")))
        except ValueError:
            continue
        found.append(Source(name, str(entry["url"]), str(entry.get("path", "")),
                            str(entry.get("branch", ""))))
    return found


def _check(name: str, url: str, path: str, branch: str) -> None:
    if not _NAME.match(name):
        raise ValueError("a source name is lowercase letters, digits and hyphens, starting with a letter")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.path.strip("/") == "":
        raise ValueError("a source URL must be https:// with a host and a path")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError("a source URL cannot hold credentials, a query or a fragment")
    if any(c.isspace() or c in "\\" for c in url):
        raise ValueError("a source URL cannot hold spaces or backslashes")
    folder = path.strip("/")
    if path.startswith("/") or ".." in folder.split("/") or "\\" in path:
        raise ValueError("a source path is a folder inside the repository")
    if branch and not _BRANCH.match(branch):
        raise ValueError("that is not a branch name")


def _write(sources: list[Source]) -> None:
    lines = []
    off = sorted(s.name for s in sources if s.builtin and not s.enabled)
    lines.append(f"disabled = {json.dumps(off)}")
    lines.append("")
    for s in sources:
        if s.builtin:
            continue
        lines.append(f"[sources.{s.name}]")
        lines.append(f"url = {json.dumps(s.url)}")
        lines.append(f"path = {json.dumps(s.path)}")
        lines.append(f"branch = {json.dumps(s.branch)}")
        lines.append("")
    target = _file()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    os.replace(tmp, target)


def add(name: str, url: str, path: str = "", branch: str = "") -> Source:
    _check(name, url, path, branch)
    current = load()
    if any(s.name == name for s in current):
        raise ValueError(f"there is already a source called {name}")
    source = Source(name, url, path.strip("/"), branch)
    _write([*current, source])
    return source


def remove(name: str) -> bool:
    """Forget one of the user's sources (its clone is deleted by the caller, if wanted)."""
    current = load()
    for s in current:
        if s.name == name:
            if s.builtin:
                raise ValueError("a built-in source can be turned off, not removed")
            _write([x for x in current if x.name != name])
            return True
    return False


def set_enabled(name: str, enabled: bool) -> None:
    """Turn a built-in on or off."""
    current = load()
    for s in current:
        if s.name == name and s.builtin:
            _write([replace(x, enabled=enabled) if x.name == name else x for x in current])
            return
    raise ValueError(f"{name} is not a built-in source")


def _stamp(source: Source) -> Path:
    return _root() / f"{source.name}.fetched"


def fetched(source: Source) -> str | None:
    """The time of the last fetch (UTC, ISO 8601), or None if never fetched."""
    try:
        text = _stamp(source).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text or None


def _git(run: Callable, args: list[str]) -> str:
    argv = ["git", "-c", "core.hooksPath=/dev/null", *args]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    done = run(argv, capture_output=True, text=True, timeout=FETCH_TIMEOUT, env=env)
    if done.returncode != 0:
        message = (done.stderr or done.stdout or "").strip().splitlines()
        raise RuntimeError(f"git {args[0]} failed: {message[-1] if message else done.returncode}")
    return done.stdout or ""


def fetch(source: Source, *, run: Callable = subprocess.run) -> str:
    """Make or update the shallow clone of ``source`` and return its commit."""
    _check(source.name, source.url, source.path, source.branch)
    dest = clone_dir(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    branch = ["--branch", source.branch] if source.branch else []
    if (dest / ".git").is_dir():
        _git(run, ["-C", str(dest), "fetch", "--depth", "1", "origin", source.branch or "HEAD"])
        _git(run, ["-C", str(dest), "reset", "--hard", "FETCH_HEAD"])
    else:
        _git(run, ["clone", "--depth", "1", *branch, "--", source.url, str(dest)])
    commit = _git(run, ["-C", str(dest), "rev-parse", "HEAD"]).strip()
    _stamp(source).write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), encoding="utf-8")
    return commit


def _walk(folder: Path) -> list[Path]:
    """Regular files under ``folder``, never following a symlink."""
    found: list[Path] = []
    for here, dirs, names in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != ".git" and not (Path(here) / d).is_symlink())
        for n in sorted(names):
            p = Path(here) / n
            if not p.is_symlink() and p.is_file():
                found.append(p)
    return found


def index(source: Source) -> list[Entry]:
    """The skills in the clone of ``source`` (nothing if it was never fetched)."""
    if source.kind != "skills":
        return []
    base = clone_dir(source)
    top = base / source.path if source.path else base
    if not base.is_dir() or base.is_symlink() or top.is_symlink() or not top.is_dir():
        return []
    try:
        if not top.resolve().is_relative_to(base.resolve()):
            return []
        children = sorted(top.iterdir())
    except OSError:
        return []
    found: list[Entry] = []
    for folder in children:
        if folder.name == ".git" or folder.is_symlink() or not folder.is_dir():
            continue
        manifest = folder / "SKILL.md"
        try:
            if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > MAX_MANIFEST:
                continue
            meta = skills.parse_front_matter(manifest.read_text(encoding="utf-8"))
            files = _walk(folder)
            size = sum(p.stat().st_size for p in files)
        except (OSError, UnicodeDecodeError):
            continue
        found.append(Entry(
            source=source.name,
            name=meta.get("name") or folder.name,
            description=meta.get("description", ""),
            path=folder.relative_to(base).as_posix(),
            size=size,
            files=tuple(p.relative_to(folder).as_posix() for p in files),
        ))
    return found


def search(text: str) -> list[Entry]:
    """Skills from every fetched, enabled source; every word must be in the name or description."""
    words = text.lower().split()
    if not words:
        return []
    ranked: list[tuple[int, str, str, Entry]] = []
    for source in load():
        if not source.enabled or fetched(source) is None:
            continue
        for entry in index(source):
            name = entry.name.lower()
            both = f"{name} {entry.description.lower()}"
            if all(w in both for w in words):
                rank = 0 if all(w in name for w in words) else 1
                ranked.append((rank, name, source.name, entry))
    ranked.sort(key=lambda r: r[:3])
    return [r[3] for r in ranked[:MAX_RESULTS]]
