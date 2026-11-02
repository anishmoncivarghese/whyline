<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-01T02:00:00+05:30 -->
# Relay tooling: status line, switching agents, recovery lessons and Fix mode

Merged on 2026-11-01 from five plans, in run order: relay-status-line (RST-1..7), relay-live-agents (LIVE-1..4), agent-switch-at-pause (SWP-1..7), relay-recovery-lessons (LSN-1..8), resolve-fix-mode (FIX-1..9) and a Round cap part (RCAP-1..2). PFB-1..5 moved to `plans/sdlc-pipeline.plan.md`. Starts after `plans/done/job-search-4-pdf-workday-bulk.plan.md` is complete. RTL-1 pauses after Part 1 until whyline-relay with RLY-1..13 is released, because Parts 2 to 4 need it. RTL-2 publishes at the end.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task. Each part keeps its own intro and rules; read the intro of the part a task is in before starting it.

## Part 1: Relay status line: stage, reruns, plan progress, per-turn timer, issue counts, live test progress and a selectable Copy view

Starts after `plans/done/job-search-4-pdf-workday-bulk.plan.md` is complete, since both change the console. Best after whyline-relay ships RLY-11 (`stage` and `visit` in `.whyline/relay/running.json`), but every task here also works with the current relay. Without RLY-11, rerun counts are just not shown.

What the user gets:
- **Today:** `relay: JOB-24, claude… 5945s`. The seconds count from when the console started the relay, not from the current turn.
- **First pass:** `relay: JOB-24 (2 of 10, 10%) · implementing · claude · round 1 of 24 · 7m 02s`
- **After a rejection:** `relay: JOB-24 (2 of 10, 10%) · fixing after review 1 · claude · round 3 of 24 · 1m 40s`, then `… · re-review 2 · codex · round 4 of 24 · 0m 35s`.
- **Copy** opens the transcript in a view where you can select just part of it. Copying everything stays one click.
- **Issues:** when a tester or reviewer sends a task back, the line shows `failed 2× (last: 2 issues)`, and an **Issues** button lists every round's outcome and issues for the current task.
- **Live test progress:** while a test or review stage runs, the line shows what the agent last reported, for example `suite 40%, 0 failed (codex says)`. It is labelled as the agent's report because it is read from the agent's own messages.
- The % is plan progress: tasks ticked out of all tasks. Nothing estimates how far one task has got, because agents do not report that and a guessed bar would mislead.

Global constraints:
- No new dependency. The console reads the relay's files through `whyline_relay` (`running.read`, `state.load`, `plan.parse`, `config.load`) and never writes them.
- Every read tolerates a missing or half-written file, and a marker without `stage`/`visit` (relay 0.2.38 and older). A failed read drops that part of the line. It never raises and never blanks the whole line.
- Reading happens at most every 2 seconds. The 0.1 s spinner tick reuses the last result.
- Verify every task with `uv run pytest -q tests/console` and then `uv run pytest -q`. Change nothing outside the files a task names.

