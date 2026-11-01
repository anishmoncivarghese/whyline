<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-01T12:00:00+05:30 -->
# Job search, part 5: saved searches, a setup check, run results with tailored CVs, and an apply pack

Merged on 2026-11-01 from `job-search-5-tailored-cv` (CVT-1..7, unchanged) and the user's new job search requests. Runs after `plans/sdlc-pipeline.plan.md`, before `personal-assistant`. JSR-1 publishes at the end.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task. Each part keeps its own intro and rules. Read the intro of the part a task is in before starting it.

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

## Part 1: Companies table you can read

The Companies table in Jobs shows 7 rows and gives no count. After **Accept all suggested**, the user couldn't tell what was accepted, and couldn't see that every company still had `ats = unknown` because **Check boards** had never run.

- [ ] CMP-1: Select all, a count line and a status filter in the Companies table
  Edit `src/whyline/console/jobs_screens.py` and `tests/console/test_jobs_screens.py` only.
  1. Above the table, add a count line computed from `companies.list()`. For example: `39 accepted · 12 with a job board · 27 board not found or not checked · 0 suggested`. A company counts as "with a job board" when `ats != "unknown"`. Refresh the line wherever `_refresh_companies` runs.
  2. When any accepted company has never been checked (`checked_at` empty), add a second line: `27 companies have not been checked. Press Check boards so whyline can find their job boards.`
  3. Add a `Select` filter next to the table: All, Accepted, Suggested, No board, Removed. The default is All. The filter applies only to which rows show, and ticks on rows that are hidden are cleared.
  4. Add a **Select all** checkbox that ticks or clears every visible row. It is ticked only when every visible row is ticked.
  5. Raise the table's `max-height` from 7 to 14 rows.
  6. Add a Board column showing the board type, or `—`. Add a Checked column showing the date, or `never`.
  Tests:
  - the count lines for a mix of companies
  - each filter value
  - Select all ticks only visible rows, and its state follows manual ticks
  - the new columns
  Verify with `uv run pytest -q tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] CMP-2: After Check boards, say what was found and what to do about the rest
  Edit `src/whyline/jobs/companies.py` (only the summary that `check` returns), `src/whyline/console/jobs_screens.py` and their tests only.
  1. After **Check boards** finishes, the status line says, for example: `Checked 39: 12 boards found (Workday 7, Greenhouse 3, Lever 2), 27 not found.`
  2. When some boards were not found, add: `For those, paste the company's job board link with Add company… and the same name, or set up a job alert from LinkedIn or Naukri with Mail rule….`
  3. The CLI `whyline jobs companies check` prints the same summary from the same function.
  Tests: the summary for all found, none found and a mix, and the same text from the console and the CLI. Change nothing else.

## Part 2: A tailored CV in your own Word template

Runs after Part 1. Build on the real names in `src/whyline/jobs/`: `profile.import_cv`, `profile.import_cv_text`, `profile._read_docx_text`, `profile._extract_paragraphs`, `profile._write_private_text`, `profile.CV_FILE`, `paths.home`, `paths.configured_home`, `apply.draft`, `apply.DraftResult`, `apply._review_and_revise`, `apply._review_instructions`, `apply._write_private`, `apply.folder_for`, `apply.DRAFT_FILE`, `apply.FINAL_FILE`, and on `JobsHomeScreen` in `src/whyline/console/jobs_screens.py` (`_start_draft`, `_on_draft_done`, `_open_draft_folder`, `open_file_fn`). Where a name has moved, follow the repository and keep the behaviour.

What the user gets:
- When the CV is imported from a `.docx`, whyline keeps that Word file as the CV template. The CV panel says `Word template: <file name>`.
- **Draft application** then also writes `<your file name> - <Company>.docx` in the job's application folder. It's your own Word file, with the same fonts, layout, columns, colours, photo, headers and bullet styles. The summary and bullets are tailored to the job: reworded, and reordered within each role. Nothing outside those paragraphs changes.
- `cv-changes.md` next to it lists every change as before → after, plus every suggested change whyline refused and why.
- **Open tailored CV** opens the Word file. **Rebuild CV** re-applies the edits from `final.md` (or `draft.md`) without running an AI. You can fix a wording in `final.md`, rebuild, and get a new Word file in a second.
- CLI for scripts: `whyline jobs draft` prints the tailored CV's path. `whyline jobs cv-build <ref>` is Rebuild CV.
- A CV imported from `.md`, `.txt`, `.pdf` or pasted text has no Word template. Drafts work as today, and the CV panel says `No Word template. Import your CV as .docx to get a tailored CV in your own layout.`

