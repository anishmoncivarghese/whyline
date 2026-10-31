<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-10-31T12:00:00+05:30 -->
# Job search, part 4: PDF CVs, picking several companies at once, and Workday job boards

Runs after `job-search-3-alerts-and-applications.plan.md` (shipped in 0.3.58). Build on the real names in `src/whyline/jobs/`: `profile.import_cv`, `profile._pasted_path`, `profile.import_cv_text`, `profile.CV_EXTENSIONS`, `companies.Company`, `companies.add`, `companies.accept`, `companies.remove`, `companies.check`, `companies.suggest`, `ats.HttpClient`, `ats.make_http`, `ats.detect`, `ats.BOARD_API_HOSTS`, `ats._extract_board_matches`, `fetch.Posting`, `fetch.board_jobs` and `fetch._PARSERS`, and on `JobsHomeScreen` in `src/whyline/console/jobs_screens.py`. Where a name has moved, follow the repository and keep the behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

What the user gets:
- **Import CV…** and `whyline jobs profile import-cv <file>` accept a `.pdf` as well as `.md`, `.txt` and `.docx`. A scanned PDF with no text is refused with a plain message, so a near-empty CV is never saved. After any import, whyline shows how much text it read and the first lines.
- In the Companies table the user can tick several rows and accept or remove them in one step, or accept every suggested company at once. The full reason for the highlighted company shows under the table.
- Companies whose jobs are on **Workday** (`*.myworkdayjobs.com`; most large banks and IT services firms) are read like the other job boards. whyline finds the Workday board from the company's careers page, or the user pastes the Workday link.

Rules every task keeps:
- Console first. Every CLI change gets its console counterpart in the same task, saving through the same function.
- The one new dependency is `pypdf`, added only in JOB-23. Nothing else new. No whyline-relay change. No version bump, tag, push or publication.
- Tests use recorded fixtures and stubs, never the network, a real provider or the real home folder. They never sleep and never contain "/Users/".
- PDF files and web responses are untrusted input. Reading them never runs code and never follows a link outside the rules below. Every library or parse error becomes a plain `ProfileError` or `FetchError` naming the file or company.

