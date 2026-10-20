"""The inbox rides the agents tick, one leased job at a time."""

import json
import logging
import os
from datetime import datetime, timedelta

import pytest

from whyline import cli
from whyline.agents import launchd, telegram
from whyline.ideas import bot, brainstorm, paths, store, telegram_in, worker

NOW = datetime(2026, 10, 20, 12, 0, 0)
PAST = "2026-10-20T11:00:00"
CHAT = 11


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


def _enable(conn, value="on"):
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES ('enabled', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (value,),
    )


def _idea(conn, text="Keep a ledger of ideas"):
    return store.add(conn, text, source="telegram", source_ref=f"{CHAT}:5")


def _job(conn, idea, **fields):
    data = {
        "idea_id": idea.id,
        "kind": "score",
        "state": "queued",
        "lease_until": None,
        "attempts": 0,
        "error": None,
        "pid": None,
    }
    data.update(fields)
    cursor = conn.execute(
        """
        INSERT INTO jobs (idea_id, kind, state, lease_until, attempts, error, pid)
        VALUES (:idea_id, :kind, :state, :lease_until, :attempts, :error, :pid)
        """,
        data,
    )
    return conn.execute(
        "SELECT * FROM jobs WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()


def _run(**overrides):
    seen = {"poll": 0, "handle": [], "flush": 0, "spawn": [], "stop": []}

    def poll(conn):
        seen["poll"] += 1
        return 0

    def handle(conn, row):
        seen["handle"].append(row["update_id"])

    def flush(conn):
        seen["flush"] += 1
        return 0

    def spawn(job_id):
        seen["spawn"].append(job_id)
        return 4242

    def stop(pid):
        seen["stop"].append(pid)

    kwargs = {
        "now": NOW,
        "poll": poll,
        "handle": handle,
        "flush": flush,
        "spawn": spawn,
        "stop": stop,
        "pid_alive": lambda pid: False,
    }
    kwargs.update(overrides)
    worker.run_once(**kwargs)
    return seen


def _message(text, *, update_id=1, message_id=5):
    return {
        "update_id": update_id,
        "chat_id": CHAT,
        "message_id": message_id,
        "text": text,
        "callback_data": None,
        "callback_id": None,
        "kind": "message",
        "handled": 0,
    }


def _press(data, callback_id, *, update_id=2):
    return {
        "update_id": update_id,
        "chat_id": CHAT,
        "message_id": 5,
        "text": "",
        "callback_data": data,
        "callback_id": callback_id,
        "kind": "callback_query",
        "handled": 0,
    }


def _button(conn, label):
    rows = conn.execute(
        "SELECT buttons_json FROM outbox WHERE buttons_json IS NOT NULL ORDER BY id"
    ).fetchall()
    for row in rows:
        for line in json.loads(row["buttons_json"]):
            for cell in line:
                if cell["text"] == label:
                    return cell["callback_data"]
    raise AssertionError(f"no button {label}")


def test_a_disabled_inbox_does_nothing(conn):
    idea = _idea(conn)
    _job(conn, idea)
    conn.execute(
        """
        INSERT INTO inbound (update_id, chat_id, at, kind, text, handled)
        VALUES (1, ?, '2026-10-20T00:00:00Z', 'message', 'hello', 0)
        """,
        (CHAT,),
    )
    conn.execute(
        """
        INSERT INTO outbox (chat_id, kind, text, attempts, idea_id)
        VALUES (?, 'message', 'pending', 0, ?)
        """,
        (CHAT, idea.id),
    )

    seen = _run()

    assert seen == {"poll": 0, "handle": [], "flush": 0, "spawn": [], "stop": []}
    job = conn.execute("SELECT state, attempts FROM jobs").fetchone()
    assert (job["state"], job["attempts"]) == ("queued", 0)
    inbound = conn.execute("SELECT handled, text FROM inbound").fetchone()
    assert (inbound["handled"], inbound["text"]) == (0, "hello")
    outbox = conn.execute("SELECT text, attempts, sent_at FROM outbox").fetchone()
    assert (outbox["text"], outbox["attempts"], outbox["sent_at"]) == ("pending", 0, None)

    _enable(conn, "off")
    again = _run()
    assert again["poll"] == 0 and again["spawn"] == []


def test_an_inbox_exception_does_not_stop_due_agents(tmp_path, monkeypatch, caplog):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    ideas = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(ideas))
    conn = store.connect()
    _enable(conn)
    conn.close()

    repo = tmp_path / "repo"
    path = repo / ".whyline" / "agents" / "a.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        'name="a"\ninstructions="x"\nrunner="claude"\n'
        '[trigger]\nkind="daily"\nat="07:00"\n'
    )
    from whyline.agents import definitions as d
    from whyline.agents import state
    from whyline.agents import tick

    defn = d.load(path, kind="repo", repo_root=repo)
    agents = state.connect()
    state.accept(agents, defn)
    state.update(agents, defn.agent_id, accepted_at="2026-10-01T00:00:00")

    def boom(**kwargs):
        raise RuntimeError("inbox down")

    monkeypatch.setattr(worker, "run_once", boom)
    caplog.set_level(logging.ERROR, logger="whyline.agents.tick")
    started = []
    report = tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=started.append)

    assert report.started == started
    assert len(started) == 1
    assert "idea inbox tick failed" in caplog.text
    assert "inbox down" in caplog.text


