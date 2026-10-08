"""Email through the Mail app (deliveries spec 6). Recipients, subject, body
and attachment paths go to osascript as arguments, never into the script
text, so no address or subject can change what the script does."""
from __future__ import annotations

import platform
import subprocess
from pathlib import Path

SCRIPT = """on run argv
	set subj to item 1 of argv
	set body to item 2 of argv
	set n to (item 3 of argv) as integer
	tell application "Mail"
		if (count of accounts) is 0 then error "whyline: no Mail account" number 9001
		set m to make new outgoing message with properties {subject:subj, content:body & return & return, visible:false}
		tell m
			repeat with i from 4 to (3 + n)
				make new to recipient at end of to recipients with properties {address:(item i of argv)}
			end repeat
			repeat with i from (4 + n) to (count of argv)
				make new attachment with properties {file name:(POSIX file (item i of argv))} at after the last paragraph of content
			end repeat
		end tell
		delay 3
		send m
	end tell
end run
"""


class MailError(RuntimeError):
    pass


def _explain(stderr: str) -> str:
    if "-1743" in stderr:
        return ("allow whyline to control Mail in System Settings → "
                "Privacy & Security → Automation")
    if "9001" in stderr:
        return "Mail has no account set up"
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[0] if lines else "Mail couldn't send the message"


def send(to: list[str], subject: str, body: str, attachments: list[Path], *,
         run=subprocess.run, system=platform.system) -> None:
    if system() != "Darwin":
        raise MailError("email needs the Mail app on macOS")
    argv = ["osascript", "-", subject, body, str(len(to)), *to, *[str(p) for p in attachments]]
    try:
        result = run(argv, input=SCRIPT, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MailError(f"Mail couldn't be reached: {error}") from error
    if result.returncode != 0:
        raise MailError(_explain(result.stderr or ""))
