<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-waiting-on-you-design.md | created: 2026-11-14T12:00:00+05:30 -->
# Waiting on you: relay and release stops reach Telegram, with buttons

Spec: `docs/superpowers/specs/2026-11-14-waiting-on-you-design.md`. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **The security-finding card (spec card 5) is not built.** The security gate is a console screen before the release starts and leaves no saved state the worker can read. It is a later design.
- **Card text:** each task gives the exact text. Use it as written.

Runs after `plans/quick-fixes.plan.md`, and before `plans/assistant-feedback.plan.md`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Rules every task keeps:
- **Console first.** Every setting and list has a console counterpart that saves through the same function as its `whyline idea waiting …` command.
- **Messages are data.** No inbound text picks a command, path or repo. Repos come only from `whyline.ideas.setup.list_repos`. A typed word never acts without a tap on a current card.
- **The only sender is the ideas worker tick** (`whyline.ideas.worker`), through the existing outbox in `ideas/bot.py`. The relay and release code send nothing new to Telegram.
- **Every action is audited**: one `requests` row for each requested, refused, confirmed, run or failed action, as the assistant does today.
- **No secret, diff or whole log in a message.**
  - All card and answer text goes through `waiting.safe_text`, from WAIT-2.
  - Excerpts are at most 20 lines.
- **One at a time.** This plan adds the next database version to `src/whyline/ideas/store.py`. Never run it in parallel with another plan that does (waiting-on-you and the assistant plans), and run them in the order in `plans/RUN-ORDER.md`.
- **No new dependency.**
- **Tests:**
  - never call Telegram, `gh`, git remotes, a provider, or a real relay or release process
  - use temporary folders and fakes
  - never sleep for a fixed duration
  - keep Python 3.11 compatibility
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item below is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- The same stop seen on many ticks sends one card. A different stop in the same repo sends a new one. WAIT-2, `test_one_card_per_stop`.
- A stop that clears edits its card to the done text and removes the buttons. WAIT-2, `test_cleared_stop_edits_card`.
- A secret-looking value in a reason or log excerpt never reaches the outbox. WAIT-2, `test_card_text_is_redacted`.
- A tap on Resume or Rerun while the release or relay is already running does nothing and answers `Already running (started in the console).` WAIT-4, `test_tap_refused_while_running`.
- A push or publish needs Go on and then Yes. Thirty minutes with no answer pauses the release. WAIT-5, `test_go_ahead_needs_two_taps_and_times_out`.

- [ ] WAIT-1: Find what is waiting
  Create `src/whyline/ideas/waiting.py` and `tests/ideas/test_waiting.py` only.
  1. `@dataclass(frozen=True) class Waiting`: `repo: str`, `root: Path`, `kind: str`, `key: str`, `text: str`, `buttons: tuple[str, ...]`.
     - `kind` is one of `release_stopped`, `relay_stopped`, `relay_finished`.
     - `key` identifies this stop:
       - release: `f"{version}|{failed_id}|{reason}"`
       - relay stopped: `f"{plan}|{task_id}|{paused_at or paused_reason}"`
       - relay finished: `f"{plan}|done"`
  2. `scan(repos: list[tuple[str, Path]], *, relay_state=..., relay_live=..., release_state=..., pid_alive=..., plan_tasks=...) -> list[Waiting]`.
     - The defaults are `whyline_relay.state.load`, `whyline_relay.running.live`, `whyline.release.state.load`, a pid check, and `whyline_relay.plan.parse` of the state's plan. Every one is injectable for tests. Any error reading one repo skips that repo.
     - **release_stopped:** the state exists, and `failed_id` is set or `reason` starts with `You stopped before`, and it is not (`running` and the pid alive).
       - Text: `<repo> v<version> stopped at <step title or failed_id>: <reason>`.
       - When `state.failure` has a cause, use the failure's plain sentence (the same text `whyline release why` prints first) instead of `<reason>`.
       - Buttons: `why`, then `rerun` when the failure has a CI cause or `resume` otherwise, then `ask`.
     - **relay_stopped:** a relay state exists, `relay_live` is None, and either `paused_reason` is set or the plan has unticked tasks.
       - Text: `<repo> relay paused at <task_id>: <paused_reason>`, or `<repo> relay stopped at <task_id>` when there is no reason.
       - Buttons: `why`, `resume`, `ask`.
     - **relay_finished:** a relay state exists, it is not live, and every plan task is ticked.
       - Text: `<repo> relay finished <plan file stem>: <n> tasks`.
       - No buttons.
  Tests: one per kind, a running release (live pid) gives nothing, a dead pid with `running` true counts as stopped, a CI failure offers `rerun` not `resume`, an unreadable repo is skipped and the others still scanned, and keys differ when the reason or task changes.

