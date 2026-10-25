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
HINT = "Enable {agent} in Settings or choose another provider."


@pytest.fixture(autouse=True)
def _isolate_global_account(monkeypatch, tmp_path):
    from whyline import account

    home = tmp_path / "whyline-account"
    home.mkdir()
    monkeypatch.setattr(account.paths, "global_whyline_dir", lambda: home)


def _set_enabled(enabled):
    from whyline import account

    account.save_global({
        name: {"enabled": name in set(enabled), "available": True}
        for name in account.AGENT_ORDER
    })


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


def _enable(conn, value="on"):
    _kv(conn, "enabled", value)


def _kv(conn, key, value):
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
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

    def poll(conn, timeout=0):
        seen["poll"] += 1
        # A live job keeps the tick polling. Stop the loop the way a
        # Telegram error would, so these tests still return.
        if seen["poll"] > 1:
            raise telegram.TelegramError("stopped")
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
        # Lease checks follow the clock, which advances during a real tick.
        # These tests pin both to NOW.
        "clock": lambda: NOW,
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
    assert first_pass["poll"] == 2 and second_pass["poll"] == 2
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
    """A live pid past its lease takes the timeout path, not the sleep one."""
    _enable(conn)
    idea = _idea(conn, "Score this")
    job = _job(conn, idea, state="running", attempts=1, lease_until=PAST, pid=77)

    def live(_pid):
        return True

    first = _run(pid_alive=live)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job["id"],)).fetchone()
    assert first["spawn"] == [job["id"]]
    assert first["stop"] == [77]
    assert (row["state"], row["attempts"]) == ("running", 2)
    assert datetime.fromisoformat(row["lease_until"]) - NOW == timedelta(minutes=45)
    assert conn.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0

    conn.execute(
        "UPDATE jobs SET lease_until = ? WHERE id = ?", (PAST, job["id"])
    )
    second = _run(pid_alive=live)

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
    start = _button(conn, "Start")
    bot.handle(conn, _press(start, "cb-start", update_id=3))
    bot.handle(conn, _press(start, "cb-again", update_id=4))

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
    assert texts.count(
        "Brainstorm started with claude, 1 pass. "
        "Usually 15-40 minutes; I'll message you when it's done."
    ) == 1
    assert store.get(conn, idea.id).status == "brainstorm_configuring"


def test_service_on_sets_enabled_and_status_says_catch_up(ideas_home, capsys, monkeypatch):
    turned = []
    monkeypatch.setattr(launchd, "supported", lambda: True)
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: None)
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
    job = _job(conn, idea, kind="unknown", state="running", attempts=1, pid=None)

    assert worker.work(job["id"]) == 1

    row = conn.execute("SELECT state, error, pid FROM jobs WHERE id = ?", (job["id"],)).fetchone()
    assert row["state"] == "failed"
    assert row["pid"] == os.getpid()
    assert "unknown job kind unknown" in row["error"]
    sent = conn.execute("SELECT chat_id, text FROM outbox").fetchone()
    assert sent["chat_id"] == CHAT
    assert sent["text"] == row["error"]
    assert not paths.workbook().exists()


def test_a_fresh_tap_keeps_the_tick_awake_for_the_next_one(conn):
    _enable(conn)
    moment = {"at": NOW}
    polls = []
    handled = []

    def clock():
        return moment["at"]

    def poll(db, timeout=0):
        polls.append(timeout)
        update_id = len(polls)
        if update_id <= 2:
            db.execute(
                """
                INSERT INTO inbound (
                  update_id, chat_id, at, kind, text, callback_data, handled
                ) VALUES (?, ?, '2026-10-20T12:00:00Z', 'callback_query', '', ?, 0)
                """,
                (update_id, CHAT, f"score:1:{update_id}"),
            )
            return 1
        moment["at"] = NOW + timedelta(minutes=10)
        return 0

    def handle(db, row):
        handled.append(row["update_id"])
        db.execute(
            "UPDATE inbound SET handled = 1 WHERE update_id = ?",
            (row["update_id"],),
        )

    worker.run_once(
        now=NOW,
        clock=clock,
        poll=poll,
        handle=handle,
        flush=lambda _db: 0,
        spawn=lambda _job_id: 1,
        pid_alive=lambda _pid: False,
        stop=lambda _pid: None,
    )

    assert handled == [1, 2]
    assert polls[0] == 0
    assert polls[1] == 25
    assert len(polls) == 3


