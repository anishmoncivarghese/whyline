<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-10-31-release-design.md | created: 2026-10-31T22:00:00+05:30 -->
# Release 1: config, Ready check, step engine, GitHub, and the Release button

Spec: `docs/superpowers/specs/2026-10-31-release-design.md`. Read it before every task. Where a name in the repository has moved, follow the repository and keep the behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Starts after `plans/job-search-4-pdf-workday-bulk.plan.md` and `plans/relay-status-line.plan.md` are complete. The busy line here reuses RST-2's rendering, and both plans change `tui.py`. `plans/release-2-targets.plan.md` follows this one.

What the user gets from this plan:
- A **Release** button in Relay mode that releases to GitHub: version bump, notes, checks, push, CI, tag, GitHub release.
- A Ready check, Ask, Step and Auto modes, a progress line with step % and elapsed time, and Resume after a failure.
- GitHub setup in the console: sign in through `gh`, and create and link the repository.
- A plan's release task can be finished with **Run Release**.
- `whyline release check | run | status | resume | setup github` for scripts.

Global constraints:
- New code lives in `src/whyline/release/` with tests in `tests/release/`. No new runtime dependency. Read TOML with `tomllib`.
- Every subprocess goes through an injected `run` (default `subprocess.run`), and every HTTP read through an injected `fetch`. Tests use temporary git repositories with a local bare repository as `origin`. No test reaches GitHub, PyPI or the network, and no test sleeps (inject `sleep` and `now`).
- Whyline never asks for, stores or prints a GitHub token. GitHub access is `gh` only.
- Run state is `.git/whyline-release/state.json`, never under `.whyline/`.
- Console first: every CLI command here has a console counterpart that calls the same function.
- Verify every task with `uv run pytest -q tests/release tests/console` and then `uv run pytest -q`. Change nothing outside the files a task names.

- [ ] REL-1: Release config: load, save, detect
  Create `src/whyline/release/__init__.py`, `src/whyline/release/config.py` and `tests/release/test_config.py` only.
  - `ReleaseConfig` (frozen dataclass) with the fields and defaults of the spec's `.whyline/release.toml`: mode, branch, start_after_plan, checks, ci_ignore, notes, version_files, after, and `targets: Targets` (github, pypi, npm, docker, homebrew bools, `docker: DockerTarget(registries, image)`, `homebrew: HomebrewTarget(tap, formula)`, `custom: tuple[CustomTarget(name, run, verify), ...]`).
  - `load(root) -> ReleaseConfig`: defaults when the file is missing. `ConfigError` with the key named for a bad value: mode not in ask/step/auto, a non-list `checks`, a custom entry without `name` or `run`, or a duplicate custom name.
  - `save(root, cfg)`: writes the file in the spec's fixed shape with a small writer (strings escaped as TOML basic strings), atomically. `load(save(x)) == x`.
  - `detect(root) -> ReleaseConfig`: the defaults plus suggestions. pypi when `pyproject.toml` has `[project]`; npm when `package.json` exists without `"private": true`; docker when a `Dockerfile` exists; github always. `checks` defaults to `["uv run pytest -q"]` for a uv project, `["npm test"]` when `package.json` has a `test` script, otherwise `[]`.
  - `normalise(cfg)`: any target ticked means github is ticked.
  - Pending setup files: `add_pending(root, path)`, `pending(root) -> list[Path]` and `clear_pending(root)`, kept in `.git/whyline-release/pending.json`. Set up records each file it writes there (a workflow, a Dockerfile). The release commit adds them, and the Ready check's clean-tree item ignores them. A recorded path that no longer exists is dropped on read.
  Tests: defaults, round-trip with every field set, each `ConfigError`, each detection case, normalise, pending add/read/clear and a dropped missing path.

- [ ] REL-2: Read and bump the version
  Create `src/whyline/release/version.py` and `tests/release/test_version.py` only.
  - `current(root, cfg) -> str`: from `pyproject.toml` `[project] version`, else `package.json` `version`, else `VersionError("No version found; add one to pyproject.toml or package.json, or list a file in version_files")`.
  - `bump(version, kind) -> str` for `patch`, `minor`, `major` (plain `X.Y.Z`; a pre-release suffix is refused with a clear message). `validate(text)` accepts `X.Y.Z` and `X.Y.ZrcN`/`-rc.N`.
  - `files_to_change(root, cfg) -> list[Path]`: pyproject, a `__version__ = "…"` line in the package's `__init__.py` when present (found from `[project] name`, with `-` turned into `_`, under `src/` or the root), package.json, plus `version_files`.
  - `write(root, cfg, new, *, run) -> list[Path]`: replaces the old version string only on the known line in each file (never a global replace), then runs `uv lock` when `uv.lock` exists, or `npm install --package-lock-only` when `package-lock.json` exists. It returns every changed path. If a file holds no line with the old version, it raises before writing anything.
  Tests: each source, each bump, a pre-release refusal, `__version__` found in a src layout, a file without the old version leaves every file untouched, and the lock commands are recorded through the fake `run`.

