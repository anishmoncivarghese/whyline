import os
import subprocess
import sys

import pytest

from whyline import processes

windows = pytest.mark.skipif(os.name != "nt", reason="Windows-only process check")


@windows
def test_this_process_is_alive():
    assert processes.windows_pid_alive(os.getpid()) is True


@windows
def test_a_finished_child_is_not_alive():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert processes.windows_pid_alive(child.pid) is False


@windows
def test_a_running_child_is_alive_and_left_running():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert processes.windows_pid_alive(child.pid) is True
        assert child.poll() is None
    finally:
        child.kill()
        child.wait()


@windows
def test_no_pid_is_not_alive():
    assert processes.windows_pid_alive(0) is False
