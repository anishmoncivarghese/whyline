"""Tests for recovery route classification and attempt records."""

from __future__ import annotations

import json
from pathlib import Path

from whyline.console import adapters, recovery


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



