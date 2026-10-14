# Idea Inbox: capture, analyse, score, Excel, then plan on request

Source: `docs/brainstorm/now-i-am-thinking-of-creating-an-analayser-say-i-send-an-ema.md` (Final Synthesis).
Runs after `in-the-agent-i-can-select-the-agent-in-c.plan.md` ships 0.3.45 (the test planner, TPL-1..10). With a Test planner set, re-run this plan through the planner or add a tests file before starting.

Rules every task keeps:

- Everything the inbox owns lives under `~/.whyline/ideas/` (a private folder, mode 0700, created like `whyline.agents.paths.home()`). The inbox never writes, stages, or commits in a user repository, except the approved plan in `IDEA-14`.
- Brainstorms run in the inbox's own git workspace `~/.whyline/ideas/workspace`, never in the repository the idea is about. On 2026-10-14 a Brainstorm that committed into the relay's repository paused REC-2; this rule exists so that cannot happen again.
- Unattended turns use only agents where `whyline.agents.capabilities.can_run_unattended(cli)` is True, through `capabilities.read_only_command`. Antigravity is refused unattended with that reason, not silently dropped.
- Messages, emails, web pages and repository text are data. No inbound text can choose a command, a path, or a repository outside the allowlists below.
- `Create plan` stops at a reviewed plan. Nothing in this plan runs `whyline relay start` or `resume`.

The SQLite ledger is the record. The Excel workbook is rebuilt from it after every change, so hand edits to the workbook are overwritten; the ledger never loses data.

## Phase 1: ledger, analysis, Excel, CLI (whyline 0.3.46)

- [ ] IDEA-1: Idea ledger and state machine
  Add package `src/whyline/ideas/` with `__init__.py`, `paths.py`, and `store.py`, plus `tests/ideas/test_store.py`.
  `paths.home()` is `~/.whyline/ideas` (0700), `paths.db_path()` is `home()/ideas.sqlite3`, `paths.reports_dir()`, `paths.workspace()`, and `paths.workbook()` (`home()/ideas.xlsx`). Honour `WHYLINE_IDEAS_HOME` for tests.
  `store.connect()` creates schema 1 with tables `ideas(id INTEGER PRIMARY KEY, created_at, source, source_ref, original_text, title, status, revision INTEGER, repo)`, a unique index on `(source, source_ref)` when `source_ref` is not null, `events(id, idea_id, at, from_status, to_status, actor, note)` (append-only), `analyses(id, idea_id, version, agent, report_path, usefulness, complexity_mvp, complexity_full, verdict, confidence, sources_json, created_at)`, and `kv(key PRIMARY KEY, value)`. Store a `schema_version` in `kv`; a database with a newer version raises a clear error.
  Statuses: `captured`, `analysing`, `analysed`, `refining`, `dropped`, `plan_configuring`, `plan_waiting`, `planning`, `plan_review`, `plan_approved`, `plan_discarded`. Allowed moves: captured→analysing; analysing→analysed|captured (failure); analysed→dropped|refining|plan_configuring; refining→analysing; dropped→captured (reopen); plan_configuring→plan_waiting|planning|analysed (cancel); plan_waiting→planning; planning→plan_review|analysed (failure); plan_review→plan_approved|plan_discarded|planning (revise).
  Functions: `add(conn, text, *, source, source_ref=None) -> Idea` returns the existing idea for a repeated `(source, source_ref)` instead of a duplicate; `get`, `list_ideas(conn, status=None)`; `transition(conn, idea_id, to, *, expected_revision, actor, note="")` raises `IllegalMove` for a move not listed and `StaleRevision` when the revision differs, and on success bumps `revision` and appends one event in the same transaction; `add_analysis(conn, idea_id, ...)` gives the next version number.
  Tests: every allowed move works and one disallowed move raises; a stale revision raises and writes nothing; a repeated source_ref returns the same id; events are appended in order; a newer schema_version is refused.
  Verify with `uv run pytest -q tests/ideas` and `uv run pytest -q`. Change nothing else.

