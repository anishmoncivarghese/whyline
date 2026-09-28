# Windows Compatibility Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four distinct root causes behind the five test failures Windows CI surfaced on its first run -- a real, unlocked-writer race in `state.py`'s file lock, 71 test fixtures missing an explicit text encoding, a path-separator bug in `hook_entry.py`, and a permission-simulation test that only works on POSIX.

**Architecture:** `state.py`'s `file_lock()` gets a portable, stdlib-only implementation using exclusive file creation (`os.open` with `O_CREAT | O_EXCL`) instead of `fcntl`-or-nothing. Every `.write_text`/`.read_text` call found missing `encoding="utf-8"` gets it added. `hook_entry.py`'s `_relative()` returns `.as_posix()`. One test is redesigned to simulate a write failure in a platform-independent way.

**Tech Stack:** Python 3.11+, stdlib only. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-29-windows-compatibility-fixes-design.md`

## Global Constraints

- No new runtime dependency -- the lock fix uses only `os.open`/`os.close`/`Path.unlink`, all stdlib.
- Each task's own job stops at implementing, testing locally, committing, and handing off -- never attempt `git push`/checking GitHub Actions results yourselves. Your own sandboxed environment may not have outbound network access to github.com at all (confirmed on WFX-3: a DNS resolution failure inside the sandbox, not a real outage -- pushing the identical branch succeeded immediately from outside it). Real Windows CI verification against every fix in this plan is the orchestrator's own job, done once the whole plan completes, not each agent's.
- `encoding="utf-8"` is added to every occurrence found missing it (Task 2's own list); no new occurrence should be introduced by any other task's own new code.
- Every existing test in this repo must still pass after every task.

**Note on this pairing:** Antigravity implements, Codex reviews -- the same pairing that completed console foundation, relay lifecycle views, and the mouse TUI cleanly in this repo.

---

### Task 1: Portable file lock (WFX1)

**Files:**
- Modify: `src/whyline/state.py`
- Test: `tests/test_state_lock.py` (new file)

**Interfaces:**
- Produces: `file_lock(path)` (unchanged public signature and context-manager behavior) now implemented via two new private helpers, `_acquire_lock(lock_path: Path, timeout: float = 10.0) -> None` and `_release_lock(lock_path: Path) -> None`, both stdlib-only and portable across POSIX and Windows.

- [ ] **Step 1: Read `state.py` fresh**

Read the whole file (it's short) before changing anything -- confirm
`file_lock`'s current body matches what's shown below.

```python
@contextmanager
def file_lock(path: Path):
    """Serialize a checkout-local read/modify/write cycle on macOS and Linux."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows remains unverified
        yield
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_state_lock.py`:

```python
import os
import time
from pathlib import Path

import pytest

from whyline import state


def test_acquire_then_release_allows_a_second_acquire(tmp_path: Path):
    lock_path = tmp_path / "x.lock"
    state._acquire_lock(lock_path)
    state._release_lock(lock_path)
    # Must not raise or block -- the lock file is gone after release.
    state._acquire_lock(lock_path)
    state._release_lock(lock_path)


def test_a_held_lock_blocks_a_second_acquire_until_timeout(tmp_path: Path):
    lock_path = tmp_path / "x.lock"
    state._acquire_lock(lock_path)
    try:
        with pytest.raises(TimeoutError, match=str(lock_path)):
            state._acquire_lock(lock_path, timeout=0.3)
    finally:
        state._release_lock(lock_path)


def test_a_stale_lock_is_cleared_and_reacquired(tmp_path: Path):
    lock_path = tmp_path / "x.lock"
    lock_path.write_text("", encoding="utf-8")
    # Force the lock file's mtime far enough into the past to look abandoned.
    old = time.time() - 3600
    os.utime(lock_path, (old, old))
    # Must succeed quickly -- the stale lock is cleared, not waited out.
    started = time.monotonic()
    state._acquire_lock(lock_path, timeout=5.0)
    elapsed = time.monotonic() - started
    state._release_lock(lock_path)
    assert elapsed < 2.0


def test_release_of_an_already_missing_lock_does_not_raise(tmp_path: Path):
    lock_path = tmp_path / "never-created.lock"
    state._release_lock(lock_path)  # must not raise


def test_file_lock_context_manager_still_works(tmp_path: Path):
    target = tmp_path / "some-state.json"
    with state.file_lock(target):
        target.write_text("{}", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "{}"
    # The lock file itself must not be left behind after a clean exit.
    assert not target.with_name(target.name + ".lock").exists()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_state_lock.py -v`
Expected: FAIL (`AttributeError: module 'state' has no attribute '_acquire_lock'`)

- [ ] **Step 4: Implement**

Replace `file_lock` in `src/whyline/state.py` with:

```python
_STALE_LOCK_SECONDS = 10.0
_POLL_INTERVAL_SECONDS = 0.05


def _acquire_lock(lock_path: Path, timeout: float = 10.0) -> None:
    """Blocks until `lock_path` can be exclusively created, or raises
    TimeoutError. os.O_CREAT | os.O_EXCL is honored identically on POSIX
    and Windows -- no platform branch, no new dependency. A lock file
    older than _STALE_LOCK_SECONDS is treated as abandoned by a crashed
    process (this primitive, unlike fcntl.flock, does not auto-release on
    crash) and cleared before retrying."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue  # another process just released it -- retry immediately
            if age > _STALE_LOCK_SECONDS:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass  # another process already cleared it -- fine either way
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"could not acquire lock {lock_path} within {timeout}s"
                )
            time.sleep(_POLL_INTERVAL_SECONDS)


