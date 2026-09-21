# whyline-relay Implementation Plan

> **Roles for building this plan:** **Codex is the developer.** **Claude is the reviewer and the only committer.** Codex implements a task and hands off without committing; Claude reviews the working-tree diff, runs the tests itself, and commits on approval or sends the task back. Read "Roles and handoff protocol" below before dispatching any task. Do not implement tasks with subagents or inline. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone `whyline-relay` tool that runs a Markdown task plan through Codex (implementer) and Claude (reviewer and committer) unattended, routing solely on whyline's own handoff record.

**Architecture:** A deterministic subprocess driver. Pure functions parse the plan, read `.whyline/active-handoff.json`, and decide the next move; thin wrappers launch `codex` and `claude` in headless mode and tee their output. One module (`loop.py`) makes decisions; everything else is a pure function or a subprocess call. No model, no API keys, no output parsing for routing.

**Tech Stack:** Python 3.11+, standard library only (`subprocess`, `json`, `tomllib`, `pathlib`, `signal`, `threading`, `dataclasses`), pytest for tests, hatchling for packaging.

**Spec:** `/Users/anish/agentdock/docs/superpowers/specs/2026-09-20-whyline-relay-design.md` — read it before starting. The plan argues from the spec; where they disagree, the spec wins and the disagreement is a bug in this plan.

## Global Constraints

- **New repository.** All work happens in `/Users/anish/whyline-relay`, a fresh local git repo with no remote. Nothing in `/Users/anish/agentdock` is modified by this plan.
- **Python 3.11+**, `requires-python = ">=3.11"`. `tomllib` is stdlib from 3.11.
- **Zero runtime dependencies.** `dependencies = []`. pytest is a dev dependency only. This matches whyline's rule.
- **Standard library only** in `src/whyline_relay/`.
- **Never** emit `--dangerously-skip-permissions`, `--dangerously-bypass-approvals-and-sandbox`, or `--dangerously-bypass-hook-trust` in any code path, default, template, or test.
- **Never** run `git push` from any code path.
- **No vendor process in the test suite.** Tests use fake agent scripts. A test run must never launch real `codex` or `claude`, and must never spend subscription quota.
- **Binary lookup is late-bound.** Resolve executables through a module-level function called at invocation time. Never cache `shutil.which` in a default argument or module constant. whyline's `runner.py` carries comments from two incidents (2026-08-17, 2026-08-18) where this exact mistake execed the real Claude Code from a test run.
- **Default agent commands** (verified in a real run against `codex-cli 0.155.1` and `claude 2.1.278`; the prompt is always appended as the final argument):
  - Codex: `["codex", "exec", "-s", "workspace-write", "--color", "never"]`
  - Claude: `["claude", "-p", "--permission-mode", "acceptEdits", "--output-format", "json", "--settings", ".whyline/relay/claude-settings.json"]` (added by Task 8b: `acceptEdits` alone denies every Bash command, and a project `.claude/settings.json` allowlist is ignored until the workspace is trusted interactively; `--settings` is honored regardless)
- **Codex is not sandboxed from committing.** Measured on `codex-cli 0.155.1`: asked to `git commit` under `-s workspace-write`, it did. "Codex never commits" is enforced by the relay (Task 8b checks that HEAD did not move after every Codex turn), not by the sandbox.
- **Default status strings:** `ready-for-review`, `changes-requested`, `approved`, `blocked`, `assigned`.
- **Milestone gate:** after Task 8 (M2), STOP and hand back to the owner for a watched real-CLI run before starting Task 9. This gate is in the spec (§11) and is not optional.

**Deviation from the spec's module table (§4), deliberate:** this plan splits four
modules out of what the spec drew as `loop.py` and `cli.py` — `routing.py` (the
routing table as a pure function, so every decision is testable without a
subprocess), `state.py` (the resume record), `whylinecmd.py` (the two whyline
commands the relay issues), and `init.py` (the permission writer). Same
responsibilities, smaller files. Nothing else in the spec changes.

## Roles and handoff protocol

This section governs how *this plan is built*. The tool it builds applies the same split at run time (Codex implements, Claude reviews and commits), so building it by hand is a manual run of the workflow it will automate.

| Role | Who | Does | Never |
|---|---|---|---|
| Developer | Codex | Writes the code and tests a task specifies, runs the tests, records decisions, hands off | `git add`, `git commit`, `git push`; edits this plan; starts the next task |
| Reviewer and committer | Claude | Reviews the diff, runs the tests, checks Global Constraints, commits on approval, sends back on rejection | Fixes a rejected task itself. It sends the task back to Codex. A defect in the plan is the exception: Claude fixes the plan, then re-dispatches |
| Owner | The human | Decides anything marked `blocked`; approving Codex hook trust is optional (the dispatch prompt runs `whyline sync` itself, and hooks fired under `codex exec` in the M2 run regardless) | — |

**Task ids.** Task *n* is `RELAY-<n>`. The id appears in every handoff, every `whyline note`, and every commit message.

**Status of the build.** Tasks 1-4 were built before this split. Claude implemented them and they are committed in `/Users/anish/whyline-relay` (`b3a156e`, `1ef5300`, `7ae7ac3`, `9b7dde2`); the ledger records a review only for Task 1. Their Commit steps ran under the old workflow and must not be re-run. **Tasks 5-13 follow this protocol.** Task 8 (M2) is committed and its real-CLI run is done; the findings are Task 8b, which comes before Task 9. **Tasks 8-13 were pre-reviewed before dispatch:** their code was assembled in a scratch copy exactly as written, run, and probed with real processes and repositories. Every defect found is fixed in the text below and marked "Revised after pre-review"; the new tests were confirmed to fail on the original code and pass on the fixed code.

**One-time setup, before Task 5** (Claude, in `/Users/anish/whyline-relay`, which has no `.whyline` yet):

1. `whyline init --yes`, then commit the result as `chore: whyline init (RELAY-0)`.
2. Owner opens `/hooks` in Codex in that directory and approves the project hook. Trust applies only to future Codex sessions, so do this before the first dispatch. Until then Codex gets no automatic sync, which is why the dispatch prompt below runs `whyline sync` explicitly.

**Per-task loop.**

1. **Assign (Claude).** Record HEAD (`git rev-parse HEAD`), then:

   ```bash
   cd /Users/anish/whyline-relay
   whyline handoff RELAY-<n> --from claude --to codex --status assigned --summary "Task <n>: <title>"
   ```

2. **Dispatch (Claude).** Launch Codex headless with the prompt below. The owner may run the same command in a second terminal to watch. `-s workspace-write` does **not** stop Codex committing (measured on `codex-cli 0.155.1`: asked to commit, it did), so the prompt forbids it and Claude verifies in step 4 that HEAD is unmoved; from Task 8b the relay checks this too.

   ```bash
   cd /Users/anish/whyline-relay
   codex exec -s workspace-write --color never "<prompt>"
   ```

   ````text
   Run `whyline sync` first.

   You are the developer for RELAY-<n>. Claude reviews and commits; you do not.

   Read the spec: /Users/anish/agentdock/docs/superpowers/specs/2026-09-20-whyline-relay-design.md
   Then implement Task <n> from /Users/anish/agentdock/docs/superpowers/plans/2026-09-20-whyline-relay.md
   exactly as written, following its Global Constraints. Do not edit the plan. Do not start any other task.

   Do not run `git add`, `git commit` or `git push`. Skip the git commands in the task's final step.
   Run the task's tests and note the exact command and result.

   Record any genuine decision a future reader would wonder about:
     whyline note "<decision>" --because "<why>" --rejected "<option>: <why not>" \
       --file <path> --actor codex --role implementer --task RELAY-<n>

   Finish by handing off exactly once:
     whyline handoff RELAY-<n> --from codex --to claude --status ready-for-review \
       --summary "<what you changed>" --file <each file you touched> \
       --test "<command>: <result>" --risk "<anything the reviewer should check>"

   If you cannot finish, hand off with --status blocked and a --question. Do not exit without handing off.
   ````

   On a re-dispatch after `changes-requested`, append: `Review feedback to address: <Claude's summary>`.

3. **Wait.** Codex works the task's steps, skips the git commands in the final step, and hands off `ready-for-review`.

4. **Review (Claude).** Do all of these; do not trust Codex's reported result:
   - `git rev-parse HEAD` equals the value recorded in step 1 (Codex made no commit), and `git status --short` shows only files the task's **Files** list names.
   - Read the whole `git diff` against the task's steps and interfaces. Flag scope creep and any deviation from the spec.
   - Run `uv run pytest -v` yourself and confirm it matches the handoff's `--test` claim.
   - Check the Global Constraints: no `--dangerously-*` flag, no `git push` executed, no cached `shutil.which`, no test that launches a real `codex` or `claude`.
   - Record the ruling: `whyline note "<ruling>" --because "<why>" --file <path> --actor claude --role reviewer --task RELAY-<n>`.

