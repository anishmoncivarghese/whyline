"""Make, list and remove the git worktrees used for brainstorms and plans."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from whyline.paths import global_whyline_dir

KINDS = ("brainstorm", "plan")
MAX_NAME = 40


class WorktreeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    kind: str
    exists: bool


def _git(cwd: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        raise WorktreeError(f"git could not run: {exc}") from exc
    if proc.returncode != 0:
        raise WorktreeError(proc.stderr.strip() or proc.stdout.strip() or "git failed")
    return proc.stdout


def _base(root: Path) -> Path:
    return global_whyline_dir() / "worktrees" / root.resolve().name


def _clean_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    cleaned = cleaned[:MAX_NAME].strip("-")
    return cleaned or "work"


def _default_branch(root: Path) -> str:
    try:
        ref = _git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
        if ref:
            return ref
    except WorktreeError:
        pass
    for candidate in ("main", "master"):
        try:
            _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{candidate}")
            return candidate
        except WorktreeError:
            continue
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()


def _branch_exists(root: Path, branch: str) -> bool:
    try:
        _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        return True
    except WorktreeError:
        return False


def make(root: Path, kind: str, name: str) -> Path:
    if kind not in KINDS:
        raise WorktreeError(f"kind must be one of {', '.join(KINDS)}, not {kind!r}")
    base = _base(root)
    stem = _clean_name(name)
    candidate = stem
    n = 1
    while True:
        path = base / f"{kind}-{candidate}"
        if not path.exists() and not _branch_exists(root, f"{kind}/{candidate}"):
            break
        n += 1
        suffix = f"-{n}"
        candidate = f"{stem[: MAX_NAME - len(suffix)].strip('-')}{suffix}"
    base.mkdir(parents=True, exist_ok=True)
    _git(
        root,
        "worktree",
        "add",
        "-b",
        f"{kind}/{candidate}",
        str(path),
        _default_branch(root),
    )
    return path


def _entries(root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in _git(root, "worktree", "list", "--porcelain").splitlines():
        if not line:
            if current:
                entries.append(current)
            current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        entries.append(current)
    return entries


def list_all(root: Path) -> list[Worktree]:
    base = _base(root).resolve()
    found: list[Worktree] = []
    for entry in _entries(root):
        path = Path(entry.get("worktree", ""))
        try:
            rel = path.resolve().relative_to(base)
        except ValueError:
            continue
        if len(rel.parts) != 1:
            continue
        kind = rel.parts[0].split("-", 1)[0]
        if kind not in KINDS:
            continue
        branch = entry.get("branch", "").removeprefix("refs/heads/")
        found.append(Worktree(path, branch, kind, path.exists()))
    return found


def remove(root: Path, path: Path) -> None:
    target = path.resolve()
    if not any(w.path.resolve() == target for w in list_all(root)):
        raise WorktreeError(f"{path} is not a whyline worktree of this repo")
    if target.exists():
        if _git(target, "status", "--porcelain").strip():
            raise WorktreeError(
                f"{path} has uncommitted changes; commit or discard them first"
            )
        _git(root, "worktree", "remove", str(target))
    _git(root, "worktree", "prune")
