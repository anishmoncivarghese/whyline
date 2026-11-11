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
