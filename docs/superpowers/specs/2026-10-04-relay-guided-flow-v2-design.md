# Relay guided flow v2: brainstorm-first plans, specs, committer and release roles

Date: 2026-10-04
Status: draft for review
Repos: whyline-relay (the engine: spec pipeline, plan from a spec, automatic
committer, release pauses) and whyline (the console: the screens).
Builds on: `2026-10-04-relay-plan-flow-design.md` (Run, the plan job,
questions, named plans; released in whyline 0.3.32).

## Why

Run (0.3.32) goes from a plan to a started relay. The user wants the whole
lifecycle in Relay mode, the way we have actually been working: brainstorm,
review the synthesis, write a spec, review it, write a plan from it, then
set up who implements, tests, reviews, commits and releases, and start.
Today the brainstorm goes straight to a plan with no review of the
synthesis, there is no spec step, the committer depends on a config detail
the user can't see, and release tasks have no place: we did them by hand,
outside the relay.

## Decisions (2026-10-04, with the user)

1. **New plans start with a brainstorm by default.** "I'll describe it" and
   "I have a plan already" stay as quick paths.
2. **A spec is on by default, and skippable.**
   - After a brainstorm: always.
   - After "I'll describe it": a **Write a spec first** checkbox, ticked by
     default.
   - A pasted plan: never.
3. **One Drafter and one Reviewer** write and check both the spec and the
   plan. After a brainstorm, the Drafter defaults to the agent that wrote the
   final synthesis.
4. **The relay commits automatically** once a task is approved: the task's
   files only, with a message from the task id and the implementer's
   summary.
5. **A Release role, defaulting to "you".** Release tasks pause the relay
   with a checklist until the user types `done` (or `skip`). If an agent is
   chosen, the ready check warns when its sandbox can't push, tag or reach
   the network.

Architecture: the **engine** (whyline-relay) gets the spec pipeline, plan
from a spec, the automatic committer and release pauses. The **console**
gets the screens. The user works only in the console; the same engine steps
can also be called from a terminal.

## Design

### 1. The flow

```
start / run ─▶ "Existing plan" ───────────────────────────────▶ Roles ─▶ Check ─▶ Start
           └▶ "Create a new plan"
                ├─ Brainstorm (default): models · passes · timeout · final write-up
                │     └▶ Synthesis review: approve / change / answer open questions
                │           └▶ Spec (Drafter writes, Reviewer checks) ─▶ your review
                ├─ "I'll describe it": [✓ Write a spec first]
                │     ├─ ticked ─▶ Spec ─▶ your review
                │     └─ unticked ─────────────────────┐
                │                                       ▼
                └─ "I have a plan already" (paste) ─▶ Plan (from the spec, or the description) ─▶ your review
```

- `start` with no `--plan` (typed, or the Start button with no plan
  selected) begins this flow, exactly like `run`. `start --plan <file>`
  still starts directly.
- **Brainstorm form.** The existing brainstorm fields (topic, models,
  review passes, final write-up, per-agent timeout) plus attachments from
  the attachments work. The Drafter and Reviewer dropdowns appear here, so
  the whole path is chosen once. The quick paths are links under the form:
  **I'll describe it** opens the description form (description,
  attachments, Drafter, Reviewer, the spec checkbox), and **I have a plan
  already** opens paste.

### 2. Synthesis review (console)

When the brainstorm finishes, the main window shows its `## Final
Synthesis`: the first 40 lines, then **View full** for the rest. The console
enters the **synthesis review** state, alongside the existing "plan review"
and "answering" states:

- `approve` (typed, or the **Approve** button) moves on to the spec step.
- Any other text is a change request. The final-synthesis agent revises the
  `## Final Synthesis` section with that feedback, through
  `brainstorm.revise_synthesis(...)` (new, below), and the review repeats.
- Items under `## Open questions` in the synthesis are shown as numbered
  questions first, and answering them is the same as a change request whose
  text is the questions and answers.
- **Discard** leaves the flow. The brainstorm document stays, as it does
  today.

### 3. The spec pipeline (relay: `whyline_relay.specs`)

This mirrors `planner`, with its own files so a spec and a plan can be in
progress at the same time:

