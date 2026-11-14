<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-sdlc-upgrade-design.md | created: 2026-11-14T21:00:00+05:30 -->
# SDLC evidence: every criterion names its test, and whyline reads the result

Spec: `docs/superpowers/specs/2026-11-14-sdlc-upgrade-design.md`, Part 3. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **Whyline runs the named tests once per feature, before Accept, and on demand**, not after every task. A run after each task would double the relay's test time.
- **Demo capture covers a command's text output and a Textual screen.** Web page capture through an agent's browser tool is a follow-up.
- **The tester's prompt is not changed** (that would need a whyline-relay release). The criteria and their tests reach the tester through the test plan file it already reads.

Runs after `plans/sdlc-product-owner.plan.md`, and before `plans/sdlc-done.plan.md`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: `trace.coverage` shows which requirement a test plan scenario covers, but nothing checks that a named test exists, ran and passed. The tester's "passed" is taken on trust, and nothing shows the feature working.

What the user gets:
- The test plan maps each acceptance criterion to an automated test id or a manual check.
- Before Accept, whyline runs the named tests itself and shows its own results in the table. A test that is missing or didn't run counts as failed.
- An optional demo: a command's output, or a console screen, saved with the document set and linked from the build record and the pull request.

Rules every task keeps:
- **Console first.** Running the checks, seeing results and capturing a demo work from Docs through the same functions as `whyline docs …`.
- **Whyline's result wins.** The table shows what whyline read from the result file. The tester's claim is shown beside it only when it differs.
- **Test ids are data.** A test id must match `^[\w./-]+(::[\w\[\]. -]+)*$` and resolve to a file inside the repository. It is passed as an argv element, never through a shell.
- **The test command comes from Release → Set up** (`ReleaseConfig.checks`) or the default `uv run pytest`. A plan or a document never supplies a command to run for tests.
- **A demo command is run only after the user approves it** once per document set, shown in full. It runs in the repository with a time limit, an argv list and no shell. Its output passes `security.secrets.scan_text` redaction before it is saved.
- **Evidence files** live in `docs/sdlc/<slug>/evidence/`, each at most 1 MB.
- **No new dependency.** JUnit XML is read with `xml.etree.ElementTree`.
- **Tests:** never run a real provider or a real nested test suite (use a fake runner writing a result file). Use temporary folders. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A named test that doesn't exist, or isn't in the result file, is failed, never passed. EVD-2, `test_missing_test_is_a_failure`.
- A test id with shell characters or a path outside the repository is refused and never run. EVD-1, `test_bad_test_ids_are_refused`.
- A demo command never runs before the user approved exactly that command. EVD-4, `test_demo_needs_approval_of_this_command`.
- A secret in demo output is redacted before the file is written. EVD-4, `test_demo_output_is_redacted`.
- A criterion with no check is shown as uncovered, and Accept still lets the user decide. EVD-3, `test_uncovered_criterion_is_shown`.

- [ ] EVD-1: Criteria in the test plan
  Edit `src/whyline/sdlc/trace.py`, the test plan part of the plan-stage prompt in `src/whyline/sdlc/runner.py`, and their tests.
  1. A scenario in the test plan may carry a line `Checks: R1.A1, R1.A2` and, for an automated one, `Test: tests/x/test_y.py::test_name` (one or more, comma separated). Read them from the scenario's detail lines without changing `whyline_relay.testplan`.
  2. `trace.checks(tests_text, root) -> dict[str, list[Check]]` keyed by criterion id. `Check` has `scenario`, `kind` (`auto` or `manual`), `tests: tuple[str, ...]` and `problem: str`. A test id that fails the pattern, or whose file is outside the repository or missing, gets a `problem` and is never returned as runnable.
  3. `trace.Coverage` gains `unchecked: list[str]` (criteria with no check) and `manual_only: list[str]`.
  4. The plan-stage prompt asks the test planner to give every criterion a scenario with `Checks:` and, for automated ones, `Test:` with the exact test id it expects the implementer to write.
  5. `review.approve` for the plan warns (it does not refuse) when a criterion has no check: the approval dialog lists them.
  Tests: `test_bad_test_ids_are_refused` (`;`, `$(…)`, backticks, `..`, an absolute path), parsing several tests, `unchecked` and `manual_only`, and the warning list.