- [ ] REL-3: The Ready check
  Create `src/whyline/release/ready.py` and `tests/release/test_ready.py` only.
  - `ReadyItem(key, ok, text, fix)` and `check(root, cfg, version, *, run, fetch, relay_state) -> list[ReadyItem]`. The items, in order: git installed, gh installed, gh signed in (`gh auth status`), origin is GitHub (`git remote get-url origin` host github.com), tree clean (`git status --porcelain` empty apart from `config.pending(root)` paths, run with `GIT_OPTIONAL_LOCKS=0`), relay idle (from the injected `relay_state`: running → ✗, paused on a release task → ✓), HEAD on or ahead of `origin/<branch>` (after `git fetch origin <branch>`), tag `v<version>` absent locally and remotely (`git ls-remote --tags origin`).
  - Target items come from a registry, `register_ready(target, fn)`, which plan 2 fills in. This task registers none.
  - Each item runs in its own `try`. An exception becomes ✗ with "could not check: <short reason>". The whole check has a 30 s budget, and items not reached are ✗ "not checked (time limit)".
  - `ok(items) -> bool`.
  Tests: all ✓ on a prepared temp repository, then each item ✗ alone with its fix text, a running relay versus a release pause, an exception item, the time budget (fake clock).

- [ ] REL-4: Step engine, run state, modes and Resume
  Create `src/whyline/release/engine.py`, `src/whyline/release/state.py` and `tests/release/test_engine.py` only.
  - `Step(id, title, irreversible, done_check, run)`. `Plan(version, steps)`. `Progress(step_index, total, title, detail, started_at, step_started_at)`.
  - State in `.git/whyline-release/state.json` (atomic write): version, step ids, done ids, failed id and reason, mode, started. `state.load/save/clear`.
  - `run(root, plan, *, mode, confirm, on_progress, cancel_event, now) -> Result`:
    - For each step not marked done, call `done_check()`. If it returns true, mark the step done and skip it.
    - Before an irreversible step, call `confirm(step)`: in `step` mode before every one, in `ask` mode once before the first one, in `auto` never. A false answer pauses with "You stopped before <title>."
    - Run the step, then mark it done. An exception or a false return marks it failed with the reason, saves state and stops.
    - `cancel_event` is checked between steps and passed to the steps that wait.
  - `resume(root, steps_by_id, ...)` continues from saved state and refuses when the saved version differs from the plan's version.
  - `percent(progress) = done*100//total`.
  - A second `run` while state shows a run in progress by a live pid (same pid check as the relay marker) raises `AlreadyReleasing`.
  Tests: order and skipping, each mode's confirm calls, a declined confirm pauses, a failure saves state, resume skips done steps and reruns the failed one, `done_check` skips, cancel between steps, a version mismatch on resume, the % at each step.

- [ ] REL-5: GitHub steps
  Create `src/whyline/release/github.py` and `tests/release/test_github.py` only.
  Build `Step`s for spec steps 4–9 (commit, checks, push, ci, tag, github_release):
  - `commit`: add only the paths returned by `version.write`, the notes file and `config.pending(root)`, commit `chore: release v<version>`, then `config.clear_pending(root)`. Its `done_check` is true when HEAD's subject is that message.
  - `checks`: run each command with `shell=True` in root, streaming lines to `on_progress` detail. It fails with the command and the last 20 lines.
  - `push`: `git push origin HEAD:<branch>`. When `origin/<branch>` isn't an ancestor, fail with "origin/<branch> has commits this branch doesn't; merge them first". When the push is rejected for protection (stderr contains `protected branch` or `GH006`), fail with `open_pr=True` in the result so the screen can offer **Open PR** (`gh pr create --fill --base <branch>`). Its `done_check`: `git ls-remote origin <branch>` equals HEAD.
  - `ci`: poll `gh run list --commit <sha> --json name,status,conclusion,url` every 15 s (injected sleep), ignore `ci_ignore` names, and report "n of m checks" in detail. It fails with the failed run's name and URL, and gives up after 60 minutes with a resumable failure. No runs at all after 2 minutes counts as passed, with a note "no CI configured".
  - `tag`: annotated `v<version>` with message `v<version>`, then pushed. Its `done_check` is that the remote tag exists.
  - `github_release`: `gh release create v<version> --title v<version> --notes-file <notes>` (or `--generate-notes` when notes is ""). Its `done_check` is that `gh release view v<version>` exits 0.
  Tests against a temp repository and a bare origin, with `gh` faked through `run`: each step, its `done_check`, push to a diverged origin, the protected-branch result, CI pass/fail/ignored/no-CI/timeout.

