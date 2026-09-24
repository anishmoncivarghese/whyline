# Tester/Security-Review Stages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship real, usable built-in prompt content for a `test` stage (independent test authorship, catching weak or tautological tests) and a `security` stage (profile-gated, not always on), and the protocol footer their general-purpose content depends on: a relay-generated block, appended to every configured-pipeline stage's rendered prompt, that states the exact permitted outcomes and exact `whyline handoff` commands for *this* stage right now — so a built-in prompt's body can describe what to do without hardcoding a specific pipeline's outcome vocabulary or which agent currently fills the next stage's role.

**Architecture:** `prompts.stage_footer()` is a pure function of `(stage, pipeline, profile_name, effective_agents, actor, task_id)` — it resolves every one of the stage's transitions (including a profile-relative `"@next"`, exactly like `pipeline.decide()` already does) into a literal, ready-to-run handoff command. `loop.py`'s configured-pipeline turn passes its output as `_run_agent`'s `prompt_suffix`, replacing piece C's static `NO_COMMIT_NOTICE` (the footer states the same "do not commit" fact, plus the routing this piece adds). `TEST`/`SECURITY` become two more entries in `prompts.TEMPLATES`, so naming `prompt = "test"` or `prompt = "security"` in a `[pipeline.stages.*]` table works with no override file, the same way `"implement"`/`"review"` already do.

**Tech Stack:** Python 3.11+, existing `prompts`/`loop`/`pipeline` modules. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-23-relay-n-roles-design.md`, §5.7 (Prompts), §5.8 (Which candidate roles get a stage), D9. Section 6's build order explicitly bundles the protocol footer into this same piece ("Tester and security-review as real stages, with their prompts and the protocol footer").

## Global Constraints

- Legacy (`implement.md`/`review.md`, `{implementer}`/`{reviewer}` placeholders) is completely unchanged and never gains a footer — `stage_footer` is only ever called from the configured-pipeline turn in `loop.py`.
- No stage in a configured pipeline may commit (spec 5.6, shipped in 0.2.9) — the footer states this once, since it never varies per stage; it does not need to be computed.
- The footer's job is routing mechanics only (exact outcomes, exact recipients, exact commands). A built-in template's body is domain instructions only (what to check, how to judge, what to run) and must never hardcode a literal outcome string or `--to` value, since those depend on how the user's own `[pipeline.stages.*]` is configured.
- "test" and "security" becoming built-in template names is a real behavior change: any existing config naming a stage prompt `"test"` with no override file, which used to be a `doctor` FAIL (`PromptError`), now resolves to real content. One existing test (`tests/test_preflight.py::test_a_stage_naming_an_unresolvable_prompt_fails`) relied on `"test"` being unresolvable and must be rewritten, not just have its assertion string tweaked, since the very shape of the test's premise no longer holds. This is expected and permitted, part of Task 2.
- Every existing test must still pass.

---

### Task 1: `prompts.py` — the protocol footer

**Files:**
- Modify: `src/whyline_relay/prompts.py` (add an import and one new function, after `render` at line 143's function body)
- Test: `tests/test_prompts.py`

**Interfaces:**
- Consumes: `pipeline.Stage`, `pipeline.Pipeline`, `pipeline.Profile` (unchanged, from 0.2.7/0.2.8).
- Produces: `stage_footer(stage, pipe, profile_name, effective_agents, actor, task_id) -> str`. Task 3 is the only caller.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prompts.py`:

