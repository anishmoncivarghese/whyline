<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-01T12:00:00+05:30 -->
# Job search, part 5: saved searches, a setup check, run results with tailored CVs, and an apply pack — b: saved searches and the Check page

Runs after `plans/job-search-5a-companies-cv.plan.md`, and before `plans/job-search-5c-results-apply.plan.md`. Split on 2026-11-15 from `job-search-5.plan.md` (27 tasks) into three plans, so each relay is short and ends with a release. This file builds: Parts 3 and 4 (SRCH-1..6, CHK-1..3). Press Release when it finishes.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task. Each part keeps its own intro and rules. Read the intro of the part a task is in before starting it.

There is no publish task (removed 2026-11-11). When the relay finishes, press **Release**: it sets the version, writes the notes, runs the checks and the security scan, pushes, waits for CI, tags and publishes. This repository's relay has no `release` profile, so a publish task would only bump the version.
Its release notes must mention the one-time move of job files into "My job search" and its backup folder. Check them in the Release window before confirming.

What the user gets, end to end:
1. **Jobs opens on a list of saved searches**, such as "Anish Job search" and "Anish_Data_job". You can create, open, edit, duplicate, rename or delete a search. Each search has its own CV, Word template, preferences, companies, schedule and delivery.
2. **Opening a search shows five steps** with a ✓ or ✗ on each: CV → Preferences → Companies → Schedule and delivery → Check. **Check** lists everything that is ready or wrong, each with a fix button. Examples are 27 companies with no job board, an agent that isn't accepted, or Telegram not connected. Then **Close**.
3. **In Agents**, each saved search is its own agent with the search's name. You pick "Anish Job search" and run or schedule it.
4. **After a run**, **Results** shows every job with its score, company, role, location, why it matched, an **Apply** link and **Tailor CV**. A finished tailored CV has **Save to Downloads**, **Open** and **Email it to me**.
5. **Each run tailors the top 3 jobs** that score 80 or more, in your own Word template. It attaches them, with an Excel shortlist if you want one, to the email and the Telegram message. In Telegram, `/cv 5` tailors job 5 from the last message and sends the Word file back.
6. **An apply pack per job**: tailored CV, cover letter, and ready answers to the usual form questions to copy in. whyline never submits an application. Assisted form filling is designed in ASF-1 and built in a later plan.

Rules every task keeps, on top of each part's own rules:
- Console first. Every CLI command or setting gets its console counterpart in the same task, saving through the same function.
- Everything under `~/.whyline/jobs/` is private user data: files mode 0600, folders mode 0700. Writes go to a temporary file and then `os.replace`.
- No new dependency in Parts 1 to 6. No whyline-relay change.
- Tests never use the real home folder, a real provider, the network or a real browser. They never sleep and never contain "/Users/".
- Each task ends with `uv run pytest -q` passing.

## Part 3: Saved searches

A saved search is a named set of everything one job hunt needs:
- CV and Word template
- profile and rubric
- preferences
- companies
- applications
- its own agent, schedule and delivery

Data layout after this part:
- `~/.whyline/jobs/searches.toml`: the index. One table per search, with `name`, `slug`, `created` and `agent`, plus `current = "<slug>"`.
- `~/.whyline/jobs/searches/<slug>/`: `cv.md`, `cv-template.docx`, `cv-template.json`, `profile.md`, `rubric.md`, `preferences.toml`, `companies.toml` and `applications/`.
- Shared across searches, left in `~/.whyline/jobs/`:
  - the job tracker (`jobs.sqlite`, `jobs.xlsx`)
  - the seen-postings database
  - alert settings and the alert inbox
  - `answers.toml` (Part 6)

Rules for this part:
- A name is 1 to 60 printable characters and unique, ignoring case. The slug is the lower-case name with every run of other characters replaced by `-`, cut to 40 characters, with `-2`, `-3` and so on added when it clashes. The slug never changes after creation, so a rename keeps the folder and the agent.
- With no `--search` and no console choice, every function works on the current search. Existing callers keep working without changes.
- The first search is created by migrating today's files. Nothing is deleted. Each existing file is moved, and the whole folder is first copied to `~/.whyline/jobs-backup-<YYYYMMDD-HHMMSS>/`.