- [ ] WAIT-2: Send, dedupe, redact and clear cards
  Edit `src/whyline/ideas/waiting.py`, `src/whyline/ideas/worker.py`, `src/whyline/ideas/store.py` (schema), `src/whyline/ideas/bot.py` and their tests only.
  1. A `waiting_cards` table, as the next schema version in `store.py`'s migration list.
     - Columns: `id`, `repo`, `kind`, `key`, `chat_id`, `message_id`, `nonce`, `state` (`open`/`done`), `created`, `updated`.
     - Unique `(repo, kind, key)`.
  2. `safe_text(text: str, *, lines: int = 20) -> str`.
     - Replaces every secret found by `whyline.security.secrets.scan_text` with `•••`.
     - Cuts to `lines` lines and to the Telegram message limit.
  3. `sync(conn, items: list[Waiting], *, enabled: Callable[[str], bool]) -> None`.
     - For each enabled item with no row, queue one card through the bot outbox to every allowed chat (`telegram_in.allowed_chats`) and insert the row.
     - Each button's callback carries a fresh `confirm.issue` code bound to the row and the action, kept within `bot.CALLBACK_DATA_LIMIT`.
     - Button labels: `Why`, `Rerun`, `Resume`, `Ask agent` (release) or `Ask` (relay).
     - For each `open` row of a repo and kind whose key is no longer in `items`, edit the card to `<original text>\nDone ✓` with no buttons, and mark the row `done`.
  4. The worker tick calls `waiting.sync(conn, waiting.scan(setup.list_repos(conn)), enabled=…)` after `watch.tick`, inside the same try/except, so a failure is logged and never stops the worker.
  Tests: `test_one_card_per_stop`, `test_cleared_stop_edits_card`, `test_card_text_is_redacted` (a `ghp_` token in a reason), a disabled kind sends nothing, no allowed chat sends nothing and records nothing, and a sync error does not stop the worker tick.

- [ ] WAIT-3: Why and Ask taps (read-only)
  Edit `src/whyline/ideas/actions.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/waiting.py` and their tests only.
  1. Register actions `release_why`, `release_ask`, `relay_why` and `relay_ask` in `actions.py`. Each has `writes=False` and approval `none`.
  2. **Why.**
     - Release: send the text `whyline release why` prints. Call the same function the CLI calls, never a subprocess.
     - Relay: send `whyline_relay.status.pause_line` plus the last 20 lines of the relay log (`state.log_path`).
     - Everything goes through `safe_text`.
  3. **Ask.**
     - Release: run the same function as `whyline release ask` and send its answer through `safe_text`.
     - Relay: reply `What do you want to ask about the <repo> relay?`. The chat's next free-text message is the question, the same pending-question mechanism **Refine** uses. Answer with `whyline.relaychat.ask.ask(root, question)`.
  4. A tap whose code is stale, or whose row is `done`, answers `This card is out of date.`
  Tests: each action calls its function with the card's root and audits one request, a relay Ask takes the next message as the question, a stale tap is refused, and a typed `why` without a card is answered with help text, not run.

