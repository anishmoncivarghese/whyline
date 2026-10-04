# Relay plan flow, Part D: whyline 0.3.32 (planning in the main window, plan dropdown, Run)

Every task below is one task of
`docs/superpowers/plans/2026-10-04-relay-plan-flow.md` (spec:
`docs/superpowers/specs/2026-10-04-relay-plan-flow-design.md`). Read that task
in full and follow its steps exactly: write the failing test first, see it
fail, implement, then run the whole suite with `uv run pytest -q`. The plan's
"Global Constraints" apply. whyline-relay 0.2.29 is already installed and
required (Task 11 Step 1, the dependency bump, is done -- skip it).

Tests must not depend on which agent CLIs (claude, codex, agy, grok) are
installed on the machine: CI has none. Stub relay_ops.relay_agents,
account.agent_status or shutil.which where a test needs agents. Tests must
never read or write the real ~/.gemini/antigravity-cli/settings.json.

Release steps are done by a human afterwards: never push, tag, bump the
version or publish.

- [x] RPF-11: relay_ops for plan files and questions
  Implement "Task 11: relay_ops for plan files and questions" from the plan,
  starting at Step 2: PLANS_DIR, PlanInfo, plan_slug, plan_path, with_marker,
  list_plans, save_pasted_plan(root, text, name, replace=), approve_plan(root,
  draft, name, replace=), configured_plan, select_plan, planner_agents,
  save_planner, plan_questions_error, answer_plan, open_questions,
  question_feedback, and planner drafts' drafted_by "<draft> (reviewed by
  <review>)". Verify: uv run pytest tests/console/test_relay_ops.py -q, then
  uv run pytest -q.

- [x] RPF-12: The plan job (no widgets)
  Implement "Task 12: The plan job (no widgets)" from the plan: create
  src/whyline/console/plan_job.py (PlanRequest, Outcome, run_request,
  run_revision, run_answer, summary, questions_text) and
  tests/console/test_plan_job.py. Verify: uv run pytest -q.

- [x] RPF-13: Plan popup becomes a form
  Implement "Task 13: Plan popup becomes a form" from the plan: RelayPlanScreen
  only collects a PlanRequest (Plan name, Drafter/Reviewer dropdowns, name
  clash confirm, Resume as a request; Paste still saves instantly), and add
  PlanDraftScreen. Delete and update the tests the task names.
  Verify: uv run pytest -q.

- [ ] RPF-14: The plan job in the main window
  Implement "Task 14: The plan job in the main window" from the plan: plan
  state ("working" / "review" / "answering"), progress lines "plan · ...",
  the Approve / View draft / Discard row, typed "approve" or change requests,
  numbered questions answered in the prompt, Escape to leave, slash commands
  still working. Verify: uv run pytest -q.

- [ ] RPF-15: Set up chooses the plan
  Implement "Task 15: Set up chooses the plan" from the plan, including Step
  4b: the Plan dropdown, "No plan yet" with Make a plan, typed start refused
  without a plan, Check run against the chosen plan (run_checks(root, plan)),
  and "Clear old run" instead of Resume for a paused run whose task is
  already ticked. Verify: uv run pytest -q.

- [ ] RPF-16: Run, one guided path
  Implement "Task 16: Run, one guided path" from the plan, including Step 5b:
  the Run button and typed "run", RunChoiceScreen, guided Set up with the
  roles summary (Looks good / Change), recommended roles from installed and
  logged-in agents with the "what it means" line, and the run flow carrying
  a newly saved plan into guided Set up. Verify: uv run pytest -q, and the
  Run button fits an 80-column terminal.