def _release_lock(lock_path: Path) -> None:
    lock_path.unlink(missing_ok=True)


@contextmanager
def file_lock(path: Path):
    """Serialize a checkout-local read/modify/write cycle, portably."""
    lock_path = path.with_name(path.name + ".lock")
    _acquire_lock(lock_path)
    try:
        yield
    finally:
        _release_lock(lock_path)
```

Add `import time` to the existing imports at the top of `state.py` (it
currently imports `json`, `os`, `tempfile`, `contextmanager`, `Path` --
`os` is already there, `time` is new).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_state_lock.py -v`
Expected: PASS

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS (including the pre-existing
`tests/test_ownership.py::test_concurrent_claims_do_not_overwrite_each_other`,
unmodified -- the fix is underneath it)

- [ ] **Step 7: Commit**

```bash
git add src/whyline/state.py tests/test_state_lock.py
git commit -m "fix: portable file lock using exclusive creation instead of fcntl"
```

---

### Task 2: Add missing `encoding="utf-8"` everywhere (WFX2)

**Files:**
- Modify: `tests/test_model.py`, `tests/test_sync.py`, `tests/test_claudemd.py`, `tests/test_init_relay.py`, `tests/test_handoff.py`, `tests/test_hooks.py`, `tests/test_gitq.py`, `tests/test_agentsmd.py`, `tests/test_account_cli.py`, `tests/test_cli.py`, `tests/test_account.py`, `tests/test_decisions.py`, `tests/test_ledger.py`, `tests/console/test_adapters_relay_structured.py`

**Interfaces:**
- Produces: no interface changes -- every listed call site gains an explicit `encoding="utf-8"` keyword argument, with no other behavior change.

- [ ] **Step 1: Fix every occurrence in this exact list**

This is the complete, verified list of every `.write_text(...)`/
`.read_text(...)` call in `src/` and `tests/` missing an explicit
`encoding=` keyword (confirmed by scanning each call's full span, not
just its opening line, so a multi-line call already specifying encoding
on a later line is correctly excluded). `src/` has none -- every
occurrence is in a test file. For each, add `encoding="utf-8"` as a
keyword argument: a bare `.read_text()` becomes
`.read_text(encoding="utf-8")`; a `.write_text(some_value)` becomes
`.write_text(some_value, encoding="utf-8")` (or, for an already
multi-line call, add `encoding="utf-8"` as one more argument on its own
line before the closing parenthesis, matching that call's existing
style).

