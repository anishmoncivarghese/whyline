import json
import threading
from types import SimpleNamespace

import pytest

from whyline.release import engine, github, state, workflows
from whyline.release.ci_failure import Failure, diagnose
from whyline.release.engine import Plan, Step
from whyline.release.github import StepError

JOB = "test (macos-latest, 3.13)"


def fake_gh(*, steps=None, annotations=(), failed_log="", api_log="", job_name=JOB,
            view_rc=0):
    calls = []

    def run(args, cwd=None, **kw):
        calls.append(args)
        if args[:3] == ["gh", "run", "view"] and "--log-failed" in args:
            return SimpleNamespace(returncode=0, stdout=failed_log, stderr="")
        if args[:3] == ["gh", "run", "view"]:
            data = {"name": "ci", "url": "https://x/run/7", "attempt": 2, "jobs": [
                {"name": "lint", "conclusion": "success", "databaseId": 1, "steps": []},
                {"name": job_name, "conclusion": "failure", "databaseId": 5,
                 "url": "https://x/job/5", "steps": steps or []}]}
            return SimpleNamespace(returncode=view_rc, stdout=json.dumps(data), stderr="boom")
        if args[:2] == ["gh", "api"]:
            if "annotations" in args[2]:
                return SimpleNamespace(
                    returncode=0, stdout=json.dumps([{"message": m} for m in annotations]),
                    stderr="")
            return SimpleNamespace(returncode=0, stdout=api_log, stderr="")
        raise AssertionError(args)

    run.calls = calls
    return run


def steps(*pairs):
    return [{"name": n, "conclusion": c} for n, c in pairs]


def test_never_started_job_is_no_runner(tmp_path):
    run = fake_gh(steps=steps(("Set up job", ""), ("Run pytest", "")),
                  annotations=["The job was not acquired by Runner of type hosted even after "
                               "waiting 300 minutes", "capacity"])
    failure = diagnose(tmp_path, 7, run=run)
    assert failure.cause == "no-runner"
    assert failure.job == JOB and failure.attempt == 2 and failure.workflow == "ci"
    assert failure.text().startswith(
        "GitHub couldn't find a macOS machine for test (macos-latest, 3.13). "
        "Your code is fine; rerun it.")


def test_no_conclusion_on_any_step_is_no_runner_without_annotations(tmp_path):
    assert diagnose(tmp_path, 7, run=fake_gh(steps=[])).cause == "no-runner"


def test_job_over_its_limit_is_timeout(tmp_path):
    run = fake_gh(steps=steps(("Run pytest", "cancelled")),
                  annotations=["The job running on runner X exceeded the maximum execution "
                               "time of 360 minutes."])
    failure = diagnose(tmp_path, 7, run=run)
    assert failure.cause == "timeout"
    assert "time limit" in failure.text()


def test_failed_tests_are_named(tmp_path):
    log = ("x\nFAILED tests/a.py::test_one - assert 1\nFAILED tests/b.py::test_two\n"
           "FAILED tests/a.py::test_one - assert 1\n")
    run = fake_gh(steps=steps(("Run pytest", "failure")), failed_log=log)
    failure = diagnose(tmp_path, 7, run=run)
    assert failure.cause == "tests"
    assert failure.tests == ["tests/a.py::test_one", "tests/b.py::test_two"]
    text = failure.text()
    assert "tests/b.py::test_two" in text and "ci, attempt 2" in text
    assert text.endswith("https://x/job/5")


def test_empty_failed_log_falls_back_to_the_job_log(tmp_path):
    run = fake_gh(steps=steps(("Run tests", "failure")), api_log="FAILED t.py::test_x\n")
    assert diagnose(tmp_path, 7, run=run).tests == ["t.py::test_x"]


def failing(run, marker):
    """Wrap a fake gh so any call whose args contain `marker` exits non-zero."""
    def wrapped(args, cwd=None, **kw):
        if any(marker in a for a in args):
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        return run(args, cwd=cwd, **kw)
    return wrapped


@pytest.mark.parametrize("marker", ["annotations", "--log-failed"])
def test_failed_later_gh_call_is_other_with_known_fields(tmp_path, marker):
    run = failing(fake_gh(steps=steps(("Run pytest", "failure")),
                          failed_log="FAILED t.py::test_x\n"), marker)
    failure = diagnose(tmp_path, 7, run=run)
    assert failure.cause == "other"
    assert failure.job == JOB and failure.step == "Run pytest"
    assert failure.workflow == "ci" and failure.attempt == 2 and failure.tests == []


def test_failed_job_log_fallback_is_other(tmp_path):
    run = failing(fake_gh(steps=steps(("Run pytest", "failure"))), "actions/jobs")
    failure = diagnose(tmp_path, 7, run=run)
    assert failure.cause == "other" and failure.step == "Run pytest"