def test_a_failing_handler_does_not_keep_the_tick_awake(conn):
    """A poison row stays unhandled and does not reset the quiet window.

    The tick that stored it still waits out ten quiet minutes, then
    releases the poll lock. The next tick is the one that tries again.
    """
    _enable(conn)
    moment = {"at": NOW}
    polls = []
    attempts = []

    def clock():
        return moment["at"]

    def poll(db, timeout=0):
        polls.append(timeout)
        if len(polls) > 3:
            raise AssertionError("poison row reset the quiet window")
        if len(polls) == 1:
            db.execute(
                """
                INSERT INTO inbound (
                  update_id, chat_id, at, kind, text, callback_data, handled
                ) VALUES (?, ?, '2026-10-20T12:00:00Z', 'callback_query', '', ?, 0)
                """,
                (1, CHAT, "score:1:1"),
            )
            return 1
        moment["at"] = NOW + timedelta(minutes=9 if len(polls) == 2 else 10)
        return 0

    def handle(_db, row):
        attempts.append(row["update_id"])
        raise RuntimeError("poison")

    worker.run_once(
        now=NOW,
        clock=clock,
        poll=poll,
        handle=handle,
        flush=lambda _db: 0,
        spawn=lambda _job_id: 1,
        pid_alive=lambda _pid: False,
        stop=lambda _pid: None,
    )

    assert attempts == [1]
    assert polls == [0, 25, 25]
    assert moment["at"] - NOW == timedelta(minutes=10)
    assert conn.execute(
        "SELECT handled FROM inbound WHERE update_id = 1"
    ).fetchone()["handled"] == 0

    later = []

    def later_poll(_db, timeout=0):
        later.append(timeout)
        return 0

    worker.run_once(
        now=moment["at"],
        clock=lambda: moment["at"],
        poll=later_poll,
        handle=handle,
        flush=lambda _db: 0,
        spawn=lambda _job_id: 1,
        pid_alive=lambda _pid: False,
        stop=lambda _pid: None,
    )

    assert later == [0]
    assert attempts == [1, 1]
    assert conn.execute(
        "SELECT handled FROM inbound WHERE update_id = 1"
    ).fetchone()["handled"] == 0


def test_a_hung_job_crosses_its_lease_while_the_tick_is_still_polling(conn):
    """A finite lease expires on the poll clock, not the tick's timestamp.

    The pid stays alive, so only the lease can reclaim the job. The tick's
    ``now`` stays before that lease. If recovery kept using it, the job
    would look live forever and this process would keep the poll lock.
    """
    _enable(conn)
    idea = _idea(conn)
    started = NOW + timedelta(minutes=20)
    job = _job(
        conn,
        idea,
        state="running",
        attempts=1,
        lease_until=started.isoformat(timespec="seconds"),
        pid=77,
    )
    moment = {"at": NOW}
    polls = []
    stopped = []
    restarted = {}

    def clock():
        return moment["at"]

    def poll(db, timeout=0):
        polls.append(timeout)
        n = len(polls)
        if n == 2:
            moment["at"] = started
        elif n == 3:
            restarted["row"] = db.execute(
                "SELECT state, attempts, lease_until, pid FROM jobs WHERE id = ?",
                (job["id"],),
            ).fetchone()
            moment["at"] = started + timedelta(minutes=45)
        elif n > 6:
            raise telegram.TelegramError("lease was not applied")
        return 0

    def stop(pid):
        stopped.append(pid)

    worker.run_once(
        now=NOW,
        clock=clock,
        poll=poll,
        handle=lambda _db, _row: None,
        flush=lambda _db: 0,
        spawn=lambda _job_id: 4242,
        pid_alive=lambda _pid: True,
        stop=stop,
    )

    assert restarted["row"]["state"] == "running"
    assert restarted["row"]["attempts"] == 2
    assert restarted["row"]["pid"] == 4242
    assert datetime.fromisoformat(restarted["row"]["lease_until"]) - started == timedelta(
        minutes=45
    )
    row = conn.execute(
        "SELECT state, error FROM jobs WHERE id = ?", (job["id"],)
    ).fetchone()
    assert row["state"] == "failed"
    assert "time limit" in row["error"]
    assert stopped == [77, 4242]
    assert polls == [25, 25, 25]
    assert conn.execute(
        "SELECT value FROM kv WHERE key = ?", (telegram_in.LAST_ERROR_KEY,)
    ).fetchone() is None


