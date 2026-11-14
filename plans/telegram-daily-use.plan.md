<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-15T00:20:00+05:30 -->
# Telegram daily use and the plan queue: waiting cards, the queue, instant feedback and the router

Runs after `plans/quick-fixes.plan.md`, and before `plans/raaid-log.plan.md`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

This plan joins four plans so they run in one relay and ship in one release. They were `waiting-on-you`, `plan-queue`, `assistant-feedback` and `assistant-router`. The tasks and their ids are unchanged. The parts run in the order below: Part 2 needs Part 1, and Part 4 needs Part 3.

There is no publish task. When the relay finishes, press **Release** once for all four parts.

How to read this plan:
- **A task belongs to the part its id names:** WAIT to Part 1, QUE to Part 2, FB to Part 3, RT to Part 4.
- **A task keeps the rules of its own part, plus the rules for every part below.** Another part's rules and review focus do not apply to it.
- **A reviewer's bar is the task's own tests plus its own part's review focus list.** A gap outside the bar is recorded with `whyline handoff <task> --issue "follow-up: <gap>"` and the task is approved, never rejected for it.
- **Where a part says "this plan", it means that part.**

Rules for every part:
- **Console first.** Every setting and action has a console counterpart saving through the same function as its CLI command.
- **Messages are data.** No inbound text chooses a command, a path, a repo, a plan or a version.
- **Database versions go in order.** Parts 1, 3 and 4 each add the next database version to `src/whyline/ideas/store.py`, one after the other. Never run this plan in parallel with another plan that does.
- **No new dependency.** Keep Python 3.11 compatibility.
- **Tests never call Telegram, a provider, `gh`, a remote, or a real relay or release.** Use fakes and temporary folders, and never sleep for a fixed time.
- **Edit only the files a task names, plus their tests.** Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

## Part 1: Waiting on you: relay and release stops reach Telegram, with buttons (WAIT-1..7)

Spec: `docs/superpowers/specs/2026-11-14-waiting-on-you-design.md`. Read it before every WAIT task. Where this plan and the spec differ, this plan wins. In particular:
- **The security-finding card (spec card 5) is not built.** The security gate is a console screen before the release starts and leaves no saved state the worker can read. It is a later design.
- **Card text:** each task gives the exact text. Use it as written.

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

## Part 2: Plan queue: run several plans one after another, releasing as it goes (QUE-1..11)

It needs Part 1's Telegram cards. Spec: `docs/superpowers/specs/2026-11-14-plan-queue-design.md`. Read it before every QUE task. Where this plan and the spec differ, this plan wins. In particular:
- **Rehearse and the release record are not used here.** `plans/release-safety.plan.md` runs later. The go-ahead shows the Ready check's result only. Using Rehearse in the go-ahead is a follow-up for that plan.
- **The install check covers PyPI and npm targets.** Other targets are skipped with a line saying so.
- **No database change.** Telegram cards reuse the tables `waiting-on-you` added.

Why: whyline can take one plan from relay to a released version without the user, but it cannot go on to the next plan. Between two plans the user has to notice the relay ended, release, wait, pick the next plan and start it. `plans/RUN-ORDER.md` lists over 30 plans.

What the user gets:
- A **Queue** screen: tick plans, order them, choose `Release` or `Carry on` after each, and Start.
- One setting for the queue, **Publish by itself** or **Ask me before publishing**, and an **Ask me** box per plan.
- The queue runs each relay, releases, checks the published version installs, brings in main and starts the next plan, with the console closed if the user likes.
- Any failure holds the queue where it is and says why. It never skips ahead.

Words used in this plan:
- **item**: one plan in the queue, with its settings and state.
- **stage**: one of `bring-in`, `relay`, `go-ahead`, `release`, `install-check`.
- **hold**: the queue stops at a stage, keeps its place and runs nothing until resumed.

Rules every task keeps:
- **Console first.** Every queue action is in the console's Queue screen and calls the same function as its `whyline queue …` command.
- **The queue removes questions, never checks.** No stage passes a flag or builds a step list that skips a release step, a check, the security scan or Verify. The release it runs is the one `whyline release run --mode auto` runs.
- **A hold never advances.** After any failure the queue's position does not move, and no later item starts.
- **The queue never forces and never edits.** No force push, no deleted tag or branch, no `--no-verify`, no merge strategy option. It never edits a plan, a spec or code.
- **Reuse, don't copy.** Starting a relay, merging main and running a release each go through the existing function named in the task. Where that code is inline today, the task moves it into a function and both callers use it.
- **Inbound text is data.** No Telegram message text chooses a plan, a version, a position or a command. Buttons carry ids that are looked up in the queue's own state.
- **No secret's value** in the state file, the log, a card or a dialog. Hold reasons pass `security.secrets` redaction, and home paths are shown as `~`.
- **No new dependency.**
- **Tests:** never start a real relay, release, `gh`, `uv`, `npm`, Telegram or a remote. Use fakes, temporary repositories and injected `run`, `spawn` and `clock` functions. Never sleep for a fixed time. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- The queue's release runs every step the normal release runs, in the same order. QUE-4, `test_release_stage_runs_every_step`.
- After a hold at any stage, no later item starts and the position is unchanged. QUE-5, `test_hold_never_skips_ahead`.
- A release is never started twice for one plan, by the queue and by `Release when a plan completes`. QUE-5, `test_release_is_not_started_twice`.
- Skip is refused once the item's relay has made a commit. QUE-5, `test_skip_refused_after_a_commit`.
- A go-ahead given for one commit is not used for another. QUE-6, `test_go_ahead_is_for_one_commit`.
- A Telegram tap with an unknown or stale id does nothing, and message text never selects an item. QUE-10, `test_taps_only_act_on_known_ids`.

## Part 3: Assistant feedback: an always-on listener, reactions and a "Working on it" message (FB-1..7)

Spec: `docs/superpowers/specs/2026-11-14-assistant-2-design.md`, Part 2. Read it before every FB task. Where this plan and the spec differ, this plan wins. In particular:
- **Reactions are 👀 (received), 👍 (done) and 😢 (failed).** Telegram bots may only set reactions from a fixed list, and ✅ and ❌ are not on it.
- **The listener is the existing worker loop kept running**, not a second poller. It holds the poll lock, so the 120-second tick still returns without polling, as it does today when the lock is taken.

