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
- **One product PRD** at `docs/product/prd.md`, versioned v1.0, v1.1, v1.2… A new project writes it. A Feature or Large run updates only the sections that feature changes, as the next version, or records `No PRD change: <reason>`. Small never touches it. Specs, designs and plans stay per feature (PRD-1..3).
- Documents live on the default branch, in a docs checkout (WTD-1), never on a relay branch. You can write and review the next feature while a relay builds.
- Every requirement can be traced to the tasks that build it, the tests that check it, and their results (TRC-1..2). Plan changes during a build are recorded as plan versions (LIFE-1). A finished feature is closed out: plan moved to `plans/done/`, set marked Released, and an optional pull request (LIFE-2..3).
- Every document gets a **fresh-eyes review** before approval (GFR-1..6). Separate read-only reviewer agents, which never saw the drafting, check it through lenses such as "too much?", "clear to a newcomer?", "fits the code?" and "ready to build?". Findings are 🔴 Blocker, 🟡 Major or 🟢 Nit. Auto approves only with no Blockers, after at most 2 rounds of changes, and otherwise stops for you. The idea comes from Google's Elephant-Goldfish Model (github.com/google/elephant-goldfish-model, Apache-2.0).
- **Project home** for a new project (HOME-1..6, added 2026-11-08). After the brainstorm, the pipeline stops once in both modes and asks where the project lives:
  - **Create a new folder**: the agent suggests 2 or 3 names, you pick one or type your own, and choose the parent folder. Whyline creates the folder, runs `git init`, sets up whyline, adds a README and `.gitignore`, moves the document set there and makes the first commits.
  - **Use this repository**: the default when the current repository has no code yet.
  - Optionally, **Create GitHub repository**: private by default, with Public as a choice. It runs only after you confirm what it will create and push.
  - The console then switches to the new project, and the rest of the pipeline (PRD, design, plan, build) runs there.

Rules every task keeps:
- Console first: every console action saves through the same function the CLI calls.
- No new dependency. Word and PDF reuse `whyline.agents.docx` and `whyline.ideas.documents`. PDF and Word reading reuse the readers in `whyline.jobs.profile`.
- New non-widget code goes in `src/whyline/sdlc/`, with tests in `tests/sdlc/`. Console code goes in the files a task names, with tests in `tests/console/`.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- Tests never run a real agent, open a real picker or editor, start a relay, or contain "/Users/". Agents are stubbed at the `relay_ops` boundary.
- Never commit on a relay branch while that relay runs. Every function that commits or drafts calls the SDLC-11 guard first.
- Document functions take the docs checkout from `workspace.docs_root(root)` (WTD-1). Functions that read the build (git log, test plan ticks, the running plan) take the code checkout `root`.

## Part 1: Ready

- [x] SDLC-1: Install whyline-relay with RDOC-1..3
  relay-profile: release
  In `~/whyline-relay`, `plans/documents.plan.md` (RDOC-1..3) is implemented and released as 0.2.41 or later, and `uv tool upgrade whyline-relay` shows it. If not, stop here and do that first.

- [x] SDLC-2: Raise the whyline-relay floor to 0.2.41
  Edit `pyproject.toml`, `uv.lock` and `tests/test_dependencies.py` (create it if it is missing) only.
  1. Set `whyline-relay>=0.2.41,<0.3` and run `uv lock`.
  2. Add a test that imports `whyline_relay.documents` and checks it has `draft`, `revise_text`, `discard` and `DocKind`.
  Change nothing else.

- [x] SDLC-3: Remove Test planner from Chat Brainstorm
  Edit `src/whyline/console/tui.py`, `src/whyline/console/relay_screens.py` and `tests/console/` only.
  1. `brainstorm_field_widgets` gets a keyword `with_test_planner: bool`. The Chat `BrainstormScreen` passes False, and the Plan dialog passes True.
  2. With False, the Test planner row and its tip aren't composed and `_save_test_planner` is never called. The sync with `#rp-test-planner` (relay_screens.py, near the `bs-test-planner` handler) only runs when the field exists.
  3. Add one line under Final write-up: `The test plan and test cases are written when you make a plan from this brainstorm (Relay → Plan).`
  Tests:
  - the Chat screen has no `#bs-test-planner`
  - starting a chat brainstorm leaves the saved planner agents unchanged
  - the Plan dialog still has the field

## Part 2: The document set (no widgets)

- [x] SDLC-4: The document set manifest
  Create `src/whyline/sdlc/__init__.py`, `src/whyline/sdlc/docset.py` and `tests/sdlc/test_docset.py`.
  1. `Size` is small, feature or large. `Mode` is human or auto. `Status` is draft, in_review, changes_requested, approved, out_of_date or superseded. Each has a display label, for example "Human in the loop", "In review" and "Out of date".
  2. `PrdMode` is new, update or none, with the labels "New project: write the PRD", "Update the product PRD" and "No PRD change". `documents_for(size, brainstorm_first: bool, prd_mode: str) -> list[str]`, with kinds from the design's table:
     - small: `spec`, `plan`, `build-record`. Small's spec uses the short-spec template. Small has no PRD, whatever `prd_mode` says.
     - feature: `prd`, `spec`, `plan`, `build-record`, with `brainstorm` first when `brainstorm_first` is set
     - large: `brainstorm`, `prd`, `design`, `plan`, `build-record`
     - `prd` is left out when `prd_mode` is none. In update mode the `prd` document is this feature's update of the product PRD, not a new PRD (PRD-1 and PRD-2).
     - `plan` stands for the plan and its test plan together.
  3. `create(root, name, size, mode, *, brainstorm_first=False, prd_mode=None, prd_major=False, build=True, roles: dict) -> DocSet`:
     - `prd_mode=None` means update when `docs/product/prd.md` exists, and new otherwise. Small always stores none.
     - It writes `docs/sdlc/<slug>/docset.json`. The slug comes from the existing slug helper used for plans. When the folder exists, it adds `-2`, `-3` and so on.
     - Fields: schema 1, name, slug, size, mode, prd_mode, prd_major, build, roles, created, and `documents`, a list of `{kind, path, status, version, written_by, reviewed_by, approved_by, approved_at, upstream: {kind: sha256}}`.
     - A plan's path is `plans/<slug>.plan.md`. Every other kind's path is `docs/sdlc/<slug>/<kind>.md`.
  4. `load(root, slug)`, `save(root, docset)` (atomic, through `whyline.state.atomic_write_json`) and `all_sets(root)`.
  Tests: each size × prd_mode's documents, the prd_mode default with and without `docs/product/prd.md`, slug clashes, a save/load round trip, and a missing or corrupt `docset.json`, which gives a plain error and no crash.

