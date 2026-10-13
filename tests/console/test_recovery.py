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

