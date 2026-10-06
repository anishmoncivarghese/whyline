import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.console import relay_process

SCRIPT = (
    "import sys, time\n"
    "for i in range(3):\n"
    "    print(f'line {i}', flush=True)\n"
    "    time.sleep(0.2)\n"
    "sys.stdout.write('no newline at the end')\n"
    "sys.exit(int(sys.argv[1]))\n"
)


def _run(tmp_path: Path, code: int = 0, follow: bool = True):
    lines, exits, done = [], [], threading.Event()

    def on_exit(exit_code, text):
        exits.append((exit_code, text))
        done.set()

    proc = relay_process.RelayProcess(
        tmp_path,
        ["start"],
        on_line=lines.append,
        on_exit=on_exit,
        argv=[sys.executable, "-c", SCRIPT, str(code)],
        poll=0.05,
    )
    proc.start()
    return proc, lines, exits, done


def test_lines_stream_in_order_before_exit(tmp_path):
    proc, lines, exits, done = _run(tmp_path)
    deadline = time.monotonic() + 10
    while not lines and time.monotonic() < deadline:
        time.sleep(0.02)
    assert lines[0] == "line 0"
    assert proc.running()  # it arrived while the process was still going
    assert done.wait(10)
    assert lines == ["line 0", "line 1", "line 2", "no newline at the end"]
    assert exits[0][0] == 0
    assert "line 2" in exits[0][1]


def test_nonzero_exit_is_reported(tmp_path):
    proc, lines, exits, done = _run(tmp_path, code=3)
    assert done.wait(10)
    assert exits[0][0] == 3


def test_output_goes_to_the_log_file_not_a_pipe(tmp_path):
    proc, lines, exits, done = _run(tmp_path)
    assert done.wait(10)
    assert "line 1" in relay_process.log_path(tmp_path).read_text()


def test_relay_keeps_running_after_the_console_stops_following(tmp_path):
    # The console quitting must not kill the relay (no broken pipe).
    proc, lines, exits, done = _run(tmp_path)
    proc.stop_following()
    assert proc.wait(10) == 0
    assert "no newline at the end" in relay_process.log_path(tmp_path).read_text()


def test_request_stop_writes_the_stop_file(tmp_path):
    proc, lines, exits, done = _run(tmp_path)
    proc.request_stop()
    assert relay_process.stop_path(tmp_path).exists()
    assert done.wait(10)


def test_relay_argv_runs_the_relay_cli_with_this_python(tmp_path):
    argv = relay_process.relay_argv(["start", "--only", "T3"], tmp_path)
    assert argv[0] == sys.executable
    assert argv[-5:] == ["start", "--only", "T3", "--repo", str(tmp_path)]


@pytest.mark.skipif(os.name == "nt", reason="no Ctrl+C for another process on Windows")
def test_interrupt_stops_the_relay_like_ctrl_c(tmp_path):
    exits, done = [], threading.Event()
    proc = relay_process.RelayProcess(
        tmp_path,
        ["start"],
        on_line=lambda line: None,
        on_exit=lambda code, text: (exits.append(code), done.set()),
        argv=[sys.executable, "-c",
              "import time\nprint('working', flush=True)\ntime.sleep(30)\n"],
        poll=0.05,
    )
    proc.start()
    time.sleep(0.5)  # let the interpreter install its Ctrl+C handling
    proc.interrupt()
    assert done.wait(10)
    assert exits[-1] != 0


def test_interrupt_on_windows_pauses_after_this_turn(tmp_path, monkeypatch):
    proc, lines, exits, done = _run(tmp_path)
    monkeypatch.setattr(relay_process, "os", SimpleNamespace(name="nt"))
    proc.interrupt()
    assert relay_process.stop_path(tmp_path).exists()
    assert done.wait(10)
