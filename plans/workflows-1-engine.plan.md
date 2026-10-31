<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-10-29-workflows-design.md | created: 2026-10-29T10:00:00+05:30 -->
# Workflows 1: engine, core steps, triggers, CLI and console

Spec: `docs/superpowers/specs/2026-10-29-workflows-design.md`. Read it before every task. Where this plan and the spec differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the spec's behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

This plan builds Workflows without credentials, HTTP or Telegram control. At its end a user can build a scheduled workflow of `set`, `condition`, `switch`, `wait`, `stop`, `approval`, `agent` and `deliver` steps in the console, accept it, and watch it run. `workflows-2-connections.plan.md` and `workflows-3-telegram.plan.md` follow.

Global constraints:

- New code lives in `src/whyline/workflows/` (package) and `src/whyline/console/workflows_screens.py`. Do not grow `src/whyline/console/tui.py` beyond the mode wiring a task names.
- No new runtime dependency. Read TOML with `tomllib`; write it with the package's own renderer.
- Python 3.11 and 3.13 both. No dataclass field may default to a dict, list, set or mappingproxy (`tests/test_dataclass_defaults.py` enforces this).
- Console first: every CLI command a task adds has a console counterpart in the same or an earlier task, and both call one function in `whyline.workflows.service`.
- Tests: no network, no real vendor agent (inject fake runners), no real home directory (monkeypatch `whyline.paths.global_whyline_dir`), no `/Users/` path, no fixed sleep. Console tests use `App.run_test()`, press buttons by id, `await pilot.pause()` with no duration, and pass at 80x24.
- Run tests only with `uv run pytest`. Each task names its focused files; also run `uv run pytest -q` and report any failure outside them.

Review focus, each one pinned by the test named in its task:

- A workflow file edited while a run is in progress: the run finishes on the revision it started with. WF-4, `test_run_keeps_its_revision_after_edit`.
- The Mac asleep across three schedule times: one catch-up run, two recorded as missed. WF-8, `test_sleep_across_three_times_runs_once`.
- The tick firing twice for the same due time: one run. WF-8, `test_same_due_time_claims_once`.
- A crash while a `deliver` step is running: the run becomes `unknown_outcome` and nothing is sent again. WF-4, `test_crash_during_write_is_unknown_outcome`.
- A template that reads a step on the branch not taken: the step fails naming the path; the engine does not crash. WF-4, `test_template_reading_skipped_step_fails_clearly`.
- A hand-broken TOML file: listed as broken with the parse error; other workflows still tick. WF-8, `test_broken_file_does_not_stop_other_workflows`.

