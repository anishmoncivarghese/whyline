<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-assistant-2-design.md | created: 2026-11-14T15:00:00+05:30 -->
# Assistant feedback: an always-on listener, reactions and a "Working on it" message

Spec: `docs/superpowers/specs/2026-11-14-assistant-2-design.md`, Part 2. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **Reactions are 👀 (received), 👍 (done) and 😢 (failed).** Telegram bots may only set reactions from a fixed list, and ✅ and ❌ are not on it.
- **The listener is the existing worker loop kept running**, not a second poller. It holds the poll lock, so the 120-second tick still returns without polling, as it does today when the lock is taken.

Runs after `plans/plan-queue.plan.md` and before `plans/assistant-router.plan.md`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

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
