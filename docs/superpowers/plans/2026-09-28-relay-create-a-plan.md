# Relay "Create a Plan" via Brainstorming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `whyline-relay setup` gains a third plan-source choice, "brainstorm," that runs the existing multi-model brainstorm engine and turns its final synthesis into a real, validated, human-approved `plan.md`; the role wizard gains a backup-chain question, now meaningful since the backup chain shipped (0.2.21).

**Architecture:** One new function in `brainstorm.py` (`generate_plan_from_synthesis`, reusing `chat.run_turn` unchanged) turns the synthesis into a checkbox-formatted plan.md, validated via `plan.parse()` with a bounded retry. The existing approve/revise/discard human gate in `planner.py` (`_human_gate`) is generalized into a public, parameterized `review_gate` that both the existing simple-draft flow and the new brainstorm flow share, each supplying its own "what happens on revise" behavior.

**Tech Stack:** Python 3.11+, stdlib only. No new dependency. Entirely within `whyline-relay`.

**Spec:** `docs/superpowers/specs/2026-09-28-relay-create-a-plan-design.md`

## Global Constraints

- No new runtime dependency.
- The simple 2-agent draft flow (`planner.py`) is untouched in behavior -- Task 2's refactor must not change any of its existing tests' outcomes.
- No cross-invocation resume/checkpointing is added for the brainstorm-to-plan flow -- a crash mid-flow means starting the "brainstorm" choice over.
- The backup-chain wizard question is never validated inline -- a bad agent name surfaces later at the existing `doctor` gate, matching how implementer/tester/reviewer already behave.
- `generate_plan_from_synthesis`'s retry budget is exactly 2 total attempts; an agent-availability failure (`AgentMissing`/`AgentTimeout`/`AgentUnavailable`) is never treated as a retry-worthy parse failure -- it propagates immediately.
- Every existing test in this repo must still pass after every task, except the ones this plan explicitly rewrites because the wizard's own answer sequence gained a new question.

**Note on this pairing:** Grok implements, Codex reviews -- every task in this plan only modifies existing files (`setup.py`, `planner.py`, `brainstorm.py`), never creates a new top-level directory, matching exactly the kind of task Grok has been reliable on all session (chat-failover, backup-chain) as opposed to the one task shape (new-directory creation) that proved unreliable in the console-foundation plan.

---

### Task 1: `run_role_wizard` gains a backup-chain question

**Files:**
- Modify: `src/whyline_relay/setup.py`
- Test: `tests/test_setup.py`

**Interfaces:**
- Produces: `run_role_wizard(...)` now returns `{"implementer": ..., "tester": ..., "reviewer": ..., "backup": <comma-joined string, "" if none>}`. Writes `[backup]\nchain = [...]\n` appended to config.toml only when the answer is non-empty.

- [ ] **Step 1: Write the failing tests**

First, fix every *existing* test in `tests/test_setup.py` that supplies a
fixed `answers` sequence to `run_role_wizard` or `setup.run` -- each now
needs one more answer for the new backup question, inserted right after
the reviewer answer:

1. `test_run_role_wizard_writes_config_and_test_prompt`: change
   `answers = iter(["grok", "codex", ""])` to
   `answers = iter(["grok", "codex", "", ""])` (blank reviewer default,
   blank backup), and change the assertion to
   `assert result == {"implementer": "grok", "tester": "codex", "reviewer": "claude", "backup": ""}`.
2. `test_run_role_wizard_config_parses_as_a_valid_pipeline`: change
   `answers = iter(["codex", "claude", "claude"])` to
   `answers = iter(["codex", "claude", "claude", ""])`.
3. `test_run_commits_setup_before_running_doctor`: change
   `answers = iter(["existing", "codex", "claude", "claude", "n"])` to
   `answers = iter(["existing", "codex", "claude", "claude", "", "n"])`.
4. `test_run_refuses_to_offer_start_on_a_fail`: change
   `answers = iter(["existing", "codex", "claude", "claude"])` to
   `answers = iter(["existing", "codex", "claude", "claude", ""])`.
