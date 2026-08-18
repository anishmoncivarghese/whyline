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
# Rewritten 2026-08-18, third time, because the first two measured the wrong
# thing. An absolute 200 ms failed CI, where one macOS job spent 215 ms on
# interpreter startup alone. Wall-clock overhead above that baseline then made
# `explain` flaky, since it spawns `git blame` and its time mixes import cost with
# a subprocess. A ratio against interpreter startup was meant to be machine
# independent and is not: a *faster* machine has a smaller baseline, so the same
# import cost yields a LARGER ratio — locally 0.45, on CI 1.01, which failed a
# limit of 1.0 while nothing was wrong.
#
# Module count replaces timing for the regression that matters. It is exact,
# identical on every machine and every run, and the signal is large: whyline.cli
# pulls in 36 modules, a single `import asyncio` pulls in 102. A loose absolute
# timing cap stays as a backstop, since a module that does heavy work at import
# time would import few modules and slip past a count check.
IMPORT_MODULE_BUDGET = 60
IMPORT_TIME_CAP_SECONDS = 0.20
COMMAND_CEILING_SECONDS = 0.5


def _median_run(args: list[str], runs: int = 5) -> float:
    timings = []
    for _ in range(runs):
        start = time.perf_counter()
        subprocess.run(args, capture_output=True)
        timings.append(time.perf_counter() - start)
    return statistics.median(timings)


def _module_count(preamble: str) -> int:
    """Modules resident after running `preamble`. Deterministic, unlike timing."""
    completed = subprocess.run(
        [sys.executable, "-c", f"{preamble}; import sys; print(len(sys.modules))"],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return int(completed.stdout.strip())


def test_importing_whyline_pulls_in_few_modules():
    """The regression that matters: an eagerly imported heavy module.

    Verified capable of failing — a single `import asyncio` at module scope in
    cli.py takes this from 36 to 138.
    """
    baseline = _module_count("pass")
    with_import = _module_count("import whyline.cli")
    added = with_import - baseline
    assert added < IMPORT_MODULE_BUDGET, (
        f"importing whyline.cli pulls in {added} modules above a {baseline}-module "
        "baseline; something heavy is being imported at module scope"
    )


def test_importing_whyline_is_not_slow_even_if_it_imports_little():
    """Backstop for a module that does work at import time rather than importing
    many others — the count check above cannot see that."""
    baseline = _median_run([sys.executable, "-c", "pass"])
    with_import = _median_run([sys.executable, "-c", "import whyline.cli"])
    cost = with_import - baseline
    assert cost < IMPORT_TIME_CAP_SECONDS, (
        f"importing whyline.cli costs {cost * 1000:.0f} ms above a "
        f"{baseline * 1000:.0f} ms interpreter baseline"
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
