<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-02T15:00:00+05:30 -->
# Safe pause: a Pause / Pausing… / Resume button that pauses the relay between turns, so nothing is lost

Runs after `plans/relay-chat.plan.md` and before `plans/sdlc-pipeline.plan.md`. Needs whyline-relay with RPZ-1..4 (`~/whyline-relay/plans/safe-pause.plan.md`, released by RPZ-5), which PZ-1 checks. Design: `docs/superpowers/specs/2026-11-02-safe-pause-design.md`. Read it before any task. Where this plan and the design differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the design's behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

What the user gets:
- While a relay runs, Relay mode shows **Pause** next to Stop. Pressing it moves through these states:
  - **Pausing…**: the current agent finishes its turn and hands off. The status line says `⏸ Pausing — letting codex finish its turn so nothing is lost (1m 20s so far)`. **Pause now** and **Keep going** are offered.
  - **Paused**: `⏸ Paused by you at RCH-3, round 2 — press Resume to continue`, and **Resume** replaces Pause.
  - **Resume** continues with the next turn, and nothing is redone.
- A turn cut off by Pause now or Stop has its changed files recorded and handed to the next agent.
- Safeguards:
  - a safe pause on low battery
  - an offer to pause after the Mac wakes from sleep
  - an Awake hint when starting on battery
  - **Pause safely and quit** when quitting with a relay running
- `whyline relay-safety` on the command line saves the safeguards through the same function as Settings.

Rules every task keeps:
- Console first: every console control saves through the same function the CLI calls.
- Pause is always a request through whyline-relay's `request_pause`. The console never kills a process to pause; only Pause now and Stop do, through the existing paths.
- No new dependency. Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- Tests never run a real agent or relay, never call `pmset`, and never contain "/Users/". Use fakes for `relay_ops`, `run`, and the wall and monotonic clocks.

## Part 1: Pause, Pausing… and Resume

- [x] PZ-1: whyline-relay safe pause is out, and the relay_ops wrappers
  Edit `src/whyline/console/relay_ops.py`, `pyproject.toml`, `uv.lock` and their tests only.
  1. Check that whyline-relay with RPZ-1..4 is published (`whyline_relay.loop.request_pause` and `whyline_relay.status.pause_state` exist in the newest release on PyPI). If not, write `@blocked: needs whyline-relay safe pause (RPZ-5)` in the handoff and stop.
  2. Raise the `whyline-relay` lower bound to that version, and run `uv lock`.
  3. Add these wrappers, which work for a relay this console started and for one started elsewhere:
     - `request_pause(root)`
     - `cancel_pause(root)`
     - `pause_now(root)`, which calls `request_pause(now=True)` then the existing interrupt path
     - `pause_state(root)`
  Tests: the wrappers call whyline-relay with the right arguments; `pause_now` on a live run interrupts it.

- [x] PZ-2: The Pause / Pausing… / Resume buttons
  Edit `src/whyline/console/tui.py` and add tests in `tests/console/test_safe_pause.py`.
  1. Add these buttons to the relay controls:
     - `Button("Pause", id="pause")`, shown while a relay runs
     - `Button("Pausing…", id="pausing", disabled=True)`
     - `Button("Pause now", id="pause-now")`
     - `Button("Keep going", id="pause-cancel")`
  2. A 1-second timer reads `relay_ops.pause_state` while the relay tab is visible and a relay is running or pausing. It shows:
     - **running**: Pause and Stop
     - **pausing**: Pausing…, Pause now and Keep going
     - **paused_by_user** or **cut_off**: the existing Resume, in Pause's place, and Stop
  3. Pause calls `request_pause` and switches to the Pausing buttons at once, without waiting for the timer.
  4. Keep going calls `cancel_pause`.
  5. Pause now opens a one-line confirm: "Cut off codex's turn now? Its changed files are kept and the next turn continues from them." On yes it calls `pause_now`.
  6. Resume is the existing Resume flow.
  Pilot tests, with fake `relay_ops`:
  - each state shows the right buttons
  - Pause shows Pausing… at once
  - Keep going goes back to running
  - Pause now asks first
  - Resume after a safe pause calls the existing resume

