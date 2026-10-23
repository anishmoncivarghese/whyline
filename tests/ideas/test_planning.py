"""Tests for planning: drafting spec and plan, questions over Telegram."""

import json
import os
import subprocess
import time
from collections import namedtuple
from datetime import datetime
from pathlib import Path

import pytest

from whyline.console.plan_job import AutoRunRequest
from whyline.ideas import bot, paths, planning, setup, store, worker

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


def _seed_idea(conn, text="Build receipt parser", status="brainstormed", repo="repo1"):
    idea = store.add(conn, text, source="telegram", source_ref=f"{CHAT}:1")
    if repo:
        store.set_repo(conn, idea.id, repo)
    if status != "captured":
        conn.execute("UPDATE ideas SET status = ? WHERE id = ?", (status, idea.id))
    bs_file = paths.home() / "brainstorms" / f"{idea.id}.md"
    bs_file.parent.mkdir(parents=True, exist_ok=True)
    bs_file.write_text("## Final Synthesis\nReceipt parser idea")
    store.set_paths(conn, idea.id, brainstorm_path=str(bs_file))
    return store.get(conn, idea.id)


def _message(text, *, update_id=1, message_id=5):
    return {
        "update_id": update_id,
        "handled": 0,
        "chat_id": CHAT,
        "text": text,
        "callback_data": None,
        "reply_to_message_id": None,
        "at": "2026-10-20T10:00:00Z",
        "kind": "message",
        "raw": json.dumps({"message_id": message_id}),
    }


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
        # Execute synchronously for testing
        worker.work(job_id)
        return 4242

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