5. **Decide (Claude).** Exactly one:
   - **Approve.** Run the task's final step (the commit block), then `whyline handoff RELAY-<n> --from claude --to claude --status approved --summary "<what you approved>"`.
   - **Request changes.** Do not commit. `whyline handoff RELAY-<n> --from claude --to codex --status changes-requested --summary "<specific, actionable change>"`, then re-dispatch (step 2). After 3 rounds (the tool's own default `max_rounds`), stop and report to the owner instead of a fourth.
   - **Blocked.** Stop and ask the owner.

**Milestone gate.** After RELAY-8 is approved and committed, STOP for the owner's watched real-CLI run before dispatching Task 9, as Global Constraints require.

---

### Task 1: Repository scaffold and configuration

Creates the repo, the package skeleton, and `config.py`. Configuration is first because every later module takes a `Config`.

**Files:**
- Create: `/Users/anish/whyline-relay/pyproject.toml`
- Create: `/Users/anish/whyline-relay/.gitignore`
- Create: `/Users/anish/whyline-relay/src/whyline_relay/__init__.py`
- Create: `/Users/anish/whyline-relay/src/whyline_relay/config.py`
- Test: `/Users/anish/whyline-relay/tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `config.Config` dataclass with fields `plan: str`, `max_rounds: int`, `timeout_minutes: int`, `branch_prefix: str`, `agents: dict[str, list[str]]`, `status_map: dict[str, str]`; `config.DEFAULTS: dict`; `config.load(root: Path) -> Config`.

- [ ] **Step 1: Create the repository and directories**

```bash
mkdir -p /Users/anish/whyline-relay/src/whyline_relay /Users/anish/whyline-relay/tests
cd /Users/anish/whyline-relay
git init
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "whyline-relay"
version = "0.1.0"
description = "Runs a planned task list through Codex and Claude, routing on whyline handoffs."
requires-python = ">=3.11"
license = "Apache-2.0"
readme = "README.md"
authors = [{ name = "Anish Varghese" }]
dependencies = []

[project.scripts]
whyline-relay = "whyline_relay.cli:entry"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/whyline_relay"]

[tool.hatch.build.targets.sdist]
only-include = ["src/whyline_relay", "tests", "README.md", "LICENSE"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[dependency-groups]
dev = ["pytest>=8.0"]
```

Create `README.md` with a single line for now: `# whyline-relay` — hatchling needs the file to exist.

- [ ] **Step 3: Write `.gitignore`**

```
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
dist/
*.egg-info/
.DS_Store
```

- [ ] **Step 4: Write the failing test**

`tests/test_config.py`:

```python
from pathlib import Path

from whyline_relay import config


def test_defaults_when_no_file(tmp_path: Path):
    loaded = config.load(tmp_path)
    assert loaded.plan == "plan.md"
    assert loaded.max_rounds == 3
    assert loaded.timeout_minutes == 30
    assert loaded.branch_prefix == "relay/"
    assert loaded.agents["codex"][0] == "codex"
    assert loaded.agents["claude"][0] == "claude"
    assert loaded.status_map["review"] == "ready-for-review"


def test_file_overrides_only_given_keys(tmp_path: Path):
    target = tmp_path / ".whyline" / "relay"
    target.mkdir(parents=True)
    (target / "config.toml").write_text(
        'max_rounds = 5\n\n[agents.codex]\ncommand = ["codex", "exec"]\n'
    )
    loaded = config.load(tmp_path)
    assert loaded.max_rounds == 5
    assert loaded.agents["codex"] == ["codex", "exec"]
    assert loaded.timeout_minutes == 30
    assert loaded.agents["claude"][0] == "claude"


def test_malformed_toml_raises_config_error(tmp_path: Path):
    target = tmp_path / ".whyline" / "relay"
    target.mkdir(parents=True)
    (target / "config.toml").write_text("max_rounds = [unclosed\n")
    try:
        config.load(tmp_path)
    except config.ConfigError as error:
        assert "config.toml" in str(error)
    else:
        raise AssertionError("expected ConfigError")
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'whyline_relay'` or `AttributeError: module has no attribute 'load'`.

- [ ] **Step 6: Write `src/whyline_relay/__init__.py`**

```python
"""Runs a planned task list through Codex and Claude."""

__version__ = "0.1.0"
```

- [ ] **Step 7: Write `src/whyline_relay/config.py`**

```python
"""Relay configuration: built-in defaults, overridden by .whyline/relay/config.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULTS = {
    "plan": "plan.md",
    "max_rounds": 3,
    "timeout_minutes": 30,
    "branch_prefix": "relay/",
    "agents": {
        "codex": ["codex", "exec", "-s", "workspace-write", "--color", "never"],
        "claude": [
            "claude",
            "-p",
            "--permission-mode",
            "acceptEdits",
            "--output-format",
            "json",
        ],
    },
    "status_map": {
        "review": "ready-for-review",
        "changes": "changes-requested",
        "approved": "approved",
        "blocked": "blocked",
        "assigned": "assigned",
    },
}


class ConfigError(ValueError):
    """The config file exists but cannot be used."""


@dataclass(frozen=True)
class Config:
    plan: str
    max_rounds: int
    timeout_minutes: int
    branch_prefix: str
    agents: dict[str, list[str]]
    status_map: dict[str, str]


def relay_dir(root: Path) -> Path:
    return root / ".whyline" / "relay"


def config_path(root: Path) -> Path:
    return relay_dir(root) / "config.toml"


def load(root: Path) -> Config:
    """Read config.toml if present, layering it over DEFAULTS."""
    path = config_path(root)
    raw: dict = {}
    if path.exists():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError) as error:
            raise ConfigError(f"could not read {path.name} ({path}): {error}") from error
    agents = dict(DEFAULTS["agents"])
    for name, table in (raw.get("agents") or {}).items():
        command = table.get("command")
        if command is not None:
            agents[name] = list(command)
    status_map = {**DEFAULTS["status_map"], **(raw.get("status_map") or {})}
    return Config(
        plan=raw.get("plan", DEFAULTS["plan"]),
        max_rounds=int(raw.get("max_rounds", DEFAULTS["max_rounds"])),
        timeout_minutes=int(raw.get("timeout_minutes", DEFAULTS["timeout_minutes"])),
        branch_prefix=raw.get("branch_prefix", DEFAULTS["branch_prefix"]),
        agents=agents,
        status_map=status_map,
    )
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd /Users/anish/whyline-relay && uv run pytest -v`
Expected: 3 passed.

- [ ] **Step 9: Commit**

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: repository scaffold and relay configuration"
```

---

### Task 2: Plan file parsing and ticking

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/plan.py`
- Test: `/Users/anish/whyline-relay/tests/test_plan.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `plan.Task` frozen dataclass with fields `task_id: str`, `text: str`, `checked: bool`, `line_index: int`; `plan.parse(content: str) -> list[Task]`; `plan.next_unchecked(tasks: list[Task]) -> Task | None`; `plan.find(tasks: list[Task], task_id: str) -> Task | None`; `plan.tick(content: str, task_id: str) -> str`; `plan.PlanError`.

`Task.text` is the full task block handed to the implementer: the checkbox line with `- [ ] ` stripped, plus any indented detail lines dedented by their common leading whitespace.

- [ ] **Step 1: Write the failing test**

`tests/test_plan.py`:

```python
import pytest

from whyline_relay import plan

SAMPLE = """# Plan

- [x] WL-0: Scaffold the module
- [ ] WL-1: Add bounded cache invalidation
      Cache must evict on write, not on a timer.
      Keep the public API unchanged.
- [ ] WL-2: Add cache metrics
"""


def test_parse_finds_every_task_in_order():
    tasks = plan.parse(SAMPLE)
    assert [task.task_id for task in tasks] == ["WL-0", "WL-1", "WL-2"]
    assert [task.checked for task in tasks] == [True, False, False]


def test_task_text_includes_dedented_detail_block():
    tasks = plan.parse(SAMPLE)
    assert tasks[1].text == (
        "WL-1: Add bounded cache invalidation\n"
        "Cache must evict on write, not on a timer.\n"
        "Keep the public API unchanged."
    )


def test_task_without_detail_is_just_its_title():
    tasks = plan.parse(SAMPLE)
    assert tasks[2].text == "WL-2: Add cache metrics"


def test_next_unchecked_skips_checked_tasks():
    assert plan.next_unchecked(plan.parse(SAMPLE)).task_id == "WL-1"


def test_next_unchecked_returns_none_when_all_done():
    assert plan.next_unchecked(plan.parse("- [x] WL-1: Done\n")) is None


def test_tick_marks_only_the_named_task():
    updated = plan.tick(SAMPLE, "WL-1")
    tasks = plan.parse(updated)
    assert [task.checked for task in tasks] == [True, True, False]


def test_tick_preserves_every_other_line_exactly():
    updated = plan.tick(SAMPLE, "WL-2")
    assert updated.splitlines()[0] == "# Plan"
    assert "Cache must evict on write, not on a timer." in updated
    assert updated.count("- [ ]") == 1


def test_tick_on_unknown_task_raises():
    with pytest.raises(plan.PlanError):
        plan.tick(SAMPLE, "WL-99")


def test_parse_rejects_duplicate_task_ids():
    with pytest.raises(plan.PlanError):
        plan.parse("- [ ] WL-1: One\n- [ ] WL-1: Two\n")


def test_checkbox_line_without_colon_uses_whole_line_as_id():
    tasks = plan.parse("- [ ] WL-7 do the thing\n")
    assert tasks[0].task_id == "WL-7"
    assert tasks[0].text == "WL-7 do the thing"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_plan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'whyline_relay.plan'`.

- [ ] **Step 3: Write `src/whyline_relay/plan.py`**

```python
"""Reading and updating the Markdown task checklist."""

from __future__ import annotations

import re
from dataclasses import dataclass

CHECKBOX = re.compile(r"^(?P<indent>\s*)- \[(?P<mark>[ xX])\]\s+(?P<body>.*)$")


class PlanError(ValueError):
    """The plan file cannot be used as written."""


@dataclass(frozen=True)
class Task:
    task_id: str
    text: str
    checked: bool
    line_index: int


def _task_id(body: str) -> str:
    head, separator, _ = body.partition(":")
    candidate = head if separator else body.split()[0] if body.split() else ""
    return candidate.strip()


def _dedent(lines: list[str]) -> list[str]:
    stripped = [line for line in lines if line.strip()]
    if not stripped:
        return []
    common = min(len(line) - len(line.lstrip()) for line in stripped)
    return [line[common:].rstrip() for line in lines if line.strip()]


def parse(content: str) -> list[Task]:
    """Parse checklist items in file order. Indented lines below one are its detail."""
    lines = content.splitlines()
    tasks: list[Task] = []
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        match = CHECKBOX.match(lines[index])
        if match is None:
            index += 1
            continue
        body = match.group("body").strip()
        task_id = _task_id(body)
        if not task_id:
            raise PlanError(f"line {index + 1}: checklist item has no task id")
        if task_id in seen:
            raise PlanError(f"line {index + 1}: duplicate task id {task_id!r}")
        seen.add(task_id)
        detail: list[str] = []
        cursor = index + 1
        while cursor < len(lines):
            following = lines[cursor]
            if CHECKBOX.match(following) or (following.strip() and not following.startswith((" ", "\t"))):
                break
            detail.append(following)
            cursor += 1
        text = "\n".join([body, *_dedent(detail)])
        tasks.append(
            Task(task_id=task_id, text=text, checked=match.group("mark") != " ", line_index=index)
        )
        index = cursor
    return tasks


def next_unchecked(tasks: list[Task]) -> Task | None:
    for task in tasks:
        if not task.checked:
            return task
    return None


def find(tasks: list[Task], task_id: str) -> Task | None:
    for task in tasks:
        if task.task_id == task_id:
            return task
    return None


def tick(content: str, task_id: str) -> str:
    """Return `content` with `task_id`'s checkbox marked done. Only that line changes."""
    task = find(parse(content), task_id)
    if task is None:
        raise PlanError(f"no task {task_id!r} in the plan")
    lines = content.splitlines(keepends=True)
    line = lines[task.line_index]
    lines[task.line_index] = line.replace("- [ ]", "- [x]", 1)
    return "".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_plan.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: parse and tick the Markdown task plan"
```

---

### Task 3: Reading whyline

Reads the handoff record and wraps the two whyline commands the relay issues. These belong together: both are the relay's contact surface with whyline.

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/handoff.py`
- Create: `/Users/anish/whyline-relay/src/whyline_relay/whylinecmd.py`
- Test: `/Users/anish/whyline-relay/tests/test_handoff.py`
- Test: `/Users/anish/whyline-relay/tests/test_whylinecmd.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `handoff.Handoff` frozen dataclass with fields `event_id: str`, `task: str`, `to_actor: str`, `status: str`, `summary: str`; `handoff.read(root: Path) -> Handoff | None`; `whylinecmd.sync(root: Path, task: str, runner=None) -> str`; `whylinecmd.claim(root: Path, task: str, actor: str, role: str, runner=None) -> None`; `whylinecmd.WhylineUnavailable`.

`runner` is an injection point for tests and defaults to `subprocess.run`. Note the field name is `to_actor`, matching whyline's own JSON key — not `to`.

- [ ] **Step 1: Write the failing tests**

`tests/test_handoff.py`:

```python
import json
from pathlib import Path

from whyline_relay import handoff


def write_handoff(root: Path, **fields) -> None:
    target = root / ".whyline"
    target.mkdir(parents=True, exist_ok=True)
    record = {
        "v": 1,
        "id": "abc123",
        "ts": "2026-09-20T10:00:00.000Z",
        "type": "Handoff",
        "task": "WL-1",
        "from_actor": "codex",
        "to_actor": "claude",
        "status": "ready-for-review",
        "summary": "Implemented the cache",
        **fields,
    }
    (target / "active-handoff.json").write_text(json.dumps(record))


def test_read_returns_none_when_absent(tmp_path: Path):
    assert handoff.read(tmp_path) is None


def test_read_extracts_the_routing_fields(tmp_path: Path):
    write_handoff(tmp_path)
    record = handoff.read(tmp_path)
    assert record.event_id == "abc123"
    assert record.task == "WL-1"
    assert record.to_actor == "claude"
    assert record.status == "ready-for-review"
    assert record.summary == "Implemented the cache"


def test_read_returns_none_on_corrupt_json(tmp_path: Path):
    target = tmp_path / ".whyline"
    target.mkdir(parents=True)
    (target / "active-handoff.json").write_text("{not json")
    assert handoff.read(tmp_path) is None


def test_missing_fields_become_empty_strings(tmp_path: Path):
    write_handoff(tmp_path, summary=None)
    assert handoff.read(tmp_path).summary == ""
```

`tests/test_whylinecmd.py`:

```python
import subprocess
from pathlib import Path

import pytest

from whyline_relay import whylinecmd


class FakeRun:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "")


def test_sync_passes_the_task_and_returns_stdout(tmp_path: Path):
    fake = FakeRun(stdout="SYNC PACKET")
    assert whylinecmd.sync(tmp_path, "WL-1", runner=fake) == "SYNC PACKET"
    argv = fake.calls[0][0]
    assert argv[:2] == ["whyline", "sync"]
    assert "--task" in argv and "WL-1" in argv


def test_sync_raises_when_whyline_fails(tmp_path: Path):
    with pytest.raises(whylinecmd.WhylineUnavailable):
        whylinecmd.sync(tmp_path, "WL-1", runner=FakeRun(returncode=2))


def test_claim_sends_actor_and_role(tmp_path: Path):
    fake = FakeRun()
    whylinecmd.claim(tmp_path, "WL-1", "codex", "implementer", runner=fake)
    argv = fake.calls[0][0]
    assert argv[:2] == ["whyline", "claim"]
    assert "--actor" in argv and "codex" in argv
    assert "--role" in argv and "implementer" in argv
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_handoff.py tests/test_whylinecmd.py -v`
Expected: FAIL — modules do not exist.

- [ ] **Step 3: Write `src/whyline_relay/handoff.py`**

```python
"""Reading whyline's active handoff record. The relay reads it; it never writes it."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Handoff:
    event_id: str
    task: str
    to_actor: str
    status: str
    summary: str


def path(root: Path) -> Path:
    return root / ".whyline" / "active-handoff.json"


def _text(record: dict, key: str) -> str:
    value = record.get(key)
    return value if isinstance(value, str) else ""


def read(root: Path) -> Handoff | None:
    """Return the current handoff, or None if it is absent or unreadable.

    An unreadable record is treated as absent on purpose: the caller's next move
    is to pause either way, and guessing at half-written JSON is how a relay
    routes on a lie.
    """
    try:
        record = json.loads(path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    return Handoff(
        event_id=_text(record, "id"),
        task=_text(record, "task"),
        to_actor=_text(record, "to_actor"),
        status=_text(record, "status"),
        summary=_text(record, "summary"),
    )
```

- [ ] **Step 4: Write `src/whyline_relay/whylinecmd.py`**

```python
"""The two whyline commands the relay issues on its own behalf."""

from __future__ import annotations

import subprocess
from pathlib import Path


class WhylineUnavailable(RuntimeError):
    """whyline is not installed, or refused the command."""


def _run(runner, argv: list[str], root: Path) -> subprocess.CompletedProcess:
    run = runner if runner is not None else subprocess.run
    try:
        return run(argv, cwd=str(root), capture_output=True, text=True)
    except FileNotFoundError as error:
        raise WhylineUnavailable("whyline is not installed or not on PATH") from error


def sync(root: Path, task: str, runner=None) -> str:
    """Return the compact active-task packet for `task`."""
    result = _run(runner, ["whyline", "sync", "--task", task], root)
    if result.returncode != 0:
        raise WhylineUnavailable(
            f"whyline sync failed ({result.returncode}): {(result.stderr or '').strip()}"
        )
    return result.stdout


def claim(root: Path, task: str, actor: str, role: str, runner=None) -> None:
    """Record advisory ownership. A conflict is a warning from whyline, not an error."""
    result = _run(
        runner,
        ["whyline", "claim", task, "--actor", actor, "--role", role],
        root,
    )
    if result.returncode != 0:
        raise WhylineUnavailable(
            f"whyline claim failed ({result.returncode}): {(result.stderr or '').strip()}"
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_handoff.py tests/test_whylinecmd.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: read whyline handoffs and issue sync and claim"
```

---

### Task 4: Prompt templates and rendering

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/prompts.py`
- Test: `/Users/anish/whyline-relay/tests/test_prompts.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `prompts.IMPLEMENT: str`; `prompts.REVIEW: str`; `prompts.PLACEHOLDERS: tuple[str, ...]`; `prompts.load(root: Path, name: str) -> str` where `name` is `"implement"` or `"review"`; `prompts.render(template: str, *, task_id: str, task_text: str, sync_packet: str, round_: int, review_feedback: str) -> str`.

Substitution is `str.replace`, never `str.format`: the templates contain JSON and shell braces that `.format` would reject.

- [ ] **Step 1: Write the failing test**

`tests/test_prompts.py`:

```python
from pathlib import Path

from whyline_relay import prompts


def test_render_substitutes_every_placeholder():
    rendered = prompts.render(
        "{sync_packet}|{task_id}|{task_text}|{round}|{review_feedback}",
        task_id="WL-1",
        task_text="WL-1: Do the thing",
        sync_packet="PACKET",
        round_=2,
        review_feedback="tests are missing",
    )
    assert rendered == "PACKET|WL-1|WL-1: Do the thing|2|tests are missing"


def test_render_leaves_json_braces_alone():
    rendered = prompts.render(
        'use {"permissions": {"allow": []}} for {task_id}',
        task_id="WL-1",
        task_text="",
        sync_packet="",
        round_=1,
        review_feedback="",
    )
    assert '{"permissions": {"allow": []}}' in rendered


def test_builtin_templates_use_only_known_placeholders():
    import re

    for template in (prompts.IMPLEMENT, prompts.REVIEW):
        for found in re.findall(r"\{([a-z_]+)\}", template):
            assert found in prompts.PLACEHOLDERS, found


def test_implement_template_names_the_exact_handoff_command():
    assert "whyline handoff {task_id} --from codex --to claude" in prompts.IMPLEMENT
    assert "--status ready-for-review" in prompts.IMPLEMENT
    assert "whyline note" in prompts.IMPLEMENT


def test_review_template_names_both_permitted_outcomes():
    assert "--status approved" in prompts.REVIEW
    assert "--to codex --status changes-requested" in prompts.REVIEW


def test_no_template_ever_suggests_a_bypass_flag():
    for template in (prompts.IMPLEMENT, prompts.REVIEW):
        assert "dangerously" not in template
        assert "git push" not in template


def test_load_prefers_a_user_template(tmp_path: Path):
    target = tmp_path / ".whyline" / "relay" / "prompts"
    target.mkdir(parents=True)
    (target / "implement.md").write_text("MINE {task_id}")
    assert prompts.load(tmp_path, "implement") == "MINE {task_id}"


def test_load_falls_back_to_the_builtin(tmp_path: Path):
    assert prompts.load(tmp_path, "review") == prompts.REVIEW
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_prompts.py -v`
Expected: FAIL — no module named `whyline_relay.prompts`.

- [ ] **Step 3: Write `src/whyline_relay/prompts.py`**

```python
"""What each agent is told, and how it is assembled."""

from __future__ import annotations

from pathlib import Path

PLACEHOLDERS = ("task_id", "task_text", "sync_packet", "round", "review_feedback")

IMPLEMENT = """{sync_packet}

You are the implementer for this task. Round {round}.

## Task {task_id}

{task_text}

## Feedback from the previous review round

{review_feedback}

## How to finish

Implement the task. Run the project's tests and note the exact command and its
result — you will report both in your handoff.

Do not commit. The reviewer commits.

Record any genuine decision a future reader would wonder about:

    whyline note "<one-line decision>" --because "<why>" --rejected "<option>: <why not>" \\
      --file <path> --actor codex --role implementer --task {task_id}

Finish by handing off, exactly once, with exactly these values:

    whyline handoff {task_id} --from codex --to claude --status ready-for-review \\
      --summary "<what you changed>" --file <each file you touched> \\
      --test "<command>: <result>" --risk "<anything the reviewer should check>"

If you cannot complete the task, hand off with --status blocked and a --question
saying what you need. Do not exit without running whyline handoff: the relay
reads that record to decide what happens next, and stops if it is missing.
"""

REVIEW = """{sync_packet}

You are the reviewer and committer for this task. Round {round}.

## Task {task_id}

{task_text}

## How to review

Read the working-tree diff. Judge whether it does what the task asked, whether
the tests genuinely cover it, and whether anything is unsafe or clearly wrong.

Record your ruling — reviewing is deciding:

    whyline note "<one-line ruling>" --because "<why>" \\
      --file <path> --actor claude --role reviewer --task {task_id}

## How to finish

Exactly one of these two outcomes.

Approve: commit the work with the task id in the message, then hand off.

    git add -A
    git commit -m "<type>: <what changed> ({task_id})"
    whyline handoff {task_id} --from claude --to claude --status approved \\
      --summary "<what you approved>"

Request changes: do not commit. Hand back with concrete, actionable feedback.

    whyline handoff {task_id} --from claude --to codex --status changes-requested \\
      --summary "<what must change, specifically>"

If the task is blocked on a human decision, hand off with --status blocked and a
--question. Do not exit without running whyline handoff: the relay reads that
record to decide what happens next, and stops if it is missing.
"""

TEMPLATES = {"implement": IMPLEMENT, "review": REVIEW}


def prompts_dir(root: Path) -> Path:
    return root / ".whyline" / "relay" / "prompts"


def load(root: Path, name: str) -> str:
    """Return the user's template for `name`, falling back to the built-in one."""
    candidate = prompts_dir(root) / f"{name}.md"
    try:
        return candidate.read_text(encoding="utf-8")
    except OSError:
        return TEMPLATES[name]


def render(
    template: str,
    *,
    task_id: str,
    task_text: str,
    sync_packet: str,
    round_: int,
    review_feedback: str,
) -> str:
    """Substitute the five placeholders.

    str.replace, not str.format: the templates carry JSON and shell braces, and
    .format would raise on the first one it met.
    """
    values = {
        "{task_id}": task_id,
        "{task_text}": task_text,
        "{sync_packet}": sync_packet,
        "{round}": str(round_),
        "{review_feedback}": review_feedback or "(none — this is the first round)",
    }
    rendered = template
    for placeholder, value in values.items():
        rendered = rendered.replace(placeholder, value)
    return rendered
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_prompts.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: implement and review prompt templates"
```

---

### Task 5: Launching an agent

The riskiest module. Read the late-binding constraint in Global Constraints before writing a line of it.

**Revised after review round 1 (RELAY-5).** The first version decoded agent output as strict UTF-8 and stopped a timed-out agent with SIGTERM only. Both failed when probed with a real process: one invalid byte raised `UnicodeDecodeError` and left the child running, and an agent that ignores SIGTERM outlived a 1-second timeout by its full runtime. The code and the two extra tests below are the fix. Do not simplify them away.

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/agents.py`
- Test: `/Users/anish/whyline-relay/tests/test_agents.py`
- Create: `/Users/anish/whyline-relay/tests/fake_agent.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `agents.AgentMissing`; `agents.AgentTimeout`; `agents.build_argv(command: list[str], prompt: str) -> list[str]`; `agents.run(command: list[str], prompt: str, *, cwd: Path, log_path: Path, timeout_seconds: int, which=None, echo=True) -> int`; `agents.RATE_LIMIT_MARKERS: tuple[str, ...]`; `agents.rate_limited(text: str) -> bool`; `agents.KILL_GRACE_SECONDS: int` (seconds between SIGTERM and SIGKILL on timeout; read at call time so tests can shorten it).

- [ ] **Step 1: Write the fake agent**

`tests/fake_agent.py` — the stand-in for `codex` and `claude` throughout the suite. It never calls a vendor.

```python
"""A fake agent. Prints, optionally writes a handoff, optionally hangs."""

import json
import sys
import time
from pathlib import Path


def main() -> int:
    mode = sys.argv[1]
    root = Path(sys.argv[2])
    prompt = sys.argv[-1]
    print(f"fake-agent {mode} received {len(prompt)} chars of prompt")
    if mode == "hang":
        time.sleep(600)
    if mode == "silent":
        return 0
    if mode == "fail":
        print("fake-agent failing on purpose", file=sys.stderr)
        return 1
    if mode == "ratelimited":
        print("You have exceeded your usage limit. Try again later.")
        return 1
    to_actor, status = {
        "review": ("claude", "ready-for-review"),
        "approve": ("claude", "approved"),
        "changes": ("codex", "changes-requested"),
        "blocked": ("claude", "blocked"),
        "weird": ("claude", "banana"),
    }[mode]
    target = root / ".whyline"
    target.mkdir(parents=True, exist_ok=True)
    existing = target / "active-handoff.json"
    previous = json.loads(existing.read_text()) if existing.exists() else {}
    counter = int(previous.get("counter", 0)) + 1
    existing.write_text(
        json.dumps(
            {
                "v": 1,
                "id": f"event{counter}",
                "counter": counter,
                "type": "Handoff",
                "task": sys.argv[3] if len(sys.argv) > 4 else "WL-1",
                "from_actor": "fake",
                "to_actor": to_actor,
                "status": status,
                "summary": f"fake {mode}",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Write the failing test**

`tests/test_agents.py`:

```python
import inspect
import sys
import time
from pathlib import Path

import pytest

from whyline_relay import agents

FAKE = str(Path(__file__).parent / "fake_agent.py")


def test_build_argv_appends_the_prompt_last():
    argv = agents.build_argv(["codex", "exec", "-s", "workspace-write"], "do it")
    assert argv == ["codex", "exec", "-s", "workspace-write", "do it"]


def test_which_is_not_bound_as_a_default_argument():
    """Binding it would ignore a later patch and exec the real agent. Twice bitten."""
    signature = inspect.signature(agents.run)
    assert signature.parameters["which"].default is None


def test_run_streams_output_to_the_log(tmp_path: Path):
    log = tmp_path / "run.log"
    code = agents.run(
        [sys.executable, FAKE, "review", str(tmp_path)],
        "the prompt",
        cwd=tmp_path,
        log_path=log,
        timeout_seconds=30,
        which=lambda name: name,
        echo=False,
    )
    assert code == 0
    assert "fake-agent review received" in log.read_text()


def test_run_returns_the_agents_exit_code(tmp_path: Path):
    code = agents.run(
        [sys.executable, FAKE, "fail", str(tmp_path)],
        "p",
        cwd=tmp_path,
        log_path=tmp_path / "run.log",
        timeout_seconds=30,
        which=lambda name: name,
        echo=False,
    )
    assert code == 1


def test_missing_binary_raises_before_launching(tmp_path: Path):
    with pytest.raises(agents.AgentMissing):
        agents.run(
            ["definitely-not-installed"],
            "p",
            cwd=tmp_path,
            log_path=tmp_path / "run.log",
            timeout_seconds=30,
            which=lambda name: None,
            echo=False,
        )


def test_timeout_kills_the_agent_and_raises(tmp_path: Path):
    log = tmp_path / "run.log"
    with pytest.raises(agents.AgentTimeout):
        agents.run(
            [sys.executable, FAKE, "hang", str(tmp_path)],
            "p",
            cwd=tmp_path,
            log_path=log,
            timeout_seconds=1,
            which=lambda name: name,
            echo=False,
        )


def test_rate_limit_marker_is_recognised():
    assert agents.rate_limited("You have exceeded your usage limit. Try again later.")
    assert not agents.rate_limited("all tests passed")


def test_non_utf8_output_does_not_crash_the_relay(tmp_path: Path):
    """An agent can print bytes that are not valid UTF-8. That must not kill the relay."""
    log = tmp_path / "run.log"
    code = agents.run(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'ok \\xff\\xfe done\\n')"],
        "p",
        cwd=tmp_path,
        log_path=log,
        timeout_seconds=30,
        which=lambda name: name,
        echo=False,
    )
    assert code == 0
    assert "ok" in log.read_text() and "done" in log.read_text()


def test_timeout_escalates_to_sigkill_for_an_agent_that_ignores_sigterm(
    tmp_path: Path, monkeypatch
):
    """A hung agent that ignores SIGTERM must still be stopped, or the timeout means nothing."""
    monkeypatch.setattr(agents, "KILL_GRACE_SECONDS", 1)
    stubborn = (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('started', flush=True); time.sleep(8)"
    )
    started = time.monotonic()
    with pytest.raises(agents.AgentTimeout):
        agents.run(
            [sys.executable, "-c", stubborn],
            "p",
            cwd=tmp_path,
            log_path=tmp_path / "run.log",
            timeout_seconds=1,
            which=lambda name: name,
            echo=False,
        )
    assert time.monotonic() - started < 6
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_agents.py -v`
Expected: FAIL — no module named `whyline_relay.agents`.

- [ ] **Step 4: Write `src/whyline_relay/agents.py`**

```python
"""Launching one agent as a child process, and watching it finish.

We supervise a child; we never exec. The parent must survive to route the next
turn. Output is teed for the human and the log, and is never parsed to decide
anything — routing comes from whyline's handoff record alone.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

# After SIGTERM, how long an agent gets to exit before it is sent SIGKILL. Read at call
# time so a test can shorten it.
KILL_GRACE_SECONDS = 5

RATE_LIMIT_MARKERS = (
    "usage limit",
    "rate limit",
    "rate_limit",
    "quota exceeded",
    "too many requests",
)


class AgentMissing(RuntimeError):
    """The agent's binary is not installed."""


class AgentTimeout(RuntimeError):
    """The agent outlived its timeout and was killed."""


def _which(name: str) -> str | None:
    """Looked up at call time. Never cache this, and never bind it as a default.

    whyline's runner.py carries the scars: a cached lookup ignores a test's
    patch and execs the real vendor CLI, which hung a test run on 2026-08-18.
    """
    return shutil.which(name)


def build_argv(command: list[str], prompt: str) -> list[str]:
    return [*command, prompt]


def rate_limited(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in RATE_LIMIT_MARKERS)


def run(
    command: list[str],
    prompt: str,
    *,
    cwd: Path,
    log_path: Path,
    timeout_seconds: int,
    which=None,
    echo: bool = True,
) -> int:
    """Run one agent to completion. Returns its exit code.

    Raises AgentMissing if the binary is absent, AgentTimeout if it overruns.
    """
    lookup = which if which is not None else _which
    argv = build_argv(command, prompt)
    if lookup(argv[0]) is None:
        raise AgentMissing(f"{argv[0]} is not installed or not on PATH")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    timed_out = threading.Event()

    process = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        start_new_session=True,
    )

    def signal_group(signum: int) -> None:
        try:
            os.killpg(os.getpgid(process.pid), signum)
        except (ProcessLookupError, PermissionError):
            pass

    def kill_group() -> None:
        timed_out.set()
        signal_group(signal.SIGTERM)
        # An agent that ignores SIGTERM must not outlive its timeout.
        hard_kill.start()

    hard_kill = threading.Timer(KILL_GRACE_SECONDS, signal_group, args=(signal.SIGKILL,))
    watchdog = threading.Timer(timeout_seconds, kill_group)
    watchdog.start()
    try:
        with log_path.open("w", encoding="utf-8") as log:
            for line in process.stdout or ():
                log.write(line)
                log.flush()
                if echo:
                    sys.stdout.write(line)
                    sys.stdout.flush()
        code = process.wait()
    finally:
        watchdog.cancel()
        hard_kill.cancel()
    if timed_out.is_set():
        raise AgentTimeout(
            f"{argv[0]} exceeded {timeout_seconds}s and was terminated"
        )
    return code


def terminate(process: subprocess.Popen) -> None:
    """Stop a running agent's whole process group. Used by the SIGINT handler."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_agents.py -v`
Expected: 9 passed. The two timeout tests take a few seconds.

- [ ] **Step 6: Hand off (Codex), then commit (Claude)**

**Codex:** do not stage or commit. Hand off, then stop:

```bash
whyline handoff RELAY-5 --from codex --to claude --status ready-for-review \
  --summary "<what you changed>" --file <each file you touched> \
  --test "uv run pytest -v: <result>" --risk "<anything the reviewer should check>"
```

**Claude:** only after the review approves, commit, then record the approval:

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: launch an agent, tee its output, enforce a timeout (RELAY-5)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
whyline handoff RELAY-5 --from claude --to claude --status approved --summary "<what you approved>"
```

---

### Task 6: Git guards and commit verification

**Revised after review round 1 (RELAY-6).** The first version verified a commit with `task_id in message`, a substring test. Probed against real repositories, a commit naming only `RELAY-10` verified `RELAY-1`, so a stray commit for Task 10-13 could tick Task 1's box and break the guarantee in spec §5.4. `_names_task` matches the whole id, and the parametrized test covers the prefix, punctuation, dotted-id and embedded-in-a-longer-word cases. Do not revert it to `in`.

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/gitcheck.py`
- Test: `/Users/anish/whyline-relay/tests/test_gitcheck.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `gitcheck.GitError`; `gitcheck.current_branch(root: Path) -> str`; `gitcheck.is_dirty(root: Path) -> bool`; `gitcheck.head_commit(root: Path) -> str`; `gitcheck.commit_message(root: Path, commit: str) -> str`; `gitcheck.ensure_branch(root: Path, name: str) -> None`; `gitcheck.commit_verified(root: Path, base_commit: str, task_id: str) -> bool`.

- [ ] **Step 1: Write the failing test**

`tests/test_gitcheck.py`:

```python
import subprocess
from pathlib import Path

import pytest

from whyline_relay import gitcheck


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (tmp_path / "README.md").write_text("hello\n")
    git("add", "-A")
    git("commit", "-m", "initial commit")
    return tmp_path


def test_current_branch(repo: Path):
    assert gitcheck.current_branch(repo) == "main"


def test_clean_tree_is_not_dirty(repo: Path):
    assert gitcheck.is_dirty(repo) is False


def test_untracked_file_makes_it_dirty(repo: Path):
    (repo / "new.txt").write_text("x")
    assert gitcheck.is_dirty(repo) is True


def test_ensure_branch_creates_then_reuses(repo: Path):
    gitcheck.ensure_branch(repo, "relay/plan")
    assert gitcheck.current_branch(repo) == "relay/plan"
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    gitcheck.ensure_branch(repo, "relay/plan")
    assert gitcheck.current_branch(repo) == "relay/plan"


def test_commit_verified_requires_a_new_commit(repo: Path):
    base = gitcheck.head_commit(repo)
    assert gitcheck.commit_verified(repo, base, "WL-1") is False


def test_commit_verified_requires_the_task_id_in_the_message(repo: Path):
    base = gitcheck.head_commit(repo)
    (repo / "a.txt").write_text("a")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: something unrelated"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    assert gitcheck.commit_verified(repo, base, "WL-1") is False


def test_commit_verified_passes_when_both_hold(repo: Path):
    base = gitcheck.head_commit(repo)
    (repo / "a.txt").write_text("a")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: add the cache (WL-1)"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    assert gitcheck.commit_verified(repo, base, "WL-1") is True


@pytest.mark.parametrize(
    ("message", "task_id", "expected"),
    [
        ("feat: add the cache (WL-10)", "WL-1", False),
        ("feat: add the cache (WL-1)", "WL-1", True),
        ("WL-1: add the cache", "WL-1", True),
        ("feat: add the cache for WL-2, WL-1", "WL-1", True),
        ("feat: add the cache (WL-0.2.0)", "WL-0.2", False),
        ("feat: add the cache (WL-0.2.0)", "WL-0.2.0", True),
        ("feat: add the cache (XWL-1)", "WL-1", False),
    ],
)
def test_commit_verified_matches_the_whole_task_id(
    repo: Path, message: str, task_id: str, expected: bool
):
    """A commit for WL-10 must not verify WL-1, or a ticked box could lie."""
    base = gitcheck.head_commit(repo)
    (repo / "a.txt").write_text("a")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True
    )
    assert gitcheck.commit_verified(repo, base, task_id) is expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_gitcheck.py -v`
Expected: FAIL — no module named `whyline_relay.gitcheck`.

- [ ] **Step 3: Write `src/whyline_relay/gitcheck.py`**

```python
"""Git guards. Git is the authority; the relay only asks it questions."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """A git command failed or git is unavailable."""


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True
        )
    except FileNotFoundError as error:
        raise GitError("git is not installed or not on PATH") from error
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def current_branch(root: Path) -> str:
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD")


def is_dirty(root: Path) -> bool:
    return bool(_git(root, "status", "--porcelain"))


def head_commit(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD")


def commit_message(root: Path, commit: str) -> str:
    return _git(root, "log", "-1", "--format=%B", commit)


def ensure_branch(root: Path, name: str) -> None:
    """Switch to `name`, creating it from the current commit if it does not exist."""
    try:
        _git(root, "rev-parse", "--verify", f"refs/heads/{name}")
    except GitError:
        _git(root, "checkout", "-b", name)
        return
    _git(root, "checkout", name)


def _names_task(message: str, task_id: str) -> bool:
    """True when `task_id` appears as a whole id, not as the start of a longer one.

    A plain substring test would let a commit for RELAY-10 verify RELAY-1.
    """
    pattern = rf"(?<![\w-]){re.escape(task_id)}(?![\w-]|\.\w)"
    return re.search(pattern, message) is not None


def commit_verified(root: Path, base_commit: str, task_id: str) -> bool:
    """True when HEAD moved past `base_commit` and names `task_id` in its message.

    A ticked checkbox must always mean a real commit exists for that task, so
    both halves are required and neither is inferred from the agent's word.
    """
    head = head_commit(root)
    if head == base_commit:
        return False
    return _names_task(commit_message(root, head), task_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_gitcheck.py -v`
Expected: 14 passed.

- [ ] **Step 5: Hand off (Codex), then commit (Claude)**

**Codex:** do not stage or commit. Hand off, then stop:

```bash
whyline handoff RELAY-6 --from codex --to claude --status ready-for-review \
  --summary "<what you changed>" --file <each file you touched> \
  --test "uv run pytest -v: <result>" --risk "<anything the reviewer should check>"
```

**Claude:** only after the review approves, commit, then record the approval:

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: git guards and commit verification (RELAY-6)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
whyline handoff RELAY-6 --from claude --to claude --status approved --summary "<what you approved>"
```

---

### Task 7: Routing decision and dry run — milestone M1

The routing table from the spec, as a pure function, plus a CLI that can print what it would do without launching anything.

**Revised after review round 1 (RELAY-7).** The first `decide()` routed on status alone and ignored `to_actor`, which contradicts the spec's routing table (§5.2: `codex` + `assigned`/`changes-requested` implements, `claude` + `ready-for-review` reviews, only `approved` and `blocked` apply to any recipient). Probed: `codex` + `ready-for-review`, `claude` + `changes-requested` and `claude` + `assigned` all routed to an agent when the spec says pause. A mis-addressed handoff means a confused agent, so `decide()` now returns `UNKNOWN` for those. Do not drop the `to_actor` checks.

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/routing.py`
- Create: `/Users/anish/whyline-relay/src/whyline_relay/cli.py`
- Test: `/Users/anish/whyline-relay/tests/test_routing.py`
- Test: `/Users/anish/whyline-relay/tests/test_cli_dryrun.py`

**Interfaces:**
- Consumes: `config.Config`, `handoff.Handoff`, `plan.parse`, `prompts.load`, `prompts.render`, `whylinecmd.sync`.
- Produces: `routing.Move` string constants `IMPLEMENT`, `REVIEW`, `APPROVED`, `BLOCKED`, `NO_HANDOFF`, `UNKNOWN`; `routing.decide(record: handoff.Handoff | None, previous_id: str | None, status_map: dict[str, str]) -> str`; `cli.entry() -> int`; `cli.main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing routing test**

`tests/test_routing.py`:

```python
import pytest

from whyline_relay import config, handoff, routing

STATUS = config.DEFAULTS["status_map"]


def record(**fields) -> handoff.Handoff:
    base = {
        "event_id": "e2",
        "task": "WL-1",
        "to_actor": "claude",
        "status": "ready-for-review",
        "summary": "",
    }
    return handoff.Handoff(**{**base, **fields})


def test_unchanged_event_id_means_the_agent_never_handed_off():
    assert routing.decide(record(event_id="e1"), "e1", STATUS) == routing.NO_HANDOFF


def test_absent_handoff_is_also_no_handoff():
    assert routing.decide(None, None, STATUS) == routing.NO_HANDOFF


def test_ready_for_review_routes_to_claude():
    assert routing.decide(record(), "e1", STATUS) == routing.REVIEW


def test_changes_requested_routes_back_to_codex():
    moved = record(to_actor="codex", status="changes-requested")
    assert routing.decide(moved, "e1", STATUS) == routing.IMPLEMENT


def test_assigned_routes_to_codex():
    moved = record(to_actor="codex", status="assigned")
    assert routing.decide(moved, "e1", STATUS) == routing.IMPLEMENT


def test_approved_is_approved_regardless_of_recipient():
    assert routing.decide(record(status="approved"), "e1", STATUS) == routing.APPROVED


def test_blocked_is_blocked():
    assert routing.decide(record(status="blocked"), "e1", STATUS) == routing.BLOCKED


def test_unrecognised_status_is_unknown_not_a_guess():
    assert routing.decide(record(status="banana"), "e1", STATUS) == routing.UNKNOWN


def test_status_map_is_honoured():
    custom = {**STATUS, "review": "needs-review"}
    moved = record(status="needs-review")
    assert routing.decide(moved, "e1", custom) == routing.REVIEW


@pytest.mark.parametrize(
    ("to_actor", "status"),
    [
        ("codex", "ready-for-review"),
        ("claude", "changes-requested"),
        ("claude", "assigned"),
    ],
)
def test_a_handoff_addressed_to_the_wrong_agent_pauses(to_actor: str, status: str):
    """Spec 5.2 routes on (to_actor, status). Mis-addressed means a confused agent."""
    moved = record(to_actor=to_actor, status=status)
    assert routing.decide(moved, "e1", STATUS) == routing.UNKNOWN
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_routing.py -v`
Expected: FAIL — no module named `whyline_relay.routing`.

- [ ] **Step 3: Write `src/whyline_relay/routing.py`**

```python
"""The routing table, as a pure function. Every relay decision passes through here."""

from __future__ import annotations

from whyline_relay import handoff

IMPLEMENT = "implement"
REVIEW = "review"
APPROVED = "approved"
BLOCKED = "blocked"
NO_HANDOFF = "no-handoff"
UNKNOWN = "unknown"

IMPLEMENTER = "codex"
REVIEWER = "claude"


def decide(
    record: handoff.Handoff | None,
    previous_id: str | None,
    status_map: dict[str, str],
) -> str:
    """Pick the next move from the handoff record alone.

    A missing record, or one whose event id has not changed since the agent
    started, means the agent exited without handing off. That is never inferred
    to be success: the caller pauses.

    Routing is on (to_actor, status), as the spec's table has it. A handoff
    addressed to the wrong agent for its status, such as ready-for-review sent
    to the implementer, means a confused agent, so it is UNKNOWN and the caller
    pauses. Only approved and blocked apply whoever the recipient is.
    """
    if record is None or (previous_id is not None and record.event_id == previous_id):
        return NO_HANDOFF
    status = record.status
    if status == status_map["approved"]:
        return APPROVED
    if status == status_map["blocked"]:
        return BLOCKED
    if status == status_map["review"] and record.to_actor == REVIEWER:
        return REVIEW
    if (
        status in (status_map["changes"], status_map["assigned"])
        and record.to_actor == IMPLEMENTER
    ):
        return IMPLEMENT
    return UNKNOWN
```

- [ ] **Step 4: Run the routing tests to verify they pass**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_routing.py -v`
Expected: 12 passed.

- [ ] **Step 5: Write the failing dry-run test**

`tests/test_cli_dryrun.py`:

```python
from pathlib import Path

from whyline_relay import cli


def make_repo(tmp_path: Path) -> Path:
    (tmp_path / ".whyline").mkdir(parents=True)
    (tmp_path / "plan.md").write_text(
        "- [x] WL-0: Done already\n- [ ] WL-1: Add the cache\n      Evict on write.\n"
    )
    return tmp_path


def test_dry_run_prints_the_next_task_and_argv(tmp_path: Path, capsys, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setattr(cli.whylinecmd, "sync", lambda root, task, runner=None: "PACKET")
    code = cli.main(["start", "--repo", str(repo), "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "WL-1" in out
    assert "WL-0" not in out
    assert "codex exec -s workspace-write" in out
    assert "PACKET" in out
    assert "Evict on write." in out


def test_dry_run_launches_nothing(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setattr(cli.whylinecmd, "sync", lambda root, task, runner=None: "PACKET")

    def explode(*args, **kwargs):
        raise AssertionError("dry run must not launch an agent")

    monkeypatch.setattr(cli.agents, "run", explode)
    assert cli.main(["start", "--repo", str(repo), "--dry-run"]) == 0


def test_dry_run_reports_an_empty_plan(tmp_path: Path, capsys):
    (tmp_path / ".whyline").mkdir(parents=True)
    (tmp_path / "plan.md").write_text("- [x] WL-1: Done\n")
    code = cli.main(["start", "--repo", str(tmp_path), "--dry-run"])
    assert code == 0
    assert "no unchecked tasks" in capsys.readouterr().out.lower()
```

- [ ] **Step 6: Run it to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_cli_dryrun.py -v`
Expected: FAIL — no module named `whyline_relay.cli`.

- [ ] **Step 7: Write `src/whyline_relay/cli.py`**

Only `start --dry-run` works in this task; the other subcommands arrive in Tasks 8–12.

```python
"""Command line entry point."""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from whyline_relay import agents, config, plan, prompts, whylinecmd

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_PAUSED = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="whyline-relay")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Run the plan from its first unchecked task")
    start.add_argument("--repo", default=".", help="Repository root (default: cwd)")
    start.add_argument("--plan", default=None, help="Plan file (default: from config)")
    start.add_argument("--dry-run", action="store_true")
    start.add_argument("--only", default=None, metavar="TASK_ID")
    return parser


def _task_for(tasks: list[plan.Task], only: str | None) -> plan.Task | None:
    if only is not None:
        return plan.find(tasks, only)
    return plan.next_unchecked(tasks)


def cmd_start(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    settings = config.load(root)
    plan_path = root / (args.plan or settings.plan)
    try:
        content = plan_path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"could not read the plan: {error}", file=sys.stderr)
        return EXIT_ERROR
    tasks = plan.parse(content)
    task = _task_for(tasks, args.only)
    if task is None:
        print("Nothing to do: no unchecked tasks in the plan.")
        return EXIT_OK

    if args.dry_run:
        packet = whylinecmd.sync(root, task.task_id)
        rendered = prompts.render(
            prompts.load(root, "implement"),
            task_id=task.task_id,
            task_text=task.text,
            sync_packet=packet,
            round_=1,
            review_feedback="",
        )
        argv = agents.build_argv(settings.agents["codex"], rendered)
        print(f"Next task: {task.task_id}")
        print(f"Would run: {shlex.join(argv[:-1])} <prompt>")
        print("--- prompt ---")
        print(rendered)
        return EXIT_OK

    print("Only --dry-run is implemented so far.", file=sys.stderr)
    return EXIT_ERROR


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "start":
        return cmd_start(args)
    return EXIT_ERROR


def entry() -> int:
    return main()


if __name__ == "__main__":
    raise SystemExit(entry())
```

- [ ] **Step 8: Run the whole suite**

Run: `cd /Users/anish/whyline-relay && uv run pytest -v`
Expected: all tests pass (66 with the tests as written).

- [ ] **Step 9: Hand off (Codex), then commit (Claude)**

**Codex:** do not stage or commit. Hand off, then stop:

```bash
whyline handoff RELAY-7 --from codex --to claude --status ready-for-review \
  --summary "<what you changed>" --file <each file you touched> \
  --test "uv run pytest -v: <result>" --risk "<anything the reviewer should check>"
```

**Claude:** only after the review approves, commit, then record the approval:

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: routing table and dry run (M1) (RELAY-7)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
whyline handoff RELAY-7 --from claude --to claude --status approved --summary "<what you approved>"
```

---

### Task 8: One task end to end — milestone M2

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/loop.py`
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/cli.py` (wire `start` to `loop.run_task`)
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/gitcheck.py` (add `ensure_relay_ignored`)
- Modify: `/Users/anish/whyline-relay/tests/fake_agent.py` (read the task id from the prompt; add a `wrongtask` mode)
- Test: `/Users/anish/whyline-relay/tests/test_loop_single.py`
- Test: `/Users/anish/whyline-relay/tests/test_gitcheck.py` (append one test)

**Interfaces:**
- Consumes: `routing.decide`, `agents.run`, `handoff.read`, `prompts.render`, `whylinecmd.sync`, `whylinecmd.claim`, `gitcheck.commit_verified`, `config.Config`, `plan.Task`.
- Produces: `loop.Paused` exception with attribute `reason: str`; `loop.Outcome` frozen dataclass with fields `task_id: str`, `rounds: int`, `committed: bool`; `loop.run_task(root: Path, settings: config.Config, task: plan.Task, *, base_commit: str, echo: bool = True, resume: bool = False, start_round: int = 1, on_turn: Callable[[int, str | None], None] | None = None) -> Outcome`; `gitcheck.ensure_relay_ignored(root: Path) -> None`.

`run_task` raises `Paused` for every stop condition. The caller decides what a pause means.

**Revised after pre-review (RELAY-8).** The plan's code was built in a scratch copy and probed before dispatch; three defects turned up and are fixed below. (1) The rate-limit check scanned the agent's whole output *before* routing, so a successful task whose output merely said "Too Many Requests" (any HTTP code does) was paused and its handoff discarded. It now runs only when the agent handed nothing off. (2) Nothing ignored `.whyline/relay/`, so the reviewer's `git add -A` committed the agent logs into every task's commit and left the tree dirty. `run_task` now calls `gitcheck.ensure_relay_ignored`, which writes local excludes to `.git/info/exclude` (never committed, never dirties the tree). (3) The round cap was implemented and untested; a test now covers it. A second review added two more. (4) A handoff naming a *different task* was routed as if it were this one; `run_task` now pauses on it (the fake agent now reads the task id from the prompt, so its handoffs carry the right id). (5) `resume` re-entered at round 1 and re-ran Codex even after it had handed off, contradicting spec §5.6 ("re-enters the loop at the same decision point"); with `resume=True`, `run_task` now derives the next move from whyline's handoff record, the single source of truth: `ready-for-review` goes straight to the review, `changes-requested` carries its feedback into Codex's turn, `approved` goes straight to commit verification, and a record naming another task is ignored. `on_turn` reports the round and last handoff id before each turn so Task 9 can save real state. Do not remove any of the five.

- [ ] **Step 1: Write the failing test**

`tests/test_loop_single.py`:

```python
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from whyline_relay import config, loop, plan

FAKE = str(Path(__file__).parent / "fake_agent.py")
TASK = plan.Task(task_id="WL-1", text="WL-1: Add the cache", checked=False, line_index=0)


def settings_using(codex_mode: str, claude_mode: str, root: Path) -> config.Config:
    base = config.load(root)
    return config.Config(
        plan=base.plan,
        max_rounds=base.max_rounds,
        timeout_minutes=base.timeout_minutes,
        branch_prefix=base.branch_prefix,
        agents={
            "codex": [sys.executable, FAKE, codex_mode, str(root)],
            "claude": [sys.executable, FAKE, claude_mode, str(root)],
        },
        status_map=base.status_map,
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-b", "relay/plan")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    (tmp_path / "README.md").write_text("x\n")
    git("add", "-A")
    git("commit", "-m", "initial")
    (tmp_path / ".whyline").mkdir()
    monkeypatch.setattr(loop.whylinecmd, "sync", lambda root, task, runner=None: "PACKET")
    monkeypatch.setattr(loop.whylinecmd, "claim", lambda *a, **k: None)
    return tmp_path


def commit_for_task(root: Path) -> None:
    (root / "feature.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: cache (WL-1)"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_implement_then_review_then_approve(repo: Path, monkeypatch):
    settings = settings_using("review", "approve", repo)
    real_run = loop.agents.run

    def run_then_commit(command, prompt, **kwargs):
        code = real_run(command, prompt, **kwargs)
        if "approve" in command:
            commit_for_task(repo)
        return code

    monkeypatch.setattr(loop.agents, "run", run_then_commit)
    base = loop.gitcheck.head_commit(repo)
    outcome = loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    assert outcome.committed is True
    assert outcome.rounds == 1


def test_agent_that_writes_no_handoff_pauses(repo: Path):
    settings = settings_using("silent", "approve", repo)
    base = loop.gitcheck.head_commit(repo)
    with pytest.raises(loop.Paused) as raised:
        loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    assert "without handing off" in raised.value.reason


def test_blocked_handoff_pauses(repo: Path):
    settings = settings_using("blocked", "approve", repo)
    base = loop.gitcheck.head_commit(repo)
    with pytest.raises(loop.Paused) as raised:
        loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    assert "blocked" in raised.value.reason


def test_unknown_status_pauses(repo: Path):
    settings = settings_using("weird", "approve", repo)
    base = loop.gitcheck.head_commit(repo)
    with pytest.raises(loop.Paused) as raised:
        loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    assert "banana" in raised.value.reason


def test_approved_without_a_commit_pauses(repo: Path):
    settings = settings_using("review", "approve", repo)
    base = loop.gitcheck.head_commit(repo)
    with pytest.raises(loop.Paused) as raised:
        loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    assert "no commit" in raised.value.reason.lower()


def test_rate_limited_agent_pauses_with_a_useful_reason(repo: Path):
    settings = settings_using("ratelimited", "approve", repo)
    base = loop.gitcheck.head_commit(repo)
    with pytest.raises(loop.Paused) as raised:
        loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    assert "limit" in raised.value.reason.lower()


def test_logs_are_written_per_round_and_agent(repo: Path, monkeypatch):
    settings = settings_using("review", "approve", repo)
    real_run = loop.agents.run

    def run_then_commit(command, prompt, **kwargs):
        code = real_run(command, prompt, **kwargs)
        if "approve" in command:
            commit_for_task(repo)
        return code

    monkeypatch.setattr(loop.agents, "run", run_then_commit)
    base = loop.gitcheck.head_commit(repo)
    loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    logs = sorted(p.name for p in (repo / ".whyline" / "relay" / "logs").iterdir())
    assert logs == ["WL-1-1-claude.log", "WL-1-1-codex.log"]


def test_the_round_cap_stops_a_review_that_never_approves(repo: Path):
    settings = settings_using("review", "changes", repo)
    base = loop.gitcheck.head_commit(repo)
    with pytest.raises(loop.Paused) as raised:
        loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    assert "3-round cap" in raised.value.reason
    logs = list((repo / ".whyline" / "relay" / "logs").iterdir())
    assert len(logs) == 6


def test_output_that_only_mentions_a_rate_limit_does_not_discard_a_handoff(
    repo: Path, monkeypatch
):
    """An agent writing an HTTP client prints 'Too Many Requests' and still finishes."""
    settings = settings_using("review", "approve", repo)
    chatty = (
        "print('handling HTTP 429 Too Many Requests'); import runpy; "
        f"runpy.run_path({FAKE!r}, run_name='__main__')"
    )
    codex = [sys.executable, "-c", chatty, "review", str(repo)]
    settings = replace(settings, agents={**settings.agents, "codex": codex})
    real_run = loop.agents.run

    def run_then_commit(command, prompt, **kwargs):
        code = real_run(command, prompt, **kwargs)
        if "approve" in command:
            commit_for_task(repo)
        return code

    monkeypatch.setattr(loop.agents, "run", run_then_commit)
    base = loop.gitcheck.head_commit(repo)
    outcome = loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    assert outcome.committed is True


def test_the_relays_own_logs_stay_out_of_the_reviewers_commit(repo: Path, monkeypatch):
    settings = settings_using("review", "approve", repo)
    real_run = loop.agents.run

    def run_then_commit(command, prompt, **kwargs):
        code = real_run(command, prompt, **kwargs)
        if "approve" in command:
            commit_for_task(repo)
        return code

    monkeypatch.setattr(loop.agents, "run", run_then_commit)
    base = loop.gitcheck.head_commit(repo)
    loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    committed = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout
    assert "feature.py" in committed
    assert "relay/" not in committed


def test_a_handoff_for_another_task_pauses(repo: Path):
    settings = settings_using("wrongtask", "approve", repo)
    base = loop.gitcheck.head_commit(repo)
    with pytest.raises(loop.Paused) as raised:
        loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    assert "OTHER-1" in raised.value.reason


def write_handoff(root: Path, task: str, to_actor: str, status: str, summary: str = "") -> None:
    (root / ".whyline").mkdir(exist_ok=True)
    (root / ".whyline" / "active-handoff.json").write_text(
        json.dumps(
            {
                "v": 1,
                "id": "prior1",
                "type": "Handoff",
                "task": task,
                "from_actor": "x",
                "to_actor": to_actor,
                "status": status,
                "summary": summary,
            }
        )
    )


def watch_agents(monkeypatch, repo: Path, *, commit_on_approve: bool):
    """Record which agent ran and with what prompt; optionally commit like a reviewer."""
    seen: list[tuple[str, str]] = []
    real_run = loop.agents.run

    def spy(command, prompt, **kwargs):
        seen.append(("claude" if "approve" in command else "codex", prompt))
        code = real_run(command, prompt, **kwargs)
        if commit_on_approve and "approve" in command:
            commit_for_task(repo)
        return code

    monkeypatch.setattr(loop.agents, "run", spy)
    return seen


def test_resume_goes_straight_to_the_review_after_a_handoff(repo: Path, monkeypatch):
    write_handoff(repo, "WL-1", "claude", "ready-for-review")
    seen = watch_agents(monkeypatch, repo, commit_on_approve=True)
    base = loop.gitcheck.head_commit(repo)
    outcome = loop.run_task(
        repo, settings_using("review", "approve", repo), TASK,
        base_commit=base, echo=False, resume=True,
    )
    assert [agent for agent, _ in seen] == ["claude"]
    assert outcome.committed is True


def test_resume_after_changes_requested_carries_the_feedback(repo: Path, monkeypatch):
    write_handoff(repo, "WL-1", "codex", "changes-requested", "fix the cache key")
    seen = watch_agents(monkeypatch, repo, commit_on_approve=True)
    base = loop.gitcheck.head_commit(repo)
    loop.run_task(
        repo, settings_using("review", "approve", repo), TASK,
        base_commit=base, echo=False, resume=True, start_round=2,
    )
    assert seen[0][0] == "codex"
    assert "fix the cache key" in seen[0][1]


def test_resume_of_an_approved_task_verifies_without_running_an_agent(
    repo: Path, monkeypatch
):
    base = loop.gitcheck.head_commit(repo)
    commit_for_task(repo)
    write_handoff(repo, "WL-1", "claude", "approved")
    seen = watch_agents(monkeypatch, repo, commit_on_approve=False)
    outcome = loop.run_task(
        repo, settings_using("review", "approve", repo), TASK,
        base_commit=base, echo=False, resume=True,
    )
    assert seen == []
    assert outcome.committed is True


def test_resume_ignores_a_handoff_left_by_another_task(repo: Path, monkeypatch):
    write_handoff(repo, "WL-9", "claude", "ready-for-review")
    seen = watch_agents(monkeypatch, repo, commit_on_approve=True)
    base = loop.gitcheck.head_commit(repo)
    loop.run_task(
        repo, settings_using("review", "approve", repo), TASK,
        base_commit=base, echo=False, resume=True,
    )
    assert seen[0][0] == "codex"
```

Also patch `tests/fake_agent.py` so its handoffs name the task the prompt is for, and add a mode that names the wrong one:

```diff
-import json
-import sys
+import json
+import re
+import sys
```

```diff
     prompt = sys.argv[-1]
+    match = re.search(r"^## Task (\S+)", prompt, re.M)
+    task_id = match.group(1) if match else "WL-1"
```

```diff
         "weird": ("claude", "banana"),
+        "wrongtask": ("claude", "ready-for-review"),
```

```diff
-                "task": sys.argv[3] if len(sys.argv) > 4 else "WL-1",
+                "task": "OTHER-1" if mode == "wrongtask" else task_id,
```

Also append to `tests/test_gitcheck.py`:

```python
def test_relay_files_are_ignored_and_ignoring_is_idempotent(repo: Path):
    relay = repo / ".whyline" / "relay"
    (relay / "logs").mkdir(parents=True)
    (relay / "logs" / "WL-1-1-codex.log").write_text("x")
    (relay / "state.json").write_text("{}")
    (relay / "STOP").write_text("")
    (relay / "config.toml").write_text("max_rounds = 3\n")
    assert "logs" in _status(repo)
    gitcheck.ensure_relay_ignored(repo)
    gitcheck.ensure_relay_ignored(repo)
    status = _status(repo)
    assert "logs" not in status and "state.json" not in status and "STOP" not in status
    assert "config.toml" in status
    exclude = (repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert exclude.count(".whyline/relay/logs/") == 1


def _status(repo: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_loop_single.py -v`
Expected: FAIL — no module named `whyline_relay.loop`.

- [ ] **Step 3: Write `src/whyline_relay/loop.py` and add `ensure_relay_ignored` to `gitcheck.py`**

```python
"""The state machine. The only module in the relay that decides anything."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from whyline_relay import agents, config, gitcheck, handoff, plan, prompts, routing, whylinecmd


class Paused(RuntimeError):
    """The relay stopped and wants a human. Carries the reason and the log path."""

    def __init__(self, reason: str, log_path: Path | None = None):
        super().__init__(reason)
        self.reason = reason
        self.log_path = log_path


@dataclass(frozen=True)
class Outcome:
    task_id: str
    rounds: int
    committed: bool


def log_path(root: Path, task_id: str, round_: int, agent: str) -> Path:
    return root / ".whyline" / "relay" / "logs" / f"{task_id}-{round_}-{agent}.log"


def _run_agent(
    root: Path,
    settings: config.Config,
    agent: str,
    template_name: str,
    task: plan.Task,
    round_: int,
    review_feedback: str,
    echo: bool,
) -> Path:
    """Render the prompt, run the agent, and return the log path."""
    packet = whylinecmd.sync(root, task.task_id)
    prompt = prompts.render(
        prompts.load(root, template_name),
        task_id=task.task_id,
        task_text=task.text,
        sync_packet=packet,
        round_=round_,
        review_feedback=review_feedback,
    )
    target = log_path(root, task.task_id, round_, agent)
    try:
        agents.run(
            settings.agents[agent],
            prompt,
            cwd=root,
            log_path=target,
            timeout_seconds=settings.timeout_minutes * 60,
            echo=echo,
        )
    except agents.AgentTimeout as error:
        raise Paused(str(error), target) from error
    except agents.AgentMissing as error:
        raise Paused(str(error), target) from error
    return target


def _hit_a_limit(target: Path) -> bool:
    """Whether the agent's output says it ran out of quota.

    Only asked when the agent handed nothing off. Ordinary code and prose say
    "rate limit" and "too many requests" all the time, so those words alone must
    never discard a handoff the agent did make.
    """
    try:
        return agents.rate_limited(target.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False


def _approved(
    root: Path, task: plan.Task, base_commit: str, round_: int, log: Path | None
) -> Outcome:
    """An approval counts only when a real commit naming the task exists."""
    if not gitcheck.commit_verified(root, base_commit, task.task_id):
        raise Paused(
            f"{task.task_id} was approved but no commit naming it exists; "
            "the checkbox was not ticked",
            log,
        )
    return Outcome(task_id=task.task_id, rounds=round_, committed=True)


def run_task(
    root: Path,
    settings: config.Config,
    task: plan.Task,
    *,
    base_commit: str,
    echo: bool = True,
    resume: bool = False,
    start_round: int = 1,
    on_turn: Callable[[int, str | None], None] | None = None,
) -> Outcome:
    """Drive one task from implement to an approved, verified commit.

    Raises Paused for every stop condition. Never infers a verdict from an
    agent's exit code or output — only from the handoff record it wrote.

    With `resume`, re-enter at the decision point the handoff record shows,
    not at the start: a task Codex already handed off goes straight to the
    review, one sent back carries its feedback into Codex's next turn, and one
    already approved goes straight to commit verification. A record that names
    another task is ignored. `on_turn` is told the round and the last handoff
    id before every agent turn, so a caller can save resumable state.
    """
    round_ = start_round
    feedback = ""
    next_move = routing.IMPLEMENT
    gitcheck.ensure_relay_ignored(root)
    whylinecmd.claim(root, task.task_id, "codex", "implementer")
    if resume:
        current = handoff.read(root)
        if current is not None and current.task == task.task_id:
            resumed = routing.decide(current, None, settings.status_map)
            if resumed in (routing.REVIEW, routing.APPROVED):
                next_move = resumed
            elif (
                resumed == routing.IMPLEMENT
                and current.status == settings.status_map["changes"]
            ):
                feedback = current.summary

    while True:
        if next_move == routing.APPROVED:
            return _approved(root, task, base_commit, round_, None)
        agent = "codex" if next_move == routing.IMPLEMENT else "claude"
        template = "implement" if agent == "codex" else "review"
        previous = handoff.read(root)
        previous_id = previous.event_id if previous else None
        if on_turn is not None:
            on_turn(round_, previous_id)

        target = _run_agent(
            root, settings, agent, template, task, round_, feedback, echo
        )

        record = handoff.read(root)
        move = routing.decide(record, previous_id, settings.status_map)

        if move == routing.NO_HANDOFF:
            if _hit_a_limit(target):
                raise Paused(
                    f"{agent} hit a usage or rate limit; try again when it resets",
                    target,
                )
            raise Paused(
                f"{agent} exited without handing off; nothing was routed", target
            )
        if record.task != task.task_id:
            raise Paused(
                f"{agent} handed off for {record.task!r}, but this run is on "
                f"{task.task_id!r}; the relay will not guess",
                target,
            )
        if move == routing.BLOCKED:
            raise Paused(
                f"{agent} reported blocked: {record.summary or 'no summary given'}",
                target,
            )
        if move == routing.UNKNOWN:
            raise Paused(
                f"unrecognised handoff status {record.status!r}; the relay will not guess",
                target,
            )
        if move == routing.APPROVED:
            return _approved(root, task, base_commit, round_, target)
        if move == routing.IMPLEMENT:
            feedback = record.summary
            round_ += 1
            if round_ > settings.max_rounds:
                raise Paused(
                    f"{task.task_id} hit the {settings.max_rounds}-round cap without "
                    "an approval",
                    target,
                )
        next_move = move
```

Then append to `src/whyline_relay/gitcheck.py`:

```python
RELAY_IGNORE = (
    ".whyline/relay/logs/",
    ".whyline/relay/state.json*",
    ".whyline/relay/STOP",
)


def ensure_relay_ignored(root: Path) -> None:
    """Keep the relay's own logs, state and stop file out of `git status` and commits.

    Written to .git/info/exclude, which is local and never committed, so this
    neither dirties the tree nor adds a file to a task's commit. Without it the
    reviewer's `git add -A` sweeps the agent logs into the commit. Idempotent.
    """
    target = Path(_git(root, "rev-parse", "--git-path", "info/exclude"))
    if not target.is_absolute():
        target = root / target
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    present = existing.splitlines()
    missing = [pattern for pattern in RELAY_IGNORE if pattern not in present]
    if not missing:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write("\n".join(missing) + "\n")
```

- [ ] **Step 4: Run the loop tests to verify they pass**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_loop_single.py tests/test_gitcheck.py -v`
Expected: 30 passed (15 loop, 15 git).

- [ ] **Step 5: Wire `start` to the loop in `cli.py`**

Replace the `print("Only --dry-run is implemented so far.")` branch at the end of `cmd_start` with:

```python
    try:
        gitcheck.ensure_branch(root, args.branch or f"{settings.branch_prefix}{plan_path.stem}")
        base = gitcheck.head_commit(root)
        outcome = loop.run_task(root, settings, task, base_commit=base)
    except loop.Paused as paused:
        print(f"\nPaused: {paused.reason}", file=sys.stderr)
        if paused.log_path is not None:
            print(f"Log: {paused.log_path}", file=sys.stderr)
        print("Resume with: whyline-relay resume", file=sys.stderr)
        return EXIT_PAUSED
    plan_path.write_text(plan.tick(content, outcome.task_id), encoding="utf-8")
    print(f"\n{outcome.task_id} approved and committed in {outcome.rounds} round(s).")
    return EXIT_OK
```

Add `from whyline_relay import gitcheck, loop` to the imports and `start.add_argument("--branch", default=None)` to the parser. Guards come in Task 10; this task's `start` assumes a clean tree on a relay branch.

- [ ] **Step 6: Run the whole suite**

Run: `cd /Users/anish/whyline-relay && uv run pytest -v`
Expected: all pass.

- [ ] **Step 7: Hand off (Codex), then commit (Claude)**

**Codex:** do not stage or commit. Hand off, then stop:

```bash
whyline handoff RELAY-8 --from codex --to claude --status ready-for-review \
  --summary "<what you changed>" --file <each file you touched> \
  --test "uv run pytest -v: <result>" --risk "<anything the reviewer should check>"
```

**Claude:** only after the review approves, commit, then record the approval:

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: run one task from implement to verified commit (M2) (RELAY-8)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
whyline handoff RELAY-8 --from claude --to claude --status approved --summary "<what you approved>"
```

- [ ] **Step 8: STOP — owner checkpoint**

**Done on 2026-09-21**, against `codex-cli 0.155.1` and `claude 2.1.278`, in a throwaway repository with the real relay. It worked end to end once the Claude permissions were passed with `--settings`, and it disproved two assumptions; both are fixed in Task 8b. **Do not start Task 9 until Task 8b is approved and its real-CLI re-check (its last step) passes.**

---

### Task 8b: What the real CLIs taught — the Codex commit guard, Claude's permissions, and pause reasons

Task 8's M2 checkpoint was run against the real `codex` and `claude` on 2026-09-21, in a throwaway repository, with the real relay. It disproved two assumptions the plan and spec rested on and exposed a third weakness. This task fixes all three; Task 9 must not start until it is approved.

**What was measured (`codex-cli 0.155.1`, `claude 2.1.278`):**

1. **Codex can commit under `-s workspace-write`.** Asked to `git add -A && git commit`, it committed (the sandbox does not make `.git` read-only). In the M2 run it declined to commit only because its prompt said not to. The spec's "Codex never commits holds by construction" is false; the relay must check.
2. **`claude -p --permission-mode acceptEdits` denies every Bash command** (`git add`, `git commit`, `whyline note`, `whyline handoff`, even `python3`) unless permissions are supplied, so the relay paused after a correct review.
3. **A project `.claude/settings.json` allowlist is ignored** in a workspace nobody has trusted interactively (Claude's log begins `Ignoring 7 permissions.allow entries … this workspace has not been trusted`). So the allowlist Task 12's `init` was going to write would silently do nothing on a fresh checkout. Passing the same content with `--settings <file>` is honored (tested so it could fail: `whyline sync` was allowed with the flag and denied without). A missing `--settings` file fails at once with `Settings file not found`, no API call.
4. The pause reason said only "claude exited without handing off". Claude's JSON result names the denied commands in `permission_denials`, and the log's last line named the cause when there was no JSON.

**What passed:** Codex ran headless, ran its test and handed off from inside the sandbox; resume picked up at the recorded decision point (only Claude ran on resume); the relay's logs stayed out of the reviewer's commit; nested `claude -p` works; Claude found and read the new untracked file unprompted. Cost was about 7k Codex tokens and under $0.10 per Claude review turn.

**Files:**
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/loop.py`
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/config.py`
- Modify: `/Users/anish/whyline-relay/tests/fake_agent.py`
- Test: `/Users/anish/whyline-relay/tests/test_loop_single.py` (append three tests)
- Test: `/Users/anish/whyline-relay/tests/test_config.py` (append one test)

**Interfaces:**
- Consumes: `gitcheck.head_commit`, `loop.Paused`.
- Produces: no new public interface. `config.DEFAULTS["agents"]["claude"]` gains `--settings .whyline/relay/claude-settings.json`. `run_task` pauses when Codex moves HEAD, and its "exited without handing off" reasons now name what stopped the agent (diagnostic only, never used to route).

- [ ] **Step 1: Write the failing tests**

Patch `tests/fake_agent.py` to add a `denied` mode (prints Claude's untrusted-workspace warning and a JSON result with a permission denial, hands off nothing) and a `codexcommit` mode (commits, then hands off):

```diff
-import re
-import sys
+import re
+import subprocess
+import sys
```

```diff
         print("You have exceeded your usage limit. Try again later.")
         return 1
+    if mode == "denied":
+        print("Ignoring 7 permissions.allow entries: this workspace has not been trusted.")
+        denial = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}}
+        print(json.dumps({"type": "result", "permission_denials": [denial]}))
+        return 0
```

```diff
         "wrongtask": ("claude", "ready-for-review"),
+        "codexcommit": ("claude", "ready-for-review"),
     }[mode]
+    if mode == "codexcommit":
+        subprocess.run(
+            ["git", "commit", "--allow-empty", "-m", "sneaky"],
+            cwd=root, check=True, capture_output=True,
+        )
```

Append to `tests/test_loop_single.py`:

```python
def test_a_commit_by_the_implementer_pauses(repo: Path):
    """Codex's sandbox does not block git commit, so the relay must notice."""
    settings = settings_using("codexcommit", "approve", repo)
    base = loop.gitcheck.head_commit(repo)
    with pytest.raises(loop.Paused) as raised:
        loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    assert "forbids" in raised.value.reason
    assert f"git reset {base[:12]}" in raised.value.reason


def test_a_denied_reviewer_says_what_it_was_denied(repo: Path):
    settings = settings_using("review", "denied", repo)
    base = loop.gitcheck.head_commit(repo)
    with pytest.raises(loop.Paused) as raised:
        loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    reason = raised.value.reason
    assert "without handing off" in reason
    assert "git commit -m x" in reason
    assert "claude-settings.json" in reason


def test_a_silent_agent_pause_quotes_its_last_output_line(repo: Path):
    settings = settings_using("silent", "approve", repo)
    base = loop.gitcheck.head_commit(repo)
    with pytest.raises(loop.Paused) as raised:
        loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
    assert "its last output was" in raised.value.reason
    assert "fake-agent silent" in raised.value.reason
```

Append to `tests/test_config.py`:

```python
def test_default_claude_command_passes_the_relay_permissions(tmp_path: Path):
    """Project settings are ignored in a workspace never trusted interactively,
    so the permissions travel with the command instead."""
    command = config.load(tmp_path).agents["claude"]
    assert command[command.index("--settings") + 1] == ".whyline/relay/claude-settings.json"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_loop_single.py tests/test_config.py -v`
Expected: 4 FAIL (the three loop tests and the config test).

- [ ] **Step 3: Patch `loop.py` and `config.py`**

In `src/whyline_relay/loop.py`:

Add `import json` to the imports: replace

```python
from collections.abc import Callable
```

with

```python
import json
from collections.abc import Callable
```

Add this function directly above `_hit_a_limit`:

```python
def _no_handoff_detail(target: Path) -> str:
    """Why an agent that handed nothing off probably stopped, for the human only.

    Never used to route. Claude's JSON result lists the commands it was denied;
    failing that, the last line the agent printed is usually the cause (for
    example a settings file that was not found).
    """
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [line for line in text.splitlines() if line.strip()]
    if lines and lines[-1].startswith("{"):
        try:
            result = json.loads(lines[-1])
        except ValueError:
            result = None
        denials = result.get("permission_denials", []) if isinstance(result, dict) else []
        commands = [
            str(d.get("tool_input", {}).get("command", d.get("tool_name", "?")))[:60]
            for d in denials
            if isinstance(d, dict)
        ]
        if commands:
            return (
                f"; it was denied permission to run: {', '.join(commands)}. "
                "Check .whyline/relay/claude-settings.json"
            )
    if lines:
        last = "".join(ch for ch in lines[-1].strip() if ch.isprintable())[:160]
        return f'; its last output was: "{last}"'
    return ""
```

Capture HEAD before each agent turn: replace

```python
        previous_id = previous.event_id if previous else None
        if on_turn is not None:
            on_turn(round_, previous_id)
```

with

```python
        previous_id = previous.event_id if previous else None
        head_before = gitcheck.head_commit(root)
        if on_turn is not None:
            on_turn(round_, previous_id)
```

Right after the agent runs, refuse a commit by Codex: replace

```python
        target = _run_agent(
            root, settings, agent, template, task, round_, feedback, echo
        )
```

with

```python
        target = _run_agent(
            root, settings, agent, template, task, round_, feedback, echo
        )
        if agent == "codex" and gitcheck.head_commit(root) != head_before:
            # Codex's sandbox does not stop it committing (measured on
            # codex-cli 0.155.1); only the prompt says not to, so check.
            raise Paused(
                "codex made a commit, which the relay forbids (only the reviewer "
                f"commits). Undo it with `git reset {head_before[:12]}` (your files "
                "stay), then resume",
                target,
            )
```

Make the no-handoff pause say what stopped the agent: replace

```python
            raise Paused(
                f"{agent} exited without handing off; nothing was routed", target
            )
```

with

```python
            raise Paused(
                f"{agent} exited without handing off{_no_handoff_detail(target)}; "
                "nothing was routed",
                target,
            )
```

In `src/whyline_relay/config.py`, in `DEFAULTS["agents"]["claude"]`, replace

```python
            "acceptEdits",
            "--output-format",
            "json",
        ],
