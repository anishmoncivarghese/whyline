# Whyline Unified Console Design

**Status:** Proposed
**Date:** 2026-09-28

## 1. Summary

Whyline needs one terminal interface through which a user can use both the
core `whyline` CLI and `whyline-relay`. The interface must work on macOS,
Linux, and Windows terminals, support a mouse-enabled full-screen mode, and
retain a keyboard-first console fallback.

The UI is a front end, not a replacement for the workflow engines. Whyline
continues to own decisions, notes, handoffs, account state, and routing.
Whyline Relay continues to own plans, agent execution, reviews, failover,
pauses, and task ticking. Agents remain external subprocesses.

## 2. Goals

- Provide an editable multiline prompt instead of a one-line `input()` prompt.
- Let users switch route, agent, and model without leaving the session.
- Let users attach text files, documents, images, and directories.
- Send approved attachments automatically to the selected agent workflow.
- Show agent output, handoffs, pauses, tests, and failures in one view.
- Expose core Whyline commands and relay commands from one command palette.
- Provide equivalent keyboard-only operation when the full-screen UI is not
  available or the user prefers a plain terminal.
- Keep the core package and existing CLI usable without UI dependencies.

## 3. Non-goals

- Replacing Claude, Codex, Grok, or Antigravity terminals.
- Implementing a new model provider or account authentication system.
- Uploading attachments to a Whyline service.
- Making semantic completion decisions in the UI.
- Replacing deterministic tests, Git checks, or Whyline handoff state.

## 4. User experience

`whyline ui` opens the full-screen console when the optional UI dependencies
are installed. `whyline console` explicitly opens the keyboard console.
Bare `whyline` may continue to use the existing entry menu until the UI is
proven stable.

The full-screen layout contains:

```text
┌─ Whyline ───────────────────────────────────────────────┐
│ repository · branch · route · agent/model · status       │
├─────────────────────────────────────────────────────────┤
│ transcript and streamed agent output                     │
│ handoffs, tests, pauses, and errors                      │
├─────────────────────────────────────────────────────────┤
│ attachments: plan.md  account.py                        │
├─────────────────────────────────────────────────────────┤
│ > multiline prompt                                      │
├─────────────────────────────────────────────────────────┤
│ Send  Model  Route  Attach  History  Stop  Help         │
└─────────────────────────────────────────────────────────┘
```

The buttons are also keyboard actions. Every mouse action must have a
keyboard equivalent.

The keyboard console supports `/model`, `/route`, `/attach PATH`,
`/attachments`, `/history`, `/clear`, `/status`, `/stop`, `/help`, and
`/exit`. Ctrl+Enter sends; Ctrl+M opens model selection; Ctrl+A opens
attachment selection; Escape cancels the current operation.

## 5. Shared session model

The UI uses a provider-neutral session object containing:

- repository root and current branch;
- current mode: `chat`, `relay`, `plan`, `brainstorm`, or `command`;
- selected agent and model;
- route and fallback policy;
- transcript entries with timestamps and source (`user`, `agent`, `whyline`,
  or `relay`);
- attachment manifest;
- active task, handoff status, and process state.

The session engine exposes events rather than printing directly. The TUI and
keyboard console render the same events, so behavior cannot diverge between
interfaces.

## 6. Whyline and Relay integration

The first implementation uses existing CLI boundaries through a command
adapter. It may invoke `whyline` and `whyline-relay` as subprocesses, capture
stdout/stderr, and translate known status lines and JSON records into session
events. It must not duplicate relay state-machine logic.

The adapter supports:

- core commands: `sync`, `note`, `handoff`, `account`, `model`, and status;
- relay commands: `chat`, `start`, `resume`, `doctor`, `plan`, and status;
- cancellation using the existing process termination policy;
- preserving the relay's pause and resume instructions;
- streaming output without corrupting the prompt editor.

Later versions may add an explicit machine-readable relay protocol, but the
initial UI must work with the released CLI commands.

## 7. Attachments

Attachments are represented by a manifest, never silently pasted into the
terminal prompt. Each item records path, display name, MIME guess, size,
sha256, extraction status, and whether it is an image or text document.

Supported initial inputs:

