from __future__ import annotations

import json
from pathlib import Path

from whyline.console.file_pane import active_plan_file


def _write_config(root: Path, plan: str) -> None:
    dest = root / ".whyline" / "relay" / "config.toml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(f"plan = {json.dumps(plan)}\n", encoding="utf-8")


def _write_plan(root: Path, rel: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# plan\n", encoding="utf-8")
    return path


def _save_run(root: Path, plan: str) -> None:
    from whyline_relay import state

    state.save(
        root,
        state.RelayState(
            plan=plan,
            branch="relay/run",
            task_id="PANE-1",
            round=1,
            base_commit="",
            paused_reason="",
            log_path="",
        ),
    )


def test_run_plan_wins(tmp_path: Path) -> None:
    run = _write_plan(tmp_path, "plans/run.plan.md")
    _write_plan(tmp_path, "plans/configured.plan.md")
    _write_config(tmp_path, "plans/configured.plan.md")
    _save_run(tmp_path, "plans/run.plan.md")
    assert active_plan_file(tmp_path) == run


def test_missing_run_plan_does_not_fall_through(tmp_path: Path) -> None:
    _write_plan(tmp_path, "plans/configured.plan.md")
    _write_config(tmp_path, "plans/configured.plan.md")
    _save_run(tmp_path, "plans/missing.plan.md")
    assert active_plan_file(tmp_path) is None


def test_configured_plan_when_idle(tmp_path: Path) -> None:
    configured = _write_plan(tmp_path, "plans/configured.plan.md")
    _write_config(tmp_path, "plans/configured.plan.md")
    assert active_plan_file(tmp_path) == configured


def test_plan_outside_repo_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.plan.md"
    outside.write_text("# outside\n", encoding="utf-8")
    _write_config(tmp_path, str(outside))
    assert active_plan_file(tmp_path) is None

    link = tmp_path / "plans" / "link.plan.md"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    _write_config(tmp_path, "plans/link.plan.md")
    assert active_plan_file(tmp_path) is None


def test_no_plan(tmp_path: Path) -> None:
    assert active_plan_file(tmp_path) is None
