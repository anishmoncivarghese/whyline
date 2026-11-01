<!-- whyline-plan v1 | source: hand | drafted-by: codex | created: 2026-10-10T18:48:10+05:30 -->
# Fix post-plan cleanup, history commits, and setup selection

- [x] PPF-1: Release planner-owned live markers
  In `/Users/anish/whyline-relay`, make every planner/spec pipeline release the
  `running.json` marker in a `finally` path after success, pause, or failure.
  Keep `running.clear` ownership-safe so another process's newer marker cannot
  be removed. Add regression tests that reproduce an in-process planner whose
  PID remains alive after the draft/review pipeline finishes.

- [x] PPF-2: Commit planning decisions with approved artifacts
  In `/Users/anish/whyline-relay`, include a changed tracked
  `.whyline/decisions.md` in the same approval commit as the spec or plan.
  Preserve unrelated dirty files and keep approval idempotent. Update planner
  and spec approval tests to prove both the history inclusion and isolation.

- [x] PPF-3: Keep the console correct on the current relay dependency floor
  In this repository, add compatibility helpers for the currently supported
  `whyline-relay>=0.2.32`: clear a console-owned planning marker after each
  in-process planning job, and commit pending planning decisions after a
  successful spec or plan approval when the installed relay did not already do
  so. Both helpers must be safe no-ops with the fixed relay package. Add focused
  console tests for success and failure cleanup and for clean post-approval Git
  state.

- [x] PPF-4: Preselect the plan that was just created
  Keep the newly saved plan as an in-memory setup hint. When the user creates a
  plan from the standalone Plan flow and then opens Set up, select that exact
  plan instead of the previously configured plan. Do not persist the choice
  until the existing Check action. Add a UI regression test with an older
  configured plan and a newer just-created plan.

- [x] PPF-5: Verify and recover the current repository
  Run the focused tests in both repositories, then their full test suites in
  proportion to runtime. Record the design decisions in each repository.
  Commit the source changes without publishing or changing reserved versions.
  Finally, after proving the live PID has no agent children, clear only the
  stale `__plan__` marker, commit the accumulated decision history, and confirm
  the new plan is the setup default with a clean working tree.