Rules every task keeps:
- Console first. Every CLI change gets its console counterpart in the same task, calling the same function.
- No new dependency. Word files are read with `zipfile` and `xml.etree.ElementTree` and written by splicing the original XML text (CVT-3 says why). No whyline-relay change. No version bump, tag, push or publication.
- whyline never adds facts. The agent may only reword, reorder or drop paragraphs that already exist. It never adds a paragraph, and it never adds a number that isn't already in the CV. whyline enforces both mechanically, not only through the prompt.
- The template and every tailored file are private user data: mode 0600 in folders that are mode 0700, under `~/.whyline/jobs/`.
- A Word file is untrusted input. Reading it never runs macros or follows external links, and every parse error becomes a plain `ProfileError` or `ApplyError` naming the file.
- Tests build small `.docx` files in a temporary folder from XML strings. They never use the real home folder, a real provider or the network, never sleep, and never contain "/Users/".

- [ ] CVT-1: Keep the Word CV as the template
  Edit `src/whyline/jobs/profile.py`, `src/whyline/jobs/cli.py` (the `profile show` / status output), `src/whyline/console/jobs_screens.py` (the CV status line) and their tests only.
  1. Add `TEMPLATE_FILE = "cv-template.docx"` and `TEMPLATE_META = "cv-template.json"`.
  2. When `import_cv` imports a `.docx` and `cv.md` is written, copy the source file byte for byte to `~/.whyline/jobs/cv-template.docx` (mode 0600, written to a temporary file then `os.replace`). Write `cv-template.json` with `{"name": "<original file name>", "imported": "<ISO time>", "cv_sha256": "<sha256 of the new cv.md>"}`. Refuse a `.docx` over 10 MB before copying, with `Word file is over the 10 MB limit.`
  3. When `import_cv` imports any other format, or `import_cv_text` is called directly (Paste CV…), delete both template files. The new CV no longer matches the old Word file.
  4. If writing `cv.md` fails, leave the existing template untouched.
  5. Add `profile.cv_template() -> CvTemplate | None` with `path`, `name`, `imported` and `stale: bool`. `stale` is true when the sha256 of the current `cv.md` differs from `cv_sha256`, meaning cv.md was edited by hand after the import. Return None when either file is missing or the JSON is unreadable.
  6. CLI status and the console CV status line show one of:
     - `Word template: <name>`
     - `Word template: <name> (cv.md was edited after import; the tailored CV uses the Word file's text)`
     - `No Word template. Import your CV as .docx to get a tailored CV in your own layout.`
  Tests:
  - a `.docx` import writes the template copy byte-identical to the source, plus the meta, both mode 0600
  - `.md`, `.txt` and Paste CV remove an existing template
  - a failed import keeps the old template
  - `stale` flips after cv.md is edited
  - the over-10 MB refusal
  - the console line in all three states
  Verify with `uv run pytest -q tests/jobs tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] CVT-2: Read the template's paragraphs
  Add `src/whyline/jobs/word_cv.py` and `tests/jobs/test_word_cv.py`. Change nothing else.
  Add `read_paragraphs(docx: Path) -> list[CvParagraph]`. A `CvParagraph` has:
  - `id` (`P1`, `P2`, … in document order)
  - `text`
  - `style` (the `w:pStyle` value or "")
  - `list_level` (from `w:numPr/w:ilvl`, or None when not a list item)
  - `group` (consecutive paragraphs with the same parent element, the same `w:numId` and the same level share a group id `G1`, `G2`, …; non-list paragraphs have no group)
  - `locked` (a reason string, or "" when editable)
  Rules:
  1. Read only `word/document.xml`, with the same 10 MB and no-entities limits as `profile._read_docx_text`. Find the prefix bound to the WordprocessingML namespace (`http://schemas.openxmlformats.org/wordprocessingml/2006/main`) from the root element. Never assume it is `w`.
  2. Number every `w:p` in the body in document order, including paragraphs inside tables. Skip paragraphs whose text is empty after stripping, but keep their numbers so ids stay stable.
  3. Refuse the whole file with `ProfileError("This Word file has tracked changes. Accept or reject all changes in Word, save, and import it again.")` if any `w:ins` or `w:del` exists.
  4. Lock a paragraph (editable = False, with a reason) when it:
     - is inside `w:txbxContent` ("text box"; Word stores text boxes twice, in `mc:Choice` and `mc:Fallback`, so editing one copy would show different text in different apps)
     - contains `w:fldChar`, `w:fldSimple` or `w:hyperlink` ("link or field")
     - contains `w:drawing`, `w:object` or `w:pict` ("picture")
     - has fewer than 3 words ("heading or label")
  5. Add `paragraph_map(paragraphs) -> str`, the Markdown the agent reads:
     ```
     # Word CV paragraphs
     P3 [G1 · list level 0] Led the migration of …
     P4 [G1 · list level 0] Built …
     P9 [locked: text box] Contact …
     ```
     One line per non-empty paragraph, each text cut to 400 characters.
  Tests: build each case as a minimal `.docx` from XML strings:
  - plain paragraphs, and a non-`w` prefix
  - a bullet list giving one group, and two lists giving two groups
  - a table cell
  - a text box, a hyperlink and a picture, each locked
  - a tracked change refused
  - stable ids around empty paragraphs
  - the map's format and the 400-character cut
  Verify with `uv run pytest -q tests/jobs` and then `uv run pytest -q`. Change nothing else.

