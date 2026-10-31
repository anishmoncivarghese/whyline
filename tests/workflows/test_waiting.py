from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from whyline.workflows import definitions as d
from whyline.workflows import engine, state

HEAD = '''
name = "demo"
version = 1

[trigger]
kind = "manual"
'''

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return state.connect()


def make_run(conn, body: str) -> int:
    wf = d.parse(HEAD + body, kind="personal", path=Path("demo.toml"))
    return state.claim_run(conn, wf, source="manual", dedupe_key="k", inputs={})


def statuses(conn, run_id):
    return {r["step_id"]: r["status"] for r in state.steps_of(conn, run_id)}


def run_row(conn, run_id):
    return conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()


WAIT = '''
[[step]]
id = "first"
type = "set"
[step.values]
x = 1

[[step]]
id = "pause"
type = "wait"
minutes = 30

[[step]]
id = "last"
type = "set"
[step.values]
y = 2
'''


def test_wait_resumes_only_after_wake_at_and_keeps_earlier_steps(conn):
    run = make_run(conn, WAIT)
    assert engine.execute(run, now=T0) == "waiting"
    row = run_row(conn, run)
    assert row["reason"] == "timer"
    assert datetime.fromisoformat(row["wake_at"]) == T0 + timedelta(minutes=30)
    attempts = {r["step_id"]: r["attempt"] for r in state.steps_of(conn, run)}

    assert engine.resume_due(T0 + timedelta(minutes=29)) == []
    assert engine.execute(run, now=T0 + timedelta(minutes=29)) == "waiting"  # woken early
    assert engine.resume_due(T0 + timedelta(minutes=30)) == [run]
    assert engine.execute(run, now=T0 + timedelta(minutes=31)) == "succeeded"
    assert statuses(conn, run) == {"first": "succeeded", "pause": "succeeded",
                                   "last": "succeeded"}
    after = {r["step_id"]: r["attempt"] for r in state.steps_of(conn, run)}
    assert after["first"] == attempts["first"] == 1  # earlier step did not run again


def test_until_past_today_waits_until_tomorrow(conn):
    local_noon = datetime(2026, 1, 1, 12, 0).astimezone()
    for until, days in (("08:00", 1), ("13:00", 0)):
        conn.execute("DELETE FROM runs")
        run = make_run(conn, f'[[step]]\nid = "w"\ntype = "wait"\nuntil = "{until}"\n')
        assert engine.execute(run, now=local_noon) == "waiting"
        wake = datetime.fromisoformat(run_row(conn, run)["wake_at"]).astimezone()
        hour, minute = (int(p) for p in until.split(":"))
        assert (wake.hour, wake.minute) == (hour, minute)
        assert wake.date() == local_noon.date() + timedelta(days=days)


APPROVAL = '''
[[step]]
id = "ask"
type = "approval"
message = "ship it?"
expires_hours = 2

[[step]]
id = "after"
type = "set"
[step.values]
ok = true
'''


def start_approval(conn):
    run = make_run(conn, APPROVAL)
    assert engine.execute(run, now=T0) == "waiting"
    row = state.latest_approval(conn, run, "ask")
    assert run_row(conn, run)["reason"] == "approval"
    assert row["status"] == "pending"
    assert datetime.fromisoformat(row["expires_at"]) == T0 + timedelta(hours=2)
    return run, row


def test_approve_continues(conn):
    run, row = start_approval(conn)
    assert state.decide(conn, row["id"], row["nonce"], "approve", "ana", now=T0) == "approved"
    assert engine.resume_due(T0) == [run]
    assert engine.execute(run, now=T0) == "succeeded"
    assert statuses(conn, run) == {"ask": "succeeded", "after": "succeeded"}


def test_deny_fails_the_step(conn):
    run, row = start_approval(conn)
    assert state.decide(conn, row["id"], row["nonce"], "deny", "ana", now=T0) == "denied"
    assert statuses(conn, run)["ask"] == "failed"
    final = run_row(conn, run)
    assert final["status"] == "failed"
    assert "denied by ana" in final["reason"]
    assert engine.resume_due(T0) == []


def test_second_decision_is_out_of_date(conn):
    run, row = start_approval(conn)
    assert state.decide(conn, row["id"], row["nonce"], "approve", "ana", now=T0) == "approved"
    assert state.decide(conn, row["id"], row["nonce"], "deny", "bo", now=T0) == "out_of_date"
    assert state.latest_approval(conn, run, "ask")["decided_by"] == "ana"


def test_wrong_nonce_is_out_of_date_and_changes_nothing(conn):
    run, row = start_approval(conn)
    assert state.decide(conn, row["id"], "nope", "approve", "ana", now=T0) == "out_of_date"
    assert state.latest_approval(conn, run, "ask")["status"] == "pending"
    assert run_row(conn, run)["status"] == "waiting"


def test_expiry_fails_the_step(conn):
    run, row = start_approval(conn)
    assert engine.resume_due(T0 + timedelta(hours=1)) == []
    assert engine.resume_due(T0 + timedelta(hours=2)) == []  # failed, not listed
    assert statuses(conn, run)["ask"] == "failed"
    final = run_row(conn, run)
    assert final["status"] == "failed"
    assert "approval expired" in final["reason"]
    assert state.latest_approval(conn, run, "ask")["status"] == "expired"
    late = state.decide(conn, row["id"], row["nonce"], "approve", "ana", now=T0 + timedelta(hours=3))
    assert late == "out_of_date"
