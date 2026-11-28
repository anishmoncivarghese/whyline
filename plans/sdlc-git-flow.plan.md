<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-sdlc-upgrade-design.md | created: 2026-11-14T20:00:00+05:30 | revised: 2026-11-22 -->
# SDLC git flow: each plan in its own worktree, one pull request per plan, and Park and Reopen

Spec: `docs/superpowers/specs/2026-11-14-sdlc-upgrade-design.md`, Part 1 and Part 1b (revised 2026-11-22). Read both before every task. Where this plan and the spec differ, this plan wins. In particular:
- **Publish plan (plan-only pull requests) is not built here.** Plan-only commits go straight to `main` while it is unprotected. It is a follow-up.
- **The acceptance table, evidence and checklist in the pull request body** arrive with the later sdlc plans. This plan's body holds the plan, its tasks, and the document set links.

Runs after `plans/raaid-log.plan.md`, and before `plans/sdlc-product-owner.plan.md`. Needs `plans/telegram-daily-use.plan.md` (WAIT, for the "ready to merge" card and the go-ahead verbs).

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: a relay branches from whatever is checked out and never fetches, so "HEAD is behind origin/main" only shows at release time. The relay works in the project folder itself, so Release has to bring `main` into the relay branch; on 2026-11-21 that merge made the v0.3.77 release loop on "Commit the release" and refuse its push. Nothing reaches `main` through a pull request. And a finished project can't be safely removed from the laptop and brought back.

