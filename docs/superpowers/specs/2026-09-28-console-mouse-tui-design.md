# Console Mouse-Enabled TUI Design

**Status:** Approved by user, section-by-section, 2026-09-28.

## Goal

Sub-project #4 of the console roadmap: a full-screen, mouse-enabled
terminal UI (header, transcript, prompt editor, controls) built as a pure
rendering layer over the console foundation's existing `SessionEvent`
stream and `adapters.py` functions -- no logic duplicated, every mouse
action backed by the same dispatch path the keyboard console already uses.

## Context

Sub-projects #1-3 (foundation, model palette -- already covered by the
foundation itself, relay lifecycle views) are shipped. This is the single
riskiest, most platform-sensitive piece of the roadmap, which is why it
comes after an already-working keyboard core, not before it.

## Non-goals

- **An attachments panel.** Attachments (sub-project #7) remain deferred
  indefinitely; there is no attachment data model yet to render. Added
  later, alongside whatever attachments itself needs.
- **True forceful cancellation of an in-flight blocking call.** `/stop`
  marks a worker's eventual result as discarded, but cannot interrupt
  Python code already running inside a thread -- see Error Handling.
- **Verified Windows behavior.** Built using only cross-platform-safe
  Textual APIs, but only actually tested on macOS/Linux in this
  environment; Windows compatibility is a code-level goal, not a tested
  claim.
- **Rich interactive picker modals for Model/Route.** Buttons dispatch the
  exact same text commands the keyboard console already accepts (e.g.
  `/model`, `/route chat`) rather than a separate, richer selection UI --
  keeps mouse and keyboard paths identical, not two implementations to
  keep in sync. A picker modal is a reasonable future refinement, not part
  of this sub-project.

## Decisions

- **MTU1 -- `textual` is a new, separate optional extra, `[ui]`.** Not
  merged into the existing `[console]` extra (`prompt_toolkit`) -- Textual
  has its own input widgets and does not need `prompt_toolkit` at all,
  and the two serve genuinely different console modes (keyboard-only vs
  mouse-enabled). Import-guarded in a new `tui.py` module exactly like
  `editor.py` already guards `prompt_toolkit`.
- **MTU2 -- One new module, `tui.py`, reusing the foundation completely
  unchanged.** `ConsoleSession`, `SessionEvent`, and every one of
  `adapters.py`'s five functions are used as-is. The only change to
  existing code is renaming `repl.py`'s private `_dispatch` to public
  `dispatch`, so both the keyboard REPL and the TUI share one mode-routing
  implementation rather than two.
- **MTU3 -- Blocking calls run in a background thread via
  `App.run_worker(..., thread=True)`.** Necessary specifically because
  Textual is asyncio-based -- a blocking call on the main thread would
  freeze the entire screen (not just the prompt, as it does in the
  keyboard console). The worker posts its resulting `SessionEvent` back
  through Textual's own thread-safe messaging for the transcript to
  render.
- **MTU4 -- Layout: header, transcript, prompt, control row -- no
  attachments panel.** Header shows repo/branch/mode/agent/status,
  reactive to `ConsoleSession` state. Transcript is a scrollable log
  rendering every `SessionEvent` the same way `repl.py`'s `_print_event`
  already does. Prompt is a multiline `TextArea`. Controls: Send, Model,
  Route, History, Stop, Help (Attach omitted, matching the keyboard
  console's own slash-command set).
- **MTU5 -- Every button dispatches the identical text command a keyboard
  user would type.** Send submits the prompt through `dispatch()`
  unchanged; Model/Route/History/Help populate and submit the equivalent
  `/model`/`/route`/`/history`/`/help` text through the same path -- one
  implementation, not a mouse-specific duplicate, satisfying "every mouse
  action has a keyboard equivalent" by construction.
- **MTU6 -- `/stop` becomes real for the first time, with an honest
  limit.** The keyboard console's `/stop` was a documented no-op (nothing
  could ever be "in flight" in a synchronous REPL). Here, Stop marks the
  active worker cancelled -- its result, when the underlying blocking call
  eventually returns, is discarded rather than rendered. It cannot
  forcibly interrupt code already running inside the thread; that would
  need the agent process itself to be signaled, out of scope here.

## Architecture

```
tui.py
  │
  ├─ WhylineConsoleApp(App)
  │    ConsoleSession (unchanged, from session.py)
  │
  ├─ Header widget -- reactive: repo, branch, mode, agent, status
  ├─ Transcript (RichLog) -- renders every SessionEvent (MTU4)
  ├─ Prompt (TextArea, multiline)
  ├─ Controls: Send | Model | Route | History | Stop | Help
  │
  ├─ on Send / Ctrl+Enter:
  │    run_worker(lambda: dispatch(session, text), thread=True)  (MTU3)
  │    -> on completion: render the returned SessionEvent
  │
  └─ on Model/Route/History/Help click:
       dispatch(session, "/model" | "/route ..." | "/history" | "/help")  (MTU5)
```

`repl.py` change: `_dispatch` -> `dispatch` (public), otherwise unchanged.

## File layout

- `src/whyline/console/tui.py` -- the Textual `App` and its widgets.
- `src/whyline/console/repl.py` -- `_dispatch` renamed to `dispatch` (MTU2).
- `cli.py`'s existing `console` subcommand gains a `--ui` flag: `whyline
  console --ui` launches the mouse TUI; bare `whyline console` keeps
  launching today's keyboard-only REPL. One command, not two -- fragmenting
  into a separate `whyline ui` command would work against the "unified
  console" framing that is the whole point of this roadmap, and keeps
  sub-project #6's eventual cutover (bare `whyline` launching the console
  directly) a one-flag decision rather than a choice between two commands.
- `pyproject.toml` gains `[project.optional-dependencies] ui = ["textual"]`.

## Error handling

- A worker exception (anything not already caught by `adapters.py`'s own
  known-exception handling) is caught and rendered as an `error`
  `SessionEvent`, never crashes the app.
- `/stop`/Stop button: marks the worker cancelled; its eventual result is
  discarded, never rendered late (MTU6). Documented as a request, not a
  guarantee -- true interruption is out of scope.
- `textual` not installed: `tui.py`'s guarded import mirrors `editor.py`'s
  `EditorUnavailable` pattern exactly -- clear install hint, clean exit.
- A terminal-level startup failure (unsupported features): caught and
  reported plainly; this is a new, opt-in command, so a failure here
  leaves the existing keyboard console and entry menu completely
  unaffected.

## Testing strategy

- `dispatch()`: existing `repl.py` tests continue to cover its logic
  directly after the rename; both callers share one tested implementation.
- The TUI itself: Textual's own official `Pilot` (`App.run_test()`),
  simulating key presses and button clicks, asserting on the rendered
  transcript and header -- the standard, supported way to test a Textual
  app.
- Parity: a Model/Route button click produces the identical dispatch call
  typing the equivalent slash command would.
- A worker exception renders as an `error` event without crashing the app.
- Stop marks the active worker cancelled; a still-running result that
  completes afterward is discarded, never rendered into a later state.
- An import-guard test for `textual` absent, mirroring `editor.py`'s own.
- Every TUI-specific test is skipped (not failed) when `textual` isn't
  installed, matching the foundation's own precedent for `prompt_toolkit`.
