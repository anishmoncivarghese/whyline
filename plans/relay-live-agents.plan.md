<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-01T01:00:00+05:30 -->
# Change a role's agent while the relay runs, from its next turn

Needs whyline-relay with RLY-13 (`roles.switch`, the `manual` switch reason, `ActiveOverride.keep`). Release that first, then raise this repository's `whyline-relay` floor in LIVE-1. Build on the real names: `relay_ops.current_roles`, `relay_ops.save_roles`, `relay_ops.clear_stale_switches`, `relay_ops.relay_agents`, `relay_ops.live_run`, `RelaySetupScreen` in `src/whyline/console/relay_screens.py`, and in `src/whyline/console/tui.py` `_sync_relay_buttons`, the `relay-setup` button handler and `_relay_line`. Where a name has moved, follow the repository and keep the behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: during JOB-26, codex hit its usage limit and the reviewer moved to antigravity. When codex's usage came back, the only way back was `whyline relay roles reset reviewer` in a terminal, because **Set up** is disabled while a relay runs.

What the user gets:
- **Set up** stays enabled while a relay runs. It opens **Agents for this run** instead of the full setup.
- Each role shows its configured agent and the agent it's on now, with why. For example: `reviewer: codex · now antigravity (codex hit a usage limit, since 00:14)`.
- A role on a backup gets **Back to codex**. Every role gets a dropdown of the agents this run can use.
- **Keep for future runs** (ticked by default) also saves the choice to the normal setup.
- The plan, steps, round limits, models and backup chain are shown but can't be changed here, with the line `Plan and settings stay as they are while the relay runs. Stop the relay to change them.`
- The running turn is never touched. The change applies at that role's next turn. Until then the status line shows `reviewer → codex from its next turn`. When it takes effect, the transcript shows the relay's own line.
- If the agent you picked hits its limit, the relay falls back through the backup chain as usual.
- CLI for scripts: `whyline relay roles switch <role> <agent> [--keep]`, which is the relay's own command. The console calls the same `roles.switch`.

Rules every task keeps:
- Console first. The console saves through `whyline_relay.roles.switch`, the function behind the CLI, and through `relay_ops.save_roles` for **Keep for future runs**.
- Never stop, signal, resume or restart the running relay. Never commit. Write only `.whyline/relay/active-roles.json` (through `roles.switch`) and, with **Keep**, `.whyline/relay/config.toml` (through `save_roles`).
- No new dependency beyond the raised `whyline-relay` floor. No version bump, tag, push or publication.
- Tests use temporary repositories and stub relays. They never start a real agent, never sleep and never contain "/Users/".

