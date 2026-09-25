# Planner Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `whyline-relay plan "<description>"` — drafts a `plan.md` from a free-text description via an unattended draft/structural-review loop, then a three-way human gate (approve / request changes / discard), with an offer to start the real run immediately on approval, and full crash-safe resume.

**Architecture:** A new, small `planner.py` module compiles `[planner]` config into a literal two-stage `pipeline.Pipeline` (`draft`, `review`) and drives it with its own loop, reusing `loop.py`'s already-shared `run_agent`/`check_visit_cap` helpers (promoted from private to public for this second caller) and `pipeline.decide()` for routing — but never touching git, never ticking `plan.md`, and checkpointing to a new, separate `PlanState`/`plan-state.json` rather than overloading `RelayState`. Once the loop checkpoints `"@complete"`, a human gate (in `planner.py`, `init.py`-style: prints, asks via an injectable `confirm`, returns a result) takes over: approve writes and commits the real `plan.md` and optionally launches `loop.run_plan` directly; request-changes redrafts (unbounded, human-driven); discard clears the checkpoint. `cli.py` gains `plan "<description>"` and `plan --discard`, and `cmd_resume` gains a branch that dispatches to the planner's own resume path before falling through to the existing task-resume path.

**Tech Stack:** Python 3.11+, existing `pipeline`/`prompts`/`loop`/`state`/`gitcheck`/`config`/`cli` modules. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-25-relay-planner-workflow.md`, all sections. Relates to `docs/superpowers/specs/2026-09-23-relay-n-roles-design.md` (roadmap piece E, whose non-goals section deferred this piece to begin with).

## Global Constraints

- Zero runtime dependencies (`pyproject.toml`'s `dependencies = []`) — every piece of this plan uses only the standard library and the project's own modules.
- No stage in the draft/review pipeline may commit, tick `plan.md`, or be subject to a git-HEAD check — nothing worth committing exists until the human approves (spec P4).
- An agent-declared `blocked` outcome, or a stage's `max_visits` being exceeded, always raises `loop.Paused` — never a graceful in-process branch. This matches every other stage in the project and was a deliberate simplification made while grounding the spec against the real code (spec 5.6, decision log).
- A human's own "request changes" round at the approval gate is never bounded by `max_visits`; only the unattended draft↔review loop is (spec P5).
- Planner handoffs use the fixed, reserved whyline task id `__plan__` (spec P10).
- Every existing test must still pass after every task.

---

### Task 1: `loop.py` — promote `_run_agent`/`_check_visit_cap` to public API

**Files:**
- Modify: `src/whyline_relay/loop.py` (renames only, at lines 56, 80, 283, 474, 508, 609 — confirmed by `grep -n "_run_agent\|_check_visit_cap" src/whyline_relay/loop.py` to be the only six occurrences)
- Test: `tests/test_loop_pipeline.py`

**Interfaces:**
- Produces: `loop.run_agent(...)` (same signature `_run_agent` already has) and `loop.check_visit_cap(pipe, stage_id, stage_visits, task)` (same signature `_check_visit_cap` already has). Task 6 is the only new caller.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_loop_pipeline.py`:

```python
def test_run_agent_and_check_visit_cap_are_public():
    # Both were already shared internally by _run_task and _run_configured_task;
    # this plan adds a third caller (planner.py, Task 6) in a different module,
    # which needs them importable without a leading underscore.
    assert callable(loop.run_agent)
    assert callable(loop.check_visit_cap)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_loop_pipeline.py -k public -v`
Expected: FAIL — `AttributeError: module 'whyline_relay.loop' has no attribute 'run_agent'`.

- [ ] **Step 3: Implement**

In `src/whyline_relay/loop.py`, rename the two function definitions (no other changes to their bodies):

```python
def check_visit_cap(
```

(was `def _check_visit_cap(`, at line 56)

```python
def run_agent(
```

(was `def _run_agent(`, at line 80)

Then update the four call sites. At line 283 (inside `_run_task`):

```python
        target = run_agent(
```

(was `target = _run_agent(`)

