import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline import cli
from whyline.agents import definitions as d, paths, state, tick


def _scheduled(repo, at="07:00", name="a"):
    path = repo / ".whyline/agents" / f"{name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'name="{name}"\ninstructions="x"\nrunner="claude"\n[trigger]\nkind="daily"\nat="{at}"'
    )
    defn = d.load(path, kind="repo", repo_root=repo)
    conn = state.connect()
    state.accept(conn, defn)
    state.update(conn, defn.agent_id, accepted_at="2026-10-01T00:00:00")
    return defn


def test_a_due_run_is_claimed_and_started_once(repo, home):
    _scheduled(repo)
    started = []
    now = datetime(2026, 10, 5, 7, 1)
    report = tick.run_tick(now=now, spawn=started.append)
    assert len(report.started) == 1 and started == report.started
    again = tick.run_tick(now=now, spawn=started.append)
    assert again.started == [] and len(started) == 1


def test_two_ticks_at_once_start_one_run(repo, home):
    _scheduled(repo)
    started, lock = [], threading.Lock()

    def spawn(occ):
        with lock:
            started.append(occ)

    now = datetime(2026, 10, 5, 7, 1)
    threads = [threading.Thread(target=tick.run_tick, kwargs={"now": now, "spawn": spawn}) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(started) == 1


def test_an_edited_definition_is_not_run(repo, home):
    defn = _scheduled(repo)
    defn.path.write_text(defn.path.read_text().replace('instructions="x"', 'instructions="changed"'))
    report = tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=lambda occ: None)
    assert report.started == [] and report.reviewed == [defn.agent_id]


def test_missed_days_are_recorded_and_one_catch_up_runs(repo, home):
    defn = _scheduled(repo)
    conn = state.connect()
    state.update(conn, defn.agent_id, last_run_at="2026-10-02T07:00:00")
    report = tick.run_tick(now=datetime(2026, 10, 5, 9, 0), spawn=lambda occ: None)
    assert len(report.started) == 1 and report.missed == 2
    occ = state.occurrence(conn, report.started[0])
    assert occ["source"] == "catch_up" and occ["due_at"] == "2026-10-05T07:00:00"


def test_paused_backoff_and_busy_agents_wait(repo, home):
    defn = _scheduled(repo)
    conn = state.connect()
    state.set_status(conn, defn.agent_id, "paused", "by you")
    assert tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=lambda o: None).started == []
    state.update(conn, defn.agent_id, status="active", backoff_until="2026-10-05T10:00:00")
    assert tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=lambda o: None).started == []


def test_a_queued_claim_is_not_started_after_its_definition_changes(repo, home):
    """Three due agents fill both run slots. Editing the one still claimed,
    then freeing a slot, must mark it needs_review and leave it claimed."""
    conn = state.connect()
    for name in ("a", "b", "c"):
        path = repo / ".whyline/agents" / f"{name}.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'name="{name}"\ninstructions="x"\nrunner="claude"\n'
            '[trigger]\nkind="daily"\nat="07:00"\n'
        )
        defn = d.load(path, kind="repo", repo_root=repo)
        state.accept(conn, defn)
        state.update(conn, defn.agent_id, accepted_at="2026-10-01T00:00:00")

    now = datetime(2026, 10, 5, 7, 1)
    first = tick.run_tick(now=now, spawn=lambda occ: None)
    assert len(first.started) == 2 and first.skipped_busy == 1
    waiting = conn.execute(
        "SELECT id, agent_id FROM occurrences WHERE status='claimed'"
    ).fetchone()
    assert waiting is not None
    act = state.get(conn, waiting["agent_id"])
    Path(act.def_path).write_text(
        Path(act.def_path).read_text().replace('instructions="x"', 'instructions="changed"')
    )
    freed = conn.execute(
        "SELECT id FROM occurrences WHERE status='running' ORDER BY id"
    ).fetchone()
    state.set_occurrence(conn, freed["id"], status="done")

    started = []
    report = tick.run_tick(now=now, spawn=started.append)
    assert waiting["agent_id"] in report.reviewed
    assert state.get(conn, waiting["agent_id"]).status == "needs_review"
    assert waiting["id"] not in report.started and waiting["id"] not in started
    assert state.occurrence(conn, waiting["id"])["status"] == "claimed"


