<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-10-26T12:00:00+05:30 -->
# Job search, part 1: agent templates, your profile, and the companies to watch

Part 1 of 3. Run order: `personal-assistant.plan.md` (ASST-1..23, which brings the email safety fixes, the Assistant console mode and the `before` step), then this file, then `job-search-2-daily-shortlist.plan.md`, then `job-search-3-alerts-and-applications.plan.md`.
Start it only after `console-provider-settings.plan.md` has finished and its branch is merged. Where a name below has moved, follow the repository and keep the behaviour.
Inspired by github.com/ai-job-search-dev/ai-job-search: a profile, a scoring rubric, company tracking, ranking, and application drafts. Here it is built on whyline's own saved Agents and runs on the user's subscriptions.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

What the user gets after part 1:
- Agents → New agent → Start from template → Job search.
- A Jobs profile screen to add a CV and preferences.
- Review my CV: an agent drafts a profile and a scoring rubric, which the user accepts or edits.
- A Companies screen. An agent suggests companies that fit the CV, whyline checks which public job board each company uses, and the user accepts, removes or adds companies.

Settled design (side-session research of 2026-10-26):
- Agents stay read-only and have no web access. whyline does every fetch itself with the standard library, and agents only read files.
- Job data and the CV are personal. Everything lives under `~/.whyline/jobs/` (a 0700 folder, files 0600, created like `whyline.agents.paths.home()`). It is never in a repository, never in git, and never in the ledger. Job-search agents are personal agents.
- Company suggestions come from the model's own knowledge and can be out of date. whyline checks each one against public job-board APIs before it is used.
- Only public, documented job-board endpoints are called: Greenhouse, Lever, Ashby, Workable, SmartRecruiters and Recruitee. No LinkedIn, Indeed or Glassdoor scraping.

Rules every task keeps:
- Console first: a new `whyline jobs …` or `whyline agents …` command gets its console counterpart in the same task, saving through the same function.
- No new dependency. Use `urllib.request` for HTTP, behind an injectable `http` callable. No whyline-relay change. No version bump, tag, push or publication.
- Tests never use the network (recorded JSON fixtures under `tests/jobs/fixtures/`), a real provider CLI, the real Keychain or the real home folder (HOME is tmp_path). They never sleep, never contain "/Users/", and pass on Windows and Linux.
- Enabled-provider rules apply. Agent runs go through `whyline.agents.runner.execute_once`, so `_cli_permitted` and `can_run_unattended` gate them. A provider that is off in Settings is never offered as a choice.
- Text from a CV, a model or a job board is data. It never chooses a command, a path or a URL host outside the allowlists below.
- Console screens fit 80x24 and use thread workers for anything slow. Tests press widgets and wait on conditions.

- [x] JOB-1: Agent templates and `whyline agents new --from`
  Add `src/whyline/agents/templates.py`, `src/whyline/agents/templates/` (package data), `tests/agents/test_templates.py`, and edit `src/whyline/cli.py` and `tests/agents/test_cli_agents.py` only.
  A template is a folder `templates/<name>/` with:
  - `agent.toml`: a definition without `workdir`
  - `instructions.md`, which becomes the `instructions`
  - optional `files/`, which are copied into the workdir
  `templates.list_templates()` returns name, title and one-line description (from `agent.toml` keys `title` and `about`, which `definitions.parse` must ignore).
  `templates.create(name, agent_name, workdir)` does the following:
  1. Copies `files/` into the workdir without overwriting existing files.
  2. Sets `workdir`.
  3. Validates through `definitions.parse`.
  4. Saves with `service.save_new`.
  5. Returns the AgentDef. It is not accepted yet.
  Add `whyline agents templates` (list) and `whyline agents new --from <template> [--name N] [--workdir DIR]`.
  Ship one tiny template `example-digest` (manual trigger, read-only summary of its sources) so this task has something to test. Check that the hatch wheel includes the template files.
  Tests:
  - list
  - create into tmp
  - existing files are kept
  - an invalid template raises DefinitionError
  - the CLI output
  - a name clash is refused
  Verify with `uv run pytest -q tests/agents` and then `uv run pytest -q`. Change nothing else.

