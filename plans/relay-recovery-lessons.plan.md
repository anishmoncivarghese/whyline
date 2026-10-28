<!-- whyline-plan v1 | source: draft | drafted-by: claude | created: 2026-10-28 -->
# Relay recovery lessons from the personal-assistant run

Draft. It is not part of `plans/personal-assistant.plan.md`. 0.3.53 already shipped the Telegram test guard and the fix for Resolve opening after a finished plan.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

What happened on 2026-10-27..28, and what each task fixes:

- ASST-16 hit review's 6-visit cap. Resolve showed three codex rejections from rounds 12–18 and recommended Ask agent. Round 19 had already fixed all three and passed testing. The right choice was Retry stage. (LSN-4)
- After Claude paused ASST-17, Ask agent ran codex read-only with no network. Its test run hung on a Telegram call for minutes, and the console showed `0s` with no way to stop it. (LSN-1, LSN-2)
- Claude paused ASST-17 twice for the same cause (it ran `python -m pytest`). The second Resolve looked just like the first and didn't say the cause had repeated. (LSN-3)
- No setting tells agents which test command to use. (LSN-5)
- A console Brainstorm runs in the console's own repo. While a relay ran there, it had to be moved to a worktree by hand. A Telegram Plan waits until the relay finishes. (LSN-6..8)

The relay-side fixes are whyline-relay RLY-4..7 in `relay-followups-plan.md`. LSN-5 needs RLY-4 released first. Raise the whyline-relay floor in its own release task.

Console first: every new setting has a console control that saves through the same function the CLI calls.

Tests use `App.run_test()`, press buttons by id, and `await pilot.pause()` with no duration. No fixed sleep, no network, no real vendor agent (inject fake runners), no real home directory, and no `/Users/` path. New console tests must pass at 80x24. `uv run pytest -q` is the suite command.

- [ ] LSN-1: Ask agent has a time limit
  Edit `src/whyline/console/recovery.py` (`ask_agent`) and `tests/console/test_recovery.py` only.
  `ask_agent` takes `timeout_seconds`. The default is the relay timeout from `relay_ops` (`_timeout_seconds_kwarg`), capped at 10 minutes. When it runs out, end the agent's whole process group. Then return a result whose diagnosis says "<agent> did not answer within <n> min", with no recommendation, so Resolve still offers its other options.
  Tests: a fake agent that never exits is ended at the limit and its process group is gone, a fast agent is unchanged, and a timed-out result offers Resume and keep changes.

- [ ] LSN-2: Ask agent shows it is working and can be stopped
  Edit `src/whyline/console/tui.py` (the Ask agent run and `_ask_agent_finished`) and `tests/console/test_tui.py` only.
  While Ask agent runs, the status line reads `Ask agent: <agent> · <elapsed>` and updates every second. The Relay row's Stop button ends the Ask agent run (reuse LSN-1's process-group end), then shows "Ask agent stopped." and the Resolve options again.
  Tests: elapsed time advances under a fake clock, Stop ends the fake agent and shows the options, and a normal finish clears the status line.

- [ ] LSN-3: Resolve says when a pause cause repeats
  Edit `src/whyline/console/recovery.py` (`_pause_identity`, `record_attempt`, and the Resolve header) and `tests/console/test_recovery.py` only.
  Keep a normalised cause with each recorded attempt: the reason with round numbers, paths, and text after the first 120 characters removed. When a new pause on the same task has the same cause as its last attempt, the Resolve header starts with "Same cause as the last pause (round <n>)." If the cause is a refused test command, put "Set the test command in Settings, then Resume and keep changes" first.
  Tests: two pauses with the same cause show the line, different causes don't, and a refused test command gets the Settings hint.

- [ ] LSN-4: Resolve marks rejections a later round already answered
  Edit `src/whyline/console/recovery.py` (`recent_rejections`, `_handoff_rejections`, `_log_rejections`, and the cap options) and `tests/console/test_recovery.py` only.
  Each rejection carries its round, shown as "round <n>" before the agent name. After a review visit cap, if the handoff history has a later draft and a later passing test than the newest rejection, label the rejections "answered by round <m>" and make Retry stage the recommended option instead of Ask agent. Otherwise keep today's order.
  Tests: the ASST-16 history (rejections in rounds 12, 15 and 18, a draft and a passing test in round 19) recommends Retry stage, a rejection newer than the last pass keeps Ask agent first, and rounds show in the text.

- [ ] LSN-5: Test command in the console
  Edit `src/whyline/console/relay_screens.py` (the setup screen next to Timeout), `src/whyline/console/relay_ops.py` and `tests/console/test_relay_setup_screen.py` only.
  Needs whyline-relay with RLY-4. Add a "Test command" input that shows `whyline_relay.config.test_command(root)`, marked "(detected)" when it isn't set. Save calls `whyline_relay.config.save_test_command`, the same function `whyline relay test-command` calls. Do not write the file directly.
  Tests: shows the detected value, saving calls `save_test_command` with the typed text, clearing it saves "", and the screen fits 80x24.

- [ ] LSN-6: One place to make and list brainstorm worktrees
  Edit `src/whyline/worktrees.py` (new) and `tests/test_worktrees.py` (new) only.
  `make(root, kind, name) -> Path` adds a git worktree under `~/.whyline/worktrees/<repo>/<kind>-<name>` on a new branch `<kind>/<name>` from the repo's default branch. `kind` is `brainstorm` or `plan`, and `name` is reduced to `[a-z0-9-]`, at most 40 characters. A name already in use gets `-2`, `-3` and so on.
  `list_all(root) -> list[Worktree]` returns the worktrees under that folder, with path, branch, kind, and whether the folder still exists. `remove(root, path)` runs `git worktree remove` and then `git worktree prune`. It refuses a worktree with uncommitted changes and says so.
  Tests use a temporary repo and a temporary home: make, a repeated name, list, remove, refusing a dirty one, and pruning a worktree whose folder is gone.

- [ ] LSN-7: A console Brainstorm moves to a worktree while a relay runs
  Edit `src/whyline/console/tui.py` (`_start_brainstorm`, `_brainstorm_in_thread`) and `tests/console/test_tui.py` only.
  When `whyline_relay.running.live(self.session.root)` is true, the Brainstorm uses `worktrees.make(root, "brainstorm", <topic>)` as its root instead of the console's repo. Before it starts, the transcript says "A relay is running here, so this Brainstorm runs in <path> (branch <branch>)." With no relay running, nothing changes.
  Tests: with a fake live relay, the brainstorm runner gets the worktree path and the transcript names it. With no relay, it gets the console's root.

- [ ] LSN-8: Worktrees in the console and the doctor
  Edit `src/whyline/console/assistant_screen.py`, `src/whyline/ideas/cli.py`, `tests/console/test_assistant_screen.py` and `tests/ideas/test_cli.py` only.
  Add `whyline idea worktrees [--remove PATH]` and a Worktrees list on the Assistant screen with Open and Remove for each. Both call `worktrees.list_all` and `worktrees.remove`. `assistant_doctor` warns about worktrees whose folder is gone, and about any worktree older than 14 days.
  Tests: the CLI and the console list the same entries, Remove refuses a dirty worktree and shows why, and the doctor warns about a missing folder.