- Draft file: `.whyline/relay/draft-spec.md`. Checkpoint:
  `.whyline/relay/spec-state.json`. Both are added to `RELAY_IGNORE`.
- Task id `__spec__`. Stages: `draft` (role Drafter, prompt `spec-draft`)
  and `review` (role Reviewer, prompt `spec-review`, outcomes `approved`,
  `revise` and `blocked`). Agents come from `[planner] draft/review`.
- API (same shapes as `planner`):
  - `draft(root, settings, request, *, attachments=(), print_fn=None)
    -> Path`. `request` is the brainstorm document path or the description
    text, with a `kind` of `brainstorm` or `description`.
  - `revise`, `resume_draft`, `answer`, `discard`, `pending_description`.
  - `approve(root, draft_path, *, name, replace=False) -> Path` writes
    `docs/specs/<slug>.md` and commits only that file (`docs: add spec
    <slug>`).
  - `SpecQuestions(loop.Paused)`, raised for a `blocked` handoff with
    questions, exactly like `PlanQuestions`.
- **`spec-draft` prompt.** Write a design spec with these sections: Why,
  Decisions (anything already decided), Design (numbered sections), Error
  handling, Testing, Releases. Base it on the brainstorm's Final Synthesis
  (or the description) and on any attachments. Prefer recommending to
  listing options. Put choices inside questions ("(a) … (b) …") and ask only
  about what the inputs don't settle.
- **`spec-review` prompt.** Check that the spec is complete, internally
  consistent, free of placeholders, and specific enough to plan from. Don't
  judge whether it is the right product; that is the human's call.
- **Console.** A spec job runs in the main window like the plan job:
  `spec · …` progress lines, then the **spec review** state with Approve /
  View spec / Discard, typed `approve` or changes, and questions. Approving
  commits the spec and moves straight on to the plan step.

### 4. Plan from a spec (relay)

- `planner.draft(..., spec: Path | None = None)` passes the approved spec as
  the description's main input ("Write the plan from this spec: <path>.
  Read it in full first.").
- The `plan-draft` prompt adds a rule: tasks that release, publish, tag or
  deploy must include the line `relay-profile: release` in their detail.
  The plan reviewer checks that this was done.
- The plan's marker line gains `| spec: docs/specs/<slug>.md` when it came
  from a spec. `relay_ops.list_plans` shows it, and Set up's plan dropdown
  labels the plan "from spec".
- After a brainstorm, the plan path is always brainstorm, then spec, then
  plan. `generate_plan_from_synthesis` stays for compatibility but is no
  longer used by Run.

### 5. Automatic committer (relay)

- In every config format, the reviewer's prompt says "approve; do not
  commit; whyline commits". The older two-role `review` template changes;
  the pipeline format already says this.
- After a stage outcome resolves to `@complete`, the loop commits with
  `gitcheck.commit_paths(root, changed, message)`:
  - `changed` is the task's files: the files in the implementer's handoff
    `--file` list, plus any other files the working tree shows as changed
    since the task's base commit, so nothing is silently left out.
  - The `.whyline/` runtime files stay ignored, as today.
- The message is `<type>: <summary> (<TASK-ID>)`. `<type>` is `feat`, or
  `fix` / `docs` / `test` / `chore` when the task title starts with that
  word. `<summary>` is the implementer's handoff summary, first sentence,
  at most 72 characters.
- If nothing changed, the task is still ticked, with the commit `chore:
  <TASK-ID> needed no changes`.
- The "commit naming the task" check that ticks the plan keeps working,
  because the message contains `(<TASK-ID>)`.
- The Roles step shows **Committer: whyline (automatic)**, read-only.

### 6. Release tasks (relay and console)

- **Config.** `[roles] release = "human"` is the default and is written by
  Set up. It may name an agent instead.
- **Relay loop.** Before looking up a task's profile in `[pipeline]`, a task
  with `relay-profile: release` is handled specially, so `release` never
  needs a pipeline profile:
  - **release = human:** the relay saves state and **pauses** with the
    reason `release task for you: <TASK-ID>`. The task text is kept as a
    checklist, one item per detail line or bullet.
  - **release = an agent:** the task runs through the normal stages, with
    that agent as the implementer and no tester stage.
