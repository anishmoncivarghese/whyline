# RAAID log: risks, assumptions, actions, issues and dependencies for a repository

Status: draft for review, 2026-11-09. Runs after `plans/sdlc-pipeline.plan.md`.

## Problem

A team running an SDLC keeps a RAID log. Whyline has the pieces of one, but they are scattered and most of them disappear:

- **Issues** live in the relay's **Issues** popup. It shows one task's review rounds and forgets them once the task finishes. Nothing lists the problems a whole plan or repository still carries.
- **Risks** sit in design docs (Risks section) and in fresh-eyes review findings (GFR). Nobody sees them again after the document is approved.
- **Assumptions** are the calls an agent made without asking: "my call" choices, "Left to the builder", defaults picked in a brainstorm. In agentic work these are the most important thing to review, and today they are the hardest to find.
- **Actions** are follow-ups: "goes in a follow-up note, not this task" in a plan's review focus, manual test checks, a document waiting for your review, a pull request waiting for a merge, a `whyline note` still to write. They live in agent summaries and in the user's memory.
- **Dependencies** are written as prose in plan headers ("Runs after `plans/safe-pause.plan.md`", "Needs whyline-relay with RPZ-1..4") and in the one-PRD-update-at-a-time rule. Nothing says which are met.

## Why it matters more with agents

Agents work faster than a person can read, and they make many small decisions on the way. A log is worth keeping only if it doesn't need keeping by hand. So the rule for this design is: **agents and whyline fill the log; the user reviews and closes.** The value is that every silent call and every loose end becomes one row the user can look at, accept or act on, and that agents starting a session see the open ones.

## What the user gets

### A RAAID tab

- A **RAAID** button in the Files pane next to **Chat**: `Working file · Plan · All files · Chat · RAAID`. It shows for any repository set up for whyline, in every mode.
- Inside, five sub-tabs with their open counts: **Risks 2 · Assumptions 5 · Actions 3 · Issues 1 · Dependencies 4**.
- On each sub-tab:
  - **Open** (default) or **Closed**
  - a scope: **This plan** (the active plan), **This feature** (the document set that owns the active plan) or **All** (the repository), default All
  - a list, newest first, each row `ISS-7 · 🟡 Major · Install fails on Python 3.11 · SDLC-12 · grok · 2h ago`
  - the selected item's detail: title, detail text, source with **Open source** (opens the file in the file view at the right line), who raised it and when, and its history (raised, edited, closed, reopened)
  - buttons: **Add**, **Edit**, **Close…**, **Reopen**, **Copy**