Why: a Telegram message can wait up to 120 seconds to be read (`agents/launchd.py`, `StartInterval`), then up to 120 more for a read-only agent turn that runs inside the poll loop (`bot._free` → `assistant.propose`), with nothing shown. The user can't tell working from failed.

What the user gets:
- 👀 on their message within about a second.
- "typing…" while an agent works, and after 8 seconds one `Working on it… (<agent>)` message that is later edited into the answer.
- Always an ending: 👍, or 😢 with the reason and a **Try again** button.

Rules every task keeps:
- **Console first.** Every setting and status has a console counterpart saving through the same function as its `whyline idea …` command.
- **Feedback never breaks the work.** A failed reaction, chat action or edit is logged and ignored. It never fails a poll, a turn or a send.
- **Only allowed chats** (`telegram_in.allowed_chats`) get a reaction or a message.
- **Messages are data.** Nothing here reads message text to choose a command.
- **One at a time.** This plan adds the next database version to `src/whyline/ideas/store.py`. Never run it in parallel with another plan that does (waiting-on-you and the assistant plans), and run them in the order in `plans/RUN-ORDER.md`.
- **No new dependency.** The bot token never appears in a log, an argv or an error (`telegram.redact`).
- **Tests:**
  - never call Telegram, launchctl, a provider or a real child process
  - use fakes and temporary folders
  - never sleep for a fixed duration (inject the clock and the sleeper)
  - keep Python 3.11 compatibility
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A reaction or chat-action error never stops the poll or the turn. FB-1, `test_feedback_errors_are_swallowed`.
- With the listener running, the 120-second tick does not poll Telegram, and no update is handled twice. FB-3, `test_tick_does_not_poll_while_listener_holds_lock`.
- A slow turn does not block reading the next message. FB-4, `test_poll_continues_while_a_turn_runs`.
- A turn that dies leaves 😢 and the stopped message, never only 👀. FB-5, `test_dead_turn_is_marked_failed`.
- A fast answer (under the delay) sends no `Working on it…` message. FB-5, `test_fast_turn_sends_no_working_message`.

## Part 4: Assistant router: decide what a message wants before anything runs (RT-1..7)

It needs Part 3's turns (FB-4) and failure replies (FB-5).

Spec: `docs/superpowers/specs/2026-11-14-assistant-2-design.md`, Part 1. Read it before every RT task. Where this plan and the spec differ, this plan wins. In particular:
- **One model turn per message, not two.** For a `task` route the router's own block is validated and turned into a card or request by the code `assistant.propose` uses today. `propose` is not called again.
- **`research` is not a route target yet.** It arrives with the research plan. Until then the router may only choose actions in `actions.REGISTRY`.

Why: `intent.route` treats text as an instruction only when it names an agent with a strong verb, or carries a time or a control word. Everything else is `capture`, so "what's on my calendar tomorrow" or "check why CI failed" becomes an idea card with Quick score and Brainstorm buttons.

What the user gets:
- A plain message is read by a router that picks: idea, brainstorm, task, question, chat, or unclear.
- An unclear message comes back with three buttons: **Save as idea**, **Do it**, **Just answer**. The choice teaches the router.
- A main and a backup agent. The backup takes over when the main fails or is out of usage, and the main is skipped until its usage resets.
- If both fail, the message is saved as an idea with **Try again**, so nothing is lost.

Rules every task keeps:
- **Console first.** Every setting, list and action has a console counterpart saving through the same function as its `whyline idea …` command.
- **The router only chooses.** It never runs a command, edits a file or sends anything. Its turn is read-only, in the inbox workspace, through `capabilities.read_only_command`, on providers that are enabled and pass `can_run_unattended`.
- **Messages are data.** The router's output can only name:
  - a route from the fixed list
  - an action in `actions.REGISTRY`
  - values `assistant.validate` accepts (allowlisted repos, saved agents, plan tasks, ideas)

  Anything else is refused by name, as today.
