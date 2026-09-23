# Relay-Side Commit Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For a configured `[pipeline]`, the relay itself makes the one commit that finishes a task — no stage, including the terminal one, may commit anymore. Legacy (no `[pipeline]`) is completely untouched: the reviewer keeps committing exactly as it always has.

**Architecture:** Every stage's turn is already HEAD-checked to catch a stray commit (0.2.8 exempted the terminal stage from this; this plan removes that exemption). When `pipeline.decide()` returns `"complete"`, the relay checkpoints an `"@complete"` marker in `state.json` *before* creating the commit, then builds the commit message from the terminal handoff's `--summary` plus the task id, stages everything with `git add -A`, and commits it itself — reusing the existing `_approved()` verification unchanged. On resume, a saved `stage == "@complete"` skips straight to retrying the commit: no agent runs.

**Tech Stack:** Python 3.11+, existing `gitcheck`/`loop`/`state` modules. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-23-relay-n-roles-design.md`, §5.6 (Commit ownership) — this plan implements that section's five numbered steps exactly, plus the crash-safety and prompt-safety mechanics it implies but doesn't spell out in code.

## Global Constraints

- Legacy (`settings.pipeline is None`) is untouched: `_run_task`, `_approved`, and every legacy test must remain byte-for-byte unaffected. Only `_run_agent` gains one new optional, defaulted parameter that legacy's call site never passes.
- No stage in a configured pipeline may run `git commit`, ever — not just non-terminal stages. A stage that does is paused with a clear message and an exact `git reset` recovery command, the same shape every other HEAD-check in this codebase already uses.
- The relay's own commit is checkpointed *before* it's made (spec 5.6 step 1): a crash between "the terminal stage approved" and "the relay committed" must resume straight to retrying the commit, never re-running the terminal stage's agent, and never silently losing the approval either.
- Every existing test must still pass. Three existing tests in `tests/test_loop_pipeline.py` (added in 0.2.8, before this piece existed) simulate the terminal stage committing itself — that was correct then and is a live bug fixture now; this plan updates those three tests as part of Task 2, not as an afterthought.

---

### Task 1: `gitcheck.py` — `commit_all()`

**Files:**
- Modify: `src/whyline_relay/gitcheck.py` (add one function, after `commit_paths`, line 165)
- Test: `tests/test_gitcheck.py`

**Interfaces:**
- Produces: `commit_all(root: Path, message: str) -> bool` — stages everything (`git add -A`) and commits it as one commit; returns `False` and commits nothing if there was nothing staged. Task 2 is the only caller.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_gitcheck.py`, reusing its existing `repo` fixture (a git repo with one commit already made, `README.md` at `hello\n`) and its own `gitcheck.commit_message`/`gitcheck.dirty_paths` functions — the same idiom `test_commit_paths_commits_only_the_named_files` already uses, right above where you add these:

```python
def test_commit_all_stages_and_commits_everything(repo: Path):
    (repo / "README.md").write_text("changed\n")
    (repo / "other.txt").write_text("x")

    committed = gitcheck.commit_all(repo, "feat: two files (T-1)")

    assert committed is True
    assert gitcheck.dirty_paths(repo) == []
    assert gitcheck.commit_message(repo, gitcheck.head_commit(repo)) == "feat: two files (T-1)"


def test_commit_all_does_nothing_and_returns_false_when_the_tree_is_clean(repo: Path):
    before = gitcheck.head_commit(repo)

    committed = gitcheck.commit_all(repo, "chore: nothing")

    assert committed is False
    assert gitcheck.head_commit(repo) == before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_gitcheck.py -k commit_all -v`
Expected: FAIL — `gitcheck.commit_all` does not exist yet (`AttributeError`).

- [ ] **Step 3: Implement**

In `src/whyline_relay/gitcheck.py`, immediately after `commit_paths`:

```python
def commit_all(root: Path, message: str) -> bool:
    """Stage and commit everything in the tree as one commit.

    For a configured pipeline (spec 5.6): the relay itself makes the one commit
    that finishes a task, instead of trusting an agent to. Returns False,
    committing nothing, when there is nothing staged -- a task that touched no
    files (for example, one that only recorded a decision) is not an error, and
    repeating this call is always safe.
    """
    _git(root, "add", "-A")
    if not _git(root, "diff", "--cached", "--name-only"):
        return False
    _git(root, "commit", "-m", message)
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_gitcheck.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — a new, unused-until-Task-2 function cannot affect anything else.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/gitcheck.py tests/test_gitcheck.py
git commit -m "feat: gitcheck.commit_all() stages and commits the whole tree as one commit"
```

