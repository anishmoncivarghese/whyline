<!-- whyline-plan v1 | source: moved | created: 2026-10-19T00:00:00+05:30 -->
# Windows as a release gate again

Moved on 2026-10-19 from `plans/in-the-agent-i-can-select-the-agent-in-c.plan.md` after whyline 0.3.45 shipped, so that plan could close. Run it whenever Windows is worth gating on again.

Windows stopped being a release gate on 2026-10-15 after Windows-only test failures blocked three v0.3.42 release attempts. `ci.yml` still runs it on every push with `continue-on-error`, and `release.yml` does not run it.

- [ ] WIN-1: Make the suite pass on Windows and make Windows a release gate again
  Edit only tests and source files that a Windows failure points at, plus `.github/workflows/ci.yml` and `.github/workflows/release.yml`.
  Start from the latest `ci` run on this branch: list every failing test in the `windows-latest` jobs, for Python 3.11 and 3.13, across at least three runs (re-run the Windows jobs to separate intermittent failures from consistent ones). Known causes so far, all fixed only where noted: a `pilot.pause()` after a button that calls `app.exit()` (fixed in `tests/console/test_tui_relay_run.py`); `os.replace` and `unlink` on a file another thread has open (fixed in `whyline.state` for JSON state and the Auto lock); UI waits shorter than a slow runner needs. Still failing on Windows at 0.3.43: `tests/console/test_see_files.py::test_gather_follow_detects_real_changes_and_ledger_hints` reads `\r\n` where the test expects `\n` (decide whether the Files pane should normalise line endings or the test should compare with them); `tests/console/test_drop_attachments.py::test_dropping_two_files_asks_then_attaches` intermittently finds no `#confirm` on `ConfirmScreen` (Python 3.11). Fix each by its cause: wait on the real condition, never a longer sleep, and never skip a test on Windows unless the feature itself is macOS-only (launchd, Mail.app), in which case skip with that reason.
  When three consecutive `windows-latest` runs pass on both Python versions, remove `continue-on-error` from `ci.yml`, add `windows-latest` back to `release.yml`'s matrix, and delete the comments that point at this task.
  Verify with three green `ci` runs including Windows, and `uv run pytest -q`. Change nothing else.

