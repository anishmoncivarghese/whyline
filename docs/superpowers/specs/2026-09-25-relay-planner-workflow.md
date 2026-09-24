# whyline-relay: the planner workflow

Status: design, awaiting the owner's review. Written 2026-09-25.
Relates to: `2026-09-23-relay-n-roles-design.md` (the N-roles design), whose section 2 named this
piece "planner" (roadmap E), explicitly deferred it, and settled two things about it in advance:
it is **not** a per-task pipeline stage — it produces `plan.md`, which the per-task engine that
design built then consumes — and it reuses that design's `Role`/`Stage`/`Profile`/`Pipeline`
engine (`pipeline.py`) as a separate, outer workflow. This document is that separate workflow,
scoped and designed for the first time.

## 1. Summary

Today, turning a feature idea into a `plan.md` the relay can run is entirely manual: the owner
writes it by hand, following `whyline-relay plan-format`'s documentation of the expected shape.
This design adds `whyline-relay plan "<description>"`, which drafts a `plan.md` from a free-text
description using an agent, runs an automatic structural check before ever showing it to a human,
and then asks the owner to approve, request changes, or discard — offering to start the real run
immediately once they approve. It reuses `pipeline.py`'s existing engine for the draft↔review loop
and the existing crash-safe-checkpoint idiom (`state.py`) for a new, separate resumable state.

## 2. Goals and non-goals

Goals

- `whyline-relay plan "<description>"` drives an unattended draft→structural-review loop (an
  agent drafts, a second agent checks structure only) and stops for a human once it converges.
- The structural check is narrow and mechanical in spirit — reuses/extends the same checks
  `preflight._plan_checks` already applies to a hand-written plan (parses, has an id, has detail,
  no placeholder text) — never a judgment call about whether the plan is strategically *right*.
- The human decides content: approve (write `plan.md` for real), request changes with feedback
  (redraft, unbounded — a human iterating is their own call, not a runaway loop), or discard.
- On approval, offer to start `whyline-relay start` immediately, without a separate manual step.
- `[planner]` defaults to the existing `[roles]` implementer/reviewer agents when not configured,
  so a repo that never touches the new config table still gets a working `plan` command.
- Crash-safe resume: an interrupted draft/review loop, or a crash at the human gate itself, is
  recoverable via `whyline-relay resume` the same way a paused per-task run already is.

Non-goals

- **Consuming or modifying an existing `plan.md`.** `plan` always starts a fresh draft from a
  description; editing or extending an already-approved plan is future scope, not this piece.
- **Any judgment about the plan's correctness beyond structure.** Whether the drafted tasks are
  the *right* tasks is entirely the human's call at the approval gate — never automated.
  Rejection never autonomously reaches back into the draft loop from a human's silence; only an
  explicit human "request changes" (with feedback) or the automated structural reviewer re-drafts.
- **Editing the draft in place.** The approval gate is approve / request-changes-with-feedback /
  discard — there is no "open an editor on the draft" flow. A human who wants to hand-edit can
  edit the staging file directly and is told where it lives.
- **Multiple concurrent planning sessions.** Exactly one plan draft can be in flight per repo,
  same restriction `start`/`resume` already apply to a running task.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| P1 | Input is a single free-text description, given as a CLI argument | Simplest possible entry point; no new file format to teach before the plan format itself exists |
