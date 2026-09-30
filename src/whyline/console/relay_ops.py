"""The console's calls into whyline-relay for planning and setup. Every
function returns plain data or raises; the Plan and Set up popups own all
presentation. whyline_relay is imported inside each function, like
adapters.py does, so the console imports without it."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace as dc_replace
from pathlib import Path

from whyline.console.adapters import BRAINSTORM_LABELS

_DEFAULT_ROLES = {"implementer": "codex", "tester": "claude", "reviewer": "claude"}


@dataclass(frozen=True)
class Draft:
    path: Path
    text: str
    drafted_by: str
    source: str  # "planner" | "brainstorm"
    topic: str = ""
    agent: str = ""


@dataclass(frozen=True)
class CheckLine:
    status: str
    message: str
    hint: str | None = None


def _settings(root: Path):
    from whyline_relay import config

    return config.load(root)


def plan_exists_error():
    from whyline_relay import planner

    return planner.PlanExists


def in_progress_error():
    from whyline_relay import planner

    return planner.PlanAlreadyInProgress


def validate_plan(text: str) -> list[str]:
    from whyline_relay import planner

    return planner.validate(text)


def save_pasted_plan(root: Path, text: str, *, replace: bool = False) -> Path:
    from whyline_relay import config, planner

    problems = planner.validate(text)
    if problems:
        raise ValueError("\n".join(problems))
    source = config.relay_dir(root) / "pasted-plan.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    try:
        return planner.approve(
            root, _settings(root), source, drafted_by="hand", replace=replace
        )
    finally:
        source.unlink(missing_ok=True)


def missing_references(root: Path, refs: list[str]) -> list[str]:
    missing = []
    for ref in refs:
        path = Path(ref).expanduser()
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            missing.append(ref)
    return missing


def draft_description(description: str, refs: list[str]) -> str:
    if not refs:
        return description
    listed = "\n".join(f"- {ref}" for ref in refs)
    return (
        f"{description}\n\nRead these reference documents before planning:\n{listed}"
    )


def _planner_draft(root: Path, path: Path) -> Draft:
    return Draft(
        path=path,
        text=path.read_text(encoding="utf-8"),
        drafted_by=_settings(root).planner.draft,
        source="planner",
    )


def draft_plan(root: Path, description: str, refs: list[str], *, progress) -> Draft:
    from whyline_relay import planner

    path = planner.draft(
        root, _settings(root), draft_description(description, refs), print_fn=progress
    )
    return _planner_draft(root, path)


def pending_draft(root: Path) -> str | None:
    from whyline_relay import planner

    return planner.pending_description(root)


def resume_draft(root: Path, *, progress) -> Draft:
    from whyline_relay import planner

    return _planner_draft(
        root, planner.resume_draft(root, _settings(root), print_fn=progress)
    )


def discard_draft(root: Path, draft: Draft | None) -> None:
    """Drops the planner's checkpoint; a brainstorm draft has none. The draft
    file itself stays on disk either way."""
    from whyline_relay import planner

    if draft is None or draft.source == "planner":
        planner.discard(root)


def _models(agent: str) -> list[tuple[str, str]]:
    return [(agent, BRAINSTORM_LABELS[agent])]


def revise_plan(root: Path, draft: Draft, feedback: str, *, progress) -> Draft:
    from whyline_relay import brainstorm, planner

    settings = _settings(root)
    if draft.source == "planner":
        planner.revise(root, settings, feedback, print_fn=progress)
    else:
        progress(f"{BRAINSTORM_LABELS[draft.agent]} is revising the plan")
        brainstorm.generate_plan_from_synthesis(
            root,
            settings,
            draft.agent,
            _models(draft.agent),
            draft.topic,
            feedback=feedback,
        )
    return dc_replace(draft, text=draft.path.read_text(encoding="utf-8"))


def approve_plan(root: Path, draft: Draft, *, replace: bool = False) -> Path:
    from whyline_relay import planner

    return planner.approve(
        root,
        _settings(root),
        draft.path,
        drafted_by=draft.drafted_by,
        replace=replace,
        clear_checkpoint=draft.source == "planner",
    )


def brainstorm_docs(root: Path) -> list[str]:
    folder = root / "docs" / "brainstorm"
    if not folder.is_dir():
        return []
    return sorted(path.stem for path in folder.glob("*.md"))


def plan_from_brainstorm(
    root: Path, topic: str, agent: str, *, progress, timeout_minutes: int | None = None
) -> Draft:
    from whyline_relay import brainstorm

    progress(f"{BRAINSTORM_LABELS[agent]} is turning the brainstorm into a plan")
    kwargs = {"timeout_seconds": timeout_minutes * 60} if timeout_minutes else {}
    path = brainstorm.generate_plan_from_synthesis(
        root, _settings(root), agent, _models(agent), topic, **kwargs
    )
    return Draft(
        path=path,
        text=path.read_text(encoding="utf-8"),
        drafted_by=f"brainstorm ({agent})",
        source="brainstorm",
        topic=topic,
        agent=agent,
    )


def relay_agents() -> list[str]:
    from whyline_relay import adapters as relay_adapters

    return sorted(relay_adapters.BUILTIN)


def current_roles(root: Path) -> dict:
    from whyline_relay import config

    agents = relay_agents()
    roles = dict(_DEFAULT_ROLES)
    backup: list[str] = []
    path = config.config_path(root)
    if path.exists():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            raw = {}
        for key in roles:
            value = (raw.get("roles") or {}).get(key)
            if value in agents:
                roles[key] = value
        backup = [
            name
            for name in (raw.get("backup") or {}).get("chain", [])
            if name in agents
        ]
    return {**roles, "backup": backup}


def save_roles(
    root: Path, implementer: str, tester: str, reviewer: str, backup: list[str]
) -> None:
    from whyline_relay import setup

    setup.write_roles(root, implementer, tester, reviewer, backup)


def run_checks(root: Path) -> list[CheckLine]:
    from whyline_relay import preflight

    return [CheckLine(c.status, c.message, c.hint) for c in preflight.run(root)]


def live_run(root: Path) -> str | None:
    from whyline_relay import running

    active = running.live(root)
    return None if active is None else f"{active.task}, {active.agent}"


def paused_run(root: Path) -> bool:
    from whyline_relay import state

    return state.load(root) is not None
