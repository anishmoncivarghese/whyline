<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-01T02:00:00+05:30 -->
# Release button: core, security checks and publishing targets

Merged on 2026-11-01 from three plans, in run order: release-1-core (REL-1..12), release-3-security (SEC-1..14) and release-2-targets (REL-13..19). Spec: `docs/superpowers/specs/2026-10-31-release-design.md`. Starts after `plans/relay-tooling.plan.md` is complete. Security comes before the targets, so nothing is published to a registry before the checks exist. RLS-1 publishes at the end.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task. Each part keeps its own intro and rules; read the intro of the part a task is in before starting it.

## Part 1: config, Ready check, step engine, GitHub, and the Release button

Spec: `docs/superpowers/specs/2026-10-31-release-design.md`. Read it before every task. Where a name in the repository has moved, follow the repository and keep the behaviour.

Starts after `plans/relay-tooling.plan.md` is complete. The busy line here reuses RST-2's rendering, and both plans change `tui.py`.

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

- [x] REL-1: Release config: load, save, detect
  Create `src/whyline/release/__init__.py`, `src/whyline/release/config.py` and `tests/release/test_config.py` only.
  - `ReleaseConfig` (frozen dataclass) with the fields and defaults of the spec's `.whyline/release.toml`: mode, branch, start_after_plan, checks, ci_ignore, notes, version_files, after, and `targets: Targets` (github, pypi, npm, docker, homebrew bools, `docker: DockerTarget(registries, image)`, `homebrew: HomebrewTarget(tap, formula)`, `custom: tuple[CustomTarget(name, run, verify), ...]`).
  - `load(root) -> ReleaseConfig`: defaults when the file is missing. `ConfigError` with the key named for a bad value: mode not in ask/step/auto, a non-list `checks`, a custom entry without `name` or `run`, or a duplicate custom name.
  - `save(root, cfg)`: writes the file in the spec's fixed shape with a small writer (strings escaped as TOML basic strings), atomically. `load(save(x)) == x`.
  - `detect(root) -> ReleaseConfig`: the defaults plus suggestions. pypi when `pyproject.toml` has `[project]`; npm when `package.json` exists without `"private": true`; docker when a `Dockerfile` exists; github always. `checks` defaults to `["uv run pytest -q"]` for a uv project, `["npm test"]` when `package.json` has a `test` script, otherwise `[]`.
  - `normalise(cfg)`: any target ticked means github is ticked.
  - Pending setup files: `add_pending(root, path)`, `pending(root) -> list[Path]` and `clear_pending(root)`, kept in `.git/whyline-release/pending.json`. Set up records each file it writes there (a workflow, a Dockerfile). The release commit adds them, and the Ready check's clean-tree item ignores them. A recorded path that no longer exists is dropped on read.
  Tests: defaults, round-trip with every field set, each `ConfigError`, each detection case, normalise, pending add/read/clear and a dropped missing path.

- [x] REL-2: Read and bump the version
  Create `src/whyline/release/version.py` and `tests/release/test_version.py` only.
  - `current(root, cfg) -> str`: from `pyproject.toml` `[project] version`, else `package.json` `version`, else `VersionError("No version found; add one to pyproject.toml or package.json, or list a file in version_files")`.
  - `bump(version, kind) -> str` for `patch`, `minor`, `major` (plain `X.Y.Z`; a pre-release suffix is refused with a clear message). `validate(text)` accepts `X.Y.Z` and `X.Y.ZrcN`/`-rc.N`.
  - `files_to_change(root, cfg) -> list[Path]`: pyproject, a `__version__ = "…"` line in the package's `__init__.py` when present (found from `[project] name`, with `-` turned into `_`, under `src/` or the root), package.json, plus `version_files`.
  - `write(root, cfg, new, *, run) -> list[Path]`: replaces the old version string only on the known line in each file (never a global replace), then runs `uv lock` when `uv.lock` exists, or `npm install --package-lock-only` when `package-lock.json` exists. It returns every changed path. If a file holds no line with the old version, it raises before writing anything.
  Tests: each source, each bump, a pre-release refusal, `__version__` found in a src layout, a file without the old version leaves every file untouched, and the lock commands are recorded through the fake `run`.

- [x] REL-3: The Ready check
  Create `src/whyline/release/ready.py` and `tests/release/test_ready.py` only.
  - `ReadyItem(key, ok, text, fix)` and `check(root, cfg, version, *, run, fetch, relay_state) -> list[ReadyItem]`. The items, in order: git installed, gh installed, gh signed in (`gh auth status`), origin is GitHub (`git remote get-url origin` host github.com), tree clean (`git status --porcelain` empty apart from `config.pending(root)` paths, run with `GIT_OPTIONAL_LOCKS=0`), relay idle (from the injected `relay_state`: running → ✗, paused on a release task → ✓), HEAD on or ahead of `origin/<branch>` (after `git fetch origin <branch>`), tag `v<version>` absent locally and remotely (`git ls-remote --tags origin`).
  - Target items come from a registry, `register_ready(target, fn)`, which plan 2 fills in. This task registers none.
  - Each item runs in its own `try`. An exception becomes ✗ with "could not check: <short reason>". The whole check has a 30 s budget, and items not reached are ✗ "not checked (time limit)".
  - `ok(items) -> bool`.
  Tests: all ✓ on a prepared temp repository, then each item ✗ alone with its fix text, a running relay versus a release pause, an exception item, the time budget (fake clock).

- [x] REL-4: Step engine, run state, modes and Resume
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

- [x] REL-5: GitHub steps
  Create `src/whyline/release/github.py` and `tests/release/test_github.py` only.
  Build `Step`s for spec steps 4–9 (commit, checks, push, ci, tag, github_release):
  - `commit`: add only the paths returned by `version.write`, the notes file and `config.pending(root)`, commit `chore: release v<version>`, then `config.clear_pending(root)`. Its `done_check` is true when HEAD's subject is that message.
  - `checks`: run each command with `shell=True` in root, streaming lines to `on_progress` detail. It fails with the command and the last 20 lines.
  - `push`: `git push origin HEAD:<branch>`. When `origin/<branch>` isn't an ancestor, fail with "origin/<branch> has commits this branch doesn't; merge them first". When the push is rejected for protection (stderr contains `protected branch` or `GH006`), fail with `open_pr=True` in the result so the screen can offer **Open PR** (`gh pr create --fill --base <branch>`). Its `done_check`: `git ls-remote origin <branch>` equals HEAD.
  - `ci`: poll `gh run list --commit <sha> --json name,status,conclusion,url` every 15 s (injected sleep), ignore `ci_ignore` names, and report "n of m checks" in detail. It fails with the failed run's name and URL, and gives up after 60 minutes with a resumable failure. No runs at all after 2 minutes counts as passed, with a note "no CI configured".
  - `tag`: annotated `v<version>` with message `v<version>`, then pushed. Its `done_check` is that the remote tag exists.
  - `github_release`: `gh release create v<version> --title v<version> --notes-file <notes>` (or `--generate-notes` when notes is ""). Its `done_check` is that `gh release view v<version>` exits 0.
  Tests against a temp repository and a bare origin, with `gh` faked through `run`: each step, its `done_check`, push to a diverged origin, the protected-branch result, CI pass/fail/ignored/no-CI/timeout.