- [ ] JOB-23: Read PDF CVs
  Edit `pyproject.toml`, `uv.lock`, `src/whyline/jobs/profile.py`, `src/whyline/jobs/cli.py` (the `import-cv` help text), `src/whyline/console/jobs_screens.py` (the path placeholder and the empty-path message) and `tests/jobs/test_profile.py` only, and add PDF fixtures under `tests/jobs/fixtures/`.
  Add `pypdf` to `[project] dependencies` with an upper bound below its next major version, then run `uv lock`.
  Add `.pdf` to `CV_EXTENSIONS`. Every message listing the formats becomes ".md, .txt, .docx, or .pdf".
  Add `_read_pdf_text(source)`:
  1. Refuse a file over 10 MB before opening it, with `PDF is over the 10 MB limit.`
  2. Open it with `pypdf.PdfReader(strict=False)`. An encrypted PDF that does not open with an empty password is refused with `This PDF is password-protected; export it without a password and try again.`
  3. Read text from at most the first 20 pages with `extract_text()`, join the pages with a blank line, and collapse runs of 3 or more newlines to two.
  4. If the stripped text has fewer than 200 characters, refuse with `No text found in this PDF. It looks like a scan; export your CV from Word or Google Docs as .docx or PDF and try again.`
  5. Any pypdf or parsing exception becomes `ProfileError("Could not read PDF file: <short reason>")`.
  The result goes through `import_cv_text`, so the 200 KB text limit and the keep-the-old-CV-on-failure behaviour stay the same.
  Fixtures: a small text PDF written by hand as bytes (one page with a name and a few lines; no generator dependency), an image-only or blank PDF, an encrypted PDF and a truncated file. Keep each under 20 KB.
  Tests:
  - a text PDF imports, and its lines reach cv.md
  - a blank or image PDF is refused, and the existing CV stays
  - an encrypted PDF is refused with the password message
  - a truncated PDF is refused with `Could not read PDF file`
  - a file over 10 MB is refused before pypdf is called (monkeypatch `PdfReader` to fail if it is called)
  - only the first 20 pages are read (monkeypatch a reader with 25 pages)
  - a quoted pasted path to a PDF still imports
  Verify with `uv run pytest -q tests/jobs tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] JOB-24: Show what was read after a CV import
  Edit `src/whyline/jobs/profile.py`, `src/whyline/jobs/cli.py`, `src/whyline/console/jobs_screens.py` and their tests only.
  Add `profile.cv_summary(path=None) -> CvSummary` with `chars`, `lines` and `preview` (the first 5 non-blank lines, each cut to 100 characters), read from cv.md.
  CLI: after `import-cv` succeeds, print `Imported N characters. First lines:` followed by the preview, indented.
  Console: after **Import CV…** or **Paste CV…** succeeds, the CV status line on JobsHomeScreen shows `CV: N characters from <file name>`. Below it, show the preview in a dim block with the hint `Check this reads like your CV. If lines are jumbled, try the .docx version.` The block is gone when the screen is reopened.
  Tests:
  - `cv_summary` counts and cuts lines correctly, and skips blank lines
  - the CLI prints the preview
  - the console shows the preview after an import and saves through the same `import_cv` function
  Verify with `uv run pytest -q tests/jobs tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] JOB-25: Accept or remove several companies at once
  Edit `src/whyline/jobs/companies.py`, `src/whyline/jobs/cli.py`, `src/whyline/console/jobs_screens.py` and their tests only.
  Add `companies.accept_many(names)` and `companies.remove_many(names)`. Each loads the store once, changes every named company, and writes once. If any name is unknown, raise `CompanyError` listing all unknown names and change nothing. `accept` and `remove` call them with one name, keeping their return values.
  Add `companies.suggested_names()`, which returns the names with status `suggested` in table order.
  CLI: `whyline jobs companies accept` and `remove` take one or more names. `accept --all-suggested` takes no names. Each prints one line per company, then `Accepted N companies.` or `Removed N companies.`
  Console, in the Companies section of JobsHomeScreen:
  - Add a first column `✓`. **Space** or a click on that cell ticks or unticks the highlighted row. Ticks are kept by company name, so a table refresh after Check boards or Suggest keeps them.
  - **Accept** and **Remove** act on the ticked rows, or on the highlighted row when nothing is ticked. Their labels read `Accept (3)` and `Remove (3)` while 3 rows are ticked.
  - Add **Accept all suggested**. It shows a confirm line, `Accept 39 suggested companies?` with Yes and Cancel, before calling `accept_many(suggested_names())`.
  - After an action, clear the ticks and show `Accepted 3 companies.` in the existing status line.
  - Below the table, a dim line shows the highlighted company's full reason and careers URL. It changes with the cursor, so the cut-off Reason column can be read in full.
  Tests:
  - `accept_many` changes all named companies in one write, and an unknown name changes nothing
  - the CLI takes several names and `--all-suggested`
  - Space ticks rows, and ticks survive a table refresh
  - the Accept and Remove labels show the count
  - Accept with ticks calls `accept_many` with exactly the ticked names
  - Accept all suggested asks first, and Cancel changes nothing
  - the reason line follows the cursor
  Verify with `uv run pytest -q tests/jobs tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] JOB-26: Workday boards in the HTTP client and URL parser
  Edit `src/whyline/jobs/ats.py` and `tests/jobs/test_ats.py` only.
  A Workday board lives at `https://<tenant>.<wdN>.myworkdayjobs.com/[<locale>/]<site>`. Examples: `bnymellon.wd1.myworkdayjobs.com/en-US/BNY_Careers` and `mastercard.wd1.myworkdayjobs.com/CorporateCareers`. Its public job search is `POST https://<host>/wday/cxs/<tenant>/<site>/jobs`, and one job's detail is `GET https://<host>/wday/cxs/<tenant>/<site><externalPath>`.
  1. Add `workday` to the board names. Store its slug as `<tenant>/<wdN>/<site>`. The site part keeps its case; the tenant and `wdN` are lower-cased.
  2. `_extract_board_matches` recognises a myworkdayjobs.com URL in any of the forms above, skipping a locale segment such as `en-US`, and returns `("workday", slug)`. Hosts must match `^[a-z0-9-]+\.wd[0-9]{1,3}\.myworkdayjobs\.com$`, and site names `^[A-Za-z0-9_-]{1,80}$`. Anything else is not a Workday match.
  3. `validate_fetch_url` allows a `*.myworkdayjobs.com` host matching that pattern only for paths under `/wday/cxs/`.
  4. `HttpClient` gains `post_json(url, body: dict)`. It sends `Content-Type: application/json` and `Accept: application/json`, and goes through the same URL validation, rate limiter, redirect handler, 5 MB cap and injected-transport hooks as GET. Only `/wday/cxs/.../jobs` URLs may be POSTed; any other URL raises `HostNotAllowedError`. A test transport can see the method and body.
  5. Before the first request to a Workday host in a run, read its `robots.txt` with `urllib.robotparser` through the same client. If `/wday/cxs/` is disallowed for our user agent, raise `AtsError("<host> robots.txt disallows its job search")`. Cache the answer per host for the client's lifetime.
  Tests:
  - every URL form parses to the right slug, and look-alike hosts (`myworkdayjobs.com.evil.com`, `evil.com/myworkdayjobs.com`) do not
  - a POST to a non-jobs path is refused
  - a GET outside `/wday/cxs/` on a Workday host is refused
  - POST passes the rate limiter and the size cap
  - a robots.txt disallow stops the request with the plain message
  Verify with `uv run pytest -q tests/jobs` and then `uv run pytest -q`. Change nothing else.

