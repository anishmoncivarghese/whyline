<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-assistant-2-design.md | created: 2026-11-14T18:00:00+05:30 -->
# Assistant triggers: something happens, an action follows

Spec: `docs/superpowers/specs/2026-11-14-assistant-2-design.md`, Part 6. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **No public webhook server and no tunnel.** GitHub, mail and calendar are watched through the check-in gates. The only inbound door is an endpoint on `127.0.0.1` for the user's own scripts.

Runs after `plans/assistant-research.plan.md`. It needs the gates (`plans/assistant-checkins.plan.md`, CHK-1) and the action registry.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: only a Telegram message, an email or a clock can start anything. A failed CI run, a script finishing or a file landing in a folder can't.

What the user gets:
- A **trigger**: a name, a source (a gate, or "called by a script"), and one action from the registry.
- `whyline idea trigger fire <name>` and a localhost endpoint, for the user's own scripts.
- A Triggers list in the console with last fired and **Fire now**.

Rules every task keeps:
- **Console first.** Triggers are created, listed, fired and removed in the console through the same functions as `whyline idea trigger …`.
- **A trigger's action comes from `actions.REGISTRY`**, with arguments checked by `assistant.validate` when the trigger is saved. An action that writes (`do_task`, `stop`, and the `*_resume`/`*_rerun` actions) still sends its tap card. A trigger never skips an approval.
- **Text handed to a trigger is data.** It is cut to 1000 characters, passed through `ideas.guard.clean`, and given to the action as its text argument. It never picks the action, a repo, a path or a recipient.
- **The endpoint listens on 127.0.0.1 only**, needs a token, and accepts only `POST /trigger/<name>` for a name that exists. Everything else gets 404 with no detail.
- **The token** is made by whyline, kept through `whyline.credentials` (the Keychain), and never printed after it is first shown.
- **Rate limit:** a trigger fires at most once per 60 seconds, and 60 times a day. Extra calls are counted and dropped.
- **No new dependency.** The endpoint is `http.server` from the standard library.
- **Tests:** never open a real socket beyond `127.0.0.1` on an ephemeral port, never call `gh`, osascript, Telegram or a provider. Use fakes and an injected clock. Never sleep. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A request without the right token, to an unknown name, with another method or another path gets 404 and fires nothing. TRG-3, `test_endpoint_refuses_everything_else`.
- The server binds to 127.0.0.1 and never to all interfaces. TRG-3, `test_endpoint_binds_localhost_only`.
- A trigger whose action writes produces a tap card, not a run. TRG-2, `test_writing_action_still_needs_a_tap`.
- Trigger text can't change the action or its allowlisted arguments. TRG-2, `test_trigger_text_is_only_data`.
- A trigger fired twice within 60 seconds runs once. TRG-2, `test_trigger_rate_limit`.

- [ ] TRG-1: Trigger definitions
  Create `src/whyline/ideas/triggers.py` and `tests/ideas/test_triggers.py`. Edit `src/whyline/ideas/store.py` (schema) and its tests.
  1. A `triggers` table as the next schema version: `name` (primary key, `^[a-z][a-z0-9-]{0,39}$`), `source` (`script` or `gate`), `gate`, `gate_args` (JSON), `every_minutes`, `action`, `args` (JSON), `chat_id`, `enabled`, `gate_state` (JSON), `last_fired`, `fired_today`, `dropped`, `created`.
  2. `triggers.save(conn, *, name, source, action, args, chat_id, gate="", gate_args=None, every_minutes=15) -> Trigger`. It validates:
     - the name
     - the action is in `actions.REGISTRY`, and its arguments pass `assistant.validate`
     - a `gate` source has a gate that passes `agents.gates.validate`, and `every_minutes` from 5 to 720
     - the chat is in `telegram_in.allowed_chats`
  3. `triggers.list_all(conn)`, `triggers.get(conn, name)`, `triggers.remove(conn, name)`, `triggers.set_enabled(conn, name, on)`.
  Tests: round trip, a bad name, an unknown action, an argument the allowlist refuses, an unknown gate, a chat that isn't allowed, and remove.