```

with

```python
            "acceptEdits",
            "--output-format",
            "json",
            "--settings",
            ".whyline/relay/claude-settings.json",
        ],
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_loop_single.py tests/test_config.py -v`
Expected: 22 passed (18 loop, 4 config).

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/anish/whyline-relay && uv run pytest -v`
Expected: all pass (86 with the tests as written).

- [ ] **Step 6: Hand off (Codex), then commit (Claude)**

**Codex:** do not stage or commit. Hand off, then stop:

```bash
whyline handoff RELAY-8b --from codex --to claude --status ready-for-review \
  --summary "<what you changed>" --file <each file you touched> \
  --test "uv run pytest -v: <result>" --risk "<anything the reviewer should check>"
```

**Claude:** only after the review approves, commit, then record the approval:

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "fix: forbid implementer commits, pass Claude's permissions, explain pauses (RELAY-8b)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
whyline handoff RELAY-8b --from claude --to claude --status approved --summary "<what you approved>"
```

- [ ] **Step 7: Real-CLI re-check (Claude runs it, in a throwaway repository)**

Task 12's `init` does not exist yet, so write the settings file by hand. It is what `init` will write for a repository with no recognised stack:

```bash
mkdir /tmp/relay-m2b && cd /tmp/relay-m2b && git init -b main
git config user.email you@example.com && git config user.name you
printf -- '- [ ] T-1: Create hello.py in the repository root that prints "hello" when run with python3\n' > plan.md
echo "# scratch" > README.md
whyline init --yes
mkdir -p .whyline/relay
cat > .whyline/relay/claude-settings.json <<'EOF'
{"permissions": {"allow": ["Edit", "Bash(git add:*)", "Bash(git commit:*)", "Bash(git diff:*)", "Bash(git status:*)", "Bash(git log:*)", "Bash(whyline:*)"], "deny": ["Bash(git push:*)", "Bash(rm -rf:*)"]}}
EOF
printf 'timeout_minutes = 6\nmax_rounds = 2\n' > .whyline/relay/config.toml
git add -A && git commit -m initial
uv --project /Users/anish/whyline-relay run whyline-relay start
```

Expected: `T-1 approved and committed in 1 round(s).`, exit 0. Then check that (a) `git log` shows a commit by Claude naming `T-1` that contains `hello.py` and `.whyline/decisions.md` and **no** `.whyline/relay/logs`; (b) Codex made no commit (the only commits are `initial` and Claude's); (c) `whyline sync` shows `claude -> claude approved`. At this stage `plan.md` is ticked but uncommitted; the tick commit arrives with Task 9. Do not start Task 9 until this passes.

---

### Task 9: Multi-task runs and resumable state — milestone M3, part 1

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/state.py`
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/loop.py` (add `run_plan`)
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/gitcheck.py` (add `dirty_paths`, `commit_paths`)
- Test: `/Users/anish/whyline-relay/tests/test_state.py`
- Test: `/Users/anish/whyline-relay/tests/test_loop_plan.py`
- Test: `/Users/anish/whyline-relay/tests/test_gitcheck.py` (append two tests)

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: `state.RelayState` frozen dataclass with fields `plan: str`, `branch: str`, `task_id: str`, `round: int`, `base_commit: str`, `paused_reason: str`, `log_path: str`, `only: str = ""`, `last_handoff_id: str = ""`; `state.save(root: Path, value: RelayState) -> None`; `state.load(root: Path) -> RelayState | None`; `state.clear(root: Path) -> None`; `loop.run_plan(root: Path, settings: config.Config, plan_path: Path, *, branch: str, only: str | None = None, resume: bool = False, allow_dirty: bool = False, echo: bool = True) -> list[Outcome]`; `gitcheck.dirty_paths(root: Path) -> list[str]`; `gitcheck.commit_paths(root: Path, paths: list[Path], message: str) -> None`.

