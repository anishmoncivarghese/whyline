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


def _require_usable_repo(root: Path) -> None:
    """Raise GitUnavailable if git is missing or `root` is not a repository.

    Called only on blame_line's failure path. A blame failure is ambiguous on
    its own — it is the expected shape of "untracked file" and "line past
    end of file" (benign, should become None), but it is also the shape of
    "git binary missing" and "corrupted repository" (infrastructure failure,
    must NOT become None). Task 5 treats blame_line's None as "no reasoning
    recorded for this line"; if a broken git install silently produced None
    for every line, explain would confidently report nothing everywhere it
    looked, which is exactly the false negative spec S7 rules out. Probing
    with `rev-parse --git-dir` distinguishes the two: it fails the same way
    the blame call would for missing-git or not-a-repo, but succeeds for the
    benign cases, so it re-raises only when the failure was real.
    """
    _git(root, "rev-parse", "--git-dir")


def blame_line(root: Path, rel_path: str, line: int) -> Blame | None:
    """Blame exactly one line. Returns None when the line cannot be blamed."""
    try:
        output = _git(
            root, "blame", "-L", f"{line},{line}", "--porcelain", "--", rel_path
        )
    except GitUnavailable:
        _require_usable_repo(root)
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
    # --follow requires exactly one pathspec, which `rel_path` always is here.
    # Without it, history stops at the most recent rename, and
    # previous_commit_epoch would then see a renamed file as brand new.
    output = _git(root, "log", "--follow", "--format=%H %at", "--", rel_path)
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


def head_commit(root: Path) -> str:
    """Current full commit id, or an empty string for an unborn repository."""
    try:
        return _git(root, "rev-parse", "HEAD").strip()
    except GitUnavailable:
        _require_usable_repo(root)
        return ""


def branch_name(root: Path) -> str:
    """Current branch, or an empty string for detached/unborn HEAD."""
    try:
        return _git(root, "branch", "--show-current").strip()
    except GitUnavailable:
        _require_usable_repo(root)
        return ""


def changed_paths(root: Path) -> list[str]:
    """Tracked and untracked changed paths, excluding local Whyline state."""
    output = _git(
        root, "status", "--porcelain=v1", "-z", "--untracked-files=all"
    )
    local_state = {
        ".whyline/active-handoff.json",
        ".whyline/index.db",
        ".whyline/ledger.jsonl",
        ".whyline/ownership.json",
        ".whyline/ownership.json.lock",
        ".whyline/readside.log",
    }
    parts = output.split("\0")
    found: set[str] = set()
    index = 0
    while index < len(parts):
        raw = parts[index]
        index += 1
        if not raw:
            continue
        status = raw[:2]
        path = raw[3:]
        if "R" in status or "C" in status:
            # In porcelain v1 -z, the destination is first and the original
            # path follows as a second NUL-delimited field.
            index += 1
        if path and path not in local_state and not path.endswith(".bak"):
            found.add(path)
    return sorted(found)
