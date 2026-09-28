# Windows Compatibility Fixes Design

**Status:** Approved by user, 2026-09-29.

## Goal

Fix the four distinct, concretely-diagnosed causes behind the five test
failures Windows CI surfaced on its very first run (added in sub-project
#5, packaging & release readiness) -- a real, previously-invisible
cross-platform gap, not a hypothetical one.

## Context

`ci.yml`/`release.yml` gained a `windows-latest` job on 2026-09-28. Its
first run failed 5 tests (both Python 3.11 and 3.13, identically):
`test_concurrent_claims_do_not_overwrite_each_other`,
`test_parse_entries_yields_empty_values_for_missing_sections`,
`test_parse_entries_tolerates_unexpected_prose_between_entries`,
`test_codex_apply_patch_records_each_in_repo_path`, and
`test_note_reports_cleanly_when_decisions_md_cannot_be_written`. Each was
read down to its root cause in the actual source before this spec was
written -- see Decisions below for exactly where.

## Non-goals

- **A general "make everything work on Windows" audit.** Scoped strictly
  to the four root causes these five specific failures revealed. A future
  Windows CI failure is its own future fix, not pre-empted here.
- **A new runtime dependency for file locking.** The fix uses only stdlib
  `os.open` with portable flags -- no `portalocker`/`filelock`-style
  addition, consistent with the base install's existing zero-dependency
  footprint.
- **Perfect crash-safety for the new lock primitive.** Stale-lock
  detection via a timeout is a reasonable, honest mitigation for this
  project's actual usage (short-lived, local, single-machine `whyline
  claim`/`release` operations) -- not a claim of distributed-systems-grade
  correctness.

## Decisions

- **WFX1 -- Replace the `fcntl`-or-nothing lock with a portable one using
  exclusive file creation.** `os.open(lock_path, os.O_CREAT | os.O_EXCL)`
  succeeds only when the lock file doesn't already exist and is honored
  identically by POSIX and Windows -- no platform branch, no new
  dependency. `state.py`'s current `file_lock()` (`try: import fcntl
  except ImportError: yield` -- silently no-locks on Windows) is why
  `test_concurrent_claims_do_not_overwrite_each_other` crashed with
  `PermissionError` on Windows rather than passing: two racing,
  *unlocked* writers collided on `os.replace()`, and Windows' stricter
  replace semantics surfaced that as a hard error. Includes stale-lock
  detection: a lock file older than a short timeout (10s) is treated as
  abandoned by a crashed process and cleared before retrying, since this
  primitive -- unlike `fcntl.flock` -- does not auto-release when a
  process dies.
- **WFX2 -- Add explicit `encoding="utf-8"` everywhere it's missing.**
  `tests/test_decisions.py`'s fixtures write text containing em-dashes via
  `path.write_text(...)` with no explicit encoding; Windows defaults to
  the locale's own encoding (cp1252) instead of UTF-8, turning the
  em-dash into byte `0x97`, which then fails a later strict UTF-8 read.
  This project's own prose uses em-dashes constantly, so this exact
  failure mode is not a one-off -- audit every `write_text`/`open`/
  `read_text` call across `src/` and `tests/` missing an explicit
  `encoding=` and add it.
- **WFX3 -- `hook_entry.py`'s `_relative()` returns `.as_posix()`, not
  `str(...)`.** Plain `str()` on a `Path` uses the OS-native separator;
  `.as_posix()` is the direct, one-line fix, producing forward-slash-
  consistent paths on every platform, matching how they're already used
  elsewhere (JSON records, git-relative paths).
- **WFX4 -- Redesign the permission-simulation test to be genuinely
  cross-platform, not skipped on Windows.** `os.chmod(dir, 0o500)`
  doesn't restrict write access on Windows the way it does on POSIX.
  Instead, make `decisions.md`'s own path a *directory* before running
  `note` -- writing text to a path that is actually a directory fails
  consistently on every platform, with no OS-specific permission
  semantics involved at all. This preserves real test coverage on
  Windows rather than trading it away for a `skipif`.

## Architecture

```
state.py
  file_lock(path)
    -> _acquire(lock_path, timeout=10)   (new, WFX1)
         loop: os.open(lock_path, O_CREAT|O_EXCL) -> success, return
               FileExistsError -> check lock file age
                 older than timeout -> remove it (stale), retry
                 else -> sleep briefly, retry until timeout raises TimeoutError
    -> _release(lock_path)               (new, WFX1)
         lock_path.unlink(missing_ok=True)

hook_entry.py
  _relative(root, raw) -> ... .as_posix()   (WFX3, one line)

tests/test_decisions.py, and any other write_text/open/read_text call
found missing encoding="utf-8" during the WFX2 audit
  -> encoding="utf-8" added explicitly

tests/test_cli.py
  test_note_reports_cleanly_when_decisions_md_cannot_be_written
    -> simulate failure via decisions.md being a directory, not chmod
```

## Error handling

- Lock acquisition timing out (WFX1) after the full timeout with no stale
  lock detected (a genuinely long-held, active lock): raises a clear
  `TimeoutError` naming the lock path -- never silently proceeds without
  the lock, which would reintroduce the exact race this fix closes.
- A lock file removed as stale by one process while a second process is
  also about to remove it: the second removal's `FileNotFoundError` is
  caught and ignored -- not treated as a fatal error, since the outcome
  (the stale lock is gone) is identical either way.
- The WFX2 audit finds a call that's intentionally binary (not text) --
  left alone; `encoding=` only applies to text-mode I/O, and this audit
  never touches binary-mode calls.

## Testing strategy

- WFX1: unit tests for the lock primitive directly -- two sequential
  acquisitions succeed; a lock file with its mtime forced into the past
  is detected as stale and cleared rather than blocking; a genuinely
  fresh, held lock blocks a second acquirer until released or until
  timeout raises `TimeoutError`. The existing
  `test_concurrent_claims_do_not_overwrite_each_other` should then pass
  on all three platforms unmodified -- the fix is underneath it, not in
  the test.
- WFX2: no new tests -- correctness verified by the existing
  `UnicodeDecodeError`-raising tests passing on Windows CI once fixed.
- WFX3: the existing `test_codex_apply_patch_records_each_in_repo_path`
  should pass on Windows unmodified; optionally add a direct unit test
  for `_relative()` asserting forward slashes regardless of platform.
- WFX4: the redesigned test itself is the verification -- written to fail
  before the directory-based simulation is in place and pass after, on
  all three platforms.
- End-to-end: push and read the actual Windows CI job's real result --
  this sub-project's own standard (verified, not assumed) applies to
  itself.
