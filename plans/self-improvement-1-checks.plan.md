<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-02T12:00:00+05:30 -->
# Self-improvement: scheduled self-checks that find, plan, fix and report, across chosen repos — 1: settings, checks, GitHub and the workspace

Runs after `plans/job-search-5d-after-apply.plan.md`, and before `plans/self-improvement-2-fix.plan.md`. Split on 2026-11-15 from `self-improvement.plan.md` (37 tasks) into three plans, so each relay is short and ends with a release. This file builds: Parts 1 and 2 (IMP-1..10). Design: `docs/superpowers/specs/2026-11-02-self-improvement-design.md`. Read it before any task. Where this plan and the design differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the design's behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

There is no publish task (removed 2026-11-11). When the relay finishes, press **Release**: it sets the version, writes the notes, runs the checks and the security scan, pushes, waits for CI, tags and publishes. This repository's relay has no `release` profile, so a publish task would only bump the version.

What the user gets:
- **Settings → Self-improvement** in the console holds all of it:
  - an **On / Off** switch for the loop
  - **Daily** (optionally weekdays only), **Weekly** on chosen days, or **Monthly** on a day or the last day, at a set time
  - messages and delivery
  - limits
  - the repos it looks after, each at a permission level: **Report only**, **Plan** or **Fix and ask** (default)

  **Relay → Set up** shows the current repo's line, with a link into that tab.
- On each scheduled run, one run goes through every repo, one at a time. For each repo it:
  1. pulls the latest default branch into its own clone, and checks it: tests, extra checks, CI on the default branch
  2. looks up newly published **vulnerabilities** in its dependencies (OSV.dev, plus Dependabot alerts when available)
  3. reviews it with a read-only agent, which says how to resolve each problem and each vulnerability
  4. writes a Small fix plan through the SDLC pipeline
  5. makes the fix locally with the relay
  6. runs a mechanical guard on the diff, then rechecks
  7. **tells the user what changed and waits.** Nothing is pushed until the user approves that exact change. Then it pushes a branch and opens a PR. Merging is also only on the user's approval.
- One combined Telegram and/or email message per run, sent even when all is well, with a Word report and the change's `.patch` attached. Approval cards: **Push and open PR** / **Discard**, and **Merge** / **Close** once CI is green. Immediate alerts for crashes, guard refusals, time limits, missed runs and new high or critical vulnerabilities.
- `whyline improve …` on the command line, calling the same functions.

Rules every task keeps:
- Console first: every console action saves through the same function the CLI calls.
- No new dependency. Word goes through `whyline.agents.docx`. Sending goes through `whyline.agents.deliver.send`. GitHub goes through the `gh` CLI, called with an injectable `run`.
- New non-widget code goes in `src/whyline/improve/`, with tests in `tests/improve/`. Console code goes in the files a task names, with tests in `tests/console/`.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- Tests never:
  - run a real agent, relay, `gh` or `git push` to a real remote
  - call Telegram, send mail or open a socket
  - contain "/Users/"

  Use fakes for `run`, the clock, the agent runner, the relay launcher and `deliver.send`. Real `git` is allowed only on temporary repos made inside the test.
- Self-improvement never writes to the user's own checkout or its `.git`, never pushes a default branch, and never force-pushes a branch it didn't create.
- **Human in the loop for GitHub:** no code path pushes, opens a PR or merges, except the approval functions in `improve/changes.py`. Each of those requires an approval naming the exact commit sha shown to the user. A test in IMP-23 checks this by searching the package for calls to `github.push`, `create_pr` and `merge`.
- Advisory text from OSV and Dependabot is untrusted data, the same as test output.
- No secret appears in a report, digest, log, PR body or alert. Redact through `improve.report.redact` (IMP-17).


**Added 2026-11-15 (IMP-38..46):** model levels (Best for review and planning, Standard for the fix), catch-up after a missed run and keeping the Mac awake, a dismissed list, a rotating review focus, a second opinion on serious findings, suggestions for findings that are too big, and the run's cost. This file has IMP-38 and IMP-39. IMP-37's documentation covers all of them.