def test_publish_step(tmp_path):
    run = fake_gh(steps=steps(("Build", "success"), ("Publish to PyPI", "failure")),
                  failed_log="HTTP 403\n")
    failure = diagnose(tmp_path, 7, run=run)
    assert failure.cause == "publish" and failure.step == "Publish to PyPI"
    assert "Publishing failed" in failure.text() and "HTTP 403" in failure.text()


def test_other_keeps_a_20_line_excerpt(tmp_path):
    log = "\n".join(f"line {i}" for i in range(50))
    run = fake_gh(steps=steps(("Lint", "failure")), failed_log=log)
    failure = diagnose(tmp_path, 7, run=run)
    assert failure.cause == "other"
    assert failure.excerpt.splitlines() == [f"line {i}" for i in range(30, 50)]


def test_gh_error_gives_other(tmp_path):
    failure = diagnose(tmp_path, 7, run=fake_gh(view_rc=1))
    assert failure.cause == "other" and failure.run_id == "7"


def test_gh_raising_gives_other(tmp_path):
    def run(args, cwd=None, **kw):
        raise OSError("no gh")

    assert diagnose(tmp_path, 7, run=run).cause == "other"


@pytest.mark.parametrize("cause, word", [
    ("no-runner", "rerun it"), ("timeout", "time limit"), ("tests", "Tests failed"),
    ("publish", "Publishing failed"), ("other", "isn't clear")])
def test_text_for_each_cause(cause, word):
    failure = Failure(cause=cause, workflow="ci", attempt=3, job="j", step="s",
                      url="https://u", tests=["t::a"], excerpt="tail")
    text = failure.text()
    assert word in text and "ci, attempt 3" in text and text.endswith("https://u")
    assert ("t::a" in text) == (cause == "tests")
    assert ("tail" in text) == (cause != "tests")


def test_round_trip_dict():
    failure = Failure(cause="tests", run_id="7", tests=["a"])
    assert Failure.from_dict(failure.to_dict()) == failure
    assert Failure.from_dict({}) is None


def failed_item(run_id=7):
    return {"databaseId": run_id, "name": "ci", "status": "completed",
            "conclusion": "failure", "url": "https://x/run/7"}


def test_run_outcome_raises_with_failure(tmp_path):
    run = fake_gh(steps=steps(("Run pytest", "failure")), failed_log="FAILED t::a\n")
    outcome = github._run_outcome(tmp_path, run, failed_item(), set())
    assert isinstance(outcome, StepError)
    assert outcome.failure.cause == "tests" and str(outcome) == outcome.failure.text()


def test_wait_for_tag_run_raises_with_failure(tmp_path):
    inner = fake_gh(steps=steps(("Publish", "failure")))

    def run(args, cwd=None, **kw):
        if args[:3] == ["gh", "run", "list"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps([failed_item()]), stderr="")
        return inner(args, cwd=cwd, **kw)

    with pytest.raises(StepError) as exc:
        workflows.wait_for_tag_run(tmp_path, "v1", "release.yml", run=run,
                                   cancel_event=threading.Event())
    assert exc.value.failure.cause == "publish"
    assert str(exc.value) == exc.value.failure.text()


def test_state_saves_failure_and_clears_on_success(tmp_path):
    (tmp_path / ".git").mkdir()
    failure = Failure(cause="no-runner", job="j", workflow="ci")
    calls = {"n": 0}

    def flaky(cancel):
        calls["n"] += 1
        if calls["n"] == 1:
            raise StepError(failure.text(), failure=failure)

    plan = Plan("1.0", [Step("a", "A", False, lambda: False, flaky),
                        Step("b", "B", False, lambda: False, lambda cancel: None)])
    assert engine.run(tmp_path, plan, mode="auto").status == engine.FAILED
    saved = state.load(tmp_path)
    assert Failure.from_dict(saved.failure) == failure
    assert engine.run(tmp_path, plan, mode="auto").status == engine.DONE
    assert state.load(tmp_path) is None


def test_failure_cleared_when_the_next_run_starts(tmp_path):
    (tmp_path / ".git").mkdir()
    failure = Failure(cause="tests")
    attempts = {"n": 0}

    def step(cancel):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise StepError("x", failure=failure)
        raise RuntimeError("plain")

    plan = Plan("1.0", [Step("a", "A", False, lambda: False, step)])
    engine.run(tmp_path, plan, mode="auto")
    assert state.load(tmp_path).failure["cause"] == "tests"
    engine.run(tmp_path, plan, mode="auto")
    assert state.load(tmp_path).failure == {}


def test_old_state_file_without_failure_loads(tmp_path):
    (tmp_path / ".git").mkdir()
    state.save(tmp_path, state.State("1.0", ["a"]))
    data = json.loads(state.path(tmp_path).read_text())
    del data["failure"]
    state.path(tmp_path).write_text(json.dumps(data))
    assert state.load(tmp_path).failure == {}


