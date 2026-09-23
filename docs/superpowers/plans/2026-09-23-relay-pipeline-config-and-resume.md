# Pipeline Config + Crash-Safe Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `config.toml` configure a real `[pipeline]` of named stages/profiles (built on 0.2.7's `pipeline.py` engine), and drive it end to end in `loop.py` with crash-safe resume — a task paused mid-pipeline picks back up at the exact stage and visit count it paused at, not from scratch.

**Architecture:** `config.py` compiles `[pipeline]`/`[pipeline.profiles]`/`[pipeline.stages.*]` into a `pipeline.Pipeline` (already built in 0.2.7) plus a content hash (`pipeline_fingerprint`) of that table. `loop.py` gains a second task-runner, `_run_configured_task`, that walks stages via `pipeline.decide()`'s new stage/profile-aware mode instead of the fixed implementer/reviewer pair; `run_task()` dispatches to it whenever `settings.pipeline is not None`. `RelayState` gains additive fields (`profile`, `stage`, `stage_visits`, `pipeline_fingerprint`) written to disk *before* every agent launch, so a crash mid-turn always resumes from the last stage that actually ran, never re-running it and never skipping its already-written handoff.

**Tech Stack:** Python 3.11+, tomllib (stdlib), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-23-relay-n-roles-design.md` (D5 profiles, D8 crash-safe stage cursor). This plan makes the low-level implementation calls the spec leaves open (fingerprint scheme, checkpoint timing, commit-eligibility rule, prompt-placeholder set) — those calls are recorded here, not in the spec.

## Global Constraints

- `[roles.backup]` and `[pipeline]` are mutually exclusive (`ConfigError`) — a configured pipeline has no failover; a stage with no working agent just pauses. Already enforced in `config.py` as of this plan's Task 3; do not add backup support to `_run_configured_task`.
- Hand-written `[status_map]` and `[pipeline]` are mutually exclusive (`ConfigError`) — a pipeline's stages define their own outcome vocabulary via `[pipeline.stages.<id>.on]`.
- No static "unbounded cycle" detection at config-load time. Every stage requires a positive `max_visits` (default 3); the runtime per-stage visit count in `_run_configured_task` already bounds every possible loop shape, so a separate graph analysis would be redundant (YAGNI).
- Relay-side auto-commit ownership (spec D6) is **not** built here. A configured pipeline's terminal-reaching stage still self-commits using the existing HEAD-check-guarded mechanism, generalized from "only the reviewer may commit" to "only a stage whose transitions include a path to `@complete` may commit."
- The relay never pushes, and every agent command is checked for permission-bypass flags before it runs (existing `bypass.find` mechanism) — this plan must not weaken either guarantee for pipeline-mode agents.
- Every existing test in `tests/` must still pass unedited after every task in this plan; `test_routing.py` and `test_pipeline.py`'s existing cases are the regression net for 0.2.7's legacy behavior.

---

### Task 1: `pipeline.decide()` — stage-and-profile-aware routing

**Files:**
- Modify: `src/whyline_relay/pipeline.py` (only `decide()`; `Role`, `Stage`, `Profile`, `Pipeline`, `Decision`, `compile_legacy` are unchanged)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `decide(record, previous_id, pipeline, effective_agents, *, current_stage_id=None, profile_name=None) -> Decision`. `current_stage_id=None` (the default) reproduces exactly today's legacy behavior — checks every stage's transitions. Given `current_stage_id`, only that stage's transitions are checked, and `"@next"` resolves against `pipeline.profiles[profile_name]`'s own stage order. Task 7 is the only new caller of the keyword form.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pipeline.py`:

```python
def test_decide_with_current_stage_only_checks_that_stage():
    # "review"'s status_map transitions must not leak into "draft"'s outcome vocabulary
    # once the caller says which stage actually ran.
    p = Pipeline(
        roles={"implementer": Role("implementer", agent="codex"),
               "reviewer": Role("reviewer", agent="claude")},
        stages={
            "draft": Stage("draft", "implementer", "implement", {"ready": "review"}),
            "review": Stage("review", "reviewer", "review", {"approved": "@complete"}),
        },
        profiles={"full": Profile("full", ("draft", "review"))},
        default_profile="full",
    )
    agents = {"implementer": "codex", "reviewer": "claude"}
    # "approved" is a real outcome of "review", but draft just ran -- must not match.
    record = Handoff(event_id="e1", task="T", to_actor="claude", status="approved", summary="")
    result = decide(record, None, p, agents, current_stage_id="draft", profile_name="full")
    assert result == Decision("unknown", None)


def test_decide_next_resolves_relative_to_the_active_profile():
    # The SAME stage's "@next" means a different target depending on which
    # profile is running it -- this is why decide() cannot resolve "@next" once
    # at compile time the way compile_legacy's fixed two stages can.
    p = Pipeline(
        roles={"implementer": Role("implementer", agent="codex"),
               "tester": Role("tester", agent="claude"),
               "reviewer": Role("reviewer", agent="claude")},
        stages={
            "draft": Stage("draft", "implementer", "implement", {"ready": "@next"}),
            "test": Stage("test", "tester", "test", {"passed": "@next"}),
            "review": Stage("review", "reviewer", "review", {"approved": "@complete"}),
        },
        profiles={
            "full": Profile("full", ("draft", "test", "review")),
            "small": Profile("small", ("draft", "review")),
        },
        default_profile="full",
    )
    agents = {"implementer": "codex", "tester": "claude", "reviewer": "claude"}
    record = Handoff(event_id="e1", task="T", to_actor="claude", status="ready", summary="")
    full = decide(record, None, p, agents, current_stage_id="draft", profile_name="full")
    small = decide(record, None, p, agents, current_stage_id="draft", profile_name="small")
    assert full == Decision("advance", "test")
    assert small == Decision("advance", "review")


def test_decide_next_on_the_last_stage_of_its_profile_is_unknown():
    p = Pipeline(
        roles={"reviewer": Role("reviewer", agent="claude")},
        stages={"review": Stage("review", "reviewer", "review", {"done": "@next"})},
        profiles={"solo": Profile("solo", ("review",))},
        default_profile="solo",
    )
    record = Handoff(event_id="e1", task="T", to_actor="claude", status="done", summary="")
    result = decide(record, None, p, {"reviewer": "claude"}, current_stage_id="review", profile_name="solo")
    assert result == Decision("unknown", None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -k "current_stage or next_resolves or last_stage" -v`
Expected: FAIL — `decide()` does not accept `current_stage_id`/`profile_name` yet (`TypeError: decide() got an unexpected keyword argument`).

- [ ] **Step 3: Implement**

Replace `decide()` in `src/whyline_relay/pipeline.py`:

```python
def decide(
    record: handoff.Handoff | None,
    previous_id: str | None,
    pipeline: Pipeline,
    effective_agents: dict[str, str],
    *,
    current_stage_id: str | None = None,
    profile_name: str | None = None,
) -> Decision:
    """Pick the next move from the handoff record alone.

    Legacy mode (current_stage_id=None, the default): checks every stage's
    transitions for one that accepts this status, reproducing routing.py's
    actual statelessness (see compile_legacy). "@complete" and "@blocked" apply
    regardless of recipient; a real stage target requires the handoff be
    addressed to whoever fills that stage's role.

    Configured-pipeline mode (current_stage_id given): checks only the stage
    that just ran, and resolves "@next" against the named profile's own stage
    sequence -- a stage's "@next" can mean a different next stage depending on
    which profile is running it, so this cannot be resolved once at compile
    time the way compile_legacy's fixed two stages can.

    Never guesses: no match anywhere is "unknown", not a default.
    """
    if record is None or (previous_id is not None and record.event_id == previous_id):
        return Decision("no-handoff", None)
    if current_stage_id is not None:
        candidates = [pipeline.stages[current_stage_id]]
        profile = pipeline.profiles[profile_name] if profile_name else None
    else:
        candidates = list(pipeline.stages.values())
        profile = None
    for stage in candidates:
        target = stage.transitions.get(record.status)
        if target is None:
            continue
        if target == "@next":
            if profile is None:
                continue
            index = profile.stages.index(stage.id)
            if index + 1 >= len(profile.stages):
                continue
            target = profile.stages[index + 1]
        if target == "@blocked":
            return Decision("blocked", None)
        if target == "@complete":
            return Decision("complete", None)
        target_stage = pipeline.stages[target]
        if record.to_actor == effective_agents.get(target_stage.role):
            return Decision("advance", target)
    return Decision("unknown", None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py tests/test_routing.py -v`
