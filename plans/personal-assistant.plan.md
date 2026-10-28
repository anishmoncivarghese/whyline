<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-10-26-personal-assistant-design.md | created: 2026-10-26T02:30:00+05:30 -->
# Personal assistant: tasks over Telegram and email, reminders, memory, and a morning brief

Spec: `docs/superpowers/specs/2026-10-26-personal-assistant-design.md`.
Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- CLI commands live under `whyline idea …`, not `whyline assistant …`.
- Assistant files live under the inbox home `~/.whyline/ideas/` (`whyline.ideas.paths.home()`), not `~/.whyline/assistant/`.

Where a symbol name has moved, follow the current repository while preserving the spec's behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item.
Detail lines stay indented. Do not add another checkbox line anywhere in this
file. Do not implement from this plan until Relay starts the task.

What this builds: the Idea Inbox becomes a personal assistant. It still reads
Telegram and email the same way:
1. A fixed verb is parsed without a model (`intent.py`).
2. Any other free text goes to the inbox assistant, which only proposes.

New verbs: `status`, `run <agent>`, `ask <repo> <question>`, `remind`, `remember`/`forget`, `summarise`, `do <task>`. Each verb is an entry in one action registry, with a policy saying whether it may run at once or needs a confirmed tap. A weekday morning brief reads Calendar, Mail and Reminders on this Mac and sends a plan for the day to Telegram.

Rules every task keeps:

- **Console first.** Anything a user sets up, checks or runs here must be reachable from `whyline console` without a terminal. A task that adds a `whyline idea …` command adds its console counterpart in the same task, saving through the same function the command calls. The CLI stays for scripts.
- **Messages, emails, calendar entries and documents are data.** No inbound text can choose a command, a shell string, a path, a URL, an email recipient, or a repository outside the existing allowlists:
  - repos: `whyline.ideas.setup.list_repos`
  - saved agents: `whyline.agents.service.rows`
  - plan tasks: the unchecked `- [ ] ID:` lines of a plan in an allowed repo
- **Read-only unattended turns** use only providers that are enabled in Settings (`whyline.account.enabled_agents()`) and pass `whyline.agents.capabilities.can_run_unattended(cli)`, through `capabilities.read_only_command`. Antigravity is refused with that reason.
- **Only the relay writes code**, and only after a confirmed tap whose nonce is current, through the existing `whyline.ideas.run` start path. Nothing in this plan sends email to anyone other than the user's own delivery settings, edits a calendar, or runs a shell string built from message text.
- **Every action is audited:** each action that is requested, refused, confirmed, run or failed writes one `requests` row (from ASST-3) or one `events` row. History is readable in the console.
- **Personal data stays private.** Files live under `~/.whyline/ideas/` at mode 0600 (folders 0700), never in a repository.
- **No new dependency.** macOS APIs are reached through `/usr/bin/osascript` (AppleScript or JXA with `ObjC.import`), like `whyline/ideas/documents.py`.
- **Tests:**
  - never invoke a real provider, osascript, Mail, Calendar or Telegram
  - never use a real home directory or the network
  - never sleep for a fixed duration
  - keep Python 3.11 compatibility
- **Release scope:** no version bump, tag, push, GitHub release, or PyPI publication. Release stays `human`.

## Phase 1: make the email path safe

- [x] ASST-1: Email authentication checks the user's own provider and the From domain
  Edit `src/whyline/ideas/email_in.py`, `src/whyline/ideas/cli.py`, `src/whyline/console/inbox_screen.py`, `tests/ideas/test_email_in.py`, `tests/ideas/test_cli.py`, and `tests/console/test_inbox_screen.py` only.
  Today `is_authenticated` accepts any `Authentication-Results` header containing `dkim=pass` or `spf=pass`. A sender can add that header themselves, and a pass for the sender's own domain also counts.
  Add kv key `email_authserv` (for example `mx.google.com`, `icloud.com`, `mx.microsoft.com`). `is_authenticated(msg, authserv)` must:
  - read only `Authentication-Results` headers whose authserv-id (the first token before `;`) equals the configured value, and use the topmost such header only
  - accept when `dmarc=pass`, or when `dkim=pass` with `header.d` equal to the From address's domain (or a parent of it)
  - not count SPF alone
  When `email_authserv` is unset, refuse every message with the event note `email authentication is not set up: choose your mail provider in Inbox`.
  Add `whyline idea email authserv [<id>]`, which prints or saves the value through one `set_authserv(conn, value)` function. Add an `Email provider check` input on the Inbox screen saving through the same function. The input shows a hint of three common values. The Inbox `Check` reports when it is unset.
  Tests:
  - a forged header below the real one is ignored
  - a header from another authserv is ignored
  - dkim pass for a different domain is refused
  - dkim pass with an aligned subdomain is accepted
  - dmarc pass is accepted
  - spf-only is refused
  - an unset value refuses with the note
  - CLI and console both save through `set_authserv`
  Verify with `uv run pytest -q tests/ideas/test_email_in.py tests/ideas/test_cli.py tests/console/test_inbox_screen.py`. Change nothing else.