- [ ] WAIT-4: Resume and Rerun taps
  Edit `src/whyline/ideas/actions.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/waiting.py`, `src/whyline/release/cli.py` and their tests only.
  1. Register `release_resume`, `release_rerun` and `relay_resume`. Each has `writes=True` and approval `tap`.
  2. Before acting, check whether the release state is `running` with a live pid, or `whyline_relay.running.live(root)` for a relay. If it is, answer `Already running (started in the console).` and do nothing.
  3. **Release.** Start a detached `whyline release resume --confirm-via telegram` (or `rerun …`) in the repo, the way `ideas/run.py` spawns relays, and answer `Resuming v<version>.`
     - For a tests-failed cause, Rerun first asks `Tests failed. Rerunning won't fix a real failure. Rerun anyway?` with **Rerun anyway** and **Cancel**.
  4. **Relay.** Resume through `whyline.ideas.watch.resume_relay` (the `console.recovery` path), and answer `Resuming the <repo> relay.`
  5. Add the `--confirm-via` option (choices `terminal` (the default) and `telegram`) to `resume` and `rerun` in `release/cli.py`, hidden from help. In this task, `telegram` is accepted and behaves like `terminal`. WAIT-5 makes it real.
  Tests: `test_tap_refused_while_running` (release and relay), the spawned argv for resume and rerun, the tests-failed second question, the audit rows, and `--confirm-via` parsing.

- [ ] WAIT-5: Go-ahead from Telegram for a resumed release
  Create `src/whyline/ideas/goahead.py` and `tests/ideas/test_goahead.py`. Edit `src/whyline/release/cli.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/actions.py` and their tests.
  1. `goahead.confirm_step(root, version, step, *, wait_minutes=30, clock=..., poll=...) -> bool`.
     - Queues a card: `<repo> v<version> is ready to: <step title>.` For a push, the text adds `<n> commits` (from `git rev-list --count origin/<branch>..HEAD`). The card has **Go on** and **Stop**.
     - **Go on** answers with a second card: `<step title> for v<version>? This can't be undone.` with **Yes, <short verb>** and **Stop**. The short verb is `push`, `tag`, `release` or `publish`, from the step id.
     - Returns True only after **Yes**. **Stop** returns False. No answer within `wait_minutes` returns False and edits the card to `No answer in 30 minutes; the release is paused. Press Resume on the stopped card to go on.`
     - It waits by polling the request row, never with a fixed sleep in tests.
  2. `goahead.confirm_notes(root, version, path) -> bool`. Sends the notes through `safe_text`, as a message, or as a file when they are longer than one message. The buttons are **Approve notes** and **Stop**.
  3. With `--confirm-via telegram`, `release/cli.py`'s `_confirmers` returns these two functions instead of the terminal prompts.
  4. Register `release_go`, with `writes=True` and approval `tap`.
  Tests: `test_go_ahead_needs_two_taps_and_times_out` (Go on then Yes gives True; Go on alone, then the timeout, gives False and the paused text; Stop gives False), the notes as a message and as a file, the commit count in a push card, and the terminal confirmer unchanged without the option.

- [ ] WAIT-6: Settings, list and doctor in the console and CLI
  Edit `src/whyline/ideas/waiting.py`, `src/whyline/ideas/cli.py`, `src/whyline/console/assistant_screen.py`, the assistant doctor (`ideas/cli.py` doctor) and their tests only.
  1. `waiting.settings(conn) -> dict[str, bool]` and `waiting.set_enabled(conn, kind, on: bool)`, stored in kv. All three kinds are on by default.
  2. `waiting.open_cards(conn) -> list[row]`.
  3. **CLI.**
     - `whyline idea waiting` prints the open cards (repo, kind, text, age) and the settings.
     - `whyline idea waiting set <kind> on|off` saves through `set_enabled`.
  4. **Assistant screen.**
     - A **Waiting on you** section with one checkbox per kind, saving through `set_enabled`.
     - A table of open cards from `open_cards`.
  5. The assistant doctor adds the line `Waiting on you: on for <kinds>; last card <time or never>`.
  Tests: CLI and console both save through `set_enabled`, the list matches `open_cards`, the doctor line, and an unknown kind refused.

- [ ] WAIT-7: Docs
  Edit `docs/assistant.md`, `docs/release.md` and `README.md` only.
  Cover:
  - the three cards and their buttons
  - that buttons do what the console does
  - the two taps for a push or publish, and the 30-minute pause
  - turning kinds on and off in the console and the CLI
  - that the security Allow stays in the console
  Verify with `uv run pytest -q`.