At line 474 (inside `_run_configured_task`'s resume-consult branch):

```python
                check_visit_cap(pipe, current_stage_id, stage_visits, task)
```

(was `_check_visit_cap(pipe, current_stage_id, stage_visits, task)`)

At line 508 (inside `_run_configured_task`'s main loop):

```python
        target = run_agent(
```

(was `target = _run_agent(`)

At line 609 (inside `_run_configured_task`'s main loop, after a stage advances):

```python
        check_visit_cap(pipe, current_stage_id, stage_visits, task)
```

(was `_check_visit_cap(pipe, current_stage_id, stage_visits, task)`)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_loop_pipeline.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — this is a pure rename; every other test that already exercised `_run_task`/`_run_configured_task` exercises the exact same code under its new name.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/loop.py tests/test_loop_pipeline.py
git commit -m "refactor: promote loop._run_agent/_check_visit_cap to public API for planner.py"
```

---

### Task 2: `state.py` — `PlanState` and its own checkpoint file

**Files:**
- Modify: `src/whyline_relay/state.py`
- Modify: `src/whyline_relay/gitcheck.py` (`RELAY_IGNORE`)
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `state.PlanState` (dataclass: `description: str, stage: str, round: int, stage_visits: dict[str, int], agent: str, feedback: str, draft_path: str, paused_reason: str, log_path: str`), `state.plan_path(root) -> Path`, `state.save_plan(root, value)`, `state.load_plan(root) -> PlanState | None`, `state.clear_plan(root)`. Task 6/7 are the only callers.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_state.py`:

```python
def sample_plan() -> state.PlanState:
    return state.PlanState(
        description="add a health-check endpoint",
        stage="review",
        round=2,
        stage_visits={"draft": 1, "review": 1},
        agent="claude",
        feedback="",
        draft_path="/tmp/draft-plan.md",
        paused_reason="",
        log_path="/tmp/x.log",
    )


def test_load_plan_returns_none_when_absent(tmp_path: Path):
    assert state.load_plan(tmp_path) is None


def test_save_then_load_plan_round_trips(tmp_path: Path):
    state.save_plan(tmp_path, sample_plan())
    assert state.load_plan(tmp_path) == sample_plan()


def test_clear_plan_removes_it(tmp_path: Path):
    state.save_plan(tmp_path, sample_plan())
    state.clear_plan(tmp_path)
    assert state.load_plan(tmp_path) is None


def test_corrupt_plan_state_reads_as_absent(tmp_path: Path):
    target = tmp_path / ".whyline" / "relay"
    target.mkdir(parents=True)
    (target / "plan-state.json").write_text("{broken")
    assert state.load_plan(tmp_path) is None


def test_plan_state_and_relay_state_live_at_different_paths(tmp_path: Path):
    state.save(tmp_path, sample())
    state.save_plan(tmp_path, sample_plan())
    assert state.path(tmp_path) != state.plan_path(tmp_path)
    assert state.load(tmp_path) == sample()
    assert state.load_plan(tmp_path) == sample_plan()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_state.py -v`
Expected: FAIL — `AttributeError: module 'whyline_relay.state' has no attribute 'PlanState'`.

- [ ] **Step 3: Implement**

In `src/whyline_relay/state.py`, add the `PlanState` dataclass after `RelayState`, and the four functions after `clear`:

```python
@dataclass(frozen=True)
class PlanState:
    description: str
    stage: str
    round: int
    stage_visits: dict[str, int]
    agent: str
    feedback: str
    draft_path: str
    paused_reason: str
    log_path: str


def plan_path(root: Path) -> Path:
    return config.relay_dir(root) / "plan-state.json"


def save_plan(root: Path, value: PlanState) -> None:
    """Write atomically, exactly like save() -- a half-written checkpoint would
    strand a `resume` the same way for either kind of state."""
    target = plan_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(asdict(value), indent=2), encoding="utf-8")
    os.replace(temporary, target)


def load_plan(root: Path) -> PlanState | None:
    try:
        record = json.loads(plan_path(root).read_text(encoding="utf-8"))
        return PlanState(**record)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def clear_plan(root: Path) -> None:
    plan_path(root).unlink(missing_ok=True)
```

In `src/whyline_relay/gitcheck.py`, add two entries to `RELAY_IGNORE` (spec's "where this sits" table: `state.json*` is a specific-filename pattern, not a directory wildcard, so a differently-named file needs its own entry):

```python
RELAY_IGNORE = (
    ".whyline/relay/logs/",
    ".whyline/relay/state.json*",
    ".whyline/relay/plan-state.json*",
    ".whyline/relay/draft-plan.md",
    ".whyline/relay/STOP",
    ".whyline/relay/running.json",
    ".whyline/relay/active-roles.json",
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_state.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — `RELAY_IGNORE` grew, but every existing reference to it is relative, not a hardcoded count: `tests/test_remove.py::test_declining_removes_nothing` compares against `len(gitcheck.RELAY_IGNORE)` dynamically, and `tests/test_gitcheck.py::test_existing_relay_excludes_pick_up_the_running_marker` slices `RELAY_IGNORE[:-1]` (both entries this task adds land in the middle of the tuple, before `STOP`/`running.json`/`active-roles.json`, so the tuple's last element is unchanged and that slice still means the same thing). Confirmed by reading both files directly, not assumed.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/state.py src/whyline_relay/gitcheck.py tests/test_state.py
git commit -m "feat: state.PlanState, a separate crash-safe checkpoint for the planner"
```

---

### Task 3: `config.py` — the `[planner]` table

**Files:**
- Modify: `src/whyline_relay/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `adapters.BUILTIN`, `Config.adapters` (existing, from role/backup validation).
- Produces: `config.PlannerConfig` (dataclass: `draft: str, review: str, max_visits: int = 3`), `Config.planner: PlannerConfig` (new field, always populated — never `None` — defaulting to `Roles.implementer`/`Roles.reviewer` for legacy configs). Task 6 is the only caller of `settings.planner`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_no_planner_table_defaults_to_the_legacy_roles(tmp_path: Path):
    settings = config.load(tmp_path)
    assert settings.planner == config.PlannerConfig(draft="codex", review="claude")


def test_no_planner_table_with_a_configured_pipeline_defaults_to_first_and_last_role(tmp_path):
    write(tmp_path, PIPELINE_TOML)
    settings = config.load(tmp_path)
    # PIPELINE_TOML's [roles] declares implementer, tester, reviewer in that order.
    assert settings.planner == config.PlannerConfig(draft="codex", review="claude")


def test_a_planner_table_overrides_draft_review_and_max_visits(tmp_path: Path):
    write(
        tmp_path,
        '[roles]\nimplementer = "codex"\nreviewer = "claude"\n'
        '[planner]\ndraft = "claude"\nreview = "codex"\nmax_visits = 5\n',
    )
    settings = config.load(tmp_path)
    assert settings.planner == config.PlannerConfig(draft="claude", review="codex", max_visits=5)


def test_planner_draft_naming_an_unknown_agent_is_refused(tmp_path: Path):
    write(tmp_path, '[planner]\ndraft = "nonexistent"\n')
    with pytest.raises(config.ConfigError, match="not a built-in agent"):
        config.load(tmp_path)


def test_planner_max_visits_must_be_a_positive_integer(tmp_path: Path):
    write(tmp_path, "[planner]\nmax_visits = 0\n")
    with pytest.raises(config.ConfigError, match="positive integer"):
        config.load(tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -k planner -v`
Expected: FAIL — `AttributeError: module 'whyline_relay.config' has no attribute 'PlannerConfig'`.

- [ ] **Step 3: Implement**

In `src/whyline_relay/config.py`, add `PlannerConfig` right after the `Roles` dataclass:

```python
@dataclass(frozen=True)
class PlannerConfig:
    draft: str = "codex"
    review: str = "claude"
    max_visits: int = 3
```

Add `planner` to the `Config` dataclass, after `pipeline_fingerprint`:

```python
    planner: PlannerConfig = field(default_factory=PlannerConfig)
```

In `load()`, immediately before the final `return Config(...)` (after both the `if raw_pipeline is not None:` and `else:` branches have run, so `role_names` — a `dict[str, str]` of role name to agent, populated by either branch — is in scope), add:

```python
    raw_planner = raw.get("planner") or {}
    role_agents = list(role_names.values())
    default_draft, default_review = role_agents[0], role_agents[-1]

    def _planner_agent(key: str, default: str) -> str:
        value = raw_planner.get(key, default)
        if not isinstance(value, str):
            raise ConfigError(f"[planner] {key} must be a string")
        if value not in adapters.BUILTIN and value not in configured_adapters:
            builtins = ", ".join(sorted(adapters.BUILTIN))
            raise ConfigError(
                f"[planner] {key} names {value!r}, which is not a built-in agent "
                f"({builtins}) or a configured generic agent"
            )
        return value

    planner_max_visits = raw_planner.get("max_visits", 3)
    if (
        not isinstance(planner_max_visits, int)
        or isinstance(planner_max_visits, bool)
        or planner_max_visits < 1
    ):
        raise ConfigError("[planner] max_visits must be a positive integer")
    planner_cfg = PlannerConfig(
        draft=_planner_agent("draft", default_draft),
        review=_planner_agent("review", default_review),
        max_visits=planner_max_visits,
    )
```

Then add `planner=planner_cfg,` as a new argument to the `return Config(...)` call at the end of `load()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — `Config.planner` has a default, so every existing hand-built `config.Config(...)` call across the test suite (which never passes `planner=`) keeps working unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/config.py tests/test_config.py
git commit -m "feat: config gains an optional [planner] table, defaulting to the existing roles"
```

---

### Task 4: `prompts.py` — built-in `plan-draft`/`plan-review` content

**Files:**
- Modify: `src/whyline_relay/prompts.py`
- Test: `tests/test_prompts.py`

**Interfaces:**
- Produces: `prompts.PLAN_DRAFT`, `prompts.PLAN_REVIEW` (string constants). `TEMPLATES` gains `"plan-draft"` and `"plan-review"` keys. Task 6 is the only caller that names these as a stage's `prompt`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prompts.py`:

```python
def test_plan_draft_and_plan_review_are_built_in_templates(tmp_path):
    assert prompts.load(tmp_path, "plan-draft") == prompts.PLAN_DRAFT
    assert prompts.load(tmp_path, "plan-review") == prompts.PLAN_REVIEW


def test_the_planner_templates_use_the_configured_pipeline_placeholders():
    for template in (prompts.PLAN_DRAFT, prompts.PLAN_REVIEW):
        rendered = prompts.render(
            template, task_id="__plan__", task_text="add a health-check endpoint",
            sync_packet="PACKET", round_=1, review_feedback="", actor="codex",
            role="draft", stage="draft", profile="default",
        )
        assert "{actor}" not in rendered and "{role}" not in rendered
        assert "codex" in rendered and "draft-plan.md" in rendered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prompts.py -k plan_draft -v`
Expected: FAIL — `AttributeError: module 'whyline_relay.prompts' has no attribute 'PLAN_DRAFT'`.

- [ ] **Step 3: Implement**

In `src/whyline_relay/prompts.py`, add two new template strings immediately above the existing `TEMPLATES = {...}` line:

```python
PLAN_DRAFT = """{sync_packet}

You are drafting an implementation plan from a feature description. Round {round}.

## Description

{task_text}

## Feedback from the previous round

{review_feedback}

## How to draft

Write a plan file at `.whyline/relay/draft-plan.md` -- not `plan.md` -- following the
format `whyline-relay plan-format` documents: a Markdown checklist, one
`- [ ] TASK-ID: title` line per task, with detail lines indented underneath. Every
task needs a unique id, a title, and at least one real detail line describing what
to do and how to verify it. Do not write placeholder text like "TBD" or "fill in
details" anywhere -- every task must be something an engineer could start on
immediately, with no further clarification needed.

## How to finish

Exactly one of the outcomes listed below.
"""

PLAN_REVIEW = """{sync_packet}

You are checking a drafted plan's structure only. Round {round}.

## Original description

{task_text}

## What to check

Read `.whyline/relay/draft-plan.md`. Check only structure, never whether these are
the *right* tasks for the goal -- that judgment belongs to a human, not you. Confirm:
the file exists and parses as the documented checklist format; every task has a
unique, present id; every task has at least one real detail line, not just a bare
title; nothing reads as placeholder text ("TBD", "fill in", "similar to the above",
etc.).

If everything checks out, approve it. If something is genuinely missing or broken,
send it back with concrete, specific feedback about exactly what to fix -- not a
vague "make it better."

## How to finish

Exactly one of the outcomes listed below.
"""
```

Then change:

```python
TEMPLATES = {
    "implement": IMPLEMENT,
    "review": REVIEW,
    "test": TEST,
    "security": SECURITY,
}
```

to:

```python
TEMPLATES = {
    "implement": IMPLEMENT,
    "review": REVIEW,
    "test": TEST,
    "security": SECURITY,
    "plan-draft": PLAN_DRAFT,
    "plan-review": PLAN_REVIEW,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_prompts.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/prompts.py tests/test_prompts.py
git commit -m "feat: ship built-in plan-draft/plan-review prompt content"
```

---

### Task 5: `planner.py` — the draft/review loop

**Files:**
- Create: `src/whyline_relay/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- Consumes: `config.Config.planner` (Task 3), `state.PlanState`/`save_plan`/`load_plan` (Task 2), `prompts.stage_footer`/`TEMPLATES["plan-draft"|"plan-review"]` (Task 4), `loop.run_agent`/`check_visit_cap`/`Paused` (Task 1), `pipeline.decide`/`Pipeline`/`Role`/`Stage`/`Profile` (unchanged), `whylinecmd.claim` (unchanged), `gitcheck.ensure_relay_ignored` (unchanged).
- Produces: `planner.PLAN_TASK_ID` (`"__plan__"`), `planner.draft_path(root) -> Path`, `planner._run_pipeline(root, settings, description, *, current_stage_id="draft", round_=1, stage_visits=None, feedback="", consult_handoff=False, echo=True, runner=subprocess.run) -> None` (module-private for now; Task 6 is the only caller, from the same module). Raises `loop.Paused` for every stop condition; returns normally only once `"@complete"` is checkpointed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planner.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

import pytest

from whyline_relay import config, loop, planner, state

FAKE = str(Path(__file__).parent / "fake_pipeline_agent.py")
DESCRIPTION = "add a health-check endpoint"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    (tmp_path / "README.md").write_text("x\n")
    git("add", "-A")
    git("commit", "-m", "initial")
    (tmp_path / ".whyline").mkdir()
    monkeypatch.setattr(
        loop.whylinecmd, "sync", lambda root, task, runner=None: "PACKET"
    )
    monkeypatch.setattr(loop.whylinecmd, "claim", lambda *a, **k: None)
    monkeypatch.setattr(planner.whylinecmd, "claim", lambda *a, **k: None)
    return tmp_path


def settings_with_planner(root: Path, max_visits=3) -> config.Config:
    base = config.load(root)
    return config.Config(
        plan=base.plan,
        max_rounds=base.max_rounds,
        timeout_minutes=base.timeout_minutes,
        branch_prefix=base.branch_prefix,
        agents={"codex": ["codex"], "claude": ["claude"]},
        status_map=base.status_map,
        planner=config.PlannerConfig(draft="codex", review="claude", max_visits=max_visits),
    )


def _scripted_run(specs: list[str]):
    def run(command, prompt, *, cwd, log_path, timeout_seconds, which=None, echo=True, agent_name=None):
        spec = specs.pop(0)
        result = subprocess.run(
            [sys.executable, FAKE, spec, str(cwd), prompt], cwd=cwd, capture_output=True, text=True
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(result.stdout + result.stderr)
        return result.returncode

    return run


def test_a_fresh_session_advances_from_draft_to_complete(repo, monkeypatch):
    settings = settings_with_planner(repo)
    # "claude:ready" -- the draft stage (agent codex) hands "ready" to whoever
    # fills "review" (claude); only @complete/@blocked are ever self-addressed.
    monkeypatch.setattr(loop.agents, "run", _scripted_run(["claude:ready", "claude:approved"]))
    planner._run_pipeline(repo, settings, DESCRIPTION, echo=False)
    saved = state.load_plan(repo)
    assert saved.stage == "@complete"


def test_a_review_revise_outcome_sends_it_back_to_draft(repo, monkeypatch):
    settings = settings_with_planner(repo)
    # Turn 1 (draft/codex) -> ready, addressed to review's agent (claude).
    # Turn 2 (review/claude) -> revise, addressed to draft's agent (codex).
    # Turn 3 (draft/codex) -> ready, addressed to claude again.
    # Turn 4 (review/claude) -> approved, self-addressed (@complete).
    monkeypatch.setattr(
        loop.agents, "run",
        _scripted_run(["claude:ready", "codex:revise", "claude:ready", "claude:approved"]),
    )
    planner._run_pipeline(repo, settings, DESCRIPTION, echo=False)
    saved = state.load_plan(repo)
    assert saved.stage == "@complete"
    # round starts at 1 and increments once per advance (not on the final
    # "complete" turn): draft(1) -> review(2) -> draft(3) -> review(4).
    assert saved.round == 4


def test_a_blocked_outcome_pauses_instead_of_completing(repo, monkeypatch):
    settings = settings_with_planner(repo)
    # blocked is always self-addressed, like @complete -- no recipient check
    # applies to it, so "codex:blocked" (draft blocking itself) is correct.
    monkeypatch.setattr(loop.agents, "run", _scripted_run(["codex:blocked"]))
    with pytest.raises(loop.Paused, match="blocked"):
        planner._run_pipeline(repo, settings, DESCRIPTION, echo=False)


def test_exceeding_max_visits_pauses(repo, monkeypatch):
    settings = settings_with_planner(repo, max_visits=1)
    # Turn 1: draft -> ready -> review (stage_visits: draft=1, review=1, ok).
    # Turn 2: review -> revise -> draft (stage_visits: draft=2 > cap 1, raises
    # before a third turn is ever launched -- only 2 specs are consumed).
    monkeypatch.setattr(loop.agents, "run", _scripted_run(["claude:ready", "codex:revise"]))
    with pytest.raises(loop.Paused, match="visit cap"):
        planner._run_pipeline(repo, settings, DESCRIPTION, echo=False)


def test_a_crash_resume_advances_past_a_stage_whose_handoff_already_landed(repo, monkeypatch):
    settings = settings_with_planner(repo)
    # Simulate a crash right after the draft stage wrote its "ready" handoff,
    # but before the loop processed it: write the handoff by hand, exactly as
    # fake_pipeline_agent.py itself would have produced it for that turn.
    handoff_path = repo / ".whyline" / "active-handoff.json"
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(json.dumps({
        "id": "event1", "counter": 1, "task": planner.PLAN_TASK_ID,
        "to_actor": "claude", "status": "ready", "summary": "drafted", "from_actor": "",
    }))
    # Only one more spec is provided: if consult_handoff mistakenly re-ran
    # draft instead of advancing to review, this would raise IndexError
    # (fake agent's spec list exhausted) instead of reaching "@complete".
    monkeypatch.setattr(loop.agents, "run", _scripted_run(["claude:approved"]))
    planner._run_pipeline(
        repo, settings, DESCRIPTION,
        current_stage_id="draft", round_=1, stage_visits={"draft": 1},
        consult_handoff=True, echo=False,
    )
    assert state.load_plan(repo).stage == "@complete"
    logs = list((repo / ".whyline" / "relay" / "logs").glob("*"))
    assert any("review" in p.name for p in logs)
    assert not any("draft" in p.name for p in logs)


def test_a_human_driven_redraft_ignores_the_stale_approved_handoff(repo, monkeypatch):
    # After a completed session, the on-disk handoff still says "approved". A
    # fresh call with consult_handoff=False (the default) must not re-decide
    # against it -- it always starts a genuinely new turn at current_stage_id.
    settings = settings_with_planner(repo)
    monkeypatch.setattr(loop.agents, "run", _scripted_run(["claude:ready", "claude:approved"]))
    planner._run_pipeline(repo, settings, DESCRIPTION, echo=False)
    assert state.load_plan(repo).stage == "@complete"

    monkeypatch.setattr(loop.agents, "run", _scripted_run(["claude:ready", "claude:approved"]))
    planner._run_pipeline(
        repo, settings, DESCRIPTION,
        current_stage_id="draft", round_=1, stage_visits={"draft": 1}, feedback="make it shorter",
        echo=False,
    )
    assert state.load_plan(repo).stage == "@complete"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_planner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'whyline_relay.planner'`.

- [ ] **Step 3: Implement**

Create `src/whyline_relay/planner.py`:

```python
"""The planner: drafts a plan.md from a free-text description via its own small
draft<->review pipeline, then a human approval gate.

Reuses pipeline.py's Role/Stage/Profile/Pipeline engine and loop.py's run_agent/
check_visit_cap -- shared, not duplicated, since both were already shared
between _run_task and _run_configured_task before this module became a third
caller. Never touches git, never ticks plan.md: nothing worth committing exists
until a human approves at this module's own gate (added in Task 6, below).

Spec: docs/superpowers/specs/2026-09-25-relay-planner-workflow.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from whyline_relay import config, failover, gitcheck, handoff
from whyline_relay import pipeline as pipeline_module
from whyline_relay import plan, prompts, state, whylinecmd
from whyline_relay import loop

PLAN_TASK_ID = "__plan__"


class PlanAlreadyInProgress(RuntimeError):
    """A plan session is already checkpointed; resume or discard it first."""


def draft_path(root: Path) -> Path:
    return config.relay_dir(root) / "draft-plan.md"


def _pipeline_for(settings: config.Config) -> pipeline_module.Pipeline:
    cfg = settings.planner
    return pipeline_module.Pipeline(
        roles={
            "draft": pipeline_module.Role(name="draft", agent=cfg.draft),
            "review": pipeline_module.Role(name="review", agent=cfg.review),
        },
        stages={
            "draft": pipeline_module.Stage(
                id="draft",
                role="draft",
                prompt="plan-draft",
                transitions={"ready": "@next", "blocked": "@blocked"},
                max_visits=cfg.max_visits,
            ),
            "review": pipeline_module.Stage(
                id="review",
                role="review",
                prompt="plan-review",
                transitions={
                    "approved": "@complete",
                    "revise": "draft",
                    "blocked": "@blocked",
                },
                max_visits=cfg.max_visits,
            ),
        },
        profiles={"default": pipeline_module.Profile("default", ("draft", "review"))},
        default_profile="default",
    )


def _task_for(description: str) -> plan.Task:
    return plan.Task(task_id=PLAN_TASK_ID, text=description, checked=False, line_index=0)


def _blocked_reason(record: handoff.Handoff) -> str:
    reason = f"the plan draft was blocked: {record.summary or 'no summary given'}"
    for question in record.questions:
        reason += f". Question: {question}"
    return reason


def _checkpoint(
    root: Path,
    description: str,
    stage: str,
    round_: int,
    stage_visits: dict[str, int],
    feedback: str,
) -> None:
    state.save_plan(
        root,
        state.PlanState(
            description=description,
            stage=stage,
            round=round_,
            stage_visits=dict(stage_visits),
            agent="",
            feedback=feedback,
            draft_path=str(draft_path(root)),
            paused_reason="",
            log_path="",
        ),
    )


def _run_pipeline(
    root: Path,
    settings: config.Config,
    description: str,
    *,
    current_stage_id: str = "draft",
    round_: int = 1,
    stage_visits: dict[str, int] | None = None,
    feedback: str = "",
    consult_handoff: bool = False,
    echo: bool = True,
    runner: failover.Runner = subprocess.run,
) -> None:
    """Drive the draft<->review loop until "@complete" is checkpointed.

    Raises loop.Paused for every stop condition -- no-handoff, an unrecognised
    outcome, either stage's own "blocked", or a stage's max_visits exceeded --
    exactly like _run_configured_task. blocked is always a Paused exception
    here too, never a graceful in-process branch (spec 5.6).

    consult_handoff=True is a genuine crash-resume: the last turn may already
    have written its handoff before the process died, so the saved stage is
    re-decided against whatever handoff exists before launching anything new.
    consult_handoff=False (the default) always starts a fresh turn at
    current_stage_id -- used both for a brand-new session and for a
    human-initiated "request changes" round, which must not reuse a stale
    handoff left over from the review stage's own prior "approved".
    """
    pipe = _pipeline_for(settings)
    effective_agents = {name: role.agent for name, role in pipe.roles.items()}
    task = _task_for(description)
    gitcheck.ensure_relay_ignored(root)
    stage_visits = dict(stage_visits) if stage_visits else {current_stage_id: round_}

    if consult_handoff:
        previous = handoff.read(root)
        if previous is not None and previous.task == task.task_id:
            decision = pipeline_module.decide(
                previous, None, pipe, effective_agents,
                current_stage_id=current_stage_id, profile_name="default",
            )
            if decision.kind == "advance":
                current_stage_id = decision.target_stage
                stage_visits[current_stage_id] = stage_visits.get(current_stage_id, 0) + 1
                loop.check_visit_cap(pipe, current_stage_id, stage_visits, task)
                feedback = previous.summary
            elif decision.kind == "complete":
                _checkpoint(root, description, "@complete", round_, stage_visits, feedback)
                return
            elif decision.kind == "blocked":
                raise loop.Paused(_blocked_reason(previous), None)
            # "unknown"/"no-handoff": current_stage_id/feedback stand; re-run it.

    while True:
        stage = pipe.stages[current_stage_id]
        agent = pipe.roles[stage.role].agent
        previous = handoff.read(root)
        previous_id = previous.event_id if previous else None
        whylinecmd.claim(root, task.task_id, agent, stage.role)
        _checkpoint(root, description, current_stage_id, round_, stage_visits, feedback)
        target = loop.run_agent(
            root, settings, agent, stage.role, stage.prompt, task, round_, feedback, echo,
            implementer="", reviewer="",
            action_label=stage.id, log_suffix=stage.id, actor=agent,
            stage=current_stage_id, profile="default",
            prompt_suffix=prompts.stage_footer(
                stage, pipe, "default", effective_agents, agent, task.task_id
            ),
            runner=runner,
        )
        record = handoff.read(root)
        decision = pipeline_module.decide(
            record, previous_id, pipe, effective_agents,
            current_stage_id=current_stage_id, profile_name="default",
        )
        if decision.kind == "no-handoff":
            raise loop.Paused(f"{agent} exited without handing off; nothing was routed", target)
        if record.task != task.task_id:
            raise loop.Paused(
                f"{agent} handed off for {record.task!r}, but this plan session uses "
                f"{task.task_id!r}; the relay will not guess",
                target,
            )
        if decision.kind == "blocked":
            raise loop.Paused(_blocked_reason(record), target)
        if decision.kind == "unknown":
            raise loop.Paused(
                f"unrecognised outcome {record.status!r} for stage {current_stage_id!r}; "
                "the relay will not guess",
                target,
            )
        if decision.kind == "complete":
            _checkpoint(root, description, "@complete", round_, stage_visits, feedback)
            return
        feedback = record.summary
        current_stage_id = decision.target_stage
        round_ += 1
        stage_visits[current_stage_id] = stage_visits.get(current_stage_id, 0) + 1
        loop.check_visit_cap(pipe, current_stage_id, stage_visits, task)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_planner.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — `planner.py` is new and only self-referenced by its own tests so far.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/planner.py tests/test_planner.py
git commit -m "feat: planner.py drives the draft/review pipeline with crash-safe checkpoints"
```

---

### Task 6: `planner.py` — the human approval gate and CLI-facing entry points

**Files:**
- Modify: `src/whyline_relay/planner.py` (add `start`, `resume`, `discard`, `_human_gate`)
- Test: `tests/test_planner.py`

**Interfaces:**
- Consumes: `_run_pipeline`, `draft_path`, `PlanAlreadyInProgress` (Task 5); `gitcheck.commit_paths`/`ensure_branch` (unchanged); `loop.run_plan` (unchanged); `invocation.command` (unchanged).
- Produces: `planner.start(root, settings, description, *, echo=True, confirm=input, runner=subprocess.run) -> str`, `planner.resume(root, settings, saved, *, echo=True, confirm=input, runner=subprocess.run) -> str`, `planner.discard(root) -> str`. Task 7 (`cli.py`) is the only caller.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_planner.py`:

```python
def _confirm(answers: list[str]):
    def confirm(prompt: str) -> str:
        return answers.pop(0)

    return confirm


def test_start_refuses_when_a_session_is_already_checkpointed(repo, monkeypatch):
    settings = settings_with_planner(repo)
    state.save_plan(
        repo,
        state.PlanState(
            description=DESCRIPTION, stage="draft", round=1, stage_visits={"draft": 1},
            agent="", feedback="", draft_path=str(planner.draft_path(repo)),
            paused_reason="", log_path="",
        ),
    )
    with pytest.raises(planner.PlanAlreadyInProgress):
        planner.start(repo, settings, DESCRIPTION)


def test_approving_writes_and_commits_plan_md_without_starting(repo, monkeypatch):
    settings = settings_with_planner(repo)

    def run(command, prompt, *, cwd, log_path, timeout_seconds, which=None, echo=True, agent_name=None):
        if agent_name == "codex":
            planner.draft_path(repo).write_text("- [ ] T-1: build it\n  Do the thing.\n")
        return _scripted_run(["claude:ready", "claude:approved"])(
            command, prompt, cwd=cwd, log_path=log_path, timeout_seconds=timeout_seconds,
            which=which, echo=echo, agent_name=agent_name,
        )

    monkeypatch.setattr(loop.agents, "run", run)
    result = planner.start(repo, settings, DESCRIPTION, confirm=_confirm(["a", "n"]))
    assert "Wrote" in result
    assert (repo / "plan.md").read_text() == "- [ ] T-1: build it\n  Do the thing.\n"
    assert state.load_plan(repo) is None
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "plan" in log.lower()


def test_discarding_clears_the_checkpoint_and_keeps_the_draft_file(repo, monkeypatch):
    settings = settings_with_planner(repo)

    def run(command, prompt, *, cwd, log_path, timeout_seconds, which=None, echo=True, agent_name=None):
        if agent_name == "codex":
            planner.draft_path(repo).write_text("- [ ] T-1: x\n  y.\n")
        return _scripted_run(["claude:ready", "claude:approved"])(
            command, prompt, cwd=cwd, log_path=log_path, timeout_seconds=timeout_seconds,
            which=which, echo=echo, agent_name=agent_name,
        )

    monkeypatch.setattr(loop.agents, "run", run)
    result = planner.start(repo, settings, DESCRIPTION, confirm=_confirm(["d"]))
    assert "Discarded" in result
    assert state.load_plan(repo) is None
    assert planner.draft_path(repo).exists()
    assert not (repo / "plan.md").exists()


def test_requesting_changes_redrafts_before_the_gate_reappears(repo, monkeypatch):
    settings = settings_with_planner(repo)
    calls = {"n": 0}

    def run(command, prompt, *, cwd, log_path, timeout_seconds, which=None, echo=True, agent_name=None):
        calls["n"] += 1
        spec = ["claude:ready", "claude:approved", "claude:ready", "claude:approved"][calls["n"] - 1]
        if agent_name == "codex":
            planner.draft_path(repo).write_text(f"- [ ] T-1: round {calls['n']}\n  y.\n")
        return _scripted_run([spec])(
            command, prompt, cwd=cwd, log_path=log_path, timeout_seconds=timeout_seconds,
            which=which, echo=echo, agent_name=agent_name,
        )

    monkeypatch.setattr(loop.agents, "run", run)
    result = planner.start(
        repo, settings, DESCRIPTION,
        confirm=_confirm(["r", "make it shorter", "a", "n"]),
    )
    assert "Wrote" in result
    # calls["n"] only advances the draft file's content on the draft (codex)
    # turn: 1 (session 1's draft) writes "round 1", 2 is session 1's review
    # turn (no write), 3 is session 2's draft turn after "request changes"
    # (writes "round 3"), 4 is session 2's review turn. The approved content
    # is whatever the draft stage wrote last -- "round 3" -- proving a real
    # second draft round happened, not a repeat of the first.
    assert "round 3" in (repo / "plan.md").read_text()
    assert "round 1" not in (repo / "plan.md").read_text()


def test_discard_with_no_session_says_so(repo):
    assert planner.discard(repo) == "Nothing to discard."


def test_resuming_at_complete_reprints_the_draft_without_rerunning_any_agent(repo, monkeypatch):
    settings = settings_with_planner(repo)
    planner.draft_path(repo).parent.mkdir(parents=True, exist_ok=True)
    planner.draft_path(repo).write_text("- [ ] T-1: x\n  y.\n")
    saved = state.PlanState(
        description=DESCRIPTION, stage="@complete", round=2, stage_visits={"draft": 1, "review": 1},
        agent="", feedback="", draft_path=str(planner.draft_path(repo)),
        paused_reason="", log_path="",
    )
    state.save_plan(repo, saved)

    def run(*a, **k):
        raise AssertionError("no agent should run when resuming at @complete")

    monkeypatch.setattr(loop.agents, "run", run)
    result = planner.resume(repo, settings, saved, confirm=_confirm(["d"]))
    assert "Discarded" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_planner.py -k "start or discard or resuming_at_complete or requesting_changes" -v`
Expected: FAIL — `AttributeError: module 'whyline_relay.planner' has no attribute 'start'`.

- [ ] **Step 3: Implement**

In `src/whyline_relay/planner.py`, add the import of `invocation` and `loop` already imports `run_plan`-adjacent needs — extend the existing import block at the top:

```python
from whyline_relay import config, failover, gitcheck, handoff, invocation
from whyline_relay import pipeline as pipeline_module
from whyline_relay import plan, prompts, state, whylinecmd
from whyline_relay import loop
```

Add the four new functions at the end of the file:

```python
def start(
    root: Path,
    settings: config.Config,
    description: str,
    *,
    echo: bool = True,
    confirm=input,
    runner: failover.Runner = subprocess.run,
) -> str:
    """Start a brand-new plan session: draft, auto-review, then the human gate."""
    if state.load_plan(root) is not None:
        raise PlanAlreadyInProgress(
            "a plan draft is already in progress; run "
            f"`{invocation.command('resume')}` or `{invocation.command('plan --discard')}`"
        )
    _run_pipeline(root, settings, description, echo=echo, runner=runner)
    return _human_gate(root, settings, description, confirm=confirm, echo=echo, runner=runner)


def resume(
    root: Path,
    settings: config.Config,
    saved: state.PlanState,
    *,
    echo: bool = True,
    confirm=input,
    runner: failover.Runner = subprocess.run,
) -> str:
    """Resume an in-flight plan session from its checkpoint."""
    if saved.stage != "@complete":
        _run_pipeline(
            root, settings, saved.description,
            current_stage_id=saved.stage, round_=saved.round, stage_visits=saved.stage_visits,
            feedback=saved.feedback, consult_handoff=True, echo=echo, runner=runner,
        )
    return _human_gate(
        root, settings, saved.description, confirm=confirm, echo=echo, runner=runner
    )


def discard(root: Path) -> str:
    saved = state.load_plan(root)
    if saved is None:
        return "Nothing to discard."
    state.clear_plan(root)
    return f"Discarded. The draft is still at {saved.draft_path}, if you want it."


def _human_gate(
    root: Path,
    settings: config.Config,
    description: str,
    *,
    confirm=input,
    echo: bool = True,
    runner: failover.Runner = subprocess.run,
) -> str:
    """The three-way human approval gate, reached once the inner pipeline has
    checkpointed "@complete". Reads the draft from disk, not from memory, so a
    resumed session sees exactly the draft a crash interrupted (spec 5.4).
    """
    draft = draft_path(root)
    text = draft.read_text(encoding="utf-8")
    print(text)
    try:
        answer = confirm("Approve, [r]equest changes, or [d]iscard? [A/r/d] ").strip().lower()
    except EOFError:
        answer = "d"

    if answer.startswith("r"):
        try:
            feedback = confirm("What should change? ").strip()
        except EOFError:
            feedback = ""
        _run_pipeline(
            root, settings, description,
            current_stage_id="draft", round_=1, stage_visits={"draft": 1}, feedback=feedback,
            echo=echo, runner=runner,
        )
        return _human_gate(root, settings, description, confirm=confirm, echo=echo, runner=runner)

    if answer.startswith("d"):
        state.clear_plan(root)
        return f"Discarded. The draft is still at {draft}, if you want it."

    target = root / settings.plan
    if target.exists():
        try:
            overwrite = confirm(f"{target} already exists. Replace it? [y/N] ").strip().lower()
        except EOFError:
            overwrite = "n"
        if not overwrite.startswith("y"):
            return f"Not approved: {target} already exists and was not replaced."
    target.write_text(text, encoding="utf-8")
    gitcheck.commit_paths(root, [target], f"docs: add plan drafted by {settings.planner.draft}")
    state.clear_plan(root)
    try:
        start_now = confirm("Start whyline-relay on this plan now? [y/N] ").strip().lower()
    except EOFError:
        start_now = "n"
    if not start_now.startswith("y"):
        return f"Wrote {target}. Run `{invocation.command('start')}` when ready."
    branch = f"{settings.branch_prefix}{target.stem}"
    gitcheck.ensure_branch(root, branch)
    outcomes = loop.run_plan(root, settings, target, branch=branch, only=None)
    return f"Plan complete: {len(outcomes)} task(s) approved and committed."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_planner.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/planner.py tests/test_planner.py
git commit -m "feat: the planner's three-way human approval gate"
```

---

### Task 7: `cli.py` — `plan`/`plan --discard`, and `resume`'s new branch

**Files:**
- Modify: `src/whyline_relay/cli.py`
- Test: `tests/test_planner_cli.py`

**Interfaces:**
- Consumes: `planner.start`/`resume`/`discard`/`PlanAlreadyInProgress` (Task 6), `state.load_plan` (Task 2).
- Produces: `whyline-relay plan "<description>"`, `whyline-relay plan --discard`, `cmd_resume` dispatches to the planner path first.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planner_cli.py`:

```python
import subprocess
from pathlib import Path

import pytest

from whyline_relay import cli, planner, state


def make_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / ".whyline" / "relay").mkdir(parents=True)
    (tmp_path / ".whyline" / "relay" / "config.toml").write_text("")
    return tmp_path


def test_plan_with_no_description_and_no_discard_is_an_error(tmp_path, capsys):
    repo = make_repo(tmp_path)
    assert cli.main(["plan", "--repo", str(repo)]) == cli.EXIT_ERROR
    assert "description is required" in capsys.readouterr().err


def test_plan_discard_with_nothing_in_progress(tmp_path, capsys):
    repo = make_repo(tmp_path)
    assert cli.main(["plan", "--discard", "--repo", str(repo)]) == cli.EXIT_OK
    assert "Nothing to discard" in capsys.readouterr().out


def test_plan_refuses_when_already_in_progress(tmp_path, capsys, monkeypatch):
    repo = make_repo(tmp_path)
    state.save_plan(
        repo,
        state.PlanState(
            description="x", stage="draft", round=1, stage_visits={"draft": 1},
            agent="", feedback="", draft_path=str(planner.draft_path(repo)),
            paused_reason="", log_path="",
        ),
    )
    assert cli.main(["plan", "do a thing", "--repo", str(repo)]) == cli.EXIT_ERROR
    assert "already in progress" in capsys.readouterr().err


def test_resume_dispatches_to_the_planner_when_a_plan_checkpoint_exists(tmp_path, capsys, monkeypatch):
    # planner.resume's own interactive gate is already exercised directly, with
    # an explicit confirm=, by Task 6's tests -- confirm=input is a default
    # bound once at import time, so monkeypatching builtins.input here would
    # not reach it (the same reason tests/test_roles.py and tests/test_init.py
    # always pass confirm= explicitly rather than patching builtins.input).
    # This test proves only cmd_resume's new dispatch branch: a saved PlanState
    # routes to planner.resume instead of falling through to the task-resume path.
    repo = make_repo(tmp_path)
    saved = state.PlanState(
        description="x", stage="@complete", round=1, stage_visits={"draft": 1, "review": 1},
        agent="", feedback="", draft_path=str(planner.draft_path(repo)),
        paused_reason="", log_path="",
    )
    state.save_plan(repo, saved)
    monkeypatch.setattr(planner, "resume", lambda root, settings, plan_state: "Discarded. ok")
    assert cli.main(["resume", "--repo", str(repo)]) == cli.EXIT_OK
    assert "Discarded" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_planner_cli.py -v`
Expected: FAIL — `argparse` rejects the unknown `plan` subcommand (`SystemExit`/`error: argument command: invalid choice`).

- [ ] **Step 3: Implement**

In `src/whyline_relay/cli.py`, add `planner` to the module import block:

```python
from whyline_relay import (
    adapters,
    agents,
    config,
    failover,
    gitcheck,
    init,
    invocation,
    loop,
    notify,
    plan,
    planhelp,
    planner,
    preflight,
    prompts,
    remove,
    roles,
    running,
    state,
    whylinecmd,
)
```

Add the `plan` subparser in `build_parser()`, right after the `plan_format` subparser is built and before `return parser`:

```python
    plan_parser = subparsers.add_parser(
        "plan", help="Draft a plan.md from a free-text description"
    )
    plan_parser.add_argument(
        "description", nargs="?", default=None, help="What to build, in plain language."
    )
    plan_parser.add_argument(
        "--repo", default=".", help="Use this repository root (default: current directory)."
    )
    plan_parser.add_argument(
        "--discard", action="store_true", help="Clear an in-flight plan session without resuming it."
    )
    return parser
```

(this replaces the bare `return parser` that currently follows `plan_format`'s definition)

Add `cmd_plan` near `cmd_plan_format`:

```python
def cmd_plan(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    active = running.live(root)
    if active is not None:
        # Checked before --discard too: discarding a checkpoint out from under
        # a genuinely live turn (a subprocess mid-flight) could race with it --
        # every other command that touches saved state (start, resume, stop)
        # checks this first, before anything else.
        print(
            f"Refusing to touch the plan checkpoint: another relay is running "
            f"here (pid {active.pid}). Run `{invocation.command('stop')}` first.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    if args.discard:
        print(planner.discard(root))
        return EXIT_OK
    if args.description is None:
        print("a description is required (or pass --discard)", file=sys.stderr)
        return EXIT_ERROR
    settings = config.load(root)
    try:
        summary = planner.start(root, settings, args.description)
    except planner.PlanAlreadyInProgress as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    except loop.Paused as paused:
        return _report_pause(paused)
    except (gitcheck.GitError, whylinecmd.WhylineUnavailable) as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    print(summary)
    return EXIT_OK
```

In `cmd_resume`, add the planner branch right after the existing `active is not None` check and before `saved = state.load(root)`:

```python
    plan_state = state.load_plan(root)
    if plan_state is not None:
        settings = config.load(root)
        try:
            summary = planner.resume(root, settings, plan_state)
        except loop.Paused as paused:
            return _report_pause(paused)
        except (gitcheck.GitError, whylinecmd.WhylineUnavailable) as error:
            print(str(error), file=sys.stderr)
            return EXIT_ERROR
        print(summary)
        return EXIT_OK
    saved = state.load(root)
```

Finally, add `"plan": cmd_plan,` to the `commands` dict in `main()`:

```python
        commands = {
            "start": cmd_start,
            "resume": cmd_resume,
            "status": cmd_status,
            "stop": cmd_stop,
            "init": cmd_init,
            "remove": cmd_remove,
            "roles": cmd_roles,
            "doctor": cmd_doctor,
            "plan-format": cmd_plan_format,
            "plan": cmd_plan,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_planner_cli.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — `cmd_resume`'s new branch only triggers when `state.load_plan` finds something, which no existing test ever writes, so every prior `resume` test is unaffected.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/cli.py tests/test_planner_cli.py
git commit -m "feat: whyline-relay plan/plan --discard, and resume dispatches to the planner"
```

---

### Task 8: `preflight.py` — warn on a real task colliding with the reserved plan id

**Files:**
- Modify: `src/whyline_relay/preflight.py` (`_plan_checks`, around line 308's per-task loop)
- Test: `tests/test_preflight.py`

**Interfaces:**
- Consumes: `planner.PLAN_TASK_ID` (Task 5).
- Produces: no new public interface — `_plan_checks` gains one more `warn`-level check.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_preflight.py`:

```python
def test_a_task_named_after_the_reserved_plan_id_warns(ready_repo: Path):
    (ready_repo / "plan.md").write_text("- [ ] __plan__: x\n  y.\n")
    checks = preflight.run(ready_repo, runner=successful_runner())
    assert any(
        c.status == "warn" and "__plan__" in c.message and "reserved" in c.message
        for c in checks
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_preflight.py -k reserved_plan_id -v`
Expected: FAIL — no such warning is produced yet.

- [ ] **Step 3: Implement**

In `src/whyline_relay/preflight.py`, add the import of `planner` to the existing import block:

```python
from whyline_relay import (
    adapters,
    config,
    gitcheck,
    invocation,
    pipeline as pipeline_module,
    plan,
    planner,
    prompts,
    running,
)
```

In `_plan_checks`, inside the existing `for task in tasks:` loop (right after the `if len(task.text.splitlines()) == 1:` warn block, before whatever check follows it), add:

```python
        if task.task_id == planner.PLAN_TASK_ID:
            checks.append(
                _result(
                    "warn",
                    f"task {task.task_id!r} uses the reserved id the planner uses for its "
                    "own handoffs; a real plan.md task with this id can be silently "
                    "confused with a plan-drafting session",
                )
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_preflight.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/preflight.py tests/test_preflight.py
git commit -m "feat: doctor warns if a real plan task collides with the planner's reserved id"
```

---

### Task 9: README — document `whyline-relay plan`

**Files:**
- Modify: `README.md`

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Update the README**

Find the section documenting `plan-format` (or the section introducing how a `plan.md` gets written), and add a new subsection immediately after it:

```markdown
### Drafting a plan instead of writing one by hand

`whyline-relay plan "<free-text description>"` drafts a `plan.md` for you: one agent (`[planner].draft`, defaulting to your implementer) writes a candidate plan, a second agent (`[planner].review`, defaulting to your reviewer) checks it for structural problems only — never whether it's the *right* plan, which stays your call — and bounces it back for another draft if something's missing (`[planner].max_visits`, default 3). Once it passes, you're shown the draft and asked to approve it, request changes with feedback (unbounded — keep iterating as long as you like), or discard it. Approving writes and commits the real `plan.md` and offers to run `whyline-relay start` on it immediately.

```toml
[planner]
draft = "codex"     # defaults to your implementer's agent if omitted
review = "claude"   # defaults to your reviewer's agent if omitted
max_visits = 3
```

A plan session checkpoints the same way a running task does — `whyline-relay resume` picks an interrupted draft/review loop, or an unanswered approval gate, back up; `whyline-relay plan --discard` abandons one without resuming it.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document whyline-relay plan"
```

## Not in this plan

- **Preflight/dirty-tree checks before `plan` itself runs.** Unlike `start`, `plan` doesn't touch git until a human approves, so there's nothing for a preflight pass to protect against beforehand; the ordinary `start` guard still applies once "start now?" is answered yes.
- **`cmd_status` showing an in-flight plan session.** The spec's CLI surface (5.5) only names `plan`/`plan --discard`/`resume`; extending `status` to describe planner state too is a natural follow-up, not required for this piece to work.
- **A non-interactive/`--yes` mode for `plan`.** The human gate is the point of this feature; a scripted, unattended variant is explicitly flagged as unscoped in the spec's risks section (7).
- **Consuming or editing an existing `plan.md`.** `plan` always drafts fresh, per the spec's stated non-goals.
