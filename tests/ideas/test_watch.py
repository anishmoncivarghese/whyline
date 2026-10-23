"""Tests for watch.py: Status, pause alerts with Resolve buttons, Stop, and Done."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from whyline.console import recovery
from whyline.ideas import bot, paths, run as ideas_run, setup, store, watch, worker

NOW = datetime(2026, 10, 20, 12, 0, 0)
CHAT = 88


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
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=repo_dir, check=True
    )
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


def _seed_idea(
    conn,
    text="Build receipt parser",
    status="running",
    repo="repo1",
    fake_repo=None,
    plan_content="# Plan\n- [ ] TASK-1: first task\n",
):
    idea = store.add(conn, text, source="telegram", source_ref=f"{CHAT}:1")
    if repo:
        store.set_repo(conn, idea.id, repo)
    if status != "captured":
        conn.execute("UPDATE ideas SET status = ? WHERE id = ?", (status, idea.id))
        conn.execute(
            """
            INSERT INTO events (idea_id, at, from_status, to_status, actor, note)
            VALUES (?, ?, 'captured', ?, 'test', 'seed')
            """,
            (idea.id, "2026-10-20T11:00:00Z", status),
        )
    bs_file = paths.home() / "brainstorms" / f"{idea.id}.md"
    bs_file.parent.mkdir(parents=True, exist_ok=True)
    bs_file.write_text("## Final Synthesis\nReceipt parser idea")
    spec_path = str(fake_repo / "spec.md") if fake_repo else None
    plan_path = (
        str(fake_repo / "plans" / "receipt-parser.plan.md") if fake_repo else None
    )
    if fake_repo and plan_path:
        (fake_repo / "plans").mkdir(parents=True, exist_ok=True)
        Path(plan_path).write_text(plan_content)
        subprocess.run(["git", "add", "-A"], cwd=fake_repo, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "add plan"], cwd=fake_repo, check=True
        )
    store.set_paths(
        conn,
        idea.id,
        brainstorm_path=str(bs_file),
        spec_path=spec_path,
        plan_path=plan_path,
    )
    return store.get(conn, idea.id)


def _set_relay_state(repo: Path, **kwargs):
    state_dir = repo / ".whyline" / "relay"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "state.json"
    default_state = {
        "plan": "plans/receipt-parser.plan.md",
        "branch": "relay/receipt-parser.plan",
        "task_id": "TASK-1",
        "round": 1,
        "base_commit": "HEAD~1",
        "paused_reason": "",
        "log_path": "",
        "stage": "draft",
        "profile": "",
        "stage_visits": {},
        "timeout_minutes": 15,
    }
    default_state.update(kwargs)
    state_file.write_text(json.dumps(default_state))
    return default_state


def _press(data, callback_id="cb-1", *, update_id=2):
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


def _outbox(conn, kind=None):
    if kind is None:
        return conn.execute("SELECT * FROM outbox ORDER BY id").fetchall()
    return conn.execute(
        "SELECT * FROM outbox WHERE kind = ? ORDER BY id", (kind,)
    ).fetchall()


# 1. Tests with fake relay state: a new pause sends one alert with the diagnosed
# options in order and a repeated tick sends nothing new
def test_new_pause_sends_one_alert_with_diagnosed_options_in_order_and_repeated_tick_sends_nothing(
    conn, fake_repo, token
):
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, fake_repo=fake_repo, status="running")
    log_file = fake_repo / ".whyline" / "relay" / "logs" / "TASK-1-1-codex.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("sample log output\n")

    _set_relay_state(
        fake_repo,
        task_id="TASK-1",
        paused_reason="Turn exceeded 900s and was terminated",
        log_path=str(log_file),
    )

    # First tick: alert should be sent
    acted = watch.tick(conn)
    assert acted == [idea.id]

    fresh = store.get(conn, idea.id)
    assert fresh.status == "paused"

    outbox = _outbox(conn, "message")
    assert len(outbox) == 1
    alert = outbox[0]
    assert "Turn exceeded 900s and was terminated" in alert["text"]
    assert "TASK-1" in alert["text"]
    assert str(log_file) in alert["text"]

    buttons = json.loads(alert["buttons_json"])
    # First option should be recommended (resume-longer) and marked with ★
    first_row = buttons[0]
    first_btn = first_row[0]
    assert "★" in first_btn["text"]
    assert "resume-longer" in first_btn["callback_data"]

    # All buttons flat list
    flat_buttons = [btn for row in buttons for btn in row]
    evidence_btn = flat_buttons[-1]
    assert evidence_btn["text"] == "Show evidence"
    assert "evidence" in evidence_btn["callback_data"]

    # Repeated tick: sends nothing new
    acted2 = watch.tick(conn)
    assert acted2 == []
    assert len(_outbox(conn, "message")) == 1


# 2. tapping resume-longer calls recovery.apply with that id and moves to running
def test_tapping_resume_longer_calls_recovery_apply_and_moves_to_running(
    conn, fake_repo, monkeypatch, token
):
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, fake_repo=fake_repo, status="paused")
    log_file = fake_repo / ".whyline" / "relay" / "logs" / "TASK-1-1-codex.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("sample log\n")

    _set_relay_state(
        fake_repo,
        task_id="TASK-1",
        paused_reason="Turn exceeded 900s and was terminated",
        log_path=str(log_file),
    )

    applied_calls = []
    original_apply = recovery.apply

    def fake_apply(root, problem, option_id, launch=None):
        applied_calls.append((root, problem, option_id))
        return "Resumed relay."

    monkeypatch.setattr(recovery, "apply", fake_apply)

    # Tap resume-longer
    press = _press(
        f"resolve_resume-longer:{idea.id}:{idea.revision}", "cb_resume_longer"
    )
    bot.handle(conn, press)

    assert len(applied_calls) == 1
    root_arg, prob_arg, opt_id_arg = applied_calls[0]
    assert opt_id_arg == "resume-longer"
    assert root_arg == fake_repo.resolve()

    fresh = store.get(conn, idea.id)
    assert fresh.status == "running"

    messages = _outbox(conn, "message")
    resumed_msg = next(m for m in messages if "Resumed relay." in m["text"])
    assert "Status" in resumed_msg["buttons_json"]
    assert "Stop" in resumed_msg["buttons_json"]


# 3. a confirm=True option needs a second tap
def test_confirm_true_option_needs_second_tap(conn, fake_repo, monkeypatch, token):
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, fake_repo=fake_repo, status="paused")

    _set_relay_state(
        fake_repo,
        task_id="TASK-1",
        paused_reason="Some pause reason",
    )

    def fake_diagnose(root, fail_lines=None, pause_reason=""):
        return [
            recovery.Problem(
                id="prob-1",
                summary="Problem with confirm option",
                evidence=["Some evidence"],
                options=[
                    recovery.Option(
                        "stash",
                        "Stash changes",
                        "stash details",
                        recommended=False,
                        confirm=True,
                    ),
                    recovery.Option(
                        "resume",
                        "Resume",
                        "resume details",
                        recommended=True,
                        confirm=False,
                    ),
                ],
            )
        ]

    monkeypatch.setattr(recovery, "diagnose", fake_diagnose)

    applied_calls = []

    def fake_apply(root, problem, option_id, launch=None):
        applied_calls.append(option_id)
        return "Stashed changes."

    monkeypatch.setattr(recovery, "apply", fake_apply)

    # First tap on stash (which has confirm=True)
    press = _press(f"resolve_stash:{idea.id}:{idea.revision}", "cb_stash_1")
    bot.handle(conn, press)

    # First tap: apply not yet called, asks again before acting
    assert len(applied_calls) == 0
    fresh = store.get(conn, idea.id)
    assert fresh.status == "paused"

    confirm_msg = _outbox(conn, "message")[-1]
    assert "Confirm" in confirm_msg["text"]
    buttons = json.loads(confirm_msg["buttons_json"])
    assert any(
        "confirm_resolve_stash" in btn["callback_data"]
        for row in buttons
        for btn in row
    )

    # Second tap: confirmed tap
    second_press = _press(
        f"confirm_resolve_stash:{fresh.id}:{fresh.revision}",
        "cb_stash_2",
        update_id=3,
    )
    bot.handle(conn, second_press)

    # Second tap calls apply
    assert applied_calls == ["stash"]


# 4. a release pause offers no publish option
def test_release_pause_offers_no_publish_option(conn, fake_repo, monkeypatch, token):
    setup.add_repo(conn, "repo1", fake_repo)
    plan_text = """\