---

### Task 2: `loop.py` — the relay commits, no stage does

**Files:**
- Modify: `src/whyline_relay/loop.py` (`_run_agent`, a new `NO_COMMIT_NOTICE` constant and `_commit_and_approve` function after `_approved` at line 178, the resume block and per-turn guard and `"complete"` branch inside `_run_configured_task` starting at line 359)
- Modify (existing tests, matching the new, correct behavior): `tests/test_loop_pipeline.py`
- Test: `tests/test_loop_pipeline.py` (new cases, added to the existing file)

**Interfaces:**
- Consumes: `gitcheck.commit_all` (Task 1).
- Produces: `_run_agent` gains one new optional keyword parameter, `prompt_suffix: str = ""`, appended to the rendered prompt verbatim. `NO_COMMIT_NOTICE`, a module-level string constant, passed as that suffix for every configured-pipeline stage. `_commit_and_approve(root, task, base_commit, round_, log, summary) -> Outcome`, the relay's own commit-and-verify step, reusing `_approved()` internally. `_run_configured_task`'s per-turn guard now forbids a commit from *any* stage, not just non-terminal ones; its `"complete"` handling checkpoints before calling `_commit_and_approve` instead of calling `_approved` directly; its resume handling recognizes a saved `stage == "@complete"` and retries the commit without launching any agent.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_loop_pipeline.py`. First, fix the two existing scripts that simulate the terminal stage committing itself — that was correct under 0.2.8, and is exactly the bug this plan closes:

In `test_a_three_stage_pipeline_runs_end_to_end_with_a_bounce_back`, change:

```python
    monkeypatch.setattr(
        loop.agents,
        "run",
        _scripted_run(
            [
                "claude:ready",
                "codex:failed",
                "claude:ready",
                "claude:passed",
                "commit:claude:approved",
            ]
        ),
    )
```

to:

```python
    monkeypatch.setattr(
        loop.agents,
        "run",
        _scripted_run(
            [
                "claude:ready",
                "codex:failed",
                "claude:ready",
                "claude:passed",
                "claude:approved",
            ]
        ),
    )
```

In `test_resume_reconstructs_stage_and_advances_past_the_unrouted_handoff`, change:

```python
    monkeypatch.setattr(
        loop.agents,
        "run",
        _scripted_run(["claude:passed", "commit:claude:approved"]),
    )
```

to:

```python
    monkeypatch.setattr(
        loop.agents,
        "run",
        _scripted_run(["claude:passed", "claude:approved"]),
    )
```

In `test_a_non_terminal_stage_committing_is_refused`, change the match string (the guard's wording changes because it's no longer specific to "a stage that can reach @complete" — now *no* stage may commit):

```python
    with pytest.raises(loop.Paused, match="only a stage that can reach"):
```

to:

```python
    with pytest.raises(loop.Paused, match="only the relay itself commits"):
```

Now add three new tests, proving the terminal stage is guarded exactly like any other, and the new crash-safety property:

```python
def test_a_terminal_stage_committing_is_also_refused(repo, monkeypatch):
    pipe = make_pipeline()
    settings = settings_with_pipeline(repo, pipe)
    monkeypatch.setattr(
        loop.agents,
        "run",
        _scripted_run(["claude:ready", "claude:passed", "commit:claude:approved"]),
    )
    with pytest.raises(loop.Paused, match="only the relay itself commits"):
        loop.run_task(repo, settings, TASK, base_commit=head(repo), echo=False)


def test_the_relay_makes_the_commit_not_the_agent(repo, monkeypatch):
    pipe = make_pipeline()
    settings = settings_with_pipeline(repo, pipe)
    # None of these specs run "commit:" -- if a real commit exists afterward,
    # the relay made it, not any agent turn.
    monkeypatch.setattr(
        loop.agents,
        "run",
        _scripted_run(["claude:ready", "claude:passed", "claude:approved"]),
    )
    outcome = loop.run_task(repo, settings, TASK, base_commit=head(repo), echo=False)
    assert outcome.committed is True
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    assert "(T-1)" in subject