def test_a_missing_inbox_is_not_created_by_the_tick(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    ideas = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(ideas))
    repo = tmp_path / "repo"
    path = repo / ".whyline" / "agents" / "a.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        'name="a"\ninstructions="x"\nrunner="claude"\n'
        '[trigger]\nkind="daily"\nat="07:00"\n'
    )
    from whyline.agents import definitions as d
    from whyline.agents import state
    from whyline.agents import tick

    defn = d.load(path, kind="repo", repo_root=repo)
    agents = state.connect()
    state.accept(agents, defn)
    state.update(agents, defn.agent_id, accepted_at="2026-10-01T00:00:00")

    started = []
    report = tick.run_tick(now=datetime(2026, 10, 5, 7, 1), spawn=started.append)

    assert len(report.started) == 1 and started == report.started
    assert not (ideas / "ideas.sqlite3").exists()
    assert not ideas.exists()


def test_one_queued_job_is_started_once_across_two_ticks(conn):
    _enable(conn)
    idea = _idea(conn)
    first = _job(conn, idea)
    second = _job(conn, idea, kind="brainstorm")
    conn.execute(
        """
        INSERT INTO inbound (update_id, chat_id, at, kind, text, handled)
        VALUES (7, ?, '2026-10-20T00:00:00Z', 'message', 'hi', 0)
        """,
        (CHAT,),
    )
    handled = []

    def handle(db, row):
        handled.append(row["update_id"])
        db.execute(
            "UPDATE inbound SET handled = 1 WHERE update_id = ?",
            (row["update_id"],),
        )

    spawned = []

    def spawn(job_id):
        spawned.append(job_id)
        return 4242

    kwargs = {
        "now": NOW,
        "spawn": spawn,
        "handle": handle,
        "pid_alive": lambda pid: True,
        "stop": lambda pid: None,
    }
    first_pass = _run(**kwargs)
    second_pass = _run(**kwargs)

    assert spawned == [first["id"]]
    assert first_pass["poll"] == 1 and second_pass["poll"] == 1
    assert first_pass["flush"] == 1 and second_pass["flush"] == 1
    assert handled == [7]
    started = conn.execute(
        "SELECT state, attempts, pid, lease_until FROM jobs WHERE id = ?",
        (first["id"],),
    ).fetchone()
    assert (started["state"], started["attempts"], started["pid"]) == ("running", 1, 4242)
    assert datetime.fromisoformat(started["lease_until"]) - NOW == timedelta(minutes=45)
    waiting = conn.execute(
        "SELECT state FROM jobs WHERE id = ?", (second["id"],)
    ).fetchone()
    assert waiting["state"] == "queued"


def test_an_expired_lease_requeues_once_then_fails_with_a_chat_message(conn):
    _enable(conn)
    idea = _idea(conn, "Score this")
    job = _job(conn, idea, state="running", attempts=1, lease_until=PAST, pid=77)

    first = _run()

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job["id"],)).fetchone()
    assert first["spawn"] == [job["id"]]
    assert first["stop"] == [77]
    assert (row["state"], row["attempts"]) == ("running", 2)
    assert datetime.fromisoformat(row["lease_until"]) - NOW == timedelta(minutes=45)
    assert conn.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0

    conn.execute(
        "UPDATE jobs SET lease_until = ? WHERE id = ?", (PAST, job["id"])
    )
    second = _run()

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job["id"],)).fetchone()
    assert second["spawn"] == []
    assert second["stop"] == [4242]
    assert row["state"] == "failed"
    assert "tried again once" in row["error"]
    assert "time limit" in row["error"]
    sent = conn.execute("SELECT chat_id, kind, text FROM outbox").fetchone()
    assert (sent["chat_id"], sent["kind"], sent["text"]) == (CHAT, "message", row["error"])


