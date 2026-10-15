import os
import re
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
        # match= is a regex, not a literal string -- a real path can contain
        # regex metacharacters (backslashes on Windows in particular, which
        # pytest.raises would otherwise try to interpret as escape
        # sequences, e.g. \U, and fail to even compile the pattern).
        with pytest.raises(TimeoutError, match=re.escape(str(lock_path))):
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


def test_a_lock_file_being_deleted_on_windows_counts_as_busy(tmp_path, monkeypatch):
    """Windows refuses to create a file whose deletion is still pending
    (PermissionError, not FileExistsError) -- the moment right after
    another thread released the lock. That is contention, not a failure:
    seen on CI as test_concurrent_claims_do_not_overwrite_each_other
    crashing on windows-latest."""
    import os

    from whyline import state

    real_open = os.open
    attempts = []

    def pending_delete_once(path, flags, *args):
        attempts.append(path)
        if len(attempts) == 1:
            raise PermissionError(13, "Permission denied", path)
        return real_open(path, flags, *args)

    monkeypatch.setattr(state, "_WINDOWS", True)
    monkeypatch.setattr(state.os, "open", pending_delete_once)
    with state.file_lock(tmp_path / "x.json"):
        pass
    assert len(attempts) == 2


def test_permission_errors_elsewhere_are_still_errors(tmp_path, monkeypatch):
    import os

    import pytest

    from whyline import state

    def denied(path, flags, *args):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(state, "_WINDOWS", False)
    monkeypatch.setattr(state.os, "open", denied)
    with pytest.raises(PermissionError):
        with state.file_lock(tmp_path / "x.json"):
            pass


def _flaky_replace(monkeypatch, failures: int) -> list[int]:
    """os.replace that is refused `failures` times, like Windows replacing a
    file another thread still has open."""
    calls = [0]
    real = os.replace

    def replace(src, dst):
        calls[0] += 1
        if calls[0] <= failures:
            raise PermissionError(5, "Access is denied")
        real(src, dst)

    monkeypatch.setattr(state.os, "replace", replace)
    monkeypatch.setattr(state, "_POLL_INTERVAL_SECONDS", 0.001)
    return calls


def test_atomic_write_retries_a_busy_target_on_windows(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(state, "_WINDOWS", True)
    calls = _flaky_replace(monkeypatch, failures=3)
    target = tmp_path / "auto-run.json"
    state.atomic_write_json(target, {"phase": "stopped"})
    assert calls[0] == 4
    assert state.load_object(target) == {"phase": "stopped"}
    assert [p.name for p in tmp_path.iterdir()] == ["auto-run.json"]


def test_atomic_write_gives_up_on_a_target_that_stays_busy(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(state, "_WINDOWS", True)
    _flaky_replace(monkeypatch, failures=10**9)
    target = tmp_path / "auto-run.json"
    with pytest.raises(PermissionError):
        state._replace(tmp_path / "missing.tmp", target, timeout=0.05)


def test_atomic_write_does_not_retry_off_windows(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(state, "_WINDOWS", False)
    calls = _flaky_replace(monkeypatch, failures=1)
    with pytest.raises(PermissionError):
        state.atomic_write_json(tmp_path / "auto-run.json", {"phase": "stopped"})
    assert calls[0] == 1
    assert list(tmp_path.iterdir()) == []