**Reuse what exists now (decided 2026-11-15; this wins over the task text below).** This plan was written on 2026-11-02, before these existed:
- **IMP-6, CI status:** when the latest run failed, get the reason from `whyline.release.ci_failure.diagnose` (cause and plain sentence) and put that in the tail, instead of only the URL. Keep `ci_status`'s own signature.
- **IMP-8 and IMP-9, dependencies and vulnerabilities:** `whyline.security.deps` already reads lock files and queries OSV with a cache (`check`, `severity_of`). Build `improve/deps.py` and `improve/vulns.py` as thin layers over it, adding only what it lacks (the `fixed` versions, `direct`, Dependabot alerts, and "what's new since the last run"). Do not write a second OSV client or a second severity mapping.

## Part 1: Ready

- [ ] IMP-1: SDLC Auto with build off
  Edit `src/whyline/sdlc/runner.py` and its tests only.
  1. `run(...)` gets a keyword `build: bool = True`.
     - With `build=False`, Auto stops after the plan stage. The plan is approved and written under `plans/`, and `run` returns the plan path.
     - It does no Auto preflight, never calls `relay_ops.select_plan`, never calls `launcher`, and never writes `.whyline/relay/config.toml`.
  2. Add `run_build_record(root, slug, *, progress) -> StageResult`, which runs only the build-record stage for a set whose plan was built outside the console.
  Tests:
  - `build=False` writes the plan and test plan, and leaves `config.toml` byte-identical
  - the launcher stub is never called
  - `run_build_record` adds a build-record version

## Part 2: Settings, checks, GitHub and the workspace

- [ ] IMP-2: Repos and settings files
  Create `src/whyline/improve/__init__.py`, `src/whyline/improve/paths.py`, `src/whyline/improve/settings.py` and their tests.
  1. `paths.home()` is `~/.whyline/improve`, overridable by `WHYLINE_IMPROVE_HOME` for tests. Files are written 0600, and folders 0700.
  2. `Repo(name, path, level, test_command="", checks=(Check(name, command, timeout_minutes),...), fix_from="medium", max_fixes=3, max_minutes=90, max_changed_lines=400, never_touch=(...defaults...), paused=False, accepted_hash="")`. `LEVELS = ("report", "plan", "fix")`, default `"fix"`. There is no level that pushes or merges.
  3. `Settings(enabled=False, schedule=Schedule(), digest="combined"|"per-repo", run_minutes=240, max_agent_starts=40, paused=False, repo_defaults=RepoDefaults(...))`. `Schedule` comes from IMP-4. Until that task exists, store it as a table and validate it there.
     - `enabled` is the On/Off switch: Off means no scheduled runs, and Run now still works.
     - `paused` is the temporary Pause, which also stops a running run at its next step.
     - `repo_defaults` fills new repos' limits.
  4. `load_repos()`, `save_repo(repo)`, `remove_repo(name)`, `load_settings()` and `save_settings(s)`, using `repos.toml` and `settings.toml`. Names are unique, matching `^[a-z0-9][a-z0-9-]{0,39}$`, and default to the folder name.
  Tests: round-trip, file modes, a duplicate name refused, a bad level refused, a bad time refused, defaults filled in.

- [ ] IMP-3: Levels, what they allow, and acceptance
  Edit `src/whyline/improve/settings.py` and its tests only.
  1. `allows(repo) -> list[str]` returns plain lines for the level, for example:
     - "Runs your test command and these checks: …"
     - "Looks up vulnerabilities in your dependencies on OSV.dev (sends package names and versions only)"
     - "Makes fixes in its own copy of the repo on improve/… branches, and asks you before pushing anything"
     - "Pushes and opens a pull request only when you approve a change; merges only when you approve"
  2. `capability_hash(repo)` hashes the level, path, test command, checks and never_touch list. `accept(name)` stores it. `accepted(repo) -> bool` compares it.
  3. Any change to those fields makes `accepted` False until accepted again. A runner must skip a repo that isn't accepted, with the reason `not accepted since its settings changed`.
  Tests: each level's lines, a raised level needing acceptance, a changed check needing acceptance, and changing `max_fixes` not needing it.

