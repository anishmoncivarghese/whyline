"""Plan file resolution and the repository tree for the Files pane."""

from __future__ import annotations

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
