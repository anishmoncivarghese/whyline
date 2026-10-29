<!-- whyline-plan v1 | source: draft | drafted-by: claude | created: 2026-10-29 -->
# One-click agent switch when the relay pauses on a limit

Draft. It is not part of `plans/job-search-1-profile-and-companies.plan.md`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

What happened on 2026-10-29 at JOB-8, and what each task fixes:

- grok was out of credit (402) and antigravity out of quota (429, "Resets in 159h57m31s"). The relay paused: "every backup in the chain is unavailable for implementer". Nothing remembered either limit. (whyline-relay RLY-8, SWP-1)
- To switch, the user pressed Change agents, picked antigravity, pressed Check, then Resolve, then "Resume and keep changes". That was five steps. antigravity failed again 13 s later, so the user repeated all five steps to pick claude. (SWP-2..5)
- Set up's check failed with "working tree has uncommitted changes", but the change was JOB-8's own draft. That false failure is what sent the user through Resolve. (SWP-3, SWP-4)
- Resolve said grok "is logged in again", offered "Switch back to grok anyway", and recommended Ask agent. None of those helps when an agent is out of quota. (SWP-6)
- The backup chain held only grok and antigravity, so the relay had to stop and ask. (SWP-5)

The relay side is whyline-relay RLY-8 and RLY-9 in `relay-followups-plan.md`. SWP-1 raises the whyline-relay floor to the release that has them, so start this plan only after that release.

Console first: each action has a console control, and the console saves through the same function the CLI calls (`relay_ops.save_roles`, `failover.ready_agents`).

Tests use `App.run_test()`, press buttons by id, and `await pilot.pause()` with no duration. No fixed sleep, no network, no real vendor agent (inject fake runners and a fake `ready_agents`), no real home directory, and no `/Users/` path. New console tests must pass at 80x24. `uv run pytest -q` is the suite command.

- [ ] SWP-1: Read agent readiness from the relay
  Edit `pyproject.toml` and `uv.lock` (the whyline-relay floor), `src/whyline/console/relay_ops.py` and `tests/console/test_relay_ops.py` only.
  Raise the whyline-relay floor to the release with RLY-8 and RLY-9. Add `relay_ops.agent_readiness(root) -> list[AgentReadiness]`, which calls `failover.ready_agents` with the loaded settings and returns `[]` when the config cannot load. Add `relay_ops.ready_for(root, role) -> list[str]`: the ready agents that are enabled providers (`setup_choice_agents`), excluding the agent the role is already configured or switched to.
  Tests: readiness passes through, a broken config gives `[]`, disabled providers and the role's current agent are left out.

- [ ] SWP-2: Set up labels agents that cannot run
  Edit `src/whyline/console/relay_screens.py` (`RelaySetupScreen._role_options` and the backup chain picker) and `tests/console/test_relay_screens.py` only.
  Each role and backup option whose readiness row is not ready reads `<agent> — <why>`, for example "antigravity — out of quota until 2026-11-04 18:30". It can still be chosen. When one is saved for a role, Check shows `warn  <role> is <agent>, which is <why>`.
  Tests: a limited agent's label carries its reason, a ready agent's label is unchanged, and saving a limited implementer makes Check warn.

- [ ] SWP-3: Tell the paused task's own changes from other changes
  Edit `src/whyline/console/recovery.py` and `tests/console/test_recovery.py` only.
  Add `recovery.task_owned_dirty(root, task_id) -> tuple[list[str], list[str]]`, returning (owned, unrelated). Relay runtime state under `.whyline/relay/` is ignored. A dirty path counts as owned when any of these is true:
  - one of the task's handoffs lists it (reuse `_task_handoff_paths`)
  - the task text in the plan names it
  - it was modified after the task's first round started (from the relay state's `started`)
  `retry_stage_args` uses it. Its behaviour is unchanged for paths that handoffs list.
  Tests: a JOB-8-like draft with no handoff, named in the task text, is owned. A file edited before the task started is unrelated. Runtime state is ignored. `retry_stage_args` is unchanged for handoff paths.

- [ ] SWP-4: Set up from a pause does not fail on the task's own changes
  Edit `src/whyline/console/relay_screens.py` (Check and the Resume button in `RelaySetupScreen`), `src/whyline/console/tui.py` (`_open_relay_setup` when a task is paused) and their console tests only.
  When Set up opens while a task is paused and every dirty path is owned (SWP-3), Check shows `ok    1 file from paused JOB-8 is kept when you resume` in place of the dirty-tree FAIL. In that case Set up's Resume saves the roles and launches `resume --allow-dirty` directly, with no Resolve step. Unrelated dirty paths keep today's FAIL and today's Resume.
  Tests: owned changes give the ok line and a direct `resume --allow-dirty`, an unrelated file keeps FAIL, and a clean tree is unchanged.

- [ ] SWP-5: "Continue with <agent>" on a limit pause
  Edit `src/whyline/console/tui.py` (the `#pause-actions` row and its handler), `src/whyline/console/relay_ops.py` (one new function) and `tests/console/test_tui.py` only.
  When the pause reason is a usage limit, a lost login, or "every backup in the chain is unavailable", `#pause-actions` shows up to three buttons, `Continue with <agent>`, from `relay_ops.ready_for(root, role)`. They sit before Change agents, with a checkbox "Also use as backup next time", checked by default.
  One press calls `relay_ops.switch_role(root, role, agent, add_backup) -> list[str]`, which saves through `save_roles` with only that role changed. With `add_backup` it appends the agent to the chain when it is missing. It returns the resume arguments: `["resume", "--allow-dirty"]` when every dirty path is owned (SWP-3), else `["resume"]`. The console prints "Switched <role> to <agent>; resuming." and launches them.
  With no ready agent, it shows "No other agent is ready: <agent — why, …>" and Change agents only.
  Tests: a limit pause shows a button per ready agent and none for a limited one. One press saves the role, adds it to the chain, and launches `resume --allow-dirty`. Unticking the box leaves the chain as it was. Another kind of pause shows no Continue buttons.

- [ ] SWP-6: Resolve recommends a ready agent for limit pauses
  Edit `src/whyline/console/recovery.py` (the role-override problem around "is logged in again" and the options built for limit pauses) and `tests/console/test_recovery.py` only.
  When the configured agent has a limit (`failover.agent_limits`), the problem text says "<agent> is logged in but out of quota until …" and "Switch back to <agent> anyway" is left out. For a limit pause with a ready agent, option 1 (recommended) is "Continue with <first ready agent>", which runs `relay_ops.switch_role` and the resume it returns. Ask agent moves after it. Auto Resolve applies option 1 only when that agent is already in the backup chain. Otherwise it stops and asks, so Auto never starts an agent the user did not choose.
  Tests: a limited configured agent gets the quota text and no "Switch back" option, the ready agent is recommended, Auto applies it only from the chain, and with no ready agent the options are unchanged.

- [ ] SWP-7: Docs and help
  Edit `docs/relay.md` (or the relay section of `README.md` if there is no `docs/relay.md`) and the console Help text in `src/whyline/console/tui.py`, with their tests only.
  Explain the Continue with buttons, the "Also use as backup next time" checkbox, the quota labels in Set up, and `whyline relay roles status` for the same readiness from the command line.
  Tests: the Help text names Continue with and roles status.
