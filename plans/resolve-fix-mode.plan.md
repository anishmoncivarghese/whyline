<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-10-31T23:30:00+05:30 -->
# Resolve Fix mode: Ask agent can talk it through, fix, check and continue the relay

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Starts after `plans/relay-status-line.plan.md` is complete, and before `plans/release-1-core.plan.md`: every later relay benefits from it. It needs no whyline-relay change. It builds on ASK-1..4 (in `plans/idea-inbox.plan.md`): `recovery.ask_agent`, `build_ask_agent_prompt`, `CATALOG_ACTIONS`, `apply_steps`, and Auto's safe set.

Why: Ask agent already diagnoses every pause with full context and proposes catalog steps, but it is read-only and one-shot. On 2026-10-31 the pauses that buttons could not solve all needed files edited or commands run:
- approved WF-13 work left uncommitted after an index.lock error
- a stale test failing on both Pythons
- a bug in whyline's own CV path handling
Each time the user took screenshots to a separate Claude or ChatGPT session and came back with commands to run.

What the user gets:
- **A conversation.** The Resolve panel gets a reply box. Follow-ups ("why?", "try another way", "run the tests") keep the pause's context and the earlier answers.
- **Three levels** (a setting next to Resolve's Ask/Auto, and switchable per pause):
  - **Suggest:** today's behaviour.
  - **Fix with approval:** the agent edits files and runs checks, then you review the diff before anything continues.
  - **Auto fix:** the same, and whyline continues on its own when the checks pass.
- **Hard limits, enforced by whyline.** The agent may edit files, run tests and read-only git commands, and change relay config. It may not commit, push, reset, clean, rebase, switch branches or edit ticked plan tasks. Commits stay whyline's, through catalog actions.
- **Undo fix.** A snapshot before the agent touches anything puts the working tree back exactly.
- **Check, then continue.** After a fix, whyline runs relay doctor and the task's own verify command, then applies the agent's last step (resume or start), and the relay continues in the console.
- **Bugs in whyline itself** go to the Idea Inbox as a ready-to-fix report, with a workaround applied where there is one. The agent never edits the installed tool.
- **Check** (anytime in Relay mode, suggest-only): the agent looks over a running relay for a stuck agent, a quota about to run out, or a task going round in circles.

Global constraints:
- New code lives in `src/whyline/console/fixmode.py`, with tests in `tests/console/test_fixmode.py`, unless a task names other files.
- Fix mode's own files live under `.git/whyline-fix/` (session, snapshots list, attempts), so a relay's `git add -A` can never sweep them.
- Fix mode only runs while the relay is paused or stopped, never while a relay runs. **Check** is read-only and may run anytime.
- Every subprocess goes through an injected `run`, and every agent through the existing injectable runner. No test runs a real agent.
- Verify every task with `uv run pytest -q tests/console` and then `uv run pytest -q`. Change nothing outside the files a task names.

- [ ] FIX-1: Snapshot and Undo fix
  Create `src/whyline/console/fixmode.py` and `tests/console/test_fixmode.py` only.
  - `snapshot(root, *, run) -> Snapshot(id, head, branch, commit, untracked, created)`:
    - build a commit of the whole working tree with a temporary index: `GIT_INDEX_FILE=<tmp> git add -A`, then `git write-tree`, then `git commit-tree <tree> -p HEAD -m "whyline fix snapshot <id>"`. This covers tracked changes and untracked files that aren't ignored. HEAD, the real index and the working tree are never touched.
    - store it as `refs/whyline/fix/<id>`
    - record HEAD, the branch and the untracked list in `.git/whyline-fix/snapshots.json`
  - `changed_since(root, snap, *, run) -> list[Change(path, kind)]` compares the working tree with the snapshot commit, using the same temporary-index method. Kinds are added, modified and deleted.
  - `undo(root, snap, *, run) -> list[str]`:
    - restore every path the snapshot has, with `git restore --source=<commit> --worktree -- <paths>`
    - delete files that are absent from the snapshot and appeared after it (never ignored files)
    - re-stage exactly what was staged at snapshot time (save `git diff --cached --name-only` in the record and re-add those paths)
    It returns the paths it changed. It refuses when HEAD or the branch moved since the snapshot, and says why.
  - `prune(root, keep=20)` deletes the oldest snapshot refs.
  Tests (temp repos):
  - modified, added, deleted and staged files all come back after undo
  - an ignored file is untouched
  - undo refuses after HEAD moves
  - the snapshot never changes HEAD, the index or the working tree
  - prune keeps the newest 20

- [ ] FIX-2: Run an agent that can edit but not commit
  Edit `src/whyline/agents/capabilities.py` and `tests/agents/test_capabilities.py`; edit `src/whyline/console/fixmode.py` and its test only.
  - `capabilities.fix_command(cli, command) -> list[str] | None`, an edit-allowed command with guards:
    - claude: `--permission-mode acceptEdits`, plus `--disallowedTools` for `Bash(git commit:*)`, `Bash(git push:*)`, `Bash(git reset:*)`, `Bash(git clean:*)`, `Bash(git rebase:*)`, `Bash(git checkout:*)`, `Bash(git switch:*)`, `Bash(git stash:*)`, `Bash(git tag:*)`, `Bash(git branch -D:*)`, `Bash(rm -rf:*)`. Any bypass flag already in the command is removed.
    - codex: `--sandbox workspace-write`, which has no network by default, so pushes fail. Remove any danger or bypass flag.
    - any other agent: None. That agent isn't offered Fix mode, and the chain moves to the next agent that has a guard.
  - `fixmode.guard(root, snap, before, *, run) -> list[Violation]` runs after every agent turn and checks:
    - HEAD, branch and every ref under `refs/heads` and `refs/tags` are unchanged
    - `.git/config` and `.git/hooks/` are unchanged
    - the lines of ticked plan tasks in the configured plan are unchanged
    - no changed path lies outside the repository (resolved symlinks included)
    Any violation runs `undo`, after resetting HEAD with `git reset --soft <snapshot head>` only when the agent made a local commit. Every violation is reported in plain words. A moved remote-tracking ref is reported as "the agent may have pushed", and nothing is undone there.
  Tests:
  - each agent's command, with bypass flags removed
  - None for an unknown agent
  - each guard check, using a fake agent that commits, edits a ticked task, edits `.git/hooks`, or writes through a symlink outside the repository
  - a commit made by the agent is undone and reported

- [ ] FIX-3: New catalog actions for fixes
  Edit `src/whyline/console/recovery.py` and `tests/console/test_recovery.py` only.
  Add these to `CATALOG_ACTIONS`, with validation and `apply_steps` support:
  - `commit-task {task}`: only when the task's last handoff in the ledger is approved, or the user confirmed. It commits the dirty files as `feat: <task title> (<task>)` (the relay's format), ticks the task in the plan with `whyline_relay.plan.tick`, then commits `chore: tick <task> in the plan`. This is the WF-13 case.
  - `run-check {command}`: runs a command the plan or config names: the task's `Verify with` commands, relay config's test command, or relay doctor. It returns the exit code and the last 40 lines. Any other command is refused.
  - `config-commit`: commits only relay config files, as ASK-3 does.
  - `report-bug {title, body, component: whyline|whyline-relay}`: adds an idea to the Idea Inbox (`ideas.store.add(ideas.store.connect(), text, source="resolve", source_ref=<pause id>)`), tagged `bug:<component>`, with the pause reason, versions (`whyline --version`, the relay version) and the agent's diagnosis.
  - `undo-fix {snapshot}`: calls `fixmode.undo`.
  Tests: commit-task makes both commits only after an approved handoff; run-check refuses an unlisted command; report-bug writes one idea with the tag and versions; undo-fix restores.

