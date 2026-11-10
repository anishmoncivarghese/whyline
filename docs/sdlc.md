# Plan, Brainstorm and the document set

**Relay → Plan** turns an idea into reviewed documents and a plan the relay can
build. Every run makes one *document set* in `docs/sdlc/<slug>/` that you, or a
senior developer or architect, can open and review without asking anyone.

Everything here is in the console (**Relay → Plan** and **Docs**). The
`whyline docs` commands call the same functions, for scripts.

## The pipeline, sizes and modes

Start from a description, a brainstorm (any file in `docs/brainstorm/`, or a
`.md`, `.txt`, `.pdf` or `.docx` you choose), or a PRD or spec you already have.
Stages before the one you bring are skipped. **I have a plan already** still
works as before.

| Size | For | Documents |
|---|---|---|
| **Small** | a bug fix or a tweak to one screen | short spec, plan with test plan |
| **Feature** (default) | a feature | PRD update, spec, plan with test plan |
| **Large** | a new subsystem or architecture change | brainstorm, PRD update, design doc with decision records, design review, plan with test plan |

Every size ends with a **build record** once the relay has built it. A
**Stages** line under the form shows what will run, with each stage's agent.

- **Human in the loop** (default) stops after every document and waits for you.
- **Auto** runs from the request to the end of the build, with no review stops. It
  still stops when an agent is stuck, has a question it can't answer from the
  request, or preflight fails. For a new project, both modes also pause for
  the required Project home choice. While Auto runs, **Pause after this stage** (shown only for
  Auto docs runs) switches back to Human in the loop when the current stage
  finishes. The mode is saved with the set.

**Test planner** belongs to Plan. Chat → Brainstorm has no Test planner field:
it never affected a chat brainstorm.

## The document set and its templates

```text
docs/sdlc/<slug>/
  index.md  brainstorm.md  prd.md  spec.md  design.md
  decisions.md  build-record.md  review-log.md  history/  reviews/  docset.json
```

The plan and test plan stay at `plans/<slug>.plan.md` and
`plans/<slug>.tests.md`, because the relay reads them there. The Docs screen
shows them as part of the set.

Each document type has a fixed list of sections (PRD, spec, short spec, design
doc, build record). The writer fills every section and writes
`Not applicable — <reason>` rather than dropping one.

**Template overrides:** put your own at `.whyline/sdlc/templates/<name>.md`,
where `<name>` is `prd`, `spec`, `short-spec`, `design` or `build-record`. An
override replaces the built-in one for that repository.

Each document has a header, rewritten from `docset.json`, with its status
(Draft, In review, Changes requested, Approved, Out of date, Superseded),
version, who wrote and reviewed it, who approved it and when.

## Where documents live

Documents, the product PRD and the plan are written and committed in a *docs
checkout* on the default branch: the repository itself when it is on the default
branch, an existing worktree of it, or a new one next to your relay worktrees.
Commits touch only the files whyline wrote, and whyline never pushes them.

That is why you can draft and review documents while a relay builds in another
checkout. Docs is read-only only when a relay runs in the docs checkout itself.
Before a relay launches from another checkout, the plan and test plan are copied
there and committed. Only one stage drafts at a time in a repository.

## Reviewing at each stop

When a stage finishes, **Docs** opens on that document:

- **Approve** marks it approved at that version, saves it to `history/`, logs
  it, commits the set and starts the next stage.
- **Ask for changes** takes your comments, optionally for one section. The
  writer revises, the reviewer checks, and it returns as the next version. If
  other sections changed too, it says so (`Also changed: Goals, Risks`).
- **Edit** opens the file in your editor; your change becomes the next version.
- **Redo** brings an out-of-date document into line with the one before it.
- **Stop here** leaves the set In review; **Run the rest on Auto** switches mode.

Questions from the writer stop the stage in both modes; answer them on the
screen. In Auto, the reviewer agent's final review counts as approval and is
recorded as `approved by <agent> (Auto)`; its comments stay in `review-log.md`.

### Out of date

An approved document records the hash of each document before it. If one changes
later, the later ones show **Out of date** with the reason, for example
`PRD changed (v1.2 → v1.3) after this was approved`. Out of date never blocks a
relay already running. A set that has been built keeps the PRD version it was
built on and is never marked by later PRD changes.

### The Docs screen

**Relay → Docs** lists every set, newest first, with a one-line summary, and
older plans without a set under **Earlier plans**. It shows the set's documents
with status, version and approval, and the selected document as Markdown.
**History** shows versions, the review log and a diff between any two versions.
A read-only **Docs** tab in the Files pane shows the active plan's set.

### Export pack and the `whyline docs` commands

**Export pack** writes a Word file and a PDF of the whole set (cover page,
documents in order, the plan and test plan, the review log as an appendix) to
`~/Downloads`, or `--out DIR`. It is how a reviewer outside whyline gets the
documents; their comments come back through **Ask for changes**.