**Revised after pre-review (RELAY-9).** Probed against real runs, `run_plan` had these defects, all fixed below. (1) It ticked a copy of the plan read *before* the agents ran, silently overwriting any edit an agent made to the plan meanwhile; it now re-reads before ticking. (2) `--only <unknown id>` returned an empty result and the CLI reported success; it now raises `plan.PlanError`. (3) `resume` recomputed the base commit from HEAD, so a task the reviewer had already committed could never verify; it now reuses the saved base, the saved round and `last_handoff_id`, and Task 8's `run_task(resume=True)` picks the next agent from the handoff record. (4) A pause under `--only` was not remembered, so `resume` would run a different task; `RelayState.only` records it. (5) The tick left `plan.md` modified after every approval, so it rode into the *next* task's commit and the last tick stayed uncommitted. **Decision:** after `run_task` has verified Claude's commit, the relay checks nothing else is uncommitted (pausing with the files named; the task stays unticked, so `resume` simply re-verifies), then ticks the box and makes one mechanical commit of only `plan.md` (`chore: tick <id> in the plan`). The relay is therefore a second committer, but only for that one file and never a model; Claude remains the only committer of code. `--allow-dirty` skips the check. `run_plan` also saves state on `KeyboardInterrupt`, which Task 11's Ctrl+C handling depends on.

