<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-09T10:00:00+05:30 -->
# RAAID log: risks, assumptions, actions, issues and dependencies for a repository

Runs after `plans/telegram-daily-use.plan.md`, and before `plans/sdlc-git-flow.plan.md`. Design: `docs/superpowers/specs/2026-11-09-raaid-log-design.md`. Read it before any task. This plan needs the SDLC pipeline's modules (`whyline.sdlc.docset`, `templates`, `goldfish`, `record`, `close`, `product`, `export`, `library`) and the Chat tab in the Files pane.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

There is no publish task (removed 2026-11-11). When the relay finishes, press **Release**: it sets the version, writes the notes, runs the checks and the security scan, pushes, waits for CI, tags and publishes. This repository's relay has no `release` profile, so a publish task would only bump the version.

What the user gets:
- A **RAAID** tab in the Files pane next to **Chat**, with **Risks**, **Assumptions**, **Actions**, **Issues** and **Dependencies**, each with its open count, **Open** or **Closed**, and a scope: **This plan**, **This feature** or **All**.
- The log fills itself from relay pauses, issues let through at approval, the build record's Known gaps, approved documents' Risks and Assumptions sections, open review findings, manual test checks, documents waiting for review, pull requests and plan headers. Agents add items with `whyline raaid add` as they work.
- Only the user closes an item, with an outcome and a reason, except a few facts whyline closes itself (a paused task finished, a dependency met, a manual check passed, a review done). Judgment outcomes are recorded as `whyline note`s too.
- The **Issues** popup becomes **RAAID → Issues → This plan → Review rounds**. The Issues button opens it there.
- `whyline raaid …` on the command line, the RAAID appendix in the SDLC Export pack, and a RAAID line in `whyline sync`.

Rules every task keeps:
- Console first: every console action saves through the same function the CLI calls.
- No new dependency. Word export reuses `whyline.agents.convert.to_docx`.
- New non-widget code goes in `src/whyline/raaid/`, with tests in `tests/raaid/`. Console code goes in the files a task names, with tests in `tests/console/`.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- Tests never run a real agent, start a relay, or contain "/Users/".
- The log never commits. `.whyline/raaid.jsonl` goes in with the next commit, like `.whyline/decisions.md`.
- An open item never blocks a relay, an approval or a release.

## Part 1: The log