- [x] WTD-1: Where documents live
  Create `src/whyline/sdlc/workspace.py` and `tests/sdlc/test_workspace.py`. Edit `src/whyline/worktrees.py` and its tests only to add the helper in 1.
  1. `worktrees.default_branch_worktree(root) -> Path | None` returns the path of any worktree of this repository that has the default branch checked out (`git worktree list --porcelain`), or None.
  2. `docs_root(root) -> Path`:
     - `root` itself when it is on the default branch
     - otherwise the worktree from 1
     - otherwise it creates one at `<worktrees base>/docs` with `git worktree add <path> <default branch>` (no new branch) and returns it
  3. `docs_commit(docs, paths, message) -> bool` commits only `paths` (pathspec) in `docs`. It refuses with a plain message when any of those paths has uncommitted changes that whyline didn't write, and returns False when nothing changed. It never pushes. Pushing stays with the user.
  4. `copy_plan_to(root, docs, slug) -> bool` copies `plans/<slug>.plan.md` and `plans/<slug>.tests.md` from `docs` into `root` and commits them there by pathspec. It is used before a relay launches from a checkout that is not the docs checkout.
  Tests: each case in 2 with a temporary repository and worktrees, the dirty-path refusal, pathspec-only commits, and the copy.
  Review focus (closed): 2 and the refusal in 3. Anything else goes in a follow-up note, not this task.

- [x] SDLC-5: Versions, history and the review log
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
  4. `commit(root, docset, message)` calls `workspace.docs_commit` in `docs_root(root)` with `docs/sdlc/<slug>/`, `docs/product/` when the set touched it, and the plan and tests paths when they exist. It returns False and commits nothing when nothing changed.
  Tests: version numbers and history files, log entries, upstream hashes, and that a commit touches only the set's paths. Use a temporary git repository.

- [x] SDLC-6: Headers and index.md
  Edit `src/whyline/sdlc/docset.py` and its tests only.
  1. `render_header(docset, kind) -> str` builds the block between `<!-- docset-header -->` and `<!-- /docset-header -->`. It shows status, version, written by, reviewed by, approved by and when, and links to the documents before and after it (relative paths).
  2. `apply_header(text, header) -> str` replaces an existing block or puts one at the top. Text outside the block is never touched. Plan and test plan files never get a header.
  3. `render_index(docset) -> str`, written as `index.md`:
     - name, size, mode
     - a table of the documents with their status, version and approval
     - links to the plan and test plan
  4. Every function in docset.py that changes a status rewrites the affected headers and `index.md`.
  Tests: a header round trip that leaves the body byte-identical, the plan getting no header, and index content.

- [x] SDLC-7: Out of date
  Edit `src/whyline/sdlc/docset.py` and its tests only.
  1. `refresh_out_of_date(root, docset) -> list[tuple[str, str]]`. When the file of a document named in an approved document's `upstream` now has a different sha256, that approved document becomes out_of_date. The reason reads `<Kind> changed (v<old> → v<new>) after this was approved`, or `<Kind> was edited on disk after this was approved` when the version is the same. Headers and index are not rewritten for the hash check itself, only on a status change.
  2. A document that is out_of_date goes back to approved when its upstream hashes match again.
  3. `content_hash(kind, text) -> str` is the sha256 used everywhere. For the plan and test plan it first turns every `- [x]` into `- [ ]`, so the relay ticking tasks never counts as a change.
  4. A plan or test plan path is resolved through `plan_file(docs, slug)`, which looks in `plans/` and then `plans/done/`.
  Tests: a PRD re-approval marks the spec, an edit on disk marks it, a revert clears it, ticked tasks giving the same hash, and a plan moved to `plans/done/` still found.

- [x] SDLC-8: Built-in templates
  Create `src/whyline/sdlc/templates/{prd,spec,short-spec,design,build-record}.md`, `src/whyline/sdlc/templates.py` and its tests.
  1. Each template is the section list from the design, as `##` headings, each with one line saying what goes there. Each starts with the rule: `Fill every section. Write "Not applicable — <reason>" rather than dropping one. No filler.`
  2. `template_for(root, kind, size) -> str`:
     - The spec kind uses short-spec for small.
     - It reads `.whyline/sdlc/templates/<name>.md` when that exists, or else the built-in one.
  3. `sections(text) -> list[str]` returns the `##` headings, used by the section picker and by "Also changed".
  Tests: every kind resolves, an override wins, the built-ins are included in the wheel (check `importlib.resources`), and `sections` ignores headings inside fenced code.

- [x] SDLC-9: Import a file as version 1
  Create `src/whyline/sdlc/importer.py` and its tests.
  1. `read_source(path) -> str`:
     - `.md` and `.txt` as text
     - `.pdf` and `.docx` through the readers in `whyline.jobs.profile` (make them importable without a leading underscore if needed, keeping the old names as aliases)
     - It refuses other types, an empty result, or more than 2 MB of text, with a plain message.
  2. `import_as(root, docset, kind, path, *, actor)` calls `add_version` with the text and the note `imported from <file name>`, then `log_review` with action `imported`.
  3. `import_brainstorm(root, docset, path)` is the same for the `brainstorm` kind. A file already in `docs/brainstorm/` keeps its place and is copied into the set.
  Tests: each file type (small fixtures), each refusal, and the log entry.