- [ ] TRG-2: Firing a trigger
  Edit `src/whyline/ideas/triggers.py`, `src/whyline/ideas/worker.py` and their tests.
  1. `triggers.fire(conn, name, *, text="", by: str, now) -> Fired`. `Fired` has `state` (`run`, `waiting_tap`, `dropped`, `refused`) and `detail`.
     - An unknown or disabled trigger is `refused`.
     - Within 60 seconds of `last_fired`, or past 60 fires today, it is `dropped` and the counter rises.
     - Otherwise it creates a request through `requests.create` with `proposed_by="trigger:<name>"`, `channel="trigger"`, the trigger's chat, its saved action and arguments, and the cleaned text as the action's text argument where the action takes one.
     - The request then follows the action's policy: it runs at once, or its tap card is sent to the chat with the line `Trigger <name> wants to: <summary>`.
  2. Gate triggers: on the worker tick, each enabled gate trigger that is due (`every_minutes` since its last check) runs `agents.gates.check` with its own `gate_state`. When items are found, it calls `fire` once with the items' lines as the text.
  3. Every fire, drop and refusal writes one `events` or `requests` row, as the assistant's audit rule requires.
  Tests: `test_writing_action_still_needs_a_tap`, `test_trigger_text_is_only_data` (text that looks like `repo: other` or a command changes nothing in the request's action and arguments), `test_trigger_rate_limit`, the daily cap, a gate trigger fires once for a new item and not again for the same item, a disabled trigger refused, and the audit rows.

- [ ] TRG-3: The localhost endpoint
  Create `src/whyline/ideas/trigger_http.py` and `tests/ideas/test_trigger_http.py`. Edit `src/whyline/ideas/listener.py`, `src/whyline/ideas/triggers.py` and their tests.
  1. `triggers.token() -> str` returns the token, creating a 32-byte random one on first use and saving it as the credential `whyline-trigger` (kind `env`). `triggers.rotate_token() -> str`.
  2. `trigger_http.serve(conn_factory, *, port: int, token_fn, fire=triggers.fire) -> Server`. It binds `("127.0.0.1", port)`.
     - `POST /trigger/<name>` with the header `Authorization: Bearer <token>` (compared with `hmac.compare_digest`) fires the trigger. The body, at most 4 KB of UTF-8 text, is the trigger text. It answers 200 with `{"state": "<state>"}`.
     - Any other method, path, missing or wrong token, unknown name, or larger body answers 404 with an empty body.
     - Nothing from the request is logged except the trigger name and the state.
  3. The listener (`ideas/listener.py`) starts the endpoint when kv `trigger_port` is set (1024 to 65535, unset by default, so the endpoint is off until the user turns it on). A port that is in use is recorded for the doctor and never stops the listener.
  Tests: `test_endpoint_refuses_everything_else`, `test_endpoint_binds_localhost_only`, a good call fires and returns the state, a 5 KB body refused, the token created once and stable, `rotate_token` invalidates the old one, and a busy port leaves the listener running.

- [ ] TRG-4: Triggers in the console and CLI
  Edit `src/whyline/ideas/cli.py`, `src/whyline/console/assistant_screen.py`, the assistant doctor in `ideas/cli.py`, and their tests.
  1. CLI:
     - `whyline idea trigger add <name> --action <action> [--arg key=value …] [--gate <gate> --gate-arg key=value … --every <minutes>]`
     - `whyline idea trigger list` (name, source, action, last fired, fired today, dropped)
     - `whyline idea trigger fire <name> [--text <text>]`
     - `whyline idea trigger on|off <name>`, `whyline idea trigger remove <name>`
     - `whyline idea trigger endpoint on <port> | off | token | rotate`. `token` prints the token once, with a ready `curl` line for `127.0.0.1`.
  2. Assistant screen: a **Triggers** section with the list, **New trigger** (name, source, gate and its arguments, action and its arguments), **Fire now**, **On/Off**, **Remove**, and an **Endpoint** line with the port, **Turn on/off**, **Show token** and **New token**. Each calls the same function as its command.
  3. Doctor: `Triggers: <n> on; endpoint 127.0.0.1:<port>` or `endpoint off`, and `endpoint port <port> is in use` when it failed to bind.
  Tests: CLI and console call the same functions, **Fire now** goes through `triggers.fire` with `by="console"`, a bad port refused, and the doctor lines.

- [ ] TRG-5: Docs
  Edit `docs/assistant.md` and `README.md` only.
  Cover: what a trigger is, gate triggers with an example (CI failed on main → the Why card), firing from a script with the CLI and with `curl` on `127.0.0.1`, the token and rotating it, the rate limit, that writing actions still ask for a tap, and why there is no public webhook.
  Verify with `uv run pytest -q`.
