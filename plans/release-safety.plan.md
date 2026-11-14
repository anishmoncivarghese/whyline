<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-15-release-hardening-design.md | created: 2026-11-15T15:00:00+05:30 -->
# Release safety: a record of each release, Rehearse, and Release went wrong

Runs after `plans/security-earlier.plan.md`, and before `plans/release-supply-chain.plan.md`. Spec: `docs/superpowers/specs/2026-11-15-release-hardening-design.md`, Part 3. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **Rehearse does not build Docker images or run publish targets' own builds** other than the Python and npm package builds the contents check already does.
- **Recover handles GitHub and PyPI fully, and npm's deprecate.** Docker and Homebrew show written steps only.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: there is no way to see what a release will do before it does it, nothing helps after a bad version is published, and nothing records who confirmed what in a release.

What the user gets:
- **Rehearse**: everything a release would do up to the first step that can't be undone, in a throwaway copy, with a summary of what would be pushed, tagged and published.
- **Release went wrong**: warn users on the GitHub release, a guided yank on PyPI, and a patch release started for the fix.
- A record file for every release.

Rules every task keeps:
- **Console first.** Every action is in the Release screen through the same functions as `whyline release …`.
- **Rehearse changes nothing** in the user's checkout, its branches, its tags, its release state or any remote. It works in a temporary worktree that is removed afterwards.
- **Recover never deletes.** No tag is removed, no release is deleted, and no history is rewritten. Each of its actions asks first, in every mode.
- **Outward actions use the release's `run`** with argv lists, its timeouts and RCR's retries.
- **No secret's value** in a record, a summary or a log.
- **No new dependency.**
- **Tests:** never call a real `gh`, PyPI, npm or a remote. Use fakes and temporary repositories. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- After a rehearsal the checkout, refs, tags and release state are byte-for-byte what they were. SAF-2, `test_rehearse_leaves_no_trace`.
- A rehearsal never runs a step marked irreversible. SAF-2, `test_rehearse_stops_before_irreversible`.
- Recover makes no delete call of any kind. SAF-4, `test_recover_never_deletes`.
- Each Recover action runs only after its own confirm. SAF-4, `test_recover_actions_ask_first`.
- The release record holds no secret and no home path. SAF-1, `test_record_is_clean`.

- [ ] SAF-1: A record of each release
  Create `src/whyline/release/record.py` and `tests/release/test_record.py`. Edit `src/whyline/release/engine.py`, `src/whyline/release/plan.py` and their tests.
  1. `record.path(root, cfg, version) -> Path`: beside the notes, `docs/releases/v<version>.json` (the notes path with `.json`).
  2. `Record`: `version`, `commit`, `branch`, `started`, `finished`, `mode`, `steps` (id, title, state, started, finished, confirmed_by where a confirm was asked: `console`, `terminal`, `telegram` or `auto`), `checks` (command, exit code, seconds), `security` (counts per kind and level, and the allowed count; no finding text), `notes` (the `Checked.summary` when available), `artifacts` (file name, size, sha256), `targets` (name, state, url), `ci` (workflow, run id, url, attempts).
  3. `record.start`, `record.step`, `record.finish` update `.git/whyline-release/record.json` as the release runs. The `after` step writes the final file to `record.path` and commits it with the message `chore: record release v<version>` only when the release config has `record = true` (new field `ReleaseConfig.record: bool = True`). It is pushed with the next release, never by itself.
  4. Every string written passes `security.secrets.scan_text` redaction, and home paths are replaced by `~`.
  5. `record.load(root, cfg, version) -> Record | None`, and `record.versions(root, cfg) -> list[str]`, newest first.
  Tests: `test_record_is_clean`, a full run's record, a resumed run keeping earlier steps, the confirm source per mode, artifacts hashed, `record = false` writing nothing, and `versions`.

