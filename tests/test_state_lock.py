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
