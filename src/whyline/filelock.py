"""Exclusive file locks that work on macOS, Linux and Windows.

POSIX uses ``fcntl.flock``; Windows uses ``msvcrt.locking`` on the first byte.
Either way the lock belongs to the open file, so another open of the same path,
in this process or another, cannot take it until it is released or closed.
"""

from __future__ import annotations

import os
import time
from typing import IO

_WINDOWS = os.name == "nt"
_RETRY_SECONDS = 0.05


def lock(handle: IO, *, blocking: bool = True) -> bool:
    """Take an exclusive lock on ``handle``. Returns False only when
    ``blocking`` is False and someone else holds it."""
    if _WINDOWS:
        import msvcrt

        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                if not blocking:
                    return False
                time.sleep(_RETRY_SECONDS)
    import fcntl

    flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
    try:
        fcntl.flock(handle.fileno(), flags)
    except BlockingIOError:
        return False
    return True


def unlock(handle: IO) -> None:
    """Release a lock taken with :func:`lock`. Closing the file also releases it."""
    if _WINDOWS:
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
