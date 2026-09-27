# Relay Setup Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `whyline-relay setup` walks you from "I have (or want) a plan" to "it's safely running unattended" — using or drafting a plan, assigning implementer/tester/reviewer, auto-committing that setup, then refusing to offer `start` until `doctor`'s own existing correctness checks pass.

**Architecture:** A new module, `setup.py`, built from three small, independently-testable pieces (plan existing-or-draft, the role wizard's file writes, and the orchestrating gate-then-start flow), reusing `planner.start`, `gitcheck.commit_all`, and `preflight.run`/`print_checks`/`failures` completely unchanged. Wired into `cli.py` as a new `setup` subcommand, mirroring exactly how `chat` was added.

**Tech Stack:** Python 3.11+, stdlib only (`os`, `shutil`, `subprocess`, `sys`). No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-27-whyline-menu-relay-setup-design.md`, decisions M3 through M8.

## Global Constraints

- No new runtime dependency.
- `doctor`'s own checks (`preflight.run`/`print_checks`/`failures`) are reused completely unchanged — no new validation engine.
- The wizard auto-commits its own generated files (`config.toml`, `prompts/test.md`) before ever running `doctor` or asking to start — a plan already mid-flight elsewhere in this session hit exactly the "working tree has uncommitted changes" wall this must never cause.
- `which`/`exec_fn`/`runner` must be resolved at call time, not bound as default arguments.
- Every existing test must still pass after every task.

---

### Task 1: `setup.py` — plan source and the role wizard

**Files:**
- Create: `src/whyline_relay/setup.py`
- Test: `tests/test_setup.py`

**Interfaces:**
- Produces: `setup.choose_plan_source(root, settings, *, input_fn=None, print_fn=None, planner_start=None) -> bool` (`True` once a usable plan file exists; `False` if drafting was refused or nothing exists to proceed with). `setup.run_role_wizard(root, *, input_fn=None, print_fn=None) -> dict[str, str]` (`{"implementer": ..., "tester": ..., "reviewer": ...}`; also writes `.whyline/relay/config.toml` and `.whyline/relay/prompts/test.md`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_setup.py`:

```python
from pathlib import Path

from whyline_relay import config, setup


def test_choose_plan_source_existing_default_when_plan_exists(tmp_path: Path):
    (tmp_path / "plan.md").write_text("- [ ] TASK-1: x\n")
    settings = config.load(tmp_path)
    answers = iter([""])  # accept the bracketed default: existing
    result = setup.choose_plan_source(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    assert result is True


def test_choose_plan_source_refuses_when_no_plan_and_existing_chosen(tmp_path: Path):
    settings = config.load(tmp_path)
    answers = iter(["existing"])
    printed = []
    result = setup.choose_plan_source(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
    )
    assert result is False
    assert any("does not exist" in line for line in printed)


def test_choose_plan_source_draft_calls_planner_start(tmp_path: Path):
    settings = config.load(tmp_path)
    calls = []

    def fake_planner_start(root, settings_arg, description):
        calls.append((root, description))
        (root / settings_arg.plan).write_text("- [ ] TASK-1: drafted\n")
        return "drafted!"

    answers = iter(["draft", "build a widget"])
    result = setup.choose_plan_source(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
        planner_start=fake_planner_start,
    )
    assert result is True
    assert calls == [(tmp_path, "build a widget")]


def test_choose_plan_source_draft_with_no_description_does_nothing(tmp_path: Path):
    settings = config.load(tmp_path)
    calls = []
    answers = iter(["draft", ""])
    result = setup.choose_plan_source(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
        planner_start=lambda root, s, d: calls.append(d),
    )
    assert result is False
    assert calls == []


def test_choose_plan_source_draft_handles_a_plan_already_in_progress(tmp_path: Path):
    from whyline_relay import planner

    settings = config.load(tmp_path)

    def fake_planner_start(root, settings_arg, description):
        raise planner.PlanAlreadyInProgress("a plan draft is already in progress")

    answers = iter(["draft", "build a widget"])
    printed = []
    result = setup.choose_plan_source(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        planner_start=fake_planner_start,
    )
    assert result is False
    assert any("already in progress" in line for line in printed)


def test_run_role_wizard_writes_config_and_test_prompt(tmp_path: Path):
    answers = iter(["grok", "codex", ""])
    result = setup.run_role_wizard(
        tmp_path,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    assert result == {"implementer": "grok", "tester": "codex", "reviewer": "claude"}
    config_text = (tmp_path / ".whyline" / "relay" / "config.toml").read_text()
    assert 'implementer = "grok"' in config_text
    assert 'tester      = "codex"' in config_text
    assert 'reviewer    = "claude"' in config_text
    assert "[pipeline.stages.test]" in config_text
    assert 'default_profile = "full"' in config_text
    test_prompt = (tmp_path / ".whyline" / "relay" / "prompts" / "test.md").read_text()
    assert "You are the tester for this task" in test_prompt
    assert "{actor}" in test_prompt
    assert "{tester}" not in test_prompt  # no such placeholder exists in render()


def test_run_role_wizard_config_parses_as_a_valid_pipeline(tmp_path: Path):
    # The wizard's own output must be immediately usable by config.load --
    # not just plausible-looking TOML. Uses only built-in agents so this
    # exercises the happy path; an unconfigured name is Task 2's concern
    # (doctor correctly reports it as a FAIL rather than crashing).
    answers = iter(["codex", "claude", "claude"])
    setup.run_role_wizard(
        tmp_path,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    loaded = config.load(tmp_path)
    assert loaded.pipeline is not None
    assert set(loaded.pipeline.stages) == {"draft", "test", "review"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -v`
Expected: FAIL — `whyline_relay.setup` does not exist.

- [ ] **Step 3: Implement**

Create `src/whyline_relay/setup.py`:

```python
"""The `whyline-relay setup` wizard: plan source, roles, then a doctor gate."""

from __future__ import annotations

from pathlib import Path

from whyline_relay import config, planner

TEST_PROMPT_TEMPLATE = """{sync_packet}

You are the tester for this task. Round {round}.

## Task {task_id}

{task_text}

## How to test

Run the project's own test suite in full, plus anything this task's own
instructions call for. Judge only whether the implementation behaves
correctly -- not whether the diff is well-written; that is the reviewer's
job next.

Record your ruling -- testing is deciding:

    whyline note "<one-line ruling>" --because "<why>" \\
      --file <path> --actor {actor} --role tester --task {task_id}

## How to finish

Exactly one of these outcomes.

Passed: hand off to the reviewer.

    whyline handoff {task_id} --from {actor} --to {reviewer} --status passed \\
      --summary "<what you verified>" --test "<command>: <result>"

Failed: hand back to the implementer with concrete, actionable detail.

    whyline handoff {task_id} --from {actor} --to {implementer} --status failed \\
      --summary "<what failed>" --test "<command>: <result>"

Do not commit either way -- the reviewer commits once this task is fully
approved.
"""

PIPELINE_CONFIG_TEMPLATE = """[roles]
implementer = "{implementer}"
tester      = "{tester}"
reviewer    = "{reviewer}"

[pipeline]
default_profile = "full"

[pipeline.profiles]
full = ["draft", "test", "review"]

[pipeline.stages.draft]
role   = "implementer"
prompt = "implement"
[pipeline.stages.draft.on]
ready = "@next"

[pipeline.stages.test]
role       = "tester"
prompt     = "test"
max_visits = 5
[pipeline.stages.test.on]
passed = "@next"
failed = "draft"

[pipeline.stages.review]
role   = "reviewer"
prompt = "review"
[pipeline.stages.review.on]
approved = "@complete"
rejected = "draft"
"""


def choose_plan_source(
    root: Path,
    settings: "config.Config",
    *,
    input_fn=None,
    print_fn=None,
    planner_start=None,
) -> bool:
    """Ask "use existing or draft a new plan?" and act on it. Returns True
    once a plan file exists and setup should continue; False otherwise."""
    input_fn = input_fn if input_fn is not None else input
    print_fn = print_fn if print_fn is not None else print
    planner_start = planner_start if planner_start is not None else planner.start

    plan_path = root / settings.plan
    default_choice = "existing" if plan_path.exists() else "draft"
    choice = (
        input_fn(
            f"Use the existing {settings.plan}, or draft a new one? "
            f"[{default_choice}]: "
        ).strip().lower()
        or default_choice
    )

    if choice == "draft":
        description = input_fn("What should this plan build? ").strip()
        if not description:
            print_fn("No description given -- nothing drafted.")
            return plan_path.exists()
        try:
            summary = planner_start(root, settings, description)
        except planner.PlanAlreadyInProgress as error:
            print_fn(str(error))
            return plan_path.exists()
        print_fn(summary)
        return plan_path.exists()

    if not plan_path.exists():
        print_fn(
            f"{settings.plan} does not exist -- write one by hand, or run "
            f"`whyline-relay plan \"...\"` to draft one, then run "
            f"`whyline-relay setup` again."
        )
        return False
    return True


