"""Tests for recovery route classification and attempt records."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whyline.console import adapters, recovery, tui


def test_every_kind_maps_as_listed() -> None:
    # Preflight clean-tree FAIL kind
    assert recovery.route("dirty", [".whyline/decisions.md"]) == "fix"
    assert recovery.route("dirty", ["src/other.py"]) == "human"

    # adapters.failure_kind values
    assert recovery.route("sandbox", []) == "human"
    assert recovery.route("visit-cap", []) == "human"
    assert recovery.route("no-handoff", []) == "agent"
    assert recovery.route("rate-limit", []) == "failover"
    assert recovery.route("auth", []) == "human"
    assert recovery.route("blocked", []) == "human"
    assert recovery.route("round-cap", []) == "human"
    assert recovery.route("release", []) == "human"
    assert recovery.route("other", []) == "human"

    # Any unrecognized kind falls back to human
    assert recovery.route("unknown-kind", []) == "human"


def test_failure_kind_integration() -> None:
    reasons_and_expected = [
        ("codex could not run a required command: pytest: permission denied", "human"),
        ("T-1 hit stage 'review''s 3-visit cap without reaching \"@complete\"", "human"),
        ("hit a usage or rate limit", "failover"),
        ("is no longer logged in", "human"),
        ("exited without handing off", "agent"),
        ("hit round cap without completion", "human"),
        ("reported blocked: permission denied", "human"),
        ("release task for you: check results", "human"),
        ("something unexpected crashed", "human"),
    ]
    for reason, expected_route in reasons_and_expected:
        kind = adapters.failure_kind(reason)
        assert recovery.route(kind, []) == expected_route


def test_decision_log_only_dirty_set_is_fix_and_adding_one_more_path_is_human() -> None:
    # Exactly [".whyline/decisions.md"] is fix
    assert recovery.route("dirty", [".whyline/decisions.md"]) == "fix"

    # Adding one more path makes it human
    assert recovery.route("dirty", [".whyline/decisions.md", "src/foo.py"]) == "human"
    assert recovery.route("dirty", [".whyline/decisions.md", "tests/test_foo.py"]) == "human"
    assert recovery.route("dirty", [".whyline/decisions.md", ".whyline/config.toml"]) == "human"

    # Other dirty sets are human
    assert recovery.route("dirty", ["src/foo.py"]) == "human"
    assert recovery.route("dirty", []) == "human"
    assert recovery.route("dirty", None) == "human"


def test_allowed_refuses_second_attempt_and_allows_new_round(tmp_path: Path) -> None:
    # Initially allowed
    assert recovery.allowed(tmp_path, "REC-1", 1) is True

    # First attempt recorded
    entry = recovery.record_attempt(
        tmp_path,
        task="REC-1",
        round=1,
        kind="no-handoff",
        agent="codex",
        verdict="needs-human",
    )
    assert entry["task"] == "REC-1"
    assert entry["round"] == 1
    assert entry["kind"] == "no-handoff"
    assert entry["agent"] == "codex"
    assert entry["verdict"] == "needs-human"
    assert "at" in entry and isinstance(entry["at"], str)

    # Second attempt for same task and round is refused
    assert recovery.allowed(tmp_path, "REC-1", 1) is False

    # A new round for the same task is allowed
    assert recovery.allowed(tmp_path, "REC-1", 2) is True

    # A different task for the same round is allowed
    assert recovery.allowed(tmp_path, "REC-2", 1) is True

    # Record round 2 attempt
    recovery.record_attempt(
        tmp_path,
        task="REC-1",
        round=2,
        kind="rate-limit",
        agent="grok",
        verdict="failover",
    )
    assert recovery.allowed(tmp_path, "REC-1", 2) is False

    # Check recovery.json file content on disk
    rec_file = tmp_path / ".whyline" / "relay" / "recovery.json"
    assert rec_file.is_file()
    records = json.loads(rec_file.read_text(encoding="utf-8"))
    assert len(records) == 2
    assert records[0]["task"] == "REC-1"
    assert records[0]["round"] == 1
    assert records[1]["task"] == "REC-1"
    assert records[1]["round"] == 2


def test_corrupt_or_missing_file_reads_as_empty(tmp_path: Path) -> None:
    rec_file = tmp_path / ".whyline" / "relay" / "recovery.json"

    # Missing file
    assert recovery.load_attempts(tmp_path) == []
    assert recovery.allowed(tmp_path, "REC-1", 1) is True

    # Corrupt JSON syntax
    rec_file.parent.mkdir(parents=True, exist_ok=True)
    rec_file.write_text("{broken json", encoding="utf-8")
    assert recovery.load_attempts(tmp_path) == []
    assert recovery.allowed(tmp_path, "REC-1", 1) is True

    # JSON object instead of list
    rec_file.write_text(json.dumps({"task": "REC-1", "round": 1}), encoding="utf-8")
    assert recovery.load_attempts(tmp_path) == []
    assert recovery.allowed(tmp_path, "REC-1", 1) is True

    # JSON scalar instead of list
    rec_file.write_text('"not a list"', encoding="utf-8")
    assert recovery.load_attempts(tmp_path) == []
    assert recovery.allowed(tmp_path, "REC-1", 1) is True

    # List of non-dicts
    rec_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert recovery.load_attempts(tmp_path) == []
    assert recovery.allowed(tmp_path, "REC-1", 1) is True


def test_writes_go_through_temp_file_and_os_replace(tmp_path: Path, monkeypatch) -> None:
    replaced = []
    real_replace = recovery.os.replace

    def spy_replace(src, dst):
        replaced.append((Path(src), Path(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(recovery.os, "replace", spy_replace)

    recovery.record_attempt(
        tmp_path,
        task="REC-1",
        round=1,
        kind="dirty",
        agent="",
        verdict="fixed",
    )

    assert len(replaced) == 1
    src, dst = replaced[0]
    assert dst == tmp_path / ".whyline" / "relay" / "recovery.json"
    assert src.parent == dst.parent
    assert src.name.startswith(".recovery.json.")


def _init_scratch_repo(path: Path) -> Path:
    import subprocess
    from whyline_relay import gitcheck

    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=path, check=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["whyline", "init", "--yes"], cwd=path, check=True)
    gitcheck.ensure_relay_ignored(path)
    relay = path / ".whyline" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "codex"\nreviewer = "claude"\n',
        encoding="utf-8",
    )
    (relay / "claude-settings.json").write_text("{}\n", encoding="utf-8")
    (path / ".whyline" / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    return path


def _commit_count(path: Path) -> int:
    import subprocess

    res = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=path,
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return int(res.stdout.strip())


def _last_commit_message(path: Path) -> str:
    import subprocess

    res = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=path,
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return res.stdout.strip()


def test_decision_log_only_pause_commits_once_and_resolves(tmp_path: Path) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    count_before = _commit_count(repo)

    # Dirty only .whyline/decisions.md
    (repo / ".whyline" / "decisions.md").write_text(
        "# Decisions\n- [2026-10-14] Test decision\n", encoding="utf-8"
    )

    res = recovery.fix(repo, "REC-2")

    assert res == "resolved"
    assert res.verdict == "resolved"
    assert res.fail_lines == []
    assert _commit_count(repo) == count_before + 1
    assert _last_commit_message(repo) == "chore: record REC-2 decisions"


def test_second_dirty_path_is_human_and_commits_nothing(tmp_path: Path) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    count_before = _commit_count(repo)

    # Dirty .whyline/decisions.md AND another path
    (repo / ".whyline" / "decisions.md").write_text(
        "# Decisions\n- [2026-10-14] Test decision\n", encoding="utf-8"
    )
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "other.py").write_text("x = 1\n", encoding="utf-8")

    res = recovery.fix(repo, "REC-2")

    assert res == "human"
    assert res.verdict == "human"
    assert len(res.fail_lines) > 0
    assert any("working tree has uncommitted changes" in line for line in res.fail_lines)
    assert _commit_count(repo) == count_before
    # Both paths remain dirty
    assert (repo / "src" / "other.py").is_file()


def test_newer_handoff_in_second_repository_is_diagnosed(tmp_path: Path) -> None:
    relay_repo = _init_scratch_repo(tmp_path / "relay")
    second_repo = _init_scratch_repo(tmp_path / "second")

    plan_file = relay_repo / "plan.md"
    plan_file.write_text(
        f"""# Plan
- [ ] TASK-9: Task in second repository
  Edit {second_repo / "src" / "feature.py"} and implement the feature.
""",
        encoding="utf-8",
    )
    state_file = relay_repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "TASK-9",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-handoff-111",
        }),
        encoding="utf-8",
    )

    handoff_file = second_repo / ".whyline" / "active-handoff.json"
    handoff_file.write_text(
        json.dumps({
            "v": 1,
            "id": "new-handoff-999",
            "type": "Handoff",
            "task": "TASK-9",
            "from_actor": "codex",
            "to_actor": "antigravity",
            "status": "ready-for-review",
            "summary": "Done",
        }),
        encoding="utf-8",
    )

    diag = recovery.cross_repository_handoff(relay_repo)
    assert diag is not None
    assert "new-handoff-999" in diag
    assert str(second_repo.resolve()) in diag
    assert "TASK-9" in diag
    assert diag.handoff_id == "new-handoff-999"
    assert diag.repo == second_repo.resolve()
    assert diag.task_id == "TASK-9"

    # Aliases
    assert recovery.cross_repo_handoff(relay_repo) == diag
    assert recovery.diagnose_cross_repo_handoff(relay_repo) == diag


def test_handoff_for_another_task_or_equal_to_last_handoff_id_is_not_diagnosed(
    tmp_path: Path,
) -> None:
    relay_repo = _init_scratch_repo(tmp_path / "relay")
    second_repo = _init_scratch_repo(tmp_path / "second")

    plan_file = relay_repo / "plan.md"
    plan_file.write_text(
        f"""# Plan
- [ ] TASK-9: Task in second repository
  Edit {second_repo / "src" / "feature.py"} and implement the feature.
""",
        encoding="utf-8",
    )
    state_file = relay_repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "TASK-9",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-handoff-111",
        }),
        encoding="utf-8",
    )

    handoff_file = second_repo / ".whyline" / "active-handoff.json"

    # Case 1: Handoff for another task
    handoff_file.write_text(
        json.dumps({
            "v": 1,
            "id": "new-handoff-888",
            "type": "Handoff",
            "task": "DIFFERENT-TASK",
            "status": "ready-for-review",
        }),
        encoding="utf-8",
    )
    assert recovery.cross_repository_handoff(relay_repo) is None

    # Case 2: Handoff equal to last_handoff_id
    handoff_file.write_text(
        json.dumps({
            "v": 1,
            "id": "old-handoff-111",
            "task": "TASK-9",
            "status": "ready-for-review",
        }),
        encoding="utf-8",
    )
    assert recovery.cross_repository_handoff(relay_repo) is None

    # Case 3: Missing handoff file
    handoff_file.unlink()
    assert recovery.cross_repository_handoff(relay_repo) is None


def test_fix_reads_task_id_from_state_when_omitted(tmp_path: Path) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-STATE",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "dirty",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )
    (repo / ".whyline" / "decisions.md").write_text(
        "# Decisions\n- Note\n", encoding="utf-8"
    )
    res = recovery.fix(repo)
    assert res == "resolved"
    assert _last_commit_message(repo) == "chore: record REC-STATE decisions"


def test_cross_repository_handoff_ignores_paths_in_relay_root(tmp_path: Path) -> None:
    relay_repo = _init_scratch_repo(tmp_path / "relay")
    plan_file = relay_repo / "plan.md"
    plan_file.write_text(
        f"""# Plan
- [ ] TASK-1: Relay only
  Edit `{relay_repo / 'src' / 'file.py'}` and nothing else.