- [ ] EVD-2: Whyline runs the named tests and reads the result
  Create `src/whyline/sdlc/evidence.py` and `tests/sdlc/test_evidence.py` only.
  1. `evidence.folder(docs, slug) -> Path`.
  2. `evidence.run_checks(root, docs, docset, *, run=…, timeout_minutes=20) -> Results`:
     - collects the runnable test ids from `trace.checks`
     - runs the repository's test command with the ids and `--junitxml=<evidence>/results.xml` appended (the first entry of `ReleaseConfig.checks` that starts with `uv run pytest` or `pytest`, else `uv run pytest`)
     - parses the XML into `{test id: passed | failed | skipped | missing}`, matching a result to an id by file and test name
  3. `Results` has `per_test`, `per_criterion` (`passed` only when every test of every automated check passed; `failed` when any failed, is missing or was skipped; `manual` when only manual checks cover it; `uncovered`), `ran_at`, `command` and `exit_code`. It is saved as `evidence/results.json`.
  4. When the command can't run or times out, every automated criterion is `failed` with the reason.
  5. `evidence.load(docs, slug) -> Results | None`, and `evidence.stale(root, results) -> bool` (HEAD moved since `ran_at`'s commit).
  Tests: `test_missing_test_is_a_failure`, a parametrised test id matched, a skipped test counted as failed, the command chosen from the release config, the timeout, and `stale`.

- [ ] EVD-3: Results in the Accept table, the build record and the pull request
  Edit `src/whyline/sdlc/accept.py`, `src/whyline/sdlc/owner.py`, `src/whyline/sdlc/record.py`, `src/whyline/release/pullrequest.py`, `src/whyline/sdlc/cli.py`, `src/whyline/console/docs_screen.py` and their tests.
  1. `accept.table` lines gain whyline's result per criterion and, where the relay's handoff for the covering task claimed a pass that whyline read as failed, the flag `tester said passed`. A flagged line raises a RAAID issue when `whyline.raaid` is importable (once per criterion).
  2. Entering the Accept stage runs `evidence.run_checks` when there are no results or they are stale. `owner.read` is given whyline's results.
  3. Manual checks are listed with **Passed** and **Failed** (with a note), saved through `whyline_relay.testplan.mark_passed` / `mark_failed` on the test plan file.
  4. The build record's Acceptance section and the pull request body get the table: criterion, check, result.
  5. CLI: `whyline docs check <slug>` runs the checks and prints the table. Docs: **Run checks** and the table on the Accept view.
  Tests: `test_uncovered_criterion_is_shown`, the mismatch flag and its single RAAID issue, stale results rerun, manual pass and fail written to the test plan, and the table in the build record and the pull request body.

- [ ] EVD-4: Demo capture
  Create `src/whyline/sdlc/demo.py` and `tests/sdlc/test_demo.py`. Edit `src/whyline/sdlc/cli.py`, `src/whyline/console/docs_screen.py` and their tests.
  1. A plan may have, in its header area, a line `Demo: <command>` and optionally `Demo screen: <console screen name>`. `demo.declared(plan_text) -> Demo | None`.
  2. `demo.approved(docs, slug) -> str | None` and `demo.approve(docs, slug, command)`: the exact command the user approved, stored in the set's manifest. A changed command needs a new approval.
  3. `demo.capture_command(root, docs, slug, command, *, run=…, timeout_seconds=120) -> Path`: refuses unless `command == demo.approved(...)`. Splits with `shlex.split`, runs without a shell, redacts, cuts to 1 MB, and writes `evidence/demo.txt` with the command, the exit code and the output.
  4. `demo.capture_screen(root, docs, slug, screen: str) -> Path`: for a repository that is whyline itself or another Textual app exposing a test pilot, saves an SVG (`App.export_screenshot`) of the named screen to `evidence/demo.svg`. A screen name is one of a list the console exposes (`mode-relay`, `mode-agents`, `assistant`, `docs`, `release`); anything else is refused. When the app can't be driven, it returns the reason and writes nothing.
  5. CLI: `whyline docs demo <slug>` shows the declared command and asks to approve and run. `--yes` approves this command. Docs: **Demo** on the Accept view with the same approve-then-run flow, and the captured text or `Screenshot saved: <path>`.
  6. The build record and pull request body link the evidence files.
  Tests: `test_demo_needs_approval_of_this_command` (a changed command is refused), `test_demo_output_is_redacted`, the 1 MB cap, the timeout, an unknown screen refused, and no demo declared shows `No demo for this feature.`

- [ ] EVD-5: Docs
  Edit `docs/sdlc.md` (or the page that documents the pipeline) and `README.md` only.
  Cover: `Checks:` and `Test:` lines in a test plan, how whyline's result is decided, the `tester said passed` flag, manual checks, the demo line and its approval, and where evidence is kept.
  Verify with `uv run pytest -q`.
