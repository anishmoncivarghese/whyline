import subprocess
from pathlib import Path

from whyline.release import config
from whyline.release.config import ReleaseConfig
from whyline.release.ready import default_run
from whyline.release.source import Source, source

MARKER = "<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-11T09:00:00+05:30 -->\n"


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root, check=True, capture_output=True,
    )


def commit(root: Path, name: str) -> None:
    (root / name).write_text(name)
    git(root, "add", name)
    git(root, "commit", "-m", name)


def make_repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    commit(root, "a")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "origin", "main")
    return root


def no_fetch(root, branch):
    pass


def run_source(root: Path, fetch=no_fetch) -> Source:
    return source(root, ReleaseConfig(), run=default_run, fetch=fetch)


def write_plan(root: Path, name: str, *states: str, folder: str = "plans") -> Path:
    path = root / folder / f"{name}.plan.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"- [{s}] T-{i}: task {i}" for i, s in enumerate(states, 1)]
    path.write_text(MARKER + "# Plan\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_on_main(tmp_path):
    root = make_repo(tmp_path)
    src = run_source(root)
    assert (src.branch, src.on_release_branch, src.ahead, src.behind) == ("main", True, 0, 0)
    assert src.line() == "Releasing main"


def test_branch_ahead_only(tmp_path):
    root = make_repo(tmp_path)
    git(root, "checkout", "-b", "relay/x")
    commit(root, "b")
    commit(root, "c")
    src = run_source(root)
    assert (src.branch, src.on_release_branch, src.ahead, src.behind) == ("relay/x", False, 2, 0)
    assert src.line() == "Releasing relay/x · 2 commits"


def test_ahead_and_behind_after_fetch(tmp_path):
    root = make_repo(tmp_path)
    git(root, "checkout", "-b", "relay/x")
    commit(root, "b")
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(tmp_path / "remote.git"), str(other)], check=True, capture_output=True)
    commit(other, "m1")
    commit(other, "m2")
    git(other, "push", "origin", "main")
    fetched = []

    def fetch(r, branch):
        fetched.append(branch)
        git(r, "fetch", "origin", branch)

    assert run_source(root).behind == 0  # nothing fetched yet
    src = run_source(root, fetch)
    assert fetched == ["main"]
    assert (src.ahead, src.behind) == (1, 2)
    assert src.line() == "Releasing relay/x · 1 commits · main has 2 commits this branch doesn't"


def test_finished_plans_ignore_done_folder_and_unfinished(tmp_path):
    root = make_repo(tmp_path)
    finished = write_plan(root, "finished", "x", "x")
    write_plan(root, "partial", "x", " ")
    write_plan(root, "archived", "x", folder="plans/done")
    assert run_source(root).finished_plans == (finished,)


def test_custom_branch(tmp_path):
    root = make_repo(tmp_path)
    git(root, "checkout", "-b", "trunk")
    git(root, "push", "origin", "trunk")
    src = source(root, ReleaseConfig(branch="trunk"), run=default_run, fetch=no_fetch)
    assert src.on_release_branch and src.line() == "Releasing trunk"


def test_config_key_round_trip(tmp_path):
    config.save(tmp_path, ReleaseConfig(bring_in_main=False))
    assert config.load(tmp_path).bring_in_main is False


# --- bring_in_main -------------------------------------------------------

import pytest  # noqa: E402

from whyline.release import plan as release_plan  # noqa: E402
from whyline.release.github import StepError  # noqa: E402
from whyline.release.source import bring_in_main  # noqa: E402

IDLE = lambda root: False  # noqa: E731


@pytest.fixture(autouse=True)
def _identity(monkeypatch):
    for key, value in (("GIT_AUTHOR_NAME", "t"), ("GIT_COMMITTER_NAME", "t"),
                       ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(key, value)


def real_fetch(root, branch):
    git(root, "fetch", "origin", branch)


def push_to_main(tmp_path: Path, name: str, text: str | None = None) -> None:
    other = tmp_path / f"other-{name}"
    subprocess.run(["git", "clone", str(tmp_path / "remote.git"), str(other)],
                   check=True, capture_output=True)
    (other / name).write_text(text or name)
    git(other, "add", name)
    git(other, "commit", "-m", name)
    git(other, "push", "origin", "main")


def bring(root, **kw):
    kw.setdefault("relay_running", IDLE)
    return bring_in_main(root, ReleaseConfig(), "1.2.3", run=default_run, fetch=real_fetch, **kw)


def test_clean_merge_then_checks_see_merged_file(tmp_path):
    root = make_repo(tmp_path)
    git(root, "checkout", "-b", "relay/x")
    commit(root, "b")
    push_to_main(tmp_path, "m1")
    seen = []
    summary = bring(root)
    seen.append((root / "m1").is_file())  # a check running after the step
    assert seen == [True] and "merged 1 commits" in summary
    log = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=root,
                         capture_output=True, text=True).stdout.strip()
    assert log == "merge: bring main into relay/x for v1.2.3"


