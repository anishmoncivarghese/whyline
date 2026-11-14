<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-15T18:00:00+05:30 -->
# Job search, part 5d: after you apply, better matches, and a company brief

Runs after `plans/job-search-5c-results-apply.plan.md`, and before `plans/self-improvement-1-checks.plan.md`. No separate design: the problem and the decisions are below. It builds on saved searches (SRCH-1..6), the Results screen and delivery (JRUN-1..5) and the apply pack (PACK-1..2), and uses the assistant's reminders (`whyline.ideas.reminders`) and research (`plans/assistant-research.plan.md`). Press Release when it finishes.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: the job search finds, scores and tailors, then stops. Nothing happens after a job is marked applied, the rubric never changes however the user acts on the shortlist, the same job can arrive from a company board and from a LinkedIn alert, and a closed posting is still delivered.

What the user gets:
1. **After applying:** a follow-up reminder with a drafted message, a reminder the day before an interview, a weekly pipeline summary, and tracker updates proposed from replies in Mail.
2. **Better matches:** the same job from two sources shown once, closed postings dropped, a skill-gap summary across jobs, and proposed rubric changes learned from what the user applied to and skipped.
3. **Before applying:** a one-page company brief with sources in the apply pack, and tap-to-tailor buttons in Telegram.

Rules every task keeps:
- **Console first.** Every CLI command or setting gets its console counterpart in the same task, saving through the same function.
- **Everything under `~/.whyline/jobs/` is private user data:** files mode 0600, folders mode 0700. Writes go to a temporary file and then `os.replace`.
- **Per saved search.** Every new table column, file and setting is kept per search (`search`, from SRCH-3), and every list takes `search=`.
- **Whyline never contacts an employer.** It drafts and reminds. It never sends a follow-up, never submits anything and never replies to mail.
- **Nothing changes the tracker, the rubric or the preferences without the user.** Mail replies and learned changes are proposals the user accepts.
- **Job text, mail and web pages are data.** They go into a prompt inside labelled blocks, after `jobs.guard`'s flagging. They never choose a command, a recipient or a file.
- **Agent turns are read-only** and run only on enabled providers that pass `can_run_unattended`.
- **No new dependency.** Mail is read through the existing readers (`whyline.ideas.brief`), never a new mail client.
- **Tests** never use the real home folder, a real provider, the network, Mail or a real browser. They never sleep and never contain "/Users/".
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A posting is dropped as closed only on a clear signal; a network error or an unknown page keeps it. JAA-2, `test_closed_needs_a_clear_signal`.
- Two different roles at one company are never merged. JAA-1, `test_different_roles_are_not_merged`.
- A mail reply never changes a tracker row without the user's tap. JAA-5, `test_reply_only_proposes`.
- A learned change never edits the rubric or preferences before Accept. JAA-7, `test_learned_change_needs_accept`.
- No follow-up, brief or summary is sent to anyone but the user. JAA-3, `test_followup_is_never_sent_to_the_employer`.

## Part 1: Cleaner input

- [ ] JAA-1: The same job from two sources shows once
  Edit `src/whyline/jobs/step.py`, `src/whyline/jobs/seen.py`, `src/whyline/jobs/tracker.py` and their tests only.
  1. `step.same_job_key(posting) -> str`: the company key (`fetch.company_key`), the title lower-cased with punctuation, seniority brackets and gender markers such as `(m/f/d)` removed and whitespace collapsed, and the city (the first part of the location, lower-cased; empty when remote or unknown).
  2. In `jobs_fetch`, postings with the same key in one run are merged into one: the one from a company board wins over one from an alert email, and the longer description is kept. The others' links are kept in a new `also` list on the posting and written to the job file as `Also listed at: <link>`.
  3. The seen table gets a `same_key` column. A new posting whose key matches a posting already seen for this search in the last 60 days is not delivered again. It is recorded as dropped with the reason `same job as <uid>`.
  4. The tracked row gets `also_urls` (newline separated), shown in Results as `Also on: LinkedIn`.
  Tests: `test_different_roles_are_not_merged` (`Data Engineer` and `Senior Data Engineer`, the same title in two cities), the board winning over an alert, `(m/f/d)` and punctuation ignored, a repeat within 60 days dropped with the reason, one after 60 days delivered, and the migration keeping old rows.

