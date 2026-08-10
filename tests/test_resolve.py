from whyline import events, ledger, paths, resolve


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
