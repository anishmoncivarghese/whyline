from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from whyline.sdlc import close, docset, guard, product, workspace

PLAN = "# Plan\n\n- [x] T-1: Login\n  covers: R1\n"
TESTS = "# Tests\n\n- [x] S-1: [R1] Login works\n  covers: T-1\n  kind: auto\n"
BUILT = (
    "# Build record\n\n## What was built\n\nA login form.\n\n"
    "## Known gaps\n\nNo password reset.\n\n## Other\n\nx\n"
)


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "docs_root", lambda root: tmp_path)
    monkeypatch.setattr(guard, "check", lambda root: None)
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "a@b.c")
    git(tmp_path, "config", "user.name", "a")
    (tmp_path / "a.py").write_text("1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "login.plan.md").write_text(PLAN)
    (tmp_path / "plans" / "login.tests.md").write_text(TESTS)
    made = docset.create(tmp_path, "Login", "small", "auto", roles={"writer": "claude"})
    made.build_base = base
    for doc in made.documents:
        if doc["kind"] != "plan":
            (tmp_path / doc["path"]).write_text(BUILT if doc["kind"] == "build-record" else "# x\n")
    made.document("build-record")["status"] = "approved"
    docset.save(tmp_path, made)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "docs")
    return tmp_path


def test_close_moves_both_files_and_updates_paths(repo):
    result = close.close(repo, "login")
    assert result.done
    assert not (repo / "plans/login.plan.md").exists()
    assert (repo / "plans/done/login.plan.md").read_text() == PLAN
    assert (repo / "plans/done/login.tests.md").read_text() == TESTS
    found = docset.load(repo, "login")
    assert found.document("plan")["path"] == "plans/done/login.plan.md"
    assert git(repo, "log", "-1", "--format=%s") == "docs: close Login"
    assert git(repo, "status", "--porcelain") == ""


def test_close_is_released_with_a_tag_and_built_without(repo):
    assert close.close(repo, "login").state == "built"
    assert docset.load(repo, "login").state == "built"


def test_close_released_records_version_and_tag(repo):
    (repo / "b.py").write_text("2\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "feat")
    git(repo, "tag", "v1.2.0")
    result = close.close(repo, "login")
    assert (result.state, result.tag, result.version) == ("released", "v1.2.0", "1.2.0")
    found = docset.load(repo, "login")
    assert (found.state, found.version, found.tag) == ("released", "1.2.0", "v1.2.0")


def test_close_leaves_no_prd_claim(repo):
    product.claim_update(repo, "login")
    close.close(repo, "login")
    assert product._meta(repo).get("update_claim") is None


def test_close_refuses_an_unapproved_record_and_a_guarded_checkout(repo, monkeypatch):
    found = docset.load(repo, "login")
    found.document("build-record")["status"] = "draft"
    docset.save(repo, found)
    assert "Approve the build record" in close.close(repo, "login").error
    assert (repo / "plans/login.plan.md").exists()
    monkeypatch.setattr(guard, "check", lambda root: "A relay is running.")
    assert close.close(repo, "login").error == "A relay is running."


def test_pr_body_has_summary_table_gaps_and_links(repo):
    close.close(repo, "login")
    body = close.pr_body(repo, repo, docset.load(repo, "login"))
    assert "A login form." in body and "No password reset." in body
    assert "Other" not in body.split("## Known gaps")[1].split("## Documents")[0]
    assert "## Requirements traceability" in body
    assert "(docs/sdlc/login/build-record.md)" in body
    assert "(plans/done/login.plan.md)" in body and "(plans/done/login.tests.md)" in body


class Gh:
    def __init__(self, signed_in=True, create_code=0):
        self.calls = []
        self.signed_in = signed_in
        self.create_code = create_code

    def __call__(self, args, cwd):
        self.calls.append(args)
        if args[:2] == ["auth", "status"]:
            return SimpleNamespace(returncode=0 if self.signed_in else 1, stdout="", stderr="")
        return SimpleNamespace(
            returncode=self.create_code, stdout="https://github.com/o/r/pull/7\n", stderr="denied"
        )


@pytest.fixture
def remote(repo, tmp_path_factory):
    bare = tmp_path_factory.mktemp("remote")
    git(bare, "init", "-q", "--bare")
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "checkout", "-qb", "relay/login.plan")
    return repo, bare


def test_open_pr_pushes_only_the_branch_and_saves_the_url(remote):
    repo, bare = remote
    gh = Gh()
    url = close.open_pr(repo, repo, "login", gh_fn=gh)
    assert url == "https://github.com/o/r/pull/7"
    create = gh.calls[-1]
    assert create[:2] == ["pr", "create"]
    assert create[create.index("--base") + 1] == "main"
    assert create[create.index("--head") + 1] == "relay/login.plan"
    assert create[create.index("--title") + 1] == "Login"
    assert "A login form." in create[create.index("--body") + 1]
    assert git(bare, "branch", "--list").replace("*", "").split() == ["relay/login.plan"]
    assert docset.load(repo, "login").pr_url == url
    assert "pull request opened" in (repo / "docs/sdlc/login/review-log.md").read_text()


def test_open_pr_refuses_without_gh(remote, monkeypatch):
    repo, bare = remote
    def missing(*args, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(close, "subprocess", SimpleNamespace(run=missing))
    with pytest.raises(close.CloseError, match="not installed"):
        close.open_pr(repo, repo, "login")
    assert git(bare, "branch", "--list") == ""


def test_open_pr_refuses_when_not_signed_in(remote):
    repo, bare = remote
    with pytest.raises(close.CloseError, match="not signed in"):
        close.open_pr(repo, repo, "login", gh_fn=Gh(signed_in=False))
    assert git(bare, "branch", "--list") == ""


def test_open_pr_refuses_without_a_remote(repo):
    git(repo, "checkout", "-qb", "relay/login.plan")
    with pytest.raises(close.CloseError, match="no remote"):
        close.open_pr(repo, repo, "login", gh_fn=Gh())


def test_open_pr_never_pushes_the_default_branch(remote):
    repo, bare = remote
    git(repo, "checkout", "-q", "main")
    with pytest.raises(close.CloseError, match="Only the relay branch"):
        close.open_pr(repo, repo, "login", gh_fn=Gh())
    assert git(bare, "branch", "--list") == ""


def test_open_pr_reports_a_refused_pull_request(remote):
    repo, _ = remote
    with pytest.raises(close.CloseError, match="denied"):
        close.open_pr(repo, repo, "login", gh_fn=Gh(create_code=1))
    assert docset.load(repo, "login").pr_url == ""
