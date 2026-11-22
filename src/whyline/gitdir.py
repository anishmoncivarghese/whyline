"""Where a checkout keeps its git data, including in a git worktree.

In a plain checkout that is ``<root>/.git``. In a worktree ``<root>/.git`` is a
file reading ``gitdir: <path>``, and the data lives at that path. Reading the
file (rather than running git) keeps this cheap and lets tests that fake git
still use it.
"""

from __future__ import annotations

from pathlib import Path


def git_dir(root: Path | str) -> Path:
    """The checkout's own git folder; ``<root>/.git`` when it can't tell."""
    root = Path(root)
    dot_git = root / ".git"
    if dot_git.is_file():
        try:
            text = dot_git.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return dot_git
        for line in text.splitlines():
            if line.startswith("gitdir:"):
                target = Path(line.removeprefix("gitdir:").strip())
                return target if target.is_absolute() else root / target
    return dot_git


def release_dir(root: Path | str) -> Path:
    """Where Release keeps its state, log, pending list and scratch clones."""
    return git_dir(root) / "whyline-release"
