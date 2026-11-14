<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-assistant-2-design.md | created: 2026-11-14T16:30:00+05:30 -->
# Assistant memory: daily notes, a nightly tidy-up and recall

Spec: `docs/superpowers/specs/2026-11-14-assistant-2-design.md`, Part 3. Read it before every task. Where this plan and the spec differ, this plan wins.

Runs after `plans/assistant-router.plan.md`. It uses the router's turns (`ideas/turn.py`) and routing rows.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: memory is one list of 100 lines the user fills by hand with `remember` (`ideas/memory.py`). Nothing the assistant did yesterday can be found today.

What the user gets:
- A daily note file the assistant writes itself: what was asked and how it ended.
- A nightly card proposing up to 5 facts to keep and up to 3 to drop. Nothing enters memory without a tap.
- `recall <words>` in Telegram and a search box in the console, over notes and memory.

Rules every task keeps:
- **Console first.** Every setting, list and action has a console counterpart saving through the same function as its `whyline idea …` command.
- **Nothing enters memory without a tap.** The tidy-up only proposes.
- **Notes hold no forwarded mail bodies, no document text and no secrets.** A note line is written by code from the request's own fields, passed through `security.secrets.scan_text` with matches replaced by `•••`, and cut to 200 characters.
- **Private files:** `~/.whyline/ideas/notes/` is 0700 and each file 0600, never in a repository.
- **Notes and memory are data** when they go into a prompt, inside a block labelled as data, as `memory.for_prompt` does.
- **No new dependency.** Search is SQLite FTS5 from Python's own sqlite3.
- **Tests:** never invoke a real provider or Telegram, use temporary folders and an injected clock, never sleep, keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A secret-looking value in a request never reaches a note file. MEM-1, `test_note_line_is_redacted`.
- A tidy-up proposal changes memory only after Keep or Drop is tapped. MEM-3, `test_tidy_changes_nothing_before_a_tap`.
- Recall text with FTS operators or quotes never raises and never matches everything. MEM-2, `test_recall_query_is_escaped`.
- A prompt never gets more than 40 memory lines. MEM-4, `test_prompt_memory_is_capped`.
- Notes older than the keep period are deleted, and today's are never deleted. MEM-1, `test_old_notes_are_trimmed`.

- [ ] MEM-1: Daily notes
  Create `src/whyline/ideas/notes.py` and `tests/ideas/test_notes.py`. Edit `src/whyline/ideas/turn.py`, `src/whyline/ideas/worker.py` and their tests.
  1. `notes.folder() -> Path` (`paths.home() / "notes"`), `notes.path(day: date) -> Path` (`YYYY-MM-DD.md`).
  2. `notes.add(day, at: datetime, asked: str, route: str, outcome: str) -> None` appends `- HH:MM · <route> · <asked> → <outcome>`. `asked` is the message's first line. Both texts are redacted and cut as the rules say.
  3. `notes.read(day) -> list[str]`, `notes.days() -> list[date]` (newest first), `notes.remove_line(day, n)`.
  4. `notes.trim(today, keep_days: int) -> int` deletes files older than `keep_days` (kv `notes_keep_days`, default 180, 0 keeps everything).
  5. `turn.run` calls `notes.add` when a turn ends, with the outcome `done`, `asked what to do`, `saved as idea`, `waiting for a tap` or `failed: <reason>`. A finished request (`requests.finish`) adds a line the same way from the worker. A `summarise` request's note says `summarised a forwarded message` and never includes its text.
  6. The worker calls `notes.trim` once a day.
  Tests: `test_note_line_is_redacted`, `test_old_notes_are_trimmed`, file and folder modes, one line per turn, the summarise wording, and `remove_line`.