- [x] RST-1: Build the live relay summary
  Edit `src/whyline/console/relay_ops.py` and `tests/console/test_relay_ops.py` only.
  Add a frozen dataclass `LiveStatus(task, agent, role, stage, visit, round, max_rounds, started, position, total, done)`. `started` is an aware datetime or None. `position` is the current task's 1-based index in the plan, and `total`/`done` are task and ticked counts. Any of these is 0, "" or None when unknown.
  Add `live_status(root) -> LiveStatus | None`. It returns None when `running.live(root)` is None. It reads `stage` and `visit` with `getattr(marker, ..., default)` so an older relay still works. It takes the plan path from `whyline_relay.state.load(root).plan` (relative to `root`) and parses it with `whyline_relay.plan.parse`. It takes `max_rounds` from `whyline_relay.config.load(root)`. Each of these three reads sits in its own `try` that catches `Exception` and leaves its fields unknown.
  Add `stage_words(stage, role, visit) -> str`:
  - stage `implement` (or role `implementer` when stage is ""): "implementing", or "fixing after review N" with N = visit - 1 when visit > 1
  - stage `review` (or role `reviewer`): "reviewing", or "re-review N" with N = visit when visit > 1
  - any other stage id: the id itself, plus " (rerun N)" with N = visit - 1 when visit > 1
  - nothing known: ""
  Add `format_live(status, now) -> str`. It joins with " · ", skipping empty parts: `TASK (P of T, X%)` (X = done*100//total; only the task when total is 0), the stage words, the agent, `round R of N` (or `round R` when N is unknown), and the elapsed time since `started`. Elapsed reads `42s` under a minute, `7m 02s` under an hour, and `1h 03m` from there, and is omitted when `started` is None. Keep `live_run` unchanged for its other callers.
  Tests:
  - each `stage_words` case, including an unknown stage with visit 3
  - `format_live` for the three example lines in this plan's header
  - a marker in the old shape (no stage or visit) formats with the role's words and no rerun count
  - a missing state file, an unparsable plan and a broken config each drop only their own part
  - elapsed formatting at 0 s, 59 s, 60 s, 3599 s and 3600 s

- [x] RST-2: Show it in the console's busy line, with a timer per turn
  Edit `src/whyline/console/tui.py` and `tests/console/test_tui_relay_run.py` only.
  1. Hold `self._relay_status: LiveStatus | None` and `self._relay_status_read: float` (monotonic). `_relay_line` and `_tick` call `relay_ops.live_status` at most every 2 s while a relay runs, catching `Exception` and keeping the last value.
  2. While `_relay_status` is set and no `_busy_text` is showing, `_tick` renders `<spinner> relay: <format_live(status, now)>`, with no `…` or seconds suffix (the elapsed time is in the summary). Otherwise it keeps today's `label… Ns`.
  3. `_relay_label` (used by the quit dialog and the plan pane title) becomes `relay: <task>, <agent>` as today, so those screens do not change.
  4. `_relay_finished` clears `_relay_status`.
  Inject the clock and `live_status` the same way the file's other relay tests do, so tests never touch a real relay.
  Tests:
  - the busy line shows the formatted summary while a relay runs
  - the elapsed time follows the marker's `started`, not when the relay launched (a marker started 7 minutes after launch shows about 0 s)
  - two ticks within 2 s read the files once
  - a `live_status` that raises keeps the previous line
  - finishing clears it and the old `label… Ns` line returns for chat replies

- [x] RST-3: Telegram and docs
  Edit `src/whyline/ideas/bot.py`, `tests/ideas/test_bot.py`, `README.md` and `docs/releases/` notes only if a release note for the next version already exists.
  1. `bot._relay_status` adds ` · now: <format_live(...)>` to a repository's line when `relay_ops.live_status(root)` returns a value. It catches `Exception`, and the line stays as today otherwise.
  2. README: where Relay mode is described, add one short paragraph with the example lines from this plan's header. Explain that the % counts finished tasks in the plan, and that a rerun count needs whyline-relay with RLY-11.
  Tests:
  - the bot line includes the live summary when a relay runs
  - the bot line is unchanged when none runs, and when `live_status` raises

- [x] RST-4: Copy opens a selectable view of the transcript
  Edit `src/whyline/console/tui.py` and `tests/console/test_tui.py` only.
  Today **Copy** (`_copy_transcript`) puts the whole transcript on the clipboard. The transcript is a `RichLog`, which cannot select text, and a terminal drag selects whole screen rows, including the plan pane beside it.
  1. Move the text building out of `_copy_transcript` into `_transcript_text(events) -> str` (same `_PREFIX` lines as today), and the clipboard part into `_put_on_clipboard(text) -> str`. That helper tries `_system_copy`, falls back to `copy_to_clipboard`, and returns the message that `_copy_transcript` shows today, so both paths say the same thing.
  2. Add `CopyScreen(ModalScreen)` next to `QuitRelayScreen`. It shows the transcript text in a read-only `TextArea` (`read_only=True`, soft wrap on), with the cursor at the end so the latest lines show. Below it are four buttons:
     - **Copy selection**: copies `text_area.selected_text`. It is disabled while nothing is selected (update on `TextArea.SelectionChanged`).
     - **Copy all**: today's behaviour.
     - **Copy last block**: the events after the last `input` event (the user's last message or relay command). With no `input` event, it copies the last 200 lines.
     - **Close**
     Cmd+C or Ctrl+C inside the view copies the selection when there is one. Esc closes the view. After a copy the view closes and the main log shows the message `_put_on_clipboard` returned, for example `Copied 12 lines to clipboard.`. Copy all keeps `Transcript copied to clipboard.`.
  3. The **Copy** button opens `CopyScreen`. With an empty transcript it still shows `(nothing to copy yet)` and opens nothing. The view holds a snapshot taken when it opens, so a running relay adding lines does not move the selection.
  4. If the transcript is over 5,000 lines, the view shows the last 5,000 with a first line `(earlier lines left out; Copy all copies everything)`. **Copy all** still copies the full transcript.
  Inject the clipboard function so tests never touch the real clipboard.
  Tests:
  - Copy opens the view, and an empty transcript shows the old message instead
  - selecting a range and pressing Copy selection copies exactly that text
  - Copy selection is disabled with no selection
  - Copy all copies the same text as before this task
  - Copy last block copies only the lines after the last `input` event, and the last 200 lines when there is none
  - lines added while the view is open don't change it
  - Esc closes without copying
  - a 6,000-line transcript shows 5,000 lines plus the note, and Copy all still copies 6,000

- [x] RST-5: `whyline handoff --issue`, and ask the project's tester for it
  Edit `src/whyline/cli.py`, `src/whyline/handoff.py`, `tests/test_handoff.py`, `tests/test_cli.py` and `.whyline/relay/prompts/test.md` only.
  1. `whyline handoff` gains a repeatable `--issue TEXT` (`dest="issues"`), kept as `issues: list[str]` in the handoff event the same way `risks` is (one line each, in order). `handoff.create` takes `issues=None`.
  2. `format_text` prints each one as `Issue          <n>. <text>` after the summary, so `whyline sync` shows them to the next agent.
  3. `.whyline/relay/prompts/test.md`, under its Failed outcome, adds: `--issue "<one concrete problem, with file and line when known>"`, once per problem, in priority order, as well as `--summary`.
  Tests: `--issue` twice is stored in order; a record without `issues` still formats; `format_text` numbers the issues; the CLI help lists `--issue`.

- [x] RST-6: Issue counts in the status line, and an Issues view
  Edit `src/whyline/console/relay_ops.py`, `src/whyline/console/tui.py`, `src/whyline/console/relay_screens.py`, `tests/console/test_relay_ops.py` and `tests/console/test_tui_relay_run.py` only.
  1. `relay_ops.task_rounds(root, task_id) -> list[RoundOutcome]` reads the handoff events for that task from the ledger (`ledger.read_all(paths.ledger_path(root))`), oldest first. `RoundOutcome(at, from_actor, to_actor, status, summary, issues, tests, sent_back)`:
     - `issues` is the event's `issues`. For an older event without them, use the summary's bullet items (text split on lines or on ` - ` that starts a bullet), or `()` when there are none.
     - `sent_back` is true for status `failed` or the relay's changes status (`whyline_relay.config.load(root).status_map["changes"]`, else `changes`).
     - Events for a different task, and events from before the task's last `approved`/terminal status, are left out, so a re-run task starts clean.
  2. `LiveStatus` gains `sent_back: int` and `last_issues: int`. `format_live` adds ` · failed N× (last: M issues)` when N > 0. It reads `last: see summary` when the last send-back had no issues.
  3. An **Issues** button in the Relay row, enabled while the current or paused task has any `RoundOutcome`, opens `IssuesScreen(ModalScreen)`. It shows one block per outcome (`Round k · <from> → <to> · ✗ sent back / ✓ passed · N issues`), the numbered issues, and `Test: <command>: <result>` lines, plus **Copy all**, **Copy selected issue** (the highlighted line) and **Close**. It is read-only and never changes relay state.
  Tests:
  - task_rounds with `issues`, with only a bulleted summary, and for another task
  - the count resets after an approval
  - format_live with and without send-backs
  - the button is disabled with no outcomes
  - the screen lists blocks in order and Copy all copies them

- [x] RST-7: Live test progress from the agent's own messages
  Edit `src/whyline/console/relay_ops.py`, `src/whyline/console/tui.py`, `tests/console/test_relay_ops.py` and `tests/console/test_tui_relay_run.py` only.
  Testers already narrate progress in the stream the console receives ("The repository run has crossed 32% without an error", or pytest's own `[ 32%]`).
  1. `relay_ops.progress_from_line(line) -> ProgressNote | None` with `ProgressNote(percent: int | None, failed: int | None)`:
     - pytest's `[ NN%]` sets percent
     - any `NN%` (0–100) in a line that also mentions suite, pytest, tests, green, passed, failure or error sets percent
     - `N failed` sets failed
     - "no failures", "without an error", "no failed" or "still green" set failed to 0
     - a pytest summary line such as `N passed[, M failed][, …] in X.XXs` sets percent 100 and failed M (or 0)
     - anything else returns None
  2. While `live_status` reports a stage other than implement (or the role is reviewer), `_relay_line` feeds each line to it, and the latest non-None values are kept. A line that starts a new pytest command (contains `pytest` and `-q` or `run pytest`) resets percent to None, so a focused run's 100% doesn't stick into the full run.
  3. `format_live` adds ` · suite P%[, F failed] (<agent> says)` when a value is known. The values are cleared when the marker's `started` changes (a new turn).
  4. Nothing is shown during implement stages, and no reading of logs or files is added: only lines already arriving.
  Tests:
  - each pattern, using the five narration lines in the screenshot this task came from ("green through 13%", "remains clean at 18%", "reached 20% with no failures", "crossed 32% without an error", "approaching 40%, still with no failures")
  - a pytest bracket line and a pytest summary with failures
  - a percent over 100 is ignored
  - a new pytest command resets
  - a new turn clears
  - the implement stage shows nothing

- [x] RTL-1: Publish whyline with RST-1..7, and install whyline-relay with RLY-1..13
  relay-profile: release
  Part 2 onwards raise the `whyline-relay` floor, so this pause makes sure that release exists first.
  1. In `~/whyline-relay`, RLY-1..13 (`relay-followups-plan.md`) are implemented, released to PyPI, and `uv tool upgrade whyline-relay` shows the new version. If not, stop here and do that first.
  2. Publish whyline with RST-1..7: bump the version in `pyproject.toml`, `src/whyline/__init__.py` and `uv.lock` to the next patch version, write `docs/releases/v<version>.md`, run `uv run pytest -q` with the agent CLIs off PATH and `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1` and again on Python 3.11, push, wait for green CI on Linux and macOS, tag `v<version>`, push the tag and let the release workflow publish to PyPI. Then `uv tool upgrade whyline`.

## Part 2: Change a role's agent while the relay runs, from its next turn

Needs whyline-relay with RLY-13 (`roles.switch`, the `manual` switch reason, `ActiveOverride.keep`). Release that first, then raise this repository's `whyline-relay` floor in LIVE-1. Build on the real names: `relay_ops.current_roles`, `relay_ops.save_roles`, `relay_ops.clear_stale_switches`, `relay_ops.relay_agents`, `relay_ops.live_run`, `RelaySetupScreen` in `src/whyline/console/relay_screens.py`, and in `src/whyline/console/tui.py` `_sync_relay_buttons`, the `relay-setup` button handler and `_relay_line`. Where a name has moved, follow the repository and keep the behaviour.

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

- [x] LIVE-1: Read and change a running relay's agents
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

- [x] LIVE-2: Agents for this run screen
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

- [x] LIVE-3: Show a pending change in the status line
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

- [x] LIVE-4: Docs
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

### Later, not in this part

- Changing the backup chain or a model mid-run. The relay reads both only when a run starts, so this needs a whyline-relay change to re-read them per stage.
- An option to apply a switch from the next task instead of the next turn.
- Suggest **Back to codex** by itself once codex's limit has reset. This needs RLY-8's limit memory (agent-switch plan).

## Part 3: One-click agent switch when the relay pauses on a limit

Separate from the job-search plans.

What happened on 2026-10-29 at JOB-8, and what each task fixes:

- grok was out of credit (402) and antigravity out of quota (429, "Resets in 159h57m31s"). The relay paused: "every backup in the chain is unavailable for implementer". Nothing remembered either limit. (whyline-relay RLY-8, SWP-1)
- To switch, the user pressed Change agents, picked antigravity, pressed Check, then Resolve, then "Resume and keep changes". That was five steps. antigravity failed again 13 s later, so the user repeated all five steps to pick claude. (SWP-2..5)
- Set up's check failed with "working tree has uncommitted changes", but the change was JOB-8's own draft. That false failure is what sent the user through Resolve. (SWP-3, SWP-4)
- Resolve said grok "is logged in again", offered "Switch back to grok anyway", and recommended Ask agent. None of those helps when an agent is out of quota. (SWP-6)
- The backup chain held only grok and antigravity, so the relay had to stop and ask. (SWP-5)

The relay side is whyline-relay RLY-8 and RLY-9 in `relay-followups-plan.md`. SWP-1 raises the whyline-relay floor to the release that has them, so start this plan only after that release.

Console first: each action has a console control, and the console saves through the same function the CLI calls (`relay_ops.save_roles`, `failover.ready_agents`).

Tests use `App.run_test()`, press buttons by id, and `await pilot.pause()` with no duration. No fixed sleep, no network, no real vendor agent (inject fake runners and a fake `ready_agents`), no real home directory, and no `/Users/` path. New console tests must pass at 80x24. `uv run pytest -q` is the suite command.

- [x] SWP-1: Read agent readiness from the relay
  Edit `pyproject.toml` and `uv.lock` (the whyline-relay floor), `src/whyline/console/relay_ops.py` and `tests/console/test_relay_ops.py` only.
  Raise the whyline-relay floor to the release with RLY-8 and RLY-9. Add `relay_ops.agent_readiness(root) -> list[AgentReadiness]`, which calls `failover.ready_agents` with the loaded settings and returns `[]` when the config cannot load. Add `relay_ops.ready_for(root, role) -> list[str]`: the ready agents that are enabled providers (`setup_choice_agents`), excluding the agent the role is already configured or switched to.
  Tests: readiness passes through, a broken config gives `[]`, disabled providers and the role's current agent are left out.

- [x] SWP-2: Set up labels agents that cannot run
  Edit `src/whyline/console/relay_screens.py` (`RelaySetupScreen._role_options` and the backup chain picker) and `tests/console/test_relay_screens.py` only.
  Each role and backup option whose readiness row is not ready reads `<agent> — <why>`, for example "antigravity — out of quota until 2026-11-04 18:30". It can still be chosen. When one is saved for a role, Check shows `warn  <role> is <agent>, which is <why>`.
  Tests: a limited agent's label carries its reason, a ready agent's label is unchanged, and saving a limited implementer makes Check warn.

- [x] SWP-3: Tell the paused task's own changes from other changes
  Edit `src/whyline/console/recovery.py` and `tests/console/test_recovery.py` only.
  Add `recovery.task_owned_dirty(root, task_id) -> tuple[list[str], list[str]]`, returning (owned, unrelated). Relay runtime state under `.whyline/relay/` is ignored. A dirty path counts as owned when any of these is true:
  - one of the task's handoffs lists it (reuse `_task_handoff_paths`)
  - the task text in the plan names it
  - it was modified after the task's first round started (from the relay state's `started`)
  `retry_stage_args` uses it. Its behaviour is unchanged for paths that handoffs list.
  Tests: a JOB-8-like draft with no handoff, named in the task text, is owned. A file edited before the task started is unrelated. Runtime state is ignored. `retry_stage_args` is unchanged for handoff paths.

- [x] SWP-4: Set up from a pause does not fail on the task's own changes
  Edit `src/whyline/console/relay_screens.py` (Check and the Resume button in `RelaySetupScreen`), `src/whyline/console/tui.py` (`_open_relay_setup` when a task is paused) and their console tests only.
  When Set up opens while a task is paused and every dirty path is owned (SWP-3), Check shows `ok    1 file from paused JOB-8 is kept when you resume` in place of the dirty-tree FAIL. In that case Set up's Resume saves the roles and launches `resume --allow-dirty` directly, with no Resolve step. Unrelated dirty paths keep today's FAIL and today's Resume.
  Tests: owned changes give the ok line and a direct `resume --allow-dirty`, an unrelated file keeps FAIL, and a clean tree is unchanged.

- [x] SWP-5: "Continue with <agent>" on a limit pause
  Edit `src/whyline/console/tui.py` (the `#pause-actions` row and its handler), `src/whyline/console/relay_ops.py` (one new function) and `tests/console/test_tui.py` only.
  When the pause reason is a usage limit, a lost login, or "every backup in the chain is unavailable", `#pause-actions` shows up to three buttons, `Continue with <agent>`, from `relay_ops.ready_for(root, role)`. They sit before Change agents, with a checkbox "Also use as backup next time", checked by default.
  One press calls `relay_ops.switch_role(root, role, agent, add_backup) -> list[str]`, which saves through `save_roles` with only that role changed. With `add_backup` it appends the agent to the chain when it is missing. It returns the resume arguments: `["resume", "--allow-dirty"]` when every dirty path is owned (SWP-3), else `["resume"]`. The console prints "Switched <role> to <agent>; resuming." and launches them.
  With no ready agent, it shows "No other agent is ready: <agent — why, …>" and Change agents only.
  Tests: a limit pause shows a button per ready agent and none for a limited one. One press saves the role, adds it to the chain, and launches `resume --allow-dirty`. Unticking the box leaves the chain as it was. Another kind of pause shows no Continue buttons.

- [x] SWP-6: Resolve recommends a ready agent for limit pauses
  Edit `src/whyline/console/recovery.py` (the role-override problem around "is logged in again" and the options built for limit pauses) and `tests/console/test_recovery.py` only.
  When the configured agent has a limit (`failover.agent_limits`), the problem text says "<agent> is logged in but out of quota until …" and "Switch back to <agent> anyway" is left out. For a limit pause with a ready agent, option 1 (recommended) is "Continue with <first ready agent>", which runs `relay_ops.switch_role` and the resume it returns. Ask agent moves after it. Auto Resolve applies option 1 only when that agent is already in the backup chain. Otherwise it stops and asks, so Auto never starts an agent the user did not choose.
  Tests: a limited configured agent gets the quota text and no "Switch back" option, the ready agent is recommended, Auto applies it only from the chain, and with no ready agent the options are unchanged.

- [x] SWP-7: Docs and help
  Edit `docs/relay.md` (or the relay section of `README.md` if there is no `docs/relay.md`) and the console Help text in `src/whyline/console/tui.py`, with their tests only.
  Explain the Continue with buttons, the "Also use as backup next time" checkbox, the quota labels in Set up, and `whyline relay roles status` for the same readiness from the command line.
  Tests: the Help text names Continue with and roles status.

## Part 4: Relay recovery lessons from the personal-assistant run

Separate from `plans/personal-assistant.plan.md`. 0.3.53 already shipped the Telegram test guard and the fix for Resolve opening after a finished plan.

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

## Part 5: Resolve Fix mode: Ask agent can talk it through, fix, check and continue the relay

Starts after Parts 1 to 4 of this plan, and before `plans/release-button.plan.md`: every later relay benefits from it. It needs no whyline-relay change. It builds on ASK-1..4 (in `plans/done/idea-inbox.plan.md`): `recovery.ask_agent`, `build_ask_agent_prompt`, `CATALOG_ACTIONS`, `apply_steps`, and Auto's safe set.

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

## Part 6: Round cap in Set up and at the pause

Why: whyline-relay paused RLY-1 at "the 3-round cap" because that repository's `.whyline/relay/config.toml` had no `max_rounds`, so the relay's default of 3 applied. agentdock had 24. The only ways to change it were editing the file, `--max-rounds` for one run, or **Resolve** adding 6 after a pause.

- [ ] RCAP-1: A Round cap field in Set up, with a sensible default
  Edit `src/whyline/console/relay_screens.py`, `src/whyline/console/relay_ops.py`, `src/whyline/console/recovery.py` (only to call the new saver), `src/whyline/cli.py` and their tests only.
  1. Add `relay_ops.save_max_rounds(root, n)`. It validates 1 to 99 and writes `max_rounds` with the same top-level setter `recovery._raise_max_rounds` uses (`relay_setup._set_unquoted_top_level`), as a `setup: max_rounds N` commit. `recovery._raise_max_rounds` calls it, so there is one saver.
  2. In `RelaySetupScreen`, add **Round cap** next to Timeout: an `Input` restricted to digits, showing the repository's current `max_rounds`. Under it, a hint: `Rounds per task before the relay pauses. Each review or test send-back uses one.`
  3. When the repository's config has no `max_rounds`, the field shows 24 (`DEFAULT_SETUP_ROUNDS = 24`) and marks it `(not saved yet; the relay's own default is 3)`. Set up saves it with the other settings, so a new repository never runs with 3 by accident.
  4. **Check** shows `Round cap: 24`, and warns when it is below 6: `A cap under 6 pauses most tasks after one or two send-backs.`
  5. While a relay runs, the field is read-only with `Takes effect on the next run or resume.`, because the relay reads the cap at start.
  6. CLI counterpart: `whyline relay rounds [N]` prints the current cap, or saves N through `save_max_rounds`.
  Tests:
  - the field shows the saved value, and 24 when the config has none
  - Set up saves it as a `setup:` commit
  - validation of 0, 100 and text
  - the Check line and the low-cap warning
  - Resolve's "more rounds" goes through the same saver
  - the CLI
  Verify with `uv run pytest -q tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] RCAP-2: "Add rounds" on a round-cap pause
  Edit `src/whyline/console/tui.py`, `src/whyline/console/relay_ops.py` and their tests only. Needs RCAP-1's `save_max_rounds`.
  Today a round-cap pause shows only **Change agents** under the transcript. Raising the cap is hidden inside **Resolve**.
  1. When the saved pause reason is a round cap (`hit the N-round cap`, the same match `adapters` uses for `round-cap`), show two more buttons in `#pause-actions` next to **Change agents**:
     - **Add 6 rounds and resume**: calls `save_max_rounds(root, current + 6)` and then the same resume path as **Resume**. The status line says `Round cap 3 → 9; resuming RLY-1.`
     - **Set round cap…**: a small dialog with the current value and a number input (1 to 99). It offers **Save and resume** and **Save only**, both through `save_max_rounds`.
     The buttons are hidden for any other kind of pause.
  2. The pause text in the transcript adds one line: `Raise the cap with Add 6 rounds, or set it in Set up.`
  3. If the new cap isn't higher than the round the task reached, refuse with `RLY-1 is at round 9; choose more than 9.`
  4. Typing `rounds 12` in the relay input does the same as **Set round cap…** with **Save only**, and `rounds +6` does the same as **Add 6 rounds** without resuming.
  Tests:
  - the buttons show only for a round-cap pause
  - Add 6 saves current+6 and resumes once
  - the dialog saves, with and without resuming
  - refusing a cap not above the reached round
  - the typed commands
  Verify with `uv run pytest -q tests/console` and then `uv run pytest -q`. Change nothing else.

