<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-10-31T21:00:00+05:30 -->
# Relay status line: stage, reruns, plan progress and a per-turn timer, plus a selectable Copy view

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Starts after `plans/job-search-4-pdf-workday-bulk.plan.md` is complete, since both change the console. Best after whyline-relay ships RLY-11 (`stage` and `visit` in `.whyline/relay/running.json`), but every task here also works with the current relay. Without RLY-11, rerun counts are just not shown.

What the user gets:
- **Today:** `relay: JOB-24, claude… 5945s`. The seconds count from when the console started the relay, not from the current turn.
- **First pass:** `relay: JOB-24 (2 of 10, 10%) · implementing · claude · round 1 of 24 · 7m 02s`
- **After a rejection:** `relay: JOB-24 (2 of 10, 10%) · fixing after review 1 · claude · round 3 of 24 · 1m 40s`, then `… · re-review 2 · codex · round 4 of 24 · 0m 35s`.
- **Copy** opens the transcript in a view where you can select just part of it. Copying everything stays one click.
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
