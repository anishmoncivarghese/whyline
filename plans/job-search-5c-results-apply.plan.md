<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-01T12:00:00+05:30 -->
# Job search, part 5: saved searches, a setup check, run results with tailored CVs, and an apply pack — c: run results, the apply pack and docs

Runs after `plans/job-search-5b-saved-searches.plan.md`, and before `plans/self-improvement-1-checks.plan.md`. Split on 2026-11-15 from `job-search-5.plan.md` (27 tasks) into three plans, so each relay is short and ends with a release. This file builds: Parts 5 to 8 (JRUN-1..5, PACK-1..2, ASF-1, JSD-1). Press Release when it finishes.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task. Each part keeps its own intro and rules. Read the intro of the part a task is in before starting it.

There is no publish task (removed 2026-11-11). When the relay finishes, press **Release**: it sets the version, writes the notes, runs the checks and the security scan, pushes, waits for CI, tags and publishes. This repository's relay has no `release` profile, so a publish task would only bump the version.

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

## Part 5: Run results and tailored CVs

Builds on CVT (Part 2), the tracker's `run_id` and `rank` (SRCH-3), and `apply.draft` / `apply.build_cv`.

Rules for this part:
- Tailoring runs an AI. It's never started without a reason the user set up or a click.
- Auto-tailoring never delays the run's delivery by more than its time budget.
- A job's number in Results, in the email and in the Telegram message is the same `rank`.

- [ ] JRUN-1: The Results screen for a run
  Edit `src/whyline/console/jobs_screens.py`, `src/whyline/console/agents_screens.py` (only to add the entry point) and their tests only.
  1. Add `JobRunResultsScreen(search, run_id)`. It shows the run's tracked rows ordered by rank, with columns #, Score, Company, Role, Location, Posted, Status, CV and Why. CV is ✓ when a tailored `.docx` exists for that job.
  2. A **Run** select at the top lists that search's runs, newest first, labelled like `Today 07:30 · 14 jobs`. It defaults to the newest run.
  3. Buttons for the highlighted job:
     - **Apply**: opens the link, same path as `_open_job_link`.
     - **Tailor CV**
     - **Open CV**
     - **Save to Downloads**
     - **Email it to me**
     - **Status…**: the tracker statuses, same function as `TrackedJobsScreen`.
     - **Apply pack**: Part 6. Disabled until PACK-2.
  4. The detail area under the table shows the full reason, plus `missing:` items when the agent gave them.
  5. Entry points:
     - **Results** on the search page
     - **Results** on a job-search agent's row in Agents
     - **Show results** after **Fetch now** or a run finishes in the console
  Tests:
  - rows by rank
  - the run select
  - button enabled states with and without a CV
  - Apply opens the link
  - Status saves through the tracker
  - each entry point opens the screen with the right search and run
  Change nothing else.

- [ ] JRUN-2: Tailor, save and email one job's CV
  Edit `src/whyline/jobs/apply.py`, `src/whyline/agents/deliver.py` (a small `send_files` helper only), `src/whyline/console/jobs_screens.py`, `src/whyline/jobs/cli.py` and their tests only.
  1. **Tailor CV** runs `apply.draft` for the job in a thread worker. It shows progress and can be stopped like **Draft application**. When it finishes, the row's CV becomes ✓ and the status line says `Tailored CV ready: <file name> (N changes, M refused).`
     Without a Word template, the status line says `No Word template. Import your CV as .docx first.` and offers **Import CV**.
  2. **Save to Downloads** copies the `.docx` to `~/Downloads/<file name>`, adding ` (2)` and so on rather than overwriting. It then shows the path and a **Show in Finder** button.
  3. **Email it to me** sends the `.docx` and `cv-changes.md` to the search's delivery email through `deliver.send_files(delivery, subject, body, files)`. The subject is `Tailored CV: <Role> at <Company>`. With no email set, it says `Set an email in Schedule and delivery first.`
  4. CLI:
     - `whyline jobs cv-save <ref> [--to DIR]`
     - `whyline jobs cv-email <ref>`
     Both call the same functions.
  Tests:
  - tailor success, failure and stop
  - no template
  - Downloads name clash
  - email with and without an address, using a stub mailer
  - the CLI
  Change nothing else.

