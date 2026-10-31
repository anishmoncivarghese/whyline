import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from whyline.agents import tick as agents_tick
from whyline.workflows import definitions as d
from whyline.workflows import state, tick

BODY = '''
[[step]]
id = "a"
type = "set"
[step.values]
x = 1
'''


def head(name, trigger):
    return f'name = "{name}"\nversion = 1\n\n[trigger]\n{trigger}\n{BODY}'


DAILY = 'kind = "daily"\nat = "07:00"'


@pytest.fixture
def conn(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return state.connect()


def accept(conn, tmp_path, name="demo", trigger=DAILY, text=None):
    path = tmp_path / f"{name}.toml"
    path.write_text(text or head(name, trigger))
    wf = d.load(path, kind="personal")
    act = state.accept(conn, wf)
    conn.execute("UPDATE activations SET accepted_at=? WHERE workflow_id=?",
                 ("2026-10-01T00:00:00", wf.workflow_id))
    return wf, path, act


def runs(conn, status=None):
    sql = "SELECT * FROM runs" + (" WHERE status=?" if status else "") + " ORDER BY id"
    return conn.execute(sql, (status,) if status else ()).fetchall()


def test_sleep_across_three_times_runs_once(conn, tmp_path):
    accept(conn, tmp_path)
    spawned = []
    now = datetime(2026, 10, 3, 7, 1)  # 10-01, 10-02 and 10-03 at 07:00 all passed
    report = tick.run(now, spawn=spawned.append)
    assert len(report.claimed) == 1 and spawned == report.claimed
    assert report.missed == 2
    assert len(runs(conn, "running")) == 1
    again = tick.run(now, spawn=spawned.append)
    assert again.claimed == [] and again.missed == 0


def test_same_due_time_claims_once(conn, tmp_path):
    wf, _, _ = accept(conn, tmp_path)
    now = datetime(2026, 10, 1, 7, 1)
    tick.run(now, spawn=lambda r: None)
    conn.execute("UPDATE activations SET last_run_at=NULL")  # even a lost marker cannot double-run
    report = tick.run(now, spawn=lambda r: None)
    assert report.claimed == []
    keys = [r["dedupe_key"] for r in runs(conn)]
    assert keys == [f"{wf.workflow_id}@2026-10-01T07:00:00"]
    assert state.get(conn, wf.workflow_id).next_due_at == "2026-10-02T07:00:00"


def test_broken_file_does_not_stop_other_workflows(conn, tmp_path):
    _, bad, _ = accept(conn, tmp_path, "aaa")
    accept(conn, tmp_path, "bbb")
    bad.write_text("this is not toml [")
    spawned = []
    report = tick.run(datetime(2026, 10, 2, 7, 1), spawn=spawned.append)
    broken = state.get(conn, "personal:aaa")
    assert broken.status == "broken" and "TOML" in broken.reason
    assert report.broken == ["personal:aaa"] and len(spawned) == 1
    assert runs(conn)[0]["workflow_id"] == "personal:bbb"
    bad.write_text(head("aaa", DAILY))  # fixed: it is active again
    tick.run(datetime(2026, 10, 2, 7, 3), spawn=spawned.append)
    assert state.get(conn, "personal:aaa").status == "active"


def test_needs_review_and_paused_do_not_run(conn, tmp_path):
    accept(conn, tmp_path, "edited")
    accept(conn, tmp_path, "paused")
    accept(conn, tmp_path, "fine")
    (tmp_path / "edited.toml").write_text(head("edited", 'kind = "daily"\nat = "08:00"'))
    state.pause(conn, "personal:paused")
    spawned = []
    tick.run(datetime(2026, 10, 2, 9, 0), spawn=spawned.append)
    assert [r["workflow_id"] for r in runs(conn, "running")] == ["personal:fine"]
    assert state.get(conn, "personal:edited").status == "needs_review"
    assert len(spawned) == 1


def test_a_paused_workflow_with_a_queued_run_waits(conn, tmp_path):
    wf, _, _ = accept(conn, tmp_path, trigger='kind = "manual"')
    state.claim_run(conn, wf, source="manual", dedupe_key="m", inputs={})
    state.pause(conn, wf.workflow_id)
    spawned = []
    tick.run(datetime(2026, 10, 2, 9, 0), spawn=spawned.append)
    assert spawned == []
    state.resume(conn, wf.workflow_id)
    tick.run(datetime(2026, 10, 2, 9, 2), spawn=spawned.append)
    assert len(spawned) == 1


def test_a_folder_trigger_fires_once_for_two_new_files(conn, tmp_path):
    watched = tmp_path / "home" / "inbox"
    watched.mkdir()
    (watched / "old.txt").write_text("old")
    accept(conn, tmp_path, trigger=f'kind = "folder"\nfolder = "{watched}"')
    spawned = []
    now = datetime(2026, 10, 2, 9, 0)
    tick.run(now, spawn=spawned.append)  # records what is already there
    assert spawned == []
    (watched / "a.txt").write_text("a")
    (watched / "b.txt").write_text("b")
    tick.run(now + timedelta(minutes=2), spawn=spawned.append)
    assert len(spawned) == 1
    row = runs(conn)[0]
    assert row["source"] == "folder"
    assert row["inputs_json"] == (
        '{"trigger": {"files": ["%s", "%s"]}}' % (watched / "a.txt", watched / "b.txt"))
    tick.run(now + timedelta(minutes=4), spawn=spawned.append)
    assert len(spawned) == 1 and len(runs(conn)) == 1


def test_a_waiting_run_past_wake_at_is_spawned(conn, tmp_path):
    wf, _, _ = accept(conn, tmp_path, trigger='kind = "manual"')
    run_id = state.claim_run(conn, wf, source="manual", dedupe_key="m", inputs={})
    wake = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
    state.set_run(conn, run_id, status="waiting", reason="wait", wake_at=wake.isoformat())
    spawned = []
    tick.run(wake - timedelta(minutes=1), spawn=spawned.append)
    assert spawned == []
    tick.run(wake + timedelta(minutes=1), spawn=spawned.append)
    assert spawned == [run_id]


def test_a_due_waiting_run_and_a_queued_run_do_not_start_together(conn, tmp_path):
    wf, _, _ = accept(conn, tmp_path, trigger='kind = "manual"')
    waiting = state.claim_run(conn, wf, source="manual", dedupe_key="w", inputs={})
    wake = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
    state.set_run(conn, waiting, status="waiting", reason="wait", wake_at=wake.isoformat())
    queued = state.claim_run(conn, wf, source="manual", dedupe_key="q", inputs={})
    spawned = []
    later = wake + timedelta(minutes=1)
    tick.run(later, spawn=spawned.append)
    assert spawned == [waiting]
    tick.run(later, spawn=spawned.append)  # a repeat tick spawns nothing while it runs
    assert spawned == [waiting]
    assert runs(conn, "queued") == [queued] or [r["id"] for r in runs(conn, "queued")] == [queued]


def test_a_future_waiting_run_blocks_a_queued_run(conn, tmp_path):
    wf, _, _ = accept(conn, tmp_path, trigger='kind = "manual"')
    waiting = state.claim_run(conn, wf, source="manual", dedupe_key="w", inputs={})
    wake = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
    state.set_run(conn, waiting, status="waiting", reason="wait", wake_at=wake.isoformat())
    state.claim_run(conn, wf, source="manual", dedupe_key="q", inputs={})
    spawned = []
    tick.run(wake - timedelta(hours=1), spawn=spawned.append)
    assert spawned == []
    assert [r["id"] for r in runs(conn, "waiting")] == [waiting]


def test_a_queued_run_waits_while_the_workflow_is_running(conn, tmp_path):
    wf, _, _ = accept(conn, tmp_path, trigger='kind = "manual"')
    first = state.claim_run(conn, wf, source="manual", dedupe_key="1", inputs={})
    state.set_run(conn, first, status="running")
    state.claim_run(conn, wf, source="manual", dedupe_key="2", inputs={})
    spawned = []
    tick.run(datetime(2026, 10, 2, 9, 0), spawn=spawned.append)
    assert spawned == []


def test_an_exception_in_the_workflow_tick_lets_the_agents_tick_finish(
        conn, monkeypatch, caplog, repo):
    def boom(now, *, spawn=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(tick, "run", boom)
    ran = []
    monkeypatch.setattr(agents_tick, "_run_inbox", ran.append)
    with caplog.at_level(logging.ERROR):
        report = agents_tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=lambda o: None)
    assert report.started == [] and len(ran) == 1
    assert "workflow tick failed" in caplog.text