- [ ] IDEA-2: The scoring contract
  Add `src/whyline/ideas/report.py` and `tests/ideas/test_report.py`. No model calls here.
  An analysis turn must end with a fenced block tagged `idea-report` holding JSON: `title` (≤80 chars), `problem`, `users`, `usefulness` 1-9, `complexity_mvp` 1-9, `complexity_full` 1-9, `verdict` one of `YES`, `NO`, `NOT YET`, `confidence` one of `low`, `medium`, `high`, `existing` (list of `{name, url, how_it_differs}`), `sources` (list of `{url, title}` the agent actually opened), `deploy` (where it would run and why), `risks` (list), `next_step` (one sentence).
  `parse(text) -> Report` takes the last such block, validates every field and range, and raises `ReportError` naming the first bad field. `existing` may be empty only when `sources` is not; an empty `sources` forces `confidence` to `low` and adds a risk line "no sources were checked". `render_markdown(report, original_text)` gives the report a reader sees, with the original text quoted first and a `Sources checked` list. `RUBRIC` is a module constant with the 1-9 definitions for usefulness and complexity that `IDEA-3`'s prompt includes; changing it needs a new `RUBRIC_VERSION`.
  Tests: a valid block parses; the last of two blocks wins; out-of-range scores, an unknown verdict, and missing fields raise naming the field; no sources forces low confidence; the rendered report quotes the original text.
  Verify with `uv run pytest -q tests/ideas` and `uv run pytest -q`. Change nothing else.

- [ ] IDEA-3: Analyse one idea with one read-only agent turn
  Add `src/whyline/ideas/analyse.py` and `tests/ideas/test_analyse.py`.
  `analyse(conn, idea_id, *, agents: list[str], run_fn=None, timeout_minutes=15, unattended=True) -> Analysis`. Move the idea to `analysing`. Try each agent in order: skip, with a recorded reason, any agent where `capabilities.can_run_unattended` is False when `unattended`, or `can_run` is False otherwise. Build its command with `capabilities.read_only_command` and run it through `whyline_relay.agents.run` (or `run_fn`) with `cwd=paths.workspace()`, never a user repository.
  The prompt holds the original text, the `report.RUBRIC`, the titles and verdicts of the 50 most recent other ideas (so it can flag a repeat), and these instructions: search the web and GitHub for existing products, libraries and repositories that do this; list only sources it opened; "not found" is not "does not exist"; end with the `idea-report` block.
  On a parsed report: write `render_markdown` to `paths.reports_dir()/<id>-v<version>.md`, store the analysis, set the idea's title from the report, and move to `analysed`. A model failure (missing, login, rate limit, timeout) or a `ReportError` moves to the next agent; when every agent fails, move back to `captured` with an event note naming each agent and its reason.
  Tests with a fake `run_fn`: a valid answer stores version 1 and moves to `analysed`; a second analysis is version 2; a malformed answer falls through to the next agent; antigravity is skipped unattended with its reason; all failing returns the idea to `captured` naming every agent; the fake sees `cwd` equal to the workspace.
  Verify with `uv run pytest -q tests/ideas` and `uv run pytest -q`. Change nothing else.

- [ ] IDEA-4: The Excel workbook, written with the standard library
  Add `src/whyline/ideas/xlsx.py` and `tests/ideas/test_xlsx.py`. Write SpreadsheetML with `zipfile` and `xml.sax.saxutils`, the way `whyline/agents/docx.py` writes Word files; add no dependency.
  `export(conn, target=None) -> Path` writes four sheets from the ledger: `Ideas` (id, created, source, title, status, latest usefulness, MVP complexity, full complexity, verdict, confidence, report path), `Scores` (one row per analysis version), `Sources` (idea id, version, title, url), `History` (every event). Bold frozen header row, sensible column widths, dates as real date cells.
  Any text starting with `=`, `+`, `-`, `@`, a tab, or a carriage return is written with a leading `'` so Excel never evaluates it. Write to a temp file in the same folder, reopen it with `zipfile`, parse each sheet, and check the row counts match the ledger before `os.replace`. If the replace fails because the file is open or locked, write `ideas-<YYYYmmdd-HHMMSS>.xlsx` beside it and return that path; never delete the old workbook first.
  Tests: the workbook opens as a zip with the four sheets and the right row counts; a title `=HYPERLINK("x")` is stored as text; a failing `os.replace` leaves the old file and returns the timestamped one; an empty ledger writes headers only.
  Verify with `uv run pytest -q tests/ideas` and `uv run pytest -q`. Change nothing else.

