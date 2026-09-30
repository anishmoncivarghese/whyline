"""Item 5 of the brainstorm roadmap: rename-aware relevance and
`explain --diff` (docs/superpowers/plans/2026-09-30-brainstorm-roadmap.md)."""

import json

from whyline import brief, cli, events, gitq, ledger, paths, resolve, sync


def _init(repo):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()


def run_in(repo, argv, capsys, monkeypatch):
    monkeypatch.chdir(repo.path)
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _note(repo, decision, files, ts, **extra):
    event = events.new_event(events.NOTE, decision=decision, files=files, **extra)
    event["ts"] = ts
    ledger.append(paths.ledger_path(repo.path), event)
    return event


def _rename(repo, old, new, epoch):
    (repo.path / new).parent.mkdir(parents=True, exist_ok=True)
    repo._git("mv", old, new)
    return repo.commit({}, f"rename {old} -> {new}", epoch=epoch)


BEFORE_FIRST = "1970-01-12T13:46:30.000Z"  # just before epoch 1_000_000


# --- 5.1 historical paths -------------------------------------------------------------


def test_historical_paths_follow_renames(repo):
    repo.commit({"old.py": "a\nb\n"}, "first", epoch=1_000_000)
    _rename(repo, "old.py", "mid.py", 1_000_100)
    _rename(repo, "mid.py", "src/new.py", 1_000_200)
    assert gitq.historical_paths(repo.path, "src/new.py") == ["src/new.py", "mid.py", "old.py"]


def test_historical_paths_of_an_untracked_file_is_itself(repo):
    repo.commit({"a.py": "1\n"}, "first", epoch=1_000_000)
    assert gitq.historical_paths(repo.path, "not-yet.py") == ["not-yet.py"]


# --- 5.2 rename-aware matching -----------------------------------------------------------


def test_explain_finds_a_decision_recorded_under_the_old_name(repo):
    repo.commit({"old.py": "a\n"}, "first", epoch=1_000_000)
    _init(repo)
    _note(repo, "why a", ["old.py"], BEFORE_FIRST)
    _rename(repo, "old.py", "new.py", 1_000_100)

    result = resolve.explain(repo.path, "new.py", 1)

    assert result.confidence == resolve.HIGH
    assert [n["decision"] for n in result.notes] == ["why a"]
    assert result.notes[0]["matched_path"] == "old.py"


def test_explain_text_shows_the_old_name(repo, capsys, monkeypatch):
    repo.commit({"old.py": "a\n"}, "first", epoch=1_000_000)
    _init(repo)
    _note(repo, "why a", ["old.py"], BEFORE_FIRST)
    _rename(repo, "old.py", "new.py", 1_000_100)
    _, out, _ = run_in(repo, ["explain", "new.py:1"], capsys, monkeypatch)
    assert "(recorded as old.py)" in out


def test_file_filters_expand_to_old_names(repo, capsys, monkeypatch):
    repo.commit({"old.py": "a\n"}, "first", epoch=1_000_000)
    _init(repo)
    _note(repo, "about the file", ["old.py"], BEFORE_FIRST)
    _note(repo, "unrelated", ["other.py"], BEFORE_FIRST)
    _rename(repo, "old.py", "new.py", 1_000_100)

    assert "about the file" in brief.compose(repo.path, files=["new.py"])
    assert "unrelated" not in brief.compose(repo.path, files=["new.py"])
    assert "about the file" in sync.compose(repo.path, files=["new.py"])
    _, out, _ = run_in(repo, ["decisions", "list", "--file", "new.py"], capsys, monkeypatch)
    assert "about the file" in out and "unrelated" not in out


# --- 5.3 / 5.4 blame_range and explain_blamed ------------------------------------------------