- **Close…** asks for an outcome from the kind's list and a one-line reason. Outcomes:

  | Kind | Outcomes |
  |---|---|
  | Risk | Mitigated · Accepted · Happened · No longer applies |
  | Assumption | Confirmed · Wrong · No longer applies |
  | Action | Done · Dropped |
  | Issue | Fixed · Accepted (won't fix) · Duplicate |
  | Dependency | Met · Dropped |

  - **Happened** (risk) and **Wrong** (assumption) offer to raise a follow-up Issue or Action with the text filled in.
  - Outcomes that are a judgment call (Accepted, Confirmed, Wrong, Dropped, Accepted (won't fix)) are also recorded as a `whyline note`, so they show in decisions and in the build record. Outcomes that are facts (Fixed, Done, Met, Mitigated, Duplicate, No longer applies) are not.

### The Issues popup moves into the tab

- **RAAID → Issues → This plan** gets a **Review rounds** section: today's round-by-round view for the current task (`Round 1 · claude → grok · ✓ passed · 0 issues`, the issues and the tests), with a task select to look at any task in the plan, and **Copy all** and **Copy selected issue** as today.
- The **Issues** button on the Relay screen stays. It opens the RAAID tab on that view instead of the popup. The popup is removed.
- The review rounds stay a history, not log items: issues sent back and fixed inside the review loop are not added to the log. Only what is left over is (see the sources below).

### What fills the log automatically

`collect(root)` reads these sources. It runs when the tab opens, when a relay task finishes or pauses, when a relay plan finishes, and after an SDLC document is approved. Every collected item has a stable key, so collecting again never duplicates it, and a closed item is never reopened by a collection.

| Kind | Source | Closes by itself when |
|---|---|---|
| Issue | A relay pause (stuck, round cap, refused command, preflight failed), with the pause reason | the task finishes (`Fixed`, by whyline) |
| Issue | Issues listed in the round that approved a task (notes the reviewer let through) | never: you close them |
| Issue | The build record's Known gaps: one per requirement that didn't pass | never |
| Risk | Bullets of the Risks section in an approved PRD, spec or design | never |
| Risk | 🟡 Major fresh-eyes findings still open when a document is approved, and 🔴 Blockers you approved over | never |
| Assumption | Bullets of the new **Assumptions** section in an approved PRD, spec or design | never |
| Action | Manual test cases in an approved test plan | the case is ticked passed |
| Action | A document set waiting for your review (`Review the Spec for Job search 5`) | it is approved or stopped |
| Action | A pull request opened from Docs (`Merge or close PR #…`) | never: you close it |
| Dependency | Plan headers: the `Runs after` line and `needs:` lines (below) | the plan it waits for is in `plans/done/`, or the installed package meets the version (`Met`, by whyline) |
| Dependency | A set waiting for another set's PRD update | that update is approved |

Reading plan headers for dependencies:

- In the line that starts `Runs after`, every backticked `plans/<name>.plan.md` before the word `before` is a plan this plan waits for. Every one after `before` is a plan that waits for this one. Each pair is one item, keyed by the two plan names, so it is found once from either plan.
- A new optional header line, `needs: <package> >= <version>` (for example `needs: whyline-relay >= 0.2.43`), is a package this plan waits for. It is met when `importlib.metadata.version(<package>)` is at least that version, compared as numbers part by part.
- Prose such as "Needs whyline-relay with RPZ-1..4" is not read. Plans written from now on add a `needs:` line.

Each item records the plan, task and document set it belongs to when the source gives them. An item added with `--task` alone gets its plan by finding that task id in `plans/` and `plans/done/`. **This plan** shows items whose plan is the active plan; **This feature** shows items whose set owns the active plan.

Severity: Risks are High, Medium (default) or Low. Issues are 🔴 Blocker, 🟡 Major (default) or 🟢 Nit, as in fresh-eyes reviews. Other kinds have none.

Only these whyline-made closes happen without the user, and each is shown as `closed by whyline: <reason>`. Everything else is closed by the user.

### Agents add items as they work

- The managed block whyline writes into `AGENTS.md` gets a short **RAAID** section: when you make a call the plan didn't, add an assumption; when you leave something for later, add an action; when you spot a risk, add a risk; never close an item.

      whyline raaid add assumption "Treat an empty plans/done as no finished plans" --task SDLC-7 --by grok

- The plans' review-focus rule changes from "goes in a follow-up note" to "goes in the RAAID log as an action" for new plans. Existing plans are not rewritten.
- `whyline sync` prints one line when anything is open, for example `RAAID: 2 risks, 5 assumptions, 1 issue open (whyline raaid list)`, and lists the open items for the task it was given.

### The log in Docs and exports

- Each document set in Docs shows its open count (`RAAID 3 open`) and a link to the tab filtered to that feature.
- The SDLC **Export pack** adds an appendix **RAAID log** with the set's open and closed items.
- `whyline raaid export` writes the whole log as Markdown and Word.

### CLI (console first: each calls the same function the tab calls)

- `whyline raaid list [--kind K] [--closed | --all] [--plan PLAN | --set SLUG]`
- `whyline raaid show <id>`
- `whyline raaid add <kind> "<title>" [--detail TEXT] [--severity S] [--task ID] [--set SLUG] [--plan PLAN] [--by NAME]`. `--by` defaults to `you` in a terminal and `agent` otherwise.
- `whyline raaid edit <id> [--title] [--detail] [--severity]`
- `whyline raaid close <id> --as <outcome> --because "<reason>" [--yes]`. In a terminal it asks for confirmation unless `--yes`. Without a terminal (an agent) it refuses unless `--yes`, and the AGENTS.md section tells agents never to close.
- `whyline raaid reopen <id> --because "<reason>"`
- `whyline raaid collect`
- `whyline raaid export [--out DIR]`

## Storage

- One append-only file, `.whyline/raaid.jsonl`, committed like `.whyline/decisions.md`. Each line is an event: `add`, `edit`, `close` or `reopen`, with the item id, the time and who did it. The current state of an item is its events replayed in order.
- `.gitattributes` gets `.whyline/raaid.jsonl merge=union`. Two branches that both added items merge cleanly, because every line stands alone and ids can't clash (below).
- Ids are the kind prefix plus a number: `RSK-3`, `ASM-12`, `ACT-4`, `ISS-7`, `DEP-2`. The number is the next free one in this checkout. When a merge brings two items with the same id, the later one is shown with a suffix (`ISS-7b`) and the next add continues after the highest number. Lines are never rewritten.
- Whyline doesn't commit the file itself. Like decisions.md, it goes in with the next commit, which during a relay is the relay's own task commit.

## Goals

- One place for every open risk, assumption, action, issue and dependency in a repository, with open and closed apart.
- Filled by agents and whyline, closed by the user.
- Agents see the open items when they start.
- Nothing lost between a task, a plan and a feature.

## Non-goals

- Owners, due dates, reminders or a board. A row says who raised it, not who must do it.
- A risk score (likelihood × impact). A risk has one severity: High, Medium or Low.
- Syncing with GitHub Issues, Jira or another tracker.
- Rewriting existing plans' review-focus lines.

## Anti-goals

- A log the user has to keep up by hand. If an item can be collected, it is collected.
- Flooding: issues fixed inside the review loop never become items, and collecting twice never adds twice.
- Agents closing their own risks or assumptions.
- Blocking work. An open item never stops a relay, an approval or a release. The log only shows.

## Constraints

- Console first, as every whyline feature.
- No new dependency. Word export reuses `whyline.agents.convert.to_docx`.
- No commits by the log itself, and nothing written while collecting except new events.
- Works with no document sets and no relay history: the tab is then empty with one line on what fills it.

## How it fits the code today

- **Issues popup:** `relay_screens.IssuesScreen` and `issues_text(rounds)`, opened by `tui._open_issues` from `relay_ops.task_rounds(root, task)`, which reads handoff events from the ledger. `issues_text` is kept and reused in the Review rounds section. `IssuesScreen` is removed.
- **Files pane:** the tab buttons `#file-working`, `#file-plan`, `#file-all` and `#file-chat` in `tui.py`. `#file-raaid` is added the same way, with its panel in a new `console/raaid_tab.py`, like `relay_chat_tab.RelayChatPanel`.
- **Decisions:** `cli.cmd_note` builds the note event and writes decisions.md, then the ledger. Its body moves into `decisions.record_note(root, *, decision, because, alternatives, files, actor, role, task) -> dict`, which `cmd_note` and the RAAID close both call.
- **AGENTS.md:** `agentsmd.INSTRUCTION` is the managed block. The RAAID section is added there, so `whyline init` and its refresh install it.
- **Sync:** `sync.compose` gets the RAAID line.
- **SDLC sources** (from `plans/sdlc-pipeline.plan.md`): approved documents in `docs/sdlc/<slug>/`, fresh-eyes reviews in `reviews/<kind>-v<N>.md` (`goldfish.latest_review`), the build record's Known gaps (`record.py`, TRC-2), the test plan's manual cases, `close.open_pr`'s saved PR URL, `product.claim_holder`, and `templates.sections`.
- **Templates:** an `## Assumptions` section is added to the built-in PRD, spec, short-spec and design templates (SDLC-8), with the line `Calls this document makes that nobody confirmed. One per line.`
- **New code:** `src/whyline/raaid/` (`store.py`, `collect.py`, `cli.py`, `export.py`) with tests in `tests/raaid/`, and `src/whyline/console/raaid_tab.py` with tests in `tests/console/`.

## Left to the builder

- Row layout and colours in the tab, within the existing console style.
- How the detail pane lays out the item history.
- The wording of collected titles, as long as each names its source.

## Calls I made (please check)

- The tab is repository-wide with a scope filter, rather than one log per plan.
- The log lives in `.whyline/raaid.jsonl` in the checkout, merged with union, not in the default-branch docs checkout. Items raised during a relay go in with the relay's commits, like decisions.
- Only whyline-made facts close by themselves (a paused task that finished, a met dependency, a ticked manual check, an approved review). Everything else waits for the user.
- Judgment outcomes are also `whyline note`s; factual ones are not.
- The Issues popup is removed and its view moves into the tab; the Issues button stays as a shortcut.