- [x] ASST-2: Confirmation codes are random, bound and short-lived
  Add `src/whyline/ideas/confirm.py` and `tests/ideas/test_confirm.py`. Edit `src/whyline/ideas/email_in.py` and `tests/ideas/test_email_in.py` only.
  Today `email_in.code_for` is an unkeyed `sha256("whyline-email:{id}:{rev}")[:6]`, which anyone can compute. Replace it with `confirm.issue(conn, *, scope, subject, actor, ttl_minutes=30) -> str` and `confirm.consume(conn, code, *, scope, subject, actor, now=None) -> bool`:
  - **issue** stores a random 8-character code from `secrets` (lower-case letters and digits, without look-alikes) in kv as JSON `{scope, subject, actor, expires_at}`.
  - **consume** succeeds once, only for the same scope, subject and actor before expiry, and then deletes the code.
  - `subject` is a string such as `idea:12:rev:4` or `request:7`.
  Email confirmation uses it, with actor = the authenticated sender address. Remove `code_for`. Old `email_code:*` keys are ignored, not migrated.
  Tests:
  - two issues differ
  - a wrong code, wrong actor, wrong subject, expired code and a second use all fail and change nothing
  - the existing email confirm flow still starts the brainstorm with a current code
  Verify with `uv run pytest -q tests/ideas/test_confirm.py tests/ideas/test_email_in.py`. Change nothing else.

- [x] ASST-3: Install the Mail rule script from the console
  Edit `src/whyline/console/inbox_screen.py`, `src/whyline/console/agents_screens.py`, `tests/console/test_inbox_screen.py`, and the closest existing agent detail screen test file only.
  `whyline idea email mail-script` and `whyline agents mail-script <name>` have no console counterpart.
  - Add `Install Mail rule…` to the Inbox screen's email section, and the same button to the saved-agent detail screen (shown only for agents whose trigger is manual or folder). Both call `whyline.agents.mail.install(name)` (`"idea"` for the inbox), exactly as the CLI does.
  - On success, show the written path and the steps the user must do in Mail.app, which cannot be automated: Mail → Settings → Rules → Add Rule, set the conditions (From is the allowed sender), then Run AppleScript → choose `whyline-<name>.applescript`.
  - On a non-macOS host, show `mail.NEEDS_MACOS` and disable the button. An error is one plain-text line and does not dismiss the screen.
  Tests:
  - the button calls an injected install with `idea` / the agent name
  - success shows the path and steps
  - an unsupported host disables the button
  - an install error stays on the screen
  Verify with the named focused tests. Change nothing else.

## Phase 2: the action registry and requests

- [x] ASST-4: Action registry and policy
  Add `src/whyline/ideas/actions.py` and `tests/ideas/test_actions.py`. Edit `src/whyline/ideas/cli.py` and `tests/ideas/test_cli.py` only.
  Define a frozen `Action(name, verb, writes, cost, default_approval, min_approval, summary)`, with `approval` one of `none`, `tap`. Define `REGISTRY` with exactly these actions:

  | name | writes | cost | default approval | minimum approval |
  |---|---|---|---|---|
  | `capture` | no | instant | none | none |
  | `brainstorm` | no | long | tap | tap |
  | `status` | no | instant | none | none |
  | `run_agent` | no | long | none | none |
  | `ask_repo` | no | turn | none | none |
  | `summarise` | no | turn | none | none |
  | `remind` | no | instant | none | none |
  | `remember` | no | instant | none | none |
  | `forget` | no | instant | none | none |
  | `do_task` | yes | long | tap | tap |
  | `stop` | yes | instant | tap | tap |

  `run_agent` is raised to `tap` at request time when the agent's delivery has a `command`, or its timeout is over 15 minutes (enforced in ASST-8, not here).
  Policy lives in kv `assistant_policy` as JSON `{name: {"enabled": bool, "approval": str}}`:
  - `policy(conn)` returns the defaults merged with the saved values.
  - `set_policy(conn, name, *, enabled=None, approval=None)` refuses an unknown name, and refuses an approval below `min_approval` with `<name> changes things, so it always needs a tap.`
  - `approval_for(conn, name, *, proposed_by)` returns `tap` when `proposed_by == "assistant"` (an AI guess is always confirmed), otherwise the policy value.
  Add `whyline idea actions list` (a table of name, on/off, approval, summary) and `whyline idea actions set <name> [--on|--off] [--approval none|tap]`, both through these functions.
  Tests:
  - defaults
  - a merge keeps unknown saved keys out
  - `do_task` and `stop` can't drop to none
  - an unknown name is refused
  - assistant proposals always need a tap
  - CLI list and set
  Verify with `uv run pytest -q tests/ideas/test_actions.py tests/ideas/test_cli.py`. Change nothing else.