- [x] PZ-3: The status line while pausing and paused
  Edit `src/whyline/console/tui.py` (the relay status line from RST-1) and its tests.
  1. While **pausing**, the status text becomes `⏸ Pausing — letting <agent> finish its turn so nothing is lost (<elapsed> so far)`. The plan % and task ticks stay.
  2. Once **paused_by_user**, it becomes `⏸ Paused by you at <task>, round <n> — press Resume to continue`.
  3. For **cut_off**: `⏸ Paused — <agent>'s turn was cut off; its <n> changed files are kept. Press Resume to continue.`
  4. Other pauses keep today's text.
  5. The transcript gets one line at each change: "Pause requested…", "Paused by you.", "Pause withdrawn."
  Tests:
  - each text, with a fake clock for the elapsed time
  - % stays visible
  - each transcript line is written once

## Part 2: Safeguards

- [x] PZ-4: Safeguard settings and `whyline relay-safety`
  Create `src/whyline/relaysafety.py` and its tests. Edit `src/whyline/cli.py`.
  1. Add `load() -> SafetySettings(battery_percent: int | None = 15, on_wake: str = "ask", on_quit: str = "ask")` and `save(**changes)`.
     - They are stored per Mac in `~/.whyline/relay-safety.toml`, written atomically, with an injectable base dir.
     - `on_wake` is one of ask / pause / off. `on_quit` is one of ask / pause / leave.
     - Bad values are refused with a plain message.
  2. Add the command `whyline relay-safety [--battery N|off] [--on-wake ask|pause|off] [--on-quit ask|pause|leave]`.
     - With no flags, it prints the settings.
     - Exit codes: 0, or 2 on a bad value.
  Tests: round trip, refusals, CLI.

- [x] PZ-5: Low battery pauses safely
  Create `src/whyline/console/power.py` and edit `src/whyline/console/tui.py`, with tests.
  1. `battery(run=subprocess.run) -> Battery(on_battery: bool, percent: int) | None` parses `pmset -g batt`. It returns None off macOS or on any failure.
  2. While a relay runs, check once a minute.
     - When on battery and at or below `battery_percent`, call `request_pause` once, and show: `Battery at 14% — pausing safely so nothing is lost. Plug in and press Resume.`
     - It doesn't fire again until the battery has been back above the limit, or the relay has been resumed.
  3. With `battery_percent` off, it never fires.
  Tests: parsing real `pmset` output samples, the threshold, firing once, and the setting turned off.

- [x] PZ-6: Sleep and wake, and the Awake hint
  Edit `src/whyline/console/power.py` and `src/whyline/console/tui.py`, with tests.
  1. `WakeWatch(wall, mono)`: on each 1-second tick, a wall-clock gain more than 2 minutes beyond the monotonic gain means the Mac slept. It reports the sleep length.
  2. When the Mac woke while a relay was running:
     - with `on_wake=ask`, show `The Mac slept for 42m while codex was working; its turn may time out.` with **Pause safely** (calls `request_pause`) and **Keep going** buttons
     - with `on_wake=pause`, call `request_pause` and show the same line without buttons
     - with `on_wake=off`, do nothing
  3. When a relay starts on battery with Awake off, add the line: `On battery: press Awake to keep the Mac from sleeping mid-turn.`
  Tests: the fake clocks detect a 42-minute gap and ignore small drift; each `on_wake` value; the Awake hint shows only on battery with Awake off.

- [x] PZ-7: Pause safely and quit
  Edit `src/whyline/console/tui.py` (`action_quit`) and its tests.
  1. When quitting while a relay this console can see is running, ask: **Pause safely and quit** / **Leave it running** / **Cancel**.
     - `on_quit=pause` skips the question and pauses safely.
     - `on_quit=leave` skips it and leaves the relay running.
  2. Pause safely and quit calls `request_pause`, shows the Pausing… status with its elapsed time, and quits once `pause_state` shows paused. Pause now stays available while it waits.
  3. With no relay running, quitting is unchanged.
  Pilot tests: each choice, each `on_quit` value, and quitting only after the fake state shows paused.

