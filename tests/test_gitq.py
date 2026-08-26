import pytest

from whyline import gitq

UNCOMMITTED_SHA = "0" * 40


def test_blame_line_reports_sha_author_and_epoch(repo):
    sha = repo.commit({"a.py": "one\ntwo\n"}, "add a", epoch=1_000_000)
    blame = gitq.blame_line(repo.path, "a.py", 2)
    assert blame is not None
    assert blame.sha == sha
    assert blame.author == "Test"
    assert blame.epoch == 1_000_000
    assert blame.committed is True


def test_blame_line_attributes_to_the_commit_that_changed_that_line(repo):
    repo.commit({"a.py": "one\ntwo\n"}, "first", epoch=1_000_000)
    second = repo.commit({"a.py": "one\nCHANGED\n"}, "second", epoch=2_000_000)
    blame = gitq.blame_line(repo.path, "a.py", 2)
    assert blame.sha == second
    assert blame.epoch == 2_000_000


def test_blame_line_marks_uncommitted_work_as_not_committed(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    (repo.path / "a.py").write_text("one\nbrand new\n", encoding="utf-8")
    blame = gitq.blame_line(repo.path, "a.py", 2)
    assert blame.committed is False
    assert blame.sha == UNCOMMITTED_SHA


def test_blame_line_returns_none_for_an_untracked_file(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    (repo.path / "untracked.py").write_text("x\n", encoding="utf-8")
    assert gitq.blame_line(repo.path, "untracked.py", 1) is None


def test_blame_line_returns_none_past_end_of_file(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    assert gitq.blame_line(repo.path, "a.py", 99) is None


def test_commits_touching_returns_newest_first(repo):
    first = repo.commit({"a.py": "1\n"}, "first", epoch=1_000_000)
    second = repo.commit({"a.py": "2\n"}, "second", epoch=2_000_000)
    repo.commit({"other.py": "x\n"}, "unrelated", epoch=3_000_000)
    assert gitq.commits_touching(repo.path, "a.py") == [
        (second, 2_000_000),
        (first, 1_000_000),
    ]


def test_previous_commit_epoch_finds_the_prior_change_to_that_path(repo):
    repo.commit({"a.py": "1\n"}, "first", epoch=1_000_000)
    second = repo.commit({"a.py": "2\n"}, "second", epoch=2_000_000)
    assert gitq.previous_commit_epoch(repo.path, "a.py", second) == 1_000_000


def test_previous_commit_epoch_is_none_for_the_first_commit(repo):
    first = repo.commit({"a.py": "1\n"}, "first", epoch=1_000_000)
    assert gitq.previous_commit_epoch(repo.path, "a.py", first) is None


def test_git_queries_raise_outside_a_repository(tmp_path):
    with pytest.raises(gitq.GitUnavailable):
        gitq.commits_touching(tmp_path, "a.py")


def test_blame_line_raises_when_git_binary_is_missing(repo, monkeypatch):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(gitq.subprocess, "run", fake_run)
    with pytest.raises(gitq.GitUnavailable):
        gitq.blame_line(repo.path, "a.py", 1)


def test_blame_line_raises_when_directory_is_not_a_repository(tmp_path):
    (tmp_path / "a.py").write_text("one\n", encoding="utf-8")
    with pytest.raises(gitq.GitUnavailable):
        gitq.blame_line(tmp_path, "a.py", 1)


def test_commits_touching_follows_renames(repo):
    first = repo.commit({"a.py": "1\n"}, "first", epoch=1_000_000)
    (repo.path / "a.py").unlink()
    second = repo.commit({"b.py": "1\n"}, "rename a to b", epoch=2_000_000)
    assert gitq.commits_touching(repo.path, "b.py") == [
        (second, 2_000_000),
        (first, 1_000_000),
    ]
    assert gitq.previous_commit_epoch(repo.path, "b.py", second) == 1_000_000


def test_changed_paths_reports_rename_destination_once(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    repo._git("mv", "a.py", "b.py")

    assert gitq.changed_paths(repo.path) == ["b.py"]


def test_changed_paths_excludes_checkout_local_whyline_state(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    directory = repo.path / ".whyline"
    directory.mkdir()
    (directory / "ledger.jsonl").write_text("event\n")
    (directory / "active-handoff.json").write_text("{}\n")
    (directory / "decisions.md").write_text("# Decisions\n")

    assert gitq.changed_paths(repo.path) == [".whyline/decisions.md"]