def test_two_ticks_do_not_poll_at_once(conn):
    _enable(conn)
    outer = {"n": 0}
    inner = {"n": 0}

    def poll(db, timeout=0):
        outer["n"] += 1

        def inner_poll(_db, timeout=0):
            inner["n"] += 1
            return 0

        worker.run_once(
            now=NOW,
            poll=inner_poll,
            handle=lambda _db, _row: None,
            flush=lambda _db: 0,
            spawn=lambda _job_id: 1,
            pid_alive=lambda _pid: False,
            stop=lambda _pid: None,
        )
        return 0

    worker.run_once(
        now=NOW,
        poll=poll,
        handle=lambda _db, _row: None,
        flush=lambda _db: 0,
        spawn=lambda _job_id: 1,
        pid_alive=lambda _pid: False,
        stop=lambda _pid: None,
    )

    assert outer["n"] == 1
    assert inner["n"] == 0


def test_quick_score_edits_one_status_on_fallback_and_when_it_lands(conn, monkeypatch):
    idea = _idea(conn)
    conn.execute(
        "INSERT INTO kv (key, value) VALUES ('default_agents', ?)",
        (json.dumps(["claude", "codex"]),),
    )
    monkeypatch.setattr(
        bot.capabilities, "can_run_unattended", lambda name: name in {"claude", "codex"}
    )
    bot.begin_progress(
        conn,
        CHAT,
        idea.id,
        "Quick score started with claude. Usually 2-5 minutes; I'll message you when it's done.",
    )
    seen = []

    def fake_analyse(db, idea_id, *, agents, on_fallback=None, **_kwargs):
        on_fallback(agents[0], "rate limit — slow down", agents[1])
        seen.append(db.execute("SELECT text FROM outbox ORDER BY id").fetchone()["text"])
        md = paths.reports_dir() / "landed.md"
        md.write_text("# Report\n", encoding="utf-8")
        store.add_analysis(
            db,
            idea_id,
            agent="codex",
            report_path=str(md),
            usefulness=5,
            complexity_mvp=4,
            complexity_full=6,
            verdict="YES",
            confidence="medium",
        )

    monkeypatch.setattr("whyline.ideas.analyse.analyse", fake_analyse)
    worker._execute(conn, {"kind": "score", "idea_id": idea.id})

    texts = [
        row["text"]
        for row in conn.execute("SELECT text FROM outbox ORDER BY id")
    ]
    assert seen == ["claude failed (rate limit); trying codex…"]
    assert texts[0] == "Quick score done ↓"
    assert "Usefulness: 5/9" in texts[-1]


def test_score_job_does_not_run_a_disabled_provider(conn, monkeypatch):
    _set_enabled({"codex"})
    idea = _idea(conn)
    conn.execute(
        "INSERT INTO kv (key, value) VALUES ('default_agents', ?)",
        (json.dumps(["claude"]),),
    )
    monkeypatch.setattr(
        bot.capabilities, "can_run_unattended", lambda name: True
    )
    called = []
    monkeypatch.setattr(
        "whyline.ideas.analyse.analyse",
        lambda *a, **k: called.append(True),
    )
    with pytest.raises(RuntimeError, match="Enable claude"):
        worker._execute(conn, {"kind": "score", "idea_id": idea.id})
    assert called == []


def test_brainstorm_job_refuses_a_mixed_saved_chain_before_a_subprocess(
    conn, monkeypatch,
):
    _set_enabled({"grok", "codex"})
    idea = _idea(conn)
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?)",
        (
            f"telegram_settings:{idea.id}",
            json.dumps({
                "models": ["claude", "grok"],
                "passes": 1,
                "final": "claude",
                "backup": ["codex"],
                "timeout": 15,
            }),
        ),
    )
    called = []
    monkeypatch.setattr(brainstorm, "run", lambda *a, **k: called.append(True))
    with pytest.raises(RuntimeError, match="Enable claude"):
        worker._execute(conn, {"kind": "brainstorm", "idea_id": idea.id})
    assert called == []


