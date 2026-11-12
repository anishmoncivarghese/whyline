import json
import subprocess
import threading
from types import SimpleNamespace

import pytest

from whyline.release import config as release_config
from whyline.release import github
from whyline.release.config import ReleaseConfig
from whyline.release.github import StepError

EVENT = threading.Event()


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    root = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True,
                   capture_output=True)
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "T")
    git(root, "remote", "add", "origin", str(origin))
    (root / "a.txt").write_text("1")
    git(root, "add", ".")
    git(root, "commit", "-m", "first")
    git(root, "push", "origin", "main")
    return root


class FakeGh:
    """Real git, faked gh."""

    def __init__(self, runs=None, release_exists=False):
        self.runs = runs if runs is not None else []
        self.release_exists = release_exists
        self.calls = []

    def __call__(self, args, cwd=None, **kw):
        if args[0] == "gh":
            self.calls.append(args)
            if args[1:3] == ["run", "list"]:
                return SimpleNamespace(returncode=0, stdout=json.dumps(self.runs), stderr="")
            if args[1:3] == ["release", "view"]:
                return SimpleNamespace(returncode=0 if self.release_exists else 1,
                                       stdout="", stderr="not found")
            if args[1:3] == ["release", "create"]:
                self.release_exists = True
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if args[1:3] == ["pr", "create"]:
                return SimpleNamespace(returncode=0, stdout="https://x/pr/1", stderr="")
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
        return SimpleNamespace(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)


def steps(root, run, cfg=None, **kw):
    out = github.build_steps(root, cfg or ReleaseConfig(), "1.2.3", run=run, **kw)
    return {s.id: s for s in out}


def test_step_order_and_irreversible(repo):
    s = steps(repo, FakeGh())
    assert list(s) == ["commit", "checks", "push", "ci", "tag", "github_release"]
    assert [k for k, v in s.items() if v.irreversible] == ["push", "tag", "github_release"]


def test_commit_adds_only_listed_paths(repo):
    (repo / "pyproject.toml").write_text("v")
    notes = repo / "notes.md"
    notes.write_text("n")
    (repo / "pend.txt").write_text("p")
    (repo / "stray.txt").write_text("s")
    release_config.add_pending(repo, "pend.txt")
    s = steps(repo, FakeGh(), changed_files=lambda: [repo / "pyproject.toml"],
              notes_path=notes)
    assert not s["commit"].done_check()
    s["commit"].run(EVENT)
    assert git(repo, "log", "-1", "--format=%s") == "chore: release v1.2.3"
    assert set(git(repo, "show", "--name-only", "--format=", "HEAD").split()) == {
        "pyproject.toml", "notes.md", "pend.txt"}
    assert "stray.txt" in git(repo, "status", "--porcelain")
    assert release_config.pending(repo) == []
    assert s["commit"].done_check()


def test_checks_stream_and_fail(repo):
    seen = []
    cfg = ReleaseConfig(checks=("echo hello",))
    steps(repo, FakeGh(), cfg, on_progress=seen.append)["checks"].run(EVENT)
    assert any("hello" in t for t in seen)
    cfg = ReleaseConfig(checks=("for i in $(seq 1 30); do echo line$i; done; exit 3",))
    with pytest.raises(StepError) as exc:
        steps(repo, FakeGh(), cfg)["checks"].run(EVENT)
    text = str(exc.value)
    assert "Check failed: for i" in text and "line30" in text and "line10\n" not in text


def test_push_and_done_check(repo):
    (repo / "b.txt").write_text("2")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "second")
    s = steps(repo, FakeGh())
    assert not s["push"].done_check()
    s["push"].run(EVENT)
    assert s["push"].done_check()


def test_push_refuses_diverged_origin(repo, tmp_path):
    other = tmp_path / "other"
    git(tmp_path, "clone", str(tmp_path / "origin.git"), str(other))
    git(other, "config", "user.email", "t@example.com")
    git(other, "config", "user.name", "T")
    (other / "c.txt").write_text("3")
    git(other, "add", ".")
    git(other, "commit", "-m", "remote")
    git(other, "push", "origin", "main")
    (repo / "b.txt").write_text("2")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "local")
    with pytest.raises(StepError) as exc:
        steps(repo, FakeGh())["push"].run(EVENT)
    assert str(exc.value) == "origin/main has commits this branch doesn't; merge them first"
    assert not exc.value.open_pr


@pytest.mark.parametrize("stderr", ["remote: error: GH006: Protected branch update failed",
                                    "remote: protected branch hook declined"])