- [x] PRD-1: The product PRD
  Create `src/whyline/sdlc/product.py` and `tests/sdlc/test_product.py`. Edit `src/whyline/sdlc/docset.py` and its tests only where 4 and 5 say.
  1. `docs/product/` holds `prd.md`, `product.json` (schema 1, version, approved_by, approved_at, sha256, update_claim), `changelog.md` and `history/prd-v<version>.md`.
  2. `current(root) -> ProductPrd | None` returns the version (for example "1.2"), path, text and sha256. It returns None when there is no `prd.md`.
  3. Each version step:
     - `next_version(version: str | None, *, major=False) -> str` gives "1.0" first, then "1.1", "1.2", and "2.0" when major.
     - `publish(root, text, *, set_name, slug, approver, major=False) -> str` writes `prd.md` with the first line `<!-- product-prd v<version> -->`, the history copy and `product.json`, and appends a changelog line `v<version> · <date> · <set name> · changed: <sections> · approved by <approver>`. The sections come from `changed_sections`, or `all (new PRD)` for v1.0. It returns the version.
     - `changed_sections(old, new) -> list[str]` compares section text by `templates.sections` headings, in order.
     - `claim_update(root, slug)`, `release_update(root, slug)` and `claim_holder(root) -> str | None` store the one open update in `product.json`. A claim whose set no longer exists or is approved is taken over.
     - `moved(root, docset) -> bool` compares the PRD document's `based_on` with `current`.
  4. In `docset.py`, the `prd` document's upstream for later documents is `docs/product/prd.md` and its version label, not the set's draft file. Later documents record `based_on_prd`. `refresh_out_of_date` gives the reason `PRD changed (v1.2 → v1.3) after this was approved`, but only for sets with no `build_base` yet. A set that has been built keeps the PRD version it was built on and is never marked by later PRD changes.
  5. `render_header` and `render_index` show the PRD as `Product PRD v1.3 (draft 2)` while in review and `Product PRD v1.3` once approved.
  Tests: version steps, publish writing all four files, the changelog line, changed_sections ignoring untouched sections, a claim, a refusal and a stale-claim takeover, `moved`, out of date for an unbuilt set and not for a built one, and the header label.
  Review focus (closed): 3 and the built-set rule in 4. Anything else goes in a follow-up note, not this task.

## Part 3: Running the pipeline (no widgets)

- [x] SDLC-10: Stages for a set
  Create `src/whyline/sdlc/stages.py` and its tests.
  1. `plan_stages(size, start, *, brainstorm_first, build) -> list[Stage]`:
     - `start` is description, brainstorm, prd or spec.
     - The PRD stage is labelled `PRD` for new and `PRD update` for update. With none it is skipped, with the reason `no PRD change` (or `Small has no PRD`).
     - Each `Stage` has its kind, whether it is skipped, and the reason (for example "starting from a brainstorm").
     - Large adds a `design-review` stage after design.
     - `build` adds implement, test, review and release (shown, run by the relay), then build-record, then done (LIFE-2).
  2. `next_stage(docset) -> Stage | None` is the first stage that isn't skipped and isn't approved.
  3. `stages_line(stages, roles) -> str` returns the design's line, for example `PRD (claude, reviewed by codex) → Spec (claude) → …`, with `—` and the reason for each skipped stage.
  Tests: each size × start, each prd_mode, the Large design review, build on and off, and the exact line for the design's example.

- [x] SDLC-11: One drafter at a time, and no commits on a running relay's branch
  Create `src/whyline/sdlc/guard.py` and its tests.
  1. `check(root) -> str | None` returns a plain refusal only when a relay is running in the docs checkout itself (`whyline_relay.running.live(docs_root(root))`). When the relay's state shows it paused, the text says to finish or stop it first. A relay running in another checkout of the repository does not refuse: documents are written and committed in the docs checkout, with its own handoff file.
  2. `drafting(root)` is a context manager that holds `.whyline/sdlc/drafting.lock` in the docs checkout, with the pid inside, and refuses with "Another document is being written (<set>, <kind>)". A lock whose pid is dead is taken over.
  Tests: a relay running in the docs checkout refuses, a relay running in another worktree does not, a held lock refuses, and a stale lock is taken.

- [x] SDLC-12: Document drafting through whyline-relay
  Edit `src/whyline/console/relay_ops.py` and `tests/console/test_relay_ops.py` only.
  1. `draft_document(root, kind_name, request, *, template, attachments, progress) -> Draft` calls `whyline_relay.documents.draft` with the matching `DocKind`:
     - `prd` and `design` use the RDOC kinds.
     - `spec` uses the spec kind.
     - `build-record` uses the RDOC build-record kind.
  2. `revise_document_text(root, kind_name, text, feedback, *, template, attachments, progress) -> Draft` calls `documents.revise_text`.
  3. `discard_document(root, kind_name)`.
  4. Questions surface as the existing `Outcome("questions", …)` shape that plan_job uses.
  Tests with a stubbed `whyline_relay.documents`: each kind maps to the right DocKind, and the template and attachments are passed.

- [x] SDLC-13: Run a document stage
  Create `src/whyline/sdlc/runner.py` and its tests.
  1. `run_stage(root, docset, stage, *, progress) -> StageResult` (done, questions or error), under `guard.check` and `guard.drafting`:
     - **brainstorm**: `adapters.run_brainstorm` with the set's brainstorm roles. The final synthesis is added as a version.
     - **prd, new mode**: `relay_ops.draft_document` as below. When the repository has no product PRD yet but already has code, `README.md` is attached too, and the request starts "Write the product PRD for this existing project from its README and code, then cover the feature below."
     - **prd, update mode** (needs PRD-1): `product.claim_update` first. When another set holds the claim, refuse with `Another feature is updating the PRD (<set>)`. Then `relay_ops.revise_document_text` on the current product PRD text, with the feedback "Update this PRD for the feature below. Change only the sections this feature affects, and keep every other section word for word. If no section needs to change, reply with only `No PRD change: <reason>`." That reply marks the stage skipped with the reason and releases the claim. Otherwise the result is added as a version with the note `based on PRD v<current>`, and `based_on` is saved in the document entry.
     - **spec, design, build-record**: `relay_ops.draft_document`. The request is the set's description. The template comes from `template_for`. Attachments are the approved documents before it, plus the brainstorm when there is one. The draft is added as a version, and the relay checkpoint is discarded.
     - **design-review**: GFR-3 runs this stage as a fresh-eyes review by the architect reviewer. Until GFR-3, `run_stage` returns done for it and changes nothing.
  2. `StageResult.questions` carries open questions. The set's status for that document becomes in_review, with the questions saved in `docset.json` under `pending_questions`.
  3. The set records `stage` and `started_at` in `docset.json` while running, so a crash leaves it resumable.
  Tests: each stage kind with stubs, a PRD update, `No PRD change`, the claim refusing, new mode attaching README, questions, the guard refusing, and the checkpoint being discarded after a draft.