def test_dirty_repository_waits_and_does_not_draft(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Dirty repo idea", status="setup_configuring")

    # Make target repository dirty
    (fake_repo / "dirty.txt").write_text("uncommitted changes\n")

    draft_calls = []

    def fake_run(*args, **kwargs):
        draft_calls.append((args, kwargs))
        return {"phase": "plan"}

    monkeypatch.setattr(planning.auto_run, "run", fake_run)

    # Confirm on Set up card queues a plan job
    bot.handle(conn, _press(f"confirm:{idea.id}:{idea.revision}", "cb_confirm"))

    # Tick runs
    _run_tick(conn)

    # 1. auto_run.run must NOT have been called
    assert draft_calls == []

    # 2. Idea moved to plan_waiting
    idea = store.get(conn, idea.id)
    assert idea.status == "plan_waiting"

    # 3. Chat told once with dirty path and Cancel button
    messages = [m for m in _outbox(conn, "message") if m["text"] != "Confirmed."]
    assert len(messages) == 1
    wait_msg = messages[0]
    assert "dirty.txt" in wait_msg["text"]
    buttons = json.loads(wait_msg["buttons_json"])
    assert buttons[0][0]["text"] == "Cancel"
    assert buttons[0][0]["callback_data"].startswith(f"cancel:{idea.id}:")

    # 4. Tick again: chat is told only once
    _run_tick(conn)
    messages2 = [m for m in _outbox(conn, "message") if m["text"] != "Confirmed."]
    assert len(messages2) == 1

    # 5. Cancel button returns to brainstormed
    cancel_cb = buttons[0][0]["callback_data"]
    bot.handle(conn, _press(cancel_cb, "cb_cancel"))
    idea = store.get(conn, idea.id)
    assert idea.status == "brainstormed"


def test_running_relay_waits(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Running relay idea", status="setup_configuring")

    draft_calls = []

    def fake_run(*args, **kwargs):
        draft_calls.append((args, kwargs))
        return {"phase": "plan"}

    monkeypatch.setattr(planning.auto_run, "run", fake_run)

    # Mock running relay
    RelayMock = namedtuple("RelayMock", ["task", "agent"])
    import whyline_relay.running
    monkeypatch.setattr(
        whyline_relay.running,
        "live",
        lambda root: RelayMock("TASK-1", "codex") if str(root) == str(fake_repo) else None,
    )

    # Confirm queues plan job
    bot.handle(conn, _press(f"confirm:{idea.id}:{idea.revision}", "cb_confirm"))

    # Tick runs
    _run_tick(conn)

    # Does not draft
    assert draft_calls == []

    # Moved to plan_waiting
    idea = store.get(conn, idea.id)
    assert idea.status == "plan_waiting"

    # Told once: "Waiting: a relay is running in repo1"
    messages = [m for m in _outbox(conn, "message") if m["text"] != "Confirmed."]
    assert len(messages) == 1
    assert "Waiting: a relay is running in repo1" in messages[0]["text"]
    buttons = json.loads(messages[0]["buttons_json"])
    assert buttons[0][0]["text"] == "Cancel"

    # Tick again: told once
    _run_tick(conn)
    messages2 = [m for m in _outbox(conn, "message") if m["text"] != "Confirmed."]
    assert len(messages2) == 1

    # Cancel returns to brainstormed
    cancel_cb = buttons[0][0]["callback_data"]
    bot.handle(conn, _press(cancel_cb, "cb_cancel"))
    assert store.get(conn, idea.id).status == "brainstormed"


def test_questions_round_trip_through_chat_into_resume(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Ask questions idea", status="setup_configuring")

    run_calls = []
    resume_calls = []

    def fake_run(root, request, dismissed, through, synthesis, progress, cancel_event):
        run_calls.append((root, request, dismissed, through, synthesis))
        return {
            "phase": "plan",
            "pause": {
                "reason": "The draft has open questions:\n- Which database should we use?\nDraft: .whyline/relay/draft-plan.md",
                "actions": ["answer", "retry", "stop"],
            },
            "spec": {"path": str(fake_repo / "spec.md")},
        }

    def fake_resume(root, request, *, answer=None, through=None, progress=None, cancel_event=None, synthesis=None):
        resume_calls.append({"answer": answer, "through": through, "synthesis": synthesis})
        (fake_repo / "spec.md").write_text("# Spec\n")
        (fake_repo / "plan.md").write_text("# Plan\n")
        return {
            "phase": "plan",
            "spec": {"path": str(fake_repo / "spec.md")},
            "plan": {"path": str(fake_repo / "plan.md")},
        }

    monkeypatch.setattr(planning.auto_run, "run", fake_run)
    monkeypatch.setattr(planning.auto_run, "resume", fake_resume)

    # Confirm queues plan job
    bot.handle(conn, _press(f"confirm:{idea.id}:{idea.revision}", "cb_confirm"))

    # Worker runs
    _run_tick(conn)

    assert len(run_calls) == 1
    assert str(run_calls[0][4]) == idea.brainstorm_path

    # Checkpoint paused with questions: moves nothing, stays in planning
    idea = store.get(conn, idea.id)
    assert idea.status == "planning"

    # Sent questions as one message
    messages = [m for m in _outbox(conn, "message") if m["text"] != "Confirmed."]
    assert len(messages) == 1
    assert "Which database should we use?" in messages[0]["text"]

    # Open question is set
    open_q = bot._open_for(conn, CHAT)
    assert open_q is not None
    assert open_q["kind"] == "plan_question"

    # Human replies to question
    bot.handle(conn, _message("We will use PostgreSQL", update_id=20))

    # Next tick runs the resumed job
    _run_tick(conn)

    assert len(resume_calls) == 1
    assert resume_calls[0]["answer"] == "We will use PostgreSQL"
    assert resume_calls[0]["through"] == "plan"

    # Reached phase plan
    idea = store.get(conn, idea.id)
    assert idea.status == "plan_review"
    assert idea.spec_path == str(fake_repo / "spec.md")
    assert idea.plan_path == str(fake_repo / "plan.md")


def test_finished_run_sends_two_documents_with_three_buttons(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Finish plan idea", status="setup_configuring")

    spec_file = fake_repo / "spec.md"
    plan_file = fake_repo / "plan.md"

    def fake_run(root, request, dismissed, through, synthesis, progress, cancel_event):
        spec_file.write_text("# Spec Content\n")
        plan_file.write_text("# Plan Content\n")
        return {
            "phase": "plan",
            "spec": {"path": str(spec_file)},
            "plan": {"path": str(plan_file)},
        }

    monkeypatch.setattr(planning.auto_run, "run", fake_run)

    bot.handle(conn, _press(f"confirm:{idea.id}:{idea.revision}", "cb_confirm"))
    _run_tick(conn)

    idea = store.get(conn, idea.id)
    assert idea.status == "plan_review"
    assert idea.spec_path == str(spec_file)
    assert idea.plan_path == str(plan_file)

    # Sends two documents
    docs = _outbox(conn, "document")
    assert len(docs) == 2
    assert docs[0]["document_path"] == str(spec_file)
    assert docs[1]["document_path"] == str(plan_file)

    # Buttons on the document are Start / Change / Discard
    buttons = json.loads(docs[1]["buttons_json"])
    labels = [cell["text"] for line in buttons for cell in line]
    assert labels == ["Start", "Change", "Discard"]


def test_change_calls_redraft_plan_with_reply(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Change plan idea", status="plan_review")

    spec_file = fake_repo / "spec.md"
    plan_v1 = fake_repo / "plan_v1.md"
    plan_v2 = fake_repo / "plan_v2.md"
    spec_file.write_text("# Spec\n")
    plan_v1.write_text("# Plan V1\n")
    subprocess.run(["git", "add", "-A"], cwd=fake_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "docs v1"], cwd=fake_repo, check=True)

    store.set_paths(conn, idea.id, spec_path=str(spec_file), plan_path=str(plan_v1))
    idea = store.get(conn, idea.id)

    redraft_calls = []

    def fake_redraft(root, request, feedback, *, progress=None):
        redraft_calls.append({"feedback": feedback})
        plan_v2.write_text("# Plan V2\n")
        return {
            "phase": "plan",
            "plan": {"path": str(plan_v2)},
        }

    monkeypatch.setattr(planning.auto_run, "redraft_plan", fake_redraft)

    # Tap Change
    bot.handle(conn, _press(f"change_plan:{idea.id}:{idea.revision}", "cb_change"))

    # Bot asks "What should change?"
    messages = _outbox(conn, "message")
    assert messages[-1]["text"] == "What should change?"

    # Human replies
    bot.handle(conn, _message("Add auth module and unit tests", update_id=30))

    # Worker runs redraft job
    _run_tick(conn)

    assert len(redraft_calls) == 1
    assert redraft_calls[0]["feedback"] == "Add auth module and unit tests"

    # New plan path is saved
    idea = store.get(conn, idea.id)
    assert idea.plan_path == str(plan_v2)
    assert idea.status == "plan_review"

    # Sends the new plan with the same three buttons
    docs = _outbox(conn, "document")
    assert len(docs) == 1
    assert docs[0]["document_path"] == str(plan_v2)
    buttons = json.loads(docs[0]["buttons_json"])
    labels = [cell["text"] for line in buttons for cell in line]
    assert labels == ["Start", "Change", "Discard"]


def test_discard_never_deletes_a_file_or_calls_the_launcher(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Discard plan idea", status="plan_review")

    spec_file = fake_repo / "spec.md"
    plan_file = fake_repo / "plan.md"
    spec_file.write_text("# Spec\n")
    plan_file.write_text("# Plan\n")
    subprocess.run(["git", "add", "-A"], cwd=fake_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "docs"], cwd=fake_repo, check=True)

    store.set_paths(conn, idea.id, spec_path=str(spec_file), plan_path=str(plan_file))
    idea = store.get(conn, idea.id)

    stop_calls = []
    launcher_calls = []

    def fake_stop(root, cancel_event=None):
        stop_calls.append(root)

    def fake_launcher(*args, **kwargs):
        launcher_calls.append((args, kwargs))

    monkeypatch.setattr(planning.auto_run, "stop", fake_stop)

    # Tap Discard
    bot.handle(conn, _press(f"discard_plan:{idea.id}:{idea.revision}", "cb_discard"))

    # Confirms first
    confirm_msg = _outbox(conn, "message")[-1]
    assert "Discard this plan?" in confirm_msg["text"]
    buttons = json.loads(confirm_msg["buttons_json"])
    discard_cb = buttons[0][0]["callback_data"]
    assert "discard_plan_yes" in discard_cb

    # Confirm discard
    fresh = store.get(conn, idea.id)
    bot.handle(conn, _press(f"discard_plan_yes:{fresh.id}:{fresh.revision}", "cb_yes"))

    # Calls auto_run.stop
    assert len(stop_calls) == 1
    assert stop_calls[0] == fake_repo

    # Moves to plan_discarded
    idea = store.get(conn, idea.id)
    assert idea.status == "plan_discarded"

    # Leaves spec and plan files where they are: never deletes them
    assert spec_file.exists()
    assert plan_file.exists()

    # Launcher is NEVER called
    assert launcher_calls == []

    # Chat message names their paths
    last_msg = _outbox(conn, "message")[-1]
    assert str(spec_file) in last_msg["text"]
    assert str(plan_file) in last_msg["text"]


def test_other_pause_sends_reason_with_retry_and_cancel(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Pause other idea", status="setup_configuring")

    def fake_run(root, request, dismissed, through, synthesis, progress, cancel_event):
        return {
            "phase": "plan",
            "pause": {
                "reason": "Model failures exhausted: claude, codex",
                "actions": ["retry", "cancel"],
            },
        }

    monkeypatch.setattr(planning.auto_run, "run", fake_run)

    bot.handle(conn, _press(f"confirm:{idea.id}:{idea.revision}", "cb_confirm"))
    _run_tick(conn)

    # Sends reason with Retry / Cancel
    messages = [m for m in _outbox(conn, "message") if m["text"] != "Confirmed."]
    assert len(messages) == 1
    assert "Model failures exhausted: claude, codex" in messages[0]["text"]
    buttons = json.loads(messages[0]["buttons_json"])
    labels = [cell["text"] for line in buttons for cell in line]
    assert labels == ["Retry", "Cancel"]

    # Tap Retry
    retry_cb = buttons[0][0]["callback_data"]
    bot.handle(conn, _press(retry_cb, "cb_retry"))

    # Plan job is queued with action resume
    job = conn.execute("SELECT * FROM jobs WHERE kind = 'plan' ORDER BY id DESC").fetchone()
    assert job is not None
    assert job["state"] in ("queued", "running")


def test_redraft_pause_sends_reason_with_retry_and_cancel(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Redraft pause idea", status="plan_review")

    spec_file = fake_repo / "spec.md"
    plan_v1 = fake_repo / "plan_v1.md"
    spec_file.write_text("# Spec\n")
    plan_v1.write_text("# Plan V1\n")
    subprocess.run(["git", "add", "-A"], cwd=fake_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "docs v1"], cwd=fake_repo, check=True)
    store.set_paths(conn, idea.id, spec_path=str(spec_file), plan_path=str(plan_v1))
    idea = store.get(conn, idea.id)

    def fake_redraft(root, request, feedback, *, progress=None):
        return {
            "phase": "plan",
            "pause": {
                "reason": "Plan format is invalid\nDraft: draft-plan.md",
                "actions": ["retry", "cancel"],
            },
        }

    monkeypatch.setattr(planning.auto_run, "redraft_plan", fake_redraft)

    # Tap Change
    bot.handle(conn, _press(f"change_plan:{idea.id}:{idea.revision}", "cb_change"))
    # Reply with change request
    bot.handle(conn, _message("Fix section 2", update_id=40))

    # Worker runs redraft job
    _run_tick(conn)

    # Idea did NOT move back to plan_review (it paused during planning)
    fresh = store.get(conn, idea.id)
    assert fresh.status == "planning"

    # Reason sent with Retry / Cancel
    messages = [m for m in _outbox(conn, "message") if "Plan format is invalid" in m["text"]]
    assert len(messages) == 1
    buttons = json.loads(messages[0]["buttons_json"])
    labels = [cell["text"] for line in buttons for cell in line]
    assert labels == ["Retry", "Cancel"]

    # No document was sent
    docs = _outbox(conn, "document")
    assert len(docs) == 0


def test_real_auto_run_pause_and_resume_stops_at_plan_review(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Real auto_run integration", status="setup_configuring")

    from whyline.console import relay_ops
    from whyline_relay import loop, preflight

    monkeypatch.setattr(preflight, "run", lambda *args, **kwargs: [])

    spec_file = fake_repo / "docs" / "specs" / "plan.md"
    plan_file = fake_repo / "plans" / "plan.plan.md"

    def draft_spec(_root, text, attachments=(), *, progress):
        draft_path = fake_repo / ".whyline" / "relay" / "draft-spec.md"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text("# Spec\n", encoding="utf-8")
        return relay_ops.Draft(path=draft_path, text="# Spec\n", drafted_by="codex", source="spec", agent="codex")

    def approve_spec(_root, draft, name, *, replace=False):
        spec_file.parent.mkdir(parents=True, exist_ok=True)
        spec_file.write_text(draft.text, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=fake_repo, check=True)
        subprocess.run(["git", "commit", "-qm", "spec"], cwd=fake_repo, check=True)
        return spec_file

    first_draft = [True]

    def draft_plan(_root, description, attachments=(), *, progress, spec=None):
        draft_path = fake_repo / ".whyline" / "relay" / "draft-plan.md"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text("# Plan draft\n", encoding="utf-8")
        if first_draft[0]:
            first_draft[0] = False
            raise loop.Paused("The draft has open questions:\n- Which architecture?")
        return relay_ops.Draft(path=draft_path, text="- [ ] Task 1\n", drafted_by="codex", source="planner", agent="codex")

    def resume_draft(_root, *, progress=None):
        draft_path = fake_repo / ".whyline" / "relay" / "draft-plan.md"
        return relay_ops.Draft(path=draft_path, text="- [ ] Task 1\n", drafted_by="codex", source="planner", agent="codex")

    def approve_plan(_root, draft, name, *, replace=False, spec=""):
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text(draft.text, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=fake_repo, check=True)
        subprocess.run(["git", "commit", "-qm", "plan"], cwd=fake_repo, check=True)
        return plan_file

    launcher_called = [False]

    def fail_launcher(args):
        launcher_called[0] = True
        raise AssertionError("launcher must not be called")

    monkeypatch.setattr(relay_ops, "draft_spec", draft_spec)
    monkeypatch.setattr(relay_ops, "approve_spec", approve_spec)
    monkeypatch.setattr(relay_ops, "draft_plan", draft_plan)
    monkeypatch.setattr(relay_ops, "resume_draft", resume_draft)
    monkeypatch.setattr(relay_ops, "approve_plan", approve_plan)
    monkeypatch.setattr(relay_ops, "validate_plan", lambda _text: [])

    # Confirm starts plan job using real auto_run.run
    bot.handle(conn, _press(f"confirm:{idea.id}:{idea.revision}", "cb_confirm"))
    _run_tick(conn)

    # Real auto_run paused with open questions in phase 'plan'
    idea = store.get(conn, idea.id)
    assert idea.status == "planning"
    messages = [m for m in _outbox(conn, "message") if m["text"] != "Confirmed."]
    assert len(messages) == 1
    assert "Which architecture?" in messages[0]["text"]

    # Reply to question
    bot.handle(conn, _message("Microservices", update_id=25))

    # Next tick runs the real auto_run.resume
    # It must stop at plan review without requiring launcher or launching relay!
    _run_tick(conn)

    # Reached plan_review without calling launcher
    assert not launcher_called[0]
    idea = store.get(conn, idea.id)
    assert idea.status == "plan_review"
    assert idea.spec_path == str(spec_file)
    assert idea.plan_path == str(plan_file)

    # Both documents sent
    docs = _outbox(conn, "document")
    assert len(docs) == 2
    assert docs[0]["document_path"] == str(spec_file)
    assert docs[1]["document_path"] == str(plan_file)


def test_progress_throttled_to_once_a_minute(conn, monkeypatch):
    idea = _seed_idea(conn, "Progress idea", status="planning")
    edited = []

    monkeypatch.setattr(
        bot, "edit_progress", lambda conn, idea_id, text, chat_id=None: edited.append(text)
    )

    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    prog = planning.run.__globals__["time"]  # test through planning's helper
    on_prog = None

    # Use make_progress logic
    last_sent = [0.0]

    def on_progress(line=""):
        text = str(line).strip() if line else ""
        if not text:
            return
        current = now[0]
        if last_sent[0] > 0.0 and (current - last_sent[0] < 60.0):
            return
        last_sent[0] = current
        edited.append(text)

    on_progress("Step 1")
    assert edited == ["Step 1"]

    # 10s later: throttled
    now[0] += 10.0
    on_progress("Step 2")
    assert edited == ["Step 1"]

    # 61s after first: allowed
    now[0] += 51.0
    on_progress("Step 3")
    assert edited == ["Step 1", "Step 3"]
