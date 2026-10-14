
## Relay package, test plans (`/Users/anish/whyline-relay`), after whyline 0.3.44

A plan may have a test plan beside it: `plans/<name>.tests.md` for `plans/<name>.plan.md`. The test plan is written by an optional Test planner, a different agent from the Drafter where possible, so the tests do not share the plan writer's blind spots. The Reviewer reviews both files together. Each phase ends with a Verify task that turns the automatic scenarios into tests and runs them, and a release cannot continue while a manual check that covers its tasks is still unconfirmed. With no Test planner configured, everything behaves exactly as today.

- [ ] TPL-1: The test plan format and its validator
  Edit only `/Users/anish/whyline-relay/src/whyline_relay/testplan.py` (new) and `/Users/anish/whyline-relay/tests/test_testplan.py` (new). Leave this whyline checkout untouched.
  A test plan is Markdown. Each scenario is `- [ ] TP-<n>: <title>` with indented lines `covers: <task id>, <task id>`, `kind: auto` or `kind: manual`, `steps:` (one or more following `  - ` lines), and `expected:` (one or more following `  - ` lines). Optional `not-covered: <task id> — <reason>` lines at top level name plan tasks deliberately left without a scenario.
  Add `path_for(plan_path) -> Path` (`x.plan.md` → `x.tests.md`, any other `x.md` → `x.tests.md`), `parse(text) -> list[Scenario]` with frozen `Scenario(id, title, covers, kind, steps, expected, checked, note)`, `validate(test_text, plan_text) -> list[str]`, and `open_manual(test_text, task_ids) -> list[Scenario]`.
  `validate` reports: a duplicate scenario id; a `covers` id not in the plan; a kind other than auto or manual; a scenario with no steps or no expected lines; a plan task, other than a `relay-profile: release` or `relay-profile: verify` task, that no scenario covers and no `not-covered` line names. Problems are one line each and name the scenario or task.
  `open_manual` returns the unchecked manual scenarios that cover any of `task_ids`.
  Tests: a well-formed file parses with every field; each problem above is reported with its id; release and verify tasks need no scenario; `not-covered` silences a task; `open_manual` ignores checked and auto scenarios and scenarios for other tasks; `path_for` maps both names.
  Verify with `uv run pytest -q tests/test_testplan.py` and `uv run pytest -q` in `/Users/anish/whyline-relay`. Change nothing else.

- [ ] TPL-2: An optional Test planner stage in the planner
  Edit only `/Users/anish/whyline-relay/src/whyline_relay/config.py`, `planner.py`, `prompts.py`, `setup.py`, and their tests under `/Users/anish/whyline-relay/tests/`. Leave this whyline checkout untouched.
  `PlannerConfig` gains `test: str = ""`; `[planner] test = "<agent>"` sets it, and an unknown agent name is a `ConfigError` like `draft` and `review`. Empty means no Test planner. `setup.write_planner(root, draft, review, test="")` writes it, leaving every other table unchanged.
  When `test` is set, `_pipeline_for` becomes draft → tests → review. The new `tests` stage (prompt `plan-tests`) gives the Test planner the request and the draft plan, and asks it to write `draft-plan.tests.md` beside the draft plan in the format from `TPL-1`: auto scenarios for behaviour a test can check, manual scenarios for anything on screen or on another device, a happy path, edge cases and failure cases (crash, offline, dirty repository, stale input) per feature, and no code. The review prompt then says to review both files, to run `testplan.validate` and treat every problem as a reason to revise, and to check that every phase of the plan ends with a `relay-profile: verify` task before its release task. Review transitions gain `revise-tests` → `tests`; `revise` still goes to `draft`, and after a new draft the `tests` stage runs again.
  The plan-draft prompt, when `test` is set, tells the Drafter to put a task with `relay-profile: verify` immediately before every `relay-profile: release` task, naming the scenarios it must automate.
  `approve` writes `testplan.path_for(target)` beside the plan and commits both files in the same commit; a draft test plan with validation problems refuses approval with those problems. When `test` is empty, the pipeline, prompts and `approve` are byte-for-byte what they are today.
  Tests: config round-trips `test`; with `test` empty the pipeline has two stages and approve writes one file; with `test` set there are three stages, `revise-tests` returns to `tests`, approve writes and commits both files, and an invalid test plan blocks approval naming the problem.
  Verify with `uv run pytest -q tests/test_planner.py tests/test_planner_api.py tests/test_config.py tests/test_setup.py` and `uv run pytest -q` in `/Users/anish/whyline-relay`. Change nothing else.

