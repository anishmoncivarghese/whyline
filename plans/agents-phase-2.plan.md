<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-10-04-agents-mode-design.md | created: 2026-10-07T23:00:00+05:30 -->
# Agents mode, Phase 2 (whyline 0.3.37)

Each task is one task of `docs/superpowers/plans/2026-10-04-agents-mode.md`
(spec: `docs/superpowers/specs/2026-10-04-agents-mode-design.md`).
Read the task in full and follow its steps exactly: write the failing test
first, see it fail, implement, then run the whole suite with `uv run pytest -q`.
The plan's "Global Constraints" and "Review Focus" apply; Phase 2 is where
the Review Focus cases (two ticks at once, a definition edited while
scheduled, a usage limit with a backup, 30 files in a minute, two days
asleep) must be pinned by tests.

Phase 1 is released as whyline 0.3.36: `whyline.agents` (definitions,
records, capabilities, state, runner, service), `whyline agents
list|show|run|pause|resume|accept|history|delete`, and Agents mode in the
console are in the code you start from. Build on their actual names; where
the plan's code differs from what Phase 1 built, follow Phase 1's code and
keep the plan's behaviour. Grok's read-only command keeps no permission
grant (capabilities.py, decided in AG-4); do not loosen it.

Tests must not depend on installed agent CLIs or the whyline binary, must
never touch the real home folder (point HOME at tmp_path; never the real
~/Library/LaunchAgents, ~/Library/Application Scripts, ~/.whyline, the
notification centre, launchctl, osascript or an agent CLI; stub them), must
pass on Windows and Linux (macOS-only features are stubbed in tests and
disabled with a clear message on other systems; check POSIX permission bits
only when os.name != "nt"; compare paths as Path, show them with
.as_posix(), no characters Windows forbids in file names), must not contain
"/Users/" paths, and must press buttons by widget and wait for screens in a
loop rather than click by position or pause one frame. The bottom bar must
fit 80 columns. No whyline-relay changes and no new dependencies.
Never push, tag, bump the version or publish.

- [x] AG-11: Due-time logic (pure functions)
  Implement "Task 11: Due-time logic (pure functions)" from the plan:
  schedule.py with due_times, freshness, plan_tick and next_due, in local
  wall-clock time, including at most one catch-up run and stale due times
  returned as missed. Verify: uv run pytest -q.

- [x] AG-12: The tick: claim once, catch up once, start runs
  Implement "Task 12: The tick" from the plan: tick.py, the occurrence
  functions and accepted_at in state.py (with the ALTER TABLE for stores
  Phase 1 created), `whyline agents tick` and `whyline agents run
  --occurrence ID`. Two ticks at the same moment must run each due
  occurrence once (the unique claim). Verify: uv run pytest -q.

- [ ] AG-13: Folder watch and whyline agents trigger
  Implement "Task 13: Folder watch and `whyline agents trigger`" from the
  plan: folders.py, service.trigger with TooSoon, and `whyline agents
  trigger <name> [--file PATH ...]` (exit code 3 for TooSoon). A folder
  that receives 30 files in one minute starts one run, not 30.
  Verify: uv run pytest -q.

- [ ] AG-14: After a run: backoff, pause, needs attention, notifications
  Implement "Task 14: After a run" from the plan: after.finish, and
  service.run_now calling it with notify=False. Notifications go through a
  stubbed sender in tests. Verify: uv run pytest -q.

- [ ] AG-15: The scheduler on and off, and the console's scheduler controls
  Implement "Task 15" from the plan: launchd.py, `whyline agents scheduler
  on|off|status`, and the console's #agents-scheduler button and
  #agents-status line. Replace Phase 1's placeholders in tui.py ("Scheduler:
  not available yet (comes in the next release)" and "Scheduling arrives in
  the next release; agents run with Run now meanwhile."). On a system that
  isn't macOS, #agents-scheduler is disabled and the status says "Scheduling
  needs macOS for now; agents still run with Run now."
  Verify: uv run pytest -q.

- [ ] AG-16: The Mail recipe
  Implement Steps 1, 2 and 4 of "Task 16: The Mail recipe" from the plan:
  docs/agents-mail-recipe.md, mail.py and `whyline agents mail-script
  <name>`. Skip Step 3 (the live Mail check): it is done by a person before
  the 0.3.37 release. Verify: uv run pytest -q.

- [ ] AG-18: An empty agents list says so
  Not in the plan; found after the 0.3.36 release. With no agents,
  `whyline agents list` prints nothing and exits 0. Make it print one line,
  "No agents yet. Create one with New in the console's Agents tab.", and
  exit 0, and make the console's Agents list (and `list` typed in Agents
  mode) say the same instead of showing an empty list. Write the failing
  tests first. Verify: uv run pytest -q.
