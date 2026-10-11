"""Schema 1 AutoRunRequest and its fingerprint, on a scratch git repo."""

import hashlib
import json
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
    attachment.write_text("one\n", encoding="utf-8")
    request = _request(attachments=(attachment,))
    before = auto_run.fingerprint(root, request)
    entry = auto_run.document(root, request)["attachments"][0]
    assert entry["size"] == len(b"one\n")
    assert entry["sha256"] == hashlib.sha256(b"one\n").hexdigest()
    attachment.write_text("two\n", encoding="utf-8")
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
