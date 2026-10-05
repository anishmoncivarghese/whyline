<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-10-05-console-context-bar-design.md | created: 2026-10-05T17:01:30+05:30 -->
# Console context bar, repo setup and mode-specific controls (0.3.35)

Each task is one task of `docs/superpowers/plans/2026-10-05-console-context-bar.md`
(spec: `docs/superpowers/specs/2026-10-05-console-context-bar-design.md`).
Read the task in full and follow its steps exactly: write the failing test
first, see it fail, implement, then run the whole suite with `uv run pytest -q`.
The plan's "Global Constraints" apply. Prerequisite whyline 0.3.34 is
released: guided flow v2 is in the code you start from.

Tests must not depend on installed agent CLIs or the whyline binary (stub
subprocess calls to `whyline init` in repo-setup tests), must never touch the
real home folder (point HOME at tmp_path), must pass on Windows (compare
paths as Path, show them with .as_posix(), no characters Windows forbids in
file names), must not contain "/Users/" paths, and must press buttons by
widget and wait for screens in a loop rather than click by position or pause
one frame. Every popup's main button and the context bar must fit 80x24.
Never push, tag, bump the version or publish.

- [x] CB-1: Saved default agent, per repo and global
  Implement "Task 1" from the plan: model.default_agent / set_default_agent /
  global_path / load_global / save_global / resolve (repo, then global, then
  claude), /model saving the default, and the console starting on it.
  Verify: uv run pytest -q.

- [ ] CB-2: Inspecting and setting up a repo (no UI)
  Implement "Task 2" from the plan: repo_setup.inspect / describe / setup /
  SetupError, with home and nested-repo refusals, step-by-step setup that
  skips finished steps, and a first commit of only the files setup created.
  Verify: uv run pytest -q.

- [ ] CB-3: The context bar
  Implement "Task 3" from the plan: Agent / Model / Repo / all repos / Save,
  Save greyed until a change, unavailable agents snapping back with their
  hint, saving defaults, switching or setting up a repo with one
  confirmation, refusing a switch while a job runs, and the 80-column fit.
  Verify: uv run pytest -q.

- [ ] CB-4: Retire Command mode; /<command> runs whyline anywhere
  Implement "Task 4" from the plan: modes chat / relay / agents (default
  chat), /<whyline subcommand> routed to run_whyline_command after the
  console's own slash commands, /route command explained, /help listing
  whyline commands, and the "/" hint. Update existing tests that used
  Command mode to use /<command> instead, keeping what they check.
  Verify: uv run pytest -q.

- [ ] CB-5: Each mode shows only its own buttons
  Implement "Task 5" from the plan: _MODE_BUTTONS, _SHARED_BUTTONS,
  _sync_mode_buttons, Attach in Chat only, shared buttons last, every mode
  within 80 columns. Verify: uv run pytest -q.