Expected: PASS, all of them — including every pre-existing case (this step must not touch `compile_legacy`, and `test_routing.py` must stay byte-for-byte unedited).

- [ ] **Step 5: Commit**

```bash
git add src/whyline_relay/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline.decide() resolves a single stage's transitions and profile-relative @next"
```

---

### Task 2: `RelayState` — crash-safe pipeline fields

**Files:**
- Modify: `src/whyline_relay/state.py`
- Test: `tests/test_state.py` (create if it doesn't already exist — check first with `ls tests/test_state.py`)

**Interfaces:**
- Produces: `RelayState` gains `profile: str = ""`, `stage: str = ""`, `stage_visits: dict[str, int] = field(default_factory=dict)`, `pipeline_fingerprint: str = ""`. All four are empty/absent for a legacy (unconfigured-pipeline) run. Task 7 is the only writer/reader of non-empty values.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_state.py
from pathlib import Path

from whyline_relay import state


def test_pipeline_fields_round_trip(tmp_path: Path):
    value = state.RelayState(
        plan="plan.md", branch="relay/T-1", task_id="T-1", round=2,
        base_commit="abc123", paused_reason="stopped", log_path="",
        profile="full", stage="test", stage_visits={"draft": 1, "test": 1},
        pipeline_fingerprint="deadbeef",
    )
    state.save(tmp_path, value)
    loaded = state.load(tmp_path)
    assert loaded == value


def test_a_state_file_saved_before_this_field_existed_still_loads(tmp_path: Path):
    # An older relay's state.json has none of these keys; RelayState(**record)
    # must fill them from defaults rather than raise.
    import json
    target = state.path(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "plan": "plan.md", "branch": "relay/T-1", "task_id": "T-1", "round": 1,
        "base_commit": "abc", "paused_reason": "x", "log_path": "",
    }))
    loaded = state.load(tmp_path)
    assert loaded.profile == "" and loaded.stage == ""
    assert loaded.stage_visits == {} and loaded.pipeline_fingerprint == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_state.py -v`
Expected: FAIL — `RelayState.__init__()` rejects `profile`/`stage`/`stage_visits`/`pipeline_fingerprint` (`TypeError: unexpected keyword argument`).

- [ ] **Step 3: Implement**

In `src/whyline_relay/state.py`:

```python
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from whyline_relay import config


@dataclass(frozen=True)
class RelayState:
    plan: str
    branch: str
    task_id: str
    round: int
    base_commit: str
    paused_reason: str
    log_path: str
    only: str = ""
    last_handoff_id: str = ""
    # Configured-pipeline resume only (empty/absent for a legacy, unconfigured run).
    profile: str = ""
    stage: str = ""
    stage_visits: dict[str, int] = field(default_factory=dict)
    pipeline_fingerprint: str = ""
```

(The rest of `state.py` — `path`, `save`, `load`, `clear` — is unchanged; `load()`'s `RelayState(**record)` already fills missing keys from these defaults.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_state.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, unchanged count plus the new tests — this field addition must not move any existing assertion.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/state.py tests/test_state.py
git commit -m "feat: RelayState gains additive fields for crash-safe pipeline resume"
```

---

### Task 3: `[pipeline]` config loading and fingerprint

**Files:**
- Modify: `src/whyline_relay/config.py`
- Test: `tests/test_config.py` (add to the existing file)