# --- rerun ---------------------------------------------------------------------


def _failed_run(returncode=0, stderr=""):
    calls = []

    def run(args, cwd=None, **kw):
        calls.append(args)
        return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

    run.calls = calls
    return run


def test_rerun_runs_gh_rerun_failed(tmp_path):
    from whyline.release.ci_failure import rerun

    run = _failed_run()
    rerun(tmp_path, Failure(run_id="77"), run=run)
    assert run.calls == [["gh", "run", "rerun", "77", "--failed"]]


def test_rerun_raises_with_gh_message(tmp_path):
    from whyline.release.ci_failure import rerun

    with pytest.raises(StepError, match="run is still in progress"):
        rerun(tmp_path, Failure(run_id="77"), run=_failed_run(1, "run is still in progress"))


# -- RCR-5: ask an agent ------------------------------------------------------

import subprocess

from whyline.release import ci_failure


def _git_repo(path):
    def git(*args):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (path / "a.txt").write_text("1\n")
    git("add", ".")
    git("commit", "-qm", "first")
    git("tag", "v1.0.0")
    (path / "a.txt").write_text("2\n")
    git("commit", "-qam", "change a thing")


def _real_run(args, cwd=None, **kw):
    if args[0] == "gh":
        log = "\n".join(f"line {i}" for i in range(500))
        return SimpleNamespace(returncode=0, stdout=log, stderr="")
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return SimpleNamespace(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def _failure():
    return Failure(cause="tests", run_id="7", job="test", tests=["tests/a.py::t"])


def test_ask_prompt_has_failure_log_commits_and_stat_with_caps(tmp_path):
    _git_repo(tmp_path)
    seen = []
    ci_failure.ask(tmp_path, _failure(), ask_agent=lambda p: seen.append(p) or "<answer>x</answer>",
                   run=_real_run)
    prompt = seen[0]
    assert "tests/a.py::t" in prompt
    assert "change a thing" in prompt and "first" not in prompt.split("Commits since")[1]
    assert "a.txt" in prompt and "git diff --stat v1.0.0..HEAD" in prompt
    assert "line 499" in prompt and "line 299" not in prompt
    assert sum(1 for line in prompt.splitlines() if line.startswith("line ")) == 200
    assert "<answer>" in prompt and "NEEDS_CODE_FIX: yes" in prompt


def test_parse_answer_extracts_answer_and_flag():
    got = ci_failure.parse_answer("hi\n<answer>\nFix the test.\n</answer>\nNEEDS_CODE_FIX: yes")
    assert got.text == "Fix the test." and got.needs_fix is True
    got = ci_failure.parse_answer("<answer>Rerun it.</answer>\nNEEDS_CODE_FIX: no")
    assert got.text == "Rerun it." and got.needs_fix is False


def test_unmarked_reply_uses_whole_reply_and_missing_flag_is_no():
    got = ci_failure.parse_answer("Just rerun it.")
    assert got.text == "Just rerun it." and got.needs_fix is False
    got = ci_failure.parse_answer("Change the code.\nNEEDS_CODE_FIX: yes")
    assert got.text == "Change the code." and got.needs_fix is True


def test_ask_logs_the_answer_and_leaves_the_repo_alone(tmp_path):
    _git_repo(tmp_path)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                          text=True).stdout
    before = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True,
                            text=True).stdout
    ci_failure.ask(tmp_path, _failure(), ask_agent=lambda p: "<answer>Bad test</answer>",
                   run=_real_run)
    after = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True,
                           text=True).stdout
    assert after == before
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                          text=True).stdout == head
    assert "Bad test" in ci_failure.log_path(tmp_path).read_text()


def test_default_ask_agent_is_read_only_in_a_temp_folder(tmp_path, monkeypatch):
    from whyline.relaychat import agent_choice, ask as relay_ask
    from whyline.release import plan as release_plan
    import whyline_relay.agents as agents

    cwds = []
    monkeypatch.setattr(agent_choice, "pick", lambda root, a: SimpleNamespace(agent="claude"))
    monkeypatch.setattr(relay_ask, "command", lambda root, agent: ["claude", "-p"])
    monkeypatch.setattr(relay_ask, "extract", lambda root, agent, out, f: out)
    monkeypatch.setattr(agents, "run", lambda argv, prompt, cwd, **kw: (
        cwds.append(cwd) or SimpleNamespace(exit_code=0, output="<answer>ok</answer>")))
    got = ci_failure.ask(tmp_path, _failure(), ask_agent=release_plan.default_ask_agent(tmp_path),
                         run=_real_run)
    assert got.text == "ok"
    assert cwds and cwds[0] != tmp_path and tmp_path not in cwds[0].parents