## Part 3: Settings, Help and docs

- [x] PZ-8: Settings section, Help and docs
  Edit `src/whyline/console/settings_screen.py`, the console Help text and `README.md`, and create `docs/safe-pause.md`, with tests.
  1. The Settings screen gets a **Relay safety** section, saved on Save through `relaysafety.save`, and transactional like the rest of the screen. It has:
     - the battery limit (off, 10, 15, 20, 25 or a number)
     - when the Mac wakes: ask / pause / off
     - when quitting: ask / pause / leave
  2. The Help text and `docs/safe-pause.md` explain:
     - Pause versus Pause now versus Stop
     - why Pausing… can take a while
     - what Resume does after each
     - the safeguards
     - `whyline-relay pause` and `whyline relay-safety`
  Tests: the Settings round trip; the Help mentions Pause, Pause now and `whyline relay-safety`.

- [x] PZ-10: "Send back as a rejection" in Resolve
  Edit `src/whyline/console/recovery.py`, `src/whyline/console/tui.py` and their tests only. Needs whyline-relay RPZ-7 (`resume --as-rejection`), which PZ-1's version floor covers.
  On 2026-11-02 a review rejection mentioning "sandbox" was misread as a refused command, and Resume paused again on the same text every time.
  1. When the pause reason starts with "<agent> could not run a required command" and the last handoff is `rejected`, Resolve offers **Send back to <implementer agent>** as the first option. It runs `whyline-relay resume --as-rejection`. Ask agent's catalog gets the same action as `send-back`, in the auto-safe set.
  2. Its line says: "The reviewer's rejection was read as a refused command. Send it back to <agent> as a normal rejection."
  Tests: the option shows only for that pause with a rejected handoff; it launches `resume --as-rejection`; Auto picks it once per pause.

- [x] PZ-11: A bigger question box in the Chat tab
  Edit `src/whyline/console/relay_chat_tab.py` and `tests/console/test_relay_chat_tab.py` only.
  Today `#chat-input` is a one-row `Input` with its border removed (`on_mount`). It is hard to see, and a long question scrolls sideways out of view.
  1. Replace it with a small `TextArea` subclass, `ChatQuestion`, in the same file, keeping the id `chat-input`:
     - `soft_wrap=True`, no line numbers, and a visible border like the main `#prompt` box.
     - Placeholder "Ask about this relay".
     - Its height follows the wrapped text: at least 3 rows of text, growing to at most 6, plus the border. Past 6 rows it scrolls inside the box.
     - The answer log (`#chat-log`, `1fr`) gives up the rows. The quick-question and Send/Clear rows stay one line high.
  2. Enter sends the question, the same as before. Terminals cannot reliably tell Shift+Enter from Enter, so there is no new-line key. Text pasted with new lines is kept as typed.
  3. Keep a `value` property (get and set, mapped to the text) so `_send` and the existing tests keep working. `_send` clears the box after sending, and an empty or whitespace-only question still sends nothing.
  4. The Send button, the quick questions, Stop and Clear behave as before.
  Tests:
  - Enter in the box sends the typed question and clears the box.
  - Enter on an empty box sends nothing.
  - A question longer than the box's width wraps, and the box grows past 3 rows of text without going over 6.
  - The box has a border, and its placeholder is "Ask about this relay".
  - The existing tab tests still pass unchanged.

