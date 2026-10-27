"""Tests for starting the relay on a confirmed tap: preflight, launch, and caffeinate."""

import json
import os
import subprocess
import sys
from collections import namedtuple
from datetime import datetime
from pathlib import Path

import pytest

from whyline.ideas import bot, paths, run as ideas_run, setup, store, worker

NOW = datetime(2026, 10, 20, 12, 0, 0)
CHAT = 77


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(bot.telegram, "token_get", lambda: "")
    return ""


@pytest.fixture
def fake_repo(tmp_path):
    repo_dir = tmp_path / "repo1"
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo_dir, check=True)
    wl_dir = repo_dir / ".whyline"
    wl_dir.mkdir(parents=True, exist_ok=True)
    (wl_dir / "ledger.jsonl").write_text('{"event": "init"}\n')

    relay_dir = wl_dir / "relay"
    relay_dir.mkdir(parents=True, exist_ok=True)
    config_toml = """\
timeout_minutes = 45

[roles]
implementer = "codex"
reviewer = "claude"

[backup]
chain = ["codex"]

[planner]
draft = "codex"
review = "claude"
"""
    (relay_dir / "config.toml").write_text(config_toml)

    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo_dir, check=True)
    return repo_dir


def _seed_idea(conn, text="Build receipt parser", status="plan_review", repo="repo1", fake_repo=None):
    idea = store.add(conn, text, source="telegram", source_ref=f"{CHAT}:1")
    if repo:
        store.set_repo(conn, idea.id, repo)
    if status != "captured":
        conn.execute("UPDATE ideas SET status = ? WHERE id = ?", (status, idea.id))
    bs_file = paths.home() / "brainstorms" / f"{idea.id}.md"
    bs_file.parent.mkdir(parents=True, exist_ok=True)
    bs_file.write_text("## Final Synthesis\nReceipt parser idea")
    spec_path = str(fake_repo / "spec.md") if fake_repo else None
    plan_path = str(fake_repo / "plans" / "receipt-parser.plan.md") if fake_repo else None
    if fake_repo:
        (fake_repo / "plans").mkdir(parents=True, exist_ok=True)
        Path(plan_path).write_text("# Plan Content\n")
        subprocess.run(["git", "add", "-A"], cwd=fake_repo, check=True)
        subprocess.run(["git", "commit", "-qm", "add plan"], cwd=fake_repo, check=True)
    store.set_paths(conn, idea.id, brainstorm_path=str(bs_file), spec_path=spec_path, plan_path=plan_path)
    return store.get(conn, idea.id)


def _press(data, callback_id, *, update_id=2):
    return {
        "update_id": update_id,
        "handled": 0,
        "chat_id": CHAT,
        "text": None,
        "callback_data": data,
        "reply_to_message_id": None,
        "at": "2026-10-20T10:00:00Z",
        "kind": "callback",
        "raw": json.dumps({"id": callback_id}),
    }


def _enable(conn, value="on"):
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES ('enabled', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (value,),
    )


def _run_tick(conn, *, now=NOW):
    seen = {"poll": 0, "spawn": []}

    def poll(conn, timeout=0):
        seen["poll"] += 1
        if seen["poll"] > 1:
            from whyline.agents import telegram
            raise telegram.TelegramError("stopped")
        return 0

    def handle(conn, row):
        pass

    def flush(conn):
        return 0

    def spawn(job_id):
        seen["spawn"].append(job_id)
        worker.work(job_id)
        return None

    def stop(pid):
        pass

    _enable(conn)
    worker.run_once(
        now=now,
        poll=poll,
        handle=handle,
        flush=flush,
        spawn=spawn,
        stop=stop,
        pid_alive=lambda pid: False,
    )
    return seen


def _outbox(conn, kind=None):
    if kind is None:
        return conn.execute("SELECT * FROM outbox ORDER BY id").fetchall()
    return conn.execute(
        "SELECT * FROM outbox WHERE kind = ? ORDER BY id", (kind,)
    ).fetchall()