- [ ] IMP-4: Daily, Weekly and Monthly schedules
  Create `src/whyline/improve/schedule.py` and its tests.
  1. `Schedule(frequency="daily"|"weekly"|"monthly", at="02:00", weekdays_only=False, days=("mon",), day_of_month=1 | "last")`.
     - `validate(schedule)` raises a plain `ScheduleError`:
       - a bad time
       - weekly with no days
       - a day of month outside 1–28 that isn't "last"
     - Days 29–31 are refused, with "use Last day", so every month has the day.
  2. `due_times(schedule, *, after, until) -> list[datetime]` uses local wall-clock time and is built per calendar day, as `agents.schedule` does, so daylight-saving changes need no special case.
     - Daily with `weekdays_only` skips Sat and Sun.
     - Weekly fires on each listed day.
     - Monthly fires on the day, or on the month's last day for "last".
  3. `next_due(schedule, now)`, `freshness(schedule)` (2 hours), and `describe(schedule)`, for example "daily at 02:00", "weekdays at 02:00", "weekly on Mon, Thu at 02:00" or "monthly on the last day at 02:00".
  4. `to_table` / `from_table` are used by `settings.py`. Replace IMP-2's interim table with `Schedule`.
  Tests:
  - each frequency across a month boundary
  - "last" in February in a leap year and a non-leap year
  - weekdays only over a weekend
  - a DST change day
  - each validation error
  - `describe` text

- [ ] IMP-5: Running checks
  Create `src/whyline/improve/checks.py` and its tests.
  1. `run_check(cwd, name, command, timeout_minutes, *, run) -> CheckResult(name, ok, flaky, code, seconds, tail, log_path)`:
     - The command runs through `shlex.split`, never a shell.
     - A timeout is a failure, with `code=None` and the tail ending "timed out after N min".
     - The full output goes to `log_path`. `tail` is the last 60 lines.
  2. A failing **test** check is run once more. If it passes then, the result is `ok=True, flaky=True`. Other checks aren't rerun.
  3. `run_all(cwd, repo, run_dir, *, run) -> list[CheckResult]`: the test command first, then the extra checks in order.
  Tests: pass, fail, flaky, timeout, the tail capped at 60 lines, and no shell (a command with `;` is passed as an argument).

- [ ] IMP-6: CI status and Detect
  Edit `src/whyline/improve/checks.py` and its tests only.
  1. `ci_status(cwd, branch, *, run) -> CheckResult` reads the latest run on the branch with `gh run list --branch B --limit 1 --json conclusion,status,url,name`.
     - `success` → ok
     - `failure` → not ok, with the url in the tail
     - still running, or no runs → ok with the tail "no finished CI run"
     - `gh` missing or failing → ok with the tail "CI status unavailable: <first line>"
  2. `detect(path) -> list[Check]` suggests checks from the files present:
     - `pyproject.toml` with ruff configured → `ruff check`
     - `uv.lock` → `uv lock --check`
     - `pyproject.toml` with `requires-python` allowing 3.11 → `uv run --python 3.11 pytest -q`
     - `package.json` with a `lint` script → `npm run lint`
     - A suggestion is never added on its own.
  Tests: each `gh` outcome with a fake run, and detect on temporary folders.

- [ ] IMP-7: GitHub through gh
  Create `src/whyline/improve/github.py` and its tests. Every function takes `run` and `cwd`, and raises `GitHubError` with a plain message.
  1. `can_push(cwd) -> tuple[bool, str]` uses `gh auth status` and `gh repo view --json viewerPermission,defaultBranchRef`. Push is allowed for WRITE, MAINTAIN or ADMIN.
  2. `default_branch(cwd) -> str`.
  3. `open_improve_pr(cwd) -> PR | None` returns the open PR whose head starts with `improve/` and was created by the signed-in user (`gh pr list --state open --json number,headRefName,url,author`).
  4. `push(cwd, branch)` runs `git push -u origin <branch>`. It refuses a branch that doesn't start with `improve/`, and refuses the default branch.
  5. `create_pr(cwd, branch, title, body_file) -> PR` uses `--body-file`, never the body on the command line.
  6. `pr_state(cwd, number) -> PRState(open, merged, ci="green"|"red"|"running"|"none", head_sha)`, using `gh pr view N --json state,mergedAt,headRefOid,statusCheckRollup`. It never waits.
  7. `merge(cwd, number)` runs `gh pr merge N --squash --delete-branch`. `close(cwd, number)` runs `gh pr close N --delete-branch`.
  8. `dependabot_alerts(cwd) -> list[dict] | str` uses `gh api repos/{owner}/{repo}/dependabot/alerts?state=open --paginate`. On 403 or 404 it returns the plain reason, `Dependabot alerts not available: <reason>`, instead of raising.
  Tests: each with a fake run, including refusals for `main` and for `feature/x`, a PR body with backticks and `$()` passed through a file, `pr_state` for each CI value, and Dependabot 403.

