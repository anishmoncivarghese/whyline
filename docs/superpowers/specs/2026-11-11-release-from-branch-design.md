# Releasing from a relay branch: bring in main first

Status: draft for review, 2026-11-11. Runs right after `plans/sdlc-pipeline.plan.md`.

## Problem

A relay builds on its own branch (`relay/<plan>`), and the next relay usually starts from that branch, so finished plans stack up unmerged. The Release button releases whatever is checked out and publishes it with `git push origin HEAD:main`. That only works when `main` hasn't moved since the branch started. When it has (plan files committed to `main` while a relay ran, which is the normal case), the Ready check stops with `HEAD is behind origin/main` and the user has to merge by hand. Finished plans also stay in `plans/` until someone moves them.

## What the user gets

- When the checked-out branch isn't the release branch, the Release screen says where the release comes from: `Releasing relay/sdlc-pipeline.plan · 143 commits · main has 6 commits this branch doesn't`.
- A new first step, **Bring in main**:
  1. It refuses while a relay is running in this checkout, and when the working tree has changes (naming the files).
  2. It fetches and merges `origin/main` into the branch (`merge: bring main into <branch> for v<version>`), so the checks and tests run on exactly what will land on `main`.
  3. On a conflict it aborts the merge, lists the files, and stops with `Merge main into <branch> yourself (or ask an agent), then resume the release`. Nothing is left half-merged.
  4. It moves every plan in `plans/` whose tasks are all ticked, and its `.tests.md`, to `plans/done/`, and commits `chore: move finished plans to plans/done`.
  In **ask** mode it asks first, showing the commit counts and the plans it will move.
- After the push, when another checkout has the release branch checked out with no changes (for example a separate `main` folder), it is fast-forwarded to the released commit. Otherwise it says `Your main checkout at <path> has changes; update it with git pull`.
- A setting, **Bring in main before releasing** (`bring_in_main`, default on), in the console's Release settings and in `release.toml`. Off, the release behaves as today.
- `whyline release` prints the same source line and runs the same step.

## Goals

- Pressing Release after a relay finishes publishes it to `main` without manual git work, in the common case.
- Tests and security checks run on the merged code.
- Finished plans are archived as part of the release.

## Non-goals

- Resolving merge conflicts automatically.
- Releasing through a pull request. The existing protected-branch path (which offers to open a pull request) is unchanged.
- Deleting relay branches after release.

## Anti-goals

- A half-finished merge left in the tree.
- Merging while a relay is still running in the checkout.
- Moving a plan that still has unticked tasks.

## How it fits the code today

- `whyline.release.plan.build` lists the steps: `ready`, `version`, `notes`, then `github.build_steps` (commit, checks, push, CI, tag) and the targets. **Bring in main** goes before `ready`, because Ready's `synced` check (`ready._synced`) is the one that fails today.
- `github.build_steps`' push step already fast-forwards `origin/<branch>` from HEAD and stops when the remote has commits HEAD doesn't. After Bring in main, it never does.
- `relay_ops.list_plans(root)` gives each plan's done and total counts. `relay_process` / `whyline_relay.running.live(root)` says whether a relay runs here.
- `worktrees.default_branch_worktree(root)` (WTD-1, in the SDLC plan) finds another checkout of the release branch.
- New code: `src/whyline/release/source.py`, with tests in `tests/release/`.
