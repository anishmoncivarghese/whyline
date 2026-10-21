"""The console's calls into whyline-relay for planning and setup. Every
function returns plain data or raises; the Plan and Set up popups own all
presentation. whyline_relay is imported inside each function, like
adapters.py does, so the console imports without it."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
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
    spec: str = ""


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
    """One check row. `group` is empty for Set up and set by `candidate_checks`."""

    status: str
    message: str
    hint: str | None = None
    group: str = ""


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


def with_marker(
    text: str,
    *,
    source: str,
    drafted_by: str,
    spec: str = "",
    now: datetime | None = None,
) -> str:
    created = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    lines = text.splitlines()
    if lines and lines[0].startswith(_MARKER):
        lines = lines[1:]
    body = "\n".join(lines).strip("\n")
    spec_field = f" | spec: {spec}" if spec else ""
    return (
        f"{_MARKER} | source: {source} | drafted-by: {drafted_by}{spec_field} | "
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
            spec=fields.get("spec", ""),
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
    replace: bool, clear_checkpoint: bool = False, spec: str = "",
    draft_path: Path | None = None,
) -> Path:
    from whyline_relay import config, planner, testplan

    settings = _settings(root)
    if draft_path is None and settings.planner.test:
        settings = dc_replace(
            settings,
            planner=dc_replace(settings.planner, test=""),
        )
    staged = config.relay_dir(root) / "approved-plan.md"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(
        with_marker(text, source=source, drafted_by=drafted_by, spec=spec), encoding="utf-8"
    )
    staged_tests = testplan.path_for(staged)
    draft_tests = testplan.path_for(draft_path) if draft_path is not None else None
    if settings.planner.test and draft_tests is not None and draft_tests.is_file():
        staged_tests.write_text(draft_tests.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        staged_tests.unlink(missing_ok=True)
    try:
        target = planner.approve(
            root, settings, staged, drafted_by=drafted_by, replace=replace,
            clear_checkpoint=clear_checkpoint, target=plan_path(root, name),
        )
        commit_planning_decisions(root)
        return target
    finally:
        staged.unlink(missing_ok=True)
        staged_tests.unlink(missing_ok=True)


def configured_plan(root: Path) -> Path | None:
    try:
        return root / _settings(root).plan
    except Exception:  # unreadable config
        return None


def select_plan(root: Path, path: Path) -> None:
    from whyline_relay import setup

    setup.write_plan(root, path.relative_to(root).as_posix())


def planner_agents(root: Path) -> tuple[str, str, str]:
    try:
        planner_cfg = _settings(root).planner
    except Exception:
        return ("codex", "claude", "")
    return planner_cfg.draft, planner_cfg.review, planner_cfg.test


def save_planner(root: Path, draft: str, review: str, test: str = "") -> None:
    from whyline_relay import setup

    actual_test = (
        test
        if test
        else getattr(draft, "_test_planner", "") or getattr(review, "_test_planner", "")
    )
    setup.write_planner(root, str(draft), str(review), str(actual_test))


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
            if re.match(r"^\s*[-*]\s+\[[ xX]\]", line):
                break
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


def _planner_draft(root: Path, path: Path) -> Draft:
    cfg = _settings(root).planner
    return Draft(
        path=path,
        text=path.read_text(encoding="utf-8"),
        drafted_by=f"{cfg.draft} (reviewed by {cfg.review})",
        source="planner",
    )


def draft_plan(
    root: Path,
    description: str,
    attachments: Sequence[Path] = (),
    *,
    progress,
    spec: Path | None = None,
) -> Draft:
    from whyline_relay import planner

    kwargs = {"spec": spec} if spec is not None else {}
    path = planner.draft(
        root, _settings(root), description, attachments=attachments, print_fn=progress, **kwargs
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


def _spec_draft(root: Path, path: Path) -> Draft:
    cfg = _settings(root).planner
    return Draft(
        path=path,
        text=path.read_text(encoding="utf-8"),
        drafted_by=f"{cfg.draft} (reviewed by {cfg.review})",
        source="spec",
    )


def draft_spec(
    root: Path,
    request: str,
    attachments: Sequence[Path] = (),
    *,
    progress,
) -> Draft:
    from whyline_relay import specs

    path = specs.draft(
        root, _settings(root), request, attachments=attachments, print_fn=progress
    )
    return _spec_draft(root, path)


def pending_spec(root: Path) -> str | None:
    from whyline_relay import specs

    return specs.pending_description(root)


def resume_spec(root: Path, *, progress) -> Draft:
    from whyline_relay import specs

    return _spec_draft(
        root, specs.resume_draft(root, _settings(root), print_fn=progress)
    )


def revise_spec(root: Path, draft: Draft, feedback: str, *, progress) -> Draft:
    from whyline_relay import specs

    specs.revise(root, _settings(root), feedback, print_fn=progress)
    return dc_replace(draft, text=draft.path.read_text(encoding="utf-8"))


def answer_spec(root: Path, answers: str, *, progress) -> Draft:
    from whyline_relay import specs

    return _spec_draft(
        root, specs.answer(root, _settings(root), answers, print_fn=progress)
    )


def discard_spec(root: Path) -> None:
    from whyline_relay import specs

    specs.discard(root)


def approve_spec(
    root: Path, draft: Draft | Path, name: str, *, replace: bool = False
) -> Path:
    from whyline_relay import specs

    path = draft.path if isinstance(draft, Draft) else draft
    target = specs.approve(root, path, name=name, replace=replace)
    commit_planning_decisions(root)
    return target


def spec_questions_error():
    from whyline_relay import specs

    return specs.SpecQuestions



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


def approve_plan(
    root: Path, draft: Draft, name: str, *, replace: bool = False, spec: str = ""
) -> Path:
    return _approve_marked(
        root,
        draft.path.read_text(encoding="utf-8"),
        name=name,
        source=_SOURCE_LABELS.get(draft.source, draft.source),
        drafted_by=draft.drafted_by,
        replace=replace,
        clear_checkpoint=draft.source == "planner",
        spec=spec,
        draft_path=draft.path,
    )


def brainstorm_docs(root: Path) -> list[str]:
    folder = root / "docs" / "brainstorm"
    if not folder.is_dir():
        return []
    return sorted(path.stem for path in folder.glob("*.md"))


def _timeout_seconds_kwarg(timeout_minutes: int | None) -> dict:
    if timeout_minutes is None:
        return {}
    if timeout_minutes == 0:
        from whyline_relay import chat

        return {"timeout_seconds": chat.NO_LIMIT}
    return {"timeout_seconds": timeout_minutes * 60}


def plan_from_brainstorm(
    root: Path,
    topic: str,
    agent: str,
    *,
    progress,
    timeout_minutes: int | None = None,
    attachments: Sequence[Path] = (),
) -> Draft:
    from whyline_relay import brainstorm

    progress(f"{BRAINSTORM_LABELS[agent]} is turning the brainstorm into a plan")
    kwargs = _timeout_seconds_kwarg(timeout_minutes)
    path = brainstorm.generate_plan_from_synthesis(
        root, _settings(root), agent, _models(agent), topic, attachments=attachments, **kwargs
    )
    return Draft(
        path=path,
        text=path.read_text(encoding="utf-8"),
        drafted_by=f"brainstorm ({agent})",
        source="brainstorm",
        topic=topic,
        agent=agent,
    )


def final_synthesis(root: Path, topic: str) -> str:
    from whyline_relay import brainstorm

    return brainstorm.final_synthesis(root, topic)


def revise_synthesis(
    root: Path,
    topic: str,
    agent: str,
    agents: Sequence[str | tuple[str, str]],
    feedback: str,
    *,
    progress,
    timeout_minutes: int | None = None,
    attachments: Sequence[Path] = (),
) -> None:
    from whyline_relay import brainstorm

    label = BRAINSTORM_LABELS.get(agent, agent)
    progress(f"{label} is revising the synthesis")
    models = [
        item if isinstance(item, tuple) else (item, BRAINSTORM_LABELS.get(item, item))
        for item in agents
    ]
    kwargs = _timeout_seconds_kwarg(timeout_minutes)
    brainstorm.revise_synthesis(
        root,
        _settings(root),
        agent,
        models,
        topic,
        feedback,
        attachments=attachments,
        **kwargs,
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


def read_backup(root: Path) -> list[str]:
    from whyline_relay import setup

    return setup.read_backup(root)


def current_roles(root: Path) -> dict:
    from whyline_relay import config

    # Every agent the relay knows, installed or not: Set up shows what the
    # config says, and the ready check is what flags a missing agent.
    agents = relay_agents(root, which=lambda binary: binary)
    roles = dict(_DEFAULT_ROLES)
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
    # A missing file is an empty chain. ConfigError from a bad name or a
    # broken file propagates; it is not reported as an empty chain.
    backup = [name for name in read_backup(root) if name in agents]
    return {**roles, "backup": backup}


def _stored_roles(root: Path) -> dict[str, str]:
    """The [roles] table as written, unfiltered: what the config said before a
    save, so a changed role can be told from an unchanged one."""
    from whyline_relay import config

    try:
        raw = tomllib.loads(config.config_path(root).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    table = raw.get("roles")
    if not isinstance(table, dict):
        return {}
    return {key: value for key, value in table.items() if isinstance(value, str)}


def clear_stale_switches(
    root: Path,
    saved: dict[str, tuple[str | None, str]] | None = None,
    chain: list[str] | None = None,
) -> dict[str, str]:
    """Drop the backup switches (.whyline/relay/active-roles.json) a save
    made stale, so what the user picks is what runs: the relay's
    effective_agent prefers a switch over the configured agent.

    `saved` maps a role to (agent stored before, agent saved now). Its switch
    goes when the saved agent differs from the one stored before, or from the
    agent the switch was standing in for (`backup_for`). `chain`, when given,
    is the saved backup chain: a switch to an agent no longer in it goes too.
    Other roles' switches are untouched. Returns {role: backup agent it was
    on} for each switch cleared. Never creates active-roles.json."""
    from whyline_relay import failover

    saved = saved or {}
    cleared: dict[str, str] = {}
    for role, override in failover.read_overrides(root).items():
        stale = False
        if role in saved:
            before, now = saved[role]
            stale = now != before or now != override.backup_for
        if chain is not None and override.agent not in chain:
            stale = True
        if stale:
            failover.clear_overrides(root, role=role)
            cleared[role] = override.agent
    return cleared


def save_backup(root: Path, chain: list[str]) -> dict[str, str]:
    """Save the chain; returns the switches it cleared (clear_stale_switches)."""
    from whyline_relay import setup

    setup.write_backup(root, chain)
    return clear_stale_switches(root, chain=[name for name in chain if name])


def save_roles(
    root: Path, implementer: str, tester: str, reviewer: str, backup: list[str]
) -> dict[str, str]:
    """Save the roles and chain; returns the switches it cleared
    (clear_stale_switches), e.g. {"implementer": "claude"}."""
    from whyline_relay import setup

    before = _stored_roles(root)
    setup.write_roles(root, implementer, tester, reviewer, backup)
    picked = {"implementer": implementer, "tester": tester, "reviewer": reviewer}
    return clear_stale_switches(
        root,
        saved={role: (before.get(role), agent) for role, agent in picked.items()},
        chain=[name for name in backup if name],
    )


def save_release(root: Path, value: str) -> None:
    from whyline_relay import setup

    setup.write_release(root, value)


# Set up's per-agent-run limits, plus 0 for none. 30 is the floor: a relay
# stage that runs the test suite routinely needs more than 15 minutes.
RELAY_TIMEOUT_OPTIONS = (30, 45, 60, 0)


def relay_timeout(root: Path) -> int:
    """The saved `timeout_minutes`, or the relay's default 30 when unreadable."""
    try:
        return int(_settings(root).timeout_minutes)
    except Exception:
        return 30