- [ ] IMP-8: Read dependencies from lock files
  Create `src/whyline/improve/vulns.py` and its tests.
  `dependencies(root) -> list[Dep(ecosystem, name, version, direct, source_file)]`:
  - **Python (`PyPI`):**
    - `uv.lock` (`[[package]]` name/version)
    - `poetry.lock`
    - `requirements*.txt` lines pinned with `==`. Unpinned lines are listed in `unpinned` and not looked up.
  - **npm:**
    - `package-lock.json` (`packages`, v2 and v3)
    - `pnpm-lock.yaml` (the `packages:` keys only, parsed by hand, with no YAML dependency)
  - **`direct`:** the name is listed in `pyproject.toml` `[project].dependencies` / optional groups, or in `package.json` dependencies / devDependencies.
  - Names are normalised the same way OSV expects (PEP 503 for PyPI). Duplicates are removed.
  - Files are parsed with `tomllib` / `json` only. A file that doesn't parse is reported in `problems` and skipped.
  Tests: each format from small fixture files, direct versus transitive, normalisation, an unparseable file, and unpinned lines.

- [ ] IMP-9: Look up vulnerabilities, and what's new
  Edit `src/whyline/improve/vulns.py` and its tests only.
  1. `lookup(deps, *, http) -> list[Vuln] | str`:
     - It posts to `https://api.osv.dev/v1/querybatch` in chunks of 500, through the injected `http(url, body_bytes, timeout) -> bytes`. The default uses `urllib.request` with a 30 s timeout.
     - It fetches the details of each returned id from `https://api.osv.dev/v1/vulns/<id>`, at most 200 per run.
     - `Vuln(id, aliases, summary, severity, score, published, package, version, fixed, direct, url)`:
       - **severity:** critical, high, medium, low or unknown, from the CVSS v3 base score when present (9.0 / 7.0 / 4.0 cut-offs), else from `database_specific.severity`
       - **fixed:** the `fixed` events for the affected range
     - A network or parse failure returns `vulnerability check unavailable: <reason>`. It never raises.
  2. `from_dependabot(alerts) -> list[Vuln]` maps Dependabot alerts the same way. `merge(osv, dependabot)` removes duplicates by id and aliases.
  3. **New since last run:** `mark_new(repo_name, vulns) -> list[Vuln]` sets `new=True` on ids not in `home()/seen/<repo>.json`, then saves the ids. Removing a repo removes its file.
  4. All summary text passes through `report.redact`. A summary is cut to 500 characters.
  Tests, all with a fake `http`:
  - a batch with no vulnerabilities
  - a batch with two, details fetched
  - each severity mapping, and the CVSS cut-offs
  - fixed versions
  - chunking at 500
  - the detail cap
  - a timeout → the unavailable text
  - Dependabot mapping and de-duplication
  - new on the first sighting and not on the second

