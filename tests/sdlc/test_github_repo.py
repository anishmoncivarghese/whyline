from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from whyline.release.ready import Result
from whyline.sdlc import docset as docset_mod
from whyline.sdlc import github_repo, runner


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.txt").write_text("a")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-m", "init")
    docset_mod.create(root, "Login", "feature", "human", roles={"implementer": "claude"})
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "set")
    return root


def _stub(calls, *, gh=0, origin="", create=0, url="https://github.com/me/login\n"):
    def run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["gh", "--version"] or args[:2] == ["gh", "auth"]:
            return Result(gh)
        if args[:3] == ["git", "remote", "get-url"]:
            return Result(0 if origin else 2, origin + "\n" if origin else "")
        if args[:3] == ["gh", "repo", "create"]:
            return Result(create, url if create == 0 else "", "" if create == 0 else "name taken\nmore")
        if args[:2] == ["gh", "api"]:
            return Result(0, "me\n")
        raise AssertionError(args)
    return run


def _creates(calls):
    return [c for c in calls if c[:3] == ["gh", "repo", "create"]]


def test_describe_text():
    assert (github_repo.describe("me", "login", True)
            == "Create github.com/me/login (private), add it as origin, and push main?")
    assert github_repo.describe("me", "login", False).endswith("(public), add it as origin, and push main?")


def test_gh_ready_none_and_fix_text():
    assert github_repo.gh_ready("/x", run=_stub([])) is None
    assert github_repo.gh_ready("/x", run=_stub([], gh=1)) is not None

    def signed_out(args, **kwargs):
        return Result(1 if args[:2] == ["gh", "auth"] else 0)
    assert github_repo.gh_ready("/x", run=signed_out) == "Run: gh auth login"


def test_default_owner():
    assert github_repo.default_owner("/x", run=_stub([])) == "me"
    assert github_repo.default_owner("/x", run=lambda a, **k: Result(1)) is None


def test_private_is_the_default(repo):
    calls = []
    url = github_repo.create_repo(repo, owner="me", name="login", run=_stub(calls))
    assert url == "https://github.com/me/login"
    (call,) = _creates(calls)
    assert call == ["gh", "repo", "create", "me/login", "--private", "--source", str(repo),
                    "--remote", "origin", "--push"]


def test_public_argument(repo):
    calls = []
    github_repo.create_repo(repo, owner="me", name="login", private=False, run=_stub(calls))
    (call,) = _creates(calls)
    assert "--public" in call and "--private" not in call


def test_saves_url_and_logs(repo):
    github_repo.create_repo(repo, owner="me", name="login", private=False, run=_stub([]))
    folder = repo / docset_mod.SDLC_DIR / "login"
    data = json.loads((folder / docset_mod.MANIFEST).read_text())
    assert data["github"] == {"url": "https://github.com/me/login", "private": False}
    assert "GitHub repository created: https://github.com/me/login" in (
        folder / docset_mod.REVIEW_LOG).read_text()
    assert _git(repo, "status", "--porcelain").strip() == ""
    assert "GitHub repository created" in _git(repo, "log", "-1", "--format=%s")


def test_refuses_when_gh_not_ready(repo):
    calls = []
    with pytest.raises(github_repo.GithubRepoError):
        github_repo.create_repo(repo, owner="me", name="login", run=_stub(calls, gh=1))
    assert not _creates(calls)


def test_refuses_existing_origin(repo):
    calls = []
    with pytest.raises(github_repo.GithubRepoError,
                       match="This project already has a remote: git@github.com:a/b.git"):
        github_repo.create_repo(repo, owner="me", name="login",
                                run=_stub(calls, origin="git@github.com:a/b.git"))
    assert not _creates(calls)


@pytest.mark.parametrize("name", ["", "   "])
def test_refuses_empty_name(repo, name):
    calls = []
    with pytest.raises(github_repo.GithubRepoError):
        github_repo.create_repo(repo, owner="me", name=name, run=_stub(calls))
    assert not _creates(calls)


def test_create_failure_saves_nothing(repo):
    with pytest.raises(github_repo.GithubRepoError, match="name taken"):
        github_repo.create_repo(repo, owner="me", name="login", run=_stub([], create=1))
    data = json.loads((repo / docset_mod.SDLC_DIR / "login" / docset_mod.MANIFEST).read_text())
    assert "github" not in data


def test_runner_run_never_calls_it(repo, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("create_repo must only be called by a user action")
    monkeypatch.setattr(github_repo, "create_repo", boom)
    assert "github_repo" not in Path(runner.__file__).read_text()
    for mode in ("human", "auto"):
        docset = docset_mod.load(repo, "login")
        docset.mode = mode
        docset_mod.save(repo, docset)
        try:
            runner.run(repo, "login", launcher=lambda *a, **k: None)
        except AssertionError:
            raise
        except Exception:
            pass
