"""Item 3 of the brainstorm roadmap: decision lifecycle (supersede,
retract), review evidence, and the `whyline decisions` query surface
(docs/superpowers/plans/2026-09-30-brainstorm-roadmap.md)."""

import json

from whyline import brief, cli, decisions, history, ledger, paths, resolve, sync


def _init(repo):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()


def run_in(repo, argv, capsys, monkeypatch):
    monkeypatch.chdir(repo.path)
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _note(repo, capsys, monkeypatch, *argv):
    code, _, err = run_in(repo, ["note", *argv], capsys, monkeypatch)
    assert code == cli.EXIT_OK, err
    return ledger.read_all(paths.ledger_path(repo.path))[0][-1]


def _by_decision(root):
    return {e.event["decision"]: e.event for e in history.load(root).notes}


def _clone(repo):
    paths.ledger_path(repo.path).unlink()


# --- 3.1 / 3.3 supersede ---------------------------------------------------------------


def test_supersede_marks_the_old_decision_and_survives_a_clone(repo, capsys, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    old = _note(repo, capsys, monkeypatch, "use polling", "--file", "a.py")
    new = _note(repo, capsys, monkeypatch, "use webhooks", "--supersedes", old["id"][:8])

    assert new["supersedes"] == [old["id"]]
    for clone in (False, True):  # with the ledger, then from a clone
        if clone:
            _clone(repo)
        notes = _by_decision(repo.path)
        assert notes["use polling"]["lifecycle"] == "superseded"
        assert notes["use polling"]["superseded_by"] == new["id"]
        assert notes["use webhooks"]["lifecycle"] == "active"
    text = paths.decisions_path(repo.path).read_text(encoding="utf-8")
    assert f"**Supersedes:** {old['id'][:8]}" in text


def test_supersedes_must_name_an_existing_decision(repo, capsys, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    code, _, err = run_in(repo, ["note", "x", "--supersedes", "nope"], capsys, monkeypatch)
    assert code == cli.EXIT_ERROR and "No decision with id nope" in err
    assert history.load(repo.path).notes == []


# --- 3.2 / 3.3 retract -------------------------------------------------------------------


def test_retract_records_a_visible_entry_and_marks_the_decision(repo, capsys, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    old = _note(repo, capsys, monkeypatch, "cache forever", "--file", "a.py")

    code, out, _ = run_in(
        repo, ["retract", old["id"][:8], "--because", "stale data bug", "--actor", "claude"],
        capsys, monkeypatch,
    )

    assert code == cli.EXIT_OK and "Retracted" in out
    text = paths.decisions_path(repo.path).read_text(encoding="utf-8")
    assert "— Retracted: cache forever" in text
    assert "**Because:** stale data bug" in text
    for clone in (False, True):
        if clone:
            _clone(repo)
        loaded = history.load(repo.path)
        # the retraction is not itself a decision
        assert [e.event["decision"] for e in loaded.notes] == ["cache forever"]
        note = loaded.notes[0].event
        assert note["lifecycle"] == "retracted"
        assert note["retracted_because"] == "stale data bug"


def test_retract_needs_a_reason_and_a_real_decision(repo, capsys, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    old = _note(repo, capsys, monkeypatch, "d")
    code, _, _ = run_in(repo, ["retract", old["id"]], capsys, monkeypatch)
    assert code == cli.EXIT_USAGE
    code, _, err = run_in(repo, ["retract", "zzz", "--because", "x"], capsys, monkeypatch)
    assert code == cli.EXIT_ERROR and "No decision" in err


def test_a_retracted_decision_no_longer_supersedes_anything(repo, capsys, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    old = _note(repo, capsys, monkeypatch, "A")
    new = _note(repo, capsys, monkeypatch, "B", "--supersedes", old["id"])
    run_in(repo, ["retract", new["id"], "--because", "B was wrong"], capsys, monkeypatch)
    notes = _by_decision(repo.path)
    assert notes["A"]["lifecycle"] == "active"
    assert notes["B"]["lifecycle"] == "retracted"


# --- 3.4 current reasoning only ------------------------------------------------------------


def test_brief_and_sync_only_hand_over_active_decisions(repo, capsys, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    old = _note(repo, capsys, monkeypatch, "old approach")
    _note(repo, capsys, monkeypatch, "new approach", "--supersedes", old["id"])
    gone = _note(repo, capsys, monkeypatch, "bad idea")
    run_in(repo, ["retract", gone["id"], "--because", "wrong"], capsys, monkeypatch)

    for text in (brief.compose(repo.path), sync.compose(repo.path)):
        assert "new approach" in text
        assert "old approach" not in text
        assert "bad idea" not in text


# --- 3.5 explain -----------------------------------------------------------------------------


def _timed(repo, decision, ts, **extra):
    from whyline import events

    event = events.new_event(events.NOTE, decision=decision, files=["a.py"], **extra)
    event["ts"] = ts
    ledger.append(paths.ledger_path(repo.path), event)
    return event


def test_explain_prefers_the_one_active_decision_among_several(repo):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    old = _timed(repo, "first idea", "1970-01-12T13:46:00.000Z")
    _timed(repo, "revised idea", "1970-01-12T13:46:10.000Z", supersedes=[old["id"]])

    result = resolve.explain(repo.path, "a.py", 1)

    assert result.confidence == resolve.HIGH
    assert [n["decision"] for n in result.notes] == ["revised idea"]
    assert "1 superseded or retracted" in result.reason


def test_explain_still_shows_a_sole_superseded_decision_with_its_status(repo, capsys, monkeypatch):
    from whyline import render

    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    old = _timed(repo, "original reason", "1970-01-12T13:46:00.000Z")
    repo.commit({"b.py": "1\n"}, "later", epoch=1_000_500)
    run_in(repo, ["note", "replacement", "--supersedes", old["id"]], capsys, monkeypatch)

    result = resolve.explain(repo.path, "a.py", 1)

    assert [n["decision"] for n in result.notes] == ["original reason"]
    text = render.explanation_text(result)
    assert "Status            superseded" in text
    assert render.explanation_json(result)["notes"][0]["lifecycle"] == "superseded"


# --- 3.6 review evidence ---------------------------------------------------------------------


def test_review_evidence_round_trips(repo, capsys, monkeypatch):
    head = repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    _note(
        repo, capsys, monkeypatch, "approve the retry change",
        "--verdict", "approved", "--reviewed-commit", head[:7],
        "--test", "uv run pytest -q: 400 passed", "--test", "ruff: clean",
    )
    _clone(repo)
    [entry] = history.load(repo.path).notes
    note = entry.event
    assert note["verdict"] == "approved"
    assert note["reviewed_commit"] == head
    assert note["tests"] == [
        {"command": "uv run pytest -q", "result": "400 passed"},
        {"command": "ruff", "result": "clean"},
    ]
    lines = brief.entry_lines(entry)
    assert "    verdict: approved (reviewed " + head[:7] + ")" in lines
    assert "    test: uv run pytest -q: 400 passed" in lines


def test_reviewed_commit_must_exist(repo, capsys, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    code, _, err = run_in(repo, ["note", "x", "--reviewed-commit", "beef"], capsys, monkeypatch)
    assert code == cli.EXIT_ERROR and "not a commit" in err


# --- 3.7 whyline decisions --------------------------------------------------------------------


def _seed(repo, capsys, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    old = _note(repo, capsys, monkeypatch, "Use SQLite", "--task", "DB-1", "--file", "db.py",
                "--because", "zero setup")
    new = _note(repo, capsys, monkeypatch, "Use Postgres", "--task", "DB-2", "--file", "db.py",
                "--supersedes", old["id"], "--because", "concurrent writers")
    other = _note(repo, capsys, monkeypatch, "Log to stderr", "--task", "OPS-1",
                  "--rejected", "syslog: not portable")
    return old, new, other


def test_decisions_list_shows_active_newest_first(repo, capsys, monkeypatch):
    _, new, other = _seed(repo, capsys, monkeypatch)
    code, out, _ = run_in(repo, ["decisions"], capsys, monkeypatch)
    assert code == cli.EXIT_OK
    assert "Use SQLite" not in out
    assert out.index("Log to stderr") < out.index("Use Postgres")
    assert new["id"][:8] in out


def test_decisions_list_all_includes_status_and_filters(repo, capsys, monkeypatch):
    _seed(repo, capsys, monkeypatch)
    _, out, _ = run_in(repo, ["decisions", "list", "--all"], capsys, monkeypatch)
    assert "[superseded] Use SQLite" in out
    _, out, _ = run_in(repo, ["decisions", "list", "--file", "db.py", "--all"], capsys, monkeypatch)
    assert "Log to stderr" not in out and "Use SQLite" in out
    _, out, _ = run_in(repo, ["decisions", "list", "--task", "OPS-1", "--json"], capsys, monkeypatch)
    assert [d["decision"] for d in json.loads(out)] == ["Log to stderr"]
    _, out, _ = run_in(repo, ["decisions", "list", "--limit", "1"], capsys, monkeypatch)
    assert "Log to stderr" in out and "Use Postgres" not in out


def test_decisions_search_is_case_insensitive_across_fields(repo, capsys, monkeypatch):
    _seed(repo, capsys, monkeypatch)
    _, out, _ = run_in(repo, ["decisions", "search", "CONCURRENT"], capsys, monkeypatch)
    assert "Use Postgres" in out and "Log to stderr" not in out
    _, out, _ = run_in(repo, ["decisions", "search", "syslog"], capsys, monkeypatch)
    assert "Log to stderr" in out
    _, out, _ = run_in(repo, ["decisions", "search", "zero setup"], capsys, monkeypatch)
    assert "No matching decisions" in out  # superseded, hidden without --all
    _, out, _ = run_in(repo, ["decisions", "search", "zero setup", "--all"], capsys, monkeypatch)
    assert "Use SQLite" in out


def test_decisions_show_prints_the_full_record(repo, capsys, monkeypatch):
    old, new, _ = _seed(repo, capsys, monkeypatch)
    code, out, _ = run_in(repo, ["decisions", "show", old["id"][:8]], capsys, monkeypatch)
    assert code == cli.EXIT_OK
    assert "Use SQLite" in out and "zero setup" in out
    assert f"superseded by {new['id'][:8]}" in out
    _, out, _ = run_in(repo, ["decisions", "show", new["id"], "--json"], capsys, monkeypatch)
    assert json.loads(out)["supersedes"] == [old["id"]]
    code, _, err = run_in(repo, ["decisions", "show", "zzz"], capsys, monkeypatch)
    assert code == cli.EXIT_ERROR and "No decision" in err
