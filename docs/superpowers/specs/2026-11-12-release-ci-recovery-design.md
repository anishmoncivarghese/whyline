# Release CI recovery: say why it failed, rerun, ask an agent

Status: draft for review, 2026-11-12. Runs after `plans/done/release-from-branch.plan.md`, before `plans/raaid-log.plan.md`.

## Problem

When a release's GitHub Actions run fails, the Release screen shows one line, for example `Publish to PyPI failed: release.yml failed in job test (macos-latest, 3.13) <url>`, with **Resume release** and **Close**. It doesn't say why. On 2026-11-12 (v0.3.72) the cause was GitHub's: the job was never given a macOS machine (`The job was not acquired by Runner of type hosted even after multiple attempts`) and was cancelled after 15 minutes. No test failed. The fix was `gh run rerun <id> --failed`, which whyline doesn't offer. Resume only re-reads the same failed run.

A slow `gh` reply also stops a release: `default_run` gives every command 30 seconds, and one timeout while polling raised a StepError (the 0.3.71 crash).

## What the user gets

When the **Wait for CI** step or a target's workflow wait (PyPI's `release.yml`) fails, the failure screen shows:

1. **Why, in plain words.** Whyline reads the failed jobs and their GitHub annotations and sorts the failure into one cause:
   - **GitHub had no runner**: a job cancelled or failed without starting its steps, or with an annotation about runners or capacity. `GitHub couldn't find a <os> machine for test (macos-latest, 3.13). Your code is fine; rerun it.`
   - **Timed out**: a job ended by its time limit. Names the job and the step it was in.
   - **Tests failed**: a failed step whose name runs the tests. Names the failing tests (lines starting `FAILED ` in the job log) and shows the first error lines, at most 20.
   - **Publish failed**: the failed step is the publish step (PyPI upload). Shows its last lines and points to Release → Set up.
   - **Something else**: the failed job and step names and the last 20 log lines.
   Each cause also names the run (`release.yml, attempt 1`) and keeps the link.
2. **Buttons:**
   - **Rerun failed jobs**: `gh run rerun <id> --failed`, then the release continues by itself: it waits for the new attempt and goes on to the next step (PyPI). It is the main button for a runner or timeout cause. For tests failed it asks first: `Tests failed. Rerunning won't fix a real failure. Rerun anyway?`
   - **Ask an agent**: a read-only agent gets the cause, the failed job's log excerpt (at most 200 lines), and the release's commit list and diff stat, and answers what went wrong and what to do. Its answer is shown in the screen and kept in the release log. It never edits, commits or reruns.
   - **Fix with an agent** (shown after an answer that says code must change): opens the existing Fix flow with the cause and the answer as its context. Every change waits for approval and nothing is pushed. After a fix the user starts a new release: the version is already tagged, so it won't move the tag.
   - **Open run** and **Close**, as today. **Resume release** stays for the other failures.
3. **Automatic rerun for GitHub's own problems**, a Release setting **When GitHub has no runner**: `ask` (default: show the screen), `rerun once` (rerun the failed jobs once without asking, saying so in the log; a second runner failure shows the screen), or `off` (show the screen with no automatic action and no rerun suggestion). Real test failures are never rerun automatically.
4. **Slow `gh` replies don't stop a release.** While waiting for CI, a `gh` timeout or a network error is retried (up to 5 times in a row, the normal poll interval apart) before the step stops, and then the message says `GitHub didn't answer`.
5. From a terminal: `whyline release why` prints the cause of the stopped release; `whyline release rerun` reruns the failed jobs and resumes; `whyline release ask` prints the agent's answer. Same functions as the screen.

## Goals

- A GitHub hiccup costs one button press, or none with `rerun once`.
- A real failure is explained without opening GitHub.
- Nothing reruns, edits or pushes without either the user's press or the setting they chose.

## Non-goals

- Fixing code automatically or moving a tag that's already pushed.
- Other CI systems than GitHub Actions.
- Recovering the earlier steps (push, tag); they already have their own messages.

## Anti-goals

- Rerunning a real test failure without asking.
- An agent that changes files or reruns from the Ask button.
- A whole job log in the screen or the prompt.

## How it fits the code today

- `whyline.release.github`: `ci()` in `build_steps` polls `gh run list --commit`; `_run_outcome` turns a failed run into `StepError(f"CI failed: …")`.
- `whyline.release.workflows.wait_for_tag_run` polls a tag's workflow (PyPI's `release.yml`) and raises `StepError(f"{name} failed in job {job} {url}")`, finding the job with `_failed_job`.
- `StepError(message, open_pr=…)` in `github.py` carries only text. `whyline.release.state.State` saves `failed_id` and `reason`.
- `ReleaseFailedScreen` in `console/release_screens.py` returns `RESUME` or `OPEN_PR`; `tui.py` (around `ReleaseFailedScreen(result.message, …)`) handles them.
- `whyline.release.plan.default_ask_agent(root)` already runs the chat agent once, read-only, in a temporary folder (RFB-8). Ask an agent reuses it.
- Fix flow: `whyline.console.fixmode` (`Session`, `run_fix`), used today for relay pauses.
- Release settings: `ReleaseConfig` in `release/config.py`, the Set up checkboxes in `release_screens.py`, and `release/cli.py`.
- New code: `src/whyline/release/ci_failure.py`.

## Calls I made (please check)

- `rerun once` is not the default; `ask` is. A rerun uses GitHub minutes and can queue a long time, so the first time it's the user's press.
- Ask an agent is read-only and separate from Fix, so asking is always safe.
- After a code fix the user starts a new release (a new version). Whyline never moves a pushed tag.
- `whyline release ask` exists so the console and the terminal match (console first, in reverse).