- [x] SDLC-14: Run the plan and test plan stage
  Edit `src/whyline/sdlc/runner.py` and its tests only.
  1. The plan stage calls `relay_ops.draft_plan(..., spec=<approved spec or design path>)` with the Test planner set from the set's roles. The plan draft and its test plan draft are added as one version. The plan text goes in `history/plan-v<N>.md` and the tests in `history/plan-v<N>.tests.md`.
  2. A revision of the plan uses `revise_document_text` with the plan kind, and keeps the test plan in step (RDOC-2 runs the tests stage on revise_text).
  3. Approving the plan writes `plans/<slug>.plan.md` and `plans/<slug>.tests.md` through the existing `relay_ops._approve_marked` path, with `spec:` in the marker pointing at the approved spec or design.
  Tests: the plan and tests versions, approval writing both files with a valid marker, and `testplan.validate` passing on the stubbed output.

- [x] TRC-1: Requirements in the plan and test plan
  Create `src/whyline/sdlc/trace.py` and `tests/sdlc/test_trace.py`. Edit `src/whyline/sdlc/runner.py` and its tests only where 3 says.
  1. Parsers:
     - `requirements(text) -> list[str]` returns the R-numbers (R1, R2…) in a document's Requirements or Requirements covered section.
     - `plan_covers(plan_text) -> dict[str, list[str]]` reads each task's `covers: R1, R3` detail line. `covers: none (<reason>)` gives [].
     - `test_covers(tests_text) -> dict[str, list[str]]` does the same for test cases.
  2. `coverage(docs, docset) -> Coverage` uses the requirements in scope (the approved spec's or design's Requirements covered, or the PRD's Requirements when there is no spec). It lists:
     - requirements no task covers
     - requirements no test covers
     - tasks that cover an R-number not in scope
     - tasks with no covers line
     `Coverage.line()` is, for example, `Covers 7 of 8 requirements · R5 has no test`.
  3. The plan stage's request (SDLC-14) adds: "Give every task a `covers: R<n>, …` detail line naming the requirements it builds, or `covers: none (<reason>)`. Give every test case the same line." Check that `testplan.validate` still passes with that line in a test case. If it doesn't, put the R-numbers in the test case's title as `[R3]` and make `test_covers` read that instead.
  4. A PRD update never renumbers requirements. New ones take the next free number, and a removed one stays as `R4 — removed in v<version>`. Add this to the update feedback in SDLC-13's runner code.
  Tests: each parser, coverage gaps of all four kinds, the line text, the plan request text, and the test plan staying valid.
  Review focus (closed): 2 and 3. Anything else goes in a follow-up note, not this task.

- [x] SDLC-15: Review actions
  Create `src/whyline/sdlc/review.py` and its tests. Every action calls `guard.check` first.
  1. `approve(root, slug, kind, *, approver)` approves, commits (`docs: approve <Kind> v<N> for <name>`), runs `refresh_out_of_date`, and returns the next stage.
     - For `prd` it also calls `product.publish`, which makes v1.0 in new mode, or the next minor version (the next major when `prd_major`) in update mode. The commit message names that version: `docs: PRD v1.3 for <name>`.
     - In update mode it first checks `product.moved(root, docset)`. When the product PRD changed after this draft was based on it, it refuses with `The PRD is now v<new>. Redo this update first.` and approves nothing.
  2. `ask_for_changes(root, slug, kind, comments, *, section="", progress)`:
     - It logs `changes requested`.
     - It calls `revise_document_text` with the current version. With a section, it adds "Change only the section '<section>' unless the comments say otherwise."
     - It adds the result as a version.
     - It compares `sections()` content before and after and logs `changed_sections`.
     - It returns any section that changed beyond the one asked for.
  3. `edited(root, slug, kind, *, editor_name)`: when the file differs from the last version, it adds it as a version with the note `edited by <name>`.
  4. `redo(root, slug, kind, *, progress)` is ask_for_changes with "Update this to match <upstream> v<N>. Change only what that change needs."
  5. `answer_questions(root, slug, kind, answers, *, progress)` reuses `relay_ops.question_feedback` and ask_for_changes.
  6. `stop(root, slug)` clears `stage`, releases the set's PRD claim, and leaves everything else.
  Tests: each action, including "Also changed", the guard refusing, PRD approval publishing the right version, the moved-PRD refusal, and stop releasing the claim.

- [x] SDLC-16: Auto mode and switching modes
  Edit `src/whyline/sdlc/runner.py`, `src/whyline/sdlc/review.py` and their tests only.
  1. `run(root, slug, *, progress, cancel_event, launcher)` loops over `next_stage`:
     - In auto mode, each finished document is approved by its reviewer agent (`approver="<agent> (Auto)"`), with the reviewer's last review text logged.
     - In human mode, it returns after the first finished stage, waiting for review.
     - Questions stop it in either mode.
  2. `set_mode(root, slug, mode)` saves the mode. **Run the rest on Auto** is approve, then set_mode auto, then run. **Pause after this stage** is set_mode human, which `run` reads between stages.
  3. After the plan is approved and `build` is set, it calls `workspace.copy_plan_to(root, docs, slug)` when `root` is not the docs checkout, then runs Auto's final preflight and launcher. Move `_preflight_phase` and `_launch` out of `auto_run.py` into a small shared helper if they can't be called as they are, and keep `auto_run` working. It stores the launch commit as `build_base` in `docset.json`.
  Tests: a full auto run with stubs from description to launch, human mode stopping after one stage, switching mid-run, and a cancel between stages.

- [x] HOME-1: Project names and where it goes
  Create `src/whyline/sdlc/home.py` and `tests/sdlc/test_home.py`.
  1. `folder_name(name: str) -> str`: lowercase, every run of characters other than a-z and 0-9 becomes one `-`, no `-` at either end, at most 40 characters. An empty result is `project`. "Trade Journal!" gives `trade-journal`.
  2. `suggest_names(root, docset, *, agent, run_fn=None) -> list[NameIdea]`, with `NameIdea(name, folder, reason)`:
     - It runs the set's Writer agent once, read-only, in a fresh temporary folder, through `capabilities.read_only_command` and `whyline_relay.agents.run`, the way `relaychat.ask.ask` does, with the cancelled-turn retry.
     - The prompt holds only the brainstorm's final synthesis (or the set's description when there is no brainstorm) and: `Suggest 3 short names for this project. Reply with one line each: <Name> — <why, in under 12 words>. Nothing else.`
     - It keeps the first 3 lines that parse, and at least 2. When fewer than 2 parse or the agent fails, it returns one idea from the set's name with the reason `from the plan's name`. It never raises for an agent failure.
  3. `is_fresh(root) -> bool` is True when every tracked file (`git ls-files`) is `README*`, `LICENSE*`, `.gitignore`, `.gitattributes`, or under `.whyline/`, `.claude/`, `docs/` or `plans/`. That is a repository with no code yet.
  4. `check_target(root, parent: Path, folder: str) -> str | None` returns a plain refusal, or None:
     - `<parent> doesn't exist.`
     - `<path> already exists and isn't empty. Pick another name or folder.`
     - `<path> is inside the repository <outer>. Pick a folder outside it.` (from `repo_setup.inspect`, kind nested, which also covers a folder inside `root`)
     - the home folder itself is refused with the console's existing home refusal text
  5. `last_parent() -> Path` reads `last_parent` from `paths.global_whyline_dir() / "sdlc-home.json"`. With none saved, it returns `~/projects` when that exists, else the home folder. `save_parent(path)` writes it.
  Tests: folder_name cases (punctuation, spaces, empty, a 60-character name), suggest_names parsing 3 lines, a bad reply falling back, an agent error falling back, the prompt holding only the synthesis, is_fresh with only docs and with a `src/` file, each refusal, and last_parent with and without a saved value.
  Review focus (closed): the refusals in 4 and the fallback in 2. Anything else goes in a follow-up note, not this task.