def test_a_none_timeout_job_with_a_live_pid_is_not_requeued(conn):
    _enable(conn)
    idea = _idea(conn)
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?)",
        (
            f"telegram_settings:{idea.id}",
            json.dumps({"timeout": "none"}),
        ),
    )
    job = _job(
        conn,
        idea,
        kind="brainstorm",
        state="running",
        attempts=1,
        pid=42,
        lease_until=None,
    )

    seen = _run(pid_alive=lambda pid: pid == 42)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job["id"],)).fetchone()
    assert (row["state"], row["attempts"], row["pid"], row["lease_until"]) == (
        "running",
        1,
        42,
        None,
    )
    assert seen["spawn"] == []
    assert seen["stop"] == []


def test_a_none_timeout_job_with_a_dead_pid_is_requeued(conn):
    _enable(conn)
    idea = _idea(conn)
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?)",
        (
            f"telegram_settings:{idea.id}",
            json.dumps(
                {
                    "models": ["claude"],
                    "passes": 1,
                    "final": "claude",
                    "backup": [],
                    "timeout": "none",
                }
            ),
        ),
    )
    job = _job(
        conn,
        idea,
        kind="brainstorm",
        state="running",
        attempts=1,
        pid=42,
        lease_until=None,
    )

    seen = _run(pid_alive=lambda pid: False)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job["id"],)).fetchone()
    assert seen["spawn"] == [job["id"]]
    assert seen["stop"] == [42]
    assert (row["state"], row["attempts"], row["lease_until"], row["pid"]) == (
        "running",
        2,
        None,
        4242,
    )


def test_start_brainstorm_queues_one_job(conn, monkeypatch):
    monkeypatch.setattr(
        "whyline.agents.capabilities.can_run_unattended",
        lambda name: name == "claude",
    )

    def fail_run(*_args, **_kwargs):
        raise AssertionError("brainstorm ran inside the button handler")

    monkeypatch.setattr(brainstorm, "run", fail_run)
    conn.execute(
        "INSERT INTO kv (key, value) VALUES ('default_agents', ?)",
        (json.dumps(["claude"]),),
    )
    bot.handle(conn, _message("  A quiet ledger  \nfor receipts"))
    idea = store.list_ideas(conn)[0]
    bot.handle(conn, _press(_button(conn, "Brainstorm"), "cb-open", update_id=2))
    bot.handle(conn, _press(_button(conn, "Start brainstorm"), "cb-start", update_id=3))
    bot.handle(conn, _press(_button(conn, "Start brainstorm"), "cb-again", update_id=4))

    jobs = conn.execute("SELECT * FROM jobs").fetchall()
    assert len(jobs) == 1
    assert (jobs[0]["idea_id"], jobs[0]["kind"], jobs[0]["state"]) == (
        idea.id,
        "brainstorm",
        "queued",
    )
    stored = json.loads(
        conn.execute(
            "SELECT value FROM kv WHERE key = ?",
            (f"telegram_settings:{idea.id}",),
        ).fetchone()[0]
    )
    assert stored["timeout"] == 15
    assert stored["models"] == ["claude"]
    texts = [
        row["text"]
        for row in conn.execute("SELECT text FROM outbox ORDER BY id")
    ]
    assert texts.count("Brainstorming with claude…") == 1
    assert store.get(conn, idea.id).status == "brainstorm_configuring"


