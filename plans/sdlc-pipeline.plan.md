<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-01T18:00:00+05:30 -->
# Plan as an agentic SDLC pipeline, with a reviewable document set

Runs after `plans/safe-pause.plan.md` (after `plans/relay-chat.plan.md`, after `plans/relay-tooling.plan.md`) and before `plans/job-search-5.plan.md`. Design: `docs/superpowers/specs/2026-11-01-agentic-sdlc-pipeline-design.md`. Read it before any task. This plan replaces PFB-1..5, which were dropped from `plans/relay-tooling.plan.md`. It needs whyline-relay 0.2.41 with RDOC-1..3 (`~/whyline-relay/plans/documents.plan.md`), which SDLC-1 checks.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

What the user gets:
- Relay → **Plan** starts one pipeline from a description, a brainstorm or a document they already have, sized **Small**, **Feature** or **Large**, in **Human in the loop** or **Auto** mode.
- Each run writes a versioned document set in `docs/sdlc/<slug>/`:
  - brainstorm, PRD, spec or design doc, decision records, build record, review log and history
  - the plan and test plan stay in `plans/`
- In Human in the loop, the pipeline stops after every document with **Approve**, **Ask for changes**, **Edit**, **Stop here** and **Run the rest on Auto**.
- A **Docs** screen (library and review screen in one), a **Docs** tab in the Files pane, and **Export pack** to Word and PDF for a senior developer or architect.
- `whyline docs …` on the command line, calling the same functions.
- Every document gets a **fresh-eyes review** before approval (GFR-1..6). Separate read-only reviewer agents, which never saw the drafting, check it through lenses such as "too much?", "clear to a newcomer?", "fits the code?" and "ready to build?". Findings are 🔴 Blocker, 🟡 Major or 🟢 Nit. Auto approves only with no Blockers, after at most 2 rounds of changes, and otherwise stops for you. The idea comes from Google's Elephant-Goldfish Model (github.com/google/elephant-goldfish-model, Apache-2.0).

Rules every task keeps:
- Console first: every console action saves through the same function the CLI calls.
- No new dependency. Word and PDF reuse `whyline.agents.docx` and `whyline.ideas.documents`. PDF and Word reading reuse the readers in `whyline.jobs.profile`.
- New non-widget code goes in `src/whyline/sdlc/`, with tests in `tests/sdlc/`. Console code goes in the files a task names, with tests in `tests/console/`.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- Tests never run a real agent, open a real picker or editor, start a relay, or contain "/Users/". Agents are stubbed at the `relay_ops` boundary.
- Never commit on a relay branch while that relay runs. Every function that commits or drafts calls the SDLC-11 guard first.

## Part 1: Ready

- [x] SDLC-1: Install whyline-relay with RDOC-1..3
  relay-profile: release
  In `~/whyline-relay`, `plans/documents.plan.md` (RDOC-1..3) is implemented and released as 0.2.41 or later, and `uv tool upgrade whyline-relay` shows it. If not, stop here and do that first.

- [x] SDLC-2: Raise the whyline-relay floor to 0.2.41
  Edit `pyproject.toml`, `uv.lock` and `tests/test_dependencies.py` (create it if it is missing) only.
  1. Set `whyline-relay>=0.2.41,<0.3` and run `uv lock`.
  2. Add a test that imports `whyline_relay.documents` and checks it has `draft`, `revise_text`, `discard` and `DocKind`.
  Change nothing else.

- [ ] SDLC-3: Remove Test planner from Chat Brainstorm
  Edit `src/whyline/console/tui.py`, `src/whyline/console/relay_screens.py` and `tests/console/` only.
  1. `brainstorm_field_widgets` gets a keyword `with_test_planner: bool`. The Chat `BrainstormScreen` passes False, and the Plan dialog passes True.
  2. With False, the Test planner row and its tip aren't composed and `_save_test_planner` is never called. The sync with `#rp-test-planner` (relay_screens.py, near the `bs-test-planner` handler) only runs when the field exists.
  3. Add one line under Final write-up: `The test plan and test cases are written when you make a plan from this brainstorm (Relay → Plan).`
  Tests:
  - the Chat screen has no `#bs-test-planner`
  - starting a chat brainstorm leaves the saved planner agents unchanged
  - the Plan dialog still has the field

## Part 2: The document set (no widgets)