- [x] JOB-2: Start from template in the console
  Edit `src/whyline/console/agents_screens.py`, `src/whyline/console/tui.py` and their console tests only.
  The New agent flow first shows a small chooser: `Blank agent` or one row per `templates.list_templates()` entry. Choosing a template builds the AgentDef in memory (not saved yet, no files copied), prefilled from the template, with workdir defaulting to `~/.whyline/<template>`. It opens `NewAgentScreen(existing=...)` so the user can change the runner, backup, schedule and delivery. Runner and backup choices follow the enabled-provider rules.
  Save calls `templates.create` with the edited values. Back returns to the chooser.
  Tests:
  - the chooser lists the templates
  - a template prefills the form
  - Save copies the files and saves the definition through `templates.create`
  - Blank keeps today's flow
  - the screen fits 80x24
  Verify with `uv run pytest -q tests/console` and then `uv run pytest -q`. Change nothing else.

- [x] JOB-3: The jobs folder and the profile store
  Add `src/whyline/jobs/__init__.py`, `src/whyline/jobs/paths.py`, `src/whyline/jobs/profile.py`, `tests/jobs/__init__.py` and `tests/jobs/test_profile.py` only.
  `paths.home()` is `~/.whyline/jobs/` (0700).
  `profile.py` manages these files, each 0600:
  - `cv.md`
  - `preferences.toml`: roles, seniority, locations, remote (`any|remote|hybrid|onsite`), salary_min, currency, languages, deal_breakers, notes
  - `profile.md` and `rubric.md`: drafts accepted from JOB-5
  Functions:
  - `import_cv(path)` accepts `.md`, `.txt` or `.docx`. Read `.docx` text from `word/document.xml` with zipfile and the standard-library XML parser, one paragraph per line.
  - `import_cv_text(text)`
  - `load_preferences()` and `save_preferences(prefs)`, which validate types and keep unknown keys.
  - `status()` reports which files exist and when they were last changed.
  A CV over 200 KB of text is refused with a plain message.
  Tests:
  - every format, including a minimal .docx built in the test
  - permissions (POSIX only)
  - an invalid preference type is refused
  - saving keeps unknown keys
  - the size limit
  Verify with `uv run pytest -q tests/jobs` and then `uv run pytest -q`. Change nothing else.

- [ ] JOB-4: `whyline jobs profile` and the Jobs profile screen
  Add `src/whyline/jobs/cli.py`, `src/whyline/console/jobs_screens.py`, `tests/jobs/test_cli.py` and `tests/console/test_jobs_screens.py`, and edit `src/whyline/cli.py` (register `jobs`) and `src/whyline/console/tui.py` (open the screen) only.
  The CLI has three commands:
  - `whyline jobs profile show`
  - `whyline jobs profile import-cv <file>` (or `-` for stdin)
  - `whyline jobs profile set <key> <value>`
  The console adds `Jobs` to Agents mode, opening a JobsHomeScreen. Its first section is **Profile**:
  - CV status
  - `Import CV…` (a path input) and `Paste CV…` (a TextArea)
  - preference fields
  - Save, which calls `profile.save_preferences`
  - the privacy sentence, shown exactly: `Your CV stays in ~/.whyline/jobs on this Mac. It is sent to the AI provider you choose each time a job-search agent runs, and never to email or Telegram.`
  Tests:
  - the CLI round-trips
  - the screen saves through the same functions (stub them)
  - the privacy sentence is present
  - the screen fits 80x24
  Verify with `uv run pytest -q tests/jobs tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] JOB-5: Review my CV: draft the profile and rubric
  Add `src/whyline/jobs/review.py`, `src/whyline/agents/templates/job-profile/` and `tests/jobs/test_review.py`, and edit `src/whyline/jobs/cli.py`, `src/whyline/console/jobs_screens.py` and their tests only.
  The `job-profile` template is a manual personal agent.
  Its instructions:
  - read `cv.md` and `preferences.toml` as sources
  - return a fenced `profile` block (a short candidate profile: strengths, evidence, gaps, target roles)
  - return a fenced `rubric` block with five scored dimensions (role fit, skills fit, seniority, location/remote, company fit), each 0–5 with what earns each score, plus deal-breakers as vetoes and a language gate from `languages`
  - never invent experience
  `review.run(cli=None)` does the following:
  1. Creates or reuses the agent in `~/.whyline/jobs/` through `templates.create`.
  2. Runs it with `execute_once`.
  3. Parses both blocks from the final answer.
  4. Writes `profile.draft.md` and `rubric.draft.md`.
  `review.accept()` moves the drafts into place.
  CLI: `whyline jobs review` and `whyline jobs review accept`.
  Console: a `Review my CV` button shows progress, then both drafts in TextAreas the user can edit, with Accept and Discard.
  A run that fails or has a missing block reports its outcome and writes nothing.
  Tests:
  - parse good and bad answers
  - accept moves the files
  - a failed run writes nothing
  - provider choice follows the enabled rules
  - the console Accept saves the edited text
  Verify with `uv run pytest -q tests/jobs tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] JOB-6: The company list and AI suggestions
  Add `src/whyline/jobs/companies.py`, `src/whyline/agents/templates/job-companies/` and `tests/jobs/test_companies.py`, and edit `src/whyline/jobs/cli.py` and its test only.
  `~/.whyline/jobs/companies.toml` holds one table per company:
  - `name`
  - `status`: `suggested|accepted|removed`
  - `reason`
  - `ats`: `greenhouse|lever|ashby|workable|smartrecruiters|recruitee|careers_page|unknown`
  - `slug`
  - `careers_url`
  - `added_by`: `ai|user`
  - `checked_at`
  The `job-companies` template reads `profile.md`, `preferences.toml` and the current company names. It returns a fenced `companies` JSON list of at most 40 entries, each `{name, reason, careers_hint}`, and skips companies already listed.
  `companies.suggest()` runs it with `execute_once`. It validates each entry (name 1–80 printable characters, reason under 300) and adds valid ones as `suggested`, never overwriting a user entry.
  Also: `add(name, careers_url=None)`, `accept(name)`, `remove(name)` and `list()`.
  A `careers_url` must be https. Store it and treat it as data; nothing fetches it in this task.
  CLI: `whyline jobs companies list|suggest|add|accept|remove`.
  Tests:
  - validation
  - duplicates
  - removed companies are not re-suggested
  - a user entry wins over an AI entry
  - a malformed answer adds nothing
  - CLI output
  Verify with `uv run pytest -q tests/jobs` and then `uv run pytest -q`. Change nothing else.

