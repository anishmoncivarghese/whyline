"""Schema 1 AutoRunRequest, its fingerprint, and the Auto checkpoint."""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from whyline import account, model
from whyline.console import auto_run, plan_job, relay_ops


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "T")
    (path / "README.md").write_text("x\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "initial")
    return path


def _request(**overrides) -> plan_job.AutoRunRequest:
    fields = dict(
        name="plan",
        topic="topic",
        replace=False,
        continue_paths=False,
        agents=("claude", "codex"),
        passes=1,
        final_agent="claude",
        timeout_minutes=15,
        attachments=(),
        drafter="claude",
        reviewer="codex",
        implementer="grok",
        tester="claude",
        reviewer_role="codex",
        release="human",
        chain=("codex",),
    )
    fields.update(overrides)
    return plan_job.AutoRunRequest(**fields)


def test_same_request_and_tree_hash_equal(tmp_path):
    root = _repo(tmp_path)
    body = auto_run.document(root, _request())
    assert body["schema"] == 1
    assert body["porcelain"] == ""
    assert len(body["head"].strip()) == 40
    assert auto_run.fingerprint(root, _request()) == auto_run.fingerprint(root, _request())


def test_untracked_file_changes_the_hash(tmp_path):
    root = _repo(tmp_path)
    request = _request()
    before = auto_run.fingerprint(root, request)
    (root / "aut1-untracked.md").write_text("new\n", encoding="utf-8")
    body = auto_run.document(root, request)
    assert "aut1-untracked.md" in body["porcelain"]
    assert auto_run.fingerprint(root, request) != before


def test_missing_attachment_stores_null_size_and_digest(tmp_path):
    root = _repo(tmp_path)
    missing = root / "gone.md"
    request = _request(attachments=(missing,))
    body = auto_run.document(root, request)
    assert body["attachments"] == [{"path": str(missing), "size": None, "sha256": None}]
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    assert '"size":null' in raw and '"sha256":null' in raw
    assert auto_run.fingerprint(root, request) == hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_attachment_bytes_change_the_hash(tmp_path):
    root = _repo(tmp_path / "repo")
    attachment = tmp_path / "note.md"
    attachment.write_bytes(b"one\n")  # exact bytes: write_text gives \r\n on Windows
    request = _request(attachments=(attachment,))
    before = auto_run.fingerprint(root, request)
    entry = auto_run.document(root, request)["attachments"][0]
    assert entry["size"] == len(b"one\n")
    assert entry["sha256"] == hashlib.sha256(b"one\n").hexdigest()
    attachment.write_bytes(b"two\n")
    assert auto_run.fingerprint(root, request) != before


@pytest.mark.parametrize("value", [True, False])
def test_bool_timeout_raises_type_error(value):
    with pytest.raises(TypeError, match="bool"):
        _request(timeout_minutes=value)


def test_zero_timeout_is_stored_and_negative_is_rejected():
    assert _request(timeout_minutes=0).timeout_minutes == 0
    with pytest.raises(ValueError):
        _request(timeout_minutes=-1)


def test_trust_unused_when_antigravity_is_not_named(tmp_path, monkeypatch):
    root = _repo(tmp_path)

    def consulted(root):
        raise AssertionError("antigravity trust was consulted")

    monkeypatch.setattr(relay_ops, "antigravity_state", consulted)
    body = auto_run.document(root, _request())
    assert body["antigravity"] == "unused"
    assert set(body["models"]) == {"claude", "codex", "grok"}
    assert set(body["available"]) == {"claude", "codex", "grok"}


def test_named_antigravity_records_trust(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(relay_ops, "antigravity_state", lambda root: "declined")
    body = auto_run.document(root, _request(release="antigravity"))
    assert body["antigravity"] == "declined"
    assert "antigravity" in body["models"]


def test_repo_model_overrides_global_models(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(model, "load", lambda root: {"claude": "opus"})
    monkeypatch.setattr(
        model,
        "load_global",
        lambda: {"default_agent": "claude", "models": {"claude": "sonnet", "grok": "grok-4"}},
    )
    body = auto_run.document(root, _request())
    assert body["models"]["claude"] == "opus"
    assert body["models"]["grok"] == "grok-4"
    assert body["models"]["codex"] == ""


def test_available_comes_from_agent_status(tmp_path, monkeypatch):
    root = _repo(tmp_path)

    def status(root):
        return {
            name: {"available": name == "claude"}
            for name in ("claude", "codex", "antigravity", "grok")
        }

    monkeypatch.setattr(account, "agent_status", status)
    body = auto_run.document(root, _request())
    assert body["available"]["claude"] is True
    assert body["available"]["codex"] is False
    assert body["available"]["grok"] is False


def _dead_pid() -> int:
    from whyline_relay import running

    dead = 1_000_000
    while running.pid_is_alive(dead) and dead < 1_000_200:
        dead += 1
    assert not running.pid_is_alive(dead)
    return dead


def _lock(root: Path) -> Path:
    return root / ".whyline" / "relay" / "auto-run.lock"


def _assigns(text: str, key: str, value: str) -> bool:
    """True when a TOML line sets `key` to `value`, ignoring alignment spaces."""
    return re.search(rf"(?m)^{re.escape(key)}\s*=\s*{re.escape(value)}$", text) is not None


def test_form_fingerprint_ignores_head(tmp_path):
    root = _repo(tmp_path)
    request = _request()
    form = auto_run.form_fingerprint(root, request)
    full = auto_run.fingerprint(root, request)
    assert "head" not in auto_run.form_document(root, request)
    assert "porcelain" not in auto_run.form_document(root, request)
    (root / "README.md").write_text("y\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "move head")
    assert auto_run.form_fingerprint(root, request) == form
    assert auto_run.fingerprint(root, request) != full


def test_lock_file_is_exclusive(tmp_path):
    root = _repo(tmp_path)
    auto_run.acquire_lock(root)
    lock = _lock(root)
    held = lock.read_text(encoding="utf-8")
    assert int(held.strip()) == os.getpid()
    with pytest.raises(auto_run.AutoBusy):
        auto_run.acquire_lock(root)
    assert lock.read_text(encoding="utf-8") == held


def test_dead_pid_is_taken(tmp_path):
    root = _repo(tmp_path)
    lock = _lock(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(f"{_dead_pid()}\n", encoding="utf-8")
    auto_run.acquire_lock(root)
    assert int(lock.read_text(encoding="utf-8").strip()) == os.getpid()
    auto_run.release_lock(root)
    assert not lock.exists()
    lock.write_text(f"{_dead_pid()}\n", encoding="utf-8")
    request = _request()
    auto_run.run(root, request, auto_run.fingerprint(root, request))
    assert not lock.exists()
    saved = json.loads(
        (root / ".whyline" / "relay" / "auto-run.json").read_text(encoding="utf-8")
    )
    assert saved["phase"] == "persist"


def test_live_pid_raises_auto_busy(tmp_path):
    root = _repo(tmp_path)
    lock = _lock(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(f"{os.getpid()}\n", encoding="utf-8")
    with pytest.raises(auto_run.AutoBusy):
        auto_run.acquire_lock(root)
    assert int(lock.read_text(encoding="utf-8").strip()) == os.getpid()
    request = _request()
    with pytest.raises(auto_run.AutoBusy):
        auto_run.run(root, request, auto_run.fingerprint(root, request))
    assert not (root / ".whyline" / "relay" / "auto-run.json").exists()
    assert _git(root, "log", "--format=%s").splitlines() == ["initial"]


def test_ensure_relay_ignored_runs_before_the_lock_file(tmp_path, monkeypatch):
    from whyline_relay import gitcheck

    root = _repo(tmp_path)
    lock = _lock(root)
    seen: list[Path] = []
    real = gitcheck.ensure_relay_ignored

    def spy(target):
        assert not lock.exists()
        seen.append(target)
        real(target)

    monkeypatch.setattr(gitcheck, "ensure_relay_ignored", spy)
    auto_run.acquire_lock(root)
    assert seen == [root]
    exclude = (root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert ".whyline/relay/auto-run.json" in exclude
    assert ".whyline/relay/auto-run.lock" in exclude


def _distinct_request(**overrides) -> plan_job.AutoRunRequest:
    fields = dict(
        drafter="claude",
        reviewer="codex",
        implementer="grok",
        tester="claude",
        reviewer_role="grok",
        release="codex",
        chain=("codex", "grok"),
        timeout_minutes=15,
    )
    fields.update(overrides)
    return _request(**fields)


def test_persist_commits_the_config_once(tmp_path):
    root = _repo(tmp_path)
    request = _distinct_request()
    dismissed = auto_run.fingerprint(root, request)
    auto_run.run(root, request, dismissed)
    assert _git(root, "rev-list", "--count", "HEAD").strip() == "2"
    assert (
        _git(root, "log", "-1", "--format=%s").strip()
        == "setup: auto run roles, backup, and timeout"
    )
    committed = set(
        _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").split()
    )
    assert committed == {
        ".whyline/relay/config.toml",
        ".whyline/relay/prompts/test.md",
    }
    config = (root / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")
    assert _assigns(config, "draft", '"claude"')
    assert _assigns(config, "review", '"codex"')
    assert _assigns(config, "implementer", '"grok"')
    assert _assigns(config, "tester", '"claude"')
    assert _assigns(config, "reviewer", '"grok"')
    assert _assigns(config, "release", '"codex"')
    assert _assigns(config, "chain", '["codex", "grok"]')
    assert _assigns(config, "timeout_minutes", "15")
    head = _git(root, "rev-parse", "HEAD").strip()
    saved = json.loads(
        (root / ".whyline" / "relay" / "auto-run.json").read_text(encoding="utf-8")
    )
    assert saved["schema"] == 1
    assert saved["phase"] == "persist"
    assert saved["topic"] == request.topic
    assert saved["name"] == request.name
    assert saved["fingerprint"] == dismissed
    assert saved["last_check"] == dismissed
    assert saved["persist_commit"] == head
    assert saved["brainstorm"] == {"path": None, "sha256": None}
    assert saved["spec"] == {"path": None, "sha256": None}
    assert saved["plan"] == {"path": None, "sha256": None}
    assert "pause" not in saved
    assert "head" not in saved["request"]
    assert "porcelain" not in saved["request"]
    assert saved["request"]["attachments"] == []
    assert "models" in saved["request"]
    assert "available" in saved["request"]
    assert "antigravity" in saved["request"]
    assert not _lock(root).exists()
    assert _git(root, "status", "--porcelain") == ""
    # The persist commit moved HEAD, so Check's fingerprint no longer matches.
    assert auto_run.fingerprint(root, request) != dismissed
    auto_run.run(root, request, dismissed)
    assert _git(root, "rev-parse", "HEAD").strip() == head
    assert _git(root, "rev-list", "--count", "HEAD").strip() == "2"
    with pytest.raises(auto_run.AutoStale):
        auto_run.run(root, _distinct_request(topic="other"), dismissed)
    assert _git(root, "rev-parse", "HEAD").strip() == head


def test_zero_timeout_minutes_is_unquoted(tmp_path):
    root = _repo(tmp_path)
    request = _request(timeout_minutes=0)
    dismissed = auto_run.fingerprint(root, request)
    auto_run.run(root, request, dismissed)
    text = (root / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")
    assert _assigns(text, "timeout_minutes", "0")
    assert not _assigns(text, "timeout_minutes", '"0"')
    head = _git(root, "rev-parse", "HEAD")
    auto_run.run(root, request, dismissed)
    assert _git(root, "rev-parse", "HEAD") == head
    text = (root / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")
    assert _assigns(text, "timeout_minutes", "0")
    assert not _assigns(text, "timeout_minutes", '"0"')


def test_changed_form_writes_nothing(tmp_path):
    root = _repo(tmp_path)
    dismissed = auto_run.fingerprint(root, _request())
    with pytest.raises(auto_run.AutoStale, match="out of date"):
        auto_run.run(root, _request(topic="other"), dismissed)
    assert not (root / ".whyline" / "relay" / "auto-run.json").exists()
    assert not _lock(root).exists()
    assert _git(root, "log", "--format=%s").splitlines() == ["initial"]


def test_matching_artifact_is_not_pending(tmp_path):
    path = tmp_path / "doc.md"
    path.write_bytes(b"hello\n")
    digest = hashlib.sha256(b"hello\n").hexdigest()
    assert auto_run.artifact_matches({"path": str(path), "sha256": digest})
    assert not auto_run.artifact_matches({"path": str(path), "sha256": "0" * 64})
    assert not auto_run.artifact_matches({"path": str(tmp_path / "missing.md"), "sha256": digest})
    assert not auto_run.artifact_matches({"path": None, "sha256": None})
    path.write_bytes(b"bye\n")
    assert not auto_run.artifact_matches({"path": str(path), "sha256": digest})
