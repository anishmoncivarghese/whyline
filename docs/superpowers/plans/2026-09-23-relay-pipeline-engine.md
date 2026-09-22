# whyline-relay pipeline engine (relay 0.2.7) Implementation Plan

> **For agentic workers:** this plan is run by whyline-relay itself, on its own repository: Codex implements each task, Claude reviews and commits it. Each task is handed to a fresh agent with no memory of the others, so each one stands alone: the "Rules for every task" line under each title repeats the Global Constraints for that reason.

**Goal:** Introduce the `Role`/`Stage`/`Profile`/`Pipeline` engine from the N-roles design, and make `routing.decide()` a thin, behavior-preserving wrapper over it for today's fixed implementer/reviewer shape — with **zero changes to any other file**, proven by the fact that `loop.py`, `config.py`, and the entire existing test suite, including `test_routing.py` byte for byte, pass completely unedited.

**Architecture:** This is deliberately the narrowest possible slice of the N-roles design that is both real (wired into the live code path, not dead code) and safe (touches nothing else). `routing.decide()` today is genuinely stateless — it has never known or cared which agent's turn just ended, only `(status, to_actor)` — so the compiled two-role pipeline gives both of its stages the *same* transition table, which is what reproduces that statelessness exactly rather than accidentally changing it. Exposing `[pipeline]` in `config.toml`, stage-aware crash-safe resume, profiles, and relay-side commits are later phases in the design's own build order (section 6) and are explicitly **not** built here — this plan only proves the new engine and cuts the one existing call site over to it.

