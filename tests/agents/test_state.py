import os
import sqlite3

import pytest

from whyline.agents import definitions as d, state


def _agent(repo, instructions="x"):
    path = repo / ".whyline/agents/a.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'name="a"\ninstructions="{instructions}"\nrunner="claude"')
    return d.load(path, kind="repo", repo_root=repo)


def test_accept_then_get(repo, home):
    conn = state.connect()
    act = state.accept(conn, _agent(repo))
    assert act.status == "active" and state.get(conn, act.agent_id).accepted_hash == act.accepted_hash
    if os.name != "nt":  # Windows has no POSIX permission bits
        assert (state.paths.state_path().stat().st_mode & 0o777) == 0o600


def test_an_edited_definition_needs_review_until_accepted_again(repo, home):
    conn = state.connect()
    state.accept(conn, _agent(repo))
    edited = _agent(repo, instructions="changed by a git pull")
    assert state.check_hash(conn, edited) == "needs_review"
    assert state.get(conn, edited.agent_id).status == "needs_review"
    # A later tick sees the same edit and still does not run it.
    assert state.check_hash(conn, edited) == "needs_review"
    assert state.status_of(conn, edited) == "needs_review"
    state.accept(conn, edited)
    assert state.check_hash(conn, edited) == "active"
    assert state.get(conn, edited.agent_id).status == "active"


def test_an_edit_stops_a_paused_agent_until_accepted_again(repo, home):
    conn = state.connect()
    agent = _agent(repo)
    state.accept(conn, agent)
    state.set_status(conn, agent.agent_id, "paused", "by you")
    edited = _agent(repo, instructions="changed by a git pull")
    assert state.check_hash(conn, edited) == "needs_review"
    assert state.status_of(conn, edited) == "needs_review"
    state.accept(conn, edited)
    assert state.check_hash(conn, edited) == "active"


def test_pause_resume_and_not_accepted(repo, home):
    conn = state.connect()
    agent = _agent(repo)
    assert state.status_of(conn, agent) == "not accepted"
    assert state.check_hash(conn, agent) == "not accepted"
    state.accept(conn, agent)
    state.set_status(conn, agent.agent_id, "paused", "by you")
    assert state.get(conn, agent.agent_id).paused_reason == "by you"
    state.set_status(conn, agent.agent_id, "active")
    assert state.get(conn, agent.agent_id).status == "active"


def test_update_rejects_unknown_fields_and_remove_clears_occurrences(repo, home):
    conn = state.connect()
    agent = _agent(repo)
    state.accept(conn, agent)
    state.update(conn, agent.agent_id, consecutive_failures=2, backoff_until="2026-10-05T10:00:00")
    act = state.get(conn, agent.agent_id)
    assert act.consecutive_failures == 2 and act.backoff_until == "2026-10-05T10:00:00"
    with pytest.raises(ValueError, match="unknown"):
        state.update(conn, agent.agent_id, nope=1)
    conn.execute(
        "INSERT INTO occurrences (agent_id, due_at, source, status) VALUES (?, ?, 'schedule', 'claimed')",
        (agent.agent_id, "2026-10-05T07:00:00"),
    )
    state.remove(conn, agent.agent_id)
    assert state.get(conn, agent.agent_id) is None
    assert conn.execute("SELECT count(*) FROM occurrences").fetchone()[0] == 0


def test_the_same_due_time_cannot_be_claimed_twice(repo, home):
    conn = state.connect()
    agent = _agent(repo)
    state.accept(conn, agent)
    sql = (
        "INSERT INTO occurrences (agent_id, due_at, source, status) "
        "VALUES (?, ?, 'schedule', 'claimed')"
    )
    conn.execute(sql, (agent.agent_id, "2026-10-05T07:00:00"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (agent.agent_id, "2026-10-05T07:00:00"))


def test_a_corrupt_store_is_set_aside(home):
    path = state.paths.state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a database")
    conn = state.connect()
    assert state.all_activations(conn) == []
    aside = [p for p in path.parent.iterdir() if p.name.startswith("state.sqlite3.corrupt-")]
    assert aside and aside[0].read_bytes() == b"not a database"
    if os.name != "nt":  # Windows has no POSIX permission bits
        assert (path.stat().st_mode & 0o777) == 0o600