- [ ] SDLC-4: The document set manifest
  Create `src/whyline/sdlc/__init__.py`, `src/whyline/sdlc/docset.py` and `tests/sdlc/test_docset.py`.
  1. `Size` is small, feature or large. `Mode` is human or auto. `Status` is draft, in_review, changes_requested, approved, out_of_date or superseded. Each has a display label, for example "Human in the loop", "In review" and "Out of date".
  2. `documents_for(size, brainstorm_first: bool) -> list[str]`, with kinds from the design's table:
     - small: `spec`, `plan`, `build-record`. Small's spec uses the short-spec template.
     - feature: `prd`, `spec`, `plan`, `build-record`, with `brainstorm` first when `brainstorm_first` is set
     - large: `brainstorm`, `prd`, `design`, `plan`, `build-record`
     - `plan` stands for the plan and its test plan together.
  3. `create(root, name, size, mode, *, brainstorm_first=False, build=True, roles: dict) -> DocSet`:
     - It writes `docs/sdlc/<slug>/docset.json`. The slug comes from the existing slug helper used for plans. When the folder exists, it adds `-2`, `-3` and so on.
     - Fields: schema 1, name, slug, size, mode, build, roles, created, and `documents`, a list of `{kind, path, status, version, written_by, reviewed_by, approved_by, approved_at, upstream: {kind: sha256}}`.
     - A plan's path is `plans/<slug>.plan.md`. Every other kind's path is `docs/sdlc/<slug>/<kind>.md`.
  4. `load(root, slug)`, `save(root, docset)` (atomic, through `whyline.state.atomic_write_json`) and `all_sets(root)`.
  Tests: each size's documents, slug clashes, a save/load round trip, and a missing or corrupt `docset.json`, which gives a plain error and no crash.

- [ ] SDLC-5: Versions, history and the review log
  Edit `src/whyline/sdlc/docset.py` and its tests only.
  1. `add_version(root, docset, kind, text, *, author, note) -> int`:
     - It writes the document's file.
     - It copies the text to `history/<kind>-v<N>.md`.
     - It bumps `version`, sets the status to in_review, saves, and returns N.
     - The plan kind writes no file in `plans/` here. Its history copy is the review copy until approval.
  2. `log_review(root, docset, kind, *, actor, action, comment="", section="", changed_sections=())` appends one entry to `review-log.md`:
     - a `### <date> · <kind> v<N> · <action> · <actor>` heading
     - then the comment, the section, and `Changed: …`
  3. `approve(root, docset, kind, *, approver)`:
     - It sets approved, `approved_by` and `approved_at`.
     - It records `upstream` as the sha256 of each approved document before this one in `documents_for` order.
     - It logs the review and saves.
  4. `commit(root, docset, message)` stages only `docs/sdlc/<slug>/` (plus the plan and tests paths when they exist) and commits. It returns False and commits nothing when nothing changed.
  Tests: version numbers and history files, log entries, upstream hashes, and that a commit touches only the set's paths. Use a temporary git repository.

- [ ] SDLC-6: Headers and index.md
  Edit `src/whyline/sdlc/docset.py` and its tests only.
  1. `render_header(docset, kind) -> str` builds the block between `<!-- docset-header -->` and `<!-- /docset-header -->`. It shows status, version, written by, reviewed by, approved by and when, and links to the documents before and after it (relative paths).
  2. `apply_header(text, header) -> str` replaces an existing block or puts one at the top. Text outside the block is never touched. Plan and test plan files never get a header.
  3. `render_index(docset) -> str`, written as `index.md`:
     - name, size, mode
     - a table of the documents with their status, version and approval
     - links to the plan and test plan
  4. Every function in docset.py that changes a status rewrites the affected headers and `index.md`.
  Tests: a header round trip that leaves the body byte-identical, the plan getting no header, and index content.

- [ ] SDLC-7: Out of date
  Edit `src/whyline/sdlc/docset.py` and its tests only.
  1. `refresh_out_of_date(root, docset) -> list[tuple[str, str]]`. When the file of a document named in an approved document's `upstream` now has a different sha256, that approved document becomes out_of_date. The reason reads `<Kind> changed (v<old> → v<new>) after this was approved`, or `<Kind> was edited on disk after this was approved` when the version is the same. Headers and index are not rewritten for the hash check itself, only on a status change.
  2. A document that is out_of_date goes back to approved when its upstream hashes match again.
  Tests: a PRD re-approval marks the spec, an edit on disk marks it, and a revert clears it.

