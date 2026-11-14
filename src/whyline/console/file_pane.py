"""Plan file resolution and the repository tree for the Files pane."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from whyline.console import relay_ops

try:
    from textual.widgets import DirectoryTree
except ImportError:
    DirectoryTree = object  # type: ignore[misc, assignment]


def active_plan_file(root: Path) -> Path | None:
    try:
        from whyline_relay import state as relay_state

        loaded = relay_state.load(root)
    except Exception:
        return None
    if loaded is not None:
        # A loaded run does not fall through to the configured plan.
        if not loaded.plan:
            return None
        return _repo_file(root, loaded.plan)
    try:
        configured = relay_ops.configured_plan(root)
    except Exception:
        return None
    if configured is None:
        return None
    return _repo_file(root, configured)


def owning_set(root: Path, docs: Path | None = None) -> tuple[Path, str] | None:
    """The (docs checkout, slug) of the document set that owns the active plan, if any.

    Looks in `docs` when given, else in the repository and its default-branch
    worktree; never creates a worktree."""
    plan = active_plan_file(root)
    if plan is None or not plan.name.endswith(".plan.md"):
        return None
    slug = plan.name.removesuffix(".plan.md")
    candidates: list[Path] = [docs] if docs is not None else [root]
    if docs is None:
        try:
            from whyline import worktrees

            extra = worktrees.default_branch_worktree(root)
        except Exception:
            extra = None
        if extra is not None:
            candidates.append(extra)
    from whyline.sdlc import docset

    for candidate in candidates:
        try:
            docset.load(candidate, slug)
        except docset.DocSetError:
            continue
        return candidate, slug
    return None


# Only the top of a plan names its design: the header comment's `spec:` field,
# or a "Spec:"/"Design:" line before the tasks.
_LINK_LINES = 30
_HEADER_SPEC = re.compile(r"\|\s*spec:\s*([^|\s][^|]*?)\s*(?:\||-->)")
_LINE_SPEC = re.compile(r"\b(?:Spec|Design):\s*`([^`]+\.md)`")


def linked_design(root: Path) -> Path | None:
    """The design document the active plan names, when it is a file in the repository."""
    plan = active_plan_file(root)
    if plan is None:
        return None
    try:
        with plan.open(encoding="utf-8") as handle:
            head = [line for _, line in zip(range(_LINK_LINES), handle)]
    except (OSError, UnicodeDecodeError):
        return None
    for line in head:
        found = _HEADER_SPEC.search(line) if line.lstrip().startswith("<!--") else None
        found = found or _LINE_SPEC.search(line)
        if found:
            linked = _repo_file(root, found.group(1).strip())
            if linked is not None:
                return linked
    return None


def _repo_file(root: Path, candidate: str | Path) -> Path | None:
    try:
        path = Path(candidate)
        if not path.is_absolute():
            path = root / path
        resolved = path.resolve()
        root_resolved = root.resolve()
        if not resolved.is_relative_to(root_resolved):
            return None
        if not resolved.is_file():
            return None
        return root / resolved.relative_to(root_resolved)
    except Exception:
        return None


class RepoTree(DirectoryTree):
    """Repository tree. Hides ``.git`` and anything that resolves outside the root."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        try:
            root = Path(self.path).expanduser().resolve()
        except Exception:
            return []
        kept: list[Path] = []
        for path in paths:
            if path.name == ".git":
                continue
            try:
                resolved = path.resolve()
            except Exception:
                continue
            if not resolved.is_relative_to(root):
                continue
            kept.append(path)
        return kept