| P2 | Modeled as a literal two-stage `Pipeline` (`draft`, `review`) built from `pipeline.py`'s existing `Role`/`Stage`/`Profile`/`Pipeline` dataclasses, driven by a new, separate `planner.py` runner loop — not folded into `_run_configured_task` | Reuses the routing/decision engine the N-roles design already built and proved, without contorting the per-task loop (which ticks `plan.md`, checks git HEAD, and commits) to also cover a workflow that does none of those things |
| P3 | The structural check is a real agent turn (default: the `reviewer` role's agent), not pure relay-side code | Matches the earlier-agreed design: "an agent (reusing the reviewer role) checks the draft plan for structural problems" — keeps the auto-review consistent with every other agent-filled stage in this project rather than inventing a second class of check |
| P4 | Draft/review stages never touch git: no commit, no HEAD-equality check, no `plan.md` tick | Nothing worth committing exists until the human approves; the real `plan.md` is written exactly once, at approval, by the relay itself |
| P5 | The auto-review loop is bounded by `[planner].max_visits` (default 3); a human's own "request changes" round is not bounded at all | `max_visits` exists to catch *unattended* runaway looping between two agents; a human explicitly choosing to iterate again is not that failure mode |
| P6 | The human gate has three outcomes — approve / request-changes-with-feedback / discard — mirroring the shape every other approval point in this project already uses, not a bare yes/no | Consistency: "request changes" feeding text back into the next draft is exactly how `changes-requested` already works between implementer and reviewer |
| P7 | On approval, ask "Start whyline-relay on this plan now? [y/N]" (default no) before writing anything beyond `plan.md` itself | The owner explicitly asked for this over the simpler "write and stop" option; default-no because starting an unattended run is a bigger commitment than approving a plan draft |
| P8 | Crash-safe resume reuses the existing atomic-checkpoint idiom (`state.py`'s save/load/clear-before-launch pattern) but through a **new, separate** `PlanState` dataclass and file (`plan-state.json`), not by overloading `RelayState` | `RelayState`'s fields (`branch`, `base_commit`, `plan`, `task_id`) are all task/git-shaped and meaningless before a plan is approved; forcing them to carry empty/dummy values for a planning session is worse than a second small, honestly-shaped state file |
| P9 | The `@complete` checkpoint-before-asking pattern already shipped for the per-task engine (0.2.9) is reused as-is: reaching structural approval is checkpointed *before* the human is asked anything | A crash exactly at the human gate then just re-shows the same draft on resume, without repeating any agent turn — same proven shape, not a new one |
| P10 | Planner handoffs use a fixed, reserved whyline task id, `__plan__` | Only one plan session is ever in flight per repo (goal, non-goals section), so a fixed id is sufficient; the double-underscore shape matches this project's existing reserved-token convention (`@next`/`@complete`/`@blocked`) and preflight can warn if a real plan task ever collides with it |

## 4. Where this sits relative to today's code (measured, relay 0.2.12)

| File | Today | What changes |
|---|---|---|
| `pipeline.py` | `Role`, `Stage`, `Profile`, `Pipeline`, `Decision` dataclasses; `compile_legacy()`; not yet wired into anything but `routing.py` | **Unchanged.** The planner compiles its own `Pipeline` value from `[planner]` config using these same dataclasses; no new fields needed — `draft`/`review`'s `transitions` and `max_visits` already say everything required |
| `state.py` | `RelayState` + `path`/`save`/`load`/`clear`, one file (`state.json`) shaped around a running task | Gains a second, independent dataclass `PlanState` (`description`, `stage`, `round`, `agent`, `feedback`, `draft_path`, `paused_reason`, `log_path`) and its own `plan_path`/`save_plan`/`load_plan`/`clear_plan`, at `.whyline/relay/plan-state.json`, using the identical atomic-write technique (write `.tmp`, `os.replace`) |
| `prompts.py` | `TEMPLATES = {"implement", "review", "test", "security"}`; `stage_footer()` generic over any `Stage`/`Pipeline` | Gains two new built-in templates, `"plan-draft"` and `"plan-review"`, added to `TEMPLATES`. `stage_footer()` itself needs **no change** — it already only depends on `Stage`/`Pipeline`/`profile_name`/`effective_agents`/`actor`/`task_id`, all of which the planner's compiled `Pipeline` and `"__plan__"` task id supply directly |
| `preflight.py` | `_plan_checks(plan_path, pipeline=None) -> list[Check]`, called against a hand-written `plan.md` before `start`/`resume` | **Unchanged as the planner's gate** — the planner's review stage prompt instructs the reviewing agent to apply the same criteria this function already checks (parses, has an id, has detail, no placeholder text); the relay does not call `_plan_checks` itself as a gate — see 5.2 for why the check stays agent-driven, not code-driven. Gains one small, unrelated addition of its own (5.6): a `warn` if a real plan task's id collides with the reserved `__plan__` id (P10) |
| `loop.py` | `_run_configured_task` (task/git-shaped orchestration loop), `_run_agent` (render prompt, run agent, return log path — confirmed by inspection to contain no git logic of its own; the surrounding HEAD-equality check lives in `_run_configured_task`'s own loop, not inside `_run_agent`) | **Unchanged.** New, separate `planner.py` owns the draft/review loop, calling `_run_agent` **directly** with a synthetic `plan.Task(task_id="__plan__", text=description, checked=False, line_index=0)` — confirmed viable since `_run_agent` takes exactly that type and does not itself assume anything about commits. `planner.py`'s own loop simply omits the HEAD-check block `_run_configured_task` wraps around its call (P4) |
| `cli.py` | `start`, `resume`, `roles {status,set,reset}`, `plan-format` | Gains `plan "<description>"` and `plan --discard`; `cmd_resume` gains a branch at its top: if `state.load_plan(root)` finds a `PlanState`, dispatch to `planner.resume()` before falling through to the existing task-resume path |
| `config.py` | `[roles]`, `[roles.backup]`, `[pipeline]` (+ `.profiles`, `.stages.*`) | Gains an optional `[planner]` table (`draft`, `review`, `max_visits`); omitted entirely, `draft`/`review` default to `settings.roles.implementer`/`settings.roles.reviewer` (or, for a configured `[pipeline]`, to `current_roles(settings)`'s first and last entries — see 5.1) |
| `gitcheck.py` | `RELAY_IGNORE`, a **specific-filename** tuple (`state.json*`, `logs/`, `STOP`, `running.json`, `active-roles.json`) written to `.git/info/exclude` by `ensure_relay_ignored` — not a directory wildcard | Gains two more literal entries, `.whyline/relay/plan-state.json*` and `.whyline/relay/draft-plan.md`, confirmed necessary by inspection: `state.json*` does not match a differently-named file, so without this, `git add -A` (run by the terminal stage or the relay's own commit) would sweep the draft and its checkpoint into a real commit |

## 5. Design

### 5.1 Configuration and compilation

```toml
[planner]
draft = "codex"     # defaults to the implementer role's agent if omitted
review = "claude"   # defaults to the reviewer role's agent if omitted
max_visits = 3       # bounds only the draft<->review auto loop (P5)
```

Compiled once per invocation into a real `pipeline.Pipeline`:

```python
Pipeline(
    roles={
        "draft": Role(name="draft", agent=draft_agent),
        "review": Role(name="review", agent=review_agent),
    },
    stages={
        "draft": Stage(
            id="draft", role="draft", prompt="plan-draft",
            transitions={"ready": "@next"}, max_visits=max_visits,
        ),
        "review": Stage(
            id="review", role="review", prompt="plan-review",
            transitions={"approved": "@complete", "revise": "draft"},
            max_visits=max_visits,
        ),
    },
    profiles={"default": Profile(name="default", stages=("draft", "review"))},
    default_profile="default",
)
```

When `[planner]` is absent, `draft`/`review` default to `roles.current_roles(settings)` — for a
legacy two-role config, that is `implementer`/`reviewer` directly; for a configured `[pipeline]`,
the same "first configured role, last configured role" convention `init`'s wizard already applies
nowhere else needs inventing, since `current_roles()` (shipped 0.2.11) already exists precisely to
answer "which roles exist right now" for exactly this kind of generic, config-shape-agnostic code.

### 5.2 The draft and review stages

**Draft**: the `plan-draft` prompt receives the free-text description (first round) or the
description plus the reviewing agent's or human's feedback (later rounds). It writes a candidate
plan to a staging file, `.whyline/relay/draft-plan.md` — never the real `plan.md` — so an existing
plan is never at risk and a discarded draft leaves nothing behind. It hands off `ready`.

**Review**: the `plan-review` prompt is deliberately narrow. It instructs the agent to check
*only* what `preflight._plan_checks` already mechanically checks for a hand-written plan — the
file parses via the documented format, every task has a unique, present id, every task has real
detail lines, nothing reads as placeholder text ("TBD", "fill in", etc.) — and explicitly *not* to
judge whether the plan is the right plan for the goal. This stays an agent turn rather than a
direct call to `_plan_checks` (P3) so the reviewing agent can also catch shape problems `_plan_checks`
doesn't encode as rules (a task description that doesn't parse as a coherent unit of work, though
it technically has an id and detail lines) — the same reason a human reviewer adds value beyond a
linter. Two outcomes: `approved` → `@complete`; `revise` → back to `draft` with the reviewer's
concrete feedback, bounded by `max_visits` (P5).

Both stages are launched via `loop._run_agent` directly (4, `loop.py` row), each turn claimed first
via `whylinecmd.claim(root, "__plan__", agent, stage.role)` — the same advisory-ownership call
`_run_configured_task` makes at the start of a task, reused here unmodified since it only takes a
task id, actor, and role.

Both stages get the existing `stage_footer()` unchanged (4, `prompts.py` row) — its "never commit"
line is simply true here too (P4), and its "the task is finished" `@complete` framing reads
correctly as "the draft passed structural review," addressed to `"__plan__"` (P10).

### 5.3 Crash-safe resume

```python
@dataclass(frozen=True)
class PlanState:
    description: str
    stage: str            # "draft" | "review" | "@complete"
    round: int
    agent: str
    feedback: str          # accumulated reviewer/human feedback for the next draft, if any
    draft_path: str
    paused_reason: str
    log_path: str
```

Stored at `.whyline/relay/plan-state.json`, via `state.save_plan`/`load_plan`/`clear_plan`, using
the same write-`.tmp`-then-`os.replace` atomic technique `state.py` already uses for `RelayState`
(P8) — a half-written checkpoint can never strand a resume, for the same reason it can't today.
The relay checkpoints the target stage before launching the next agent, exactly like the per-task
engine (spec `2026-09-23-relay-n-roles-design.md` 5.4): a crash before that save re-enters the same
turn; a crash after it does not repeat a turn that already happened.

`stage: "@complete"` is written the moment the review stage approves — **before** the human is
asked anything (P9). If the process dies at "Use this plan?", `whyline-relay resume` sees a
`PlanState` with `stage == "@complete"`, re-prints the same draft, and re-asks the same question,
without re-running any agent. Once the human answers (approve or discard), `clear_plan` removes
the checkpoint; "request changes" instead writes a fresh `PlanState` back at `stage: "draft"` with
the human's feedback folded in and `round` reset to 0, since a human-initiated redraft is a new
top-level attempt, not a continuation of the bounded auto-loop (P5).

`cmd_resume` gains a check at its top, before its existing `state.load(root)` task-resume path:

```python
plan_state = state.load_plan(root)
if plan_state is not None:
    return planner.resume(root, settings, plan_state)
```

### 5.4 The human approval gate

Presented once the inner pipeline reaches `@complete` (structurally approved, not yet a human
decision):

1. Print the full contents of `.whyline/relay/draft-plan.md`.
2. Ask: **"Approve, [r]equest changes, or [d]iscard? [A/r/d]"**
   - **Approve**: copy the staging file to the real `plan.md` (refusing, same as `init`'s
     overwrite guard elsewhere, if one already exists and the human hasn't confirmed replacing
     it), then commit it as its own small commit. This step is not optional: `start`'s existing
     dirty-tree guard (`gitcheck.is_dirty`) would otherwise refuse the very run P7 is about to
     offer, since an uncommitted `plan.md` makes the tree dirty. Then `clear_plan`, and ask
     **"Start whyline-relay on this plan now? [y/N]"** — a yes calls directly into the existing
     `start` machinery (P7); a no leaves `plan.md` written and committed, and stops, printing the
     ordinary `whyline-relay start` command to run later.
   - **Request changes**: prompt for free-text feedback, fold it into a fresh `PlanState` at
     `stage: "draft"` (P6), and re-enter the loop — unbounded, since a human is directly driving
     it (P5).
   - **Discard**: `clear_plan`, leave the staging file on disk, print its path in case the human
     wants to salvage anything from it by hand, and exit cleanly.

### 5.5 CLI surface

- `whyline-relay plan "<description>"` — starts a new session. Refuses, pointing at `resume`, if
  `plan-state.json` already exists (mirrors `start`'s existing "another relay is running here" /
  "nothing to resume" family of guards).
- `whyline-relay resume` — unchanged entry point; now checks for a `PlanState` first (5.3).
- `whyline-relay plan --discard` — clears an in-flight `PlanState` without resuming or asking
  anything, for a human who decided mid-way they don't want to continue and don't want `resume`
  to keep prompting them about it.

### 5.6 Error handling and edge cases

- **`max_visits` exhausted without structural approval** → the loop ends in `@blocked`, the same
  terminal shape `pipeline.py` already defines. The relay shows the human the last draft and the
  reviewer's final structural complaint at the same gate described in 5.4, with "approve" there
  meaning "accept it despite the flagged structural issue" — a human's informed override, not a
  silent failure.
- **Malformed or missing draft output** (the staging file was never written, or doesn't parse) is
  treated as an automatic `revise` outcome carrying "no valid plan file was produced" as feedback;
  it counts against `max_visits` exactly like any other structural rejection.
- **A `plan.md` already exists when the human approves** — refuse to overwrite silently; ask for
  confirmation the same way `init --overwrite` already gates replacing `config.toml`.
- **A real plan task ever uses the id `__plan__`** — `preflight._plan_checks` gains a `warn`
  (not `FAIL`, to stay additive and non-breaking) flagging the collision, since P10 relies on that
  id staying free for the planner's own handoffs.

## 6. Build order

One phase — this is scoped tightly enough (a single new CLI command, one new small module, one
new config table, two new prompts) not to need splitting the way the N-roles design's six phases
did. Regression net: the entire existing suite and every existing acceptance suite pass unedited,
since nothing here touches `loop.py`, `routing.py`, or `RelayState`.

## 7. Risks and open questions

- **The structural review staying "agent-driven, not code-driven" (5.2, P3) is the least proven
  part of this design.** It relies on the reviewing agent actually restricting itself to structure
  and not drifting into content judgment despite the prompt's instruction — this needs real
  acceptance testing with a deliberately-bad-content-but-structurally-fine draft, confirming the
  reviewer approves it rather than second-guessing the plan's substance.
- **The human-driven "request changes" loop being unbounded (P5)** trusts a human to eventually
  stop; there is no fallback if a scripted caller drives `plan` non-interactively in a loop. Not a
  concern for the interactive CLI this is designed for, but worth noting if `plan` ever grows a
  non-interactive/`--yes` mode later.
- **Reusing `stage_footer()` unchanged (5.2) is confirmed by inspection, not yet by a real run** —
  its only planner-specific claim ("the task is finished" on `@complete`) needs to actually read
  sensibly to the reviewing agent in context; this is exactly the kind of thing empirical
  scratch-verification (this project's established practice) checks before a line of the
  implementation plan is written.

## 8. Roadmap update

This completes roadmap piece "E" (planner), the last deferred piece named in
`2026-09-23-relay-n-roles-design.md`'s section 8. Remaining deferred pieces from that document are
unchanged by this design: **D** (subscription-aware setup) and **C** (first-run interactive setup
beyond what that design's 5.10 covers) stay separate, harder, and unscoped.

## 9. Decision log (this design session, 2026-09-25)

| Question | Answer |
|---|---|
| Planner input shape? | A single free-text description (owner's choice) |
| Auto-review's job? | Structure only, via an agent turn reusing/extending `_plan_checks`'s criteria — never plan content or strategy (owner's choice) |
| What happens right after human approval? | Offer to start the real run immediately, not just write-and-stop (owner's explicit choice, over the simpler recommended option) |
| `[planner]` defaults? | The existing implementer/reviewer agents, via `roles.current_roles()` (owner's choice) |
| Model the draft/review loop as its own `Pipeline`, or something simpler? | A literal two-stage `Pipeline` via the existing `pipeline.py` engine, driven by a new, separate `planner.py` loop |
| Does the human gate get a bare yes/no, or something richer? | The same three-outcome shape (approve / request-changes / discard) already used everywhere else in this project |
| Is a human's "request changes" round bounded like the auto-loop is? | No — `max_visits` only bounds unattended agent-to-agent looping |
| Does the planner's crash-safety reuse `RelayState` directly, or a new shape? | A new, separate `PlanState`/`plan-state.json`, sharing the same atomic-checkpoint technique but not the same fields, since none of `RelayState`'s task/git fields apply before a plan is approved |
| Does the planner ever touch git before human approval? | No — no commit, no HEAD check, no plan.md tick, until the relay writes the real `plan.md` itself at approval |