- [ ] **Step 1: Write the failing state test**

`tests/test_state.py`:

```python
from pathlib import Path

from whyline_relay import state


def sample() -> state.RelayState:
    return state.RelayState(
        plan="plan.md",
        branch="relay/plan",
        task_id="WL-2",
        round=2,
        base_commit="abc123",
        paused_reason="codex exited without handing off",
        log_path="/tmp/x.log",
    )


def test_load_returns_none_when_absent(tmp_path: Path):
    assert state.load(tmp_path) is None


def test_save_then_load_round_trips(tmp_path: Path):
    state.save(tmp_path, sample())
    assert state.load(tmp_path) == sample()


def test_clear_removes_it(tmp_path: Path):
    state.save(tmp_path, sample())
    state.clear(tmp_path)
    assert state.load(tmp_path) is None


def test_corrupt_state_reads_as_absent(tmp_path: Path):
    target = tmp_path / ".whyline" / "relay"
    target.mkdir(parents=True)
    (target / "state.json").write_text("{broken")
    assert state.load(tmp_path) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_state.py -v`
Expected: FAIL — no module named `whyline_relay.state`.

- [ ] **Step 3: Write `src/whyline_relay/state.py`**

```python
"""Where the relay is, so `resume` can pick it up."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
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


def path(root: Path) -> Path:
    return config.relay_dir(root) / "state.json"


def save(root: Path, value: RelayState) -> None:
    """Write atomically: a half-written state file would strand a resume."""
    target = path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(asdict(value), indent=2), encoding="utf-8")
    os.replace(temporary, target)


def load(root: Path) -> RelayState | None:
    try:
        record = json.loads(path(root).read_text(encoding="utf-8"))
        return RelayState(**record)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def clear(root: Path) -> None:
    path(root).unlink(missing_ok=True)
```

