<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-10-08-agent-deliveries-design.md | created: 2026-10-08T13:00:00+05:30 -->
# Agent deliveries (whyline 0.3.38)

Each task is one task of `docs/superpowers/plans/2026-10-08-agent-deliveries.md`
(spec: `docs/superpowers/specs/2026-10-08-agent-deliveries-design.md`).
Read the task in full and follow its steps exactly: write the failing test
first, see it fail, implement, then run the whole suite with `uv run pytest -q`.
The plan's "Global Constraints" and "Review Focus" apply.

whyline 0.3.37.1 is released and `main` also has the personal-Claude
`--settings` fix and typed `edit`/`delete` in Agents mode: build on that code
and its actual names. Where the plan's code differs from what is in the
repository, follow the repository's code and keep the plan's behaviour.
The agents stay read-only; only whyline delivers, after the run.

Tests must not use the network, Mail, the Keychain, textutil, osascript or a
real Telegram bot (stub them), must never touch the real home folder (point
HOME at tmp_path), must pass on Windows and Linux (check POSIX permission
bits only when os.name != "nt"; write paths into hand-made TOML with
json.dumps; compare paths as Path), must not contain "/Users/" paths, and
must press buttons by widget and wait for screens on a condition rather than
click by position or pause a fixed time. Console screens fit 80x24.
The only new dependency is markdown>=3.5,<4. No whyline-relay changes.
Never push, tag, bump the version or publish.

- [x] DL-1: Delivery settings store and run-record field
  Implement "Task 1" from the plan: deliveries.py (Delivery, validation,
  ~/.whyline/agents/deliveries.toml at 0600, keyed by agent id),
  RunRecord.deliveries with records.run_folder/load/save_metadata, and
  service.delete removing the agent's deliveries. Verify: uv run pytest -q.

- [x] DL-2: Word attachment and summary
  Implement "Task 2" from the plan: the markdown dependency, convert.py
  (to_html, to_docx through textutil, summary up to the first table).
  Verify: uv run pytest -q.

- [x] DL-3: Telegram
  Implement "Task 3" from the plan: telegram.py (token in the Keychain or a
  0600 file, getMe, chat discovery, known chats, sendDocument/sendMessage as
  plain text, one retry on a network error, the token redacted from every
  error). Verify: uv run pytest -q.

- [x] DL-4: Email through Mail
  Implement "Task 4" from the plan: mail_send.py, with every recipient,
  subject, body and attachment passed to osascript as arguments, never
  spliced into the script. Verify: uv run pytest -q.

- [x] DL-5: Delivering after a run, the command, test sends and resend
  Implement "Task 5" from the plan: deliver.py (after_run, the advanced
  command, send_test, status_text, describe), the hook in after.finish that
  never raises, and service.resend. Verify: uv run pytest -q.

- [ ] DL-6: The CLI
  Implement "Task 6" from the plan: whyline agents deliver, resend and
  telegram setup|chats, and delivery status in whyline agents history.
  Verify: uv run pytest -q.

- [ ] DL-7: Console Telegram setup screen and Runs delivery status
  Implement "Task 7" from the plan: TelegramSetupScreen, the Delivered column
  and Resend button in RunsScreen, and _agent_resend in tui.py.
  Verify: uv run pytest -q.

- [ ] DL-8: Console Deliver to section, Review sentence and Send test
  Implement "Task 8" from the plan: the Deliver to fields in the agent form,
  AgentForm, Send test, Set up Telegram from the form, saving deliveries with
  the agent (and moving them when an agent is renamed), the Review sentence,
  and Back keeping what was typed. Update existing tests that used the old
  AgentDef result to use AgentForm, keeping what they check.
  Verify: uv run pytest -q.
