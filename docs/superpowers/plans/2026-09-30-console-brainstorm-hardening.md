# Console Brainstorm Hardening Plan (0.3.19)

**Goal:** Fix the defects found while using 0.3.18's Brainstorm for real: a
console crash on Enter in the brainstorm form, an unreadable focused
checkbox, silent loss of a pending result, and no per-model progress during
long research passes.

**Source:** user reports on 2026-09-30 (screenshots of the brainstorm form,
a `NoMatches: No nodes match '#prompt'` traceback, and a 54 s "Researching
independently" line with no per-model detail).

## Analysis

| # | Symptom | Root cause |
|---|---------|------------|
| 1 | Enter in the brainstorm topic crashes the console; clicking Start works | `Input.Submitted` from the dialog's input bubbles to the app, whose handler calls `_send()`, which looks up `#prompt` via `App.query_one` -- that searches the *active* (modal) screen, so `NoMatches` |
| 2 | Same class of crash, latent: progress lines or the spinner while any dialog is open | every app-level `self.query_one(...)` targets the active screen, not the console's own |
| 3 | Focused model checkbox looks like an empty text box | Textual's `ToggleButton:focus` adds `border: tall`, overriding our `border: none`; on a one-line checkbox the border covers the label |
| 4 | Sending chat during a brainstorm silently drops the brainstorm's result | a new dispatch replaces `_dispatch_token`, so the brainstorm's `_finish_dispatch` sees a stale token and discards |
| 5 | Minutes of "Researching independently" with no per-model detail | whyline did not use relay 0.2.23's structured `progress_fn` |
| 6 | Intermittent `NoMatches: '#thinking'` in the test suite | the spinner timer can tick once after widgets are torn down (quitting mid-reply) |

## Tasks

- [x] **T1 — Main-screen queries.** Add `WhylineConsoleApp._main()` that
  queries `screen_stack[0]`; route every app-level widget lookup through it.
  Test: render progress + spinner ticks with a dialog on top.
- [x] **T2 — Enter in the brainstorm form.** App's `on_input_submitted`
  only acts on `#prompt`; `BrainstormScreen.on_input_submitted` stops the
  event and presses Start. Test: type topic + Enter starts the run.
- [x] **T3 — Focused checkbox.** `BrainstormScreen Checkbox:focus { border:
  none; }`, keeping Textual's label highlight. Test: focused checkbox's
  content region is still one line tall.
- [x] **T4 — Busy guard.** While a request is pending, non-slash sends are
  refused with "Still working…" and the text stays in the box; slash
  commands and mode buttons still work. Test covers all three.
- [x] **T5 — Per-model progress.** Require `whyline-relay>=0.2.23`; pass
  `progress_fn` to every brainstorm stage and print
  `format_progress_line(event)` for every status except `running`. Test with
  a stub `ProgressEvent` stream.
- [x] **T6 — Spinner on shutdown.** `_tick` ignores `NoMatches`. Verified by
  8 consecutive full-suite runs with no failure (previously ~1 in 3).

## Release

- [x] Full suite green; decisions recorded with `whyline note`.
- [x] Bump to 0.3.19, release notes, commit, tag, push.
- [x] CI green on all six runners; confirm on PyPI; upgrade local install.

## Out of scope

- Whether Brainstorm should follow the current mode: it deliberately does
  not. It runs the same from Command, Chat or Relay, writes to the one
  transcript, and leaves the mode unchanged. Its agent turns are recorded in
  the repository's chat history, so Chat can refer to them afterwards.