- [x] REL-6: Release notes drafted by an agent
  Create `src/whyline/release/notes.py` and `tests/release/test_notes.py` only.
  - `commits_since_last_tag(root, *, run) -> list[str]`: subjects from `git log <last v-tag>..HEAD`, or the last 50 when there is no tag.
  - `draft(root, cfg, version, *, ask_agent) -> str`: a prompt with the version, the commit subjects and the previous notes file (if `notes` names a pattern and the previous version's file exists) as a style example. It asks for markdown notes for users, grouped by what changed, without inventing anything not in the commits. `ask_agent(prompt) -> str` is injected. The console passes a function that calls `adapters.run_chat_turn` with the relay's main agent, then each backup in turn on failure.
  - `fallback(version, commits)`: when every agent fails, a plain bulleted list of the commit subjects under `# v<version>`, so a release never blocks on an agent.
  - `write(root, cfg, version, text) -> Path | None`: writes to `notes.format(version=...)` and returns None when notes is "".
  Tests: commits with and without tags, the prompt includes the style example, the fallback on agent failure, write with and without a notes path.

- [x] REL-7: `whyline release` CLI
  Create `src/whyline/release/cli.py` and `tests/release/test_cli.py`; edit `src/whyline/cli.py` only to register it the way `_add_workflows`/`cmd_workflows` do.
  - `whyline release check [--version X]`: prints the Ready items. Exits 1 when any is ✗.
  - `whyline release run [--bump patch|minor|major|--version X] [--mode ask|step|auto] [--yes]`: builds the plan (`release.plan.build(root, cfg, version, ...)` in a new `src/whyline/release/plan.py`, which assembles ready → version → notes → commit → checks → github steps → after) and runs it, printing progress lines. In ask/step mode on a terminal it asks y/n at each confirm. Without a terminal it refuses unless `--yes` or mode auto. Notes use the agent with the fallback, and in ask mode it prints the notes path and asks to continue.
  - `whyline release status`: the saved state, or "No release in progress."
  - `whyline release resume [--yes]`.
  - The `after` step (spec step 14) lives in `plan.py`: run each `after` command (warn on failure), then send `Released v<version> of <repo>` through `whyline.agents.telegram.send_message` when the assistant's bot token and chat are set up. Otherwise skip quietly.
  Tests: each subcommand with a faked engine and run, the refusal without a terminal, `--yes`, and the after step's warning and Telegram call.

- [x] REL-8: GitHub setup: sign in, create and link the repository
  Create `src/whyline/release/setup_github.py` and `tests/release/test_setup_github.py`; edit `src/whyline/release/cli.py` and its test only.
  - `status(root, *, run) -> GitHubStatus(gh_installed, signed_in, user, origin_url, origin_is_github)`.
  - `sign_in(*, run_streaming, on_line)`: runs `gh auth login --web --git-protocol https --hostname github.com` with "\n" on stdin, passing each output line to `on_line` (the one-time code appears there). It returns the exit code.
  - `create_repo(root, name, *, private=True, description="", run)`: checks the name against `^[A-Za-z0-9._-]{1,100}$`, refuses when `origin` exists, and runs `gh repo create <name> --private|--public --source . --remote origin [--description …]`. It never pushes. It returns the new URL.
  - CLI: `whyline release setup github [--create NAME] [--public]`. It prints the status, runs sign in when not signed in and on a terminal, and creates the repository when asked.
  Tests: each status case, sign-in streams lines and passes the newline, create's argv for private and public, an existing origin is refused, a bad name is refused, no command contains a token.

- [x] REL-9: The Release button and its Release tab
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

- [x] REL-10: Run a release from the console: progress, confirmations, notes review, failure
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

- [x] REL-11: The Set up tab: targets, mode, checks and GitHub
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

- [x] REL-12: Release from a plan's release task, release after a plan, and docs
  Edit `src/whyline/console/tui.py`, `tests/console/test_tui_relay_run.py` and `README.md`; create `docs/release.md` only.
  1. When the relay is paused on a release task (`relay_ops.release_task` returns a value), the "Release done…" action offers **Run Release** as well as Done/Skip. It opens `ReleaseScreen` with the checklist from the pause shown above the steps. When the engine finishes successfully, the console sends `done <task_id>` through the same `_launch_relay(["done", task_id])` path typing it uses. A failed or stopped release leaves the relay paused.
  2. With `start_after_plan = true`, when the relay finishes with every plan task ticked, the console opens `ReleaseScreen` with **Check** already run. Ask and Step modes still wait for the user. Auto starts only when every Ready item is ✓.
  3. `docs/release.md`: what each target does, setup per target, the modes, Resume, and what is never stored. The README's Relay section links it.
  Tests: Run Release on a release pause sends `done` after success and not after failure, start_after_plan opens the screen in ask mode, auto only starts on an all-✓ check.

## Part 2: security checks before anything is published

Spec: `docs/superpowers/specs/2026-10-31-release-design.md` (Release). This plan adds security checks to it. Where this plan and the spec differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the behaviour.

Starts after Part 1 (REL-1..12) is complete. It uses REL-1 (`release.toml`), REL-3 (`register_ready`), REL-8 (GitHub setup) and REL-11 (the Set up tab). It runs before Part 3 (REL-13..19). SEC-6's npm and Docker checks only matter once those targets exist, and they run whenever the project has a `package.json` or `Dockerfile`.

What the user gets:
- **Nothing to install.** Whyline has its own secret scanner, built on a bundled copy of gitleaks' MIT-licensed default rules. It checks dependencies through OSV.dev's free public API and inspects package contents itself. If `gitleaks`, `betterleaks` or `osv-scanner` is on PATH, whyline also runs them for wider coverage. Setup suggests `brew install gitleaks osv-scanner` but never requires it.
- **A release gate.** The Ready check gains a Security item. Before anything is pushed it scans:
  - the commits about to be pushed, for keys, tokens, private keys and `.env`-style files
  - the dependencies, for known vulnerabilities
  - the files each package will actually publish
- Each finding offers **Fix**, **Ignore once** or **Allow** (saved with a reason).
- **Settings → Release → Security.** Each check is On (block), Warn or Off. Secrets default to block. Dependencies default to blocking on high or critical and warning below that.
- **Scan history** runs once over the whole git history, for an existing repository about to go public.
- **Check every commit** (optional) installs a pre-commit hook, so a secret is stopped before it even reaches a local commit, the relay's included.
- **GitHub protection.** GitHub setup offers to turn on GitHub's own secret scanning, push protection and Dependabot alerts.
- **Deep audit** (off by default, on demand). Your main agent runs a multi-phase audit using a bundled copy of Cloudflare's MIT-licensed security-audit method. The Release gate can optionally block on *confirmed* high or critical findings.

Global constraints:
- New code lives in `src/whyline/security/` with tests in `tests/security/`. No new runtime dependency.
- A found secret is never printed, logged, stored or sent in full anywhere. That includes the transcript, the CLI, JSON output, allowlists, agent prompts and Telegram. Show only `first4…last2 (N chars)`. Allowlist entries store a fingerprint: sha256 of rule id, path and secret, first 16 hex characters.
- The dependency check sends only public package names, versions and ecosystems to `https://api.osv.dev`. A package not from the public registry (local path, git, workspace, a private index URL) is never sent and is listed as "not checked (private source)".
- Every subprocess goes through an injected `run`, and every HTTP call through an injected `fetch`. No test reaches the network, and no test needs gitleaks or osv-scanner installed.
- Scanning stays fast: the release gate covers only `origin/<branch>..HEAD` plus the package contents, and must finish in under 20 s on this repository. History scanning is separate and shows progress.
- Console first: every CLI command has a console counterpart calling the same function.
- Verify every task with `uv run pytest -q tests/security tests/release tests/console` and then `uv run pytest -q`. Change nothing outside the files a task names.

- [x] SEC-1: Findings, settings and the allowlist
  Create `src/whyline/security/__init__.py`, `src/whyline/security/findings.py`, `src/whyline/security/settings.py` and `tests/security/test_settings.py`; edit `src/whyline/release/config.py` and its test only.
  - `Finding(kind, rule, title, severity, path, line, commit, preview, fingerprint, fix_hint, source)`:
    - `kind` is secret / dependency / contents / audit
    - `severity` is critical / high / medium / low / unknown
    - `source` is builtin / gitleaks / betterleaks / osv-scanner / audit
    - `preview` follows the masking rule
  - `[security]` in `release.toml`:
    - `secrets = "block"`, `dependencies = "block-high"` (block / block-high / warn / off), `contents = "block"`
    - `history_scanned = ""` (date of the last full scan)
    - `pre_commit = false`
    - `audit = "off"` (off / warn / block-confirmed)
    REL-1's `load`/`save` read and write it, and unknown values are a `ConfigError`.
  - Allowlist in `.whyline/security-allow.toml`, committed: entries `{fingerprint, rule, path, reason, added}`. `allow(root, finding, reason)` refuses an empty reason. `is_allowed(root, finding)`. `ignore_once(state_dir, finding)` lasts only for the current release run, under `.git/whyline-release/`.
  - `decide(findings, settings) -> Decision(blocking, warnings, allowed)`.
  Tests: masking for short and long values, fingerprint stability, settings round-trip and errors, allow needs a reason, decide per setting (block-high lets medium through as a warning).

- [x] SEC-2: Bundled secret rules and the Go-to-Python regex translator
  Create `src/whyline/security/rules/gitleaks.toml`, `src/whyline/security/rules/LICENSE-gitleaks`, `src/whyline/security/rules/VERSION`, `src/whyline/security/rules.py`, `scripts/update_secret_rules.py` and `tests/security/test_rules.py` only. Make sure the package data ships the `rules/` files (check `pyproject.toml`'s build config, and add the include there only if needed).
  - Copy gitleaks' `config/gitleaks.toml` from its latest release tag, with its MIT licence text. `VERSION` holds the tag and the date. `scripts/update_secret_rules.py --ref <tag>` refreshes all three. It's a developer-only script, never run by whyline.
  - `load_rules() -> RuleSet`. Each rule carries id, description, regex, secret_group, entropy, keywords (lowercased), path regex and its allowlists (regexes, stopwords, paths, `regexTarget`), plus the global allowlist.
  - `translate(go_regex) -> str`:
    - `\z` becomes `\Z`
    - a `(?i)` (or other inline flag group) that isn't at the very start becomes a scoped group `(?i:…)` covering the rest of its enclosing group, with parentheses and character classes tracked properly
    - possessive and atomic forms Python lacks are left to fail
    In today's file, 25 of 222 regexes don't compile in Python as written (22 mid-pattern flags, 3 `\z`).
  - Rules that still fail to compile are skipped, and their ids are listed in `RuleSet.skipped`.
  Tests:
  - the bundled file loads, and at least 98% of its rules compile after translation
  - `translate` on `abc(?i)def`, `x(?:a(?i)b)c`, `foo\z`, and a `(?i)` inside a character class (left alone)
  - every skipped id is reported
  - for 10 named rules (AWS access key, GitHub PAT, GitHub fine-grained PAT, Slack bot token, Stripe secret key, OpenAI key, Anthropic key, Google API key, a private key block, a generic API key), a synthetic sample matches and a near-miss doesn't. Build the samples in the test from pieces, so the test file itself never contains a matching literal: GitHub push protection and this plan's own scanner would flag it.

- [x] SEC-3: The built-in secret scanner
  Create `src/whyline/security/secrets.py` and `tests/security/test_secrets.py` only.
  - `scan_text(text, path, rules) -> list[Finding]`:
    - skip paths in the global allowlist
    - per rule, check keywords before running the regex (case-insensitive)
    - take `secretGroup` (or the whole match)
    - apply the rule's entropy threshold (Shannon entropy) and allowlists
    - mask the preview
  - `DENY_NAMES`: `.env`, `.env.*` (but not `.env.example`/`.env.sample`), `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa`, `id_ed25519`, `.npmrc` containing `_authToken`, `.pypirc` with a password, `credentials.toml`, `.whyline/relay/logs/`. Each produces a `contents`-kind finding even when nothing inside matches.
  - Scopes:
    - `scan_range(root, rev_range, *, run)`: added lines only, from `git log -p --no-color --unified=0 <range>`, with commit and line numbers
    - `scan_staged(root, *, run)`: `git diff --cached -U0`
    - `scan_paths(root, paths)`: whole files, skipping binaries (a NUL byte in the first 8 KB) and files over 2 MB
    - `scan_history(root, *, run, on_progress, cancel_event)`: `git log -p --all` streamed, with progress as commits done of `git rev-list --all --count`
  - Findings are de-duplicated by fingerprint, keeping the earliest commit.
  Tests (temp git repos, secrets built from pieces):
  - a key added in the range is found with its commit and line
  - a key removed later is still found by history and not by the range
  - the staged scope
  - a keyword miss skips the regex (spy)
  - low entropy is ignored
  - allowlisted paths are skipped
  - each DENY_NAMES case, including `.env.example` passing
  - no finding, repr or exception message contains the full secret (assert across all outputs)

- [x] SEC-4: Read dependency lockfiles
  Create `src/whyline/security/lockfiles.py`, fixtures under `tests/security/fixtures/` and `tests/security/test_lockfiles.py` only.
  - `Dependency(name, version, ecosystem, source_file, public: bool)`. `read_all(root) -> list[Dependency]` finds and parses:
    - `uv.lock`: `[[package]]` with `source.registry` on pypi.org counts as public; editable, virtual, path, git and other registries are private. The root project itself is skipped.
    - `poetry.lock`
    - `requirements*.txt`: only `name==version` pins; other lines are listed as "unpinned, not checked"
    - `package-lock.json` v2 and v3: `packages` entries under `node_modules/`, public when `resolved` is on registry.npmjs.org; `link: true` and `file:` are private
    - `pnpm-lock.yaml` and `yarn.lock`: names and versions with a small line parser, and no YAML dependency
  - Ecosystem names are OSV's (`PyPI`, `npm`). PyPI names are normalised as PEP 503 does.
  Tests: one fixture per format, with private and public entries, the root skipped, and unpinned requirements reported.

- [x] SEC-5: Check dependencies against OSV.dev
  Create `src/whyline/security/deps.py` and `tests/security/test_deps.py` only.
  - `check(deps, *, fetch, cache_dir, now) -> DepReport(findings, not_checked, error)`.
    - POST `https://api.osv.dev/v1/querybatch` with only public deps, in chunks of 500, with a 20 s timeout per call. Then GET `https://api.osv.dev/v1/vulns/<id>` for each new id.
    - Each vuln is cached for 24 hours in `~/.whyline/security/osv-cache/`.
  - Severity:
    - use `database_specific.severity` when present (GHSA's CRITICAL/HIGH/MODERATE/LOW, with MODERATE as medium)
    - otherwise the CVSS v3 base score from `severity[].score`, computed from the vector with a small built-in calculator: 9.0+ critical, 7.0+ high, 4.0+ medium, else low
    - otherwise unknown
  - `fix_hint`: "upgrade <name> to <first fixed version>" from `affected[].ranges[].events[].fixed` for the matching package, or "no fixed version yet".
  - A network failure returns `error="could not reach OSV.dev"` and no findings. The gate treats that as a warning, never as passing silently.
  Tests (fake fetch): a vulnerable and a clean package, chunking at 500, the cache hit, each severity source including a CVSS vector, fix hints, a private dep never in any request body, the network error.

- [x] SEC-6: Check what each package actually publishes
  Create `src/whyline/security/contents.py` and `tests/security/test_contents.py` only.
  - Python (`pyproject.toml` with `[project]`): run `uv build --out-dir <tmp under .git/whyline-release/build>`, list the wheel (zipfile) and sdist (tarfile) members, and run `scan_text` over each text member, plus DENY_NAMES on member names.
  - npm (`package.json`, not private): run `npm pack --dry-run --json`, then scan the listed files from the working tree.
  - Docker (`Dockerfile`): compute the build context as the files `git ls-files --cached --others --exclude-standard` lists, minus `.dockerignore` patterns (a small matcher with `*`, `**`, `!` and leading `/`), then scan those. Warn when there is no `.dockerignore`.
  - `check(root, *, run) -> list[Finding]` returns `contents` findings with `path` as `<artifact>:<member>`. A build failure is one finding, "could not build <kind>: <last line>", at warn level.
  Tests: a wheel fixture containing a `.env`, a sdist with a key in a text file, npm pack JSON listing a `.npmrc`, `.dockerignore` matching (negation included), and the build-failure finding.

- [x] SEC-7: Use gitleaks, betterleaks or osv-scanner when installed
  Create `src/whyline/security/external.py` and `tests/security/test_external.py` only.
  - `available(which=shutil.which) -> dict[str, str]` (tool → path).
  - Run the tool with JSON output to a temp file, never to stdout in the transcript:
    - secrets: `gitleaks git --log-opts "<range>" --report-format json --report-path <tmp> --redact`, and `dir` mode for paths. betterleaks takes the same flags: check its README at implementation time and adapt in this one function if not.
    - deps: `osv-scanner scan source -r . --format json`
  - Convert the results to `Finding`s. Use `source` = the tool name and the same masked preview: the `--redact` output has no secret, so the preview is `(redacted by <tool>)`.
  - `merge(builtin, external)`: de-duplicate by `(path, line, rule family)`, and prefer the external finding's rule name.
  - A tool that crashes or times out (60 s) becomes a warning, and the built-in results stand.
  Tests: parsing recorded JSON samples for each tool (fixtures written in the test, secrets built from pieces), merge de-duplication, a tool crash, `--redact` always passed.

- [x] SEC-8: `whyline security` CLI and the Release gate
  Create `src/whyline/security/scan.py`, `src/whyline/security/cli.py` and `tests/security/test_cli.py`; edit `src/whyline/cli.py` only to register it the way `_add_workflows`/`cmd_workflows` do; edit `src/whyline/release/ready.py` and its test only to register the item.
  - `scan.run(root, scope, settings, *, run, fetch, which, on_progress, cancel_event) -> ScanReport`. Scope is `release` (`origin/<branch>..HEAD` plus contents plus deps), `staged`, `history` or `all`. It combines SEC-3 to SEC-7, filters through the allowlist and ignore-once, and calls `decide`. On a completed history scan it saves `history_scanned`.
  - CLI:
    - `whyline security scan [--staged|--history|--all] [--json]`: findings grouped by kind, then a summary. Exits 1 when anything blocks.
    - `whyline security allow <fingerprint> --reason TEXT`
    - `whyline security status`: settings, tools found, rules version, last history scan
  - Release: `register_ready("security", …)`. The Ready item is ✓ with "no findings" or "N warnings", ✗ with "N blocking findings (secrets: a, dependencies: b, contents: c)", or ✗ "security scan failed: <reason>". The fix text is "Open Security to review". When `history_scanned` is empty and the repository has never been pushed (no `origin/<branch>`), a second item suggests **Scan history** (✗ only when secrets is "block").
  Tests: each scope's combination (fakes), the exit codes, allow from the CLI, `--json` contains no secret, the Ready item in each state, the history suggestion only before the first push.

- [x] SEC-9: Security in the console
  Create `src/whyline/console/security_screens.py` and `tests/console/test_security_screens.py`; edit `src/whyline/console/release_screens.py` and its test only.
  - `SecurityScreen(ModalScreen)` opens from **Security…** on the Release tab, from the Ready item's fix, and from a Security section in the Set up tab.
    - It shows findings grouped by kind: severity badge, title, `path:line`, commit short sha, masked preview and fix hint.
    - Per finding: **Fix** opens the file at the line in the console's editor (for a secret, the hint also says "rotate this key; deleting it doesn't remove it from history once pushed"). **Ignore once**. **Allow…** asks for a reason.
    - **Scan again**, **Scan history** (a worker, with progress `commits n of m` and **Stop**), and **Copy report**, which has masked values only.
  - The Set up tab's Security section has:
    - three selects (secrets, dependencies, contents) with block/warn/off, and block-high for dependencies
    - **Check every commit** (SEC-10) and Deep audit (SEC-12)
    - tools found, with the `brew install gitleaks osv-scanner` hint and **Copy** when missing
    - the rules version and date
    Everything saves through `config.save`.
  Tests: grouping and badges, Allow needs a reason and writes through `allow`, Ignore once, history scan progress and Stop, Copy report contains no full secret, the settings round-trip.

- [ ] SEC-10: Check every commit (optional pre-commit hook)
  Create `src/whyline/security/hook.py` and `tests/security/test_hook.py`; edit `src/whyline/security/cli.py`, `src/whyline/console/security_screens.py` and their tests only.
  - `install(root)` writes `.git/hooks/pre-commit` running `whyline security scan --staged --hook`. If a hook already exists and isn't whyline's, it is kept: `install` refuses and tells the user to add the line themselves (shown with **Copy**). `uninstall(root)` removes only whyline's hook. `installed(root)`.
  - `--hook` mode prints only blocking secret findings (masked) and the line `Commit stopped by whyline security. Review: whyline security scan --staged`. It exits 1 on a block and 0 otherwise. It skips the dependency and contents checks, so it stays under 2 s. With `secrets = "off"`, it exits 0 at once.
  - When it blocks a relay commit, the relay's commit fails, and with whyline-relay RLY-10 the relay pauses with the task kept. The pause message includes the hook's output, so Resolve shows it.
  - The CLI gets `whyline security hook install|uninstall|status`. The Security section's **Check every commit** switch calls the same functions.
  Tests: install, uninstall, an existing foreign hook kept, `--hook` blocking on a staged secret and passing on a clean change (a temp repo with a real commit through the installed hook), the hook output is masked, the off setting.

- [ ] SEC-11: GitHub's own protection
  Edit `src/whyline/release/setup_github.py`, `src/whyline/console/release_screens.py` and their tests only.
  - `protection_status(owner_repo, *, run)` reads `gh api repos/<o>/<r> --jq .security_and_analysis` and `gh api repos/<o>/<r>/vulnerability-alerts` (204 on, 404 off). It returns secret scanning, push protection and Dependabot alerts as on/off/unavailable.
  - `enable_protection(owner_repo, which, *, run)`:
    - `gh api -X PATCH repos/<o>/<r> -f security_and_analysis[secret_scanning][status]=enabled`, and the same for `secret_scanning_push_protection`
    - `gh api -X PUT repos/<o>/<r>/vulnerability-alerts`
    Check GitHub's REST docs at implementation time and match field names there. A 403 or 422 (for example a private repository without the needed plan) becomes "not available for this repository: <message>", never a crash.
  - The GitHub Set up panel shows the three with **Turn on** buttons, and says that GitHub's push protection is a second net, not a replacement for the local scan.
  Tests: each status, the enable argv, the unavailable message on 403/422.

- [ ] SEC-12: Deep audit run by the main agent
  Create `src/whyline/security/audit.py`, `src/whyline/security/audit_method/` (the method files and `LICENSE-cloudflare`) and `tests/security/test_audit.py` only.
  - Bundle Cloudflare's security-audit-skill method (MIT) from its latest tag, keeping the licence and a `VERSION` file:
    - the phase instructions
    - the attack-class playbooks relevant to this kind of project (LLM, prompt injection and agent tooling; supply chain and release; HTTP and auth; resource exhaustion; data isolation; desktop IPC)
    - the findings JSON schema
  - `run(root, *, agent, ask_agent, out_dir=None, cancel_event, on_progress) -> AuditReport`:
    - output goes to `~/.whyline/security/audits/<repo-name>/run-<N>/`, never inside the repository
    - the prompt gives the method, the repository path and the output directory, and says not to run the project's code (no sandbox is provided, so unverifiable leads stay `needs_validation`), not to modify the repository, and to write `findings.json` against the schema
    - it uses the relay's main agent with no timeout cap beyond the user's setting, falling back to the backup chain only on a limit or auth failure
  - The `findings.json` is validated against the schema with a small built-in validator for the schema's subset. Invalid output is kept, and the report says "the agent's output didn't match the schema", with the first errors.
  - Findings become `Finding(kind="audit", …)` keeping the verdict: confirmed, needs_validation or rejected. Rejected findings are only counted.
  Tests (fake agent writing fixture files): the output dir outside the repo, the prompt's must-not lines, a valid file to findings with verdicts, invalid JSON and schema errors reported, run numbering, cancel.

- [ ] SEC-13: Deep audit in the console and the Release gate
  Edit `src/whyline/console/security_screens.py`, `src/whyline/security/scan.py`, `src/whyline/security/cli.py` and their tests only.
  - The Security screen gets an **Audit** tab. **Run deep audit** shows that it uses your main agent, may take a long time and many tokens, and that a single run finds only part of what repeated runs do. It then runs in a worker with elapsed time and **Stop**.
  - Findings are listed by verdict and severity, with **Open report** for the run folder's `REPORT.md`. Past runs are listed.
  - `whyline security audit [--agent NAME]` calls the same function.
  - The Release gate with `audit = "warn"` shows confirmed findings from the latest audit as warnings. With `block-confirmed`, confirmed high or critical ones block. `needs_validation` never blocks. With no audit run yet, `block-confirmed` gives a ✗ "run a deep audit first".
  Tests: the tab lists runs and verdicts, Stop, each gate setting, and needs_validation never blocking.

- [ ] SEC-14: Docs
  Create `docs/security.md`; edit `docs/release.md` and `README.md` only.
  - What each check looks at, what leaves the Mac (only public package names and versions, to OSV.dev), the settings and their defaults, Allow versus Ignore once, and Scan history with why a pushed key must be rotated.
  - Check every commit, GitHub protection, the deep audit's cost and limits, and the optional tools.
  - Credits: gitleaks rules (MIT) and Cloudflare's security-audit method (MIT), with links and the bundled versions.

## Part 3: PyPI, npm, Docker, Homebrew and custom targets

Spec: `docs/superpowers/specs/2026-10-31-release-design.md`. Read it before every task. Where a name in the repository has moved, follow the repository and keep the behaviour.

Starts after Parts 1 and 2 are complete. It builds on REL-1 (config), REL-3 (`register_ready`), REL-4 (`Step`, engine), REL-5 (the CI polling helpers), REL-6 (`ask_agent`), REL-7 (`plan.build`) and REL-11 (the Set up tab).

What the user gets from this plan:
- Tick PyPI, npm, Docker, Homebrew or any custom command in **Set up**, finish that target's guided setup once, and every release then publishes there too. An unticked target is never touched.
- Each target's own Ready items, a wait step that follows its GitHub workflow, and a check that the version actually arrived.

Global constraints:
- Every constraint in Part 1 applies.
- Publish tokens for PyPI and npm are never stored anywhere: these use trusted publishing from GitHub Actions. Docker Hub's token is stored only as a GitHub repository secret, set with `gh secret set` with the value on stdin. It is never written to disk, a log, argv or the transcript.
- Workflow templates live as text in `src/whyline/release/templates/` and are written only when the user presses **Add workflow**. Each file Set up writes (workflow, Dockerfile) is recorded with `config.add_pending`, so the next release commit includes it (REL-5), never a separate commit mid-relay. Pin each action to its current major version. Before writing a template, the implementer checks the action's and registry's current docs, and records the source URL in a comment at the top of the template.
- Verify every task with `uv run pytest -q tests/release tests/console` and then `uv run pytest -q`. Change nothing outside the files a task names.

- [ ] REL-13: Target registry, workflow helpers and the plan hook
  Create `src/whyline/release/targets/__init__.py`, `src/whyline/release/workflows.py` and `tests/release/test_targets.py`; edit `src/whyline/release/plan.py` and `src/whyline/release/github.py` and their tests only.
  - A `Target` protocol: `key`, `title`, `ready_items(root, cfg, version, *, run, fetch) -> list[ReadyItem]`, `steps(root, cfg, version, *, run, fetch) -> list[Step]`, `verify(root, cfg, version, *, run, fetch) -> tuple[bool, str]`, and `setup_status(root, cfg, *, run) -> list[str]`. Plus `REGISTRY: dict[str, Target]` and `enabled(cfg) -> list[Target]` in this order: pypi, npm, docker, homebrew, custom.
  - `workflows.find_publishing(root, needle) -> Path | None`: the first `.github/workflows/*.yml` that contains `needle` and runs on tag pushes (`tags:` under `push:`). `workflows.write_template(root, name, text) -> Path` refuses to overwrite.
  - `workflows.wait_for_tag_run(root, tag, workflow_file, *, run, sleep, now, cancel_event, on_detail)` reuses REL-5's CI polling: `gh run list --workflow <file> --branch <tag> --json status,conclusion,url,databaseId`. It reports the run's status, fails with the failed job name (`gh run view <id> --json jobs`) and URL, and gives up after 45 minutes with a resumable failure.
  - `plan.build` inserts each enabled target's steps after `github_release`, then one `verify` step that calls every enabled target's `verify` and fails listing those that failed, then `after`. `ready.check` calls `ready_items` of enabled targets.
  - A Verify step has `done_check` false, so it always runs.
  Tests: order of enabled targets, finding a publishing workflow (and ignoring one that runs only on branches), no overwrite, the tag-run wait for pass/fail/timeout/cancel, `plan.build` with two fake targets, verify listing failures.

- [ ] REL-14: PyPI target
  Create `src/whyline/release/targets/pypi.py`, `src/whyline/release/templates/release-pypi.yml` and `tests/release/test_target_pypi.py`; edit `src/whyline/console/release_screens.py` and its test only.
  - The template runs on push of tags `v*`, uses environment `pypi` and `permissions: id-token: write, contents: read`, and does checkout, `astral-sh/setup-uv`, `uv build`, then `pypa/gh-action-pypi-publish`.
  - The workflow file is the existing publishing one (`find_publishing(root, "pypa/gh-action-pypi-publish")`) or `release-pypi.yml`.
  - Ready items:
    - the workflow exists
    - the project name is in `pyproject.toml`
    - `https://pypi.org/pypi/<name>/<version>/json` is 404, meaning the version isn't published yet. A network error gives "could not reach PyPI".
  - Steps: `pypi` waits for the tag run of the workflow. Its `done_check` is that the version JSON returns 200.
  - Verify: the version JSON returns 200, retried for up to 5 minutes (injected sleep), because PyPI's index lags.
  - `setup_status` lines:
    - whether the workflow exists, with its path
    - whether the project exists on PyPI
    - the values for pypi.org's trusted publisher form: owner, repository, workflow file name, environment `pypi`, and for a new project "use Add a pending publisher"
  - Console: the PyPI **Set up…** panel shows those lines, with **Add workflow** (shown when none exists), **Open pypi.org** (opens `https://pypi.org/manage/account/publishing/` with `open`) and **Ask agent**.
  Tests: ready on 404/200/network error, reuse of an existing publishing workflow, template written once, verify retry, the panel's buttons and lines.

- [ ] REL-15: npm target
  Create `src/whyline/release/targets/npm.py`, `src/whyline/release/templates/release-npm.yml` and `tests/release/test_target_npm.py`; edit `src/whyline/console/release_screens.py` and its test only.
  - The template runs on tag `v*` with `permissions: id-token: write, contents: read`. It uses `actions/setup-node` with `registry-url: https://registry.npmjs.org`, a current Node LTS, an npm new enough for trusted publishing (upgrade npm in the job when needed), `npm ci`, then `npm publish --provenance --access public`. Before writing it, check npm's trusted-publishing docs and match them.
  - The workflow file is found by `find_publishing(root, "npm publish")`, or `release-npm.yml`.
  - Ready items: the workflow exists, `package.json` has a name and isn't private, and the version isn't on npm (`https://registry.npmjs.org/<name>/<version>` returns 404; scoped names URL-encoded).
  - Steps: `npm` waits for the tag run. Its `done_check` is that the registry URL returns 200.
  - Verify: the same URL returns 200, retried for up to 5 minutes.
  - `setup_status` lines:
    - whether the workflow exists
    - whether the package exists on npm
    - the values for npmjs.com's trusted publisher form (owner, repository, workflow file name)
    - for a package that isn't published yet, the first-publish rule from npm's docs as found during this task. If npm needs a first manual publish: "Run `npm login` and `npm publish` once in a terminal; later releases publish automatically."
  - Console: the npm panel, with **Add workflow**, **Open npmjs.com** and **Ask agent**.
  Tests: as for PyPI, plus a scoped package name and a private package refused in ready.

- [ ] REL-16: Docker target
  Create `src/whyline/release/targets/docker.py`, `src/whyline/release/templates/release-docker.yml` and `tests/release/test_target_docker.py`; edit `src/whyline/console/release_screens.py` and its test only.
  - The template runs on tag `v*` with `permissions: contents: read, packages: write`. It uses `docker/setup-buildx-action`, `docker/login-action` (GHCR through `GITHUB_TOKEN`; Docker Hub through `secrets.DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN`, written only when `dockerhub` is in `registries`), `docker/metadata-action` (tags `v<version>`, `<version>` and `latest`) and `docker/build-push-action` with `push: true`. The image name comes from config (default `<owner>/<repo>`, lowercased).
  - Ready items:
    - a `Dockerfile` exists
    - the workflow exists
    - for Docker Hub, both secrets are present (`gh secret list --json name`)
  - Steps: `docker` waits for the tag run.
  - Verify: `docker manifest inspect <ref>:<version>` when `docker` is installed. Otherwise the tag run's success counts, with a note.
  - `store_dockerhub_secrets(root, username, token, *, run)` runs `gh secret set DOCKERHUB_USERNAME` and `gh secret set DOCKERHUB_TOKEN` with the values on stdin only.
  - `draft_dockerfile(root, *, ask_agent) -> str` asks the main agent for a Dockerfile for this project (language, entry point and lockfile from the tree listing and the manifest files), saying it must be small and non-root.
  - Console: the Docker panel shows status, registry checkboxes (GHCR/Docker Hub), image name and **Add workflow**.
    - **Draft Dockerfile** puts the draft in a read-only view with **Save as Dockerfile** and **Discard**.
    - The Docker Hub username field and a masked token field (`Input(password=True)`) go with **Store as GitHub secrets**, which clears the field after storing and never logs it.
    - **Ask agent**.
  Tests:
  - the template with and without Docker Hub
  - the ready items
  - the secrets go on stdin and never in argv (assert the sentinel isn't in any recorded argv or transcript event)
  - the draft goes through `ask_agent` and is never written without Save
  - verify with and without docker

- [ ] REL-17: Homebrew target
  Create `src/whyline/release/targets/homebrew.py` and `tests/release/test_target_homebrew.py`; edit `src/whyline/console/release_screens.py` and its test only.
  - The tap defaults to `<owner>/homebrew-tap` and the formula to the project name. `create_tap(owner, name, *, run)` runs `gh repo create <owner>/homebrew-<name> --public` (taps must be public for `brew tap` without credentials, so say so in the panel).
  - The tap is worked in a scratch clone: `gh repo clone <tap> <tmp>` under `.git/whyline-release/tap`, refreshed with `git pull` on reuse.
  - Ready items: the tap repository exists (`gh repo view`), `Formula/<formula>.rb` exists in it, and you can push (`gh api repos/<tap> --jq .permissions.push`).
  - Step `homebrew` (irreversible):
    1. Download `https://github.com/<owner>/<repo>/archive/refs/tags/v<version>.tar.gz` through `fetch` and compute its sha256.
    2. Replace the formula's `url` and `sha256` lines (only those lines).
    3. When the formula contains `resource "` blocks and `brew` is installed, run `brew update-python-resources <path>`. When `brew` is missing, keep the old resources and add a warning to the step detail.
    4. Commit `<formula> <version>` and push.
    Its `done_check` is that the tap's formula already has the new url.
  - Verify: the tap's formula on the remote (`gh api repos/<tap>/contents/Formula/<formula>.rb`) contains the version's URL.
  - `draft_formula(root, *, ask_agent)`: the agent writes a first formula (a `Language::Python::Virtualenv` formula for a Python project, with the test block running `<cli> --version`). You review it in the panel, and **Push to tap** commits it.
  - Console: the Homebrew panel shows tap and formula fields, **Create tap**, **Draft formula**, **Push to tap**, the `brew tap <owner>/<name>` / `brew install <formula>` lines users will run, with **Copy**, and **Ask agent**.
  Tests: the sha256 from a fixture tarball, only the url and sha256 lines change, resources updated when brew exists and a warning when it doesn't, `done_check`, verify, create_tap argv, the draft is reviewed before push.

- [ ] REL-18: Custom targets
  Create `src/whyline/release/targets/custom.py` and `tests/release/test_target_custom.py`; edit `src/whyline/console/release_screens.py` and its test only.
  - Ready item per entry: the first word of `run` (after `shlex.split`) is on PATH, or is a path that exists.
  - One irreversible step per entry, `custom:<name>`, running `run` with `shell=True` in root, with `WHYLINE_RELEASE_VERSION=<version>` and `WHYLINE_RELEASE_TAG=v<version>` in the environment. Lines stream to detail, and a failure shows the last 20 lines. Its `done_check` runs `verify` when set (exit 0 = done), otherwise false.
  - Verify: each entry's `verify` exits 0. Entries without one count as verified, with "no verify command" in the detail.
  - Console: the Custom panel lists entries with **Add**, **Edit** and **Remove** (name, command, optional verify command), and saves through `config.save`.
  Tests: ready on a missing command, the env vars reach the command, `verify` as `done_check`, the editor round-trips through `config.save`, a duplicate name is refused.

- [ ] REL-19: End-to-end check and docs
  Create `tests/release/test_end_to_end.py`; edit `docs/release.md` and `README.md` only.
  - An end-to-end test: a temp repository with a bare origin, every target enabled through fakes for `gh`, `fetch`, `brew` and `docker`, and auto mode. It runs `plan.build` and the engine to completion. Then:
    - a second run is refused as already released (tag exists)
    - a run failed at the PyPI wait resumes and finishes without repeating the tag or the GitHub release (assert the fake `gh` saw `release create` once)
    - an unticked target's steps never appear and none of its commands run
  - `docs/release.md`: a section per target (what it publishes, the one-time setup, where tokens live or why there are none, how to verify by hand), plus a troubleshooting list built from each step's failure messages.

## Part 4: Relay chat answers that stopped early (found while running this plan, 2026-11-06)

On 2026-11-06 the Chat tab was asked "status" while grok reviewed REL-10. The working line went away and the whole answer was "I'll read the relay snapshot and project state, then answer with the current status." Chat runs grok read-only (`--permission-mode dontAsk`, no allowed shell commands, `agents/capabilities.py:_grok`), and headless grok ends its whole turn as cancelled on any command outside that, with exit 0, `"stopReason": "cancelled"` and only its opening line as text. `ask.ask` treated that as an answer, and `ask.final_message` is still a stub that returns its input. The tab also showed a 4 Nov "adhoc" answer about PZ-1 as if it were current, because `RelayChatPanel` reads `_run_id` once when it's created, while `ask` saves under the run id of the moment. And `test_transcript_line_reopens_report_and_ask_feeds_chat` wrote `~/.whyline/relay-chat/test_transcript_line_reopens_r0-…` to the real home folder.

- [ ] CHF-1: Chat retries a cancelled grok turn and never shows its opening line as the answer
  Edit `src/whyline/relaychat/ask.py`, `src/whyline/console/relay_chat_tab.py` and `tests/console/test_fixmode_check.py`, with tests in `tests/relaychat/test_ask.py` and `tests/console/test_relay_chat_tab.py`.
  1. `INSTRUCTIONS` gains: "Everything you need is in the snapshot below. Answer from it. Read a file only when the snapshot doesn't have what the question needs, and never run shell commands."
  2. Add `ask.cancelled_turn(cli: str, raw: str) -> bool`: true for grok when the JSON object in `raw` (parse it the way `whyline.agents.runner._answer` does) has `stopReason == "cancelled"`. Other CLIs return False. Add `ask.refused_command(raw: str) -> str | None`: the command in the first "permission required: Execute `<command>`" in `raw`, else None.
  3. In `ask.ask`, when the run exits 0 but `cancelled_turn` is true, and the user didn't press Stop:
     - Run once more. When `raw` has a `sessionId`, use the same command with `--resume <sessionId>` inserted just before the final `-p`. Otherwise, start fresh with the same prompt. The retry prompt is: "Your last turn was stopped because a shell command isn't allowed in this read-only chat. Don't run shell commands. Answer the question from the snapshot you were given." When `refused_command` found one, add before it: "Your last command, `<command>`, is not allowed."
     - A retry that answers normally is the answer, and is saved like any other.
     - When the retry is cancelled too, or fails, the answer is `ok=False`: "<cli> stopped before answering: its read-only mode refused `<command>`. Ask again, or pick another agent in the list above." Without a found command: "<cli> stopped before answering (its read-only mode refused a command). Ask again, or pick another agent in the list above."
     - A cancelled turn's text is never returned or saved as an answer.
     - `ask` gains keyword `on_progress: Callable[[str], None] | None = None` and calls it with "<cli> was stopped by its read-only rules, retrying…" before the retry.
  4. The Chat tab passes `on_progress`. The working line shows that text, keeping the spinner and the elapsed seconds, until the answer arrives. Stop still cancels the retry.
  5. History follows the run. Before each question and each time the tab is shown, `RelayChatPanel` re-reads the run id with `_current_run_id()`. When it has changed, it updates `_run_id` and reloads the log. History entries older than today show their date in the log, as `You (4 Nov): …` and `Agent (4 Nov): …`.
  6. In `tests/console/test_fixmode_check.py`, the `repo` fixture sets `HOME` to `tmp_path / "home"` with `monkeypatch.setenv`, the way `test_relay_chat_tab.py` does, so no test writes under the real `~/.whyline`.
  Tests (fake runner, no real grok):
  - a cancelled grok output (exit 0, `stopReason: cancelled`, text "I'll read the relay snapshot…", a "permission required: Execute `git -c x diff`" line, a `sessionId`) followed by a normal answer: the second call has `--resume <id>` before `-p`, its prompt names `git -c x diff`, `on_progress` got the retry text, and the answer and history are the second answer
  - cancelled twice: `ok` is False, the text names the command, and history has no "I'll read the relay snapshot" entry
  - a cancelled turn without a `sessionId` retries fresh with the retry prompt
  - a codex or claude output with a `stopReason` key is not treated as cancelled
  - a cancel_event set during the first run gives `STOPPED` and no retry
  - the tab's working line shows the retry text with the spinner and seconds, then clears on the answer
  - changing the run id between two questions reloads the log for the new run, and an entry dated yesterday shows its date
  - `INSTRUCTIONS` contains "never run shell commands"
  - after the Check tests, nothing under the real home is touched (the fixture's HOME is under tmp_path)

On 2026-11-06 the console also showed "⏸ Pausing — letting antigravity finish its turn so nothing is lost" for over 12 minutes while the relay itself had no pause request: `whyline_relay.status.pause_state` said `none` and `.whyline/relay/PAUSE` did not exist. The run had been paused at 14:50 and resumed at 14:56. `_sync_pause_buttons` shows Pausing when `self._pause_requested or kind == "pausing"`, and clears `_pause_requested` only when a tick sees no running relay while the Relay buttons are mounted, so a pause and resume made while another screen was open left the flag on for the next run. The same screen showed the 16 relay buttons as a 6-column grid of equal, mostly empty cells over 3 rows (`#controls.wrap`, `grid-size: 6`), where two packed rows fit.

- [ ] CHF-2: Pausing shows only while the relay has a pause request
  Edit `src/whyline/console/tui.py`, with tests in `tests/console/test_pause_status.py`.
  1. `_pause_requested` only bridges the click to the relay seeing `PAUSE`. In `_sync_pause_buttons`, once `pause_state` has returned `pausing` since the flag was set, a later `none` while a relay runs clears the flag ("Pause withdrawn." as today). A flag set more than 10 seconds ago whose request never showed is cleared too.
  2. Starting or resuming a relay from the console (Run, Resume, Keep going after a pause, Continue with, Resolve's resume) sets `_pause_requested = False` and `_quit_when_paused = False` before the process starts.
  3. When the flag is cleared because the request is gone, the status line and the Pausing / Pause now / Keep going buttons go back to Pause on the same tick.
  Tests:
  - flag set, relay running, `pause_state` returns `pausing` then `none`: the next tick shows Pause, not Pausing
  - flag set with a fake clock, `pause_state` stays `none` for 11 seconds while running: Pausing goes away
  - the 14:50 case: flag set, a pause screen pushed so the ticks can't reach the buttons, the relay pauses and a new run starts; after resume the bar shows Pause and the status line has no Pausing text
  - Resume after a pause clears both flags before the process starts (fake process)
  - a real pending request (`pause_state` `pausing`) still shows Pausing with Pause now and Keep going

- [ ] CHF-3: The button bar wraps into packed rows, not a wide 6-column grid
  Edit `src/whyline/console/tui.py`, with tests in `tests/console/test_awake.py` and a new `tests/console/test_controls_rows.py`.
  1. `_fit_controls` keeps one row when the visible buttons fit. Otherwise it picks the fewest rows (2, then 3, …) where every row fits the bar's width, using the same width estimate as today (`max(6, len(label) + 2)` per button), with columns = ceil(visible / rows) and each grid column as wide as its widest button.
  2. It sets that on `#controls` as `styles.grid_size_columns` with `grid-columns: auto` in `#controls.wrap`, so no cell is wider than its button. Buttons keep their order, left to right then top to bottom.
  3. It runs again when the window or the split pane is resized and when a label changes (Mark released, Awake ●), as today.
  Tests:
  - the Relay bar while a relay runs (16 visible buttons, as in Pausing) at 130 columns wide uses 2 rows and every button's region is inside the bar
  - at 80 columns, the same bar uses the fewest rows that fit, and no button is cut off (`test_each_mode_row_fits_80_columns_with_awake` still passes)
  - no gap between two neighbouring buttons in a row is wider than 2 cells
  - a bar that fits stays one row without the `wrap` class

## Release

- [ ] RLS-1: Publish whyline with the Release button (REL-1..19), the security checks (SEC-1..14) and the Chat and console fixes (CHF-1..3)
  relay-profile: release
  Bump the version in `pyproject.toml`, `src/whyline/__init__.py` and `uv.lock` to the next patch version. Write `docs/releases/v<version>.md` from every task since the previous release (`git log v<previous>..HEAD`), in user terms. Run `uv run pytest -q` with the agent CLIs off PATH and `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1`, and again on Python 3.11. Push, wait for green CI on Linux and macOS, then tag `v<version>`, push the tag and let the release workflow publish to PyPI. Afterwards run `uv tool upgrade whyline` and confirm `whyline --version`.