- [ ] JOB-27: Fetch Workday jobs
  Edit `src/whyline/jobs/fetch.py`, `tests/jobs/test_fetch.py` and add JSON fixtures under `tests/jobs/fixtures/workday/` only.
  Add `_workday(name, slug, client)` and register it in `_PARSERS`.
  1. Page through `POST .../jobs` with `{"appliedFacets": {}, "limit": 20, "offset": N, "searchText": ""}` until a page is empty, `offset >= total`, or 200 jobs have been read.
  2. Each item in `jobPostings` becomes a Posting:
     - uid `workday:<slug>:<bulletFields[0] or externalPath>`
     - title from `title`
     - location from `locationsText`
     - url `https://<host>/<site><externalPath>`
     - posted_at from `postedOn` as given (for example "Posted 3 Days Ago")
  3. For postings the JOB-10 seen store has not seen, up to 40 per company per run, GET the detail and set `text` from `jobPostingInfo.jobDescription` through `html_to_text`, plus `remote` when `jobPostingInfo.remoteType` says so. A failed detail keeps the posting with the note `Only the job title and location are available for this job.`
  4. Workday's lists carry no description, so when the 40 cap leaves postings without text, the fetch report says `<company>: N more Workday jobs will be read on the next run`.
  `board_jobs` then works for `ats = "workday"` with no other change.
  Tests:
  - two list pages and the stop on an empty page
  - the 200 cap
  - detail text reaches the posting
  - the 40-detail cap and its report line
  - a failed detail keeps the posting with the note
  - already-seen jobs get no detail request (assert on the stub)
  - a malformed list response gives a FetchError naming the company
  Verify with `uv run pytest -q tests/jobs` and then `uv run pytest -q`. Change nothing else.

- [ ] JOB-28: Find a company's Workday board
  Edit `src/whyline/jobs/ats.py`, `src/whyline/jobs/companies.py`, `src/whyline/console/jobs_screens.py` and their tests only.
  `ats.detect`:
  1. When `careers_url` is itself a Workday URL, probe its `/jobs` endpoint with `limit: 1`. A valid `jobPostings` list records `ats = "workday"` and the slug.
  2. Otherwise, after the existing board probes fail and before falling back to `careers_page`, fetch the careers page once (robots.txt respected, same rules as JOB-18). Collect myworkdayjobs.com links from its `href`s and inline scripts, follow at most one same-host redirect, and probe each distinct Workday slug found (at most 3). The first valid one wins.
  3. A careers page that is not reachable or names no Workday board falls through to the current `careers_page` or `unknown` result.
  `companies.suggest`: the prompt asks for `careers_url` to be the page where the company's jobs are listed, and to use a `myworkdayjobs.com`, Greenhouse or Lever link when the company uses one. Detection still verifies every URL, so a wrong link only ends as `unknown`.
  Console: a company row with board `unknown` or `careers_page` shows, in the JOB-25 reason line, `No board found. If the company's job search is on myworkdayjobs.com, paste that link with Add company… and the same name.` `companies.add` already updates an existing company's URL and accepts it. Check that it resets `ats` and `slug` and that the next Check boards picks up Workday.
  Tests:
  - a direct Workday careers_url is detected
  - a careers page linking to a Workday board is detected, and a link on a look-alike host is ignored
  - no Workday link falls through to careers_page
  - at most 3 Workday probes
  - robots.txt disallowing the careers page stops the scan
  - the suggest prompt mentions myworkdayjobs.com
  - re-adding a company with a Workday link from the console then checking it records workday
  Verify with `uv run pytest -q tests/jobs tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] JOB-29: Docs for part 4
  Edit `docs/job-search.md` only.
  - CV: list the four formats. Say that `.docx` usually gives the cleanest text, that a scanned PDF has no text to read and is refused, and that a pasted path may keep its quotes from Finder's Copy as Pathname.
  - Companies: ticking rows, Accept all suggested, and that suggested companies are never fetched until accepted.
  - Boards: add Workday to the list of boards read. Say how whyline finds a Workday board, how to paste a Workday link when it doesn't, and that whyline respects each Workday host's robots.txt and reads at most 40 new job descriptions per company per run.
  Verify with `uv run pytest -q`. Change nothing else.

## Later, not in this plan

- Other enterprise job systems (Oracle Recruiting Cloud, SAP SuccessFactors, Eightfold, Phenom). Add one at a time, after Workday shows how many companies on real lists still end as `unknown`.