- [ ] SDLC-8: Built-in templates
  Create `src/whyline/sdlc/templates/{prd,spec,short-spec,design,build-record}.md`, `src/whyline/sdlc/templates.py` and its tests.
  1. Each template is the section list from the design, as `##` headings, each with one line saying what goes there. Each starts with the rule: `Fill every section. Write "Not applicable — <reason>" rather than dropping one. No filler.`
  2. `template_for(root, kind, size) -> str`:
     - The spec kind uses short-spec for small.
     - It reads `.whyline/sdlc/templates/<name>.md` when that exists, or else the built-in one.
  3. `sections(text) -> list[str]` returns the `##` headings, used by the section picker and by "Also changed".
  Tests: every kind resolves, an override wins, the built-ins are included in the wheel (check `importlib.resources`), and `sections` ignores headings inside fenced code.

- [ ] SDLC-9: Import a file as version 1
  Create `src/whyline/sdlc/importer.py` and its tests.
  1. `read_source(path) -> str`:
     - `.md` and `.txt` as text
     - `.pdf` and `.docx` through the readers in `whyline.jobs.profile` (make them importable without a leading underscore if needed, keeping the old names as aliases)
     - It refuses other types, an empty result, or more than 2 MB of text, with a plain message.
  2. `import_as(root, docset, kind, path, *, actor)` calls `add_version` with the text and the note `imported from <file name>`, then `log_review` with action `imported`.
  3. `import_brainstorm(root, docset, path)` is the same for the `brainstorm` kind. A file already in `docs/brainstorm/` keeps its place and is copied into the set.
  Tests: each file type (small fixtures), each refusal, and the log entry.

## Part 3: Running the pipeline (no widgets)

- [ ] SDLC-10: Stages for a set
  Create `src/whyline/sdlc/stages.py` and its tests.
  1. `plan_stages(size, start, *, brainstorm_first, build) -> list[Stage]`:
     - `start` is description, brainstorm, prd or spec.
     - Each `Stage` has its kind, whether it is skipped, and the reason (for example "starting from a brainstorm").
     - Large adds a `design-review` stage after design.
     - `build` adds implement, test, review and release (shown, run by the relay) and then build-record.
  2. `next_stage(docset) -> Stage | None` is the first stage that isn't skipped and isn't approved.
  3. `stages_line(stages, roles) -> str` returns the design's line, for example `PRD (claude, reviewed by codex) → Spec (claude) → …`, with `—` and the reason for each skipped stage.
  Tests: each size × start, the Large design review, build on and off, and the exact line for the design's example.

- [ ] SDLC-11: One drafter at a time, and nothing while a relay runs
  Create `src/whyline/sdlc/guard.py` and its tests.
  1. `check(root) -> str | None` returns a plain refusal when a relay is running in the repository (`whyline_relay.running.live(root)`). When the relay's state shows it paused, the text says to finish or stop it first. It returns None otherwise.
  2. `drafting(root)` is a context manager that holds `.whyline/sdlc/drafting.lock`, with the pid inside, and refuses with "Another document is being written (<set>, <kind>)". A lock whose pid is dead is taken over.
  Tests: a running stub refuses, a held lock refuses, and a stale lock is taken.

- [ ] SDLC-12: Document drafting through whyline-relay
  Edit `src/whyline/console/relay_ops.py` and `tests/console/test_relay_ops.py` only.
  1. `draft_document(root, kind_name, request, *, template, attachments, progress) -> Draft` calls `whyline_relay.documents.draft` with the matching `DocKind`:
     - `prd` and `design` use the RDOC kinds.
     - `spec` uses the spec kind.
     - `build-record` uses the RDOC build-record kind.
  2. `revise_document_text(root, kind_name, text, feedback, *, template, attachments, progress) -> Draft` calls `documents.revise_text`.
  3. `discard_document(root, kind_name)`.
  4. Questions surface as the existing `Outcome("questions", …)` shape that plan_job uses.
  Tests with a stubbed `whyline_relay.documents`: each kind maps to the right DocKind, and the template and attachments are passed.

