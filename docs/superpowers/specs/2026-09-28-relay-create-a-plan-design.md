# Relay "Create a Plan" via Brainstorming Design

**Status:** Approved by user, section-by-section, 2026-09-28.

## Goal

`whyline-relay setup` gains a third plan-source choice, "brainstorm," that
runs the existing multi-model brainstorm engine and turns its final
synthesis into a real, checkbox-formatted `plan.md` -- validated, human-
approved, and ready for `whyline-relay start` -- and the role wizard gains a
backup-chain question, now meaningful since the backup chain (BC-1..BC-7,
0.2.21) shipped.

## Context

Piece A, deferred from the chat-brainstorm design and explicitly sequenced
after pipeline backup/failover (piece B, now shipped as the backup chain).
The user's own original request: "relay start with a plan or create a
plan. In create a plan we call in the brainstorming, and the final model
then creates the plan and test which can run in whyline run and user have
to select the model for implementer, tester, reviewer, and back up." The
"test" stage and implementer/tester/reviewer selection already exist in
`run_role_wizard`/the fixed 3-stage pipeline template -- only the
brainstorm-to-plan path and the backup question are new.

## Non-goals

- **Changing the simple 2-agent draft flow (`planner.py`).** It stays
  exactly as it is, as a separate, faster option alongside brainstorming --
  this is purely additive.
- **Cross-invocation resume for the brainstorm-to-plan flow.** The
  underlying brainstorm phases already degrade gracefully within one
  session (B7); this spec does not add `PlanState`-style crash-resume
  checkpointing to that path. A crash mid-flow means starting the
  "brainstorm" choice over, same as any other single-session wizard step
  in `setup.py` today.
- **Per-role backup selection.** The backup chain (BC) is deliberately one
  shared chain for the whole pipeline, not per-role -- the new wizard
  question reflects that shape exactly, asking once, not per role.
- **Validating the backup agent name inline at the wizard prompt.** Matches
  how implementer/tester/reviewer already work: no inline check, surfaced
  later at the existing `doctor` gate in the same `setup run` flow.

## Decisions

- **RCP1 -- A third `choose_plan_source` choice, purely additive.** "Use
  the existing plan, draft a new one, or brainstorm one? [existing]:" (the
  default logic -- existing if `plan.md` exists, else draft -- is
  unchanged; brainstorm is never the default, always explicit). Choosing
  "brainstorm" calls the existing `ask_brainstorm_setup` (topic, models,
  passes, final model) unchanged, then runs the existing pass-0/merge/
  review-passes/final-synthesis phases unchanged.
- **RCP2 -- One new function, `generate_plan_from_synthesis`, reusing
  `chat.run_turn` unchanged.** After final synthesis, one more turn to the
  *same* final-synthesis agent: "read `docs/brainstorm/<slug>.md`'s Final
  Synthesis section and write a real plan.md (checkbox format: `- [ ]
  TASK-ID: description`, indented detail lines below each, one task per
  independently implementable and testable step) at `<temp draft path>`."
  Writes to a temp draft location (`config.relay_dir(root) /
  "brainstorm-plan-draft.md"`, mirroring the planner's own `draft-plan.md`
  convention), never straight to the real `plan.md`.
- **RCP3 -- Immediate validation with a bounded retry, reusing `plan.parse`
  unchanged.** The temp draft is parsed immediately after the agent writes
  it. A `plan.PlanError` triggers one more `generate_plan_from_synthesis`
  call to the same agent with the exact error text appended to the prompt;
  after a small, fixed retry budget (2 total attempts) still failing, the
  human is told plainly and the malformed draft is left at its temp path
  for manual inspection or hand-editing -- never silently discarded.
- **RCP4 -- The existing human gate is generalized, not duplicated.**
  Today's `_human_gate` (in `planner.py`) hardcodes `draft_path(root)` and
  calls `_run_pipeline` on "revise," plus planner-specific checkpoint
  clearing. It becomes a shared helper parameterized by `draft_path` and a
  `revise_fn` callback: the planner's own call site passes its existing
  `_run_pipeline`-based revise behavior (unchanged results for existing
  tests); the new brainstorm call site passes a revise behavior that calls
  `generate_plan_from_synthesis` again with the human's typed feedback
  folded into the prompt -- never re-running the expensive research/review
  passes just to revise a plan. Approve/discard behavior (write to the real
  `plan.md`, commit, offer to start) is identical for both call sites.
