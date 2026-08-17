import json
import statistics
import subprocess
import sys
import time

import pytest

from whyline import events, paths

# The spec's target is 200 ms of user-perceived latency on a developer machine,
# where the real total is 41-79 ms (of which ~20 ms is bare interpreter startup).
#
# Rewritten 2026-08-18, twice. The first version asserted an absolute 200 ms and
# failed CI, where one macOS job spent 215 ms on interpreter startup alone. The
# second measured wall-clock overhead above that baseline, but lumped whyline's
# import cost together with the `git blame` subprocess `explain` spawns — so a
# budget tight enough to catch an eager import made `explain` flaky on CI (84 ms
# there against 60 ms locally).
#
# The two costs are now measured separately, because only the first is a
# regression this project can commit:
#
#   * IMPORT_BUDGET guards the import path directly, which is what an eagerly
#     imported heavy module actually breaks. Real cost is ~22 ms.
#   * COMMAND_CEILING is a generous absolute backstop per command, so a genuine
#     blow-up still fails the build without CI variance causing false alarms.
# Tightened 2026-08-18 (third revision). An absolute 0.06 was 7x the real cost of
# 8.7 ms, so a single `import asyncio` (+34 ms) slipped through — it caught only
# multi-module regressions. Rather than guess an absolute number that a slow CI
# runner might trip, the budget is now relative to the machine: importing whyline
# must cost less than starting Python at all. Real ratio is ~0.5; whyline plus one
# asyncio would be ~2.4. That scales with hardware, so it is tight everywhere.
IMPORT_RATIO_LIMIT = 1.0
IMPORT_ABSOLUTE_CAP_SECONDS = 0.06
COMMAND_CEILING_SECONDS = 0.5


def _median_run(args: list[str], runs: int = 5) -> float:
    timings = []
    for _ in range(runs):
        start = time.perf_counter()
        subprocess.run(args, capture_output=True)
        timings.append(time.perf_counter() - start)
    return statistics.median(timings)


def test_importing_whyline_stays_cheap():
    """The regression that matters: an eagerly imported heavy module.

    Verified capable of failing — a single `import asyncio` at module scope in
    cli.py trips this, as does any heavier addition.
    """
    baseline = _median_run([sys.executable, "-c", "pass"])
    with_import = _median_run([sys.executable, "-c", "import whyline.cli"])
    cost = with_import - baseline
    ratio = cost / baseline if baseline else float("inf")
    assert ratio < IMPORT_RATIO_LIMIT, (
        f"importing whyline.cli costs {cost * 1000:.0f} ms, which is "
        f"{ratio:.1f}x the {baseline * 1000:.0f} ms cost of starting Python at "
        "all; something heavy is being imported at module scope"
    )
    assert cost < IMPORT_ABSOLUTE_CAP_SECONDS, (
        f"importing whyline.cli costs {cost * 1000:.0f} ms in absolute terms"
    )


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
def test_each_command_stays_under_the_ceiling(repo, argv):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    elapsed = min(measure(repo, argv) for _ in range(3))
    assert elapsed < COMMAND_CEILING_SECONDS, (
        f"{' '.join(argv)} took {elapsed * 1000:.0f} ms"
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