- [ ] SDLC-13: Run a document stage
  Create `src/whyline/sdlc/runner.py` and its tests.
  1. `run_stage(root, docset, stage, *, progress) -> StageResult` (done, questions or error), under `guard.check` and `guard.drafting`:
     - **brainstorm**: `adapters.run_brainstorm` with the set's brainstorm roles. The final synthesis is added as a version.
     - **prd, spec, design, build-record**: `relay_ops.draft_document`. The request is the set's description. The template comes from `template_for`. Attachments are the approved documents before it, plus the brainstorm when there is one. The draft is added as a version, and the relay checkpoint is discarded.
     - **design-review**: GFR-3 runs this stage as a fresh-eyes review by the architect reviewer. Until GFR-3, `run_stage` returns done for it and changes nothing.
  2. `StageResult.questions` carries open questions. The set's status for that document becomes in_review, with the questions saved in `docset.json` under `pending_questions`.
  3. The set records `stage` and `started_at` in `docset.json` while running, so a crash leaves it resumable.
  Tests: each stage kind with stubs, questions, the guard refusing, and the checkpoint being discarded after a draft.

- [ ] SDLC-14: Run the plan and test plan stage
  Edit `src/whyline/sdlc/runner.py` and its tests only.
  1. The plan stage calls `relay_ops.draft_plan(..., spec=<approved spec or design path>)` with the Test planner set from the set's roles. The plan draft and its test plan draft are added as one version. The plan text goes in `history/plan-v<N>.md` and the tests in `history/plan-v<N>.tests.md`.
  2. A revision of the plan uses `revise_document_text` with the plan kind, and keeps the test plan in step (RDOC-2 runs the tests stage on revise_text).
  3. Approving the plan writes `plans/<slug>.plan.md` and `plans/<slug>.tests.md` through the existing `relay_ops._approve_marked` path, with `spec:` in the marker pointing at the approved spec or design.
  Tests: the plan and tests versions, approval writing both files with a valid marker, and `testplan.validate` passing on the stubbed output.

- [ ] SDLC-15: Review actions
  Create `src/whyline/sdlc/review.py` and its tests. Every action calls `guard.check` first.
  1. `approve(root, slug, kind, *, approver)` approves, commits (`docs: approve <Kind> v<N> for <name>`), runs `refresh_out_of_date`, and returns the next stage.
  2. `ask_for_changes(root, slug, kind, comments, *, section="", progress)`:
     - It logs `changes requested`.
     - It calls `revise_document_text` with the current version. With a section, it adds "Change only the section '<section>' unless the comments say otherwise."
     - It adds the result as a version.
     - It compares `sections()` content before and after and logs `changed_sections`.
     - It returns any section that changed beyond the one asked for.
  3. `edited(root, slug, kind, *, editor_name)`: when the file differs from the last version, it adds it as a version with the note `edited by <name>`.
  4. `redo(root, slug, kind, *, progress)` is ask_for_changes with "Update this to match <upstream> v<N>. Change only what that change needs."
  5. `answer_questions(root, slug, kind, answers, *, progress)` reuses `relay_ops.question_feedback` and ask_for_changes.
  6. `stop(root, slug)` clears `stage` and leaves everything else.
  Tests: each action, including "Also changed" and the guard refusing.

- [ ] SDLC-16: Auto mode and switching modes
  Edit `src/whyline/sdlc/runner.py`, `src/whyline/sdlc/review.py` and their tests only.
  1. `run(root, slug, *, progress, cancel_event, launcher)` loops over `next_stage`:
     - In auto mode, each finished document is approved by its reviewer agent (`approver="<agent> (Auto)"`), with the reviewer's last review text logged.
     - In human mode, it returns after the first finished stage, waiting for review.
     - Questions stop it in either mode.
  2. `set_mode(root, slug, mode)` saves the mode. **Run the rest on Auto** is approve, then set_mode auto, then run. **Pause after this stage** is set_mode human, which `run` reads between stages.
  3. After the plan is approved and `build` is set, it runs Auto's final preflight and launcher. Move `_preflight_phase` and `_launch` out of `auto_run.py` into a small shared helper if they can't be called as they are, and keep `auto_run` working. It stores the launch commit as `build_base` in `docset.json`.
  Tests: a full auto run with stubs from description to launch, human mode stopping after one stage, switching mid-run, and a cancel between stages.