- [x] ASST-5: Requests table, reminders table and ledger schema 6
  Edit `src/whyline/ideas/store.py` and `tests/ideas/test_store.py`. Add `src/whyline/ideas/requests.py` and `tests/ideas/test_requests.py`. Edit nothing else.
  Bump `SCHEMA_VERSION` to 6 with a forward migration from 5 that keeps every existing row. Add these tables:
  - `requests(id INTEGER PRIMARY KEY, created_at, channel TEXT, actor TEXT, chat_id INTEGER, action TEXT NOT NULL, args_json TEXT NOT NULL, proposed_by TEXT NOT NULL, state TEXT NOT NULL, approval TEXT NOT NULL, confirmed_at, started_at, finished_at, lease_until, pid INTEGER, result_path, error)`. `state` is one of `waiting_tap`, `queued`, `running`, `done`, `failed`, `refused`, `cancelled`.
  - `reminders(id INTEGER PRIMARY KEY, created_at, chat_id INTEGER, due_at TEXT NOT NULL, text TEXT NOT NULL, state TEXT NOT NULL, sent_at, request_id INTEGER)`
  `requests.py` provides:
  - `create(conn, *, channel, actor, chat_id, action, args, proposed_by)`, which validates the action is in `actions.REGISTRY` and enabled, sets `approval` from `actions.approval_for`, and starts in `waiting_tap` or `queued`. A disabled action is stored as `refused` with note `<verb> is turned off in the console`.
  - `confirm(conn, request_id, code, *, actor)`, using `confirm.consume` with scope `request`
  - `cancel`, `claim_next(conn, now)` (one queued request, lease = 30 min plus the action's timeout, the same pid rule as `worker.py`), `finish(conn, id, *, result_path=None, error=None)`, and `history(conn, limit=50)`
  Each state move is checked against an explicit allowed-moves table, as `store.ALLOWED` does.
  Tests:
  - the 5 → 6 migration keeps ideas, jobs and outbox
  - a newer schema still raises
  - create honours policy and refusal
  - confirm needs the right code and actor, once
  - illegal moves raise
  - `claim_next` respects the lease and reclaims a dead pid
  Verify with `uv run pytest -q tests/ideas/test_store.py tests/ideas/test_requests.py`. Change nothing else.

- [x] ASST-6: Request cards and taps in Telegram, and `yes <code>` by email
  Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/email_in.py`, `tests/ideas/test_intent.py`, `tests/ideas/test_bot.py`, and `tests/ideas/test_email_in.py` only.
  - A request in `waiting_tap` sends a card titled with the action's summary and its arguments in plain text, with `Confirm` and `Cancel` buttons. Callback data is `req:<action>:<request_id>:<code>`, kept under 64 bytes, where `<action>` is `ok` or `no`. `intent._callback` parses it. Confirm calls `requests.confirm` with actor = the chat id. Cancel calls `requests.cancel`.
  - A used, expired or foreign code replies `This card is out of date.` and changes nothing.
  - By email, the same request sends the summary and `Reply yes <code> to confirm`. `email_in` routes `yes <code>` to a request when the code's scope is `request`, otherwise to the existing idea flow.
  - This task only moves requests to `queued`. Nothing runs yet.
  Tests:
  - the card shape and 64-byte limit
  - confirm queues
  - cancel cancels
  - a second tap is out of date
  - another chat's tap is refused
  - an email yes queues only for the same sender
  - idea buttons still work unchanged
  Verify with `uv run pytest -q tests/ideas/test_intent.py tests/ideas/test_bot.py tests/ideas/test_email_in.py`. Change nothing else.

- [x] ASST-MODE: An Assistant mode in the console
  Added 2026-10-26 at the user's request: the assistant gets its own console mode beside Chat, Relay and Agents, so all of its setup and settings are in one place.
  Edit `src/whyline/console/tui.py`, `tests/console/test_mode_buttons.py`, `tests/console/test_agents_mode.py`, and `tests/console/test_tui.py` only.
  - Add `"assistant"` to `_MODES` and an `Assistant` button (`#mode-assistant`) after `Agents` in the mode bar. Mode switching, the `mode:` sub-title and the button highlight work as for the other modes. Settings stays a shared control in all four modes.
  - The Assistant mode's controls row has these buttons:
    - `Inbox` and `Ideas`, moved from Agents mode with new ids `#assistant-inbox` and `#assistant-ideas`, still opening through `_open_inbox` and `_open_ideas`
    - `Assistant…`, a placeholder that ASST-7 wires to `AssistantScreen`
    - `Check`, which runs the existing inbox Check
  - Agents mode keeps saved agents only. Remove `#agents-inbox` and `#agents-ideas` from it, and update the tests that pressed them to press the Assistant-mode buttons instead, keeping what they check.
  - Typing in the input while in Assistant mode prints `Use the buttons above, or message the bot on Telegram.` and runs no agent.
  - At 80x24 the four mode buttons and Settings fit on one row, and the Assistant controls stay reachable.
  Tests:
  - switching to Assistant mode and back
  - the highlight
  - Inbox and Ideas open their screens from Assistant mode
  - Agents mode no longer shows them
  - input in Assistant mode runs nothing
  - the 80x24 layout
  Verify with `uv run pytest -q tests/console/test_mode_buttons.py tests/console/test_agents_mode.py tests/console/test_tui.py`. Change nothing else.

- [x] ASST-7: Assistant screen in the console: actions and history
  Add `src/whyline/console/assistant_screen.py` and `tests/console/test_assistant_screen.py`. Edit `src/whyline/console/tui.py` and `tests/console/test_mode_buttons.py` only to wire the Assistant mode's `Assistant…` button (from ASST-MODE) to open it.
  Later tasks that add a section to `assistant_screen.py` (Reminders, Memory, Help/doctor, Morning brief) put it on this screen, so every assistant setting is reached from Assistant mode.
  `AssistantScreen` is a modal with two sections:
  - **Actions:** one row per `actions.REGISTRY` entry, with an on/off checkbox and an approval select. A writing action's select offers only `tap`. Save calls `actions.set_policy` once per changed row and stays open, with the error, on a refusal.
  - **History:** the last 50 `requests.history` rows, showing time, channel, action, state, and the error or result path.
  Also `Save` and `Cancel` buttons. Cancel writes nothing. It works with no Telegram set up. At 80x24 and 120x40 the buttons stay reachable.
  Tests:
  - every registry action is listed
  - a writing action can't be set to none
  - Save writes only changed rows
  - Cancel writes nothing
  - history renders states
  - both sizes keep buttons on-screen
  Verify with `uv run pytest -q tests/console/test_assistant_screen.py tests/console/test_mode_buttons.py`. Change nothing else.

## Phase 3: read-only verbs

- [x] ASST-8: `status` for agents and the relay
  Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `tests/ideas/test_intent.py`, and `tests/ideas/test_bot.py` only.
  `status` keeps today's idea behaviour. Add these forms, all with no model call:
  - `status agents`: each saved agent from `whyline.agents.service.rows(None)` with its last run outcome and time, and whether it is paused
  - `status <agent-name>`: the last 3 runs from `service.history`, with the outcome and the first line of the reason
  - `status relay`: for each allowed repo with a relay state file, the plan, task, stage, and paused reason
  Each reply is one message under Telegram's 4096-character limit, truncated with `…and N more`. Unknown names reply `No saved agent named <x>.` Record a `requests` row with action `status`, state `done`.
  Tests: each form, truncation, an unknown name, the existing idea status unchanged, and no provider or subprocess called.
  Verify with `uv run pytest -q tests/ideas/test_intent.py tests/ideas/test_bot.py`. Change nothing else.

- [x] ASST-9: `run <agent>` from Telegram or email
  Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/worker.py`, `src/whyline/ideas/email_in.py`, `tests/ideas/test_intent.py`, `tests/ideas/test_bot.py`, `tests/ideas/test_worker.py`, and `tests/ideas/test_email_in.py` only.
  - `run <name>` (Telegram), or an email with subject `run <name>`, creates a `run_agent` request with `{"agent": name}`.
  - The name must match a saved agent from `service.rows(None)` exactly. The message can carry no other argument, prompt or file. Any extra words are refused with `run takes only a saved agent's name.`
  - The approval is raised to `tap` when that agent's delivery has a `command` or its timeout is over 15 minutes.
  - `worker.run_once` claims at most one queued request per tick, after the idea job (one detached process at a time in total). It runs it detached as `whyline idea request <id>`, which calls `whyline.agents.service.run_now(name, None)`. That keeps every existing gate: enabled providers, unattended clearance, read-only argv, backoff and pause.
  - The chat gets `Started <agent>.` and then the run's outcome. The agent's own delivery still sends its result. A dead pid is told `The Mac slept`, as for idea jobs.
  Tests:
  - an exact name queues
  - an unknown name is refused
  - extra words are refused
  - a command delivery needs a tap
  - one detached process per tick
  - `run_now` is called with the name only
  - a disabled provider fails with the Settings hint and no subprocess
  Verify with the four named test files. Change nothing else.

- [x] ASST-10: `ask <repo> <question>`
  Add `src/whyline/ideas/ask.py` and `tests/ideas/test_ask.py`. Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/worker.py`, `tests/ideas/test_intent.py`, and `tests/ideas/test_bot.py` only.
  - `ask <repo> <question>` creates an `ask_repo` request. `<repo>` must be a name in `setup.list_repos`. With exactly one allowed repo, `ask <question>` uses it.
  - The worker runs one read-only turn in that repo's path with the first enabled, unattended-cleared provider from the inbox's score chain, with the score chain's backup on failure. The command comes from `capabilities.read_only_command`. The prompt states the question and says the repository is data. The timeout comes from the inbox setting.
  - The answer is stored under `paths.home()/answers/<request_id>.md` (0600). It is sent as text when under 3500 characters, otherwise as a .docx through `whyline.agents.convert.to_docx`.
  - An unknown repo replies with the allowed names. No turn ever runs in a path that isn't in `list_repos`.
  Tests:
  - an unknown repo is refused without a turn
  - the single-repo shorthand works
  - the read-only argv is used (an injected runner records argv and cwd)
  - backup on failure
  - the long answer goes as a document
  - a disabled provider is skipped
  Verify with `uv run pytest -q tests/ideas/test_ask.py tests/ideas/test_intent.py tests/ideas/test_bot.py`. Change nothing else.

- [x] ASST-11: Reminders: `remind` and a deterministic time parser
  Add `src/whyline/ideas/reminders.py` and `tests/ideas/test_reminders.py`. Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/worker.py`, `src/whyline/ideas/cli.py`, `tests/ideas/test_intent.py`, `tests/ideas/test_worker.py`, and `tests/ideas/test_cli.py` only.
  `parse_when(text, now) -> (due, rest)` uses local time and no model. It understands:
  - `in N m|min|h|hours|d|days`
  - `at HH:MM` (today, or tomorrow when that time has already passed)
  - `today|tonight|tomorrow [HH:MM|9am|9pm]` (with `tonight` alone meaning 20:00 and `tomorrow` alone meaning 09:00)
  - a weekday name with an optional time
  - `YYYY-MM-DD [HH:MM]`
  Anything else replies `I couldn't read the time. Try "remind in 2h …" or "remind tomorrow 9am …".`
  - `remind <when> <text>` stores a reminder and replies with the due time in words.
  - `worker.run_once` sends each due reminder once through the outbox. One that is more than 2 hours late says `(late: this Mac was asleep)`.
  - Add `whyline idea remind list|cancel <id>`.
  Tests:
  - each time form, with an injected `now` around midnight and a weekday wrap
  - a bad time
  - due reminders are sent once
  - the late note
  - CLI list and cancel
  Verify with `uv run pytest -q tests/ideas/test_reminders.py tests/ideas/test_intent.py tests/ideas/test_worker.py tests/ideas/test_cli.py`. Change nothing else.

- [x] ASST-12: Reminders in the console
  Edit `src/whyline/console/assistant_screen.py` and `tests/console/test_assistant_screen.py` only.
  Add a **Reminders** section to `AssistantScreen`:
  - pending reminders with due time and text, each with `Cancel`, through the same function `whyline idea remind cancel` uses
  - an `Add` row (when, text) using `reminders.parse_when` and showing its error inline
  Tests: list, add, a bad time error, and cancel through the shared function.
  Verify with `uv run pytest -q tests/console/test_assistant_screen.py`. Change nothing else.

- [x] ASST-13: Memory: `remember` and `forget`
  Add `src/whyline/ideas/memory.py` and `tests/ideas/test_memory.py`. Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/assistant.py`, `src/whyline/ideas/cli.py`, `src/whyline/console/assistant_screen.py`, `tests/ideas/test_assistant.py`, and `tests/console/test_assistant_screen.py` only.
  Memory is `paths.home()/memory.md` (0600), a numbered Markdown list.
  - `remember <fact>` appends a line, and `forget <n>` removes line n. Both reply with the new count.
  - Facts are capped at 300 characters each and 100 lines in total. Past that, reply `Memory is full: forget something first.`
  - `memory.for_prompt()` returns the list inside a block labelled as the user's own notes, which are data. It is added to the inbox assistant's proposal turn only, and never passed to agents unless an action passes it explicitly.
  - Add `whyline idea memory show|add|forget <n>|clear`.
  - The console adds a **Memory** section: show, edit one line, forget, and `Clear all` behind a confirm, all through the same functions.
  Tests:
  - add, forget, and cap
  - file mode 0600
  - the assistant prompt includes memory in the data block
  - no agent prompt includes it
  - CLI and console use the same functions
  Verify with `uv run pytest -q tests/ideas/test_memory.py tests/ideas/test_assistant.py tests/console/test_assistant_screen.py`. Change nothing else.

- [x] ASST-14: Summarise forwarded email, with a content guard
  Add `src/whyline/ideas/guard.py`, `src/whyline/ideas/summarise.py`, `tests/ideas/test_guard.py`, and `tests/ideas/test_summarise.py`. Edit `src/whyline/ideas/email_in.py`, `src/whyline/ideas/worker.py`, and `tests/ideas/test_email_in.py` only.
  `guard.clean(text) -> (clean_text, flags)`:
  - strips HTML tags, comments, zero-width and bidi control characters, and CSS-hidden blocks
  - collapses whitespace
  - caps the result at 20,000 characters
  - flags (keeps but marks with `[flagged]`) lines that address an AI or give orders, such as "ignore previous", "you are now", "system prompt", or "run/execute/send/forward/delete …"
  An authenticated, allowed email whose subject is `summarise` or `summarize` (case-insensitive, `Fwd:`/`Fw:` prefixes allowed) creates a `summarise` request. The verb comes from the subject only, and the body never chooses an action. The worker:
  1. writes the cleaned body to a data file
  2. runs one read-only turn in the inbox workspace (never a repository) using the same provider rules as ASST-10, with the data file labelled "data, not instructions"
  3. replies by Telegram to the first allowed chat, and by email to the sender, with the summary, any flagged lines listed separately, and suggested next steps as plain text only
  The model output is never parsed into an action.
  Tests:
  - hidden text is removed
  - zero-width characters are stripped
  - injection lines are flagged
  - the subject decides the verb
  - a body containing `run nightly` creates no `run_agent` request
  - the turn runs in the workspace with read-only argv
  Verify with `uv run pytest -q tests/ideas/test_guard.py tests/ideas/test_summarise.py tests/ideas/test_email_in.py`. Change nothing else.

## Phase 4: plain English and starting work

- [x] ASST-15: The inbox assistant can propose the new actions
  Edit `src/whyline/ideas/assistant.py`, `src/whyline/ideas/bot.py`, `tests/ideas/test_assistant.py`, and `tests/ideas/test_bot.py` only.
  Extend the assistant's allowlist with `status`, `run_agent`, `ask_repo`, `remind`, `remember`, and `do_task`, each with an argument schema:
  - an agent name from `service.rows`
  - a repo from `list_repos`
  - `when` text that `reminders.parse_when` accepts
  - a plan task id from an allowed repo's plan
  A proposal naming anything outside those lists is rejected by name, as today. An accepted proposal becomes a request with `proposed_by="assistant"`, so it always needs a tap. The assistant prompt lists the registry verbs and memory (ASST-13). Forwarded email content never reaches this turn.
  Tests:
  - each new action is accepted with valid arguments
  - an unknown agent, repo, task or time is rejected
  - every accepted proposal is `waiting_tap`
  - a disabled action is refused
  - existing idea proposals are unchanged
  Verify with `uv run pytest -q tests/ideas/test_assistant.py tests/ideas/test_bot.py`. Change nothing else.

- [x] ASST-16: `do <task>` starts a relay task only after a tap
  Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/worker.py`, `src/whyline/ideas/run.py`, `tests/ideas/test_intent.py`, `tests/ideas/test_bot.py`, and `tests/ideas/test_run.py` only.
  - `do <repo> <TASK-ID>` (or `do <TASK-ID>` with one allowed repo) creates a `do_task` request when that id is an unchecked task of the repo's configured relay plan.
  - The card shows the repo, branch, plan, task title, and Set up roles. It always needs a tap.
  - On confirm, the worker calls a new `run.start_task(conn, repo_name, task_id, …)`. Today `run.run` is bound to an idea, so `start_task` reuses its preflight and launcher (clean repo, no relay running, Auto's checks, caffeinate) and passes the relay's existing only-this-task option (relay state field `only`). Status and Stop then work as for idea runs.
  - `do <anything else>` captures the text as a new idea and replies `Saved as idea <n>. Brainstorm or plan it from its card.` It never starts a relay from free text.
  Tests:
  - a valid task id waits for a tap
  - no relay process starts before confirm
  - a dirty repo or running relay refuses with the reason
  - an unknown id is refused
  - free text becomes an idea
  - the start passes `only=<id>`
  Verify with `uv run pytest -q tests/ideas/test_intent.py tests/ideas/test_bot.py tests/ideas/test_run.py`. Change nothing else.

- [x] ASST-17: Help text and the assistant doctor
  Edit `src/whyline/ideas/bot.py`, `src/whyline/ideas/cli.py`, `src/whyline/console/assistant_screen.py`, `tests/ideas/test_bot.py`, `tests/ideas/test_cli.py`, and `tests/console/test_assistant_screen.py` only.
  - `help` lists every enabled verb with one example each, generated from `actions.REGISTRY` and the policy.
  - Add `assistant_doctor(conn) -> list[Check]`, used by both `whyline idea doctor` and a `Check` button on `AssistantScreen`. It reports:
    - the bot token and webhook (reuse the existing checks)
    - whether the inbox service is on
    - which providers are enabled and cleared for unattended runs
    - whether `email_authserv` is set
    - whether the Mail rule script exists
    - the last email seen
    - pending reminders that are overdue (meaning the Mac slept)
    - whether memory.md is 0600
  Tests: help reflects a disabled verb, each doctor check passes and fails, and CLI and console share the function.
  Verify with the three named test files. Change nothing else.

## Phase 5: morning brief

- [x] ASST-18: Calendar export
  Add `src/whyline/ideas/brief.py`, `src/whyline/ideas/calendar_today.js`, and `tests/ideas/test_brief.py`. Edit `src/whyline/ideas/cli.py`, `src/whyline/console/assistant_screen.py`, `tests/ideas/test_cli.py`, and `tests/console/test_assistant_screen.py` only.
  - `calendar_today.js` is JXA using `ObjC.import('EventKit')`. It lists today's events from the chosen calendars (title, start, end, location, all-day, calendar name) as JSON, and reports access denied distinctly.
  - `brief.calendar(out_dir, *, calendars, run=subprocess.run)` runs it through `/usr/bin/osascript -l JavaScript` with a 30-second timeout. It writes `today.md`: time-ordered events, free blocks of 30 minutes or more between 08:00 and 19:00, and clashes.
  - Selected calendar names live in kv `brief_calendars`. An empty value means all calendars.
  - Add `whyline idea brief calendar [--preview]`.
  - The console adds a **Morning brief** section with a `Grant Calendar access and preview` button that runs the same function while the user is present, so macOS can show its permission prompt. It shows the preview or the denial with the System Settings path, and a calendar picker.
  Tests (with an injected `run` returning recorded JSON):
  - ordering
  - free blocks
  - clashes
  - all-day events
  - access denied
  - a timeout
  - calendar filtering
  - the CLI and console share the function
  Verify with `uv run pytest -q tests/ideas/test_brief.py tests/ideas/test_cli.py tests/console/test_assistant_screen.py`. Change nothing else.

- [x] ASST-19: Mail and Reminders export
  Edit `src/whyline/ideas/brief.py`, `src/whyline/ideas/cli.py`, `src/whyline/console/assistant_screen.py`, `tests/ideas/test_brief.py`, `tests/ideas/test_cli.py`, and `tests/console/test_assistant_screen.py` only.
  `brief.mail(out_dir, *, mailboxes, hours=24, limit=40, run=…)` reads unread and flagged messages through AppleScript to Mail.app, from the chosen mailboxes (kv `brief_mailboxes`), received in the last `hours`. For each message it writes sender, subject, date, and the first 40 lines of the body, passed through `guard.clean`, to `mail.md`. Bodies of mailboxes not chosen are never read.
  `brief.reminders(out_dir, run=…)` reads incomplete Reminders.app items due today or overdue into `tasks.md`, together with:
  - whyline reminders due today (ASST-11)
  - `memory.for_prompt()`
  - a one-line whyline status (paused relay, agents that failed last run)
  If Mail is not running, `mail.md` says so rather than launching Mail. The console section adds a mailbox picker and a `Grant Mail and Reminders access and preview` button. Add `whyline idea brief mail|tasks [--preview]`.
  Tests (with injected `run`):
  - parsing, the hour window, and the limit
  - the guard is applied
  - Mail not running
  - permission denied
  - unchosen mailboxes are untouched
  - tasks merge whyline reminders and memory
  Verify with the three named test files. Change nothing else.

- [x] ASST-20: A `before` step on saved agents
  Edit `src/whyline/agents/definitions.py`, `src/whyline/agents/runner.py`, `tests/agents/test_definitions.py`, and `tests/agents/test_runner.py` only.
  - Add an optional definition field `before`, whose only allowed values are `""` and `"brief-collect"`. It is a built-in name, never a shell command. Any other value raises `DefinitionError`.
  - Before building the prompt, `runner.execute_once` calls `whyline.ideas.brief.collect(run_dir)` for `brief-collect`, which writes `today.md`, `mail.md` and `tasks.md`, and adds those files as event files.
  - A collect failure is recorded on the run as `before step failed: <reason>` and no provider is started.
  - TOML round-trips keep the field.
  Tests:
  - an unknown value is refused
  - collect files become event files labelled as data
  - a collect failure starts no provider
  - agents without `before` are unchanged
  Verify with the named focused tests. Change nothing else.

- [x] ASST-21: Set up the morning brief agent from the console
  Edit `src/whyline/ideas/brief.py`, `src/whyline/ideas/cli.py`, `src/whyline/console/assistant_screen.py`, `tests/ideas/test_brief.py`, `tests/ideas/test_cli.py`, and `tests/console/test_assistant_screen.py` only.
  `brief.setup(*, at="07:00", runner, backup, chat_id)` writes the personal agent `morning-brief` through `whyline.agents.service.save_new` and then `service.accept`. The definition has:
  - trigger `weekdays` at `at`
  - `before = "brief-collect"`
  - `runner` and `backup`: enabled, unattended-cleared providers only
  - a 15-minute timeout
  - Telegram delivery as a message to `chat_id`, which must be an allowed inbox chat
  The instructions file asks for:
  1. today's schedule
  2. the top 3 priorities
  3. emails that need a reply, each with a suggested reply as text to copy
  4. clashes and preparation needed
  5. a closing fenced `brief-actions` block listing at most 5 suggested reminders as `remind <when> <text>` lines
  The instructions say never to act and never to invent events. Running setup again updates the time, runner and chat without duplicating the agent.
  Add `whyline idea brief setup --at HH:MM`. The console adds `Create morning brief` / `Update` with time, runner, backup and chat fields. The section says plainly that each brief sends calendar and email excerpts to the chosen provider and through Telegram.
  Tests:
  - the definition fields
  - a re-run updates without duplicating
  - a disabled or uncleared provider is refused
  - a chat that isn't allowed is refused
  - the CLI and console share `setup`
  Verify with the three named test files. Change nothing else.

- [x] ASST-22: Brief suggestions become reminder cards
  Edit `src/whyline/agents/deliver.py`, `src/whyline/ideas/brief.py`, `tests/ideas/test_brief.py`, and `tests/agents/test_deliver.py` only.
  After the `morning-brief` agent delivers, `brief.after_delivery(record)` reads its final text, removes the `brief-actions` block from the delivered message, and parses up to 5 `remind <when> <text>` lines with `reminders.parse_when`. Each valid line becomes a `remind` request with `proposed_by="assistant"`, so the user gets a Confirm/Cancel card. Any other line in the block is ignored and counted in the history note. No other action can come from brief output. This hook runs only for the agent named `morning-brief`.
  Tests:
  - valid lines become tap cards
  - a `run` or `do` line is ignored
  - more than 5 lines are cut to 5
  - the block is removed from the delivered text
  - other agents are unaffected
  Verify with the named focused tests. Change nothing else.

- [x] ASST-23: Morning brief check and documentation
  Edit `src/whyline/ideas/brief.py`, `src/whyline/console/assistant_screen.py`, `tests/ideas/test_brief.py`, `tests/console/test_assistant_screen.py`, and add `docs/assistant.md`. Edit `docs/idea-inbox.md` only to link it.
  `brief.check()` is added to `assistant_doctor` and the console `Check`. It reports:
  - Calendar, Mail and Reminders access
  - whether Mail is running
  - whether the agent exists and is accepted
  - the last brief's outcome
  - the next run time
  - a hint when the Mac sleeps at the brief time: set a scheduled wake in System Settings → Battery/Energy → Schedule, or `sudo pmset repeat wakeorpoweron MTWRF <time>`. This is the user's choice, and whyline never runs it.
  `docs/assistant.md` covers every verb with an example, the approval rules, the email provider check and Mail rule steps, memory, reminders, the morning brief, and the limits: Mac asleep, Telegram's 24-hour retention, provider terms, personal data sent to the provider and Telegram, and no sending to other people or calendar edits. Console steps come first and the CLI comes second.
  Run `git diff --check` and `uv run pytest -q`. If a failure needs an application-code change outside this task's files, leave the task unapproved with the exact failing test and request a new task.
