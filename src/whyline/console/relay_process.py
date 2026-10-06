"""Runs `whyline relay start|resume` as its own process for the console.
Output goes to a log file, not a pipe, and a thread follows that file: once
the console quits there is no reader left, and a relay writing to a closed
pipe would die of it. The process also gets its own session / process group,
so closing the terminal doesn't take it down."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

_RELAY_MAIN = (
    "import sys; from whyline_relay.cli import main; "
    "sys.exit(main(sys.argv[1:], prog='whyline relay'))"
)


def log_path(root: Path) -> Path:
    return root / ".whyline" / "relay" / "logs" / "console-run.log"


def stop_path(root: Path) -> Path:
    return root / ".whyline" / "relay" / "STOP"


def relay_argv(args: list[str], root: Path) -> list[str]:
    return [sys.executable, "-c", _RELAY_MAIN, *args, "--repo", str(root)]


class RelayProcess:
    def __init__(
        self,
        root: Path,
        args: list[str],
        *,
        on_line,
        on_exit,
        argv: list[str] | None = None,
        poll: float = 0.1,
    ) -> None:
        self.root = root
        self.args = args
        self._argv = argv if argv is not None else relay_argv(args, root)
        self._on_line = on_line
        self._on_exit = on_exit
        self._poll = poll
        self._proc: subprocess.Popen | None = None
        self._following = True

    def start(self) -> None:
        path = log_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        if os.name == "nt":
            group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            group = {"start_new_session": True}
        with path.open("w", encoding="utf-8") as log:
            self._proc = subprocess.Popen(
                self._argv,
                cwd=self.root,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                **group,
            )
        threading.Thread(target=self._follow, args=(path,), daemon=True).start()

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def wait(self, timeout: float | None = None) -> int:
        if self._proc is None:
            raise RuntimeError("Process not started")
        return self._proc.wait(timeout)

    def request_stop(self) -> None:
        """The relay checks for this file between agent turns: the current
        agent finishes, nothing new starts, and the run pauses cleanly."""
        target = stop_path(self.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")

    def interrupt(self) -> None:
        """Stops the relay now, like Ctrl+C: it ends the agent's turn and
        saves a paused state that Resume carries on from. Windows has no
        Ctrl+C for another process, so there it pauses after this turn."""
        if not self.running():
            return
        if os.name == "nt":
            self.request_stop()
        else:
            self._proc.send_signal(signal.SIGINT)

    def stop_following(self) -> None:
        """Stops reporting (the console is quitting); the relay keeps going."""
        self._following = False

    def _follow(self, path: Path) -> None:
        collected: list[str] = []
        pending = ""
        with path.open(encoding="utf-8", errors="replace") as reader:
            while self._following:
                chunk = reader.readline()
                if chunk:
                    pending += chunk
                    if pending.endswith("\n"):
                        line = pending.rstrip("\r\n")
                        collected.append(line)
                        self._on_line(line)
                        pending = ""
                    continue
                if self._proc is not None and self._proc.poll() is not None:
                    rest = reader.read()
                    for line in (pending + rest).splitlines():
                        collected.append(line)
                        self._on_line(line)
                    self._on_exit(self._proc.returncode, "\n".join(collected) + "\n")
                    return
                time.sleep(self._poll)
