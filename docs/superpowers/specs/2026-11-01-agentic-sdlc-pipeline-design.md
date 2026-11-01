# Plan as an agentic SDLC pipeline, with a reviewable document set

Date: 2026-11-01. Status: draft for the user's review. Plan: `plans/sdlc-pipeline.plan.md` (SDLC-1..). It needs a whyline-relay change first: `~/whyline-relay/plans/documents.plan.md` (RDOC-1..3).

## Problem

Relay → **Plan** has four separate sources today: **Brainstorm it**, **I'll describe it**, **I have a plan already** and **Auto — brainstorm to implementation**. Most of the steps exist (brainstorm, spec, plan, test plan, plan review, then implement, test, review and release through the relay), but:

- There is no **PRD**. The spec has to say both what and why (users, problem, goals, success measures) and how (architecture).
- You can't start in the middle. "I'll describe it" skips brainstorming, and Auto always starts a fresh brainstorm. A brainstorm file outside `docs/brainstorm/` can't be used at all.
- The documents aren't a record anyone can review. They're spread over `docs/brainstorm/`, `docs/specs/` and `plans/`. Nothing links them, nothing says whether one was approved, by whom, or against which version of the document before it. Nothing records what was actually built against what was designed.
- In a larger organisation a senior developer or architect reviews a PRD and a design doc at any time. Whyline gives them nothing to open.

## What the user gets

### One pipeline in Plan

The Plan dialog keeps **I have a plan already**. The other three sources become one form:

- **Start from**:
  - **A description**, which is typed, plus attachments as today.
  - **A brainstorm**: any file in `docs/brainstorm/`, or **Choose file…** for a `.md`, `.txt`, `.pdf` or `.docx` anywhere. The file is imported into the document set.
  - **A document I already have**: a PRD or a spec/design, from **Choose file…**. The stages before it are skipped and the file becomes that stage's first version.
- **Size**:

  | Size | For | Documents |
  |---|---|---|
  | **Small** | a bug fix, or a tweak to one screen | short spec, plan with test plan |
  | **Feature** (default) | a feature like job-search-5 or round cap | PRD, spec, plan with test plan |
  | **Large** | a new subsystem, an architecture change | brainstorm, PRD, full design doc with decision records, design review, plan with test plan |

  Every size ends with a **build record** once the relay has built it. Feature has a **Brainstorm first** checkbox, off by default. Large always brainstorms unless it starts from a brainstorm or a later document.
- **Mode**:
  - **Human in the loop** (default). The pipeline stops after every document and waits for you.
  - **Auto**. It runs from the start to the end of the build with no stops. It stops only when an agent is stuck, an agent has a question it can't answer from the request, or preflight fails, as Auto does today.
- **Roles**: Writer, Reviewer and Test planner, as today. Large adds **Architect reviewer** (default: an agent that is not the writer). The execution roles (implementer, tester, reviewer, release) show only when the pipeline goes on to build. That is always in Auto, and in Human in the loop when **Build when the plan is approved** is ticked (default on).
- A **Stages** line under the form shows what will run from the current choices, each with its agent. For example:

  `PRD (claude, reviewed by codex) → Spec (claude) → Plan + test plan (claude, tests by codex) → Implement → Test → Review → Release → Build record`

  A stage that is skipped shows `—` and the reason, for example `Brainstorm — (starting from a brainstorm)`.
- **Start** creates the document set and runs the first stage.

### The document set

Each run creates one folder, `docs/sdlc/<slug>/`, where `<slug>` comes from the name in the form:

```
docs/sdlc/<slug>/
  index.md           # the cover page: what this is, size, mode, status of each document, links
  brainstorm.md      # Large, or when asked for, or imported
  prd.md             # Feature and Large
  spec.md            # Small (short spec) and Feature
  design.md          # Large (full design doc; replaces spec.md)
  decisions.md       # the decision records: from the design doc and from whyline notes
  build-record.md    # after the build
  review-log.md      # every review action, newest last
  history/           # every earlier version: prd-v1.md, prd-v2.md, ...
  docset.json        # the manifest (machine-readable; the files above are for people)
```