@pytest.mark.parametrize("kind", ["score", "brainstorm"])
def test_work_starts_caffeinate_with_the_job_pid(conn, monkeypatch, kind):
    monkeypatch.setattr(worker, "_execute", lambda _conn, _job: None)
    monkeypatch.setattr(worker, "_publish", lambda _conn: None)
    monkeypatch.setattr(worker, "_flush", lambda _conn: None)
    idea = _idea(conn)
    job = _job(conn, idea, kind=kind, state="running", attempts=1, pid=None)
    launched = []

    def popen(argv, **kwargs):
        launched.append((list(argv), kwargs))

    real_isfile = os.path.isfile

    def isfile(path):
        if path == worker._CAFFEINATE:
            return True
        return real_isfile(path)

    monkeypatch.setattr(worker.os.path, "isfile", isfile)
    monkeypatch.setattr(worker.subprocess, "Popen", popen)

    assert worker.work(job["id"]) == 0

    assert len(launched) == 1
    argv, kwargs = launched[0]
    pid = conn.execute(
        "SELECT pid FROM jobs WHERE id = ?", (job["id"],)
    ).fetchone()["pid"]
    assert pid == os.getpid()
    assert argv == ["/usr/bin/caffeinate", "-i", "-w", str(pid)]
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] is worker.subprocess.DEVNULL


def test_a_missing_caffeinate_does_not_fail_the_job(conn, monkeypatch):
    monkeypatch.setattr(worker, "_execute", lambda _conn, _job: None)
    monkeypatch.setattr(worker, "_publish", lambda _conn: None)
    monkeypatch.setattr(worker, "_flush", lambda _conn: None)
    idea = _idea(conn)
    job = _job(conn, idea, kind="score", state="running", attempts=1, pid=None)
    launched = []
    real_isfile = os.path.isfile

    def isfile(path):
        if path == worker._CAFFEINATE:
            return False
        return real_isfile(path)

    monkeypatch.setattr(worker.os.path, "isfile", isfile)
    monkeypatch.setattr(
        worker.subprocess, "Popen", lambda *_args, **_kwargs: launched.append(1)
    )

    assert worker.work(job["id"]) == 0
    assert launched == []
    assert conn.execute(
        "SELECT state FROM jobs WHERE id = ?", (job["id"],)
    ).fetchone()["state"] == "done"


def test_a_dead_pid_with_an_unexpired_lease_is_requeued_at_once(conn):
    _enable(conn)
    idea = _idea(conn)
    lease = (NOW + timedelta(minutes=30)).isoformat(timespec="seconds")
    job = _job(
        conn,
        idea,
        kind="brainstorm",
        state="running",
        attempts=1,
        pid=77,
        lease_until=lease,
    )

    seen = _run(pid_alive=lambda pid: False)

    row = conn.execute("SELECT state, attempts FROM jobs WHERE id = ?", (job["id"],)).fetchone()
    assert seen["spawn"] == [job["id"]]
    assert seen["stop"] == [77]
    assert (row["state"], row["attempts"]) == ("running", 2)
    texts = [
        item["text"]
        for item in conn.execute("SELECT text FROM outbox ORDER BY id")
    ]
    assert texts == [
        "Your brainstorm stopped when the Mac went to sleep or shut down; "
        "starting it again."
    ]


def _gap(conn, previous, allowed=(CHAT,)):
    _enable(conn)
    _kv(conn, "last_tick_at", previous.isoformat(timespec="seconds"))
    _kv(conn, telegram_in.ALLOW_KEY, json.dumps(list(allowed)))


def _tick(conn, moment, poll, handle=None):
    flushes = []

    def flush(db):
        flushes.append(
            [row["text"] for row in db.execute("SELECT text FROM outbox ORDER BY id")]
        )
        return 0

    worker.run_once(
        now=moment,
        clock=lambda: moment,
        poll=poll,
        handle=handle or (lambda _db, _row: None),
        flush=flush,
        spawn=lambda _job_id: 1,
        pid_alive=lambda _pid: True,
        stop=lambda _pid: None,
    )
    return flushes


def test_a_two_minute_gap_sends_nothing(conn):
    moment = datetime(2026, 10, 20, 15, 10, 0)
    _gap(conn, moment - timedelta(minutes=2))
    polls = {"n": 0}

    def poll(db, timeout=0):
        polls["n"] += 1
        if polls["n"] > 1:
            raise telegram.TelegramError("stop")
        db.execute(
            """
            INSERT INTO inbound (update_id, chat_id, at, kind, text, handled)
            VALUES (1, ?, '2026-10-20T15:10:00Z', 'message', 'hi', 0)
            """,
            (CHAT,),
        )
        return 1

    def handle(db, row):
        db.execute(
            """
            INSERT INTO outbox (chat_id, kind, text, attempts)
            VALUES (?, 'message', 'reply', 0)
            """,
            (row["chat_id"],),
        )
        db.execute(
            "UPDATE inbound SET handled = 1 WHERE update_id = ?",
            (row["update_id"],),
        )

    flushes = _tick(conn, moment, poll, handle)

    texts = [
        row["text"]
        for row in conn.execute("SELECT text FROM outbox ORDER BY id")
    ]
    assert texts == ["reply"]
    assert all("I was offline" not in text for batch in flushes for text in batch)