- [ ] TPL-3: Test plans from the brainstorm path
  Edit only `/Users/anish/whyline-relay/src/whyline_relay/brainstorm.py`, `prompts.py`, and their tests. Leave this whyline checkout untouched.
  When the planner config has `test` set, `generate_plan_from_synthesis` runs one more turn after the plan draft: the Test planner receives the final synthesis and the draft plan and writes the test plan beside the draft, with the same format, prompt rules and `testplan.validate` check as `TPL-2`. Every success or acceptance criterion the synthesis states (for example an "is successful when" list) must become at least one scenario; the prompt says so and lists them. A Test planner failure moves to the backup chain the same way the plan draft does; an exhausted chain keeps the plan draft and reports that no test plan was written, and does not approve silently without one.
  Tests with a fake runner: the test plan is written beside the brainstorm plan draft; a synthesis with three acceptance criteria produces a prompt listing all three; with `test` empty no extra turn runs; a failing Test planner falls through to the backup and an exhausted chain reports it.
  Verify with `uv run pytest -q tests/test_brainstorm_plan.py` and `uv run pytest -q` in `/Users/anish/whyline-relay`. Change nothing else.

- [ ] TPL-4: Verify tasks run the automatic scenarios
  Edit only `/Users/anish/whyline-relay/src/whyline_relay/loop.py`, `plan.py`, `prompts.py`, and their tests. Leave this whyline checkout untouched.
  Add task profile `verify` (`relay-profile: verify`). A verify task runs through the configured pipeline like any task, with this added to its prompt: the test plan's auto scenarios that cover any task above it and below the previous release, each turned into an automated test under `tests/acceptance/` named after its scenario id, and run; the task is ready only when they pass. A scenario that cannot be automated must be changed to `kind: manual` in the test plan with the reason, not skipped. The relay's commit for a verify task includes the test plan file.
  A plan with no test plan beside it treats `verify` tasks as ordinary tasks.
  Tests with fake agents: a verify task's prompt lists exactly the in-range auto scenarios; scenarios for tasks after the release are excluded; a plan without a test plan runs verify as an ordinary task.
  Verify with `uv run pytest -q` in `/Users/anish/whyline-relay`. Change nothing else.

- [ ] TPL-5: Manual checks block the release until you confirm them
  Edit only `/Users/anish/whyline-relay/src/whyline_relay/loop.py`, `cli.py`, `testplan.py`, and their tests. Leave this whyline checkout untouched.
  Before any `relay-profile: release` task, whoever runs the release (the user or an agent set as the release role, including the agent path in `_with_release_implementer`), the relay computes `testplan.open_manual` for the tasks since the previous release. If any are open it pauses with reason `Manual checks before <task id>:` followed by one line per scenario (`TP-n title`, its steps and expected lines), and does not start the release.
  Add `whyline relay manual` (lists open manual checks for the paused release), `whyline relay manual <TP-id> pass [note]`, and `whyline relay manual <TP-id> fail <note>`. `pass` ticks the scenario in the test plan, adds `note:` when given, and commits only that file with `test: confirm <TP-id>`. `fail` records `note: FAILED <note>` without ticking, commits only that file, and keeps the release blocked. `whyline relay done` and `resume` refuse with the open list while any remain; when none remain, `resume` continues into the release as today.
  Tests on scratch repos: two open manual checks pause before the release and list both; `pass` ticks and commits one file; `fail` keeps the pause and records the note; `done` is refused while one is open; with all passed the release starts; with the release role set to an agent, that agent is not started while a check is open and is started on the next `resume` once all pass; a plan without a test plan never pauses for this.
  Verify with `uv run pytest -q` in `/Users/anish/whyline-relay`. Change nothing else.