- [x] HOME-2: Create the project home
  Edit `src/whyline/sdlc/home.py` and its tests only.
  1. `create_home(root, slug, parent: Path, folder: str, *, name: str, agents: list[str], progress) -> Path`, under `guard.check(root)`:
     - It raises `HomeError` with the `check_target` refusal when there is one.
     - It runs `repo_setup.setup(repo_setup.inspect(target), agents=agents, progress=progress)`. That creates the folder, runs `git init -b main`, runs whyline init, writes the agent settings and makes the first commit, as the console's repository setup does today. A `repo_setup.SetupError` becomes a `HomeError` with the same text.
     - It writes `README.md` (`# <name>`, a blank line, then the first paragraph of the brainstorm's synthesis, or the set's description) and a `.gitignore` with `.DS_Store`, `.env`, `.venv/`, `__pycache__/` and `node_modules/`, each only when the file doesn't exist yet.
     - It copies `docs/sdlc/<slug>/` from `workspace.docs_root(root)` into the target, sets `home` in the copy's `docset.json` to `{"created_from": "<root>", "at": "<now>"}`, and commits README, `.gitignore` and the set by pathspec with `docs: start <name>` through `workspace.docs_commit`.
     - In the old docs checkout it sets the set's `state` to `moved` and `moved_to` to the target path, and commits `docs: <name> moved to <target>` through `docs_commit`. It never deletes the old set.
     - It calls `save_parent(parent)` and returns the target.
  2. `use_here(root, slug) -> Path` sets `home` to `{"here": true, "at": "<now>"}`, commits through `docs_commit`, and returns `root`.
  3. Nothing here pushes, and nothing creates a remote.
  4. `check_target` refuses the home folder with `Pick a folder other than your home folder.` and no longer uses the console's `_HOME_REFUSAL` text, which is about running agents in the home repository. `home.py` imports nothing from `whyline.console.repl` for it. Update its HOME-1 test to this text.
  Tests with temporary folders and a stubbed `repo_setup.setup`: the files written, README text with and without a brainstorm, an existing README kept, the set copied with `home` set, the old set marked moved and still present, both commits by pathspec, a refusal raising `HomeError` with nothing created, a setup error, and use_here.
  Review focus (closed): nothing created when a refusal applies, and the old set never deleted. Anything else goes in a follow-up note, not this task.

- [x] HOME-3: A GitHub repository for the project
  Create `src/whyline/sdlc/github_repo.py` and `tests/sdlc/test_github_repo.py`.
  1. `gh_ready(root, *, run=None) -> str | None` reuses `release.ready`'s gh installed and signed-in checks and returns their fix text (for example `Run: gh auth login`) or None.
  2. `default_owner(root, *, run=None) -> str | None` is `gh api user --jq .login`.
  3. `describe(owner, name, private: bool) -> str` returns `Create github.com/<owner>/<name> (private), add it as origin, and push main?`, with `(public)` when not private. The console and CLI show this exact text before anything runs.
  4. `create_repo(root, *, owner, name, private=True, run=None) -> str`:
     - It refuses with a plain message when `gh_ready` fails, when `origin` already exists (`This project already has a remote: <url>`), or when the name is empty.
     - It runs `gh repo create <owner>/<name> --private|--public --source <root> --remote origin --push` and returns the repository URL.
     - It saves `github` (URL and visibility) in the set's `docset.json` and adds `GitHub repository created: <url>` to `review-log.md`, committed through `docs_commit`.
  5. It is never called by `runner.run`, in either mode. Only a user action calls it.
  Tests with a stubbed `run`: private and public arguments, the describe text, each refusal, the URL saved, and that `runner.run` never calls it (patch it to raise).
  Review focus (closed): 5, and private as the default. Anything else goes in a follow-up note, not this task.