def test_push_protected_branch_offers_pr(repo, stderr):
    base = FakeGh()

    def run(args, cwd=None, **kw):
        if args[:2] == ["git", "push"]:
            return SimpleNamespace(returncode=1, stdout="", stderr=stderr)
        return base(args, cwd=cwd, **kw)

    with pytest.raises(StepError) as exc:
        steps(repo, run)["push"].run(EVENT)
    assert exc.value.open_pr is True
    assert github.open_pr(repo, "main", run=base) == "https://x/pr/1"
    assert base.calls[-1] == ["gh", "pr", "create", "--fill", "--base", "main"]


def test_push_other_failure_is_not_pr(repo):
    base = FakeGh()

    def run(args, cwd=None, **kw):
        if args[:2] == ["git", "push"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="network down")
        return base(args, cwd=cwd, **kw)

    with pytest.raises(StepError) as exc:
        steps(repo, run)["push"].run(EVENT)
    assert not exc.value.open_pr and "network down" in str(exc.value)


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, n):
        self.sleeps.append(n)
        self.t += n


def ci_step(repo, runs, cfg=None, sequence=None):
    gh = FakeGh(runs)
    clock = Clock()
    seen = []
    run = gh
    if sequence:
        items = iter(sequence)

        def run(args, cwd=None, **kw):
            if args[:3] == ["gh", "run", "list"]:
                return SimpleNamespace(returncode=0, stdout=json.dumps(next(items)), stderr="")
            return gh(args, cwd=cwd, **kw)

    s = steps(repo, run, cfg, sleep=clock.sleep, now=clock.now, on_progress=seen.append)
    return s["ci"], clock, seen


def item(name, status="completed", conclusion="success"):
    return {"name": name, "status": status, "conclusion": conclusion, "url": f"u/{name}"}


def test_ci_passes_after_polling(repo):
    step, clock, seen = ci_step(repo, [], sequence=[
        [item("a", "in_progress", "")],
        [item("a"), item("b", "in_progress", "")],
        [item("a"), item("b")]])
    step.run(EVENT)
    assert clock.sleeps == [15, 15]
    assert "1 of 2 checks" in seen and seen[-1] == "2 of 2 checks"


def test_ci_failure_names_run_and_url(repo):
    step, _, _ = ci_step(repo, [item("lint"), item("tests", conclusion="failure")])
    with pytest.raises(StepError) as exc:
        step.run(EVENT)
    assert "tests" in str(exc.value) and "u/tests" in str(exc.value)


def test_ci_ignores_named_runs(repo):
    cfg = ReleaseConfig(ci_ignore=("flaky",))
    step, _, _ = ci_step(repo, [item("flaky", conclusion="failure"), item("tests")], cfg)
    assert step.run(EVENT) is None


# -- ignoring single jobs inside a workflow run --------------------------------


WIN = "test (windows-latest, 3.13)"
LINUX = "test (ubuntu-latest, 3.13)"


def wf(run_id, name="ci", status="completed", conclusion="failure"):
    return {"databaseId": run_id, "name": name, "status": status,
            "conclusion": conclusion, "url": f"u/{name}"}


def job(name, status="completed", conclusion="success"):
    return {"name": name, "status": status, "conclusion": conclusion, "url": f"j/{name}"}


def jobs_step(repo, run_seq, jobs_seq, cfg):
    """ci step whose `gh run list` and `gh run view <id> --json jobs` answer from
    sequences, one item per poll; the last item repeats."""
    gh = FakeGh()
    clock = Clock()
    seen = []
    calls = []
    lists, views = list(run_seq), list(jobs_seq)

    def answer(items):
        return items.pop(0) if len(items) > 1 else items[0]

    def run(args, cwd=None, **kw):
        if args[:3] == ["gh", "run", "list"]:
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout=json.dumps(answer(lists)), stderr="")
        if args[:3] == ["gh", "run", "view"]:
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout=json.dumps({"jobs": answer(views)}),
                                   stderr="")
        return gh(args, cwd=cwd, **kw)

    s = steps(repo, run, cfg, sleep=clock.sleep, now=clock.now, on_progress=seen.append)
    return s["ci"], clock, seen, calls


def test_ci_passes_when_only_an_ignored_job_failed(repo):
    cfg = ReleaseConfig(ci_ignore=(WIN,))
    step, _, seen, calls = jobs_step(
        repo, [[wf(7)]], [[job(LINUX), job(WIN, conclusion="failure")]], cfg)
    assert step.run(EVENT) is None
    assert ["gh", "run", "view", "7", "--json", "jobs"] in calls
    assert seen[-1] == "1 of 1 checks"


