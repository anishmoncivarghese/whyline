<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-10-31T21:00:00+05:30 -->
# Relay status line: stage, reruns, plan progress, per-turn timer, issue counts, live test progress and a selectable Copy view

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Starts after `plans/job-search-4-pdf-workday-bulk.plan.md` is complete, since both change the console. Best after whyline-relay ships RLY-11 (`stage` and `visit` in `.whyline/relay/running.json`), but every task here also works with the current relay. Without RLY-11, rerun counts are just not shown.

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

- [ ] RST-1: Build the live relay summary
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

- [ ] RST-2: Show it in the console's busy line, with a timer per turn
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

- [ ] RST-3: Telegram and docs
  Edit `src/whyline/ideas/bot.py`, `tests/ideas/test_bot.py`, `README.md` and `docs/releases/` notes only if a release note for the next version already exists.
  1. `bot._relay_status` adds ` · now: <format_live(...)>` to a repository's line when `relay_ops.live_status(root)` returns a value. It catches `Exception`, and the line stays as today otherwise.
  2. README: where Relay mode is described, add one short paragraph with the example lines from this plan's header. Explain that the % counts finished tasks in the plan, and that a rerun count needs whyline-relay with RLY-11.
  Tests:
  - the bot line includes the live summary when a relay runs
  - the bot line is unchanged when none runs, and when `live_status` raises

- [ ] RST-4: Copy opens a selectable view of the transcript
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

- [ ] RST-5: `whyline handoff --issue`, and ask the project's tester for it
  Edit `src/whyline/cli.py`, `src/whyline/handoff.py`, `tests/test_handoff.py`, `tests/test_cli.py` and `.whyline/relay/prompts/test.md` only.
  1. `whyline handoff` gains a repeatable `--issue TEXT` (`dest="issues"`), kept as `issues: list[str]` in the handoff event the same way `risks` is (one line each, in order). `handoff.create` takes `issues=None`.
  2. `format_text` prints each one as `Issue          <n>. <text>` after the summary, so `whyline sync` shows them to the next agent.
  3. `.whyline/relay/prompts/test.md`, under its Failed outcome, adds: `--issue "<one concrete problem, with file and line when known>"`, once per problem, in priority order, as well as `--summary`.
  Tests: `--issue` twice is stored in order; a record without `issues` still formats; `format_text` numbers the issues; the CLI help lists `--issue`.

- [ ] RST-6: Issue counts in the status line, and an Issues view
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

- [ ] RST-7: Live test progress from the agent's own messages
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