- [ ] GFR-1: Review lenses
  Create `src/whyline/sdlc/lenses.py`, `src/whyline/sdlc/lenses/{zoom-out,comprehension,design-critic,codebase-fit,readiness}.md`, `src/whyline/sdlc/lenses/ATTRIBUTION.md` and `tests/sdlc/test_lenses.py`.
  1. Each lens file is a short reviewer brief in plain words, adapted from the Elephant-Goldfish Model reviewer personas (not copied verbatim):
     - **zoom-out**: is anything here not needed now? Does existing code in this repository already do it? Is it over-built?
     - **comprehension**: could someone new to the project follow it? Are there undefined terms, missing steps, or two readings of one sentence?
     - **design-critic**: failure modes, data loss, security and privacy, and claims about behaviour or performance with no reason given
     - **codebase-fit**: do the files, functions and names it mentions exist, and does it match how the code works today?
     - **readiness**: could an implementer start now without making a design decision? For a plan, each task names its files and tests, is small (at most about 5 numbered steps and 4 source files), and a guard or security task has a closed Review focus list.
     Every lens tells the reviewer: you are read-only; you have not seen how this document was written; report only problems; and use exactly one line per finding, `- [blocker|major|nit] <section> — <problem> — <suggested fix>`, or the single line `No findings.`
  2. `ATTRIBUTION.md` names the source (github.com/google/elephant-goldfish-model, commit e9e1f06, Apache-2.0) and says the texts are adapted.
  3. `lenses_for(size, kind) -> list[str]`:
     - small: spec gets zoom-out and readiness; plan gets readiness
     - feature: brainstorm gets zoom-out; prd gets zoom-out and comprehension; spec gets comprehension, codebase-fit and design-critic; plan gets readiness and zoom-out
     - large: brainstorm gets zoom-out; prd gets zoom-out and comprehension; design gets all five; plan gets readiness, zoom-out and codebase-fit
     - build-record gets none (GFR-4 covers it)
  4. `lens_text(root, name) -> str` reads `.whyline/sdlc/lenses/<name>.md` when it exists, or else the built-in one, like `template_for`.
  5. `Finding(lens, severity, section, problem, fix)` and `parse_findings(lens, text) -> list[Finding] | None`. It returns None when the text has neither a finding line nor `No findings.` It ignores other lines and lines inside fenced code.
  Tests: each size × kind, an override winning, the built-ins in the wheel (`importlib.resources`), parsing all three severities, `No findings.` giving [], and chatter-only text giving None.
  Review focus (closed): the table in 3 and the parser in 5. Anything else goes in a follow-up note, not this task.

- [ ] GFR-2: Run a fresh-eyes review
  Create `src/whyline/sdlc/goldfish.py` and `tests/sdlc/test_goldfish.py`. Make the helpers it needs in `src/whyline/relaychat/ask.py` public (keep the old names as aliases). Do not copy them.
  1. `review_document(root, docset, kind, *, agent, progress, cancel_event=None, run_fn=None) -> Review` runs every lens in `lenses_for(docset.size, kind)` under `guard.check` and `guard.drafting`.
  2. Each lens is its own new agent process, run the way `relaychat.ask.ask` runs one: the read-only command from `whyline.agents.capabilities.read_only_command`, `whyline_relay.agents.run`, a new temporary folder, and no `--resume`. The prompt holds only:
     - the lens text
     - the document's path and version
     - the paths of the approved documents before it
     - the line "Read code in this repository when the document names it."
     It never holds the set's request, the drafting conversation, the review log or earlier reviews.
  3. `agent` must have a read-only mode (`relaychat.agent_choice.choices`). When it is the document's writer and another read-only agent is installed, use that other agent instead. When none is installed, the report says `Reviewed by the writer (no other read-only agent installed).`
  4. A lens that fails, times out, is cancelled by its read-only rules twice, or returns text `parse_findings` can't read is retried once. After that it is listed as not run. It never counts as zero findings.
  5. The function writes `docs/sdlc/<slug>/reviews/<kind>-v<N>.md`:
     - a first line `Blockers: <n> · Major: <n> · Nits: <n> · Not run: <lenses or none> · Reviewer: <agent>`
     - the findings grouped by severity, with exact duplicates (same section and problem, ignoring case) merged and their lens names joined
     It then calls `log_review` with action `fresh review` and that first line as the comment.
  6. `Review(path, findings, not_run, agent)`, and `latest_review(root, docset, kind) -> Review | None` reads the newest report back.
  Tests with a stubbed `run_fn`: the prompt has the document path and no request text or earlier review, one process per lens, the retry then not run, the report's first line and grouping, the writer swap, and `guard.check` refusing.
  Review focus (closed): prompt isolation in 2 and the not-run rule in 4. Anything else goes in a follow-up note, not this task.

