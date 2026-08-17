import json
import subprocess
import sys
import time

import pytest

from whyline import events, paths

# The spec's target is 200 ms of user-perceived latency on a developer machine,
# where the real figure is ~18 ms. A shared CI runner spends most of that budget
# on interpreter startup alone — one job measured 215 ms for `status` — so an
# absolute assertion there tests the runner, not this code.
#
# Changed 2026-08-18: measure whyline's own contribution *above* bare interpreter
# startup on the same machine. That is what this project controls, it catches the
# regression that actually matters (an eager heavy import), and it is meaningful
# on any hardware. The absolute figure stays documented in the README and is
# still asserted, with headroom, so a genuine blow-up is not masked.
OVERHEAD_BUDGET_SECONDS = 0.15
ABSOLUTE_CEILING_SECONDS = 1.0


def baseline_interpreter_startup() -> float:
    """Cost of starting Python at all, on this machine, right now."""
    best = None
    for _ in range(3):
        start = time.perf_counter()
        subprocess.run([sys.executable, "-c", "pass"], capture_output=True)
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
    return best or 0.0


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


@pytest.mark.parametrize(
    "argv", [["status"], ["timeline"], ["brief"], ["explain", "a.py:1"]]
)
def test_cold_start_overhead_is_within_budget(repo, argv):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    baseline = baseline_interpreter_startup()
    elapsed = min(measure(repo, argv) for _ in range(3))
    overhead = elapsed - baseline
    assert overhead < OVERHEAD_BUDGET_SECONDS, (
        f"{' '.join(argv)} added {overhead * 1000:.0f} ms over a "
        f"{baseline * 1000:.0f} ms interpreter baseline"
    )
    assert elapsed < ABSOLUTE_CEILING_SECONDS, (
        f"{' '.join(argv)} took {elapsed * 1000:.0f} ms in total"
    )


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