What the user gets (decided by the user on 2026-11-22):
- **Deliver as** in Relay → Set up: **Pull request** (the default for projects already on GitHub) or **Straight to main** (today's way; the only choice for a project not on GitHub yet).
- With Pull request, each plan runs in its own worktree on `relay/<plan>`, made from the latest `origin/main`. The project folder stays on `main`.
- When the relay finishes, whyline opens one pull request for the plan. **Merge** in the console merges it, updates `main`, removes the worktree and comes back to the project.
- **Who merges**: **You** (the default: nothing reaches `main` until the user presses Merge) or **Automatic** (merges once checks pass, then says so).
- Release runs from `main`. Its version bump goes straight to `main`, unless `main` is protected, when it goes through its own small pull request.
- **Projects**, **Park** and **Reopen**: a list of projects; Park saves whyline's local files compressed and moves the folder to the Trash after checking nothing exists only on the laptop; Reopen clones it back and restores them.

Rules every task keeps:
- **Console first.** Every setting and action has a console counterpart saving through the same function as its CLI command.
- **Straight to main is unchanged.** With Deliver as Straight to main, a relay start and a release take exactly today's steps. Tests pin this.
- **Nothing outward without the user.** Opening a pull request, merging, protecting `main`, parking and reopening are confirmed in ask and step modes. With Who merges set to You, Merge needs the user's click in every mode, Auto included. Park always asks, in every mode.
- **Never force.** No `--force`, no history rewrite, no `git branch -D`, no removing a worktree with changes.
- **`gh` and git are called with argv lists** through the release's existing `run`, with its timeouts and RCR's retries.
- **No whyline-relay change.** The relay is started in the worktree with `--branch relay/<name>`; it keeps all its files under the folder it starts in.
- **No new dependency.**
- **Tests:** never call a real `gh`, a remote or a relay. Use the fake `run` and `fetch` the release tests use, or a real git repository in `tmp_path` with a bare repository as `origin`. Point `Path.home()` at `tmp_path` so nothing touches the real `~/.whyline`. Never sleep. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- With Deliver as Straight to main, a relay start and the release's step ids and order are exactly today's. GIT-3, `test_straight_to_main_is_unchanged`.
- A relay never starts on top of a stale `main` silently: it fast-forwards, or stops with the reason. GIT-1, `test_stale_main_is_updated_or_refused`.
- Merge never runs with failing or pending checks, and with Who merges You never without the user's click, in any mode. GIT-8, `test_merge_needs_green_checks_and_the_user`.
- A worktree with uncommitted changes or a branch that isn't merged is never removed. GIT-8, `test_merge_cleanup_never_loses_work`.
- Park refuses while anything exists only on the laptop, and never runs without the user's yes. GIT-14, `test_park_check_finds_every_blocker`; GIT-15, `test_park_asks_and_saves_local_files`.

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
  5. `on_github(root, *, run=…) -> str`: "" when `origin` is a github.com remote and `origin/<default>` exists, else the reason (`Not on GitHub yet; publish it first`, or `origin isn't on GitHub`).
  Tests: `test_stale_main_is_updated_or_refused`, `test_offline_start_goes_on`, each state with a fake `run`, that nothing but `fetch` and `merge --ff-only` is ever run, and `on_github` for a GitHub remote, a non-GitHub remote and no remote.

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

- [ ] GIT-3: Deliver as and Who merges settings
  Create `src/whyline/delivery.py` and `tests/test_delivery.py`. Edit `src/whyline/cli.py`, `src/whyline/console/relay_screens.py` (`RelaySetupScreen`), `src/whyline/console/settings_screen.py` and their tests.
  1. `deliver_as(root) -> str` (`pr` or `direct`): the saved value in `.whyline/delivery.toml` (`deliver = "pr" | "direct"`), else `pr` when `gitflow.on_github(root)` is "" and `direct` otherwise. A saved `pr` on a project that isn't on GitHub reads as `direct`. `save_deliver_as(root, value)` refuses `pr` with the `on_github` reason. Any other value raises `ValueError` naming it.
  2. `who_merges() -> str` (`you` or `auto`, default `you`) and `save_who_merges(value)`, in `~/.whyline/delivery.json` (global, not per project). `run_who_merges` overrides it for one relay run, stored with the run's other settings in `.whyline/relay/` (ignored by git).
  3. CLI: `whyline relay settings deliver pr|direct`, `whyline settings who-merges you|auto`.
  4. Relay → Set up: a **Deliver as** choice (**Pull request** / **Straight to main**), with one line under each saying what it does. When the project isn't on GitHub, Pull request is disabled with the reason. Under it, **Who merges** (**You** / **Automatic**) for this run, defaulting to the global value. Settings gets the global **Who merges**. Both save through the functions above.
  Tests: `test_straight_to_main_is_unchanged` (with `direct`, the relay start argv and the release's step ids equal the lists the test fixes from today's code), the default for on-GitHub and not-on-GitHub projects, `pr` refused off GitHub, the per-run override, unknown values refused, and CLI and console saving through one function.

- [ ] GIT-4: Pull request helpers
  Create `src/whyline/release/pullrequest.py` and `tests/release/test_pullrequest.py`. Edit `src/whyline/sdlc/close.py` and its tests.
  1. `body(root, *, plan_path, docset=None) -> str`: the plan's title, its ticked and unticked task lines, and, when a document set owns the plan, the links `sdlc.close.pr_body` builds. `close.pr_body` is split so both use one function.
  2. `ensure(root, branch, base, title, body, *, run) -> PullRequest` (`number`, `url`). It finds an open pull request for the branch (`gh pr list --head <branch> --base <base> --state open --json number,url`) and edits it (`gh pr edit`), or creates one (`gh pr create --base --head --title --body-file`).
  3. `checks(root, number, *, run) -> Checks` (`state`: `passing`, `failing`, `pending`, `none`; `failed`: names) from `gh pr checks <number> --json name,state,bucket`.
  4. `merge(root, number, *, run) -> str`: refuses unless `checks` is `passing`, runs `gh pr merge <number> --merge --delete-branch`, and returns the merge commit's sha from `gh pr view <number> --json mergeCommit`.
  5. `state(root, number, *, run) -> str`: `open`, `merged` or `closed`.
  Tests: `ensure` creating and editing, `checks` for each state, `merge` refusing on `failing`, `pending` and `none`, the exact argv of each call, and the body with and without a document set.

- [ ] GIT-5: A worktree for each plan
  Edit `src/whyline/worktrees.py` and `tests/test_worktrees.py` only.
  1. Add the kind `relay` to `KINDS`. `make(root, "relay", plan_name, base="origin/main")` makes the branch `relay/<name>` (with the existing `-2`, `-3` suffix on a clash) from `base`, at `~/.whyline/worktrees/<project>/relay-<name>`. `base` defaults to today's behaviour for the other kinds.
  2. `for_plan(root, plan_name) -> Worktree | None`: the existing relay worktree for that plan, so a second Run resumes it instead of making another.
  3. `branch_merged(root, branch, base) -> bool`: True when `origin/<base>` contains the branch's tip.
  Tests with a real repository in `tmp_path` and a bare `origin`: the branch name and path, starting from `origin/main` when the local `main` is behind, `for_plan` finding it, the suffix on a clash, and `branch_merged` before and after a merge.

- [ ] GIT-6: Run a plan in its worktree
  Edit `src/whyline/console/tui.py` (`_launch_relay`), `src/whyline/console/relay_process.py`, `src/whyline/cli.py` and their tests.
  1. When `delivery.deliver_as(root) == "pr"` and the command is `start`: after `gitflow.before_start`, get `worktrees.for_plan(root, plan)` or `worktrees.make(root, "relay", plan, base=f"origin/{default}")`, and start the relay there with `--branch relay/<name>`.
  2. The console moves into the worktree with `repl.switch_repo` and shows `Plan worktree: <plan> · <path>` with a **Back to <project>** button that switches back without stopping the relay. Opening the project again while a plan worktree exists shows `<plan> is running in its worktree` with **Open it**.
  3. CLI `whyline relay start` with Pull request makes the worktree, prints its path, and starts the relay there.
  4. `resume` runs in the worktree it started in. With `direct`, nothing here runs.
  Tests: the worktree is made from `origin/main` and the relay argv has `--branch`, a second start reuses it, the console's root moves and Back returns, resume stays in the worktree, and `direct` takes today's path.

- [ ] GIT-7: Open the plan's pull request when the relay finishes
  Edit `src/whyline/console/tui.py` (`_relay_finished`), `src/whyline/cli.py`, and their tests. Create `src/whyline/console/pr_panel.py` and `tests/console/test_pr_panel.py`.
  1. When a relay in a plan worktree finishes with every task done: push the branch (`git push -u origin relay/<name>`), then `pullrequest.ensure` with the plan's title and `pullrequest.body`. In ask and step modes each is confirmed first.
  2. A pull request panel in the Relay view shows its number, link, checks (refreshed every 30 seconds while pending) and **Open**, **Merge** (enabled only when checks pass), **Back to <project>**. A failed check shows RCR's **Why**, **Rerun** and **Ask an agent**.
  3. With Who merges You and checks passing: the console says `Pull request #<n> is ready to merge`, and a WAIT card says the same on Telegram with the go-ahead verb `merge`.
  4. CLI: `whyline pr open` (push and ensure for the current plan worktree) and `whyline pr status`.
  5. The pull request number is saved in the worktree's `.whyline/relay/pull-request.json`, so the panel comes back after a restart.
  Tests: push and ensure called once with the right branch and body, the confirms in ask mode, the panel's states (pending, failing, passing), the ready line and WAIT card, and the panel restored from the saved file.

- [ ] GIT-8: Merge, and come back to the project
  Create `src/whyline/merge.py` and `tests/test_merge.py`. Edit `src/whyline/console/pr_panel.py`, `src/whyline/cli.py` and their tests.
  1. `merge_plan(root, worktree, number, *, run, fetch) -> MergeResult` is the one function Merge, `whyline pr merge` and the Telegram `merge` verb call. It:
     - calls `pullrequest.merge`, which refuses unless checks pass
     - fetches, and fast-forwards the project folder's default branch when it is checked out there and clean; otherwise says `main is behind GitHub; pull when ready`
     - removes the worktree with `worktrees.remove` (which refuses on uncommitted changes) and deletes the local branch with `git branch -d` only when `worktrees.branch_merged`
     - returns what it did and anything it left, with the reason
  2. The console moves back to the project folder and shows `Merged #<n> into main` with what was cleaned up.
  3. With Who merges You, Merge runs only from the user's click, `whyline pr merge` typed by the user, or the user's Telegram `merge`. No other path calls it.
  Tests: `test_merge_needs_green_checks_and_the_user` (Auto mode and a finished relay never call `merge_plan` with Who merges You), `test_merge_cleanup_never_loses_work` (a dirty worktree and an unmerged branch are kept and named), the fast-forward and the "behind" message, and the console moving back.

- [ ] GIT-9: Who merges Automatic
  Edit `src/whyline/console/pr_panel.py`, `src/whyline/merge.py` and their tests.
  1. With Who merges Automatic (the run's value, else the global one), when the panel sees the checks pass it calls `merge.merge_plan` once, then says `Merged #<n> automatically` in the console and on Telegram.
  2. A failing check never merges. It shows the failure with Why, Rerun and Ask an agent, as with You.
  3. Changing Who merges back to You while a pull request waits takes effect before the next check.
  Tests: passing checks merge once and only once, failing checks never merge, the Telegram message, and switching to You mid-wait stops it.

- [ ] GIT-10: Release from main, with a small pull request when main is protected
  Edit `src/whyline/release/github.py`, `src/whyline/release/plan.py`, `src/whyline/release/source.py`, `src/whyline/release/setup_github.py`, `src/whyline/ideas/goahead.py` and their tests.
  1. `setup_github.branch_protection(owner_repo, branch, *, run) -> dict | None`: the current rule from `gh api repos/<owner_repo>/branches/<branch>/protection`, None when there is none (404), and the `UNAVAILABLE` text when GitHub refuses.
  2. With Deliver as Pull request and the checkout on the default branch, `source` skips Bring in main.
  3. When `branch_protection` is None (unprotected), the steps are exactly today's: the release commit is pushed straight to `main`.
  4. When `main` is protected, `build_steps` replaces `push` with `push_branch` (pushes `release/v<version>`) and `open_pr` (`pullrequest.ensure`, title `Release v<version>`, body the release notes), points `ci` at `pullrequest.checks`, and adds `merge` before `tag`. `merge` follows Who merges: with You it is irreversible and waits for the user's yes in every mode, Auto included. `tag` is made on the merge commit's sha.
  5. The Telegram go-ahead (`whyline.ideas.goahead`, from WAIT-5) gets `push the branch`, `open the pull request` and `merge` for the new steps.
  Tests: unprotected gives today's step ids, protected gives `push_branch`, `open_pr`, `ci`, `merge`, `tag` in order, Auto mode waits at `merge` with Who merges You, the tag on the merge commit, Bring in main skipped on the default branch, a resumed release skipping finished steps, and `branch_protection`'s three answers.

- [ ] GIT-11: Protect main on GitHub
  Edit `src/whyline/release/setup_github.py`, `src/whyline/release/cli.py`, `src/whyline/console/release_screens.py` and their tests.
  1. `protect_branch(owner_repo, branch, checks: list[str], *, run) -> str`: saves the earlier state to `whyline.gitdir.release_dir(root) / "protection-before.json"`, then `PUT`s a rule: pull request required with 0 approvals, the given status checks required, no force pushes, no deletions, administrators not exempt. Returns "" or the reason.
  2. `unprotect_branch(owner_repo, branch, *, run) -> str`: restores the saved earlier state (deleting the rule when there was none before).
  3. The required checks are the check names of the latest successful run on the branch, shown to the user before saving.
  4. Console, in Release → Set up, shown only with Deliver as Pull request: `main is not protected` with **Protect main…**, which shows exactly what will be set and asks, or `main is protected` with **Undo**. It says that with `main` protected, releases go through a small pull request. CLI: `whyline release setup protect` and `whyline release setup unprotect`, each asking unless `--yes`.
  Tests: `test_protect_asks_and_undoes`, the exact `PUT` payload, the unavailable case with its reason, the earlier state saved and restored, and the option hidden for Straight to main.

- [ ] GIT-12: Clean up and docs for the git flow
  Edit `src/whyline/release/plan.py` (the `after` step), `src/whyline/console/release_screens.py`, `docs/release.md`, `docs/relay.md` (or the page on running a relay), `README.md` and their tests.
  1. After a release, the `after` step lists local `relay/*` branches fully merged into `origin/<base>` (other than the current one) and relay worktrees whose branch is merged and whose tree is clean, and says `<n> merged branches and <m> worktrees can be removed` with **Clean up**. It uses `git branch -d` and `worktrees.remove` only.
  2. Docs cover: starting from the latest main and the stale dialog; Deliver as; the plan worktree and Back; the pull request panel and Merge; Who merges; releasing from main and the small pull request when `main` is protected; protecting `main` and undoing it; and what stays the same with Straight to main.
  Tests: only merged branches and clean merged worktrees are listed, `-d` is used, the current branch is never listed, and Straight to main shows no cleanup line.

- [ ] GIT-13: The Projects list
  Create `src/whyline/projects.py`, `tests/test_projects.py`, `src/whyline/console/projects_screen.py` and `tests/console/test_projects_screen.py`. Edit `src/whyline/console/repl.py` (`switch_repo`), `src/whyline/cli.py`, the repository picker in `src/whyline/console/tui.py`, and their tests.
  1. `~/.whyline/projects.json`: a list of `Project` (`key`, `path`, `remote`, `branch`, `last_release`, `parked`, `parked_at`, `archive`). `key` is the GitHub `owner/name` when there is one, else the folder path. `record(root)` adds or refreshes a project; `list_projects()`; `get(key)`. Writes are atomic.
  2. `switch_repo` and console start call `record(root)`. `last_release` is the newest `v*` tag.
  3. Console: **Projects** from the repository picker, listing each project with its folder, GitHub address, last release and Parked, with **Open**. **Park…** and **Reopen…** arrive with GIT-15 and GIT-16. CLI: `whyline project list`.
  Tests: record and refresh, the key with and without GitHub, the atomic write, the screen's rows, and the CLI listing.

- [ ] GIT-14: Check a project can be parked
  Edit `src/whyline/projects.py` and `tests/test_projects.py` only.
  1. `park_check(root, *, run, fetch) -> list[Blocker]` (`kind`, `detail`). After a fetch, it lists:
     - each local branch with commits not on any `origin` branch (`git rev-list <branch> --not --remotes`), with the count
     - stashes (`git stash list`)
     - changed or untracked files git doesn't ignore (up to 5 named, then the count)
     - relay worktrees from `worktrees.list_all` that still exist
     - a relay running or paused (`whyline_relay.running`, the pause file) or a release not finished (`whyline.release.state`)
     - open pull requests from `relay/*` branches (`gh pr list --state open`)
     - no `origin` on GitHub: `Not on GitHub; parking would lose it`
     - offline: `Couldn't reach GitHub to check; try again online`
  2. An empty list means it is safe to park.
  Tests: `test_park_check_finds_every_blocker` (a real repository in `tmp_path` with a bare `origin`, one case per blocker), and a clean, pushed project giving an empty list.

- [ ] GIT-15: Park a project
  Edit `src/whyline/projects.py`, `src/whyline/console/projects_screen.py`, `src/whyline/cli.py` and their tests.
  1. `park(root, *, confirm) -> ParkResult` refuses with the blockers when `park_check` is not empty. Otherwise:
     - archives the files under `.whyline/` that git ignores (`git ls-files --others --ignored --exclude-standard .whyline`) into `~/.whyline/parked/<safe key>.tar.gz` with `tarfile` (gzip), and checks the archive opens and lists every file before going on
     - shows the folder, its size, the archive's size and what happens next, and calls `confirm`; nothing changes without a yes
     - on macOS moves the folder into `~/.Trash` (a name clash gets a timestamp suffix); elsewhere `confirm` must return the project's folder name typed by the user, then the folder is deleted
     - marks the project parked with `parked_at` and `archive`
  2. Console: **Park…** shows the blockers, or the summary and a confirm. CLI: `whyline project park [path]`, always asking (there is no `--yes`).
  Tests: `test_park_asks_and_saves_local_files` (no change on no; the archive holds the ignored `.whyline` files and not committed ones; the folder is in the Trash; the project is marked parked), refusal with blockers, the typed name off macOS, and an archive that fails its check stopping before the move.

- [ ] GIT-16: Reopen a project, and docs for Projects
  Edit `src/whyline/projects.py`, `src/whyline/console/projects_screen.py`, `src/whyline/cli.py`, `README.md` and their tests. Create `docs/projects.md`.
  1. `reopen(key, *, dest=None, run) -> Path`: clones `remote` into `dest` (default the old `path`; refuses when it exists and isn't empty), restores the archive into `.whyline/` (refusing any member with an absolute path or `..`), runs `uv sync` when `uv.lock` exists (a failure is reported, not fatal), marks the project not parked, and keeps the archive until the next successful park.
  2. Console: **Reopen…** asks where (default the old folder), shows progress, then opens the project. CLI: `whyline project reopen <key> [--to <folder>]`.
  3. `docs/projects.md` explains Projects, what Park checks and saves, where the archive lives, the Trash, and Reopen. `README.md` links it.
  Tests: clone and restore into an empty folder, refusal on a non-empty folder, an unsafe archive member refused, `uv sync` run only with `uv.lock` and its failure reported, and the console opening the reopened project.
  Verify with `uv run pytest -q`.