def test_ci_fails_on_a_job_that_is_not_ignored_and_names_it(repo):
    cfg = ReleaseConfig(ci_ignore=(WIN,))
    step, _, _, _ = jobs_step(
        repo, [[wf(7)]],
        [[job(LINUX, conclusion="failure"), job(WIN, conclusion="failure")]], cfg)
    with pytest.raises(StepError) as exc:
        step.run(EVENT)
    assert LINUX in str(exc.value)
    assert f"j/{LINUX}" in str(exc.value)
    assert WIN not in str(exc.value)


def test_ci_waits_for_jobs_still_running_but_not_for_ignored_ones(repo):
    cfg = ReleaseConfig(ci_ignore=(WIN,))
    step, clock, _, _ = jobs_step(
        repo,
        [[wf(7, status="in_progress", conclusion="")]],
        [[job(LINUX, "in_progress", ""), job(WIN, "in_progress", "")],
         [job(LINUX), job(WIN, "in_progress", "")]],
        cfg)
    assert step.run(EVENT) is None
    assert clock.sleeps == [15]


def test_ci_whole_workflow_name_still_ignores_the_run(repo):
    cfg = ReleaseConfig(ci_ignore=("nightly",))
    step, _, _, calls = jobs_step(
        repo, [[wf(7, "nightly"), wf(8, "ci", conclusion="success")]], [[]], cfg)
    assert step.run(EVENT) is None
    assert not any(c[:3] == ["gh", "run", "view"] for c in calls)


def test_ci_without_ignores_never_reads_jobs(repo):
    step, _, _, calls = jobs_step(repo, [[wf(7, conclusion="success")]], [[]], ReleaseConfig())
    assert step.run(EVENT) is None
    assert not any(c[:3] == ["gh", "run", "view"] for c in calls)


def test_ci_failed_run_with_no_jobs_still_fails(repo):
    cfg = ReleaseConfig(ci_ignore=(WIN,))
    step, _, _, _ = jobs_step(repo, [[wf(7, conclusion="startup_failure")]], [[]], cfg)
    with pytest.raises(StepError) as exc:
        step.run(EVENT)
    assert "ci, attempt 1" in str(exc.value) and exc.value.failure.cause == "other"


def test_ci_no_runs_counts_as_passed_after_two_minutes(repo):
    step, clock, seen = ci_step(repo, [])
    step.run(EVENT)
    assert clock.t >= 120 and seen[-1] == "no CI configured"


def test_ci_times_out_resumably(repo):
    step, clock, _ = ci_step(repo, [item("a", "in_progress", "")])
    with pytest.raises(StepError) as exc:
        step.run(EVENT)
    assert "60 minutes" in str(exc.value) and "resume" in str(exc.value)
    assert clock.t >= 3600
    assert not step.done_check()


def test_ci_cancel(repo):
    step, _, _ = ci_step(repo, [item("a", "in_progress", "")])
    cancel = threading.Event()
    cancel.set()
    assert step.run(cancel) is False


def test_tag_creates_annotated_and_pushes(repo):
    s = steps(repo, FakeGh())
    assert not s["tag"].done_check()
    s["tag"].run(EVENT)
    assert git(repo, "cat-file", "-t", "v1.2.3") == "tag"
    assert git(repo, "tag", "-l", "--format=%(contents:subject)", "v1.2.3") == "v1.2.3"
    assert s["tag"].done_check()


def test_tag_reuses_existing_local_tag(repo):
    git(repo, "tag", "-a", "v1.2.3", "-m", "v1.2.3")
    s = steps(repo, FakeGh())
    s["tag"].run(EVENT)
    assert s["tag"].done_check()


def test_github_release_with_notes_file(repo):
    gh = FakeGh()
    notes = repo / "n.md"
    s = steps(repo, gh, notes_path=notes)
    assert not s["github_release"].done_check()
    s["github_release"].run(EVENT)
    assert gh.calls[-1] == ["gh", "release", "create", "v1.2.3", "--title", "v1.2.3",
                            "--notes-file", str(notes)]
    assert s["github_release"].done_check()


def test_github_release_generates_notes_when_none(repo):
    gh = FakeGh()
    steps(repo, gh)["github_release"].run(EVENT)
    assert gh.calls[-1][-1] == "--generate-notes"


