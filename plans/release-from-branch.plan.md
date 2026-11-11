<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-11T09:00:00+05:30 -->
# Releasing from a relay branch: bring in main first

Runs after `plans/sdlc-pipeline.plan.md` and before `plans/raaid-log.plan.md`. Design: `docs/superpowers/specs/2026-11-11-release-from-branch-design.md`. Read it before any task.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

What the user gets:
- Pressing **Release** after a relay finishes merges `main` into the relay's branch first, so checks run on what will land, then publishes to `main` as today.
- Finished plans move to `plans/done/` as part of the release.
- A separate checkout of `main` is fast-forwarded after the push when it has no changes.
- **Bring in main before releasing** can be turned off in Release settings.

There is no publish task. When the relay finishes, press **Release**: it sets the version, writes the notes, runs the checks, pushes, waits for CI, tags and publishes. (This repository's relay has no `release` profile, so a `relay-profile: release` task would only bump the version.)

Rules every task keeps:
- Console first: every console action saves through the same function the CLI calls.
- No new dependency. Git runs through the `run` callable the release code already injects, so tests use a fake `run` or a temporary repository, never the network.
- Never leave a merge half-done: on any failure after `git merge` starts, run `git merge --abort`.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.

Review focus, each one pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A conflict: the merge is aborted, the tree is clean, and the step stops naming the files. RFB-2, `test_conflict_aborts_and_names_files`.
- A relay running in the checkout: refused before anything changes. RFB-2, `test_refused_while_relay_runs`.
- A plan with one unticked task: not moved. RFB-2, `test_unfinished_plan_stays`.

- [ ] RFB-1: Where the release comes from
  Create `src/whyline/release/source.py` and `tests/release/test_source.py`. Edit `src/whyline/release/config.py` and its tests to add `bring_in_main: bool = True` (key `release.bring_in_main`), written by `config.save`.
  1. `source(root, cfg, *, run, fetch) -> Source(branch, on_release_branch, ahead, behind, finished_plans)`:
     - `branch` from `git rev-parse --abbrev-ref HEAD`; `on_release_branch` when it equals `cfg.branch`
     - after `fetch(root, cfg.branch)`, `ahead` and `behind` from `git rev-list --left-right --count HEAD...origin/<branch>`
     - `finished_plans`: paths from `relay_ops.list_plans(root)` in `plans/` (not `plans/done/`) with `total > 0` and `done == total`
  2. `Source.line() -> str`: `Releasing <branch> · <ahead> commits · main has <behind> commits this branch doesn't`, leaving out the last part when `behind` is 0, and just `Releasing <branch>` on the release branch.
  Tests with a temporary repository and a fake fetch: on main, on a branch ahead only, ahead and behind, the finished plans list ignoring `plans/done/` and unfinished ones, the line text, and the config key round trip.

- [ ] RFB-2: The Bring in main step
  Edit `src/whyline/release/source.py`, `src/whyline/release/plan.py` and their tests only.
  1. `bring_in_main(root, cfg, version, *, run, fetch, relay_running) -> str` (a summary):
     - refuses with `A relay is running here; release when it finishes` when `relay_running(root)` (`test_refused_while_relay_runs`), and with `Commit or stash these first: <files>` when `git status --porcelain` is not empty
     - fetches, then when `behind > 0` runs `git merge --no-ff origin/<branch> -m "merge: bring main into <branch> for v<version>"`. On failure it reads the conflicted files (`git diff --name-only --diff-filter=U`), runs `git merge --abort`, and raises `StepError("Merge main into <branch> yourself (or ask an agent), then resume the release. Conflicts: <files>")` (`test_conflict_aborts_and_names_files`)
     - then `git mv`s each finished plan and its `.tests.md` (when present) into `plans/done/`, and commits `chore: move finished plans to plans/done` when anything moved (`test_unfinished_plan_stays`)
  2. In `plan.build`, when `cfg.bring_in_main` is on and HEAD is not on `cfg.branch`, a step `Step("bring-in-main", "Bring in main", True, done, run)` comes first. `done` is true when `behind == 0` and `finished_plans` is empty. It is irreversible, so ask mode confirms it, and the confirmation text is `Source.line()` plus `Moves to plans/done: <names>`.
  3. `relay_running` defaults to `whyline_relay.running.live(root)`.
  Tests in a temporary repository: a clean merge with tests running after it (a fake check sees the merged file), `test_conflict_aborts_and_names_files` with a clean tree afterwards, `test_refused_while_relay_runs`, the dirty-tree refusal, plans moved and committed, `test_unfinished_plan_stays`, the step absent on the release branch and when the setting is off, and `done` skipping a resumed run.

- [ ] RFB-3: Update the other main checkout after the push
  Edit `src/whyline/release/github.py` and its tests only.
  After a successful push in `build_steps`, when `worktrees.default_branch_worktree(root)` returns a checkout other than `root`:
  - with no changes there (`git status --porcelain` empty), run `git -C <it> merge --ff-only origin/<branch>` after a fetch, and report `Updated <path> to v<version>`
  - otherwise report `Your <branch> checkout at <path> has changes; update it with git pull`
  A failure here is a warning, never a failed release.
  Tests: a clean other checkout fast-forwarded, a dirty one left alone with the message, none found, and a failing merge reported as a warning.

- [ ] RFB-4: Bring in main in the console and the CLI
  Edit `src/whyline/console/release_screens.py`, `src/whyline/release/cli.py` and their tests only.
  1. The Release screen shows `Source.line()` above the steps, and `Moves to plans/done: …` when there are finished plans. The ask-mode confirmation for the step uses the same text.
  2. Release settings get **Bring in main before releasing** (default on), saved through `config.save`.
  3. `whyline release` prints the same line before the steps, and `--no-bring-in` turns the step off for that run.
  Tests: the line on a branch and on main, the settings checkbox round trip, the CLI line, and `--no-bring-in`.

- [ ] RFB-5: Docs
  Edit `README.md` where it describes the Release button, and `docs/` pages on releasing.
  Cover: releasing right after a relay, what Bring in main does and when it stops, conflicts, plans moved to `plans/done/`, the other main checkout, and the setting.
  Verify with `uv run pytest -q`.