- [ ] GFR-3: Review gate in the pipeline
  Edit `src/whyline/sdlc/runner.py`, `src/whyline/sdlc/review.py` and their tests only.
  1. After each document stage finishes (brainstorm, prd, spec, design, plan), `run` calls `goldfish.review_document` with the set's Reviewer agent. The **design-review** stage is a review of the approved design with the Architect reviewer agent, using all five lenses.
  2. `gate(review) -> str` returns `pass` (no Blocker and nothing not run), `fix` (one or more Blockers) or `stop` (a lens not run).
  3. In auto mode:
     - `pass` approves with `approver="<agent> (Auto, fresh review)"`.
     - `fix` calls `ask_for_changes` with each Blocker and Major as `<section>: <problem> — <fix>`, then reviews again. `MAX_FIX_ROUNDS = 2`. After that it stops waiting for review, with `Still has blockers after 2 rounds of changes`.
     - `stop` stops waiting for review, with `A reviewer didn't run: <lenses>`.
     Majors and Nits alone never block.
  4. In human mode, the review runs before `run` returns, so the findings are there when Docs opens. Approving with Blockers still works, and the review log records `approved with <n> blockers`.
  5. `review.review_again(root, slug, kind, *, progress)` runs `review_document` on the current version.
  Tests: auto pass, a fix round that clears, two fix rounds that stop, a not-run stop, human mode returning with the review, the design-review stage using the architect agent, and approve-with-blockers logging.
  Review focus (closed): the round limit and the three gate outcomes. Anything else goes in a follow-up note, not this task.

- [ ] SDLC-17: The build record and decisions.md
  Create `src/whyline/sdlc/record.py` and its tests. Edit `src/whyline/console/tui.py` only where the console notices the relay finishing a plan.
  1. `build_inputs(root, docset) -> Path` writes `docs/sdlc/<slug>/build-inputs.md`:
     - `git log --oneline <build_base>..HEAD`
     - the test plan's scenarios with passed or failed status
     - `whyline decisions` entries for the plan's task ids
     - the release tag, when one was made since `build_base`
  2. `render_decisions(root, docset) -> str` writes `decisions.md`:
     - the design's Decision records section, when there is one
     - then every whyline decision for the set's slug or its plan's task ids, newest last
     It is regenerated on every approval and after the build.
  3. When the relay finishes a plan that belongs to a set, the console runs the build-record stage, with `build-inputs.md` attached. In auto mode it is approved by the reviewer agent. In human mode it waits in Docs.
  Tests: inputs from a temporary repository, decisions content, and the console hook calling the stage once.

