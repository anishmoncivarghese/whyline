"""macOS-only ways to bring files in: the Finder picker and a screenshot on
the clipboard, both through the built-in osascript. Paths reach AppleScript
as `on run argv` arguments, never spliced into the script text."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_PICK = """
set fs to choose file with multiple selections allowed
set out to ""
repeat with f in fs
  set out to out & POSIX path of f & linefeed
end repeat
return out
"""

_PASTE = """
on run argv
  set target to POSIX file (item 1 of argv)
  set f to open for access target with write permission
  try
    set eof f to 0
    write (the clipboard as «class PNGf») to f
    close access f
  on error message
    close access f
    error message
  end try
end run
"""


class PickerError(RuntimeError):
    pass


def available() -> bool:
    return sys.platform == "darwin" and shutil.which("osascript") is not None


def pick_files(run=subprocess.run) -> list[Path]:
    result = run(["osascript", "-e", _PICK], capture_output=True, text=True)
    if result.returncode != 0:
        if "-128" in (result.stderr or "") or "User canceled" in (result.stderr or ""):
            return []
        raise PickerError((result.stderr or "the file picker failed").strip())
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def paste_image(target: Path, run=subprocess.run) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    result = run(["osascript", "-e", _PASTE, str(target)], capture_output=True, text=True)
    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        return False
    return True