- [ ] TPL-6: Publish whyline-relay 0.2.38
  relay-profile: release
  relay-repo: /Users/anish/whyline-relay
  In `/Users/anish/whyline-relay` only, set `pyproject.toml` to `0.2.38`. Write `docs/releases/v0.2.38.md` in the same shape as `docs/releases/v0.2.37.md`: an optional Test planner writes `<plan>.tests.md` beside each plan, from a plain request or from a brainstorm, and the Reviewer reviews both; each phase ends with a Verify task that automates and runs its scenarios; a release waits until you confirm its manual checks with `whyline relay manual`; with no Test planner nothing changes. Run `uv run pytest -q` and confirm it exits 0. Tag `v0.2.38`, push, publish to PyPI the way `v0.2.37` was published, and confirm `pip index versions whyline-relay` lists `0.2.38`.

## Console, test plans, after whyline-relay 0.2.38

- [ ] TPL-7: Depend on whyline-relay 0.2.38
  In this whyline checkout, raise both `whyline-relay` bounds in `pyproject.toml` to `>=0.2.38,<0.3`. Refresh `uv.lock`. Install the published `0.2.38` and confirm `whyline_relay.testplan` imports and `setup.write_planner` accepts `test`. Do not add UI. Do not tag or publish whyline.
  Verify with `uv run pytest -q`. Change nothing else.

- [ ] TPL-8: A Test planner select in the plan, brainstorm and Auto forms
  Edit only `src/whyline/console/relay_ops.py`, `src/whyline/console/relay_screens.py`, `src/whyline/console/tui.py`, `src/whyline/console/auto_run.py`, and their tests.
  `relay_ops.planner_agents(root)` returns `(draft, review, test)`; `relay_ops.save_planner(root, draft, review, test="")` passes `test` through to `setup.write_planner`. Update every caller.
  The plan form gains `Test planner:` (`Select` id `rp-test-planner`) below Drafter: `None` (default, value `""`) followed by the usable agents, shown and hidden with the Drafter and Reviewer rows. When it equals the Drafter, a dim line under it says `Tip: a different agent from the Drafter catches more.` and does not block. The brainstorm form and the Auto form gain the same select with their own ids (`bs-test-planner`, the Auto form's next id in its pattern), saved and restored with the other planner choices. After a plan is approved with a test plan, the transcript names both files.
  Tests: None is the default and saves `test = ""`; choosing codex saves it and reopening shows it; the same agent as the Drafter shows the tip and still saves; the brainstorm and Auto forms carry the value into the planner call; an approved plan with a test plan prints both paths.
  Verify with `uv run pytest -q tests/console` and `uv run pytest -q`. Change nothing else.

- [ ] TPL-9: Confirm manual checks from the console
  Edit only `src/whyline/console/tui.py`, `src/whyline/console/repl.py` (`_help_text`), and their tests.
  When the relay pauses with a `Manual checks before` reason, the transcript lists each open check with its steps and expected lines, and a row `#manual-actions`, shaped like `#plan-actions`, shows Pass and Fail for the first open check. Pass runs `whyline relay manual <id> pass` through the relay launcher; Fail asks for a note in the prompt, then runs `manual <id> fail <note>`. After each, the list is re-read and the next open check is shown. When none remain, print `All manual checks passed. Press Resume to release.` and enable Resume. Typing `manual`, `manual TP-3 pass`, or `manual TP-3 fail <note>` in the Relay prompt does the same. `_help_text` gains `manual  confirm a release's manual checks`.
  Tests: a manual-check pause shows the first check with Pass and Fail; Pass launches `manual TP-1 pass` and moves to the next check; Fail requires a note; the last Pass enables Resume and prints the hint; a release pause with no manual checks shows no row.
  Verify with `uv run pytest -q tests/console/test_tui.py tests/console/test_repl.py` and `uv run pytest -q`. Change nothing else.

- [ ] TPL-10: Publish whyline 0.3.45
  relay-profile: release
  In this whyline checkout, bump `pyproject.toml` from `0.3.44` to `0.3.45`. Write `docs/releases/v0.3.45.md` in the same shape as `docs/releases/v0.3.44.md`: the plan, brainstorm and Auto forms have an optional Test planner that writes a test plan beside the plan, which the Reviewer reviews with it; each phase ends with a Verify task that automates its scenarios; a release waits on its manual checks, which you pass or fail from the console with a note. Needs whyline-relay 0.2.38. Run `uv run pytest -q` and confirm it exits 0. Tag `v0.3.45`, push, publish to PyPI the way `v0.3.44` was published, and confirm `uv tool upgrade whyline` installs `0.3.45`.