- [ ] CVT-3: Apply edits to the template, keeping its formatting
  Edit `src/whyline/jobs/word_cv.py` and `tests/jobs/test_word_cv.py` only.
  Add `CvEdits(replace: dict[str, str], order: list[list[str]], drop: list[str])` and `apply_edits(template: Path, edits: CvEdits, cv_text: str, out: Path) -> ApplyReport`. An `ApplyReport` has:
  - `applied`: (id, before, after) for each change made
  - `refused`: (id, reason) for each change refused
  - `path`: the output file, or None
  Why splice: `ElementTree` rewrites namespace prefixes and drops declarations it thinks are unused. `mc:Ignorable="w14 wp14 …"` names prefixes only by string, so a re-serialised `document.xml` can make Word refuse to open the file. So:
  - Parse with ElementTree only to find paragraphs and runs.
  - Write by splicing the original `document.xml` text, using character offsets from a small scanner. The scanner matches `<P:p>`/`<P:p …>` to `</P:p>` with nesting depth, and finds `<P:t>`/`<P:t …>` elements inside each paragraph.
  - Copy every other zip entry byte for byte, with its original name, order and compression.
  Each edit is checked on its own. A refused edit is reported and skipped, and the rest still apply:
  1. **Unknown or locked id**: refused with "unknown paragraph" or the lock reason.
  2. **Replace length budget**: the new text may be at most 15% plus 20 characters longer than the original. Otherwise it's refused with "too long; would change the layout". This keeps a one-page CV on one page.
  3. **No new numbers**: every number in the new text (digit runs, including forms like `40%`, `3.5`, `2019`, `$2M`, reduced to their digits) must appear somewhere in `cv_text`. Otherwise it's refused with "adds a number not in your CV: <n>".
  4. **Replace keeps run formatting**: put the new text in the paragraph's first `w:t` and empty the other `w:t` elements in that paragraph, keeping every `w:rPr`. One exception: if the first run's formatting differs from the second's (a bold lead-in like `Python:`) and the new text starts with the first run's exact text, keep that run's text and put the rest in the second run. Set `xml:space="preserve"` on any `w:t` whose new text starts or ends with a space. Escape `&`, `<` and `>`.
  5. **Order**: each list must be exactly a permutation of the paragraph ids of one group (CVT-2). Otherwise it's refused with "order must reorder one whole bullet group". Reorder by moving whole paragraph spans. Spans between the group's paragraphs, such as empty paragraphs, stay where they are.
  6. **Drop**: allowed only for list paragraphs. At least 2 paragraphs must stay in the group. Remove the whole paragraph span.
  7. **No adds**: there is no add operation. An id that isn't in the template is "unknown paragraph".
  Write to a temporary file in `out`'s folder, check the result opens as a zip and its `document.xml` parses, then `os.replace` with mode 0600. If nothing was applied, write no file and set `path` to None.
  Tests:
  - a replace keeps the paragraph's `w:pPr` and the first run's `w:rPr` byte for byte
  - the bold lead-in rule
  - escaping and `xml:space`
  - over-budget and new-number refusals, with the other edits still applied
  - reorder within a group; a cross-group order refused
  - drop, and drop refused at 2 left
  - `mc:Ignorable` and every root namespace declaration survive unchanged
  - every non-`document.xml` entry is byte-identical
  - the output's text read back through `profile._read_docx_text` shows the edits
  Verify with `uv run pytest -q tests/jobs` and then `uv run pytest -q`. Change nothing else.