- **New commands:**
  - `whyline relay done <TASK-ID>` ticks the task in the plan, commits the
    plan (`chore: release task <TASK-ID> done by hand`), clears the pause,
    and resumes the run in the same process.
  - `whyline relay skip <TASK-ID>` resumes without ticking it; the relay
    moves to the next task.
  - `whyline relay resume` on a release pause prints "This is a release task
    for you: run `whyline relay done <TASK-ID>` when it's done".
- **Ready check.** With an agent as the release role, preflight tries
  `git ls-remote origin` and checks that tags can be written
  (`git tag --list`, plus a write test on `.git/refs/tags` with the agent's
  sandbox, if the adapter can describe its sandbox). It warns, rather than
  fails, when either is blocked: "codex's sandbox blocks network access and
  tag writes; release tasks will likely fail". Codex `workspace-write` is
  known to block both.
- **Console.** A release pause shows in the main window as:

  ```
  ⏸ RPF-17 is a release task for you:
     1. Bump the version to 0.3.35 …
     2. Tag v0.3.35 and push …
  Type "done" when finished, or "skip".
  ```

  The console enters the **release** state: `done` runs `whyline relay done
  RPF-17` and `skip` runs `whyline relay skip RPF-17`. The Resume button's
  label becomes **Release done…**.

### 7. Roles step (console)

Guided Set up shows:
- Implementer, Tester, Reviewer (as today);
- **Committer: whyline (automatic)**, read-only;
- **Release:** "you" (the default) or any installed agent;
- **Backup** (per repo, as today).

The "what it means" line adds: "… codex reviews; whyline commits; you do
the release steps."

## Error handling

- **A spec or synthesis job fails** (agent missing, timeout): the same
  error line and kept checkpoint as the plan job. Plan → Resume draft also
  resumes a pending spec, and the popup says which kind of draft is
  pending.
- **`done` for a task that isn't the paused release task:** refused, naming
  the paused one.
- **The plan file changed during a release pause** (the user edited it):
  `done` re-reads the plan and ticks by task id. A task id that no longer
  exists is refused.
- **An automatic commit fails** (for example a pre-commit hook rejects it):
  the relay pauses with git's message. The task stays unticked, and Resume
  retries the commit before running anything else.

## Testing

Relay (pytest, fake agents):
- the spec pipeline: draft → review → approve writes and commits only
  `docs/specs/<slug>.md`; questions raise `SpecQuestions`; `answer` re-runs
  the asking stage; a spec and a plan checkpoint can both exist;
- plan from a spec: the prompt names the spec path, and the marker records
  `spec:`;
- the release profile is marked by the drafter prompt rule (text check),
  and a `relay-profile: release` task with `release = "human"` pauses
  without a pipeline profile named `release`;
- `done` ticks, commits only the plan, and resumes; `skip` resumes without
  ticking; `done` for the wrong task is refused;
- the automatic committer: only the task's files, the message format,
  "needed no changes", a failing commit pausing and being retried on resume;
- old two-role configs no longer tell the reviewer to commit;
- the release-agent ready check warns (with `git ls-remote` stubbed to
  fail).

Console (pilot, stubbed relay):
- `start` with no plan begins the flow;
- the brainstorm form is the default, and its quick paths open the
  description form and paste;
- synthesis review: approve leads to the spec job, a change request calls
  `revise_synthesis`, open questions are numbered;
- spec review: approve commits and starts the plan job; unticking "Write a
  spec first" skips the spec;
- the Roles step shows Committer (read-only) and Release;
- the release state: the checklist is shown, `done` and `skip` call the
  relay, and the Resume label changes;
- everything fits 80 columns, and tests don't depend on installed agent
  CLIs.

## Releases

1. whyline-relay 0.2.31: `specs`, plan from a spec, the drafter
   release-marking rule, the automatic committer, release pauses with
   `done`/`skip`, the release-agent ready check, and
   `brainstorm.revise_synthesis`.
2. whyline 0.3.34: the console flow. Agents mode moves to 0.3.35 (Phase 1)
   and 0.3.36 (Phase 2).