- [ ] JRUN-3: Auto-tailor the top jobs after each run
  Edit `src/whyline/jobs/searches.py` (settings only), `src/whyline/agents/after.py`, `src/whyline/jobs/apply.py` and their tests only.
  1. Per-search settings in `searches.toml`, all validated:
     - `auto_tailor` (0 to 5, default 3)
     - `auto_tailor_min_score` (0 to 100, default 80)
     - `auto_tailor_minutes` (5 to 60, default 15)
  2. After `_jobs_track` records a succeeded run, tailor the highest-ranked jobs whose score meets the minimum, up to `auto_tailor`. Run them one at a time, and stop starting new ones once the time budget is used. Skip jobs that already have a tailored CV, and searches without a Word template.
  3. Write `tailored.json` in the run folder listing each job's rank, file and note, plus the skipped ones with why.
  4. A tailoring failure never fails the run.
  5. This happens before delivery, because `_post_run` runs before `deliver.after_run`; keep that order.
  6. The console search page shows these settings under Schedule and delivery, saved through the same function as `whyline jobs searches set NAME --auto-tailor N --min-score N --minutes N`. Add that CLI here.
  Tests:
  - the top N by score
  - min score
  - an existing CV skipped
  - the budget stops further jobs
  - no template
  - a failure keeps the run succeeded
  - `tailored.json`
  - the settings in both console and CLI
  Change nothing else.

- [ ] JRUN-4: Deliver the shortlist with numbers, tailored CVs and an optional Excel file
  Edit `src/whyline/agents/deliveries.py`, `src/whyline/agents/deliver.py`, `src/whyline/agents/telegram.py`, `src/whyline/jobs/tracker.py`, the delivery editor in `src/whyline/console/agents_screens.py` and their tests only.
  1. Two new delivery settings for job-search agents:
     - `attach_cvs` (default true): attach the run's tailored CVs.
     - `attach_excel` (default false): attach `shortlist-<date>.xlsx` of this run's rows, built with `tracker.export_xlsx`, filtered to the run.
     Both are validated and shown in the console delivery editor, for job-search agents only.
  2. Email sends all attachments in one message. Telegram sends the shortlist text first, then one document per file.
  3. Every job line in the email and Telegram body starts with its rank, for example `5. 86 · Data Engineer · Acme · Apply: <link>`. A job with a tailored CV ends with `· CV attached`.
  4. The Telegram body ends with `Reply /cv <number> for a tailored CV of any job.`
  5. When the total attachment size would pass 20 MB, attach the shortlist only, and say so in the body.
  Tests:
  - attachment lists for each setting
  - the size cap
  - numbered lines
  - Telegram sending several documents
  - an old deliveries file without the new keys
  Change nothing else.