- source files, Markdown, JSON, TOML, YAML, and plain text;
- PDF and common document formats through optional extractors;
- PNG, JPEG, GIF, and WebP images;
- directories, expanded into a bounded file list.

The manifest is passed to the agent adapter. Text-capable agents receive
extracted text and paths. Vision-capable agents receive image paths through
their existing CLI mechanism. Unsupported files receive metadata and a clear
notice rather than being discarded.

Attachments are local-only, size-limited, and stored under ignored UI state.
The UI displays every attachment before sending and supports removal. Secret
files should be detected heuristically and warned about, but the user’s
explicit send action remains authoritative.

## 8. Model and route controls

The model palette lists only configured and available accounts/models. A
selection changes the next request and is shown in the header. Existing
Whyline account capability detection remains the source of truth.

Route choices include `chat`, `work`, `plan`, `human`, and the relay's
available workflows. The UI may recommend a route, but Whyline owns any
confirmation gate and deterministic transition.

## 9. Failure and recovery

- Agent output cannot freeze the input editor.
- Ctrl+C stops the active request and leaves a resumable session.
- Relay pauses show the exact resume command and log path.
- Rate-limit, missing-account, and permission failures are distinct states.
- A failed UI process must not delete relay state, handoffs, attachments, or
  transcripts.
- Plain console mode remains available if Textual cannot start.

## 10. Packaging and compatibility

The base installation remains usable without UI dependencies. Add optional
extras, for example `whyline[ui]`, containing the TUI and editor libraries.
The implementation must be tested on macOS, Linux, and Windows-compatible
terminal behavior, with graceful degradation for terminals without mouse
support or image protocols.

## 11. Roadmap and sub-projects

This document is the overarching vision; it is deliberately too broad for
one spec or plan (see the brainstorming session that produced
`docs/superpowers/specs/2026-09-28-console-foundation-design.md`). It is
built as a sequence of independently-shippable sub-projects, each with its
own spec and plan:

1. **Console foundation** -- session/event model, command adapters
   (in-process for whyline's own commands; direct calls into whyline-
   relay's already-structured functions for chat/doctor/status, `cli.main`
   in-process for start/resume), the keyboard-only multiline console.
   **Shipped** (whyline 0.3.8, `docs/superpowers/specs/2026-09-28-console-foundation-design.md`).
2. **Model/route palette** -- wires in `available_agents()` (already
   shipped via account-capability gating). Not yet designed.
3. **Relay lifecycle & recovery views** -- pauses, handoffs, resume
   instructions rendered well, on top of the foundation's event model. Not
   yet designed.
4. **Full-screen mouse-enabled TUI** -- a pure rendering layer over the
   foundation's `SessionEvent` stream, layered on an already-working
   keyboard core. Not yet designed.
5. **Cross-platform packaging & release readiness** -- wraps up once 2-4
   are stable. Not yet designed.
6. **Final cutover** -- once the console reaches parity with today's plain
   entry menu (both chat *and* relay setup, not chat alone), bare `whyline`
   launches the console directly instead of the current Chat/Relay text
   menu. The old menu is deprecated at that point, not kept indefinitely as
   a second interface -- this document's own goal is one unified console,
   not two interfaces maintained in parallel forever. Not yet designed;
   explicitly out of scope until sub-projects 2-5 are done, since there is
   nothing to cut over to before then.
7. **Attachments** (files, images, directories) -- its own future
   sub-project, deferred indefinitely, no sequencing commitment yet.

Each numbered item gets its own spec and plan when its turn comes, per this
project's established brainstorming/writing-plans process -- this document
is never itself turned directly into an implementation plan.

## 12. Acceptance criteria

- A user can launch one interface and invoke both Whyline and Whyline Relay.
- A multiline prompt supports selection, word deletion, history, and paste.
- Mouse buttons and keyboard shortcuts perform the same actions.
- Model and route changes affect the next request and are visible in the UI.
- At least one text file and one image can be attached and passed to an
  agent with a manifest.
- Relay start/resume/pause and handoff events are visible and recoverable.
- Existing core and relay CLIs continue to work without the UI extra.
- Tests cover session events, command adaptation, attachments, keyboard
  actions, mouse actions, fallback mode, and subprocess cancellation.