- [x] PZ-12: A working line while Chat waits for an answer
  Edit `src/whyline/console/relay_chat_tab.py` and `tests/console/test_relay_chat_tab.py` only.
  An answer can take a minute or more. Today the only sign is the Stop button, so on 2026-11-05 a question looked unanswered while grok was still working.
  1. While a question is out, show one line between the answer log and the question box: `⠋ grok is working on your question… 42s`. Use the agent the answer is coming from (`agent_choice.pick`), the console's `_SPINNER` frames from `tui.py` (import them, don't copy), and seconds since the question was sent.
  2. Turn the frame and the seconds with `set_interval` about every 0.2 seconds, using a clock the tests can replace. Stop the timer when the answer, an error or Stop arrives, and hide the line.
  3. After Stop, the line says `Stopping…` until the worker returns.
  4. A quick-question button sends nothing while a question is out, the same as Send.
  Tests:
  - Sending shows the line with the agent's name and `0s`, and moving the fake clock moves the seconds.
  - The line hides and the timer stops when the answer arrives, when the agent fails, and after Stop.
  - Stop changes the line to `Stopping…`.
  - Nothing new is sent while a question is out.

- [x] PZ-13: Chat answers show only the final answer, with markdown styled
  Edit `src/whyline/relaychat/ask.py`, `src/whyline/console/relay_chat_tab.py` and their tests (`tests/relaychat/test_ask.py`, `tests/console/test_relay_chat_tab.py`) only.
  On 2026-11-05 a grok answer began "…give a short status.I have the snapshot; next I'll cite…": its progress messages were joined to the answer with no space. It also showed `**running PZ-1**` and backticks as raw text.
  1. Final answer only:
     - Add to `INSTRUCTIONS` in `ask.py`: "Reply with the final answer only. Do not describe what you are about to read or do."
     - In `ask.py`, after `_extract`, call a new `final_message(cli: str, raw: str, text: str) -> str`. For grok, if its JSON output holds the turn as a list of separate assistant messages, return the last non-empty one. Otherwise return `text` unchanged. Never guess where to split a single combined string.
     - Save one real grok `--output-format json` output with more than one assistant message as `tests/relaychat/fixtures/grok_multi_message.json`, with paths and ids replaced by placeholders. If grok's output has no separate messages, say so in the handoff and keep only the instruction change.
  2. Markdown in the tab:
     - Add `render_answer(repo: Path, text: str) -> Text` in `relay_chat_tab.py`, used by `_write` for agent lines in place of the plain `link_paths` call.
     - `**x**` becomes bold `x`, and `` `x` `` becomes cyan `x` without the backticks.
     - A line starting `# `, `## ` or `### ` becomes a bold line without the hashes, and a line starting `- ` or `* ` becomes `• `.
     - Then apply the `path:line` links from `link_paths` to the rendered text, so a path inside backticks is still a link.
     - Unmatched `**` or a single backtick stays as typed.
     - History, `whyline ask` output and Copy keep the raw text.
  Tests:
  - `final_message` returns the last message from the grok fixture, and returns `text` unchanged for other agents and for a single combined string.
  - `render_answer`: bold and code are styled without their markers; headings and bullets as above; `` `src/a.py:3` `` is a link that opens line 3; unmatched markers stay; the plain text has no `**` or backticks.
  - The prompt contains the new instruction.

- [x] PZ-14: A roomier Settings screen with spaced sections
  Edit `src/whyline/console/settings_screen.py` and its tests only. Runs after PZ-8, which adds the Relay safety section to this screen.
  On 2026-11-05 the screen was cramped: the popup is 78 wide, the body is capped at 10 rows, the sections run together, and the Relay chat Agent dropdown was cut off.
  1. Size:
     - The popup is 100 wide, at most 90% of the terminal.
     - The body (`#ss-body`) may use up to 70% of the terminal height (`70vh`) and scrolls past that.
     - The title, hint, error line and buttons always stay visible below the body.
  2. Sections, in this order: **AI subscriptions**, **Relay chat**, **Relay safety**.
     - Each heading is bold and has one blank row above it, except the first.
     - Each section's one-line description sits under its heading.
     - Give every section heading a shared class `ss-section-title` and keep the existing ids.
  3. Rows:
     - Each provider row stays one line.
     - Rows with a `Select` or `Input` are tall enough to show the whole control with its border, so the Agent dropdown is never cut off.
     - Field labels stay in one column of width 36.
  4. Behaviour, ids and saving do not change.
  Tests:
  - At 160×50: the popup is 100 wide; all four providers and every Relay chat and Relay safety field are visible without scrolling.
  - At 80×24: the buttons are visible, and the body scrolls.
  - Each heading after the first has a blank row above it, and the headings come in the order above.
  - The Agent `Select` region is its full height.
  - The existing Settings tests pass unchanged.

