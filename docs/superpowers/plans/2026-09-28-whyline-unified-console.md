# Whyline Unified Console Implementation Plan

## Goal

Build a cross-platform terminal UI and keyboard console that exposes both
Whyline and Whyline Relay while preserving their existing state machines and
CLI contracts.

## Global Constraints

- Do not duplicate Whyline or Whyline Relay orchestration logic in the UI.
- Keep the base installation usable without UI dependencies.
- Every mouse action must have a keyboard equivalent.
- Never send an attachment without displaying it in the pending manifest.
- Never write secrets, credentials, or agent output into committed files.
- Agent processes remain subprocesses owned by the adapter layer.
- Existing CLI behavior and tests must remain compatible after every task.
- Cancellation must preserve resumable relay state.
- Test changes must be scoped to the task being implemented.

## Task 1: Shared session, events, and command adapters

- Add the provider-neutral session state and event types.
- Add adapters for core `whyline` and `whyline-relay` commands.
- Stream stdout/stderr as events and preserve exit codes and pause messages.
- Add cancellation and process cleanup tests.
- Verify existing CLI behavior remains unchanged.

## Task 2: Keyboard console and multiline editor

- Add the optional editor dependency and a plain-console entry point.
- Implement multiline editing, history, paste, word deletion, and Ctrl+Enter.
- Implement slash commands: `/model`, `/route`, `/attach`, `/attachments`,
  `/history`, `/clear`, `/status`, `/stop`, `/help`, and `/exit`.
- Provide a plain fallback when the optional editor cannot be imported.
- Test keyboard actions without starting real agents.

## Task 3: Attachment manifest and extraction

- Add attachment data structures and ignored local storage.
- Implement file, directory, document, and image inspection with size limits.
- Add text extraction and image capability metadata.
- Add removal, duplicate detection, and secret-file warnings.
- Test that the adapter receives the manifest and that unsupported files are
  reported instead of silently omitted.

## Task 4: Model, route, and account controls

- Read available models from Whyline account capability state.
- Add model and route palettes to the shared session layer.
- Preserve Whyline confirmation gates and route transitions.
- Add keyboard commands and tests for unavailable models and fallback routes.

## Task 5: Full-screen mouse-enabled TUI

- Add the optional full-screen TUI dependency.
- Implement the header, transcript, attachment panel, prompt editor, status
  bar, and clickable controls.
- Bind every control to the same session commands used by the keyboard mode.
- Keep streamed agent output separate from the editable prompt.
- Add snapshot/component tests for the main states and keyboard/mouse parity.

## Task 6: Relay lifecycle and recovery views

- Render relay start, task progress, handoffs, reviews, tests, pauses, and
  resume instructions.
- Add stop/resume controls that call existing relay commands.
- Display rate-limit, authentication, permission, and test failures as
  distinct states.
- Test interrupted subprocesses and resumable relay state.

## Task 7: Cross-platform packaging and compatibility

- Add optional dependency groups and a `whyline ui` entry point.
- Verify macOS, Linux, and Windows-compatible terminal behavior.
- Verify terminals without mouse or image support degrade to keyboard mode.
- Add documentation for installation, shortcuts, attachments, and fallback.

## Task 8: End-to-end verification and release readiness

- Run the complete Whyline suite and relay suite.
- Run a fake-agent end-to-end session covering chat, relay, attachment,
  cancellation, and resume.
- Confirm no local attachment, transcript, or credential files enter the
  package artifacts.
- Record decisions and update release notes only after all acceptance checks
  pass.

## Final check

The feature is ready when a clean installation can launch the full-screen UI,
fall back to the keyboard console, switch models, attach a text file and an
image, invoke both Whyline and Whyline Relay, and recover from a cancelled or
rate-limited agent without losing state.
