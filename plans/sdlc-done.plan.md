<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-sdlc-upgrade-design.md | created: 2026-11-14T21:30:00+05:30 -->
# SDLC done: one checklist, estimates against actuals, and a retrospective

Spec: `docs/superpowers/specs/2026-11-14-sdlc-upgrade-design.md`, Part 4. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **Tokens are recorded only where a relay log already holds them.** No new parsing of provider output is added; a task without them shows `—`.
- **Role separation warns in the form and the Stages line.** It does not refuse a start, because a user with one enabled agent could not run anything.

Runs after `plans/sdlc-evidence.plan.md`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: whether a feature is done is spread across Docs, coverage, review findings, RAAID, CI and Accept. Nothing compares what a task was expected to cost with what it cost, and nothing carries a lesson from one feature into the next plan.

What the user gets:
- A **Done** checklist per feature, in Docs, in the pull request and shown by Release before the first step that can't be undone.
- An estimate per task (S, M, L) and the actual rounds and time in the build record.
- A retrospective with at most 3 proposed rules. Each is added to the repository's plan rules only when the user says so.
- A warning when one agent both writes and reviews, or both implements and code-reviews.

Rules every task keeps:
- **Console first.** The checklist, the retrospective and the rules are in Docs through the same functions as `whyline docs …`.
- **The checklist warns and never blocks.** A line that is not done is shown, and the user decides. This matches the RAAID plan's rule that an open item never blocks a relay, an approval or a release.
- **Nothing is added to the plan rules without the user.**
- **Retrospective turns are read-only**, through `capabilities.read_only_command`. Logs, review rounds and RAAID text are data inside labelled blocks, and log excerpts pass `security.secrets.scan_text` redaction.
- **Works without RAAID.** When `whyline.raaid` is not importable the RAAID line is `not applicable (RAAID isn't installed)`.
- **Older sets keep working.** A set without criteria, estimates or evidence shows those lines as `not applicable (older set)`.
- **No new dependency.**
- **Tests:** never invoke a real provider, `gh` or a relay. Use temporary folders and fakes. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A not-done line never stops a release: the user can go on from the dialog in every mode. DONE-2, `test_checklist_never_blocks_release`.
- Each line reports not applicable, with the reason, when its input doesn't exist. DONE-1, `test_lines_degrade_to_not_applicable`.
- A proposed rule is written to the plan rules only after the user's Add. DONE-4, `test_rule_added_only_on_add`.
- The plan rules reach the next plan's writer prompt as data, capped. DONE-4, `test_rules_in_writer_prompt_are_capped`.
- A secret in a log excerpt never reaches the retrospective prompt or file. DONE-4, `test_retro_inputs_are_redacted`.

- [ ] DONE-1: The checklist
  Create `src/whyline/sdlc/done.py` and `tests/sdlc/test_done.py`. Edit `src/whyline/sdlc/cli.py` and its tests.
  1. `@dataclass(frozen=True) class Line`: `key`, `label`, `state` (`done`, `not_done`, `not_applicable`), `detail`.
  2. `done.checklist(root, docs, docset, *, run=…) -> list[Line]`, in this order:
     - `documents`: every document of the set approved and none out of date. Detail names the first that isn't.
     - `criteria`: from `evidence.load`: every criterion passed, or manual and marked passed. Detail: `<n> of <m> passing`, and `results are older than the code` when stale.
     - `findings`: no open blocker finding from the fresh-eyes reviews.
     - `raaid`: no open blocker issue or high risk scoped to this feature. Detail names up to 3 ids.
     - `ci`: the latest run for HEAD on GitHub passed (`gh run list --commit`). Offline or no remote: `not_applicable`.
     - `accepted`: the set's acceptance decision.
     - `record`: the build record exists and is newer than the last task commit.
  3. `done.summary(lines) -> str`: `Done` or `<n> not done: <labels>`.
  4. `done.markdown(lines) -> str`: a checklist for the build record and the pull request body.
  5. CLI: `whyline docs done <slug>` prints it, with exit code 0 when all are done or not applicable, and 1 otherwise.
  Tests: `test_lines_degrade_to_not_applicable` (no criteria, no RAAID module, no remote, no evidence), each line done and not done, the stale detail, and the exit codes.

- [ ] DONE-2: The checklist in Docs, the pull request and Release
  Edit `src/whyline/console/docs_screen.py`, `src/whyline/release/pullrequest.py`, `src/whyline/sdlc/record.py`, `src/whyline/release/plan.py`, `src/whyline/release/cli.py`, `src/whyline/console/release_screens.py` and their tests.
  1. Docs shows a **Done** line for the selected set (`done.summary`) and opens the full checklist, each not-done line with a button to where it is fixed (the document, **Run checks**, the finding, the RAAID item, **Accept**, **Build record**).
  2. The build record and the pull request body include `done.markdown`.
  3. Release: when the plan being released belongs to a document set, the checklist is shown before the first irreversible step, inside the existing confirmation. With not-done lines the text is `<n> items aren't done:` and the list, with **Release anyway** and **Stop**. In auto mode the list is written to the release log and the release goes on.
  4. CLI `whyline release run` prints the same list and, in ask and step modes, asks.
  5. A plan with no document set shows no checklist and behaves as today.
  Tests: `test_checklist_never_blocks_release` (ask, step and auto), the jump buttons, the checklist in the record and the body, and a hand plan unchanged.