def test_an_old_store_gains_accepted_at(home):
    path = paths.state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path)
    raw.execute(
        """
        CREATE TABLE activations (
          agent_id TEXT PRIMARY KEY, kind TEXT, root TEXT, def_path TEXT, accepted_hash TEXT,
          status TEXT, paused_reason TEXT DEFAULT '', last_run_at TEXT DEFAULT '',
          next_due_at TEXT DEFAULT '', consecutive_failures INTEGER DEFAULT 0,
          backoff_until TEXT DEFAULT '', using_backup_until TEXT DEFAULT '',
          folder_snapshot TEXT DEFAULT ''
        )
        """
    )
    raw.execute(
        "INSERT INTO activations (agent_id, kind, root, def_path, accepted_hash, status) "
        "VALUES ('personal:a', 'personal', '/', '/a.toml', 'h', 'active')"
    )
    raw.commit()
    raw.close()
    conn = state.connect()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(activations)")}
    assert "accepted_at" in columns
    assert state.get(conn, "personal:a").accepted_at == ""
    state.update(conn, "personal:a", accepted_at="2026-10-01T00:00:00")
    assert state.get(conn, "personal:a").accepted_at == "2026-10-01T00:00:00"


def test_tick_command_is_quiet_until_something_happens(repo, home, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    reports = [
        tick.TickReport(),
        tick.TickReport(started=[7], missed=2, reviewed=["repo:x:a"]),
    ]

    def run_tick(**kwargs):
        return reports.pop(0)

    monkeypatch.setattr(tick, "run_tick", run_tick)
    assert cli.main(["agents", "tick"]) == 0
    assert capsys.readouterr().out == ""
    assert (paths.home() / "scheduler.log").exists()
    assert cli.main(["agents", "tick"]) == 0
    out = capsys.readouterr().out
    assert "tick" in out and "started 1" in out and "missed 2" in out and "repo:x:a" in out


def _running_occurrence(repo, name="a"):
    defn = _scheduled(repo, name=name)
    report = tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=lambda occ: None)
    assert len(report.started) == 1
    return defn, report.started[0]


def _runner_calls(monkeypatch):
    calls = []

    def execute_once(defn, **kwargs):
        calls.append((defn, kwargs))
        return SimpleNamespace(run_id="run-1")

    monkeypatch.setattr("whyline.agents.runner.execute_once", execute_once)
    return calls


def test_run_occurrence_executes_the_accepted_definition(repo, home, monkeypatch):
    defn, occ_id = _running_occurrence(repo)
    calls = _runner_calls(monkeypatch)
    record = tick.run_occurrence(occ_id)
    assert record is not None and record.run_id == "run-1"
    assert len(calls) == 1
    ran, kwargs = calls[0]
    assert ran.agent_id == defn.agent_id and kwargs["unattended"] is True
    assert kwargs["source"] == "schedule"
    occ = state.occurrence(state.connect(), occ_id)
    assert occ["status"] == "done" and occ["run_id"] == "run-1"


def test_run_occurrence_does_not_run_after_an_edit_or_pause(repo, home, monkeypatch):
    """The detached process starts after spawn. An edit or a pause in
    between must not call the runner, and must leave the due time claimed."""
    defn, edited_id = _running_occurrence(repo, "a")
    calls = _runner_calls(monkeypatch)
    defn.path.write_text(defn.path.read_text().replace('instructions="x"', 'instructions="changed"'))
    assert tick.run_occurrence(edited_id) is None
    assert calls == []
    conn = state.connect()
    assert state.occurrence(conn, edited_id)["status"] == "claimed"
    assert state.get(conn, defn.agent_id).status == "needs_review"

    paused, paused_id = _running_occurrence(repo, "b")
    state.set_status(conn, paused.agent_id, "paused", "by you")
    assert tick.run_occurrence(paused_id) is None
    assert calls == []
    assert state.occurrence(conn, paused_id)["status"] == "claimed"
    assert state.get(conn, paused.agent_id).status == "paused"