```
tests/test_model.py:15
tests/test_model.py:21
tests/test_sync.py:39
tests/test_sync.py:143
tests/test_claudemd.py:7
tests/test_claudemd.py:14
tests/test_claudemd.py:16
tests/test_claudemd.py:26
tests/test_claudemd.py:32
tests/test_claudemd.py:34
tests/test_init_relay.py:143
tests/test_handoff.py:24
tests/test_hooks.py:11
tests/test_hooks.py:17
tests/test_hooks.py:33
tests/test_hooks.py:54
tests/test_hooks.py:66
tests/test_hooks.py:69
tests/test_hooks.py:75
tests/test_hooks.py:78
tests/test_hooks.py:84
tests/test_hooks.py:87
tests/test_hooks.py:95
tests/test_gitq.py:110
tests/test_gitq.py:111
tests/test_gitq.py:112
tests/test_agentsmd.py:7
tests/test_agentsmd.py:15
tests/test_agentsmd.py:17
tests/test_agentsmd.py:26
tests/test_account_cli.py:30
tests/test_cli.py:222
tests/test_cli.py:234
tests/test_cli.py:238
tests/test_cli.py:245
tests/test_cli.py:247
tests/test_cli.py:254
tests/test_cli.py:255
tests/test_cli.py:258
tests/test_cli.py:259
tests/test_cli.py:264
tests/test_cli.py:265
tests/test_cli.py:271
tests/test_cli.py:272
tests/test_cli.py:274
tests/test_cli.py:275
tests/test_cli.py:618
tests/test_cli.py:634
tests/test_cli.py:751
tests/test_cli.py:788
tests/test_cli.py:824
tests/test_cli.py:850
tests/test_cli.py:868
tests/test_cli.py:931
tests/test_cli.py:949
tests/test_cli.py:979
tests/test_account.py:23
tests/test_account.py:31
tests/test_account.py:38
tests/test_account.py:50
tests/test_account.py:66
tests/test_account.py:179
tests/test_account.py:202
tests/test_decisions.py:37
tests/test_decisions.py:48
tests/test_decisions.py:80
tests/test_decisions.py:94
tests/test_ledger.py:13
tests/test_ledger.py:19
tests/console/test_adapters_relay_structured.py:13
tests/console/test_adapters_relay_structured.py:183
```

