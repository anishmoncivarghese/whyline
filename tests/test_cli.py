import pytest

from whyline import cli


def test_version_flag_succeeds(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == cli.EXIT_OK
    assert "0.1.0" in capsys.readouterr().out


def test_unknown_command_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["nonsense"])
    assert exit_info.value.code == cli.EXIT_USAGE


def test_no_command_is_a_usage_error():
    assert cli.main([]) == cli.EXIT_USAGE


import json
import os

from whyline import cli, events, ledger, paths


def run_in(repo, argv, capsys):
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        code = cli.main(argv)
    finally:
        os.chdir(previous)
    return code, capsys.readouterr().out


def test_explain_reports_no_record_when_the_ledger_is_empty(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    paths.ledger_path(repo.path).parent.mkdir(parents=True)
    paths.ledger_path(repo.path).touch()
    code, out = run_in(repo, ["explain", "a.py:1"], capsys)
    assert code == cli.EXIT_OK
    assert "no reasoning recorded" in out.lower()


def test_explain_json_includes_confidence_and_path(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    paths.ledger_path(repo.path).parent.mkdir(parents=True)
    paths.ledger_path(repo.path).touch()
    code, out = run_in(repo, ["explain", "a.py:1", "--json"], capsys)
    assert code == cli.EXIT_OK
    payload = json.loads(out)
    assert payload["confidence"] == "none"
    assert payload["path"] == "a.py"
    assert payload["line"] == 1


def test_explain_shows_the_decision_and_rejected_alternatives(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    event = events.new_event(
        events.NOTE,
        decision="Use Redis with a 30-second key",
        because="responses are user-specific",
        alternatives=[{"option": "in-memory LRU", "why_not": "lost on deploy"}],
        files=["a.py"],
    )
    event["ts"] = "1970-01-12T13:46:40.000Z"  # epoch 1_000_000
    ledger.append(paths.ledger_path(repo.path), event)
    code, out = run_in(repo, ["explain", "a.py:1"], capsys)
    assert code == cli.EXIT_OK
    assert "Use Redis with a 30-second key" in out
    assert "in-memory LRU" in out
    assert "lost on deploy" in out


def test_explain_without_initialisation_exits_three(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    code, out = run_in(repo, ["explain", "a.py:1"], capsys)
    assert code == cli.EXIT_UNINITIALISED


def test_explain_accepts_a_path_without_a_line(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    paths.ledger_path(repo.path).parent.mkdir(parents=True)
    paths.ledger_path(repo.path).touch()
    code, out = run_in(repo, ["explain", "a.py", "--json"], capsys)
    assert code == cli.EXIT_OK
    assert json.loads(out)["line"] is None


def test_explain_does_not_print_a_recorded_note_for_an_uncommitted_line(repo, capsys):
    """Pins the Task 5 carry-forward constraint: resolve.explain populates
    `notes` on the uncommitted-line branch even though confidence is "none".
    The renderer must gate what it prints on confidence, not on whether
    `notes` is non-empty — otherwise an uncommitted line would appear to
    have recorded reasoning under a "Confidence: None" heading.
    """
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    event = events.new_event(
        events.NOTE,
        decision="Use Redis with a 30-second key",
        because="responses are user-specific",
        files=["a.py"],
    )
    event["ts"] = "2001-09-09T01:46:40.000Z"  # epoch 1_000_000_000
    ledger.append(paths.ledger_path(repo.path), event)
    # Append an uncommitted second line — git blame reports sha == all zeros.
    (repo.path / "a.py").write_text("one\ntwo\n", encoding="utf-8")
    code, out = run_in(repo, ["explain", "a.py:2"], capsys)
    assert code == cli.EXIT_OK
    assert "none" in out.lower()
    assert "Use Redis with a 30-second key" not in out


def test_explain_does_not_print_a_recorded_note_for_an_untracked_file(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    event = events.new_event(
        events.NOTE,
        decision="Use Redis with a 30-second key",
        files=["untracked.py"],
    )
    ledger.append(paths.ledger_path(repo.path), event)
    (repo.path / "untracked.py").write_text("one\n", encoding="utf-8")

    code, out = run_in(repo, ["explain", "untracked.py:1"], capsys)

    assert code == cli.EXIT_OK
    assert "none" in out.lower()
    assert "Use Redis with a 30-second key" not in out


def test_explain_json_hides_notes_that_are_not_attributed_to_the_line(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    event = events.new_event(
        events.NOTE,
        decision="Use Redis with a 30-second key",
        files=["a.py"],
    )
    ledger.append(paths.ledger_path(repo.path), event)
    (repo.path / "a.py").write_text("one\ntwo\n", encoding="utf-8")

    code, out = run_in(repo, ["explain", "a.py:2", "--json"], capsys)

    assert code == cli.EXIT_OK
    payload = json.loads(out)
    assert payload["confidence"] == "none"
    assert payload["notes"] == []


def test_explain_low_confidence_does_not_deny_existing_reasoning(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    event = events.new_event(
        events.NOTE,
        decision="A later decision",
        files=["a.py"],
    )
    event["ts"] = "1970-01-24T03:33:20.000Z"  # epoch 2_000_000
    ledger.append(paths.ledger_path(repo.path), event)

    code, out = run_in(repo, ["explain", "a.py:1"], capsys)

    assert code == cli.EXIT_OK
    assert "Low — recorded evidence cannot be tied to this line." in out
    assert "all of it postdates" in out
    assert "no reasoning was recorded" not in out


def test_explain_warns_once_when_ledger_lines_are_unreadable(
    repo, capsys, monkeypatch
):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    path = paths.ledger_path(repo.path)
    path.parent.mkdir(parents=True)
    path.write_text("{torn\n{also-torn\n", encoding="utf-8")
    monkeypatch.chdir(repo.path)

    code = cli.main(["explain", "a.py:1"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_OK
    assert captured.err.count("warning:") == 1
    assert "skipped 2 unreadable ledger lines" in captured.err