def run_role_wizard(root: Path, *, input_fn=None, print_fn=None) -> dict[str, str]:
    """Asks implementer/tester/reviewer, writes config.toml and
    prompts/test.md. Returns the three chosen agent names."""
    input_fn = input_fn if input_fn is not None else input
    print_fn = print_fn if print_fn is not None else print

    implementer = input_fn("Who implements? [codex]: ").strip() or "codex"
    tester = input_fn("Who tests?      [claude]: ").strip() or "claude"
    reviewer = input_fn("Who reviews?    [claude]: ").strip() or "claude"

    relay = config.relay_dir(root)
    config_path = relay / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        PIPELINE_CONFIG_TEMPLATE.format(
            implementer=implementer, tester=tester, reviewer=reviewer
        ),
        encoding="utf-8",
    )
    print_fn(f"Wrote {config_path.relative_to(root)}.")

    test_prompt_path = relay / "prompts" / "test.md"
    test_prompt_path.parent.mkdir(parents=True, exist_ok=True)
    test_prompt_path.write_text(TEST_PROMPT_TEMPLATE, encoding="utf-8")
    print_fn(f"Wrote {test_prompt_path.relative_to(root)}.")

    return {"implementer": implementer, "tester": tester, "reviewer": reviewer}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/setup.py tests/test_setup.py
