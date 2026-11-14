<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-sdlc-upgrade-design.md | created: 2026-11-14T20:30:00+05:30 -->
# SDLC product owner: acceptance criteria, a backlog and an Accept step

Spec: `docs/superpowers/specs/2026-11-14-sdlc-upgrade-design.md`, Part 2. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **Send back reopens tasks by unticking them in the plan** and recording why. It does not start the relay; the user presses Run.
- **Evidence in the Accept table** is the test plan's scenarios and their state in this plan. Whyline-read test results and demo captures arrive with `plans/sdlc-evidence.plan.md`.

Runs after `plans/sdlc-git-flow.plan.md`, and before `plans/sdlc-evidence.plan.md`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: there is a PRD writer, but nothing says what "met" means for a requirement, nothing orders what to build next, and no step lets the user accept the result against what was asked.

What the user gets:
- Each requirement has acceptance criteria (`R1.A1: Given … when … then …`), and a spec can't be approved without them.
- A backlog with Now, Next and Later, fed from ideas, RAAID actions and typed rows, with a **Groom** action that proposes an order.
- An **Accept** step after the build: the criteria, a product owner agent's reading of each, and **Accept**, **Accept with follow-ups** or **Send back**.

Rules every task keeps:
- **Console first.** Every action is in Docs in the console and saves through the same function as its `whyline docs …` command.
- **The agent proposes; the user decides.** Grooming changes no row and the agent's reading accepts nothing until the user presses a button.
- **Product owner turns are read-only**, through `capabilities.read_only_command`, on enabled providers that pass `can_run_unattended`. Documents, ideas and RAAID text are data inside labelled blocks.
- **Small stays small.** A Small set needs one criterion per requirement and has no backlog or PRD step forced on it.
- **Existing document sets keep working.** A set approved before this plan has no criteria; it is shown as `no criteria (older set)` and can still be built, closed and exported.
- **Nothing here commits while a relay runs in the checkout** (the existing `sdlc.guard` rule).
- **No new dependency.**
- **Tests:** never invoke a real provider, `gh` or a relay. Use temporary folders and fakes. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A spec with a requirement that has no criterion can't be approved, and the message names the requirement. PO-1, `test_requirement_without_criterion_blocks_approval`.
- A set approved before this plan still loads, builds and closes. PO-1, `test_older_set_without_criteria_still_works`.
- Grooming never reorders or edits the backlog by itself. PO-3, `test_groom_only_proposes`.
- Nothing is recorded as accepted without the user's button, whatever the agent's reading says. PO-4, `test_agent_reading_never_accepts`.
- Send back unticks only the tasks that cover the named criteria. PO-4, `test_send_back_reopens_only_covering_tasks`.

