import subprocess
import sys
import types

import pytest

from whyline import filelock


def test_second_open_cannot_take_a_held_lock(tmp_path):
    path = tmp_path / "x.lock"
    with open(path, "a+") as first, open(path, "a+") as second:
        assert filelock.lock(first, blocking=False)
        assert not filelock.lock(second, blocking=False)
        filelock.unlock(first)
        assert filelock.lock(second, blocking=False)
        filelock.unlock(second)


def test_closing_releases_the_lock(tmp_path):
    path = tmp_path / "x.lock"
    first = open(path, "a+")
    assert filelock.lock(first)
    first.close()
    with open(path, "a+") as second:
        assert filelock.lock(second, blocking=False)


@pytest.mark.parametrize(
    "module", ["whyline.filelock", "whyline.ideas.worker", "whyline.sdlc.guard"]
)
def test_imports_without_fcntl(module):
    # Windows has no fcntl; v0.3.77 CI failed to collect 10 test files there.
    code = f"import sys; sys.modules['fcntl'] = None; import {module}"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_windows_path_uses_msvcrt(monkeypatch, tmp_path):
    held = set()
    calls = []

    def locking(fd, mode, nbytes):
        calls.append(mode)
        if mode == fake.LK_NBLCK:
            if held:
                raise OSError("locked")
            held.add(fd)
        elif mode == fake.LK_UNLCK:
            held.discard(fd)

    fake = types.SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0, locking=locking)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(filelock, "_WINDOWS", True)
    with open(tmp_path / "x.lock", "a+") as first, open(tmp_path / "x.lock", "a+") as second:
        assert filelock.lock(first, blocking=False)
        assert not filelock.lock(second, blocking=False)
        filelock.unlock(first)
        assert filelock.lock(second)
    assert calls == [2, 2, 0, 2]