git commit -m "feat: setup wizard -- plan source and the implementer/tester/reviewer roles"
```

---

### Task 2: `setup.py` — auto-commit, the doctor gate, and the start confirmation

**Files:**
- Modify: `src/whyline_relay/setup.py`
- Test: `tests/test_setup.py`

**Interfaces:**
- Consumes: `choose_plan_source`, `run_role_wizard` (Task 1); `gitcheck.commit_all`, `preflight.run`/`print_checks`/`failures` (existing, unchanged).
- Produces: `setup.run(root, *, input_fn=None, print_fn=None, exec_fn=None, which=None, runner=None) -> int` — the whole `whyline-relay setup` flow, returning a process exit code.

- [ ] **Step 1: Write the failing tests**

First, read `src/whyline_relay/preflight.py`'s `Check` dataclass (`status: Literal["ok", "warn", "FAIL"]`, `message: str`, `hint: str | None = None`) so the fakes below match its real shape exactly.

Add to `tests/test_setup.py`:

```python
import subprocess

from whyline_relay import preflight


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    (root / "README.md").write_text("hi\n")
    (root / "plan.md").write_text("- [ ] TASK-1: x\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)


def test_run_commits_setup_before_running_doctor(tmp_path: Path, monkeypatch):
    _init_repo(tmp_path)
    answers = iter(["existing", "codex", "claude", "claude", "n"])
    seen_dirty_at_doctor_time = []

    def fake_runner(*a, **k):
        # doctor's own login-status checks call this; report "logged in"
        return subprocess.CompletedProcess(a, 0, "", "")

    def fake_preflight_run(root, *a, **k):
        from whyline_relay import gitcheck
        seen_dirty_at_doctor_time.append(gitcheck.is_dirty(root))
        return [preflight.Check("ok", "all good")]

    monkeypatch.setattr(setup.preflight, "run", fake_preflight_run)
    code = setup.run(
        tmp_path,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
        exec_fn=lambda binary, argv: (_ for _ in ()).throw(
            AssertionError("should not start -- test answers 'n'")
        ),
        which=lambda name: "/bin/x",
        runner=fake_runner,
    )
    assert seen_dirty_at_doctor_time == [False]
    assert code == 0


def test_run_refuses_to_offer_start_on_a_fail(tmp_path: Path, monkeypatch):
    _init_repo(tmp_path)
    answers = iter(["existing", "codex", "claude", "claude"])

    def fake_preflight_run(root, *a, **k):
        return [preflight.Check("FAIL", "grok is not on PATH", "install grok")]

    monkeypatch.setattr(setup.preflight, "run", fake_preflight_run)
    code = setup.run(
        tmp_path,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
        exec_fn=lambda binary, argv: (_ for _ in ()).throw(
            AssertionError("should never be offered on a FAIL")
        ),
        which=lambda name: "/bin/x",
    )
    assert code == 1


def test_run_asks_before_proceeding_on_a_warn_and_honors_no(tmp_path: Path, monkeypatch):
    _init_repo(tmp_path)
    answers = iter(["existing", "codex", "claude", "claude", "n"])

    def fake_preflight_run(root, *a, **k):
        return [preflight.Check("warn", "grok has no login check")]

    monkeypatch.setattr(setup.preflight, "run", fake_preflight_run)
    code = setup.run(
        tmp_path,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
        exec_fn=lambda binary, argv: (_ for _ in ()).throw(
            AssertionError("declined -- must not exec")
        ),
        which=lambda name: "/bin/x",
    )
    assert code == 0


def test_run_execs_into_start_when_clean_and_confirmed(tmp_path: Path, monkeypatch):
    _init_repo(tmp_path)
    answers = iter(["existing", "codex", "claude", "claude", ""])  # "" accepts [Y]

    def fake_preflight_run(root, *a, **k):
        return [preflight.Check("ok", "all good")]

    monkeypatch.setattr(setup.preflight, "run", fake_preflight_run)
    calls = []
    code = setup.run(
        tmp_path,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
        exec_fn=lambda binary, argv: calls.append((binary, argv)),
        which=lambda name: "/bin/x",
    )
    assert calls == [("whyline-relay", ["whyline-relay", "start"])]
    assert code == 0


def test_run_stops_early_when_no_plan_source_resolved(tmp_path: Path):
    answers = iter(["existing"])  # no plan.md exists, "existing" is refused
    code = setup.run(
        tmp_path,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
        exec_fn=lambda binary, argv: (_ for _ in ()).throw(
            AssertionError("must not reach the wizard with no plan")
        ),
        which=lambda name: "/bin/x",
    )
    assert code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -k "test_run_" -v`
Expected: FAIL — `setup.run` does not exist.

- [ ] **Step 3: Implement**

Add to `src/whyline_relay/setup.py`. First, extend the imports at the top:

```python
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from whyline_relay import config, gitcheck, planner, preflight
```

Then add, at the end of the file:

```python
def _which(name: str) -> str | None:
    return shutil.which(name)


def _exec(binary: str, argv: list[str]) -> None:
    os.execvp(binary, argv)


def run(
    root: Path,
    *,
    input_fn=None,
    print_fn=None,
    exec_fn=None,
    which=None,
    runner=None,
) -> int:
    """The whole `whyline-relay setup` flow: plan source, roles, an
    auto-committed setup, doctor's gate, then an offer to start."""
    input_fn = input_fn if input_fn is not None else input
    print_fn = print_fn if print_fn is not None else print
    exec_fn = exec_fn if exec_fn is not None else _exec
    which = which if which is not None else _which

    settings = config.load(root)
    if not choose_plan_source(root, settings, input_fn=input_fn, print_fn=print_fn):
        return 1

    run_role_wizard(root, input_fn=input_fn, print_fn=print_fn)

    if gitcheck.commit_all(root, "setup: assign implementer/tester/reviewer roles"):
        print_fn("Committed setup.")

    preflight_kwargs = {} if runner is None else {"runner": runner}
    checks = preflight.run(root, **preflight_kwargs)
    preflight.print_checks(checks, stream=sys.stdout, include_ok=True, summary=True)

    if preflight.failures(checks):
        print_fn("Fix the FAILs above before starting.")
        return 1

    has_warnings = any(check.status == "warn" for check in checks)
    if has_warnings:
        proceed = input_fn("Proceed anyway? [y/N]: ").strip().lower()
        if proceed != "y":
            return 0

    start_choice = input_fn("Ready to start? [Y/n]: ").strip().lower()
    if start_choice in ("", "y", "yes"):
        exec_fn("whyline-relay", ["whyline-relay", "start"])
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/setup.py tests/test_setup.py
git commit -m "feat: setup auto-commits, gates on doctor, then offers to start"
```

---

### Task 3: `cli.py` — wire the `setup` subcommand

**Files:**
- Modify: `src/whyline_relay/cli.py`
- Test: `tests/test_cli_setup.py`

**Interfaces:**
- Consumes: `setup.run` (Task 2).
- Produces: `whyline-relay setup [--repo PATH]` on the command line.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_setup.py`:

```python
import os
from pathlib import Path

from whyline_relay import cli


def test_setup_subcommand_is_registered():
    parser = cli.build_parser()
    args = parser.parse_args(["setup"])
    assert args.command == "setup"


def test_cmd_setup_calls_setup_run(tmp_path: Path, monkeypatch):
    from whyline_relay import setup

    calls = []
    monkeypatch.setattr(setup, "run", lambda root, **kwargs: calls.append(root) or 0)
    previous = os.getcwd()
    os.chdir(tmp_path)
    try:
        args = cli.build_parser().parse_args(["setup"])
        code = cli.cmd_setup(args)
    finally:
        os.chdir(previous)
    assert code == cli.EXIT_OK
    assert calls == [tmp_path.resolve()]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_setup.py -v`
Expected: FAIL — no `setup` subcommand, no `cmd_setup`.

- [ ] **Step 3: Implement**

In `src/whyline_relay/cli.py`, add `setup` to the module-level import from
`whyline_relay` (alongside `adapters, agents, chat, config, ...`):

```python
from whyline_relay import (
    adapters,
    agents,
    chat,
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
    setup,
    state,
    whylinecmd,
)
```

In `build_parser()`, right after the `chat_parser` block, add:

```python
    setup_parser = subparsers.add_parser(
        "setup", help="Assign roles to a plan and gate on doctor before starting"
    )
    setup_parser.add_argument(
        "--repo", default=".", help="Use this repository root (default: current directory)."
    )
```

Add a new command function, near `cmd_chat`:

```python
def cmd_setup(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    return setup.run(root)
```

Find `main()`'s dispatch dict (the one containing `"chat": cmd_chat`) and
add `"setup": cmd_setup` to it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_setup.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/cli.py tests/test_cli_setup.py
git commit -m "feat: whyline-relay setup -- the CLI entry point"
```

---

### Task 4: README — document the setup wizard

**Files:**
- Modify: `README.md`

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Update the README**

Add a new section, immediately after "## Configuring a custom pipeline":

````markdown
## `whyline-relay setup`: a guided path from plan to running

Hand-writing `[roles]`/`[pipeline]`/a stage's prompt file works, but
`whyline-relay setup` does the common case (implementer -> tester ->
reviewer) for you, and refuses to let you start until `doctor`'s own checks
pass:

```
$ whyline-relay setup
Use the existing plan.md, or draft a new one? [existing]: 
Who implements? [codex]: grok
Who tests?      [claude]: codex
Who reviews?    [claude]: 
Wrote .whyline/relay/config.toml.
Wrote .whyline/relay/prompts/test.md.
Committed setup.

  ok    directory is inside a git repository
  ok    whyline is installed and initialised
  ok    relay setup is complete
  ok    grok is on PATH
  ok    codex is on PATH
  ok    codex is logged in
  ok    plan parses and has unchecked tasks: plan.md
  ok    working tree is clean
All checks passed.

Ready to start? [Y/n]: 
```

If no plan file exists yet (or you choose "draft"), it calls the existing
`whyline-relay plan "..."` planner workflow first, then continues into the
role wizard once a plan exists. The wizard's own generated files are
committed automatically, before `doctor` ever runs -- so you never hit
"working tree has uncommitted changes" right after finishing it. A `FAIL`
from `doctor` refuses to offer `start` at all; a `warn`-only result asks
whether to proceed anyway. This is exactly `whyline-relay doctor`'s own
existing check list, run for you as part of the flow -- not a new or
different validation.
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document whyline-relay setup"
```

## Not in this plan

- **Automatic pipeline failover** — a separate plan, deferred (per the
  original sequencing: chat-failover, then pipeline-failover, then this
  wizard). The wizard's generated `config.toml` has no `[roles.backup]`
  (forbidden together with `[pipeline]` regardless).
- **A fully custom stage/transition builder** — explicit non-goal; the
  wizard offers exactly the fixed implementer/tester/reviewer template.
- **Whyline's own entry menu** — a separate, sibling plan,
  `2026-09-27-whyline-entry-menu.md`. That plan's "relay" choice execs into
  the `setup` command this plan builds; either can ship first.