- [ ] **Step 4: Write the failing multi-task test**

`tests/test_loop_plan.py`:

```python
import subprocess
import sys
from pathlib import Path

import pytest

from whyline_relay import config, loop, plan

FAKE = str(Path(__file__).parent / "fake_agent.py")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-b", "relay/plan")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    (tmp_path / "README.md").write_text("x\n")
    (tmp_path / ".whyline").mkdir()
    (tmp_path / ".whyline" / ".gitignore").write_text("active-handoff.json\nledger.jsonl\n")
    (tmp_path / "plan.md").write_text("- [ ] WL-1: One\n- [ ] WL-2: Two\n")
    git("add", "-A")
    git("commit", "-m", "initial")
    monkeypatch.setattr(loop.whylinecmd, "sync", lambda root, task, runner=None: "PACKET")
    monkeypatch.setattr(loop.whylinecmd, "claim", lambda *a, **k: None)
    return tmp_path


def approving_settings(root: Path, monkeypatch) -> config.Config:
    base = config.load(root)
    settings = config.Config(
        plan=base.plan,
        max_rounds=base.max_rounds,
        timeout_minutes=base.timeout_minutes,
        branch_prefix=base.branch_prefix,
        agents={
            "codex": [sys.executable, FAKE, "review", str(root)],
            "claude": [sys.executable, FAKE, "approve", str(root)],
        },
        status_map=base.status_map,
    )
    real_run = loop.agents.run
    counter = {"n": 0}

    def run_then_commit(command, prompt, **kwargs):
        code = real_run(command, prompt, **kwargs)
        if "approve" in command:
            counter["n"] += 1
            task_id = "WL-1" if counter["n"] == 1 else "WL-2"
            (root / f"f{counter['n']}.py").write_text("x = 1\n")
            subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", f"feat: work ({task_id})"],
                cwd=root,
                check=True,
                capture_output=True,
            )
        return code

    monkeypatch.setattr(loop.agents, "run", run_then_commit)
    return settings


def test_runs_every_unchecked_task_and_ticks_each(repo: Path, monkeypatch):
    settings = approving_settings(repo, monkeypatch)
    outcomes = loop.run_plan(repo, settings, repo / "plan.md", branch="relay/plan", echo=False)
    assert [outcome.task_id for outcome in outcomes] == ["WL-1", "WL-2"]
    tasks = plan.parse((repo / "plan.md").read_text())
    assert all(task.checked for task in tasks)


def test_only_runs_a_single_named_task(repo: Path, monkeypatch):
    settings = approving_settings(repo, monkeypatch)
    outcomes = loop.run_plan(
        repo, settings, repo / "plan.md", branch="relay/plan", only="WL-1", echo=False
    )
    assert [outcome.task_id for outcome in outcomes] == ["WL-1"]
    tasks = plan.parse((repo / "plan.md").read_text())
    assert [task.checked for task in tasks] == [True, False]


def test_a_pause_saves_resumable_state(repo: Path, monkeypatch):
    from whyline_relay import state

    base = config.load(repo)
    settings = config.Config(
        plan=base.plan,
        max_rounds=base.max_rounds,
        timeout_minutes=base.timeout_minutes,
        branch_prefix=base.branch_prefix,
        agents={
            "codex": [sys.executable, FAKE, "silent", str(repo)],
            "claude": [sys.executable, FAKE, "approve", str(repo)],
        },
        status_map=base.status_map,
    )
    with pytest.raises(loop.Paused):
        loop.run_plan(repo, settings, repo / "plan.md", branch="relay/plan", echo=False)
    saved = state.load(repo)
    assert saved.task_id == "WL-1"
    assert "without handing off" in saved.paused_reason
    assert plan.parse((repo / "plan.md").read_text())[0].checked is False


def test_stop_file_prevents_starting_a_new_task(repo: Path, monkeypatch):
    settings = approving_settings(repo, monkeypatch)
    stop = repo / ".whyline" / "relay"
    stop.mkdir(parents=True, exist_ok=True)
    (stop / "STOP").write_text("")
    outcomes = loop.run_plan(repo, settings, repo / "plan.md", branch="relay/plan", echo=False)
    assert outcomes == []
    assert plan.parse((repo / "plan.md").read_text())[0].checked is False


def test_success_clears_state(repo: Path, monkeypatch):
    from whyline_relay import state

    settings = approving_settings(repo, monkeypatch)
    loop.run_plan(repo, settings, repo / "plan.md", branch="relay/plan", echo=False)
    assert state.load(repo) is None


def test_ticking_keeps_an_edit_an_agent_made_to_the_plan(repo: Path, monkeypatch):
    settings = approving_settings(repo, monkeypatch)
    planfile = repo / "plan.md"
    inner = loop.agents.run

    def edit_the_plan(command, prompt, **kwargs):
        if "review" in command:  # the implementer's turn
            with planfile.open("a") as handle:
                handle.write("- [ ] WL-3: Three\n")
        return inner(command, prompt, **kwargs)

    monkeypatch.setattr(loop.agents, "run", edit_the_plan)
    loop.run_plan(repo, settings, planfile, branch="relay/plan", only="WL-1", echo=False)
    assert "WL-3" in planfile.read_text()


def test_an_unknown_only_id_is_an_error_not_a_silent_success(repo: Path, monkeypatch):
    settings = approving_settings(repo, monkeypatch)
    with pytest.raises(plan.PlanError):
        loop.run_plan(
            repo, settings, repo / "plan.md", branch="relay/plan", only="WL-99", echo=False
        )


def test_a_pause_under_only_remembers_it(repo: Path):
    from whyline_relay import state

    base = config.load(repo)
    settings = config.Config(
        plan=base.plan,
        max_rounds=base.max_rounds,
        timeout_minutes=base.timeout_minutes,
        branch_prefix=base.branch_prefix,
        agents={
            "codex": [sys.executable, FAKE, "silent", str(repo)],
            "claude": [sys.executable, FAKE, "approve", str(repo)],
        },
        status_map=base.status_map,
    )
    with pytest.raises(loop.Paused):
        loop.run_plan(
            repo, settings, repo / "plan.md", branch="relay/plan", only="WL-2", echo=False
        )
    assert state.load(repo).only == "WL-2"


def test_resume_reuses_the_saved_base_commit(repo: Path):
    from whyline_relay import state

    base_commit = loop.gitcheck.head_commit(repo)
    (repo / "feature.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: work (WL-1)"],
        cwd=repo,
        check=True,
        capture_output=True,
    )  # the reviewer committed, then the run stopped before the box was ticked
    state.save(
        repo,
        state.RelayState(
            plan=str(repo / "plan.md"),
            branch="relay/plan",
            task_id="WL-1",
            round=1,
            base_commit=base_commit,
            paused_reason="interrupted",
            log_path="",
        ),
    )
    base = config.load(repo)
    settings = config.Config(
        plan=base.plan,
        max_rounds=base.max_rounds,
        timeout_minutes=base.timeout_minutes,
        branch_prefix=base.branch_prefix,
        agents={
            "codex": [sys.executable, FAKE, "review", str(repo)],
            "claude": [sys.executable, FAKE, "approve", str(repo)],
        },
        status_map=base.status_map,
    )
    outcomes = loop.run_plan(
        repo, settings, repo / "plan.md", branch="relay/plan",
        only="WL-1", resume=True, echo=False,
    )
    assert [outcome.task_id for outcome in outcomes] == ["WL-1"]


def head_files(repo: Path) -> list[str]:
    return subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.split()


def test_each_tick_is_committed_on_its_own_and_the_tree_stays_clean(
    repo: Path, monkeypatch
):
    settings = approving_settings(repo, monkeypatch)
    loop.run_plan(repo, settings, repo / "plan.md", branch="relay/plan", echo=False)
    assert head_files(repo) == ["plan.md"]  # the last tick, alone
    assert loop.gitcheck.dirty_paths(repo) == []
    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    assert "chore: tick WL-1 in the plan" in log
    assert "chore: tick WL-2 in the plan" in log


def test_leftover_files_after_an_approval_pause_and_resume_recovers(
    repo: Path, monkeypatch
):
    from whyline_relay import state

    settings = approving_settings(repo, monkeypatch)
    real = loop.agents.run

    def commit_only_feature(command, prompt, **kwargs):
        code = real(command, prompt, **kwargs)
        if "approve" in command:
            (repo / "feature.py").write_text("x = 1\n")
            (repo / "stray.txt").write_text("oops\n")
            subprocess.run(["git", "add", "feature.py"], cwd=repo, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "feat: work (WL-1)"],
                cwd=repo, check=True, capture_output=True,
            )
        return code

    monkeypatch.setattr(loop.agents, "run", commit_only_feature)
    with pytest.raises(loop.Paused) as raised:
        loop.run_plan(
            repo, settings, repo / "plan.md", branch="relay/plan", only="WL-1", echo=False
        )
    assert "stray.txt" in raised.value.reason
    assert plan.parse((repo / "plan.md").read_text())[0].checked is False
    assert state.load(repo).task_id == "WL-1"

    (repo / "stray.txt").unlink()

    def no_agent(*args, **kwargs):
        raise AssertionError("resume of an approved task must not run an agent")

    monkeypatch.setattr(loop.agents, "run", no_agent)
    outcomes = loop.run_plan(
        repo, settings, repo / "plan.md", branch="relay/plan",
        only="WL-1", resume=True, echo=False,
    )
    assert [outcome.task_id for outcome in outcomes] == ["WL-1"]
    assert plan.parse((repo / "plan.md").read_text())[0].checked is True
    assert loop.gitcheck.dirty_paths(repo) == []


def test_resume_goes_straight_to_the_review_when_codex_already_handed_off(
    repo: Path, monkeypatch
):
    settings = approving_settings(repo, monkeypatch)
    inner = loop.agents.run
    calls: list[str] = []
    interrupt = {"on": True}

    def spy(command, prompt, **kwargs):
        agent = "codex" if "review" in command else "claude"
        calls.append(agent)
        if agent == "claude" and interrupt["on"]:
            raise KeyboardInterrupt  # Ctrl+C during the review turn
        return inner(command, prompt, **kwargs)

    monkeypatch.setattr(loop.agents, "run", spy)
    with pytest.raises(KeyboardInterrupt):
        loop.run_plan(
            repo, settings, repo / "plan.md", branch="relay/plan", only="WL-1", echo=False
        )
    interrupt["on"] = False
    calls.clear()
    loop.run_plan(
        repo, settings, repo / "plan.md", branch="relay/plan",
        only="WL-1", resume=True, echo=False,
    )
    assert calls == ["claude"]
```

Also append to `tests/test_gitcheck.py`:

```python
def test_dirty_paths_lists_modified_and_untracked_files(repo: Path):
    (repo / "README.md").write_text("changed\n")
    (repo / "new.txt").write_text("x")
    assert sorted(gitcheck.dirty_paths(repo)) == ["README.md", "new.txt"]


def test_commit_paths_commits_only_the_named_files(repo: Path):
    (repo / "README.md").write_text("changed\n")
    (repo / "other.txt").write_text("x")
    gitcheck.commit_paths(repo, [repo / "README.md"], "chore: tick WL-1 in the plan")
    assert gitcheck.dirty_paths(repo) == ["other.txt"]
    assert gitcheck.commit_message(repo, gitcheck.head_commit(repo)) == "chore: tick WL-1 in the plan"
    before = gitcheck.head_commit(repo)
    gitcheck.commit_paths(repo, [repo / "README.md"], "chore: again")
    assert gitcheck.head_commit(repo) == before
```

- [ ] **Step 5: Run it to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_loop_plan.py -v`
Expected: FAIL — `AttributeError: module 'whyline_relay.loop' has no attribute 'run_plan'`.

- [ ] **Step 6: Add `run_plan` and the stop file to `loop.py`**

First append to `src/whyline_relay/gitcheck.py`:

```python
def dirty_paths(root: Path) -> list[str]:
    """Paths `git status` reports as changed or untracked, ignored files excluded."""
    output = _git(root, "status", "--porcelain", "--untracked-files=all")
    return [line.split(maxsplit=1)[1] for line in output.splitlines() if line.strip()]


def commit_paths(root: Path, paths: list[Path], message: str) -> None:
    """Commit only `paths`, leaving everything else in the tree alone.

    Does nothing when those paths have no changes, so it is safe to repeat.
    """
    try:
        relative = [str(Path(p).resolve().relative_to(root.resolve())) for p in paths]
    except ValueError as error:
        raise GitError(f"{error}: a path lies outside the repository") from error
    _git(root, "add", "--", *relative)
    if not _git(root, "diff", "--cached", "--name-only", "--", *relative):
        return
    _git(root, "commit", "-m", message, "--", *relative)
```

Then add `from whyline_relay import state` to the imports of `loop.py`, and append:

```python
def stop_path(root: Path) -> Path:
    return config.relay_dir(root) / "STOP"


def stop_requested(root: Path) -> bool:
    return stop_path(root).exists()


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
        ),
    )


def _require_clean(root: Path, plan_path: Path, task: plan.Task) -> None:
    """After an approval nothing may be left uncommitted, or it rides into the next task.

    The plan file is exempt: it is ticked and committed straight afterwards.
    """
    try:
        own = str(plan_path.resolve().relative_to(root.resolve()))
    except ValueError:
        own = None
    leftovers = [path for path in gitcheck.dirty_paths(root) if path != own]
    if leftovers:
        raise Paused(
            f"{task.task_id} was approved and committed, but files are still "
            f"uncommitted ({', '.join(leftovers[:5])}). Stash or remove them (do not "
            "commit them: the relay verifies the last commit's message), then resume, "
            "or resume with --allow-dirty."
        )


def _tick_and_commit(root: Path, plan_path: Path, task: plan.Task) -> None:
    """Tick the box and commit that one file, so the tree is clean after every approval.

    Re-reads the plan first: an agent may have edited it while it worked, and
    ticking a copy read before the run would silently overwrite that edit.
    """
    current = plan_path.read_text(encoding="utf-8")
    plan_path.write_text(plan.tick(current, task.task_id), encoding="utf-8")
    gitcheck.commit_paths(root, [plan_path], f"chore: tick {task.task_id} in the plan")


def run_plan(
    root: Path,
    settings: config.Config,
    plan_path: Path,
    *,
    branch: str,
    only: str | None = None,
    resume: bool = False,
    allow_dirty: bool = False,
    echo: bool = True,
) -> list[Outcome]:
    """Run every unchecked task in file order. Tick each only after it commits.

    With `resume`, the first task re-enters where it stopped: it reuses the base
    commit saved when it paused (the reviewer may already have committed, and a
    fresh base would make the approval unverifiable) and the round it was on,
    and `run_task` picks the next agent from the handoff record.
    """
    outcomes: list[Outcome] = []
    resuming = state.load(root) if resume else None
    while True:
        if stop_requested(root):
            print("STOP file present; not starting another task.")
            return outcomes
        tasks = plan.parse(plan_path.read_text(encoding="utf-8"))
        if only:
            task = plan.find(tasks, only)
            if task is None:
                raise plan.PlanError(f"no task {only!r} in the plan")
        else:
            task = plan.next_unchecked(tasks)
        if task is None or task.checked:
            state.clear(root)
            return outcomes

        mid_task = resuming is not None and resuming.task_id == task.task_id
        base_commit = resuming.base_commit if mid_task else gitcheck.head_commit(root)
        start_round = (resuming.round or 1) if mid_task else 1
        resuming = None
        progress = {"round": start_round, "last": None}

        def on_turn(round_: int, previous_id: str | None) -> None:
            progress["round"] = round_
            progress["last"] = previous_id

        try:
            outcome = run_task(
                root,
                settings,
                task,
                base_commit=base_commit,
                echo=echo,
                resume=mid_task,
                start_round=start_round,
                on_turn=on_turn,
            )
            if not allow_dirty:
                _require_clean(root, plan_path, task)
        except Paused as paused:
            _save_pause(
                root, plan_path, branch, task, base_commit,
                paused.reason, paused.log_path, only, progress,
            )
            raise
        except KeyboardInterrupt:
            _save_pause(
                root, plan_path, branch, task, base_commit,
                "interrupted by the user (Ctrl+C)", None, only, progress,
            )
            raise

        _tick_and_commit(root, plan_path, task)
        outcomes.append(outcome)
        if only:
            state.clear(root)
            return outcomes
```

- [ ] **Step 7: Run the suite**

Run: `cd /Users/anish/whyline-relay && uv run pytest -v`
Expected: all pass.

- [ ] **Step 8: Hand off (Codex), then commit (Claude)**

**Codex:** do not stage or commit. Hand off, then stop:

```bash
whyline handoff RELAY-9 --from codex --to claude --status ready-for-review \
  --summary "<what you changed>" --file <each file you touched> \
  --test "uv run pytest -v: <result>" --risk "<anything the reviewer should check>"
```

**Claude:** only after the review approves, commit, then record the approval:

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: multi-task runs, stop file, and resumable state (RELAY-9)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
whyline handoff RELAY-9 --from claude --to claude --status approved --summary "<what you approved>"
```

---

### Task 10: Guards, resume, status, stop — milestone M3, part 2

**Files:**
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/cli.py`
- Test: `/Users/anish/whyline-relay/tests/test_cli_commands.py`

**Interfaces:**
- Consumes: `state.RelayState`, `loop.run_plan`, `gitcheck`, `config.Config`.
- Produces: `cli.cmd_resume`, `cli.cmd_status`, `cli.cmd_stop`, `cli.guard(root, args, branch) -> str | None` returning a refusal message or `None`; `branch` is the branch the agents will commit to.

**Revised after pre-review (RELAY-10).** Probed with real repositories, the CLI had three defects, all fixed below. (1) `guard` checked the branch you *started on*, so `whyline-relay start` from `main` (the normal starting point, and the spec's default) was refused, and `--branch NAME` did not lift the refusal its own message tells you to use. It now checks the branch the agents will commit to. (2) `resume` never switched back to the saved branch, so resuming from `main` would let the agents commit to `main`, bypassing the guard; it now calls `ensure_branch(saved.branch)`, reuses the saved base commit and `--only`, takes `--allow-dirty`, and reports git, whyline and plan errors instead of a traceback. (3) A malformed plan or an unknown `--only` id raised a traceback or exited 0; both are now clear errors with exit 1.

- [ ] **Step 1: Write the failing test**

`tests/test_cli_commands.py`:

```python
import subprocess
import sys
from pathlib import Path