def save_timeout(root: Path, minutes: int) -> None:
    from whyline_relay import setup

    setup.write_timeout_minutes(root, minutes)


def resolve_mode_path(root: Path | str) -> Path:
    return Path(root) / ".whyline" / "relay" / "resolve-mode.json"


def resolve_mode(root: Path | str) -> str:
    path = resolve_mode_path(root)
    if not path.is_file():
        return "review"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            mode = data.get("mode")
            if mode in ("auto", "review"):
                return mode
    except Exception:
        pass
    return "review"


_RESOLVE_MODE_IGNORE = ".whyline/relay/resolve-mode.json"


def _ignore_resolve_mode(root: Path) -> None:
    """Keep the saved choice out of `git status`, the way the relay keeps its
    own runtime files out: in .git/info/exclude, which is never committed.
    Tracked, every Check dirtied the tree and failed its own clean-tree check."""
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-path", "info/exclude"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return  # not a git repository: nothing to keep clean
    target = Path(res.stdout.strip())
    if not target.is_absolute():
        target = root / target
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if _RESOLVE_MODE_IGNORE in existing.splitlines():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(_RESOLVE_MODE_IGNORE + "\n")


def save_resolve_mode(root: Path | str, mode: str) -> None:
    if mode not in ("auto", "review"):
        raise ValueError(f"Invalid resolve mode: {mode!r}; must be 'auto' or 'review'")
    _ignore_resolve_mode(Path(root))
    path = resolve_mode_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "mode": mode}, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def release_role(root: Path) -> str:
    try:
        return _settings(root).release_role
    except Exception:
        return "human"