def test_blame_range_matches_per_line_blame(repo):
    repo.commit({"a.py": "1\n2\n3\n"}, "first", epoch=1_000_000)
    repo.commit({"a.py": "1\nTWO\n3\n4\n"}, "second", epoch=1_000_100)
    ranged = gitq.blame_range(repo.path, "a.py", 1, 4)
    assert sorted(ranged) == [1, 2, 3, 4]
    for line in range(1, 5):
        single = gitq.blame_line(repo.path, "a.py", line)
        assert (ranged[line].sha, ranged[line].epoch) == (single.sha, single.epoch)


def test_blame_range_at_a_revision(repo):
    first = repo.commit({"a.py": "1\n2\n"}, "first", epoch=1_000_000)
    repo.commit({"a.py": "changed\n2\n"}, "second", epoch=1_000_100)
    ranged = gitq.blame_range(repo.path, "a.py", 1, 1, rev=first)
    assert ranged[1].sha == first


def test_explain_blamed_agrees_with_explain(repo):
    from whyline import history

    repo.commit({"a.py": "1\n"}, "first", epoch=1_000_000)
    _init(repo)
    _note(repo, "why", ["a.py"], BEFORE_FIRST)
    whole = resolve.explain(repo.path, "a.py", 1)
    loaded = history.load(repo.path)
    blame = gitq.blame_line(repo.path, "a.py", 1)
    reused = resolve.explain_blamed(repo.path, loaded, "a.py", 1, blame)
    assert (reused.confidence, reused.reason) == (whole.confidence, whole.reason)
    assert reused.notes == whole.notes


# --- 5.5 explain --diff ------------------------------------------------------------------------


def _diff_repo(repo):
    repo.commit({"a.py": "one\ntwo\nthree\n", "b.py": "x\n"}, "base", epoch=1_000_000)
    _init(repo)
    note = _note(repo, "why a exists", ["a.py"], BEFORE_FIRST)
    return note


def test_explain_diff_groups_changed_lines_by_decision(repo, capsys, monkeypatch):
    note = _diff_repo(repo)
    (repo.path / "a.py").write_text("one\nTWO\nthree\nfour\n", encoding="utf-8")
    (repo.path / "b.py").write_text("changed\n", encoding="utf-8")

    code, out, _ = run_in(repo, ["explain", "--diff"], capsys, monkeypatch)

    assert code == cli.EXIT_OK
    assert f"{note['id'][:8]}  why a exists  [high]" in out
    assert "a.py:2" in out
    assert "b.py:1" in out  # explained by nothing
    assert "Coverage: 1 high" in out
    assert "1 unexplained" in out
    assert "1 new" in out  # the added "four"


def test_explain_staged_only_looks_at_the_index(repo, capsys, monkeypatch):
    _diff_repo(repo)
    (repo.path / "a.py").write_text("one\nTWO\nthree\n", encoding="utf-8")
    repo._git("add", "a.py")
    (repo.path / "b.py").write_text("unstaged change\n", encoding="utf-8")

    _, out, _ = run_in(repo, ["explain", "--staged"], capsys, monkeypatch)

    assert "a.py:2" in out
    assert "b.py" not in out


def test_explain_diff_with_no_changes(repo, capsys, monkeypatch):
    _diff_repo(repo)
    code, out, _ = run_in(repo, ["explain", "--diff"], capsys, monkeypatch)
    assert code == cli.EXIT_OK and "No changes against HEAD." in out


def test_explain_diff_counts_a_deleted_file(repo, capsys, monkeypatch):
    _diff_repo(repo)
    (repo.path / "a.py").unlink()
    _, out, _ = run_in(repo, ["explain", "--diff", "--json"], capsys, monkeypatch)
    payload = json.loads(out)
    assert payload["coverage"]["high"] == 3
    [group] = [g for g in payload["decisions"] if g["decision"] == "why a exists"]
    assert group["lines"] == [{"path": "a.py", "start": 1, "end": 3}]


def test_explain_needs_a_target_or_a_diff_flag(repo, capsys, monkeypatch):
    _diff_repo(repo)
    monkeypatch.chdir(repo.path)
    assert cli.main(["explain"]) == cli.EXIT_USAGE
    assert cli.main(["explain", "a.py", "--diff"]) == cli.EXIT_USAGE