**Tech Stack:** Python 3.11+, standard library only, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-23-relay-n-roles-design.md`, sections 5.1 and 5.3, decisions D1-D3. This plan is build-order phase 1 from that design's section 6.

## Global Constraints

- No new dependencies. Do not touch `pyproject.toml`, `uv.lock`, or the version.
- The sandbox has no network: run tests with `uv run --frozen pytest -q`.
- `loop.py`, `config.py`, `cli.py`, `preflight.py`, `prompts.py`, and every other file not named in a task below must not change at all. `routing.py`'s public names (`IMPLEMENT`, `REVIEW`, `APPROVED`, `BLOCKED`, `NO_HANDOFF`, `UNKNOWN`, `IMPLEMENTER`, `REVIEWER`, and the `decide()` function's signature and return values) must not change.
- No existing test file may be edited. The entire existing suite, including `tests/test_routing.py` verbatim, is the regression net.
- The relay never passes a permission-bypass flag, never runs `git push`, and never writes a handoff on an agent's behalf.

## File structure

| File | Responsibility | Task |
|---|---|---|
| `src/whyline_relay/pipeline.py` (new) | `Role`, `Stage`, `Profile`, `Pipeline`, `Decision`, `compile_legacy`, `decide` | 1 |
| `tests/test_pipeline.py` (new) | Every existing routing scenario reproduced through the new engine, plus genuine 3-stage tests the old system could never express | 1 |
| `src/whyline_relay/routing.py` | Becomes a thin wrapper: compiles a legacy pipeline and delegates to `pipeline.decide()` | 2 |

## Not in this plan

`[pipeline]`/`[pipeline.profiles]`/`[pipeline.stages.*]` in `config.toml` (no config-level exposure yet — phases 3 and 6 in the design's build order), the persisted stage cursor and crash-safe resume (phase 2), profiles and the `relay-profile:` task directive (phase 3), the relay committing directly (phase 4), the tester/security-review stages and their prompts (phase 5), and `init`/`roles set` (phase 6). `Role.agent`/`Role.backup` exist as fields (matching the design's dataclass shape) but are not read by anything in this plan — `pipeline.decide()` takes the acting agent names as an explicit `effective_agents` argument, the same separation of "who fills a role" from "what the engine decides" that `failover.effective_agent` already keeps in `loop.py` today.

## How this is run and checked

1. Independent acceptance tests, written before the run, from this plan's requirements. Given this plan's entire regression net *is* the existing suite passing unedited, the acceptance suite for this round is smaller than usual and focuses on proving the wrapper is really wired in (not dead code) via the real CLI.
2. A sandbox clone of the relay (remotes removed) holds the tasks below as `plan.md`. `whyline-relay start` runs them.
3. After the run: the full existing suite (byte-for-byte unedited, most importantly `tests/test_routing.py`), the existing acceptance suites (unedited), the new acceptance tests, and tripwires confirming no real agent or `osascript` binary is ever invoked.
4. Cherry-pick into the real repository, release notes (written by hand, explicit that this ships no user-visible feature — it is the foundation the next several releases build on), pre-flight, then stop for an explicit go before pushing or tagging `v0.2.7`.

## Release

Relay **0.2.7**. whyline's pin (`whyline-relay>=0.2.1,<0.3`) already admits it.

---

## The tasks

Run order matters: task 2 depends on task 1's exact module existing.

- [ ] PIPE-1: the pipeline engine
  Rules for every task: run the tests with `uv run --frozen pytest -q` (there is no network). Add no dependencies and do not touch `pyproject.toml`, `uv.lock` or the version. Touch only the files this task names; every other file, and every existing test, must be unedited. Never pass or write a permission-bypass flag, never run `git push`, and never write a handoff on an agent's behalf.

  **Create** `src/whyline_relay/pipeline.py`:

  ```python
  """The Role/Stage/Profile engine: a pure, agent-independent state machine.

  routing.py's decide() is a thin, behavior-preserving wrapper over this module for
  today's fixed two-role shape (compile_legacy). Nothing here is wired into loop.py
  yet -- config.toml cannot configure a [pipeline] table, and no other module imports
  this one except routing.py.
  """

  from __future__ import annotations

  from dataclasses import dataclass

  from whyline_relay import handoff


  @dataclass(frozen=True)
  class Role:
      name: str
      agent: str
      backup: str | None = None


  @dataclass(frozen=True)
  class Stage:
      id: str
      role: str                      # a Role.name
      prompt: str                     # which prompt template to render
      transitions: dict[str, str]      # outcome name -> a Stage.id, "@complete", or "@blocked"
      max_visits: int = 3


  @dataclass(frozen=True)
  class Profile:
      name: str
      stages: tuple[str, ...]


  @dataclass(frozen=True)
  class Pipeline:
      roles: dict[str, Role]
      stages: dict[str, Stage]
      profiles: dict[str, Profile]
      default_profile: str
      legacy: bool = False


  @dataclass(frozen=True)
  class Decision:
      kind: str                # "advance" | "complete" | "blocked" | "no-handoff" | "unknown"
      target_stage: str | None


  def compile_legacy(status_map: dict[str, str]) -> Pipeline:
      """The pipeline today's fixed implementer/reviewer shape compiles to.

      One shared transition table on both stages reproduces routing.py's actual
      statelessness: today's decide() never knows or cares which agent's turn just
      ended, only (status, to_actor). Splitting this into two different per-stage
      tables would be a behavior change, not a refactor.
      """
      shared = {
          status_map["review"]: "review",
          status_map["changes"]: "implement",
          status_map["assigned"]: "implement",
          status_map["approved"]: "@complete",
          status_map["blocked"]: "@blocked",
      }
      return Pipeline(
          roles={
              "implementer": Role(name="implementer", agent=""),
              "reviewer": Role(name="reviewer", agent=""),
          },
          stages={
              "implement": Stage(
                  id="implement", role="implementer", prompt="implement",
                  transitions=dict(shared),
              ),
              "review": Stage(
                  id="review", role="reviewer", prompt="review",
                  transitions=dict(shared),
              ),
          },
          profiles={"default": Profile(name="default", stages=("implement", "review"))},
          default_profile="default",
          legacy=True,
      )


  def decide(
      record: handoff.Handoff | None,
      previous_id: str | None,
      pipeline: Pipeline,
      effective_agents: dict[str, str],
  ) -> Decision:
      """Pick the next move from the handoff record alone.

      Checks every stage's transitions for one that accepts this status;
      "@complete" and "@blocked" apply regardless of recipient (matching today's
      approved/blocked), a real stage target requires the handoff be addressed to
      whoever fills that stage's role. Never guesses: no match anywhere is
      "unknown", not a default.
      """
      if record is None or (previous_id is not None and record.event_id == previous_id):
          return Decision("no-handoff", None)
      for stage in pipeline.stages.values():
          target = stage.transitions.get(record.status)
          if target is None:
              continue
          if target == "@blocked":
              return Decision("blocked", None)
          if target == "@complete":
              return Decision("complete", None)
          target_stage = pipeline.stages[target]
          if record.to_actor == effective_agents.get(target_stage.role):
              return Decision("advance", target)
      return Decision("unknown", None)
  ```

  **Tests first**, new `tests/test_pipeline.py`:

  ```python
  from whyline_relay import config, handoff, pipeline

  STATUS = config.DEFAULTS["status_map"]


  def record(**fields) -> handoff.Handoff:
      base = {"event_id": "e2", "task": "WL-1", "to_actor": "claude", "status": "ready-for-review", "summary": ""}
      return handoff.Handoff(**{**base, **fields})


  LEGACY_AGENTS = {"implementer": "codex", "reviewer": "claude"}


  def test_no_handoff_when_record_is_none():
      compiled = pipeline.compile_legacy(STATUS)
      assert pipeline.decide(None, None, compiled, LEGACY_AGENTS) == pipeline.Decision("no-handoff", None)


  def test_no_handoff_when_event_id_is_unchanged():
      compiled = pipeline.compile_legacy(STATUS)
      assert pipeline.decide(record(event_id="e1"), "e1", compiled, LEGACY_AGENTS).kind == "no-handoff"


  def test_ready_for_review_advances_to_the_review_stage():
      compiled = pipeline.compile_legacy(STATUS)
      assert pipeline.decide(record(), "e1", compiled, LEGACY_AGENTS) == pipeline.Decision("advance", "review")


  def test_changes_requested_advances_to_the_implement_stage():
      compiled = pipeline.compile_legacy(STATUS)
      moved = record(to_actor="codex", status="changes-requested")
      assert pipeline.decide(moved, "e1", compiled, LEGACY_AGENTS) == pipeline.Decision("advance", "implement")


  def test_approved_completes_regardless_of_recipient():
      compiled = pipeline.compile_legacy(STATUS)
      assert pipeline.decide(record(status="approved"), "e1", compiled, LEGACY_AGENTS) == pipeline.Decision("complete", None)


  def test_blocked_short_circuits_regardless_of_recipient():
      compiled = pipeline.compile_legacy(STATUS)
      moved = record(to_actor="nobody-in-particular", status="blocked")
      assert pipeline.decide(moved, "e1", compiled, LEGACY_AGENTS) == pipeline.Decision("blocked", None)


  def test_unrecognised_status_is_unknown():
      compiled = pipeline.compile_legacy(STATUS)
      assert pipeline.decide(record(status="banana"), "e1", compiled, LEGACY_AGENTS).kind == "unknown"


  def test_a_handoff_addressed_to_the_wrong_agent_is_unknown():
      compiled = pipeline.compile_legacy(STATUS)
      moved = record(to_actor="codex", status="ready-for-review")
      assert pipeline.decide(moved, "e1", compiled, LEGACY_AGENTS).kind == "unknown"


  def test_custom_status_map_is_honoured():
      custom = {**STATUS, "review": "needs-review"}
      compiled = pipeline.compile_legacy(custom)
      assert pipeline.decide(record(status="needs-review"), "e1", compiled, LEGACY_AGENTS) == pipeline.Decision("advance", "review")


  def test_swapped_agent_names_route_by_name_not_by_the_default():
      compiled = pipeline.compile_legacy(STATUS)
      agents = {"implementer": "aider", "reviewer": "gemini"}
      ready = record(to_actor="gemini", status="ready-for-review")
      assert pipeline.decide(ready, "e1", compiled, agents) == pipeline.Decision("advance", "review")
      back = record(to_actor="aider", status="changes-requested")
      assert pipeline.decide(back, "e1", compiled, agents) == pipeline.Decision("advance", "implement")


  def test_the_default_name_is_not_special_once_agents_change():
      compiled = pipeline.compile_legacy(STATUS)
      agents = {"implementer": "aider", "reviewer": "gemini"}
      ready = record(to_actor="claude", status="ready-for-review")
      assert pipeline.decide(ready, "e1", compiled, agents).kind == "unknown"


  def test_one_agent_in_both_roles_routes_by_status_alone():
      compiled = pipeline.compile_legacy(STATUS)
      agents = {"implementer": "claude", "reviewer": "claude"}
      assert pipeline.decide(record(to_actor="claude", status="ready-for-review"), "e1", compiled, agents) == pipeline.Decision("advance", "review")
      assert pipeline.decide(record(to_actor="claude", status="changes-requested"), "e1", compiled, agents) == pipeline.Decision("advance", "implement")


  # =============== genuine N-stage generality: not expressible in the old two-role system

  def three_stage_pipeline() -> pipeline.Pipeline:
      return pipeline.Pipeline(
          roles={
              "implementer": pipeline.Role("implementer", agent="codex"),
              "tester": pipeline.Role("tester", agent="claude"),
              "reviewer": pipeline.Role("reviewer", agent="claude"),
          },
          stages={
              "draft": pipeline.Stage("draft", "implementer", "implement", {"ready": "test", "blocked-status": "@blocked"}),
              "test": pipeline.Stage("test", "tester", "test", {"passed": "review", "failed": "draft", "blocked-status": "@blocked"}),
              "review": pipeline.Stage("review", "reviewer", "review", {"approved": "@complete", "rejected": "draft", "blocked-status": "@blocked"}),
          },
          profiles={"full": pipeline.Profile("full", ("draft", "test", "review"))},
          default_profile="full",
      )


  def test_three_stage_pipeline_advances_through_each_stage_in_turn():
      p = three_stage_pipeline()
      agents = {"implementer": "codex", "tester": "claude", "reviewer": "claude"}
      r1 = handoff.Handoff(event_id="e1", task="T", to_actor="claude", status="ready", summary="")
      assert pipeline.decide(r1, None, p, agents) == pipeline.Decision("advance", "test")
      r2 = handoff.Handoff(event_id="e2", task="T", to_actor="claude", status="passed", summary="")
      assert pipeline.decide(r2, "e1", p, agents) == pipeline.Decision("advance", "review")
      r3 = handoff.Handoff(event_id="e3", task="T", to_actor="claude", status="approved", summary="")
      assert pipeline.decide(r3, "e2", p, agents) == pipeline.Decision("complete", None)


  def test_three_stage_pipeline_rejection_rewinds_to_a_named_stage_not_just_implement():
      p = three_stage_pipeline()
      agents = {"implementer": "codex", "tester": "claude", "reviewer": "claude"}
      failed = handoff.Handoff(event_id="e2", task="T", to_actor="codex", status="failed", summary="")
      assert pipeline.decide(failed, "e1", p, agents) == pipeline.Decision("advance", "draft")
      rejected = handoff.Handoff(event_id="e3", task="T", to_actor="codex", status="rejected", summary="")
      assert pipeline.decide(rejected, "e2", p, agents) == pipeline.Decision("advance", "draft")


  def test_three_stage_pipeline_blocked_from_any_stage_short_circuits():
      p = three_stage_pipeline()
      agents = {"implementer": "codex", "tester": "claude", "reviewer": "claude"}
      r = handoff.Handoff(event_id="e1", task="T", to_actor="nobody", status="blocked-status", summary="")
      assert pipeline.decide(r, None, p, agents) == pipeline.Decision("blocked", None)


  def test_three_stage_pipeline_wrong_recipient_is_unknown_not_a_guess():
      p = three_stage_pipeline()
      agents = {"implementer": "codex", "tester": "claude", "reviewer": "claude"}
      r = handoff.Handoff(event_id="e1", task="T", to_actor="codex", status="ready", summary="")
      assert pipeline.decide(r, None, p, agents).kind == "unknown"
  ```

  Run `uv run --frozen pytest -q`: all existing tests pass, unedited, plus these new ones. `routing.py` is not touched by this task — do not edit it. Change nothing else.

- [ ] PIPE-2: `routing.decide()` becomes a wrapper over the pipeline engine
  Rules for every task: run the tests with `uv run --frozen pytest -q` (there is no network). Add no dependencies and do not touch `pyproject.toml`, `uv.lock` or the version. `loop.py`, `config.py`, and every existing test file, including `tests/test_routing.py`, must be unedited and pass exactly as before. Never pass or write a permission-bypass flag, never run `git push`, and never write a handoff on an agent's behalf.

  **Replace** `src/whyline_relay/routing.py` in full:

  ```python
  """The routing table: a thin, behavior-preserving wrapper over the pipeline engine."""

  from __future__ import annotations

  from whyline_relay import handoff, pipeline

  IMPLEMENT = "implement"
  REVIEW = "review"
  APPROVED = "approved"
  BLOCKED = "blocked"
  NO_HANDOFF = "no-handoff"
  UNKNOWN = "unknown"

  IMPLEMENTER = "codex"
  REVIEWER = "claude"

  _KIND_TO_MOVE = {
      "no-handoff": NO_HANDOFF,
      "blocked": BLOCKED,
      "complete": APPROVED,
      "unknown": UNKNOWN,
  }
  _STAGE_TO_MOVE = {"implement": IMPLEMENT, "review": REVIEW}


  def decide(
      record: handoff.Handoff | None,
      previous_id: str | None,
      status_map: dict[str, str],
      implementer: str = IMPLEMENTER,
      reviewer: str = REVIEWER,
  ) -> str:
      """Pick the next move from the handoff record alone.

      A missing record, or one whose event id has not changed since the agent
      started, means the agent exited without handing off. That is never inferred
      to be success: the caller pauses.

      Compiles today's fixed implementer/reviewer shape into a pipeline.Pipeline
      and delegates to pipeline.decide(); see pipeline.compile_legacy for why one
      shared transition table on both stages is what reproduces this function's
      actual behavior (it has never depended on which agent's turn just ended).
      """
      compiled = pipeline.compile_legacy(status_map)
      decision = pipeline.decide(
          record,
          previous_id,
          compiled,
          effective_agents={"implementer": implementer, "reviewer": reviewer},
      )
      if decision.kind == "advance":
          return _STAGE_TO_MOVE[decision.target_stage]
      return _KIND_TO_MOVE[decision.kind]
  ```

  Run `uv run --frozen pytest -q`: the entire existing suite passes with **zero edits**, most importantly `tests/test_routing.py`'s 15 tests, byte for byte as they exist today. If any existing test needs to change to pass, stop — that means the wrapper is not behavior-preserving, which is this task's one job. Do not touch `loop.py`, `config.py`, or any test file. Change nothing else.

---

## Self-review against the spec

**Spec coverage.** Section 5.1's `Role`, `Stage`, `Profile`, `Pipeline` dataclasses, with the exact field names and types the (already-reviewed) spec uses. Section 5.3's legacy compilation, including the specific detail that `approved`/`blocked` apply "regardless of recipient" — reproduced by having those two outcomes resolve to `@complete`/`@blocked` before any recipient check runs at all, exactly mirroring `routing.py`'s current docstring. D1 (three separate concepts), D2 (the compiled pipeline reproduces exact behavior, proven the same way every past release proved compatibility: the *old* suite unedited), D3 (stage-local outcome labels — demonstrated by the three-stage tests using entirely different status strings like `"ready"`/`"passed"`/`"failed"` than the legacy `status_map`, something the old two-constant system had no way to express).

**Why one shared transition table, not two different ones.** This is the one place this plan's author (not the spec, which left the exact mechanism to the plan) had to make a real design call, verified empirically rather than assumed: `routing.decide()` today takes no "which stage is active" input at all — it is a pure function of `(status, to_actor)`, checked against *both* the review-transition and the implement-transition on every call, regardless of which agent's turn just finished. Giving the two compiled stages *different* transition tables (e.g., only "implement" accepts `ready-for-review`) would be a subtly different, arguably more "correct-looking" design that does not actually reproduce today's behavior in every case — confirmed by writing the exact reproduction tests above and running them against a real implementation before this plan was finalized, not by reasoning about it alone.

**Placeholders.** None. Every field, function signature, and test assertion was written, then actually run, before this plan was finalized — this plan's code blocks are the exact code verified in a scratch copy of the repository, not a sketch.

**Scope discipline.** This plan deliberately implements less than the full section 5.4 ("Routing, the handoff, and crash-safe resume") — it takes only the parts assignable to build-order phase 1 (D1-D3, 5.1, 5.3) and explicitly defers the stage cursor, `[pipeline]` config parsing, and everything depending on them to their own later phases, exactly as the design's section 6 lays out. "Not in this plan" states this plainly so a reviewer isn't left wondering why `config.py` isn't touched.