- [ ] RAAID-1: Items and the event file
  Create `src/whyline/raaid/__init__.py`, `src/whyline/raaid/store.py` and `tests/raaid/test_store.py`. Edit `.gitattributes` (create it if missing) to add `.whyline/raaid.jsonl merge=union`.
  1. `Kind` is risk, assumption, action, issue or dependency, with prefixes `RSK`, `ASM`, `ACT`, `ISS`, `DEP` and labels "Risk" … "Dependency". `Severity` for risk is high, medium (default) or low; for issue blocker, major (default) or nit; None for the others.
  2. `Item` has id, kind, title, detail, severity, status (open or closed), outcome, reason, raised_by, raised_at, closed_by, closed_at, source (a dict: `type`, `path`, `line`, `ref`), plan, task, set, key, and history (the events).
  3. `.whyline/raaid.jsonl` holds one JSON event per line: `{"v":1,"event":"add|edit|close|reopen","id":…,"at":…,"by":…, …fields}`. `load(root) -> list[Item]` replays them in file order and skips a line that doesn't parse, counting it in `load_problems(root) -> int`.
  4. `add(root, kind, title, *, detail="", severity=None, source=None, plan=None, task=None, set=None, key=None, by) -> Item`:
     - The id is the prefix plus one more than the highest number of that kind in the file.
     - When `key` is given and an item with that key exists (open or closed), it returns that item and writes nothing.
     - When `task` is given without `plan`, the plan is the `plans/` or `plans/done/` file whose task lines contain that id.
  5. `edit(root, id, *, title=None, detail=None, severity=None, by)`, `close(root, id, *, outcome, reason, by)` and `reopen(root, id, *, reason, by)` append one event each. Close refuses an outcome not in the kind's list (from the design's table) and an empty reason. Reopen refuses an open item.
  6. Two items with the same id after a merge: the later one (by its add event's position in the file) is shown as `<id>b`, then `c`, and `add` numbers on from the highest.
  7. Writes append one line with `os.O_APPEND`, so a running relay's agents and the console can both add.
  Tests: add numbering per kind, key dedupe for open and closed, task-to-plan lookup, each event, close refusals, reopen refusal, the merge suffix, a bad line skipped and counted, and the `.gitattributes` line.
  Review focus (closed): 4's dedupe and 6. Anything else goes in a follow-up RAAID action, not this task.

- [ ] RAAID-2: Closing records a decision
  Create `tests/raaid/test_close_notes.py`. Edit `src/whyline/decisions.py`, `src/whyline/cli.py`, `src/whyline/raaid/store.py` and their tests only.
  1. Move the body of `cli.cmd_note` that builds the note event and writes decisions.md then the ledger into `decisions.record_note(root, *, decision, because, alternatives=(), files=(), actor, role, task, **bound) -> dict`. `cmd_note` keeps its argument handling, errors and exit codes, and calls it. Every existing `whyline note` test passes unchanged.
  2. `store.close` calls `record_note` for the judgment outcomes: risk Accepted, assumption Confirmed or Wrong, action Dropped, issue Accepted (won't fix), dependency Dropped. The decision is `<id> <outcome>: <title>`, because is the reason, actor is `by`, role `raaid`, and task the item's task or `raaid`. It never records a note for Mitigated, Happened, No longer applies, Done, Fixed, Duplicate or Met.
  3. `close` returns `CloseResult(item, follow_up_kind)`, with follow_up_kind issue for risk Happened and for assumption Wrong, else None. The caller offers the follow-up. `close` doesn't add it.
  Tests: record_note writing both stores, cmd_note unchanged, a note for each judgment outcome and none for each fact outcome, and follow_up_kind.

## Part 2: Filling the log

- [ ] RAAID-3: Collecting from the relay
  Create `src/whyline/raaid/collect.py` and `tests/raaid/test_collect.py`.
  1. `collect(root, *, now=None) -> CollectResult` (counts added and closed by kind). It calls each source in this task and the next two, catches and lists a source's error in `CollectResult.problems`, and goes on with the others.
  2. Relay pauses: when `whyline_relay.state.load(root)` returns a state with a `paused_reason`, add an issue `<task_id> paused: <paused_reason>` (first line, at most 120 characters), severity major, source type `relay-pause` with the state's `log_path`, plan the state's `plan`, key `pause:<task_id>:<round>:<sha1 of paused_reason>`, by `whyline`. The relay keeps only the current pause, so this is why the console collects when a relay pauses (RAAID-13). An open pause issue whose task has a later terminal handoff in the ledger is closed as Fixed, reason `task finished`, by `whyline`.
  3. Issues let through: for each task whose last handoff passed with a non-empty `issues` list, add one issue per entry, severity nit, source type `review`, key `review:<task>:<handoff time>:<n>`, by the reviewing actor.
  4. Rounds that were sent back and later passed add nothing.
  Tests with a temporary ledger and a stubbed `state.load`: a pause added once on two collects, a second pause of the same task in a later round added as its own item, the pause closed after the task finishes, issues in a passing round added, sent-back rounds adding nothing, and a failing source listed in problems while the others still run.

- [ ] RAAID-4: Collecting dependencies from plan headers
  Edit `src/whyline/raaid/collect.py` and its tests only.
  1. `plan_dependencies(root) -> list[Dep]` reads the header (the lines before the first `## `) of each `plans/*.plan.md`:
     - In the line that starts `Runs after`, every backticked `plans/<name>.plan.md` before the word `before` is a plan this one waits for; every one after it waits for this one.
     - A line `needs: <package> >= <version>` is a package this plan waits for.
  2. Each pair is one dependency item `<waiter> waits for <target>`, key `dep:<waiter>:<target>`, source the waiter's plan file and line, plan the waiter. It is closed as Met, by `whyline`, when the target plan is in `plans/done/`, or when `importlib.metadata.version(package)` is at least the version, compared as integers part by part (a missing package is not met).
  3. PRD waits: when `product.claim_holder(root)` is set, every other set with a PRD update in draft adds `<set> waits for <holder>'s PRD update`, key `dep:prd:<set>:<holder>`, closed as Met when that claim is released.
  Tests: before and after `before`, the same pair found from both plans once, `needs:` met and unmet and missing, the done-plan close, and the PRD wait with its close.

- [ ] RAAID-5: Collecting from document sets
  Edit `src/whyline/raaid/collect.py` and its tests only.
  For each document set (`library.sets(root)`, reading each set's `docset.json` in `workspace.docs_root(root)`):
  1. Approved PRD, spec or design: each bullet in its `## Risks` section is a risk, and each in `## Assumptions` an assumption (sections from `templates.sections`, bullets are lines starting `- `). Key `doc:<slug>:<kind>:<section>:<sha1 of the bullet text>`, source the document and line, set the slug, by the document's writer. `Not applicable — …` lines add nothing.
  2. At approval, the latest fresh-eyes review's 🟡 Major findings, and any 🔴 Blocker the user approved over, become risks (Major → medium, Blocker → high), key `finding:<slug>:<kind>:<version>:<n>`.
  3. The build record's Known gaps: one issue per requirement, severity major, key `gap:<slug>:<R-id>`.
  4. Actions:
     - each manual test case in the approved test plan, key `manual:<slug>:<case id>`, closed as Done by `whyline` when the build inputs show it passed
     - a set with a document in review: `Review the <kind> for <set name>`, key `review-wait:<slug>:<kind>:<version>`, closed as Done when that version is approved, or Dropped when the set is stopped
     - a set with a pull request URL and no merge: `Merge or close <url>`, key `pr:<slug>`, closed only by the user
  Tests with a temporary set: each source added once across two collects, a Not applicable line skipped, the finding severities, Known gaps, each action and its close.

- [ ] RAAID-6: An Assumptions section in the templates
  Edit `src/whyline/sdlc/templates/prd.md`, `spec.md`, `short-spec.md`, `design.md` and `tests/sdlc/test_templates.py` only.
  Add `## Assumptions` before `## Risks` (or last, when there is no Risks section), with the line `Calls this document makes that nobody confirmed. One per line, starting "- ".` Overrides in `.whyline/sdlc/templates/` are not changed.
  Tests: each built-in template has the section in that place, and an override without it still loads.

- [ ] RAAID-7: Agents add items, and sync shows them
  Edit `src/whyline/agentsmd.py`, `src/whyline/sync.py` and their tests only.
  1. `agentsmd.INSTRUCTION` gets a section before `## Handing off active work`:

         ## RAAID log

         When you make a call the plan or spec didn't, add it as an assumption.
         When you leave something for later, add it as an action. When you see
         a risk, add it as a risk. Never close an item: the user does.

             whyline raaid add assumption "<one line>" --task <task-id> --by <agent>

     The block stays one managed block, so `whyline init` and its refresh install it.
  2. `sync.compose` adds one line after the decisions when anything is open: `RAAID: 2 risks, 5 assumptions, 1 issue open (whyline raaid list)`, in kind order, kinds with none left out. With `task` given, it lists that task's open items under it, at most 5, then `… and N more`. It fits inside the existing token budget and is dropped first in compact mode.
  Tests: the managed block text, an existing AGENTS.md updated in place, the sync line, the task list and its limit, and nothing printed when the log is empty or missing.

## Part 3: CLI and export

- [ ] RAAID-8: `whyline raaid` CLI
  Create `src/whyline/raaid/cli.py` and its tests. Edit `src/whyline/cli.py` to register it.
  Subcommands, each calling the store and collect functions:
  - `list [--kind K] [--closed | --all] [--plan PLAN | --set SLUG]`: one line per item, `ISS-7 · major · <title> · <task> · <by> · <age>`
  - `show <id>`: every field and the history
  - `add <kind> "<title>" [--detail] [--severity] [--task] [--set] [--plan] [--by]`: `--by` defaults to `you` when stdin is a terminal, else `agent`. Prints the id.
  - `edit <id> [--title] [--detail] [--severity]`
  - `close <id> --as <outcome> --because "<reason>" [--yes]`: asks `Close <id> as <outcome>?` in a terminal unless `--yes`. Without a terminal it refuses unless `--yes`. It prints the follow-up hint when there is one: `Raise a follow-up issue: whyline raaid add issue "<title>"`.
  - `reopen <id> --because "<reason>"`
  - `collect`: prints the counts and any problems
  Each prints plain lines and exits non-zero with the refusal text.
  Tests: each subcommand, the terminal and non-terminal close paths, and a refusal's exit code.

- [ ] RAAID-9: Export, and the RAAID appendix in the Export pack
  Create `src/whyline/raaid/export.py` and its tests. Edit `src/whyline/sdlc/export.py`, `src/whyline/raaid/cli.py` and their tests only.
  1. `to_markdown(items, *, title) -> str`: one section per kind, open items first then closed, each as a table: Id, Severity, Title, Source, Raised, Status (outcome and reason when closed).
  2. `export(root, out_dir) -> ExportResult` writes `raaid-log.md` and `raaid-log.docx` (through `to_docx`), default out_dir `~/Downloads`. `whyline raaid export [--out DIR]` calls it.
  3. The SDLC Export pack adds an appendix **RAAID log** after the fresh-eyes reviews, with the set's items only (open and closed). It is left out when the set has none.
  Tests: the Markdown tables, both files written with a stubbed to_docx, the appendix position and its absence for a set with no items.

## Part 4: Console

- [ ] RAAID-10: The RAAID tab
  Create `src/whyline/console/raaid_tab.py` and `tests/console/test_raaid_tab.py`. Edit `src/whyline/console/tui.py` only to add `#file-raaid` next to `#file-chat` and mount the panel the way `RelayChatPanel` is mounted.
  1. The button shows when the repository is set up for whyline, in every mode.
  2. The panel has the five sub-tabs with open counts (`Risks 2`), an **Open**/**Closed** switch, and a scope select (**This plan**, **This feature**, **All**, default All). This plan uses `file_pane.active_plan_file`; This feature the set whose `docset.json` plan path is that plan. With no active plan, those two are disabled.
  3. A list, newest first, and under it the selected item's detail: title, detail, severity, source with **Open source** (opens the path at the line in the file view), raised by and when, and the history.
  4. It reloads on opening and when `.whyline/raaid.jsonl` changes (the file-follow mtime check the Files pane already uses). Opening runs `collect` in a thread worker first, with `Collecting…` in the panel header.
  5. With an empty log, it says `Nothing yet. Risks, assumptions, actions, issues and dependencies appear here as agents and reviews raise them.`
  Tests: the counts, the switch and scope filtering, the disabled scopes with no plan, Open source, the reload, and the empty text.

- [ ] RAAID-11: Add, Edit, Close and Reopen in the tab
  Edit `src/whyline/console/raaid_tab.py` and its tests only.
  1. **Add**: a small form with kind (the current sub-tab's, changeable), title, detail, severity for risk and issue, and task (prefilled with the relay's current task when there is one). It calls `store.add(..., by="you")`.
  2. **Edit** calls `store.edit`.
  3. **Close…**: the kind's outcomes as choices and a reason field (required). It calls `store.close(..., by="you")`. When the result has a follow-up kind, it asks `Raise a follow-up <kind>?` and opens Add prefilled with `Follow-up to <id>: <title>`.
  4. **Reopen** asks for a reason and calls `store.reopen`.
  5. **Copy** copies `<id> · <title>`, plus the detail, through the console's existing copy.
  6. Buttons show only when they apply (Close on open items, Reopen on closed).
  Tests with stubs: each action calling the store with `by="you"`, the required reason, the follow-up offer and its prefill, and button visibility.

- [ ] RAAID-12: Review rounds in the tab, and the Issues button
  Edit `src/whyline/console/raaid_tab.py`, `src/whyline/console/relay_screens.py`, `src/whyline/console/tui.py` and their tests only.
  1. On **Issues** with scope **This plan**, a **Review rounds** section sits above the list: a task select (the plan's tasks, default the relay's current task), and the text from `relay_screens.issues_text(relay_ops.task_rounds(root, task))` in a read-only text area, with **Copy all** and **Copy selected issue** working as in the popup.
  2. The Relay screen's **Issues** button opens the Files pane on RAAID → Issues → This plan with the current task selected. It keeps its enabled rule.
  3. Remove `IssuesScreen` and its tests. Keep `issues_text` and its tests.
  Tests: the section only on Issues with This plan, the task select changing the text, both copy buttons, and the Issues button opening the tab on the right task.

- [ ] RAAID-13: When the log collects, and RAAID in Docs
  Edit `src/whyline/console/tui.py`, `src/whyline/console/docs_screen.py`, `src/whyline/sdlc/library.py` and their tests only.
  1. The console runs `collect` in a thread worker when a relay task finishes or pauses, when a relay plan finishes, and after an SDLC document is approved. A collect that adds items shows one line in the relay log: `RAAID: 2 added (1 risk, 1 action)`. A collect's problems are shown once each, not on every run.
  2. In Docs, each set's summary adds `RAAID <n> open` when it has any, and the selected set has **Show in RAAID**, which opens the tab on This feature.
  Tests with stubs: each trigger calling collect once, the log line, a problem shown once, the summary count, and Show in RAAID.

## Part 5: Docs and release

- [ ] RAAID-14: Docs
  Edit `README.md` where it describes the Files pane and Relay's Issues, `docs/sdlc.md`, and create `docs/raaid.md`.
  Cover:
  - what each kind is for, with one example each from agentic work
  - what fills the log by itself, and what agents add
  - who closes items, the outcomes, and which ones become decisions
  - the tab, its scopes, and where the Issues popup went
  - the `whyline raaid` commands, the `needs:` plan-header line, and the Export pack appendix
  - that the log lives in `.whyline/raaid.jsonl`, merges with union, and is committed with your next commit
  Verify with `uv run pytest -q`.
