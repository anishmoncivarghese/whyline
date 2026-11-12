<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-12T22:30:00+05:30 -->
# Release CI recovery: say why it failed, rerun, ask an agent

Runs after `plans/done/release-from-branch.plan.md` and before `plans/raaid-log.plan.md`. Design: `docs/superpowers/specs/2026-11-12-release-ci-recovery-design.md`. Read it before any task.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

What the user gets:
- When release CI fails, the failure screen says why in plain words: GitHub had no runner, timed out, tests failed (with the test names), publish failed, or something else.
- **Rerun failed jobs** reruns them and the release carries on by itself to PyPI.
- **Ask an agent** explains the failure read-only. **Fix with an agent** opens the Fix flow when code must change.
- A setting can rerun once automatically when GitHub had no runner. Real test failures are never rerun automatically.
- A slow `gh` reply while waiting for CI no longer stops the release.
- `whyline release why`, `whyline release rerun` and `whyline release ask` do the same from a terminal.

There is no publish task. When the relay finishes, press **Release**.

Rules every task keeps:
- Console first: every console action calls the same function as its CLI command.
- No new dependency. `gh` and git run through the `run` callable the release code already injects. Tests use a fake `run` with recorded `gh` JSON and log text, never the network or a real agent.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.

Review focus, each one pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A job cancelled before any step ran, with the runner annotation: cause `no-runner`, not `tests`. RCR-1, `test_never_started_job_is_no_runner`.
- A failed test step: cause `tests` with the `FAILED` test names. RCR-1, `test_failed_tests_are_named`.
- One `gh` timeout while polling: the step keeps waiting; five in a row stop it with `GitHub didn't answer`. RCR-2, `test_gh_timeout_is_retried`.
- Rerun on a tests cause asks first; on no-runner it doesn't. RCR-4, `test_rerun_asks_only_for_tests`.
- `rerun once` reruns a no-runner failure once and never a tests failure. RCR-6, `test_auto_rerun_only_once_and_never_tests`.

- [x] RCR-1: Say why a CI run failed
  Create `src/whyline/release/ci_failure.py` and `tests/release/test_ci_failure.py`. Edit `src/whyline/release/github.py`, `src/whyline/release/workflows.py`, `src/whyline/release/state.py` and their tests.
  1. `Failure(cause, run_id, workflow, attempt, job, step, url, tests, excerpt)` (a dataclass) where `cause` is one of `no-runner`, `timeout`, `tests`, `publish`, `other`, `tests` is a list of test ids, and `excerpt` is at most 20 lines.
  2. `diagnose(root, run_id, *, run) -> Failure` reads `gh run view <id> --json jobs,name,url,attempt` and, for the first failed or cancelled job, its annotations (`gh api repos/{owner}/{repo}/check-runs/<job id>/annotations`) and its log (`gh run view <id> --log-failed`, or `gh api …/actions/jobs/<id>/logs` when that is empty). Rules, first match wins:
     - `no-runner`: no step of the job has a conclusion, or an annotation mentions `not acquired by Runner` or `capacity`
     - `timeout`: an annotation says the job exceeded its time limit (`exceeded the maximum execution time`)
     - `tests`: the failed step's name contains `pytest` or `test`; `tests` are the ids after `FAILED ` in the log
     - `publish`: the failed step's name contains `publish` or `upload`
     - `other`: anything else
     If a `gh` call fails, return what is known with cause `other`.
  3. `Failure.text() -> str`: one plain sentence per cause, as in the design (for example `GitHub couldn't find a macOS machine for test (macos-latest, 3.13). Your code is fine; rerun it.`), then `<workflow>, attempt <n>`, then the test names or excerpt, then the url.
  4. `StepError` gains `failure: Failure | None = None`. `_run_outcome` in `github.py` and `wait_for_tag_run` in `workflows.py` call `diagnose` for a failed run and raise `StepError(failure.text(), failure=failure)`.
  5. `State` gains `failure` (the `Failure` as a dict, empty by default), saved when a step fails with one and cleared on success. Old state files without it still load.
  Tests: `test_never_started_job_is_no_runner` (the 2026-11-12 annotations), a timeout, `test_failed_tests_are_named`, a publish step, other, a `gh` error giving `other`, the text for each cause, both call sites raising with `failure`, and the state round trip including an old file.

- [ ] RCR-2: Don't stop on a slow gh reply
  Edit `src/whyline/release/github.py`, `src/whyline/release/workflows.py` and their tests only.
  1. While polling in `ci()` and `wait_for_tag_run`, a `subprocess.TimeoutExpired`, an `OSError` or a failing `gh run list` is retried at the normal poll interval. After 5 in a row the step stops with `GitHub didn't answer 5 times in a row; check your connection and resume`. A good reply resets the count.
  2. The detail line says `GitHub is slow to answer (2 of 5)` while retrying.
  Tests: `test_gh_timeout_is_retried` (one timeout then success keeps waiting; five stop with the message), the count resetting, and cancel during retries.

