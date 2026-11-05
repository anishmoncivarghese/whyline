import os
import threading
from datetime import datetime, timezone

import pytest

from whyline.release import engine, state
from whyline.release.engine import AlreadyReleasing, Plan, Step, VersionMismatch


def make(calls, ids, *, irreversible=(), fail=(), done=(), raises=()):
    steps = []
    for i in ids:

        def run(cancel, i=i):
            calls.append(i)
            if i in raises:
                raise RuntimeError("boom")
            return False if i in fail else None

        steps.append(Step(i, f"Title {i}", i in irreversible, lambda i=i: i in done, run))
    return steps


@pytest.fixture
def root(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_runs_in_order_and_clears_state(root):
    calls = []
    result = engine.run(root, Plan("1.0", make(calls, "abc")), mode="auto")
    assert result.status == engine.DONE
    assert calls == ["a", "b", "c"]
    assert state.load(root) is None


@pytest.mark.parametrize("mode,expected", [("step", 2), ("ask", 1), ("auto", 0)])
def test_confirm_calls_per_mode(root, mode, expected):
    asked = []
    steps = make([], "abc", irreversible="bc")
    engine.run(root, Plan("1.0", steps), mode=mode, confirm=lambda s: asked.append(s.id) or True)
    assert len(asked) == expected
    if asked:
        assert asked[0] == "b"


def test_declined_confirm_pauses(root):
    calls = []
    steps = make(calls, "abc", irreversible="b")
    result = engine.run(root, Plan("1.0", steps), mode="ask", confirm=lambda s: False)
    assert result.status == engine.PAUSED
    assert result.message == "You stopped before Title b."
    assert calls == ["a"]
    saved = state.load(root)
    assert saved.done == ["a"] and not saved.running


def test_failure_saves_state(root):
    calls = []
    result = engine.run(root, Plan("1.0", make(calls, "abc", fail="b")), mode="auto")
    assert result.status == engine.FAILED and result.failed_id == "b"
    saved = state.load(root)
    assert saved.done == ["a"]
    assert saved.failed_id == "b"
    assert "Title b" in saved.reason
    assert saved.version == "1.0" and saved.mode == "auto" and saved.started
    assert calls == ["a", "b"]


def test_exception_fails_with_reason(root):
    result = engine.run(root, Plan("1.0", make([], "ab", raises="a")), mode="auto")
    assert result.status == engine.FAILED
    assert "boom" in state.load(root).reason


def test_resume_skips_done_and_reruns_failed(root):
    calls = []
    engine.run(root, Plan("1.0", make(calls, "abc", fail="b")), mode="auto")
    calls.clear()
    steps = {s.id: s for s in make(calls, "abc")}
    result = engine.resume(root, steps, version="1.0")
    assert result.status == engine.DONE
    assert calls == ["b", "c"]
    assert state.load(root) is None


def test_resume_version_mismatch(root):
    engine.run(root, Plan("1.0", make([], "ab", fail="b")), mode="auto")
    steps = {s.id: s for s in make([], "ab")}
    with pytest.raises(VersionMismatch):
        engine.resume(root, steps, version="2.0")


def test_done_check_skips(root):
    calls = []
    result = engine.run(root, Plan("1.0", make(calls, "abc", done="b")), mode="auto")
    assert result.status == engine.DONE
    assert calls == ["a", "c"]


def test_cancel_between_steps(root):
    calls = []
    cancel = threading.Event()
    steps = make(calls, "abc")
    first = steps[0].run
    steps[0] = Step("a", "Title a", False, lambda: False, lambda c: (first(c), cancel.set())[0])
    result = engine.run(root, Plan("1.0", steps), mode="auto", cancel_event=cancel)
    assert result.status == engine.CANCELLED
    assert calls == ["a"]
    assert state.load(root).done == ["a"]


def test_cancel_event_passed_to_steps(root):
    seen = []
    cancel = threading.Event()
    step = Step("a", "A", False, lambda: False, lambda c: seen.append(c))
    engine.run(root, Plan("1.0", [step]), mode="auto", cancel_event=cancel)
    assert seen == [cancel]


def test_percent_at_each_step(root):
    seen = []
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    engine.run(
        root,
        Plan("1.0", make([], "abcd")),
        mode="auto",
        on_progress=seen.append,
        now=lambda: t,
    )
    running = [engine.percent(p) for p in seen if p.detail == "Running"]
    assert running == [0, 25, 50, 75]
    assert engine.percent(seen[-1]) == 100
    assert seen[0].total == 4 and seen[0].started_at == t


def test_already_releasing_with_live_pid(root):
    state.save(root, state.State("1.0", ["a"], running=True, pid=os.getpid()))
    with pytest.raises(AlreadyReleasing):
        engine.run(root, Plan("1.0", make([], "a")), mode="auto")


def test_dead_pid_does_not_block(root):
    state.save(root, state.State("1.0", ["a"], running=True, pid=999999))
    result = engine.run(
        root, Plan("1.0", make([], "a")), mode="auto", pid_alive=lambda pid: False
    )
    assert result.status == engine.DONE