- [ ] FIX-4: A conversation in the Resolve panel
  Edit `src/whyline/console/recovery.py`, `src/whyline/console/tui.py`, `src/whyline/console/fixmode.py` and their tests only.
  - `fixmode.Session(pause_id, agent, level, turns: list[Turn(role, text, at)], snapshots, attempts)` is saved in `.git/whyline-fix/session.json`. A new pause (a different `pause_id`, taken from the state's pause reason and time) starts a new session, and the old one is kept as `session-<n>.json`.
  - After Ask agent answers, the Resolve panel shows a reply box. Each reply is sent to the same agent with:
    - the original `build_ask_agent_prompt` context
    - the session's turns (trimmed oldest-first to keep the prompt under 40 KB)
    - the reply
  - It runs read-only at Suggest level. Each answer may again end with the JSON proposal, which is shown with Apply buttons as today.
  - Typing `fix` or pressing **Fix it** switches this pause to Fix (FIX-5), using the level setting.
  - The transcript shows `you ›` and `<agent> ›` lines.
  Tests: a second question includes the first answer; a new pause starts a new session; trimming keeps the context and the newest turns; a proposal in a follow-up shows Apply buttons.

- [ ] FIX-5: Fix with approval
  Edit `src/whyline/console/fixmode.py`, `src/whyline/console/recovery.py`, `src/whyline/console/tui.py`, `src/whyline/console/relay_screens.py` and their tests only.
  - `fixmode.run_fix(root, session, *, agent_chain, runner, on_progress, cancel_event) -> FixResult`:
    1. Take a snapshot.
    2. Run the first agent in the chain that has a `fix_command`, with the fix prompt: the context plus the conversation, then the instructions:
       - make the smallest change that resolves the pause
       - don't commit, push or change branches
       - prefer config changes over code changes
       - if the cause is a bug in whyline or whyline-relay itself, don't edit the installed tool; propose `report-bug` and any workaround
       - end with the JSON proposal, whose last step is the way to continue
    3. Run the guard, then collect `changed_since`.
  - The Resolve panel shows:
    - the diagnosis
    - the changed files with +/− counts
    - **View diff** (opens the console's existing file or diff view)
    - the proposed steps
    - buttons **Approve and continue**, **Undo fix**, **Ask again** (back to the conversation, keeping the changes) and **Stop**
  - A guard violation shows what was undone, and offers **Ask again** or **Stop**.
  - The fix turn uses the relay's per-agent timeout, shows elapsed time, and **Stop** cancels the turn.
  Tests (fake agents):
  - a fix that edits two files shows both with counts
  - Undo restores
  - a violating agent is undone and reported
  - an agent without a guard is skipped for the next one
  - Stop cancels

- [ ] FIX-6: Check, then continue the relay
  Edit `src/whyline/console/fixmode.py`, `src/whyline/console/tui.py` and their tests only.
  - **Approve and continue**, or Auto fix, runs `verify(root, task)`:
    - relay doctor through `adapters.run_doctor`
    - the task's `Verify with` commands, taken from the plan task text (backtick-quoted commands after "Verify with"), or relay config's test command when there are none
    Each runs through `run-check`.
  - When everything passes, whyline applies the proposal's steps with `apply_steps` (catalog validation as today), so a final `resume` or `start` launches the relay in the console as the Resume button does. The transcript says `Fix checked (doctor ✓, tests ✓); resuming JOB-24.`
  - A failing check goes back to the conversation with the failing output added as the next turn. It doesn't continue, and the snapshot stays for Undo.
  - The Fix level setting: **Suggest / Fix with approval / Auto fix**, shown next to Resolve's Ask/Auto and saved the same way. It defaults to Fix with approval.
  Tests: passing checks apply the steps and launch resume; a failing test returns to the conversation with its output; Verify-with parsing finds both commands in a task like JOB-23's; the setting round-trips.

- [ ] FIX-7: Auto fix guard rails
  Edit `src/whyline/console/recovery.py`, `src/whyline/console/fixmode.py`, `src/whyline/console/tui.py` and their tests only.
  - In Auto (Resolve mode auto) with Fix level Auto fix, run when no rule-based fix applies or one already failed on this pause:
    - one fix attempt per pause
    - a second pause with the same reason after an applied fix stops for the user, naming the fix and its files
    - a 20-minute cap per fix turn
    - main agent first, then the backup chain on a limit or timeout
    - steps outside ASK-4's safe set (plus `run-check`, `config-commit`, `report-bug` and `undo-fix`) stop and show the proposal
    - `commit-task` is auto-safe only after an approved handoff
  - Every attempt is recorded in `recovery.json` and `.git/whyline-fix/attempts.json`: agent, diagnosis, files, checks, result.
  - When Auto stops, the panel says why and keeps the conversation open.
  Tests: one attempt per pause, the same reason twice stops, commit-task without approval stops, a non-safe step stops with the proposal, and the record is written.

- [ ] FIX-8: Check a running relay
  Edit `src/whyline/console/fixmode.py`, `src/whyline/console/tui.py` and their tests only.
  - A **Check** button in the Relay row (Relay mode only, enabled while a relay runs or is paused) asks the main agent, read-only, with:
    - the live marker
    - the elapsed turn time against the timeout
    - the last 200 transcript lines
    - the quota evidence ASK-2 already gathers
    - the stage visits and send-backs (RST-6's `task_rounds` when present)
    - the plan progress
  - It asks for a short health note: stuck, going round in circles, quota risk, or fine. Any suggestions use the catalog, and nothing is applied while the relay runs.
  - The answer appears in the transcript as `check › …`. With a proposal, an **Apply when paused** button stores it, and it is offered at the next pause.
  - The button is disabled while a check is running.
  Tests: the prompt contains the marker, timeout and log tail; nothing is applied while running; a stored proposal is offered at the next pause.

- [ ] FIX-9: Docs
  Edit `README.md` and `docs/` (create `docs/resolve.md` if there is none) only.
  Cover:
  - the conversation, the three levels and what the agent may and may not do (and that whyline enforces it)
  - Undo fix, the checks before continuing and the Auto guard rails
  - how whyline bugs reach the Idea Inbox, and the Check button
  Include one worked example: the WF-13 index.lock pause, fixed with `commit-task` and resumed.