def test_an_80_minute_gap_says_so_before_any_reply(conn):
    moment = datetime(2026, 10, 20, 15, 10, 0)
    _gap(conn, datetime(2026, 10, 20, 13, 50, 0), allowed=(CHAT, 22))
    polls = {"n": 0}

    def poll(db, timeout=0):
        polls["n"] += 1
        if polls["n"] > 1:
            raise telegram.TelegramError("stop")
        for update_id in (1, 2):
            db.execute(
                """
                INSERT INTO inbound (update_id, chat_id, at, kind, text, handled)
                VALUES (?, ?, '2026-10-20T15:10:00Z', 'message', 'hi', 0)
                """,
                (update_id, CHAT),
            )
        return 2

    def handle(db, row):
        db.execute(
            """
            INSERT INTO outbox (chat_id, kind, text, attempts)
            VALUES (?, 'message', 'reply', 0)
            """,
            (row["chat_id"],),
        )
        db.execute(
            "UPDATE inbound SET handled = 1 WHERE update_id = ?",
            (row["update_id"],),
        )

    flushes = _tick(conn, moment, poll, handle)

    notice = (
        "I was offline from 13:50 to 15:10 (Mac asleep or off). "
        "Catching up on 2 messages."
    )
    assert flushes[0] == [notice, notice]
    assert "reply" not in flushes[0]
    assert flushes[-1] == [notice, notice, "reply", "reply"]


def test_a_reply_queued_before_sleep_is_delivered_after_the_offline_notice(
    conn, monkeypatch
):
    """Telegram call order, not outbox id order.

    The reply is inserted first, so it has the smaller id. The notice
    still has to leave before it.
    """
    moment = datetime(2026, 10, 20, 15, 10, 0)
    _gap(conn, datetime(2026, 10, 20, 13, 50, 0), allowed=(CHAT, 22))
    conn.execute(
        """
        INSERT INTO outbox (chat_id, kind, text, attempts)
        VALUES (?, 'message', 'queued before sleep', 0)
        """,
        (CHAT,),
    )
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: "123:secret")
    calls = []

    def http(_method, _token, fields, _files):
        calls.append((fields["chat_id"], fields["text"]))
        return {"ok": True, "result": {"message_id": len(calls)}}

    polls = {"n": 0}

    def poll(db, timeout=0):
        polls["n"] += 1
        if polls["n"] > 1:
            raise telegram.TelegramError("stop")
        db.execute(
            """
            INSERT INTO inbound (update_id, chat_id, at, kind, text, handled)
            VALUES (1, ?, '2026-10-20T15:10:00Z', 'message', 'hi', 0)
            """,
            (CHAT,),
        )
        return 1

    def handle(db, row):
        db.execute(
            """
            INSERT INTO outbox (chat_id, kind, text, attempts)
            VALUES (?, 'message', 'reply', 0)
            """,
            (row["chat_id"],),
        )
        db.execute(
            "UPDATE inbound SET handled = 1 WHERE update_id = ?",
            (row["update_id"],),
        )

    worker.run_once(
        now=moment,
        clock=lambda: moment,
        poll=poll,
        handle=handle,
        flush=lambda db: bot.flush_outbox(db, http=http),
        spawn=lambda _job_id: 1,
        pid_alive=lambda _pid: True,
        stop=lambda _pid: None,
    )

    notice = (
        "I was offline from 13:50 to 15:10 (Mac asleep or off). "
        "Catching up on 1 message."
    )
    assert calls == [
        (CHAT, notice),
        (22, notice),
        (CHAT, "queued before sleep"),
        (CHAT, "reply"),
    ]


def test_a_30_hour_gap_adds_the_day_limit(conn):
    moment = datetime(2026, 10, 20, 15, 10, 0)
    _gap(conn, moment - timedelta(hours=30))
    polls = {"n": 0}

    def poll(_db, timeout=0):
        polls["n"] += 1
        if polls["n"] > 1:
            raise telegram.TelegramError("stop")
        return 0

    flushes = _tick(conn, moment, poll)

    assert flushes[0] == [
        "I was offline from 09:10 to 15:10 (Mac asleep or off). "
        "Telegram keeps undelivered messages for about a day, "
        "so anything older may be lost; please resend it."
    ]
    assert "Catching up" not in flushes[0][0]