def _mock_agents(monkeypatch):
    from whyline import account
    from whyline.console import relay_ops

    monkeypatch.setattr(relay_ops, "antigravity_state", lambda root: "trusted")
    monkeypatch.setattr(relay_ops, "usable_agents", lambda root, status: ["claude", "codex", "grok", "antigravity"])
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {
            "claude": {"logged_in": True, "installed": True, "available": True},
            "codex": {"logged_in": True, "installed": True, "available": True},
            "grok": {"logged_in": True, "installed": True, "available": True},
            "antigravity": {"logged_in": True, "installed": True, "available": True},
        },
    )


def test_stale_start_button_does_nothing(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Stale start idea", status="plan_review", fake_repo=fake_repo)

    # Tap Start on plan_review card
    bot.handle(conn, _press(f"start_plan:{idea.id}:{idea.revision}", "cb_start", update_id=10))

    messages = _outbox(conn, "message")
    assert len(messages) == 1
    # Check confirmation text and buttons
    assert "Start receipt-parser.plan.md in repo1 with" in messages[0]["text"]
    assert "timeout" in messages[0]["text"]
    buttons = json.loads(messages[0]["buttons_json"])
    assert buttons[0][0]["text"] == "Start now"
    assert buttons[0][1]["text"] == "Cancel"

    # Stale Start now button tap (revision mismatched)
    stale_press = _press(f"start_now:{idea.id}:{idea.revision + 5}", "cb_stale", update_id=11)
    bot.handle(conn, stale_press)

    # Status remains plan_review, no jobs queued
    fresh = store.get(conn, idea.id)
    assert fresh.status == "plan_review"
    jobs = conn.execute("SELECT * FROM jobs WHERE kind = 'start'").fetchall()
    assert len(jobs) == 0

    messages = _outbox(conn, "message")
    assert any(m["text"] == bot.OUT_OF_DATE for m in messages)


def test_preflight_fail_sends_lines_and_does_not_call_launcher(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Preflight fail idea", status="plan_review", fake_repo=fake_repo)

    # Tap Start, then Start now
    bot.handle(conn, _press(f"start_plan:{idea.id}:{idea.revision}", "cb_start", update_id=10))
    bot.handle(conn, _press(f"start_now:{idea.id}:{idea.revision}", "cb_now", update_id=11))

    # Moves to ready and queues start job
    idea = store.get(conn, idea.id)
    assert idea.status == "ready"
    job = conn.execute("SELECT * FROM jobs WHERE kind = 'start'").fetchone()
    assert job is not None
    assert job["state"] == "queued"

    launcher_calls = []

    def fake_resume(root, req, launcher=None, **kwargs):
        return {
            "phase": "preflight",
            "pause": {
                "reason": "FAIL  working tree dirty\nFAIL  relay lock already held\nThe Auto setup screen can open...",
            },
        }

    monkeypatch.setattr(ideas_run.auto_run, "resume", fake_resume)

    _run_tick(conn)

    # Launcher was NOT called
    assert launcher_calls == []

    # Idea did NOT move to running
    idea = store.get(conn, idea.id)
    assert idea.status == "ready"

    # FAIL lines were sent to chat with Retry / Cancel
    messages = [m for m in _outbox(conn, "message") if m["text"] != bot._MOVED]
    assert len(messages) == 1
    assert "FAIL  working tree dirty\nFAIL  relay lock already held" in messages[0]["text"]
    assert "The Auto setup screen" not in messages[0]["text"]

    buttons = json.loads(messages[0]["buttons_json"])
    assert buttons[0][0]["text"] == "Retry"
    assert buttons[0][1]["text"] == "Cancel"


def test_pass_calls_launcher_once_with_start_in_target_repo_and_moves_to_running(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Preflight pass idea", status="plan_review", fake_repo=fake_repo)

    bot.handle(conn, _press(f"start_plan:{idea.id}:{idea.revision}", "cb_start", update_id=10))
    bot.handle(conn, _press(f"start_now:{idea.id}:{idea.revision}", "cb_now", update_id=11))

    spawned = []

    class DummyProc:
        pid = 7711

    real_popen = subprocess.Popen

    def fake_popen(cmd, **kwargs):
        if list(cmd)[:1] == ["git"]:
            return real_popen(cmd, **kwargs)
        spawned.append({"cmd": list(cmd), "kwargs": kwargs})
        return DummyProc()

    monkeypatch.setattr(ideas_run.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ideas_run.os.path, "isfile", lambda p: True if p == ideas_run._CAFFEINATE else os.path.exists(p))

    def fake_resume(root, req, launcher=None, **kwargs):
        assert launcher is not None
        launcher(["start"])
        return {"phase": "relay"}

    monkeypatch.setattr(ideas_run.auto_run, "resume", fake_resume)

    _run_tick(conn)

    # Launcher called once with ["start"] in target repo
    relay_spawns = [s for s in spawned if "whyline" in s["cmd"]]
    assert len(relay_spawns) == 1
    assert relay_spawns[0]["cmd"][-1] == "start"
    assert relay_spawns[0]["kwargs"]["cwd"] == str(fake_repo)
    assert relay_spawns[0]["kwargs"]["start_new_session"] is True

    # PID recorded on the job
    job = conn.execute("SELECT * FROM jobs WHERE kind = 'start'").fetchone()
    assert job["pid"] == 7711

    # Idea moves to running
    idea = store.get(conn, idea.id)
    assert idea.status == "running"

    # Chat gets "Started. Ask /status any time."
    messages = [m for m in _outbox(conn, "message") if "Started. Ask /status any time." in m["text"]]
    assert len(messages) == 1


def test_relay_live_in_between_waits_instead_of_starting(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Relay live idea", status="plan_review", fake_repo=fake_repo)

    bot.handle(conn, _press(f"start_plan:{idea.id}:{idea.revision}", "cb_start", update_id=10))
    bot.handle(conn, _press(f"start_now:{idea.id}:{idea.revision}", "cb_now", update_id=11))

    RelayMock = namedtuple("RelayMock", ["task", "agent"])
    import whyline_relay.running
    monkeypatch.setattr(
        whyline_relay.running,
        "live",
        lambda root: RelayMock("TASK-1", "codex") if str(root) == str(fake_repo) else None,
    )

    launcher_called = []

    def fake_resume(root, req, launcher=None, **kwargs):
        launcher_called.append(True)
        return {"phase": "relay"}

    monkeypatch.setattr(ideas_run.auto_run, "resume", fake_resume)

    # Tick runs while relay is live
    _run_tick(conn)

    # Does NOT start
    assert launcher_called == []
    idea = store.get(conn, idea.id)
    assert idea.status == "ready"
    job = conn.execute("SELECT * FROM jobs WHERE kind = 'start'").fetchone()
    assert job["state"] == "queued"

    # Now relay finishes (not live anymore)
    monkeypatch.setattr(whyline_relay.running, "live", lambda root: None)

    class DummyProc:
        pid = 9988

    real_popen = subprocess.Popen

    def fake_popen2(cmd, **kwargs):
        if list(cmd)[:1] == ["git"]:
            return real_popen(cmd, **kwargs)
        return DummyProc()

    monkeypatch.setattr(ideas_run.subprocess, "Popen", fake_popen2)

    # Tick runs again
    _run_tick(conn)

    # Now it launched
    assert launcher_called == [True]
    idea = store.get(conn, idea.id)
    assert idea.status == "running"


def test_caffeinate_started_with_relay_pid_and_absence_is_not_error(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)

    # Case 1: caffeinate exists
    caffeinate_calls = []

    def fake_popen(cmd, **kwargs):
        if cmd[0] == ideas_run._CAFFEINATE:
            caffeinate_calls.append((list(cmd), kwargs))
        return namedtuple("Proc", ["pid"])(5544)

    monkeypatch.setattr(ideas_run.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ideas_run.os.path, "isfile", lambda p: True if p == ideas_run._CAFFEINATE else os.path.exists(p))

    launcher = ideas_run.make_launcher(fake_repo, conn, 1, spawn_fn=lambda r, argv: 5544)
    pid = launcher(["start"])
    assert pid == 5544
    assert len(caffeinate_calls) == 1
    assert caffeinate_calls[0][0] == ["/usr/bin/caffeinate", "-i", "-w", "5544"]
    assert caffeinate_calls[0][1]["start_new_session"] is True

    # Case 2: caffeinate is absent (not an error)
    monkeypatch.setattr(ideas_run.os.path, "isfile", lambda p: False if p == ideas_run._CAFFEINATE else os.path.exists(p))
    monkeypatch.setattr(ideas_run.shutil, "which", lambda cmd: None)

    launcher_no_caff = ideas_run.make_launcher(fake_repo, conn, 1, spawn_fn=lambda r, argv: 6655)
    pid_no_caff = launcher_no_caff(["start"])
    assert pid_no_caff == 6655

    # Case 3: caffeinate raises OSError (not an error)
    monkeypatch.setattr(ideas_run.os.path, "isfile", lambda p: True if p == ideas_run._CAFFEINATE else os.path.exists(p))

    def popen_raising(cmd, **kwargs):
        if cmd[0] == ideas_run._CAFFEINATE:
            raise OSError("caffeinate failed to start")
        return namedtuple("Proc", ["pid"])(7766)

    monkeypatch.setattr(ideas_run.subprocess, "Popen", popen_raising)
    launcher_err = ideas_run.make_launcher(fake_repo, conn, 1, spawn_fn=lambda r, argv: 7766)
    pid_err = launcher_err(["start"])
    assert pid_err == 7766


def test_retry_on_preflight_fail_requeues_start_job(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Retry fail idea", status="plan_review", fake_repo=fake_repo)

    bot.handle(conn, _press(f"start_plan:{idea.id}:{idea.revision}", "cb_start", update_id=10))
    bot.handle(conn, _press(f"start_now:{idea.id}:{idea.revision}", "cb_now", update_id=11))

    def fake_resume(root, req, launcher=None, **kwargs):
        return {
            "phase": "preflight",
            "pause": {"reason": "FAIL  uncommitted files"},
        }

    monkeypatch.setattr(ideas_run.auto_run, "resume", fake_resume)
    _run_tick(conn)

    idea = store.get(conn, idea.id)
    assert idea.status == "ready"

    # User taps Retry
    bot.handle(conn, _press(f"retry_start:{idea.id}:{idea.revision}", "cb_retry", update_id=12))

    # A new start job is queued
    queued_jobs = conn.execute("SELECT * FROM jobs WHERE kind = 'start' AND state = 'queued'").fetchall()
    assert len(queued_jobs) == 1

    messages = [m for m in _outbox(conn, "message") if m["text"] == "Retrying…"]
    assert len(messages) == 1


def test_cancel_on_start_confirm_returns_to_plan_review(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Cancel start idea", status="plan_review", fake_repo=fake_repo)

    bot.handle(conn, _press(f"start_plan:{idea.id}:{idea.revision}", "cb_start", update_id=10))
    bot.handle(conn, _press(f"cancel:{idea.id}:{idea.revision}", "cb_cancel", update_id=11))

    idea = store.get(conn, idea.id)
    assert idea.status == "plan_review"
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'start'").fetchone()[0] == 0

    messages = [m for m in _outbox(conn, "message") if m["text"] == "Cancelled."]
    assert len(messages) == 1


def test_start_confirmation_preserves_explicit_timeout_none(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Explicit timeout none idea", status="plan_review", fake_repo=fake_repo)

    setup._kv_set(conn, f"telegram_settings:{idea.id}", json.dumps({"timeout": "none"}))

    bot.handle(conn, _press(f"start_plan:{idea.id}:{idea.revision}", "cb_start", update_id=30))

    messages = _outbox(conn, "message")
    assert len(messages) == 1
    assert "timeout none?" in messages[0]["text"]
    assert "timeout 45?" not in messages[0]["text"]

    bot.handle(conn, _press(f"start_now:{idea.id}:{idea.revision}", "cb_now", update_id=31))

    observed_reqs = []

    def fake_resume(root, req, launcher=None, **kwargs):
        observed_reqs.append(req)
        launcher(["start"])
        return {"phase": "relay"}

    monkeypatch.setattr(ideas_run.auto_run, "resume", fake_resume)

    class DummyProc:
        pid = 1234

    real_popen = subprocess.Popen
    monkeypatch.setattr(
        ideas_run.subprocess,
        "Popen",
        lambda cmd, **kw: real_popen(cmd, **kw) if list(cmd)[:1] == ["git"] else DummyProc(),
    )
    monkeypatch.setattr(ideas_run.os.path, "isfile", lambda p: False)
    monkeypatch.setattr(ideas_run.shutil, "which", lambda cmd: None)

    _run_tick(conn)

    assert len(observed_reqs) == 1
    assert observed_reqs[0].timeout_minutes == 0
    job = conn.execute("SELECT * FROM jobs WHERE kind = 'start'").fetchone()
    assert job["state"] == "done"
    assert job["pid"] == 1234


def test_start_confirmation_preserves_explicit_timeout_zero(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Explicit timeout zero idea", status="plan_review", fake_repo=fake_repo)

    setup._kv_set(conn, f"telegram_settings:{idea.id}", json.dumps({"timeout": 0}))

    bot.handle(conn, _press(f"start_plan:{idea.id}:{idea.revision}", "cb_start", update_id=40))

    messages = _outbox(conn, "message")
    assert len(messages) == 1
    assert "timeout none?" in messages[0]["text"]
    assert "timeout 45?" not in messages[0]["text"]


@pytest.mark.parametrize("kind", ["score", "brainstorm", "plan"])
def test_worker_completion_retains_pid_ownership_protection(conn, monkeypatch, kind):
    monkeypatch.setattr(worker, "_keep_awake", lambda _pid: None)
    monkeypatch.setattr(worker, "_publish", lambda _conn: None)
    monkeypatch.setattr(worker, "_flush", lambda _conn: None)

    idea = store.add(conn, f"Test {kind}", source="telegram", source_ref=f"{CHAT}:1")
    conn.execute(
        """
        INSERT INTO jobs (idea_id, kind, state, attempts, pid)
        VALUES (?, ?, 'running', 1, NULL)
        """,
        (idea.id, kind),
    )
    job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def fake_execute(c, j):
        conn.execute("UPDATE jobs SET pid = ? WHERE id = ?", (os.getpid() + 9999, job_id))

    monkeypatch.setattr(worker, "_execute", fake_execute)

    result = worker.work(job_id)
    assert result == 0

    row = conn.execute("SELECT state, pid FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["state"] == "running"
    assert row["pid"] == os.getpid() + 9999


@pytest.mark.parametrize("kind", ["score", "brainstorm", "plan"])
def test_worker_completion_marks_done_when_pid_matches(conn, monkeypatch, kind):
    monkeypatch.setattr(worker, "_keep_awake", lambda _pid: None)
    monkeypatch.setattr(worker, "_publish", lambda _conn: None)
    monkeypatch.setattr(worker, "_flush", lambda _conn: None)

    idea = store.add(conn, f"Test {kind}", source="telegram", source_ref=f"{CHAT}:1")
    conn.execute(
        """
        INSERT INTO jobs (idea_id, kind, state, attempts, pid)
        VALUES (?, ?, 'running', 1, NULL)
        """,
        (idea.id, kind),
    )
    job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    monkeypatch.setattr(worker, "_execute", lambda c, j: None)

    result = worker.work(job_id)
    assert result == 0

    row = conn.execute("SELECT state, pid FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["state"] == "done"
    assert row["pid"] == os.getpid()


def test_start_job_completion_retains_detached_relay_pid(conn, monkeypatch, fake_repo):
    monkeypatch.setattr(worker, "_keep_awake", lambda _pid: None)
    monkeypatch.setattr(worker, "_publish", lambda _conn: None)
    monkeypatch.setattr(worker, "_flush", lambda _conn: None)

    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Start job pid test", status="ready", fake_repo=fake_repo)

    conn.execute(
        """
        INSERT INTO jobs (idea_id, kind, state, attempts, pid)
        VALUES (?, 'start', 'running', 1, NULL)
        """,
        (idea.id,),
    )
    job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    relay_pid = 65432

    def fake_resume(root, req, launcher=None, **kwargs):
        assert launcher is not None
        launcher(["start"])
        return {"phase": "relay"}

    monkeypatch.setattr(ideas_run.auto_run, "resume", fake_resume)

    class DummyProc:
        pid = relay_pid

    real_popen = subprocess.Popen
    monkeypatch.setattr(
        ideas_run.subprocess,
        "Popen",
        lambda cmd, **kw: real_popen(cmd, **kw) if list(cmd)[:1] == ["git"] else DummyProc(),
    )
    monkeypatch.setattr(ideas_run.os.path, "isfile", lambda p: False)
    monkeypatch.setattr(ideas_run.shutil, "which", lambda cmd: None)

    result = worker.work(job_id)
    assert result == 0

    row = conn.execute("SELECT state, pid FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["state"] == "done"
    assert row["pid"] == relay_pid


def test_start_task_passes_only_task_id_and_caffeinates(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)

    spawned = []
    caffeinated = []

    def fake_spawn(root, argv):
        spawned.append({"root": root, "argv": list(argv)})
        return 8899

    def fake_caff(pid):
        caffeinated.append(pid)

    from whyline_relay import preflight

    monkeypatch.setattr(preflight, "run", lambda *args, **kwargs: [])

    res = ideas_run.start_task(
        conn,
        "repo1",
        "TASK-1",
        plan="plans/active.plan.md",
        branch="custom/paused-run",
        spawn_fn=fake_spawn,
        caffeinate_fn=fake_caff,
    )

    assert res.ok is True
    assert len(spawned) == 1
    assert spawned[0]["argv"] == [
        "start",
        "--plan",
        "plans/active.plan.md",
        "--branch",
        "custom/paused-run",
        "--only",
        "TASK-1",
    ]
    assert str(spawned[0]["root"]) == str(fake_repo)
    assert caffeinated == [8899]


def test_start_task_ignores_existing_auto_checkpoint(
    conn, token, fake_repo, monkeypatch
):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)

    checkpoint = ideas_run.auto_run.checkpoint_path(fake_repo)
    checkpoint.write_text('{"schema": 1, "phase": "relay", "name": "OTHER-9"}\n')
    (fake_repo / ".git" / "info" / "exclude").write_text(
        ".whyline/relay/auto-run.json\n"
    )

    from whyline_relay import preflight

    preflight_calls = []

    def fake_preflight(root, plan, *, scope):
        preflight_calls.append((root, plan, scope))
        return []

    monkeypatch.setattr(preflight, "run", fake_preflight)
    monkeypatch.setattr(
        ideas_run.auto_run,
        "resume",
        lambda *args, **kwargs: pytest.fail("start_task resumed an Auto checkpoint"),
    )

    spawned = []
    res = ideas_run.start_task(
        conn,
        "repo1",
        "TASK-1",
        spawn_fn=lambda root, argv: spawned.append((root, list(argv))) or 9901,
        caffeinate_fn=lambda _pid: None,
    )

    assert res.ok is True
    assert [(root, scope) for root, _plan, scope in preflight_calls] == [
        (fake_repo, "full")
    ]
    assert spawned == [(fake_repo, ["start", "--only", "TASK-1"])]


def test_start_task_refuses_when_repo_dirty(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)

    (fake_repo / "untracked_file.txt").write_text("changes")

    spawned = []
    res = ideas_run.start_task(
        conn,
        "repo1",
        "TASK-1",
        spawn_fn=lambda r, argv: spawned.append(argv) or 123,
    )

    assert res.ok is False
    assert "untracked_file.txt" in res.reason
    assert spawned == []


def test_start_task_refuses_when_relay_live(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)

    RelayMock = namedtuple("RelayMock", ["pid", "task", "agent"])
    import whyline_relay.running
    monkeypatch.setattr(
        whyline_relay.running,
        "live",
        lambda root: RelayMock(4321, "TASK-1", "codex") if str(root) == str(fake_repo) else None,
    )

    spawned = []
    res = ideas_run.start_task(
        conn,
        "repo1",
        "TASK-1",
        spawn_fn=lambda r, argv: spawned.append(argv) or 123,
    )

    assert res.ok is False
    assert "Waiting: a relay is running in repo1" in res.reason
    assert spawned == []


def test_start_task_refuses_when_preflight_raises(
    conn, token, fake_repo, monkeypatch
):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)

    from whyline_relay import preflight

    monkeypatch.setattr(
        preflight,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("check crashed")),
    )
    spawned = []

    res = ideas_run.start_task(
        conn,
        "repo1",
        "TASK-1",
        spawn_fn=lambda r, argv: spawned.append(argv) or 123,
    )

    assert res.ok is False
    assert res.reason == "Preflight failed: check crashed"
    assert spawned == []