- [ ] JRUN-5: Telegram `/cv N`
  Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/jobs/apply.py` (a lookup helper only) and their tests only.
  1. Add a `cv` command: `/cv 5`, or `/cv <search name> 5`.
     - Without a search name, it uses the job-search run most recently delivered to this chat.
     - It finds the job by rank in that run.
  2. Queue the work the way `/run` queues a run request, so the bot loop never blocks. Reply at once with `Tailoring CV for Data Engineer at Acme… (about 2 minutes)`.
  3. When it's done, send the `.docx` and `cv-changes.md` to that chat. An existing tailored CV is sent at once without running again. On failure, send the reason in one line.
  4. Only chats already allowed by the bot can use it. A number that isn't in the run replies `No job 5 in the last shortlist (1-14).`
  5. Add `cv` to the help text.
  Tests, with a stub `apply.draft` and a stub Telegram:
  - parsing, with and without a search name
  - an unknown number
  - a reused CV
  - queued vs immediate
  - a disallowed chat
  Change nothing else.

## Part 6: Apply pack

whyline never submits applications. The apply pack puts everything for one application in one place, ready to copy.

- [ ] PACK-1: Saved answers to the usual application questions
  Add `src/whyline/jobs/answers.py`. Edit `src/whyline/jobs/cli.py`, `src/whyline/console/jobs_screens.py` and tests only.
  1. `~/.whyline/jobs/answers.toml` is shared across searches. It holds:
     - full name, email, phone, city, country
     - LinkedIn, GitHub, portfolio
     - notice period
     - current and expected salary, as free text
     - work authorisation and visa sponsorship needed (yes/no)
     - willing to relocate, years of experience, highest education
     - an extra `[[custom]]` list of question and answer pairs
     Every field is optional and validated for length, and the file is mode 0600.
  2. Console: **Answers…** on the search list and on the search page, an editable form saved through `answers.save`.
  3. CLI: `whyline jobs answers show|set KEY VALUE|unset KEY`.
  4. Never send these anywhere except into the apply pack file.
  Tests: round trip, validation, custom pairs, the file mode, and console and CLI saving the same way. Change nothing else.

- [ ] PACK-2: The apply pack for a job
  Edit `src/whyline/jobs/apply.py`, `src/whyline/console/jobs_screens.py`, `src/whyline/jobs/cli.py` and their tests only.
  1. Add `apply.build_pack(ref) -> Path`. It writes `apply-pack.md` in the job's application folder with:
     - the job title, company and Apply link
     - the tailored CV file name (or `none yet`)
     - the cover letter from `final.md` or `draft.md` when present
     - every saved answer as `Question: answer` lines
     - the job description's own screening questions when the posting text has a "questions" section, listed with the saved answer that matches by keyword, or `(answer this one yourself)`
  2. **Apply pack** in Results (JRUN-1) builds the pack, opens it, and opens the Apply link. It also offers **Tailor CV first** when there is no tailored CV.
  3. Set the job's tracker status to `shortlisted` when the pack is first built. Setting `applied` stays a deliberate choice in **Status…**.
  4. CLI: `whyline jobs pack <ref>` prints the path.
  Tests:
  - the pack with and without a CV, cover letter and answers
  - keyword matching
  - status set once
  - CLI and console calling the same function
  Change nothing else.

## Part 7: Assisted form filling, design only

The user wants whyline to help fill application forms in the browser. This part only designs it. The build is a separate plan written from the approved design.

- [ ] ASF-1: Design assisted form filling, and draft its plan
  Write `docs/superpowers/specs/<today>-assisted-apply-design.md` and `plans/assisted-apply.plan.md` only. Change no code.
  1. Compare at least three ways, with what each needs installed, how it reaches a logged-in browser, and how fragile it is:
     - (a) Playwright, or another browser driver, attached to the user's own Chrome profile
     - (b) a small Chrome extension that reads the apply pack from a local whyline endpoint
     - (c) a bookmarklet or userscript filled from the apply pack
     Cover Workday, Greenhouse, Lever, Ashby, LinkedIn Easy Apply and Naukri.
  2. Recommend one.
  3. Hard rules the design must keep:
     - It never presses Submit, Apply or Next on the last page.
     - It never solves a CAPTCHA.
     - It never types a password or creates an account; the user logs in themselves.
     - It fills only fields it matches with confidence, and highlights each filled field.
     - It uploads the tailored CV only when the user confirms the file.
     - It stops at the first page it doesn't recognise.
     - It respects each site's terms; say which sites forbid automation, and leave those to copy and paste from the apply pack.
  4. The draft plan follows this file's format, with small tasks, and starts with a manual test checklist for each site.
  5. The plan is not run until the user approves the design.
  Verify that `uv run pytest -q` still passes. Change nothing else.

## Part 8: Docs and release

- [ ] JSD-1: Docs for saved searches, Check, Results, auto-tailoring, `/cv` and the apply pack
  Edit `docs/job-search.md` and `README.md` (the Jobs section only).
  - Walk a new user through the whole flow:
    1. New search
    2. Import CV as `.docx`
    3. Review my CV
    4. Preferences
    5. Suggest companies, accept, Check boards
    6. Set up agent, schedule and delivery
    7. Check
    8. First run
    9. Results
    10. Tailor CV
    11. Apply pack
  - Explain:
    - what is per search and what is shared
    - auto-tailor settings and their AI cost
    - the numbered shortlist and `/cv N`
    - that Excel is optional
    - that whyline never submits applications
  - Keep the CVT docs from CVT-7.
  Verify with `uv run pytest -q`. Change nothing else.

## Later, not in this plan

- Save the tailored CV as PDF directly. Use LibreOffice (`soffice --headless --convert-to pdf`) when it's installed, or Word through AppleScript, and add the PDF only when the conversion is exact.
- Tailored cover letter in a Word letter template the user imports.
- Editing paragraphs inside text boxes. It needs both the `mc:Choice` and `mc:Fallback` copies changed together, and tests against Word, Pages and Google Docs.
- Assisted form filling: build it from `plans/assisted-apply.plan.md` once ASF-1's design is approved.
- Tap-to-tailor buttons in Telegram, instead of typing `/cv N`.
- Expired-posting check before delivery: re-fetch each link and drop jobs that are closed.
