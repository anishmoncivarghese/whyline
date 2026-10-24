"""Resolve the plan file the Files pane should show."""

from __future__ import annotations

from pathlib import Path

from whyline.console import relay_ops


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
