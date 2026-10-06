"""Item 2 of the brainstorm roadmap: ownership claims and handoffs stop
presenting stale state as current (docs/superpowers/plans/2026-09-30-brainstorm-roadmap.md).
"""

import json
from datetime import datetime, timedelta, timezone

from whyline import cli, events, handoff, ledger, ownership, paths, sync


def _init(repo):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def run_in(repo, argv, capsys, monkeypatch):
    monkeypatch.chdir(repo.path)
    code = cli.main(argv)
    return code, capsys.readouterr().out


# --- 2.1 claim leases ------------------------------------------------------------


def test_a_new_claim_records_a_72_hour_lease_by_default(repo):
    _init(repo)
    state, _ = ownership.claim(repo.path, task="T-1", actor="codex", role="", files=[])
    claim = state["claims"][0]
    lease = _at(claim["expires_at"]) - _at(claim["claimed_at"])
    assert lease == timedelta(hours=72)


def test_ttl_sets_the_lease_length(repo):
    _init(repo)
    state, _ = ownership.claim(
        repo.path, task="T-1", actor="codex", role="", files=[], ttl_hours=2
    )
    claim = state["claims"][0]
    assert _at(claim["expires_at"]) - _at(claim["claimed_at"]) == timedelta(hours=2)


def test_a_legacy_claim_without_expiry_goes_stale_72_hours_after_it_was_made():
    claimed = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
    legacy = {"task": "OLD", "actor": "a", "claimed_at": "2026-09-27T12:00:00.000Z"}
    active, stale = ownership.split([legacy], now=claimed + timedelta(hours=71))
    assert (active, stale) == ([legacy], [])
    active, stale = ownership.split([legacy], now=claimed + timedelta(hours=73))
    assert (active, stale) == ([], [legacy])


def test_a_claim_with_an_unreadable_timestamp_is_never_silently_hidden():
    odd = {"task": "X", "actor": "a", "claimed_at": "not a time"}
    active, stale = ownership.split([odd], now=datetime.now(timezone.utc))
    assert active == [odd] and stale == []


def test_reclaiming_renews_the_lease(repo):
    _init(repo)
    ownership.claim(repo.path, task="T-1", actor="codex", role="", files=[], ttl_hours=1)
    state, _ = ownership.claim(
        repo.path, task="T-1", actor="codex", role="", files=[], ttl_hours=10
    )
    assert len(state["claims"]) == 1
    claim = state["claims"][0]
    assert _at(claim["expires_at"]) - _at(claim["claimed_at"]) == timedelta(hours=10)


# --- 2.2 stale claims stop warning ------------------------------------------------


def test_overlaps_with_stale_claims_are_not_reported(repo):
    _init(repo)
    stale = {
        "task": "OLD", "actor": "grok", "role": "", "files": ["a.py"],
        "claimed_at": "2020-01-01T00:00:00.000Z", "expires_at": "2020-01-04T00:00:00.000Z",
    }
    paths.ownership_path(repo.path).write_text(
        json.dumps({"v": 1, "claims": [stale]}), encoding="utf-8"
    )
    state, found = ownership.claim(
        repo.path, task="NEW", actor="codex", role="", files=["a.py"]
    )
    assert found == []
    assert len(state["claims"]) == 2  # stale claim is kept, just inert