- [ ] SRCH-1: The saved-search store and the one-time migration
  Add `src/whyline/jobs/searches.py`. Edit `src/whyline/jobs/paths.py` and tests only.
  1. `Search(name, slug, created, agent)` and the following functions:
     - `list()`, `get(name_or_slug)`, `current()`, `use(name_or_slug)`
     - `create(name, *, copy_from=None)`, `rename(name_or_slug, new_name)`, `delete(name_or_slug)`
     - `validate_name`
  2. `paths.search_home(slug=None) -> Path` returns `searches/<slug>/` for the given or current search. It creates the folder with mode 0700 and refuses symlinks, like `_private_dir`.
  3. `migrate()` runs on the first call to any of these functions:
     - When `searches.toml` is missing and any per-search file exists at the top level, copy the folder to the backup, then create the search "My job search" (slug `my-job-search`, agent `job-search`).
     - Move each per-search file and `applications/` into it, and set it as current.
     - When nothing exists yet, create the same search empty.
     - Protect it with a lock file so two processes never migrate together.
     - If any move fails, move the files already moved back, and raise `SearchError` naming the file.
  4. `create(copy_from=...)` copies the CV, template, profile, rubric, preferences and companies, but not applications. `create` without it starts empty.
  5. The agent for a new search is `job-search-<slug>`.
  6. `delete` refuses the last remaining search, and refuses the current one until another is chosen. It moves the folder to `~/.whyline/jobs/deleted/<slug>-<time>/` instead of removing it. It doesn't delete the agent; it returns the agent name so the caller can offer that.
  Tests:
  - migration with files, with no files, and with a failure halfway (everything restored)
  - the lock
  - the slug rules, including clashes and rename keeping the slug
  - copy vs empty create
  - each delete refusal
  Verify with `uv run pytest -q tests/jobs`. Change nothing else.

- [ ] SRCH-2: Profile, companies, review and apply read and write the chosen search
  Edit `src/whyline/jobs/profile.py`, `companies.py`, `review.py`, `apply.py`, `doctor.py`, `word_cv.py` (if CVT created it) and their tests only.
  1. Every function that today uses `paths.home()` for a per-search file uses `paths.search_home(search)` instead. Add a keyword-only `search: str | None = None` to the public functions that need it. Leave shared files on `paths.home()`.
  2. `doctor.check(search=None)` checks that search's files and companies, and that search's agent (`Search.agent`) instead of the fixed `AGENT_NAME`.
  3. No behaviour change for callers that pass nothing.
  Tests: two searches side by side, with different CVs, companies and drafts, never see each other's files, and the existing tests still pass unchanged. Change nothing else.

- [ ] SRCH-3: Tracker, seen postings and alerts know which search a job belongs to
  Edit `src/whyline/jobs/tracker.py`, `seen.py`, `alerts.py`, `step.py`, `src/whyline/agents/after.py` and their tests only.
  1. Add a `search TEXT NOT NULL DEFAULT 'my-job-search'` column to the tracked table and to the seen table, with a migration for existing databases. Add `run_id TEXT NOT NULL DEFAULT ''` and `rank INTEGER` to the tracked table. `rank` is the job's position in that run's shortlist, starting at 1.
  2. The key for "already seen" becomes `(search, uid)`, so two searches can both get the same posting once.
  3. `list_rows(search=None, run_id=None)` filters on either. `export_xlsx(search=None)` adds a Search column when exporting every search.
  4. The alert inbox is read once by each search: record per search which alert files it has already taken, and remove a file only when every search has taken it.
  5. `step.jobs_fetch` and `_jobs_track` take the search from the agent definition (SRCH-4) and pass it down. `record_run` stores `run_id` and `rank`.
  Tests:
  - the database migrations keep existing rows
  - per-search seen
  - the run_id and rank filters
  - alerts shared by two searches
  - an old database keeps working
  Change nothing else.

- [ ] SRCH-4: One agent per search
  Edit `src/whyline/agents/definitions.py`, `templates.py`, `src/whyline/jobs/searches.py`, `src/whyline/agents/before.py` (only if needed) and their tests only.
  1. Add an optional `search = "<slug>"` key to the agent definition, written and read like the other keys. A definition with `before = "jobs-fetch"` and no `search` means the current search, which is today's behaviour.
  2. Resolve the agent's `sources` (`cv.md`, `profile.md`, `rubric.md`, `preferences.toml`) against `paths.search_home(defn.search)` for these agents. Follow how `resolve_sources` treats the jobs folder today, and keep its containment check.
  3. Add `searches.ensure_agent(name_or_slug, *, schedule=None)`. It creates the search's agent from the `job-search` template when it's missing, with name `Search.agent`, title the search name, and `search = <slug>`. It returns the definition. It never accepts the agent; the user still reviews and accepts it, as today.
  4. When a search is renamed, update its agent's title. When the agent is missing, rename only the search.
  5. Creating an agent from the Daily job shortlist template in Agents asks which saved search it is for, with a choice of the existing searches plus "New search…". It then calls `ensure_agent`.
  Tests:
  - an agent for each of two searches reads its own sources
  - a missing `search` key means current
  - `ensure_agent` is idempotent
  - rename updates the title
  - the template flow asks for a search
  Change nothing else.

