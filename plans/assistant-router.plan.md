<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-assistant-2-design.md | created: 2026-11-14T15:30:00+05:30 -->
# Assistant router: decide what a message wants before anything runs

Spec: `docs/superpowers/specs/2026-11-14-assistant-2-design.md`, Part 1. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **One model turn per message, not two.** For a `task` route the router's own block is validated and turned into a card or request by the code `assistant.propose` uses today. `propose` is not called again.
- **`research` is not a route target yet.** It arrives with the research plan. Until then the router may only choose actions in `actions.REGISTRY`.

Runs after `plans/assistant-feedback.plan.md`, and before `plans/raaid-log.plan.md`. It needs the feedback plan's turns (FB-4) and failure replies (FB-5).

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

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
