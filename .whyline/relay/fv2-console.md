# Relay guided flow v2: whyline console part (0.3.34)

Each task is one task of `docs/superpowers/plans/2026-10-04-relay-guided-flow-v2.md`
(spec: `docs/superpowers/specs/2026-10-04-relay-guided-flow-v2-design.md`).
Read the task in full and follow its steps exactly: write the failing test
first, see it fail, implement, then run the whole suite with `uv run pytest -q`.
The plan's "Global Constraints" apply. whyline-relay 0.2.31 is already
required and installed (the bump before Task 7 is done -- skip it).

Tests must not depend on installed agent CLIs or the whyline binary, must
never touch the real home folder, must pass on Windows (compare paths as
Path, show them with .as_posix()), and must press buttons by widget
(`query_one("#id", Button).press()`) and wait for screens in a loop rather
than clicking by position or pausing one frame. Every popup's main button
must stay visible at 80x24. Never push, tag, bump the version or publish.

- [x] FV2-7: relay_ops for specs, synthesis and release tasks
  Implement "Task 7" from the plan: draft/revise/resume/answer/discard/
  approve_spec, pending_spec, spec_questions_error, final_synthesis,
  revise_synthesis, draft_plan(spec=), release_task, save_release,
  release_role, and the plan marker's `spec:` field in with_marker/list_plans.
  Verify: uv run pytest -q.

- [ ] FV2-8: plan_job stages: synthesis, spec, plan
  Implement "Task 8" from the plan: Outcome.stage/text/topic/writer,
  PlanRequest.spec_first, run_request per source, run_synthesis_change,
  run_spec_from_synthesis, run_plan_from_spec, stage-aware run_revision and
  run_answer, spec_summary and synthesis_text. Verify: uv run pytest -q.

- [ ] FV2-9: Brainstorm-first Plan form; start asks first
  Implement "Task 9" from the plan: sources "Brainstorm it" (default) /
  "I'll describe it" / "I have a plan already", the "Write a spec first"
  checkbox, Drafter/Reviewer shown for brainstorm and describe, and a typed
  `start` without --plan opening the Run flow. Verify: uv run pytest -q.

- [ ] FV2-10: Synthesis and spec review in the main window
  Implement "Task 10" from the plan: review by stage (synthesis -> spec ->
  plan), approve chaining, the spec saved before the plan job with a failure
  message that keeps it, View full / View spec / View draft.
  Verify: uv run pytest -q.

- [ ] FV2-11: Committer and Release in the Roles step; the release state
  Implement "Task 11" from the plan: "Committer: whyline (automatic)", the
  Release select (you / an agent) saved with save_release, the meaning line,
  and the release pause shown as a checklist with typed done/skip launching
  `whyline relay done|skip <ID>` and Resume relabelled "Release done…".
  Verify: uv run pytest -q.