- [ ] SAF-2: Rehearse
  Create `src/whyline/release/rehearse.py` and `tests/release/test_rehearse.py`. Edit `src/whyline/release/engine.py` and its tests.
  1. `rehearse.run(root, cfg, version, *, run, fetch, ask_agent, on_progress=None, cancel_event=None) -> Rehearsal`.
     - It makes a worktree of HEAD in a temporary folder (`git worktree add --detach`), and removes it at the end, on an error and on cancel (`git worktree remove --force`, then `git worktree prune`).
     - It builds the release plan for that worktree and runs its steps in order, stopping before the first step whose `irreversible` is True. Steps that only make sense after it are not run.
     - The release state file is not written: the engine gets a `rehearsal=True` flag that keeps state in memory.
     - The notes step uses the real notes path inside the worktree. The checks and the security scan run there.
  2. `Rehearsal`: `ok`, `stopped_at` (the first irreversible step's title), `failed` (step title and reason, when a step failed), `version`, `commits` (subjects), `notes` (the text and the summary), `checks`, `security` (counts), `artifacts` (name, size, file count), `would` (plain lines: `Push 14 commits to origin/main`, `Tag v0.3.74`, `Create the GitHub release`, `Publish to PyPI`).
  3. A rehearsal is refused while a release is running in the checkout (`State.running` with a live pid).
  Tests: `test_rehearse_leaves_no_trace` (compare `git status --porcelain`, `git for-each-ref`, the worktree list and the state file before and after, on success, failure and cancel), `test_rehearse_stops_before_irreversible`, a failing check reported as `failed`, the `would` lines for Direct flow, and the refusal during a release.

- [ ] SAF-3: Rehearse in the console and CLI
  Edit `src/whyline/console/release_screens.py`, `src/whyline/console/tui.py`, `src/whyline/release/cli.py` and their tests only.
  1. A **Rehearse** button beside Release (and in the release start dialog). It shows progress like a release does, then a result window: the `would` lines first, then version, commits, notes with their summary, checks, security counts and artifacts, with **Release now** (starts the real release with the same version) and **Close**. A failure shows the step and reason with **Close**.
  2. CLI: `whyline release run --rehearse [--version X]` prints the same result and exits 0 when ok, 1 when a step failed.
  3. All result text is shown with `markup=False`.
  Tests: the button calling `rehearse.run`, the result window's sections, **Release now** passing the version, the failure view, and the CLI exit codes.

- [ ] SAF-4: Release went wrong
  Create `src/whyline/release/recover.py` and `tests/release/test_recover.py`. Edit `src/whyline/release/targets/pypi.py`, `src/whyline/release/targets/npm.py` and their tests.
  1. `recover.status(root, cfg, version, *, run, get) -> Status`: whether the GitHub release exists, is marked pre-release and already has a notice; whether PyPI shows the version and whether it is yanked (the version JSON's `yanked` field); the same for npm (`npm view <pkg>@<version> deprecated`).
  2. `recover.warn(root, version, reason, *, prerelease: bool, run) -> str`: prepends `> **Do not use this version.** <reason>` to the GitHub release's notes with `gh release edit --notes-file`, and sets `--prerelease` when asked. It never calls `gh release delete`. Running it twice replaces the notice, never stacks it.
  3. `recover.yank_steps(name, version, reason) -> Steps` for PyPI: the manage URL `https://pypi.org/manage/project/<name>/release/<version>/`, and the exact steps in words (Options → Yank, type the reason). `recover.wait_yanked(name, version, *, get, sleep, minutes=10) -> bool` polls the JSON API.
  4. `recover.deprecate_npm(name, version, reason, *, run) -> str`: `npm deprecate <name>@<version> <reason>`.
  5. `recover.patch_base(root, version, *, run) -> PatchBase`: the previous release tag, and whether the current branch contains the bad tag. It only reports. Starting the patch release is the normal Release with its version set to the next patch and a first notes line `Fixes a problem in v<version>: <reason>` passed as a hint to the notes writer.
  6. Each action writes a `whyline note` (`--role release`) and appends to the release record's `recovery` list.
  Tests: `test_recover_never_deletes` (search the recorded argv for `delete`, `-d`, `--delete`, `push --force`, `tag -d`), the notice replaced not stacked, the yank steps' URL, `wait_yanked` true and timing out, npm's argv, `patch_base`, and the note and record entries.

- [ ] SAF-5: Release went wrong in the console and CLI
  Edit `src/whyline/console/release_screens.py`, `src/whyline/release/cli.py` and their tests only.
  1. The Release screen lists recent releases from `record.versions` (and tags when there is no record), each with **Release went wrong…**. It opens a window showing `recover.status` and three actions, each with its own confirm:
     - **Warn users**: a reason box and a **Mark as pre-release** checkbox
     - **Yank from PyPI**: the steps, **Open the page**, then `Waiting for PyPI to show it as yanked…` and the result. For npm, **Deprecate on npm**. For Docker and Homebrew, the written steps.
     - **Ship a fix**: shows `patch_base`, then **Start patch release v<next>**
  2. CLI: `whyline release recover <version>` prints the status. `--warn "<reason>" [--prerelease]`, `--yank "<reason>"` (prints the steps and waits), `--deprecate "<reason>"` and `--patch` each ask `[y/N]` unless `--yes`.
  Tests: `test_recover_actions_ask_first` (console and CLI), each action calling its function, a version with no GitHub release showing only what applies, and the patch release started with the next version and the hint.

- [ ] SAF-6: Docs
  Edit `docs/release.md` and `README.md` only.
  Cover: the release record and turning it off, Rehearse and what it does and doesn't run, Release went wrong and its three actions, why nothing is deleted, and what yanking means for people who already installed the version.
  Verify with `uv run pytest -q`.