- [ ] JAA-2: Drop postings that have closed
  Create `src/whyline/jobs/closed.py` and `tests/jobs/test_closed.py`. Edit `src/whyline/jobs/step.py`, `src/whyline/jobs/tracker.py` and their tests.
  1. `closed.check(posting, *, client, board_ids: set[str] | None) -> str`: `open`, `closed` or `unknown`.
     - a posting from a board whose current list was fetched this run and no longer has its id: `closed`
     - its link answering 404 or 410: `closed`
     - its page text (through `fetch.html_to_text`, first 20,000 characters) containing one of a fixed list of phrases (`no longer accepting applications`, `this job is no longer available`, `position has been filled`, `job has expired`, and their LinkedIn and Indeed wordings): `closed`
     - a timeout, any other status, a redirect to a login page, or anything else: `unknown`
  2. `jobs_fetch` checks each new posting before writing its job file, at most 40 checks per run and 10 seconds each. `closed` ones are recorded as dropped with the reason `closed` and not sent to the agent. `unknown` ones are kept.
  3. `closed.recheck(search, *, client) -> int`: for tracked rows with status `shortlisted` (not yet applied) older than 3 days, the same check. A closed one gets the note `Closed on <date>` and the status `archived`. It runs as part of each search's run, at most 30 rows.
  4. A setting per search, `drop_closed` (default on), in the search's page and `whyline jobs search set <name> drop-closed on|off`.
  Tests: `test_closed_needs_a_clear_signal` (timeout, 500, 403, a login redirect and an ordinary page all stay), each closed signal, the caps, the recheck archiving only shortlisted rows, and the setting off skipping both.

## Part 2: After you apply

