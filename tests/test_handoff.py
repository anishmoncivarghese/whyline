import json

from whyline import events, handoff, ledger, paths


def test_create_records_explicit_handoff_and_replaces_active_state(repo):
    head = repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)

    record = handoff.create(
        repo.path,
        task="WL-42",
        from_actor="codex",
        to_actor="claude",
        status="ready-for-review",
        summary="Implemented the cache",
        files=["a.py"],
        tests=[{"command": "pytest -q", "result": "passed"}],
        risks=["large repositories untested"],
        questions=["keep the default?"],
        base_commit=head,
        current_commit=head,
    )

    active = json.loads(paths.active_handoff_path(repo.path).read_text())
    found, skipped = ledger.read_all(paths.ledger_path(repo.path))
    assert skipped == 0
    assert active == record
    assert found[-1] == record
    assert record["type"] == events.HANDOFF
    assert record["task"] == "WL-42"
    assert record["from_actor"] == "codex"
    assert record["to_actor"] == "claude"
    assert record["tests"] == [{"command": "pytest -q", "result": "passed"}]
    assert record["base_commit"] == head
    assert record["current_commit"] == head
    assert record["dirty"] is False


def test_create_derives_dirty_files_and_commits_from_git(repo):
    head = repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    paths.ledger_path(repo.path).parent.mkdir(parents=True)
    paths.ledger_path(repo.path).touch()
    (repo.path / "a.py").write_text("two\n", encoding="utf-8")
    (repo.path / "new.py").write_text("new\n", encoding="utf-8")

    record = handoff.create(
        repo.path,
        task="WL-43",
        from_actor="codex",
        to_actor="claude",
        status="review",
    )

    assert record["files"] == ["a.py", "new.py"]
    assert record["base_commit"] == head
    assert record["current_commit"] == head
    assert record["dirty"] is True


def test_parse_test_uses_the_final_colon_as_the_result_separator():
    assert handoff.parse_test("pytest tests/a.py::test_x: passed") == {
        "command": "pytest tests/a.py::test_x",
        "result": "passed",
    }


def test_load_returns_none_when_no_active_handoff_exists(repo):
    assert handoff.load(repo.path) is None