- [ ] MEM-2: Search over notes and memory
  Create `src/whyline/ideas/recall.py` and `tests/ideas/test_recall.py`. Edit `src/whyline/ideas/store.py` (schema), `src/whyline/ideas/notes.py`, `src/whyline/ideas/memory.py` and their tests.
  1. An FTS5 table `recall_index(source, ref, text)` as the next schema version. `source` is `note` or `memory`. `ref` is `YYYY-MM-DD:<line>` or the memory line number.
  2. `recall.reindex(conn)` rebuilds it from the note files and memory. `notes.add`, `notes.remove_line`, `memory.add`, `memory.edit`, `memory.forget` and `memory.clear` update it. A failure to index never fails the write.
  3. `recall.search(conn, words: str, limit=10) -> list[Hit]` (`source`, `ref`, `text`). Each word is quoted as a literal, so operators and punctuation in the user's text are never read as FTS syntax. An empty query returns nothing.
  4. When FTS5 is not available in this sqlite3, `search` falls back to a case-insensitive substring match over the same rows.
  Tests: `test_recall_query_is_escaped` (`"`, `*`, `OR`, `NEAR(`, a lone `-`), hits from notes and from memory, the index follows an add and a forget, the fallback path, and `reindex` after files changed on disk.

- [ ] MEM-3: Nightly tidy-up
  Create `src/whyline/ideas/tidy.py` and `tests/ideas/test_tidy.py`. Edit `src/whyline/ideas/worker.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/intent.py` and their tests.
  1. `tidy.propose(conn, day, *, run_fn=None) -> Tidy | None`.
     - One read-only turn on the assistant's main then backup agent (`router.order`), 120 seconds, given the day's notes and the current memory as data.
     - It asks for a JSON block: `keep` (at most 5 new facts, each at most 300 characters) and `drop` (at most 3 existing memory line numbers).
     - Anything over the limits is cut, a fact equal to an existing line is removed, and a drop number that doesn't exist is removed.
     - None when there are no notes for the day, when nothing is proposed, or when no agent answered.
  2. The proposal is stored (kv `tidy:<day>`) and sent as one card: each fact as a line with **Keep** and **Skip**, each drop as the existing line with **Drop** and **Leave**. Each button carries a `confirm.issue` code.
  3. A tap applies that one line through `memory.add` or `memory.forget` and edits the card to show it as handled. Drops are applied by matching the line's text, not its number, so an earlier drop can't shift a later one. A stale tap answers `This card is out of date.`
  4. The worker runs the tidy once a day at kv `tidy_at` (default `21:30`, empty turns it off), for today's notes. A day is never proposed twice.
  Tests: `test_tidy_changes_nothing_before_a_tap`, the limits, duplicates removed, Keep adds and Drop forgets the right line after another drop, memory full shows `memory.MEMORY_FULL` on that line, no card on an empty day, and once per day.

- [ ] MEM-4: Recall in Telegram and in the router
  Edit `src/whyline/ideas/intent.py`, `src/whyline/ideas/actions.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/router.py`, `src/whyline/ideas/memory.py` and their tests.
  1. A `recall` command and action (`writes=False`, approval `none`): `recall <words>` replies with up to 10 hits, each `<date or "memory"> · <text>`, or `Nothing found for "<words>".`
  2. `memory.MAX_LINES` rises to 300. `memory.for_prompt(match: str = "")` returns at most 40 lines: the lines `recall.search` matches for `match` first, then the most recently added.
  3. `router.decide` passes the message text as `match`, and adds up to 3 note hits to the prompt as data.
  Tests: `test_prompt_memory_is_capped` (300 lines stored, 40 in the prompt, matched lines first), the recall replies, and the router prompt holds the note hits inside a data block.

- [ ] MEM-5: Notes and tidy-up in the console and CLI
  Edit `src/whyline/ideas/cli.py`, `src/whyline/console/assistant_screen.py` and their tests.
  1. CLI:
     - `whyline idea notes [YYYY-MM-DD]` prints a day (today by default). `whyline idea notes days` lists days.
     - `whyline idea recall <words>` prints hits.
     - `whyline idea tidy` runs the tidy-up now and prints the proposal. `whyline idea tidy at <HH:MM|off>` saves the time.
     - `whyline idea notes keep <days>` saves the keep period.
  2. Assistant screen: a **Notes** section with a day list, the day's lines, **Delete line**, a search box showing `recall.search` hits, the tidy-up time, **Tidy now**, and the keep period. Each saves through the function its command calls.
  Tests: CLI and console call the same functions, a bad time or a negative keep period is refused, and **Tidy now** with no notes says `Nothing to tidy today.`

- [ ] MEM-6: Docs
  Edit `docs/assistant.md` and `README.md` only.
  Cover: what a note holds and what it never holds, where the files are, the nightly card, `recall`, the 300-line memory with 40 in a prompt, and the keep period.
  Verify with `uv run pytest -q`.