- [ ] REL-6: Release notes drafted by an agent
  Create `src/whyline/release/notes.py` and `tests/release/test_notes.py` only.
  - `commits_since_last_tag(root, *, run) -> list[str]`: subjects from `git log <last v-tag>..HEAD`, or the last 50 when there is no tag.
  - `draft(root, cfg, version, *, ask_agent) -> str`: a prompt with the version, the commit subjects and the previous notes file (if `notes` names a pattern and the previous version's file exists) as a style example. It asks for markdown notes for users, grouped by what changed, without inventing anything not in the commits. `ask_agent(prompt) -> str` is injected. The console passes a function that calls `adapters.run_chat_turn` with the relay's main agent, then each backup in turn on failure.
  - `fallback(version, commits)`: when every agent fails, a plain bulleted list of the commit subjects under `# v<version>`, so a release never blocks on an agent.
  - `write(root, cfg, version, text) -> Path | None`: writes to `notes.format(version=...)` and returns None when notes is "".
  Tests: commits with and without tags, the prompt includes the style example, the fallback on agent failure, write with and without a notes path.

- [ ] REL-7: `whyline release` CLI
  Create `src/whyline/release/cli.py` and `tests/release/test_cli.py`; edit `src/whyline/cli.py` only to register it the way `_add_workflows`/`cmd_workflows` do.
  - `whyline release check [--version X]`: prints the Ready items. Exits 1 when any is ✗.
  - `whyline release run [--bump patch|minor|major|--version X] [--mode ask|step|auto] [--yes]`: builds the plan (`release.plan.build(root, cfg, version, ...)` in a new `src/whyline/release/plan.py`, which assembles ready → version → notes → commit → checks → github steps → after) and runs it, printing progress lines. In ask/step mode on a terminal it asks y/n at each confirm. Without a terminal it refuses unless `--yes` or mode auto. Notes use the agent with the fallback, and in ask mode it prints the notes path and asks to continue.
  - `whyline release status`: the saved state, or "No release in progress."
  - `whyline release resume [--yes]`.
  - The `after` step (spec step 14) lives in `plan.py`: run each `after` command (warn on failure), then send `Released v<version> of <repo>` through `whyline.agents.telegram.send_message` when the assistant's bot token and chat are set up. Otherwise skip quietly.
  Tests: each subcommand with a faked engine and run, the refusal without a terminal, `--yes`, and the after step's warning and Telegram call.

- [ ] REL-8: GitHub setup: sign in, create and link the repository
  Create `src/whyline/release/setup_github.py` and `tests/release/test_setup_github.py`; edit `src/whyline/release/cli.py` and its test only.
  - `status(root, *, run) -> GitHubStatus(gh_installed, signed_in, user, origin_url, origin_is_github)`.
  - `sign_in(*, run_streaming, on_line)`: runs `gh auth login --web --git-protocol https --hostname github.com` with "\n" on stdin, passing each output line to `on_line` (the one-time code appears there). It returns the exit code.
  - `create_repo(root, name, *, private=True, description="", run)`: checks the name against `^[A-Za-z0-9._-]{1,100}$`, refuses when `origin` exists, and runs `gh repo create <name> --private|--public --source . --remote origin [--description …]`. It never pushes. It returns the new URL.
  - CLI: `whyline release setup github [--create NAME] [--public]`. It prints the status, runs sign in when not signed in and on a terminal, and creates the repository when asked.
  Tests: each status case, sign-in streams lines and passes the newline, create's argv for private and public, an existing origin is refused, a bad name is refused, no command contains a token.

- [ ] REL-9: The Release button and its Release tab
  Create `src/whyline/console/release_screens.py` and `tests/console/test_release_screens.py`; edit `src/whyline/console/tui.py` and `tests/console/test_tui_relay_run.py` only.
  1. Add `Button("Release", id="relay-release")` after **Resolve**. It shows only in Relay mode (follow how the other `relay-*` buttons are shown and hidden). It is disabled while a relay runs, unless the relay is paused on a release task.
  2. `ReleaseScreen(ModalScreen)` with tabs **Release** and **Set up**. This task builds **Release**; **Set up** shows "Set up comes in a later task" until REL-11.
     - Version: a select (patch/minor/major/current/custom), with the current and next version shown.
     - Mode: ask/step/auto, defaulting to the config.
     - **Check** runs the Ready check in a thread worker and lists ✓/✗ with fixes. **Start** is enabled only when every item is ✓.
     - The planned steps are listed, with irreversible ones marked ⚠.
  3. **Start** stays a stub in this task: it closes the screen and calls an injected `start_release(choice)`, which REL-10 implements.
  Tests (injected ready and config):
  - the button shows only in Relay mode, and is disabled while a relay runs but enabled on a release-task pause
  - the version choices show the right next versions
  - Check lists items, and Start is disabled with a ✗ item
  - the planned steps show ⚠ on irreversible ones
  - Start passes the chosen version and mode

- [ ] REL-10: Run a release from the console: progress, confirmations, notes review, failure
  Edit `src/whyline/console/release_screens.py`, `src/whyline/console/tui.py`, `tests/console/test_release_screens.py` and `tests/console/test_tui_relay_run.py` only.
  1. `start_release` runs `plan.build` and the engine in a thread worker. Progress goes to the transcript as `release · <title>: <detail>` lines.
  2. The busy line reads `release: v<version> · step i of n (p%) · <title>[ · <detail>] · <elapsed of this step>`, using RST-2's formatting helpers for elapsed time. **Stop** sets the cancel event.
  3. `confirm` opens a small modal naming the step and what it will do, with **Go** and **Stop here**.
  4. In ask mode the notes step opens the drafted notes in a read-only `TextArea` with **Edit** (opens the editor the console already uses for plans), **Use these** and **Stop**.
  5. A failure shows the reason, with **Resume release** and, when the push result says `open_pr`, **Open PR**.
  6. Relay **Run** and **Resume** are disabled while a release runs.
  Tests (injected engine and agent):
  - a run updates the busy line with step and %
  - each mode's confirm modals
  - the notes review in ask mode
  - Stop cancels
  - a failure offers Resume release, and Open PR when flagged
  - relay Run and Resume are disabled during a release

- [ ] REL-11: The Set up tab: targets, mode, checks and GitHub
  Edit `src/whyline/console/release_screens.py` and `tests/console/test_release_screens.py` only.
  - The tab loads `config.load`, or `config.detect` when the file is missing (shown with "Suggested; press Save to keep").
  - Rows:
    - one per target (GitHub, PyPI, npm, Docker, Homebrew, Custom), each with a checkbox, a status and **Set up…**. Only GitHub's Set up… works in this plan; the others say "Comes with release part 2".
    - mode, branch, Release when a plan completes, checks (one per line), CI jobs to ignore, notes path, after-commands
  - **Save** calls `config.normalise` then `config.save`. Ticking any target ticks GitHub and shows why.
  - Leaving with unsaved changes asks the same way the jobs preferences screen does.
  - **GitHub Set up…** shows `setup_github.status`:
    - **Sign in** runs `sign_in` in a worker and shows the one-time code line in large text
    - **Create repository** asks for name (default folder name), Private/Public (default Private) and a description
    - a `brew install gh` hint with **Copy** when gh is missing
  - **Ask agent** sends the GitHub status and the last error to the main agent through `adapters.run_chat_turn` and shows the reply. It never runs commands.
  Tests: detection prefill, save round-trip through the same `config.save`, normalise on tick, the unsaved guard, sign in shows the code, create's choices reach `create_repo`, Ask agent shows a reply.

- [ ] REL-12: Release from a plan's release task, release after a plan, and docs
  Edit `src/whyline/console/tui.py`, `tests/console/test_tui_relay_run.py` and `README.md`; create `docs/release.md` only.
  1. When the relay is paused on a release task (`relay_ops.release_task` returns a value), the "Release done…" action offers **Run Release** as well as Done/Skip. It opens `ReleaseScreen` with the checklist from the pause shown above the steps. When the engine finishes successfully, the console sends `done <task_id>` through the same `_launch_relay(["done", task_id])` path typing it uses. A failed or stopped release leaves the relay paused.
  2. With `start_after_plan = true`, when the relay finishes with every plan task ticked, the console opens `ReleaseScreen` with **Check** already run. Ask and Step modes still wait for the user. Auto starts only when every Ready item is ✓.
  3. `docs/release.md`: what each target does, setup per target, the modes, Resume, and what is never stored. The README's Relay section links it.
  Tests: Run Release on a release pause sends `done` after success and not after failure, start_after_plan opens the screen in ask mode, auto only starts on an all-✓ check.