5. `test_run_asks_before_proceeding_on_a_warn_and_honors_no`: change
   `answers = iter(["existing", "codex", "claude", "claude", "n"])` to
   `answers = iter(["existing", "codex", "claude", "claude", "", "n"])`.
6. `test_run_execs_into_start_when_clean_and_confirmed`: change
   `answers = iter(["existing", "codex", "claude", "claude", ""])` (the
   trailing `""` was for "start now [Y]") to
   `answers = iter(["existing", "codex", "claude", "claude", "", ""])` (now
   two trailing blanks: backup, then start-confirm).

Then add new tests:

```python
def test_run_role_wizard_backup_chain_writes_backup_table(tmp_path: Path):
    answers = iter(["codex", "claude", "claude", "aider, backup2"])
    result = setup.run_role_wizard(
        tmp_path,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    assert result["backup"] == "aider, backup2"
    config_text = (tmp_path / ".whyline" / "relay" / "config.toml").read_text()
    assert "[backup]" in config_text
    assert 'chain = ["aider", "backup2"]' in config_text


def test_run_role_wizard_blank_backup_writes_no_backup_table(tmp_path: Path):
    answers = iter(["codex", "claude", "claude", ""])
    result = setup.run_role_wizard(
        tmp_path,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    assert result["backup"] == ""
    config_text = (tmp_path / ".whyline" / "relay" / "config.toml").read_text()
    assert "[backup]" not in config_text


def test_run_role_wizard_backup_chain_config_loads_correctly(tmp_path: Path):
    answers = iter(["codex", "claude", "claude", "claude"])
    setup.run_role_wizard(
        tmp_path,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    loaded = config.load(tmp_path)
    assert loaded.backup_chain == ["claude"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -v`
Expected: FAIL on every test touching `run_role_wizard` (`StopIteration` from the now-too-short answer iterators, or the three new tests not yet passing).

- [ ] **Step 3: Implement**

In `src/whyline_relay/setup.py`, replace `run_role_wizard`:

```python
def run_role_wizard(root: Path, *, input_fn=None, print_fn=None) -> dict[str, str]:
    """Asks implementer/tester/reviewer/backup, writes config.toml and
    prompts/test.md. Returns the chosen agent names, "backup" as a
    comma-joined string ("" if none was given)."""
    input_fn = input_fn if input_fn is not None else input
    print_fn = print_fn if print_fn is not None else print

    implementer = input_fn("Who implements? [codex]: ").strip() or "codex"
    tester = input_fn("Who tests?      [claude]: ").strip() or "claude"
    reviewer = input_fn("Who reviews?    [claude]: ").strip() or "claude"
    backup_raw = input_fn(
        "Backup chain (comma-separated, blank for none): "
    ).strip()
    backup_chain = [name.strip() for name in backup_raw.split(",") if name.strip()]

    relay = config.relay_dir(root)
    config_path = relay / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    content = PIPELINE_CONFIG_TEMPLATE.format(
        implementer=implementer, tester=tester, reviewer=reviewer
    )
    if backup_chain:
        chain_toml = ", ".join(f'"{name}"' for name in backup_chain)
        content += f"\n[backup]\nchain = [{chain_toml}]\n"
    config_path.write_text(content, encoding="utf-8")
    print_fn(f"Wrote {config_path.relative_to(root)}.")

    test_prompt_path = relay / "prompts" / "test.md"
    test_prompt_path.parent.mkdir(parents=True, exist_ok=True)
    test_prompt_path.write_text(TEST_PROMPT_TEMPLATE, encoding="utf-8")
    print_fn(f"Wrote {test_prompt_path.relative_to(root)}.")

    return {
        "implementer": implementer,
        "tester": tester,
        "reviewer": reviewer,
        "backup": ", ".join(backup_chain),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_setup.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/setup.py tests/test_setup.py
git commit -m "feat: role wizard asks for a backup chain"
```

---

### Task 2: Generalize the human gate into `planner.review_gate`