- [x] PZ-15: A sent-back round never shows "0 issues"
  Edit `src/whyline/console/relay_ops.py`, `src/whyline/console/relay_screens.py`, `tests/console/test_relay_ops.py` and `tests/console/test_tui_relay_run.py` only.
  On 2026-11-05 PZ-6 round 2 showed "✗ sent back · 0 issues" with "Test: … 1 failed". The tester explained the failure in its summary but filed no `--issue`, and its handoff had an empty issues list, so `task_rounds` skipped the summary bullets.
  1. In `task_rounds`, the issues for a round come from the first of these that is not empty:
     - the handoff's own `issues` list
     - the summary's bullets (`_summary_bullets`), now also when `issues` is an empty list
     - for a sent-back round only:
       - one issue per test whose result reports a failure (`failed`, `error` or a non-zero exit), worded `Test failed: <command>: <result>`
       - failing that, the summary's first sentence, at most 200 characters
     A passed round with nothing filed still has 0 issues.
  2. `RoundOutcome` gets `derived: bool`, true when the issues did not come from the handoff's `issues` list. `issues_text` adds "(from the summary)" or "(from the tests)" after the count, so the user can tell a filed issue from a derived one.
  3. Under a sent-back round, `issues_text` adds a `Why:` line with the summary's first sentence (at most 200 characters), after the issues and before the tests.
  4. The status line's issue count (`last_issues`) uses the same issues, so it matches the Issues view.
  Tests:
  - An empty `issues` list with summary bullets gives those bullets.
  - A sent-back round with no bullets and a "1 failed" test gives one `Test failed: …` issue.
  - A sent-back round with no bullets and no failing test gives the first sentence.
  - A passed round with nothing filed has 0 issues, and filed issues win over everything else.
  - `issues_text` shows the label, and the `Why:` line only for sent-back rounds.
  - The status line count matches the view.

