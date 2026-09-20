# whyline-relay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

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
- **Default agent commands** (verified against `codex-cli 0.155.1` and `claude 2.1.277`; the prompt is always appended as the final argument):
  - Codex: `["codex", "exec", "-s", "workspace-write", "--color", "never"]`
  - Claude: `["claude", "-p", "--permission-mode", "acceptEdits", "--output-format", "json"]`
- **Default status strings:** `ready-for-review`, `changes-requested`, `approved`, `blocked`, `assigned`.
- **Milestone gate:** after Task 8 (M2), STOP and hand back to the owner for a watched real-CLI run before starting Task 9. This gate is in the spec (§11) and is not optional.

**Deviation from the spec's module table (§4), deliberate:** this plan splits four
modules out of what the spec drew as `loop.py` and `cli.py` — `routing.py` (the
routing table as a pure function, so every decision is testable without a
subprocess), `state.py` (the resume record), `whylinecmd.py` (the two whyline
commands the relay issues), and `init.py` (the permission writer). Same
responsibilities, smaller files. Nothing else in the spec changes.

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

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/agents.py`
- Test: `/Users/anish/whyline-relay/tests/test_agents.py`
- Create: `/Users/anish/whyline-relay/tests/fake_agent.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `agents.AgentMissing`; `agents.AgentTimeout`; `agents.build_argv(command: list[str], prompt: str) -> list[str]`; `agents.run(command: list[str], prompt: str, *, cwd: Path, log_path: Path, timeout_seconds: int, which=None, echo=True) -> int`; `agents.RATE_LIMIT_MARKERS: tuple[str, ...]`; `agents.rate_limited(text: str) -> bool`.

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
        bufsize=1,
        start_new_session=True,
    )

    def kill_group() -> None:
        timed_out.set()
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

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
Expected: 7 passed. The timeout test takes about a second.

- [ ] **Step 6: Commit**

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: launch an agent, tee its output, enforce a timeout"
```

---

### Task 6: Git guards and commit verification

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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_gitcheck.py -v`
Expected: FAIL — no module named `whyline_relay.gitcheck`.

- [ ] **Step 3: Write `src/whyline_relay/gitcheck.py`**

```python
"""Git guards. Git is the authority; the relay only asks it questions."""

from __future__ import annotations

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


def commit_verified(root: Path, base_commit: str, task_id: str) -> bool:
    """True when HEAD moved past `base_commit` and names `task_id` in its message.

    A ticked checkbox must always mean a real commit exists for that task, so
    both halves are required and neither is inferred from the agent's word.
    """
    head = head_commit(root)
    if head == base_commit:
        return False
    return task_id in commit_message(root, head)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_gitcheck.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: git guards and commit verification"
```

---

### Task 7: Routing decision and dry run — milestone M1

The routing table from the spec, as a pure function, plus a CLI that can print what it would do without launching anything.

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


def decide(
    record: handoff.Handoff | None,
    previous_id: str | None,
    status_map: dict[str, str],
) -> str:
    """Pick the next move from the handoff record alone.

    A missing record, or one whose event id has not changed since the agent
    started, means the agent exited without handing off. That is never inferred
    to be success: the caller pauses.
    """
    if record is None or (previous_id is not None and record.event_id == previous_id):
        return NO_HANDOFF
    status = record.status
    if status == status_map["approved"]:
        return APPROVED
    if status == status_map["blocked"]:
        return BLOCKED
    if status == status_map["review"]:
        return REVIEW
    if status in (status_map["changes"], status_map["assigned"]):
        return IMPLEMENT
    return UNKNOWN
```

- [ ] **Step 4: Run the routing tests to verify they pass**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_routing.py -v`
Expected: 9 passed.

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
Expected: all tests pass (about 51).

- [ ] **Step 9: Commit**

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: routing table and dry run (M1)"
```

---

### Task 8: One task end to end — milestone M2

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/loop.py`
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/cli.py` (wire `start` to `loop.run_task`)
- Test: `/Users/anish/whyline-relay/tests/test_loop_single.py`

**Interfaces:**
- Consumes: `routing.decide`, `agents.run`, `handoff.read`, `prompts.render`, `whylinecmd.sync`, `whylinecmd.claim`, `gitcheck.commit_verified`, `config.Config`, `plan.Task`.
- Produces: `loop.Paused` exception with attribute `reason: str`; `loop.Outcome` frozen dataclass with fields `task_id: str`, `rounds: int`, `committed: bool`; `loop.run_task(root: Path, settings: config.Config, task: plan.Task, *, base_commit: str, echo: bool = True) -> Outcome`.

`run_task` raises `Paused` for every stop condition. The caller decides what a pause means.

- [ ] **Step 1: Write the failing test**

`tests/test_loop_single.py`:

```python
import subprocess
import sys
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_loop_single.py -v`
Expected: FAIL — no module named `whyline_relay.loop`.

- [ ] **Step 3: Write `src/whyline_relay/loop.py`**

```python
"""The state machine. The only module in the relay that decides anything."""