def run_checks(root: Path, plan: Path | None = None) -> list[CheckLine]:
    from whyline_relay import preflight

    checks = preflight.run(root, plan) if plan is not None else preflight.run(root)
    return [CheckLine(c.status, c.message, c.hint) for c in checks]


def stale_pause(root: Path) -> str | None:
    """The task id of a paused run that has nothing left to resume: its task
    is already ticked, or its plan file is gone. None otherwise."""
    from whyline_relay import plan as relay_plan, state

    saved = state.load(root)
    if saved is None:
        return None
    path = Path(saved.plan)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        return saved.task_id or "an old run"
    try:
        tasks = relay_plan.parse(path.read_text(encoding="utf-8"))
    except relay_plan.PlanError:
        return None
    done = {task.task_id for task in tasks if task.checked}
    return saved.task_id if saved.task_id in done else None


def clear_pause(root: Path) -> None:
    from whyline_relay import state

    state.clear(root)


def release_task(root: Path) -> tuple[str, list[str]] | None:
    from whyline_relay import loop, state

    saved = state.load(root)
    if saved is None or not saved.paused_reason:
        return None
    if not saved.paused_reason.startswith(loop.RELEASE_PREFIX):
        return None
    lines = saved.paused_reason.splitlines()
    task_id = lines[0].removeprefix(loop.RELEASE_PREFIX).strip() or (saved.task_id or "")
    checklist = [line.strip() for line in lines[1:] if line.strip()]
    return (task_id, checklist)




