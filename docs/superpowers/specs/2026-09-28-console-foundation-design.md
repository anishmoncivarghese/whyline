# Console Foundation Design

**Status:** Approved by user, section-by-section, 2026-09-28. Revised
2026-09-28 after discovering `whyline` already has a precedent for
in-process integration with `whyline-relay` (see Revision note below).

## Goal

`whyline console` gives a real, editable multiline prompt (selection, word
deletion, history, paste) for driving both `whyline` and `whyline-relay` from
one keyboard-only session, replacing today's raw single-line `input()`
prompts -- without duplicating either package's own state-machine logic, and
without changing `whyline run`'s deliberate exec-and-hand-over design.

## Context

This is sub-project #2 of the wider vision in
`docs/superpowers/specs/2026-09-28-whyline-unified-console-design.md`
(committed, status "Proposed," never built). That document bundles several
independent subsystems -- session/event model, keyboard editor, attachments,
model/route palette, a full-screen mouse TUI, relay lifecycle views, and
cross-platform packaging -- which is too much for one spec or plan. This
document covers only the foundation: the session/event model, the command
adapters, and the keyboard-only multiline console. Later sub-projects (model
palette, relay lifecycle views, the mouse TUI, packaging, and eventually
attachments) each get their own spec and plan, layered on top of what this
one establishes, per the roadmap agreed with the user.

## Revision note

