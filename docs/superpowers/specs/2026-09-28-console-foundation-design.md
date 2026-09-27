# Console Foundation Design

**Status:** Approved by user, section-by-section, 2026-09-28.

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
- **A machine-readable relay protocol.** Relay one-shot commands are
  classified from their existing plain-text output (the same patterns
  `relay-auto-resume.sh` already parses: `Paused:`, `Plan complete`,
  `Running:`), not a new structured format whyline-relay would need to grow.
- **whyline importing whyline-relay's code, or vice versa.** They stay fully
  independent packages, exactly as account-capability-gating (AC6) already
  established -- the console talks to whyline-relay only as a subprocess.

## Decisions

- **UCF1 -- Lives inside the `whyline` package, not a third package.** `whyline
  console` is a new subcommand in agentdock's own `cli.py`, next to the
  existing entry menu (`run_entry_menu`), which already execs into
  `whyline-relay` as a subprocess for "relay"/"chat" -- this continues that
  exact precedent with structured, streamed output instead of a one-shot
  exec, rather than introducing a new distributable to version and release
  alongside the other two.
- **UCF2 -- In-process for whyline's own commands, subprocess for relay's.**
  Since the console already lives inside `whyline`, its own *non-interactive*
  commands (`sync`, `note`, `handoff`, `account status`/`detect`, `model
  set`/`status`) are called as direct Python function calls (output captured
  via `contextlib.redirect_stdout`), never subprocessed into itself. Only
  whyline-relay's commands go through a real subprocess, since that is a
  genuinely separate package. Bare `account` and bare `model` are
  interactive (real `input()` calls) -- `redirect_stdout` does nothing about
  stdin, so `run_whyline_command` explicitly refuses both with a message
  pointing at the dedicated `/model` slash command (UCF6) instead of hanging
  on the wrong input source. This is the one deliberate gap between "every
  whyline command" and what `run_whyline_command` actually accepts.
- **UCF3 -- Two subprocess shapes for relay, matching how each command
  actually behaves.** One-shot (`start`, `resume`, `doctor`, `status`): run
  to completion, stdout streamed line-by-line and classified via UCF-known
  text patterns. Persistent (`chat`): spawned once with piped stdin/stdout;
  the console's editor writes each sent block as a line to that pipe, and
  chat's own REPL (its slash commands, failover notices, `⚠` diff markers)
  reads and behaves exactly as if typed at a real terminal -- the console
  never reimplements chat's logic, it is a nicer input front-end piped in
  front of the existing, unchanged REPL.
