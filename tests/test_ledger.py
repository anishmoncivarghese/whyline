import json
import subprocess
from pathlib import Path

import pytest

from whyline import events, ledger, paths


def test_append_creates_parent_directory_and_writes_one_line(tmp_path):
    path = tmp_path / ".whyline" / "ledger.jsonl"
    ledger.append(path, events.new_event(events.NOTE, decision="a"))
    assert path.read_text().count("\n") == 1


def test_append_is_deterministic_and_key_sorted(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(path, {"v": 1, "type": "Note", "id": "x", "ts": "t", "a": 1})
    line = path.read_text().strip()
    assert line == json.dumps(
        {"a": 1, "id": "x", "ts": "t", "type": "Note", "v": 1},
        sort_keys=True,
        separators=(",", ":"),
    )


def test_read_all_returns_events_in_order(tmp_path):
    path = tmp_path / "ledger.jsonl"
    for name in ("first", "second", "third"):
        ledger.append(path, events.new_event(events.NOTE, decision=name))
    found, skipped = ledger.read_all(path)
    assert [event["decision"] for event in found] == ["first", "second", "third"]
    assert skipped == 0


def test_read_all_skips_a_torn_final_line_from_a_crash(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(path, events.new_event(events.NOTE, decision="good"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"v":1,"type":"Not')
    found, skipped = ledger.read_all(path)
    assert [event["decision"] for event in found] == ["good"]
    assert skipped == 1


def test_read_all_on_a_missing_file_is_empty_not_an_error(tmp_path):
    assert ledger.read_all(tmp_path / "absent.jsonl") == ([], 0)


def test_read_all_ignores_blank_lines(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(path, events.new_event(events.NOTE, decision="a"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n\n")
    found, skipped = ledger.read_all(path)
    assert len(found) == 1
    assert skipped == 0


def test_ledger_and_index_are_gitignored_but_decisions_is_not():
    """Verify that ledger and index files are gitignored, but decisions.md is not."""
    repo_root = paths.find_repo_root(Path(__file__))

    # Skip if not in a git repo
    if repo_root is None:
        pytest.skip("not inside a git repository")

    # Check that ledger.jsonl is gitignored
    result = subprocess.run(
        ["git", "check-ignore", "-v", ".whyline/ledger.jsonl"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ledger.jsonl should be gitignored: {result.stdout}"

    # Check that index.db is gitignored
    result = subprocess.run(
        ["git", "check-ignore", "-v", ".whyline/index.db"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"index.db should be gitignored: {result.stdout}"

    # Check that decisions.md is NOT gitignored
    result = subprocess.run(
        ["git", "check-ignore", "-v", ".whyline/decisions.md"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, f"decisions.md should NOT be gitignored but it is: {result.stdout}"


def test_gitignore_test_skips_when_not_in_git_repo(monkeypatch):
    """Verify that the gitignore test gracefully skips when find_repo_root returns None."""
    # Monkeypatch find_repo_root to return None (simulating non-git environment like tarball)
    monkeypatch.setattr(paths, 'find_repo_root', lambda x: None)

    # This should raise pytest.skip.Exception, not TypeError
    with pytest.raises(pytest.skip.Exception):
        test_ledger_and_index_are_gitignored_but_decisions_is_not()
