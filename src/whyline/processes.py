"""Process checks that are safe on Windows.

On Windows ``os.kill(pid, 0)`` is not a liveness probe: signal 0 is
``CTRL_C_EVENT``, so it sends Ctrl+C to the process group ``pid`` (or fails
when ``pid`` leads none). Callers keep their POSIX ``os.kill(pid, 0)`` and
ask :func:`windows_pid_alive` on Windows instead.
"""

from __future__ import annotations

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5


def windows_pid_alive(pid: int) -> bool:
    """True when a process with ``pid`` is still running (Windows only)."""
    import ctypes
    from ctypes import wintypes

    if pid <= 0:
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # It exists but belongs to someone we may not query.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)