- [ ] RST-8: Show "N of T, X%" while a task runs, not only after a pause
  Edit `src/whyline/console/relay_ops.py` and `tests/console/test_relay_ops.py` only.
  `live_status` takes the plan path from `whyline_relay.state.load(root).plan`. The relay writes `state.json` only when it pauses, and clears it on `done`, `skip` and completion. So during a normal run there is no state, `total` is 0, and the busy line drops `(P of T, X%)`. This was seen on 2026-11-01 at LIVE-1 and RDOC-1.
  1. When `state.load(root)` is None or has no `plan`, use `configured_plan(root)` (the plan from Set up). Keep the saved state first when it exists, because a paused run may name a different plan.
  2. Resolve a relative path against `root`, as today. Any failure still leaves `position`, `total` and `done` at 0, never raising.
  Tests:
  - no `state.json` and a configured plan with 10 tasks, 2 ticked, running the 3rd, gives position 3, total 10, done 2, and `format_live` shows `(3 of 10, 20%)`
  - a saved state naming another plan wins over the configured one
  - no state and a missing configured plan gives zeros
  Verify with `uv run pytest -q tests/console` and then `uv run pytest -q`. Change nothing else.

## Publish

- [ ] RTL-2: Publish whyline with LIVE-1..4, SWP-1..7, LSN-1..8, FIX-1..9 and RCAP-1..2
  relay-profile: release
  Bump the version in `pyproject.toml`, `src/whyline/__init__.py` and `uv.lock` to the next patch version. Write `docs/releases/v<version>.md` from every task since the previous release (`git log v<previous>..HEAD`), in user terms. Run `uv run pytest -q` with the agent CLIs off PATH and `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1`, and again on Python 3.11. Push, wait for green CI on Linux and macOS, then tag `v<version>`, push the tag and let the release workflow publish to PyPI. Afterwards run `uv tool upgrade whyline` and confirm `whyline --version`.