def test_conflict_aborts_and_names_files(tmp_path):
    root = make_repo(tmp_path)
    git(root, "checkout", "-b", "relay/x")
    (root / "a").write_text("branch side")
    git(root, "commit", "-am", "branch edit")
    push_to_main(tmp_path, "a", "main side")
    with pytest.raises(StepError) as err:
        bring(root)
    assert str(err.value) == (
        "Merge main into relay/x yourself (or ask an agent), then resume the release. "
        "Conflicts: a")
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                            capture_output=True, text=True).stdout
    assert status == ""


def test_refused_while_relay_runs(tmp_path):
    root = make_repo(tmp_path)
    git(root, "checkout", "-b", "relay/x")
    with pytest.raises(StepError, match="A relay is running here; release when it finishes"):
        bring(root, relay_running=lambda r: True)


def test_dirty_tree_refused(tmp_path):
    root = make_repo(tmp_path)
    git(root, "checkout", "-b", "relay/x")
    (root / "loose.txt").write_text("x")
    with pytest.raises(StepError, match="Commit or stash these first: loose.txt"):
        bring(root)


def test_plans_moved_and_committed(tmp_path):
    root = make_repo(tmp_path)
    git(root, "checkout", "-b", "relay/x")
    write_plan(root, "finished", "x", "x")
    (root / "plans" / "finished.tests.md").write_text("tests")
    git(root, "add", "-A")
    git(root, "commit", "-m", "plan")
    bring(root)
    assert (root / "plans/done/finished.plan.md").is_file()
    assert (root / "plans/done/finished.tests.md").is_file()
    assert not (root / "plans/finished.plan.md").exists()
    log = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=root,
                         capture_output=True, text=True).stdout.strip()
    assert log == "chore: move finished plans to plans/done"


def test_unfinished_plan_stays(tmp_path):
    root = make_repo(tmp_path)
    git(root, "checkout", "-b", "relay/x")
    write_plan(root, "partial", "x", " ")
    git(root, "add", "-A")
    git(root, "commit", "-m", "plan")
    bring(root)
    assert (root / "plans/partial.plan.md").is_file()


def build_plan(root, cfg=None):
    return release_plan.build(root, cfg or ReleaseConfig(), "1.2.3", fetch=real_fetch,
                              relay_running=IDLE)


def test_step_absent_on_release_branch_and_when_off(tmp_path):
    root = make_repo(tmp_path)
    assert "bring-in-main" not in [s.id for s in build_plan(root).steps]
    git(root, "checkout", "-b", "relay/x")
    assert build_plan(root).steps[0].id == "bring-in-main"
    off = build_plan(root, ReleaseConfig(bring_in_main=False))
    assert "bring-in-main" not in [s.id for s in off.steps]


def test_step_is_irreversible_and_done_skips_resumed_run(tmp_path):
    root = make_repo(tmp_path)
    git(root, "checkout", "-b", "relay/x")
    step = build_plan(root).steps[0]
    assert (step.title, step.irreversible) == ("Bring in main", True)
    assert step.done_check() is True
    push_to_main(tmp_path, "m1")
    assert step.done_check() is False
    step.run(None)
    assert step.done_check() is True


def test_confirmation_text(tmp_path):
    root = make_repo(tmp_path)
    git(root, "checkout", "-b", "relay/x")
    write_plan(root, "finished", "x")
    git(root, "add", "-A")
    git(root, "commit", "-m", "plan")
    text = release_plan.bring_confirmation(root, ReleaseConfig(), fetch=real_fetch)
    assert text == "Releasing relay/x · 1 commits\nMoves to plans/done: finished.plan.md"


def test_default_relay_check_propagates_errors(tmp_path, monkeypatch):
    from whyline_relay import running

    root = make_repo(tmp_path)

    def boom(r):
        raise OSError("state unreadable")

    monkeypatch.setattr(running, "live", boom)
    with pytest.raises(OSError):
        bring_in_main(root, ReleaseConfig(), "1.2.3", run=default_run, fetch=real_fetch)


def test_default_relay_check_refuses_live_relay(tmp_path, monkeypatch):
    from whyline_relay import running

    root = make_repo(tmp_path)
    monkeypatch.setattr(running, "live", lambda r: object())
    with pytest.raises(StepError, match="relay is running"):
        bring_in_main(root, ReleaseConfig(), "1.2.3", run=default_run, fetch=real_fetch)


def test_probe_failure_cannot_remove_the_step(tmp_path):
    root = make_repo(tmp_path)
    git(root, "checkout", "-b", "relay/x")

    def bad_fetch(r, branch):
        raise RuntimeError("no remote")

    plan = release_plan.build(root, ReleaseConfig(), "1.2.3", fetch=bad_fetch,
                              relay_running=IDLE)
    step = plan.steps[0]
    assert step.id == "bring-in-main"
    assert step.done_check() is False
