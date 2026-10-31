import stat
from pathlib import Path

import pytest

from whyline.workflows import definitions as d
from whyline.workflows import state

EXAMPLE = '''
name = "pr-digest"
description = "Weekday PR summary to Telegram"
version = 1

[trigger]
kind = "weekdays"
at = "08:00"

[[step]]
id = "summarise"
type = "agent"
runner = "claude"
backup = ["codex"]
instructions = "Summarise these PRs: what needs my action today."
output = "text"

[[step]]
id = "send"
type = "deliver"
to = "telegram"
text = "{{ steps.summarise.output }}"

[layout]
summarise = [0, 0]
send = [1, 0]
'''


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def load(text: str = EXAMPLE) -> d.Workflow:
    return d.parse(text, kind="personal", path=Path("w.toml"))


@pytest.fixture
def conn(home):
    return state.connect()


def test_accept_then_check_is_active(conn):
    wf = load()
    act = state.accept(conn, wf)
    assert act.status == "active"
    assert "Trigger: weekdays at 08:00" in act.capabilities
    assert state.check(conn, wf) == "active"


def test_edited_step_needs_review(conn):
    state.accept(conn, load())
    edited = load(EXAMPLE.replace("what needs my action", "anything"))
    assert state.check(conn, edited) == "needs_review"
    assert state.get(conn, edited.workflow_id).status == "needs_review"


def test_layout_edit_stays_active(conn):
    state.accept(conn, load())
    assert state.check(conn, load(EXAMPLE.replace("[1, 0]", "[5, 5]"))) == "active"


def test_pause_resume_remove(conn):
    wf = load()
    state.accept(conn, wf)
    state.pause(conn, wf.workflow_id)
    assert state.check(conn, wf) == "paused"
    state.resume(conn, wf.workflow_id)
    assert state.check(conn, wf) == "active"
    assert len(state.all_activations(conn)) == 1
    state.remove(conn, wf.workflow_id)
    assert state.get(conn, wf.workflow_id) is None


def test_reused_dedupe_key_returns_none(conn):
    wf = load()
    assert state.claim_run(conn, wf, source="manual", dedupe_key="k", inputs={}) is not None
    assert state.claim_run(conn, wf, source="manual", dedupe_key="k", inputs={}) is None


def test_claim_while_running_queues_and_replaces_older_queued(conn):
    wf = load()
    first = state.claim_run(conn, wf, source="manual", dedupe_key="a", inputs={})
    state.set_run(conn, first, status="running")
    second = state.claim_run(conn, wf, source="manual", dedupe_key="b", inputs={})
    assert conn.execute("SELECT status FROM runs WHERE id=?", (second,)).fetchone()[0] == "queued"
    third = state.claim_run(conn, wf, source="manual", dedupe_key="c", inputs={})
    old = conn.execute("SELECT status, reason FROM runs WHERE id=?", (second,)).fetchone()
    assert tuple(old) == ("cancelled", "replaced by a newer trigger")
    assert state.next_queued(conn)["id"] == third
    assert [r["id"] for r in state.runs_of(conn, wf.workflow_id, 10)] == [third, second, first]


def test_step_rows(conn):
    run = state.claim_run(conn, load(), source="manual", dedupe_key="a", inputs={})
    state.set_step(conn, run, "summarise", seq=0, status="running")
    state.set_step(conn, run, "summarise", status="done")
    rows = state.steps_of(conn, run)
    assert [(r["step_id"], r["status"], r["seq"]) for r in rows] == [("summarise", "done", 0)]


def test_state_file_is_private(conn, home):
    path = next(home.rglob("state.sqlite"))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