def test_crash_between_approval_and_commit_resumes_straight_to_the_commit(repo, monkeypatch):
    pipe = make_pipeline()
    settings = settings_with_pipeline(repo, pipe)
    # Simulate a crash right after the terminal "review" stage handed off "approved"
    # and the relay checkpointed stage="@complete", but before it made its own
    # commit: the handoff on disk already says approved; state.json says @complete.
    (repo / "feature.txt").write_text("x\n")
    (repo / ".whyline" / "active-handoff.json").write_text(
        '{"id": "event3", "task": "T-1", "to_actor": "claude", "status": "approved", '
        '"summary": "feat: the whole feature", "from_actor": ""}'
    )
    state.save(
        repo,
        state.RelayState(
            plan="plan.md", branch="relay/T-1", task_id="T-1", round=3,
            base_commit=head(repo), paused_reason="crash", log_path="",
            profile="full", stage="@complete",
            stage_visits={"draft": 1, "test": 1, "review": 1},
            pipeline_fingerprint=settings.pipeline_fingerprint,
        ),
    )
    called = []
    monkeypatch.setattr(loop.agents, "run", lambda *a, **k: called.append("ran"))

    outcome = loop.run_task(repo, settings, TASK, base_commit=head(repo), echo=False, resume=True)
    assert outcome.committed is True
    assert called == [], "no agent should run when only the commit itself was pending"
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    assert "feat: the whole feature (T-1)" in subject
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_loop_pipeline.py -v`
Expected: the three edited tests and `test_a_terminal_stage_committing_is_also_refused` currently FAIL (the guard still exempts the terminal stage, and its message doesn't yet say "only the relay itself commits"); `test_the_relay_makes_the_commit_not_the_agent` FAILs with `outcome.committed is False`-shaped error (no commit exists, since nothing committed); `test_crash_between_approval_and_commit_resumes_straight_to_the_commit` FAILs (`saved.stage == "@complete"` is not recognised, `pipe.stages["@complete"]` raises `KeyError`).

- [ ] **Step 3: Implement**

In `src/whyline_relay/loop.py`, add `prompt_suffix` to `_run_agent`'s signature and use it:

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
    prompt_suffix: str = "",
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
    ) + prompt_suffix
    log_role = log_suffix if log_suffix is not None else (role if implementer == reviewer else "")
    target = log_path(root, task.task_id, round_, agent, log_role)
    action = action_label or ("implementing" if role == "implementer" else "reviewing")
    ...
```

(everything from `log_role = ...` onward in the real file is unchanged — only the `_run_agent` signature and the `prompt = prompts.render(...)` expression change, as shown.)

Immediately after `_approved` (line 178's function, ending just before whatever currently follows it), add:

```python
NO_COMMIT_NOTICE = (
    "\n\nThis task uses a configured [pipeline]. Do not run `git commit` yourself, "
    "under any circumstances, even if an instruction above tells you to -- the relay "
    "commits the finished result on its own once every stage has approved. Just hand "
    "off as normal."
)


def _commit_and_approve(
    root: Path, task: plan.Task, base_commit: str, round_: int, log: Path | None, summary: str
) -> Outcome:
    """The relay itself makes a configured pipeline's one finishing commit (spec 5.6).

    No stage in a configured pipeline may commit -- the same HEAD-check every
    stage's turn is already held to also covers the terminal one, so this
    re-check is defense in depth, not the primary guard: if it ever fires, a
    stage ignored NO_COMMIT_NOTICE and a bug let it through anyway.
    """
    if gitcheck.head_commit(root) != base_commit:
        raise Paused(
            f"{task.task_id}: HEAD moved before the relay could make its own commit; "
            f"a stage committed when it must not have. Undo it with `git reset "
            f"{base_commit[:12]}` (your files stay), then resume",
            log,
        )
    body = summary.strip() or f"chore: finish {task.task_id}"
    gitcheck.commit_all(root, f"{body} ({task.task_id})")
    return _approved(root, task, base_commit, round_, log)
```

In `_run_configured_task`'s resume block, find:

```python
        profile_name = saved.profile
        current_stage_id = saved.stage
        stage_visits = dict(saved.stage_visits)
        current = handoff.read(root)
        if current is not None and current.task == task.task_id:
```

(this is immediately after the `pipeline_fingerprint` mismatch check). Insert the `"@complete"` special case directly above it:

```python
        if saved.stage == "@complete":
            # Approved and checkpointed before a previous pause, but not yet
            # committed: no agent to re-run, only the relay's own commit to retry.
            # The terminal handoff is still on disk -- nothing since has replaced
            # it, since committing it is the very last step of the task.
            current = handoff.read(root)
            if current is None or current.task != task.task_id:
                raise Paused(
                    f"{task.task_id} was approved before a previous pause, but its "
                    "handoff record is now missing or names a different task; the "
                    "relay will not guess the commit message. Resolve by hand",
                    None,
                )
            return _commit_and_approve(root, task, base_commit, round_, None, current.summary)
        profile_name = saved.profile
        current_stage_id = saved.stage
        stage_visits = dict(saved.stage_visits)
        current = handoff.read(root)
        if current is not None and current.task == task.task_id:
```

In the main `while True:` loop, find the `_run_agent(...)` call (it passes `action_label=stage.id, log_suffix=stage.id, actor=agent, stage=current_stage_id, profile=profile_name, runner=runner,`) and add `prompt_suffix=NO_COMMIT_NOTICE,` as one more keyword argument to that same call, in the same position style (right before `runner=runner,`).

Immediately after that call, find:

```python
        may_commit = "@complete" in stage.transitions.values()
        if not may_commit and gitcheck.head_commit(root) != head_before:
            raise Paused(
                f"{agent} made a commit in stage {current_stage_id!r}, which the relay "
                'forbids: only a stage that can reach "@complete" may commit. Undo it '
                f"with `git reset {head_before[:12]}` (your files stay), then resume",
                target,
            )
```

Replace it with (removing the `may_commit` carve-out entirely — every stage is guarded the same way now):

```python
        if gitcheck.head_commit(root) != head_before:
            raise Paused(
                f"{agent} made a commit in stage {current_stage_id!r}, which the relay "
                "forbids: for a configured pipeline, only the relay itself commits, "
                f"after every stage approves. Undo it with `git reset "
                f"{head_before[:12]}` (your files stay), then resume",
                target,
            )
```

Finally, find:

```python
        if decision.kind == "complete":
            return _approved(root, task, base_commit, round_, target)
        feedback = record.summary
```

Replace it with:

```python
        if decision.kind == "complete":
            # Checkpoint the approval before making the relay's own commit: a
            # crash between this save and the commit must not re-run any agent
            # on resume, only retry the commit (see the "@complete" branch above).
            if on_turn is not None:
                on_turn(
                    round_,
                    previous_id,
                    {
                        "profile": profile_name,
                        "stage": "@complete",
                        "stage_visits": dict(stage_visits),
                        "pipeline_fingerprint": settings.pipeline_fingerprint,
                    },
                )
            return _commit_and_approve(root, task, base_commit, round_, target, record.summary)
        feedback = record.summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_loop_pipeline.py -v`
Expected: PASS, all of them (the original five plus the four added/edited in this task).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — every `test_loop_*.py` legacy file must be unedited and green, proving `_run_agent`'s new defaulted parameter changed nothing observable without a configured pipeline.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/loop.py tests/test_loop_pipeline.py
git commit -m "feat: the relay itself commits a configured pipeline's finished task; no stage may"
```

---

### Task 3: README — correct the now-outdated commit-ownership claim

**Files:**
- Modify: `README.md` (the "Configuring a custom pipeline" section added in 0.2.8)

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Update the README**

Find this paragraph (added in 0.2.8, now describing exactly the behavior this plan removes):

```markdown
**Only a stage that can reach `"@complete"` may commit** — the same HEAD-check the reviewer has always been held to, generalized to whichever stage(s) your graph lets finish the task.
```

Replace it with:

```markdown
**No stage commits — the relay does.** Every stage's turn is HEAD-checked, including the terminal one: an agent that runs `git commit` itself is paused with an exact recovery command. Once the terminal stage hands off its accepted outcome, the relay stages everything and makes the one commit that finishes the task itself, using that handoff's `--summary` as the message. This removes an entire class of bug (a committing agent's own judgment being wrong) rather than only guarding against it.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: correct the commit-ownership description for a configured pipeline"
```

## Not in this plan

- Any change to legacy (unconfigured) behavior — the reviewer keeps committing inline exactly as it always has.
- The relay-generated prompt "protocol footer" from spec §5.7 (stage/role/actor/permitted-outcomes/recipient, appended structurally rather than as one plain-text notice) — `NO_COMMIT_NOTICE` here is a minimal, sufficient stand-in for the one piece of that footer this plan actually needs (telling an agent not to commit); the fuller structural footer is a separate, later piece.
