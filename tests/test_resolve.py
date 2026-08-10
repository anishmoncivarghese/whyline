import pytest

from whyline import events, gitq, ledger, paths, resolve


def add_note(repo, decision: str, files: list[str], ts: str):
    event = events.new_event(events.NOTE, decision=decision, files=files, because="")
    event["ts"] = ts
    ledger.append(paths.ledger_path(repo.path), event)


def iso(epoch: int) -> str:
    from datetime import datetime, timezone

    return (
        datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[
            :-3
        ]
        + "Z"
    )


def test_high_confidence_for_exactly_one_note_in_the_window(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    add_note(repo, "chose redis", ["a.py"], iso(1_500_000))
    repo.commit({"a.py": "one\ntwo\n"}, "second", epoch=2_000_000)
    result = resolve.explain(repo.path, "a.py", 2)
    assert result.confidence == "high"
    assert [note["decision"] for note in result.notes] == ["chose redis"]


def test_medium_confidence_when_several_notes_fall_in_the_window(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    add_note(repo, "first choice", ["a.py"], iso(1_400_000))
    add_note(repo, "second choice", ["a.py"], iso(1_600_000))
    repo.commit({"a.py": "one\ntwo\n"}, "second", epoch=2_000_000)
    result = resolve.explain(repo.path, "a.py", 2)
    assert result.confidence == "medium"
    assert len(result.notes) == 2


def test_medium_confidence_and_moved_by_when_the_note_predates_the_window(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    add_note(repo, "original reasoning", ["a.py"], iso(900_000))
    repo.commit({"a.py": "one\ntwo\n"}, "second", epoch=2_000_000)
    moving = repo.commit({"a.py": "one\n  two\n"}, "reformat", epoch=3_000_000)
    result = resolve.explain(repo.path, "a.py", 2)
    assert result.confidence == "medium"
    assert result.moved_by == moving
    assert [note["decision"] for note in result.notes] == ["original reasoning"]


def test_low_confidence_when_only_mechanical_events_exist(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    event = events.new_event(events.FILE_TOUCHED, path="a.py", tool="Edit")
    ledger.append(paths.ledger_path(repo.path), event)
    result = resolve.explain(repo.path, "a.py", 1)
    assert result.confidence == "low"
    assert result.notes == []


def test_no_confidence_when_nothing_is_recorded(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    result = resolve.explain(repo.path, "a.py", 1)
    assert result.confidence == "none"
    assert result.blame is not None


def test_no_confidence_for_uncommitted_lines(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    (repo.path / "a.py").write_text("one\nbrand new\n", encoding="utf-8")
    result = resolve.explain(repo.path, "a.py", 2)
    assert result.confidence == "none"
    assert "uncommitted" in result.reason


def test_file_level_explain_without_a_line_uses_all_notes_for_the_path(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    add_note(repo, "file level", ["a.py"], iso(1_500_000))
    result = resolve.explain(repo.path, "a.py", None)
    assert [note["decision"] for note in result.notes] == ["file level"]


def test_untracked_file_reports_no_blame_but_still_returns(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    (repo.path / "new.py").write_text("x\n", encoding="utf-8")
    result = resolve.explain(repo.path, "new.py", 1)
    assert result.blame is None
    assert result.confidence == "none"


# --- Fix round 1: anti-over-claim regression coverage (review findings 1-4) ---


def test_file_level_confidence_never_reaches_high_with_one_note(repo):
    """Finding 1: HIGH is defined as one note inside a *blamed commit's* window.
    With no line there is no blamed commit, so HIGH must be unreachable even
    when exactly one note exists for the path."""
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    add_note(repo, "solo decision", ["a.py"], iso(1_500_000))
    result = resolve.explain(repo.path, "a.py", None)
    assert result.confidence == "medium"


def test_file_level_on_path_not_in_git_does_not_invoke_git_or_claim_high(
    repo, monkeypatch
):
    """Finding 1 (b): file-level explain must not consult git at all, and a
    single note for a path git has never seen must not produce HIGH."""

    def fail_if_called(*args, **kwargs):
        raise AssertionError("blame_line must not be called for file-level explain")

    monkeypatch.setattr(resolve.gitq, "blame_line", fail_if_called)
    add_note(repo, "solo decision", ["missing.py"], iso(1_000_000))
    result = resolve.explain(repo.path, "missing.py", None)
    assert result.confidence != "high"


def test_note_after_blamed_commit_is_excluded_from_window(repo):
    """A note timestamped after the commit that wrote the line cannot be the
    reasoning behind that commit, so it must never yield high or medium."""
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    add_note(repo, "too late", ["a.py"], iso(2_000_000))
    result = resolve.explain(repo.path, "a.py", 1)
    assert result.confidence not in ("high", "medium")
    assert result.moved_by is None
    assert [note["decision"] for note in result.notes] == []


def test_note_for_a_different_path_is_excluded(repo):
    """A note recorded against another file must never leak into this file's
    explanation, however it happens to be timestamped."""
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    add_note(repo, "about b, not a", ["b.py"], iso(1_000_000))
    result = resolve.explain(repo.path, "a.py", 1)
    assert result.notes == []
    assert result.confidence != "high"


def test_note_with_empty_files_list_is_excluded(repo):
    """A note with an empty files list mentions nothing, so it must not be
    attributed to any path."""
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    add_note(repo, "orphaned note", [], iso(1_000_000))
    result = resolve.explain(repo.path, "a.py", 1)
    assert result.notes == []


def test_git_unavailable_propagates_from_explain(repo, monkeypatch):
    """Git is authoritative: if git itself is broken, explain must surface
    that loudly rather than silently reporting 'none'."""

    def boom(*args, **kwargs):
        raise gitq.GitUnavailable("git is not installed or not on PATH")

    monkeypatch.setattr(resolve.gitq, "blame_line", boom)
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    with pytest.raises(gitq.GitUnavailable):
        resolve.explain(repo.path, "a.py", 1)


def test_non_string_timestamp_does_not_crash_and_reports_unplaceable(repo):
    """Finding 2/3: a malformed ts (e.g. an int instead of a string) must not
    crash the read, and the resulting explanation must not falsely claim
    'no reasoning recorded' when reasoning does exist but can't be placed
    in time."""
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    event = events.new_event(
        events.NOTE, decision="weird timestamp", files=["a.py"], because=""
    )
    event["ts"] = 123
    ledger.append(paths.ledger_path(repo.path), event)
    result = resolve.explain(repo.path, "a.py", 1)
    assert result.confidence == "low"
    assert "unreadable" in result.reason
