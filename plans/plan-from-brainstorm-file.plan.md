<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-01T14:00:00+05:30 -->
# Plan from any brainstorm file, with the whole lifecycle shown

Runs after `plans/relay-tooling.plan.md` and before `plans/job-search-5.plan.md`. All of it is in the console. There is no whyline-relay change.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why:
- In Chat → **Brainstorm**, the **Test planner** field has no effect, because a chat brainstorm writes only `docs/brainstorm/<topic>.md`. Choosing a Test planner there also silently changes the Test planner the **Plan** dialog uses, through `relay_ops.save_planner`.
- In Relay → **Plan** → **Brainstorm it**, the **From** list shows only `docs/brainstorm/*.md`. A brainstorm saved anywhere else can't be picked. This happened with the brainstorm output in the TradingPlatform repository root.
- **Auto** always starts a new brainstorm, even when one is already written.
- The dialog doesn't show the stages a plan goes through, so the user can't see that a test plan with test cases will be written.

What the user gets:
- Chat Brainstorm has no Test planner field. The Plan dialog keeps it.
- **From** has **Choose file…**, which opens the Mac file picker for `.md`, `.txt`, `.pdf` or `.docx`. The file is copied into `docs/brainstorm/` and selected. It is then remembered at the top of the list.
- **Auto** can start from an existing brainstorm or a chosen file. It skips research and goes straight to spec, plan, test plan, review, implement, test, review and release.
- A **Lifecycle** line in the dialog shows the stages that will run from the current choices. For example: `Spec ✓ → Plan ✓ → Test plan with test cases (codex) ✓ → Plan review (claude) ✓ → Implement → Test → Review → Release`. A stage that is off shows `—` and a short hint.

Rules every task keeps:
- Console first. Every new choice saves through the same function the CLI uses.
- No new dependency. Reuse `mac_input.pick_files`, as Jobs' **Choose file…** does.
- Edit only the files a task names, and their tests. Each task ends with `uv run pytest -q` passing.
- Tests never open a real picker, run a real agent or contain "/Users/".

- [ ] PFB-1: Remove Test planner from Chat Brainstorm
  Edit `src/whyline/console/tui.py` and `tests/console/` only.
  1. `brainstorm_field_widgets` gets a keyword `with_test_planner: bool`. The Chat `BrainstormScreen` passes False, and the Plan dialog and Auto pass True.
  2. With False, the Test planner row and tip aren't composed, and `_save_test_planner` is never called, so a chat brainstorm never changes the planner settings.
  3. Add a single line under Final write-up: `Test plan and test cases are written when you make a plan from this brainstorm (Relay → Plan).`
  Tests:
  - the Chat screen has no `#bs-test-planner`
  - starting a chat brainstorm leaves `planner_agents` unchanged
  - the Plan dialog still has the field
  Change nothing else.

- [ ] PFB-2: Choose file… for a brainstorm in the Plan dialog
  Edit `src/whyline/console/relay_screens.py`, `src/whyline/console/relay_ops.py` and their tests only.
  1. Add `relay_ops.import_brainstorm(root, source: Path) -> str`:
     - It reads `.md`/`.txt` as text, and `.pdf`/`.docx` with the same readers Jobs uses for CVs.
     - It refuses an empty or unreadable file, or one over 2 MB of text, with a plain message.
     - It writes `docs/brainstorm/<slug of the file stem>.md`. Keep the original stem in a first line `<!-- imported from: <file name> -->`. When the slug exists with different text, add `-2`, `-3` and so on.
     - It returns the topic (the stem without `.md`) that `plan_from_brainstorm` takes.
     - A file already inside `docs/brainstorm/` is not copied, and its stem is returned.
  2. Under **From**, add a **Choose file…** button. It opens `mac_input.pick_files` in a thread worker, through an injectable `pick_files_fn`, and calls `import_brainstorm`. Then it refreshes the From options and selects the new topic. Errors show in `#rp-error`.
  3. List **From** options newest first by modification time, so a just-imported file is at the top.
  4. Before making the plan, show `Plan from: docs/brainstorm/<topic>.md (imported from <file name>)`.
  5. CLI: `whyline plan --from-file PATH`, or the nearest existing plan command, calls the same `import_brainstorm`. If no plan command exists in the CLI, add `whyline brainstorm import PATH`, which prints the topic.
  Tests:
  - each file type
  - the empty and too-big refusals
  - a slug clash
  - a file already in `docs/brainstorm`
  - the picker stub selecting the new option
  - the CLI
  Change nothing else.

- [ ] PFB-3: Auto from an existing brainstorm
  Edit `src/whyline/console/relay_screens.py`, `src/whyline/console/auto_run.py`, `src/whyline/console/plan_job.py` and their tests only.
  1. When the source is **Auto**, show the same **From** select and **Choose file…** as **Brainstorm it**. `New brainstorm` stays the default and keeps today's behaviour.
  2. With an existing topic chosen:
     - Hide the research fields (models, review passes, topic).
     - Add `brainstorm_topic` to `AutoRunRequest` and to the saved checkpoint.
     - `auto_run` skips the research stage and starts at spec, using `plan_from_brainstorm` with that topic.
     - Every later stage is unchanged.
  3. The Auto progress line shows `Starting from docs/brainstorm/<topic>.md` as the first step.
  4. Resuming a saved Auto request with a topic resumes from the right stage.
  Tests:
  - the request carries the topic
  - research is not called
  - the checkpoint round trip
  - a new brainstorm unchanged
  Change nothing else.

- [ ] PFB-4: A Lifecycle line in the Plan dialog
  Edit `src/whyline/console/relay_screens.py` and its tests only.
  1. Add a `#rp-lifecycle` Static under the roles that updates whenever source, **Write a spec first**, Drafter, Test planner, Reviewer, or (for Auto) the execution roles change.
  2. Stages in order, each with its agent when set:
     - Brainstorm (new brainstorm only)
     - Spec
     - Plan
     - Test plan with test cases
     - Plan review
     - then, for Auto only, Implement, Test, Review and Release
  3. A stage that is off shows `—`. Off with a hint, for example: `Test plan with test cases —  (choose a Test planner)`.
  4. Under the line, add one sentence: `The test plan lists test cases for each task: automatic ones the tester runs, and manual checks the relay pauses for.`
  Tests: the line for each source, with and without a spec, with and without a Test planner, and that Auto shows the execution stages. Change nothing else.

- [ ] PFB-5: Docs
  Edit `docs/` pages that describe Plan and Brainstorm, and `README.md` only where it describes them.
  - Making a plan from any brainstorm file
  - Auto from an existing brainstorm
  - The Lifecycle line
  - That Test planner belongs to Plan, not Chat Brainstorm
  Verify with `uv run pytest -q`. Change nothing else.
