<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-10-29-workflows-design.md | created: 2026-10-29T10:00:00+05:30 -->
# Workflows 3: Telegram control, operations and documentation

Spec: `docs/superpowers/specs/2026-10-29-workflows-design.md` (sections 12 to 14). Read it before every task. Where this plan and the spec differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the spec's behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Starts after `plans/workflows-2-connections.plan.md` is complete. It completes the first public release of Workflows.

Global constraints:

- Every constraint in `workflows-1-engine.plan.md` and `workflows-2-connections.plan.md` applies.
- Telegram text is data. A message can choose only an accepted workflow's exact name, its declared inputs, or a run id shown to that chat. It can never choose a step, host, credential, recipient or file.
- Only the inbox's allowed chats can list, run, pause, resume, cancel or approve. Every callback is answered, and the card is edited to show what happened.
- Telegram tests use the fake `http` used in `tests/ideas/test_bot.py`; the conftest guard blocks real Telegram calls.

Review focus, each one pinned by the test named in its task:

- `flow digest key=value` where `digest` declares no `key`: refused, nothing runs. WF-21, `test_undeclared_input_refused`.
- The same Telegram update delivered twice: one run. WF-21, `test_repeated_update_runs_once`.
- An approval card tapped from a chat that is not allowed: refused, the card unchanged. WF-23, `test_foreign_chat_cannot_approve`.
- A run started from Telegram that the Mac sleeps through: the progress message says so when the run resumes, and is not duplicated. WF-24, `test_progress_message_edited_not_duplicated`.
- Free text after a `manual` workflow's name: refused with the declared inputs listed. WF-24, `test_free_text_needs_telegram_trigger`.

- [ ] WF-21: `flows` and `flow <name>` from Telegram
  Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/actions.py`, `src/whyline/ideas/worker.py`, `tests/ideas/test_intent.py`, `tests/ideas/test_bot.py` and `tests/ideas/test_worker.py` only.
  - `flows` replies with one line per accepted workflow: name, status, next run. `flow runs [name]` replies with the last 5 runs (id, workflow, state, started).
  - `flow <name> [key=value ...]` creates a `run_workflow` request (new action in `actions.REGISTRY`, verb `flow`, cost `long`, default approval `none`). The approval is raised to `tap` when the workflow has a gated write (`taint.analyse`) or an `approval` step. The worker calls `service.run_now(name, inputs, source="telegram", dedupe_key=f"tg:{update_id}")` and replies `Started <name> (run <id>).`.
  - Names are exact (`service.load`), inputs must be declared and of the declared type, and nothing else is accepted. Errors: `No accepted workflow named <name>.`, `<name> takes: <inputs>.`
  - `service.run_now` gains `dedupe_key` (default a fresh UUID). Telegram-typed inputs count as tainted from now on (`taint.analyse(..., telegram_inputs=True)`).
  Tests:
  - `flows` and `flow runs` text
  - an exact name queues with the update id as dedupe key
  - `test_undeclared_input_refused`, a wrong type is refused, an unknown name is refused
  - `test_repeated_update_runs_once`
  - a workflow with a gated write needs a tap first
  Verify with `uv run pytest -q tests/ideas/test_intent.py tests/ideas/test_bot.py tests/ideas/test_worker.py`. Change nothing else.

- [ ] WF-22: Pause, resume and cancel from Telegram
  Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/actions.py`, `src/whyline/ideas/worker.py`, `tests/ideas/test_bot.py` and `tests/ideas/test_worker.py` only.
  - `flow pause <name>`, `flow resume <name>`, `flow cancel <run_id>` create `pause_workflow`, `resume_workflow`, `cancel_workflow_run` requests, each with minimum approval `tap`, through the existing request cards. Confirm calls the `service` function and replies with the new status.
  - `flow cancel` accepts only a run id of an accepted workflow that is queued, running or waiting.
  Tests:
  - each verb shows a card and acts only after Confirm
  - Cancel on the card changes nothing
  - cancelling a finished run is refused
  Verify with `uv run pytest -q tests/ideas/test_bot.py tests/ideas/test_worker.py`. Change nothing else.