- [ ] PO-1: Acceptance criteria in the documents and in trace
  Edit `src/whyline/sdlc/trace.py`, `src/whyline/sdlc/templates/prd.md`, `spec.md`, `short-spec.md`, `design.md`, `src/whyline/sdlc/review.py`, the writer prompt in `src/whyline/sdlc/runner.py`, and their tests.
  1. `trace.criteria(text) -> dict[str, list[Criterion]]`: under an `Acceptance criteria` heading, lines `R<n>.A<m>: <text>` (`Criterion` has `id`, `requirement`, `text`). A criterion for a requirement not in `trace.requirements(text)` is returned under the key `""`.
  2. The templates get an `## Acceptance criteria` section with one example line and the sentence `Every requirement needs at least one. Write each as: Given … when … then …`.
  3. The writer prompt for spec, short spec and design asks for criteria for every requirement. The PRD template has the section as optional.
  4. `review.approve` for `spec` and `design` refuses when a requirement in scope has no criterion: `R3 has no acceptance criterion`. It also refuses a criterion whose requirement doesn't exist: `R9.A1 names a requirement that isn't listed`. A set whose spec was approved before this change is not re-checked.
  5. `trace.Coverage` gains `criteria: list[str]` and `no_criteria: list[str]` (requirements without one), and its summary line mentions them.
  Tests: `test_requirement_without_criterion_blocks_approval`, `test_older_set_without_criteria_still_works`, parsing with several criteria per requirement, the orphan criterion, a Small set with one requirement and one criterion approved, and the coverage summary.

- [ ] PO-2: The backlog
  Create `src/whyline/sdlc/backlog.py` and `tests/sdlc/test_backlog.py`. Edit `src/whyline/sdlc/cli.py` and its tests.
  1. `docs/product/backlog.md` in the docs checkout, a Markdown table whyline reads and rewrites: `ID` (`B1`, `B2`…), `Title`, `Outcome` (one line), `Priority` (`Now`, `Next`, `Later`), `Size` (`Small`, `Feature`, `Large`), `Source`, `Status` (`open`, `planned:<slug>`, `done`, `dropped`). Text a user wrote above or below the table is kept.
  2. `backlog.rows(docs)`, `backlog.add(docs, *, title, outcome, priority="Later", size="Feature", source="typed") -> Row`, `backlog.update(docs, row_id, **fields)`, `backlog.move(docs, row_id, before_id | None)` (order within a priority), `backlog.drop(docs, row_id, reason)`.
  3. A `|` or a line break in a field is replaced so the table can't break. Title is cut to 80 characters and outcome to 200.
  4. `backlog.from_idea(docs, idea)` and `backlog.from_raaid(docs, item)` add a row with the source `idea <id>` or `RAAID <id>`. The same source is never added twice. `from_raaid` is available only when `whyline.raaid` is importable.
  5. CLI: `whyline docs backlog list`, `add "<title>" --outcome … [--priority …] [--size …]`, `set <id> <field> <value>`, `move <id> [--before <id>]`, `drop <id> --reason …`.
  Tests: round trip, the user's surrounding text kept, a `|` in a title, ids never reused after a drop, `move` within and across priorities, no duplicate source, and each CLI command calling its function.

- [ ] PO-3: The product owner role, and Groom
  Create `src/whyline/sdlc/owner.py` and `tests/sdlc/test_owner.py`. Edit `src/whyline/sdlc/stages.py`, `src/whyline/sdlc/docset.py` (roles), `src/whyline/sdlc/cli.py` and their tests.
  1. A `product_owner` role on a document set and as a repository default (kv or the docs settings the other roles use). Default: the writer. `stages.stages_line` shows `Product owner (<agent>)` first and `Accept (<agent>, you decide)` last.
  2. `owner.groom(docs, *, agent, run_fn=None) -> Proposal | None`: one read-only turn given the open Now and Next rows and the product PRD's goals. It returns an order for those rows and one reason line each (at most 200 characters). Rows it names that don't exist are dropped. Rows it leaves out keep their place after the named ones. None when the agent gives nothing readable.
  3. `owner.apply(docs, proposal)` reorders through `backlog.move`. It is called only from the user's **Use this order**.
  4. CLI: `whyline docs backlog groom` prints the proposal and asks `Use this order? [y/N]`. `--yes` applies it.
  Tests: `test_groom_only_proposes` (the file is unchanged after `groom`), unknown rows dropped, unnamed rows kept in place, the reason cut, `apply` reorders, and the Stages line.

- [ ] PO-4: The Accept step
  Create `src/whyline/sdlc/accept.py` and `tests/sdlc/test_accept.py`. Edit `src/whyline/sdlc/owner.py`, `src/whyline/sdlc/record.py`, `src/whyline/sdlc/stages.py`, `src/whyline/sdlc/cli.py` and their tests.
  1. `accept.table(root, docs, docset) -> list[Line]`: one line per criterion with its requirement, the test plan scenarios that cover the requirement and their state (passed, failed, open manual check), and the tasks that cover it (`trace.plan_covers`).
  2. `owner.read(root, docs, docset, *, agent, run_fn=None) -> dict[str, Reading]`: one read-only turn given the table, the build record and the diff stat. Per criterion: `met`, `not met` or `can't tell`, and a reason of at most 200 characters. A criterion it doesn't mention is `can't tell`.
  3. `accept.decide(root, docs, docset, decision, *, by, follow_ups=(), criteria=(), reason="") -> Outcome`:
     - `accept`: marks the set accepted with the time and who.
     - `follow_ups`: the same, and each follow-up becomes a backlog row (source `follow-up <slug>`) and, when `whyline.raaid` is importable, a RAAID action.
     - `send_back`: needs at least one criterion and a reason. It unticks, in the plan file, the tasks whose covers line includes those criteria's requirements, and appends `Sent back <date>: <criteria> — <reason>` to the build record. The set is not accepted.
     - Each decision is recorded with `whyline note` (`--actor <by> --role product-owner`).
  4. `stages.next_stage` returns an `accept` stage after `release` (or after `review` when the set doesn't release) and before the set can be closed. `sdlc.close.close` refuses an unaccepted set with `Accept it first, or close with --unaccepted`, and `--unaccepted` records that in the build record. A set with no criteria (an older set) skips the stage.
  5. The build record gets an `## Acceptance` section: the table, the readings, and the decision.
  6. CLI: `whyline docs accept <slug>` prints the table and readings. `--accept`, `--follow-up "<text>"` (repeatable) and `--send-back R1.A2 [--send-back …] --reason "<text>"` decide.
  Tests: `test_agent_reading_never_accepts`, `test_send_back_reopens_only_covering_tasks`, follow-ups create backlog rows once, close refused until accepted and `--unaccepted`, an older set skips the stage, the note recorded, and the Acceptance section.

- [ ] PO-5: Backlog and Accept in the Docs screen
  Edit `src/whyline/console/docs_screen.py`, `src/whyline/console/tui.py` (the Plan form's prefill), and their tests.
  1. A **Backlog** entry in the left column of Docs: the rows grouped by priority, **Add**, **Edit**, **Up**/**Down**, **Now**/**Next**/**Later**, **Drop**, **Groom** (shows the proposed order with reasons and **Use this order** / **Keep mine**), and **Plan this**, which opens the Plan form with the name, description and size filled in and marks the row `planned:<slug>` when the set is created.
  2. In the Idea Inbox screen and the RAAID tab (when present), **To backlog** on a selected idea or action calls `backlog.from_idea` / `from_raaid`.
  3. For a set waiting at the `accept` stage, Docs shows the table with the agent's reading per line, **Read again**, **Accept**, **Accept with follow-ups…** (one line per follow-up) and **Send back…** (tick the criteria, type the reason). Each calls `accept.decide`.
  4. While a relay runs in the docs checkout these actions are off, as the Docs screen's other actions are.
  Tests: each button calls the function its CLI command calls, **Plan this** prefills and marks the row, Send back needs a criterion and a reason, and the actions are off during a relay.

- [ ] PO-6: Docs
  Edit `docs/sdlc.md` (or the page that documents the pipeline) and `README.md` only.
  Cover: acceptance criteria and how to write one, the backlog and its sources, Groom, the Accept step and its three outcomes, what Send back does, and how older sets behave.
  Verify with `uv run pytest -q`.
