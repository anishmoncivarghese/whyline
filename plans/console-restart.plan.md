<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-13T18:10:00+05:30 -->
# Console restart notice, crash log and a patient Ready check

Runs after `plans/agent-tools.plan.md`, and before `plans/release-notes-review.plan.md`. No separate design: the problem and the decisions are below.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: on 2026-11-13 a console started on 2026-11-12 before whyline 0.3.72 was installed kept running 0.3.71 in memory, and crashed on a bug 0.3.72 had already fixed (a `gh` timeout message shown as markup). Nothing told the user the console was out of date, the crash left only a long traceback in the terminal, and the Ready check that failed was a single 30-second `gh auth status` timeout that answered in 0.6 seconds a minute later.

What the user gets:
- When the whyline installed on disk is newer than the running console, the title says `whyline 0.3.73 is installed · restart to use it` and the existing **Restart** button appears. It is checked every 5 minutes and right after a release of whyline itself finishes.
- When the console crashes, the error is saved to `~/.whyline/crash.log` and the terminal shows one short message saying where. **Help** and `whyline doctor` show the last crash.
- A slow `gh` or git reply in the Ready check is tried once more before it counts as not ready.

There is no publish task. When the relay finishes, press **Release**.

Rules every task keeps:
- Console first: every console action calls the same function as its CLI command.
- No new dependency. Tests use temporary folders and fakes, never the network, a real `gh` or a real crash of the test process.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.

Review focus, each one pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- The installed version newer than the running one shows the notice; equal or older shows nothing. CRS-1, `test_notice_only_when_installed_is_newer`.
- Restart while a relay runs leaves the relay running and doesn't ask to pause it. CRS-1, `test_restart_leaves_relay_running`.
- A crash writes the log and the short message; the log keeps only the last 5 crashes. CRS-2, `test_crash_log_written_and_trimmed`.
- No secret reaches the crash log: values in the traceback's locals are not written. CRS-2, `test_crash_log_has_no_locals`.
- One `gh auth status` timeout, then success: the item is ready. Two timeouts: not ready, saying GitHub didn't answer. CRS-3, `test_ready_retries_a_timeout_once`.

- [ ] CRS-1: Notice when a newer whyline is installed
  Edit `src/whyline/console/update.py`, `src/whyline/console/tui.py` and their tests only.
  1. `update.installed_version() -> str | None`: the `whyline` version installed on disk now, read fresh each call (`importlib.invalidate_caches()`, then `importlib.metadata.version("whyline")`); None on any error.
  2. The console compares it with `whyline.__version__` (the running code) at start, every 5 minutes, and when a release step `after` finishes in a repository whose `pyproject.toml` project name is `whyline`. When the installed one is newer (`update._newer`), it sets the title to `whyline <installed> is installed · restart to use it`, shows the existing `#update-restart` button and writes one log line `whyline <installed> is installed; this console is <running>. Press Restart to use it.` once per version. It hides **Update…** for that version or older.
  3. **Restart** keeps its current behaviour (`_restart_console`, `update.RESTART`). While a relay runs in this checkout the quit safeguard is skipped for this exit: the relay keeps running and the restarted console finds it, as it does today after a quit with **Leave it running**.
  Tests: `test_notice_only_when_installed_is_newer` (newer, equal, older, None), the 5-minute timer and the release trigger with fakes, one log line per version, **Update…** hidden, and `test_restart_leaves_relay_running`.

- [ ] CRS-2: Crash log
  Create `src/whyline/console/crashlog.py` and `tests/console/test_crashlog.py`. Edit `src/whyline/console/tui.py` (`launch`), `src/whyline/doctor.py`, the console Help text and their tests.
  1. `crashlog.record(error: BaseException, *, version: str, path: Path | None = None) -> Path` appends `--- <ISO time> · whyline <version> · <type>: <message>` and the plain traceback (`traceback.format_exception`, no locals, at most 200 lines) to `~/.whyline/crash.log` (0600), keeping the last 5 entries. `crashlog.last(path=None) -> tuple[str, str] | None` returns the last entry's header and text.
  2. `launch` records a crash whether Textual raises it out of `app.run()` or returns with the error stored (in textual 2.1.2, `app._exception` with a nonzero `app.return_code`), then prints `The console crashed: <type>: <first line of message>. Details are saved in ~/.whyline/crash.log. Start it again with: whyline console`. Textual's own traceback is still printed above it. `KeyboardInterrupt` and a normal exit write nothing.
  3. `whyline doctor` adds a line `Last console crash: <time> · <type> (~/.whyline/crash.log)` when there is one in the last 7 days. The console **Help** shows the same line, with **Copy** copying that entry.
  Tests: `test_crash_log_written_and_trimmed`, `test_crash_log_has_no_locals` (a local named `token = "secret-value"` in the failing frame is not in the file), both Textual paths with a fake app, nothing written on Ctrl-C, file mode 0600, the doctor line, and the Help line.

- [ ] CRS-3: Ready check tries a slow reply once more
  Edit `src/whyline/release/ready.py` and its tests only.
  1. An item whose check raised `subprocess.TimeoutExpired`, or that hit the overall time limit (`not checked (time limit)`), is run once more, alone, with the same 30-second command timeout, before it is reported. A second timeout reports `<item>: GitHub didn't answer in time; press Check again` for `gh` items and `git didn't answer in time; press Check again` for git items.
  2. The retry happens inside `check`, so the console **Check**, the release's Check ready step and `whyline release check` all get it.
  Tests: `test_ready_retries_a_timeout_once`, a non-timeout failure not retried, the time-limit case, and the message for a git item.

- [ ] CRS-4: Docs
  Edit `README.md` and the `docs/` pages on the console and releasing.
  Cover: restarting after an upgrade and the notice, `~/.whyline/crash.log` and what to send when reporting a crash, `whyline doctor`'s crash line, and Ready retrying a slow reply.
  Verify with `uv run pytest -q`.