- [x] WF-1: Paths, definitions, validation and hashes
  Create `src/whyline/workflows/__init__.py`, `paths.py`, `definitions.py`, `steps/__init__.py` (the registry), and `tests/workflows/test_definitions.py` only.
  - `paths.home()` = `global_whyline_dir() / "workflows"` (created 0700), `state_path()`, `runs_dir()` (0700), `settings_path()`, `reports_dir(name)`, `repo_dir(root)` = `root / ".whyline" / "workflows"`.
  - `steps.FieldSpec(name, kind, required, templated, choices)` with `kind` one of `str`, `int`, `bool`, `list[str]`, `table`, `step_ref`. `steps.STEP_TYPES: Mapping[str, StepType]` with `StepType(name, fields, ports, writes)` for `set`, `condition`, `switch`, `wait`, `stop`, `approval`, `agent`, `deliver` with the fields in spec 4.2. `templated=False` on every target field in spec 4.2.
  - `definitions.Workflow` (frozen): `name`, `kind` ("personal" | "repo"), `path`, `root`, `description`, `trigger: TriggerSpec`, `inputs: tuple[InputSpec, ...]`, `steps: tuple[Step, ...]`, `layout` (mapping), `raw` (the parsed table). `workflow_id` as in spec 3.
  - `parse(text, *, kind, path, repo_root=None) -> Workflow` raises `DefinitionError` with every problem found, one per line, each naming the step id and field. It checks: name pattern; trigger kind in `manual`, `daily`, `weekdays`, `every`, `folder` (WF-24 adds `telegram`) and its fields (`at` as HH:MM, `every_hours` in 1..24 dividing 24, `folder` resolving under the user's home); unique step ids matching `^[a-z][a-z0-9_]{0,31}$`; known step types; required fields and their kinds; `{{` in a non-templated field; routing targets that exist and come later in the file; at most 30 steps; unknown keys.
  - `render(workflow) -> str` writes TOML that `parse` reads back to an equal `Workflow`, keeping `[layout]` last.
  - `semantic_hash(raw) -> str` and `layout_hash(raw) -> str` per spec 4.4, over canonical JSON (`sort_keys=True`, `separators=(",", ":")`).
  - `discover(repo_root) -> list[Workflow | Broken]` scans the personal folder and, when given, the repo folder. `Broken(path, kind, error)`.
  Tests:
  - the spec 4 example without its `http` step round-trips through `parse` and `render`
  - each validation rule rejects with a message naming the step and field
  - a template in `runner`, `to` and a routing target is refused
  - a backward or self routing target is refused
  - moving a `[layout]` entry changes `layout_hash` only
  - changing an instruction changes `semantic_hash` only
  - `discover` lists a broken file as `Broken` with its parse error
  Verify with `uv run pytest -q tests/workflows/test_definitions.py`. Change nothing else.

- [x] WF-2: Templates
  Create `src/whyline/workflows/expr.py` and `tests/workflows/test_expr.py` only.
  - `render(template: str, context: Mapping) -> str` and `value(template, context) -> object` (a template that is exactly one `{{ }}` returns the raw value, not a string).
  - Grammar per spec 4.3: dotted paths of identifiers and integer list indexes, then `| filter` with optional one string argument in double quotes. Anything else raises `TemplateError` naming the position.
  - `references(template) -> list[str]` returns the paths used, for validation and (plan 2) taint.
  - A missing path raises `TemplateError("<path> is not available")` unless `default` follows.
  Tests:
  - each filter
  - a whole-template value keeps its type
  - missing path error and `default`
  - `__class__`, calls, `[ "x" ]`, arithmetic and `{% %}` are refused
  - `references` of a template with two paths
  - a 1 MB string renders without recursion problems
  Verify with `uv run pytest -q tests/workflows/test_expr.py`. Change nothing else.

- [x] WF-3: State store and acceptance
  Create `src/whyline/workflows/state.py`, `src/whyline/workflows/capabilities.py`, `tests/workflows/test_state.py` and `tests/workflows/test_capabilities.py` only.
  - `connect()` opens `state.sqlite` (0600, WAL, `PRAGMA user_version` migrations). Tables: `activations(workflow_id PK, path, accepted_hash, accepted_at, status, reason, trusted_json, capability_text, last_run_at, next_due_at, folder_snapshot)`, `runs(id PK, workflow_id, revision, definition_json, source, dedupe_key UNIQUE, inputs_json, status, reason, wake_at, created, started, ended, pid)`, `step_runs(run_id, step_id, seq, status, reason, attempt, provider, started, ended, output_path, PRIMARY KEY(run_id, step_id))`, `approvals(id PK, run_id, step_id, revision, args_hash, nonce, status, message, expires_at, decided_by, decided_at)`.
  - Activation: `accept(conn, workflow) -> Activation` (stores the semantic hash and `capabilities.summary(workflow)`), `check(conn, workflow) -> str` (`active` | `paused` | `needs_review`; sets `needs_review` when the hash differs), `pause`, `resume`, `remove`, `get`, `all_activations`.
  - Runs: `claim_run(conn, workflow, *, source, dedupe_key, inputs) -> int | None` returns None for a used key. With a run `running` or `waiting` for that workflow, the new run is `queued` and any older `queued` run for it becomes `cancelled` with reason `replaced by a newer trigger`. `next_queued`, `set_run`, `set_step`, `steps_of`, `runs_of(workflow_id, limit)`.
  - `capabilities.summary(workflow) -> list[str]`: trigger and when it fires; each `agent` step's providers; each `deliver` destination; each `approval` step. `capabilities.diff(old: list[str], new: list[str]) -> list[str]` with `+ ` and `- ` lines.
  Tests:
  - accept then check is active; an edited step makes it needs_review; a layout-only edit stays active
  - a reused dedupe key returns None
  - a second claim while running queues; a third cancels the second with the reason
  - the file is 0600
  - summary lines for the spec 4 example without `http`, and a diff after adding a recipient
  Verify with `uv run pytest -q tests/workflows/test_state.py tests/workflows/test_capabilities.py`. Change nothing else.

- [x] WF-4: Engine core, routing and crash recovery
  Create `src/whyline/workflows/engine.py`, `src/whyline/workflows/steps/basic.py` (`set`, `condition`, `switch`, `stop`), and `tests/workflows/test_engine.py` only.
  - `StepResult(status, output: dict, reason="", port="next", wake_at=None)`. `Context` holds the run, its stored definition, inputs, trigger values and the outputs so far.
  - `execute(run_id, *, now=None, handlers=None) -> str` runs from the first step without a final state, following ports, marking unreached steps `skipped`, and returns the run's final or waiting state. It reads the definition from `runs.definition_json`, never from the file.
  - Each step: set `running` (with `pid`), call its handler, write the redacted output to `runs/<run_id>/<step_id>.json` (0600; over 1 MB fails the step), set the result. `whyline.ledgerops.redact` is applied before writing.
  - On start, a step already `running` whose pid is not alive: re-run it when its type does not write; otherwise set it and the run `unknown_outcome` and stop.
  - Limits from spec 5: 2 hours wall clock, 10 agent steps, 30 steps.
  - `cancel(run_id)`, `resolve_unknown(run_id, choice)` with `done` (step succeeded, continue), `failed` (run failed), `retry` (step re-runs).
  Tests (fake handlers):
  - a linear run succeeds and writes outputs
  - `condition` takes `true` and skips the other branch; `switch` takes a case and `default`
  - `stop` ends succeeded
  - `test_template_reading_skipped_step_fails_clearly`
  - `test_run_keeps_its_revision_after_edit`
  - `test_crash_during_write_is_unknown_outcome`, and a crashed `set` step is re-run
  - each `resolve_unknown` choice
  - an output over 1 MB fails the step; a secret-looking value is redacted on disk
  Verify with `uv run pytest -q tests/workflows/test_engine.py`. Change nothing else.

- [x] WF-5: Wait and approval steps
  Create `src/whyline/workflows/steps/waiting.py` and `tests/workflows/test_waiting.py`; edit `src/whyline/workflows/engine.py` and `src/whyline/workflows/state.py` only.
  - `wait`: `minutes` or `until` sets the run `waiting` with reason `timer` and `wake_at`. `engine.resume_due(now) -> list[int]` lists waiting runs whose `wake_at` has passed; `execute` continues them at the waiting step, which then succeeds.
  - `approval`: creates an `approvals` row (nonce from `secrets.token_urlsafe(8)`, `expires_at` = now + `expires_hours`), sets the run `waiting` with reason `approval`. `state.decide(conn, approval_id, nonce, choice, actor) -> str` with choice `approve` | `deny`; a used, expired or wrong nonce returns `out_of_date` and changes nothing. Approve continues the run; deny fails the step with `denied by <actor>`. An expired pending approval fails the step with `approval expired` when `resume_due` sees it.
  Tests:
  - a wait resumes only after `wake_at` and does not re-run earlier steps
  - `until` past today's time waits until tomorrow
  - approve continues, deny fails, a second decision is out of date, a wrong nonce is out of date
  - expiry fails the step
  Verify with `uv run pytest -q tests/workflows/test_waiting.py tests/workflows/test_engine.py`. Change nothing else.

- [x] WF-6: Agent step and the daily cap
  Create `src/whyline/workflows/steps/agent.py`, `src/whyline/workflows/settings.py` and `tests/workflows/test_agent_step.py` only.
  - Build `AgentDef(name=f"wf-{workflow}-{step}", kind="personal", path=<workflow file>, root=<repo root or home>, instructions=..., runner=..., backup=..., model=..., timeout_minutes=...)` and call `whyline.agents.runner.execute_once(defn, source="workflow", payload_dir=<dir>, unattended=True, run_fn=...)`. Rendered `inputs` go into `<dir>/input-<n>.md`, one file each.
  - Output `{"output": <final text or parsed JSON>, "provider": record.cli, "run_id": record.run_id}`; `step_runs.provider` is set.
  - `output = "json"` per spec 6: fenced block or whole text, parse, check `schema` (`type`, `required`, `properties` types), one repair turn whose instructions add `Reply with only JSON matching this schema. The last answer failed: <error>.`, then fail.
  - When every attempt in `record.attempts` ended `usage_limit`, the run goes `waiting(usage_limit)` with `wake_at` read from the last attempt's reason (`usage_limit until HH:MM`, next occurrence of that time), or one hour from now when it has none.
  - `settings.load() -> Settings(daily_agent_cap: int = 0, retention_days: int = 30, keep_runs: int = 20)` and `settings.save(settings)`. Over a non-zero cap (agent steps started today across all workflows, from `step_runs`), the step waits until local midnight with reason `daily_cap`.
  Tests (fake `run_fn`):
  - inputs land as files and instructions stay literal
  - text output; JSON output; a repair that succeeds; a repair that fails
  - a usage limit waits with the reset time
  - the cap at 0 never blocks; at 2 the third agent step today waits until midnight
  - a disabled provider fails with the runner's Settings hint and no subprocess
  Verify with `uv run pytest -q tests/workflows/test_agent_step.py`. Change nothing else.

- [x] WF-7: Deliver step
  Create `src/whyline/workflows/steps/deliver.py` and `tests/workflows/test_deliver_step.py`; edit `src/whyline/agents/deliver.py` and `tests/agents/test_deliver.py` only.
  - In `agents/deliver.py`, extract the sending part of `after_run` into `send(delivery, subject, body, attachment=None, *, mail=None, tg=None) -> list[dict]`, and have `after_run` call it. Agents' behaviour is unchanged.
  - The step builds a `Delivery`: `telegram` with `chat` (must be in `telegram_in.allowed_chats`; the only allowed chat is the default; otherwise the step fails `chat <id> is not an allowed inbox chat`), `email` with the literal addresses, or `file` writing `<reports_dir>/<YYYY-MM-DD-HHMM>-<run_id>.md` (0600). `text` and `subject` are templates.
  - A failed send fails the step with the detail. The step is a write for crash recovery (WF-4).
  Tests (fake `tg` and `mail`):
  - each destination sends once with the rendered text
  - a chat that isn't allowed is refused without sending
  - a send failure fails the step
  - existing `after_run` tests still pass
  Verify with `uv run pytest -q tests/workflows/test_deliver_step.py tests/agents/test_deliver.py`. Change nothing else.

- [x] WF-8: Triggers and the tick
  Create `src/whyline/workflows/tick.py` and `tests/workflows/test_tick.py`; edit `src/whyline/agents/tick.py` and `tests/agents/test_tick.py` only.
  - `tick.run(now, *, spawn=None) -> TickReport` inside the agents tick lock, called from `agents.tick.run_tick` after `_start_waiting`, wrapped so an exception is logged as `workflow tick failed` and never stops the inbox or agents.
  - For each activation: load the file (a parse error sets status `broken` with the error and continues), `state.check` (needs_review waits), then by trigger kind. `daily` / `weekdays` / `every` use `agents.schedule.plan_tick` with an `agents.definitions.Trigger` built from the spec; stale times are recorded as missed; the due time claims dedupe key `<workflow_id>@<due iso>`. `folder` compares `agents.folders.snapshot` with the stored snapshot; new files claim `<workflow_id>@<sha of new names>` with `trigger.files`.
  - Then `engine.resume_due(now)` and start `queued` runs when the workflow has none running. Starting = `spawn(run_id)`; the default spawns `whyline workflow _execute <run_id>` detached, as `agents.tick._spawn` does.
  - `next_due_at` is updated for the Library.
  Tests (fake spawn, fixed clocks):
  - `test_sleep_across_three_times_runs_once`
  - `test_same_due_time_claims_once`
  - `test_broken_file_does_not_stop_other_workflows`
  - needs_review and paused workflows do not run
  - a folder trigger fires once for two new files and not for files present at accept
  - a waiting run past `wake_at` is spawned
  - an exception inside the workflow tick still lets the agents tick finish
  Verify with `uv run pytest -q tests/workflows/test_tick.py tests/agents/test_tick.py`. Change nothing else.

- [x] WF-9: Service and CLI
  Create `src/whyline/workflows/service.py`, `src/whyline/workflows/cli.py`, `tests/workflows/test_service.py` and `tests/workflows/test_cli.py`; edit `src/whyline/cli.py` (register `workflow`) only.
  - `service`: `rows(repo_root) -> list[Row]` (name, kind, status, trigger text, next, last), `load(name, repo_root)` (exact name; personal and repo with the same name raise `Ambiguous` naming both ids), `validate(text) -> list[str]`, `new(name, kind, repo_root) -> Path` (a manual workflow with one `set` step), `save(workflow) -> Path`, `review(name, repo_root) -> list[str]` (the capability summary, or the diff against the accepted one when re-accepting; changes nothing), `accept(name, repo_root) -> None`, `pause`, `resume`, `run_now(name, inputs, *, source, repo_root, spawn=None) -> int` (inputs checked against `[[input]]` types; unknown keys refused), `runs(name, repo_root)`, `run_detail(run_id)`, `cancel`, `decide(approval_id, nonce, choice, actor)`, `resolve(run_id, choice)`, `retry(run_id) -> int`, `dry_run(name, inputs, repo_root) -> list[str]`, `get_cap()`, `set_cap(n)`.
  - `dry_run` executes `set`, `condition`, `switch` and templates, and for `agent`, `deliver`, `wait` and `approval` reports what they would receive, without running them.
  - CLI `whyline workflow list|show|validate|new|accept|pause|resume|run|runs|run-show|cancel|approve|deny|resolve|retry|dry-run|cap|_execute`, each a thin call into `service` (`_execute` calls `engine.execute`). `run` takes `--input key=value` repeatable.
  Tests:
  - each service function on a temp home, including the Ambiguous case and an unknown input key
  - dry run of a branch shows the branch taken and what deliver would send, and calls no handler that writes
  - the CLI prints and exits non-zero on errors; `whyline workflow --help` lists every command
  Verify with `uv run pytest -q tests/workflows/test_service.py tests/workflows/test_cli.py`. Change nothing else.

- [ ] WF-10: Workflows mode and the Library
  Create `src/whyline/console/workflows_screens.py` and `tests/console/test_workflows_library.py`; edit `src/whyline/console/tui.py` and `tests/console/test_mode_buttons.py` only.
  - Add `"workflows"` to `_MODES`, a `Workflows` button `#mode-workflows` after Assistant, and controls `#workflows-library`, `#workflows-new`, `#workflows-runs`. Typing in Workflows mode prints `Use the buttons above.` and runs no agent.
  - `LibraryScreen`: a table of `service.rows(root)`; buttons Run now, Pause/Resume, Review & accept (shows `service.review` lines in a confirm screen and calls `service.accept` only on Confirm), Edit (opens the Builder from WF-12; until then, disabled), and a Daily agent cap input saving through `service.set_cap` (0 = off, shown as `off`). Broken rows show their error.
  - `New` asks for a name and scope and calls `service.new`, then opens the Library on it.
  Tests:
  - the five mode buttons and Settings fit one row at 80x24
  - the Library lists a personal and a broken workflow
  - Run now calls `run_now` with source `console`
  - accept shows the summary and stores acceptance only after confirm
  - Pause then Resume
  - the cap input saves 3 and shows `off` for 0
  - input in Workflows mode runs nothing
  Verify with `uv run pytest -q tests/console/test_workflows_library.py tests/console/test_mode_buttons.py`. Change nothing else.

- [ ] WF-11: Runs screen
  Edit `src/whyline/console/workflows_screens.py`, `src/whyline/console/tui.py` (wire `#workflows-runs`) and create `tests/console/test_workflows_runs.py` only.
  - `RunsScreen(workflow=None)`: runs newest first (workflow, source, state, started, duration). Opening one shows its steps (state, provider, duration, reason) and the selected step's redacted output, scrollable.
  - Buttons by state: Cancel (running, waiting, queued); Approve and Deny (waiting for approval, calling `service.decide` with actor `console`); Mark done, Mark failed, Retry step (unknown_outcome, through `service.resolve`); Retry run (failed, cancelled).
  - The Library's selected row opens its runs.
  Tests:
  - the timeline of a finished run with a skipped branch
  - Approve continues the run and Deny fails it
  - each unknown_outcome button
  - Cancel on a waiting run
  - 80x24 keeps the buttons reachable
  Verify with `uv run pytest -q tests/console/test_workflows_runs.py`. Change nothing else.

- [ ] WF-12: Builder outline
  Edit `src/whyline/console/workflows_screens.py` and create `tests/console/test_workflows_builder.py` only.
  - `BuilderScreen(workflow)`: left, the trigger then the steps in order (`<id>  <type>  <one-line summary>`); right, the trigger form (kind, at, every_hours, folder) and the `[[input]]` list. Buttons: Add step (choose a type from `steps.STEP_TYPES`; new id `<type>_<n>`), Move up, Move down, Delete (refused while another step routes to it, naming that step), Save, Cancel.
  - Save renders through `definitions.render` and calls `service.save`; the status line then says `Saved. Review & accept to run the new version.` when the semantic hash changed, `Saved layout.` when only layout changed. Unsaved changes ask before Cancel closes.
  - Enable the Library's Edit.
  Tests:
  - add, move and delete steps and save; the file parses back
  - deleting a routed-to step is refused
  - a trigger change marks needs_review after save
  - Cancel with changes asks first
  - 80x24
  Verify with `uv run pytest -q tests/console/test_workflows_builder.py`. Change nothing else.

- [ ] WF-13: Builder inspector, validation and dry run
  Edit `src/whyline/console/workflows_screens.py` and `tests/console/test_workflows_builder.py` only.
  - Selecting a step shows a form generated from its `StepType.fields`: text inputs (templated fields say `templates allowed`), selects for `choices` (runners come from `whyline.account.enabled_agents()`), and for `step_ref` a select of later steps only. `condition` shows `then`/`else`; `switch` lists cases with Add/Remove case.
  - Validate shows `service.validate` messages next to the step they name. Save is refused while validation fails.
  - Dry run asks for declared inputs and shows `service.dry_run` lines.
  Tests:
  - editing an agent step's instructions and runner saves them
  - a routing select offers only later steps
  - a `{{` typed into `to` shows the validation error and blocks Save
  - dry run of a condition shows the taken branch
  - a disabled provider is not offered as a runner
  Verify with `uv run pytest -q tests/console/test_workflows_builder.py`. Change nothing else.
