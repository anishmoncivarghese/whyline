<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-10-04-agents-mode-design.md | created: 2026-10-07T00:00:00+05:30 -->
# Agents mode, Phase 1 (whyline 0.3.36)

Each task is one task of `docs/superpowers/plans/2026-10-04-agents-mode.md`
(spec: `docs/superpowers/specs/2026-10-04-agents-mode-design.md`).
Read the task in full and follow its steps exactly: write the failing test
first, see it fail, implement, then run the whole suite with `uv run pytest -q`.
The plan's "Global Constraints" and "Review Focus" apply. Task 1 (the spike)
is done; see `docs/agents-capabilities.md`. Prerequisite whyline 0.3.35 is
released: the context bar, Chat/Relay/Agents modes and per-mode bottom-bar
buttons are in the code you start from.

Tests must not depend on installed agent CLIs or the whyline binary, must
never touch the real home folder (point HOME at tmp_path; never the real
~/Library/LaunchAgents, ~/.whyline, notification centre or an agent CLI),
must pass on Windows (compare paths as Path, show them with .as_posix(), no
characters Windows forbids in file names), must not contain "/Users/" paths,
and must press buttons by widget and wait for screens in a loop rather than
click by position or pause one frame. The bottom bar must fit 80 columns.
No whyline-relay changes and no new dependencies.
Never push, tag, bump the version or publish.

- [x] AG-2: Agent definitions
  Implement "Task 2: Agent definitions" from the plan: the whyline.agents
  package and definitions.py (repo and personal TOML agents, names, ids,
  the small TOML writer). Verify: uv run pytest -q.

- [x] AG-3: Run records, reports and ledger events
  Implement "Task 3: Run records, reports and ledger events" from the plan.
  Verify: uv run pytest -q.

- [ ] AG-4: CLI capabilities (from the spike)
  Implement "Task 4: CLI capabilities (from the spike)" from the plan:
  READ_ONLY settings, denial detectors and UNATTENDED_OK, exactly as
  docs/agents-capabilities.md records them. Verify: uv run pytest -q.

- [ ] AG-5: The state store (activations)
  Implement "Task 5: The state store (activations)" from the plan, including
  a definition edited by git pull stopping until accepted again.
  Verify: uv run pytest -q.

- [ ] AG-6: execute_once: prompt, read-only command, backups, outcome
  Implement "Task 6: execute_once" from the plan. Backups only after
  usage_limit, login_needed or a missing CLI; exit code 0 alone never means
  success. Verify: uv run pytest -q.

- [ ] AG-7: The service and whyline agents
  Implement "Task 7: The service and `whyline agents …`" from the plan.
  Verify: uv run pytest -q.

- [ ] AG-8: Agents mode in the console (list, detail, Run now, history)
  Implement "Task 8" from the plan, with these corrections, because whyline
  0.3.35 already built part of its Step 4:
  - Command mode is gone. Keep `_MODES = ("chat", "relay", "agents")`; do not
    add "command" back. `#mode-agents` already exists in `compose`.
  - Do not write a new visibility function. `_sync_mode_buttons` and
    `_MODE_BUTTONS["agents"]` (agents-new, agents-list, agents-runs,
    agents-scheduler) already show only the current mode's buttons. Add the
    four Buttons with those ids to `#controls`, and show `#agents-status`
    only in Agents mode.
  - Replace the "Agents mode arrives in a later release." placeholders: in
    tui.py `_placeholder("agents")` and the `/route agents` branch, and in
    repl.py `/route agents` (switch to Agents mode) and `_dispatch` (Agents
    text goes to `_agents_command`). The `/route` usage stays
    "<chat|relay|agents>".
  - Step 5's note about updating bottom-bar tests is already done by 0.3.35;
    keep existing tests passing.
  Verify: uv run pytest -q.

- [ ] AG-9: New agent form and Review
  Implement "Task 9: New agent form and Review" from the plan.
  Verify: uv run pytest -q.
