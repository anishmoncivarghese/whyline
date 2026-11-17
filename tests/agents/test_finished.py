from datetime import datetime
from pathlib import Path

import pytest

from whyline.agents import definitions as d, service, state, tick


def _agent(repo, trigger: str, name="a"):
    path = repo / ".whyline/agents" / f"{name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'name="{name}"\ninstructions="x"\nrunner="claude"\n[trigger]\n{trigger}\n')
    defn = d.load(path, kind="repo", repo_root=repo)
    conn = state.connect()
    state.accept(conn, defn)
    state.update(conn, defn.agent_id, accepted_at="2026-10-01T00:00:00")
    return defn


def _act(defn):
    return state.get(state.connect(), defn.agent_id)


def test_finished_agent_is_not_run_again(repo, home):
    defn = _agent(repo, 'kind="daily"\nat="07:00"')
    state.finish(state.connect(), defn.agent_id, "ran 3 times")
    started = []
    report = tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=started.append)
    assert report.started == [] and started == []
    assert _act(defn).status == "finished"


def test_once_finishes_after_its_run(repo, home):
    defn = _agent(repo, 'kind="once"\non="2026-10-05"\nat="07:00"')
    started = []
    tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=started.append)
    assert len(started) == 1
    act = _act(defn)
    assert (act.status, act.paused_reason) == ("finished", "ran once on 2026-10-05")


def test_a_once_waiting_for_a_slot_is_not_finished_until_it_runs(repo, home):
    defn = _agent(repo, 'kind="once"\non="2026-10-05"\nat="07:00"')
    conn = state.connect()
    for n in (1, 2):
        conn.execute(
            "INSERT INTO occurrences (agent_id, due_at, status, source) VALUES (?,?,?,?)",
            (f"other{n}", "2026-10-05T06:00:00", "running", "schedule"),
        )
    started = []
    report = tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=started.append)
    assert started == [] and report.skipped_busy == 1
    assert _act(defn).status == "active"
    conn.execute("UPDATE occurrences SET status='done' WHERE agent_id LIKE 'other%'")
    tick.run_tick(now=datetime(2026, 10, 5, 7, 3), spawn=started.append)
    assert len(started) == 1
    act = _act(defn)
    assert (act.status, act.paused_reason) == ("finished", "ran once on 2026-10-05")


def test_a_finished_agents_claimed_run_still_starts(repo, home):
    defn = _agent(repo, 'kind="once"\non="2026-10-05"\nat="07:00"')
    tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=lambda occ: None)
    occ = state.connect().execute("SELECT id FROM occurrences").fetchone()["id"]
    assert tick._runnable(state.connect(), defn.agent_id, datetime(2026, 10, 5, 7, 2),
                          allow_finished=True) is not None
    assert occ


def test_ends_finishes_the_day_after(repo, home):
    defn = _agent(repo, 'kind="daily"\nat="07:00"\nends="2026-10-05"')
    started = []
    tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=started.append)
    assert len(started) == 1 and _act(defn).status == "active"
    tick.run_tick(now=datetime(2026, 10, 6, 6, 0), spawn=started.append)
    act = _act(defn)
    assert (act.status, act.paused_reason) == ("finished", "ended on 2026-10-05")
    assert len(started) == 1


def test_max_runs_finishes_after_the_last_run(repo, home):
    defn = _agent(repo, 'kind="daily"\nat="07:00"\nmax_runs=2')
    for day in (5, 6):
        tick.run_tick(now=datetime(2026, 10, day, 7, 1), spawn=lambda occ: None)
        state.connect().execute("UPDATE occurrences SET status='done' WHERE status='running'")
    act = _act(defn)
    assert (act.status, act.paused_reason) == ("finished", "ran 2 times")
    assert state.run_count(state.connect(), defn.agent_id) == 2


def test_a_once_missed_by_over_a_day_is_recorded_and_alerts_once(repo, home):
    defn = _agent(repo, 'kind="once"\non="2026-10-05"\nat="07:00"')
    seen = []
    for _ in range(2):
        report = tick.run_tick(now=datetime(2026, 10, 7, 9, 0), spawn=lambda occ: None,
                               missed_alert=lambda *a: seen.append(a))
    act = _act(defn)
    assert (act.status, act.paused_reason) == ("finished", "missed on 2026-10-05")
    assert len(seen) == 1 and seen[0][1] == "2026-10-05T07:00:00"
    status = state.connect().execute("SELECT status FROM occurrences").fetchone()["status"]
    assert status == "missed"