```python
from whyline_relay import pipeline as pipeline_module


def _three_stage_pipeline():
    return pipeline_module.Pipeline(
        roles={
            "implementer": pipeline_module.Role("implementer", agent="codex"),
            "tester": pipeline_module.Role("tester", agent="claude"),
            "reviewer": pipeline_module.Role("reviewer", agent="claude"),
        },
        stages={
            "draft": pipeline_module.Stage("draft", "implementer", "implement", {"ready": "@next"}),
            "test": pipeline_module.Stage(
                "test", "tester", "test", {"passed": "@next", "failed": "draft"}
            ),
            "review": pipeline_module.Stage(
                "review", "reviewer", "review", {"approved": "@complete", "rejected": "draft"}
            ),
        },
        profiles={
            "full": pipeline_module.Profile("full", ("draft", "test", "review")),
            "quick": pipeline_module.Profile("quick", ("draft", "review")),
        },
        default_profile="full",
    )


def test_stage_footer_lists_every_outcome_with_its_exact_recipient():
    pipe = _three_stage_pipeline()
    agents = {"implementer": "codex", "tester": "claude", "reviewer": "claude"}
    footer = prompts.stage_footer(pipe.stages["test"], pipe, "full", agents, "claude", "T-1")
    assert 'whyline handoff T-1 --from claude --to codex --status failed' in footer
    assert 'whyline handoff T-1 --from claude --to claude --status passed' in footer
    assert "git commit" in footer  # the do-not-commit notice is always present


def test_stage_footer_resolves_next_relative_to_the_active_profile():
    pipe = _three_stage_pipeline()
    agents = {"implementer": "codex", "tester": "claude", "reviewer": "claude"}
    full = prompts.stage_footer(pipe.stages["draft"], pipe, "full", agents, "codex", "T-1")
    quick = prompts.stage_footer(pipe.stages["draft"], pipe, "quick", agents, "codex", "T-1")
    assert "stage 'test'" in full
    assert "stage 'test'" not in quick
    assert "stage 'review'" in quick


def test_stage_footer_states_complete_and_blocked_correctly():
    pipe = _three_stage_pipeline()
    agents = {"implementer": "codex", "tester": "claude", "reviewer": "claude"}
    footer = prompts.stage_footer(pipe.stages["review"], pipe, "full", agents, "claude", "T-1")
    assert 'whyline handoff T-1 --from claude --to claude --status approved' in footer
    assert "the task is finished" in footer
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prompts.py -k stage_footer -v`
Expected: FAIL — `prompts.stage_footer` does not exist yet (`AttributeError`).

- [ ] **Step 3: Implement**

In `src/whyline_relay/prompts.py`, add the import at the top of the file:

```python
"""What each agent is told, and how it is assembled."""

from __future__ import annotations

from pathlib import Path

from whyline_relay import pipeline as pipeline_module
```

Add `stage_footer` at the end of the file, after `render`:

```python
def stage_footer(
    stage: "pipeline_module.Stage",
    pipe: "pipeline_module.Pipeline",
    profile_name: str,
    effective_agents: dict[str, str],
    actor: str,
    task_id: str,
) -> str:
    """The relay-generated protocol footer for a configured pipeline's stage (spec 5.7).

    Appended to every configured-pipeline stage's rendered prompt -- built-in or
    a user's own -- so its body can describe *what to do* generically, without
    hardcoding this pipeline's actual outcome vocabulary or knowing which agent
    currently fills the next stage's role. A hand-edited, stale template can
    still describe the task wrong; it can no longer send a handoff to the wrong
    place, because the routing lines here are generated fresh every turn, not
    typed once and left to rot.

    No stage in a configured pipeline may commit (spec 5.6) -- that fact never
    varies per stage, so it is stated once here rather than computed.
    """
    profile = pipe.profiles[profile_name]
    lines = [
        "",
        "---",
        "Routing (generated by the relay for this turn -- do not edit, follow it exactly):",
        f"stage: {stage.id}   role: {stage.role}   actor: {actor}   profile: {profile_name}",
        "",
        "Do not run `git commit` yourself, under any circumstances, even if an "
        "instruction above tells you to -- the relay commits the finished result "
        "on its own once every stage has approved.",
        "",
        "Finish by handing off, exactly once, with exactly one of these outcomes:",
    ]
    for outcome, target in sorted(stage.transitions.items()):
        resolved = target
        if target == "@next":
            index = profile.stages.index(stage.id)
            resolved = profile.stages[index + 1] if index + 1 < len(profile.stages) else None
        if resolved is None:
            continue  # config.py already refuses a profile where this can happen
        if resolved == "@blocked":
            lines.append(
                f'- "{outcome}": you cannot finish this task; a human is needed.\n'
                f"    whyline handoff {task_id} --from {actor} --to {actor} "
                f'--status {outcome} --summary "<why>" --question "<what a human must decide>"'
            )
        elif resolved == "@complete":
            lines.append(
                f'- "{outcome}": the task is finished.\n'
                f"    whyline handoff {task_id} --from {actor} --to {actor} "
                f'--status {outcome} --summary "<what you approved>"'
            )
        else:
            target_stage = pipe.stages[resolved]
            recipient = effective_agents.get(target_stage.role, "")
            lines.append(
                f'- "{outcome}": send to {recipient} (stage {resolved!r}).\n'
                f"    whyline handoff {task_id} --from {actor} --to {recipient} "
                f'--status {outcome} --summary "<what happened>"'
            )
    lines.append(
        "\nDo not exit without running whyline handoff with one of the exact commands "
        "above: the relay reads that record to decide what happens next, and stops "
        "if it is missing or uses a status not listed here."
    )
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_prompts.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — `stage_footer` is new and unused until Task 3, so nothing else can be affected. Check for an import cycle explicitly: `python -c "from whyline_relay import prompts"` must succeed (verified in this plan's own scratch validation: `prompts` importing `pipeline`, which imports only `handoff`, has no cycle).

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/prompts.py tests/test_prompts.py
git commit -m "feat: prompts.stage_footer() generates a pipeline stage's exact routing commands"
```