import pytest

from whyline_relay import cli, gitcheck, state

FAKE = str(Path(__file__).parent / "fake_agent.py")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    (tmp_path / "README.md").write_text("x\n")
    git("add", "-A")
    git("commit", "-m", "initial")
    (tmp_path / ".whyline").mkdir()
    (tmp_path / "plan.md").write_text("- [ ] WL-1: One\n")
    return tmp_path


def test_refuses_to_run_on_main(repo: Path, capsys):
    code = cli.main(["start", "--repo", str(repo), "--branch", "main", "--allow-dirty"])
    assert code == cli.EXIT_ERROR
    assert "main" in capsys.readouterr().err


def test_allow_main_lifts_the_branch_refusal(repo: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli.loop, "run_plan", lambda *a, **k: [])
    code = cli.main(
        ["start", "--repo", str(repo), "--branch", "main", "--allow-main", "--allow-dirty"]
    )
    assert code == cli.EXIT_OK


def test_starting_from_main_switches_to_the_relay_branch(repo: Path, monkeypatch, capsys):
    """The guard is about where the agents will commit, not where you started."""
    monkeypatch.setattr(cli.loop, "run_plan", lambda *a, **k: [])
    code = cli.main(["start", "--repo", str(repo), "--allow-dirty"])
    assert code == cli.EXIT_OK, capsys.readouterr().err
    assert gitcheck.current_branch(repo) == "relay/plan"


def test_the_branch_flag_names_the_branch_to_use(repo: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli.loop, "run_plan", lambda *a, **k: [])
    code = cli.main(["start", "--repo", str(repo), "--branch", "feature/x", "--allow-dirty"])
    assert code == cli.EXIT_OK, capsys.readouterr().err
    assert gitcheck.current_branch(repo) == "feature/x"


def test_an_unknown_only_id_is_an_error(repo: Path, capsys):
    code = cli.main(["start", "--repo", str(repo), "--only", "WL-99", "--allow-dirty"])
    assert code == cli.EXIT_ERROR
    assert "WL-99" in capsys.readouterr().err


def test_a_malformed_plan_is_a_clear_error(repo: Path, capsys):
    (repo / "plan.md").write_text("- [ ] WL-1: a\n- [ ] WL-1: b\n")
    code = cli.main(["start", "--repo", str(repo), "--allow-dirty"])
    assert code == cli.EXIT_ERROR
    assert "duplicate" in capsys.readouterr().err


def test_refuses_a_dirty_tree(repo: Path, capsys):
    (repo / "scratch.txt").write_text("x")
    code = cli.main(["start", "--repo", str(repo), "--allow-main"])
    assert code == cli.EXIT_ERROR
    assert "uncommitted" in capsys.readouterr().err.lower()


def test_stop_writes_the_stop_file(repo: Path):
    assert cli.main(["stop", "--repo", str(repo)]) == cli.EXIT_OK
    assert (repo / ".whyline" / "relay" / "STOP").exists()


def test_status_reports_nothing_in_progress(repo: Path, capsys):
    assert cli.main(["status", "--repo", str(repo)]) == cli.EXIT_OK
    assert "no relay run in progress" in capsys.readouterr().out.lower()


def test_status_reports_the_saved_pause(repo: Path, capsys):
    state.save(
        repo,
        state.RelayState(
            plan="plan.md",
            branch="relay/plan",
            task_id="WL-1",
            round=2,
            base_commit="abc",
            paused_reason="codex exited without handing off",
            log_path="/tmp/x.log",
        ),
    )
    cli.main(["status", "--repo", str(repo)])
    out = capsys.readouterr().out
    assert "WL-1" in out
    assert "without handing off" in out


def test_resume_without_saved_state_is_an_error(repo: Path, capsys):
    assert cli.main(["resume", "--repo", str(repo)]) == cli.EXIT_ERROR
    assert "nothing to resume" in capsys.readouterr().err.lower()


def test_resume_clears_the_stop_file_before_continuing(repo: Path, monkeypatch):
    relay = repo / ".whyline" / "relay"
    relay.mkdir(parents=True)
    (relay / "STOP").write_text("")
    state.save(
        repo,
        state.RelayState(
            plan=str(repo / "plan.md"),
            branch="relay/plan",
            task_id="WL-1",
            round=1,
            base_commit="abc",
            paused_reason="paused",
            log_path="",
        ),
    )
    monkeypatch.setattr(cli.loop, "run_plan", lambda *a, **k: [])
    assert cli.main(["resume", "--repo", str(repo)]) == cli.EXIT_OK
    assert not (relay / "STOP").exists()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_resume_reuses_the_saved_base_commit(repo: Path, monkeypatch, capsys):
    relay = repo / ".whyline" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "config.toml").write_text(
        f'[agents.codex]\ncommand = ["{sys.executable}", "{FAKE}", "review", "{repo}"]\n'
        f'[agents.claude]\ncommand = ["{sys.executable}", "{FAKE}", "approve", "{repo}"]\n'
    )
    monkeypatch.setattr(cli.loop.whylinecmd, "sync", lambda root, task, runner=None: "PACKET")
    monkeypatch.setattr(cli.loop.whylinecmd, "claim", lambda *a, **k: None)
    (repo / ".whyline" / ".gitignore").write_text("active-handoff.json\nledger.jsonl\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "relay setup")
    _git(repo, "checkout", "-b", "relay/plan")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "feature.py").write_text("x = 1\n")
    _git(repo, "add", "feature.py")
    _git(repo, "commit", "-m", "feat: work (WL-1)")  # committed, then the run stopped
    state.save(
        repo,
        state.RelayState(
            plan=str(repo / "plan.md"),
            branch="relay/plan",
            task_id="WL-1",
            round=1,
            base_commit=base,
            paused_reason="interrupted",
            log_path="",
        ),
    )
    assert cli.main(["resume", "--repo", str(repo)]) == cli.EXIT_OK, capsys.readouterr().err


def test_resume_returns_to_the_saved_branch(repo: Path, monkeypatch):
    """Resuming from main must not let the agents commit to main."""
    _git(repo, "branch", "relay/plan")
    state.save(
        repo,
        state.RelayState(
            plan=str(repo / "plan.md"),
            branch="relay/plan",
            task_id="WL-1",
            round=1,
            base_commit=_git(repo, "rev-parse", "HEAD"),
            paused_reason="paused",
            log_path="",
        ),
    )
    monkeypatch.setattr(cli.loop, "run_plan", lambda *a, **k: [])
    assert cli.main(["resume", "--repo", str(repo)]) == cli.EXIT_OK
    assert gitcheck.current_branch(repo) == "relay/plan"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_cli_commands.py -v`
Expected: FAIL — unknown subcommands `stop`, `status`, `resume`.

- [ ] **Step 3: Extend `cli.py`**

Add these subparsers inside `build_parser`, after the existing `start` block:

```python
    start.add_argument("--allow-main", action="store_true")
    start.add_argument("--allow-dirty", action="store_true")
    start.add_argument("--max-rounds", type=int, default=None)
    start.add_argument("--timeout", type=int, default=None, metavar="MIN")

    resume = subparsers.add_parser("resume", help="Continue after a pause")
    resume.add_argument("--repo", default=".")
    resume.add_argument("--allow-dirty", action="store_true")

    status = subparsers.add_parser("status", help="Where the relay is")
    status.add_argument("--repo", default=".")

    stop = subparsers.add_parser("stop", help="Stop after the current agent finishes")
    stop.add_argument("--repo", default=".")
```

Add the guard and the three commands:

```python
def guard(root: Path, args: argparse.Namespace, branch: str) -> str | None:
    """Return a refusal message, or None when it is safe to start.

    `branch` is the branch the agents will commit to, not the one you are on:
    starting from main is normal, because the relay switches to its own branch.
    """
    if branch in ("main", "master") and not getattr(args, "allow_main", False):
        return (
            f"refusing to run on {branch}. Pass --branch NAME to use a different "
            "branch, or --allow-main if you really mean it."
        )
    if gitcheck.is_dirty(root) and not getattr(args, "allow_dirty", False):
        return (
            "refusing to start with uncommitted changes. Commit or stash them, "
            "or pass --allow-dirty."
        )
    return None