- **The plan and the test plan stay** at `plans/<slug>.plan.md` and `plans/<slug>.tests.md`, because the relay reads them there. `index.md` and the Docs screen show them as part of the set.
- **Standard templates.** Each document type has a fixed list of sections, built in at `src/whyline/sdlc/templates/<type>.md`. The writer is told to fill every section and to write `Not applicable — <reason>` rather than drop one. A repository can override a template at `.whyline/sdlc/templates/<type>.md`. Sections:
  - **PRD**: Summary; Problem; Users and the moment they need this; Goals; Non-goals; Anti-goals (what would make this a failure even if it works); Requirements (numbered R1, R2… so later documents can refer to them); Success measures; Risks and open questions.
  - **Spec** (Feature): Summary; Requirements covered (by R-number); Approach; Components and files; Data and formats; Interfaces (CLI, console, files); Errors and edge cases; Testing approach; Rejected alternatives.
  - **Short spec** (Small): What changes; Why; Files; Testing; Risks.
  - **Design doc** (Large): everything in Spec, plus Context and constraints; Architecture (with a diagram in Mermaid or ASCII); Data model; Security and privacy; Performance; Migration and rollback; Decision records (ADR-style: decision, context, options considered, consequences); Open questions for the architect.
  - **Build record**: What was built; Tasks and their commits; Test results (from the test plan's ticked scenarios); Changes from the design and why; Decisions recorded during the build; Known gaps; Release (version, tag, notes link).
- **A header on every document** except the plan and test plan, whose format the relay owns. It sits between `<!-- docset-header -->` and `<!-- /docset-header -->` at the top, and whyline rewrites it from `docset.json` on every status change. It shows:
  - Status: **Draft**, **In review**, **Changes requested**, **Approved**, **Out of date** or **Superseded**
  - Version
  - Written by (agent) and reviewed by (agent)
  - Approved by (a git `user.name` or an agent name with "(Auto)") and when
  - Links to the documents before and after it
- **Statuses** live in `docset.json`. A document's text never decides its own status.

### Reviewing at each stop (Human in the loop)

When a stage finishes, the console opens the **Docs** screen on that document with these actions:

- **Approve**:
  1. The document is marked Approved, version N, by you, now.
  2. The version is copied to `history/`.
  3. A line is added to `review-log.md`.
  4. The set is committed.
  5. The next stage starts.
- **Ask for changes**, the main path:
  1. You write comments and can pick a section from a list of the document's headings, or "Whole document".
  2. The writer revises. The reviewer agent reviews the revision, as the existing spec and plan revise loop does.
  3. It comes back to you as version N+1. The review log keeps your comment, the version it applied to, and which sections changed.
  4. When you picked a section and other sections also changed, the screen says so: `Also changed: Goals, Risks`.
- **Edit**:
  1. The file opens in your editor, using the console's existing editor opening.
  2. When you come back, whyline sees the file changed. It saves the version as N+1 "edited by <you>" and offers Approve or Ask for changes, working from your edit.
- **Stop here**: everything stays as it is and the set stays **In review**. It can be resumed any time from Docs or Plan.
- **Run the rest on Auto**: switches the set's mode, approves this document and continues without further stops.

While Auto runs, **Pause after this stage** switches the mode back to Human in the loop. It takes effect when the current stage finishes.

Questions from the writer (an `## Open questions` section, as today) stop the stage in both modes. You answer them in the review screen and the writer revises.

### Auto mode

- It starts from the same form and runs every stage.
- The reviewer agent's final review counts as approval. It's recorded as `approved by codex (Auto)`.
- Its comments are kept in `review-log.md` in the same way as a person's, so a later reader sees what was questioned.
- After the plan, Auto does what today's Auto does: final preflight, then launch the relay.
- When the relay finishes the plan, the build record is written, then approved by the reviewer agent.

### Out of date

- When a document is approved, `docset.json` stores the sha256 of each approved document before it.
- If one of those changes later (a re-approved PRD, or an edit on disk), the later documents show **Out of date**, with the reason: `PRD changed (v3 → v4) after this was approved`.
- **Redo** sends the writer an Ask for changes: "Update this to match <document> v<N>. Change only what that change needs."
- An out-of-date document never blocks a relay that is already running. Docs only shows it.

### Docs

1. **A Docs tab in the Files pane** (Relay mode), next to Plan. It shows the set of the plan the relay is running or has selected: each document, its status, and the selected one's text. It's read-only. **Open in Docs** goes to the full screen.
2. **A Docs button** in Relay mode opens the **Docs** screen, the library and the review screen in one:
   - **Left**: every document set in the repository, newest first, each with a one-line summary such as `Job search 5 · Feature · PRD ✓ · Spec ✓ · Plan ✓ · Built ⏳`. Older plans without a set (in `plans/` and `plans/done/`) are listed under **Earlier plans**. Each shows its plan, its test plan, and the spec or brainstorm its marker line names.
   - **Middle**: the selected set's documents, with status, version and approval.
   - **Right**: the selected document, rendered as Markdown.
   - **Buttons**:
     - **Approve**, **Ask for changes**, **Edit** and **Redo**, shown when they apply
     - **History**: versions, review-log entries, and a diff between any two versions
     - **Export pack**
     - **Resume** for a set that stopped
   - While any relay is running in the repository, every set is read-only except Export and History. See "How it fits the code today".
3. **Export pack** writes one Word file and one PDF of the whole set to `~/Downloads/<slug>-docs.docx` and `.pdf`:
   - a cover page from `index.md`, then the documents in order
   - the plan and test plan
   - the review log as an appendix

   It reuses `whyline.agents.docx` and the PDF path in `whyline.ideas.documents`, so there's no new dependency. This is how a reviewer outside whyline gets the documents. Their comments come back through **Ask for changes**.

### CLI (console first: each one calls the same function the console calls)

- `whyline docs list`
- `whyline docs show <slug> [<doc>]`
- `whyline docs approve <slug> <doc>`
- `whyline docs change <slug> <doc> "<comments>" [--section "<heading>"]`
- `whyline docs export <slug>`
- `whyline docs start --from-description TEXT | --from-file PATH [--size small|feature|large] [--auto]`
- `whyline docs resume <slug>`

## Goals

- One pipeline from a description, a brainstorm or an existing document, to an approved plan, and on through a build.
- A complete, standard, versioned document set per feature that a senior developer or architect can review without asking anyone.
- Human in the loop by default, where revision by the agent is the easy path.
- Auto that needs no human from the description to release, and still leaves the same record.

## Non-goals

- Comments made inside Word, on GitHub or anywhere outside whyline are not read back in. The reviewer's comments come back through Ask for changes.
- Reviewer accounts, permissions or sign-off by people other than the console's user. "Approved by" is the git user.
- Generating code from the PRD directly. Code still comes only from the relay running the plan.
- Changing how the relay runs a plan.

## Anti-goals

- Documents that look complete but are padding. A template section with nothing to say gets `Not applicable — <reason>`, never filler.
- A document set that silently goes stale. Out of date must show.
- Losing what you liked when you ask for a change to one section.
- Breaking today's plans, the paste source, or an Auto run that was checkpointed before this ships.

## Constraints

- Console first. Every action is in the console. The CLI calls the same functions.
- No new Python dependency.
- A plan must stay a valid relay plan (marker line, `- [ ] ID: title`). A test plan must stay valid for `whyline_relay.testplan.validate`.
- Writing and reviewing a document reuse whyline-relay's planner machinery (draft, review, revise, answer, resume, failover). The console doesn't run its own draft/review loop.
- Nothing commits on a relay branch while that relay runs.
- Tests never run a real agent, open a real picker or editor, or contain "/Users/".

## How it fits the code today

- **The PRD needs a whyline-relay change.** `whyline_relay.planner` has two private document kinds, `PLAN_KIND` and `SPEC_KIND`. Each has its own draft file, checkpoint and prompts, and one checkpoint per kind per repository.
  - **RDOC-1** adds:
    - a public `planner.DocKind(name, draft_prompt, review_prompt)`, whose draft file and checkpoint are named after `name`
    - a `documents` module with draft, revise, answer, resume, discard and pending for any kind
    - built-in `prd-draft`/`prd-review` and `design-draft`/`design-review` prompts
  - **RDOC-2** adds:
    - a `template` text appended to the draft prompt
    - `documents.revise_text(root, settings, kind, text, feedback, ...)`, which seeds a new checkpoint from existing text and runs the revise loop on it. This is how **Ask for changes**, **Redo**, a revision after **Edit**, and a revision of an imported document reach the writer, because none of them has a live checkpoint.
  - **RDOC-3** releases whyline-relay 0.2.41, after 0.2.40 (RLY-1..13). agentdock's pyproject then needs `whyline-relay>=0.2.41`.
- **No checkpoint is held while waiting for a person.** When a stage finishes, its text is copied into the set as the new version and the relay's checkpoint for that kind is discarded. Every later revision goes through `revise_text` from the set's current version. So several sets can be In review at once, and today's spec flow is never blocked by a set waiting for review.
  - Only one stage drafts at a time in a repository, under a lock at `.whyline/sdlc/drafting.lock`, because the writer shares the repository's handoff file.
  - A second **Start** or revision while one is drafting is refused with a plain message.
- **While any relay is running in the repository**, Docs is read-only (History and Export still work). Plan's **Start** and `whyline docs start` refuse too. Drafting shares the relay's handoff file, and approvals would commit on the relay's branch.
- **Earlier documents reach the writer as attachments.** The approved PRD and spec are files in `docs/sdlc/<slug>/`, inside the repository, so the existing `attachments` rule (files inside the repository only) holds. A brainstorm file or document chosen from outside the repository is first converted and copied into the set:
  - `.md` and `.txt` as they are
  - `.pdf` through `pypdf`, already a dependency
  - `.docx` through the reader `whyline.jobs.profile` uses for CVs

  The copy becomes version 1, so headers, hashes, history and diffs work on it like any other version.
- **Spec and design** use the existing `SPEC_KIND` with the template appended (Spec, Short spec) or the new design kind (Large).
- **Plan and test plan** use the existing plan kind with the Test planner, unchanged. They are reviewed at one stop, because whyline-relay drafts them together.
- **Brainstorm** uses `adapters.run_brainstorm` as today. The final synthesis is copied into the set as `brainstorm.md`, and `docs/brainstorm/<topic>.md` stays where it is.
- **Build** reuses Auto's final preflight and launcher.
- **New package** `src/whyline/sdlc/` with no widgets:
  - `docset.py`: the manifest, statuses, headers, versions, history, review log, hashes and out of date
  - `stages.py`: the stage list for a size and start point, the next stage, and gates by mode
  - `runner.py`: runs one stage through `relay_ops`, saves its checkpoint in `docset.json`, and resumes
  - `templates/`
  - `export.py`
  - `library.py`: lists sets and earlier plans
  - `cli.py`
- **Console**:
  - the Plan dialog form, in `relay_screens.py`
  - a `docs_screen.py`
  - a Docs tab in `file_pane.py` and `tui.py`
- **Today's Auto**: `auto_run.py` stays only to resume a checkpoint saved before this ships. The Plan dialog no longer starts it. Removing it is a later task.
- **Fixed on the way**: Chat → Brainstorm's Test planner field changes the Plan dialog's Test planner and has no effect on a chat brainstorm. It is removed from Chat (this was PFB-1).
- **PFB-1..5 in `plans/relay-tooling.plan.md` are dropped.** This design covers them: the file picker, starting from an existing brainstorm, the Stages line and the Chat fix. PFB-5's documentation work moves into this plan's docs task, together with the README and the `docs/` pages for Plan, Brainstorm and Docs.

## Left to the builder

- Layout details of the Docs screen and the Plan form, within the existing console style.
- The wording of the built-in templates and prompts, within the section lists above.
- How the slug is made (reuse the existing slug helpers).
- Whether `index.md` is rewritten on every change or only on approval, as long as it is never stale when a set is idle.