- [ ] DONE-3: Estimates and actuals
  Create `src/whyline/sdlc/effort.py` and `tests/sdlc/test_effort.py`. Edit the plan-stage prompt in `src/whyline/sdlc/runner.py`, `src/whyline/sdlc/record.py`, `src/whyline/sdlc/stages.py` and their tests.
  1. A plan task may carry a detail line `Estimate: S`, `M` or `L` (S: one round expected, M: up to 3, L: more). `effort.estimates(plan_text) -> dict[str, str]`. The plan-stage prompt asks for one per task.
  2. `effort.actuals(root, docset) -> dict[str, Actual]` per task id, from the relay's history and logs (`.whyline/relay/`) and git: `rounds`, `minutes` (first turn start to the task's commit), `turns`, and `tokens` when a log line already holds a total.
  3. `effort.table(estimates, actuals) -> str`: task, estimate, rounds, minutes, tokens, and a `Over` mark when rounds exceed the estimate's bound. A missing value is `—`.
  4. The build record gets an `## Effort` section with the table and totals. The Stages line shows `Build (<n> tasks: <s> S, <m> M, <l> L)` once the plan is approved.
  Tests: parsing estimates, actuals from fake history and log files, the `Over` mark, missing values, and a plan with no estimates giving a table of actuals only.

- [ ] DONE-4: Retrospective and plan rules
  Create `src/whyline/sdlc/retro.py` and `tests/sdlc/test_retro.py`. Edit `src/whyline/sdlc/runner.py` (writer prompt), `src/whyline/sdlc/cli.py`, `src/whyline/console/docs_screen.py` and their tests.
  1. `retro.inputs(root, docs, docset) -> str`: the effort table, the tasks that went over with the review round summaries for them (at most 30 lines each), the pause reasons, the Acceptance section, and this feature's RAAID items. Everything is redacted and labelled as data.
  2. `retro.write(root, docs, docset, *, agent, run_fn=None) -> Retro`: one read-only turn producing `What went well` (at most 5 lines), `What cost rounds` (at most 5) and `Proposed rules` (at most 3, each at most 200 characters, each a rule a plan could carry). Saved as `docs/sdlc/<slug>/retro.md`. Extra lines and rules are cut.
  3. `retro.rules(docs) -> list[str]` reads `docs/product/plan-rules.md` (a list whyline appends to; the user may edit it). `retro.add_rule(docs, text, *, from_slug)` appends `- <text> (from <slug>, <date>)`. A rule already present is not added twice.
  4. Each proposed rule is offered with **Add to the plan rules**, **Make it a RAAID action** (when RAAID is installed) and **Skip**. Only the buttons write.
  5. The plan and spec writer prompts include the plan rules as a data block, newest first, at most 20 rules and 3000 characters.
  6. CLI: `whyline docs retro <slug>` writes and prints it. `whyline docs rules list|add "<text>"|remove <n>`. Docs: **Retrospective** on an accepted set, and a **Plan rules** entry listing them with **Remove**.
  Tests: `test_rule_added_only_on_add`, `test_rules_in_writer_prompt_are_capped`, `test_retro_inputs_are_redacted`, the limits, no duplicate rule, and a set with no effort data still getting a retrospective.

- [ ] DONE-5: Roles in order, and the separation warning
  Edit `src/whyline/sdlc/stages.py`, the Plan form in `src/whyline/console/tui.py` (or the file that holds it), `src/whyline/sdlc/cli.py` and their tests.
  1. `stages.stages_line` names the roles in this order when they apply: Product owner → Writer → Reviewer → Architect (Large) → Test planner → Implementer → Tester → Code reviewer → Release → Accept.
  2. `stages.role_conflicts(roles) -> list[str]`: `<agent> both writes and reviews the documents` and `<agent> both implements and reviews the code`. A conflict is not raised when only one agent is enabled; the line then reads `Only <agent> is enabled, so it reviews its own work`.
  3. The Plan form shows the conflicts under the Stages line as a warning and still starts. `whyline docs start` prints them.
  Tests: the order for Small, Feature and Large, both conflicts, the single-agent wording, and that a start is never refused.

- [ ] DONE-6: Docs
  Edit `docs/sdlc.md` (or the page that documents the pipeline), `docs/release.md` and `README.md` only.
  Cover: the Done checklist and each line, that it warns and never blocks, estimates and the Effort table, the retrospective and plan rules, and the role order with the separation warning.
  Verify with `uv run pytest -q`.