**Interfaces:**
- Consumes: `pipeline.Role`, `pipeline.Stage`, `pipeline.Profile`, `pipeline.Pipeline` (Task 1's unchanged dataclasses).
- Produces: `Config.pipeline: pipeline_module.Pipeline | None` and `Config.pipeline_fingerprint: str` (empty string when `pipeline` is `None`). `config.load()` raises `ConfigError` for every malformed `[pipeline]` table, described below.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
import pytest

from whyline_relay import config


PIPELINE_TOML = '''
[roles]
implementer = "codex"
tester = "claude"
reviewer = "claude"

[pipeline]
default_profile = "full"

[pipeline.profiles]
full = ["draft", "test", "review"]
quick = ["draft", "review"]

[pipeline.stages.draft]
role = "implementer"
prompt = "implement"
[pipeline.stages.draft.on]
ready = "@next"

[pipeline.stages.test]
role = "tester"
prompt = "test"
max_visits = 5
[pipeline.stages.test.on]
passed = "@next"
failed = "draft"

[pipeline.stages.review]
role = "reviewer"
prompt = "review"
[pipeline.stages.review.on]
approved = "@complete"
rejected = "draft"
'''


def write_config(tmp_path, text):
    target = tmp_path / ".whyline" / "relay" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return tmp_path


def test_a_real_pipeline_parses_correctly(tmp_path):
    settings = config.load(write_config(tmp_path, PIPELINE_TOML))
    pipe = settings.pipeline
    assert pipe is not None
    assert set(pipe.stages) == {"draft", "test", "review"}
    assert pipe.stages["test"].max_visits == 5
    assert pipe.stages["draft"].max_visits == 3  # the default
    assert pipe.profiles["full"].stages == ("draft", "test", "review")
    assert pipe.profiles["quick"].stages == ("draft", "review")
    assert pipe.default_profile == "full"
    assert pipe.roles["tester"].agent == "claude"
    assert pipe.legacy is False
    assert settings.pipeline_fingerprint  # non-empty
    assert settings.backups == {}
    assert settings.status_map == config.DEFAULTS["status_map"]


def test_fingerprint_is_stable_and_sensitive(tmp_path):
    a = config.load(write_config(tmp_path, PIPELINE_TOML))
    b = config.load(write_config(tmp_path, PIPELINE_TOML))
    assert a.pipeline_fingerprint == b.pipeline_fingerprint
    changed = PIPELINE_TOML.replace("max_visits = 5", "max_visits = 6")
    c = config.load(write_config(tmp_path, changed))
    assert c.pipeline_fingerprint != a.pipeline_fingerprint


def test_a_legacy_config_has_no_pipeline_and_an_empty_fingerprint(tmp_path):
    settings = config.load(write_config(tmp_path, '[roles]\nimplementer = "codex"\n'))
    assert settings.pipeline is None
    assert settings.pipeline_fingerprint == ""


@pytest.mark.parametrize("bad_toml, expect_substr", [
    (
        PIPELINE_TOML + '\n[roles.backup]\nimplementer = "claude"\n',
        "[roles.backup] is not supported together with [pipeline]",
    ),
    (
        PIPELINE_TOML + '\n[status_map]\nreview = "needs-review"\n',
        "[status_map] is not supported together with [pipeline]",
    ),
    (
        PIPELINE_TOML.replace('role = "tester"', 'role = "nope"', 1),
        "names role 'nope', which is not in [roles]",
    ),
    (
        PIPELINE_TOML.replace('rejected = "draft"', 'rejected = "nowhere"'),
        "names unknown stage 'nowhere'",
    ),
    (
        '[roles]\nimplementer = "codex"\n[pipeline]\ndefault_profile = "full"\n'
        '[pipeline.profiles]\nfull = ["only"]\n[pipeline.stages.only]\n'
        'role = "implementer"\nprompt = "implement"\n[pipeline.stages.only.on]\n'
        'ready = "@next"\n',
        'uses "@next" on the last stage of profile',
    ),
    (
        '[roles]\nimplementer = "codex"\n[pipeline]\ndefault_profile = "full"\n'
        '[pipeline.profiles]\nfull = ["only"]\n[pipeline.stages.only]\n'
        'role = "implementer"\nprompt = "implement"\n[pipeline.stages.only.on]\n'
        'ready = "blocked-forever"\n',
        'has no stage that can reach "@complete"',
    ),
    (
        PIPELINE_TOML.replace('default_profile = "full"', 'default_profile = "nonexistent"'),
        "default_profile must name a profile",
    ),
])
def test_pipeline_validation_errors(tmp_path, bad_toml, expect_substr):
    with pytest.raises(config.ConfigError, match=re.escape(expect_substr)):
        config.load(write_config(tmp_path, bad_toml))
```

Add `import re` to the top of `tests/test_config.py` if it isn't already imported.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -k pipeline -v`
Expected: FAIL — `[pipeline]` is silently ignored today (0.2.7's documented, deliberate behavior), so `settings.pipeline` is `None` and none of the `ConfigError`s fire.

- [ ] **Step 3: Implement**

In `src/whyline_relay/config.py`, add the import and two new fields, then the fingerprint and loader functions, then restructure `load()`.

Top of file:

```python
import hashlib
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from whyline_relay import adapters, pipeline as pipeline_module
```

`Config` dataclass — add two fields at the end:

```python
@dataclass(frozen=True)
class Config:
    plan: str
    max_rounds: int
    timeout_minutes: int
    branch_prefix: str
    agents: dict[str, list[str]]
    status_map: dict[str, str]
    roles: Roles = field(default_factory=Roles)
    adapters: dict[str, str] = field(default_factory=dict)
    backups: dict[str, str] = field(default_factory=dict)
    pipeline: "pipeline_module.Pipeline | None" = None
    pipeline_fingerprint: str = ""
```

New functions, placed above `Config` (after `Roles`):

```python
def _pipeline_fingerprint(raw_pipeline: dict) -> str:
    """A short hash of the whole [pipeline] table, for crash-safe resume.

    A paused task's saved stage/visit counts only mean what they meant when it
    paused. If [pipeline] changes before `resume`, this changes too, so the
    relay can refuse to guess rather than replay stale stage state against a
    reshaped graph.
    """
    canonical = json.dumps(raw_pipeline, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _load_pipeline(raw_pipeline: dict, role_names: dict[str, str]) -> "pipeline_module.Pipeline":
    """Compile [pipeline]/[pipeline.profiles]/[pipeline.stages.*] into a Pipeline.

    "@next" is intentionally left unresolved here: the same stage can mean a
    different next stage in different profiles, so pipeline.decide() resolves
    it live, against whichever profile is actually running -- see pipeline.py.
    """
    stages_raw = raw_pipeline.get("stages") or {}
    if not stages_raw:
        raise ConfigError("[pipeline] needs at least one stage under [pipeline.stages.<id>]")
    stages: dict[str, pipeline_module.Stage] = {}
    for stage_id, table in stages_raw.items():
        role = table.get("role")
        if not isinstance(role, str) or not role:
            raise ConfigError(f"[pipeline.stages.{stage_id}] needs a role")
        if role not in role_names:
            raise ConfigError(
                f"[pipeline.stages.{stage_id}] names role {role!r}, which is not in [roles]"
            )
        prompt_name = table.get("prompt")
        if not isinstance(prompt_name, str) or not prompt_name:
            raise ConfigError(f"[pipeline.stages.{stage_id}] needs a prompt")
        on = table.get("on") or {}
        if not isinstance(on, dict) or not on:
            raise ConfigError(
                f"[pipeline.stages.{stage_id}] needs at least one outcome under "
                f"[pipeline.stages.{stage_id}.on]"
            )
        transitions: dict[str, str] = {}
        for outcome, target in on.items():
            if not isinstance(target, str) or not target:
                raise ConfigError(
                    f"[pipeline.stages.{stage_id}.on] {outcome!r} must be a non-empty string"
                )
            transitions[outcome] = target
        max_visits = table.get("max_visits", 3)
        if not isinstance(max_visits, int) or isinstance(max_visits, bool) or max_visits < 1:
            raise ConfigError(f"[pipeline.stages.{stage_id}] max_visits must be a positive integer")
        stages[stage_id] = pipeline_module.Stage(
            id=stage_id, role=role, prompt=prompt_name, transitions=transitions,
            max_visits=max_visits,
        )

    profiles_raw = raw_pipeline.get("profiles") or {}
    if not profiles_raw:
        raise ConfigError("[pipeline] needs at least one profile under [pipeline.profiles]")
    profiles: dict[str, pipeline_module.Profile] = {}
    for name, stage_list in profiles_raw.items():
        if not isinstance(stage_list, list) or not stage_list:
            raise ConfigError(f"[pipeline.profiles] {name!r} needs a non-empty list of stage ids")
        for sid in stage_list:
            if sid not in stages:
                raise ConfigError(f"[pipeline.profiles] {name!r} names unknown stage {sid!r}")
        profiles[name] = pipeline_module.Profile(name=name, stages=tuple(stage_list))

    default_profile = raw_pipeline.get("default_profile")
    if not isinstance(default_profile, str) or default_profile not in profiles:
        raise ConfigError(
            "[pipeline] default_profile must name a profile under [pipeline.profiles]"
        )

    for stage in stages.values():
        for outcome, target in stage.transitions.items():
            if target in ("@complete", "@blocked"):
                continue
            if target == "@next":
                containing = [p for p in profiles.values() if stage.id in p.stages]
                if not containing:
                    raise ConfigError(
                        f'[pipeline.stages.{stage.id}.on] {outcome!r} uses "@next" but '
                        f"stage {stage.id!r} is not in any profile"
                    )
                for prof in containing:
                    index = prof.stages.index(stage.id)
                    if index + 1 >= len(prof.stages):
                        raise ConfigError(
                            f'[pipeline.stages.{stage.id}.on] {outcome!r} uses "@next" on '
                            f"the last stage of profile {prof.name!r}"
                        )
                continue
            if target not in stages:
                raise ConfigError(
                    f"[pipeline.stages.{stage.id}.on] {outcome!r} names unknown stage {target!r}"
                )

    for prof in profiles.values():
        reaches_complete = False
        for index, sid in enumerate(prof.stages):
            for target in stages[sid].transitions.values():
                resolved = target
                if target == "@next":
                    resolved = prof.stages[index + 1] if index + 1 < len(prof.stages) else None
                if resolved == "@complete":
                    reaches_complete = True
        if not reaches_complete:
            raise ConfigError(
                f'[pipeline.profiles] {prof.name!r} has no stage that can reach "@complete"'
            )

    roles = {name: pipeline_module.Role(name=name, agent=agent) for name, agent in role_names.items()}
    return pipeline_module.Pipeline(
        roles=roles, stages=stages, profiles=profiles,
        default_profile=default_profile, legacy=False,
    )
```

In `load()`, find where `role_values = raw.get("roles") or {}` is computed (immediately followed by the unknown-key check for `implementer`/`reviewer`/`backup`). Restructure that section:

```python
role_values = raw.get("roles") or {}
raw_pipeline = raw.get("pipeline")

if raw_pipeline is not None:
    if "backup" in role_values:
        raise ConfigError("[roles.backup] is not supported together with [pipeline]")
    if "status_map" in raw:
        raise ConfigError(
            "[status_map] is not supported together with [pipeline]; a pipeline's "
            "stages use their own outcome labels"
        )
    role_names: dict[str, str] = {}
    for key, value in role_values.items():
        if not isinstance(value, str):
            raise ConfigError(f"[roles] {key} must be a string")
        role_names[key] = value
    for role, name in role_names.items():
        if name not in adapters.BUILTIN and name not in configured_adapters:
            builtins = ", ".join(sorted(adapters.BUILTIN))
            raise ConfigError(
                f"role '{role}' names '{name}', which is not a built-in agent "
                f"({builtins}) or a configured generic agent"
            )
    compiled_pipeline = _load_pipeline(raw_pipeline, role_names)
    pipeline_fp = _pipeline_fingerprint(raw_pipeline)
    backup_values: dict[str, str] = {}
    status_map = dict(DEFAULTS["status_map"])
    roles_obj = Roles()
else:
    # <everything load() already does today for role_values/status_map/backups,
    #  completely unchanged: the unknown-key check for implementer/reviewer/backup,
    #  the role_names dict, the per-role agent-existence check, the backup_values
    #  validation loop>
    compiled_pipeline = None
    pipeline_fp = ""
    status_map = {**DEFAULTS["status_map"], **(raw.get("status_map") or {})}
    roles_obj = Roles(**role_names)
```

And the final `return Config(...)`:

```python
return Config(
    plan=raw.get("plan", DEFAULTS["plan"]),
    max_rounds=int(raw.get("max_rounds", DEFAULTS["max_rounds"])),
    timeout_minutes=int(raw.get("timeout_minutes", DEFAULTS["timeout_minutes"])),
    branch_prefix=raw.get("branch_prefix", DEFAULTS["branch_prefix"]),
    agents=agents,
    status_map=status_map,
    roles=roles_obj,
    adapters=configured_adapters,
    backups=dict(backup_values),
    pipeline=compiled_pipeline,
    pipeline_fingerprint=pipeline_fp,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS. Every existing config test (including the plain `[roles.backup]`-only and plain `[status_map]`-only cases) must be unaffected, since `raw_pipeline is None` takes the untouched `else` branch.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/config.py tests/test_config.py
git commit -m "feat: config.py compiles a real [pipeline] table into a Pipeline, with a resume fingerprint"
```

---

### Task 4: `plan.py` — the `relay-profile:` task directive

**Files:**
- Modify: `src/whyline_relay/plan.py`
- Test: `tests/test_plan.py`

**Interfaces:**
- Produces: `Task.profile: str | None` — `None` when the task's detail has no `relay-profile:` line, else the exact name after the colon. Task 7 uses it (falling back to `pipeline.default_profile`); Task 8 validates it in `doctor`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_plan.py`:

```python
def test_relay_profile_directive_is_parsed():
    content = (
        "- [ ] T-1: build the thing\n"
        "  relay-profile: full\n"
        "  more detail here\n"
        "- [ ] T-2: a plain task\n"
        "  no directive on this one\n"
    )
    tasks = plan.parse(content)
    assert tasks[0].profile == "full"
    assert tasks[1].profile is None


def test_relay_profile_directive_requires_a_name():
    content = "- [ ] T-1: build the thing\n  relay-profile:\n"
    assert plan.parse(content)[0].profile is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plan.py -k relay_profile -v`
Expected: FAIL — `Task` has no `profile` attribute (`AttributeError`).

- [ ] **Step 3: Implement**

In `src/whyline_relay/plan.py`:

```python
CHECKBOX = re.compile(r"^(?P<indent>\s*)- \[(?P<mark>[ xX])\]\s+(?P<body>.*)$")
RELAY_PROFILE = re.compile(r"(?m)^relay-profile:\s*(\S+)\s*$")


class PlanError(ValueError):
    """The plan file cannot be used as written."""


@dataclass(frozen=True)
class Task:
    task_id: str
    text: str
    checked: bool
    line_index: int
    profile: str | None = None
```

In `parse()`, where `text` is assembled and the `Task(...)` is appended:

```python
        text = "\n".join([body, *_dedent(detail)])
        match = RELAY_PROFILE.search(text)
        tasks.append(
            Task(
                task_id=task_id, text=text, checked=match.group("mark") != " ",
                line_index=index, profile=match_ if (match_ := RELAY_PROFILE.search(text)) else None,
            )
        )
```

Simplify that to avoid the double search — write it as:

```python
        text = "\n".join([body, *_dedent(detail)])
        profile_match = RELAY_PROFILE.search(text)
        tasks.append(
            Task(
                task_id=task_id,
                text=text,
                checked=match.group("mark") != " ",
                line_index=index,
                profile=profile_match.group(1) if profile_match else None,
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plan.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — `Task.profile` defaults to `None`, so every existing `Task(...)` construction in other tests is unaffected.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/plan.py tests/test_plan.py
git commit -m "feat: plan.py parses an optional relay-profile: directive per task"
```

---

### Task 5: `prompts.py` — a real error for a missing custom prompt, plus new placeholders

**Files:**
- Modify: `src/whyline_relay/prompts.py`
- Test: `tests/test_prompts.py`

**Interfaces:**
- Produces: `PromptError(ValueError)`, raised by `load()` instead of an unhandled `KeyError`. `render()` gains four optional keyword parameters — `actor`, `role`, `stage`, `profile` — each defaulting to `""`, substituted into `{actor}`/`{role}`/`{stage}`/`{profile}`. `PLACEHOLDERS` lists all four names for documentation purposes. Task 6 is the only caller that passes non-default values.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prompts.py`:

```python
import pytest

from whyline_relay import prompts


def test_load_raises_a_clear_error_for_an_unknown_prompt_with_no_override(tmp_path):
    with pytest.raises(prompts.PromptError, match="tester"):
        prompts.load(tmp_path, "tester")


def test_load_finds_a_user_override_for_a_custom_stage_name(tmp_path):
    prompt_dir = prompts.prompts_dir(tmp_path)
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "tester.md").write_text("Test {task_id} as {actor}, stage {stage}.")
    assert prompts.load(tmp_path, "tester") == "Test {task_id} as {actor}, stage {stage}."


def test_render_substitutes_the_new_placeholders():
    rendered = prompts.render(
        "You are {actor}, role {role}, on stage {stage} of profile {profile}.",
        task_id="T-1", task_text="x", sync_packet="", round_=1, review_feedback="",
        actor="claude-fast", role="tester", stage="test", profile="full",
    )
    assert rendered == "You are claude-fast, role tester, on stage test of profile full."


def test_render_output_for_the_builtin_templates_is_unchanged():
    # New optional kwargs must not appear in output when the caller omits them --
    # the built-in IMPLEMENT/REVIEW templates never reference {actor}/{role}/{stage}/{profile}.
    before = prompts.render(
        prompts.IMPLEMENT, task_id="T-1", task_text="do it", sync_packet="PACKET",
        round_=1, review_feedback="",
    )
    after = prompts.render(
        prompts.IMPLEMENT, task_id="T-1", task_text="do it", sync_packet="PACKET",
        round_=1, review_feedback="", actor="codex", role="implementer",
        stage="implement", profile="default",
    )
    assert before == after
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prompts.py -v`
Expected: FAIL — `prompts.PromptError` doesn't exist yet (`AttributeError`), and `render()` rejects the new keyword arguments (`TypeError`).

- [ ] **Step 3: Implement**

In `src/whyline_relay/prompts.py`:

```python
PLACEHOLDERS = (
    "task_id",
    "task_text",
    "sync_packet",
    "round",
    "review_feedback",
    "implementer",
    "reviewer",
    "actor",
    "role",
    "stage",
    "profile",
)


class PromptError(ValueError):
    """A stage names a prompt with no built-in template and no user override."""


TEMPLATES = {"implement": IMPLEMENT, "review": REVIEW}


def prompts_dir(root: Path) -> Path:
    return root / ".whyline" / "relay" / "prompts"


def load(root: Path, name: str) -> str:
    """Return the user's template for `name`, falling back to the built-in one.

    Raises PromptError, not KeyError, when neither exists: a configured
    pipeline's stage can name any prompt, not only "implement"/"review".
    """
    candidate = prompts_dir(root) / f"{name}.md"
    try:
        return candidate.read_text(encoding="utf-8")
    except OSError:
        pass
    try:
        return TEMPLATES[name]
    except KeyError:
        raise PromptError(
            f"no prompt named {name!r}: no built-in template for it, and "
            f"{candidate} does not exist"
        ) from None


def render(
    template: str,
    *,
    task_id: str,
    task_text: str,
    sync_packet: str,
    round_: int,
    review_feedback: str,
    implementer: str = "codex",
    reviewer: str = "claude",
    actor: str = "",
    role: str = "",
    stage: str = "",
    profile: str = "",
) -> str:
    """Substitute the placeholders.

    str.replace, not str.format: the templates carry JSON and shell braces, and
    .format would raise on the first one it met.
    """
    rendered = template.replace("{implementer}", implementer).replace(
        "{reviewer}", reviewer
    )
    values = {
        "{task_id}": task_id,
        "{task_text}": task_text,
        "{sync_packet}": sync_packet,
        "{round}": str(round_),
        "{review_feedback}": review_feedback or "(none — this is the first round)",
        "{actor}": actor,
        "{role}": role,
        "{stage}": stage,
        "{profile}": profile,
    }
    for placeholder, value in values.items():
        rendered = rendered.replace(placeholder, value)
    return rendered
```

(`IMPLEMENT`/`REVIEW` string constants above `TEMPLATES` are unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_prompts.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/prompts.py tests/test_prompts.py
git commit -m "feat: prompts.py raises PromptError for a missing custom stage prompt, adds actor/role/stage/profile placeholders"
```

---

### Task 6: `loop.py` plumbing — behavior-preserving groundwork for Task 7

**Files:**
- Modify: `src/whyline_relay/loop.py` (only `_run_agent`, `_run_task`'s `on_turn` call, `run_task`'s type hint, `_save_pause`, `_run_plan`'s `on_turn` closure)
- Test: `tests/test_loop_single.py` (add one case), plus the existing suite as the regression net

**Interfaces:**
- Consumes: nothing new from earlier tasks (Task 7 is what actually uses `pipeline`/`state`'s new pieces).
- Produces: `on_turn` is now always called with **three** positional arguments — `on_turn(round_, previous_id, stage_state)` — where `stage_state` is `{}` for every legacy call (this task) and a populated dict for configured-pipeline calls (Task 7). `_run_agent` gains optional keyword parameters `action_label`, `log_suffix`, `actor`, `stage`, `profile` (all `None`/`""` by default, so every existing call site is unaffected). `_save_pause` reads an optional `"stage_state"` key out of `progress` and writes it into `RelayState`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_loop_single.py`:

```python
def test_on_turn_is_called_with_a_stage_state_dict(repo: Path, monkeypatch):
    settings = settings_using("review", "approve", repo)
    real_run = loop.agents.run

    def run_then_commit(command, prompt, **kwargs):
        code = real_run(command, prompt, **kwargs)
        if "approve" in command:
            commit_for_task(repo)
        return code

    monkeypatch.setattr(loop.agents, "run", run_then_commit)
    seen = []

    def on_turn(round_, previous_id, stage_state):
        seen.append(stage_state)

    base = loop.gitcheck.head_commit(repo)
    loop.run_task(repo, settings, TASK, base_commit=base, echo=False, on_turn=on_turn)
    assert seen and all(state == {} for state in seen)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_loop_single.py -k stage_state -v`
Expected: FAIL — `on_turn` is currently called with two arguments (`TypeError: on_turn() missing 1 required positional argument`).

- [ ] **Step 3: Implement**

In `src/whyline_relay/loop.py`, update `_run_agent`'s signature and body:

```python
def _run_agent(
    root: Path,
    settings: config.Config,
    agent: str,
    role: str,
    template_name: str,
    task: plan.Task,
    round_: int,
    review_feedback: str,
    echo: bool,
    *,
    implementer: str,
    reviewer: str,
    action_label: str | None = None,
    log_suffix: str | None = None,
    actor: str = "",
    stage: str = "",
    profile: str = "",
    runner: failover.Runner = subprocess.run,
) -> Path:
    """Render the prompt, run the agent, and return the log path."""
    command = settings.agents[agent]
    adapter = config.adapter_for(settings, agent)
    found = bypass.find(adapter.name, command)
    if found:
        raise Paused(
            f"refusing to run {agent}: its command contains a permission-bypass "
            f"flag ({', '.join(found)}). The relay never runs an agent that way; "
            "remove it from .whyline/relay/config.toml",
            None,
        )
    running.start_turn(root, agent, task.task_id, round_, role=role)
    packet = whylinecmd.sync(root, task.task_id)
    prompt = prompts.render(
        prompts.load(root, template_name),
        task_id=task.task_id,
        task_text=task.text,
        sync_packet=packet,
        round_=round_,
        review_feedback=review_feedback,
        implementer=implementer,
        reviewer=reviewer,
        actor=actor,
        role=role,
        stage=stage,
        profile=profile,
    )
    log_role = log_suffix if log_suffix is not None else (role if implementer == reviewer else "")
    target = log_path(root, task.task_id, round_, agent, log_role)
    action = action_label or ("implementing" if role == "implementer" else "reviewing")
    if echo:
        agents.print_status(
            f"==> {agent}: {action} {task.task_id} "
            f"(round {round_} of {settings.max_rounds})"
        )
    started = time.monotonic()
    try:
        try:
            agents.run(
                command,
                prompt,
                cwd=root,
                log_path=target,
                timeout_seconds=settings.timeout_minutes * 60,
                echo=echo,
                agent_name=agent,
            )
        finally:
            if echo:
                agents.print_status(
                    f"<== {agent} finished in "
                    f"{agents.format_duration(time.monotonic() - started)}"
                )
    except agents.AgentTimeout as error:
        raise Paused(str(error), target) from error
    except agents.AgentMissing as error:
        raise Paused(str(error), target) from error
    return target
```

In `_run_task`, change the `Callable` type hint and the one call site:

```python
    on_turn: Callable[[int, str | None, dict], None] | None = None,
```

```python
        if on_turn is not None:
            on_turn(round_, previous_id, {})
```

In `run_task`, change the type hint to match (`Callable[[int, str | None, dict], None] | None = None`); its body is otherwise unchanged in this task (Task 7 adds the dispatch).

In `_save_pause`, read the new key:

```python
def _save_pause(
    root: Path,
    plan_path: Path,
    branch: str,
    task: plan.Task,
    base_commit: str,
    reason: str,
    log: Path | None,
    only: str | None,
    progress: dict,
) -> None:
    stage_state = progress.get("stage_state") or {}
    state.save(
        root,
        state.RelayState(
            plan=str(plan_path),
            branch=branch,
            task_id=task.task_id,
            round=progress["round"],
            base_commit=base_commit,
            paused_reason=reason,
            log_path=str(log or ""),
            only=only or "",
            last_handoff_id=progress["last"] or "",
            profile=stage_state.get("profile", ""),
            stage=stage_state.get("stage", ""),
            stage_visits=stage_state.get("stage_visits", {}),
            pipeline_fingerprint=stage_state.get("pipeline_fingerprint", ""),
        ),
    )
```

In `_run_plan`, update the `on_turn` closure:

```python
        def on_turn(round_: int, previous_id: str | None, stage_state: dict) -> None:
            progress["round"] = round_
            progress["last"] = previous_id
            progress["stage_state"] = stage_state
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_loop_single.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — every existing `test_loop_*.py` file must be unedited and green. This is the regression net proving Task 6 changed nothing observable for a legacy run.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/loop.py tests/test_loop_single.py
git commit -m "refactor: loop.py's on_turn carries a stage_state dict; _run_agent gains optional stage-aware params"
```

---

### Task 7: `loop.py` — `_run_configured_task` and the `run_task` dispatch

**Files:**
- Modify: `src/whyline_relay/loop.py` (add imports, `_check_visit_cap`, `_run_configured_task`; change `run_task` to dispatch)
- Test: `tests/test_loop_pipeline.py` (new file), `tests/fake_pipeline_agent.py` (new fixture script)

**Interfaces:**
- Consumes: `pipeline.Pipeline`/`pipeline.decide()` (Task 1), `Config.pipeline`/`pipeline_fingerprint` (Task 3), `RelayState`'s new fields (Task 2), `Task.profile` (Task 4), `prompts.render()`'s new placeholders (Task 5), `on_turn`'s 3-arg contract and `_run_agent`'s new params (Task 6).
- Produces: `_run_configured_task(root, settings, task, *, base_commit, echo=True, resume=False, start_round=1, on_turn=None, runner=subprocess.run) -> Outcome` — same contract shape as `_run_task`. `run_task()` calls it whenever `settings.pipeline is not None`, else calls `_run_task` exactly as before.

- [ ] **Step 1: Write the fixture agent**

Create `tests/fake_pipeline_agent.py`:

```python
"""A fake agent for configured-pipeline tests: argv[1] is "to_actor:status",
or "commit:to_actor:status" to also make a git commit before handing off."""
import json
import re
import subprocess
import sys
from pathlib import Path


def main() -> int:
    spec = sys.argv[1]
    root = Path(sys.argv[2])
    prompt = sys.argv[-1]
    match = re.search(r"^## Task (\S+)", prompt, re.M)
    task_id = match.group(1) if match else "T-1"

    parts = spec.split(":")
    make_commit = parts[0] == "commit"
    to_actor, status = parts[-2], parts[-1]

    if make_commit:
        (root / "feature.txt").write_text("x\n")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"feat: x ({task_id})"],
            cwd=root, check=True, capture_output=True,
        )

    target = root / ".whyline" / "active-handoff.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(target.read_text()) if target.exists() else {}
    counter = int(previous.get("counter", 0)) + 1
    target.write_text(json.dumps({
        "id": f"event{counter}", "counter": counter, "task": task_id,
        "to_actor": to_actor, "status": status, "summary": f"fake {spec}",
        "from_actor": "",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_loop_pipeline.py`:

```python
import subprocess
import sys
from pathlib import Path

import pytest

from whyline_relay import config, loop, plan, pipeline as pipeline_module, state

FAKE = str(Path(__file__).parent / "fake_pipeline_agent.py")


def make_pipeline(max_visits=3):
    return pipeline_module.Pipeline(
        roles={
            "implementer": pipeline_module.Role("implementer", agent="codex"),
            "tester": pipeline_module.Role("tester", agent="claude"),
            "reviewer": pipeline_module.Role("reviewer", agent="claude"),
        },
        stages={
            "draft": pipeline_module.Stage("draft", "implementer", "implement", {"ready": "@next"}, max_visits),
            "test": pipeline_module.Stage("test", "tester", "test", {"passed": "@next", "failed": "draft"}, max_visits),
            "review": pipeline_module.Stage("review", "reviewer", "review", {"approved": "@complete", "rejected": "draft"}, max_visits),
        },
        profiles={"full": pipeline_module.Profile("full", ("draft", "test", "review"))},
        default_profile="full",
    )


def settings_with_pipeline(root: Path, pipe: pipeline_module.Pipeline, fingerprint="fp1") -> config.Config:
    base = config.load(root)
    return config.Config(
        plan=base.plan, max_rounds=10, timeout_minutes=base.timeout_minutes,
        branch_prefix=base.branch_prefix,
        agents={"codex": ["codex"], "claude": ["claude"]},
        status_map=base.status_map, pipeline=pipe, pipeline_fingerprint=fingerprint,
    )


TASK = plan.Task(task_id="T-1", text="T-1: build it", checked=False, line_index=0)


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
    monkeypatch.setattr(loop.whylinecmd, "sync", lambda root, task, runner=None: "PACKET")
    monkeypatch.setattr(loop.whylinecmd, "claim", lambda *a, **k: None)
    return tmp_path


def head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _scripted_run(specs: list[str]):
    """Stand in for agents.run: pops the next "[commit:]to_actor:status" spec and
    actually invokes fake_pipeline_agent.py with it, so the real handoff (and,
    for a "commit:"-prefixed spec, the real git commit) happens exactly as a
    genuine agent turn would produce it. Matches agents.run's real signature."""

    def run(command, prompt, *, cwd, log_path, timeout_seconds, which=None, echo=True, agent_name=None):
        spec = specs.pop(0)
        result = subprocess.run(
            [sys.executable, FAKE, spec, str(cwd), prompt],
            cwd=cwd, capture_output=True, text=True,
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(result.stdout + result.stderr)
        return result.returncode

    return run


def test_a_three_stage_pipeline_runs_end_to_end_with_a_bounce_back(repo, monkeypatch):
    pipe = make_pipeline()
    settings = settings_with_pipeline(repo, pipe)
    # draft -> ready (tester); test -> failed (implementer); draft -> ready (tester);
    # test -> passed (reviewer); review -> commit:approved (task complete)
    monkeypatch.setattr(loop.agents, "run", _scripted_run([
        "claude:ready", "codex:failed", "claude:ready", "claude:passed", "commit:claude:approved",
    ]))

    outcome = loop.run_task(repo, settings, TASK, base_commit=head(repo), echo=False)
    assert outcome.committed is True
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    assert "(T-1)" in subject


def test_a_stage_hitting_its_visit_cap_pauses_instead_of_looping(repo, monkeypatch):
    pipe = make_pipeline(max_visits=1)
    settings = settings_with_pipeline(repo, pipe)
    monkeypatch.setattr(loop.agents, "run", _scripted_run(["claude:ready", "codex:failed"]))

    with pytest.raises(loop.Paused, match="1-visit cap"):
        loop.run_task(repo, settings, TASK, base_commit=head(repo), echo=False)


def test_a_non_terminal_stage_committing_is_refused(repo, monkeypatch):
    pipe = make_pipeline()
    settings = settings_with_pipeline(repo, pipe)
    monkeypatch.setattr(loop.agents, "run", _scripted_run(["commit:claude:ready"]))

    with pytest.raises(loop.Paused, match="only a stage that can reach"):
        loop.run_task(repo, settings, TASK, base_commit=head(repo), echo=False)


def test_resume_reconstructs_stage_and_advances_past_the_unrouted_handoff(repo, monkeypatch):
    pipe = make_pipeline()
    settings = settings_with_pipeline(repo, pipe)
    # Simulate a crash right after draft wrote its handoff but before it was routed:
    # state.json says we were about to run "draft" for its 1st visit, and the
    # handoff already on disk says draft finished with "ready".
    (repo / ".whyline" / "active-handoff.json").write_text(
        '{"id": "event1", "task": "T-1", "to_actor": "claude", "status": "ready", '
        '"summary": "x", "from_actor": ""}'
    )
    state.save(repo, state.RelayState(
        plan="plan.md", branch="relay/T-1", task_id="T-1", round=1,
        base_commit=head(repo), paused_reason="crash", log_path="",
        profile="full", stage="draft", stage_visits={"draft": 1},
        pipeline_fingerprint=settings.pipeline_fingerprint,
    ))
    monkeypatch.setattr(loop.agents, "run", _scripted_run(["claude:passed", "commit:claude:approved"]))

    outcome = loop.run_task(repo, settings, TASK, base_commit=head(repo), echo=False, resume=True)
    assert outcome.committed is True


def test_resume_with_a_drifted_fingerprint_pauses_before_running_anything(repo, monkeypatch):
    pipe = make_pipeline()
    settings = settings_with_pipeline(repo, pipe, fingerprint="fp-new")
    state.save(repo, state.RelayState(
        plan="plan.md", branch="relay/T-1", task_id="T-1", round=1,
        base_commit=head(repo), paused_reason="crash", log_path="",
        profile="full", stage="draft", stage_visits={"draft": 1},
        pipeline_fingerprint="fp-old",
    ))
    called: list[str] = []
    monkeypatch.setattr(loop.agents, "run", lambda *a, **k: called.append("ran"))

    with pytest.raises(loop.Paused, match="pipeline has changed"):
        loop.run_task(repo, settings, TASK, base_commit=head(repo), echo=False, resume=True)
    assert called == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_loop_pipeline.py -v`
Expected: FAIL — `run_task` has no configured-pipeline path yet, so every test falls into `_run_task`, which reads `settings.roles`/`settings.status_map` and does not understand this shape.

- [ ] **Step 4: Implement**

Add `pipeline` to `loop.py`'s import block (alphabetical, between `invocation` and `plan`):

```python
from whyline_relay import (
    adapters,
    agents,
    config,
    failover,
    gitcheck,
    handoff,
    invocation,
    pipeline,
    plan,
    prompts,
    routing,
    running,
    state,
    whylinecmd,
)
```

Add `_check_visit_cap` near `_blocked_reason`:

```python
def _check_visit_cap(
    pipe: pipeline.Pipeline, stage_id: str, stage_visits: dict[str, int], task: plan.Task
) -> None:
    cap = pipe.stages[stage_id].max_visits
    if stage_visits[stage_id] > cap:
        raise Paused(
            f"{task.task_id} hit stage {stage_id!r}'s {cap}-visit cap without "
            'reaching "@complete"',
            None,
        )
```

Add `_run_configured_task`, placed after `_run_task`:

```python
def _run_configured_task(
    root: Path,
    settings: config.Config,
    task: plan.Task,
    *,
    base_commit: str,
    echo: bool = True,
    resume: bool = False,
    start_round: int = 1,
    on_turn: Callable[[int, str | None, dict], None] | None = None,
    runner: failover.Runner = subprocess.run,
) -> Outcome:
    """Drive one task through a configured [pipeline], stage by stage.

    Mirrors _run_task's contract and most of its per-turn checks (task
    mismatch, from_actor, blocked, unknown, no-handoff/timeout) but routes on
    pipeline.decide() against the stage that just ran, not a fixed pair of
    roles. [roles.backup] is refused together with [pipeline] at config load
    (see config.py), so there is no failover branch here: a no-handoff always
    pauses -- there is never a backup to switch to.

    With `resume`, state.json's saved stage/profile/stage_visits pick the task
    back up where it paused. State is checkpointed (via `on_turn`) before every
    agent launch, never after: a crash before that checkpoint lands re-enters
    the same turn; a crash after it but before the agent's own handoff write
    also re-enters the same turn (the checkpoint never claims a turn happened
    until it's about to). A crash after the agent already wrote its handoff is
    caught here by re-deciding on whatever handoff already exists before the
    main loop restarts, so it is never re-run and never silently dropped.
    """
    pipe = settings.pipeline
    effective_agents = {name: role.agent for name, role in pipe.roles.items()}
    round_ = start_round
    feedback = ""
    gitcheck.ensure_relay_ignored(root)

    start_profile = task.profile or pipe.default_profile
    start_stage_id = pipe.profiles[start_profile].stages[0]
    whylinecmd.claim(
        root, task.task_id, pipe.roles[pipe.stages[start_stage_id].role].agent,
        pipe.stages[start_stage_id].role,
    )

    saved = state.load(root) if resume else None
    if resume and saved is not None and saved.task_id == task.task_id and saved.stage:
        if saved.pipeline_fingerprint != settings.pipeline_fingerprint:
            raise Paused(
                f"{task.task_id} was paused mid-pipeline, but [pipeline] has changed "
                "since then; its saved stage and visit counts no longer match the "
                "configured graph. Resolve by hand before resuming",
                None,
            )
        profile_name = saved.profile
        current_stage_id = saved.stage
        stage_visits = dict(saved.stage_visits)
        current = handoff.read(root)
        if current is not None and current.task == task.task_id:
            resumed = pipeline.decide(
                current, None, pipe, effective_agents,
                current_stage_id=current_stage_id, profile_name=profile_name,
            )
            if resumed.kind == "advance":
                current_stage_id = resumed.target_stage
                stage_visits[current_stage_id] = stage_visits.get(current_stage_id, 0) + 1
                _check_visit_cap(pipe, current_stage_id, stage_visits, task)
                feedback = current.summary
            elif resumed.kind == "complete":
                return _approved(root, task, base_commit, round_, None)
            elif resumed.kind == "blocked":
                raise Paused(_blocked_reason(current.from_actor or "agent", current), None)
            # "unknown"/"no-handoff": current_stage_id/stage_visits stand; re-run it.
    else:
        profile_name = start_profile
        current_stage_id = start_stage_id
        stage_visits = {current_stage_id: 1}

    implementer_agent = pipe.roles["implementer"].agent if "implementer" in pipe.roles else ""
    reviewer_agent = pipe.roles["reviewer"].agent if "reviewer" in pipe.roles else ""

    while True:
        stage = pipe.stages[current_stage_id]
        agent = pipe.roles[stage.role].agent
        previous = handoff.read(root)
        previous_id = previous.event_id if previous else None
        head_before = gitcheck.head_commit(root)
        stage_state = {
            "profile": profile_name,
            "stage": current_stage_id,
            "stage_visits": dict(stage_visits),
            "pipeline_fingerprint": settings.pipeline_fingerprint,
        }
        if on_turn is not None:
            on_turn(round_, previous_id, stage_state)

        target = _run_agent(
            root, settings, agent, stage.role, stage.prompt, task, round_, feedback, echo,
            implementer=implementer_agent, reviewer=reviewer_agent,
            action_label=stage.id, log_suffix=stage.id,
            actor=agent, stage=current_stage_id, profile=profile_name,
            runner=runner,
        )
        may_commit = "@complete" in stage.transitions.values()
        if not may_commit and gitcheck.head_commit(root) != head_before:
            raise Paused(
                f"{agent} made a commit in stage {current_stage_id!r}, which the relay "
                "forbids: only a stage that can reach \"@complete\" may commit. Undo it "
                f"with `git reset {head_before[:12]}` (your files stay), then resume",
                target,
            )

        record = handoff.read(root)
        decision = pipeline.decide(
            record, previous_id, pipe, effective_agents,
            current_stage_id=current_stage_id, profile_name=profile_name,
        )

        if decision.kind == "no-handoff":
            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            adapter = config.adapter_for(settings, agent)
            reason = failover.failover_reason(adapter, text, settings.agents[agent], runner=runner)
            if reason is not None:
                existing = failover.read_overrides(root).get(stage.role)
                raise Paused(failover.pause_message(agent, stage.role, reason, existing), target)
            raise Paused(
                f"{agent} exited without handing off"
                f"{_no_handoff_detail(target, adapter)}; nothing was routed",
                target,
            )
        if record.task != task.task_id:
            raise Paused(
                f"{agent} handed off for {record.task!r}, but this run is on "
                f"{task.task_id!r}; the relay will not guess",
                target,
            )
        if record.from_actor and record.from_actor.strip().lower() != agent.lower():
            raise Paused(
                f"{agent} recorded its handoff as from {record.from_actor!r}, not "
                f"{agent!r}. Check the prompt templates in .whyline/relay/prompts; "
                f"after changing [pipeline] or [roles], run "
                f"`{invocation.command('init')} --overwrite`",
                target,
            )
        if decision.kind == "blocked":
            raise Paused(_blocked_reason(agent, record), target)
        if decision.kind == "unknown":
            raise Paused(
                f"unrecognised outcome {record.status!r} for stage {current_stage_id!r}; "
                "the relay will not guess",
                target,
            )
        if decision.kind == "complete":
            return _approved(root, task, base_commit, round_, target)

        feedback = record.summary
        current_stage_id = decision.target_stage
        stage_visits[current_stage_id] = stage_visits.get(current_stage_id, 0) + 1
        _check_visit_cap(pipe, current_stage_id, stage_visits, task)
        round_ += 1
        if round_ > settings.max_rounds:
            raise Paused(
                f"{task.task_id} hit the {settings.max_rounds}-round cap without "
                'reaching "@complete"',
                target,
            )
```

Change `run_task`'s body to dispatch:

```python
def run_task(
    root: Path,
    settings: config.Config,
    task: plan.Task,
    *,
    base_commit: str,
    echo: bool = True,
    resume: bool = False,
    start_round: int = 1,
    on_turn: Callable[[int, str | None, dict], None] | None = None,
    _clear_running: bool = True,
    runner: failover.Runner = subprocess.run,
) -> Outcome:
    """Drive one task and clear its live marker when used outside ``run_plan``."""
    driver = _run_configured_task if settings.pipeline is not None else _run_task
    try:
        return driver(
            root,
            settings,
            task,
            base_commit=base_commit,
            echo=echo,
            resume=resume,
            start_round=start_round,
            on_turn=on_turn,
            runner=runner,
        )
    finally:
        if _clear_running:
            running.clear(root)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_loop_pipeline.py -v`
Expected: PASS, all five.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — every pre-existing test, including all of `test_loop_*.py` (legacy path, dispatched to `_run_task` since `settings.pipeline is None` in every one of them).

- [ ] **Step 7: Commit**

```bash
git add src/whyline_relay/loop.py tests/test_loop_pipeline.py tests/fake_pipeline_agent.py
git commit -m "feat: loop.py drives a configured [pipeline] stage by stage with crash-safe resume"
```

---

### Task 8: `preflight.py` — pipeline-aware checks

**Files:**
- Modify: `src/whyline_relay/preflight.py`
- Test: `tests/test_preflight.py` (add to the existing file)

**Interfaces:**
- Consumes: `Config.pipeline` (Task 3), `Task.profile` (Task 4), `prompts.PromptError` (Task 5).
- Produces: `_agents_in_use()` now covers a configured pipeline's real agents (fixing a real gap: today it always reads `settings.roles.implementer`/`.reviewer`, which are meaningless placeholders for a configured pipeline, so `doctor`'s bypass-flag and generic-agent warnings silently never checked a pipeline's actual agents). `run()` FAILs when a stage's `prompt` doesn't resolve, and when a task's `relay-profile:` names an unknown profile; it warns when a task names `relay-profile:` but no `[pipeline]` is configured.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_preflight.py`, reusing the file's existing `_git` helper (already defined at module level — do not redefine it):

```python
PIPELINE_TOML = '''
[roles]
implementer = "codex"
tester = "claude"
reviewer = "claude"

[pipeline]
default_profile = "full"

[pipeline.profiles]
full = ["draft", "test", "review"]

[pipeline.stages.draft]
role = "implementer"
prompt = "implement"
[pipeline.stages.draft.on]
ready = "@next"

[pipeline.stages.test]
role = "tester"
prompt = "test"
[pipeline.stages.test.on]
passed = "@next"
failed = "draft"

[pipeline.stages.review]
role = "reviewer"
prompt = "review"
[pipeline.stages.review.on]
approved = "@complete"
rejected = "draft"
'''


def _pipeline_repo(tmp_path: Path, extra_toml: str = "") -> Path:
    """A git repo with a real [pipeline] config -- no override for the "test"
    stage's prompt, so it has no built-in template and no override file: this
    is the unresolvable-prompt case Task 5's PromptError exists for."""
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True)
    codex_cmd = f'["{sys.executable}", "codex-role"]'
    claude_cmd = f'["{sys.executable}", "claude-role"]'
    (relay / "config.toml").write_text(
        PIPELINE_TOML
        + f'\n[agents.codex]\ncommand = {codex_cmd}\n'
        + f'[agents.claude]\ncommand = {claude_cmd}\n'
        + extra_toml
    )
    (tmp_path / "plan.md").write_text("- [ ] T-1: build it\n  Include tests.\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "setup")
    return tmp_path


def test_a_bypass_flag_on_a_pipeline_agent_is_caught(tmp_path):
    # Regression proof for the _agents_in_use fix: before it, doctor's bypass
    # check only ever looked at settings.roles.implementer/.reviewer, which are
    # meaningless placeholders once [pipeline] is configured -- a pipeline's
    # real agents (here, "claude", filling both "tester" and "reviewer") went
    # completely unchecked.
    root = _pipeline_repo(tmp_path)
    config_path = root / ".whyline" / "relay" / "config.toml"
    config_path.write_text(
        config_path.read_text().replace(
            f'command = ["{sys.executable}", "claude-role"]',
            f'command = ["{sys.executable}", "claude-role", "--dangerously-skip-permissions"]',
        )
    )
    checks = preflight.run(root, runner=successful_runner())
    assert any(c.status == "FAIL" and "permission-bypass" in c.message for c in checks)


def test_a_stage_naming_an_unresolvable_prompt_fails(tmp_path):
    root = _pipeline_repo(tmp_path)
    checks = preflight.run(root, runner=successful_runner())
    assert any(c.status == "FAIL" and "no prompt named 'test'" in c.message for c in checks)


def test_a_task_naming_an_unknown_relay_profile_fails(tmp_path):
    root = _pipeline_repo(tmp_path)
    prompt_dir = root / ".whyline" / "relay" / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "test.md").write_text("Test {task_id} as {actor}.")
    (root / "plan.md").write_text("- [ ] T-1: x\n  relay-profile: nonexistent\n")
    checks = preflight.run(root, root / "plan.md", runner=successful_runner())
    assert any(
        c.status == "FAIL" and "relay-profile" in c.message and "nonexistent" in c.message
        for c in checks
    )


def test_a_task_naming_relay_profile_with_no_pipeline_configured_warns(ready_repo: Path):
    (ready_repo / "plan.md").write_text("- [ ] T-1: x\n  relay-profile: full\n")
    checks = preflight.run(ready_repo, runner=successful_runner())
    assert any(c.status == "warn" and "relay-profile" in c.message for c in checks)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_preflight.py -k "bypass_flag_on_a_pipeline or unresolvable_prompt or unknown_relay_profile or relay_profile_with_no_pipeline" -v`
Expected: FAIL — `_agents_in_use` doesn't look at `settings.pipeline`, so the bypass check never fires; there is no prompt-resolution check yet; `_plan_checks` doesn't know about `task.profile` yet.

- [ ] **Step 3: Implement**

In `src/whyline_relay/preflight.py`, generalize `_agents_in_use`:

```python
def _agents_in_use(
    settings: config.Config,
) -> dict[str, tuple[list[str], str | None]]:
    agents: dict[str, tuple[list[str], str | None]] = {}
    if settings.pipeline is not None:
        for role in settings.pipeline.roles.values():
            if role.agent not in agents:
                agents[role.agent] = (settings.agents[role.agent], None)
        return agents
    for role in ("implementer", "reviewer"):
        name = getattr(settings.roles, role)
        if name not in agents:
            agents[name] = (settings.agents[name], None)
    for role, name in settings.backups.items():
        if name not in agents:
            agents[name] = (settings.agents[name], role)
    return agents
```

In `_role_checks`, guard the implementer==reviewer warning (it means nothing once `[pipeline]` is set, since `settings.roles` is then just an unused placeholder — see `config.py`'s `_load_pipeline` branch):

```python
    if settings.pipeline is None and roles.implementer == roles.reviewer:
        checks.append(
            _result(
                "warn",
                f"{roles.implementer} is both the implementer and the reviewer, "
                "so the review is not independent",
            )
        )
```

In `_plan_checks`, accept the pipeline and validate `task.profile`:

```python
def _plan_checks(
    plan_path: Path, pipeline: "pipeline_module.Pipeline | None" = None
) -> list[Check]:
    if not plan_path.is_file():
        return [_result("FAIL", f"plan file does not exist: {plan_path}")]
    try:
        content = plan_path.read_text(encoding="utf-8")
        tasks = plan.parse(content)
    except (OSError, UnicodeError, plan.PlanError) as error:
        return [_result("FAIL", str(error))]

    checks: list[Check] = []
    if plan.next_unchecked(tasks) is None:
        checks.append(_result("FAIL", f"no unchecked tasks in {plan_path}"))
    else:
        checks.append(_result("ok", f"plan parses and has unchecked tasks: {plan_path}"))
    for task in tasks:
        title = task.text.splitlines()[0]
        if ":" not in title:
            checks.append(
                _result(
                    "warn",
                    f"task {task.task_id!r} has no ID before a colon; its id is its first word",
                )
            )
        if len(task.text.splitlines()) == 1:
            checks.append(_result("warn", f"task {task.task_id!r} has no detail lines"))
        if task.profile is not None:
            if pipeline is None:
                checks.append(
                    _result(
                        "warn",
                        f"task {task.task_id!r} names relay-profile {task.profile!r}, "
                        "but no [pipeline] is configured; it will be ignored",
                    )
                )
            elif task.profile not in pipeline.profiles:
                checks.append(
                    _result(
                        "FAIL",
                        f"task {task.task_id!r} names relay-profile {task.profile!r}, "
                        "which is not in [pipeline.profiles]",
                    )
                )
    return checks
```

Add the `pipeline_module` import at the top of the file (needed for the type hint's string form to resolve if ever unquoted; the quoted string form used above needs no import at runtime, but add it anyway for clarity and for the new stage-prompt check below):

```python
from whyline_relay import adapters, config, gitcheck, invocation, pipeline as pipeline_module, plan, prompts, running
```

In `run()`, update the `_plan_checks` call site and add the new prompt-resolution check right after `_role_checks`:

```python
    if settings is not None:
        results.extend(_logins(root, settings, runner))
        results.extend(_role_checks(root, settings))
        if settings.pipeline is not None:
            for stage in settings.pipeline.stages.values():
                try:
                    prompts.load(root, stage.prompt)
                except prompts.PromptError as error:
                    results.append(
                        _result(
                            "FAIL",
                            str(error),
                            f"add .whyline/relay/prompts/{stage.prompt}.md, or name a "
                            "built-in prompt (implement, review) instead",
                        )
                    )

    selected_plan = plan_path
    if selected_plan is None:
        selected_plan = root / (
            settings.plan if settings is not None else config.DEFAULTS["plan"]
        )
    elif not selected_plan.is_absolute():
        selected_plan = root / selected_plan
    results.extend(
        _plan_checks(selected_plan, settings.pipeline if settings is not None else None)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_preflight.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — the `_agents_in_use` generalization must produce byte-identical output to before whenever `settings.pipeline is None` (every existing preflight test), and the `implementer==reviewer` guard must still fire exactly as before for every legacy config.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/preflight.py tests/test_preflight.py
git commit -m "fix: doctor checks a configured pipeline's real agents and stage prompts, not the unused legacy roles placeholder"
```

---

## Not in this plan

- Relay-side commit ownership (spec D6) — a configured pipeline's commits still happen the way today's reviewer's do: the agent itself runs `git commit`, HEAD-checked afterward.
- The `init`/`roles set` wizard extensions (spec D11) for authoring a `[pipeline]` table interactively — this plan only makes the table something `config.toml` can express by hand.
- Tester/security-review stage *content* (spec D9) — this plan makes an arbitrary custom stage nameable and routable; it does not ship a built-in tester or security prompt template. A `[pipeline]` stage naming `prompt = "test"` needs a real `.whyline/relay/prompts/test.md` written by the user (Task 8's new `doctor` check exists specifically to catch it if they forget).
- Static graph analysis for unreachable or unbounded cycles beyond the per-stage `max_visits` cap and the "reaches @complete" check already in Task 3 — deliberately deferred per the Global Constraints section (YAGNI: the runtime cap already bounds every case).