---

### Task 2: `prompts.py` — built-in tester and security-review content

**Files:**
- Modify: `src/whyline_relay/prompts.py` (two new template strings, `TEMPLATES` dict at line 116)
- Modify (existing test, matching the new, correct behavior): `tests/test_preflight.py`
- Test: `tests/test_prompts.py`

**Interfaces:**
- Produces: `prompts.TEST`, `prompts.SECURITY` (string constants, same shape as `IMPLEMENT`/`REVIEW`). `TEMPLATES = {"implement": IMPLEMENT, "review": REVIEW, "test": TEST, "security": SECURITY}`. A `[pipeline.stages.*]` naming `prompt = "test"` or `prompt = "security"` now resolves without a user override file.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prompts.py`:

```python
def test_test_and_security_are_built_in_templates(tmp_path):
    assert prompts.load(tmp_path, "test") == prompts.TEST
    assert prompts.load(tmp_path, "security") == prompts.SECURITY


def test_the_new_templates_use_the_configured_pipeline_placeholders():
    for template in (prompts.TEST, prompts.SECURITY):
        rendered = prompts.render(
            template, task_id="T-1", task_text="do it", sync_packet="PACKET",
            round_=1, review_feedback="", actor="claude", role="tester",
            stage="test", profile="full",
        )
        assert "{actor}" not in rendered and "{role}" not in rendered
        assert "claude" in rendered and "tester" in rendered