- [ ] SRCH-5: CLI for saved searches
  Edit `src/whyline/jobs/cli.py` and its tests only.
  1. Add `whyline jobs searches list|new NAME [--copy-from NAME]|rename NAME NEW|delete NAME|use NAME|agent NAME`. `agent` runs `ensure_agent`.
  2. Add a `--search NAME` option on the `whyline jobs` group, passed to every subcommand.
  3. `list` marks the current search and shows the agent name and whether it is accepted.
  4. Errors from `SearchError` print plainly and exit 1.
  Tests: each subcommand, `--search` on two existing commands, and an unknown search name. Change nothing else.

- [ ] SRCH-6: Console: the saved-search list
  Edit `src/whyline/console/jobs_screens.py`, `src/whyline/console/tui.py` (only where Jobs is opened) and their tests only.
  1. Add `JobSearchesScreen`, which opens from Jobs instead of `JobsHomeScreen`. It shows a table of searches with columns Name, Agent (accepted / not accepted / missing), Schedule, Last run and New jobs in the last run.
  2. Buttons:
     - **New search…**: asks for a name and "Start from: empty / copy of <search>".
     - **Open**: opens `JobsHomeScreen` for that search and makes it current.
     - **Duplicate…**, **Rename…** and **Delete…**. Delete confirms and names the deleted folder. When the search has an agent, it offers to delete that too, through the existing agent delete.
     - **Close**.
  3. `JobsHomeScreen` takes the search and shows its name in the title, for example `Jobs · Anish Job search`. Every call it makes passes that search.
  4. With exactly one search, Jobs still opens the list, so the user learns where searches live.
  Tests: each button calls the same `searches` function as the CLI, the title, and the home screen passing the search through. Change nothing else.

## Part 4: Setup steps and a Check page

Uses `doctor.check(search=...)` from SRCH-2 and adds what it doesn't cover.

- [ ] CHK-1: A step bar on the search page
  Edit `src/whyline/console/jobs_screens.py` and its tests only.
  1. At the top of `JobsHomeScreen`, add a row of five step buttons: `1 CV`, `2 Preferences`, `3 Companies`, `4 Schedule and delivery`, `5 Check`. Each shows ✓ when done and ✗ when not:
     - CV: CV present, and profile and rubric accepted.
     - Preferences: saved.
     - Companies: at least one accepted company with a board.
     - Schedule and delivery: agent accepted, and a schedule or a delivery set.
  2. Pressing a step scrolls to and focuses that section. **Check** opens CHK-2.
  3. **Schedule and delivery** shows the search's agent schedule and delivery. A **Set up agent…** button calls `searches.ensure_agent`, then opens the existing agent schedule and delivery screens for that agent.
  Tests: the done state of each step from stubbed statuses, and that the agent button calls `ensure_agent` with this search. Change nothing else.

- [ ] CHK-2: The Check page with a fix button per problem, and Close
  Edit `src/whyline/jobs/doctor.py`, `src/whyline/console/jobs_screens.py` and their tests only.
  1. Extend `doctor.check(search=...)` with these rows:
     - **Word template**: present, missing, or stale (CVT-1).
     - **Companies not checked**: the count of accepted companies with empty `checked_at`.
     - **Companies with no board**: the count, and up to 10 names.
     - **Alerts**: the alert senders that are on, and when the last alert arrived.
     - **Delivery**: email and Telegram targets, and whether the last test send worked.
     - **Last run**: when it ran, how many new jobs, and why there were 0 when there were (CHK-3).
     Each row has a `fix_action` key as well as its fix text.
  2. Add `JobsCheckScreen`. It shows the rows with ✓, ! or ✗, the detail, and a button per row with a problem:
     - **Import CV**, **Review my CV**, **Check boards**, **Add board link…**
     - **Set up agent…**, **Accept agent**, **Send test**, **Fetch now**
     Each calls the same function as its counterpart on the search page.
  3. Below the rows, a summary: `Ready: the next run is Mon 07:30.` or `3 things to fix before the first run.`
  4. Buttons **Check again** and **Close**.
  5. `whyline jobs doctor --search NAME` prints the same rows.
  Tests:
  - each new row with ok, warn and fail stubs
  - the fix button calls the right function
  - the summary for ready and not ready
  - the CLI prints the same rows
  Change nothing else.

- [ ] CHK-3: A run with no new jobs says why
  Edit `src/whyline/jobs/step.py`, `src/whyline/agents/deliver.py` (only the body text for job-search runs) and their tests only.
  1. When `jobs_fetch` finds 0 new postings, write a `why-empty.md` into the run folder with the counts:
     - companies fetched
     - companies skipped with no board
     - postings found
     - postings filtered by preferences
     - postings already seen
     - alerts read
     Also give the most likely reason in one sentence, for example `27 of 39 companies have no job board; press Check boards or add their links.`
  2. A skipped run's delivery, when a delivery is set, sends that sentence instead of nothing. Follow how `skip_when_empty` ends the run, and keep the run marked as skipped.
  3. The Check page's **Last run** row shows that sentence.
  Tests: the sentence for no boards, everything filtered, everything already seen and no companies, plus the delivery body. Change nothing else.