from __future__ import annotations

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


def _pause_if_rate_limited(target: Path) -> None:
    try:
        output = target.read_text(encoding="utf-8")
    except OSError:
        return
    if agents.rate_limited(output):
        raise Paused(
            "the agent reported a usage or rate limit; try again when it resets",
            target,
        )


def run_task(
    root: Path,
    settings: config.Config,
    task: plan.Task,
    *,
    base_commit: str,
    echo: bool = True,
) -> Outcome:
    """Drive one task from implement to an approved, verified commit.

    Raises Paused for every stop condition. Never infers a verdict from an
    agent's exit code or output — only from the handoff record it wrote.
    """
    round_ = 1
    feedback = ""
    whylinecmd.claim(root, task.task_id, "codex", "implementer")
    next_move = routing.IMPLEMENT

    while True:
        agent = "codex" if next_move == routing.IMPLEMENT else "claude"
        template = "implement" if agent == "codex" else "review"
        previous = handoff.read(root)
        previous_id = previous.event_id if previous else None

        target = _run_agent(
            root, settings, agent, template, task, round_, feedback, echo
        )
        _pause_if_rate_limited(target)

        record = handoff.read(root)
        move = routing.decide(record, previous_id, settings.status_map)

        if move == routing.NO_HANDOFF:
            raise Paused(
                f"{agent} exited without handing off; nothing was routed", target
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
            if not gitcheck.commit_verified(root, base_commit, task.task_id):
                raise Paused(
                    f"{task.task_id} was approved but no commit naming it exists; "
                    "the checkbox was not ticked",
                    target,
                )
            return Outcome(task_id=task.task_id, rounds=round_, committed=True)
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

- [ ] **Step 4: Run the loop tests to verify they pass**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_loop_single.py -v`
Expected: 7 passed.

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

- [ ] **Step 7: Commit**

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: run one task from implement to verified commit (M2)"
```

- [ ] **Step 8: STOP — owner checkpoint**

Do not start Task 9. Report to the owner that M2 is ready for a watched run against the real `codex` and `claude` CLIs on a throwaway repository with a one-task plan. The vendor assumptions in Global Constraints are unproven until that run happens, and Tasks 9–12 build on them.

---

### Task 9: Multi-task runs and resumable state — milestone M3, part 1

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/state.py`
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/loop.py` (add `run_plan`)
- Test: `/Users/anish/whyline-relay/tests/test_state.py`
- Test: `/Users/anish/whyline-relay/tests/test_loop_plan.py`

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: `state.RelayState` frozen dataclass with fields `plan: str`, `branch: str`, `task_id: str`, `round: int`, `base_commit: str`, `paused_reason: str`, `log_path: str`; `state.save(root: Path, value: RelayState) -> None`; `state.load(root: Path) -> RelayState | None`; `state.clear(root: Path) -> None`; `loop.run_plan(root: Path, settings: config.Config, plan_path: Path, *, branch: str, only: str | None = None, echo: bool = True) -> list[Outcome]`.

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
    git("add", "-A")
    git("commit", "-m", "initial")
    (tmp_path / ".whyline").mkdir()
    (tmp_path / "plan.md").write_text("- [ ] WL-1: One\n- [ ] WL-2: Two\n")
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
```

- [ ] **Step 5: Run it to verify it fails**

Run: `cd /Users/anish/whyline-relay && uv run pytest tests/test_loop_plan.py -v`
Expected: FAIL — `AttributeError: module 'whyline_relay.loop' has no attribute 'run_plan'`.

- [ ] **Step 6: Add `run_plan` and the stop file to `loop.py`**

Add `from whyline_relay import state` to the imports, then append:

```python
def stop_path(root: Path) -> Path:
    return config.relay_dir(root) / "STOP"


def stop_requested(root: Path) -> bool:
    return stop_path(root).exists()


def run_plan(
    root: Path,
    settings: config.Config,
    plan_path: Path,
    *,
    branch: str,
    only: str | None = None,
    echo: bool = True,
) -> list[Outcome]:
    """Run every unchecked task in file order. Tick each only after it commits."""
    outcomes: list[Outcome] = []
    while True:
        if stop_requested(root):
            print("STOP file present; not starting another task.")
            return outcomes
        content = plan_path.read_text(encoding="utf-8")
        tasks = plan.parse(content)
        task = plan.find(tasks, only) if only else plan.next_unchecked(tasks)
        if task is None or task.checked:
            state.clear(root)
            return outcomes

        base_commit = gitcheck.head_commit(root)
        try:
            outcome = run_task(root, settings, task, base_commit=base_commit, echo=echo)
        except Paused as paused:
            state.save(
                root,
                state.RelayState(
                    plan=str(plan_path),
                    branch=branch,
                    task_id=task.task_id,
                    round=0,
                    base_commit=base_commit,
                    paused_reason=paused.reason,
                    log_path=str(paused.log_path or ""),
                ),
            )
            raise

        plan_path.write_text(plan.tick(content, task.task_id), encoding="utf-8")
        outcomes.append(outcome)
        if only:
            state.clear(root)
            return outcomes
```

- [ ] **Step 7: Run the suite**

Run: `cd /Users/anish/whyline-relay && uv run pytest -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: multi-task runs, stop file, and resumable state"
```

---

### Task 10: Guards, resume, status, stop — milestone M3, part 2

**Files:**
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/cli.py`
- Test: `/Users/anish/whyline-relay/tests/test_cli_commands.py`

**Interfaces:**
- Consumes: `state.RelayState`, `loop.run_plan`, `gitcheck`, `config.Config`.
- Produces: `cli.cmd_resume`, `cli.cmd_status`, `cli.cmd_stop`, `cli.guard(root, args, settings) -> str | None` returning a refusal message or `None`.

- [ ] **Step 1: Write the failing test**

`tests/test_cli_commands.py`:

```python
import subprocess
from pathlib import Path

import pytest

from whyline_relay import cli, state


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


def test_refuses_to_start_on_main(repo: Path, capsys):
    code = cli.main(["start", "--repo", str(repo), "--allow-dirty"])
    assert code == cli.EXIT_ERROR
    assert "main" in capsys.readouterr().err


def test_allow_main_lifts_the_branch_refusal(repo: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli.loop, "run_plan", lambda *a, **k: [])
    code = cli.main(["start", "--repo", str(repo), "--allow-main", "--allow-dirty"])
    assert code == cli.EXIT_OK


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

    status = subparsers.add_parser("status", help="Where the relay is")
    status.add_argument("--repo", default=".")

    stop = subparsers.add_parser("stop", help="Stop after the current agent finishes")
    stop.add_argument("--repo", default=".")
```

Add the guard and the three commands:

```python
def guard(root: Path, args: argparse.Namespace) -> str | None:
    """Return a refusal message, or None when it is safe to start."""
    branch = gitcheck.current_branch(root)
    if branch in ("main", "master") and not getattr(args, "allow_main", False):
        return (
            f"refusing to run on {branch}. Pass --branch NAME to use another branch, "
            "or --allow-main if you really mean it."
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
        loop.run_plan(root, settings, Path(saved.plan), branch=saved.branch)
    except loop.Paused as paused:
        return _report_pause(paused)
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

    refusal = guard(root, args)
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return EXIT_ERROR

    branch = args.branch or f"{settings.branch_prefix}{plan_path.stem}"
    try:
        gitcheck.ensure_branch(root, branch)
        outcomes = loop.run_plan(
            root, settings, plan_path, branch=branch, only=args.only
        )
    except loop.Paused as paused:
        return _report_pause(paused)
    except (gitcheck.GitError, whylinecmd.WhylineUnavailable) as error:
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

- [ ] **Step 5: Commit**

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: branch and dirty guards, resume, status, stop"
```

---

### Task 11: Ctrl+C and notifications

**Files:**
- Create: `/Users/anish/whyline-relay/src/whyline_relay/notify.py`
- Modify: `/Users/anish/whyline-relay/src/whyline_relay/cli.py`
- Test: `/Users/anish/whyline-relay/tests/test_notify.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `notify.command(title: str, message: str, platform: str) -> list[str] | None`; `notify.send(title: str, message: str, runner=None, platform: str | None = None) -> None`.

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

- [ ] **Step 5: Run the suite**

Run: `cd /Users/anish/whyline-relay && uv run pytest -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: interrupt handling and desktop notifications"
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
- Produces: `init.BASE_ALLOW: list[str]`; `init.DENY: list[str]`; `init.PRESETS: dict[str, list[str]]`; `init.detect_stack(root: Path) -> str`; `init.allowlist(stack: str) -> dict`; `init.merge_settings(existing: dict, proposed: dict) -> dict`; `init.codex_hook_trusted(root: Path) -> bool`; `init.run(root: Path, *, assume_yes: bool, confirm=input) -> int`.

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


def test_merge_keeps_existing_entries_and_adds_ours():
    existing = {"permissions": {"allow": ["Bash(make:*)"], "deny": []}, "model": "opus"}
    merged = init.merge_settings(existing, init.allowlist("python"))
    assert "Bash(make:*)" in merged["permissions"]["allow"]
    assert "Bash(whyline:*)" in merged["permissions"]["allow"]
    assert merged["model"] == "opus"


def test_merge_does_not_duplicate_entries():
    proposed = init.allowlist("python")
    merged = init.merge_settings(proposed, proposed)
    allowed = merged["permissions"]["allow"]
    assert len(allowed) == len(set(allowed))


def test_run_writes_settings_templates_and_config(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    assert init.run(tmp_path, assume_yes=True) == 0
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "Bash(whyline:*)" in settings["permissions"]["allow"]
    assert (tmp_path / ".whyline" / "relay" / "prompts" / "implement.md").exists()
    assert (tmp_path / ".whyline" / "relay" / "prompts" / "review.md").exists()
    assert (tmp_path / ".whyline" / "relay" / "config.toml").exists()


def test_declining_writes_nothing(tmp_path: Path):
    assert init.run(tmp_path, assume_yes=False, confirm=lambda prompt: "n") != 0
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".whyline" / "relay").exists()


def test_reports_untrusted_codex_hooks(tmp_path: Path, capsys):
    (tmp_path / ".whyline").mkdir()
    init.run(tmp_path, assume_yes=True)
    out = capsys.readouterr().out
    assert "codex" in out.lower()
    assert "dangerously" not in out
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


def merge_settings(existing: dict, proposed: dict) -> dict:
    """Add our entries to whatever is already there. We never remove a user's."""
    merged = json.loads(json.dumps(existing))
    permissions = merged.setdefault("permissions", {})
    for key in ("allow", "deny"):
        current = list(permissions.get(key, []))
        for entry in proposed["permissions"][key]:
            if entry not in current:
                current.append(entry)
        permissions[key] = current
    return merged


def codex_hook_trusted(root: Path) -> bool:
    """Whether whyline's Codex hooks have persisted trust in this checkout.

    Codex establishes hook trust only for events after the prompt is answered
    (whyline 0.2.2 documents this timing trap), so a repository only ever driven
    by `codex exec` never earns it. We report; we never pass a bypass flag.
    """
    return (root / ".codex" / "trust.json").exists()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run(root: Path, *, assume_yes: bool, confirm=input) -> int:
    stack = detect_stack(root)
    proposed = allowlist(stack)
    settings_path = root / ".claude" / "settings.json"
    try:
        existing = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = {}
    merged = merge_settings(existing, proposed)

    print(f"Detected stack: {stack}")
    print(f"Proposed {settings_path}:")
    print(json.dumps(merged, indent=2))
    print("Also writing prompt templates and config under .whyline/relay/.")
    if not assume_yes:
        answer = confirm("Write these? [Y/n] ").strip().lower()
        if answer and not answer.startswith("y"):
            print("Nothing written.")
            return 1

    _write(settings_path, json.dumps(merged, indent=2) + "\n")
    relay = config.relay_dir(root)
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
    if not codex_hook_trusted(root):
        print(
            "\nCodex hook trust is not established in this checkout. Run `codex` "
            "here once interactively and accept the hook prompt, or whyline's "
            "Codex hooks will not fire under `codex exec`."
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

Replace `README.md` with: what the tool does in two sentences; the install line; the five commands; the plan file format; a worked example; the permission model including the explicit statement that no bypass flag is ever used; and a link to the spec. State that Codex implements and never commits, Claude reviews and commits, and the human pushes.

- [ ] **Step 6: Run the suite**

Run: `cd /Users/anish/whyline-relay && uv run pytest -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "feat: init writes permissions, templates, and config (M4)"
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
    for path in SOURCE.rglob("*.py"):
        assert "git push" not in path.read_text(encoding="utf-8"), path.name
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

- [ ] **Step 5: Run the whole suite one final time**

Run: `cd /Users/anish/whyline-relay && uv run pytest -v`
Expected: every test passes. Record the exact count in the commit message.

- [ ] **Step 6: Commit**

```bash
cd /Users/anish/whyline-relay
git add -A
git commit -m "chore: license, bypass guard test, and release readiness"
```

- [ ] **Step 7: Record the decisions**

In `/Users/anish/agentdock`, record what the implementation settled that the spec left open:

```bash
cd /Users/anish/agentdock
whyline note "<one-line decision>" --because "<why>" --rejected "<option>: <why not>" \
  --actor claude --role implementer --task WL-RELAY-0.1.0
```

Record at minimum: anything where the vendor CLIs behaved differently from the spec's assumptions during the M2 checkpoint, and any place the implementation had to deviate from this plan.