- [ ] WF-23: Approval cards in Telegram
  Create `src/whyline/workflows/notify.py` and `tests/workflows/test_notify.py`; edit `src/whyline/workflows/engine.py`, `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py` and `tests/ideas/test_bot.py` only.
  - When an approval is created (an `approval` step or a gated write), `notify.approval_card(approval)` queues a message to every allowed inbox chat through the inbox outbox: workflow, step, and the approval message, with buttons Approve once, Always for this version (gated writes only) and Deny. Callback data `wfa:<o|t|d>:<approval_id>:<nonce>`, under 64 bytes.
  - `intent._callback` parses `wfa:`. The bot calls `service.decide(approval_id, nonce, choice, actor=str(chat_id))` and edits the card to `Approved by you.`, `Always allowed for this version.`, `Denied.`, or replies `This card is out of date.` for `out_of_date`.
  - Deciding in the console edits the Telegram card to `Decided in the console.`.
  Tests:
  - the card text and the 64-byte limit
  - each button decides and edits the card
  - `test_foreign_chat_cannot_approve`
  - a second tap is out of date
  - a console decision edits the card
  Verify with `uv run pytest -q tests/workflows/test_notify.py tests/ideas/test_bot.py`. Change nothing else.

- [ ] WF-24: Telegram trigger and run progress
  Edit `src/whyline/workflows/notify.py`, `src/whyline/workflows/engine.py`, `src/whyline/workflows/definitions.py`, `src/whyline/workflows/steps/__init__.py`, `src/whyline/ideas/bot.py`, `tests/workflows/test_notify.py` and `tests/ideas/test_bot.py` only.
  - Trigger kind `telegram`: `flow <name> <free text>` starts a run with `trigger.text` (tainted). Validation refuses `[[input]]` on a `telegram` workflow.
  - A run whose source is `telegram` keeps one progress message per run: `Started <name>.`, then `<n>/<total> <step>…` as steps start, `Waiting for your approval.`, `Waiting until HH:MM.`, then `Done.` or `Failed at <step>: <reason>.`. The message id is stored on the run and edited in place; a failed edit sends a new message once and stores its id.
  - When a run resumes after the Mac slept, the next edit starts with `Resumed after the Mac was asleep.`.
  Tests:
  - free text reaches `trigger.text`
  - `test_free_text_needs_telegram_trigger`
  - progress edits for a run with a wait and an approval
  - `test_progress_message_edited_not_duplicated`
  - a console-started run sends no progress messages
  Verify with `uv run pytest -q tests/workflows/test_notify.py tests/ideas/test_bot.py`. Change nothing else.

- [ ] WF-25: Doctor, retention and run export
  Create `src/whyline/workflows/doctor.py`, `tests/workflows/test_doctor.py` and `tests/console/test_workflows_check.py`; edit `src/whyline/workflows/service.py`, `src/whyline/workflows/cli.py`, `src/whyline/workflows/tick.py`, `src/whyline/console/workflows_screens.py` and `src/whyline/console/tui.py` (a `#workflows-check` button) only.
  - `doctor.checks() -> list[Check]` (reuse the `Check` shape from `assistant_doctor`): state file 0600 and runs folder 0700; credential store available; broken files; workflows needing review or a credential; runs stuck `running` with a dead pid; `unknown_outcome` runs; each active workflow's next run; whether the agents scheduler is installed.
  - Retention in the tick: delete runs (rows and output folders) older than `settings.retention_days`, always keeping the newest `settings.keep_runs` per workflow and any run that is waiting or unknown_outcome. Both settings editable in the Library next to the cap.
  - `service.export_run(run_id) -> Path`: a redacted Markdown record (definition summary, steps, states, outputs cut to 2,000 characters each) in the reports folder.
  - CLI `whyline workflow doctor` and `export-run <id>`; console `Check` shows the same lines, and Export on the Runs screen.
  Tests:
  - each check passing and failing
  - retention keeps the newest and waiting runs
  - the export contains no sentinel credential value
  - CLI and console show the same checks
  Verify with `uv run pytest -q tests/workflows/test_doctor.py tests/console/test_workflows_check.py tests/workflows/test_tick.py`. Change nothing else.

- [ ] WF-26: Documentation and help
  Create `docs/workflows.md`; edit `README.md` (one short Workflows section linking to it), `src/whyline/ideas/bot.py` (help text for `flows` and `flow`), `src/whyline/console/tui.py` (Workflows mode help line) and `tests/ideas/test_bot.py` only.
  - `docs/workflows.md` covers: what a workflow is; the file format with the spec 4 example; each step type and its fields; templates and filters; triggers; accepting and why edits need review; credentials and the HTTP limits; approvals and trust; Telegram commands; doctor, retention and export; what is not in this release (MCP, canvas, loops, webhooks, shell).
  - Every command, field and button named in the doc exists; check by running each CLI command's `--help`.
  Tests:
  - Telegram `help` lists `flows` and `flow`
  Run `git diff --check` and `uv run pytest -q`. Change nothing else.
