"""The console's calls into whyline-relay for planning and setup. Every
function returns plain data or raises; the Plan and Set up popups own all
presentation. whyline_relay is imported inside each function, like
adapters.py does, so the console imports without it."""
from __future__ import annotations

import re
import shutil
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, replace as dc_replace
from datetime import datetime
from pathlib import Path

from whyline.console.adapters import BRAINSTORM_LABELS

PLANS_DIR = "plans"
_MARKER = "<!-- whyline-plan v1"
_SOURCE_LABELS = {"planner": "draft"}
_DEFAULT_ROLES = {"implementer": "codex", "tester": "claude", "reviewer": "claude"}


@dataclass(frozen=True)
class PlanInfo:
    path: Path
    name: str
    source: str
    created: str
    done: int
    total: int


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


def plan_slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].rstrip("-")
    return slug or "plan"


def plan_path(root: Path, name: str) -> Path:
    return root / PLANS_DIR / f"{plan_slug(name)}.plan.md"


def with_marker(text: str, *, source: str, drafted_by: str, now: datetime | None = None) -> str:
    created = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    lines = text.splitlines()
    if lines and lines[0].startswith(_MARKER):
        lines = lines[1:]
    body = "\n".join(lines).strip("\n")
    return (
        f"{_MARKER} | source: {source} | drafted-by: {drafted_by} | "
        f"created: {created} -->\n{body}\n"
    )


def _marker_fields(first_line: str) -> dict | None:
    if not first_line.startswith(_MARKER):
        return None
    fields = {}
    for part in first_line.strip().removesuffix("-->").split("|")[1:]:
        key, _, value = part.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def _counts(text: str) -> tuple[int, int] | None:
    from whyline_relay import plan

    try:
        tasks = plan.parse(text)
    except plan.PlanError:
        return None
    if not tasks:
        return None
    return sum(task.checked for task in tasks), len(tasks)


def list_plans(root: Path) -> list[PlanInfo]:
    """Every saved plan, newest first; a valid legacy plan.md last."""
    found: list[PlanInfo] = []
    folder = root / PLANS_DIR
    for path in sorted(folder.glob("*.plan.md")) if folder.is_dir() else []:
        text = path.read_text(encoding="utf-8")
        fields = _marker_fields(text.split("\n", 1)[0])
        counts = _counts(text)
        if fields is None or counts is None:
            continue
        found.append(PlanInfo(
            path, path.name.removesuffix(".plan.md"), fields.get("source", ""),
            fields.get("created", ""), *counts,
        ))
    found.sort(key=lambda info: info.created, reverse=True)
    legacy = root / "plan.md"
    if legacy.is_file():
        counts = _counts(legacy.read_text(encoding="utf-8"))
        if counts:
            found.append(PlanInfo(legacy, "plan.md (older format)", "hand", "", *counts))
    return found


def _approve_marked(
    root: Path, text: str, *, name: str, source: str, drafted_by: str,
    replace: bool, clear_checkpoint: bool = False,
) -> Path:
    from whyline_relay import config, planner

    staged = config.relay_dir(root) / "approved-plan.md"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(with_marker(text, source=source, drafted_by=drafted_by), encoding="utf-8")
    try:
        return planner.approve(
            root, _settings(root), staged, drafted_by=drafted_by, replace=replace,
            clear_checkpoint=clear_checkpoint, target=plan_path(root, name),
        )
    finally:
        staged.unlink(missing_ok=True)


def configured_plan(root: Path) -> Path | None:
    try:
        return root / _settings(root).plan
    except Exception:  # unreadable config
        return None


def select_plan(root: Path, path: Path) -> None:
    from whyline_relay import setup

    setup.write_plan(root, path.relative_to(root).as_posix())


def planner_agents(root: Path) -> tuple[str, str]:
    try:
        planner_cfg = _settings(root).planner
    except Exception:
        return ("codex", "claude")
    return planner_cfg.draft, planner_cfg.review


def save_planner(root: Path, draft: str, review: str) -> None:
    from whyline_relay import setup

    setup.write_planner(root, draft, review)


def plan_questions_error():
    from whyline_relay import planner

    return planner.PlanQuestions


def answer_plan(root: Path, answers: str, *, progress) -> Draft:
    from whyline_relay import planner

    return _planner_draft(
        root, planner.answer(root, _settings(root), answers, print_fn=progress)
    )


def open_questions(text: str) -> list[str]:
    found: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip().lower() == "open questions"
            continue
        if inside:
            match = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.*\S)", line)
            if match:
                found.append(match.group(1))
    return found


def question_feedback(questions: Sequence[str], answers: str) -> str:
    asked = "\n".join(f"{n}. {q}" for n, q in enumerate(questions, 1))
    return (
        f"You listed these open questions:\n{asked}\nThe human answered:\n"
        f"{answers.strip()}\nRewrite the whole plan with these decisions, and "
        "remove the answered questions from ## Open questions."
    )


def save_pasted_plan(root: Path, text: str, name: str, *, replace: bool = False) -> Path:
    problems = validate_plan(text)
    if problems:
        raise ValueError("\n".join(problems))
    return _approve_marked(
        root, text, name=name, source="paste", drafted_by="hand", replace=replace
    )


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
    cfg = _settings(root).planner
    return Draft(
        path=path,
        text=path.read_text(encoding="utf-8"),
        drafted_by=f"{cfg.draft} (reviewed by {cfg.review})",
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


def approve_plan(root: Path, draft: Draft, name: str, *, replace: bool = False) -> Path:
    return _approve_marked(
        root,
        draft.path.read_text(encoding="utf-8"),
        name=name,
        source=_SOURCE_LABELS.get(draft.source, draft.source),
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


def relay_agents(root: Path | None = None, which=shutil.which) -> list[str]:
    """Agents the relay can run here that are installed: its built-ins plus
    the configured or recipe generic agents (grok, antigravity)."""
    from whyline_relay import adapters as relay_adapters, chat, config

    names = set(relay_adapters.BUILTIN)
    if root is not None:
        try:
            names |= set(config.load(root).agents)
        except Exception:  # an unreadable config: offer the built-ins only
            pass
    names = {chat.canonical_agent(name) for name in names}
    return sorted(name for name in names if which(chat.agent_binary(name)))


def current_roles(root: Path) -> dict:
    from whyline_relay import config

    # Every agent the relay knows, installed or not: Set up shows what the
    # config says, and the ready check is what flags a missing agent.
    agents = relay_agents(root, which=lambda binary: binary)
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


def antigravity_state(root: Path) -> str:
    from whyline_relay import antigravity

    if antigravity.is_trusted(root):
        return "trusted"
    return "declined" if antigravity.is_declined(root) else "ask"


def trust_antigravity(root: Path) -> None:
    from whyline_relay import antigravity

    antigravity.trust(root)
    antigravity.forget_decline(root)


def decline_antigravity(root: Path) -> None:
    from whyline_relay import antigravity

    antigravity.decline(root)


def forget_antigravity_decline(root: Path) -> None:
    from whyline_relay import antigravity

    antigravity.forget_decline(root)