- [ ] GFR-4: Drift check in the build record
  Edit `src/whyline/sdlc/record.py`, `src/whyline/sdlc/templates/build-record.md` and their tests only.
  1. `drift_review(root, docset, *, agent, progress, run_fn=None) -> Path` runs the codebase-fit lens once, the GFR-2 way, on the approved spec or design. It adds `git diff --stat <build_base>..HEAD` and the line "Compare what the document promised with what was built. A finding is something promised and not built, or built and not in the document." It writes `docs/sdlc/<slug>/reviews/drift.md`.
  2. The build-record stage attaches `drift.md` next to `build-inputs.md`. The template gains a `## Drift from the spec` section.
  3. When the lens doesn't run, the build record still gets written, and its section says `Drift check didn't run: <reason>`.
  Tests: the prompt has the diff stat and the spec path, the attachment, and the not-run text.
  Review focus (closed): 3. Anything else goes in a follow-up note, not this task.

## Part 4: Library, export and CLI (no widgets)

- [ ] SDLC-18: The library
  Create `src/whyline/sdlc/library.py` and its tests.
  1. `sets(root) -> list[SetSummary]`, newest first, each with a one-line summary such as `Job search 5 · Feature · PRD ✓ · Spec ✓ · Plan ✓ · Built ⏳`.
  2. `earlier_plans(root) -> list[EarlierPlan]`: every plan in `plans/` and `plans/done/` that no set owns. Each comes with its test plan, and with the spec or brainstorm its marker line names when that file exists.
  Tests: mixed sets and earlier plans, a plan in `plans/done/`, and a marker whose spec is missing.

- [ ] SDLC-19: Export pack
  Create `src/whyline/sdlc/export.py` and its tests.
  1. `export_pack(root, slug, out_dir) -> ExportResult`:
     - It builds one Markdown: a cover from `index.md`, each document in order without its header block, the plan, the test plan, and `review-log.md` as an appendix titled "Review log".
     - It writes `<slug>-docs.docx` through `whyline.agents.convert.to_docx`, and `<slug>-docs.pdf` through the PDF path in `whyline.ideas.documents`.
     - `ExportResult` lists the files and any notes (for example, PDF not available).
  2. The default `out_dir` is `~/Downloads`.
  Tests: content order, header blocks stripped, the PDF fallback note, and that a missing document is skipped with a note.

- [ ] SDLC-20: `whyline docs` CLI
  Create `src/whyline/sdlc/cli.py` and edit `src/whyline/cli.py` to register it. Add tests.
  Subcommands, each calling the Part 2 to 4 functions:
  - `list`
  - `show <slug> [<doc>]`
  - `start --from-description TEXT | --from-file PATH [--as brainstorm|prd|spec] [--size] [--auto] [--name]`
  - `resume <slug>`
  - `approve <slug> <doc>`
  - `change <slug> <doc> "<comments>" [--section]`
  - `redo <slug> <doc>`
  - `answer <slug> <doc> "<answers>"`
  - `mode <slug> human|auto`
  - `export <slug> [--out DIR]`
  Each prints plain lines and exits non-zero with the guard's message when refused.
  Tests: each subcommand with stubs.

- [ ] GFR-5: Review in the CLI and the export pack
  Edit `src/whyline/sdlc/cli.py`, `src/whyline/sdlc/export.py` and their tests only. The console counterpart is GFR-6.
  1. `whyline docs review <slug> <doc>` calls `review.review_again` and prints the report's first line and its path.
  2. `whyline docs findings <slug> <doc>` prints `latest_review`, one finding per line with its severity and lens, and the not-run lenses.
  3. The export pack adds an appendix "Fresh-eyes reviews" after the review log, with the latest review of each document.
  Tests: both subcommands with stubs, the guard refusal exiting non-zero, and the appendix order.

## Part 5: Console

- [ ] SDLC-21: The Plan form
  Edit `src/whyline/console/relay_screens.py` and its tests only.
  1. Sources become two: **New plan** (default) and **I have a plan already**, which is unchanged.
  2. New plan shows:
     - **Start from**: a description (text area and attachments as today), a brainstorm (select from `docs/brainstorm/` newest first), or a document (PRD or spec, through **Choose file…**)
     - **Choose file…** next to the brainstorm select and the document choice. It uses `mac_input.pick_files` in a thread worker through an injectable `pick_files_fn`.
     - **Name**
     - **Size**: Small, Feature or Large, default Feature, each with a one-line hint
     - **Brainstorm first**, for Feature only
     - **Mode**: Human in the loop or Auto
     - **Build when the plan is approved**, default on, always on in Auto
     - roles: Writer, Reviewer, Test planner, plus Architect reviewer for Large, plus the execution roles when building
  3. An Auto checkpoint saved before this release still shows **Resume** through the existing auto_run path. The form no longer starts the old Auto.
  Tests: each field's visibility by size, start and mode, the picker stub selecting a file, and the old Auto checkpoint still offering Resume.

- [ ] SDLC-22: The Stages line
  Edit `src/whyline/console/relay_screens.py` and its tests only.
  `#rp-stages` under the roles shows `stages.stages_line(...)` and updates on every change to start, size, brainstorm first, build, mode or roles. Under it, one sentence: `The test plan lists test cases for each task: automatic ones the tester runs, and manual checks the relay pauses for.`
  Tests: the line for each size, and its update when a role changes.

- [ ] SDLC-23: Start
  Edit `src/whyline/console/relay_screens.py`, `src/whyline/console/tui.py` and their tests only.
  **Start**:
  1. calls `guard.check` and shows a refusal in `#rp-error`
  2. creates the set, importing a chosen file as its kind
  3. closes the dialog
  4. runs `runner.run` in a thread worker, with progress in the busy line, for example `docs: Job search 5 · writing PRD · claude · 2m 10s`
  When it returns waiting for review or with questions, the console opens Docs on that document.
  Tests with a stubbed runner: the busy line text, Docs opening on the right document, and a refusal.

- [ ] SDLC-24: The Docs screen
  Create `src/whyline/console/docs_screen.py` and its tests. Edit `src/whyline/console/tui.py` to add a **Docs** button in Relay mode.
  1. The layout follows the design:
     - **left**: sets and Earlier plans from `library`
     - **middle**: the selected set's documents with status, version and approval
     - **right**: the selected document rendered as Markdown
  2. Out-of-date documents show the reason under their row.
  3. The screen opens on a given set and document, which SDLC-23 uses.
  4. While `guard.check` refuses, every action button except History and Export is disabled, and the reason shows at the top.
  Tests: the listing, selecting a document, the out-of-date reason, and read-only while a relay runs.

