# Console Relay Lifecycle Views Design

**Status:** Drafted 2026-09-28, pending user review (built in parallel while
piece A ran, per the user's own request for autonomy on this one).

## Goal

Sub-project #3 of the console roadmap. `whyline console`'s relay mode shows
a pause's exact task/reason/log-path/resume-command as clean structured
fields (reusing already-structured data, never re-parsing subprocess text),
and gains visibility into the last real handoff (from/to/status/summary/
questions) via a new `/handoff` command -- both wired into the same
`SessionEvent` model the foundation already established.

## Context

Sub-project #2 (model/route palette) turned out to already be substantially
covered by the foundation's own `/model` command (UCF-6) -- it already
lists only available agents, sets the active chat agent, and optionally
sets its model. This spec moves straight to #3.

## Non-goals

- **Full test/review-status rendering** (the vision's "handoffs, reviews,
  tests" list). Only the *last* handoff record is shown -- a history view
  is future scope if it proves needed once this exists.
- **The full-screen mouse TUI** (#4). This stays text-only, printed through
  the exact same render loop the foundation already has.
- **Changing `run_relay_oneshot`'s classification of `output`/`error`.**
  Only its `pause` case changes -- from a raw captured-text dump to a
  structured re-read.

## Decisions

- **RLV1 -- A pause reuses `run_status`'s own structured data, not raw
  captured text.** `run_relay_oneshot` already knows a `start`/`resume`
  call paused (its existing `_PAUSE_PATTERN` check). Once it does, it calls
  `state.load(root)` directly (the exact same already-structured function
  `run_status` already uses) and builds the rendered message from those
  fields, instead of returning whatever raw text `relay_cli.main` happened
  to print. `output`/`error` cases are untouched -- they have no structured
  equivalent to prefer.
- **RLV2 -- A new `run_last_handoff` adapter, reusing `handoff.read`
  unchanged.** Renders `Handoff`'s `task`/`from_actor`/`to_actor`/`status`/
  `summary`/`questions` fields directly -- no new parsing, whyline-relay's
  own `handoff.read(root)` is already exactly the structured function
  needed.
- **RLV3 -- A pause's reason is classified into a coarse `failure_kind`.**
  `rate-limit`/`auth` reuse `failover.REASON_TEXT`'s own known phrases
  ("hit a usage or rate limit", "is no longer logged in") as the match
  target -- not new invented patterns. `no-handoff` ("exited without
  handing off"), `round-cap` ("hit the ... round cap"), and `blocked`
  ("reported blocked:") are matched the same way, against this project's
  own existing, stable pause-message wording. Anything matching none of
  these is `other`. Shown as a labeled prefix on the rendered pause (e.g.
  "[rate-limit] Paused: ...").
- **RLV4 -- One new slash command, `/handoff`.** Calls `run_last_handoff`
  and renders it, added to `SLASH_COMMANDS` alongside the existing six.

## Architecture

```
run_relay_oneshot(root, argv)
  │  (start/resume, existing pause/complete/error classification unchanged)
  │
  └─ if kind == "pause":
       state.load(root)                          -- structured (RLV1)
       failure_kind(saved.paused_reason)          -- classified (RLV3)
       -> "[<kind>] Task <id>\nReason <text>\nLog <path>\nResume: whyline-relay resume"

run_last_handoff(root) -> SessionEvent            -- new (RLV2)
  handoff.read(root)
  -> "<task>: <from_actor> -> <to_actor> (<status>)\n<summary>" + questions if any

repl.py: "/handoff" -> run_last_handoff            -- new (RLV4)
```

## Error handling

- No pause state to read when `run_relay_oneshot` detects a pause (a race
  between the text classification and the state file): falls back to the
  raw captured text rather than showing nothing.
- No handoff recorded yet (`handoff.read` returns `None`): `/handoff`
  reports "No handoff recorded yet," not an error.
- A `paused_reason` matching none of RLV3's known phrases: classified as
  `other`, shown without a failure-kind label rather than guessing.

## Testing strategy

- `run_relay_oneshot`'s pause case: a fake `relay_cli.main` that prints a
  `Paused:` line, with a real `state.RelayState` saved on disk, produces a
  structured rendering (task/reason/log/resume line), not the raw text.
- `run_last_handoff`: a real `Handoff` written via `handoff.write` (or the
  repo's own test helper for it) renders correctly; no handoff present
  reports the "not yet" message, not an error.
- `failure_kind`: each of the five known phrase patterns classifies
  correctly; an unrecognized reason classifies as `other`.
- `/handoff` in `repl.py`: dispatches to `run_last_handoff` and prints its
  result, matching the existing slash-command test pattern.