**Files:**
- Modify: `src/whyline_relay/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- Produces: `review_gate(root, settings, draft_path, description, *, drafted_by, revise_fn, on_settled=lambda: None, confirm=input, echo=True, runner=subprocess.run) -> str` -- a new, public function. `revise_fn: Callable[[str], None]` is called with the human's typed feedback and is responsible for regenerating whatever's at `draft_path`. `on_settled: Callable[[], None]` is called once, right after a discard or right after a successful approve-write, for a caller with its own session state to clear (the simple planner clears its checkpoint here; the new brainstorm flow has none, so it stays the default no-op).
- Consumes: nothing new from Task 1.

- [ ] **Step 1: Write the failing tests**

Read `tests/test_planner.py` in full first (392 lines) -- it already has
five tests exercising `_human_gate`'s approve/revise/discard behavior
through `planner.start`/`resume` (their names:
`test_discarding_clears_the_checkpoint_and_keeps_the_draft_file`,
`test_requesting_changes_redrafts_before_the_gate_reappears`, and others
around lines 260-364). **None of these need to change** -- this task is a
pure refactor, and they must all still pass unchanged afterward, proving
`_human_gate`'s externally-visible behavior (via `planner.start`/`resume`)
is identical.

Add new tests exercising `review_gate` directly, at the bottom of the file:

```python
def test_review_gate_approve_writes_and_commits(tmp_path: Path):
    from whyline_relay import gitcheck

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    settings = settings_with_planner(tmp_path)
    draft = tmp_path / ".whyline" / "relay" / "some-draft.md"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("- [ ] T-1: x\n  y.\n")

    result = planner.review_gate(
        tmp_path, settings, draft, "a plan",
        drafted_by="test-agent",
        revise_fn=lambda feedback: (_ for _ in ()).throw(
            AssertionError("must not be called on approve")
        ),
        confirm=_confirm(["a", "n"]),
    )
    assert "Wrote" in result
    assert (tmp_path / settings.plan).read_text() == "- [ ] T-1: x\n  y.\n"
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=tmp_path,
        capture_output=True, text=True,
    ).stdout
    assert "test-agent" in log