- [ ] IDEA-5: `whyline idea` commands
  Edit `src/whyline/cli.py` and add `src/whyline/ideas/cli.py` and `tests/ideas/test_cli.py`.
  Commands: `whyline idea add "<text>"` (prints the id; `--analyse` runs `IDEA-3` straight away), `list [--status S]`, `show <id>` (latest report and history), `analyse <id> [--agent A ...]`, `refine <id> "<extra context>"` (appends the context to the idea as an event, moves analysed→refining→analysing and analyses again), `drop <id>`, `reopen <id>`, `export` (prints the workbook path), `doctor` (folder permissions, database schema, which agents can run unattended, workbook writable). Default agents for `analyse` come from `kv` key `default_agents`, set by `whyline idea agents claude codex grok`, defaulting to the first unattended-capable agents installed. Every command that changes the ledger calls `xlsx.export` afterwards and prints the workbook path.
  Tests: add then list shows the idea; drop then reopen round-trips; analyse with a fake runner prints the scores; `doctor` reports an unwritable workbook; an unknown id exits 1 with a clear message.
  Verify with `uv run pytest -q tests/ideas` and `uv run pytest -q`. Change nothing else.

- [ ] IDEA-6: Publish whyline 0.3.46
  relay-profile: release
  Bump `pyproject.toml` to `0.3.46`. Write `docs/releases/v0.3.46.md` in the shape of the previous release notes: `whyline idea` captures an idea, analyses it with one read-only agent turn that lists the sources it checked, scores usefulness and complexity 1-9 with a YES / NO / NOT YET verdict, and keeps every idea in `~/.whyline/ideas/ideas.xlsx`, rebuilt from a local database. Run `uv run pytest -q` and confirm it exits 0. Tag `v0.3.46`, push, publish to PyPI the way the previous release was published, and confirm `uv tool upgrade whyline` installs `0.3.46`.

## Phase 2: Telegram (whyline 0.3.47)

Review point: use the CLI for real ideas for a few days before starting this phase.

- [ ] IDEA-7: Read Telegram messages from allowed chats only
  Add `src/whyline/ideas/telegram_in.py` and `tests/ideas/test_telegram_in.py`. Use `whyline.agents.telegram`'s token and `_call`; add nothing to that module.
  Allowed chats are a list in `kv` key `telegram_allow`, managed by `whyline idea telegram allow <chat-id>` / `deny <chat-id>` / `list` (add these to `ideas/cli.py`), offered from `telegram.known_chats()`. Only private chats may be allowed.
  `poll_once(conn, *, http=None) -> int` calls `getUpdates` with `offset` = stored cursor + 1 and `timeout=0`. In one transaction per update: store it in a new `inbound(update_id UNIQUE, chat_id, at, kind, text, callback_data, reply_to_message_id, handled INTEGER)` table (schema 2 migration in `store.py`), then advance the cursor. Updates from chats not allowed are recorded as handled with no reply. Messages over 4000 characters are kept whole. A network error leaves the cursor where it was.
  Tests with a fake `http`: two updates are stored once each and the cursor advances; a repeated update id is ignored; a message from another chat gets no reply and is marked handled; a network error stores nothing and keeps the cursor; schema 1 databases migrate to 2.
  Verify with `uv run pytest -q tests/ideas` and `uv run pytest -q`. Change nothing else.