def cmd_resume(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    saved = state.load(root)
    if saved is None:
        print("Nothing to resume.", file=sys.stderr)
        return EXIT_ERROR
    loop.stop_path(root).unlink(missing_ok=True)
    settings = config.load(root)
    try:
        # Back onto the branch the run started on: the agents must not commit to
        # whatever happens to be checked out now, which could be main.
        gitcheck.ensure_branch(root, saved.branch)
        loop.run_plan(
            root,
            settings,
            Path(saved.plan),
            branch=saved.branch,
            only=saved.only or None,
            resume=True,
            allow_dirty=args.allow_dirty,
        )
    except loop.Paused as paused:
        return _report_pause(paused)
    except (gitcheck.GitError, whylinecmd.WhylineUnavailable, plan.PlanError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    print("Plan complete.")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    saved = state.load(root)
    if saved is None:
        print("No relay run in progress.")
        return EXIT_OK
    print(f"Task      {saved.task_id}")
    print(f"Branch    {saved.branch}")
    print(f"Plan      {saved.plan}")
    print(f"Paused    {saved.paused_reason}")
    if saved.log_path:
        print(f"Log       {saved.log_path}")
    print("Resume with: whyline-relay resume")
    return EXIT_OK


def cmd_stop(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    target = loop.stop_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("")
    print("STOP written. The current agent finishes; nothing new starts.")
    return EXIT_OK


def _report_pause(paused: loop.Paused) -> int:
    print(f"\nPaused: {paused.reason}", file=sys.stderr)
    if paused.log_path is not None:
        print(f"Log: {paused.log_path}", file=sys.stderr)
    print("Resume with: whyline-relay resume", file=sys.stderr)
    return EXIT_PAUSED
```

Add `from dataclasses import replace` and `from whyline_relay import state` to the imports, then replace `cmd_start` and `main` in full:

```python
def cmd_start(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    settings = config.load(root)
    if args.max_rounds is not None:
        settings = replace(settings, max_rounds=args.max_rounds)
    if args.timeout is not None:
        settings = replace(settings, timeout_minutes=args.timeout)

    plan_path = root / (args.plan or settings.plan)
    try:
        content = plan_path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"could not read the plan: {error}", file=sys.stderr)
        return EXIT_ERROR
    try:
        tasks = plan.parse(content)
    except plan.PlanError as error:
        print(f"invalid plan: {error}", file=sys.stderr)
        return EXIT_ERROR
    task = _task_for(tasks, args.only)
    if task is None:
        if args.only:
            print(f"no task {args.only!r} in the plan", file=sys.stderr)
            return EXIT_ERROR
        print("Nothing to do: no unchecked tasks in the plan.")
        return EXIT_OK

    if args.dry_run:
        packet = whylinecmd.sync(root, task.task_id)
        rendered = prompts.render(
            prompts.load(root, "implement"),
            task_id=task.task_id,
            task_text=task.text,
            sync_packet=packet,
            round_=1,
            review_feedback="",
        )
        argv = agents.build_argv(settings.agents["codex"], rendered)
        print(f"Next task: {task.task_id}")
        print(f"Would run: {shlex.join(argv[:-1])} <prompt>")
        print("--- prompt ---")
        print(rendered)
        return EXIT_OK

    branch = args.branch or f"{settings.branch_prefix}{plan_path.stem}"
    refusal = guard(root, args, branch)
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return EXIT_ERROR

    try:
        gitcheck.ensure_branch(root, branch)
        outcomes = loop.run_plan(
            root,
            settings,
            plan_path,
            branch=branch,
            only=args.only,
            allow_dirty=args.allow_dirty,
        )
    except loop.Paused as paused:
        return _report_pause(paused)
    except (gitcheck.GitError, whylinecmd.WhylineUnavailable, plan.PlanError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    print(f"\nPlan complete: {len(outcomes)} task(s) approved and committed.")
    notify.send("whyline-relay", f"{len(outcomes)} task(s) done")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    commands = {
        "start": cmd_start,
        "resume": cmd_resume,
        "status": cmd_status,
        "stop": cmd_stop,
    }
    return commands[args.command](args)
```

The guard runs after the dry-run branch on purpose: `--dry-run` prints what would
happen and touches nothing, so refusing it on a dirty tree would only make the
tool harder to inspect. `notify` arrives in Task 11 — until then, drop that one
line.

- [ ] **Step 4: Run the suite**

Run: `cd /Users/anish/whyline-relay && uv run pytest -v`
Expected: all pass.

- [ ] **Step 5: Hand off (Codex), then commit (Claude)**

**Codex:** do not stage or commit. Hand off, then stop:

```bash
whyline handoff RELAY-10 --from codex --to claude --status ready-for-review \
  --summary "<what you changed>" --file <each file you touched> \
  --test "uv run pytest -v: <result>" --risk "<anything the reviewer should check>"
```

**Claude:** only after the review approves, commit, then record the approval:

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: branch and dirty guards, resume, status, stop (RELAY-10)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
whyline handoff RELAY-10 --from claude --to claude --status approved --summary "<what you approved>"
```

---

### Task 11: Ctrl+C and notifications

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/notify.py`
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/cli.py`
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/agents.py` (stop the agent on Ctrl+C)
- Test: `/Users/anish/whyline-relay/tests/test_notify.py`
- Test: `/Users/anish/whyline-relay/tests/test_interrupt.py`
- Create: `/Users/anish/whyline-relay/tests/conftest.py` (keep tests from popping real desktop notifications)

**Interfaces:**
- Consumes: nothing.
- Produces: `notify.command(title: str, message: str, platform: str) -> list[str] | None`; `notify.send(title: str, message: str, runner=None, platform: str | None = None) -> None`.

**Revised after pre-review (RELAY-11).** The plan claimed Ctrl+C "saves state" and that "the agent's own process group dies with it", and tested neither. Probed with a real hanging agent, Ctrl+C left the agent running as an orphan (still editing the repository) and saved no state, so `resume` reported "Nothing to resume" right after the CLI told you to resume. `agents.run` now stops the agent's process group on any unwind, `run_plan` saves state on `KeyboardInterrupt` (Task 9), and `tests/test_interrupt.py` proves both with a real process. A third problem, found by probing Codex's own sandbox: `pgrep` and `pkill` fail there (`sysmond service not found … Cannot get process list`), so an interrupt test that lists processes would pass vacuously under Codex, proving nothing. The test therefore has the hanging agent write its own pid and checks it with `os.kill(pid, 0)`, which needs no process listing, and it fails if the agent never started. A fourth: the CLI calls `notify.send`, so the tests that run `cli.main(["start", ...])` executed the real `osascript` and popped desktop notifications on every run (measured with a tripwire: 3 calls); `tests/conftest.py` now stubs the CLI's notifier for every test, and `test_notify.py` still exercises the real notifier code.

- [ ] **Step 1: Write the failing test**

`tests/test_notify.py`:

```python
from whyline_relay import notify


def test_macos_uses_osascript():
    argv = notify.command("Relay", "Paused on WL-1", "darwin")
    assert argv[0] == "osascript"
    assert any("Paused on WL-1" in part for part in argv)


def test_linux_uses_notify_send():
    argv = notify.command("Relay", "Paused on WL-1", "linux")
    assert argv[0] == "notify-send"


def test_unknown_platform_gets_no_command():
    assert notify.command("Relay", "x", "win32") is None


def test_send_never_raises_when_the_notifier_is_missing():
    def explode(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    notify.send("Relay", "x", runner=explode, platform="linux")


def test_quotes_in_the_message_do_not_break_the_applescript():
    argv = notify.command("Relay", 'he said "stop"', "darwin")
    assert '"stop"' not in argv[-1] or "\\" in argv[-1]
```

Also create `tests/conftest.py`:

```python
"""Shared test setup."""

import types

import pytest

from whyline_relay import cli


@pytest.fixture(autouse=True)
def no_desktop_notifications(monkeypatch):
    """The CLI announces pauses and completions; a test run must never pop a real one."""
    monkeypatch.setattr(
        cli, "notify", types.SimpleNamespace(send=lambda *args, **kwargs: None)
    )
```

Also create `tests/test_interrupt.py`:

```python
"""Ctrl+C must stop the running agent and leave state that `resume` can use."""

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from whyline_relay import cli, config, loop, state

FAKE = str(Path(__file__).parent / "fake_agent.py")


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / "plan.md").write_text("- [ ] WL-1: One\n")
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True)
    # An agent that records its pid and then hangs. Recording the pid, rather than
    # listing processes with pgrep, keeps the test able to fail inside a sandbox
    # that cannot list processes (Codex's cannot: "Cannot get process list").
    hang = f"import os, time; open({str(tmp_path / 'agent.pid')!r}, 'w').write(str(os.getpid())); time.sleep(600)"
    (relay / "config.toml").write_text(
        f'[agents.codex]\ncommand = ["{sys.executable}", "-c", {json.dumps(hang)}]\n'
        f'[agents.claude]\ncommand = ["{sys.executable}", "{FAKE}", "approve", "{tmp_path}"]\n'
    )
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "initial")
    monkeypatch.setattr(loop.whylinecmd, "sync", lambda root, task, runner=None: "PACKET")
    monkeypatch.setattr(loop.whylinecmd, "claim", lambda *a, **k: None)
    return tmp_path


def test_run_plan_saves_state_when_interrupted(repo: Path, monkeypatch):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(loop, "run_task", interrupted)
    with pytest.raises(KeyboardInterrupt):
        loop.run_plan(
            repo, config.load(repo), repo / "plan.md", branch="relay/plan", echo=False
        )
    saved = state.load(repo)
    assert saved.task_id == "WL-1"
    assert "interrupted" in saved.paused_reason


def test_ctrl_c_stops_the_agent_process_and_saves_state(repo: Path):
    pid_file = repo / "agent.pid"
    previous = signal.getsignal(signal.SIGINT)
    timer = threading.Timer(2.0, os.kill, (os.getpid(), signal.SIGINT))
    timer.start()
    try:
        code = cli.main(["start", "--repo", str(repo)])
    finally:
        timer.cancel()
        signal.signal(signal.SIGINT, previous)
    assert pid_file.exists(), "the agent never started, so this test proved nothing"
    pid = int(pid_file.read_text())
    try:
        os.kill(pid, 0)  # raises if the process is gone
    except ProcessLookupError:
        outlived = False
    else:
        outlived = True
        os.kill(pid, signal.SIGKILL)  # never leave an orphan behind
    assert code == cli.EXIT_PAUSED
    assert not outlived, "the agent outlived Ctrl+C"
    saved = state.load(repo)
    assert saved is not None and saved.task_id == "WL-1"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_notify.py -v`
Expected: FAIL — no module named `whyline_relay.notify`.

- [ ] **Step 3: Write `src/whyline_relay/notify.py`**

```python
"""Best-effort desktop notification. No network, no service, never fatal."""

from __future__ import annotations

import subprocess
import sys


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def command(title: str, message: str, platform: str) -> list[str] | None:
    """The argv for this platform's notifier, or None if we do not know one."""
    if platform == "darwin":
        script = f'display notification "{_escape(message)}" with title "{_escape(title)}"'
        return ["osascript", "-e", script]
    if platform.startswith("linux"):
        return ["notify-send", title, message]
    return None


def send(title: str, message: str, runner=None, platform: str | None = None) -> None:
    """Notify if we can. A missing notifier is not an error worth surfacing."""
    argv = command(title, message, platform or sys.platform)
    if argv is None:
        return
    run = runner if runner is not None else subprocess.run
    try:
        run(argv, capture_output=True)
    except (OSError, ValueError):
        return
```

- [ ] **Step 4: Add the SIGINT handler and notifications to `cli.py`**

Add to the imports: `import signal`, `from whyline_relay import notify`.

Add near the top of `main`, before dispatch:

```python
def _install_sigint_handler() -> None:
    """Ctrl+C stops the run; the agent's own process group dies with it.

    Agents are started with start_new_session=True, so SIGINT does not reach
    them automatically. loop.run_plan saves state on the way out, which is what
    makes `resume` possible.
    """

    def handler(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, handler)
```

Replace `main` so the interrupt is caught, and add the notification to `_report_pause`:

```python
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _install_sigint_handler()
    commands = {
        "start": cmd_start,
        "resume": cmd_resume,
        "status": cmd_status,
        "stop": cmd_stop,
    }
    try:
        return commands[args.command](args)
    except KeyboardInterrupt:
        print("\nInterrupted. Resume with: whyline-relay resume", file=sys.stderr)
        return EXIT_PAUSED


def _report_pause(paused: loop.Paused) -> int:
    print(f"\nPaused: {paused.reason}", file=sys.stderr)
    if paused.log_path is not None:
        print(f"Log: {paused.log_path}", file=sys.stderr)
    print("Resume with: whyline-relay resume", file=sys.stderr)
    notify.send("whyline-relay paused", paused.reason)
    return EXIT_PAUSED
```

`init` is deliberately absent from that table — `cmd_init` does not exist yet,
and a dict literal naming it would raise `NameError` on every command. Task 12
adds both together.

Then, in `agents.run` in `src/whyline_relay/agents.py`, replace

```python
        code = process.wait()
    finally:
        watchdog.cancel()
        hard_kill.cancel()
```

with

```python
        code = process.wait()
    except BaseException:
        # Ctrl+C, or anything else that unwinds us: the agent must not outlive
        # the relay. It runs in its own session, so SIGINT never reaches it.
        signal_group(signal.SIGTERM)
        try:
            process.wait(timeout=KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            signal_group(signal.SIGKILL)
            process.wait()
        raise
    finally:
        watchdog.cancel()
        hard_kill.cancel()
```

- [ ] **Step 5: Run the suite**

Run: `cd /Users/anish/whyline-relay && uv run pytest -v`
Expected: all pass.

- [ ] **Step 6: Hand off (Codex), then commit (Claude)**

**Codex:** do not stage or commit. Hand off, then stop:

```bash
whyline handoff RELAY-11 --from codex --to claude --status ready-for-review \
  --summary "<what you changed>" --file <each file you touched> \
  --test "uv run pytest -v: <result>" --risk "<anything the reviewer should check>"
```

**Claude:** only after the review approves, commit, then record the approval:

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: interrupt handling and desktop notifications (RELAY-11)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
whyline handoff RELAY-11 --from claude --to claude --status approved --summary "<what you approved>"
```

---

### Task 12: `init` — milestone M4

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/init.py`
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/cli.py`
- Modify: `/Users/anish/whyline-relay/README.md`
- Test: `/Users/anish/whyline-relay/tests/test_init.py`

**Interfaces:**
- Consumes: `prompts.IMPLEMENT`, `prompts.REVIEW`, `config.DEFAULTS`.
- Produces: `init.BASE_ALLOW: list[str]`; `init.DENY: list[str]`; `init.PRESETS: dict[str, list[str]]`; `init.detect_stack(root: Path) -> str`; `init.allowlist(stack: str) -> dict`; `init.run(root: Path, *, assume_yes: bool, confirm=input) -> int`.

**Revised after pre-review (RELAY-12).** `codex_hook_trusted` looked for `.codex/trust.json`, a file nothing creates (it exists in none of the repositories checked), so it always returned false and `init` always printed a misleading warning; and the relay does not need Codex hooks at all, because every prompt already embeds `whyline sync` output. The function and warning are replaced by an accurate note. `init` with no terminal (a script, CI) raised `EOFError`; it now writes nothing and exits non-zero. After the M2 real-CLI run (Task 8b), `init` also no longer merges into `.claude/settings.json`: Claude Code ignores a project's `permissions.allow` under `claude -p` until the workspace is trusted interactively, so a fresh checkout would silently get no permissions. `init` writes a relay-owned `.whyline/relay/claude-settings.json` instead, which the default Claude command passes with `--settings` (verified against the real CLI), and it leaves the user's `.claude/settings.json` alone. `init` also now says plainly that the allowlist is a convenience, not a sandbox: `uv run`, `npm` and `npx` execute arbitrary project code, so unattended runs belong on an isolated branch or repository holding no secrets.

- [ ] **Step 1: Write the failing test**

`tests/test_init.py`:

```python
import json
from pathlib import Path

from whyline_relay import init


def test_detects_python_from_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    assert init.detect_stack(tmp_path) == "python"


def test_detects_node_from_package_json(tmp_path: Path):
    (tmp_path / "package.json").write_text("{}")
    assert init.detect_stack(tmp_path) == "node"


def test_unknown_stack_falls_back_to_base(tmp_path: Path):
    assert init.detect_stack(tmp_path) == "base"


def test_allowlist_denies_push_and_recursive_delete():
    built = init.allowlist("python")
    assert "Bash(git push:*)" in built["permissions"]["deny"]
    assert "Bash(rm -rf:*)" in built["permissions"]["deny"]


def test_allowlist_never_contains_a_bypass_flag():
    for stack in ("python", "node", "base"):
        assert "dangerously" not in json.dumps(init.allowlist(stack))


def test_python_preset_allows_pytest():
    allowed = init.allowlist("python")["permissions"]["allow"]
    assert "Bash(pytest:*)" in allowed
    assert "Bash(uv run pytest:*)" in allowed


def test_node_preset_allows_npm_test():
    assert "Bash(npm test:*)" in init.allowlist("node")["permissions"]["allow"]


def test_run_writes_settings_templates_and_config(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    assert init.run(tmp_path, assume_yes=True) == 0
    settings = json.loads(
        (tmp_path / ".whyline" / "relay" / "claude-settings.json").read_text()
    )
    assert "Bash(whyline:*)" in settings["permissions"]["allow"]
    assert (tmp_path / ".whyline" / "relay" / "prompts" / "implement.md").exists()
    assert (tmp_path / ".whyline" / "relay" / "prompts" / "review.md").exists()
    assert (tmp_path / ".whyline" / "relay" / "config.toml").exists()


def test_declining_writes_nothing(tmp_path: Path):
    assert init.run(tmp_path, assume_yes=False, confirm=lambda prompt: "n") != 0
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".whyline" / "relay").exists()


def test_says_codex_hooks_are_not_needed(tmp_path: Path, capsys):
    (tmp_path / ".whyline").mkdir()
    init.run(tmp_path, assume_yes=True)
    out = capsys.readouterr().out
    assert "codex" in out.lower()
    assert "whyline sync" in out
    assert "dangerously" not in out


def test_no_terminal_means_nothing_is_written(tmp_path: Path):
    def no_terminal(prompt):
        raise EOFError

    assert init.run(tmp_path, assume_yes=False, confirm=no_terminal) != 0
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".whyline" / "relay").exists()


def test_says_the_allowlist_is_not_a_security_boundary(tmp_path: Path, capsys):
    init.run(tmp_path, assume_yes=True)
    out = capsys.readouterr().out
    assert "not a sandbox" in out
    assert "no secrets" in out


def test_the_permissions_file_is_the_relays_own_and_leaves_claude_settings_alone(
    tmp_path: Path,
):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text('{"model": "opus"}')
    init.run(tmp_path, assume_yes=True)
    assert json.loads((tmp_path / ".claude" / "settings.json").read_text()) == {"model": "opus"}
    command = json.loads(
        (tmp_path / ".whyline" / "relay" / "claude-settings.json").read_text()
    )
    assert "Bash(git commit:*)" in command["permissions"]["allow"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_init.py -v`
Expected: FAIL — no module named `whyline_relay.init`.

- [ ] **Step 3: Write `src/whyline_relay/init.py`**

```python
"""Declaring permission up front, so no agent run needs an interactive prompt."""

from __future__ import annotations

import json
from pathlib import Path

from whyline_relay import config, prompts

BASE_ALLOW = [
    "Edit",
    "Bash(git add:*)",
    "Bash(git commit:*)",
    "Bash(git diff:*)",
    "Bash(git status:*)",
    "Bash(git log:*)",
    "Bash(whyline:*)",
]

DENY = ["Bash(git push:*)", "Bash(rm -rf:*)"]

PRESETS = {
    "python": ["Bash(pytest:*)", "Bash(uv run pytest:*)", "Bash(uv run:*)"],
    "node": ["Bash(npm test:*)", "Bash(npm run:*)", "Bash(npx:*)"],
    "base": [],
}


def detect_stack(root: Path) -> str:
    if (root / "pyproject.toml").exists():
        return "python"
    if (root / "package.json").exists():
        return "node"
    return "base"


def allowlist(stack: str) -> dict:
    return {
        "permissions": {
            "allow": [*BASE_ALLOW, *PRESETS.get(stack, [])],
            "deny": list(DENY),
        }
    }


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run(root: Path, *, assume_yes: bool, confirm=input) -> int:
    stack = detect_stack(root)
    proposed = allowlist(stack)
    settings_path = config.relay_dir(root) / "claude-settings.json"

    print(f"Detected stack: {stack}")
    print(f"Proposed {settings_path}:")
    print(json.dumps(proposed, indent=2))
    print("Also writing prompt templates and config under .whyline/relay/.")
    if not assume_yes:
        try:
            answer = confirm("Write these? [Y/n] ").strip().lower()
        except EOFError:  # no terminal: writing files nobody agreed to is worse
            answer = "n"
        if answer and not answer.startswith("y"):
            print("Nothing written.")
            return 1

    relay = config.relay_dir(root)
    _write(settings_path, json.dumps(proposed, indent=2) + "\n")
    _write(relay / "prompts" / "implement.md", prompts.IMPLEMENT)
    _write(relay / "prompts" / "review.md", prompts.REVIEW)
    codex = " ".join(config.DEFAULTS["agents"]["codex"])
    claude = " ".join(config.DEFAULTS["agents"]["claude"])
    _write(
        relay / "config.toml",
        "# whyline-relay configuration. Every key is optional.\n"
        f'plan = "{config.DEFAULTS["plan"]}"\n'
        f"max_rounds = {config.DEFAULTS['max_rounds']}\n"
        f"timeout_minutes = {config.DEFAULTS['timeout_minutes']}\n"
        f'branch_prefix = "{config.DEFAULTS["branch_prefix"]}"\n\n'
        "[agents.codex]\n"
        f"command = {json.dumps(codex.split())}\n\n"
        "[agents.claude]\n"
        f"command = {json.dumps(claude.split())}\n",
    )
    _write(relay / ".gitignore", "logs/\nstate.json\nSTOP\n")

    print(f"Wrote {settings_path} and {relay}.")
    print(
        "\nClaude reads these permissions through `--settings`, not through "
        ".claude/settings.json, which Claude ignores in a workspace nobody has "
        "trusted interactively. The relay puts `whyline sync` output into every "
        "prompt itself, so Codex hooks are not needed for relay runs. Commit these "
        "files before `whyline-relay start`, which refuses a dirty working tree."
    )
    print(
        "\nThe allowlist is a convenience, not a sandbox: `uv run`, `npm` and `npx` "
        "execute arbitrary project code. Run unattended relays on an isolated "
        "branch or repository that holds no secrets."
    )
    return 0
```

- [ ] **Step 4: Wire `init` into `cli.py`**

Add the subparser and dispatch:

```python
    init_parser = subparsers.add_parser("init", help="Write permissions and templates")
    init_parser.add_argument("--repo", default=".")
    init_parser.add_argument("--yes", action="store_true")
```

```python
def cmd_init(args: argparse.Namespace) -> int:
    return init.run(Path(args.repo).resolve(), assume_yes=args.yes)
```

Import `init` and dispatch `"init"` in `main`.

- [ ] **Step 5: Write the README**

Replace `README.md` with: what the tool does in two sentences; the install line; the five commands; the plan file format; a worked example; the permission model including the explicit statement that no bypass flag is ever used; and a link to the spec. List the requirements (Python 3.11+, `whyline` installed and `whyline init` run in the repository, `codex` and `claude` installed and logged in, with the tested versions). Make the worked example run `whyline init --yes`, then `whyline-relay init`, then `git add -A` and commit, because `start` refuses a dirty tree and needs whyline initialised. State that Codex implements and never commits, Claude reviews and commits, the relay makes one mechanical commit of only the plan file when it ticks a box, and the human pushes. State that Codex's sandbox does not stop it committing, so the relay pauses if HEAD moves. State that the permissions live in `.whyline/relay/claude-settings.json` (edit it to add the project's test command, so the reviewer can run tests) and are passed with `--settings`. State that `init`'s files must be committed before `start`, which refuses a dirty working tree, and that Codex hooks are optional because the relay embeds `whyline sync` in every prompt. State plainly that the permission allowlist is an operational convenience, not a security boundary: broad entries such as `uv run`, `npm` and `npx` execute arbitrary project code, so unattended runs belong on an isolated branch or repository that holds no valuable secrets.

- [ ] **Step 6: Run the suite**

Run: `cd /Users/anish/whyline-relay && uv run pytest -v`
Expected: all pass.

- [ ] **Step 7: Hand off (Codex), then commit (Claude)**

**Codex:** do not stage or commit. Hand off, then stop:

```bash
whyline handoff RELAY-12 --from codex --to claude --status ready-for-review \
  --summary "<what you changed>" --file <each file you touched> \
  --test "uv run pytest -v: <result>" --risk "<anything the reviewer should check>"
```

**Claude:** only after the review approves, commit, then record the approval:

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: init writes permissions, templates, and config (M4) (RELAY-12)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
whyline handoff RELAY-12 --from claude --to claude --status approved --summary "<what you approved>"
```

---

### Task 13: Release readiness

**Files:**
- Create: `/Users/anish/whyline-relay/LICENSE`
- Create: `/Users/anish/whyline-relay/tests/test_no_bypass.py`
- Modify: `/Users/anish/whyline-relay/README.md`

**Interfaces:**
- Consumes: the whole package.
- Produces: no new public interface.

**Revised after pre-review (RELAY-13).** The first push guard asserted `"git push"` appears in no source file, which contradicts Task 12's `DENY = ["Bash(git push:*)", ...]`. It failed on Task 12's code, and this task's instruction ("remove the offending line; do not relax the test") would have had Codex delete the push deny rule, inverting the safety intent. The guard now exempts permission-declaration lines (`Bash(`) and instead forbids `git push` and a bare `"push"` argument everywhere else; it was checked to fail on injected `["git", "push"]` and `os.system("git push")` calls.

- [ ] **Step 1: Write the guard test**

`tests/test_no_bypass.py`:

```python
from pathlib import Path

FORBIDDEN = (
    "--dangerously-skip-permissions",
    "--dangerously-bypass-approvals-and-sandbox",
    "--dangerously-bypass-hook-trust",
    "danger-full-access",
)

SOURCE = Path(__file__).parent.parent / "src" / "whyline_relay"


def test_no_source_file_mentions_a_bypass_flag():
    """The promise in the README, enforced by the suite rather than by memory."""
    for path in SOURCE.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        for flag in FORBIDDEN:
            assert flag not in content, f"{path.name} mentions {flag}"


def test_no_source_file_runs_git_push():
    """The deny list names the ban ("Bash(git push:*)"); nothing else may mention it."""
    for path in SOURCE.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "Bash(" in line:
                continue
            assert "git push" not in line, f"{path.name}:{number}"
            assert '"push"' not in line and "'push'" not in line, f"{path.name}:{number}"
```

- [ ] **Step 2: Run it**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_no_bypass.py -v`
Expected: 2 passed. If either fails, the offending line is a bug — remove it; do not relax the test.

- [ ] **Step 3: Add the LICENSE**

Copy the Apache-2.0 text from `/Users/anish/agentdock/LICENSE`, updating nothing but the year if it is stale.

- [ ] **Step 4: Verify the package builds and the entry point works**

```bash
cd /Users/anish/whyline-relay
uv build
uv run whyline-relay status --repo .
```
Expected: a wheel and sdist in `dist/`, and `No relay run in progress.` from the status command.

If `uv build` fails inside Codex's sandbox because it cannot download the build backend (no network), say so in the handoff and skip it: Claude runs the build outside the sandbox during review.

- [ ] **Step 5: Run the whole suite one final time**

Run: `cd /Users/anish/whyline-relay && uv run pytest -v`
Expected: every test passes. Record the exact count in the commit message.

- [ ] **Step 6: Hand off (Codex), then commit (Claude)**

**Codex:** do not stage or commit. Hand off, then stop:

```bash
whyline handoff RELAY-13 --from codex --to claude --status ready-for-review \
  --summary "<what you changed>" --file <each file you touched> \
  --test "uv run pytest -v: <result>" --risk "<anything the reviewer should check>"
```

**Claude:** only after the review approves, commit, then record the approval:

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "chore: license, bypass guard test, and release readiness (RELAY-13)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
whyline handoff RELAY-13 --from claude --to claude --status approved --summary "<what you approved>"
```

- [ ] **Step 7: Record the decisions** (Claude's step: it writes to `/Users/anish/agentdock`, outside Codex's sandbox, so Codex skips it)

In `/Users/anish/agentdock`, record what the implementation settled that the spec left open:

```bash
cd /Users/anish/agentdock
whyline note "<one-line decision>" --because "<why>" --rejected "<option>: <why not>" \
  --actor claude --role reviewer --task WL-RELAY-0.1.0
```

Record at minimum: anything where the vendor CLIs behaved differently from the spec's assumptions during the M2 checkpoint, and any place the implementation had to deviate from this plan.
