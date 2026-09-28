from pathlib import Path

from whyline.console import adapters


def _init_relay_repo(repo):
    import subprocess

    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=repo.path, check=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo.path, check=True)
    (repo.path / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo.path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo.path, check=True)


def test_run_chat_turn_returns_an_output_event_on_success(repo, monkeypatch):
    _init_relay_repo(repo)
    from whyline_relay import chat, config as relay_config

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult

        return RunResult(0, '{"type":"result","result":"pong"}\n')

    monkeypatch.setattr(
        adapters, "_chat_run_fn_for_tests", fake_run_fn, raising=False
    )
    # run_chat_turn must accept an injected run_fn the same way chat.run_turn
    # itself does -- see the implementation step for why this parameter
    # exists.
    event = adapters.run_chat_turn(
        repo.path, agent="claude", prompt="ping", run_fn=fake_run_fn
    )
    assert event.kind == "output"
    assert "pong" in event.text


def test_run_chat_turn_reports_agent_unavailable(repo):
    _init_relay_repo(repo)
    event = adapters.run_chat_turn(repo.path, agent="grok", prompt="ping")
    assert event.kind == "error"
    assert "grok" in event.text


def test_run_chat_turn_reports_agent_missing(repo, monkeypatch):
    _init_relay_repo(repo)
    from whyline_relay import agents

    def fake_run_fn(command, prompt, **kwargs):
        raise agents.AgentMissing("claude is not installed")

    event = adapters.run_chat_turn(
        repo.path, agent="claude", prompt="ping", run_fn=fake_run_fn
    )
    assert event.kind == "error"
    assert "not installed" in event.text


def test_run_doctor_reports_ok_when_checks_pass(repo, monkeypatch):
    from whyline_relay import preflight

    monkeypatch.setattr(
        preflight,
        "run",
        lambda root, plan_path=None, **kwargs: [
            preflight.Check(status="ok", message="all good")
        ],
    )
    event = adapters.run_doctor(repo.path)
    assert event.kind == "output"
    assert "all good" in event.text


def test_run_doctor_reports_error_when_a_check_fails(repo, monkeypatch):
    from whyline_relay import preflight

    monkeypatch.setattr(
        preflight,
        "run",
        lambda root, plan_path=None, **kwargs: [
            preflight.Check(status="FAIL", message="broken", hint="fix it")
        ],
    )
    event = adapters.run_doctor(repo.path)
    assert event.kind == "error"
    assert "broken" in event.text
    assert "fix it" in event.text


def test_run_status_with_nothing_running_says_so(repo):
    event = adapters.run_status(repo.path)
    assert event.kind == "output"
    assert "no relay run in progress" in event.text.lower()


def test_run_status_reports_a_paused_run(repo):
    from whyline_relay import state

    state.save(
        repo.path,
        state.RelayState(
            plan="plan.md",
            branch="relay/plan",
            task_id="T-1",
            round=1,
            base_commit="abc123",
            paused_reason="stuck",
            log_path="",
        ),
    )
    event = adapters.run_status(repo.path)
    assert event.kind == "pause"
    assert "T-1" in event.text
    assert "stuck" in event.text


def test_failure_kind_classifies_rate_limit():
    assert (
        adapters.failure_kind(
            "codex hit a usage or rate limit; try again when it resets"
        )
        == "rate-limit"
    )


def test_failure_kind_classifies_auth():
    assert (
        adapters.failure_kind(
            "codex is no longer logged in; try again once you've signed back in"
        )
        == "auth"
    )


def test_failure_kind_classifies_no_handoff():
    assert (
        adapters.failure_kind(
            "grok exited without handing off; nothing was routed"
        )
        == "no-handoff"
    )


def test_failure_kind_classifies_round_cap():
    assert (
        adapters.failure_kind("T-1 hit the 3-round cap without an approval")
        == "round-cap"
    )


def test_failure_kind_classifies_blocked():
    assert (
        adapters.failure_kind("codex reported blocked: needs clarification")
        == "blocked"
    )


def test_failure_kind_falls_back_to_other():
    assert (
        adapters.failure_kind("something entirely unrecognized happened")
        == "other"
    )


def _write_handoff(root, **fields):
    import json

    target = root / ".whyline"
    target.mkdir(parents=True, exist_ok=True)
    record = {
        "v": 1,
        "id": "abc123",
        "type": "Handoff",
        "task": "T-1",
        "from_actor": "codex",
        "to_actor": "claude",
        "status": "ready-for-review",
        "summary": "Implemented the cache",
        **fields,
    }
    (target / "active-handoff.json").write_text(
        json.dumps(record), encoding="utf-8"
    )


def test_run_last_handoff_renders_the_current_record(tmp_path):
    _write_handoff(tmp_path)
    event = adapters.run_last_handoff(tmp_path)
    assert event.kind == "output"
    assert "T-1" in event.text
    assert "codex" in event.text and "claude" in event.text
    assert "ready-for-review" in event.text
    assert "Implemented the cache" in event.text


def test_run_last_handoff_shows_questions_when_blocked(tmp_path):
    _write_handoff(
        tmp_path, status="blocked", questions=["Which cache?", "Run tests?"]
    )
    event = adapters.run_last_handoff(tmp_path)
    assert "Which cache?" in event.text
    assert "Run tests?" in event.text


def test_run_last_handoff_with_nothing_recorded_says_so(tmp_path):
    event = adapters.run_last_handoff(tmp_path)
    assert event.kind == "output"
    assert "No handoff recorded yet" in event.text
