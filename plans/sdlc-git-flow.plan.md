<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-sdlc-upgrade-design.md | created: 2026-11-14T20:00:00+05:30 -->
# SDLC git flow: start from the latest main, and reach main through a pull request

Spec: `docs/superpowers/specs/2026-11-14-sdlc-upgrade-design.md`, Part 1. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **Publish plan (plan-only pull requests) is not built here.** In Pull request flow a plan-only commit rides on the next relay branch, or the user pushes it. It is a follow-up.
- **The acceptance table, evidence and checklist in the pull request body** arrive with the later plans. This plan's body holds the notes, the plan and its tasks, and the document set links.

Runs after `plans/raaid-log.plan.md`, and before `plans/sdlc-product-owner.plan.md`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: a relay branches from whatever is checked out and never fetches, so "HEAD is behind origin/main" only shows at release time. `main` is not protected, and no pull request has ever been opened: Release pushes straight to `main`.

What the user gets:
- Starting a relay first brings the checkout up to date with GitHub, or says clearly why it can't.
- A per-repository setting, **How work reaches main**: **Direct** (the default, today's way) or **Pull request**.
- With Pull request: Release pushes the branch, opens a pull request, waits for its checks, and merges after the user confirms.
- An optional **Protect main on GitHub** switch.

Rules every task keeps:
- **Console first.** Every setting and action has a console counterpart saving through the same function as its CLI command.
- **Direct flow is unchanged.** With the setting at Direct, a release takes exactly today's steps. Tests pin this.
- **Nothing outward without the user.** Opening a pull request and merging are irreversible steps: ask and step modes confirm them, as they confirm push and tag today. Protecting `main` always asks, in every mode.
- **Never force.** No `--force`, no history rewrite, no deleting a branch that isn't merged.
- **`gh` and git are called with argv lists** through the release's existing `run`, with its timeouts and RCR's retries.
- **No new dependency.**
- **Tests:** never call a real `gh`, a remote or a relay. Use the fake `run` and `fetch` the release tests use. Never sleep. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- With flow Direct, the release's step ids and order are exactly today's. GIT-3, `test_direct_flow_is_unchanged`.
- A relay never starts on top of a stale `main` silently: it fast-forwards, or stops with the reason. GIT-1, `test_stale_main_is_updated_or_refused`.
- Offline, starting still works and says so. GIT-1, `test_offline_start_goes_on`.
- Merge never runs with failing or pending checks, and never without the confirm in ask and step modes. GIT-4, `test_merge_needs_green_checks_and_confirm`.
- Protecting `main` is never done without the user's yes, and Undo restores the earlier state. GIT-5, `test_protect_asks_and_undoes`.

- [ ] GIT-1: Bring the checkout up to date before a relay starts
  Create `src/whyline/gitflow.py` and `tests/test_gitflow.py` only.
  1. `@dataclass(frozen=True) class Fresh`: `state` and `detail`. `state` is one of `current`, `updated`, `behind_dirty`, `diverged`, `off_main`, `offline`, `no_remote`.
  2. `freshen(root, *, run=…, fetch=…) -> Fresh`:
     - no `origin` remote: `no_remote`
     - the fetch of `origin/<default branch>` fails: `offline`, detail `Couldn't reach GitHub; starting from your local <branch>`
     - HEAD is not on the default branch: `off_main`, detail `You're on <branch>, <n> commits behind origin/<default>` (or `up to date with`)
     - on the default branch and equal to origin: `current`
     - behind with a clean tree and no local-only commits: `git merge --ff-only origin/<branch>`, then `updated`, detail `Brought in <n> commits from GitHub`
     - behind with a dirty tree: `behind_dirty`, naming up to 5 changed files
     - local commits that origin doesn't have: `diverged`, detail `<n> local commits aren't on GitHub`
  3. The default branch comes from `whyline.release.config` (`ReleaseConfig.branch`) when a release config exists, else `origin/HEAD`, else `main`.
  4. `may_start(fresh) -> bool`: True for `current`, `updated`, `offline`, `no_remote`.
  Tests: `test_stale_main_is_updated_or_refused`, `test_offline_start_goes_on`, each state with a fake `run`, and that nothing but `fetch` and `merge --ff-only` is ever run.

- [ ] GIT-2: Use it wherever a relay starts
  Edit `src/whyline/console/tui.py` (`_launch_relay` for `start`), `src/whyline/console/auto_run.py`, `src/whyline/ideas/run.py`, `src/whyline/cli.py` (the `relay` command's `start`), and their tests.
  1. One function `gitflow.before_start(root, *, run, fetch) -> Fresh` is called before `start` in all four places. It is not called for `resume`.
  2. Console: `updated`, `offline` and `off_main` print their detail and start. `behind_dirty` and `diverged` show a dialog with the detail and:
     - **Push them first** (diverged only): pushes after a confirm, then freshens again
     - **Start anyway**
     - **Cancel**
  3. CLI `whyline relay start`: prints the detail. `behind_dirty` and `diverged` stop with exit code 2 and the line `Use --stale-ok to start anyway.` `--stale-ok` starts.
  4. Unattended starts (`auto_run`, `ideas/run.py`): `behind_dirty` and `diverged` do not start. Auto pauses with the detail as its reason. An idea's `do` replies with the detail.
  5. A setting `start_from_latest` (default on) in the relay Settings screen and `whyline relay settings` turns the check off.
  Tests: each entry point calls `before_start` once and not on resume, the dialog's three choices, the CLI exit code and `--stale-ok`, the unattended pause, and the setting off skips the fetch.

- [ ] GIT-3: The flow setting, and Direct unchanged
  Edit `src/whyline/release/config.py`, `src/whyline/release/cli.py`, `src/whyline/console/release_screens.py` and their tests.
  1. `ReleaseConfig.flow: str = "direct"` (`direct` or `pr`) and `require_approval: bool = False`, read from and written to the release config file like the other fields. An unknown value is a `ConfigError`.
  2. CLI: `whyline release settings flow direct|pr` and `whyline release settings require-approval on|off`.
  3. Release → Set up: a **How work reaches main** choice (**Direct** / **Pull request**) with one line under each saying what it does, and a **Require my approval on GitHub** checkbox shown only for Pull request. Both save through the function the CLI calls.
  Tests: `test_direct_flow_is_unchanged` (the built step ids for a config with `flow="direct"` equal the list the test fixes from today's `plan.build`), round trip of both fields, an unknown flow refused, and CLI and console saving through one function.

- [ ] GIT-4: Pull request flow in Release
  Create `src/whyline/release/pullrequest.py` and `tests/release/test_pullrequest.py`. Edit `src/whyline/release/github.py`, `src/whyline/release/plan.py`, `src/whyline/sdlc/close.py` and their tests.
  1. `pullrequest.body(root, cfg, version, *, notes_path, plan_path, docset) -> str`: the release notes, the plan's name with its ticked and unticked task lines, and, when a document set owns the plan, the links `sdlc.close.pr_body` builds. `close.pr_body` is split so both use one function.
  2. `pullrequest.ensure(root, branch, base, title, body, *, run) -> PullRequest` (`number`, `url`). It finds an open pull request for the branch (`gh pr list --head <branch> --base <base> --state open --json number,url`) and edits it (`gh pr edit`), or creates one (`gh pr create --base --head --title --body-file`).
  3. `pullrequest.checks(root, number, *, run) -> Checks` (`state`: `passing`, `failing`, `pending`, `none`; `failed`: names) from `gh pr checks <number> --json name,state,bucket`.
  4. With `cfg.flow == "pr"`, `build_steps` replaces `push` with:
     - `push_branch`: pushes the current branch to `origin`, with upstream. Irreversible. Done when origin's branch equals HEAD.
     - `open_pr`: `ensure`. Done when an open pull request's head is HEAD.
  5. `ci` waits on `checks` until passing. A failure raises `StepError` with a `ci_failure` diagnosis of the failed check's run, so RCR's Why, Rerun and Ask an agent work.
  6. A new step `merge` before `tag`, irreversible: it refuses unless checks are `passing`. With `require_approval` it also needs an approving review, else `Waiting for your approval on GitHub: <url>`. It runs `gh pr merge <number> --merge --delete-branch`, then fetches and checks that `origin/<base>` contains HEAD. Done when the pull request is merged.
  7. The Telegram go-ahead (`whyline.ideas.goahead`, from `plans/waiting-on-you.plan.md` WAIT-5) gets the short verbs for the new steps: `push the branch` for `push_branch`, `open the pull request` for `open_pr` and `merge` for `merge`. Edit `src/whyline/ideas/goahead.py` and its tests for this.
  8. `tag` and later steps then act on `origin/<base>`'s merge commit: the release checks out nothing, and tags that commit by its sha.
  Tests: `test_merge_needs_green_checks_and_confirm`, the step ids and order for `flow="pr"`, `ensure` creating and editing, `checks` for each state, a failing check giving a `StepError` with a `failure`, a resumed release skipping finished steps, the tag made on the merge commit, and `require_approval` waiting.

- [ ] GIT-5: Protect main on GitHub
  Edit `src/whyline/release/setup_github.py`, `src/whyline/release/cli.py`, `src/whyline/console/release_screens.py` and their tests.
  1. `branch_protection(owner_repo, branch, *, run) -> dict | None`: the current rule from `gh api repos/<owner_repo>/branches/<branch>/protection`, None when there is none, and `UNAVAILABLE` text when GitHub refuses (a private repository on a free plan).
  2. `protect_branch(owner_repo, branch, checks: list[str], *, run) -> str`: saves the earlier state to `.git/whyline-release/protection-before.json`, then `PUT`s a rule: pull request required with 0 approvals (1 with `require_approval`), the given status checks required, no force pushes, no deletions, administrators not exempt. Returns "" or the reason.
  3. `unprotect_branch(owner_repo, branch, *, run) -> str`: restores the saved earlier state (deleting the rule when there was none before).
  4. The required checks are the check names of the latest successful run on the branch, shown to the user before saving.
  5. Console, in Release → Set up, shown only when flow is Pull request: `main is not protected` with **Protect main…**, which shows exactly what will be set and asks, or `main is protected` with **Undo**. CLI: `whyline release setup protect` and `whyline release setup unprotect`, each asking unless `--yes`.
  Tests: `test_protect_asks_and_undoes`, the exact `PUT` payload, the unavailable case with its reason, the earlier state saved and restored, and the option hidden for Direct flow.

- [ ] GIT-6: Branch cleanup and docs
  Edit `src/whyline/release/plan.py` (the `after` step), `src/whyline/console/release_screens.py`, `docs/release.md`, `docs/relay.md` (or the page on running a relay), `README.md` and their tests.
  1. After a Pull request release, the `after` step lists local `relay/*` branches that are fully merged into `origin/<base>`, other than the current one, and says `<n> merged branches can be removed` with a **Clean up** button. It deletes them with `git branch -d` only, never `-D`.
  2. Docs cover: starting from the latest main and the stale dialog, the two flows, the pull request steps, **Merge**, protecting `main` and undoing it, and what stays the same in Direct.
  Tests: only fully merged branches are listed, `-d` is used, the current branch is never listed, and Direct flow shows no cleanup line.
  Verify with `uv run pytest -q`.
