<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-01T12:00:00+05:30 -->
# Job search, part 5: saved searches, a setup check, run results with tailored CVs, and an apply pack — a: the Companies table and a tailored CV

Runs after `plans/workflows-2-to-4.plan.md`, and before `plans/job-search-5b-saved-searches.plan.md`. Split on 2026-11-15 from `job-search-5.plan.md` (27 tasks) into three plans, so each relay is short and ends with a release. This file builds: Parts 1 and 2 (CMP-1..2, CVT-1..7); items 4 to 6 of the list below come with the later two plans. Press Release when it finishes.

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