- [x] HOME-4: The home stage in the pipeline
  Edit `src/whyline/sdlc/stages.py`, `src/whyline/sdlc/runner.py` and their tests only.
  1. `plan_stages` adds a `home` stage, labelled `Project home`, right after `brainstorm` (or first, when there is no brainstorm stage) when the PRD mode is new. Otherwise it is skipped with the reason `existing project`. In the Stages line it shows as `Project home (you choose)`.
  2. `run` stops at `home` in both modes, with the result `waiting_for_home`. Auto mode stops here too, because only the user picks the name and folder.
  3. `choose_home(root, slug, *, choice, parent=None, folder=None, name=None, agents, progress) -> Path`, with `choice` `new` or `here`, calls `home.create_home` or `home.use_here`, marks the stage approved by the user, and returns the root the pipeline continues in.
  4. `run(target, slug, …)` then continues from the next stage in that root, in the set's saved mode.
  Tests: the stage present for new and skipped for update and none, both modes stopping at home, choose_home with `new` returning the target and `here` returning root, and run continuing in the target.

- [x] GFR-1: Review lenses
  Create `src/whyline/sdlc/lenses.py`, `src/whyline/sdlc/lenses/{zoom-out,comprehension,design-critic,codebase-fit,readiness}.md`, `src/whyline/sdlc/lenses/ATTRIBUTION.md` and `tests/sdlc/test_lenses.py`.
  1. Each lens file is a short reviewer brief in plain words, adapted from the Elephant-Goldfish Model reviewer personas (not copied verbatim):
     - **zoom-out**: is anything here not needed now? Does existing code in this repository already do it? Is it over-built?
     - **comprehension**: could someone new to the project follow it? Are there undefined terms, missing steps, or two readings of one sentence?
     - **design-critic**: failure modes, data loss, security and privacy, and claims about behaviour or performance with no reason given
     - **codebase-fit**: do the files, functions and names it mentions exist, and does it match how the code works today?
     - **readiness**: could an implementer start now without making a design decision? For a plan, each task names its files and tests, has a `covers:` line, is small (at most about 5 numbered steps and 4 source files), and a guard or security task has a closed Review focus list.
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

- [x] GFR-2: Run a fresh-eyes review
  Create `src/whyline/sdlc/goldfish.py` and `tests/sdlc/test_goldfish.py`. Make the helpers it needs in `src/whyline/relaychat/ask.py` public (keep the old names as aliases). Do not copy them.
  1. `review_document(root, docset, kind, *, agent, progress, cancel_event=None, run_fn=None) -> Review` runs every lens in `lenses_for(docset.size, kind)` under `guard.check` and `guard.drafting`.
  2. Each lens is its own new agent process, run the way `relaychat.ask.ask` runs one: the read-only command from `whyline.agents.capabilities.read_only_command`, `whyline_relay.agents.run`, a new temporary folder, and no `--resume`. The prompt holds only:
     - the lens text
     - the document's path and version
     - the paths of the approved documents before it
     - the line "Read code in this repository when the document names it."
     - for a PRD update, a unified diff against the current product PRD, and the line "Judge the changed sections, and whether the rest of the PRD still agrees with them."
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

- [x] GFR-3: Review gate in the pipeline
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
  6. For the plan, every gap in `trace.coverage` except tasks with `covers: none (<reason>)` is added to the review as a Blocker from the lens `coverage`.
  Tests: coverage gaps becoming Blockers, auto pass, a fix round that clears, two fix rounds that stop, a not-run stop, human mode returning with the review, the design-review stage using the architect agent, and approve-with-blockers logging.
  Review focus (closed): the round limit and the three gate outcomes. Anything else goes in a follow-up note, not this task.

- [x] SDLC-17: The build record and decisions.md
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

- [x] GFR-4: Drift check in the build record
  Edit `src/whyline/sdlc/record.py`, `src/whyline/sdlc/templates/build-record.md` and their tests only.
  1. `drift_review(root, docset, *, agent, progress, run_fn=None) -> Path` runs the codebase-fit lens once, the GFR-2 way, on the approved spec or design. It adds `git diff --stat <build_base>..HEAD` and the line "Compare what the document promised with what was built. A finding is something promised and not built, or built and not in the document." It writes `docs/sdlc/<slug>/reviews/drift.md`.
  2. The build-record stage attaches `drift.md` next to `build-inputs.md`. The template gains a `## Drift from the spec` section.
  3. When the lens doesn't run, the build record still gets written, and its section says `Drift check didn't run: <reason>`.
  Tests: the prompt has the diff stat and the spec path, the attachment, and the not-run text.
  Review focus (closed): 3. Anything else goes in a follow-up note, not this task.

- [x] LIFE-1: Plan changes during a build
  Edit `src/whyline/sdlc/record.py`, `src/whyline/sdlc/docset.py` and their tests, and `src/whyline/console/tui.py` only at the SDLC-17 hook.
  1. `plan_amendments(root, docs, docset) -> Amendments` compares the approved plan and test plan (by `content_hash`) with the files in the code checkout `root`. It lists added, removed and changed task ids. Ticked boxes don't count.
  2. When there are amendments, `record_amendments` adds the code checkout's plan as a new plan version with the note `amended during build: added GFR-1..6; changed SDLC-13`, logs `amended during build`, and keeps the status approved with `approved_by` `<git user> (during build)`.
  3. `build_inputs` lists the amendments, and the build-record template gains `## Plan changes during the build`.
  4. The SDLC-17 console hook calls `record_amendments` before the build-record stage. **Docs** shows the plan row as `Plan v2 (amended during build)`.
  Tests: added, removed and changed tasks, ticks ignored, the version and log entry, and build inputs listing them.