- [ ] LIVE-1: Read and change a running relay's agents
  Edit `pyproject.toml`, `uv.lock` (`whyline-relay` floor raised to the release with RLY-13), `src/whyline/console/relay_ops.py` and `tests/console/test_relay_ops.py` only.
  1. Add `RunRole(role, configured, current, reason, since, pending: bool)` and `run_roles(root) -> list[RunRole]`. They're built from the config's roles (`current_roles`) and `failover.read_overrides`. `reason` is "" when the role isn't switched, otherwise the switch's reason in words ("usage limit", "signed out", "switched by you"). `pending` is true when the live marker (`running.live`) shows this role running with an agent other than `current`, meaning the change applies at its next turn.
  2. Add `run_agent_choices(root) -> list[str]`: the agents in the running relay's `[agents]` table (`relay_agents`), which are the only ones `roles.switch` accepts.
  3. Add `switch_live(root, role, agent, *, keep) -> str`. It:
     - with `keep`, calls `save_roles` with that one role changed **first**, because `save_roles` clears switches that its save made stale
     - then calls `whyline_relay.roles.switch(root, settings, role, agent, keep=keep)`
     - returns the relay's message
     A `RoleSetError` becomes a plain `ValueError` with the same text. With `keep` and `agent` equal to the stored role, it only calls `switch`.
  Tests:
  - `run_roles` for no switch, a usage-limit switch and a manual switch
  - `pending` true only when the marker's agent differs for that role
  - `switch_live` back to the configured agent clears the switch
  - `switch_live` to another agent with keep writes config and then the switch, and the switch survives the `save_roles` call (the order matters; assert the final file)
  - without keep, config is unchanged
  - an agent outside the run's `[agents]` is refused
  Verify with `uv run pytest -q tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] LIVE-2: Agents for this run screen
  Edit `src/whyline/console/relay_screens.py`, `src/whyline/console/tui.py` (`_sync_relay_buttons` and the `relay-setup` handler) and `tests/console/test_relay_screens.py` / `tests/console/test_tui.py` only.
  1. `_sync_relay_buttons` no longer disables **Set up** while a relay runs.
  2. The `relay-setup` handler opens the new `RunAgentsScreen` when `relay_ops.live_run` is not None. Otherwise it opens `RelaySetupScreen` as today. **Change agents…** at a pause keeps opening `RelaySetupScreen`.
  3. `RunAgentsScreen` (modal) shows:
     - the title `Agents for this run · <task>`
     - one row per role with its label, a `Select` of `run_agent_choices` set to `current`, the reason line in muted text, and **Back to <configured>** only when `current != configured`
     - the **Keep for future runs** checkbox, ticked
     - the read-only summary of the plan, steps, rounds, models and backup chain, with the line from "What the user gets"
     - **Save** and **Close**
  4. **Back to …** saves at once through `switch_live`. **Save** applies every changed role, one `switch_live` call each. Both run in a thread worker, because `save_roles` writes a file. The result lines are shown on the screen and in the transcript, for example `reviewer → codex from its next turn.`
  5. An error shows on the screen, and the dialog stays open.
  6. The screen refreshes its rows every 2 s from `run_roles`, at most once per 2 s, so a failover during the dialog shows up. When the relay stops running, the screen says `The relay has stopped. Use Set up to change everything.` and **Save** is disabled.
  Add injectable `run_roles_fn` and `switch_fn`, in the style of the other screens, so tests never touch a real relay.
  Tests:
  - Set up enabled while running opens `RunAgentsScreen`, and when idle opens `RelaySetupScreen`
  - Back to calls `switch_fn(role, configured, keep=True)`
  - Save with two changed roles makes two calls, and unchanged roles make none
  - unticking Keep passes `keep=False`
  - an error keeps the dialog open
  - the stopped state
  - no running-relay process is signalled (assert no call to `interrupt_live_run`)
  Verify with `uv run pytest -q tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] LIVE-3: Show a pending change in the status line
  Edit `src/whyline/console/tui.py` and `tests/console/test_tui.py` only.
  1. While a relay runs, after the existing busy text, add ` · <role> → <agent> from its next turn` for each `run_roles` entry whose switch the user made in this console and whose agent the marker hasn't shown yet. Track the switches this console made in memory. Read `run_roles` at most every 2 s, the same rate as the RST-2 status reads.
  2. Drop the note once the live marker shows that role on that agent, or when the relay stops.
  3. If RST-2's `format_live` exists, append to its output; otherwise append to today's busy text. Follow the repository.
  Tests:
  - the note appears after a switch
  - it disappears when a stub marker shows the new agent in that role
  - it disappears when the relay stops
  - there are no extra reads within 2 s
  Verify with `uv run pytest -q tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] LIVE-4: Docs
  Edit the console docs page that covers Relay mode's Set up (find it under `docs/`; it already documents Set up and the backup chain) only.
  Explain:
  - **Set up** while a relay runs opens **Agents for this run**
  - **Back to <agent>** after a usage limit resets, and switching to another agent
  - the change applies from that role's next turn, and the current turn finishes undisturbed
  - **Keep for future runs**
  - a this-run-only switch ends when the plan completes
  - the plan and other settings can't change mid-run
  - `whyline relay roles switch` and `roles reset` for scripts
  Verify with `uv run pytest -q`. Change nothing else.

## Later, not in this plan

- Changing the backup chain or a model mid-run. The relay reads both only when a run starts, so this needs a whyline-relay change to re-read them per stage.
- An option to apply a switch from the next task instead of the next turn.
- Suggest **Back to codex** by itself once codex's limit has reset. This needs RLY-8's limit memory (agent-switch plan).