- **RCP5 -- `run_role_wizard` gains a fourth, optional question.** "Backup
  chain (comma-separated, blank for none): ", comma-split and whitespace-
  trimmed, written as `[backup]\nchain = [...]\n` appended to config.toml
  only when non-empty -- a blank answer writes nothing, since no `[backup]`
  table is already the valid, existing "no backup" default. Asked once, not
  per role, matching the backup chain's own single-shared-chain shape.
- **RCP6 -- An empty-synthesis guard before ever generating a plan.** If
  every selected model failed pass-0 (the shared brainstorm doc ends up
  empty or missing), plan generation is refused outright with a clear
  message -- no temp draft is ever written from nothing to synthesize.

## Architecture

```
whyline-relay setup
  │
  choose_plan_source: "existing" | "draft" | "brainstorm" (RCP1)
  │
  ├─ "draft"  -> planner.start() (unchanged)
  │
  └─ "brainstorm":
       ask_brainstorm_setup()                        (existing, unchanged)
       run_pass_zero() -> merge_pass_zero()           (existing, unchanged)
       run_review_pass() x N                          (existing, unchanged)
       run_final_synthesis()                          (existing, unchanged)
       │
       if shared doc is empty: refuse, tell human (RCP6)
       │
       generate_plan_from_synthesis()                 (new, RCP2)
         -> writes brainstorm-plan-draft.md
         -> plan.parse() immediately; retry once on PlanError (RCP3)
       │
       shared human gate (generalized _human_gate, RCP4)
         approve -> write real plan.md, commit, offer to start
         revise  -> generate_plan_from_synthesis(feedback=...) again
         discard -> leave the draft, nothing committed
  │
  run_role_wizard(): implementer / tester / reviewer / backup chain (RCP5)
  │
  (rest of `setup run` unchanged: commit, doctor gate, offer to start)
```

## Error handling

- Every model failed pass-0: refused before any plan-generation turn runs,
  clear message, nothing written (RCP6).
- `generate_plan_from_synthesis` exhausts its retry budget: clear message,
  malformed draft left at its temp path, nothing committed.
- A bad backup agent name at the wizard: no inline check; surfaces at the
  existing `doctor` gate in the same `setup run` flow, same as a bad
  implementer/tester/reviewer name already does today.
- The plan-generation turn itself fails to run at all
  (`AgentMissing`/`AgentTimeout`/`chat.AgentUnavailable`, the same failure
  modes every other brainstorm phase already handles per B7): unlike a
  review pass, there is no "keep the previous content" fallback available
  here, since nothing has been generated yet -- the human is told plainly
  which error occurred and that no plan.md was written, with no retry
  consumed from RCP3's budget (a transport/availability failure is not the
  same thing as the agent producing malformed output).
- The generalized gate's "revise" path for brainstorm never re-runs
  research/review passes -- only one bounded extra plan-generation turn,
  keeping a revision cheap.
- A crash mid-brainstorm-to-plan flow: no cross-invocation resume (Non-
  goals); the user re-chooses "brainstorm" and starts that path over.

## Testing strategy

- `generate_plan_from_synthesis`: a valid plan.md accepted first try; a
  malformed one retried once with the exact parse error in the prompt and
  succeeds; a fully exhausted retry budget raises a clear error and leaves
  the draft in place.
- The generalized gate helper: the *existing* planner flow's
  approve/revise/discard tests must all still pass unchanged after the
  refactor; the new brainstorm path exercises the same three outcomes with
  a fake `run_fn`.
- `choose_plan_source`'s new "brainstorm" branch: the full path from
  wizard choice through to a written, human-approved plan.md, fake `run_fn`
  throughout, no real agent ever spawned.
- RCP6's empty-synthesis guard: an empty/missing shared doc refuses plan
  generation with a clear message rather than producing a nonsense plan.
- `run_role_wizard`: a non-empty backup answer writes `[backup].chain`
  correctly (comma-split, trimmed); a blank answer writes no `[backup]`
  table.
- End-to-end (once built): a real scratch-repo `whyline-relay setup` run
  choosing "brainstorm" with two fake agents and one review pass,
  confirming the resulting plan.md actually parses and `whyline-relay
  start` can run it -- the same empirical bar every feature this session
  has been held to before shipping.