def _push_with_other(repo, tmp_path, monkeypatch, other_path, dirty=False):
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True)
    if dirty:
        (other / "a.txt").write_text("changed")
    (repo / "b.txt").write_text("2")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "second")
    monkeypatch.setattr(github.worktrees, "default_branch_worktree",
                        lambda root: other if other_path is None else other_path(other))
    seen = []
    steps(repo, FakeGh(), on_progress=seen.append)["push"].run(EVENT)
    return other, seen


def test_push_fast_forwards_clean_other_checkout(repo, tmp_path, monkeypatch):
    other, seen = _push_with_other(repo, tmp_path, monkeypatch, None)
    assert (other / "b.txt").exists()
    assert seen == [f"Updated {other} to v1.2.3"]


def test_push_leaves_dirty_other_checkout_alone(repo, tmp_path, monkeypatch):
    other, seen = _push_with_other(repo, tmp_path, monkeypatch, None, dirty=True)
    assert not (other / "b.txt").exists()
    assert seen == [f"Your main checkout at {other} has changes; update it with git pull"]


def test_push_without_other_checkout(repo, tmp_path, monkeypatch):
    other, seen = _push_with_other(repo, tmp_path, monkeypatch, lambda o: None)
    assert seen == [] and not (other / "b.txt").exists()


def test_push_other_checkout_merge_failure_is_a_warning(repo, tmp_path, monkeypatch):
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True)
    git(other, "config", "user.email", "t@example.com")
    git(other, "config", "user.name", "T")
    (other / "c.txt").write_text("x")
    git(other, "add", ".")
    git(other, "commit", "-m", "diverged")
    (repo / "b.txt").write_text("2")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "second")
    monkeypatch.setattr(github.worktrees, "default_branch_worktree", lambda root: other)
    seen = []
    steps(repo, FakeGh(), on_progress=seen.append)["push"].run(EVENT)
    assert len(seen) == 1 and seen[0].startswith(f"Could not update {other}")


def flaky_ci(repo, replies, after_sleep=None):
    """A ci step whose `gh run list` answers come from `replies`: an exception is raised,
    a list is returned as the runs, "fail" is a non-zero gh."""
    gh = FakeGh([])
    clock = Clock()
    seen = []
    items = iter(replies)

    def run(args, cwd=None, **kw):
        if args[:3] == ["gh", "run", "list"]:
            reply = next(items)
            if isinstance(reply, Exception):
                raise reply
            if reply == "fail":
                return SimpleNamespace(returncode=1, stdout="", stderr="HTTP 502")
            return SimpleNamespace(returncode=0, stdout=json.dumps(reply), stderr="")
        return gh(args, cwd=cwd, **kw)

    def sleep(n):
        clock.sleep(n)
        if after_sleep:
            after_sleep(len(clock.sleeps))

    s = steps(repo, run, sleep=sleep, now=clock.now, on_progress=seen.append)
    return s["ci"], clock, seen


TIMEOUT = subprocess.TimeoutExpired(["gh"], 30)


def test_gh_timeout_is_retried(repo):
    step, clock, seen = flaky_ci(repo, [TIMEOUT, [item("a")]])
    assert step.run(EVENT) is None
    assert clock.sleeps == [15]
    assert "GitHub is slow to answer (1 of 5)" in seen


def test_gh_five_misses_in_a_row_stop(repo):
    step, clock, seen = flaky_ci(repo, [TIMEOUT, OSError("gone"), "fail", TIMEOUT, TIMEOUT])
    with pytest.raises(StepError) as exc:
        step.run(EVENT)
    assert str(exc.value) == (
        "GitHub didn't answer 5 times in a row; check your connection and resume")
    assert "GitHub is slow to answer (2 of 5)" in seen
    assert clock.sleeps == [15] * 4


def test_gh_good_reply_resets_the_count(repo):
    in_progress = [item("a", "in_progress", "")]
    step, _, seen = flaky_ci(repo, [TIMEOUT] * 4 + [in_progress] + [TIMEOUT] * 4 + [[item("a")]])
    assert step.run(EVENT) is None
    assert seen.count("GitHub is slow to answer (4 of 5)") == 2


def test_gh_cancel_during_retries(repo):
    cancel = threading.Event()
    step, clock, _ = flaky_ci(repo, [TIMEOUT, TIMEOUT, TIMEOUT],
                              after_sleep=lambda n: cancel.set() if n == 2 else None)
    assert step.run(cancel) is False
    assert clock.sleeps == [15, 15]
