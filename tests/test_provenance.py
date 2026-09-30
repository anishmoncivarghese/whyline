"""Item 1 of the brainstorm roadmap: exact, explicit commit provenance
(docs/superpowers/plans/2026-09-30-brainstorm-roadmap.md)."""

import json
import re

import pytest

from whyline import brief, cli, decisions, events, history, ledger, paths, resolve


def _init(repo):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()


def run_in(repo, argv, capsys, monkeypatch):
    monkeypatch.chdir(repo.path)
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _fresh_clone(repo):
    """What a clone sees: decisions.md, no gitignored ledger."""
    paths.ledger_path(repo.path).unlink()


# --- 1.1 exact metadata in decisions.md -------------------------------------------


def test_new_entries_carry_exact_time_and_commit_in_a_separate_comment():
    event = events.new_event(events.NOTE, decision="d", commit="a" * 40)
    text = decisions.render_entry(event)
    assert f"<!-- whyline-event: {event['id']} -->" in text
    meta = json.loads(re.search(r"<!-- whyline-meta: (.*) -->", text).group(1))
    assert meta == {"v": 1, "ts": event["ts"], "commit": "a" * 40}


def test_unbound_entries_carry_time_but_no_commit():
    event = events.new_event(events.NOTE, decision="d")
    meta = json.loads(
        re.search(r"<!-- whyline-meta: (.*) -->", decisions.render_entry(event)).group(1)
    )
    assert meta == {"v": 1, "ts": event["ts"]}


def test_parse_recovers_exact_time_and_commit(tmp_path):
    path = tmp_path / "decisions.md"
    event = events.new_event(events.NOTE, decision="d", commit="b" * 40)
    decisions.append_entry(path, event)
    [parsed] = decisions.parse_entries(path)
    assert parsed["id"] == event["id"]  # an older parser's regex sees the same id
    assert parsed["ts"] == event["ts"]
    assert parsed["commit"] == "b" * 40


def test_entries_written_before_meta_still_parse_at_day_precision(tmp_path):
    path = tmp_path / "decisions.md"
    path.write_text(
        decisions.HEADING
        + "\n## 2026-09-01 — old decision\n\n<!-- whyline-event: abc -->\n",
        encoding="utf-8",
    )
    [parsed] = decisions.parse_entries(path)
    assert parsed["ts"] == "2026-09-01"
    assert "commit" not in parsed


def test_a_malformed_meta_comment_falls_back_to_the_heading(tmp_path):
    path = tmp_path / "decisions.md"
    path.write_text(
        decisions.HEADING
        + "\n## 2026-09-01 — d\n\n<!-- whyline-event: abc -->\n"
        + "<!-- whyline-meta: {not json -->\n",
        encoding="utf-8",
    )
    [parsed] = decisions.parse_entries(path)
    assert parsed["ts"] == "2026-09-01"


# --- 1.2 note --commit ----------------------------------------------------------------


def test_note_commit_binds_the_full_sha(repo, capsys, monkeypatch):
    head = repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    code, _, _ = run_in(
        repo, ["note", "use a", "--file", "a.py", "--commit", head[:7]], capsys, monkeypatch
    )
    assert code == cli.EXIT_OK
    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert found[-1]["commit"] == head
    assert decisions.parse_entries(paths.decisions_path(repo.path))[-1]["commit"] == head


def test_note_commit_accepts_head_by_name_but_never_binds_by_default(repo, capsys, monkeypatch):
    head = repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    run_in(repo, ["note", "explicit", "--commit", "HEAD"], capsys, monkeypatch)
    run_in(repo, ["note", "implicit"], capsys, monkeypatch)
    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert found[-2]["commit"] == head
    assert "commit" not in found[-1]


def test_note_with_an_unknown_commit_records_nothing(repo, capsys, monkeypatch):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    code, _, err = run_in(repo, ["note", "x", "--commit", "deadbeef"], capsys, monkeypatch)
    assert code == cli.EXIT_ERROR
    assert "deadbeef" in err and "not a commit" in err
    assert ledger.read_all(paths.ledger_path(repo.path))[0] == []
    assert not paths.decisions_path(repo.path).exists()


# --- 1.3 attach -----------------------------------------------------------------------


def _note(repo, capsys, monkeypatch, decision, *extra):
    run_in(repo, ["note", decision, *extra], capsys, monkeypatch)
    return ledger.read_all(paths.ledger_path(repo.path))[0][-1]


def test_attach_binds_an_earlier_decision_by_id_prefix(repo, capsys, monkeypatch):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    note = _note(repo, capsys, monkeypatch, "plan a", "--file", "a.py")
    head = repo.commit({"a.py": "two\n"}, "implement", epoch=1_000_100)

    code, out, _ = run_in(
        repo, ["attach", note["id"][:8], "--commit", head], capsys, monkeypatch
    )

    assert code == cli.EXIT_OK
    assert f"Attached {note['id'][:8]}" in out
    [entry] = [e for e in history.load(repo.path).notes if e.event["id"] == note["id"]]
    assert entry.event["commit"] == head
    # durable: survives losing the ledger
    _fresh_clone(repo)
    [entry] = [e for e in history.load(repo.path).notes if e.event["id"] == note["id"]]
    assert entry.event["commit"] == head