Line numbers are accurate as of this plan's writing on `main` -- if a
file has drifted since (another task landed first), find each call by
the pattern (`.write_text(` or `.read_text(` with no `encoding=` anywhere
in that call's own parentheses) rather than trusting the line number
blindly once it's off by more than a line or two.

- [ ] **Step 2: Verify nothing was missed or double-handled**

Run this check -- it must print nothing (no output means no remaining
occurrences):

```bash
python3 -c "
import re
from pathlib import Path

pattern = re.compile(r'\.(write_text|read_text)\(')
for path in list(Path('src').rglob('*.py')) + list(Path('tests').rglob('*.py')):
    text = path.read_text(encoding='utf-8')
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for m in pattern.finditer(line):
            depth = 0
            buf = []
            k = i
            rem = line[m.end()-1:]
            while True:
                for ch in rem:
                    if ch == '(':
                        depth += 1
                    elif ch == ')':
                        depth -= 1
                    buf.append(ch)
                    if depth == 0:
                        break
                if depth == 0:
                    break
                k += 1
                if k >= len(lines):
                    break
                rem = lines[k]
                buf.append('\n')
            if 'encoding=' not in ''.join(buf):
                print(f'{path}:{i+1}')
"
```

- [ ] **Step 3: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "fix: add explicit encoding=\"utf-8\" to every text read/write missing it"
```

---

### Task 3: Forward-slash-consistent paths in `hook_entry.py` (WFX3)

**Files:**
- Modify: `src/whyline/hook_entry.py`
- Test: `tests/test_hook_entry.py`

**Interfaces:**
- Produces: `_relative(root, raw)` returns a forward-slash path string on every platform (unchanged return type, `str | None`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_hook_entry.py`:

```python
def test_relative_returns_forward_slashes_for_a_nested_path(tmp_path):
    from whyline.hook_entry import _relative

    nested = tmp_path / "src" / "pkg" / "mod.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("x", encoding="utf-8")
    result = _relative(tmp_path, str(nested))
    assert result == "src/pkg/mod.py"
    assert "\\" not in result
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_hook_entry.py -k forward_slashes -v`
Expected: PASS on macOS/Linux (native separator is already `/`), but this
specific defect only reproduces on Windows -- this test's real value is
being part of the suite the Windows CI job runs. If you're implementing
on macOS/Linux, this step won't show a local failure; proceed to Step 3
anyway, since the existing `test_codex_apply_patch_records_each_in_repo_path`
is the test that actually caught this bug on Windows CI and is the one
that matters here.

- [ ] **Step 3: Implement**

In `src/whyline/hook_entry.py`, find `_relative`:

```python
def _relative(root: Path, raw: str) -> str | None:
    try:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / candidate
        return str(candidate.resolve().relative_to(root.resolve()))
    except (ValueError, OSError):
        return None
```

Change the return line:

```python
def _relative(root: Path, raw: str) -> str | None:
    try:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / candidate
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_hook_entry.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/whyline/hook_entry.py tests/test_hook_entry.py
git commit -m "fix: hook_entry._relative returns forward-slash paths on every platform"
```

---

### Task 4: Cross-platform permission-simulation test (WFX4)

**Files:**
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: no interface changes -- one existing test's *setup* changes; its assertions and intent are unchanged.

- [ ] **Step 1: Read the current test fresh**

Read `test_note_reports_cleanly_when_decisions_md_cannot_be_written` in
`tests/test_cli.py` (starts at line 888) -- its exact current body, in
full, is:

```python
def test_note_reports_cleanly_when_decisions_md_cannot_be_written(repo, capsys):
    """2026-08-18: note raised a raw traceback when storage was unwritable, and
    because the ledger was written first, a failure on decisions.md left the note
    in the local ledger only — brief and status showed it while a clone never
    would. The stores diverged silently."""
    import os

    from whyline import ledger

    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    directory = paths.whyline_dir(repo.path)
    os.chmod(directory, 0o500)
    try:
        code, out, err = run_in_both(repo, ["note", "cannot store this"], capsys)
    finally:
        os.chmod(directory, 0o755)

    assert code == cli.EXIT_ERROR
    assert "Traceback" not in err
    assert "Nothing was recorded" in out + err
    # And crucially: the ledger must not hold what the committed record lacks.
    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert [e for e in found if e.get("type") == events.NOTE] == []
```

- [ ] **Step 2: Replace the permission simulation**

Replace the whole function body with:

```python
def test_note_reports_cleanly_when_decisions_md_cannot_be_written(repo, capsys):
    """2026-08-18: note raised a raw traceback when storage was unwritable, and
    because the ledger was written first, a failure on decisions.md left the note
    in the local ledger only — brief and status showed it while a clone never
    would. The stores diverged silently."""
    from whyline import ledger

    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    # Writing text to a path that is actually a directory fails consistently
    # on every platform, with no OS-specific permission semantics involved --
    # os.chmod's effect on Windows doesn't restrict writes the way it does
    # on POSIX, so this simulates "cannot write" portably instead.
    paths.decisions_path(repo.path).mkdir(parents=True, exist_ok=True)
    try:
        code, out, err = run_in_both(repo, ["note", "cannot store this"], capsys)
    finally:
        paths.decisions_path(repo.path).rmdir()

    assert code == cli.EXIT_ERROR
    assert "Traceback" not in err
    assert "Nothing was recorded" in out + err
    # And crucially: the ledger must not hold what the committed record lacks.
    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert [e for e in found if e.get("type") == events.NOTE] == []
```

Note `import os` is removed -- it was only ever used for the two
`os.chmod` calls this replaces, and nothing else in this function needs
it.

- [ ] **Step 3: Run the test to verify it still passes with the new setup**

Run: `uv run pytest tests/test_cli.py -k test_note_reports_cleanly_when_decisions_md_cannot_be_written -v`
Expected: PASS

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli.py
git commit -m "fix: simulate an unwritable decisions.md portably, not via POSIX chmod"
```

---

## Final check

After Task 4's commit, push to `main` and read the *actual* Windows CI
job's result -- all five originally-failing tests
(`test_concurrent_claims_do_not_overwrite_each_other`,
`test_parse_entries_yields_empty_values_for_missing_sections`,
`test_parse_entries_tolerates_unexpected_prose_between_entries`,
`test_codex_apply_patch_records_each_in_repo_path`,
`test_note_reports_cleanly_when_decisions_md_cannot_be_written`) must now
pass on `windows-latest` for both Python 3.11 and 3.13, not just locally
on macOS/Linux. This sub-project's own standard (verified, not assumed)
applies to its own fixes too.