- [ ] SDLC-25: Review actions in Docs
  Edit `src/whyline/console/docs_screen.py` and its tests only.
  1. **Approve**, **Ask for changes**, **Edit**, **Redo**, **Answer questions**, **Stop here**, **Run the rest on Auto** and **Resume** show only when they apply.
  2. Each calls the matching `review` or `runner` function in a thread worker.
  3. **Ask for changes** opens a small form: a comments text area, and a section select from `templates.sections`, with "Whole document" first.
  4. **Edit** opens the file through the console's existing editor opening. When the console regains focus or the user presses **I've finished editing**, it calls `review.edited`.
  5. After a revision, an `Also changed: …` line shows when it applies.
  6. **Approve** on a human-mode set continues the pipeline with `runner.run`.
  Tests: each action with stubs, the section list, and the Also changed line.

- [ ] GFR-6: Findings in Docs
  Edit `src/whyline/console/docs_screen.py` and its tests only.
  1. Under the selected document, a **Findings** panel shows `latest_review`: the first line, then the findings grouped 🔴 Blocker, 🟡 Major, 🟢 Nit, each with its section and lens, and any not-run lenses. With no review, it says `Not reviewed yet.`
  2. **Review again** calls `review.review_again` in a thread worker. It is disabled while `guard.check` refuses, like the other actions.
  3. The **Ask for changes** form gets a findings checklist, with Blockers and Majors ticked by default. Ticked findings are added to the comments as `<section>: <problem> — <fix>`.
  4. The middle list shows the counts after each document's status, for example `Spec v3 · In review · 🔴 1 🟡 2`.
  Tests: the panel with and without a review, the checklist adding ticked findings, the counts, and Review again with a stub.

- [ ] SDLC-26: History in Docs
  Edit `src/whyline/console/docs_screen.py` and its tests only.
  **History** shows the document's versions and its `review-log.md` entries. Picking two versions shows a unified diff (difflib), and one version shows its text.
  Tests: versions listed and a diff between v1 and v2.

- [ ] SDLC-27: Docs tab in the Files pane, and Export in Docs
  Edit `src/whyline/console/tui.py`, `src/whyline/console/file_pane.py`, `src/whyline/console/docs_screen.py` and their tests only.
  1. A **Docs** button sits in the Files pane next to **Plan**. It shows the set that owns the active plan (`file_pane.active_plan_file`): each document's status, and the selected one's text. It is read-only. **Open in Docs** opens the screen. With no owning set, it says `This plan has no document set.`
  2. **Export pack** in Docs calls `export.export_pack`, shows the files and notes, and offers **Reveal in Finder**.
  Tests: the tab with and without a set, and export with a stub.

- [ ] SDLC-28: Pause after this stage
  Edit `src/whyline/console/tui.py` and its tests only.
  While an Auto pipeline runs, the busy line shows **Pause after this stage**, which calls `runner.set_mode(..., "human")`. The line then reads `docs: … · will pause after PRD`.
  Tests: the button, and that the mode is saved.

## Part 6: Docs and release

- [ ] SDLC-29: Docs
  Edit `README.md` where it describes Plan, Auto or Brainstorm, `docs/` pages that describe Plan and Brainstorm, and create `docs/sdlc.md`.
  Cover:
  - the pipeline, sizes and modes
  - the document set and its templates
  - review at each stop, out of date, and the Docs screen
  - Export pack, the `whyline docs` commands, and template overrides
  - fresh-eyes review: the lenses, the Auto gate and its 2-round limit, lens overrides in `.whyline/sdlc/lenses/`, the drift check, and credit to the Elephant-Goldfish Model
  - that Test planner belongs to Plan, not Chat Brainstorm
  Verify with `uv run pytest -q`.

- [ ] SDLC-30: Publish whyline with SDLC-1..29 and GFR-1..6
  relay-profile: release
  Bump the version in `pyproject.toml`, `src/whyline/__init__.py` and `uv.lock` to the next patch version. Write `docs/releases/v<version>.md` from every task since the previous release (`git log v<previous>..HEAD`), in user terms. Run `uv run pytest -q` with the agent CLIs off PATH and `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1`, and again on Python 3.11. Push, wait for green CI on Linux and macOS, then tag `v<version>`, push the tag and let the release workflow publish to PyPI. Afterwards run `uv tool upgrade whyline` and confirm `whyline --version`.