def test_sync_hides_stale_claims_behind_one_line(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    stale = [
        {"task": f"OLD-{n}", "actor": "antigravity", "role": "", "files": [],
         "claimed_at": "2020-01-01T00:00:00.000Z"}
        for n in range(25)
    ]
    paths.ownership_path(repo.path).write_text(
        json.dumps({"v": 1, "claims": stale}), encoding="utf-8"
    )
    ownership.claim(repo.path, task="LIVE", actor="codex", role="implementer", files=[])

    text = sync.compose(repo.path)

    assert "LIVE" in text
    assert "OLD-3" not in text
    assert "25 stale claims hidden" in text
    assert "whyline release --stale" in text

    payload = sync.payload(repo.path, None, None)
    assert [c["task"] for c in payload["ownership"]["claims"]] == ["LIVE"]
    assert len(payload["ownership"]["stale"]) == 25


# --- 2.3 release forms ------------------------------------------------------------


def _claims(repo):
    return [(c["task"], c["actor"]) for c in ownership.load(repo.path)["claims"]]


def _seed(repo):
    _init(repo)
    ownership.claim(repo.path, task="T-1", actor="codex", role="", files=[])
    ownership.claim(repo.path, task="T-1", actor="claude", role="", files=[])
    ownership.claim(repo.path, task="T-2", actor="codex", role="", files=[])
    state = ownership.load(repo.path)
    state["claims"].append({"task": "OLD", "actor": "grok", "claimed_at": "2020-01-01T00:00:00.000Z"})
    paths.ownership_path(repo.path).write_text(json.dumps(state), encoding="utf-8")


def test_release_task_and_actor_is_unchanged(repo, capsys, monkeypatch):
    _seed(repo)
    code, out = run_in(repo, ["release", "T-1", "--actor", "codex"], capsys, monkeypatch)
    assert code == cli.EXIT_OK
    assert ("T-1", "codex") not in _claims(repo)
    assert ("T-1", "claude") in _claims(repo)
    assert "Released 1 claim" in out


def test_release_task_without_actor_releases_every_actor(repo, capsys, monkeypatch):
    _seed(repo)
    code, out = run_in(repo, ["release", "T-1"], capsys, monkeypatch)
    assert code == cli.EXIT_OK
    assert sorted(_claims(repo)) == [("OLD", "grok"), ("T-2", "codex")]
    assert "Released 2 claims" in out


def test_release_stale_removes_only_expired_claims(repo, capsys, monkeypatch):
    _seed(repo)
    code, out = run_in(repo, ["release", "--stale", "--json"], capsys, monkeypatch)
    assert code == cli.EXIT_OK
    assert json.loads(out)["released"] == 1
    assert ("OLD", "grok") not in _claims(repo)
    assert len(_claims(repo)) == 3


def test_release_all_removes_everything(repo, capsys, monkeypatch):
    _seed(repo)
    code, _ = run_in(repo, ["release", "--all"], capsys, monkeypatch)
    assert code == cli.EXIT_OK
    assert _claims(repo) == []


def test_release_needs_something_to_release(repo, capsys, monkeypatch):
    _seed(repo)
    code = None
    monkeypatch.chdir(repo.path)
    code = cli.main(["release"])
    assert code == cli.EXIT_USAGE
    assert "TASK, --stale or --all" in capsys.readouterr().err
    assert len(_claims(repo)) == 4


# --- 2.4 handoff close --------------------------------------------------------------


def _handoff(repo, status="ready-for-review"):
    return handoff.create(
        repo.path, task="WL-42", from_actor="codex", to_actor="claude", status=status,
    )


def test_close_marks_the_handoff_closed_without_touching_relay_fields(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    original = _handoff(repo)

    closed = handoff.close(repo.path, status="completed", summary="shipped")

    on_disk = json.loads(paths.active_handoff_path(repo.path).read_text(encoding="utf-8"))
    assert on_disk == closed
    # whyline-relay routes on these; closing must not look like a new handoff
    for key in ("id", "task", "to_actor", "from_actor", "status"):
        assert on_disk[key] == original[key]
    assert on_disk["closed"] is True
    assert on_disk["closed_status"] == "completed"
    assert on_disk["closed_summary"] == "shipped"
    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert found[-1]["type"] == events.HANDOFF_CLOSED
    assert found[-1]["closes"] == original["id"]


def test_close_refuses_when_there_is_nothing_open(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    assert handoff.close(repo.path) is None
    _handoff(repo)
    assert handoff.close(repo.path) is not None
    assert handoff.close(repo.path) is None  # already closed


def test_handoff_close_command(repo, capsys, monkeypatch):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    _handoff(repo)
    code, out = run_in(
        repo, ["handoff", "close", "--status", "cancelled"], capsys, monkeypatch
    )
    assert code == cli.EXIT_OK
    assert "Closed handoff WL-42 (cancelled)" in out
    code = cli.main(["handoff", "close"])
    assert code == cli.EXIT_ERROR
    assert "No open handoff" in capsys.readouterr().err


def test_an_ordinary_handoff_still_requires_from_and_to(repo, capsys, monkeypatch):
    _init(repo)
    monkeypatch.chdir(repo.path)
    code = cli.main(["handoff", "WL-1", "--status", "x"])
    assert code == cli.EXIT_USAGE
    assert "--from" in capsys.readouterr().err


# --- 2.5 settled handoffs -------------------------------------------------------------


def test_settled_when_closed(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    _handoff(repo)
    record = handoff.close(repo.path)
    assert handoff.settled(repo.path, record)["reason"] == "closed"


def test_settled_when_terminal_and_head_has_moved_on(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    record = _handoff(repo, status="Approved")
    assert handoff.settled(repo.path, record) is None  # still at HEAD
    repo.commit({"b.py": "two\n"}, "second", epoch=1_000_100)
    repo.commit({"c.py": "three\n"}, "third", epoch=1_000_200)
    settled = handoff.settled(repo.path, record)
    assert settled == {"reason": "behind", "commits_behind": 2}


def test_not_settled_when_open_even_if_head_moved(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    record = _handoff(repo, status="ready-for-review")
    repo.commit({"b.py": "two\n"}, "second", epoch=1_000_100)
    assert handoff.settled(repo.path, record) is None


def test_not_settled_when_the_commit_is_unknown_or_not_an_ancestor(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    record = {**_handoff(repo, status="approved"), "current_commit": "f" * 40}
    assert handoff.settled(repo.path, record) is None
    assert handoff.settled(repo.path, {**record, "current_commit": ""}) is None


def test_sync_shows_a_settled_handoff_as_one_line_and_stops_narrowing_by_it(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    record = _handoff(repo, status="approved")
    repo.commit({"b.py": "two\n"}, "second", epoch=1_000_100)
    for task in ("WL-42", "WL-99"):
        ledger.append(paths.ledger_path(repo.path), events.new_event(
            events.NOTE, decision=f"decision for {task}", because="x",
            alternatives=[], files=[], actor="codex", role="", task=task,
        ))

    text = sync.compose(repo.path)

    assert "Active handoff: none" in text
    assert "Last handoff: WL-42 (approved" in text
    assert "1 commit ago" in text
    # the old task no longer filters decisions: both show
    assert "decision for WL-42" in text and "decision for WL-99" in text

    payload = sync.payload(repo.path, None, None)
    assert payload["active_handoff"] is None
    assert payload["last_handoff"]["id"] == record["id"]
    assert payload["last_handoff"]["settled"] == {"reason": "behind", "commits_behind": 1}


def test_explicit_task_still_selects_after_settling(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    handoff.create(repo.path, task="WL-42", from_actor="a", to_actor="b", status="done")
    repo.commit({"b.py": "two\n"}, "second", epoch=1_000_100)
    assert sync.payload(repo.path, "WL-42", None)["task"] == "WL-42"


# --- status and instructions ---------------------------------------------------------


def test_status_reports_stale_claims_and_a_settled_handoff(repo, capsys, monkeypatch):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    handoff.create(repo.path, task="FC-3", from_actor="a", to_actor="b", status="approved")
    repo.commit({"b.py": "two\n"}, "second", epoch=1_000_100)
    paths.ownership_path(repo.path).write_text(json.dumps({"v": 1, "claims": [
        {"task": "OLD", "actor": "grok", "claimed_at": "2020-01-01T00:00:00.000Z"},
    ]}), encoding="utf-8")
    code, out = run_in(repo, ["status"], capsys, monkeypatch)
    assert "Last handoff   FC-3: approved (settled, 1 commit behind HEAD)" in out
    assert "0 active claims; 1 stale (whyline release --stale)" in out


def test_installed_instructions_say_how_to_close_and_release():
    from whyline import agentsmd

    assert "whyline handoff close --status" in agentsmd.INSTRUCTION
    assert "whyline release <task-id>" in agentsmd.INSTRUCTION


# --- finished tasks: a later terminal handoff retires the claim ----------------------


def test_a_claim_goes_stale_when_its_task_is_later_handed_off_as_finished(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    ownership.claim(repo.path, task="T-1", actor="antigravity", role="", files=["a.py"])
    ownership.claim(repo.path, task="T-2", actor="codex", role="", files=[])
    handoff.create(repo.path, task="T-1", from_actor="codex", to_actor="x", status="Approved")
    handoff.create(repo.path, task="T-2", from_actor="codex", to_actor="x", status="ready-for-review")

    payload = sync.payload(repo.path, None, None)

    assert [c["task"] for c in payload["ownership"]["claims"]] == ["T-2"]
    assert [c["task"] for c in payload["ownership"]["stale"]] == ["T-1"]
    # and it no longer overlaps anything
    _, found = ownership.claim(repo.path, task="T-9", actor="claude", role="", files=["a.py"])
    assert found == []


def test_a_claim_made_after_the_finishing_handoff_stays_active(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    handoff.create(repo.path, task="T-1", from_actor="grok", to_actor="x", status="approved")
    ownership.claim(repo.path, task="T-1", actor="antigravity", role="", files=[])
    assert [c["task"] for c in sync.payload(repo.path, None, None)["ownership"]["claims"]] == ["T-1"]


def test_closing_a_handoff_finishes_its_task(repo):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    ownership.claim(repo.path, task="WL-42", actor="codex", role="", files=[])
    _handoff(repo)
    handoff.close(repo.path, status="cancelled")
    assert sync.payload(repo.path, None, None)["ownership"]["claims"] == []


def test_release_stale_also_releases_finished_claims(repo, capsys, monkeypatch):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    _init(repo)
    ownership.claim(repo.path, task="T-1", actor="codex", role="", files=[])
    ownership.claim(repo.path, task="T-2", actor="codex", role="", files=[])
    handoff.create(repo.path, task="T-1", from_actor="codex", to_actor="x", status="done")
    code, out = run_in(repo, ["release", "--stale"], capsys, monkeypatch)
    assert code == cli.EXIT_OK and "Released 1 claim" in out
    assert _claims(repo) == [("T-2", "codex")]


def test_timeline_names_the_task_and_status_of_handoff_events():
    from whyline import render

    text = render.timeline_text([
        {"ts": "2026-09-30T01:00:00.000Z", "type": "Handoff", "task": "T-1", "status": "approved"},
        {"ts": "2026-09-30T02:00:00.000Z", "type": "HandoffClosed", "task": "T-1", "status": "completed"},
    ])
    assert "Handoff         T-1: approved" in text
    assert "HandoffClosed   T-1: completed" in text


def test_timeline_names_an_agent_run():
    from whyline import render

    text = render.timeline_text([
        {
            "ts": "2026-10-05T07:00:03.000Z",
            "type": "AgentRunCompleted",
            "agent": "digest",
            "outcome": "succeeded",
            "cli": "codex",
            "run_id": "20261005-070003-digest-ab12",
        },
    ])
    assert "AgentRunCompleted digest: succeeded via codex" in text
