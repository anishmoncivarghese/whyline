"""Small helpers for atomically replaced checkout-local JSON state."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def load_object(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


# Windows reports creating a file whose deletion is still pending as
# PermissionError rather than FileExistsError -- the instant right after
# another thread or process released the lock. There it means "busy".
_WINDOWS = os.name == "nt"

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
        except PermissionError:
            if not _WINDOWS:
                raise
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"could not acquire lock {lock_path} within {timeout}s"
                )
            time.sleep(_POLL_INTERVAL_SECONDS)
            continue
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
