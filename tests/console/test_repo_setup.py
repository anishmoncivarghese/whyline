import os
import subprocess
from pathlib import Path

import pytest

from whyline.console import repo_setup as rs


def _git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """The plan points HOME at a temp directory. Path.home() ignores HOME
    on Windows, so the check has to follow the env var."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))

    def _home(*_args):
        return Path(os.environ["HOME"])

    monkeypatch.setattr(Path, "home", _home)
    return h


def _fake_init(root):
    """Stands in for `whyline init`: what it writes, including an ignored file."""
    (root / ".whyline").mkdir(exist_ok=True)
    (root / ".whyline/.gitignore").write_text("ledger.jsonl\n")
    (root / ".whyline/ledger.jsonl").write_text("")
    (root / "AGENTS.md").write_text("# agents\n")


@pytest.fixture(autouse=True)
def stub_whyline_init(monkeypatch):
    monkeypatch.setattr(rs, "_whyline_init", _fake_init)


@pytest.fixture(autouse=True)
def git_identity(monkeypatch):
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "T")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "t@example.com")


def test_home_and_nested_paths_are_refused(home, tmp_path):
    assert rs.inspect(home).kind == "home"
    outer = tmp_path / "outer"
    (outer / "sub").mkdir(parents=True)
    _git(outer, "init", "-q")
    got = rs.inspect(outer / "sub")
    assert got.kind == "nested" and got.outer == outer.resolve()


def test_a_missing_folder_needs_every_step(tmp_path):
    got = rs.inspect(tmp_path / "new")
    assert got.kind == "needs_setup" and got.missing == ("folder", "git", "whyline", "agents")
    assert "create the folder" in rs.describe(got) and "git init" in rs.describe(got)


def test_setup_creates_repo_and_commits_only_its_own_files(tmp_path, monkeypatch):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "notes.txt").write_text("the user's, uncommitted")
    lines = []

    def fake_prepare(root, agents):
        settings = root / ".whyline/relay/claude-settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("{}")
        return [settings]

    monkeypatch.setattr(rs, "_prepare_agents", fake_prepare)
    root = rs.setup(rs.inspect(target), agents=["claude"], progress=lines.append)
    assert root == target.resolve()
    committed = _git(root, "show", "--name-only", "--format=", "HEAD").split()
    assert "notes.txt" not in committed and ".whyline/relay/claude-settings.json" in committed
    assert _git(root, "log", "-1", "--format=%s").strip() == "chore: set up whyline"
    assert "notes.txt" in _git(root, "status", "--porcelain")
    assert rs.inspect(root).kind == "ready"
    assert "run git init" in lines


def test_a_failed_step_is_named_and_a_retry_finishes(tmp_path, monkeypatch):
    target = tmp_path / "proj2"
    calls = {"n": 0}

    def flaky(root):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        _fake_init(root)

    monkeypatch.setattr(rs, "_whyline_init", flaky)
    monkeypatch.setattr(rs, "_prepare_agents", lambda root, agents: [])
    with pytest.raises(rs.SetupError) as failed:
        rs.setup(rs.inspect(target), agents=[], progress=lambda l: None)
    assert failed.value.step == "whyline"
    assert rs.inspect(target).missing == ("whyline", "agents")
    rs.setup(rs.inspect(target), agents=[], progress=lambda l: None)
    assert rs.inspect(target).kind == "ready"


def test_a_whyline_init_that_leaves_dot_whyline_is_rerun(tmp_path, monkeypatch):
    target = tmp_path / "proj3"
    calls = {"n": 0}

    def flaky(root):
        calls["n"] += 1
        if calls["n"] == 1:
            (root / ".whyline").mkdir()
            raise OSError("disk full")
        _fake_init(root)

    monkeypatch.setattr(rs, "_whyline_init", flaky)
    monkeypatch.setattr(rs, "_prepare_agents", lambda root, agents: [])
    with pytest.raises(rs.SetupError) as failed:
        rs.setup(rs.inspect(target), agents=[], progress=lambda _line: None)
    assert failed.value.step == "whyline"
    assert rs.inspect(target).missing == ("whyline", "agents")
    rs.setup(rs.inspect(target), agents=[], progress=lambda _line: None)
    assert calls["n"] == 2
    assert rs.inspect(target).kind == "ready"


def test_an_existing_repo_keeps_the_users_uncommitted_files(tmp_path, monkeypatch):
    target = tmp_path / "existing"
    target.mkdir()
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "t@example.com")
    _git(target, "config", "user.name", "T")
    (target / "README.md").write_text("shipped\n")
    _git(target, "add", "README.md")
    _git(target, "commit", "-qm", "initial")
    (target / "notes.txt").write_text("still mine\n")

    def fake_prepare(root, agents):
        settings = root / ".whyline/relay/claude-settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("{}\n")
        return [settings]

    monkeypatch.setattr(rs, "_prepare_agents", fake_prepare)
    root = rs.setup(rs.inspect(target), agents=["claude"], progress=lambda _line: None)
    committed = _git(root, "show", "--name-only", "--format=", "HEAD").split()
    assert "notes.txt" not in committed and "README.md" not in committed
    assert ".whyline/relay/claude-settings.json" in committed
    assert _git(root, "log", "-1", "--format=%s").strip() == "chore: set up whyline"
    assert "notes.txt" in _git(root, "status", "--porcelain")
    assert _git(root, "log", "--format=%s").splitlines()[-1] == "initial"


def _tracked(root):
    return _git(root, "ls-files").split()


def test_an_agents_step_that_writes_then_fails_is_rerun_and_committed(tmp_path, monkeypatch):
    # Codex's CB-2 round-6 defect: a surviving agents-phase marker means
    # preparation has not returned, even when claude-settings.json already
    # exists. Retry must run agents again (prepare_agents will not overwrite)
    # and still commit every file the failed attempt wrote.
    target = tmp_path / "agents-fail"
    calls = {"n": 0}

    def prepare(root, agents):
        calls["n"] += 1
        settings = root / ".whyline/relay/claude-settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        if calls["n"] == 1:
            settings.write_text("{}\n")
            raise OSError("the second agent's file failed")
        return [settings]

    monkeypatch.setattr(rs, "_prepare_agents", prepare)
    with pytest.raises(rs.SetupError) as failed:
        rs.setup(rs.inspect(target), agents=["claude", "grok"], progress=lambda _l: None)
    assert failed.value.step == "agents"
    assert (target / ".whyline/relay/claude-settings.json").is_file()
    assert rs.inspect(target).missing == ("agents",)
    rs.setup(rs.inspect(target), agents=["claude", "grok"], progress=lambda _l: None)
    assert calls["n"] == 2
    assert rs.inspect(target).kind == "ready"
    assert ".whyline/relay/claude-settings.json" in _tracked(target)
    assert _git(target, "status", "--porcelain", "--untracked-files=all") == ""


def test_a_surviving_agents_phase_marker_is_unfinished(tmp_path, monkeypatch):
    # The previous setup wrote `.git/whyline-agents-pending` with phase
    # "agents", then created claude-settings.json and stopped. Inspect must
    # not treat that file as proof the step finished.
    target = tmp_path / "legacy-marker"
    target.mkdir()
    _git(target, "init", "-q", "-b", "main")
    settings = target / ".whyline/relay/claude-settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("{}\n")
    (target / ".git" / "whyline-agents-pending").write_text("agents\n")
    calls = {"n": 0}

    def prepare(root, agents):
        calls["n"] += 1
        return [settings]

    monkeypatch.setattr(rs, "_prepare_agents", prepare)
    got = rs.inspect(target)
    assert got.kind == "needs_setup" and got.missing == ("agents",)
    rs.setup(got, agents=["claude"], progress=lambda _l: None)
    assert calls["n"] == 1
    assert rs.inspect(target).kind == "ready"
    assert ".whyline/relay/claude-settings.json" in _tracked(target)
    assert not (target / ".git" / "whyline-agents-pending").exists()


def test_files_a_failed_whyline_init_wrote_are_committed_by_the_retry(tmp_path, monkeypatch):
    target = tmp_path / "init-fail"
    calls = {"n": 0}

    def flaky(root):
        calls["n"] += 1
        _fake_init(root)
        if calls["n"] == 1:
            raise subprocess.CalledProcessError(1, ["whyline", "init"])

    monkeypatch.setattr(rs, "_whyline_init", flaky)
    monkeypatch.setattr(rs, "_prepare_agents", lambda root, agents: [])
    with pytest.raises(rs.SetupError):
        rs.setup(rs.inspect(target), agents=[], progress=lambda _l: None)
    assert rs.inspect(target).missing == ("whyline", "agents")
    rs.setup(rs.inspect(target), agents=[], progress=lambda _l: None)
    assert calls["n"] == 2
    tracked = _tracked(target)
    assert "AGENTS.md" in tracked and ".whyline/.gitignore" in tracked
    assert ".whyline/ledger.jsonl" not in tracked  # ignored by init's own gitignore
    assert rs.inspect(target).kind == "ready"


def test_a_failed_setup_never_commits_the_users_files(tmp_path, monkeypatch):
    target = tmp_path / "mine"
    target.mkdir()
    (target / "notes.txt").write_text("the user's\n")

    def prepare(root, agents):
        raise OSError("boom")

    monkeypatch.setattr(rs, "_prepare_agents", prepare)
    with pytest.raises(rs.SetupError):
        rs.setup(rs.inspect(target), agents=["claude"], progress=lambda _l: None)
    assert "notes.txt" not in _tracked(target)
    assert "notes.txt" in _git(target, "status", "--porcelain")