- [x] PZ-16: Check falls back to the backups when an agent is out
  Edit `src/whyline/console/fixmode.py`, `src/whyline/console/tui.py`, `tests/console/test_fixmode_check.py` and `tests/console/test_tui_relay_run.py` only.
  On 2026-11-05 codex was over its usage limit. Check ran it and showed its output (codex's echo of the prompt, then "ERROR: You've hit your usage limit…") as codex's note. It never tried the backups, antigravity and grok. `run_check` only moves on when the runner raises, and a usage limit returns a non-zero exit instead.
  1. Skip agents known to be out. Before running an agent, `run_check` checks `relay_ops.agent_readiness(root)`. An agent whose row is not ready is skipped, using its `why` (for example "codex has reached its usage limit until Nov 8, 00:27"), and the skip is recorded through `pass_over`. If readiness can't be read, nothing is skipped.
  2. Judge every run, not only exceptions:
     - Classify each run with `whyline.agents.runner._classify(agent, exit_code, raw, failure)`, the same as `relaychat.ask`.
     - `usage_limit`, `login_needed`, `timed_out`, `missing` and `failed` all move on to the next agent through `pass_over`, with a reason worded like Chat's ("codex has reached its usage limit.").
     - `cancelled` still stops Check.
     - A run that exits 0 with no text also moves on.
     - Use the runner result's `exit_code` when it has one. A bare string result counts as exit 0.
  3. The note is the agent's answer, not its transcript. Pass the output through `runner._answer` for that agent, the way `relaychat.ask` does, before looking for the JSON block and the prose.
  4. The console shows the fallbacks:
     - `_begin_check` passes `on_progress` and prints each line as `check › codex has reached its usage limit, trying antigravity…`. The line is posted to the UI thread with `call_from_thread`.
     - When every agent is passed over, `_check_finished` prints one line per agent with its reason, instead of "no agent could answer."
  5. Show that Check is working. On 2026-11-05 a claude Check took about 30 seconds, and the only sign was "check › asking claude…".
     - While Check runs, the busy line shows `⠋ check: asking claude · 12s`, using `_SPINNER`, the agent being asked, and seconds since it started. The same tick turns it that drives the Ask agent busy line.
     - The line updates when Check moves to the next agent.
     - The Check button is disabled while it runs, and a Stop next to it cancels through `cancel_event`.
     - The line clears on any result.
  6. Don't let old logs pass as current. On 2026-11-05 Check reported "Grok's balance is exhausted (402)" from a grok log dated the day before, although grok had reviewed successfully since.
     - The prompt gives each log or error it quotes with that file's modification time.
     - The prompt says: "A failure older than the agent's most recent successful turn is history, not current state."
  Tests (additional):
  - The busy line shows the agent and the seconds while a fake runner blocks, moves to the next agent on a fallback, and clears on the result.
  - The Check button is disabled while running, and Stop cancels.
  - The prompt carries the log times and the history sentence.
  Tests:
  - A fake runner returns exit 1 with codex's usage-limit text: Check tries the next agent, and its note is that agent's answer.
  - A not-ready agent in a fake `agent_readiness` is never run, and its skip reason is recorded.
  - An empty exit-0 run moves on.
  - Cancel still stops Check.
  - A note never contains the prompt text.
  - When every agent fails, the console lists each agent with its reason.
  - The existing Check tests still pass.

- [x] PZ-17: A model dropdown in the top bar, and a "not saved yet" hint
  Edit `src/whyline/console/tui.py` and `tests/console/test_context_bar.py` only.
  On 2026-11-05 the user switched the top bar's Agent to claude and wasn't offered any models. The Model field (`#cb-model`) is a free-text `Input`, although `relay_ops.model_options_for_agent` already gives each agent's models and Resolve uses them as a dropdown. The switch also wasn't saved, so Check kept using codex and nothing said so.
  1. Make `#cb-model` a `Select`, keeping its id:
     - Its options are "default" (value `""`) first, then `relay_ops.model_options_for_agent(agent)` for the agent shown, then "Other…".
     - When that function returns `None` (antigravity with no cached list), offer "default" and "Other…" only.
  2. When the Agent select changes, rebuild the options for the new agent and select that agent's saved model (`_model_for`), or "default". This replaces today's rule for keeping typed text.
  3. "Other…" opens a one-line `Input` next to the select, for a custom id. Enter or Save saves it, and `relay_ops.valid_model` checks it first, as today. Esc or an empty value returns to the previous choice.
  4. A saved model not in the list shows as an extra option, "<id> (saved)", so it never disappears.
  5. While the shown agent or model differs from the saved one, `#cb-save` stays enabled as today, and a muted label after it says "not saved yet". Check and Chat keep using the saved agent. The label goes away on Save or when the choice is set back.
  6. "default" is a valid choice. Today `_cb_save` refuses an empty model through `_model_rejected` ("A model name is required"), so switching to an agent with no saved model could never be saved. On 2026-11-05 switching to claude failed this way and Check kept running codex.
     - Save accepts "default" (value `""`) and writes the agent with no model through `model.set_one(root, agent, "")`, which already clears it.
     - `_model_rejected` still refuses spaces and quotes in an Other… id.
     - A Save that is refused prints its error and also shows it in place of "not saved yet", so it can't be missed.
  7. Every code path that reads `#cb-model` (`_cb_saved_tuple`, `_cb_dirty`, `_cb_save`, the narrow-layout label) reads the select's value, or the Other input's value when Other is chosen.
  Tests:
  - Choosing claude lists default, opus, sonnet, haiku and the claude ids, then Other…. Choosing codex lists codex's models.
  - Switching agent selects that agent's saved model.
  - A saved id that isn't listed shows as "(saved)".
  - Other… with "claude-opus-5-5-high" is refused by `valid_model`, and a valid custom id is saved.
  - "not saved yet" appears after changing the agent and goes away after Save.
  - Switching to claude with "default" and pressing Save writes `default_agent: claude` with no claude model, and Check then uses claude.
  - A refused Save shows its error next to Save.
  - Save writes the agent and model through `model.set_default_agent` and `model.set_one`, as today.
  - The existing context-bar tests are updated only where they typed into `#cb-model`.

- [x] PZ-18: Check's answer as a short report, with actions and follow-up
  Edit `src/whyline/console/fixmode.py`, `src/whyline/console/relay_screens.py`, `src/whyline/console/tui.py` and their tests (`tests/console/test_fixmode_check.py`, `tests/console/test_relay_screens.py`, `tests/console/test_tui_relay_run.py`) only. Runs after PZ-16.
  On 2026-11-05 Check's answer came back as one long paragraph inside the transcript. It was hard to read, and it offered nothing to do next and no way to ask about it.
  1. Ask for a structure. In `build_check_prompt`, replace the closing instructions with a request for one fenced JSON block:
     ```
     {"health": "fine|stuck|going round in circles|quota risk",
      "headline": "<one sentence, at most 120 characters>",
      "findings": ["<at most 4 short points, each at most 140 characters, citing path:line where it helps>"],
      "steps": [...catalog steps, as today...],
      "confidence": "high|medium|low"}
     ```
     Prose outside the block is ignored.
  2. Parse it. `CheckResult` gets `health: str`, `headline: str` and `findings: list[str]`. `run_check` reads them from the JSON:
     - An unknown `health` becomes "unclear".
     - Findings past 4 are dropped, and long ones are cut at 140 characters with "…".
     - With no JSON block, the first sentence becomes the headline, the next three sentences become the findings, and health is "unclear". The raw text is never shown whole.
  3. Show it in a modal, `CheckReportScreen` in `relay_screens.py`, styled like `IssuesScreen`. It shows, in order:
     - A health line with a mark: `✓ Fine`, `⚠ Quota risk`, `⚠ Going round in circles`, `✗ Stuck` or `? Unclear`, then `· asked claude · 31s` (plus "after codex: usage limit" when it fell back).
     - The headline.
     - The findings as bullets. `path:line` opens the file, using `relay_chat_tab.link_paths`.
     - Under "Suggested for the next pause", each step in plain words from the catalog labels (for example "Use claude for the reviewer"), or "Nothing to change" when there are none.
  4. Buttons:
     - **Apply when paused** shows only when there are steps, and calls the existing `_store_check_proposal`.
     - **Ask about this** puts the report into the Chat history as an assistant line (`relaychat.history.append(..., "assistant", <report text>, agent="check")`), opens the Files pane's Chat tab and focuses its question box. Chat's next question then has the report as context.
     - **Check again** and **Close**.
  5. The transcript gets one line, `check › ⚠ Quota risk — <headline> (Show report)`, and clicking it reopens the last report. The full text stays in `check-agent-<agent>.log`.
  Tests:
  - JSON with all fields fills the result. A bad health becomes "unclear". The 5th finding is dropped, and a long finding is cut.
  - Text with no JSON gives a headline and at most 3 findings.
  - The report shows the health mark, the agent, the headline, the bullets and the plain-word steps. "Apply when paused" is hidden when there are no steps.
  - Ask about this appends one assistant line with agent "check", and shows the Chat tab with focus in its box.
  - The transcript line reopens the report.
  - The prompt asks for the JSON fields above.

## Publish

- [x] PZ-9: Publish whyline with PZ-1..8 and PZ-10..18
  relay-profile: release
  Bump the version in `pyproject.toml`, `src/whyline/__init__.py` and `uv.lock` to the next patch version. Write `docs/releases/v<version>.md` from every task since the previous release (`git log v<previous>..HEAD`), in user terms. Run `uv run pytest -q` with the agent CLIs off PATH and `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1`, and again on Python 3.11. Push, wait for green CI on Linux and macOS, then tag `v<version>`, push the tag and let the release workflow publish to PyPI. Afterwards run `uv tool upgrade whyline` and confirm `whyline --version`.