- [ ] CVT-4: Ask the drafting agent for Word CV edits
  Edit `src/whyline/jobs/apply.py`, `src/whyline/jobs/word_cv.py`, add `src/whyline/agents/templates/job-apply/word-cv.md`, edit `src/whyline/agents/templates/job-apply/review.md`, and edit their tests only.
  The user's existing `job-apply` agent keeps the instructions it was created with, so the new rules must not go into `instructions.md`. Instead, `apply.draft` appends `word-cv.md` at run time, read the same way as `_review_instructions`.
  1. When `profile.cv_template()` is not None, write `cv-paragraphs.md` (the CVT-2 map) into the application folder (mode 0600). Add it to the run's `sources`, and append `word-cv.md` to the run's instructions. When there's no template, nothing changes.
  2. `word-cv.md` tells the agent to add a fifth section after `## Gaps (not added)`:
     ~~~
     ## Word CV edits
     ```json
     {"replace": {"P3": "…"}, "order": [["P5", "P4", "P6"]], "drop": ["P7"]}
     ```
     ~~~
     The rules it states:
     - use only ids from `cv-paragraphs.md`, never a locked one
     - replace the summary paragraph with the tailored summary
     - reword bullets toward the posting using only facts already in that bullet or elsewhere in `cv.md`
     - keep each replacement about as long as the original
     - put each role's most relevant bullets first with `order`
     - drop at most the weakest one or two bullets of a role, and only when they are unrelated to the posting
     - never add a number, employer, title, date, skill or credential
     - if no edit is worth making, return `{}`
  3. `review.md` adds a fifth critique kind: `[Word CV edit]` for an edit that changes a fact, moves a bullet out of its role, or drops something the posting asks for. Pass `cv-paragraphs.md` to the reviewer's sources when it exists.
  4. The revise step already asks for "the complete revised four sections". When a template exists, ask for five sections.
  5. Add `word_cv.parse_edits(answer: str) -> CvEdits | None`. It takes the first fenced `json` block under `## Word CV edits`, accepts only the keys `replace`, `order` and `drop` with the right types, and ignores unknown keys. It returns None when the section or block is missing or the JSON is invalid, and never raises.
  6. A missing or invalid edits section never fails the draft. The four existing sections are still required, as today.
  Tests:
  - with a template, `cv-paragraphs.md` is written, in sources, and `word-cv.md` is appended (check the run definition given to a stub `run_fn`)
  - without a template, nothing changes
  - `parse_edits`: a valid block, a missing section, bad JSON, wrong types, unknown keys
  - the reviewer gets the map
  - a draft whose answer lacks the fifth section still succeeds
  Verify with `uv run pytest -q tests/jobs` and then `uv run pytest -q`. Change nothing else.

- [ ] CVT-5: Build the tailored CV after a draft, and `cv-build`
  Edit `src/whyline/jobs/apply.py`, `src/whyline/jobs/cli.py`, `src/whyline/jobs/word_cv.py` and their tests only.
  1. Add `apply.build_cv(ref) -> CvBuildResult(ok, path, changes_path, applied, refused, note)`. It:
     - finds the application folder
     - reads `final.md` if it exists, else `draft.md`
     - parses the edits, then calls `word_cv.apply_edits` on the template with the text of `cv.md`
     - writes `cv-changes.md`
     It runs no AI.
     Notes, in order:
     - `No Word template.`
     - `No draft yet; run Draft application first.`
     - `The draft has no Word CV edits.`
     - `No edit could be applied; see cv-changes.md.`
     - otherwise `N changes applied, M refused.`
  2. Output name: `<template stem> - <Company>.docx`, using the template's original file name from the meta, not `cv-template`. Remove `/ \ : * ? " < > |` and control characters, and cut to 80 characters. Each build overwrites the previous file for that job.
  3. `cv-changes.md` has a heading with the job title and company, then `Changed` with each `Pn` as a before line and an after line, `Reordered`, `Dropped`, and `Refused` with each id and reason. It ends with: `Check the file in Word before sending it. whyline never adds facts, but check every line reads as you would say it.`
  4. At the end of a successful `apply.draft`, call `build_cv`. Add `cv_path` and `cv_note` to `DraftResult`. A build error becomes `cv_note`, and the draft still succeeds.
  5. CLI:
     - `whyline jobs draft` prints `Wrote <cv path>.` and the note.
     - Add `whyline jobs cv-build <ref>`, which prints the path and note. Exit 0 when a file was written, 1 otherwise.
  Tests, with a stub `run_fn` returning a fixed answer:
  - draft → tailored file and `cv-changes.md` exist, and the name uses the original stem and the company
  - `final.md` takes priority over `draft.md`
  - editing `final.md` by hand then running `cv-build` reflects the edit
  - each note case
  - a filename with forbidden characters
  - the CLI output and exit codes
  Verify with `uv run pytest -q tests/jobs` and then `uv run pytest -q`. Change nothing else.

