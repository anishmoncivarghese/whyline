import json
from datetime import datetime, timedelta

import pytest

from whyline.agents import definitions as d, folders, service, state, tick


def _folder_agent(repo, home, gap=10):
    watched = home / "inbox"
    watched.mkdir()
    path = repo / ".whyline/agents/w.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'name="w"\ninstructions="x"\nrunner="claude"\n[trigger]\nkind="folder"\n'
                    f'folder={json.dumps(str(watched))}\nmin_gap_minutes={gap}')  # escapes Windows backslashes
    defn = d.load(path, kind="repo", repo_root=repo)
    state.accept(state.connect(), defn)
    return defn, watched


def test_snapshot_is_regular_files_only(tmp_path):
    folder = tmp_path / "box"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.txt").write_text("a")
    (folder / "sub" / "no.txt").write_text("no")
    (folder / "link.txt").symlink_to(folder / "a.txt")
    assert set(folders.snapshot(folder)) == {"a.txt"}
    assert folders.snapshot(tmp_path / "missing") == {}


def test_first_tick_only_records_then_new_files_start_one_run(repo, home):
    defn, watched = _folder_agent(repo, home)
    (watched / "old.txt").write_text("old")
    t0 = datetime(2026, 10, 5, 9, 0)
    assert tick.run_tick(now=t0, spawn=lambda o: None).started == []
    for n in range(30):
        (watched / f"new{n}.txt").write_text(str(n))
    report = tick.run_tick(now=t0 + timedelta(minutes=2), spawn=lambda o: None)
    assert len(report.started) == 1
    occ = state.occurrence(state.connect(), report.started[0])
    copied = sorted(p.name for p in __import__("pathlib").Path(occ["payload_dir"]).iterdir())
    assert len(copied) == 30 and "old.txt" not in copied and occ["source"] == "folder"


def test_changes_inside_the_gap_wait(repo, home):
    defn, watched = _folder_agent(repo, home, gap=10)
    t0 = datetime(2026, 10, 5, 9, 0)
    tick.run_tick(now=t0, spawn=lambda o: None)
    (watched / "a.txt").write_text("a")
    started = tick.run_tick(now=t0 + timedelta(minutes=2), spawn=lambda o: None).started
    assert len(started) == 1
    # run_occurrence marks the row done before last_run_at moves. The stub
    # spawn does neither, and a still-running row blocks the next start.
    state.set_occurrence(state.connect(), started[0], status="done")
    state.update(state.connect(), defn.agent_id, last_run_at=(t0 + timedelta(minutes=2)).isoformat())
    (watched / "b.txt").write_text("b")
    assert tick.run_tick(now=t0 + timedelta(minutes=4), spawn=lambda o: None).started == []
    assert len(tick.run_tick(now=t0 + timedelta(minutes=13), spawn=lambda o: None).started) == 1


def test_a_folder_change_waits_while_a_run_is_still_going(repo, home):
    defn, watched = _folder_agent(repo, home, gap=10)
    t0 = datetime(2026, 10, 5, 9, 0)
    tick.run_tick(now=t0, spawn=lambda o: None)
    (watched / "a.txt").write_text("a")
    assert len(tick.run_tick(now=t0 + timedelta(minutes=2), spawn=lambda o: None).started) == 1
    state.update(state.connect(), defn.agent_id, last_run_at=(t0 + timedelta(minutes=2)).isoformat())
    (watched / "b.txt").write_text("b")
    report = tick.run_tick(now=t0 + timedelta(minutes=13), spawn=lambda o: None)
    assert report.started == [] and report.skipped_busy == 1
    conn = state.connect()
    waiting = conn.execute(
        "SELECT payload_dir FROM occurrences WHERE agent_id=? AND status='claimed'",
        (defn.agent_id,),
    ).fetchone()
    copied = sorted(p.name for p in __import__("pathlib").Path(waiting["payload_dir"]).iterdir())
    assert copied == ["b.txt"]


def test_trigger_copies_files_and_enforces_the_gap(repo, home):
    defn, _ = _folder_agent(repo, home, gap=10)
    mail = home / "mail.txt"
    mail.write_text("From: x\nSubject: y\n\nbody")
    started = []
    now = datetime(2026, 10, 5, 9, 0)
    occ = service.trigger("w", repo, [mail], now=now, spawn=started.append)
    assert started == [occ]
    payload = state.occurrence(state.connect(), occ)["payload_dir"]
    assert (__import__("pathlib").Path(payload) / "mail.txt").read_text().startswith("From: x")
    state.update(state.connect(), defn.agent_id, last_run_at=now.isoformat())
    with pytest.raises(service.TooSoon) as raised:
        service.trigger("w", repo, [], now=now + timedelta(minutes=3), spawn=started.append)
    assert raised.value.next_allowed == now + timedelta(minutes=10)


def test_trigger_refuses_an_agent_that_is_not_active(repo, home):
    defn, _ = _folder_agent(repo, home)
    state.set_status(state.connect(), defn.agent_id, "paused", "by you")
    with pytest.raises(ValueError, match="paused"):
        service.trigger("w", repo, [], spawn=lambda o: None)


def test_trigger_command_exits_3_during_the_gap(repo, home, monkeypatch, capsys):
    from whyline import cli

    defn, _ = _folder_agent(repo, home, gap=10)
    monkeypatch.chdir(repo)
    state.update(state.connect(), defn.agent_id, last_run_at=datetime.now().isoformat())
    assert cli.main(["agents", "trigger", "w"]) == 3
    assert "Too soon" in capsys.readouterr().err


def test_trigger_command_passes_each_file(repo, home, monkeypatch):
    from whyline import cli

    monkeypatch.chdir(repo)
    seen = {}

    def fake(name, root, files=(), **kwargs):
        seen["name"] = name
        seen["files"] = list(files)
        return 1

    monkeypatch.setattr(service, "trigger", fake)
    assert cli.main(["agents", "trigger", "w", "--file", "a.txt", "--file", "b.txt"]) == 0
    assert seen == {"name": "w", "files": ["a.txt", "b.txt"]}