def test_review_gate_revise_calls_revise_fn_with_feedback(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    settings = settings_with_planner(tmp_path)
    draft = tmp_path / ".whyline" / "relay" / "some-draft.md"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("- [ ] T-1: round 1\n  y.\n")
    received = []

    def revise(feedback: str) -> None:
        received.append(feedback)
        draft.write_text("- [ ] T-1: round 2\n  y.\n")

    result = planner.review_gate(
        tmp_path, settings, draft, "a plan",
        drafted_by="test-agent", revise_fn=revise,
        confirm=_confirm(["r", "make it shorter", "a", "n"]),
    )
    assert received == ["make it shorter"]
    assert "round 2" in (tmp_path / settings.plan).read_text()


def test_review_gate_discard_calls_on_settled_and_keeps_the_draft(tmp_path: Path):
    settings = settings_with_planner(tmp_path)
    draft = tmp_path / ".whyline" / "relay" / "some-draft.md"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("- [ ] T-1: x\n  y.\n")
    settled = []

    result = planner.review_gate(
        tmp_path, settings, draft, "a plan",
        drafted_by="test-agent",
        revise_fn=lambda feedback: (_ for _ in ()).throw(
            AssertionError("must not be called on discard")
        ),
        on_settled=lambda: settled.append(True),
        confirm=_confirm(["d"]),
    )
    assert "Discarded" in result
    assert settled == [True]
    assert draft.exists()
    assert not (tmp_path / settings.plan).exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_planner.py -v`
Expected: FAIL on the three new `review_gate` tests
(`AttributeError: module 'planner' has no attribute 'review_gate'`); the
five pre-existing gate-related tests still pass (nothing has changed yet).

- [ ] **Step 3: Implement**

In `src/whyline_relay/planner.py`, replace `_human_gate` with a new public
`review_gate` plus a thin wrapper preserving the old name and exact
behavior for this module's own two call sites (`start`, `resume`):

```python
def review_gate(
    root: Path,
    settings: config.Config,
    draft_path: Path,
    description: str,
    *,
    drafted_by: str,
    revise_fn,
    on_settled=lambda: None,
    confirm=input,
    echo: bool = True,
    runner: failover.Runner = subprocess.run,
) -> str:
    """The shared three-way human approval gate for any drafted plan.md.

    `revise_fn(feedback)` is called on "request changes" and must leave a
    revised draft at `draft_path` when it returns -- the gate then re-reads
    it and asks again. `on_settled()` is called once, right after a discard
    or right after a successful approve-write, so a caller with its own
    session state (the simple planner's checkpoint; a future caller's own
    equivalent) can clear it -- callers with none pass the default no-op.
    """
    text = draft_path.read_text(encoding="utf-8")
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
        revise_fn(feedback)
        return review_gate(
            root, settings, draft_path, description,
            drafted_by=drafted_by, revise_fn=revise_fn, on_settled=on_settled,
            confirm=confirm, echo=echo, runner=runner,
        )
    if answer.startswith("d"):
        on_settled()
        return f"Discarded. The draft is still at {draft_path}, if you want it."
    target = root / settings.plan
    if target.exists():
        try:
            overwrite = confirm(f"{target} already exists. Replace it? [y/N] ").strip().lower()
        except EOFError:
            overwrite = "n"
        if not overwrite.startswith("y"):
            return f"Not approved: {target} already exists and was not replaced."
    target.write_text(text, encoding="utf-8")
    gitcheck.commit_paths(root, [target], f"docs: add plan drafted by {drafted_by}")
    on_settled()
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


def _human_gate(
    root: Path,
    settings: config.Config,
    description: str,
    *,
    confirm=input,
    echo: bool = True,
    runner: failover.Runner = subprocess.run,
) -> str:
    """The simple planner's own gate -- a thin wrapper over review_gate,
    preserving exact prior behavior (revise re-runs the draft<->review
    pipeline; settling clears this module's own checkpoint)."""

    def revise(feedback: str) -> None:
        _run_pipeline(
            root, settings, description,
            current_stage_id="draft", round_=1, stage_visits={"draft": 1},
            feedback=feedback, echo=echo, runner=runner,
        )

    return review_gate(
        root, settings, draft_path(root), description,
        drafted_by=settings.planner.draft,
        revise_fn=revise,
        on_settled=lambda: state.clear_plan(root),
        confirm=confirm, echo=echo, runner=runner,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_planner.py -v`
Expected: PASS -- all pre-existing tests plus the three new ones.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/planner.py tests/test_planner.py
git commit -m "feat: generalize the human plan-review gate into planner.review_gate"
```

---

### Task 3: `brainstorm.py` -- `generate_plan_from_synthesis`

**Files:**
- Modify: `src/whyline_relay/brainstorm.py`
- Test: `tests/test_brainstorm_plan.py` (new file)

**Interfaces:**
- Consumes: `chat.run_turn` (unchanged), `plan.parse`/`plan.PlanError` (unchanged).
- Produces: `brainstorm.plan_draft_path(root) -> Path`. `brainstorm.NothingToSynthesize(RuntimeError)`. `generate_plan_from_synthesis(root, settings, final_agent, models, topic, *, feedback=None, run_fn=None, runner=None, max_attempts=2) -> Path` -- returns the validated draft's path on success; raises `NothingToSynthesize` if the shared doc is empty/missing (RCP6), or the last `plan.PlanError` if still invalid after `max_attempts`; `agents.AgentMissing`/`AgentTimeout`/`chat.AgentUnavailable` propagate immediately, uncaught, unretried.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_brainstorm_plan.py`:

```python
import subprocess
from pathlib import Path

import pytest

from whyline_relay import brainstorm, config, plan


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    (root / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)


def _write_shared_doc(root: Path, topic: str) -> None:
    shared = brainstorm.shared_path(root, topic)
    shared.parent.mkdir(parents=True, exist_ok=True)
    shared.write_text(
        f"# Brainstorm: {topic}\n\n## Final Synthesis\n\ndo X then Y\n"
    )


def test_generate_plan_from_synthesis_succeeds_first_try(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)
    _write_shared_doc(tmp_path, "my topic")
    models = [("claude", "Claude")]

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        brainstorm.plan_draft_path(tmp_path).write_text(
            "- [ ] T-1: do X\n  detail.\n- [ ] T-2: do Y\n  detail.\n"
        )
        return RunResult(0, '{"type":"result","result":"done"}\n')

    result = brainstorm.generate_plan_from_synthesis(
        tmp_path, settings, "claude", models, "my topic", run_fn=fake_run_fn,
    )
    assert result == brainstorm.plan_draft_path(tmp_path)
    assert len(plan.parse(result.read_text(encoding="utf-8"))) == 2


def test_generate_plan_from_synthesis_retries_once_on_a_parse_error(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)
    _write_shared_doc(tmp_path, "my topic")
    models = [("claude", "Claude")]
    attempts = []

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        attempts.append(prompt)
        if len(attempts) == 1:
            brainstorm.plan_draft_path(tmp_path).write_text("not a real plan\n")
        else:
            brainstorm.plan_draft_path(tmp_path).write_text(
                "- [ ] T-1: do X\n  detail.\n"
            )
        return RunResult(0, '{"type":"result","result":"done"}\n')

    result = brainstorm.generate_plan_from_synthesis(
        tmp_path, settings, "claude", models, "my topic", run_fn=fake_run_fn,
    )
    assert len(attempts) == 2
    assert "did not parse" in attempts[1]
    assert len(plan.parse(result.read_text(encoding="utf-8"))) == 1


def test_generate_plan_from_synthesis_raises_after_exhausting_retries(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)
    _write_shared_doc(tmp_path, "my topic")
    models = [("claude", "Claude")]

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        brainstorm.plan_draft_path(tmp_path).write_text("not a real plan\n")
        return RunResult(0, '{"type":"result","result":"done"}\n')

    with pytest.raises(plan.PlanError):
        brainstorm.generate_plan_from_synthesis(
            tmp_path, settings, "claude", models, "my topic", run_fn=fake_run_fn,
        )
    assert brainstorm.plan_draft_path(tmp_path).exists()


def test_generate_plan_from_synthesis_refuses_when_nothing_to_synthesize(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)
    models = [("claude", "Claude")]
    with pytest.raises(brainstorm.NothingToSynthesize):
        brainstorm.generate_plan_from_synthesis(
            tmp_path, settings, "claude", models, "a topic with no doc",
        )


def test_generate_plan_from_synthesis_propagates_agent_missing_without_retrying(
    tmp_path: Path,
):
    from whyline_relay import agents

    _init_repo(tmp_path)
    settings = config.load(tmp_path)
    _write_shared_doc(tmp_path, "my topic")
    models = [("claude", "Claude")]
    attempts = []

    def fake_run_fn(command, prompt, **kwargs):
        attempts.append(1)
        raise agents.AgentMissing("claude is not installed")

    with pytest.raises(agents.AgentMissing):
        brainstorm.generate_plan_from_synthesis(
            tmp_path, settings, "claude", models, "my topic", run_fn=fake_run_fn,
        )
    assert len(attempts) == 1


def test_generate_plan_from_synthesis_includes_feedback_when_revising(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)
    _write_shared_doc(tmp_path, "my topic")
    models = [("claude", "Claude")]
    prompts_seen = []

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        prompts_seen.append(prompt)
        brainstorm.plan_draft_path(tmp_path).write_text("- [ ] T-1: x\n  y.\n")
        return RunResult(0, '{"type":"result","result":"done"}\n')

    brainstorm.generate_plan_from_synthesis(
        tmp_path, settings, "claude", models, "my topic",
        feedback="make it shorter", run_fn=fake_run_fn,
    )
    assert "make it shorter" in prompts_seen[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_brainstorm_plan.py -v`
Expected: FAIL (`AttributeError: module 'brainstorm' has no attribute
'generate_plan_from_synthesis'`, etc.)

- [ ] **Step 3: Implement**

In `src/whyline_relay/brainstorm.py`, add `import plan` alongside the
existing `from whyline_relay import agents, chat, config, gitcheck` (change
it to `from whyline_relay import agents, chat, config, gitcheck, plan`),
then add near the bottom of the file:

```python
PLAN_GENERATION_PROMPT = (
    'Read {shared_path} in full, especially its "## Final Synthesis" '
    "section. Write a real plan.md at {draft_path} in whyline-relay's own "
    'checkbox format: one "- [ ] TASK-ID: short description" line per '
    "independently implementable and testable step, with indented detail "
    "lines below each explaining what to build and how to verify it. Base "
    "it on the Final Synthesis, translating its recommendation into "
    "concrete, ordered tasks."
)


class NothingToSynthesize(RuntimeError):
    """The shared brainstorm doc has no real content to turn into a plan."""


def plan_draft_path(root: Path) -> Path:
    return config.relay_dir(root) / "brainstorm-plan-draft.md"


def generate_plan_from_synthesis(
    root: Path,
    settings: "config.Config",
    final_agent: str,
    models: list[tuple[str, str]],
    topic: str,
    *,
    feedback: str | None = None,
    run_fn=None,
    runner=None,
    max_attempts: int = 2,
) -> Path:
    """Prompts final_agent to turn its own synthesis into a real plan.md,
    validating with plan.parse() and retrying once on a parse error. Raises
    NothingToSynthesize if the shared doc is empty or missing, or the last
    plan.PlanError if still invalid after max_attempts.
    agents.AgentMissing/AgentTimeout/chat.AgentUnavailable propagate
    immediately -- an availability failure is not a retry-worthy parse
    failure, and there is no "keep the previous content" fallback here
    since nothing has been generated yet."""
    shared = shared_path(root, topic)
    if not shared.exists() or not shared.read_text(encoding="utf-8").strip():
        raise NothingToSynthesize(
            f"{shared} is empty or missing -- nothing to turn into a plan"
        )
    draft = plan_draft_path(root)
    exclude = frozenset(key for key, _ in models if key != final_agent)
    kwargs = {"run_fn": run_fn} if run_fn is not None else {}
    if runner is not None:
        kwargs["runner"] = runner

    prompt = PLAN_GENERATION_PROMPT.format(shared_path=shared, draft_path=draft)
    if feedback:
        prompt += (
            f"\n\nA human reviewed a previous draft at {draft} and asked "
            f"for this change: {feedback}\n\nRewrite the whole file at "
            f"{draft} to address it, keeping the same checkbox format."
        )

    last_error: plan.PlanError | None = None
    for attempt in range(1, max_attempts + 1):
        chat.run_turn(
            root,
            agent=final_agent,
            prompt=prompt,
            settings=settings,
            commit_message=(
                f'brainstorm: {final_agent} drafts plan.md from synthesis '
                f'on "{topic}"'
            ),
            exclude=exclude,
            **kwargs,
        )
        try:
            plan.parse(draft.read_text(encoding="utf-8"))
            return draft
        except plan.PlanError as error:
            last_error = error
            if attempt < max_attempts:
                prompt = (
                    PLAN_GENERATION_PROMPT.format(
                        shared_path=shared, draft_path=draft
                    )
                    + f"\n\nYour previous attempt at {draft} did not parse "
                    f"as a valid plan: {error}\n\nRewrite the whole file "
                    f"at {draft}, fixing this."
                )
    raise last_error
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_brainstorm_plan.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/brainstorm.py tests/test_brainstorm_plan.py
git commit -m "feat: brainstorm.generate_plan_from_synthesis turns a synthesis into a real plan.md"
```

---

### Task 4: Wire "brainstorm" into `choose_plan_source`, end to end

**Files:**
- Modify: `src/whyline_relay/setup.py`
- Test: `tests/test_setup.py`

**Interfaces:**
- Consumes: `brainstorm.ask_brainstorm_setup`/`run_pass_zero`/`merge_pass_zero`/`run_review_pass`/`run_final_synthesis`/`generate_plan_from_synthesis`/`NothingToSynthesize` (Task 3), `planner.review_gate` (Task 2).
- Produces: `choose_plan_source(...)` accepts `"brainstorm"` as a third choice; a new `_run_brainstorm_plan_source(root, settings, *, input_fn, print_fn, run_fn=None, runner=None, confirm=None) -> bool` implements it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_setup.py`:

```python
def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)


def test_choose_plan_source_brainstorm_end_to_end_writes_a_real_plan(tmp_path: Path):
    _init_git_repo(tmp_path)
    settings = config.load(tmp_path)

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        from whyline_relay import brainstorm

        if "Research" in prompt:
            brainstorm.temp_path(tmp_path, "claude").parent.mkdir(
                parents=True, exist_ok=True
            )
            brainstorm.temp_path(tmp_path, "claude").write_text("some findings\n")
        elif "checkbox format" in prompt:
            brainstorm.plan_draft_path(tmp_path).write_text(
                "- [ ] T-1: build it\n  as synthesized.\n"
            )
        elif "Final Synthesis" in prompt:
            pass  # the final-synthesis turn itself needs no file write here
        return RunResult(0, '{"type":"result","result":"ok"}\n')

    answers = iter([
        "brainstorm",   # choose_plan_source's own choice
        "build a widget",  # topic
        "1",            # models: claude only
        "0",            # passes: 0 (straight to synthesis)
        "",             # final model: default (claude)
        "a",            # review_gate: approve
        "n",            # don't start now
    ])
    result = setup.choose_plan_source(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
        run_fn=fake_run_fn,
    )
    assert result is True
    written = (tmp_path / settings.plan).read_text(encoding="utf-8")
    assert "build it" in written
    from whyline_relay import plan
    assert len(plan.parse(written)) == 1


def test_choose_plan_source_brainstorm_declined_at_availability_check(tmp_path: Path):
    settings = config.load(tmp_path)
    answers = iter([
        "brainstorm", "build a widget", "4", "0", "", "n",  # "4" = grok, unavailable here; "n" declines
    ])
    result = setup.choose_plan_source(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    assert result is False


def test_choose_plan_source_brainstorm_nothing_to_synthesize_is_reported(
    tmp_path: Path, capsys
):
    _init_git_repo(tmp_path)
    settings = config.load(tmp_path)

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        # Every phase runs but never writes any temp/shared content, so the
        # shared doc ends up empty -- simulates every model failing pass-0.
        return RunResult(0, '{"type":"result","result":"ok"}\n')

    printed = []
    answers = iter(["brainstorm", "build a widget", "1", "0", ""])
    result = setup.choose_plan_source(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        run_fn=fake_run_fn,
    )
    assert result is False
    assert any("nothing to turn into a plan" in line for line in printed)
```

Check `brainstorm.ask_brainstorm_setup`'s exact prompt wording (read it in
`src/whyline_relay/brainstorm.py` before trusting the answer sequences
above verbatim) -- the model-selection menu text, pass-count prompt, and
final-model prompt must match what these fake answers are actually
responding to.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -k brainstorm -v`
Expected: FAIL (`choose_plan_source` doesn't accept `run_fn` yet, and has
no "brainstorm" branch).

- [ ] **Step 3: Implement**

In `src/whyline_relay/setup.py`, add the necessary imports at the top:
`from whyline_relay import agents, brainstorm, chat, plan` (alongside the
existing `from whyline_relay import config, gitcheck, planner, preflight`).

Add a new function:

```python
def _run_brainstorm_plan_source(
    root: Path,
    settings: "config.Config",
    *,
    input_fn=None,
    print_fn=None,
    run_fn=None,
    runner=None,
    confirm=None,
) -> bool:
    """The "brainstorm" choice: runs the existing brainstorm engine
    unchanged, then turns its final synthesis into a real plan.md via the
    shared review gate (RCP1)."""
    input_fn = input_fn if input_fn is not None else input
    print_fn = print_fn if print_fn is not None else print
    confirm = confirm if confirm is not None else input

    setup_answers = brainstorm.ask_brainstorm_setup(
        root, settings, input_fn=input_fn, print_fn=print_fn
    )
    if setup_answers is None:
        return (root / settings.plan).exists()

    topic = setup_answers["topic"]
    models = setup_answers["models"]
    passes = setup_answers["passes"]
    final_agent = setup_answers["final_agent"]
    kwargs = {"run_fn": run_fn} if run_fn is not None else {}
    if runner is not None:
        kwargs["runner"] = runner

    actual_agents = brainstorm.run_pass_zero(
        root, models, topic, settings=settings, print_fn=print_fn, **kwargs
    )
    brainstorm.merge_pass_zero(root, models, topic, actual_agents=actual_agents)
    for pass_number in range(1, passes + 1):
        actual_agents = brainstorm.run_review_pass(
            root, models, topic, pass_number, settings=settings,
            print_fn=print_fn, actual_agents=actual_agents, **kwargs,
        )
    brainstorm.run_final_synthesis(
        root, final_agent, models, topic, settings=settings, **kwargs
    )

    try:
        draft = brainstorm.generate_plan_from_synthesis(
            root, settings, final_agent, models, topic, **kwargs
        )
    except brainstorm.NothingToSynthesize as error:
        print_fn(str(error))
        return (root / settings.plan).exists()
    except (agents.AgentMissing, agents.AgentTimeout, chat.AgentUnavailable) as error:
        print_fn(f"Could not generate a plan from the synthesis: {error}")
        return (root / settings.plan).exists()
    except plan.PlanError as error:
        print_fn(
            f"The drafted plan still did not parse after retrying: {error}. "
            f"Left at {brainstorm.plan_draft_path(root)} for you to fix by hand."
        )
        return (root / settings.plan).exists()

    def revise(feedback: str) -> None:
        brainstorm.generate_plan_from_synthesis(
            root, settings, final_agent, models, topic, feedback=feedback, **kwargs
        )

    result = planner.review_gate(
        root, settings, draft, topic,
        drafted_by=f"brainstorm ({final_agent})",
        revise_fn=revise,
        confirm=confirm,
    )
    print_fn(result)
    return (root / settings.plan).exists()
```

Now update `choose_plan_source` itself: add `run_fn=None, runner=None,
confirm=None` to its parameter list, and add a third branch. Find:

```python
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
```

and insert a new branch right after the `if choice == "draft":` block,
before `if not plan_path.exists():`:

```python
    if choice == "brainstorm":
        return _run_brainstorm_plan_source(
            root, settings, input_fn=input_fn, print_fn=print_fn,
            run_fn=run_fn, runner=runner, confirm=confirm,
        )

    if not plan_path.exists():
```

Also update the prompt text and its default-choice logic slightly higher
up in the same function -- find:

```python
    choice = (
        input_fn(
            f"Use the existing {settings.plan}, or draft a new one? "
            f"[{default_choice}]: "
        ).strip().lower()
        or default_choice
    )
```

and change the prompt wording only (the default-choice logic itself is
unchanged -- brainstorm is never the default):

```python
    choice = (
        input_fn(
            f"Use the existing {settings.plan}, draft a new one, or "
            f"brainstorm one? [{default_choice}]: "
        ).strip().lower()
        or default_choice
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_setup.py -v`
Expected: PASS (every test in the file, old and new)

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/setup.py tests/test_setup.py
git commit -m "feat: wire brainstorming into choose_plan_source as a third option"
```

---

## Final check

After Task 4's commit, run `uv run pytest -q` one more time, then manually
try the flow in a real scratch repo with two real, cheap agents and one
review pass: `whyline-relay setup`, choose "brainstorm," confirm the
resulting `docs/brainstorm/<slug>.md` reads sensibly, confirm the review
gate shows a real, parseable `plan.md` draft, approve it, and confirm
`whyline-relay start` can actually run the result.
