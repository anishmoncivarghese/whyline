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


def test_note_writes_to_both_the_ledger_and_decisions_md(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True)
    paths.ledger_path(repo.path).touch()
    code, _ = run_in(
        repo,
        [
            "note",
            "Store absolute monotonic expiry",
            "--because",
            "clock is injected",
            "--rejected",
            "sleep in tests: slow and flaky",
            "--file",
            "cache.py",
        ],
        capsys,
    )
    assert code == cli.EXIT_OK
    found, skipped = ledger.read_all(paths.ledger_path(repo.path))
    assert skipped == 0
    assert found[-1]["type"] == events.NOTE
    assert found[-1]["alternatives"] == [
        {"option": "sleep in tests", "why_not": "slow and flaky"}
    ]
    assert found[-1]["files"] == ["cache.py"]
    assert "monotonic expiry" in paths.decisions_path(repo.path).read_text()


def test_note_requires_initialisation(repo, capsys):
    code, _ = run_in(repo, ["note", "something"], capsys)
    assert code == cli.EXIT_UNINITIALISED


def test_init_scaffolds_ledger_and_gitignore(repo, capsys):
    code, _ = run_in(repo, ["init", "--yes"], capsys)
    assert code == cli.EXIT_OK
    assert paths.ledger_path(repo.path).exists()
    ignore = (repo.path / ".whyline" / ".gitignore").read_text()
    assert "ledger.jsonl" in ignore
    assert "!decisions.md" in ignore


def test_init_preserves_existing_whyline_gitignore_entries(repo, capsys):
    directory = repo.path / ".whyline"
    directory.mkdir()
    (directory / ".gitignore").write_text("keep-me.tmp\n")
    run_in(repo, ["init", "--yes"], capsys)
    ignore = (directory / ".gitignore").read_text()
    assert "keep-me.tmp" in ignore
    assert "ledger.jsonl" in ignore


def test_init_is_idempotent(repo, capsys):
    run_in(repo, ["init", "--yes"], capsys)
    agents_before = (repo.path / "AGENTS.md").read_text()
    claude_before = (repo.path / "CLAUDE.md").read_text()
    code, _ = run_in(repo, ["init", "--yes"], capsys)
    assert code == cli.EXIT_OK
    assert (repo.path / "AGENTS.md").read_text() == agents_before
    assert (repo.path / "CLAUDE.md").read_text() == claude_before


def test_init_writes_shared_agent_instructions_with_yes(repo, capsys):
    run_in(repo, ["init", "--yes"], capsys)
    assert "whyline note" in (repo.path / "AGENTS.md").read_text()
    claude = (repo.path / "CLAUDE.md").read_text()
    assert "@AGENTS.md" in claude
    assert "canonical source" in claude


def test_init_preserves_existing_instruction_files(repo, capsys):
    (repo.path / "AGENTS.md").write_text("Existing agents rules.\n")
    (repo.path / "CLAUDE.md").write_text("Existing Claude rules.\n")
    run_in(repo, ["init", "--yes"], capsys)
    assert (repo.path / "AGENTS.md").read_text().startswith("Existing agents rules.")
    assert (repo.path / "CLAUDE.md").read_text().startswith("Existing Claude rules.")


def test_init_without_confirmation_does_not_modify_instruction_files(
    repo, capsys, monkeypatch
):
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    code, _ = run_in(repo, ["init"], capsys)
    assert code == cli.EXIT_OK
    assert not (repo.path / "AGENTS.md").exists()
    assert not (repo.path / "CLAUDE.md").exists()


def test_brief_command_prints_the_context_block(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True)
    paths.ledger_path(repo.path).touch()
    code, out = run_in(repo, ["brief"], capsys)
    assert code == cli.EXIT_OK
    assert "<whyline-context>" in out


def test_brief_without_initialisation_exits_three(repo, capsys):
    code, _ = run_in(repo, ["brief"], capsys)
    assert code == cli.EXIT_UNINITIALISED


def test_run_still_prints_the_brief_when_the_agent_is_missing(repo, capsys, monkeypatch):
    from whyline import runner

    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    code, out = run_in(repo, ["run", "codex", "do the thing"], capsys)
    assert code == cli.EXIT_ERROR
    assert "<whyline-context>" in out


def test_run_requires_initialisation(repo, capsys):
    code, _ = run_in(repo, ["run", "codex", "task"], capsys)
    assert code == cli.EXIT_UNINITIALISED


def _ledger_note(repo, decision, ts, files=None):
    event = events.new_event(events.NOTE, decision=decision, files=files or [])
    event["ts"] = ts
    ledger.append(paths.ledger_path(repo.path), event)


def test_timeline_lists_events_newest_first(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    _ledger_note(repo, "older", "2026-08-01T10:00:00.000Z", ["a.py"])
    _ledger_note(repo, "newer", "2026-08-05T10:00:00.000Z", ["a.py"])
    code, out = run_in(repo, ["timeline"], capsys)
    assert code == cli.EXIT_OK
    assert out.index("newer") < out.index("older")


def test_timeline_filters_by_file(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    _ledger_note(repo, "keep", "2026-08-01T10:00:00.000Z", ["a.py"])
    _ledger_note(repo, "drop", "2026-08-01T10:00:00.000Z", ["b.py"])
    code, out = run_in(repo, ["timeline", "--file", "a.py"], capsys)
    assert code == cli.EXIT_OK
    assert "keep" in out
    assert "drop" not in out


def test_timeline_filters_by_since(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    _ledger_note(repo, "old", "2026-08-01T10:00:00.000Z")
    _ledger_note(repo, "recent", "2026-08-09T10:00:00.000Z")
    code, out = run_in(repo, ["timeline", "--since", "2026-08-05"], capsys)
    assert code == cli.EXIT_OK
    assert "recent" in out
    assert "old" not in out


def test_timeline_on_an_empty_ledger_says_so(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    code, out = run_in(repo, ["timeline"], capsys)
    assert code == cli.EXIT_OK
    assert "No events recorded" in out


def test_timeline_requires_initialisation(repo, capsys):
    code, _ = run_in(repo, ["timeline"], capsys)
    assert code == cli.EXIT_UNINITIALISED


def test_status_json_reports_counts_and_hook_state(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    _ledger_note(repo, "a", "2026-08-01T10:00:00.000Z")
    code, out = run_in(repo, ["status", "--json"], capsys)
    assert code == cli.EXIT_OK
    payload = json.loads(out)
    assert payload["events"] == 1
    assert payload["notes"] == 1
    assert payload["hook_installed"] is False
    assert payload["initialised"] is True


def test_status_reports_skipped_torn_lines(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    _ledger_note(repo, "a", "2026-08-01T10:00:00.000Z")
    with paths.ledger_path(repo.path).open("a", encoding="utf-8") as handle:
        handle.write('{"torn')
    code, out = run_in(repo, ["status", "--json"], capsys)
    assert code == cli.EXIT_OK
    assert json.loads(out)["skipped_lines"] == 1


def test_status_works_before_initialisation(repo, capsys):
    """status must not exit 3 — reporting "not initialised" is its whole job."""
    code, out = run_in(repo, ["status", "--json"], capsys)
    assert code == cli.EXIT_OK
    assert json.loads(out)["initialised"] is False
