"""Requests honour policy, confirmation, allowed moves, and the job lease."""

import json
import os
from datetime import datetime, timedelta

import pytest

from whyline.ideas import actions, confirm, requests, store

NOW = datetime(2026, 10, 20, 12, 0, 0)
DEAD_PID = 2_147_483_647


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


def _create(conn, **overrides):
    kwargs = {
        "channel": "telegram",
        "actor": "alice",
        "chat_id": 11,
        "action": "capture",
        "args": {"text": "hello"},
        "proposed_by": "keyword",
    }
    kwargs.update(overrides)
    return requests.create(conn, **kwargs)


def _row(conn, request_id):
    return conn.execute(
        "SELECT * FROM requests WHERE id = ?", (request_id,)
    ).fetchone()


def test_create_honours_policy_and_refusal(conn):
    queued = _create(conn)
    assert queued.action == "capture"
    assert queued.state == "queued"
    assert queued.approval == "none"
    assert queued.proposed_by == "keyword"
    assert json.loads(queued.args_json) == {"text": "hello"}
    assert queued.error is None

    tap = _create(conn, action="brainstorm", args={"idea_id": 1})
    assert tap.state == "waiting_tap"
    assert tap.approval == "tap"

    guessed = _create(conn, action="status", args={}, proposed_by="assistant")
    assert guessed.state == "waiting_tap"
    assert guessed.approval == "tap"

    actions.set_policy(conn, "status", approval="tap")
    raised = _create(conn, action="status", args={})
    assert raised.state == "waiting_tap"
    assert raised.approval == "tap"

    actions.set_policy(conn, "capture", enabled=False)
    refused = _create(conn, args={"text": "nope"})
    assert refused.state == "refused"
    assert refused.error == "idea is turned off in the console"
    assert _row(conn, refused.id)["state"] == "refused"

    with pytest.raises(actions.PolicyError, match="unknown action explode"):
        _create(conn, action="explode", args={})
    assert conn.execute("SELECT count(*) FROM requests").fetchone()[0] == 5


def test_confirm_needs_the_right_code_and_actor_once(conn):
    req = _create(conn, action="brainstorm", args={"idea_id": 1})
    code = confirm.issue(
        conn, scope="request", subject=f"request:{req.id}", actor="alice"
    )
    before = _row(conn, req.id)
    with pytest.raises(requests.ConfirmError):
        requests.confirm(conn, req.id, "zzzzzzzz", actor="alice")
    with pytest.raises(requests.ConfirmError):
        requests.confirm(conn, req.id, code, actor="bob")
    assert tuple(_row(conn, req.id)) == tuple(before)

    moved = requests.confirm(conn, req.id, code, actor="alice")
    assert moved.state == "queued"
    assert moved.confirmed_at
    with pytest.raises(requests.ConfirmError):
        requests.confirm(conn, req.id, code, actor="alice")
    assert _row(conn, req.id)["state"] == "queued"


def test_illegal_moves_raise(conn):
    queued = _create(conn)
    with pytest.raises(requests.IllegalMove, match="queued to done"):
        requests.finish(conn, queued.id)
    assert _row(conn, queued.id)["state"] == "queued"
    code = confirm.issue(
        conn, scope="request", subject=f"request:{queued.id}", actor="alice"
    )
    with pytest.raises(requests.IllegalMove, match="queued to queued"):
        requests.confirm(conn, queued.id, code, actor="alice")
    assert _row(conn, queued.id)["state"] == "queued"
    requests.cancel(conn, queued.id)
    with pytest.raises(requests.IllegalMove, match="cancelled to cancelled"):
        requests.cancel(conn, queued.id)

    waiting = _create(conn, action="brainstorm", args={"idea_id": 1})
    with pytest.raises(requests.IllegalMove, match="waiting_tap to done"):
        requests.finish(conn, waiting.id)
    assert _row(conn, waiting.id)["state"] == "waiting_tap"
    requests.cancel(conn, waiting.id)

    done = _create(conn, action="status", args={})
    claimed = requests.claim_next(conn, NOW)
    assert claimed.id == done.id
    requests.finish(conn, done.id, result_path="ok.md")
    with pytest.raises(requests.IllegalMove, match="done to cancelled"):
        requests.cancel(conn, done.id)
    assert _row(conn, done.id)["state"] == "done"


def test_claim_next_respects_the_lease_and_reclaims_a_dead_pid(conn):
    first = _create(conn, action="status", args={})
    second = _create(conn, action="ask_repo", args={"repo": "whyline"})
    assert first.state == "queued" and second.state == "queued"

    claimed = requests.claim_next(conn, NOW)
    assert claimed.id == first.id
    assert claimed.state == "running"
    assert claimed.pid == os.getpid()
    assert claimed.started_at
    assert (
        datetime.fromisoformat(claimed.lease_until) - NOW
        == timedelta(minutes=30)
    )
    assert requests.claim_next(conn, NOW) is None
    assert _row(conn, second.id)["state"] == "queued"

    conn.execute(
        "UPDATE requests SET lease_until = ? WHERE id = ?",
        ((NOW + timedelta(minutes=10)).isoformat(timespec="seconds"), first.id),
    )
    assert requests.claim_next(conn, NOW) is None

    conn.execute(
        "UPDATE requests SET pid = ? WHERE id = ?",
        (DEAD_PID, first.id),
    )
    reclaimed = requests.claim_next(conn, NOW)
    assert reclaimed.id == first.id
    assert reclaimed.state == "running"
    assert reclaimed.pid == os.getpid()
    assert (
        datetime.fromisoformat(reclaimed.lease_until) - NOW
        == timedelta(minutes=30)
    )
    assert _row(conn, second.id)["state"] == "queued"

    requests.finish(conn, first.id, result_path="status.md")
    turn = requests.claim_next(conn, NOW)
    assert turn.id == second.id
    assert (
        datetime.fromisoformat(turn.lease_until) - NOW
        == timedelta(minutes=45)
    )

    expired = NOW - timedelta(minutes=1)
    conn.execute(
        "UPDATE requests SET lease_until = ? WHERE id = ?",
        (expired.isoformat(timespec="seconds"), second.id),
    )
    again = requests.claim_next(conn, NOW)
    assert again.id == second.id
    assert again.pid == os.getpid()
    assert (
        datetime.fromisoformat(again.lease_until) - NOW
        == timedelta(minutes=45)
    )

    requests.finish(conn, second.id, error="provider down")
    failed = _row(conn, second.id)
    assert failed["state"] == "failed"
    assert failed["error"] == "provider down"
    assert failed["finished_at"]
    assert requests.claim_next(conn, NOW) is None
    rows = requests.history(conn, limit=2)
    assert [row.id for row in rows] == [second.id, first.id]
    assert [row.state for row in rows] == ["failed", "done"]