- [ ] CVT-6: Console: Open tailored CV and Rebuild CV
  Edit `src/whyline/console/jobs_screens.py` and `tests/console/test_jobs_screens.py` only.
  1. Next to **Open folder**, add **Open tailored CV** and **Rebuild CV**. Both are disabled until a draft for the highlighted job exists. **Open tailored CV** is enabled only when that job's tailored file exists.
  2. After a draft finishes, the status line adds the CV note, for example `Draft ready in ~/.whyline/jobs/applications/acme_data-engineer. Tailored CV: 6 changes applied, 1 refused.`
  3. **Open tailored CV** opens the `.docx` through the same `open_file_fn` / `_open_with_macos` path as **Open folder**.
  4. **Rebuild CV** calls `apply.build_cv` in a thread worker, shows its note, and refreshes the button state. Add an injectable `build_cv_fn`, in the same style as `draft_fn`.
  5. When the highlighted job changes, the buttons follow that job's folder, not only the last draft.
  Tests:
  - the button states for no draft, a draft without a CV, and a draft with a CV
  - Open calls the opener with the `.docx` path
  - Rebuild calls the same `build_cv` and shows its note
  - the status line after a draft
  Verify with `uv run pytest -q tests/jobs tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] CVT-7: Docs for part 5
  Edit `docs/job-search.md` only.
  - Explain the tailored CV in your own Word layout:
    - import as `.docx`
    - what changes and what never does
    - the no-new-facts and no-new-numbers rules
    - the length budget
    - why text boxes, links and pictures are left alone
    - `cv-changes.md`
    - Rebuild CV after editing `final.md`
    - `whyline jobs cv-build`
  - Say that a Google Docs CV should be downloaded as `.docx`, and that a CV with tracked changes must have them accepted first.
  - Say that PDF is not written: open the tailored `.docx` in Word or Pages and export it as PDF.
  Verify with `uv run pytest -q`. Change nothing else.

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

- [ ] JSR-1: Publish whyline with job search part 5
  relay-profile: release
  1. Bump the version in `pyproject.toml`, `src/whyline/__init__.py` and `uv.lock` to the next patch version.
  2. Write `docs/releases/v<version>.md` from every task since the previous release (`git log v<previous>..HEAD`), in user terms.
  3. Mention:
     - the one-time move of job files into "My job search"
     - its backup folder
  4. Run `uv run pytest -q` with the agent CLIs off PATH and `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1`, and again on Python 3.11.
  5. Push, and wait for green CI on Linux and macOS.
  6. Tag `v<version>`, push the tag and let the release workflow publish to PyPI.
  7. Run `uv tool upgrade whyline` and confirm `whyline --version`.

## Later, not in this plan

- Save the tailored CV as PDF directly. Use LibreOffice (`soffice --headless --convert-to pdf`) when it's installed, or Word through AppleScript, and add the PDF only when the conversion is exact.
- Tailored cover letter in a Word letter template the user imports.
- Editing paragraphs inside text boxes. It needs both the `mc:Choice` and `mc:Fallback` copies changed together, and tests against Word, Pages and Google Docs.
- Assisted form filling: build it from `plans/assisted-apply.plan.md` once ASF-1's design is approved.
- Tap-to-tailor buttons in Telegram, instead of typing `/cv N`.
- Expired-posting check before delivery: re-fetch each link and drop jobs that are closed.