- [ ] IMP-10: The clone, held fixes and skip reasons
  Create `src/whyline/improve/workspace.py` and its tests.
  1. `clone_dir(repo)` is `home()/work/<name>`.
  2. `prepare(repo, *, run) -> Path`:
     - If the clone doesn't exist, it runs `git clone <origin url of repo.path> clone_dir`.
     - It then runs `git fetch origin`, `git checkout -B <default> origin/<default>`, `git reset --hard` and `git clean -fdx -e .whyline/relay/state.json`.
     - It refuses when the repo has a held fix.
  3. Held fixes:
     - `hold(repo, branch, reason)` writes `home()/held/<name>.json`.
     - `held(repo) -> Held | None` reads it.
     - `discard(repo)` removes the record, checks out the default branch in the clone, and deletes the local `improve/*` branch.
  4. `skip_reason(repo, settings, *, run, relay_live) -> str | None` checks, in this order:
     - Self-improvement paused
     - the repo paused
     - the repo not accepted
     - a relay live in `repo.path` (`relay_live` defaults to `whyline_relay.running.live`)
     - the user's path missing or not a git repo
  5. `fix_blocked(repo, *, run) -> str | None` is separate. A blocked repo is still checked, looked up and reviewed, but gets no new fix. It returns, in order:
     - "a change is waiting for your approval since <date>" (IMP-20)
     - "fix held since <date>: <reason>"
     - "PR #N is open (CI <state>)"
     - None
  Tests:
  - real git, with a temporary origin and a bare remote
  - the clone is made once, and is reset when dirty
  - the user's checkout is unchanged: same files and same `git for-each-ref` output
  - prepare refuses while a fix is held
  - each skip reason and each fix-blocked reason, in order

- [ ] IMP-38: Model levels: Best and Standard for each agent
  Create `src/whyline/modellevels.py` and `tests/test_modellevels.py`. Edit `src/whyline/improve/settings.py`, `src/whyline/console/settings_screen.py`, `src/whyline/cli.py` (a `whyline models` command) and their tests.
  1. `LEVELS = ("best", "standard")`. `modellevels.load() -> dict[str, dict[str, str]]` (agent → level → model name) from `~/.whyline/models.toml` (0600), filled with defaults for agents the file doesn't name: claude `best = "opus"`, `standard = "sonnet"`; every other agent `""` for both, meaning "the CLI's own default".
  2. `modellevels.model(agent, level) -> str` and `modellevels.save(agent, level, model)`. A model name is one line of at most 80 characters matching `^[A-Za-z0-9._:/-]*$`; anything else is refused.
  3. `improve.settings.Settings` gains `models: dict[str, str]`, one level per step: `review`, `plan`, `plan_review`, `fix`, `test`, `fix_review`. Defaults: `best` for review, plan, plan_review and fix_review; `standard` for fix and test. An unknown step or level is refused. These are not part of `capability_hash`: changing a model level doesn't need a new acceptance.
  4. CLI: `whyline models` prints the table. `whyline models set <agent> <best|standard> <model>` saves.
  5. Console: the Settings screen's providers area gets a **Models** table, one row per enabled agent with **Best** and **Standard** inputs, saving through `modellevels.save`. An empty input shows `CLI default`.
  Tests: defaults, round trip, file mode, a bad model name refused, the six step defaults, an unknown level refused, a level change keeping the repo accepted, and CLI and console saving through one function.

- [ ] IMP-39: The dismissed list
  Create `src/whyline/improve/dismissed.py` and `tests/improve/test_dismissed.py` only.
  1. A finding's `key(repo_name, finding) -> str`: a hash of the repo name, the finding's kind, the vulnerability id when it has one, else its title lower-cased with digits and whitespace runs collapsed, and the first file path in its evidence. The same problem reported with a different line number or wording of the evidence gives the same key.
  2. `home()/dismissed.json` (0600): `key`, `repo`, `title`, `kind`, `reason`, `by`, `at`, and `until` (empty for always). `add(repo_name, finding, *, reason, by, days: int | None = None)`, `remove(key)`, `listing(repo_name=None)`, and `is_dismissed(repo_name, finding, *, now) -> bool` (an entry past its `until` no longer counts and is removed).
  3. A dismissed **vulnerability** comes back when its severity rises or a fixed version appears that wasn't there when it was dismissed: the entry stores the severity and the fixed versions, and `is_dismissed` compares them.
  4. At most 500 entries; the oldest are dropped.
  Tests: the same key across line-number and wording changes, different keys for different files, add, remove, expiry, the vulnerability coming back on a higher severity and on a new fixed version, and the cap.