- [ ] IDEA-8: Work out what a message means, without a model when possible
  Add `src/whyline/ideas/intent.py` and `tests/ideas/test_intent.py`.
  `route(text, callback_data, *, open_question) -> Intent` returns one of `capture(text)`, `action(name, idea_id, revision)`, `command(name, args)`, `answer(text)`, or `unclear(text)`. Button callbacks are `<action>:<idea_id>:<revision>` and are parsed exactly. Commands are `/new`, `/list`, `/status`, `/excel`, `/plan`, `/drop <id>`, `/help`, with or without the slash, matched case-insensitively and with `difflib.get_close_matches(cutoff=0.8)` so `exel` and `/staus` work. A reply while `IDEA-14` has an open planner question is `answer`. Any other text is `capture`.
  Agent names in a plan request are normalised by `normalise_agent(word)`: aliases `agy`→`antigravity`, `claud`/`cluade`→`claude`, `codx`→`codex`, `grock`→`grok`, then `get_close_matches(cutoff=0.75)` over `claude`, `codex`, `antigravity`, `grok`; no match returns None.
  Only text that starts like a command but matches none (`unclear`) may be sent to one constrained model turn (`IDEA-3`'s agent order, read-only, `cwd` the workspace) that must answer `INTENT: <one of the commands>` or `INTENT: none`. The answer never acts by itself: the bot replies "Did you mean /excel?" with Yes / No buttons.
  Tests: each command and its near-misses route correctly; callback data parses and malformed data is `unclear`; agent aliases and typos normalise and `banana` returns None; plain prose is `capture`; a fake model answer produces a confirmation, not an action.
  Verify with `uv run pytest -q tests/ideas` and `uv run pytest -q`. Change nothing else.

- [ ] IDEA-9: Reply with cards, buttons, and a retrying outbox
  Add `src/whyline/ideas/bot.py` and `tests/ideas/test_bot.py`.
  Outgoing messages go into an `outbox(id, chat_id, kind, text, buttons_json, document_path, attempts, next_try_at, sent_at)` table (schema 3) and `flush_outbox(conn, *, http=None)` sends them with `sendMessage` / `sendDocument` and an inline keyboard, retrying with backoff 1, 5, 15, 60 minutes and giving up after 8 attempts with an event note. Button presses are acknowledged with `answerCallbackQuery`.
  `handle(conn, inbound) ` per intent: `capture` stores the idea (`source="telegram"`, `source_ref=<chat>:<message_id>`) and replies with a card: the normalised first line, and buttons Analyse / Cancel. `Analyse` queues a job (`IDEA-10`) and replies "Analysing with <agents>…". When an analysis lands, send the summary (title, three scores, verdict, confidence, top three existing products) with buttons Full report / Create plan / Refine / Drop / Excel. `Full report` sends the report `.md` as a document; `Excel` runs `xlsx.export` and sends the workbook; `Drop` asks to confirm; `Refine` asks "What should I add?" and the next reply is the extra context. A button whose revision is older than the idea's replies "This card is out of date" and changes nothing. `/help` lists the commands and the `/plan` template from `IDEA-12`.
  Tests with fake http: a message produces one idea and one card; pressing Analyse twice queues one job; a stale button changes nothing; Excel sends a document; an outbox send that fails is retried later and not duplicated after success.
  Verify with `uv run pytest -q tests/ideas` and `uv run pytest -q`. Change nothing else.

- [ ] IDEA-10: Run the inbox from the existing scheduler, with leases
  Edit `src/whyline/agents/tick.py` and add `src/whyline/ideas/worker.py` and `tests/ideas/test_worker.py`.
  `whyline idea service on|off|status` sets `kv` key `enabled` and, when turning on, makes sure the existing scheduler is on (`whyline.agents.launchd.turn_on`). `tick.run_tick` calls `ideas.worker.run_once()` when enabled, inside a try/except that logs and never breaks scheduled agents.
  `run_once` runs `telegram_in.poll_once`, handles unhandled inbound rows, starts at most one queued job in a detached subprocess (`whyline idea work <job-id>`, the way `tick._spawn` starts agents), and flushes the outbox. Jobs live in `jobs(id, idea_id, kind, state, lease_until, attempts, error)` (schema 4); a job's lease is 30 minutes beyond its agent timeout, and an expired lease is re-queued once, then failed with a message to the chat. On startup after the Mac was off, the same steps catch up: Telegram keeps undelivered updates for about 24 hours, and `whyline idea service status` says so.
  Tests: a disabled inbox does nothing; an exception in the inbox does not stop `run_tick` from starting due agents; one queued job is started once even across two ticks; an expired lease re-queues once then fails with a chat message.
  Verify with `uv run pytest -q tests/ideas tests/agents` and `uv run pytest -q`. Change nothing else.

- [ ] IDEA-11: Publish whyline 0.3.47
  relay-profile: release
  Bump `pyproject.toml` to `0.3.47`. Write `docs/releases/v0.3.47.md`: send an idea to your Telegram bot and get scores, a report, and the workbook back, with buttons for Full report, Refine, Drop and Excel; only chats you allow are read; it runs from the existing scheduler without a terminal while you are logged in, and catches up on messages from up to about a day when the Mac was off. Run `uv run pytest -q` and confirm it exits 0. Tag `v0.3.47`, push, publish to PyPI the way the previous release was published, and confirm `uv tool upgrade whyline` installs `0.3.47`.

## Phase 3: Create plan (whyline 0.3.48)

- [ ] IDEA-12: Read a plan request and confirm it
  Add `src/whyline/ideas/plan_request.py` and `tests/ideas/test_plan_request.py`, and the `/plan` and `Create plan` handling in `src/whyline/ideas/bot.py`.
  Repositories an idea may be planned into are an allowlist in `kv` key `repos` (name → absolute path), managed by `whyline idea repos add <name> <path>` / `remove` / `list`; a path must be a git repository.
  `parse(text) -> PlanRequest(models, passes, final, backup, repo)` reads lines `models:`, `passes:`, `final:`, `backup:`, `repo:` in any order and case, using `intent.normalise_agent` for every name. Defaults: models from `default_agents`, passes 1, final the first model, backup empty, repo the only allowlisted repo if there is one. Errors name the line: unknown agent, passes outside 1-3, unknown repo. Antigravity, or any agent where `can_run_unattended` is False, is removed with a note saying why.
  `Create plan` sends the template with placeholders:
  `create plan` / `models: claude, codex, grok` / `passes: 1` / `final: claude` / `backup: codex` / `repo: <one of: ...>`
  and the reply produces a confirmation card showing the normalised request, with Start / Edit / Cancel, moving the idea to `plan_configuring`.
  Tests: a full request parses; typos in agent names normalise; antigravity is removed with its reason; an unknown repo and passes 5 fail naming the line; Cancel returns the idea to `analysed`.
  Verify with `uv run pytest -q tests/ideas` and `uv run pytest -q`. Change nothing else.

- [ ] IDEA-13: Brainstorm in the inbox's own workspace
  Add `src/whyline/ideas/brainstorm.py` and `tests/ideas/test_brainstorm.py`.
  `paths.workspace()` is a git repository the inbox creates on first use (`git init`, one empty commit). `run(conn, idea_id, request, *, run_fn=None)` calls `whyline.console.adapters.run_brainstorm(root=paths.workspace(), topic=..., agents=request.models, passes=request.passes, final_agent=request.final, attachments=[latest report])`. The topic is the idea's original text plus one line naming the target repository's path, which the agents may read but must not change. Progress lines go to the chat, at most one message per minute.
  After it finishes, copy the synthesis to `paths.home()/brainstorms/<id>.md`, send it as a document, and record the path. Before and after, snapshot the target repository's `HEAD` and `git status --porcelain`; any difference fails the job with the changed paths and is reported.
  Tests with a fake `run_fn`: the brainstorm writes inside the workspace only; the target repository's HEAD and status are unchanged; a fake that touches the target repository fails the job naming the path; the synthesis is sent as a document.
  Verify with `uv run pytest -q tests/ideas` and `uv run pytest -q`. Change nothing else.

- [ ] IDEA-14: Draft the plan in the target repository and stop for review
  Add `src/whyline/ideas/planning.py` and `tests/ideas/test_planning.py`.
  Before drafting, the target repository must have a clean `git status --porcelain` and `whyline_relay.running.live(root)` must be None. Otherwise move the idea to `plan_waiting`, tell the chat once ("Waiting: a relay is running in <repo>" or the dirty paths), and retry on each tick.
  Draft with `whyline_relay.planner.draft(root, settings, request)` where the request is the brainstorm synthesis plus the analysis report. Planner questions go to the chat as one message; the reply is passed to `planner.answer`. When the draft is ready, move to `plan_review` and send the draft file with Approve / Revise / Discard. `Revise` takes the reply as feedback for `planner.revise`. `Approve` calls `planner.approve(root, draft, name=<slug>)` only after rechecking the clean tree and that no relay is running, then replies with the plan path and "Start it from Set up when you are ready". `Discard` calls `planner.discard`. Nothing here calls `whyline relay start` or `resume`.
  Tests with fakes: a dirty repository waits and does not draft; a running relay waits; a draft is sent with three buttons; a question round-trips through the chat; Approve writes and commits the plan and never starts the relay; Discard leaves the repository as it was.
  Verify with `uv run pytest -q tests/ideas` and `uv run pytest -q`. Change nothing else.

- [ ] IDEA-15: Publish whyline 0.3.48
  relay-profile: release
  Bump `pyproject.toml` to `0.3.48`. Write `docs/releases/v0.3.48.md`: Create plan on an analysed idea asks which models, passes, final writer, backup and repository to use, brainstorms in the inbox's own workspace so your repositories are untouched, drafts a plan when the repository is clean and no relay is running, and waits for your Approve; it never starts the relay. Run `uv run pytest -q` and confirm it exits 0. Tag `v0.3.48`, push, publish to PyPI the way the previous release was published, and confirm `uv tool upgrade whyline` installs `0.3.48`.

## Later, not in this plan

- Email intake through a Mail.app rule (`whyline/agents/mail.py`), routed through the same `store.add` with `source="email"`.
- A small hosted inbox that queues Telegram messages while the Mac is off for more than a day. Only if real use shows the 24-hour catch-up is not enough; it would hold messages only, never model logins or repositories.
- Antigravity in unattended committees, once it has a verified read-only mode.