- [ ] RCR-3: Rerun failed jobs and carry on
  Edit `src/whyline/release/ci_failure.py`, `src/whyline/release/engine.py`, `src/whyline/release/cli.py` and their tests.
  1. `rerun(root, failure, *, run) -> None` runs `gh run rerun <run_id> --failed` and raises `StepError` with gh's message on failure.
  2. `rerun_and_resume(root, *, run, …)` reruns the saved `State.failure` and resumes the release at the failed step. The CI and tag-workflow waits then pick up the new attempt of the same run (its status is `queued` again), so no step changes. A rerun when the state has no failure, or no release is stopped, says `Nothing to rerun`.
  3. CLI: `whyline release why` prints `Failure.text()` of the stopped release (or `The release isn't stopped`); `whyline release rerun [--yes]` asks `Tests failed. Rerunning won't fix a real failure. Rerun anyway? [y/N]` for cause `tests` only, then calls `rerun_and_resume`.
  Tests: the rerun command, a gh error, resume reaching the next step with a fake run whose second attempt passes, nothing to rerun, `why` output, and the CLI question only for `tests`.

- [ ] RCR-4: The failure screen
  Edit `src/whyline/console/release_screens.py`, `src/whyline/console/tui.py` (where it pushes `ReleaseFailedScreen`) and their tests only.
  1. `ReleaseFailedScreen(reason, open_pr=False, failure=None)`. With a failure it shows `Failure.text()` (plain text, `markup=False`, scrollable) and the buttons **Rerun failed jobs**, **Ask an agent**, **Open run**, **Close**; **Rerun failed jobs** is the primary button for `no-runner` and `timeout`. Without one, the screen is as today (**Resume release**).
  2. **Rerun failed jobs** on cause `tests` first asks `Tests failed. Rerunning won't fix a real failure. Rerun anyway?` (Rerun / Cancel). Then it closes with a new result `RERUN`, and `tui.py` calls `ci_failure.rerun_and_resume` in a worker, showing progress in the release log as resume does today.
  3. **Open run** opens the url with the system opener, as the docs links do.
  Tests: `test_rerun_asks_only_for_tests`, the buttons with and without a failure, the primary button per cause, RERUN reaching `rerun_and_resume` with a fake, and long text scrolling.

- [ ] RCR-5: Ask an agent, then Fix with an agent
  Edit `src/whyline/release/ci_failure.py`, `src/whyline/release/cli.py`, `src/whyline/console/release_screens.py`, `src/whyline/console/tui.py` and their tests only. Read `src/whyline/release/plan.py` (`default_ask_agent`) and `src/whyline/console/fixmode.py` first.
  1. `ask(root, failure, *, ask_agent, run) -> Answer(text, needs_fix)`: the prompt holds the failure text, the failed job's log excerpt (at most 200 lines), the commits since the last tag and `git diff --stat <last tag>..HEAD`, and asks for what went wrong and what to do, between `<answer>` and `</answer>`, ending with a line `NEEDS_CODE_FIX: yes` or `no`. The agent is `default_ask_agent(root)` (read-only, temporary folder). Unmarked replies use the whole reply; a missing flag counts as `no`. The answer is appended to the release log.
  2. **Ask an agent** shows `Asking <agent>…`, then the answer in the screen. With `needs_fix`, **Fix with an agent** appears: it starts a Fix session (`fixmode`) whose context is the failure text and the answer, at the user's Fix level, so each change waits for approval and nothing is pushed. When the session ends the screen says `Start a new release when the fix is in; v<version> is already tagged.`
  3. CLI `whyline release ask` prints the answer.
  Tests: the prompt contents and size cap, `<answer>` extraction, the flag, the read-only agent used (no commit, `git status` unchanged), the Fix button only with `needs_fix`, the Fix session receiving the context, and the CLI.

- [ ] RCR-6: Rerun once when GitHub had no runner
  Edit `src/whyline/release/config.py`, `src/whyline/release/engine.py`, `src/whyline/console/release_screens.py`, `src/whyline/release/cli.py` and their tests only.
  1. `ReleaseConfig.on_no_runner: str = "ask"` (key `release.on_no_runner`, one of `ask`, `rerun once`, `off`), shown in Release → Set up as **When GitHub has no runner** and set with a new `whyline release settings [--on-no-runner <value>]` (no option prints the current Release settings), both saving through the same function.
  2. With `rerun once`, a failure with cause `no-runner` reruns automatically once per run id, logging `GitHub had no runner for <job>; rerunning once`. A second `no-runner` failure on the same run, and every other cause, show the failure screen. With `off`, the screen doesn't make Rerun the primary button.
  Tests: `test_auto_rerun_only_once_and_never_tests`, the setting round trip in the file, the screen and the CLI, and `off`.

- [ ] RCR-7: Docs
  Edit `README.md` where it describes the Release button, and the `docs/` pages on releasing.
  Cover: what each cause means, Rerun failed jobs, Ask an agent and Fix with an agent, the **When GitHub has no runner** setting, slow GitHub replies, and `whyline release why`, `rerun` and `ask`.
  Verify with `uv run pytest -q`.