def test_attach_latest_binding_wins(repo, capsys, monkeypatch):
    first = repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    note = _note(repo, capsys, monkeypatch, "plan")
    second = repo.commit({"a.py": "two\n"}, "second", epoch=1_000_100)
    run_in(repo, ["attach", note["id"], "--commit", first], capsys, monkeypatch)
    run_in(repo, ["attach", note["id"], "--commit", second], capsys, monkeypatch)
    [entry] = history.load(repo.path).notes
    assert entry.event["commit"] == second


def test_attach_rejects_unknown_ambiguous_and_bad_commits(repo, capsys, monkeypatch):
    head = repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    note = _note(repo, capsys, monkeypatch, "plan")
    code, _, err = run_in(repo, ["attach", "zzzz", "--commit", head], capsys, monkeypatch)
    assert code == cli.EXIT_ERROR and "No decision" in err
    code, _, err = run_in(repo, ["attach", "", "--commit", head], capsys, monkeypatch)
    assert code == cli.EXIT_ERROR
    code, _, err = run_in(repo, ["attach", note["id"], "--commit", "nope"], capsys, monkeypatch)
    assert code == cli.EXIT_ERROR and "not a commit" in err


def test_attach_refuses_an_ambiguous_prefix(repo, capsys, monkeypatch):
    head = repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    for n in range(2):
        event = events.new_event(events.NOTE, decision=f"d{n}")
        event["id"] = f"abc{n}" + "0" * 28
        decisions.append_entry(paths.decisions_path(repo.path), event)
        ledger.append(paths.ledger_path(repo.path), event)
    code, _, err = run_in(repo, ["attach", "abc", "--commit", head], capsys, monkeypatch)
    assert code == cli.EXIT_ERROR and "matches 2 decisions" in err


# --- 1.4 explain prefers binding --------------------------------------------------------


def test_a_bound_decision_is_high_confidence_even_from_a_clone(repo, capsys, monkeypatch):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    head = repo.commit({"a.py": "two\n"}, "second", epoch=1_000_100)
    run_in(repo, ["note", "why two", "--file", "a.py", "--commit", head], capsys, monkeypatch)
    _fresh_clone(repo)

    result = resolve.explain(repo.path, "a.py", 1)

    assert result.confidence == resolve.HIGH
    assert [n["decision"] for n in result.notes] == ["why two"]
    assert "bound to the commit" in result.reason


def test_a_decision_bound_elsewhere_is_not_matched_by_time(repo, capsys, monkeypatch):
    first = repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    # recorded after `first` and before `second`: the time window would
    # otherwise attribute it to `second`
    event = events.new_event(events.NOTE, decision="about first", files=["a.py"], commit=first)
    event["ts"] = "1970-01-12T13:47:00.000Z"  # epoch 1_000_020
    ledger.append(paths.ledger_path(repo.path), event)
    repo.commit({"a.py": "two\n"}, "second", epoch=1_000_100)

    result = resolve.explain(repo.path, "a.py", 1)

    assert result.confidence != resolve.HIGH
    assert "bound to the commit" not in result.reason


def test_a_bound_decision_without_files_still_explains_its_commit(repo, capsys, monkeypatch):
    head = repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    run_in(repo, ["note", "whole commit", "--commit", head], capsys, monkeypatch)
    result = resolve.explain(repo.path, "a.py", 1)
    assert result.confidence == resolve.HIGH
    assert [n["decision"] for n in result.notes] == ["whole commit"]


def test_unbound_decisions_behave_as_before(repo, capsys, monkeypatch):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    event = events.new_event(events.NOTE, decision="timed", files=["a.py"])
    event["ts"] = "1970-01-12T13:46:30.000Z"  # epoch 1_000_000 - 10... before commit
    ledger.append(paths.ledger_path(repo.path), event)
    result = resolve.explain(repo.path, "a.py", 1)
    assert result.confidence == resolve.HIGH
    assert "matches the commit" in result.reason


# --- 1.5 show it -------------------------------------------------------------------------


def test_brief_lines_show_a_bound_commit():
    entry = history.HistoryEntry({"ts": "2026-09-30T00:00:00Z", "decision": "d", "commit": "c" * 40}, "ledger")
    assert "    commit: ccccccc" in brief.entry_lines(entry)
    unbound = history.HistoryEntry({"ts": "2026-09-30", "decision": "d"}, "ledger")
    assert not any("commit:" in line for line in brief.entry_lines(unbound))