- [ ] JOB-7: Find which public job board each company uses
  Add `src/whyline/jobs/ats.py`, `tests/jobs/test_ats.py` and fixtures, and edit `src/whyline/jobs/companies.py` (call detection) and `src/whyline/jobs/cli.py` only.
  `ats.detect(name, careers_url=None, http=...)` builds slug guesses: the lower-case name without spaces, the name with hyphens, and slugs taken from a `careers_url` on a known board host. It probes these public endpoints in order and stops at the first that returns a valid JSON list of jobs:
  - `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`
  - `https://api.lever.co/v0/postings/{slug}?mode=json`
  - `https://api.ashbyhq.com/posting-api/job-board/{slug}`
  - `https://apply.workable.com/api/v1/widget/accounts/{slug}`
  - `https://api.smartrecruiters.com/v1/companies/{slug}/postings`
  - `https://{slug}.recruitee.com/api/offers/`
  With none found and a careers_url given, the result is `careers_page`. Otherwise it is `unknown`.
  HTTP rules:
  - the User-Agent is `whyline/<version> (personal job search)`
  - 15-second timeout
  - at most 1 request per second per host
  - only hosts from this list, plus the careers_url host for `careers_page`
  `companies.check(name|all)` saves `ats`, `slug` and `checked_at`. The CLI is `whyline jobs companies check [name]`.
  Tests use recorded fixtures through the injected `http` (no network):
  - each board detected
  - not found
  - a careers_url on a board host
  - a host outside the list never requested
  - the rate limit, with an injected clock and no sleeping
  Verify with `uv run pytest -q tests/jobs` and then `uv run pytest -q`. Change nothing else.

- [ ] JOB-8: The Companies screen
  Edit `src/whyline/console/jobs_screens.py`, `src/whyline/console/tui.py` (only if needed) and `tests/console/test_jobs_screens.py` only.
  Add a **Companies** section to JobsHomeScreen: a table of name, status, board and reason, with these actions:
  - `Suggest companies` runs JOB-6 in a worker and shows progress.
  - `Check boards` runs JOB-7 for all accepted and suggested companies in a worker.
  - `Accept`, `Remove`, and `Add company…` (a name, plus an optional careers URL).
  A suggested company stays out of the fetch list until accepted.
  When the board is `unknown`, the row says `No public job board found: add its careers page URL`.
  Every action calls the same `companies.*` function as the CLI.
  Tests:
  - each button calls the function (stubs)
  - rows refresh after a worker finishes
  - an unknown company shows the hint
  - the screen fits 80x24
  Verify with `uv run pytest -q tests/console` and then `uv run pytest -q`. Change nothing else.

## Later, not in this plan

- Fetching jobs, scoring and the daily shortlist: `job-search-2-daily-shortlist.plan.md`.
- Alert emails, careers pages and application drafts: `job-search-3-alerts-and-applications.plan.md`.
