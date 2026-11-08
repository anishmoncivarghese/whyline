"""Where SDLC documents live: the default-branch checkout, never a plan branch."""

from __future__ import annotations

import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path

from whyline import worktrees
from whyline.worktrees import WorktreeError


def _current_branch(path: Path) -> str:
    return worktrees._git(path, "rev-parse", "--abbrev-ref", "HEAD").strip()


def docs_root(root: Path) -> Path:
    default = worktrees._default_branch(root).removeprefix("origin/")
    if _current_branch(root) == default:
        return root
    existing = worktrees.default_branch_worktree(root)
    if existing is not None:
        return existing
    path = worktrees._base(root) / "docs"
    path.parent.mkdir(parents=True, exist_ok=True)
    worktrees._git(root, "worktree", "add", str(path), default)
    return path


def _dirty(docs: Path, paths: list[str]) -> list[str]:
    out = worktrees._git(docs, "status", "--porcelain", "--", *paths)
    return [line[3:].strip().strip('"') for line in out.splitlines() if line.strip()]


def docs_commit(
    docs: Path,
    paths: Iterable[str],
    message: str,
    written: Mapping[str, str] | None = None,
) -> bool:
    """Commit only `paths` in `docs`; never pushes.

    `written` maps path -> the exact text whyline wrote there. A dirty path is
    accepted only when its content still equals that text; any other
    uncommitted change is refused. Returns False when nothing changed.
    """
    rels = [str(p) for p in paths]
    if not rels:
        return False
    written = written or {}
    staged = worktrees._git(docs, "diff", "--cached", "--name-only", "--", *rels).split("\n")
    staged = [s.strip() for s in staged if s.strip()]
    if staged:
        raise WorktreeError(
            "These files have staged changes whyline did not write: "
            + ", ".join(staged)
            + ". Commit or unstage them, then try again."
        )
    dirty = _dirty(docs, rels)
    foreign = []
    for rel in dirty:
        target = docs / rel
        expected = written.get(rel)
        if expected is None or not target.is_file() or target.read_text() != expected:
            foreign.append(rel)
    if foreign:
        raise WorktreeError(
            "These files have changes whyline did not write: "
            + ", ".join(foreign)
            + ". Commit or discard them, then try again."
        )
    if not dirty:
        return False
    worktrees._git(docs, "add", "--", *rels)
    worktrees._git(docs, "commit", "-m", message, "--", *rels)
    return True


def copy_plan_to(root: Path, docs: Path, slug: str) -> bool:
    """Copy the plan and tests files from `docs` into `root` and commit them."""
    if root.resolve() == docs.resolve():
        return False
    rels = [f"plans/{slug}.plan.md", f"plans/{slug}.tests.md"]
    written: dict[str, str] = {}
    for rel in rels:
        src = docs / rel
        if not src.is_file():
            continue
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        written[rel] = src.read_text()
    if not written:
        return False
    return docs_commit(root, list(written), f"docs: copy {slug} plan", written)