- **Policy is unchanged.** An action that writes still needs a tap (`requests.create` and the action's approval).
- **Every routed message is recorded** in the routing history (RT-6).
- **One at a time.** This plan adds the next database version to `src/whyline/ideas/store.py`. Never run it in parallel with another plan that does (waiting-on-you and the assistant plans), and run them in the order in `plans/RUN-ORDER.md`.
- **No new dependency.**
- **Tests:**
  - never invoke a real provider or Telegram
  - use fakes and temporary folders
  - never sleep for a fixed duration
  - keep Python 3.11 compatibility
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- Router output naming an unknown route, action, repo or agent is refused and never acted on. RT-1, `test_router_output_is_validated`.
- The main is skipped while its usage limit is remembered, and tried again after the reset time. RT-2, `test_limited_main_is_skipped_until_reset`.
- Both agents failing saves the message as an idea with Try again; the text is never lost. RT-4, `test_both_fail_saves_as_idea`.
- A `task` route for a writing action produces a request waiting for a tap, never a direct run. RT-3, `test_writing_task_needs_a_tap`.
- Low confidence shows the three buttons and acts on nothing until one is tapped. RT-5, `test_unclear_asks_and_waits`.

## Tasks

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

- [ ] QUE-1: Queue state, lock and log
  Create `src/whyline/queue/__init__.py`, `src/whyline/queue/state.py` and `tests/queue/test_state.py` only.
  1. `@dataclass class Item`: `plan: str` (path relative to the repository), `after: str = "release"` (`release` or `carry-on`), `bump: str = "patch"` (`patch` or `minor`), `ask: bool = False`, `state: str = "waiting"`, `stage: str = ""`, `version: str = ""`, `base_commit: str = ""` (HEAD when its relay started), `started: str = ""`, `finished: str = ""`, `hold_reason: str = ""`.
     - `state` is one of `waiting`, `running`, `releasing`, `waiting-for-you`, `held`, `done`, `skipped`.
  2. `@dataclass class Queue`: `schema: int = 1`, `publish: str = "ask"` (`auto` or `ask`), `items: list[Item]`, `started: str = ""`, `finished: str = ""`, `hold_after_current: bool = False`, `pid: int = 0`, `go_ahead: dict` (empty, or `version`, `commit`, `at`, `by`).
  3. `path(root)` is `.git/whyline-queue/queue.json`. `load(root) -> Queue | None` returns None for a missing file and raises `QueueError` with a plain sentence for an unreadable one or a newer `schema`. `save(root, queue)` writes atomically (`whyline.state.atomic_write_json`). Unknown keys in the file are kept on the next save.
  4. `current(queue) -> Item | None`: the first item not `done` or `skipped`. `active(queue) -> bool`: `started` is set and `finished` is not.
  5. `acquire(root, *, pid_alive=…)` and `release(root)`: a lock file `.git/whyline-queue/runner.lock` holding the pid. A lock whose pid is dead is taken over. A live one raises `QueueBusy`. `running(root, *, pid_alive=…) -> bool`.
  6. `log(root, line)` appends `<ISO time> <line>` to `.git/whyline-queue/queue.log`, after redaction, and keeps the last 2000 lines.
  Tests: round trip, unknown keys kept, a newer schema refused with its sentence, `current` and `active`, the lock taken over from a dead pid and refused for a live one, the log redacting a secret and a home path, and the log trimmed.

- [ ] QUE-2: Order, edits and warnings
  Create `src/whyline/queue/edit.py` and `tests/queue/test_edit.py` only.
  1. `candidates(root) -> list[PlanInfo]`: plans from `console.relay_ops.list_plans` that are in `plans/` itself (not `plans/done/`) and have unticked tasks.
  2. `suggest_order(root, plans) -> list[str]`: the order of the plan names in `plans/RUN-ORDER.md`'s table when that file exists; plans not in it follow, ordered by each one's `Runs after \`plans/<name>\`` line where it names another candidate, then by name. A cycle in the `Runs after` lines falls back to by name.
  3. Edits, each returning the changed `Queue` and raising `QueueError` with a plain sentence when refused: `add(queue, plan, *, after, bump, ask)`, `remove(queue, plan)`, `move(queue, plan, position)`, `set_item(queue, plan, *, after=None, bump=None, ask=None)`, `set_publish(queue, publish)`.
     - Only a `waiting` item can be removed, moved or changed, and it cannot move ahead of an item that is not `waiting`.
     - The last item not `done` or `skipped` is always `after = "release"`. Edits that would leave it `carry-on` set it back, and say so in the returned queue's `notice` (a plain string field on the result, not saved).
     - `ask=False` on an item is ignored while `publish` is `ask`.
     - A plan already in the queue is refused.
  4. `asks(queue, item) -> bool`: `queue.publish == "ask" or item.ask`.
  5. `warnings(root, queue, *, release_cfg, security_settings) -> list[str]`, in plain sentences, none blocking:
     - `<plan> runs after <other>, which isn't finished and isn't earlier in this queue.`
     - `No publish target is set, so Release will only push and tag.`
     - `The security check is off.` and `Secrets are only checked at release.` (the commit hook off)
     - `Nothing upgrades the installed tool after a release.` when the repository's project name is the running tool's (`whyline`) and `release_cfg.after` is empty.
  6. `releases(queue) -> int`: how many items not yet done have `after == "release"`.
  Tests: the order from a RUN-ORDER fixture, from `Runs after` lines and by name, a cycle, each edit and each refusal, the last item forced to release with its notice, `asks` in the four combinations, each warning and its absence, and `releases`.

- [ ] QUE-3: The bring-in and relay stages
  Create `src/whyline/queue/stages.py` and `tests/queue/test_stages.py`. Edit `src/whyline/release/source.py`, `src/whyline/console/relay_ops.py`, `src/whyline/console/tui.py` and their tests.
  1. `source.merge_main(root, cfg, message, *, run, fetch) -> int` holds the fetch, the behind count and the `merge --no-ff` with its abort-on-conflict that `bring_in_main` has today, and returns the number of commits merged. `bring_in_main` calls it, with no change in its behaviour or messages.
  2. `relay_ops.start_args(root, plan: Path) -> list[str]`: the relay arguments the console's Start uses for a plan. Where `tui.py` builds them inline today, it calls this function.
  3. `@dataclass(frozen=True) class Outcome`: `ok: bool`, `hold: str = ""` (the reason, empty when ok), `detail: str = ""`.
  4. `stages.bring_in(root, cfg, item, *, run, fetch) -> Outcome`:
     - refuses when the checkout has uncommitted changes other than release-pending files (the same test `bring_in_main` uses), with `Commit or stash these first: <files>`
     - calls `merge_main` with the message `merge: bring <branch> in before <plan name>`
     - a conflict gives a hold with `source`'s own message
     - then checks the plan file exists and parses; a missing or unparsable plan gives a hold `<plan> is missing after bringing in <branch>` or the parser's message
     - a plan with no unticked task gives `Outcome(True, detail="nothing left")`, and the runner marks it done
  5. `stages.start_relay(root, item, *, launch, checks) -> Outcome`:
     - runs `relay_ops.select_plan` and `relay_ops.run_checks(root, plan)`; any `FAIL` line gives a hold with the first one's text
     - records `item.base_commit` (HEAD)
     - starts the relay with `ideas.run.launch(start_args(root, plan), root=root)`
  6. `stages.relay_outcome(root, item, *, live, paused, plan_tasks) -> Outcome | None`: None while `whyline_relay.running.live(root)` is set. Otherwise ok when every task of the plan is ticked, else a hold with the relay's pause line (`whyline_relay.status.pause_line`) or `The relay stopped at <task> with <n> tasks left`.
  Tests: `bring_in_main` unchanged (its existing tests pass untouched), a merge, a conflict hold with the merge aborted, a dirty checkout, the plan missing after the merge, nothing left, a preflight FAIL holding without a launch, the launch argv equal to `start_args`, `base_commit` recorded, and the three relay outcomes.

- [ ] QUE-4: The release stage and the install check
  Create `src/whyline/queue/installcheck.py` and `tests/queue/test_installcheck.py`. Edit `src/whyline/queue/stages.py`, `src/whyline/release/cli.py`, `src/whyline/release/config.py` and their tests.
  1. `release/cli.py` gets `run_auto(root, cfg, *, bump: str, say, on_progress=None) -> engine.Result`: the version from the existing next-version function for `bump`, the plan from the existing plan builder, then `engine.run(mode="auto")`. `_run` calls it for `--mode auto --yes`, so both paths build one plan.
  2. `stages.release(root, cfg, item, *, run_auto=…) -> Outcome`: calls `run_auto`, stores `item.version`, and returns ok for a finished release. Any other result gives a hold with the result's message. A release already stopped for this checkout (`release.state.load` with `failed_id` or a `You stopped before` reason) is never restarted here: it gives a hold `The release of v<version> is stopped; resume it, then resume the queue`.
  3. `stages.release_done(root, item) -> bool`: no release state is left and the tag `v<item.version>` exists on `origin`. The runner uses it on resume, so a release the user finished by hand is not run again.
  4. `ReleaseConfig.install_check: str = ""`: empty means automatic, `off` turns it off, anything else is the command to run (split with `shlex`, never through a shell), with `{version}` replaced. Read and written like the other fields.
  5. `installcheck.command(root, cfg, version) -> list[str] | None`:
     - the configured command when set
     - PyPI target: `uvx --no-cache --from <project name>==<version> <first console script> --version` when `uv` is on PATH and `pyproject.toml` has `[project.scripts]`
     - npm target: `npx --yes <package>@<version> --version` when `package.json` has a `bin`
     - otherwise None
  6. `installcheck.run(root, cfg, version, *, run, clock, sleep) -> Outcome`: runs the command in an empty temporary folder with a 5-minute timeout. A non-zero exit is tried again every 30 seconds for up to 5 minutes, because a registry's index lags the upload. Still failing gives a hold `v<version> was published but doesn't install or start: <last 3 lines>`. None gives ok with the detail `No install check for this target`.
  Tests: `test_release_stage_runs_every_step` (the step ids `run_auto` hands the engine equal the ids the normal `--mode auto` run builds, in order, for a branch release and a release-branch release), a finished release, a failed one holding with its message, a stopped release not restarted, `release_done`, each `command` form, `off`, a configured command with `{version}`, the retry then success, the hold text, and round trip of `install_check`.

- [ ] QUE-5: The runner
  Create `src/whyline/queue/runner.py` and `tests/queue/test_runner.py`. Edit `src/whyline/console/tui.py` (`_plan_release_due`) and its test.
  1. `runner.step(root, *, stage_fn, clock) -> str` does one stage for the current item and saves, returning `continue`, `wait`, `held` or `finished`:
     - order per item: `bring-in`, `relay` (start, then poll `relay_outcome`), then for `after == "release"`: `go-ahead` when `edit.asks`, `release`, `install-check`
     - a `carry-on` item is `done` after its relay
     - every stage start and end is logged
     - a hold sets the item `held` with its reason and stage, and returns `held`
     - after the last item, `finished` is set and the summary line is logged: `Queue finished: <n> plans, <m> releases (<versions>), <duration>.`
     - `hold_after_current` turns into a hold with the reason `You asked to hold after <plan>` once the current item is done
  2. `runner.run(root, *, spawn, sleep, pid_alive)`: takes the lock, then loops on `step`. Each stage runs as a new process, `[sys.executable, "-m", "whyline", "queue", "stage", <name>]`, waited for. The relay is polled every 20 seconds. The loop ends on `held` or `finished` and releases the lock. An exception in the loop is logged, turned into a hold with its one-line message, and never leaves the lock behind.
  3. `runner.resume(root) -> str`: refused with the reason while the cause is still there (the relay is paused or stopped with tasks left; a release is stopped; the checkout has a merge in progress). Otherwise the item goes back to its stage and the runner can be started. A `release` stage is skipped when `stages.release_done` is true.
  4. `runner.skip(root) -> str`: marks the current item `skipped`, only while `git rev-list --count <base_commit>..HEAD` is 0 or its relay never started. Otherwise it is refused: `<plan> has commits; later plans may build on them. Stop the queue or fix and resume.`
  5. `runner.stop(root)`: sets `finished`, logs it, and leaves the checkout and any running relay alone. It is refused while a release stage is running.
  6. `runner.hold(root, *, after_current: bool)`: `after_current` sets the flag. Without it, a hold is set at once when no stage is running, else after the running stage ends. It never interrupts a relay turn or a release.
  7. The console's `_plan_release_due` returns False while `queue.state.active` is true for the checkout, so `Release when a plan completes` does not start a second release.
  Tests: `test_hold_never_skips_ahead` (a hold injected at each of the five stages, then ten more `step` calls: the position and every later item's state are unchanged), `test_release_is_not_started_twice`, `test_skip_refused_after_a_commit`, a three-item queue with one carry-on run to `finished` with fakes, the summary line, hold after current, resume refused while the relay is paused, resume skipping a release finished by hand, stop refused during a release, an exception becoming a hold with the lock released, and each stage spawned as its own process.

- [ ] QUE-6: The go-ahead
  Create `src/whyline/queue/goahead.py` and `tests/queue/test_goahead.py`. Edit `src/whyline/queue/runner.py` and its tests.
  1. `goahead.prepare(root, cfg, item, *, ready, run) -> Ask`: runs the release's Ready check for the next version and returns `version`, `commit` (HEAD), `tasks` and `commits` (since the last release tag), `ready_ok`, and `text`: `<repo>: <plan stem> is ready to release as v<version>. <n> tasks, <m> commits. Checks passed.` A failed Ready check gives a hold with its first failing item.
  2. The `go-ahead` stage sets the item `waiting-for-you`, saves the `Ask` in the queue, and returns `wait`. The runner polls the queue file every 20 seconds while waiting and runs nothing else.
  3. `goahead.give(root, version, commit, *, by) -> str`: accepted only when both match the saved `Ask` and HEAD is still `commit`. It records `go_ahead` (`version`, `commit`, `at`, `by`: `console`, `terminal` or `telegram`). Otherwise it is refused with `That go-ahead was for <old>; the queue is now at <new>. Check it again.`, and the `Ask` is prepared again.
  4. `goahead.given(root, item) -> bool`: a recorded go-ahead whose commit is HEAD. The release stage is refused without it when `edit.asks`.
  5. `goahead.decline(root)`: holds the queue with `You held the release of v<version>`.
  6. `goahead.reminder_due(queue, *, clock) -> bool`: true once, 6 hours after the `Ask` was saved.
  Tests: `test_go_ahead_is_for_one_commit` (given, then HEAD moves: `given` is false and a new `Ask` is saved), the text, a failed Ready check holding, give with a wrong version or commit refused, decline, the release stage refused without a go-ahead when asked and allowed when not asked, and the reminder true once.

- [ ] QUE-7: The CLI
  Create `src/whyline/queue/cli.py` and `tests/queue/test_cli.py`. Edit `src/whyline/cli.py` (register `queue`) and its test.
  1. Commands, each calling the function named:
     - `whyline queue list`: candidates in suggested order with their task counts (`edit.candidates`, `edit.suggest_order`)
     - `whyline queue add <plan> [--after release|carry-on] [--bump patch|minor] [--ask]`, `remove <plan>`, `move <plan> <position>`, `set <plan> […]`, `publish auto|ask`
     - `whyline queue start [--publish auto|ask] [--yes]`: prints the warnings; with `publish auto` asks `This queue will publish <n> releases without asking. Each one can't be undone. Start? [y/N]` unless `--yes`; refuses with the reason when a relay, a release or a queue is running, the checkout is dirty, or the Ready check fails for sign-in or remote; then starts `whyline queue run` detached (`start_new_session`, output to the queue log)
     - `whyline queue status`: one line per item (`<n>. <plan stem>  <state>  <detail>`), and the hold reason or the go-ahead text
     - `whyline queue hold [--after-current]`, `resume`, `skip`, `stop`
     - `whyline queue go-ahead`: prints the `Ask` text and asks `Release v<version>? This can't be undone. [y/N]` unless `--yes`
     - `whyline queue run` and `whyline queue stage <name>`: used by the runner, hidden from help
  2. A plan is named by its file name or stem, resolved only against `edit.candidates` and the queue's items. A path outside `plans/` is refused.
  3. Exit code 0 on success, 1 for a refusal, with the sentence on stderr.
  Tests: each command calling its function, the start question and `--yes`, each start refusal, a plan name outside the candidates refused, the status lines for every state, and the hidden commands absent from `--help`.

- [ ] QUE-8: The Queue screen: setting up
  Create `src/whyline/console/queue_screen.py` and `tests/console/test_queue_screen.py`. Edit `src/whyline/console/tui.py` (open it from the Relay screen's buttons and the command list) and its test.
  1. `QueueScreen` lists `edit.candidates` in `edit.suggest_order`, one row each:
     - a checkbox
     - the plan's title and `<done> of <total> tasks`
     - **After**: a select, `Release` or `Carry on`
     - **Version**: a select, `patch` or `minor`, shown only for `Release`
     - **Ask me**: a checkbox, disabled and ticked while the queue's setting is `Ask me before publishing`
     - **Up** and **Down**
  2. Above the rows: **Publishing**, a select with `Ask me before publishing` (the default) and `Publish by itself`. Below them: the warnings from `edit.warnings`, then the line `<n> plans, <m> releases`.
  3. **Start** saves through the same functions as the CLI and calls the CLI's start function. With `Publish by itself` it first shows `This queue will publish <m> releases without asking. Each one can't be undone.` with **Start** and **Ask me before each instead**. A refusal is shown in the screen with its reason.
  4. The last ticked row always shows `Release`, with the note `The last plan always releases` when the user picks `Carry on` there.
  5. All plan titles and reasons are shown with `markup=False`. The screen fits 80x24 and scrolls its rows.
  Tests: the rows in suggested order, ticking and reordering saved through `edit`, the last row forced to Release with its note, **Ask me** disabled under the queue setting, the warnings shown, the publish question and both its buttons, a refusal shown, a title with square brackets shown as plain text, and the fit at 80x24.

- [ ] QUE-9: The Queue screen: while it runs
  Edit `src/whyline/console/queue_screen.py`, `src/whyline/console/tui.py` and their tests only.
  1. While `queue.state.active`, the screen shows one row per item with its state in words: `waiting`, `running · <task>, <done> of <total> tasks`, `releasing · <step title>`, `waiting for you`, `held`, `done · v<version>`, `done · carried on`, `skipped`. It refreshes every 2 seconds from the queue file, the relay's live status (`relay_ops.live_status`) and the release state.
  2. Waiting rows keep their controls from QUE-8, plus **Remove**. **Add a plan** lists the candidates not in the queue. The running row has no controls.
  3. Buttons by state:
     - running: **Hold after this plan**, **Stop queue**
     - waiting for you: the `Ask` text, **Publish** (then `Release v<version> to <targets>? This can't be undone.` with **Yes, publish**) and **Hold**
     - held: the reason, **Resume queue**, **Skip this plan**, **Stop queue**, and **Open** which goes to the screen that fixes it (the relay's Resolve for a relay hold, the Release screen for a release hold)
  4. Each button calls the function its CLI command calls. A refusal is shown with its reason.
  5. The console title adds `queue <n> of <total>` while a queue is active, `queue held` when held and `queue waiting for you` at a go-ahead.
  6. When the queue's runner is not alive but the queue is active and not held (the Mac restarted), the screen says `The queue isn't running` with **Start it again**, which calls the same start function.
  Tests: each state's row text, the 2-second refresh with fakes, controls only on waiting rows, each button calling its function, Publish needing the second yes, a refused resume shown, the three title forms, and **Start it again**.

- [ ] QUE-10: Telegram cards for the queue
  Edit `src/whyline/ideas/waiting.py`, `src/whyline/ideas/actions.py`, `src/whyline/ideas/bot.py` and their tests only.
  1. `waiting.scan` gains three kinds, read from each repo's queue file:
     - `queue_held`: text `<repo> queue is holding at <plan stem>: <reason>. <n> plans are waiting behind this.` Buttons: `queue_resume`. When the hold comes from a stopped relay or release, that stop's own card (WAIT-1) is still sent, and this card follows it.
     - `queue_goahead`: the `Ask` text. Buttons: `queue_publish`, `queue_hold`. Key: `<version>|<commit>`.
     - `queue_finished`: the summary line. No buttons.
     Keys change with the item, stage and reason, so WAIT-2's dedupe sends each once. The 6-hour reminder (`goahead.reminder_due`) sends the go-ahead card once more with `Still waiting:` in front.
  2. Actions, registered like WAIT-4's:
     - `queue_resume` (`writes=True`, approval `tap`): `runner.resume`, then starts the runner. A refusal is answered with its reason.
     - `queue_publish` (`writes=True`, approval `tap`): answers with a second card, `Release v<version> to <targets>? This can't be undone.` with **Yes, publish** and **Hold**. **Yes** calls `goahead.give(root, version, commit, by="telegram")` with the version and commit stored in the card's request row, never from message text.
     - `queue_hold` (`writes=True`, approval `tap`): `goahead.decline`.
  3. A tap whose request row is unknown, already answered or for a version and commit the queue has moved past is answered `That card is out of date.` and does nothing.
  4. The cards are on by default and follow WAIT-6's on/off settings for relay and release cards. No new setting.
  Tests: `test_taps_only_act_on_known_ids` (an unknown id, an answered id, a stale version, and free text naming a plan: nothing in the queue changes), each kind's text and buttons, the reminder sent once, publish needing both taps, hold, resume refused with its reason, and the cards off when WAIT-6's setting is off.

- [ ] QUE-11: Docs
  Create `docs/queue.md`. Edit `docs/release.md`, `docs/assistant.md` and `README.md` only.
  Cover: setting up a queue, Release and Carry on, the two publishing settings and the per-plan box, what the queue does for each plan, the install check and its setting, every reason it holds and how to resume, Skip and why it is refused after a commit, the Telegram cards, running it with the console closed, the `whyline queue` commands, and adding an upgrade command to the release's `after` list when the repository's tool is the one running the queue.
  Verify with `uv run pytest -q`.

- [ ] FB-1: Reactions, chat actions and message ids in the Telegram client
  Edit `src/whyline/agents/telegram.py` and `tests/agents/test_telegram.py` only.
  1. `set_reaction(token, chat_id, message_id, emoji: str | None, *, http=None, sleep=time.sleep) -> bool`. Calls `setMessageReaction` with `reaction` as a JSON list holding one `{"type": "emoji", "emoji": emoji}`, or an empty list for None. Returns False on any `TelegramError` and never raises.
  2. `send_chat_action(token, chat_id, action="typing", *, http=None, sleep=time.sleep) -> bool`. Same error rule.
  3. `send_message` returns the sent message's id (`int | None`) from the API result. Existing callers ignore it.
  4. Constants `SEEN = "👀"`, `DONE = "👍"`, `FAILED = "😢"`.
  Tests: the exact fields sent for each call, `test_feedback_errors_are_swallowed` (both calls return False on an API error and on a network error), `send_message` returns the id, and the token is absent from every recorded error.

- [ ] FB-2: 👀 when a message is stored
  Edit `src/whyline/ideas/telegram_in.py`, `src/whyline/ideas/feedback.py` (new) and their tests only.
  1. `feedback.py`: `enabled(conn) -> bool` (kv `feedback_reactions`, default on) and `set_enabled(conn, on: bool)`.
  2. `feedback.seen(conn, token, chat_id, message_id, *, http=None)` sets `telegram.SEEN` when enabled. It never raises.
  3. `poll_once` calls `feedback.seen` right after it stores a text message from an allowed chat. Not for a tap (a tap is answered by `_answer_callback` already), not for a chat that isn't allowed, and not for an update it had already stored.
  Tests: a stored text message gets one 👀, a tap gets none, a refused chat gets none, a re-delivered update gets none, disabled sends none, and a reaction error leaves the row stored and the poll successful.

- [ ] FB-3: The always-on listener
  Edit `src/whyline/ideas/worker.py`, `src/whyline/ideas/listener.py` (new), `src/whyline/agents/launchd.py`, `src/whyline/ideas/cli.py`, `src/whyline/console/inbox_screen.py` and their tests only.
  1. `worker.run_once` gets `forever: bool = False`. When True, the awake loop never ends on the quiet window. It still ends when it cannot take the poll lock, when the inbox is turned off, and on a Telegram error (the process exits and launchd restarts it).
  2. `listener.run()` calls `worker.run_once(forever=True)`. On a Telegram error it waits 30 seconds (injected sleeper) before returning, so a restart loop is slow.
  3. `launchd`: a second plist, label `com.whyline.listen`, `ProgramArguments [whyline, "idea", "listen"]`, `KeepAlive` true, `ThrottleInterval` 30, and the same environment as the agents plist. Add `listener_on(run=…)`, `listener_off(run=…)` and `listener_status(run=…)`, built the same way as `turn_on`, `turn_off` and `status`.
  4. CLI: `whyline idea listen` runs the listener in the foreground. `whyline idea service on` and `off` turn the listener on and off together with the inbox. `whyline idea service status` adds the line `Listener: running (last poll <time>)` or `Listener: not running`.
  5. Console: the Inbox screen's service switch does the same through the same functions, and shows the same Listener line.
  6. The worker writes kv `last_poll` after every poll.
  Tests: `test_tick_does_not_poll_while_listener_holds_lock`, `forever` ignores the quiet window, the listener exits when the inbox is turned off, the plist's keys, on/off/status with a fake `run`, the CLI and console both call `listener_on`/`listener_off`, and an unsupported platform reports `launchd.NEEDS_MACOS`.

- [ ] FB-4: Free-text turns run outside the poll loop
  Edit `src/whyline/ideas/worker.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/turn.py` (new), `src/whyline/ideas/store.py` (schema), `src/whyline/ideas/cli.py` and their tests only.
  1. A `turns` table as the next schema version: `id`, `update_id` (unique), `chat_id`, `message_id`, `state` (`queued`/`running`/`done`/`failed`), `pid`, `agent`, `working_message_id`, `error`, `created`, `started`, `finished`.
  2. `bot.handle`, for a `free` intent, inserts a `queued` turn row and returns. It no longer calls `assistant.propose` inline. Commands, taps, settings, answers and captures are unchanged and stay inline.
  3. The worker loop starts each queued turn as a detached child, `whyline idea turn <id>`, using the same spawn helper it uses for requests. At most 2 turns run at once, and at most one per chat. A later message in the same chat waits for the earlier one.
  4. `turn.run(turn_id, *, run_fn=None, …)` marks the row `running` with its pid, calls today's free-text path (the body moved out of `bot._free`, unchanged), queues the reply through the outbox, and marks `done`, or `failed` with the error.
  5. CLI: `whyline idea turn <id>` (hidden from help).
  Tests: `test_poll_continues_while_a_turn_runs` (a queued turn whose child is still alive does not stop the next poll or the next message's 👀), one turn per chat in order, the cap of 2, a turn row is created once per update, the child's argv, and the moved free-text path gives the same replies as before for a card, a refusal and a plain answer.

- [ ] FB-5: Typing, the "Working on it" message, and an ending
  Edit `src/whyline/ideas/turn.py`, `src/whyline/ideas/feedback.py`, `src/whyline/ideas/worker.py`, `src/whyline/ideas/bot.py` and their tests only.
  1. While a turn runs, a background thread in the child calls `send_chat_action` every 4 seconds until the turn ends.
  2. After `feedback.working_delay(conn)` seconds (kv `feedback_working_delay`, default 8, 0 turns it off), the child sends `Working on it… (<agent>)` and stores its id in `working_message_id`.
  3. The answer:
     - When there is a working message and the answer is plain text, the working message is edited into the answer (`edit_message_text`).
     - When the answer is a card with buttons or a document, the working message is edited to `Done ↓` and the answer is sent as usual through the outbox.
  4. The ending: 👍 on the user's message on `done`. On `failed`: 😢, and a reply `Couldn't do that: <reason in one line>.` with a **Try again** button, which queues a new turn for the same text.
  5. Recovery: the worker's existing recovery pass marks a `running` turn whose pid is dead, or that is older than 5 minutes, as `failed` with `Stopped without an answer (the Mac slept or the agent was cut off).`, and gives it the same 😢 and reply.
  Tests: `test_fast_turn_sends_no_working_message`, a slow turn (fake clock past the delay) sends one working message and edits it into the answer, a card answer edits it to `Done ↓`, typing is sent on the 4-second cadence and stops at the end, `test_dead_turn_is_marked_failed`, Try again queues a new turn once, and reactions disabled sends no reaction but still sends the failure reply.

- [ ] FB-6: Settings and doctor
  Edit `src/whyline/ideas/cli.py`, `src/whyline/console/assistant_screen.py`, the assistant doctor in `ideas/cli.py`, and their tests only.
  1. CLI: `whyline idea feedback` prints the settings. `whyline idea feedback reactions on|off` and `whyline idea feedback delay <seconds>` save through `feedback.set_enabled` and `feedback.set_working_delay` (0 to 60).
  2. Assistant screen: a **Feedback** section with a **Reactions** checkbox and a **"Working on it" after (seconds)** input, saving through the same functions.
  3. Doctor: `Listener: running, last poll <time>` or `Listener: not running — turn the inbox on`, and `Turns: <n> running, <n> failed in the last day`.
  Tests: CLI and console save through the same functions, a delay outside 0 to 60 is refused, and both doctor lines.

- [ ] FB-7: Docs
  Edit `docs/assistant.md` and `README.md` only.
  Cover: what 👀, 👍 and 😢 mean, the `Working on it…` message, **Try again**, the listener and how to check it, and the settings.
  Verify with `uv run pytest -q`.

- [ ] RT-1: The router's prompt, block and validation
  Create `src/whyline/ideas/router.py` and `tests/ideas/test_router.py` only.
  1. `ROUTES = ("idea", "brainstorm", "task", "question", "chat", "unclear")`. `CONFIDENT = 0.7`.
  2. `@dataclass(frozen=True) class Routed`: `route: str`, `action: str = ""`, `fields: Mapping[str, object] = {}`, `confidence: float = 0.0`, `reply: str = ""`, `agent: str = ""`, `error: str = ""`.
  3. `build_prompt(text, *, recent: list[str], examples: list[tuple[str, str]], allowed: assistant.Allowed, memory: str) -> str`.
     - It holds: the six routes with one line each, the registered actions and their fields (reuse `assistant._registry_verbs_text` and `_allowed_text`), up to 5 recent messages of this chat, up to 20 `(text, route)` examples, and the memory block.
     - Every user-supplied part sits inside a block labelled as data, in the style of `memory.for_prompt`.
     - It asks for one fenced JSON block: `route`, `action`, `fields`, `confidence` (0 to 1), `reply`.
  4. `parse(text) -> Routed | None`: the last fenced JSON block (reuse `assistant._load_last_block`). None when there is no block or it is not an object.
  5. `validate(routed, allowed) -> Routed`:
     - an unknown route gives `error`
     - `task` with an action outside `actions.REGISTRY` gives `error`
     - `task` fields are checked with `assistant.validate`
     - `confidence` is clamped to 0..1
     - a confident route below `CONFIDENT` becomes `unclear`
     - `reply` is cut to 1000 characters and kept only for `question` and `chat`
  Tests: `test_router_output_is_validated` (unknown route, unknown action, unknown repo, unknown saved agent), the prompt holds the examples and the data labels, parse takes the last block, low confidence becomes unclear, and a `reply` on a `task` is dropped.

- [ ] RT-2: Main and backup, with usage-limit memory
  Edit `src/whyline/ideas/router.py`, `src/whyline/ideas/assistant.py` and their tests only.
  1. `router.limits(conn) -> dict[str, datetime]` and `router.note_limit(conn, agent, until)`, stored in kv `router_limit:<agent>` as an ISO time. An entry in the past is ignored and removed.
  2. `router.order(conn, *, now) -> tuple[list[str], dict[str, datetime]]`: `assistant._order(*assistant.selected(conn))` without the agents whose limit is still in the future, plus those skipped agents with their reset times.
  3. `router.decide(conn, text, *, chat_id, run_fn=None, now=…) -> Routed`.
     - It runs one turn per agent in order with a 30-second limit, the way `assistant._turn` runs one (same argv builder, workspace and log folder, with the log named `router-<chat>-<agent>.log`).
     - A turn that fails, times out or returns no readable block moves to the next agent.
     - When the turn's output shows a usage limit, `note_limit` records the reset time from `whyline_relay.failover.reset_deadline(text)`, or one hour from now when it gives none. The usage-limit check is the relay's own rate-limit text check in `whyline_relay.failover`. Do not write new patterns.
     - When every listed agent was skipped for a limit, the one with the earliest reset is tried anyway.
     - The result carries `agent`. When no agent produced a block, it returns `Routed(route="unclear", error=<reason>)` with the reason `no assistant agent is set`, `<agent> is out of usage until <time>` or `<agent> didn't answer`.
  4. `router.footer(routed, skipped) -> str`: empty when the main answered, else `answered by <agent> (<main> is out of usage until HH:MM)` or `answered by <agent> (<main> didn't answer)`.
  Tests: `test_limited_main_is_skipped_until_reset`, the backup is used when the main returns no block, a limit with no reset time is remembered for one hour, all-limited tries the earliest reset, no agents set gives the reason, and the footer texts.

- [ ] RT-3: Route plain messages through the router
  Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/turn.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/assistant.py` and their tests only.
  1. `intent.route`'s last step changes.
     - Text starting with `idea:` (any case) or `💡` is `capture`, with the prefix removed.
     - Text starting with `?` is `free`, with a `question` hint.
     - Everything else that reached that step is `free`.
     - `_is_instruction` is no longer used to choose between the two. Taps, commands, settings and answers to an open question are unchanged.
  2. In `assistant.py`, move the tail of `propose` (from `validate` to the returned `Proposal` with its card or request) into `assistant.accept(conn, parsed, *, current, allowed, chat_id, channel, actor) -> Proposal`. `propose` calls it. Behaviour is unchanged.
  3. `turn.run` calls `router.decide`, then:
     - `idea`: today's capture path (`bot._capture`).
     - `brainstorm`: capture, then the same step the **Brainstorm** button takes on the new idea's card.
     - `task`: build a `Proposal` from the routed action and fields and pass it to `assistant.accept`. The result is handled exactly as `bot._free` handles a proposal today (card, request card, refusal text, status).
     - `question` and `chat`: send `routed.reply`. When it is empty, say `I don't have an answer for that.`
     - `unclear`: RT-5. Until RT-5 lands, it falls back to today's `assistant.propose` path.
     - An `error` on a route other than unclear is sent as the refusal text.
  4. `router.footer` is appended to the reply when it is not empty.
  Tests: `test_writing_task_needs_a_tap` (`do <task>` routed as `task` creates a `waiting_tap` request and starts nothing), each route's outcome, `idea:` and `?` shortcuts make no router call for an idea, `propose` still passes its existing tests after the move, and a message with an open question is still an answer.

- [ ] RT-4: When both agents fail, keep the message
  Edit `src/whyline/ideas/turn.py`, `src/whyline/ideas/bot.py` and their tests only.
  1. When `router.decide` returns the no-agent result, the message is saved as an idea through `store.add`, and the reply is `Couldn't read this now (<reason>). Saved as an idea so it isn't lost.` with **Try again** and the idea's usual buttons.
  2. **Try again** queues a new turn for the same text (FB-5's mechanism). When that turn routes to anything other than `idea`, the saved idea is dropped with the note `re-routed as <route>`.
  3. The turn ends `done`, not `failed`: the user got an answer, so the reaction is 👍.
  Tests: `test_both_fail_saves_as_idea`, Try again re-routes and drops the saved idea once, Try again that routes to `idea` keeps the one idea and adds no second, and the reason text for a usage limit names the reset time.

- [ ] RT-5: Unclear messages ask, and the answer teaches
  Edit `src/whyline/ideas/router.py`, `src/whyline/ideas/turn.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/intent.py`, `src/whyline/ideas/store.py` (schema) and their tests only.
  1. A `route_examples` table as the next schema version: `id`, `text` (cut to 300 characters), `route`, `created`. `router.examples(conn) -> list[tuple[str, str]]` returns the newest 20. `router.add_example(conn, text, route)` inserts and deletes all but the newest 20.
  2. For `unclear` with no error, the reply quotes the message's first line (cut to 100 characters) under `What should I do with this?`, with buttons **Save as idea**, **Do it** and **Just answer**. Each button carries a `confirm.issue` code bound to the turn, within `bot.CALLBACK_DATA_LIMIT`.
  3. A tap:
     - **Save as idea** captures it and adds the example `idea`.
     - **Do it** runs `router.decide` again with the instruction `the user says this is a task`, and handles the result as RT-3 does. If it is still not a `task`, the reply is `I couldn't turn that into something I can do. Try: help`. The example is added only when it became a `task`.
     - **Just answer** runs it again with `the user says this is a question`, sends the reply and adds the example `question`.
     - A stale or repeated tap answers `This card is out of date.`
  4. `router.decide` passes `router.examples(conn)` into the prompt.
  Tests: `test_unclear_asks_and_waits` (nothing is captured or requested before a tap), each button's outcome and example, the 20-example cap, a stale tap, and examples appear in the next prompt.

- [ ] RT-6: Routing history, in the console and the CLI
  Edit `src/whyline/ideas/router.py`, `src/whyline/ideas/turn.py`, `src/whyline/ideas/store.py` (schema), `src/whyline/ideas/cli.py`, `src/whyline/console/assistant_screen.py` and their tests only.
  1. A `routes` table as the next schema version: `id`, `turn_id`, `chat_id`, `text` (cut to 300), `route`, `action`, `agent`, `confidence`, `seconds`, `created`. `turn.run` writes one row per routed message. Rows older than 30 days are deleted when a row is written.
  2. `router.history(conn, limit=50)` and `router.refile(conn, route_id, route)`: adds the example, and for `idea` captures the text. It refuses any route but `idea`, `task` and `question`.
  3. CLI:
     - `whyline idea route "<text>"` prints the route, action, confidence and agent, without acting or recording.
     - `whyline idea routes` prints the history.
     - `whyline idea routes refile <id> <route>` calls `refile`.
  4. Assistant screen: a **Routing** table of the last 50 rows (time, text, route, agent, seconds), and a **Wrong?** button on the selected row with the three routes, calling `refile`. The main and backup agent selects already on this screen get the line `Also used to route messages.`
  Tests: one row per turn, the 30-day trim, `route` does not record or act, CLI and console call `refile`, and an unknown route is refused.

- [ ] RT-7: Help text, doctor and docs
  Edit `src/whyline/ideas/bot.py` (`help_text`), the assistant doctor in `src/whyline/ideas/cli.py`, `docs/assistant.md`, `README.md` and their tests only.
  1. Help: add `Just write what you want. Start with "idea:" to save an idea, or "?" to ask a question.`
  2. Doctor: `Router: <main>, backup <backup>` or `Router: no agent set — choose one in Assistant`, and `<agent> is out of usage until <time>` for each remembered limit.
  3. Docs cover: the six routes, the three buttons, main and backup with the usage-limit skip, what happens when both fail, the shortcuts, and the Routing table with **Wrong?**.
  Verify with `uv run pytest -q`.