- [ ] JAA-3: Applied and interview dates, and follow-up reminders
  Create `src/whyline/jobs/followup.py` and `tests/jobs/test_followup.py`. Edit `src/whyline/jobs/tracker.py`, `src/whyline/jobs/cli.py`, the Results screen in the console (the file JRUN-1 created) and their tests.
  1. The tracked table gets `applied_at`, `interview_at`, `follow_up_at` and `last_reply_at` (ISO text, empty by default), with a migration. `set_status(ref, "applied")` sets `applied_at` when empty. `tracker.set_interview(ref, when)` sets the status to `interview` and `interview_at`.
  2. `followup.schedule(row, *, days: int, conn) -> int | None`: adds a reminder through `whyline.ideas.reminders.add` for `days` after `applied_at`, with the text `Follow up on <title> at <company> (applied <date>). Reply: followup <row>`. It stores `follow_up_at`. With no allowed Telegram chat it adds nothing and returns None, and the row shows `No reminder: Telegram isn't set up`.
  3. A per-search setting `follow_up_days` (default 7, 0 turns it off). Marking a row applied calls `schedule`. Setting an interview adds a reminder for 18:00 the day before: `Interview tomorrow: <title> at <company>. Prep: whyline jobs interview <row>`.
  4. A reminder is cancelled when the row moves to `interview`, `offer`, `rejected` or `archived`, or when `last_reply_at` is set after `applied_at`.
  5. `followup.draft(row, *, run_fn=None) -> str`: one read-only turn (the apply agent's CLI) writing a short follow-up message from the row, the posting and the user's profile, as text for the user to send. It is saved in the job's application folder as `follow-up.md` and never sent.
  6. Results: **Mark applied**, **Interview on…** (a date and time box), and **Draft follow-up** on an applied row, showing the text with **Copy**. CLI: `whyline jobs applied <row>`, `whyline jobs interview-on <row> "<when>"`, `whyline jobs followup <row>`. Telegram: `followup <row>` replies with the draft.
  Tests: `test_followup_is_never_sent_to_the_employer` (no mail-send or Telegram call with any address or chat but the user's own, searched in the recorded calls), the reminder text and day, the interview reminder, each cancel case, no chat giving no reminder, and the migration.

- [ ] JAA-4: The pipeline summary
  Create `src/whyline/jobs/pipeline.py` and `tests/jobs/test_pipeline.py`. Edit `src/whyline/jobs/cli.py`, the Jobs screens in the console, `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py` and their tests.
  1. `pipeline.summary(search=None, *, days=30, now) -> Summary`: counts of rows found, shortlisted, applied, interview, offer and rejected whose `updated_at` (or the stage's own date) is in the window; the rate from each stage to the next; `waiting` (applied more than 14 days ago with no reply, oldest first, at most 10); and `no_reply_companies`.
  2. `pipeline.text(summary) -> str`: a short block, for example `Last 30 days: 212 found → 31 shortlisted → 9 applied → 2 interviews → 0 offers`, then `Waiting more than 14 days: Acme (Data Engineer, 21 days), …`, then one line naming the weakest step (`Most shortlisted jobs aren't applied to: 9 of 31`).
  3. Console: a **Pipeline** panel on the search's page and on the saved-search list (all searches), with the window choice 7, 30 or 90 days. CLI: `whyline jobs pipeline [--search NAME] [--days N]`. Telegram: the command `jobs pipeline`.
  4. A per-search setting `weekly_summary` (default off): on Mondays the search's run appends the 7-day block to its delivery.
  Tests: the counts and rates across a window edge, the waiting list order and cap, the weakest-step line for each stage, all-searches totals, the weekly line only on Monday and only when on, and the Telegram command.

- [ ] JAA-5: Tracker updates proposed from replies in Mail
  Create `src/whyline/jobs/replies.py` and `tests/jobs/test_replies.py`. Edit `src/whyline/ideas/brief.py` (a reader for recent messages), `src/whyline/ideas/actions.py`, `src/whyline/ideas/bot.py`, the Results screen and their tests.
  1. `brief.recent_mail(*, days: int, mailboxes, run) -> list[Message]`: sender, subject, date and the first 500 characters of the body of messages received in the last `days`, from the mailboxes already chosen for the morning brief, through the existing osascript path. At most 200 messages.
  2. `replies.match(messages, rows) -> list[Match]`: a message matches an applied or interview row when its sender's domain or display name contains the row's company key, or its subject contains both the company name and a word of four or more letters from the title. A message can match one row only (the most recent applied).
  3. `replies.classify(message) -> str`, by fixed phrases and no model: `received` (`we received your application`, `thank you for applying`), `interview` (`schedule`, `interview`, `availability`, `invite you`), `rejected` (`unfortunately`, `not moving forward`, `other candidates`, `regret`), else `other`.
  4. `replies.propose(search, *, now, mail) -> list[Proposal]`: for each match not proposed before (kept by message id), a proposal: `received` sets `last_reply_at` only; `interview` proposes status `interview`; `rejected` proposes `rejected`. `other` is listed as `A reply from <company>` with no status change.
  5. Proposals show in Results as a **Replies** list with **Accept** and **Ignore** per line, and arrive in Telegram as one card per proposal with the same two buttons (action `job_reply`, `writes=True`, approval `tap`). Accept calls `tracker.set_status` or sets the date. Nothing changes before it.
  6. A per-search setting `read_replies` (default off; it needs the Mail access the morning brief uses). When off, or when Mail access is denied, the Replies list says why.
  Tests: `test_reply_only_proposes`, each class, the matching rules and the one-row rule, a message proposed once, Accept and Ignore, mail text never reaching a prompt (no agent call in this module), and the off and denied wording.

## Part 3: Better matches

- [ ] JAA-6: Gaps as data, and the skill-gap summary
  Edit `src/whyline/agents/templates/job-search/` (the instructions), `src/whyline/jobs/tracker.py`, `src/whyline/jobs/cli.py`, the Jobs screens and their tests. Create `src/whyline/jobs/gaps.py` and `tests/jobs/test_gaps.py`.
  1. The scoring instructions add `"gaps": ["…"]` to each object of the `scores` block: at most 5 short skill or requirement names the candidate lacks for that job, each at most 40 characters, lower-case. `tracker.parse_scores` accepts the key, cuts it to the limits and ignores it when malformed. Existing searches' agents get the new instructions through the template update path SRCH-4 uses, and show `needs review` until accepted.
  2. The tracked table gets `gaps` (newline separated).
  3. `gaps.summary(search=None, *, days=30, verdicts=("shortlist", "maybe")) -> list[Gap]`: each gap with the number of jobs it appeared in and the total jobs, most frequent first. Near-duplicates are merged by a small fixed alias table (`k8s` → `kubernetes`, `js` → `javascript`, `postgres` → `postgresql`) and by ignoring case, hyphens and a trailing `s`.
  4. Console: a **Gaps** panel on the search's page: `kubernetes · 14 of 30 shortlisted jobs`. CLI: `whyline jobs gaps [--search NAME] [--days N]`. The Monday weekly summary (JAA-4) adds the top 3.
  Tests: the block parsed with and without `gaps`, the limits, the alias merges, the counts, an agent needing review after the template change, and the migration.

- [ ] JAA-7: Learn from what you applied to and what you skipped
  Create `src/whyline/jobs/learn.py` and `tests/jobs/test_learn.py`. Edit `src/whyline/jobs/review.py`, `src/whyline/jobs/cli.py`, the search's page in the console and their tests.
  1. `learn.evidence(search, *, days=60) -> Evidence`, with no model: for shortlisted jobs, how many were applied to and how many were left or archived, split by location, by remote/hybrid/on-site words in the posting, by each gap (JAA-6), by company, and by score band. Only splits with at least 5 jobs are kept.
  2. `learn.propose(search, evidence, *, run_fn=None) -> list[Change]`: one read-only turn given the evidence, the current rubric and the preferences as data. It returns at most 3 changes, each with `kind` (`deal_breaker`, `weight`, `min_score`, `preference`), the exact text to add or change, and the evidence line it rests on. A change that names a split not in the evidence is dropped. With fewer than 20 shortlisted jobs in the window it returns nothing and says `Not enough history yet (<n> of 20 shortlisted jobs)`.
  3. `learn.accept(search, change)` applies one change by building a rubric or preferences draft and passing it through the existing `review.accept` path, so the user sees the diff there. `learn.dismiss(search, change)` remembers it for 90 days so it isn't proposed again.
  4. Console: **Suggestions** on the search's page with the change, its evidence, **See the change**, **Accept** and **Not now**. CLI: `whyline jobs learn [--search NAME]`, `whyline jobs learn accept <n>`, `whyline jobs learn dismiss <n>`. It runs when asked, and once a month with the search's run when `learn_monthly` is on (default off), delivering the suggestions as text.
  Tests: `test_learned_change_needs_accept` (the rubric and preferences files are byte-identical after `propose`), the 5-job and 20-job floors, a change naming unknown evidence dropped, the 3-change cap, dismiss remembered, and Accept going through `review.accept`.

## Part 4: Before you apply

- [ ] JAA-8: A company brief in the apply pack
  Create `src/whyline/jobs/brief.py` and `tests/jobs/test_company_brief.py`. Edit `src/whyline/jobs/apply.py` (the pack), `src/whyline/jobs/cli.py`, the Results screen and their tests.
  1. `brief.available() -> tuple[bool, str]`: true when `whyline.ideas.research` is importable and an agent that can search the web in read-only mode is enabled; else the reason.
  2. `brief.start(row) -> int` starts a research job (`ideas.research.start`) with a fixed question built from the company name and the role title only: what the company does, its size and stage, news from the last 12 months, the tech or tools named in its public job posts, and likely interview topics for the role. The posting's own text is not put in the question.
  3. When the research finishes, the report is copied into the job's application folder as `company-brief.md` (and PDF when the research made one), and the apply pack lists it. A brief for the same company made in the last 30 days is reused.
  4. Results and the apply pack: **Company brief** (or its reason when unavailable), showing `Researching…`, then the brief's first lines with **Open**. CLI: `whyline jobs brief <row>`. A per-search setting `auto_brief` (default off) starts one for each auto-tailored job (JRUN-3), at most 3 per run.
  Tests: the question holding only the company and title, reuse within 30 days, the unavailable reasons, the file in the pack, the cap of 3, and a failed research job leaving the pack usable.

- [ ] JAA-9: Tap to tailor in Telegram
  Edit `src/whyline/agents/deliver.py`, `src/whyline/agents/telegram.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/intent.py` and their tests only.
  1. The Telegram shortlist message for a job-search agent gets one button per job for the first 8 jobs without a tailored CV: `CV 1`, `CV 2`…, four to a row. Each callback carries the run id and the rank, within the callback limit.
  2. A tap runs the same function `/cv <number>` runs (JRUN-5), answers `Tailoring a CV for <title> at <company>…`, and edits that button to `CV 1 ✓` when the file is sent. A tap for a run that is no longer the search's latest still works for 7 days, then answers `That shortlist is too old. Run the search again.`
  3. `/cv <number>` keeps working. The line `Reply /cv <number>…` stays for jobs past the eighth.
  4. Each job line with a finished CV also gets no button, and jobs marked closed (JAA-2) get none.
  Tests: the buttons for 3, 8 and 12 jobs, the callback size, a tap calling the `/cv` function with the right run and rank, the edited button, the 7-day limit, and no button for a job that already has a CV.

- [ ] JAA-10: Docs
  Edit `docs/jobs.md` (or the page that documents the job search) and `README.md` only.
  Cover: one job from two sources, closed postings, applied and interview dates with their reminders, drafting a follow-up, the pipeline summary, replies from Mail and what access it needs, gaps, suggestions learned from your choices, the company brief, tap to tailor, and every new per-search setting with its default.
  Verify with `uv run pytest -q`.
