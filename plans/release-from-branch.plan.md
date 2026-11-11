<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-11T09:00:00+05:30 -->
# Releasing from a relay branch: bring in main first

Runs after `plans/sdlc-pipeline.plan.md` and before `plans/raaid-log.plan.md`. Design: `docs/superpowers/specs/2026-11-11-release-from-branch-design.md`. Read it before any task.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

What the user gets:
- Pressing **Release** after a relay finishes merges `main` into the relay's branch first, so checks run on what will land, then publishes to `main` as today.
- Finished plans move to `plans/done/` as part of the release.
- A separate checkout of `main` is fast-forwarded after the push when it has no changes.
- **Bring in main before releasing** can be turned off in Release settings.
- Release → Set up shows each target's last check result instead of a fixed "Not checked", with no blank rows (RFB-5).
- When the current version has never been released, Release offers it first, so a version a plan already set isn't skipped (RFB-6).
- The security scan stops warning about its own test fixtures, and a secret found in a test file says how to allow a fake value (RFB-7).

- Release notes are written by an agent that can't change or commit anything, only the notes themselves are kept, and you see them before confirming (RFB-8, added 2026-11-11 after 0.3.70 went out with the agent's own narration at the top, a version commit named "chat: grok turn", and 0.3.69 skipped).

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
- An agent reply with text before or after the notes: only the notes are published. RFB-8, `test_notes_keep_only_the_marked_part`.
- Writing the notes during a release: no commit appears and no file outside the notes changes. RFB-8, `test_notes_agent_cannot_commit`.

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

- [ ] RFB-5: Target status in Release → Set up
  Edit `src/whyline/console/release_screens.py`, `src/whyline/release/state.py` and their tests only.
  1. Each target row's status comes from the last time its ready items ran (in Check or Set up): `✓ Ready · checked <date>` or `✗ <first failing item>`, saved per repository with the time. A target never checked says `Not checked yet`; an unticked target says nothing.
  2. Opening Set up starts a background check of the ticked targets (the same `ready_items` Release → Check uses) and updates the rows as results arrive.
  3. Rows are one line high when there is no status, so unticked targets leave no blank space. The tab bar at the top of Release and Security sits directly above the content, with no empty band.
  Tests: a saved result shown after reopening, `Not checked yet`, the background check updating a row, an unticked target with no status, and the row height with no status.

- [ ] RFB-6: Offer an unreleased current version first
  Edit `src/whyline/console/release_screens.py`, `src/whyline/release/cli.py`, `src/whyline/release/version.py` and their tests only.
  1. `version.released(root, version, *, run) -> bool` is true when tag `v<version>` exists locally or on origin (`git ls-remote --tags origin v<version>`).
  2. When the current version is not released, the version select defaults to `current → <version> (not released yet)`, listed first, and the screen's first line reads `Current version: 0.3.69 (not released yet)`. When it is released, the default stays `patch`.
  3. `whyline release run` with no `--bump` or `--version` uses the unreleased current version, and prints which it chose.
  Tests: an untagged current version chosen by default in the screen and the CLI, a tagged one keeping `patch`, and a tag only on origin counting as released.

- [ ] RFB-7: Test fixtures and fake secrets in the security scan
  Edit `src/whyline/security/deps.py`, `src/whyline/security/settings.py`, `src/whyline/security/contents.py`, `src/whyline/console/security_screens.py` and their tests only (and read `release_config.add_pending`).
  1. A `[security]` setting `skip_paths` (a list of glob patterns, default `["tests/**/fixtures/**"]`) that the dependency scan skips when it looks for lockfiles. It is shown and edited in the Security settings. The secrets and contents scans do not use it: a real secret in a test still blocks.
  2. A secret finding whose path is under `tests/` (or inside a built package, under `<name>-<version>/tests/`) adds one line: `This is in a test. If it is a fake value, Allow it with the reason "Fake value in a test".` **Allow…** opens with that reason filled in, still editable and still required.
  3. A finding inside a built package is fingerprinted by its path inside the package without the version folder: `whyline-0.3.69.tar.gz:whyline-0.3.69/tests/x.py` and the wheel's `tests/x.py` both become `<package>:tests/x.py`, so an Allow made for one version still applies to the next. The shown path keeps the full name. Existing allowlist entries with a versioned path still match that exact version.
  4. `settings.allow` marks `.whyline/security-allow.toml` with `release_config.add_pending`, so Release's clean-tree check accepts it and the release commit includes it, instead of failing with `Uncommitted changes: .whyline/security-allow.toml`.
  Tests: a vulnerable lockfile under `tests/security/fixtures/` skipped and one elsewhere still reported, the setting round trip, a secret in a test still blocking with the extra line, the prefilled reason, a secret outside `tests/` with no extra line, Release's clean check passing right after an Allow, and an Allow made on a 0.3.69 sdist finding still applying to the 0.3.70 sdist.

- [ ] RFB-8: Safe release notes
  Edit `src/whyline/release/plan.py`, `src/whyline/release/notes.py`, `src/whyline/release/cli.py`, `src/whyline/console/tui.py` (the release `confirm_notes`), `src/whyline/console/release_screens.py` and their tests only.
  1. `default_ask_agent` stops using `whyline_relay.chat.run_turn`, which can edit files and commits the tree as `chat: <agent> turn`. It runs the agent once, read-only, in a fresh temporary folder, through `capabilities.read_only_command` and `whyline_relay.agents.run`, the way `relaychat.ask.ask` does, with the commit subjects and the style example in the prompt (`test_notes_agent_cannot_commit`: HEAD and `git status` are unchanged after drafting).
  2. `build_prompt` ends with `Put the notes between a line <notes> and a line </notes>. Write nothing else.` `notes.extract(text) -> str | None` returns what is between the last such pair, stripped. With no pair, or an empty one, `draft` uses `fallback(version, commits)` and the release log says `The agent's notes were not usable; using the commit list` (`test_notes_keep_only_the_marked_part`).
  3. In ask mode the notes confirmation shows the notes text (scrollable) with **Use these notes**, **Edit** (opens the file in the editor, then shows it again) and **Stop**. `whyline release run` prints the first 40 lines and asks `Use these notes? [y/N/e]`. `--yes` skips the question, as today.
  4. When the version chosen is a bump but `docs/releases/v<current>.md` exists and `v<current>` isn't released (`version.released` from RFB-6), Release asks `v<current> has notes and was never released. Release v<current> instead?` before starting, defaulting to Yes.
  Tests: the read-only command used and no commit made, extract with text before and after, a missing or empty pair falling back, the confirmation showing the text and each button, the CLI prompt, and the unreleased-version question.

- [ ] RFB-9: Docs
  Edit `README.md` where it describes the Release button, and `docs/` pages on releasing.
  Cover: releasing right after a relay, what Bring in main does and when it stops, conflicts, plans moved to `plans/done/`, the other main checkout, the setting, target status in Set up, an unreleased current version, `skip_paths` and allowing fake test secrets, and how release notes are written and checked.
  Verify with `uv run pytest -q`.