def live_run(root: Path) -> str | None:
    from whyline_relay import running

    active = running.live(root)
    return None if active is None else f"{active.task}, {active.agent}"


def clear_live_run(root: Path) -> None:
    """Release an in-process planning marker owned by this console process."""
    from whyline_relay import running

    running.clear(root)


def commit_planning_decisions(root: Path) -> bool:
    """Commit planner-written history left dirty by older relay releases."""
    from whyline_relay import gitcheck

    return gitcheck.commit_paths(
        root,
        [root / ".whyline" / "decisions.md"],
        "chore: record planning decisions",
    )


def interrupt_live_run(root: Path) -> bool:
    """Stops a relay running in this repo that another console (or a
    terminal) started, as Ctrl+C would: the agent's turn ends and the run
    pauses for Resume. False when no relay is running here."""
    import os
    import signal

    from whyline.console.relay_process import stop_path
    from whyline_relay import running

    active = running.live(root)
    if active is None:
        return False
    if os.name == "nt":
        target = stop_path(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    else:
        os.kill(active.pid, signal.SIGINT)
    return True


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


def roles_configured(root: Path) -> bool:
    """Whether this repository's relay config already assigns roles."""
    from whyline_relay import config

    path = config.config_path(root)
    if not path.exists():
        return False
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return False
    return bool(raw.get("roles"))


_PREFERENCE = {
    "implementer": ("codex", "claude", "antigravity", "grok"),
    "tester": ("claude", "codex", "grok", "antigravity"),
    "reviewer": ("claude", "codex", "grok", "antigravity"),
}


def staged_backup(primary: str, usable: list[str]) -> list[str]:
    """Usable names except the primary, in implementer preference order.

    A name that is not in that preference tuple keeps its place in `usable`,
    after every preferred name.
    """
    rest = [name for name in usable if name != primary]
    preferred = [name for name in _PREFERENCE["implementer"] if name in rest]
    return preferred + [name for name in rest if name not in _PREFERENCE["implementer"]]


def recommend_roles(usable: list[str]) -> dict:
    """A different agent per role where possible (spec 6b); the rest back up."""
    roles: dict = {}
    used: set[str] = set()
    for role in ("implementer", "tester", "reviewer"):
        order = [a for a in _PREFERENCE[role] if a in usable] + [
            a for a in usable if a not in _PREFERENCE[role]
        ]
        fresh = [a for a in order if a not in used]
        roles[role] = (fresh or order or ["claude"])[0]
        used.add(roles[role])
    roles["backup"] = [a for a in _PREFERENCE["implementer"] if a in usable and a not in used]
    return roles


def usable_agents(root: Path, status: dict) -> list[str]:
    """Installed relay agents that are also logged in."""
    return [a for a in relay_agents(root) if status.get(a, {}).get("available")]


def role_meaning(
    implementer: str, tester: str, reviewer: str, release: str = "human"
) -> str:
    actor = "you" if release in ("human", "you") else release
    verb = "do" if actor == "you" else "does"
    return (
        f"{implementer} writes the code → {tester} runs the tests → "
        f"{reviewer} reviews; whyline commits; {actor} {verb} the release steps."
    )


def _summary_name(name: str) -> str:
    """A one-word agent label. An empty name is `none`, not a blank clause."""
    text = str(name or "")
    if not text:
        return "none"
    return text[:1].upper() + text[1:]


def _summary_release(name: str) -> str:
    text = str(name or "")
    if text in ("", "human", "you"):
        return "you"
    return _summary_name(text)


def _has_custom_pipeline(root: Path) -> bool:
    from whyline_relay import config

    try:
        loaded = config.load(root)
    except config.ConfigError:
        return False
    return loaded.pipeline is not None


_CUSTOM_PIPELINE = (
    " This repo has a custom pipeline; Run updates the three role agents"
    " and leaves the other stages."
)


def auto_summary(request) -> str:
    """One line for the unsaved Auto form.

    Research names join with ` + `. The chain keeps its order with ` → `,
    or `Backup: none` when nothing is checked. `request.root`, when set,
    is the repo whose loaded config may add the custom-pipeline sentence.
    """
    agents = tuple(getattr(request, "agents", ()) or ())
    chain = tuple(getattr(request, "chain", ()) or ())
    research = " + ".join(_summary_name(agent) for agent in agents) or "none"
    backup = " → ".join(_summary_name(agent) for agent in chain) or "none"
    line = (
        f"{research} research → {_summary_name(getattr(request, 'final_agent', ''))} synthesizes → "
        f"{_summary_name(getattr(request, 'drafter', ''))} drafts, "
        f"{_summary_name(getattr(request, 'reviewer', ''))} reviews → "
        f"{_summary_name(getattr(request, 'implementer', ''))} implements, "
        f"{_summary_name(getattr(request, 'tester', ''))} tests, "
        f"{_summary_name(getattr(request, 'reviewer_role', ''))} reviews → "
        f"whyline commits → {_summary_release(getattr(request, 'release', 'human'))} release. "
        f"Backup: {backup}."
    )
    root = getattr(request, "root", None)
    if root is not None and _has_custom_pipeline(root):
        line += _CUSTOM_PIPELINE
    return line




def prepare_agents(root: Path, agents: list[str], *, commit: bool = True) -> list[Path]:
    """Writes the permission files the chosen agents' commands need (e.g.
    claude's .whyline/relay/claude-settings.json) when they're missing, and
    commits only those files. Pass commit=False when the caller makes one
    commit that includes them. Run never asks anyone to type `init`; an
    existing, possibly customised, file is never overwritten."""
    from whyline_relay import gitcheck, init

    created: list[Path] = []
    for agent in dict.fromkeys(agents):
        created += init.ensure_permission_files(root, agent)
    if created and commit:
        gitcheck.commit_paths(root, created, "setup: generate agent permission settings")
    return created


def delivery_for(root: Path, agent: str, kind: str) -> str:
    from whyline_relay import attachments, config

    return attachments.delivery(config.load(root), agent, kind)


# The same sentence preflight._role_checks emits when Antigravity is in use.
_ANTIGRAVITY_GENERIC = (
    "antigravity is a generic agent, and its headless permission "
    "enforcement is known to be unreliable -- see README, 'Using "
    "Antigravity today', and "
    "github.com/google-antigravity/antigravity-cli#548. The relay "
    "does not manage its permissions, login or denials"
)
_PROMPT_NAMES = ("implement", "test", "review")


def _line(status: str, message: str, group: str, hint: str | None = None) -> CheckLine:
    return CheckLine(status, message, hint, group)


def _auto_plan_name(request) -> str:
    """The plan screen's `_plan_name`: the field, then the topic, then `plan`."""
    name = str(getattr(request, "name", "") or "").strip()
    topic = str(getattr(request, "topic", "") or "").strip()
    return name or topic or "plan"


def _no_limit_available() -> bool:
    from whyline_relay import chat

    return hasattr(chat, "NO_LIMIT")


def _scratch_parent(root: Path) -> Path:
    """A directory that is neither this repo nor Antigravity's settings dir."""
    from whyline_relay import antigravity

    repo = root.resolve()
    settings_dir = antigravity.settings_path().resolve().parent
    system_temp = Path(tempfile.gettempdir()).resolve()
    candidates = [system_temp, repo.parent]
    for parent in candidates:
        try:
            parent = parent.resolve()
        except OSError:
            continue
        if not parent.is_dir():
            continue
        if parent == repo or repo in parent.parents:
            continue
        if parent == settings_dir or settings_dir in parent.parents:
            continue
        return parent
    return repo.parent


def _outside(path: Path, banned: Path) -> bool:
    return path != banned and banned not in path.parents


def _set_unquoted_timeout(text: str, minutes: int) -> str:
    """Set top-level `timeout_minutes` to an unquoted integer.

    The relay's string helper would quote it, and a quoted timeout is not
    the value Run persists.
    """
    lines = text.splitlines()
    first_table = next(
        (index for index, line in enumerate(lines) if line.lstrip().startswith("[")),
        len(lines),
    )
    rendered = str(int(minutes))
    for index in range(first_table):
        match = re.match(r"^(\s*timeout_minutes\s*=\s*).*$", lines[index])
        if match:
            lines[index] = f"{match.group(1)}{rendered}"
            return "\n".join(lines).rstrip("\n") + "\n"
    insert_at = first_table
    while insert_at > 0 and not lines[insert_at - 1].strip():
        insert_at -= 1
    new = [f"timeout_minutes = {rendered}"]
    if first_table < len(lines):
        new.append("")
    lines[insert_at:first_table] = new
    return "\n".join(lines).rstrip("\n") + "\n"


def _candidate_toml(root: Path, request) -> str:
    """The TOML Run would persist, built in memory from the file on disk."""
    from whyline_relay import config, setup

    path = config.config_path(root)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    implementer = str(request.implementer or "")
    tester = str(request.tester or "")
    reviewer = str(request.reviewer_role or "")
    if setup._has_pipeline(existing):
        content = setup._set_keys(existing, "roles", {
            "implementer": implementer,
            "tester": tester,
            "reviewer": reviewer,
        })
    else:
        template = setup.PIPELINE_CONFIG_TEMPLATE.format(
            implementer=implementer, tester=tester, reviewer=reviewer,
        )
        kept = setup._without_tables(existing, {"roles", "backup", "status_map"})
        content = f"{kept}\n\n{template}" if kept else template
        existing_release = None
        if existing:
            try:
                old = tomllib.loads(existing)
            except tomllib.TOMLDecodeError:
                old = {}
            if isinstance(old.get("roles"), dict):
                existing_release = old["roles"].get("release")
        if isinstance(existing_release, str) and existing_release:
            content = setup._set_keys(content, "roles", {"release": existing_release})
    chain = [name for name in tuple(request.chain or ()) if name]
    content = setup._set_backup(content, chain)
    test_planner = str(
        getattr(request, "test_planner", "")
        or getattr(request, "test", "")
        or getattr(getattr(request, "drafter", ""), "_test_planner", "")
        or ""
    )
    content = setup._set_keys(
        content,
        "planner",
        {
            "draft": str(request.drafter or ""),
            "review": str(request.reviewer or ""),
            "test": test_planner,
        },
    )
    content = setup._set_keys(content, "roles", {"release": str(request.release or "")})
    return _set_unquoted_timeout(content, request.timeout_minutes)


def _load_candidate(root: Path, request):
    """Parse the candidate TOML on a scratch root, then remove that root."""
    from whyline_relay import antigravity, config

    text = _candidate_toml(root, request)
    parent = _scratch_parent(root)
    directory = tempfile.TemporaryDirectory(dir=str(parent))
    try:
        scratch = Path(directory.name).resolve()
        repo = root.resolve()
        settings_dir = antigravity.settings_path().resolve().parent
        if not _outside(scratch, repo):
            raise RuntimeError("candidate scratch is inside the repository")
        if not _outside(scratch, settings_dir):
            raise RuntimeError("candidate scratch is inside Antigravity settings")
        path = config.config_path(scratch)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return config.load(scratch)
    finally:
        directory.cleanup()


def _loaded_settings(root: Path):
    from whyline_relay import config

    try:
        return config.load(root)
    except (config.ConfigError, TypeError, ValueError, OSError):
        return None


def _has_login_check(root: Path, agent: str) -> bool:
    from whyline_relay import adapters, config

    settings = _loaded_settings(root)
    if settings is not None and agent in settings.agents:
        try:
            adapter = config.adapter_for(settings, agent)
        except KeyError:
            return False
        return adapter.login_argv is not None
    try:
        return adapters.get(agent).login_argv is not None
    except KeyError:
        return False


def _repository_lines(root: Path) -> list[CheckLine]:
    from whyline_relay import preflight

    checks = preflight.run(root, scope="repository")
    return [_line(check.status, check.message, "Repository", check.hint) for check in checks]


def _agent_lines(root: Path, request) -> list[CheckLine]:
    from whyline import account
    from whyline.console.auto_run import named_agents

    group = "Agents and logins"
    installed = set(relay_agents(root))
    status = account.agent_status(root)
    lines: list[CheckLine] = []
    for agent in named_agents(request):
        if agent not in installed:
            lines.append(_line("FAIL", f"{agent} is not installed", group, f"install {agent}"))
            continue
        info = status.get(agent) or {}
        if _has_login_check(root, agent) and not info.get("available"):
            label = info.get("label") or "not logged in"
            lines.append(_line("FAIL", f"{agent} is {label}", group, info.get("hint")))
        elif _has_login_check(root, agent):
            lines.append(_line("ok", f"{agent} is logged in", group))
        else:
            lines.append(_line("ok", f"{agent} is installed", group))
    if "antigravity" not in named_agents(request):
        return lines
    state = antigravity_state(root)
    if state == "declined":
        lines.append(_line("FAIL", "Antigravity is not trusted for this repo", group))
    elif state == "trusted":
        lines.append(_line("ok", "Antigravity is trusted for this repo", group))
    else:
        lines.append(_line("FAIL", "Antigravity trust is not resolved for this repo", group))
    lines.append(_line("warn", _ANTIGRAVITY_GENERIC, group))
    return lines


def _delivery_agents(request) -> list[str]:
    names = [
        *tuple(getattr(request, "agents", ()) or ()),
        str(getattr(request, "drafter", "") or ""),
        str(getattr(request, "test_planner", "") or getattr(request, "test", "") or ""),
        str(getattr(request, "reviewer", "") or ""),
    ]
    return list(dict.fromkeys(name for name in names if str(name).strip()))


def _input_lines(root: Path, request) -> list[CheckLine]:
    from whyline.console.tui import BRAINSTORM_TIMEOUT_OPTIONS
    from whyline_relay import attachments as relay_attachments

    group = "Inputs"
    lines: list[CheckLine] = []
    topic = str(request.topic or "").strip()
    if topic:
        lines.append(_line("ok", f"Topic is {topic}.", group))
    else:
        lines.append(_line("FAIL", "Topic is empty.", group))
    research = tuple(request.agents or ())
    if research:
        lines.append(_line("ok", f"Research agents: {', '.join(research)}.", group))
    else:
        lines.append(_line("FAIL", "Pick at least one research agent.", group))
    passes = str(request.passes).strip()
    if re.fullmatch(r"[0-9]+", passes):
        lines.append(_line("ok", f"Review passes: {request.passes}.", group))
    else:
        lines.append(_line(
            "FAIL", f"Review passes must be a whole number, not {request.passes!r}.", group
        ))
    minutes = request.timeout_minutes
    if minutes in BRAINSTORM_TIMEOUT_OPTIONS:
        lines.append(_line("ok", f"Timeout is {minutes} minutes.", group))
    elif minutes == 0 and _no_limit_available():
        lines.append(_line("ok", "Timeout is no limit.", group))
    elif minutes == 0:
        lines.append(_line("FAIL", "No limit is not available yet", group))
    else:
        choices = ", ".join(str(item) for item in BRAINSTORM_TIMEOUT_OPTIONS)
        lines.append(_line("FAIL", f"Timeout must be one of {choices} minutes.", group))

    readable_images: list[Path] = []
    for path in tuple(request.attachments or ()):
        shown = str(path)
        if not path.exists():
            lines.append(_line("FAIL", f"Attachment is missing: {shown}", group))
            continue
        if not path.is_file():
            lines.append(_line("FAIL", f"Attachment is not a file: {shown}", group))
            continue
        try:
            with path.open("rb") as handle:
                handle.read(1)
        except OSError as error:
            lines.append(_line("FAIL", f"Attachment is not readable: {shown} ({error})", group))
            continue
        lines.append(_line("ok", f"Attachment {shown} is readable.", group))
        try:
            kind = relay_attachments.kind_of(path)
        except OSError:
            kind = "file"
        if kind == "image":
            readable_images.append(path)

    agents = _delivery_agents(request)
    deliveries: dict[tuple[str, str], str] = {}
    for agent in agents:
        for kind in ("image", "file"):
            try:
                value = delivery_for(root, agent, kind)
            except (OSError, ValueError, KeyError) as error:
                lines.append(_line(
                    "FAIL", f"Could not check {agent} {kind} delivery: {error}", group
                ))
                continue
            if not value:
                lines.append(_line("FAIL", f"{agent} has no {kind} delivery.", group))
                value = ""
            deliveries[(agent, kind)] = value
    if readable_images:
        risky = [
            agent for agent in agents
            if deliveries.get((agent, "image")) == "path-unverified"
        ]
        if risky:
            message = (
                f"{', '.join(risky)} get images as file paths only and may not see them."
            )
            status = "warn" if request.continue_paths else "FAIL"
            lines.append(_line(status, message, group))
    return lines


def _target_line(root: Path, path: Path, replace: bool) -> CheckLine:
    try:
        shown = path.relative_to(root).as_posix()
    except ValueError:
        shown = path.as_posix()
    if not path.exists():
        return _line("ok", f"{shown} is free.", "Planning")
    if replace:
        return _line("ok", f"Run will replace {shown}.", "Planning")
    return _line("FAIL", f"{shown} already exists.", "Planning")


def _max_visits_line(root: Path) -> CheckLine:
    from whyline_relay import config

    group = "Planning"
    path = config.config_path(root)
    if not path.is_file():
        return _line("ok", "Planner max visits is 3.", group)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as error:
        return _line("FAIL", str(error), group)
    planner = raw.get("planner") or {}
    if not isinstance(planner, dict) or "max_visits" not in planner:
        return _line("ok", "Planner max visits is 3.", group)
    value = planner.get("max_visits")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return _line("FAIL", "[planner] max_visits must be a positive integer", group)
    return _line("ok", f"Planner max visits is {value}.", group)


def _planning_lines(root: Path, request) -> list[CheckLine]:
    from whyline_relay import brainstorm, specs

    group = "Planning"
    lines: list[CheckLine] = []
    for label, value in (("Drafter", request.drafter), ("Reviewer", request.reviewer)):
        if str(value or "").strip():
            lines.append(_line("ok", f"{label} is {value}.", group))
        else:
            lines.append(_line("FAIL", f"{label} is empty.", group))
    lines.append(_max_visits_line(root))
    plan_name = _auto_plan_name(request)
    targets = (
        brainstorm.shared_path(root, str(request.topic or "")),
        root / "docs" / "specs" / f"{specs._slug(plan_name)}.md",
        plan_path(root, plan_name),
    )
    for target in targets:
        lines.append(_target_line(root, target, bool(request.replace)))
    return lines


def _execution_lines(root: Path, request) -> list[CheckLine]:
    from whyline_relay import config, prompts

    group = "Execution"
    lines: list[CheckLine] = []
    for label, value in (
        ("Implementer", request.implementer),
        ("Tester", request.tester),
        ("Reviewer", request.reviewer_role),
    ):
        if str(value or "").strip():
            lines.append(_line("ok", f"{label} is {value}.", group))
        else:
            lines.append(_line("FAIL", f"{label} is empty.", group))
    implementer = str(request.implementer or "").strip()
    reviewer = str(request.reviewer_role or "").strip()
    if implementer and implementer == reviewer:
        lines.append(_line(
            "warn",
            f"{implementer} is both the implementer and the reviewer, "
            "so the review is not independent",
            group,
        ))
    release = str(request.release or "")
    if release == "human":
        lines.append(_line("ok", "Release is human.", group))
    elif not release.strip():
        lines.append(_line("FAIL", "Release is empty.", group))
    else:
        lines.append(_line("ok", f"Release is {release}.", group))
    try:
        _load_candidate(root, request)
    except (config.ConfigError, TypeError, ValueError) as error:
        lines.append(_line("FAIL", str(error), group))
    for name in _PROMPT_NAMES:
        try:
            prompts.load(root, name)
        except prompts.PromptError as error:
            lines.append(_line(
                "FAIL",
                str(error),
                group,
                f"add .whyline/relay/prompts/{name}.md, or name a "
                "built-in prompt (implement, review) instead",
            ))
        else:
            lines.append(_line("ok", f"Prompt {name} resolves.", group))
    if _has_custom_pipeline(root):
        lines.append(_line("warn", _CUSTOM_PIPELINE.strip(), group))
    return lines


def _concurrency_lines(root: Path) -> list[CheckLine]:
    from whyline_relay import invocation, running

    group = "Concurrency"
    lines: list[CheckLine] = []
    active = running.live(root)
    if active is not None:
        lines.append(_line(
            "FAIL",
            f"another relay is running here (pid {active.pid})",
            group,
            f"wait for it, or run: {invocation.command('stop')}",
        ))
    else:
        lines.append(_line("ok", "no other relay is running here", group))
    if pending_draft(root) or pending_spec(root):
        lines.append(_line(
            "FAIL",
            "A plan draft is already unfinished -- open Plan to resume or discard it.",
            group,
        ))
    else:
        lines.append(_line("ok", "No unfinished plan or spec draft.", group))
    lock = root / ".whyline" / "relay" / "auto-run.lock"
    if lock.exists():
        try:
            pid = int(lock.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = None
        if pid is not None and not running.pid_is_alive(pid):
            lines.append(_line("ok", "The stale lock will be taken.", group))
        else:
            lines.append(_line("FAIL", "An Auto run is already in progress.", group))
    return lines


def _timeout_amount(minutes: int) -> str:
    if minutes == 0:
        return "no limit"
    return f"{minutes}m"


def _will_write_lines(request) -> list[CheckLine]:
    group = "Will write"
    chain = [name for name in tuple(request.chain or ()) if name]
    chain_text = ", ".join(chain) if chain else "none"
    amount = _timeout_amount(request.timeout_minutes)
    return [
        _line("ok", f"Run will set implementer to {request.implementer}.", group),
        _line("ok", f"Run will set tester to {request.tester}.", group),
        _line("ok", f"Run will set reviewer to {request.reviewer_role}.", group),
        _line("ok", f"Run will set release to {request.release}.", group),
        _line("ok", f"Run will set the backup chain to {chain_text}.", group),
        _line(
            "ok",
            f"Run will set the planner to {request.drafter} drafts, {request.reviewer} reviews.",
            group,
        ),
        _line(
            "ok",
            "Relay timeout for this repo becomes "
            f"{amount}. Later relay tasks in this repo use that timeout.",
            group,
        ),
    ]


def candidate_checks(root: Path, request) -> list[CheckLine]:
    """Check an unsaved Auto form. Reads the repository and returns lines.

    The candidate config is parsed in a temporary directory outside the
    repository and outside Antigravity's settings file. This does not save
    roles, release, the planner, or trust, and it does not open the trust dialog.
    """
    lines = [
        *_repository_lines(root),
        *_agent_lines(root, request),
        *_input_lines(root, request),
        *_planning_lines(root, request),
        *_execution_lines(root, request),
        *_concurrency_lines(root),
        *_will_write_lines(request),
    ]
    return lines
