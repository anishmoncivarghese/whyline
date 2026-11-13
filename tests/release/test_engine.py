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


# --- rerun_and_resume ----------------------------------------------------------


def _stop_with_failure(root, cause="no-runner"):
    from whyline.release.ci_failure import Failure

    class Boom(RuntimeError):
        failure = Failure(cause=cause, run_id="77")

    def bad(cancel):
        raise Boom("ci failed")

    steps = make([], "abc")
    steps[1] = Step("b", "Title b", False, lambda: False, bad)
    engine.run(root, Plan("1.0", steps), mode="auto")


def test_rerun_and_resume_waits_on_the_new_attempt_then_reaches_the_next_step(root):
    import json
    import subprocess
    from types import SimpleNamespace

    from whyline.release import github
    from whyline.release.config import ReleaseConfig

    for args in (["init", "-b", "main"], ["config", "user.email", "t@e.com"],
                 ["config", "user.name", "T"], ["commit", "--allow-empty", "-m", "first"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    # The same run 77 is queued once the rerun starts, then succeeds.
    attempts = iter([
        {"databaseId": 77, "name": "CI", "status": "queued", "conclusion": ""},
        {"databaseId": 77, "name": "CI", "status": "in_progress", "conclusion": ""},
        {"databaseId": 77, "name": "CI", "status": "completed", "conclusion": "success"},
    ])
    gh, polls, order = [], [], []

    def run(args, cwd=None, **kw):
        if args[0] != "gh":
            p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
            return SimpleNamespace(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
        gh.append(args)
        if args[1:3] == ["run", "rerun"]:
            order.append("rerun")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[1:3] == ["run", "list"]:
            order.append("poll")
            polls.append(args)
            return SimpleNamespace(returncode=0, stdout=json.dumps([next(attempts)]), stderr="")
        pytest.fail(f"unexpected gh call {args}")

    sleeps = []
    ci = {s.id: s for s in github.build_steps(root, ReleaseConfig(), "1.0", run=run,
                                              sleep=sleeps.append)}["ci"]
    calls = []
    steps = {s.id: s for s in make(calls, "abc")}
    steps["b"] = ci  # the real CI wait stands in for the failed step
    _stop_with_failure(root)
    steps["c"] = Step("c", "Title c", False, lambda: False, lambda cancel: calls.append("c"))

    result = engine.rerun_and_resume(root, steps, run=run)

    assert order == ["rerun", "poll", "poll", "poll"]
    assert gh[0] == ["gh", "run", "rerun", "77", "--failed"]
    assert len(polls) == 3 and len(sleeps) == 2  # queued, in progress, then passed
    assert result.status == engine.DONE
    assert calls == ["c"]
    assert state.load(root) is None


def test_rerun_and_resume_gh_error_keeps_the_stop(root):
    from types import SimpleNamespace

    from whyline.release.github import StepError

    _stop_with_failure(root)
    run = lambda args, cwd=None, **kw: SimpleNamespace(returncode=1, stdout="", stderr="nope")
    with pytest.raises(StepError, match="nope"):
        engine.rerun_and_resume(root, {s.id: s for s in make([], "abc")}, run=run)
    assert state.load(root).failure["run_id"] == "77"


def test_rerun_and_resume_with_nothing_to_rerun(root):
    run = lambda *a, **k: pytest.fail("gh must not run")
    assert engine.rerun_and_resume(root, {}, run=run).message == "Nothing to rerun"
    engine.run(root, Plan("1.0", make([], "ab", fail="b")), mode="auto")  # no failure saved
    result = engine.rerun_and_resume(root, {}, run=run)
    assert result.status == engine.NOTHING and result.message == "Nothing to rerun"


# --- auto rerun when GitHub had no runner ---------------------------------------


def _auto_steps(root, cause, attempts, calls):
    """Step b fails with `cause` on each attempt listed; later it passes."""
    from whyline.release.ci_failure import Failure

    queue = list(attempts)

    def b(cancel):
        calls.append("b")
        if queue:
            err = RuntimeError("ci failed")
            err.failure = Failure(cause=cause, run_id="77", job="test", attempt=queue.pop(0))
            raise err

    return [Step("a", "A", False, lambda: False, lambda c: calls.append("a")),
            Step("b", "B", False, lambda: False, b)]


def _setting(root, value):
    from whyline.release import config
    from whyline.release.config import ReleaseConfig

    config.save(root, ReleaseConfig(on_no_runner=value))


def _fake_gh(log):
    from types import SimpleNamespace

    def run(args, cwd=None, **kw):
        log.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return run


def test_auto_rerun_only_once_and_never_tests(root):
    _setting(root, "rerun once")
    # No runner on attempt 1 reruns once; attempt 2 fails again and stops.
    gh, said, calls = [], [], []
    steps = _auto_steps(root, "no-runner", [1, 2], calls)
    result = engine.run(root, Plan("1.0", steps), mode="auto",
                        auto_run=_fake_gh(gh), say=said.append)
    assert result.status == engine.FAILED
    assert gh == [["gh", "run", "rerun", "77", "--failed"]]
    assert said == ["GitHub had no runner for test; rerunning once"]
    assert calls == ["a", "b", "b"]
    assert state.load(root).failure["attempt"] == 2

    # A single no-runner failure is rerun and the release finishes.
    gh.clear(); calls.clear()
    steps = _auto_steps(root, "no-runner", [1], calls)
    result = engine.run(root, Plan("1.0", steps), mode="auto", auto_run=_fake_gh(gh))
    assert result.status == engine.DONE and len(gh) == 1
    # Without a say callback the notice still lands in the durable release log.
    assert "GitHub had no runner for test; rerunning once" in engine.log_path(root).read_text()

    # Any other cause shows the failure screen without a rerun.
    for cause in ("tests", "timeout", "publish", "other"):
        gh.clear()
        steps = _auto_steps(root, cause, [1], [])
        result = engine.run(root, Plan("1.0", steps), mode="auto", auto_run=_fake_gh(gh))
        assert result.status == engine.FAILED and gh == []


@pytest.mark.parametrize("value", ["ask", "off"])
def test_no_auto_rerun_unless_asked(root, value):
    _setting(root, value)
    gh = []
    steps = _auto_steps(root, "no-runner", [1], [])
    result = engine.run(root, Plan("1.0", steps), mode="auto", auto_run=_fake_gh(gh))
    assert result.status == engine.FAILED and gh == []