def test_service_on_sets_enabled_and_status_says_catch_up(ideas_home, capsys, monkeypatch):
    turned = []
    monkeypatch.setattr(launchd, "supported", lambda: True)
    monkeypatch.setattr(launchd, "turn_on", lambda: turned.append("on") or ideas_home / "agent.plist")
    monkeypatch.setattr(
        launchd,
        "status",
        lambda: launchd.Status(loaded=True, plist=ideas_home / "agent.plist", last_tick="2026-10-20T09:00"),
    )

    assert cli.main(["idea", "service", "status"]) == 0
    first = capsys.readouterr().out
    assert "Inbox off." in first
    assert "about 24 hours" in first
    assert "Mac was off" in first
    assert not (ideas_home / "ideas.sqlite3").exists()

    assert cli.main(["idea", "service", "on"]) == 0
    assert capsys.readouterr().out.strip() == "Inbox on."
    assert turned == ["on"]
    conn = store.connect()
    try:
        assert conn.execute(
            "SELECT value FROM kv WHERE key = 'enabled'"
        ).fetchone()[0] == "on"
    finally:
        conn.close()

    assert cli.main(["idea", "service", "status"]) == 0
    status = capsys.readouterr().out
    assert "Inbox on." in status
    assert "Scheduler loaded." in status
    assert "about 24 hours" in status
    assert "Mac was off" in status

    assert cli.main(["idea", "service", "off"]) == 0
    assert capsys.readouterr().out.strip() == "Inbox off."
    assert turned == ["on"]
    conn = store.connect()
    try:
        assert conn.execute(
            "SELECT value FROM kv WHERE key = 'enabled'"
        ).fetchone()[0] == "off"
    finally:
        conn.close()


def test_service_status_shows_a_poll_conflict_until_the_next_poll(
    ideas_home, capsys, monkeypatch
):
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: "123:secret")
    monkeypatch.setattr(launchd, "supported", lambda: True)
    monkeypatch.setattr(
        launchd,
        "status",
        lambda: launchd.Status(loaded=False, plist=None, last_tick=""),
    )
    conn = store.connect()

    def http(method, _token, _fields, _files):
        if method != "getUpdates":
            raise AssertionError(method)
        return {
            "ok": False,
            "error_code": 409,
            "description": "Conflict: 123:secret",
        }

    assert telegram_in.poll_once(conn, http=http, sleep=lambda s: None) == 0
    raw = conn.execute(
        "SELECT value FROM kv WHERE key = ?", (telegram_in.LAST_ERROR_KEY,)
    ).fetchone()["value"]
    data = json.loads(raw)
    assert "123:secret" not in raw

    assert cli.main(["idea", "service", "status"]) == 0
    status = capsys.readouterr().out
    assert data["message"] in status
    assert data["at"] in status
    assert "123:secret" not in status

    def clear(_method, _token, _fields, _files):
        return {"ok": True, "result": []}

    assert telegram_in.poll_once(conn, http=clear, sleep=lambda s: None) == 0
    assert conn.execute(
        "SELECT value FROM kv WHERE key = ?", (telegram_in.LAST_ERROR_KEY,)
    ).fetchone() is None

    assert cli.main(["idea", "service", "status"]) == 0
    cleared = capsys.readouterr().out
    assert "Last Telegram error" not in cleared
    assert data["message"] not in cleared


def test_service_on_stays_off_when_the_scheduler_cannot_start(ideas_home, capsys, monkeypatch):
    monkeypatch.setattr(launchd, "supported", lambda: True)

    def fail():
        raise RuntimeError("launchctl bootstrap failed: busy")

    monkeypatch.setattr(launchd, "turn_on", fail)
    code = cli.main(["idea", "service", "on"])
    captured = capsys.readouterr()
    assert code == 1
    assert "launchctl bootstrap failed" in captured.err
    assert not (ideas_home / "ideas.sqlite3").exists()


def test_work_fails_an_unknown_kind_and_tells_the_chat(conn, monkeypatch):
    monkeypatch.setattr("whyline.agents.telegram.token_get", lambda **_kwargs: "")
    idea = _idea(conn)
    job = _job(conn, idea, kind="plan", state="running", attempts=1, pid=None)

    assert worker.work(job["id"]) == 1

    row = conn.execute("SELECT state, error, pid FROM jobs WHERE id = ?", (job["id"],)).fetchone()
    assert row["state"] == "failed"
    assert row["pid"] == os.getpid()
    assert "unknown job kind plan" in row["error"]
    sent = conn.execute("SELECT chat_id, text FROM outbox").fetchone()
    assert sent["chat_id"] == CHAT
    assert sent["text"] == row["error"]
    assert not paths.workbook().exists()
