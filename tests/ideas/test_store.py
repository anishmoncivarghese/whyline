import os
import sqlite3

import pytest

from whyline.ideas import paths, store

# Independent of store.ALLOWED so a missing edge in the implementation fails.
ALLOWED = {
    "captured": ("scoring", "brainstorm_configuring", "dropped"),
    "scoring": ("scored", "captured"),
    "scored": ("brainstorm_configuring", "dropped", "scoring"),
    "brainstorm_configuring": ("brainstorming", "captured", "scored"),
    "brainstorming": ("brainstormed", "captured", "scored"),
    "brainstormed": ("brainstorm_configuring", "setup_configuring", "dropped"),
    "dropped": ("captured",),
    "setup_configuring": ("plan_waiting", "planning", "brainstormed"),
    "plan_waiting": ("planning", "brainstormed"),
    "planning": ("plan_review", "brainstormed"),
    "plan_review": ("ready", "planning", "plan_discarded"),
    "plan_discarded": ("setup_configuring",),
    "ready": ("running", "plan_discarded"),
    "running": ("paused", "stopped", "done"),
    "paused": ("running", "stopped"),
    "stopped": ("running",),
}


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


def _events(conn, idea_id):
    return conn.execute(
        "SELECT * FROM events WHERE idea_id = ? ORDER BY id", (idea_id,)
    ).fetchall()


def test_home_uses_env_and_is_private(ideas_home):
    found = paths.home()
    assert found == ideas_home
    if os.name != "nt":
        assert (found.stat().st_mode & 0o777) == 0o700
    assert paths.db_path() == ideas_home / "ideas.sqlite3"
    assert paths.reports_dir() == ideas_home / "reports"
    assert paths.documents_dir() == ideas_home / "documents"
    assert paths.workspace() == ideas_home / "workspace"
    assert paths.workbook() == ideas_home / "ideas.xlsx"


def test_connect_creates_schema_6(conn, ideas_home):
    version = conn.execute(
        "SELECT value FROM kv WHERE key = 'schema_version'"
    ).fetchone()[0]
    assert version == "6"
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "ideas",
        "events",
        "analyses",
        "kv",
        "inbound",
        "outbox",
        "jobs",
        "requests",
        "reminders",
    } <= tables
    jobs = [row[1] for row in conn.execute("PRAGMA table_info(jobs)")]
    assert jobs == [
        "id",
        "idea_id",
        "kind",
        "state",
        "lease_until",
        "attempts",
        "error",
        "pid",
    ]
    requests = [row[1] for row in conn.execute("PRAGMA table_info(requests)")]
    assert requests == [
        "id",
        "created_at",
        "channel",
        "actor",
        "chat_id",
        "action",
        "args_json",
        "proposed_by",
        "state",
        "approval",
        "confirmed_at",
        "started_at",
        "finished_at",
        "lease_until",
        "pid",
        "result_path",
        "error",
    ]
    reminders = [row[1] for row in conn.execute("PRAGMA table_info(reminders)")]
    assert reminders == [
        "id",
        "created_at",
        "chat_id",
        "due_at",
        "text",
        "state",
        "sent_at",
        "request_id",
    ]
    if os.name != "nt":
        assert (paths.db_path().stat().st_mode & 0o777) == 0o600


def test_every_allowed_move(conn):
    for src, dests in ALLOWED.items():
        for dest in dests:
            idea = store.add(conn, f"{src}->{dest}", source="test")
            conn.execute("UPDATE ideas SET status = ? WHERE id = ?", (src, idea.id))
            moved = store.transition(
                conn, idea.id, dest, expected_revision=idea.revision, actor="test"
            )
            assert moved.status == dest
            assert moved.revision == idea.revision + 1
            events = _events(conn, idea.id)
            assert len(events) == 1
            assert events[0]["from_status"] == src
            assert events[0]["to_status"] == dest
            assert events[0]["actor"] == "test"


def test_disallowed_move_captured_to_running_raises(conn):
    idea = store.add(conn, "skip ahead", source="test")
    with pytest.raises(store.IllegalMove, match="captured to running"):
        store.transition(
            conn, idea.id, "running", expected_revision=idea.revision, actor="test"
        )
    got = store.get(conn, idea.id)
    assert got.status == "captured" and got.revision == 0
    assert _events(conn, idea.id) == []


def test_stale_revision_raises_and_writes_nothing(conn):
    idea = store.add(conn, "stale", source="test")
    with pytest.raises(store.StaleRevision, match="revision 0, not 99"):
        store.transition(conn, idea.id, "scoring", expected_revision=99, actor="test")
    got = store.get(conn, idea.id)
    assert got.status == "captured" and got.revision == 0
    assert _events(conn, idea.id) == []