def test_start_again_resets_the_run_count(repo, home):
    defn = _agent(repo, 'kind="daily"\nat="07:00"\nmax_runs=1')
    tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=lambda occ: None)
    assert _act(defn).status == "finished"
    service.start_again("a", repo, now=datetime(2026, 10, 5, 8, 0))
    act = _act(defn)
    assert act.status == "active" and act.accepted_at == "2026-10-05T08:00:00"
    assert state.run_count(state.connect(), defn.agent_id) == 0


def test_start_again_refuses_a_past_date(repo, home):
    once = _agent(repo, 'kind="once"\non="2026-10-05"\nat="07:00"', name="o")
    ends = _agent(repo, 'kind="daily"\nat="07:00"\nends="2026-10-05"', name="e")
    for defn in (once, ends):
        state.finish(state.connect(), defn.agent_id, "x")
    for name in ("o", "e"):
        with pytest.raises(ValueError, match="Change the date first."):
            service.start_again(name, repo, now=datetime(2026, 10, 7, 9, 0))
    assert _act(once).status == "finished"


def test_rows_and_summary_show_the_reason(repo, home):
    defn = _agent(repo, 'kind="daily"\nat="07:00"\nmax_runs=1')
    state.finish(state.connect(), defn.agent_id, "ran 1 times")
    found = [r for r in service.rows(repo) if r.defn.name == "a"]
    assert found[0].status == "finished" and found[0].reason == "ran 1 times"
    text = service.scheduler_summary(found, on=True, now=datetime(2026, 10, 9, 21, 0))
    assert "finished: ran 1 times" in text


def test_a_failed_spawn_does_not_count_as_a_run(repo, home):
    defn = _agent(repo, 'kind="once"\non="2026-10-05"\nat="07:00"\nmax_runs=1')

    def boom(occ):
        raise OSError("no spawn")

    tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=boom, alert=lambda *a: None)
    assert state.run_count(state.connect(), defn.agent_id) == 0


def test_a_failed_once_spawn_stays_active_until_the_day_has_passed(repo, home):
    defn = _agent(repo, 'kind="once"\non="2026-10-05"\nat="07:00"')

    def boom(occ):
        raise OSError("no spawn")

    tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=boom, alert=lambda *a: None)
    assert _act(defn).status == "active"
    tick.run_tick(now=datetime(2026, 10, 6, 6, 0), spawn=boom, alert=lambda *a: None)
    assert _act(defn).status == "active"
    tick.run_tick(now=datetime(2026, 10, 6, 7, 5), spawn=boom, alert=lambda *a: None)
    act = _act(defn)
    assert (act.status, act.paused_reason) == ("finished", "missed on 2026-10-05")


def test_a_failed_spawn_does_not_finish_a_max_runs_agent(repo, home):
    defn = _agent(repo, 'kind="every"\nevery_minutes=5\nmax_runs=1')

    def boom(occ):
        raise OSError("no spawn")

    tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=boom, alert=lambda *a: None)
    assert _act(defn).status == "active"


def test_queued_claims_do_not_exceed_max_runs(repo, home):
    defn = _agent(repo, 'kind="every"\nevery_minutes=5\nmax_runs=2')
    conn = state.connect()
    for n in (1, 2):
        conn.execute(
            "INSERT INTO occurrences (agent_id, due_at, status, source) VALUES (?,?,?,?)",
            (defn.agent_id, f"2026-10-05T07:0{n}:00", "done", "schedule"),
        )
    for n in (3, 4):
        conn.execute(
            "INSERT INTO occurrences (agent_id, due_at, status, source) VALUES (?,?,?,?)",
            (defn.agent_id, f"2026-10-05T07:0{n}:00", "claimed", "schedule"),
        )
    started = []
    tick.run_tick(now=datetime(2026, 10, 5, 7, 6), spawn=started.append)
    act = _act(defn)
    assert (act.status, act.paused_reason) == ("finished", "ran 2 times")
    assert started == []
    tick.run_tick(now=datetime(2026, 10, 5, 7, 12), spawn=started.append)
    assert started == [] and state.run_count(state.connect(), defn.agent_id) == 2