```text
whyline docs list | show <slug> [doc] | start | resume <slug>
whyline docs approve | change | redo | answer | mode <slug> ...
whyline docs review | findings <slug> <doc>
whyline docs prd [--history]
whyline docs trace | export | close | pr <slug>
whyline docs names | home | github <slug>
```

`start` takes `--from-description` or `--from-file` (with `--as brainstorm|prd|spec`
to import the file as that document), `--size`, `--prd new|update|none`,
`--major` and `--auto`.

## Traceability

The PRD numbers its requirements R1, R2… and an update never renumbers them. The
spec lists the ones it covers. Each plan task has a `covers: R…` line
(`covers: none (<reason>)` for a task that serves no requirement). Each test
case carries its requirement tags in its title, such as `[R1]` or `[R1][R2]`. The plan review treats a requirement with no task or no test as a
Blocker.

`whyline docs trace <slug>` prints the **coverage line** (what is built and
tested) and the build record's table. The build record has a Requirements,
Tasks, Tests and Result table, and *Known gaps* lists every requirement that
didn't pass.

## Plan changes, closing, and pull requests

- Ticking tasks is not a change. Tasks added, removed or changed after approval
  are recorded as a new plan version, `amended during build`, and listed in the
  build record.
- **Close** (after the build record is approved) moves the plan and test plan to
  `plans/done/` and marks the set Released (with version and tag) or Built.
- **Open pull request** pushes the relay branch and opens a PR whose body comes
  from the build record. It happens only when you press it and confirm, never in
  Auto. Merging stays with you.

## The product PRD

There is **one product PRD per repository**, at `docs/product/prd.md`, with its
history in `docs/product/changelog.md`. Small sets never have one. For Feature
and Large you choose:

- **New** (default when there is no PRD) writes v1.0.
- **Update** (default otherwise) starts from the current PRD and changes only the
  sections the feature affects. Approval makes v1.1, v1.2…, or v2.0 with
  **Major version**. The writer may answer `No PRD change: <reason>` and the
  stage is skipped.
- **No change** skips the stage.

Only **one PRD update is open at a time**. An update whose base version has
since changed must be redone before it can be approved. The changelog records
which feature changed which sections in each version. Specs, designs, plans and
build records stay per feature and record the PRD version they were based on, so
**built sets keep their PRD version**. `whyline docs prd --history` prints the
version, approval and changelog.

## Fresh-eyes review

Each document can get a *fresh-eyes review*: short **lenses** (zoom-out,
comprehension, design-critic, codebase-fit, readiness), each run in a new
read-only agent that sees only the document and the approved documents before
it, never the request, the drafting conversation or earlier reviews. Which
lenses run depends on size and document (a Large design gets all five).
Findings are Blockers, Major or Nits, and anything that didn't run is listed as
*Not run*. Use `whyline docs review` and `whyline docs findings`.

- **Auto gate.** Auto approves only a document with no Blocker and every lens
  run. With Blockers it asks the writer for changes and reviews again, at most
  **2 rounds**; then it stops with "Still has blockers" for you. If a lens
  didn't run it stops rather than guessing.
- **Lens overrides.** Put your own lens at `.whyline/sdlc/lenses/<name>.md` to
  replace the built-in one.
- **Drift check.** After a build, the codebase-fit lens compares the approved
  design (else spec) with what was built and writes `reviews/drift.md`: what was
  promised and not built, and what was built and not in the document. It feeds
  the build record.

The lens texts are adapted from the reviewer personas of the
[Elephant-Goldfish Model](https://github.com/google/elephant-goldfish-model)
(Apache-2.0). See `src/whyline/sdlc/lenses/ATTRIBUTION.md`.

## Project home for a new project

When the set starts a brand new project, you choose where it lives before
anything is built:

- **Name suggestions.** The writer suggests three short names, each with a
  reason (`whyline docs names <slug>`).
- **A new folder or this repository** (`whyline docs home <slug> --new` with
  `--name`, `--folder`, `--parent`, or `--here`). A new folder can't be your
  home folder or an existing non-empty one.
- **What gets created and committed.** A new git project with whyline's
  repository setup, a `README.md` (name and a first paragraph), a `.gitignore`,
  and a copy of the document set, committed as `docs: start <name>`. The old
  copy is marked moved. Choosing this repository records that and commits it.
  Nothing is pushed.
- **Optional GitHub repository** (`whyline docs github <slug>`). Private by
  default (`--public` to change, `--owner`, `--name`). It is created only after
  you confirm what it will do (`--yes` skips the prompt in scripts), needs `gh`
  signed in, adds `origin`, pushes, and records the URL in the set. It is never
  created automatically, and refuses a project that already has a remote.
