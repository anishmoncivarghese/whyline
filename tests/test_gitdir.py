import subprocess

from whyline import gitdir
from whyline.release import config, state


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _repo_with_worktree(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "commit", "-q", "--allow-empty", "-m", "first")
    other = tmp_path / "other"
    _git(main, "worktree", "add", "-q", "-b", "side", str(other))
    return main, other


def test_plain_checkout_uses_its_git_folder(tmp_path):
    main, _ = _repo_with_worktree(tmp_path)
    assert gitdir.git_dir(main) == main / ".git"


def test_worktree_follows_its_git_file(tmp_path):
    main, other = _repo_with_worktree(tmp_path)
    assert (other / ".git").is_file()
    found = gitdir.git_dir(other)
    assert found.is_dir()
    assert found.resolve() == (main / ".git" / "worktrees" / "other").resolve()


def test_relative_gitdir_line_is_read_from_the_checkout(tmp_path):
    real = tmp_path / "store" / "wt"
    real.mkdir(parents=True)
    checkout = tmp_path / "co"
    checkout.mkdir()
    (checkout / ".git").write_text("gitdir: ../store/wt\n", encoding="utf-8")
    assert gitdir.git_dir(checkout).resolve() == real.resolve()


def test_no_git_falls_back_to_dot_git(tmp_path):
    assert gitdir.git_dir(tmp_path) == tmp_path / ".git"


def test_release_state_saves_in_a_worktree(tmp_path):
    # v0.3.78 crashed here: NotADirectoryError on <worktree>/.git/whyline-release.
    _, other = _repo_with_worktree(tmp_path)
    assert state.path(other).parent == gitdir.git_dir(other) / "whyline-release"
    state.path(other).parent.mkdir(parents=True, exist_ok=True)
    assert config._pending_file(other).parent == state.path(other).parent
