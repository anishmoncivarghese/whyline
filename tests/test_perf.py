import json
import subprocess
import sys
import time

import pytest

from whyline import events, paths

BUDGET_SECONDS = 0.2


def measure(repo, argv: list[str]) -> float:
    start = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-m", "whyline", *argv],
        cwd=repo.path,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - start
    assert completed.returncode == 0, completed.stderr
    return elapsed


@pytest.mark.parametrize("argv", [["status"], ["timeline"], ["brief"]])
def test_cold_start_is_within_budget(repo, argv):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    assert measure(repo, argv) < BUDGET_SECONDS


def test_explain_cold_start_is_within_budget(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    assert measure(repo, ["explain", "a.py:1"]) < BUDGET_SECONDS


def test_explain_stays_under_one_second_with_many_events(repo):
    """Spec §9 carries a 50,000-event target. The SQLite index was deliberately
    deferred on the argument that a plain JSONL scan is fast enough; this test is
    what holds that argument to account."""
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    target = paths.ledger_path(repo.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for index in range(50_000):
            event = events.new_event(
                events.FILE_TOUCHED, path=f"file{index % 100}.py", tool="Edit"
            )
            handle.write(
                json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
            )
    assert measure(repo, ["explain", "a.py:1"]) < 1.0
