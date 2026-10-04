# Console attachments: whyline console part (0.3.33)

Each task is one task of `docs/superpowers/plans/2026-10-04-console-attachments.md`
(spec: `docs/superpowers/specs/2026-10-04-console-attachments-design.md`;
spike: `docs/attachments-capabilities.md`). Read the task in full and follow
its steps exactly: write the failing test first, see it fail, implement, then
run the whole suite with `uv run pytest -q`. The plan's "Global Constraints"
apply. whyline-relay 0.2.30 is already required and installed (the dependency
bump before Task 6 is done -- skip it).

Tests must not depend on which agent CLIs are installed (CI has none), must
not call the real osascript, Finder or clipboard (stub mac_input), and must
never write outside tmp_path. Paths shown to people use .as_posix(). The
bottom bar and input row must fit 80 columns. Never push, tag, bump the
version or publish -- a human releases afterwards.

- [ ] ATT-6: Staging, limits, drag-and-drop parsing, cleanup
  Implement "Task 6" from the plan: src/whyline/console/attachments.py
  (Attachment, PendingAttachments, stage with the 25 MB / 50 MB / 10-file
  limits, safe_name, ensure_ignored verified by git check-ignore,
  dropped_paths via shlex with file:// URIs, clean_old for session folders
  older than 7 days, never following symlinks) and
  tests/console/test_attachments.py. Verify: uv run pytest -q.

- [ ] ATT-7: Finder picker and clipboard (macOS)
  Implement "Task 7" from the plan: src/whyline/console/mac_input.py
  (available, pick_files, paste_image via osascript with paths passed as
  arguments, never spliced into the script) and tests/console/test_mac_input.py
  with an injected run function. Verify: uv run pytest -q.

- [ ] ATT-8: Attachments in Chat
  Implement "Task 8" from the plan: attachments_ui.py (AttachMenuScreen,
  AttachmentTray, status_text, needs_warning), relay_ops.delivery_for,
  attachments through adapters.run_chat_turn and repl.dispatch, and the
  console's Attach button, tray, /paste, one-time warning before sending, the
  "📎 names" transcript line, clearing only after the turn was accepted.
  Verify: uv run pytest -q.

- [ ] ATT-9: Drag and drop
  Implement "Task 9" from the plan: a PromptInput that intercepts a paste of
  only existing files and asks Attach / Keep as text; anything else is
  inserted unchanged. Verify: uv run pytest -q.

- [ ] ATT-10: Attachments in the Brainstorm and Plan forms
  Implement "Task 10" from the plan: AttachmentsField with summary_text,
  attachments in the Brainstorm form and in the Plan form (replacing the
  "Reference documents" box), PlanRequest.attachments replacing refs,
  relay_ops.draft_plan / plan_from_brainstorm and adapters.run_brainstorm
  passing attachments through. Verify: uv run pytest -q.