""",
        encoding="utf-8",
    )
    state_file = relay_repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "TASK-1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-1",
        }),
        encoding="utf-8",
    )
    assert recovery.cross_repository_handoff(relay_repo) is None


def test_recovery_turn_that_writes_new_handoff_resolves(tmp_path: Path) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-handoff-100",
        }),
        encoding="utf-8",
    )
    (repo / ".whyline" / "active-handoff.json").write_text(
        json.dumps({
            "v": 1,
            "id": "old-handoff-100",
            "task": "REC-3",
            "status": "in-progress",
        }),
        encoding="utf-8",
    )

    def fake_runner(command, prompt, **kwargs):
        (repo / ".whyline" / "active-handoff.json").write_text(
            json.dumps({
                "v": 1,
                "id": "new-handoff-200",
                "task": "REC-3",
                "status": "ready-for-review",
                "summary": "Recovered",
            }),
            encoding="utf-8",
        )
        return "RECOVERY: resolved\n"

    res = recovery.recover(repo, agent="codex", runner=fake_runner)
    assert res == "resolved"
    assert res.verdict == "resolved"

    attempts = recovery.load_attempts(repo)
    assert len(attempts) == 1
    assert attempts[0]["task"] == "REC-3"
    assert attempts[0]["round"] == 1
    assert attempts[0]["kind"] == "agent"
    assert attempts[0]["agent"] == "codex"
    assert attempts[0]["verdict"] == "resolved"

    decisions_text = (repo / ".whyline" / "decisions.md").read_text(encoding="utf-8")
    assert "recovery" in decisions_text.lower()

    import subprocess

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert status.strip() == ""


def test_recovery_turn_resolved_line_without_new_handoff_is_human(
    tmp_path: Path,
) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-handoff-100",
        }),
        encoding="utf-8",
    )
    (repo / ".whyline" / "active-handoff.json").write_text(
        json.dumps({
            "v": 1,
            "id": "old-handoff-100",
            "task": "REC-3",
            "status": "in-progress",
        }),
        encoding="utf-8",
    )

    def fake_runner(command, prompt, **kwargs):
        # Outputs resolved without writing a new handoff
        return "RECOVERY: resolved\n"

    res = recovery.recover(repo, agent="codex", runner=fake_runner)
    assert res == "human"
    assert res.verdict == "human"

    attempts = recovery.load_attempts(repo)
    assert len(attempts) == 1
    assert attempts[0]["verdict"] == "human"


def test_recovery_turn_that_edits_source_file_is_human_naming_file(
    tmp_path: Path,
) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-handoff-100",
        }),
        encoding="utf-8",
    )

    src_file = repo / "src" / "feature.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)

    def fake_runner(command, prompt, **kwargs):
        src_file.write_text("print('forbidden edit')\n", encoding="utf-8")
        (repo / ".whyline" / "active-handoff.json").write_text(
            json.dumps({
                "v": 1,
                "id": "new-handoff-200",
                "task": "REC-3",
                "status": "ready-for-review",
            }),
            encoding="utf-8",
        )
        return "RECOVERY: resolved\n"

    res = recovery.recover(repo, agent="codex", runner=fake_runner)
    assert res == "human"
    assert res.verdict == "human"
    assert "src/feature.py" in res
    assert "src/feature.py" in str(res)
    # File is not reverted by recovery
    assert src_file.is_file()


def test_recovery_failing_selected_agent_falls_through_to_first_backup(
    tmp_path: Path,
) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "grok"\nreviewer = "claude"\n[backup]\nchain = ["codex"]\n',
        encoding="utf-8",
    )
    import subprocess

    subprocess.run(["git", "commit", "-am", "update config"], cwd=repo, check=True)
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-handoff-100",
        }),
        encoding="utf-8",
    )

    from whyline_relay import agents as relay_agents

    called: list[str] = []

    def fake_runner(command, prompt, **kwargs):
        agent_name = kwargs.get("agent_name") or command[0]
        called.append(agent_name)
        if agent_name == "grok":
            raise relay_agents.AgentMissing("grok is not installed")
        if agent_name == "codex":
            (repo / ".whyline" / "active-handoff.json").write_text(
                json.dumps({
                    "v": 1,
                    "id": "new-handoff-200",
                    "task": "REC-3",
                    "status": "ready-for-review",
                }),
                encoding="utf-8",
            )
            return "RECOVERY: resolved\n"
        raise RuntimeError(f"unexpected agent {agent_name}")

    res = recovery.recover(repo, agent="grok", runner=fake_runner)
    assert res == "resolved"
    assert called == ["grok", "codex"]
    attempts = recovery.load_attempts(repo)
    assert len(attempts) == 1
    assert attempts[0]["agent"] == "codex"


def test_recovery_exhausted_chain_is_human_naming_agents_tried(
    tmp_path: Path,
) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "codex"\nreviewer = "claude"\n[backup]\nchain = ["claude"]\n',
        encoding="utf-8",
    )
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-100",
        }),
        encoding="utf-8",
    )

    from whyline_relay import agents as relay_agents

    called: list[str] = []

    def fake_runner(command, prompt, **kwargs):
        agent_name = kwargs.get("agent_name") or command[0]
        called.append(agent_name)
        raise relay_agents.AgentTimeout(f"{agent_name} timed out")

    res = recovery.recover(repo, agent="codex", runner=fake_runner)
    assert res == "human"
    assert res.verdict == "human"
    assert called == ["codex", "claude"]
    assert "codex" in res and "claude" in res
    assert "codex" in str(res) and "claude" in str(res)


def test_recovery_second_attempt_in_same_round_never_calls_runner(
    tmp_path: Path,
) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-100",
        }),
        encoding="utf-8",
    )

    recovery.record_attempt(
        repo,
        task="REC-3",
        round=1,
        kind="agent",
        agent="codex",
        verdict="human",
    )

    called = False

    def fake_runner(command, prompt, **kwargs):
        nonlocal called
        called = True
        return "RECOVERY: resolved\n"

    res = recovery.recover(repo, agent="codex", runner=fake_runner)
    assert res == "human"
    assert called is False


def test_recovery_prompt_contents_and_session(tmp_path: Path) -> None:
    from whyline.console.session import ConsoleSession

    repo = _init_scratch_repo(tmp_path / "repo")
    log_file = repo / ".whyline" / "relay" / "logs" / "round.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_lines = "\n".join(f"log line {i}" for i in range(100))
    log_file.write_text(log_lines, encoding="utf-8")

    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": ".whyline/relay/logs/round.log",
            "last_handoff_id": "old-100",
        }),
        encoding="utf-8",
    )
    (repo / ".whyline" / "active-handoff.json").write_text(
        json.dumps({
            "v": 1,
            "id": "old-100",
            "task": "REC-3",
            "status": "in-progress",
        }),
        encoding="utf-8",
    )

    captured_prompt: list[str] = []

    def fake_runner(command, prompt, **kwargs):
        captured_prompt.append(prompt)
        (repo / ".whyline" / "active-handoff.json").write_text(
            json.dumps({
                "v": 1,
                "id": "new-200",
                "task": "REC-3",
                "status": "ready-for-review",
            }),
            encoding="utf-8",
        )
        return "RECOVERY: resolved\n"

    session = ConsoleSession(root=repo, agent="codex")
    res = recovery.recover(session, runner=fake_runner)
    assert res == "resolved"
    assert len(captured_prompt) == 1
    prompt = captured_prompt[0]
    assert "no-handoff" in prompt
    assert "log line 99" in prompt
    assert "log line 20" in prompt
    assert "log line 10\n" not in prompt
    assert "old-100" in prompt
    assert "whyline handoff" in prompt
    assert "RECOVERY: resolved" in prompt
    assert "RECOVERY: needs-human <reason>" in prompt
    assert "must not edit, stage, or commit" in prompt


def test_recovery_turn_that_edits_relay_config_is_human_naming_path(
    tmp_path: Path,
) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-handoff-100",
        }),
        encoding="utf-8",
    )

    relay_cfg = repo / ".whyline" / "relay" / "config.toml"

    def fake_runner(command, prompt, **kwargs):
        relay_cfg.write_text(
            'plan = "plan.md"\n[roles]\nimplementer = "hacked"\n',
            encoding="utf-8",
        )
        (repo / ".whyline" / "active-handoff.json").write_text(
            json.dumps({
                "v": 1,
                "id": "new-handoff-200",
                "task": "REC-3",
                "status": "ready-for-review",
            }),
            encoding="utf-8",
        )
        return "RECOVERY: resolved\n"

    res = recovery.recover(repo, agent="codex", runner=fake_runner)
    assert res == "human"
    assert res.verdict == "human"
    assert ".whyline/relay/config.toml" in res
    assert ".whyline/relay/config.toml" in str(res)
    assert ".whyline/relay/config.toml" in res.paths


def test_recovery_turn_that_creates_relay_file_outside_logs_is_human_naming_path(
    tmp_path: Path,
) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-handoff-100",
        }),
        encoding="utf-8",
    )

    extra_file = repo / ".whyline" / "relay" / "forbidden.txt"

    def fake_runner(command, prompt, **kwargs):
        extra_file.write_text("unauthorized file\n", encoding="utf-8")
        (repo / ".whyline" / "active-handoff.json").write_text(
            json.dumps({
                "v": 1,
                "id": "new-handoff-200",
                "task": "REC-3",
                "status": "ready-for-review",
            }),
            encoding="utf-8",
        )
        return "RECOVERY: resolved\n"

    res = recovery.recover(repo, agent="codex", runner=fake_runner)
    assert res == "human"
    assert res.verdict == "human"
    assert ".whyline/relay/forbidden.txt" in res
    assert ".whyline/relay/forbidden.txt" in str(res)
    assert ".whyline/relay/forbidden.txt" in res.paths


def test_recovery_turn_that_edits_relay_state_json_is_human_naming_path(
    tmp_path: Path,
) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-handoff-100",
        }),
        encoding="utf-8",
    )

    def fake_runner(command, prompt, **kwargs):
        state_file.write_text(
            json.dumps({
                "plan": "hacked.md",
                "branch": "main",
                "task_id": "REC-3",
                "round": 1,
            }),
            encoding="utf-8",
        )
        (repo / ".whyline" / "active-handoff.json").write_text(
            json.dumps({
                "v": 1,
                "id": "new-handoff-200",
                "task": "REC-3",
                "status": "ready-for-review",
            }),
            encoding="utf-8",
        )
        return "RECOVERY: resolved\n"

    res = recovery.recover(repo, agent="codex", runner=fake_runner)
    assert res == "human"
    assert res.verdict == "human"
    assert ".whyline/relay/state.json" in res
    assert ".whyline/relay/state.json" in str(res)
    assert ".whyline/relay/state.json" in res.paths


def test_recovery_resolved_returns_clean_repository_with_committed_note(
    tmp_path: Path,
) -> None:
    import subprocess

    repo = _init_scratch_repo(tmp_path / "repo")
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-handoff-100",
        }),
        encoding="utf-8",
    )
    (repo / ".whyline" / "active-handoff.json").write_text(
        json.dumps({
            "v": 1,
            "id": "old-handoff-100",
            "task": "REC-3",
            "status": "in-progress",
        }),
        encoding="utf-8",
    )

    def fake_runner(command, prompt, **kwargs):
        (repo / ".whyline" / "active-handoff.json").write_text(
            json.dumps({
                "v": 1,
                "id": "new-handoff-200",
                "task": "REC-3",
                "status": "ready-for-review",
                "summary": "Recovered",
            }),
            encoding="utf-8",
        )
        return "RECOVERY: resolved\n"

    res = recovery.recover(repo, agent="codex", runner=fake_runner)
    assert res == "resolved"
    assert res.verdict == "resolved"

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert status.strip() == ""

    msg = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert msg == "chore: record REC-3 decisions"


def test_recovery_session_agent_takes_precedence_over_outside_agent_argument(
    tmp_path: Path,
) -> None:
    from whyline.console.session import ConsoleSession

    repo = _init_scratch_repo(tmp_path / "repo")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "codex"\nreviewer = "claude"\n[backup]\nchain = ["claude"]\n',
        encoding="utf-8",
    )
    import subprocess

    subprocess.run(["git", "commit", "-am", "update config"], cwd=repo, check=True)
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-100",
        }),
        encoding="utf-8",
    )

    called: list[str] = []

    def fake_runner(command, prompt, **kwargs):
        agent_name = kwargs.get("agent_name") or command[0]
        called.append(agent_name)
        (repo / ".whyline" / "active-handoff.json").write_text(
            json.dumps({
                "v": 1,
                "id": "new-200",
                "task": "REC-3",
                "status": "ready-for-review",
            }),
            encoding="utf-8",
        )
        return "RECOVERY: resolved\n"

    session = ConsoleSession(root=repo, agent="codex")
    res = recovery.recover(session, agent="rogue_agent", runner=fake_runner)
    assert res == "resolved"
    assert called == ["codex"]
    attempts = recovery.load_attempts(repo)
    assert len(attempts) == 1
    assert attempts[0]["agent"] == "codex"


def test_recovery_failing_session_agent_falls_to_backup_ignoring_outside_override(
    tmp_path: Path,
) -> None:
    from whyline.console.session import ConsoleSession
    from whyline_relay import agents as relay_agents

    repo = _init_scratch_repo(tmp_path / "repo")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "grok"\nreviewer = "claude"\n[backup]\nchain = ["codex"]\n',
        encoding="utf-8",
    )
    import subprocess

    subprocess.run(["git", "commit", "-am", "update config"], cwd=repo, check=True)
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-100",
        }),
        encoding="utf-8",
    )

    called: list[str] = []

    def fake_runner(command, prompt, **kwargs):
        agent_name = kwargs.get("agent_name") or command[0]
        called.append(agent_name)
        if agent_name == "grok":
            raise relay_agents.AgentMissing("grok missing")
        if agent_name == "codex":
            (repo / ".whyline" / "active-handoff.json").write_text(
                json.dumps({
                    "v": 1,
                    "id": "new-200",
                    "task": "REC-3",
                    "status": "ready-for-review",
                }),
                encoding="utf-8",
            )
            return "RECOVERY: resolved\n"
        raise RuntimeError(f"unexpected outside agent {agent_name}")

    session = ConsoleSession(root=repo, agent="grok")
    res = recovery.recover(session, agent="rogue_agent", runner=fake_runner)
    assert res == "resolved"
    assert called == ["grok", "codex"]
    attempts = recovery.load_attempts(repo)
    assert len(attempts) == 1
    assert attempts[0]["agent"] == "codex"


def test_recovery_exhausted_chain_with_outside_override_reports_only_chain_agents(
    tmp_path: Path,
) -> None:
    from whyline.console.session import ConsoleSession
    from whyline_relay import agents as relay_agents

    repo = _init_scratch_repo(tmp_path / "repo")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "codex"\nreviewer = "claude"\n[backup]\nchain = ["claude"]\n',
        encoding="utf-8",
    )
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-3",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "no-handoff",
            "log_path": "round.log",
            "last_handoff_id": "old-100",
        }),
        encoding="utf-8",
    )

    called: list[str] = []

    def fake_runner(command, prompt, **kwargs):
        agent_name = kwargs.get("agent_name") or command[0]
        called.append(agent_name)
        raise relay_agents.AgentTimeout(f"{agent_name} timed out")

    session = ConsoleSession(root=repo, agent="codex")
    res = recovery.recover(session, agent="rogue_agent", runner=fake_runner)
    assert res == "human"
    assert res.verdict == "human"
    assert called == ["codex", "claude"]
    assert "codex" in res and "claude" in res
    assert "rogue_agent" not in res
    assert "rogue_agent" not in str(res)
    assert res.agents == ["claude", "codex"]


def test_sandbox_pause_is_classified_sandbox_shows_command_and_changes_no_file(tmp_path: Path):
    from whyline.console import adapters

    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4B",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "codex could not run a required command: uv run pytest -q: permission denied",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )
    config_file = tmp_path / ".whyline" / "relay" / "config.toml"
    config_content = '[agents.codex]\ncommand = ["codex", "exec"]\n'
    config_file.write_text(config_content, encoding="utf-8")

    files_before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    reason = "codex could not run a required command: uv run pytest -q: permission denied"
    assert adapters.failure_kind(reason) == "sandbox"
    assert recovery.route("sandbox") == "human"

    event = adapters.classify_relay_output(tmp_path, f"Paused: {reason}", 2)
    assert event.kind == "pause"
    assert "[sandbox]" in event.text
    assert "uv run pytest -q" in event.text
    assert "Command uv run pytest -q" in event.text
    # Adapter for codex has dir flag (--add-dir), so config change is shown
    assert "Config change:" in event.text
    assert "--add-dir" in event.text
    assert "[agents.codex]" in event.text

    # Changes NO file, never edits the config
    files_after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert files_after == files_before
    assert config_file.read_text(encoding="utf-8") == config_content


def test_sandbox_pause_without_dir_flag_shows_command_and_no_config_change(tmp_path: Path):
    from whyline.console import adapters

    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4B",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "aider could not run a required command: pytest: permission denied",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )
    config_file = tmp_path / ".whyline" / "relay" / "config.toml"
    config_content = '[agents.aider]\nadapter = "generic"\ncommand = ["aider"]\n'
    config_file.write_text(config_content, encoding="utf-8")

    files_before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    reason = "aider could not run a required command: pytest: permission denied"
    assert adapters.failure_kind(reason) == "sandbox"

    event = adapters.classify_relay_output(tmp_path, f"Paused: {reason}", 2)
    assert event.kind == "pause"
    assert "[sandbox]" in event.text
    assert "pytest" in event.text
    assert "Command pytest" in event.text
    # Aider has generic adapter with no dir flag, so no config change shown
    assert "Config change:" not in event.text

    files_after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert files_after == files_before


def test_visit_cap_pause_is_classified_visit_cap_and_routes_to_human(tmp_path: Path):
    from whyline.console import adapters

    reason = "TASK-1 hit stage 'review''s 3-visit cap without reaching \"@complete\""
    assert adapters.failure_kind(reason) == "visit-cap"
    assert recovery.route("visit-cap") == "human"

    state_file = tmp_path / ".whyline" / "relay" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "TASK-1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": reason,
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )
    event = adapters.classify_relay_output(tmp_path, f"Paused: {reason}", 2)
    assert event.kind == "pause"
    assert "[visit-cap]" in event.text
    assert "Retry stage: type resume --retry-stage or press Retry stage" in event.text


def test_each_known_problem_diagnosed_with_recommended_option_first(tmp_path: Path, monkeypatch, installed_agents) -> None:
    import subprocess
    from whyline import account
    from whyline_relay import failover, running

    # 1. dirty-log
    repo_log = _init_scratch_repo(tmp_path / "repo_log")
    (repo_log / ".whyline" / "decisions.md").write_text("# Decisions\n- note\n", encoding="utf-8")
    probs = recovery.diagnose(repo_log, ["FAIL  working tree has uncommitted changes: .whyline/decisions.md"], "")
    assert len(probs) == 1
    assert probs[0].id == "dirty-log"
    assert probs[0].options[0].id == "commit-log"
    assert probs[0].options[0].recommended is True
    assert probs[0].options[-2].id == "show"
    assert probs[0].options[-1].id == "cancel"

    # 2. dirty-paused-work
    repo_paused = _init_scratch_repo(tmp_path / "repo_paused")
    (repo_paused / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({"task_id": "REC-1", "paused_reason": "dirty"}), encoding="utf-8"
    )
    (repo_paused / "work.txt").write_text("in progress\n")
    probs = recovery.diagnose(repo_paused, ["FAIL  working tree has uncommitted changes"], "dirty")
    assert probs[0].id == "dirty-paused-work"
    assert probs[0].options[0].id == "resume-keep"
    assert probs[0].options[0].recommended is True
    assert probs[0].options[1].id == "stash"
    assert probs[0].options[1].confirm is True
    assert probs[0].options[-2].id == "show"
    assert probs[0].options[-1].id == "cancel"

    # 3. dirty-other
    repo_other = _init_scratch_repo(tmp_path / "repo_other")
    (repo_other / "untracked.txt").write_text("random\n")
    probs = recovery.diagnose(repo_other, ["FAIL  working tree has uncommitted changes"], "")
    assert probs[0].id == "dirty-other"
    assert probs[0].options[0].id == "stash"
    assert probs[0].options[0].recommended is True
    assert probs[0].options[0].confirm is True
    assert probs[0].options[-2].id == "show"
    assert probs[0].options[-1].id == "cancel"

    # 4. relay-running
    repo_run = _init_scratch_repo(tmp_path / "repo_run")
    running.start_turn(repo_run, "codex", "REC-1", 1, role="implementer")
    try:
        probs = recovery.diagnose(repo_run, ["FAIL  another relay is running here"], "")
        assert probs[0].id == "relay-running"
        assert probs[0].options[0].id == "wait"
        assert probs[0].options[0].recommended is True
        assert probs[0].options[1].id == "stop"
        assert probs[0].options[1].confirm is True
        assert probs[0].options[-2].id == "show"
        assert probs[0].options[-1].id == "cancel"
    finally:
        running.clear(repo_run)

    # 5. head-moved
    repo_head = _init_scratch_repo(tmp_path / "repo_head")
    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_head, capture_output=True, text=True).stdout.strip()
    (repo_head / "src").mkdir(exist_ok=True)
    (repo_head / "src" / "alpha.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo_head, check=True)
    subprocess.run(["git", "commit", "-m", "work: alpha"], cwd=repo_head, check=True)
    (repo_head / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({"task_id": "REC-1", "base_commit": base_sha, "paused_reason": "HEAD moved before the relay could make its own commit"}),
        encoding="utf-8",
    )
    probs = recovery.diagnose(repo_head, [], "REC-1: HEAD moved before the relay could make its own commit; reset to base")
    assert probs[0].id == "head-moved"
    assert probs[0].options[0].id == "reset-keep"
    assert probs[0].options[0].recommended is True
    assert probs[0].options[0].confirm is True
    assert probs[0].options[-2].id == "show"
    assert probs[0].options[-1].id == "cancel"

    # 6. foreign-commits
    repo_fc = _init_scratch_repo(tmp_path / "repo_fc")
    base_fc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_fc, capture_output=True, text=True).stdout.strip()
    (repo_fc / "docs").mkdir(exist_ok=True)
    (repo_fc / "docs" / "brainstorm.md").write_text("doc\n")
    subprocess.run(["git", "add", "-A"], cwd=repo_fc, check=True)
    subprocess.run(["git", "commit", "-m", "brainstorm: initial ideas"], cwd=repo_fc, check=True)
    (repo_fc / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({"task_id": "REC-1", "base_commit": base_fc, "paused_reason": "codex made a commit in stage 'draft'"}),
        encoding="utf-8",
    )
    probs = recovery.diagnose(repo_fc, [], "codex made a commit in stage 'draft', which the relay forbids")
    assert probs[0].id == "foreign-commits"
    assert probs[0].options[0].id == "move-aside"
    assert probs[0].options[0].recommended is True
    assert probs[0].options[0].confirm is True
    assert probs[0].options[1].id == "reset-keep"
    assert probs[0].options[1].confirm is True
    assert probs[0].options[-2].id == "show"
    assert probs[0].options[-1].id == "cancel"

    # 7. sticky-switch
    repo_sticky = _init_scratch_repo(tmp_path / "repo_sticky")
    failover.write_override(
        repo_sticky,
        "implementer",
        failover.ActiveOverride(
            "claude",
            "codex",
            "rate-limit",
            "2026-10-14",
            [],
            resets_at="2020-01-01T00:00:00",
        ),
    )
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"codex": {"available": True, "label": "available", "hint": None}},
    )
    probs = recovery.diagnose(repo_sticky, [], "")
    assert probs[0].id == "sticky-switch"
    assert probs[0].options[0].id == "reset-role"
    assert probs[0].options[0].recommended is True
    assert probs[0].options[-2].id == "show"
    assert probs[0].options[-1].id == "cancel"

    # 8. timeout
    repo_to = _init_scratch_repo(tmp_path / "repo_to")
    probs = recovery.diagnose(repo_to, [], "codex exceeded 1800s and was terminated")
    assert probs[0].id == "timeout"
    assert probs[0].options[0].id == "resume-longer"
    assert probs[0].options[0].recommended is True
    assert probs[0].options[1].id == "resume"
    assert probs[0].options[-2].id == "show"
    assert probs[0].options[-1].id == "cancel"

    # 9. out-of-usage
    repo_usg = _init_scratch_repo(tmp_path / "repo_usg")
    (repo_usg / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "codex"\nreviewer = "claude"\n[backup]\nchain = ["codex"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-am", "update backup chain"], cwd=repo_usg, check=True)
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"codex": {"available": False}, "claude": {"available": False}, "grok": {"available": True}},
    )
    probs = recovery.diagnose(repo_usg, [], "codex hit a usage or rate limit; try again when it resets")
    assert probs[0].id == "out-of-usage"
    assert probs[0].options[0].id == "use-grok"
    assert probs[0].options[0].recommended is True
    assert probs[0].options[-2].id == "show"
    assert probs[0].options[-1].id == "cancel"

    # 10. visit-cap
    repo_vc = _init_scratch_repo(tmp_path / "repo_vc")
    probs = recovery.diagnose(repo_vc, [], "TASK-1 hit stage 'review''s 3-visit cap without reaching \"@complete\"")
    assert probs[0].id == "visit-cap"
    assert probs[0].options[0].id == "retry-stage"
    assert probs[0].options[0].recommended is True
    assert probs[0].options[-2].id == "show"
    assert probs[0].options[-1].id == "cancel"

    # 11. unknown
    repo_unk = _init_scratch_repo(tmp_path / "repo_unk")
    probs = recovery.diagnose(repo_unk, [], "unrecognized glitch occurred")
    assert probs[0].id == "unknown"
    assert probs[0].options[0].id == "ask-agent"
    assert probs[0].options[0].recommended is True
    assert probs[0].options[-2].id == "show"
    assert probs[0].options[-1].id == "cancel"


def test_commit_log_commits_one_file(tmp_path: Path) -> None:
    import subprocess

    repo = _init_scratch_repo(tmp_path / "repo")
    count_before = _commit_count(repo)
    (repo / ".whyline" / "decisions.md").write_text("# Decisions\n- [2026-10-14] new decision\n", encoding="utf-8")
    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({"task_id": "REC-4C", "paused_reason": "dirty"}), encoding="utf-8"
    )

    probs = recovery.diagnose(repo, ["FAIL  working tree has uncommitted changes: .whyline/decisions.md"], "")
    assert probs[0].id == "dirty-log"
    assert probs[0].options[0].id == "commit-log"

    launched: list[list[str]] = []
    res = recovery.apply(repo, probs[0], "commit-log", launched.append)

    assert _commit_count(repo) == count_before + 1
    assert "Committed decision log" in res
    assert _last_commit_message(repo) == "chore: record REC-4C decisions"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True).stdout
    assert status.strip() == ""
    assert launched == []


def test_stash_leaves_clean_tree_and_named_stash(tmp_path: Path) -> None:
    import subprocess

    repo = _init_scratch_repo(tmp_path / "repo")
    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({"task_id": "REC-4C", "paused_reason": "dirty"}), encoding="utf-8"
    )
    (repo / "dirty_code.py").write_text("print('dirty')\n", encoding="utf-8")

    probs = recovery.diagnose(repo, ["FAIL  working tree has uncommitted changes"], "dirty")
    assert probs[0].id == "dirty-paused-work"

    launched: list[list[str]] = []
    res = recovery.apply(repo, probs[0], "stash", launched.append)

    assert "Stashed uncommitted changes" in res
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True).stdout
    assert status.strip() == ""
    stashes = subprocess.run(["git", "stash", "list"], cwd=repo, capture_output=True, text=True, check=True).stdout
    assert "whyline resolve REC-4C" in stashes
    assert launched == []


def test_resume_keep_calls_launch_and_nothing_else(tmp_path: Path) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({"task_id": "REC-4C", "paused_reason": "dirty"}), encoding="utf-8"
    )
    (repo / "dirty_code.py").write_text("print('dirty')\n", encoding="utf-8")

    probs = recovery.diagnose(repo, ["FAIL  working tree has uncommitted changes"], "dirty")
    assert probs[0].id == "dirty-paused-work"

    launched: list[list[str]] = []
    res = recovery.apply(repo, probs[0], "resume-keep", launched.append)

    assert launched == [["resume", "--allow-dirty"]]
    assert "Resumed relay with uncommitted changes kept" in res
    assert (repo / "dirty_code.py").is_file()


def test_head_moved_lists_commits_and_their_files(tmp_path: Path) -> None:
    import subprocess

    repo = _init_scratch_repo(tmp_path / "repo")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "alpha.py").write_text("alpha = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "work: commit alpha"], cwd=repo, check=True)

    (repo / "src" / "beta.py").write_text("beta = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "work: commit beta"], cwd=repo, check=True)

    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "task_id": "REC-4C",
            "base_commit": base,
            "paused_reason": "REC-4C: HEAD moved before the relay could make its own commit; reset to base",
        }),
        encoding="utf-8",
    )

    probs = recovery.diagnose(repo, [], "REC-4C: HEAD moved before the relay could make its own commit; reset to base")
    assert probs[0].id == "head-moved"

    evidence_text = "\n".join(probs[0].evidence)
    assert "work: commit alpha" in evidence_text
    assert "work: commit beta" in evidence_text
    assert "alpha.py" in evidence_text
    assert "beta.py" in evidence_text

    detail = probs[0].options[0].detail
    assert "src/alpha.py" in detail
    assert "src/beta.py" in detail

    launched: list[list[str]] = []
    res = recovery.apply(repo, probs[0], "reset-keep", launched.append)
    assert launched == [["resume", "--allow-dirty"]]
    current_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    assert current_head == base
    assert (repo / "src" / "alpha.py").read_text(encoding="utf-8") == "alpha = 1\n"
    assert (repo / "src" / "beta.py").read_text(encoding="utf-8") == "beta = 2\n"


def test_foreign_commits_move_aside_and_src_touch_makes_head_moved(tmp_path: Path) -> None:
    import subprocess

    repo = _init_scratch_repo(tmp_path / "repo")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    (repo / "docs").mkdir(exist_ok=True)

    for i in range(1, 4):
        (repo / "docs" / f"brainstorm_{i}.md").write_text(f"draft {i}\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", f"brainstorm: pass {i}"], cwd=repo, check=True)

    # Task's dirty uncommitted work
    (repo / "task_work.txt").write_text("uncommitted work\n", encoding="utf-8")

    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "task_id": "REC-4C",
            "base_commit": base,
            "paused_reason": "codex made a commit in stage 'draft', which the relay forbids",
        }),
        encoding="utf-8",
    )

    probs = recovery.diagnose(repo, [], "codex made a commit in stage 'draft', which the relay forbids")
    assert probs[0].id == "foreign-commits"
    assert probs[0].options[0].id == "move-aside"
    assert probs[0].options[0].recommended is True
    assert probs[0].options[0].confirm is True
    assert probs[0].options[1].id == "reset-keep"

    launched: list[list[str]] = []
    res = recovery.apply(repo, probs[0], "move-aside", launched.append)

    # Move-aside leaves them on branch and HEAD at base with dirty files intact
    current_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    assert current_head == base
    assert (repo / "task_work.txt").read_text(encoding="utf-8") == "uncommitted work\n"
    assert launched == [["resume", "--allow-dirty"]]

    branches = subprocess.run(["git", "branch"], cwd=repo, capture_output=True, text=True, check=True).stdout
    assert "whyline-aside/REC-4C-" in branches

    # One commit touching src/ makes it head-moved
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "feature.py").write_text("touch = True\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/feature.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "brainstorm: touches src"], cwd=repo, check=True)

    probs2 = recovery.diagnose(repo, [], "codex made a commit in stage 'draft', which the relay forbids")
    assert probs2[0].id == "head-moved"
    assert probs2[0].options[0].id == "reset-keep"
    launched2: list[list[str]] = []
    recovery.apply(repo, probs2[0], "reset-keep", launched2.append)
    assert launched2 == [["resume", "--allow-dirty"]]


def test_timeout_steps_30_to_45_45_to_60_and_60_to_none(tmp_path: Path) -> None:
    from whyline.console import relay_ops

    repo = _init_scratch_repo(tmp_path / "repo")
    relay_ops.save_timeout(repo, 30)
    assert relay_ops.relay_timeout(repo) == 30

    # Step 1: 30 to 45
    probs = recovery.diagnose(repo, [], "codex exceeded 1800s and was terminated")
    assert probs[0].id == "timeout"
    assert probs[0].options[0].id == "resume-longer"
    launched: list[list[str]] = []
    recovery.apply(repo, probs[0], "resume-longer", launched.append)
    assert relay_ops.relay_timeout(repo) == 45
    assert launched == [["resume"]]

    # Step 2: 45 to 60
    probs = recovery.diagnose(repo, [], "codex exceeded 2700s and was terminated")
    assert probs[0].id == "timeout"
    launched = []
    recovery.apply(repo, probs[0], "resume-longer", launched.append)
    assert relay_ops.relay_timeout(repo) == 60
    assert launched == [["resume"]]

    # Step 3: 60 to none (0)
    probs = recovery.diagnose(repo, [], "codex exceeded 3600s and was terminated")
    assert probs[0].id == "timeout"
    launched = []
    recovery.apply(repo, probs[0], "resume-longer", launched.append)
    assert relay_ops.relay_timeout(repo) == 0
    assert launched == [["resume"]]


def test_timeout_offers_longer_timeout_or_another_agent(
    tmp_path: Path, monkeypatch, installed_agents
) -> None:
    import subprocess
    from whyline import account

    repo = _init_scratch_repo(tmp_path / "repo")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n'
        "[agents.antigravity]\n"
        'adapter = "generic"\n'
        'command = ["agy", "-p"]\n'
        "[roles]\n"
        'implementer = "antigravity"\n'
        'reviewer = "codex"\n'
        "[backup]\n"
        'chain = ["grok"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-qam", "antigravity implements"], cwd=repo, check=True)
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {
            "antigravity": {"available": True},
            "claude": {"available": False},
            "codex": {"available": True},
            "grok": {"available": True},
        },
    )

    probs = recovery.diagnose(repo, [], "agy exceeded 3600s and was terminated")
    assert probs[0].id == "timeout"
    option_ids = [opt.id for opt in probs[0].options]
    # Longer timeout stays the recommendation; the backup chain comes first
    # among the switches, the timed-out agent and logged-out agents are absent.
    assert option_ids == [
        "resume-longer", "use-grok", "use-codex", "resume", "show", "cancel"
    ]
    assert probs[0].options[0].recommended is True
    assert not any(opt.recommended for opt in probs[0].options[1:])
    assert probs[0].options[1].label == "Use grok instead of antigravity"

    launched: list[list[str]] = []
    res = recovery.apply(repo, probs[0], "use-grok", launched.append)
    assert launched == [["resume"]]
    assert "Set role implementer to grok" in res
    cfg_text = (repo / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")
    assert 'implementer = "grok"' in cfg_text


def test_no_handoff_with_quota_text_offers_another_agent(
    tmp_path: Path, monkeypatch, installed_agents
) -> None:
    import subprocess
    from whyline import account

    repo = _init_scratch_repo(tmp_path / "repo")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n'
        "[agents.antigravity]\n"
        'adapter = "generic"\n'
        'command = ["agy", "-p"]\n'
        "[roles]\n"
        'implementer = "antigravity"\n'
        'reviewer = "codex"\n'
        "[backup]\n"
        'chain = ["grok"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-qam", "antigravity implements"], cwd=repo, check=True)
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {
            "antigravity": {"available": True},
            "codex": {"available": True},
            "grok": {"available": True},
        },
    )

    # The pause a relay older than 0.2.38 wrote for antigravity's 429.
    reason = (
        'antigravity exited without handing off; its last output was: '
        '"{"status":"ERROR","response":"","error":"Individual quota reached. '
        'Please upgrade your subscription to "; nothing was routed'
    )
    probs = recovery.diagnose(repo, [], reason)
    assert probs[0].id == "out-of-usage"
    assert "antigravity is out of quota" in probs[0].summary
    option_ids = [opt.id for opt in probs[0].options]
    assert option_ids == ["use-grok", "use-codex", "show", "cancel"]
    assert probs[0].options[0].recommended is True

    launched: list[list[str]] = []
    recovery.apply(repo, probs[0], "use-grok", launched.append)
    assert launched == [["resume"]]
    cfg_text = (repo / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")
    assert 'implementer = "grok"' in cfg_text

    # A no-handoff without quota text stays an ordinary no-handoff.
    plain = recovery.diagnose(repo, [], "antigravity exited without handing off; nothing was routed")
    assert all(p.id != "out-of-usage" for p in plain)


def test_out_of_usage_offers_only_usable_agents(tmp_path: Path, monkeypatch, installed_agents) -> None:
    import subprocess
    from whyline import account
    from whyline_relay import failover

    repo = _init_scratch_repo(tmp_path / "repo")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "codex"\nreviewer = "claude"\n[backup]\nchain = ["codex", "claude", "grok"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-am", "update backup chain"], cwd=repo, check=True)

    failover.write_override(
        repo,
        "implementer",
        failover.ActiveOverride(
            agent="codex",
            backup_for="codex",
            reason="rate-limit",
            since="2026-10-14T10:00:00Z",
            tried=["claude", "grok"],
        ),
    )

    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {
            "codex": {"available": False},
            "claude": {"available": False},
            "grok": {"available": True},
        },
    )

    probs = recovery.diagnose(repo, [], "codex hit a usage or rate limit; try again when it resets")
    assert probs[0].id == "out-of-usage"
    option_ids = [opt.id for opt in probs[0].options]
    assert "use-grok" in option_ids
    assert "use-claude" not in option_ids
    assert "use-codex" not in option_ids
    assert probs[0].options[0].id == "use-grok"
    assert probs[0].options[0].recommended is True

    launched: list[list[str]] = []
    res = recovery.apply(repo, probs[0], "use-grok", launched.append)
    assert launched == [["resume"]]
    assert "Set role implementer to grok" in res
    cfg_text = (repo / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")
    assert 'implementer = "grok"' in cfg_text


def test_out_of_usage_configured_pipeline_updates_mapped_role_and_resumes(
    tmp_path: Path, monkeypatch, installed_agents) -> None:
    import subprocess
    from whyline import account
    from whyline_relay import failover

    repo = _init_scratch_repo(tmp_path / "repo")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        """plan = "plan.md"

