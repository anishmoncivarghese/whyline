import json
from dataclasses import replace
from datetime import datetime

import pytest

from whyline.agents import definitions as d, gates, runner

NOW = datetime(2026, 10, 5, 7, 0)
_BASE = 'name = "ck"\ninstructions = "x"\nrunner = "claude"\n'


class Result:
    def __init__(self, code, output):
        self.exit_code, self.output = code, output


def _parse(repo, table):
    return d.parse(_BASE + table, kind="repo", path=repo / ".whyline/agents/ck.toml", repo_root=repo)


def _agent(repo, **fields):
    return replace(_parse(repo, ""), gate="reminder-overdue", **fields)


def _script(*results):
    calls = []

    def run_fn(command, prompt, **kwargs):
        calls.append((list(command), prompt))
        return results[len(calls) - 1]

    return run_fn, calls


REAL = gates.Readers


def _fake_reminders(monkeypatch, rows):
    monkeypatch.setattr(gates, "Readers", lambda: REAL(reminders=lambda: rows))


def test_checkin_fields_round_trip(repo):
    defn = _parse(repo, '[checkin]\ngate = "mail-from"\nactive_hours = "09:00-17:00 mon-fri"\n'
                        'silent = true\n[checkin.gate_args]\nsender = "ann@x.com"\n')
    assert (defn.gate, defn.gate_args, defn.active_hours, defn.silent) == (
        "mail-from", {"sender": "ann@x.com"}, "09:00-17:00 mon-fri", True)
    again = d.parse(d.render(defn), kind="repo", path=defn.path, repo_root=repo)
    assert again == defn


def test_an_old_agent_file_loads_unchanged(repo):
    defn = _parse(repo, "")
    assert (defn.gate, defn.gate_args, defn.active_hours, defn.silent) == ("", {}, "", False)
    assert "[checkin]" not in d.render(defn)


@pytest.mark.parametrize("hours", ["9-17", "25:00-26:00", "09:00-17:00 monday", "09:00-09:00",
                                   "09:00-17:00 mon-"])
def test_wrong_active_hours_are_refused(repo, hours):
    with pytest.raises(d.DefinitionError, match="active_hours"):
        _parse(repo, f'[checkin]\nactive_hours = "{hours}"\n')


def test_an_unknown_gate_is_refused(repo):
    with pytest.raises(d.DefinitionError, match="checkin gate"):
        _parse(repo, '[checkin]\ngate = "nope"\n')


def test_empty_gate_skips_the_agent(repo, home, monkeypatch):
    _fake_reminders(monkeypatch, [])
    run_fn, calls = _script()
    rec = runner.execute_once(_agent(repo), source="schedule", now=NOW, run_fn=run_fn)
    assert rec.outcome == "nothing_new" and calls == []


def test_a_gate_with_items_runs_the_agent_with_found_md(repo, home, monkeypatch):
    _fake_reminders(monkeypatch, [("Pay rent", "2026-10-01T09:00:00", "Home")])
    ok = Result(0, json.dumps({"result": "ok", "permission_denials": []}))
    run_fn, calls = _script(ok)
    defn = _agent(repo)
    rec = runner.execute_once(defn, source="schedule", now=NOW, run_fn=run_fn)
    assert rec.outcome == "succeeded" and len(calls) == 1
    assert "found.md" in calls[0][1]
    # the gate remembered the item, so the next run has nothing new
    rec = runner.execute_once(defn, source="schedule", now=NOW, run_fn=run_fn)
    assert rec.outcome == "nothing_new" and len(calls) == 1


def test_a_gate_error_fails_the_run_and_starts_no_provider(repo, home, monkeypatch):
    def boom():
        raise gates.GateError("Calendar access was refused")

    monkeypatch.setattr(gates, "Readers", lambda: REAL(reminders=boom))
    run_fn, calls = _script()
    rec = runner.execute_once(_agent(repo), source="schedule", now=NOW, run_fn=run_fn)
    assert calls == [] and rec.outcome == "failed"
    assert rec.reason == "gate failed: Calendar access was refused"
