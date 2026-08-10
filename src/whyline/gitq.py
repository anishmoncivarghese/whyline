"""Read-only git queries. Git is authoritative; we only ask questions."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

UNCOMMITTED_SHA = "0" * 40


class GitUnavailable(RuntimeError):
    """git is missing, or the path is not inside a repository."""


@dataclass(frozen=True)
class Blame:
    sha: str
    author: str
    epoch: int
    committed: bool


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:  # git not installed
        raise GitUnavailable("git is not installed or not on PATH") from error
    if completed.returncode != 0:
        raise GitUnavailable(completed.stderr.strip() or "git command failed")
    return completed.stdout


def blame_line(root: Path, rel_path: str, line: int) -> Blame | None:
    """Blame exactly one line. Returns None when the line cannot be blamed."""
    try:
        output = _git(
            root, "blame", "-L", f"{line},{line}", "--porcelain", "--", rel_path
        )
    except GitUnavailable:
        return None
    if not output.strip():
        return None
    lines = output.splitlines()
    sha = lines[0].split()[0]
    author = ""
    epoch = 0
    for entry in lines[1:]:
        if entry.startswith("author "):
            author = entry[len("author ") :].strip()
        elif entry.startswith("author-time "):
            epoch = int(entry[len("author-time ") :].strip())
        elif entry.startswith("\t"):
            break
    return Blame(
        sha=sha,
        author=author,
        epoch=epoch,
        committed=sha != UNCOMMITTED_SHA,
    )


def commits_touching(root: Path, rel_path: str) -> list[tuple[str, int]]:
    """Every commit that touched this path, newest first, as (sha, epoch)."""
    output = _git(root, "log", "--format=%H %at", "--", rel_path)
    results: list[tuple[str, int]] = []
    for entry in output.splitlines():
        if not entry.strip():
            continue
        sha, _, epoch = entry.partition(" ")
        results.append((sha, int(epoch)))
    return results


def previous_commit_epoch(root: Path, rel_path: str, sha: str) -> int | None:
    """Epoch of the commit that touched this path immediately before `sha`."""
    history = commits_touching(root, rel_path)
    for index, (candidate, _) in enumerate(history):
        if candidate == sha:
            following = history[index + 1 :]
            return following[0][1] if following else None
    return None