def test_run_occurrence_is_parsed(repo, home):
    tick_args = cli.build_parser().parse_args(["agents", "tick"])
    assert tick_args.agents_command == "tick"
    occurred = cli.build_parser().parse_args(["agents", "run", "--occurrence", "4"])
    assert occurred.occurrence == 4 and occurred.name is None
    named = cli.build_parser().parse_args(["agents", "run", "a"])
    assert named.name == "a" and named.occurrence is None


def _queued(repo, name="q"):
    """An accepted agent with a claimed occurrence still waiting to start."""
    defn = _scheduled(repo, name=name)
    conn = state.connect()
    occ_id = state.claim(conn, defn.agent_id, "2026-10-05T07:00:00", "schedule")
    state.update(conn, defn.agent_id, last_run_at="2026-10-05T07:00:00")
    return defn, occ_id


def test_a_queued_claim_waits_until_backoff_expires(repo, home):
    # Codex's AG-12 round-8 finding: a claim already waiting must not start
    # while the agent is in backoff, and must start once backoff is over.
    defn, occ_id = _queued(repo)
    conn = state.connect()
    state.update(conn, defn.agent_id, backoff_until="2026-10-05T10:00:00")
    early = tick.run_tick(now=datetime(2026, 10, 5, 7, 5), spawn=lambda occ: None)
    assert occ_id not in early.started
    assert state.occurrence(conn, occ_id)["status"] == "claimed"
    later = tick.run_tick(now=datetime(2026, 10, 5, 10, 1), spawn=lambda occ: None)
    assert occ_id in later.started


def test_a_backed_off_queued_claim_does_not_block_a_later_agent(repo, home):
    first, first_id = _queued(repo, "first")
    second, second_id = _queued(repo, "second")
    conn = state.connect()
    state.update(conn, first.agent_id, backoff_until="2026-10-05T10:00:00")
    report = tick.run_tick(now=datetime(2026, 10, 5, 7, 5), spawn=lambda occ: None)
    assert first_id not in report.started
    assert second_id in report.started
    assert state.occurrence(conn, first_id)["status"] == "claimed"


def test_run_occurrence_does_not_run_during_backoff(repo, home, monkeypatch):
    defn, occ_id = _running_occurrence(repo)
    calls = _runner_calls(monkeypatch)
    conn = state.connect()
    state.update(conn, defn.agent_id, backoff_until="2026-10-05T10:00:00")
    assert tick.run_occurrence(occ_id, now=datetime(2026, 10, 5, 7, 2)) is None
    assert calls == []
    assert state.occurrence(conn, occ_id)["status"] == "claimed"
    assert tick.run_occurrence(occ_id, now=datetime(2026, 10, 5, 10, 1)) is not None
    assert len(calls) == 1


def _block(conn, defn, reason):
    if reason == "paused":
        state.set_status(conn, defn.agent_id, "paused", "by you")
    elif reason == "edited":
        defn.path.write_text(defn.path.read_text().replace('instructions="x"', 'instructions="new"'))
    elif reason == "backoff":
        state.update(conn, defn.agent_id, backoff_until="2026-10-06T00:00:00")


@pytest.mark.parametrize("reason", ["paused", "edited", "backoff"])
def test_every_reason_not_to_run_blocks_both_starting_and_running(repo, home, monkeypatch, reason):
    # One gate decides whether an agent may run; the queued start and the
    # detached run process must agree on it.
    conn = state.connect()
    queued, queued_id = _queued(repo, "q")
    _block(conn, queued, reason)
    report = tick.run_tick(now=datetime(2026, 10, 5, 7, 5), spawn=lambda occ: None)
    assert queued_id not in report.started
    assert state.occurrence(conn, queued_id)["status"] == "claimed"

    running, running_id = _running_occurrence(repo, "r")
    calls = _runner_calls(monkeypatch)
    _block(conn, running, reason)
    assert tick.run_occurrence(running_id, now=datetime(2026, 10, 5, 7, 5)) is None
    assert calls == []
    assert state.occurrence(conn, running_id)["status"] == "claimed"