- [ ] TRC-2: Traceability in the build record
  Edit `src/whyline/sdlc/record.py`, `src/whyline/sdlc/templates/build-record.md` and their tests only.
  1. `trace_table(root, docs, docset) -> str` is a Markdown table with the columns Requirement, Tasks, Tests and Result. Result is passed, failed, not run or no test, from the test plan's ticks in the code checkout.
  2. `build_inputs` includes the table. The template gains `## Requirements traceability`, and its Known gaps section must list every requirement whose result isn't passed.
  Tests: the table for a full pass, a failed test, an untested requirement, and an amended plan.

- [ ] LIFE-2: Close a feature, and open a pull request
  Create `src/whyline/sdlc/close.py` and its tests. Edit `src/whyline/sdlc/runner.py` and its tests only to add the done stage.
  1. `close(root, slug) -> CloseResult` runs as the **done** stage after the build record is approved, under `guard.check`:
     - In the docs checkout, it `git mv`s the plan and test plan to `plans/done/` and updates their paths in `docset.json`.
     - It sets the set's `state` to released, with the version and tag from `build_inputs` (or built, when there was no release), and releases any PRD claim.
     - It commits `docs: close <name>` through `docs_commit`.
     In auto mode `run` calls it. In human mode it waits for **Close**.
  2. `pr_body(root, docs, docset) -> str`: the build record's What was built, the traceability table, Known gaps, and relative links to the set's documents.
  3. `open_pr(root, docs, slug, *, gh_fn=None) -> str` runs only on an explicit user action, never in auto mode:
     - It pushes the relay branch with `git push -u origin <branch>`.
     - It runs `gh pr create --base <default> --head <branch> --title "<name>" --body <pr_body>` and returns the URL.
     - It saves the URL in `docset.json` and logs `pull request opened`.
     It refuses with a plain message when `gh` is missing or not signed in, or the branch has no remote. Merging stays with the user on GitHub.
  Tests: close moving both files and updating paths, released versus built, no PRD claim left, pr_body content, open_pr with a stubbed gh, and each refusal.
  Review focus (closed): `open_pr` never running in auto mode, and nothing pushed except the relay branch. Anything else goes in a follow-up note, not this task.

## Part 4: Library, export and CLI (no widgets)

- [ ] SDLC-18: The library
  Create `src/whyline/sdlc/library.py` and its tests.
  1. `sets(root) -> list[SetSummary]`, newest first, each with a one-line summary such as `Job search 5 · Feature · PRD ✓ · Spec ✓ · Plan ✓ · Built ⏳`.
  2. `product(root) -> ProductSummary | None`: the product PRD's version, approval and its last 10 changelog lines, listed above the sets.
  3. `earlier_plans(root) -> list[EarlierPlan]`: every plan in `plans/` and `plans/done/` that no set owns. Each comes with its test plan, and with the spec or brainstorm its marker line names when that file exists.
  Tests: mixed sets and earlier plans, a plan in `plans/done/`, and a marker whose spec is missing.

- [ ] SDLC-19: Export pack
  Create `src/whyline/sdlc/export.py` and its tests.
  1. `export_pack(root, slug, out_dir) -> ExportResult`:
     - It builds one Markdown: a cover from `index.md`, each document in order without its header block, the plan, the test plan, and `review-log.md` as an appendix titled "Review log".
     - It writes `<slug>-docs.docx` through `whyline.agents.convert.to_docx`, and `<slug>-docs.pdf` through the PDF path in `whyline.ideas.documents`.
     - `ExportResult` lists the files and any notes (for example, PDF not available).
  2. The pack includes the product PRD at the version the set was based on (from `history/`), titled `Product PRD v<version>`, followed by that set's changed sections, when it made a PRD update.
  3. The default `out_dir` is `~/Downloads`.
  Tests: content order, header blocks stripped, the PDF fallback note, and that a missing document is skipped with a note.

- [ ] SDLC-20: `whyline docs` CLI
  Create `src/whyline/sdlc/cli.py` and edit `src/whyline/cli.py` to register it. Add tests.
  Subcommands, each calling the Part 2 to 4 functions:
  - `list`
  - `show <slug> [<doc>]`
  - `start --from-description TEXT | --from-file PATH [--as brainstorm|prd|spec] [--size] [--prd new|update|none] [--major] [--auto] [--name]`
  - `prd [--history]`, which prints the product PRD's version and approval and, with `--history`, the changelog
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