# Plan
- [ ] REL-1: Publish whyline
  relay-profile: release
"""
    idea = _seed_idea(
        conn, fake_repo=fake_repo, status="running", plan_content=plan_text
    )

    _set_relay_state(
        fake_repo,
        task_id="REL-1",
        paused_reason="release task for you: REL-1",
        profile="release",
    )

    # Return problems including a publish option to test exclusion
    def fake_diagnose(root, fail_lines=None, pause_reason=""):
        return [
            recovery.Problem(
                id="release",
                summary="Release pause",
                evidence=["Release evidence"],
                options=[
                    recovery.Option(
                        "publish",
                        "Publish release",
                        "publish now",
                        recommended=True,
                        confirm=False,
                    ),
                    recovery.Option(
                        "wait",
                        "Wait",
                        "wait for console",
                        recommended=False,
                        confirm=False,
                    ),
                ],
            )
        ]

    monkeypatch.setattr(recovery, "diagnose", fake_diagnose)

    watch.tick(conn)

    fresh = store.get(conn, idea.id)
    assert fresh.status == "paused"

    outbox = _outbox(conn, "message")
    assert len(outbox) == 1
    alert = outbox[0]
    # Alert text says Release is yours
    assert "Release is yours: run it from the console" in alert["text"]
    assert "REL-1" in alert["text"]

    buttons = json.loads(alert["buttons_json"])
    flat_buttons = [btn for row in buttons for btn in row]
    # No button offers publish
    for btn in flat_buttons:
        assert "publish" not in btn["text"].lower()
        assert "publish" not in btn["callback_data"].lower()
    # But wait / Show evidence are offered
    assert any("wait" in btn["callback_data"] for btn in flat_buttons)
    assert any("evidence" in btn["callback_data"] for btn in flat_buttons)


# 5. Stop runs the stop command and moves to stopped
def test_stop_runs_stop_command_and_moves_to_stopped(
    conn, fake_repo, monkeypatch, token
):
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, fake_repo=fake_repo, status="running")

    stop_calls = []

    def fake_stop_relay(root, *, runner=None):
        stop_calls.append(root)

    monkeypatch.setattr(watch, "stop_relay", fake_stop_relay)

    # 1. Tap Stop button or send /stop
    press_stop = _press(f"stop:{idea.id}:{idea.revision}", "cb_stop_1", update_id=10)
    bot.handle(conn, press_stop)

    # Asks to confirm
    fresh = store.get(conn, idea.id)
    assert fresh.status == "running"
    confirm_msg = _outbox(conn, "message")[-1]
    assert "Stop" in confirm_msg["text"]
    buttons = json.loads(confirm_msg["buttons_json"])
    flat_btns = [b for row in buttons for b in row]
    assert any("stop_yes" in b["callback_data"] for b in flat_btns)

    # 2. Tap Stop now (confirm stop)
    press_confirm = _press(
        f"stop_yes:{fresh.id}:{fresh.revision}", "cb_stop_2", update_id=11
    )
    bot.handle(conn, press_confirm)

    assert len(stop_calls) == 1
    fresh = store.get(conn, idea.id)
    assert fresh.status == "stopped"

    stopped_msg = _outbox(conn, "message")[-1]
    assert "Stopped" in stopped_msg["text"]
    stopped_buttons = json.loads(stopped_msg["buttons_json"])
    flat_stopped = [b for row in stopped_buttons for b in row]
    assert any("resume" in b["callback_data"] for b in flat_stopped)

    # 3. Resume from stopped
    resume_calls = []

    def fake_resume_relay(root, idea_id, conn, **kwargs):
        resume_calls.append((root, idea_id))
        return "Resumed relay."

    monkeypatch.setattr(watch, "resume_relay", fake_resume_relay)

    press_resume = _press(
        f"resume:{fresh.id}:{fresh.revision}", "cb_resume", update_id=12
    )
    bot.handle(conn, press_resume)

    assert len(resume_calls) == 1
    fresh = store.get(conn, idea.id)
    assert fresh.status == "running"


# 6. status output redacts a token in the log
def test_status_output_redacts_token_in_log(conn, fake_repo, monkeypatch):
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, fake_repo=fake_repo, status="running")

    secret_token = "secret-token-abc-987"
    monkeypatch.setattr(bot.telegram, "token_get", lambda: secret_token)

    log_file = fake_repo / ".whyline" / "relay" / "logs" / "TASK-1-1-codex.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(
        f"""Line 1: starting turn