- **UCF4 -- The session emits events, never prints directly.** `ConsoleSession`
  (repo root, branch, mode, selected agent/model, growing transcript, active
  subprocess handle) and `SessionEvent` (`output`/`handoff`/`pause`/
  `error`/`exit`) are the only channel; a render loop consumes them and
  prints. This is what lets the later mouse TUI (sub-project #5) be a pure
  rendering layer on the same event stream, not a rewrite of this one.
- **UCF5 -- `prompt_toolkit` is an optional extra from day one.** `pip
  install whyline[console]` is required for `whyline console` to run at
  all; missing it prints that instruction and exits cleanly -- no degraded
  editor fallback for this sub-project (the existing, already-shipped plain
  entry menu remains the ambient fallback for anyone without the extra).
  Base `whyline`/`whyline-relay` stay fully dependency-free, consistent
  with every other plan built this session ("no new runtime dependency").
  `editor.py` itself is import-guarded (`try/except ImportError`) so the
  rest of the package stays importable and testable without the extra
  installed.
- **UCF6 -- Slash command set for this sub-project.** `/model` (in-process,
  reuses `account.available_agents`/`model.set_one` directly, not the
  interactive wizard's own `input()` loop), `/route <chat|relay|command>`
  (switches mode; starts/stops the persistent chat subprocess as needed),
  `/status`, `/stop` (terminates the active subprocess; leaves relay/chat
  state exactly as resumable as it already is), `/history` (this session's
  own transcript), `/help`, `/exit`. `/attach`/`/attachments` are explicitly
  excluded (deferred, per attachments being out of scope).
- **UCF7 -- Ctrl+C interrupts the active subprocess only.** Never the
  console process itself, and never deletes relay pause-state or chat
  history -- matching the "must not duplicate... or destroy state" spirit
  of the wider vision doc, scoped down to what this sub-project actually
  touches.

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
  │    run_whyline_command(argv)       -- in-process, redirect_stdout (UCF2)
  │    run_relay_oneshot(argv, cwd)    -- subprocess, streamed, classified (UCF3)
  │    run_relay_chat(cwd)             -- persistent piped subprocess (UCF3)
  │         (chat's own REPL, slash commands, failover, ⚠ markers -- unchanged)
  │
  └─ render loop -- consumes SessionEvents (UCF4), prints, appends to transcript
```

`command` mode: buffer treated as `whyline <words>`, dispatched via
`run_whyline_command`. `relay` mode: first word is a one-shot relay
subcommand. `chat` mode: whole buffer written as one line to the persistent
chat subprocess's stdin.

## File layout

- `src/whyline/console/session.py` -- `ConsoleSession`, `SessionEvent`.
- `src/whyline/console/adapters.py` -- the three adapter functions (UCF2/UCF3).
- `src/whyline/console/editor.py` -- the guarded `prompt_toolkit` wrapper (UCF5).
- `src/whyline/console/repl.py` -- the main loop tying the above together.
- `cli.py` gains a `console` subcommand wiring into `repl.py`.
- `pyproject.toml` gains a `[project.optional-dependencies] console =
  ["prompt_toolkit"]` extra.

## Error handling

- `prompt_toolkit` missing: `pip install whyline[console]`, clean exit
  (UCF5).
- A relay one-shot subprocess crashes or times out: surfaced as an `error`
  event carrying the exact stderr/pause text -- the console must show the
  same "Resume with: whyline-relay resume" instruction a plain terminal user
  would see, never a swallowed or summarized version.
- Ctrl+C: interrupts only the active subprocess (UCF7); relay/chat state is
  left exactly as resumable as it already is today.
- Switching `/route` away from `chat` while its persistent subprocess is
  alive: cleanly terminates it first (never orphaned); switching back starts
  a fresh one.
- An unrecognized line from a relay subprocess (matches no known pattern):
  still shown verbatim as a plain `output` event, never dropped --
  classification is for nicer rendering only, not a filter.
- Bare `account` or bare `model` typed in `command` mode: refused with a
  message pointing at `/model`, never dispatched to `run_whyline_command`
  (UCF2) -- avoids hanging on an in-process `input()` call reading from the
  wrong stdin.

## Testing strategy

- `session.py`/adapters: unit tests with a fake subprocess runner, matching
  this project's own established `run_fn`/`runner` injection pattern -- no
  real `claude`/`codex`/`whyline-relay` process ever spawned in tests.
- `run_whyline_command`: captured output matches what the same CLI call
  prints normally; exit codes preserved; bare `account`/`model` are refused
  with a message pointing at `/model`, never actually invoked.
- `run_relay_oneshot`: a fake subprocess emitting `Paused:`/`Plan
  complete`/`Running:` lines produces the right classified events; an
  unrecognized line still comes through as plain output.
- `run_relay_chat`: a fake persistent process proves input is piped in and
  output streamed out without blocking; `/stop` terminates it; switching
  `/route` away cleans it up.
- `editor.py`: importable, and its guard works with `prompt_toolkit` absent
  (mock the import failure); a real editor smoke test only runs when the
  extra is actually installed (skipped, not failed, otherwise).
- End-to-end: a fake-agent scratch-repo session exercising `/model`,
  `/route relay` -> `start` -> a simulated pause -> `/route chat` -> a turn
  -> `/exit`, confirming no relay/chat state is disturbed by the console
  layer itself.