def test_repeated_source_ref_returns_the_same_id(conn):
    first = store.add(
        conn, "hello", source="telegram", source_ref="chat:1"
    )
    again = store.add(
        conn, "different text", source="telegram", source_ref="chat:1"
    )
    assert again.id == first.id
    assert again.original_text == "hello"
    other = store.add(conn, "hello", source="telegram", source_ref="chat:2")
    assert other.id != first.id
    bare = store.add(conn, "cli one", source="cli")
    also = store.add(conn, "cli two", source="cli")
    assert bare.id != also.id


def test_events_are_appended_in_order(conn):
    idea = store.add(conn, "order", source="test")
    store.transition(
        conn, idea.id, "scoring", expected_revision=0, actor="a", note="start"
    )
    store.transition(
        conn, idea.id, "scored", expected_revision=1, actor="b", note="done"
    )
    store.transition(
        conn, idea.id, "dropped", expected_revision=2, actor="c"
    )
    rows = _events(conn, idea.id)
    assert [row["id"] for row in rows] == [1, 2, 3]
    assert [(row["from_status"], row["to_status"], row["actor"], row["note"]) for row in rows] == [
        ("captured", "scoring", "a", "start"),
        ("scoring", "scored", "b", "done"),
        ("scored", "dropped", "c", ""),
    ]


def test_newer_schema_version_is_refused(ideas_home):
    conn = store.connect()
    conn.execute("UPDATE kv SET value = '7' WHERE key = 'schema_version'")
    conn.close()
    with pytest.raises(store.SchemaError, match="schema version 7"):
        store.connect()


def test_schema_5_migrates_to_6_keeping_ideas_jobs_and_outbox(ideas_home):
    paths.home()
    path = paths.db_path()
    raw = sqlite3.connect(path)
    try:
        for statement in store._SCHEMA:
            raw.execute(statement)
        store._apply_schema_2(raw)
        store._apply_schema_3(raw)
        store._apply_schema_4(raw)
        store._apply_schema_5(raw)
        raw.execute(
            "INSERT INTO kv (key, value) VALUES ('schema_version', '5')"
        )
        raw.execute(
            """
            INSERT INTO ideas (
              created_at, source, original_text, title, status, revision
            ) VALUES (
              '2026-10-20T12:00:00.000Z', 'telegram', 'keep this idea',
              'keep this idea', 'captured', 0
            )
            """
        )
        raw.execute(
            """
            INSERT INTO jobs (idea_id, kind, state, attempts, error, pid)
            VALUES (1, 'score', 'queued', 2, 'later', 4242)
            """
        )
        raw.execute(
            """
            INSERT INTO outbox (chat_id, kind, text, attempts, idea_id)
            VALUES (11, 'message', 'still sending', 1, 1)
            """
        )
        raw.commit()
    finally:
        raw.close()

    conn = store.connect()
    try:
        version = conn.execute(
            "SELECT value FROM kv WHERE key = 'schema_version'"
        ).fetchone()[0]
        assert version == "6"
        idea = conn.execute("SELECT original_text, status FROM ideas").fetchone()
        assert tuple(idea) == ("keep this idea", "captured")
        job = conn.execute(
            "SELECT idea_id, kind, state, attempts, error, pid FROM jobs"
        ).fetchone()
        assert tuple(job) == (1, "score", "queued", 2, "later", 4242)
        outbox = conn.execute(
            "SELECT chat_id, kind, text, attempts, idea_id FROM outbox"
        ).fetchone()
        assert tuple(outbox) == (11, "message", "still sending", 1, 1)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"requests", "reminders"} <= tables
        assert conn.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM reminders").fetchone()[0] == 0
    finally:
        conn.close()


def test_get_list_set_paths_and_analysis_versions(conn):
    a = store.add(conn, "first line\nrest", source="cli")
    b = store.add(conn, "other", source="cli")
    assert a.title == "first line"
    assert store.get(conn, a.id).id == a.id
    assert store.get(conn, 999) is None
    store.transition(conn, b.id, "dropped", expected_revision=0, actor="t")
    assert [idea.id for idea in store.list_ideas(conn, status="dropped")] == [b.id]
    assert [idea.id for idea in store.list_ideas(conn)] == [a.id, b.id]

    updated = store.set_paths(
        conn, a.id, brainstorm_path="b.md", spec_path="s.md"
    )
    assert updated.brainstorm_path == "b.md"
    assert updated.spec_path == "s.md"
    assert updated.plan_path is None
    with pytest.raises(TypeError, match="unknown path"):
        store.set_paths(conn, a.id, report_path="nope")

    first = store.add_analysis(
        conn,
        a.id,
        agent="claude",
        report_path="1.md",
        usefulness=7,
        complexity_mvp=3,
        complexity_full=5,
        verdict="YES",
        confidence="high",
        sources_json="[]",
    )
    second = store.add_analysis(
        conn, a.id, agent="codex", report_path="2.md", usefulness=6
    )
    assert first.version == 1 and second.version == 2
    assert second.agent == "codex"