Line 2: auth token={secret_token} is active
Line 3: processing task
Line 4: finished round
Line 5: done
"""
    )

    _set_relay_state(
        fake_repo,
        task_id="TASK-1",
        stage="draft",
        round=2,
        log_path=str(log_file),
    )

    # Request status
    status_text, buttons = watch.build_status(
        conn, idea, token=secret_token
    )

    assert secret_token not in status_text
    assert "•••" in status_text
    assert "Plan: receipt-parser.plan.md" in status_text
    assert "Tasks: 0 of 1" in status_text
    assert "TASK-1" in status_text
    assert "Round: 2" in status_text

    button_labels = [label for label, _action in buttons]
    assert button_labels == ["Stop", "Refresh"]

    # Also test via /status command in bot
    bot.handle(
        conn,
        {
            "update_id": 20,
            "handled": 0,
            "chat_id": CHAT,
            "text": "/status",
            "callback_data": None,
            "reply_to_message_id": None,
            "at": "2026-10-20T10:00:00Z",
            "kind": "message",
            "raw": "{}",
        },
    )

    messages = _outbox(conn, "message")
    last_msg = messages[-1]
    assert secret_token not in last_msg["text"]
    assert "•••" in last_msg["text"]
    assert "Stop" in last_msg["buttons_json"]
    assert "Refresh" in last_msg["buttons_json"]


# 7. all boxes ticked moves to done once
def test_all_boxes_ticked_moves_to_done_once(conn, fake_repo, monkeypatch, token):
    setup.add_repo(conn, "repo1", fake_repo)
    plan_text = """\