- [ ] HOME-5: Project home in the CLI
  Edit `src/whyline/sdlc/cli.py` and its tests only. The console counterpart is HOME-6.
  1. `whyline docs names <slug>` prints each suggestion as `<Name> (<folder>) — <reason>`.
  2. `whyline docs home <slug> --here | --new [--name NAME] [--folder FOLDER] [--parent DIR]` calls `runner.choose_home`. `--name` defaults to the first suggestion, `--folder` to `folder_name(name)`, and `--parent` to `last_parent()`. It prints the root and `Next: whyline docs resume <slug>` with `cd <path>` when the root changed.
  3. `whyline docs github <slug> [--public] [--owner OWNER] [--name NAME]` prints `github_repo.describe` and asks for confirmation unless `--yes`, then calls `create_repo` and prints the URL. Owner defaults to `default_owner`, name to the folder name.
  Tests: each subcommand with stubs, a refusal exiting non-zero, and github without `--yes` doing nothing when the answer is no.

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
     - **PRD**, for Feature and Large: **Update the product PRD** (the default when `docs/product/prd.md` exists, showing `current v1.2`), **New project: write the PRD** (the default when it doesn't), or **No PRD change**. With update, a **Major version (v2.0)** checkbox, off by default. Small shows `Small has no PRD.`
     - **Mode**: Human in the loop or Auto
     - **Build when the plan is approved**, default on, always on in Auto
     - roles: Writer, Reviewer, Test planner, plus Architect reviewer for Large, plus the execution roles when building
  3. An Auto checkpoint saved before this release still shows **Resume** through the existing auto_run path. The form no longer starts the old Auto.
  Tests: each field's visibility by size, start and mode, the PRD choice defaults with and without a product PRD, the picker stub selecting a file, and the old Auto checkpoint still offering Resume.

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
     - **left**: **Product PRD v<version>** first (from `library.product`, opening the PRD and its changelog), then sets and Earlier plans from `library`
     - **middle**: the selected set's documents with status, version and approval
     - **right**: the selected document rendered as Markdown
  2. Out-of-date documents show the reason under their row.
  3. The screen opens on a given set and document, which SDLC-23 uses.
  4. While `guard.check` refuses (a relay running in the docs checkout itself), every action button except History and Export is disabled, and the reason shows at the top.
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

- [ ] PRD-2: PRD update in Docs
  Edit `src/whyline/console/docs_screen.py` and its tests only.
  1. For a PRD update, the right pane opens on `Changed sections: <list>` with **Show diff** (a unified diff against the current product PRD) and **Show whole PRD**.
  2. When `product.moved` is true, a line reads `The PRD is now v<new>. Redo this update first.`, and Approve is disabled until **Redo** runs.
  3. When another set holds the PRD claim, the set's PRD row says `Waiting: <set> is updating the PRD`.
  Tests: changed sections and the diff, the moved line disabling Approve, and the waiting line.

- [ ] LIFE-3: Close, pull request and coverage in Docs and the CLI
  Edit `src/whyline/console/docs_screen.py`, `src/whyline/sdlc/cli.py`, `src/whyline/sdlc/library.py` and their tests only.
  1. Docs:
     - **Close** shows on a set whose build record is approved, and calls `close.close`.
     - **Open pull request** shows on a closed or built set with no PR yet. It first asks `Push <branch> to origin and open a pull request?`, then calls `close.open_pr` in a thread worker and shows the URL.
     - The plan row shows `trace.coverage(...).line()`.
     - The set summary shows `Released v<version>` or `Built`, and `PR open` when there is a URL.
  2. CLI: `whyline docs close <slug>`, `whyline docs pr <slug>` (asks for confirmation unless `--yes`) and `whyline docs trace <slug>` (prints the coverage line and the traceability table).
  3. Docs, the Files-pane Docs tab and `whyline docs list` show where documents are written: `Documents: <docs checkout path> (<default branch>)`.
  Tests: each button's visibility, the PR confirmation, the coverage line, each subcommand with stubs, and the location line.

- [ ] HOME-6: Project home in the console
  Edit `src/whyline/console/docs_screen.py`, `src/whyline/console/tui.py`, `src/whyline/sdlc/library.py` and their tests only.
  1. When `run` returns `waiting_for_home`, the console opens a **Project home** screen in Docs:
     - **Where should this project live?**: **Create a new folder** or **Use this repository** (`<repo name>`). The default is Use this repository when `home.is_fresh(root)` is true, otherwise Create a new folder.
     - For a new folder: the 2 or 3 suggested names as choices (loaded by `home.suggest_names` in a thread worker, with `Suggesting names…` while it runs), then **My own name** with a text field. **Folder name** fills in from `folder_name` and can be edited. **Save in** shows `last_parent()`, with **Choose folder…** through the existing picker and an injectable `pick_folder_fn`. A line under them shows the full path, or the `check_target` refusal, which disables Continue.
     - **Create GitHub repository** checkbox, off by default. When ticked: **Private** (default) or **Public**, and **Owner**, defaulting to `default_owner`. When `gh_ready` fails, the checkbox is disabled with its fix text.
     - **Continue** calls `runner.choose_home` in a thread worker with progress in the busy line (`home · run git init`, and so on).
  2. When the root changed, the console switches to it through the existing `_switch_repo` path, with no extra confirmation (the user just chose it), then reopens Docs on the set there. The set continues with `runner.run` in the new root.
  3. When the GitHub box was ticked, after the switch it shows `github_repo.describe(...)` in a ConfirmScreen and calls `create_repo` only on Yes. On No, or on a refusal, the set carries on without a remote, and Docs offers **Create GitHub repository** on that set later. A failure is shown and never stops the pipeline.
  4. `library.py` shows a set whose state is `moved` as `Moved to <path>`, with **Switch to it**.
  Tests with stubs: the default choice for a fresh and a non-fresh repository, the suggestions filling the choices, the folder name following the chosen name, a refusal disabling Continue, the switch to the new root, the GitHub confirmation (Yes calls create_repo, No does not), the disabled checkbox when gh is not ready, and the moved row.

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
  - where documents live (the docs checkout on the default branch) and why you can work on documents while a relay builds
  - traceability: covers lines, the coverage line, and the build record's table
  - plan changes during a build, closing a set, and opening a pull request
  - the product PRD: one per repository, its versions and changelog, new versus update versus no change, the one-update-at-a-time rule, and why built sets keep their PRD version
  - fresh-eyes review: the lenses, the Auto gate and its 2-round limit, lens overrides in `.whyline/sdlc/lenses/`, the drift check, and credit to the Elephant-Goldfish Model
  - that Test planner belongs to Plan, not Chat Brainstorm
  - Project home for a new project: the name suggestions, a new folder or this repository, what gets created and committed, the optional GitHub repository (private by default, only after you confirm), and the `whyline docs names`, `home` and `github` commands
  Verify with `uv run pytest -q`.

- [ ] SDLC-30: Publish whyline with SDLC-1..29, WTD-1, PRD-1..2, TRC-1..2, LIFE-1..3, GFR-1..6 and HOME-1..6
  relay-profile: release
  Bump the version in `pyproject.toml`, `src/whyline/__init__.py` and `uv.lock` to the next patch version. Write `docs/releases/v<version>.md` from every task since the previous release (`git log v<previous>..HEAD`), in user terms. Run `uv run pytest -q` with the agent CLIs off PATH and `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1`, and again on Python 3.11. Push, wait for green CI on Linux and macOS, then tag `v<version>`, push the tag and let the release workflow publish to PyPI. Afterwards run `uv tool upgrade whyline` and confirm `whyline --version`.