The first approved pass of this design assumed whyline and whyline-relay
must stay fully separate, so relay integration went through a subprocess
with its plain-text output classified by pattern-matching (the same
technique `relay-auto-resume.sh` already uses). Re-reading `cli.py` fresh
before writing the plan surfaced an existing precedent this missed: `whyline`
already has an optional `[relay]` extra, and its existing `cmd_relay`
command already does `from whyline_relay import cli as relay_cli` **in
process** when that extra is installed, falling back to a clear install
hint (`relay_install_hint()`) otherwise. Given that precedent already
exists, and both packages are released by the same project (not a
third-party vendor CLI whose format could change without warning -- the
reasoning behind `whyline run`'s own exec/no-capture design), going further
than `cmd_relay` does -- importing whyline-relay's own already-structured
functions directly, not just its CLI entry point -- removes real fragility
for no real cost. This revision keeps everything else from the first pass
(UCF1, UCF4-UCF7 below) and replaces the subprocess-based UCF2/UCF3 with
UCF2'/UCF3' below.

## Non-goals

- **The full-screen mouse-enabled TUI.** A later sub-project, built as a pure
  rendering layer over this one's `SessionEvent` stream -- explicitly why
  events are never printed directly here.
- **Attachments** (files, images, directories). Deferred indefinitely: none
  of the four agent adapters (claude/codex/antigravity/grok) have any
  file/image mechanism today, and this needs its own per-adapter design once
  there is a real console to attach things to.
- **Changing `whyline run`'s exec model.** `runner.py` deliberately execs an
  agent (hands over the terminal, no capture, no parsing, "so a vendor
  changing its output format cannot break us"). This console cannot embed
  its output in a transcript without reversing that guarantee, so it doesn't
  try: `whyline run` stays exactly as it is today, launched the same way,
  outside the console's event system entirely.
- **True non-blocking/streaming execution.** A relay run or a chat turn
  blocks the console exactly as it already blocks a plain terminal running
  the same command today -- this is not a regression (neither
  `whyline-relay chat`'s own REPL nor `whyline-relay start` are non-blocking
  today either). Real concurrency (a background thread, cooperative
  cancellation) is deferred to the mouse-TUI sub-project, if it ever proves
  necessary there.
- **Reimplementing `cmd_start`/`cmd_resume`'s own orchestration** (branch
  setup, guard checks, settings overrides) in the console. That orchestration
  is real, non-trivial logic that lives only in whyline-relay's `cli.py`
  today, not in a reusable function -- duplicating it would be exactly the
  kind of state-machine duplication this spec's goal explicitly forbids.

## Decisions

- **UCF1 -- Lives inside the `whyline` package, not a third package.**
  `whyline console` is a new subcommand in agentdock's own `cli.py`, next to
  the existing entry menu (`run_entry_menu`) and `cmd_relay`, both of which
  already integrate with `whyline-relay` today (the entry menu execs into
  it; `cmd_relay` imports it in-process). This continues that precedent
  rather than introducing a new distributable to version and release
  alongside the other two. Requires the existing `[relay]` extra
  (`whyline-relay>=0.2.1,<0.3`) for any relay/chat functionality; `command`
  mode (whyline's own commands only) works without it.
- **UCF2' -- In-process for whyline's own non-interactive commands.**
  `sync`, `note`, `handoff`, `account status`/`detect`, `model set`/`status`
  are called as direct Python function calls (output captured via
  `contextlib.redirect_stdout`). Bare `account` and bare `model` are
  interactive (real `input()` calls) -- `redirect_stdout` does nothing about
  stdin, so this is explicitly refused with a message pointing at the
  dedicated `/model` slash command (UCF6) instead of hanging on the wrong
  input source.
- **UCF3' -- whyline-relay integration is in-process throughout, split by
  how deep a clean structured function already exists.** Three shapes,
  chosen per command, not one uniform mechanism:
  - **Chat** (`chat` mode): calls `whyline_relay.chat.run_turn(root, agent=,
    prompt=, settings=)` directly, per turn -- already the exact structured,
    reusable core chat's own REPL is built on (returns a `record` dict with
    `agent`, `response`, `ok`, `rate_limited`, `diff_stat`,
    `failover_notice`). `agents.AgentMissing`/`AgentTimeout` and
    `chat.AgentUnavailable` are caught the same way `chat.repl()` already
    catches them -- printed, turn skipped, session continues.
  - **`doctor`**: calls `whyline_relay.preflight.run(root, plan_path,
    allow_dirty=)` directly -- already a clean, side-effect-free function
    returning `list[Check]`.
  - **`status`**: calls `whyline_relay.running.live(root)` and
    `whyline_relay.state.load(root)` directly -- both already
    side-effect-free, structured data access; the console builds its own
    event from the fields rather than reusing `cmd_status`'s print
    statements.
  - **`start`/`resume`**: calls `whyline_relay.cli.main(["start"|"resume",
    ...])` in-process (the same shallow level `cmd_relay` already uses),
    output captured via `redirect_stdout` and lightly classified with the
    same text patterns `relay-auto-resume.sh` already parses (`Paused:`,
    `Plan complete`, `Running:`) -- a deliberate, narrow exception to
    "no text parsing," justified because `cmd_start`/`cmd_resume`'s real
    orchestration (branch setup, guards) is not factored into a reusable
    function, and reimplementing it would itself be duplication (see
    Non-goals).
- **UCF4 -- The session emits events, never prints directly.** `ConsoleSession`
  (repo root, branch, mode, selected agent/model, growing transcript) and
  `SessionEvent` (`output`/`handoff`/`pause`/`error`/`exit`) are the only
  channel; a render loop consumes them and prints. Events are now
  constructed from structured return values (a chat `record`, a `Check`, a
  `RelayState`) wherever UCF3' gives one, and from light text classification
  only for `start`/`resume`. This is what lets the later mouse TUI
  (sub-project #5) be a pure rendering layer on the same event stream, not a
  rewrite of this one.
- **UCF5 -- `prompt_toolkit` is an optional extra from day one.** `pip
  install whyline[console]` is required for `whyline console` to run at
  all; missing it prints that instruction and exits cleanly -- no degraded
  editor fallback for this sub-project (the existing, already-shipped plain
  entry menu remains the ambient fallback for anyone without the extra).
  Base `whyline`/`whyline-relay` stay fully dependency-free, consistent
  with every other plan built this session ("no new runtime dependency").
  `editor.py` itself is import-guarded (`try/except ImportError`) so the
  rest of the package stays importable and testable without the extra
  installed. This extra is separate from `[relay]` (UCF1) -- `whyline
  console` in `command` mode needs only `[console]`; `chat`/`relay` modes
  need `[relay]` too.
- **UCF6 -- Slash command set for this sub-project.** `/model` (in-process,
  reuses `account.available_agents`/`model.set_one` directly, not the
  interactive wizard's own `input()` loop), `/route <chat|relay|command>`
  (switches mode -- no persistent process to start/stop now that chat is a
  direct per-turn function call, not a piped subprocess), `/status`,
  `/stop` (only meaningful while a `start`/`resume` call is in flight;
  raises the same `KeyboardInterrupt`-based cancellation as Ctrl+C, see
  UCF7), `/history` (this session's own transcript), `/help`, `/exit`.
  `/attach`/`/attachments` are explicitly excluded (deferred, per
  attachments being out of scope).
- **UCF7 -- Ctrl+C cancels the in-flight call via a plain
  `try/except KeyboardInterrupt`.** Since every relay/chat call is now a
  direct, synchronous function call (UCF3'), not a subprocess, there is no
  process to signal -- catching `KeyboardInterrupt` around the call site is
  sufficient and simpler than the subprocess-signaling design from the
  first pass. Relay/chat state is left exactly as resumable as it already
  is: a `loop.Paused` raised mid-`start`/`resume` already means the relay's
  own pause-state file was written before the console ever sees the
  exception, so interrupting the *console* changes nothing about the
  relay's own recoverability.

## Architecture

```
whyline console
  │
  ├─ ConsoleSession (mode: chat | relay | command)
  │
  ├─ editor.py -- prompt_toolkit.PromptSession, multiline, history,
  │               import-guarded (UCF5)
  │
  ├─ adapters.py
  │    run_whyline_command(argv)   -- in-process, redirect_stdout (UCF2')
  │    run_chat_turn(agent, prompt) -- chat.run_turn(...) directly (UCF3')
  │    run_doctor()                -- preflight.run(...) directly (UCF3')
  │    run_status()                -- running.live()/state.load() directly (UCF3')
  │    run_relay_oneshot(args)     -- relay_cli.main(...) in-process,
  │                                   redirect_stdout, light classification (UCF3')
  │
  └─ render loop -- consumes SessionEvents (UCF4), prints, appends to transcript
```

`command` mode: buffer treated as `whyline <words>`, dispatched via
`run_whyline_command`. `relay` mode: first word chooses among
`run_doctor`/`run_status`/`run_relay_oneshot`. `chat` mode: whole buffer
sent as one prompt via `run_chat_turn`.

## File layout

- `src/whyline/console/session.py` -- `ConsoleSession`, `SessionEvent`.
- `src/whyline/console/adapters.py` -- the five adapter functions (UCF2'/UCF3').
- `src/whyline/console/editor.py` -- the guarded `prompt_toolkit` wrapper (UCF5).
- `src/whyline/console/repl.py` -- the main loop tying the above together.
- `cli.py` gains a `console` subcommand wiring into `repl.py`.
- `pyproject.toml` gains a `[project.optional-dependencies] console =
  ["prompt_toolkit"]` extra (separate from the existing `relay` extra).

## Error handling

- `prompt_toolkit` missing: `pip install whyline[console]`, clean exit
  (UCF5).
- `whyline-relay` not installed and `/route chat`/`relay` is chosen: the
  same `relay_install_hint()` message `cmd_relay` already shows, `/route`
  stays on `command`.
- A chat turn's `agents.AgentMissing`/`AgentTimeout`/`chat.AgentUnavailable`:
  caught exactly where `chat.repl()` already catches them, printed as an
  `error` event, session continues -- never a raw traceback.
- `loop.Paused` raised during `start`/`resume`: surfaced as a `pause` event
  carrying its exact `.reason` and `.log_path` -- the console must show the
  same "Resume with: whyline-relay resume" instruction a plain terminal
  user would see.
- Ctrl+C during any in-flight call: caught via `try/except
  KeyboardInterrupt` around that call site only (UCF7); the console itself
  keeps running afterward, ready for the next command.
- An unrecognized line from `start`/`resume`'s captured output (matches no
  known pattern): still shown verbatim as a plain `output` event, never
  dropped -- classification is for nicer rendering only, not a filter.
- Bare `account` or bare `model` typed in `command` mode: refused with a
  message pointing at `/model`, never dispatched to `run_whyline_command`
  (UCF2') -- avoids hanging on an in-process `input()` call reading from the
  wrong stdin.

## Testing strategy

- `session.py`: pure dataclass tests (event construction, transcript
  append).
- `run_whyline_command`: captured output matches what the same CLI call
  prints normally; exit codes preserved; bare `account`/`model` are refused
  with a message pointing at `/model`, never actually invoked.
- `run_chat_turn`: injects a fake `run_fn` straight into `chat.run_turn`
  (the exact same injection point whyline-relay's own `test_chat_turn.py`
  uses) -- no real agent process, no subprocess fake needed at all;
  `AgentMissing`/`AgentTimeout`/`AgentUnavailable` each produce the right
  `error` event and the session survives to the next command.
- `run_doctor`/`run_status`: call the real `preflight.run`/`running.live`/
  `state.load` against a scratch repo fixture (same pattern whyline-relay's
  own `test_preflight.py` already uses) -- genuinely structured data in,
  structured event out, no text parsing anywhere in this path to test.
- `run_relay_oneshot`: injects a fake `runner` into `relay_cli.main` the
  same way whyline-relay's own CLI tests already do; a captured `Paused:`/
  `Plan complete`/`Running:` line produces the right classified event; an
  unrecognized line still comes through as plain output.
- `editor.py`: importable, and its guard works with `prompt_toolkit` absent
  (mock the import failure); a real editor smoke test only runs when the
  extra is actually installed (skipped, not failed, otherwise).
- End-to-end: a fake-agent scratch-repo session exercising `/model`,
  `/route relay` -> `doctor` -> `start` -> a simulated pause -> `/route
  chat` -> a turn -> `/exit`, confirming no relay/chat state is disturbed by
  the console layer itself.