# Plan
- [x] TASK-1: First completed task
- [x] TASK-2: Second completed task
"""
    idea = _seed_idea(
        conn, fake_repo=fake_repo, status="running", plan_content=plan_text
    )

    # Commit a change so commits since start can be counted
    test_file = fake_repo / "test.txt"
    test_file.write_text("commit 1")
    subprocess.run(["git", "add", "test.txt"], cwd=fake_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "commit 1"], cwd=fake_repo, check=True)

    _set_relay_state(fake_repo, base_commit="HEAD~1")

    # Tick: all boxes ticked and no relay is live -> move to done
    acted = watch.tick(conn)
    assert acted == [idea.id]

    fresh = store.get(conn, idea.id)
    assert fresh.status == "done"

    docs = _outbox(conn, "document")
    assert len(docs) == 1
    doc = docs[0]
    assert "Finished" in doc["text"]
    assert "Tasks: 2" in doc["text"]
    assert "Commits:" in doc["text"]
    assert "Time taken:" in doc["text"]
    assert doc["document_path"] == idea.plan_path

    # Second tick: moves to done once, no new document
    acted2 = watch.tick(conn)
    assert acted2 == []
    assert len(_outbox(conn, "document")) == 1


# 8. Show evidence button
def test_show_evidence_button_replies_with_evidence(
    conn, fake_repo, monkeypatch, token
):
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, fake_repo=fake_repo, status="paused")

    _set_relay_state(
        fake_repo,
        task_id="TASK-1",
        paused_reason="Turn exceeded 900s and was terminated",
    )

    press = _press(f"evidence:{idea.id}:{idea.revision}", "cb_ev", update_id=30)
    bot.handle(conn, press)

    messages = _outbox(conn, "message")
    last_msg = messages[-1]
    assert "exceeded" in last_msg["text"]


# 9. Assistant status proposal
def test_assistant_status_proposal_replies_with_status(
    conn, fake_repo, monkeypatch, token
):
    from whyline.ideas import assistant

    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, fake_repo=fake_repo, status="running")

    def fake_propose(conn, text, idea=None, context=None, run_fn=None):
        return assistant.Proposal(
            kind="status",
            fields={"idea_id": idea.id if idea else None},
            summary="Status",
        )

    monkeypatch.setattr(assistant, "propose", fake_propose)

    bot.handle(
        conn,
        {
            "update_id": 40,
            "handled": 0,
            "chat_id": CHAT,
            "text": "use claude to check status",
            "callback_data": None,
            "reply_to_message_id": None,
            "at": "2026-10-20T10:00:00Z",
            "kind": "message",
            "raw": "{}",
        },
    )

    messages = _outbox(conn, "message")
    last_msg = messages[-1]
    assert "Plan: receipt-parser.plan.md" in last_msg["text"]
    assert "Stop" in last_msg["buttons_json"]
    assert "Refresh" in last_msg["buttons_json"]


# 10. Worker run_once calls watch.tick
def test_worker_run_once_calls_watch_tick(conn, fake_repo, monkeypatch, token):
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, fake_repo=fake_repo, status="running")

    _set_relay_state(
        fake_repo,
        task_id="TASK-1",
        paused_reason="Turn exceeded 900s and was terminated",
    )

    worker._kv_set(conn, "enabled", "on")

    worker.run_once(
        now=NOW,
        poll=lambda conn, timeout=0: 0,
        handle=lambda conn, row: None,
        flush=lambda conn: 0,
        spawn=lambda job_id: 1,
        pid_alive=lambda pid: False,
        stop=lambda pid: None,
    )

    fresh = store.get(conn, idea.id)
    assert fresh.status == "paused"
    assert len(_outbox(conn, "message")) == 1


# 11. Running and paused flow emits Status button, and tapping it returns status
def test_status_button_emitted_and_tapping_it_returns_status(
    conn, fake_repo, monkeypatch, token
):
    (fake_repo / ".gitignore").write_text(".whyline/relay/state.json\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=fake_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "ignore state.json"], cwd=fake_repo, check=True)

    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, fake_repo=fake_repo, status="ready")

    _set_relay_state(
        fake_repo,
        task_id="TASK-1",
        stage="draft",
        round=1,
    )

    # 1. Running and paused status buttons include Status
    for st in ("running", "paused"):
        st_buttons = bot.buttons_for(st)
        labels = [label for label, _action in st_buttons]
        assert "Status" in labels
        assert "Stop" in labels

    # 2. Start notification in run.py emits the running keyboard with Status
    def fake_resume(root, req, launcher=None):
        return {"phase": "running"}

    ideas_run.run(conn, idea.id, resume_fn=fake_resume)
    start_msgs = [
        m
        for m in _outbox(conn, "message")
        if "Started. Ask /status any time." in m["text"]
    ]
    assert len(start_msgs) == 1
    start_buttons = json.loads(start_msgs[0]["buttons_json"])
    flat_start_btns = [b for row in start_buttons for b in row]
    status_btn = next((b for b in flat_start_btns if b["text"] == "Status"), None)
    assert status_btn is not None
    assert f"status:{idea.id}" in status_btn["callback_data"]

    # 3. Tapping the emitted Status button replies with status and Stop / Refresh buttons
    fresh = store.get(conn, idea.id)
    press_status = _press(status_btn["callback_data"], "cb_status_btn", update_id=50)
    bot.handle(conn, press_status)

    messages = _outbox(conn, "message")
    status_msg = messages[-1]
    assert "Plan: receipt-parser.plan.md" in status_msg["text"]
    assert "Tasks: 0 of 1" in status_msg["text"]
    assert "TASK-1" in status_msg["text"]

    status_buttons = json.loads(status_msg["buttons_json"])
    flat_status_btns = [b for row in status_buttons for b in row]
    status_labels = [b["text"] for b in flat_status_btns]
    assert status_labels == ["Stop", "Refresh"]

    # 4. Tapping the emitted Refresh button on status also refreshes status
    refresh_btn = next(b for b in flat_status_btns if b["text"] == "Refresh")
    press_refresh = _press(
        refresh_btn["callback_data"], "cb_refresh_btn", update_id=51
    )
    bot.handle(conn, press_refresh)

    messages_after = _outbox(conn, "message")
    refreshed_msg = messages_after[-1]
    assert "Plan: receipt-parser.plan.md" in refreshed_msg["text"]
    assert "Tasks: 0 of 1" in refreshed_msg["text"]

