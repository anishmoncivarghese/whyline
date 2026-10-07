"""The Mail.app recipe (spec section 6): a Mail rule runs this AppleScript,
which saves the message as text and calls `whyline agents trigger`."""
from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path

from whyline.agents import definitions

# Mail rules exist only on macOS. install() itself still writes the file, so
# the recipe test can run with HOME pointed at a temp directory on any OS.
NEEDS_MACOS = "Mail rules need macOS for now; agents still run with Run now."

# The message body is untrusted. It is written with AppleScript's file
# commands, not pasted into a shell heredoc: a body containing the heredoc's
# delimiter line would end the quoted heredoc and run the rest as shell.
_TEMPLATE = '''using terms from application "Mail"
  on perform mail action with messages theMessages for rule theRule
    repeat with m in theMessages
      set body to "From: " & (sender of m) & linefeed & "Subject: " & (subject of m) & linefeed & ¬
        "Date: " & ((date received of m) as string) & linefeed & linefeed & (content of m)
      set tmp to (do shell script "mktemp -t whyline-mail")
      set fd to open for access (POSIX file tmp) with write permission
      try
        set eof of fd to 0
        write body to fd as «class utf8»
        close access fd
      on error errMsg number errNum
        try
          close access fd
        end try
        error errMsg number errNum
      end try
      do shell script "WHYLINE_BIN --file " & quoted form of tmp & " >/dev/null 2>&1 &"
    end repeat
  end perform mail action with messages
end using terms from
'''


def supported() -> bool:
    """Mail.app rules are a macOS facility. Other systems keep Run now."""
    return sys.platform == "darwin"


def _whyline_path() -> str:
    found = shutil.which("whyline")
    if not found:
        raise RuntimeError("can't find the whyline command on PATH")
    return str(Path(found).resolve())


def _shell_token(value: str) -> str:
    """One POSIX shell word, escaped to sit inside an AppleScript string.

    ``shlex.quote`` is the shell syntax. A path with an apostrophe makes
    that syntax contain double quotes, and a backslash is an AppleScript
    escape, so both are escaped again before they join the ``do shell script``
    string.
    """
    return shlex.quote(value).replace("\\", "\\\\").replace('"', '\\"')


def script_text(agent_name: str, whyline_path: str) -> str:
    # The name becomes both a filename and an unquoted token in the shell
    # command. The definition grammar excludes separators and metacharacters.
    # The executable is whatever shutil.which returned, spaces included.
    if definitions.NAME.match(agent_name) is None:
        raise ValueError("name must be lower-case letters, digits and -, at most 40")
    command = f"{_shell_token(whyline_path)} agents trigger {agent_name}"
    return _TEMPLATE.replace("WHYLINE_BIN", command)


def install(agent_name: str) -> Path:
    text = script_text(agent_name, _whyline_path())
    folder = Path.home() / "Library" / "Application Scripts" / "com.apple.mail"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"whyline-{agent_name}.applescript"
    path.write_text(text, encoding="utf-8")
    return path