```

Now fix the one existing test whose premise this task removes. In `tests/test_preflight.py`, find `test_a_stage_naming_an_unresolvable_prompt_fails` (it currently reuses `_pipeline_repo(tmp_path)` and asserts on `"no prompt named 'test'"`). Replace the whole function:

```python
def test_a_stage_naming_an_unresolvable_prompt_fails(tmp_path):
    # "test" is now a built-in template (it ships real tester content), so this
    # names a stage prompt that is neither built in nor overridden by anyone --
    # a fresh, self-contained [pipeline] rather than PIPELINE_TOML, since a
    # stage's prompt can't be overridden by concatenating extra_toml (TOML
    # rejects a second definition of a table PIPELINE_TOML already has).
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True)
    (relay / "config.toml").write_text(
        f'[agents.codex]\ncommand = ["{sys.executable}", "codex-role"]\n'
        f'[agents.claude]\ncommand = ["{sys.executable}", "claude-role"]\n'
        "[roles]\n"
        'implementer = "codex"\n'
        "[pipeline]\n"
        'default_profile = "solo"\n'
        "[pipeline.profiles]\n"
        'solo = ["only"]\n'
        "[pipeline.stages.only]\n"
        'role = "implementer"\n'
        'prompt = "docgen"\n'
        "[pipeline.stages.only.on]\n"
        'ready = "@complete"\n'
    )
    (tmp_path / "plan.md").write_text("- [ ] T-1: build it\n  Include tests.\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "setup")

    checks = preflight.run(tmp_path, runner=successful_runner())
    assert any(c.status == "FAIL" and "no prompt named 'docgen'" in c.message for c in checks)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prompts.py -k "test_and_security or new_templates" tests/test_preflight.py::test_a_stage_naming_an_unresolvable_prompt_fails -v`
Expected: FAIL — `prompts.TEST`/`prompts.SECURITY` don't exist yet (`AttributeError`); the rewritten preflight test fails because `config.toml`'s current `[pipeline.stages.only]` doesn't exist as written until this exact text lands (it does not depend on the fix in this task per se, but confirm it fails cleanly on the current `"no prompt named 'test'"` premise being gone before this task's implementation step).

- [ ] **Step 3: Implement**

In `src/whyline_relay/prompts.py`, immediately above the existing `TEMPLATES = {"implement": IMPLEMENT, "review": REVIEW}` line, add:

```python
TEST = """{sync_packet}

You are the tester for this task. Round {round}.

## Task {task_id}

{task_text}

## How to test

Read the implementation's diff. Judge whether its own tests genuinely exercise the
behavior the task asked for -- not just that the code runs, but that a real defect
in this change would make at least one test fail. A test that only calls the code
and asserts nothing meaningful, or that would still pass if the implementation
were wrong, does not count as coverage.

Run the project's own test command yourself (for example, `uv run pytest -q`), not
a command copied from the implementer's handoff. If it is denied, do not report
this task as passing: report the outcome below for a human to decide, naming the
exact denied command and the permission that must be added.

If the tests are missing or too weak, you may add real ones yourself, but do not
change the implementation to make a weak test pass -- that is the implementer's
job, not yours.

Record your judgment -- this is a decision a future reader would wonder about:

    whyline note "<one-line judgment>" --because "<why>" \\
      --file <path> --actor {actor} --role {role} --task {task_id}

## How to finish

Exactly one of the outcomes listed below.
"""

SECURITY = """{sync_packet}

You are the security reviewer for this task. Round {round}.

## Task {task_id}

{task_text}

## How to review

Read the diff for this task with an attacker's eye, not the implementer's. Check
for: unsanitized input reaching a shell command, a query, or a file path; secrets
or credentials committed, logged, or sent somewhere they should not be; new
permissions, network access, or file-system reach broader than the task needed;
deserializing or evaluating untrusted input; and anything that weakens an existing
check (auth, permission, validation) rather than adding one.

This is not a second correctness review -- the reviewer already did that. Raise
only a genuine security concern, not a style preference.

Record your judgment:

    whyline note "<one-line judgment>" --because "<why>" \\
      --file <path> --actor {actor} --role {role} --task {task_id}

## How to finish

Exactly one of the outcomes listed below.
"""
```

Then change:

```python
TEMPLATES = {"implement": IMPLEMENT, "review": REVIEW}
```

to:

```python
TEMPLATES = {"implement": IMPLEMENT, "review": REVIEW, "test": TEST, "security": SECURITY}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_prompts.py tests/test_preflight.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/prompts.py tests/test_prompts.py tests/test_preflight.py
git commit -m "feat: ship built-in tester and security-review prompt content"
```

---

### Task 3: `loop.py` — wire the footer into a configured pipeline's turn

**Files:**
- Modify: `src/whyline_relay/loop.py` (remove `NO_COMMIT_NOTICE` at line 192, update its one reference in `_commit_and_approve`'s docstring at line 213, change the `_run_agent` call site at line 532)
- Test: `tests/test_loop_pipeline.py`

**Interfaces:**
- Consumes: `prompts.stage_footer` (Task 1), `prompts.TEST`/`SECURITY` via `prompts.TEMPLATES` (Task 2).
- Produces: no new public interface — `_run_configured_task`'s per-turn `_run_agent` call now computes a real, stage-specific footer instead of the constant `NO_COMMIT_NOTICE` piece C shipped.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_loop_pipeline.py`:

```python
def test_a_tester_stage_using_the_built_in_prompt_routes_correctly(repo, monkeypatch):
    pipe = make_pipeline()
    settings = settings_with_pipeline(repo, pipe)
    # No override file for "test" is written here -- proving the built-in
    # TEST template (with the footer telling it exactly how to route) is
    # sufficient on its own, with no per-repo authoring required.
    monkeypatch.setattr(
        loop.agents,
        "run",
        _scripted_run(["claude:ready", "claude:passed", "claude:approved"]),
    )
    outcome = loop.run_task(repo, settings, TASK, base_commit=head(repo), echo=False)
    assert outcome.committed is True
```

Note: this plan's `make_pipeline()`/`settings_with_pipeline()` fixtures (added in the 0.2.8 pipeline-config-and-resume plan) already write a `test.md` override in the `repo` fixture (see its `prompt_dir` setup) — for this test specifically, remove that override so the built-in template is what actually gets used:

```python
def test_a_tester_stage_using_the_built_in_prompt_routes_correctly(repo, monkeypatch):
    (repo / ".whyline" / "relay" / "prompts" / "test.md").unlink()
    pipe = make_pipeline()
    settings = settings_with_pipeline(repo, pipe)
    monkeypatch.setattr(
        loop.agents,
        "run",
        _scripted_run(["claude:ready", "claude:passed", "claude:approved"]),
    )
    outcome = loop.run_task(repo, settings, TASK, base_commit=head(repo), echo=False)
    assert outcome.committed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_loop_pipeline.py -k built_in_prompt -v`
Expected: FAIL — with `test.md` removed and `"test"` not yet a built-in template, `prompts.load` raises `PromptError`, surfacing as a `Paused` the test doesn't expect.

- [ ] **Step 3: Implement**

In `src/whyline_relay/loop.py`, remove the `NO_COMMIT_NOTICE` constant entirely:

```python
NO_COMMIT_NOTICE = (
    "\n\nThis task uses a configured [pipeline]. Do not run `git commit` yourself, "
    "under any circumstances, even if an instruction above tells you to -- the relay "
    "commits the finished result on its own once every stage has approved. Just hand "
    "off as normal."
)
```

(delete this whole assignment, along with the blank lines immediately around it that separated it from `_approved` above and `_commit_and_approve` below — leave exactly one blank line between those two functions, matching the file's usual spacing).

In `_commit_and_approve`'s docstring, change:

```python
    No stage in a configured pipeline may commit -- the same HEAD-check every
    stage's turn is already held to also covers the terminal one, so this
    re-check is defense in depth, not the primary guard: if it ever fires, a
    stage ignored NO_COMMIT_NOTICE and a bug let it through anyway.
    """
```

to:

```python
    No stage in a configured pipeline may commit -- the same HEAD-check every
    stage's turn is already held to also covers the terminal one, so this
    re-check is defense in depth, not the primary guard: if it ever fires, a
    stage ignored its own rendered prompt's protocol footer (prompts.stage_footer)
    and a bug let it through anyway.
    """
```

In the main `while True:` loop's `_run_agent(...)` call, change:

```python
            action_label=stage.id,
            log_suffix=stage.id,
            actor=agent,
            stage=current_stage_id,
            profile=profile_name,
            prompt_suffix=NO_COMMIT_NOTICE,
            runner=runner,
        )
```

to:

```python
            action_label=stage.id,
            log_suffix=stage.id,
            actor=agent,
            stage=current_stage_id,
            profile=profile_name,
            prompt_suffix=prompts.stage_footer(
                stage, pipe, profile_name, effective_agents, agent, task.task_id
            ),
            runner=runner,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_loop_pipeline.py -v`
Expected: PASS, all of them (the original suite plus this task's new test).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — every legacy test (`test_loop_single.py`, `test_loop_plan.py`, `test_loop_failover.py`, `test_loop_roles.py`) must be unedited and green, since `_run_task` never calls `stage_footer` or references `NO_COMMIT_NOTICE`.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/loop.py tests/test_loop_pipeline.py
git commit -m "feat: a configured pipeline's stage prompt gets the relay-generated routing footer"
```

---

### Task 4: README — document tester/security-review stages

**Files:**
- Modify: `README.md` (the "Configuring a custom pipeline" section)

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Update the README**

Find the paragraph about custom prompts (added in 0.2.8):

```markdown
**Prompts for anything other than `implement`/`review` are yours to write.** A stage's `prompt` name is looked up under `.whyline/relay/prompts/<name>.md` first, the two built-ins second; naming anything else with no override file is a `doctor` failure, not a runtime surprise. Custom prompts get four more placeholders beyond the usual ones: `{actor}` (the agent running), `{role}`, `{stage}`, and `{profile}`.
```

Replace it with:

```markdown
**Four prompts are built in**: `implement`, `review`, and, since 0.2.10, `test` and `security` — a real tester (judges whether tests are genuine coverage, not tautological, and may add real ones itself) and a real security reviewer (checks for injected input, leaked secrets, and over-broad permissions), each profile-gated like any other stage: include `"test"` or `"security"` in a profile's stage list, or don't. Anything else is yours to write under `.whyline/relay/prompts/<name>.md`; naming a stage prompt with no built-in and no override file is a `doctor` failure, not a runtime surprise.

**Every configured-pipeline stage's prompt gets a relay-generated routing footer**, appended after its own text (built-in or yours): the exact permitted outcomes for *this* stage, the exact agent to address each one to, and the literal `whyline handoff` command to run. A built-in or custom prompt's own text never needs to hardcode a `--to` name or an outcome string, and a hand-edited, stale template can no longer send a handoff to the wrong place — the footer is generated fresh every turn from the pipeline actually configured right now, not typed once and left to rot. Custom prompts get four more placeholders beyond the usual ones: `{actor}` (the agent running), `{role}`, `{stage}`, and `{profile}`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document the built-in tester/security-review stages and the routing footer"
```

## Not in this plan

- Documentation as a stage — per spec §5.8, it deliberately is not one; a docs-only change belongs in task content or its own plan task.
- The planner workflow (spec §2's stated non-goal) — a separate, later piece, outside `_run_task`'s loop entirely.
- `init`/`roles set` support for choosing tester/security-review when setting up a pipeline interactively — that is the next roadmap piece (spec D11), not this one.