[roles]
implementer = "codex"
tester = "claude"
reviewer = "claude"

[pipeline]
default_profile = "full"

[pipeline.profiles]
full = ["draft", "test", "review"]

[pipeline.stages.draft]
role = "implementer"
prompt = "implement"

[pipeline.stages.draft.on]
ready = "@next"

[pipeline.stages.test]
role = "tester"
prompt = "test"

[pipeline.stages.test.on]
passed = "@next"
failed = "draft"

[pipeline.stages.review]
role = "reviewer"
prompt = "review"

[pipeline.stages.review.on]
approved = "@complete"
rejected = "draft"

[backup]
chain = ["codex", "claude"]
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-am", "configure pipeline"], cwd=repo, check=True)

    # Paused at stage 'draft', mapped to role 'implementer'
    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4C",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "codex hit a usage or rate limit; try again when it resets",
            "log_path": "round.log",
            "stage": "draft",
            "profile": "full",
        }),
        encoding="utf-8",
    )

    failover.write_override(
        repo,
        "implementer",
        failover.ActiveOverride(
            agent="codex",
            backup_for="codex",
            reason="rate-limit",
            since="2026-10-14T10:00:00Z",
            tried=["claude"],
        ),
    )

    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {
            "codex": {"available": False},
            "claude": {"available": False},
            "grok": {"available": True},
        },
    )

    probs = recovery.diagnose(repo, [], "codex hit a usage or rate limit; try again when it resets")
    assert probs[0].id == "out-of-usage"
    assert probs[0].options[0].id == "use-grok"
    assert probs[0].options[0].detail == "whyline relay roles set implementer grok, then resume"

    launched: list[list[str]] = []
    res = recovery.apply(repo, probs[0], "use-grok", launched.append)
    assert launched == [["resume"]]
    assert "Set role implementer to grok" in res
    cfg_text = (repo / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")
    assert 'implementer = "grok"' in cfg_text

    # Paused at stage 'test', mapped to role 'tester'
    repo_test = _init_scratch_repo(tmp_path / "repo_test")
    (repo_test / ".whyline" / "relay" / "config.toml").write_text(
        """plan = "plan.md"

[roles]
implementer = "codex"
tester = "claude"
reviewer = "claude"

[pipeline]
default_profile = "full"

[pipeline.profiles]
full = ["draft", "test", "review"]

[pipeline.stages.draft]
role = "implementer"
prompt = "implement"

[pipeline.stages.draft.on]
ready = "@next"

[pipeline.stages.test]
role = "tester"
prompt = "test"

[pipeline.stages.test.on]
passed = "@next"
failed = "draft"

[pipeline.stages.review]
role = "reviewer"
prompt = "review"

[pipeline.stages.review.on]
approved = "@complete"
rejected = "draft"

[backup]
chain = ["codex", "claude"]
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-am", "configure pipeline"], cwd=repo_test, check=True)

    (repo_test / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4C",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "claude hit a usage or rate limit; try again when it resets",
            "log_path": "round.log",
            "stage": "test",
            "profile": "full",
        }),
        encoding="utf-8",
    )
    failover.write_override(
        repo_test,
        "tester",
        failover.ActiveOverride(
            agent="claude",
            backup_for="claude",
            reason="rate-limit",
            since="2026-10-14T10:00:00Z",
            tried=["codex"],
        ),
    )
    probs_test = recovery.diagnose(repo_test, [], "claude hit a usage or rate limit; try again when it resets")
    assert probs_test[0].id == "out-of-usage"
    assert probs_test[0].options[0].id == "use-grok"
    assert probs_test[0].options[0].detail == "whyline relay roles set tester grok, then resume"

    launched_test: list[list[str]] = []
    res_test = recovery.apply(repo_test, probs_test[0], "use-grok", launched_test.append)
    assert launched_test == [["resume"]]
    assert "Set role tester to grok" in res_test
    cfg_text_test = (repo_test / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")
    assert 'tester = "grok"' in cfg_text_test


def test_unrecognised_reason_is_unknown(tmp_path: Path) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    probs = recovery.diagnose(repo, [], "a completely unrecognized error message happened")
    assert probs[0].id == "unknown"
    assert probs[0].options[0].id == "ask-agent"
    assert probs[0].options[0].recommended is True
    assert probs[0].options[-2].id == "show"
    assert probs[0].options[-1].id == "cancel"


def test_apply_with_unoffered_option_raises_value_error(tmp_path: Path) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    probs = recovery.diagnose(repo, [], "a completely unrecognized error message happened")
    assert probs[0].id == "unknown"
    with pytest.raises(ValueError, match="not offered"):
        recovery.apply(repo, probs[0], "nonexistent-option", lambda cmd: None)


def test_build_ask_agent_prompt_holds_all_required_sections(tmp_path: Path) -> None:
    repo = _init_scratch_repo(tmp_path / "repo")
    log_dir = repo / ".whyline" / "relay" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4E",
            "round": 1,
            "paused_reason": "an unclassified pause reason",
            "log_path": ".whyline/relay/logs/round-REC-4E-1.log",
        }),
        encoding="utf-8",
    )
    round_log = log_dir / "round-REC-4E-1.log"
    round_log.write_text("\n".join(f"log line {i}" for i in range(100)) + "\n", encoding="utf-8")

    (repo / "dirty_test.txt").write_text("modified\n", encoding="utf-8")

    prompt = recovery.build_ask_agent_prompt(
        repo,
        fail_lines=["FAIL preflight failed"],
        pause_reason="an unclassified pause reason",
        round_log="\n".join(f"log line {i}" for i in range(20, 100)),
        relay_status="whyline relay status output",
        git_status="?? dirty_test.txt",
    )

    assert "an unclassified pause reason" in prompt
    assert "FAIL preflight failed" in prompt
    assert "log line 99" in prompt
    assert "log line 19" not in prompt
    assert "whyline relay status output" in prompt
    assert "?? dirty_test.txt" in prompt
    for opt_id in recovery.REC_4C_OPTIONS:
        assert opt_id in prompt
    assert "You must not edit, stage, or commit anything." in prompt
    assert "EXPLANATION: <one paragraph>" in prompt
    assert "RECOMMEND: <option id>" in prompt
    assert "RECOMMEND: human" in prompt


def test_ask_agent_recommendation_of_listed_id(tmp_path: Path) -> None:
    from whyline.console.session import ConsoleSession

    repo = _init_scratch_repo(tmp_path / "repo")

    def fake_runner(command, prompt, **kwargs):
        return (
            "I checked the issue.\n"
            "EXPLANATION: Dirty changes need to be stashed away.\n"
            "RECOMMEND: stash\n"
        )

    session = ConsoleSession(root=repo, agent="codex")
    res = recovery.ask_agent(session, runner=fake_runner)

    assert res.status == "recommended"
    assert res.recommendation == "stash"
    assert res.explanation == "Dirty changes need to be stashed away."
    assert res.agent == "codex"
    assert res.option is not None
    assert res.option.id == "stash"
    assert res.option.recommended is True
    assert res.option.confirm is True


def test_ask_agent_reads_the_log_when_the_run_result_has_no_output(tmp_path: Path) -> None:
    from types import SimpleNamespace
    from whyline.console.session import ConsoleSession

    repo = _init_scratch_repo(tmp_path / "repo")

    # whyline_relay.agents.run streams the reply to log_path and returns
    # RunResult(exit_code=0, output=None); the repr is not the reply.
    def fake_runner(command, prompt, **kwargs):
        kwargs["log_path"].write_text(
            "codex\nEXPLANATION: Dirty changes need to be stashed away.\n"
            "RECOMMEND: stash\ntokens used\n",
            encoding="utf-8",
        )
        return SimpleNamespace(exit_code=0, output=None)

    session = ConsoleSession(root=repo, agent="codex")
    res = recovery.ask_agent(session, runner=fake_runner)

    assert res.status == "recommended"
    assert res.recommendation == "stash"
    assert res.explanation == "Dirty changes need to be stashed away."


def test_ask_agent_unlisted_id_ignored_and_reported(tmp_path: Path) -> None:
    from whyline.console.session import ConsoleSession

    repo = _init_scratch_repo(tmp_path / "repo")

    def fake_runner(command, prompt, **kwargs):
        return (
            "EXPLANATION: Unlisted action.\n"
            "RECOMMEND: reboot-machine\n"
        )

    session = ConsoleSession(root=repo, agent="codex")
    res = recovery.ask_agent(session, runner=fake_runner)

    assert res.status == "unlisted"
    assert res.recommendation == "reboot-machine"
    assert res.explanation == "Unlisted action."
    assert res.option is None


def test_ask_agent_turn_that_edits_file_discarded_and_names_file(tmp_path: Path) -> None:
    from whyline.console.session import ConsoleSession

    repo = _init_scratch_repo(tmp_path / "repo")

    def fake_runner(command, prompt, **kwargs):
        (repo / "sneaky_edit.txt").write_text("evil\n", encoding="utf-8")
        return (
            "EXPLANATION: Everything is fine.\n"
            "RECOMMEND: stash\n"
        )

    session = ConsoleSession(root=repo, agent="codex")
    res = recovery.ask_agent(session, runner=fake_runner)

    assert res.status == "modified"
    assert "sneaky_edit.txt" in res.changed_paths
    assert res.recommendation == ""
    assert res.option is None


def test_ask_agent_failing_selected_agent_falls_through_to_backup(tmp_path: Path) -> None:
    from whyline.console.session import ConsoleSession
    from whyline_relay import agents as relay_agents

    repo = _init_scratch_repo(tmp_path / "repo")
    # backup chain in repo config has reviewer = claude, backup_chain = ["claude"]
    relay_cfg = repo / ".whyline" / "relay" / "config.toml"
    relay_cfg.write_text(
        'plan = "plan.md"\n[backup]\nchain = ["claude"]\n[roles]\nimplementer = "grok"\nreviewer = "claude"\n',
        encoding="utf-8",
    )

    called: list[str] = []

    def fake_runner(command, prompt, **kwargs):
        agent_name = kwargs.get("agent_name") or command[0]
        called.append(agent_name)
        if agent_name == "grok":
            raise relay_agents.AgentMissing("grok missing")
        if agent_name == "claude":
            return (
                "EXPLANATION: Claude solved it.\n"
                "RECOMMEND: commit-log\n"
            )
        raise RuntimeError(f"unexpected agent {agent_name}")

    session = ConsoleSession(root=repo, agent="grok")
    res = recovery.ask_agent(session, runner=fake_runner)

    assert res.status == "recommended"
    assert res.recommendation == "commit-log"
    assert res.agent == "claude"
    assert called == ["grok", "claude"]
    assert res.option is not None
    assert res.option.id == "commit-log"


def test_ask_agent_recommend_human_and_exhausted(tmp_path: Path) -> None:
    from whyline.console.session import ConsoleSession
    from whyline_relay import agents as relay_agents

    repo = _init_scratch_repo(tmp_path / "repo")

    # 1. human recommendation
    def fake_human_runner(command, prompt, **kwargs):
        return (
            "EXPLANATION: Need human help.\n"
            "RECOMMEND: human\n"
        )

    session = ConsoleSession(root=repo, agent="codex")
    res_human = recovery.ask_agent(session, runner=fake_human_runner)
    assert res_human.status == "human"
    assert res_human.recommendation == "human"
    assert res_human.explanation == "Need human help."

    # 2. exhausted chain
    def fake_fail_runner(command, prompt, **kwargs):
        raise relay_agents.AgentTimeout("timed out")

    res_ex = recovery.ask_agent(session, runner=fake_fail_runner)
    assert res_ex.status == "exhausted"
    assert "codex" in res_ex.agents_tried


def test_ask_agent_opt_prefixed_id_is_treated_as_unlisted(tmp_path: Path) -> None:
    from whyline.console.session import ConsoleSession

    repo = _init_scratch_repo(tmp_path / "repo")

    def fake_runner(command, prompt, **kwargs):
        return (
            "EXPLANATION: Agent mistakenly prefixed option with opt-.\n"
            "RECOMMEND: opt-stash\n"
        )

    session = ConsoleSession(root=repo, agent="codex")
    res = recovery.ask_agent(session, runner=fake_runner)

    assert res.status == "unlisted"
    assert res.recommendation == "opt-stash"
    assert res.option is None


def test_make_rec_4c_option_resolves_real_configured_role(tmp_path: Path) -> None:
    from whyline_relay import failover as relay_failover

    repo = _init_scratch_repo(tmp_path / "repo")
    relay_cfg = repo / ".whyline" / "relay" / "config.toml"
    relay_cfg.parent.mkdir(parents=True, exist_ok=True)
    relay_cfg.write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "codex"\nreviewer = "claude"\n',
        encoding="utf-8",
    )

    # 1. Synthesized reset-role with no overrides resolves configured role (implementer)
    opt_reset = recovery.make_rec_4c_option("reset-role", root=repo)
    assert "<role>" not in opt_reset.detail
    assert opt_reset.detail == "whyline relay roles reset implementer"
    assert opt_reset.label == "Reset implementer"

    # 2. Synthesized reset-role with override on reviewer resolves reviewer
    ov = relay_failover.ActiveOverride(
        agent="gemini",
        reason="usage",
        backup_for="claude",
        since="2026-10-14T00:00:00",
        tried=["claude"],
    )
    relay_failover.write_override(repo, "reviewer", ov)
    opt_reset_ov = recovery.make_rec_4c_option("reset-role", root=repo)
    assert "<role>" not in opt_reset_ov.detail
    assert opt_reset_ov.detail == "whyline relay roles reset reviewer"
    assert opt_reset_ov.label == "Reset reviewer"

    # 3. Synthesized use-<agent> resolves configured role (implementer)
    opt_use = recovery.make_rec_4c_option("use-claude", root=repo)
    assert "<role>" not in opt_use.detail
    assert opt_use.detail == "whyline relay roles set implementer claude, then resume"
    assert opt_use.label == "Use claude"


def test_apply_synthesized_role_options(tmp_path: Path) -> None:
    from whyline_relay import (
        config as relay_config,
        failover as relay_failover,
        roles as relay_roles,
    )

    repo = _init_scratch_repo(tmp_path / "repo")
    relay_cfg = repo / ".whyline" / "relay" / "config.toml"
    relay_cfg.parent.mkdir(parents=True, exist_ok=True)
    relay_cfg.write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "codex"\nreviewer = "claude"\n',
        encoding="utf-8",
    )

    # Active override on implementer
    ov = relay_failover.ActiveOverride(
        agent="claude",
        reason="usage",
        backup_for="codex",
        since="2026-10-14T00:00:00",
        tried=["codex"],
    )
    relay_failover.write_override(repo, "implementer", ov)
    assert "implementer" in relay_failover.read_overrides(repo)

    # Reset role option
    opt_reset = recovery.make_rec_4c_option("reset-role", root=repo)
    problem_reset = recovery.Problem(
        id="unknown",
        summary="Unknown issue",
        evidence=[],
        options=[
            opt_reset,
            recovery.Option("show", "Show", "print evidence", recommended=False, confirm=False),
            recovery.Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
        ],
    )
    launched: list[list[str]] = []
    res_msg = recovery.apply(
        repo,
        problem_reset,
        "reset-role",
        launch=lambda args: launched.append(args),
    )
    assert "Reset role implementer" in res_msg
    assert "implementer" not in relay_failover.read_overrides(repo)

    # Use agent option
    opt_use = recovery.make_rec_4c_option("use-claude", root=repo)
    problem_use = recovery.Problem(
        id="unknown",
        summary="Unknown issue",
        evidence=[],
        options=[
            opt_use,
            recovery.Option("show", "Show", "print evidence", recommended=False, confirm=False),
            recovery.Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
        ],
    )
    res_use_msg = recovery.apply(
        repo,
        problem_use,
        "use-claude",
        launch=lambda args: launched.append(args),
    )
    assert "Set role implementer to claude and resumed relay." in res_use_msg
    settings = relay_config.load(repo)
    assert relay_roles.current_roles(settings)["implementer"] == "claude"
    assert launched == [["resume"]]


def test_synthesized_role_options_legacy_round_2(tmp_path: Path) -> None:
    from whyline_relay import (
        config as relay_config,
        failover as relay_failover,
        roles as relay_roles,
        state as relay_state,
    )

    repo = _init_scratch_repo(tmp_path / "repo")
    relay_cfg = repo / ".whyline" / "relay" / "config.toml"
    relay_cfg.parent.mkdir(parents=True, exist_ok=True)
    relay_cfg.write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "codex"\nreviewer = "codex"\n',
        encoding="utf-8",
    )

    # Legacy RelayState with empty stage and round=2
    relay_state.save(
        repo,
        relay_state.RelayState(
            plan="plan.md",
            branch="main",
            task_id="REC-4E",
            round=2,
            base_commit="HEAD~1",
            paused_reason="unknown problem",
            log_path="",
            stage="",
        ),
    )

    # 1. Make coverage: verify synthesized options select reviewer
    opt_use = recovery.make_rec_4c_option("use-claude", root=repo)
    assert "<role>" not in opt_use.detail
    assert opt_use.label == "Use claude"
    assert opt_use.detail == "whyline relay roles set reviewer claude, then resume"

    opt_reset = recovery.make_rec_4c_option("reset-role", root=repo)
    assert "<role>" not in opt_reset.detail
    assert opt_reset.label == "Reset reviewer"
    assert opt_reset.detail == "whyline relay roles reset reviewer"

    # 2. Apply coverage for use-<agent>: reviewer changes while implementer is untouched
    problem_use = recovery.Problem(
        id="unknown",
        summary="Unknown issue",
        evidence=[],
        options=[
            opt_use,
            recovery.Option("show", "Show", "print evidence", recommended=False, confirm=False),
            recovery.Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
        ],
    )
    launched: list[list[str]] = []
    res_use_msg = recovery.apply(
        repo,
        problem_use,
        "use-claude",
        launch=lambda args: launched.append(args),
    )
    assert res_use_msg == "Set role reviewer to claude and resumed relay."
    settings = relay_config.load(repo)
    current = relay_roles.current_roles(settings)
    assert current["reviewer"] == "claude"
    assert current["implementer"] == "codex"
    assert launched == [["resume"]]

    # 3. Apply coverage for reset-role: reviewer override reset while implementer is untouched
    ov_reviewer = relay_failover.ActiveOverride(
        agent="claude",
        reason="usage",
        backup_for="codex",
        since="2026-10-14T00:00:00",
        tried=["codex"],
    )
    relay_failover.write_override(repo, "reviewer", ov_reviewer)
    ov_implementer = relay_failover.ActiveOverride(
        agent="claude",
        reason="usage",
        backup_for="codex",
        since="2026-10-14T00:00:00",
        tried=["codex"],
    )
    relay_failover.write_override(repo, "implementer", ov_implementer)
    assert "reviewer" in relay_failover.read_overrides(repo)
    assert "implementer" in relay_failover.read_overrides(repo)

    problem_reset = recovery.Problem(
        id="unknown",
        summary="Unknown issue",
        evidence=[],
        options=[
            opt_reset,
            recovery.Option("show", "Show", "print evidence", recommended=False, confirm=False),
            recovery.Option("cancel", "Cancel", "cancel resolve", recommended=False, confirm=False),
        ],
    )
    launched.clear()
    res_reset_msg = recovery.apply(
        repo,
        problem_reset,
        "reset-role",
        launch=lambda args: launched.append(args),
    )
    assert res_reset_msg == "Reset role reviewer to its configured agent."
    active_overrides = relay_failover.read_overrides(repo)
    assert "reviewer" not in active_overrides
    assert "implementer" in active_overrides


def test_auto_option_returns_recommended_unconfirmed_and_none_for_confirm_unknown_or_human() -> None:
    # 1. Unknown returns None
    prob_unknown = recovery.Problem(
        id="unknown",
        summary="Mysterious pause",
        evidence=[],
        options=[
            recovery.Option("ask-agent", "Ask agent", "ask agent", recommended=True, confirm=False),
        ],
    )
    assert recovery.auto_option(prob_unknown) is None

    # 2. REC-1 human kinds return None
    for hk in ("auth", "blocked", "round-cap", "release", "sandbox", "visit-cap", "other"):
        prob_human = recovery.Problem(
            id=hk,
            summary=f"Human problem {hk}",
            evidence=[],
            options=[
                recovery.Option("dummy", "Dummy", "dummy", recommended=True, confirm=False),
            ],
        )
        assert recovery.auto_option(prob_human) is None

    # 3. Summary mapping to human returns None
    prob_auth_summary = recovery.Problem(
        id="custom-auth",
        summary="codex is no longer logged in",
        evidence=[],
        options=[
            recovery.Option("dummy", "Dummy", "dummy", recommended=True, confirm=False),
        ],
    )
    assert recovery.auto_option(prob_auth_summary) is None

    # 4. Any option with confirm=True returns None (stash, reset, move-aside, stop)
    prob_foreign = recovery.Problem(
        id="foreign-commits",
        summary="Foreign commits",
        evidence=[],
        options=[
            recovery.Option("move-aside", "Move aside", "git branch", recommended=True, confirm=True),
            recovery.Option("reset-keep", "Reset to base", "git reset", recommended=False, confirm=True),
        ],
    )
    assert recovery.auto_option(prob_foreign) is None

    prob_stash = recovery.Problem(
        id="dirty-other",
        summary="Uncommitted paths",
        evidence=[],
        options=[
            recovery.Option("stash", "Stash changes", "git stash", recommended=True, confirm=True),
        ],
    )
    assert recovery.auto_option(prob_stash) is None

    prob_head_moved = recovery.Problem(
        id="head-moved",
        summary="HEAD moved",
        evidence=[],
        options=[
            recovery.Option("reset-keep", "Reset to base commit", "git reset", recommended=True, confirm=True),
        ],
    )
    assert recovery.auto_option(prob_head_moved) is None

    # 5. Allowed auto options return the recommended option
    prob_log = recovery.Problem(
        id="dirty-log",
        summary="Decisions log only",
        evidence=[".whyline/decisions.md"],
        options=[
            recovery.Option("commit-log", "Commit decision log", "commit", recommended=True, confirm=False),
            recovery.Option("show", "Show", "show", recommended=False, confirm=False),
        ],
    )
    assert recovery.auto_option(prob_log) == prob_log.options[0]

    prob_paused_work = recovery.Problem(
        id="dirty-paused-work",
        summary="Uncommitted changes during paused task",
        evidence=["file.py"],
        options=[
            recovery.Option("resume-keep", "Resume and keep", "resume --allow-dirty", recommended=True, confirm=False),
            recovery.Option("stash", "Stash", "stash", recommended=False, confirm=True),
        ],
    )
    assert recovery.auto_option(prob_paused_work) == prob_paused_work.options[0]

    prob_timeout = recovery.Problem(
        id="timeout",
        summary="Agent exceeded 1800s timeout",
        evidence=[],
        options=[
            recovery.Option("resume-longer", "Resume with longer timeout (45m)", "timeout 45", recommended=True, confirm=False),
            recovery.Option("resume", "Resume as is", "resume", recommended=False, confirm=False),
        ],
    )
    assert recovery.auto_option(prob_timeout) == prob_timeout.options[0]

    prob_sticky = recovery.Problem(
        id="sticky-switch",
        summary="Role on backup, original logged in",
        evidence=[],
        options=[
            recovery.Option("reset-role", "Reset role", "roles reset", recommended=True, confirm=False),
        ],
    )
    assert recovery.auto_option(prob_sticky) == prob_sticky.options[0]

    prob_usage = recovery.Problem(
        id="out-of-usage",
        summary="Rate limit hit",
        evidence=[],
        options=[
            recovery.Option("use-claude", "Use claude", "roles set", recommended=True, confirm=False),
        ],
    )
    assert recovery.auto_option(prob_usage) == prob_usage.options[0]

    prob_running = recovery.Problem(
        id="relay-running",
        summary="Relay is currently running",
        evidence=[],
        options=[
            recovery.Option("wait", "Wait", "status", recommended=True, confirm=False),
            recovery.Option("stop", "Stop", "stop", recommended=False, confirm=True),
        ],
    )
    assert recovery.auto_option(prob_running) == prob_running.options[0]


def test_sticky_switch_from_antigravity_is_not_offered_reset_role(
    tmp_path: Path, monkeypatch
) -> None:
    from whyline import account
    from whyline_relay import failover

    repo = _init_scratch_repo(tmp_path / "repo_agy")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "antigravity"\nreviewer = "claude"\n',
        encoding="utf-8",
    )
    failover.write_override(
        repo,
        "implementer",
        failover.ActiveOverride(
            "claude",
            "antigravity",
            "rate-limit",
            "2026-10-14",
            [],
            resets_at="2026-10-23T00:00:00",
        ),
    )
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"antigravity": {"available": True, "label": "installed", "hint": None}},
    )
    probs = recovery.diagnose(repo, [], "")
    assert probs[0].id == "sticky-switch"
    assert all(opt.id != "reset-role" for opt in probs[0].options)
    assert [opt.id for opt in probs[0].options] == [
        "switch-back",
        "choose-agents",
        "show",
        "cancel",
    ]
    assert probs[0].options[0].label == "Switch back to antigravity anyway"
    assert probs[0].options[0].recommended is False
    assert probs[0].options[1].label == "Choose agents…"
    assert probs[0].options[1].recommended is False
    assert recovery.auto_option(probs[0]) is None
    assert any(
        "antigravity may still be out of quota (resets 2026-10-23T00:00:00)" in line
        for line in probs[0].evidence
    )


def test_sticky_switch_from_claude_whose_reset_has_passed_offers_reset_role(
    tmp_path: Path, monkeypatch
) -> None:
    from whyline import account
    from whyline_relay import failover

    repo = _init_scratch_repo(tmp_path / "repo_claude_reset")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "claude"\nreviewer = "codex"\n',
        encoding="utf-8",
    )
    failover.write_override(
        repo,
        "implementer",
        failover.ActiveOverride(
            "grok",
            "claude",
            "rate-limit",
            "2026-10-14",
            [],
            resets_at="2020-01-01T00:00:00",
        ),
    )
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"claude": {"available": True, "label": "pro", "hint": None}},
    )
    probs = recovery.diagnose(repo, [], "")
    assert probs[0].id == "sticky-switch"
    assert probs[0].options[0].id == "reset-role"
    assert probs[0].options[0].recommended is True


def test_stale_override_gives_recommended_use_option_and_clears_override(
    tmp_path: Path, monkeypatch
) -> None:
    from whyline import account
    from whyline_relay import failover

    repo = _init_scratch_repo(tmp_path / "repo_stale")
    # In config.toml, implementer is codex.
    # Override was recorded when implementer was claude.
    failover.write_override(
        repo,
        "implementer",
        failover.ActiveOverride(
            "grok",
            "claude",
            "rate-limit",
            "2026-10-14",
            [],
        ),
    )
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"codex": {"available": True, "label": "available", "hint": None}},
    )
    probs = recovery.diagnose(repo, [], "")
    assert len(probs) == 1
    assert probs[0].id == "sticky-switch"
    opt_use = probs[0].options[0]
    assert opt_use.id == "use-configured"
    assert opt_use.label == "Use codex (from Set up)"
    assert opt_use.recommended is True
    assert opt_use.confirm is False

    # Auto applies the Use option
    assert recovery.auto_option(probs[0]) == opt_use

    # Applying the Use option clears the override
    msg = recovery.apply(repo, probs[0], opt_use.id, launch=lambda args: None)
    assert "Reset role implementer" in msg or "implementer" in msg
    assert failover.read_overrides(repo) == {}


def test_generic_agent_offers_switch_back_anyway_and_choose_agents(
    tmp_path: Path, monkeypatch
) -> None:
    from whyline import account
    from whyline.console.relay_screens import RelaySetupScreen
    from whyline_relay import failover

    repo = _init_scratch_repo(tmp_path / "repo_generic")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "grok"\nreviewer = "claude"\n',
        encoding="utf-8",
    )
    failover.write_override(
        repo,
        "implementer",
        failover.ActiveOverride(
            "claude",
            "grok",
            "rate-limit",
            "2026-10-14",
            [],
        ),
    )
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"grok": {"available": True, "label": "installed", "hint": None}},
    )
    probs = recovery.diagnose(repo, [], "")
    assert len(probs) == 1
    assert probs[0].id == "sticky-switch"
    opt_ids = [opt.id for opt in probs[0].options]
    assert opt_ids == ["switch-back", "choose-agents", "show", "cancel"]

    opt_switch = probs[0].options[0]
    assert opt_switch.label == "Switch back to grok anyway"
    assert opt_switch.recommended is False

    opt_choose = probs[0].options[1]
    assert opt_choose.label == "Choose agents…"
    assert opt_choose.recommended is False

    # Auto never applies Switch back anyway (or Choose agents)
    assert recovery.auto_option(probs[0]) is None

    # Applying choose-agents opens RelaySetupScreen
    screen = recovery.apply(repo, probs[0], "choose-agents", launch=lambda args: None)
    assert isinstance(screen, RelaySetupScreen)

    # Applying switch-back clears the override
    msg = recovery.apply(repo, probs[0], "switch-back", launch=lambda args: None)
    assert "implementer" in msg
    assert failover.read_overrides(repo) == {}


def test_non_generic_agent_with_missing_reset_time_offers_switch_back_anyway_and_choose_agents(
    tmp_path: Path, monkeypatch
) -> None:
    from whyline import account
    from whyline_relay import failover

    repo = _init_scratch_repo(tmp_path / "repo_claude_no_reset")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "claude"\nreviewer = "codex"\n',
        encoding="utf-8",
    )
    failover.write_override(
        repo,
        "implementer",
        failover.ActiveOverride(
            "grok",
            "claude",
            "rate-limit",
            "2026-10-14",
            [],
            resets_at="",
        ),
    )
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"claude": {"available": True, "label": "pro", "hint": None}},
    )
    probs = recovery.diagnose(repo, [], "")
    assert len(probs) == 1
    assert probs[0].id == "sticky-switch"
    opt_ids = [opt.id for opt in probs[0].options]
    assert opt_ids == ["switch-back", "choose-agents", "show", "cancel"]
    assert probs[0].options[0].label == "Switch back to claude anyway"
    assert probs[0].options[0].recommended is False
    assert probs[0].options[1].label == "Choose agents…"
    assert probs[0].options[1].recommended is False
    assert recovery.auto_option(probs[0]) is None
    assert any(
        "claude may still be out of quota (resets unknown)" in line
        for line in probs[0].evidence
    )


def test_non_generic_agent_with_invalid_reset_time_offers_switch_back_anyway_and_choose_agents(
    tmp_path: Path, monkeypatch
) -> None:
    from whyline import account
    from whyline_relay import failover

    repo = _init_scratch_repo(tmp_path / "repo_claude_bad_reset")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "claude"\nreviewer = "codex"\n',
        encoding="utf-8",
    )
    failover.write_override(
        repo,
        "implementer",
        failover.ActiveOverride(
            "grok",
            "claude",
            "rate-limit",
            "2026-10-14",
            [],
            resets_at="invalid-iso-timestamp",
        ),
    )
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"claude": {"available": True, "label": "pro", "hint": None}},
    )
    probs = recovery.diagnose(repo, [], "")
    assert len(probs) == 1
    assert probs[0].id == "sticky-switch"
    opt_ids = [opt.id for opt in probs[0].options]
    assert opt_ids == ["switch-back", "choose-agents", "show", "cancel"]
    assert probs[0].options[0].label == "Switch back to claude anyway"
    assert probs[0].options[0].recommended is False
    assert probs[0].options[1].label == "Choose agents…"
    assert probs[0].options[1].recommended is False
    assert recovery.auto_option(probs[0]) is None
    assert any(
        "claude may still be out of quota (resets unknown)" in line
        for line in probs[0].evidence
    )


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
@pytest.mark.asyncio
async def test_resolve_choose_agents_pushes_relay_setup_screen_in_console(
    tmp_path: Path, monkeypatch, installed_agents
) -> None:
    from whyline import account
    from whyline.console.relay_screens import RelaySetupScreen
    from whyline_relay import failover

    repo = _init_scratch_repo(tmp_path / "repo_choose_tui")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "grok"\nreviewer = "claude"\n',
        encoding="utf-8",
    )
    failover.write_override(
        repo,
        "implementer",
        failover.ActiveOverride(
            "claude",
            "grok",
            "rate-limit",
            "2026-10-14",
            [],
        ),
    )
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"grok": {"available": True, "label": "installed", "hint": None}},
    )

    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test() as pilot:
        app.session.mode = "relay"
        app._start_resolve_flow(source="resume")
        await pilot.pause()

        assert app.query_one("#resolve-actions", tui.Horizontal).display is True
        assert app.query_one("#resolve-choose-agents", tui.Button).display is True

        await pilot.click("#resolve-choose-agents")
        for _ in range(100):
            await pilot.pause(0.05)
            if isinstance(app.screen, RelaySetupScreen):
                break

        assert isinstance(app.screen, RelaySetupScreen)
        assert app._main("#resolve-actions").display is False


def test_fail_line_not_logged_in_is_logged_out_with_login_claude_first(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _init_scratch_repo(tmp_path / "repo_logout")
    monkeypatch.setattr(
        recovery,
        "run_login_status",
        lambda agent: (1, '{"loggedIn": false}'),
    )
    probs = recovery.diagnose(
        repo, ["FAIL  claude (backup for the chain) is not logged in"], ""
    )
    logged = [p for p in probs if p.id == "logged-out"]
    assert len(logged) == 1
    assert logged[0].summary == "claude is not logged in"
    assert logged[0].options[0].id == "login-claude"
    assert logged[0].options[0].label == "Log in to claude"
    assert logged[0].options[0].recommended is True
    assert logged[0].options[-2].id == "show"
    assert logged[0].options[-1].id == "cancel"
    assert any("is not logged in" in line for line in logged[0].evidence)


def test_oauth_session_expired_pause_is_logged_out(tmp_path: Path, monkeypatch) -> None:
    repo = _init_scratch_repo(tmp_path / "repo_oauth")
    monkeypatch.setattr(
        recovery,
        "run_login_status",
        lambda agent: (1, '{"loggedIn": false}'),
    )
    probs = recovery.diagnose(repo, [], "OAuth session expired and could not be refreshed")
    assert probs[0].id == "logged-out"

    probs_named = recovery.diagnose(
        repo, [], "claude: OAuth session expired and could not be refreshed"
    )
    assert probs_named[0].id == "logged-out"
    assert probs_named[0].options[0].id == "login-claude"


def test_antigravity_logged_out_has_no_login_option_and_sign_in_detail(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _init_scratch_repo(tmp_path / "repo_agy_out")
    monkeypatch.setattr(
        recovery,
        "run_login_status",
        lambda agent: (1, ""),
    )
    probs = recovery.diagnose(
        repo, ["FAIL  antigravity (backup for the chain) is not logged in"], ""
    )
    logged = [p for p in probs if p.id == "logged-out"]
    assert len(logged) == 1
    assert all(not opt.id.startswith("login-") for opt in logged[0].options)
    assert [opt.id for opt in logged[0].options] == ["show", "cancel"]
    assert any(
        "Open antigravity in a terminal and sign in, then press Check again." in line
        for line in logged[0].evidence
    )


def test_auto_option_is_none_for_logged_out_and_apply_does_not_run_login(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _init_scratch_repo(tmp_path / "repo_auto_login")
    monkeypatch.setattr(
        recovery,
        "run_login_status",
        lambda agent: (1, '{"loggedIn": false}'),
    )
    probs = recovery.diagnose(
        repo, ["FAIL  claude (backup for the chain) is not logged in"], ""
    )
    problem = next(p for p in probs if p.id == "logged-out")
    assert recovery.auto_option(problem) is None

    launched: list[list[str]] = []
    ran: list[object] = []
    monkeypatch.setattr(
        recovery.subprocess,
        "run",
        lambda *args, **kwargs: ran.append((args, kwargs)) or None,
    )
    result = recovery.apply(repo, problem, "login-claude", launched.append)
    assert isinstance(result, recovery.LoginRequest)
    assert result.agent == "claude"
    assert launched == []
    assert ran == []


def test_auth_pause_reason_is_logged_out(tmp_path: Path, monkeypatch) -> None:
    repo = _init_scratch_repo(tmp_path / "repo_auth")
    monkeypatch.setattr(
        recovery,
        "run_login_status",
        lambda agent: (1, '{"loggedIn": false}'),
    )
    probs = recovery.diagnose(repo, [], "claude is no longer logged in")
    assert probs[0].id == "logged-out"
    assert probs[0].options[0].id == "login-claude"


def test_fake_agy_quota_log_yields_model_and_reset_time(tmp_path: Path):
    from datetime import datetime, timezone

    now = datetime(2026, 10, 19, 1, 12, 29, tzinfo=timezone.utc)
    log_content = (
        'error: Individual quota reached. Please upgrade your subscription to increase your limits. Resets in 154h42m31s.\n'
        'AGY_ERROR: {"short_error":"RESOURCE_EXHAUSTED (code 429): Individual quota reached. Resets in 154h42m31s.","status":"RESOURCE_EXHAUSTED","error_code":429,"modelName":"gemini-4-argon-medium"}\n'
    )
    log_file = tmp_path / "failing.log"
    log_file.write_text(log_content, encoding="utf-8")

    model, reset_time = recovery.read_quota_log(log_file, now=now)
    assert model == "gemini-4-argon-medium"
    assert reset_time == "25 Oct 11:55"

    # Also works when model is passed via CLI flag
    log_cli = tmp_path / "cli.log"
    log_cli.write_text(
        'agy -p "prompt" --model gemini-4-argon-medium\n'
        'error: Individual quota reached. Resets in 154h42m31s.\n',
        encoding="utf-8",
    )
    m2, r2 = recovery.read_quota_log(log_cli, now=now)
    assert m2 == "gemini-4-argon-medium"
    assert r2 == "25 Oct 11:55"


def test_resolve_offers_model_option_and_shows_out_until_evidence(tmp_path: Path, monkeypatch, installed_agents):
    import subprocess
    from datetime import datetime, timezone
    from whyline import account
    from whyline.console.relay_screens import RelaySetupScreen

    now = datetime(2026, 10, 19, 1, 12, 29, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", now, raising=False)

    repo = _init_scratch_repo(tmp_path / "repo_resolve_model")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "antigravity"\nreviewer = "codex"\n[backup]\nchain = ["grok"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-qam", "setup roles"], cwd=repo, check=True)
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"antigravity": {"available": True}, "codex": {"available": True}, "grok": {"available": True}},
    )

    logs_dir = repo / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "T1-1-antigravity.log"
    log_file.write_text(
        'error: Individual quota reached. Resets in 154h42m31s.\n'
        'AGY_ERROR: {"modelName":"gemini-4-argon-medium","error":"Individual quota reached. Resets in 154h42m31s."}\n',
        encoding="utf-8",
    )
    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": 'antigravity hit a usage or rate limit; try again when it resets',
            "log_path": str(log_file),
        }),
        encoding="utf-8",
    )

    probs = recovery.diagnose(repo, [], 'antigravity hit a usage or rate limit; try again when it resets')
    assert probs[0].id == "out-of-usage"
    expected_line = "antigravity · gemini-4-argon-medium out until 25 Oct 11:55"
    assert expected_line in probs[0].evidence
    assert expected_line in probs[0].summary

    # Resolve offers **Use another antigravity model…**
    model_opts = [opt for opt in probs[0].options if "model" in opt.id]
    assert len(model_opts) == 1
    assert model_opts[0].label == "Use another antigravity model…"
    assert model_opts[0].recommended is False

    # Auto never picks a model
    assert recovery.auto_option(probs[0]) != model_opts[0]
    prob_only_model = recovery.Problem(
        id="out-of-usage",
        summary="out",
        evidence=[expected_line],
        options=[
            model_opts[0],
            recovery.Option("show", "Show", "show", False, False),
            recovery.Option("cancel", "Cancel", "cancel", False, False),
        ],
    )
    assert recovery.auto_option(prob_only_model) is None

    # Applying opens Set up on that Model row
    res = recovery.apply(repo, probs[0], model_opts[0].id, lambda args: None)
    assert isinstance(res, RelaySetupScreen)
    assert getattr(res, "_focus_agent", None) == "antigravity"

    # pause_message includes model out-until text
    msg = recovery.pause_message("antigravity", "implementer", "rate-limit", root=repo, now=now)
    assert msg == expected_line

    # Production pause card shows model out-until line
    from whyline.console import adapters

    pause_card_text = adapters.format_pause_text(
        repo,
        "T1",
        "antigravity hit a usage or rate limit; try again when it resets",
        log_path=str(log_file),
    )
    assert "[rate-limit]" in pause_card_text
    assert f"Reason {expected_line}" in pause_card_text

    # classify_relay_output produces pause card with model out-until line
    ev = adapters.classify_relay_output(repo, "Paused: rate-limit\n", 2)
    assert ev.kind == "pause"
    assert f"Reason {expected_line}" in ev.text


def test_quota_log_with_no_model_name_falls_back_to_agent_level_message(tmp_path: Path, monkeypatch, installed_agents):
    import subprocess
    from datetime import datetime, timezone
    from whyline import account

    now = datetime(2026, 10, 19, 1, 12, 29, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", now, raising=False)

    repo = _init_scratch_repo(tmp_path / "repo_no_model")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "antigravity"\nreviewer = "codex"\n[backup]\nchain = []\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-qam", "setup roles"], cwd=repo, check=True)
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"antigravity": {"available": True}, "codex": {"available": True}, "grok": {"available": True}},
    )

    logs_dir = repo / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "T1-1-antigravity.log"
    log_file.write_text(
        'error: Individual quota reached. Resets in 154h42m31s.\n',
        encoding="utf-8",
    )
    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": 'antigravity hit a usage or rate limit; try again when it resets',
            "log_path": str(log_file),
        }),
        encoding="utf-8",
    )

    model, reset_time = recovery.read_quota_log(log_file, now=now)
    assert model == ""
    assert reset_time == "25 Oct 11:55"

    probs = recovery.diagnose(repo, [], 'antigravity hit a usage or rate limit; try again when it resets')
    assert probs[0].id == "out-of-usage"
    # Falls back to agent-level message
    assert "antigravity" in probs[0].summary
    assert "out until" not in probs[0].summary
    # Resolve does NOT offer model option
    assert not any("model" in opt.id for opt in probs[0].options)

    # pause_message falls back to today's agent-level message
    msg = recovery.pause_message("antigravity", "implementer", "rate-limit", root=repo, now=now)
    assert "antigravity hit a usage or rate limit" in msg
    assert "out until" not in msg

    # Production pause card also falls back to agent-level message
    from whyline.console import adapters

    pause_card_text = adapters.format_pause_text(
        repo,
        "T1",
        "antigravity hit a usage or rate limit; try again when it resets",
        log_path=str(log_file),
    )
    assert "[rate-limit]" in pause_card_text
    assert "Reason antigravity hit a usage or rate limit; try again when it resets" in pause_card_text
    assert "out until" not in pause_card_text

    ev = adapters.classify_relay_output(repo, "Paused: rate-limit\n", 2)
    assert ev.kind == "pause"
    assert "Reason antigravity hit a usage or rate limit; try again when it resets" in ev.text
    assert "out until" not in ev.text


def test_quota_preserves_absolute_resets_at_when_display_time_is_later_than_failure_time(tmp_path: Path, monkeypatch, installed_agents):
    import subprocess
    from datetime import datetime, timezone
    from whyline import account
    from whyline.console import adapters
    from whyline_relay import failover

    failure_time = datetime(2026, 10, 19, 1, 12, 29, tzinfo=timezone.utc)
    display_time = datetime(2026, 10, 21, 14, 30, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", display_time, raising=False)

    repo = _init_scratch_repo(tmp_path / "repo_display_later")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "antigravity"\nreviewer = "codex"\n[backup]\nchain = ["grok"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-qam", "setup roles"], cwd=repo, check=True)
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"antigravity": {"available": True}, "codex": {"available": True}, "grok": {"available": True}},
    )

    logs_dir = repo / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "T1-1-antigravity.log"
    log_file.write_text(
        'AGY_ERROR: {"modelName":"gemini-4-argon-medium","error":"Individual quota reached. Resets in 154h42m31s."}\n',
        encoding="utf-8",
    )

    # ActiveOverride was persisted at failure_time with resets_at 25 Oct 11:55
    override = failover.ActiveOverride(
        agent="grok",
        backup_for="antigravity",
        reason="rate-limit",
        since="2026-10-19T01:12:29",
        resets_at="2026-10-25T11:55:00+00:00",
    )
    failover.write_override(repo, "implementer", override)

    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": 'antigravity hit a usage or rate limit; try again when it resets',
            "log_path": str(log_file),
        }),
        encoding="utf-8",
    )

    expected_line = "antigravity · gemini-4-argon-medium out until 25 Oct 11:55"

    # read_failing_turn_quota honors the override's absolute resets_at, not recomputing from display_time
    m, r = recovery.read_failing_turn_quota(repo, "antigravity", override=override, now=display_time)
    assert m == "gemini-4-argon-medium"
    assert r == "25 Oct 11:55"

    # find_out_until_models also honors absolute resets_at
    out_models = recovery.find_out_until_models(repo, now=display_time)
    assert out_models.get("antigravity") == expected_line

    # pause_message preserves absolute resets_at at later display time
    msg = recovery.pause_message("antigravity", "implementer", "rate-limit", root=repo, now=display_time)
    assert msg == expected_line

    # production pause card preserves absolute resets_at
    pause_card_text = adapters.format_pause_text(
        repo,
        "T1",
        "antigravity hit a usage or rate limit; try again when it resets",
        log_path=str(log_file),
    )
    assert f"Reason {expected_line}" in pause_card_text

    ev = adapters.classify_relay_output(repo, "Paused: rate-limit\n", 2)
    assert ev.kind == "pause"
    assert f"Reason {expected_line}" in ev.text


def test_old_quota_logs_and_non_quota_state_do_not_produce_out_until_models(tmp_path: Path, monkeypatch, installed_agents):
    import subprocess
    from datetime import datetime, timezone
    from whyline import account

    now = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", now, raising=False)

    repo = _init_scratch_repo(tmp_path / "repo_old_logs")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "antigravity"\nreviewer = "codex"\n[backup]\nchain = ["grok"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-qam", "setup roles"], cwd=repo, check=True)
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"antigravity": {"available": True}, "codex": {"available": True}, "grok": {"available": True}},
    )

    # Historical quota log exists from a previous run
    logs_dir = repo / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    old_log = logs_dir / "T0-1-antigravity.log"
    old_log.write_text(
        'AGY_ERROR: {"modelName":"gemini-4-argon-medium","error":"Individual quota reached. Resets in 154h42m31s."}\n',
        encoding="utf-8",
    )

    # 1. No state and no override: old quota log must NOT produce an out-until status
    out_models = recovery.find_out_until_models(repo, now=now)
    assert out_models == {}

    m, r = recovery.read_failing_turn_quota(repo, "antigravity", now=now)
    assert m == ""
    assert r == ""

    # 2. Non-quota state (e.g. sandbox error): must NOT produce an out-until status
    sandbox_log = logs_dir / "T1-1-antigravity.log"
    sandbox_log.write_text("antigravity could not run a required command: git status\n", encoding="utf-8")
    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "antigravity could not run a required command",
            "log_path": str(sandbox_log),
        }),
        encoding="utf-8",
    )
    out_models = recovery.find_out_until_models(repo, now=now)
    assert out_models == {}

    m, r = recovery.read_failing_turn_quota(
        repo, "antigravity", reason="antigravity could not run a required command", log_path=str(sandbox_log), now=now
    )
    assert m == ""
    assert r == ""

    # 3. Non-quota state (e.g. visit-cap): must NOT produce an out-until status
    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "antigravity hit a 3-visit cap without handing off",
            "log_path": str(sandbox_log),
        }),
        encoding="utf-8",
    )
    out_models = recovery.find_out_until_models(repo, now=now)
    assert out_models == {}


def test_quota_direct_pause_anchors_reset_deadline_to_failing_turn_when_display_time_is_later(tmp_path: Path, monkeypatch, installed_agents):
    import os
    import subprocess
    from datetime import datetime, timezone
    from whyline import account
    from whyline.console import adapters
    from whyline_relay import failover

    failure_time = datetime(2026, 10, 19, 1, 12, 29, tzinfo=timezone.utc)
    display_time = datetime(2026, 10, 21, 14, 30, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", display_time, raising=False)

    repo = _init_scratch_repo(tmp_path / "repo_direct_pause_display_later")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "antigravity"\nreviewer = "codex"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-qam", "setup roles"], cwd=repo, check=True)
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"antigravity": {"available": True}, "codex": {"available": True}},
    )

    logs_dir = repo / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "T1-1-antigravity.log"
    log_file.write_text(
        'AGY_ERROR: {"modelName":"gemini-4-argon-medium","error":"Individual quota reached. Resets in 154h42m31s."}\n',
        encoding="utf-8",
    )
    os.utime(log_file, (failure_time.timestamp(), failure_time.timestamp()))

    # Direct pause without backup/override: NO override exists in repo
    assert failover.read_overrides(repo) == {}

    state_file = repo / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T1",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "antigravity hit a usage or rate limit; try again when it resets",
            "log_path": str(log_file),
        }),
        encoding="utf-8",
    )
    os.utime(state_file, (failure_time.timestamp(), failure_time.timestamp()))

    expected_line = "antigravity · gemini-4-argon-medium out until 25 Oct 11:55"

    # 1. At display_time (21 Oct 14:30), reset deadline is anchored to failure_time (25 Oct 11:55), NOT recomputed from display_time (28 Oct 01:12)
    m, r = recovery.read_failing_turn_quota(repo, "antigravity", now=display_time)
    assert m == "gemini-4-argon-medium"
    assert r == "25 Oct 11:55"

    out_models = recovery.find_out_until_models(repo, now=display_time)
    assert out_models.get("antigravity") == expected_line

    msg = recovery.pause_message("antigravity", "implementer", "rate-limit", root=repo, now=display_time)
    assert msg == expected_line

    pause_card_text = adapters.format_pause_text(
        repo,
        "T1",
        "antigravity hit a usage or rate limit; try again when it resets",
        log_path=str(log_file),
    )
    assert f"Reason {expected_line}" in pause_card_text

    ev = adapters.classify_relay_output(repo, "Paused: rate-limit\n", 2)
    assert ev.kind == "pause"
    assert f"Reason {expected_line}" in ev.text

    probs = recovery.diagnose(repo, [], "antigravity hit a usage or rate limit; try again when it resets")
    assert expected_line in probs[0].evidence
    assert expected_line in probs[0].summary

    # 2. Later, when the reset deadline has passed (expired status):
    expired_time = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", expired_time, raising=False)

    out_models_expired = recovery.find_out_until_models(repo, now=expired_time)
    assert out_models_expired == {}

    m_exp, r_exp = recovery.read_failing_turn_quota(repo, "antigravity", now=expired_time)
    assert m_exp == ""
    assert r_exp == ""

    msg_expired = recovery.pause_message("antigravity", "implementer", "rate-limit", root=repo, now=expired_time)
    assert "out until" not in msg_expired
    assert "antigravity hit a usage or rate limit; try again when it resets" in msg_expired


def test_sticky_switch_quota_override_apply_use_another_model_opens_relay_setup_screen(tmp_path: Path, monkeypatch, installed_agents):
    import subprocess
    from datetime import datetime, timezone
    from whyline import account
    from whyline.console.relay_screens import RelaySetupScreen
    from whyline_relay import failover

    display_time = datetime(2026, 10, 21, 14, 30, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", display_time, raising=False)

    repo = _init_scratch_repo(tmp_path / "repo_sticky_switch_model_apply")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "antigravity"\nreviewer = "codex"\n[backup]\nchain = ["grok"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-qam", "setup roles"], cwd=repo, check=True)
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"antigravity": {"available": True}, "codex": {"available": True}, "grok": {"available": True}},
    )

    logs_dir = repo / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "T1-1-antigravity.log"
    log_file.write_text(
        'AGY_ERROR: {"modelName":"gemini-4-argon-medium","error":"Individual quota reached. Resets in 154h42m31s."}\n',
        encoding="utf-8",
    )

    override = failover.ActiveOverride(
        agent="grok",
        backup_for="antigravity",
        reason="rate-limit",
        since="2026-10-19T01:12:29",
        resets_at="2026-10-25T11:55:00+00:00",
    )
    failover.write_override(repo, "implementer", override)

    probs = recovery.diagnose(repo, [])
    sticky_probs = [p for p in probs if p.id == "sticky-switch"]
    assert len(sticky_probs) == 1
    sticky_prob = sticky_probs[0]

    opt_ids = [opt.id for opt in sticky_prob.options]
    assert "use-another-antigravity-model" in opt_ids

    # Applying use-another-antigravity-model must open RelaySetupScreen on antigravity Model row,
    # NOT be intercepted by the sticky-switch role reset branch
    res = recovery.apply(repo, sticky_prob, "use-another-antigravity-model", lambda args: None)
    assert isinstance(res, RelaySetupScreen)
    assert getattr(res, "_focus_agent", None) == "antigravity"

    # Confirm the override was NOT reset
    current_overrides = failover.read_overrides(repo)
    assert "implementer" in current_overrides
    assert current_overrides["implementer"].agent == "grok"


def test_antigravity_override_does_not_read_unrelated_codex_state_log(tmp_path: Path, monkeypatch, installed_agents):
    """Regression for AGS-5: Quota lookup for an agent under an older rate-limit override
    must not attribute an unrelated current state log (e.g. from Codex running as backup) to that agent.
    """
    import json
    import subprocess
    from datetime import datetime, timezone
    from whyline import account
    from whyline_relay import failover

    display_time = datetime(2026, 10, 21, 14, 30, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", display_time, raising=False)

    repo = _init_scratch_repo(tmp_path / "repo_quota_override_unrelated_codex_log")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        '[relay]\nplan = "plan.md"\n[roles]\nimplementer = "antigravity"\ntester = "codex"\nreviewer = "claude"\nbackup = ["codex"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qam", "setup roles"], cwd=repo, check=True)
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"antigravity": {"available": True}, "codex": {"available": True}, "claude": {"available": True}},
    )

    # 1. Antigravity hit quota in round 1; failing turn log is stored in logs/
    logs_dir = repo / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    agy_log = logs_dir / "T1-1-antigravity.log"
    agy_log.write_text(
        'AGY_ERROR: {"modelName":"gemini-4-argon-medium","error":"Individual quota reached. Resets in 154h42m31s."}\n',
        encoding="utf-8",
    )
    override = failover.ActiveOverride(
        agent="codex",
        backup_for="antigravity",
        reason="rate-limit",
        since="2026-10-19T01:12:29",
        resets_at="2026-10-25T11:55:00+00:00",
    )
    failover.write_override(repo, "implementer", override)

    # 2. In round 2, Codex ran as backup. Current relay state points to Codex's log which mentions a model.
    codex_log = logs_dir / "T1-2-codex.log"
    codex_log.write_text(
        'running codex --model gpt-5\nCodex encountered a command error.\n',
        encoding="utf-8",
    )
    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T1",
            "round": 2,
            "base_commit": "abc",
            "paused_reason": "codex could not run a required command: pytest",
            "log_path": str(codex_log),
        }),
        encoding="utf-8",
    )

    # Quota lookup for antigravity must find Antigravity's failing turn log, NOT Codex's current state log
    m, r = recovery.read_failing_turn_quota(repo, "antigravity", override=override, now=display_time)
    assert m == "gemini-4-argon-medium"
    assert r == "25 Oct 11:55"

    out_models = recovery.find_out_until_models(repo, now=display_time)
    assert out_models.get("antigravity") == "antigravity · gemini-4-argon-medium out until 25 Oct 11:55"
    assert "gpt-5" not in out_models.get("antigravity", "")

    # Also test when Codex's state was itself a quota limit
    codex_log.write_text(
        'codex error: usage limit reached for model "gpt-5". Resets in 12h.\n',
        encoding="utf-8",
    )
    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T1",
            "round": 2,
            "base_commit": "abc",
            "paused_reason": "codex hit a usage or rate limit; try again when it resets",
            "log_path": str(codex_log),
        }),
        encoding="utf-8",
    )

    m2, r2 = recovery.read_failing_turn_quota(repo, "antigravity", override=override, now=display_time)
    assert m2 == "gemini-4-argon-medium"
    assert r2 == "25 Oct 11:55"

    out_models2 = recovery.find_out_until_models(repo, now=display_time)
    assert out_models2.get("antigravity") == "antigravity · gemini-4-argon-medium out until 25 Oct 11:55"

    # The review's reproduction: grok is the backup, and a later ordinary Codex turn's
    # log names its model in a JSON field without any quota text
    failover.write_override(
        repo,
        "implementer",
        failover.ActiveOverride(
            agent="grok",
            backup_for="antigravity",
            reason="rate-limit",
            since="2026-10-19T01:12:29+00:00",
            resets_at="2026-10-25T11:55:00+00:00",
        ),
    )
    other_log = logs_dir / "T2-1-codex.log"
    other_log.write_text('{"modelName":"gpt-5.1"}\nordinary successful turn\n', encoding="utf-8")
    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T2",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "codex could not run a required command",
            "log_path": str(other_log),
        }),
        encoding="utf-8",
    )
    assert recovery.find_out_until_models(repo, now=display_time) == {
        "antigravity": "antigravity · gemini-4-argon-medium out until 25 Oct 11:55",
    }



def test_backup_quota_pause_does_not_borrow_the_role_overrides_reset_time(tmp_path: Path, monkeypatch, installed_agents):
    """Regression for AGS-5: the role's override records antigravity's limit. When codex,
    running as that backup, later hits its own limit, codex's out-until line must use codex's
    log and reset, never antigravity's override resets_at, and antigravity keeps its own line.
    """
    import os
    import subprocess
    from datetime import datetime, timezone
    from whyline import account
    from whyline_relay import failover

    display_time = datetime(2026, 10, 21, 14, 30, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", display_time, raising=False)

    repo = _init_scratch_repo(tmp_path / "repo_backup_quota_own_reset")
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "antigravity"\nreviewer = "claude"\n[backup]\nchain = ["codex"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "commit", "-qam", "setup roles"], cwd=repo, check=True)
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: {"antigravity": {"available": True}, "codex": {"available": True}, "claude": {"available": True}},
    )

    logs_dir = repo / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    agy_log = logs_dir / "T1-1-antigravity.log"
    agy_log.write_text(
        'AGY_ERROR: {"modelName":"gemini-4-argon-medium","error":"Individual quota reached. Resets in 154h42m31s."}\n',
        encoding="utf-8",
    )
    override = failover.ActiveOverride(
        agent="codex",
        backup_for="antigravity",
        reason="rate-limit",
        since="2026-10-19T01:12:29+00:00",
        tried=["antigravity"],
        resets_at="2026-10-25T11:55:00+00:00",
    )
    failover.write_override(repo, "implementer", override)

    codex_log = logs_dir / "T1-2-codex.log"
    codex_log.write_text(
        'codex --model gpt-5\nerror: usage limit reached. Resets in 12h0m0s.\n',
        encoding="utf-8",
    )
    os.utime(codex_log, (display_time.timestamp(), display_time.timestamp()))
    reason = "codex hit a usage or rate limit; try again when it resets"
    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T1",
            "round": 2,
            "base_commit": "abc",
            "paused_reason": reason,
            "log_path": str(codex_log),
        }),
        encoding="utf-8",
    )

    codex_line = "codex · gpt-5 out until 22 Oct 02:30"
    agy_line = "antigravity · gemini-4-argon-medium out until 25 Oct 11:55"

    # Passing the role's override (antigravity's limit) for codex must not attach its reset time
    assert recovery.read_failing_turn_quota(repo, "codex", override=override, now=display_time) == (
        "gpt-5",
        "22 Oct 02:30",
    )
    # Nor may the lookup pick up that override on its own because codex is its backup
    assert recovery.read_failing_turn_quota(repo, "codex", reason=reason, now=display_time) == (
        "gpt-5",
        "22 Oct 02:30",
    )
    # Antigravity's own limit still comes from its own log and override
    assert recovery.read_failing_turn_quota(repo, "antigravity", override=override, now=display_time) == (
        "gemini-4-argon-medium",
        "25 Oct 11:55",
    )

    assert recovery.find_out_until_models(repo, now=display_time) == {
        "antigravity": agy_line,
        "codex": codex_line,
    }

    probs = recovery.diagnose(repo, [], reason)
    usage = [p for p in probs if p.id == "out-of-usage"]
    assert usage, [p.id for p in probs]
    assert codex_line in usage[0].evidence
    assert all("25 Oct" not in line for line in usage[0].evidence)
    assert any(opt.label == "Use another codex model…" for opt in usage[0].options)


def test_antigravity_override_ignores_unnamed_current_state_log(tmp_path: Path, monkeypatch, installed_agents):
    """Regression for AGS-5: a current state log whose name does not say which agent wrote it
    (e.g. chat-last-turn.log) is not antigravity's failing turn under an antigravity override,
    even when it is a quota pause that names a model.
    """
    from datetime import datetime, timezone
    from whyline_relay import failover

    display_time = datetime(2026, 10, 21, 14, 30, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(recovery, "_NOW_OVERRIDE", display_time, raising=False)

    repo = _init_scratch_repo(tmp_path / "repo_override_unnamed_state_log")
    logs_dir = repo / ".whyline" / "relay" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "T1-1-antigravity.log").write_text(
        'AGY_ERROR: {"modelName":"gemini-4-argon-medium","error":"Individual quota reached. Resets in 154h42m31s."}\n',
        encoding="utf-8",
    )
    override = failover.ActiveOverride(
        agent="codex",
        backup_for="antigravity",
        reason="rate-limit",
        since="2026-10-19T01:12:29+00:00",
        resets_at="2026-10-25T11:55:00+00:00",
    )
    failover.write_override(repo, "implementer", override)

    unnamed_log = logs_dir / "chat-last-turn.log"
    unnamed_log.write_text('usage limit reached for model "gpt-5". Resets in 12h0m0s.\n', encoding="utf-8")
    (repo / ".whyline" / "relay" / "state.json").write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "T1",
            "round": 2,
            "base_commit": "abc",
            "paused_reason": "usage limit reached; try again when it resets",
            "log_path": str(unnamed_log),
        }),
        encoding="utf-8",
    )

    assert recovery.read_failing_turn_quota(repo, "antigravity", override=override, now=display_time) == (
        "gemini-4-argon-medium",
        "25 Oct 11:55",
    )
    assert recovery.find_out_until_models(repo, now=display_time).get("antigravity") == (
        "antigravity · gemini-4-argon-medium out until 25 Oct 11:55"
    )
