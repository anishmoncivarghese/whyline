"""Schema 1 AutoRunRequest, its fingerprint, and the Auto checkpoint."""

import hashlib
import json
import os
import re
import subprocess
import threading
from pathlib import Path

import pytest

from whyline import account, model
from whyline.console import adapters, auto_run, plan_job, relay_ops
from whyline.console.session import SessionEvent


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
    auto_run.run(root, request, auto_run.fingerprint(root, request), through="persist")
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
    auto_run.run(root, request, dismissed, through="persist")
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
    auto_run.run(root, request, dismissed, through="persist")
    assert _git(root, "rev-parse", "HEAD").strip() == head
    assert _git(root, "rev-list", "--count", "HEAD").strip() == "2"
    with pytest.raises(auto_run.AutoStale):
        auto_run.run(root, _distinct_request(topic="other"), dismissed)
    assert _git(root, "rev-parse", "HEAD").strip() == head


def test_zero_timeout_minutes_is_unquoted(tmp_path):
    root = _repo(tmp_path)
    request = _request(timeout_minutes=0)
    dismissed = auto_run.fingerprint(root, request)
    auto_run.run(root, request, dismissed, through="persist")
    text = (root / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")
    assert _assigns(text, "timeout_minutes", "0")
    assert not _assigns(text, "timeout_minutes", '"0"')
    head = _git(root, "rev-parse", "HEAD")
    auto_run.run(root, request, dismissed, through="persist")
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


_CLEAN = "# Topic\n\n## Final Synthesis\n\nShip the console runner.\n"
_OPEN = _CLEAN + "\n## Open questions\n1. Which store?\n"
_SPEC = "# Spec\n\n## Done\n"
_PLAN = "- [ ] RUN-5: done\n"


def _write_synthesis(root: Path, text: str, topic: str = "topic") -> Path:
    from whyline_relay import brainstorm

    path = brainstorm.shared_path(root, topic)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _draft(path: Path, text: str, source: str) -> relay_ops.Draft:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return relay_ops.Draft(path=path, text=text, drafted_by="claude", source=source)


def _install_planning(monkeypatch, root, spec_calls, plan_calls, approved):
    def draft_spec(_root, text, attachments=(), *, progress):
        spec_calls.append(text)
        return _draft(root / ".whyline" / "relay" / "draft-spec.md", _SPEC, "spec")

    def approve_spec(_root, draft, name, *, replace=False):
        approved.append(("spec", replace))
        target = root / "docs" / "specs" / "plan.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft.text, encoding="utf-8")
        return target

    def draft_plan(_root, description, attachments=(), *, progress, spec=None):
        plan_calls.append(description)
        return _draft(root / ".whyline" / "relay" / "draft-plan.md", _PLAN, "planner")

    def approve_plan(_root, draft, name, *, replace=False, spec=""):
        approved.append(("plan", replace))
        target = root / "plans" / "plan.plan.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft.text, encoding="utf-8")
        return target

    monkeypatch.setattr(relay_ops, "draft_spec", draft_spec)
    monkeypatch.setattr(relay_ops, "approve_spec", approve_spec)
    monkeypatch.setattr(relay_ops, "draft_plan", draft_plan)
    monkeypatch.setattr(relay_ops, "approve_plan", approve_plan)


def test_brainstorm_call_forces_no_limit_cancel_and_unattended(monkeypatch):
    from whyline_relay import brainstorm, chat

    seen: dict = {}

    def spy(*_args, **kwargs):
        seen["timeout"] = kwargs.get("timeout_seconds")
        seen["cancel"] = kwargs.get("cancel_event")
        seen["unattended"] = kwargs.get("unattended")
        return {"agent": "claude", "response": "ok"}

    monkeypatch.setattr(brainstorm, "run_final_synthesis", spy)
    event = threading.Event()
    with auto_run._brainstorm_call(chat.NO_LIMIT, event, None):
        brainstorm.run_final_synthesis(timeout_seconds=15, unattended=False)
    assert seen["timeout"] is chat.NO_LIMIT
    assert seen["cancel"] is event
    assert seen["unattended"] is True
    assert auto_run._timeout_seconds(0) is chat.NO_LIMIT
    assert auto_run._timeout_seconds(15) == 900

    def spy_pass(*_args, **kwargs):
        seen["pass_timeout"] = kwargs.get("timeout_seconds")
        seen["pass_cancel"] = kwargs.get("cancel_event")
        return {}

    monkeypatch.setattr(brainstorm, "run_pass_zero", spy_pass)
    with auto_run._brainstorm_call(45 * 60, None, None):
        brainstorm.run_pass_zero(timeout_seconds=1)
    assert seen["pass_timeout"] == 2700
    assert seen["pass_cancel"] is None


def test_synthesis_revision_receives_cancel_event(monkeypatch):
    from whyline_relay import brainstorm

    seen: dict = {}

    def spy(*_args, **kwargs):
        seen["cancel"] = kwargs.get("cancel_event")
        return {"agent": "claude", "response": "ok"}

    monkeypatch.setattr(brainstorm, "revise_synthesis", spy)
    event = threading.Event()
    with auto_run._synthesis_revision_call(event):
        brainstorm.revise_synthesis(cancel_event=None)
    assert seen["cancel"] is event


def test_progress_lines_use_the_underlying_indexes():
    from whyline_relay import brainstorm

    lines: list[str] = []
    report = auto_run._on_brainstorm_progress(lines.append)
    report(
        brainstorm.ProgressEvent(
            status="starting",
            agent="codex",
            label="Codex",
            phase="pass-zero",
            ordinal=2,
            total=4,
            elapsed_seconds=0,
        )
    )
    report(
        brainstorm.ProgressEvent(
            status="running",
            agent="codex",
            label="Codex",
            phase="pass-zero",
            ordinal=2,
            total=4,
            elapsed_seconds=1,
        )
    )
    report(
        brainstorm.ProgressEvent(
            status="starting",
            agent="claude",
            label="Claude",
            phase="synthesis",
            ordinal=1,
            total=1,
            elapsed_seconds=0,
        )
    )
    assert lines == [
        "auto · research 2/4 · codex",
        "auto · synthesis · claude",
    ]
    assert auto_run._planner_progress_line("spec", "review", 1, 3, "codex") == (
        "auto · spec review 1/3 · codex"
    )
    assert auto_run._planner_progress_line("plan", "review", 2, 3, "claude") == (
        "auto · plan review"
    )


def test_open_questions_pause_until_an_answer_clears_them(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    brainstorm_calls: list[str] = []
    revised: list[str] = []
    spec_calls: list[str] = []
    plan_calls: list[str] = []
    approved: list = []

    def fake_brainstorm(_root, **kwargs):
        brainstorm_calls.append(kwargs["final_agent"])
        _write_synthesis(root, _OPEN)
        return SessionEvent("output", "saved")

    def fake_revise(_root, _topic, _agent, _agents, feedback, **kwargs):
        revised.append(feedback)
        _write_synthesis(root, _CLEAN)

    def fail_spec(*_args, **_kwargs):
        raise AssertionError("draft_spec")

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    monkeypatch.setattr(relay_ops, "revise_synthesis", fake_revise)
    monkeypatch.setattr(relay_ops, "draft_spec", fail_spec)
    paused = auto_run.run(root, request, dismissed)
    assert spec_calls == []
    assert revised == []
    assert paused["phase"] == "research"
    assert paused["pause"]["actions"] == ["resume", "change", "cancel"]
    assert "Which store?" in paused["pause"]["reason"]
    assert "brainstorm" in paused
    assert paused["brainstorm"]["sha256"]

    _install_planning(monkeypatch, root, spec_calls, plan_calls, approved)
    monkeypatch.setattr(relay_ops, "revise_synthesis", fake_revise)
    finished = auto_run.run(
        root, request, dismissed, answer="Use the first store.", through="plan"
    )
    assert brainstorm_calls == ["claude"]
    assert revised == ["Use the first store."]
    assert len(spec_calls) == 1
    assert spec_calls[0] == (
        "Write the spec from the brainstorm in docs/brainstorm/topic.md "
        "(its Final Synthesis is the agreed direction).\n\n"
        + auto_run._UNATTENDED_PARAGRAPH
    )
    assert plan_calls == ["topic"]
    assert auto_run._UNATTENDED_PARAGRAPH not in plan_calls[0]
    assert approved == [("spec", False), ("plan", False)]
    assert finished["phase"] == "plan"
    assert "pause" not in finished


def test_synthesis_answer_failure_walks_the_saved_chain(tmp_path, monkeypatch):
    from whyline_relay import agents

    root = _repo(tmp_path)
    request = _request(chain=("codex",))
    dismissed = auto_run.fingerprint(root, request)
    revised: list[tuple[str, list[str]]] = []

    def fake_brainstorm(_root, **_kwargs):
        _write_synthesis(root, _OPEN)
        return SessionEvent("output", "saved")

    def fake_revise(_root, _topic, agent, roster, _feedback, **_kwargs):
        revised.append((agent, roster))
        if agent == "claude":
            raise agents.AgentTimeout("claude timed out")
        _write_synthesis(root, _CLEAN)

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    monkeypatch.setattr(relay_ops, "revise_synthesis", fake_revise)
    paused = auto_run.run(root, request, dismissed)
    assert paused["phase"] == "research"

    _install_planning(monkeypatch, root, [], [], [])
    finished = auto_run.run(
        root, request, dismissed, answer="Use the first store.", through="plan"
    )
    assert finished["phase"] == "plan"
    assert revised == [
        ("claude", ["claude", "codex"]),
        ("codex", ["codex"]),
    ]


def test_visit_cap_does_not_approve_spec(tmp_path, monkeypatch):
    from whyline_relay import loop

    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    approved: list = []

    def fake_brainstorm(_root, **_kwargs):
        _write_synthesis(root, _CLEAN)
        return SessionEvent("output", "saved")

    def fake_spec(*_args, **_kwargs):
        raise loop.Paused(
            "__spec__ hit stage 'review''s 3-visit cap without reaching \"@complete\"",
            None,
        )

    def fake_approve(*_args, **_kwargs):
        approved.append(True)
        raise AssertionError("approve_spec")

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    monkeypatch.setattr(relay_ops, "draft_spec", fake_spec)
    monkeypatch.setattr(relay_ops, "approve_spec", fake_approve)
    paused = auto_run.run(root, request, dismissed)
    assert approved == []
    assert "visit cap" in paused["pause"]["reason"]
    assert "draft-spec.md" in paused["pause"]["reason"]
    assert paused["pause"]["actions"] == ["resume", "change", "cancel"]
    assert paused["phase"] == "spec"


def test_plan_questions_and_blocked_handoff_do_not_approve_spec(tmp_path, monkeypatch):
    from whyline_relay import loop, planner

    root = _repo(tmp_path)
    approved: list = []

    def fake_brainstorm(_root, **kwargs):
        _write_synthesis(root, _CLEAN, topic=kwargs["topic"])
        return SessionEvent("output", "saved")

    def fail_approve(*_args, **_kwargs):
        approved.append(True)

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    monkeypatch.setattr(relay_ops, "approve_spec", fail_approve)

    request = _request(topic="questions")
    dismissed = auto_run.fingerprint(root, request)

    def ask(*_args, **_kwargs):
        raise planner.PlanQuestions(
            "need a choice",
            None,
            questions=("Which db?",),
            stage="draft",
            agent="claude",
        )

    monkeypatch.setattr(relay_ops, "draft_spec", ask)
    questioned = auto_run.run(root, request, dismissed)
    assert approved == []
    assert "Which db?" in questioned["pause"]["reason"]
    assert "draft-spec.md" in questioned["pause"]["reason"]

    (root / ".whyline" / "relay" / "auto-run.json").unlink()
    blocked_request = _request(topic="blocked-spec")
    blocked_dismissed = auto_run.fingerprint(root, blocked_request)

    def blocked_spec(*_args, **_kwargs):
        raise loop.Paused("the plan draft was blocked: sandbox denied the command", None)

    monkeypatch.setattr(relay_ops, "draft_spec", blocked_spec)
    blocked = auto_run.run(root, blocked_request, blocked_dismissed)
    assert approved == []
    assert blocked["phase"] == "spec"
    assert "blocked" in blocked["pause"]["reason"]
    assert "draft-spec.md" in blocked["pause"]["reason"]


def test_parse_error_pauses_with_the_plan_draft_and_does_not_approve(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    approved: list = []

    def fake_brainstorm(_root, **_kwargs):
        _write_synthesis(root, _CLEAN)
        return SessionEvent("output", "saved")

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    _install_planning(monkeypatch, root, [], [], approved)

    def draft_plan(_root, description, attachments=(), *, progress, spec=None):
        assert auto_run._UNATTENDED_PARAGRAPH not in description
        return _draft(
            root / ".whyline" / "relay" / "draft-plan.md",
            "Prose without a checklist.\n",
            "planner",
        )

    def approve_plan(*_args, **_kwargs):
        approved.append("plan")
        raise AssertionError("approve_plan")

    monkeypatch.setattr(relay_ops, "draft_plan", draft_plan)
    monkeypatch.setattr(relay_ops, "approve_plan", approve_plan)
    paused = auto_run.run(root, request, dismissed)
    assert "plan" not in approved
    assert paused["phase"] == "plan"
    assert "draft-plan.md" in paused["pause"]["reason"]
    assert paused["pause"]["actions"] == ["resume", "change", "cancel"]
    assert paused["spec"]["sha256"]


def test_matching_phase_artifact_is_not_called_again(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request(replace=True)
    dismissed = auto_run.fingerprint(root, request)
    calls: list[str] = []
    spec_calls: list[str] = []
    plan_calls: list[str] = []
    approved: list = []

    def fake_brainstorm(_root, **_kwargs):
        calls.append("brainstorm")
        _write_synthesis(root, _CLEAN)
        return SessionEvent("output", "saved")

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)

    def draft_spec(_root, text, attachments=(), *, progress):
        calls.append("spec")
        spec_calls.append(text)
        return _draft(root / ".whyline" / "relay" / "draft-spec.md", _SPEC, "spec")

    def approve_spec(_root, draft, _name, *, replace=False):
        approved.append(("spec", replace))
        target = root / "docs" / "specs" / "plan.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft.text, encoding="utf-8")
        return target

    def draft_plan(_root, description, attachments=(), *, progress, spec=None):
        calls.append("plan")
        plan_calls.append(description)
        return _draft(root / ".whyline" / "relay" / "draft-plan.md", _PLAN, "planner")

    def approve_plan(_root, draft, _name, *, replace=False, spec=""):
        approved.append(("plan", replace))
        target = root / "plans" / "plan.plan.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft.text, encoding="utf-8")
        return target

    monkeypatch.setattr(relay_ops, "draft_spec", draft_spec)
    monkeypatch.setattr(relay_ops, "approve_spec", approve_spec)
    monkeypatch.setattr(relay_ops, "draft_plan", draft_plan)
    monkeypatch.setattr(relay_ops, "approve_plan", approve_plan)
    first = auto_run.run(root, request, dismissed, through="plan")
    assert calls == ["brainstorm", "spec", "plan"]
    assert first["phase"] == "plan"
    assert approved == [("spec", True), ("plan", True)]
    auto_run.run(root, request, dismissed, through="plan")
    assert calls == ["brainstorm", "spec", "plan"]


def test_spec_and_plan_failures_walk_only_the_saved_chain(tmp_path, monkeypatch):
    from whyline_relay import agents

    root = _repo(tmp_path)
    request = _request(chain=("codex",))
    dismissed = auto_run.fingerprint(root, request)
    seen: list[tuple[str, tuple[str, str]]] = []

    def fake_brainstorm(_root, **_kwargs):
        _write_synthesis(root, _CLEAN)
        return SessionEvent("output", "saved")

    def draft_spec(_root, _text, _attachments=(), *, progress):
        roles = relay_ops.planner_agents(root)
        seen.append(("spec", roles))
        if roles[0] == "claude":
            raise agents.AgentTimeout("claude timed out")
        return _draft(root / ".whyline" / "relay" / "draft-spec.md", _SPEC, "spec")

    def approve_spec(_root, draft, _name, *, replace=False):
        target = root / "docs" / "specs" / "plan.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft.text, encoding="utf-8")
        return target

    def draft_plan(_root, _description, _attachments=(), *, progress, spec=None):
        roles = relay_ops.planner_agents(root)
        seen.append(("plan", roles))
        if roles[0] == "claude":
            raise agents.AgentTimeout("claude timed out")
        return _draft(root / ".whyline" / "relay" / "draft-plan.md", _PLAN, "planner")

    def approve_plan(_root, draft, _name, *, replace=False, spec=""):
        target = root / "plans" / "plan.plan.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft.text, encoding="utf-8")
        return target

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    monkeypatch.setattr(relay_ops, "draft_spec", draft_spec)
    monkeypatch.setattr(relay_ops, "approve_spec", approve_spec)
    monkeypatch.setattr(relay_ops, "draft_plan", draft_plan)
    monkeypatch.setattr(relay_ops, "approve_plan", approve_plan)

    finished = auto_run.run(root, request, dismissed, through="plan")
    assert finished["phase"] == "plan"
    assert seen == [
        ("spec", ("claude", "codex")),
        ("spec", ("codex", "codex")),
        ("plan", ("claude", "codex")),
        ("plan", ("codex", "codex")),
    ]
    assert relay_ops.planner_agents(root) == ("claude", "codex")


def _planner_no_handoff(agent: str):
    """The pause `planner._drive_pipeline` raises after a nonzero exit.

    `agents.run` returns the exit code. The planner does not chain
    `AgentTimeout` or `AgentMissing` onto this exception.
    """
    from whyline_relay import loop

    error = loop.Paused(
        f"{agent} exited without handing off; nothing was routed",
        None,
    )
    assert error.__cause__ is None
    raise error


def test_nonzero_exit_without_handoff_walks_only_the_saved_chain(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request(chain=("codex",))
    dismissed = auto_run.fingerprint(root, request)
    seen: list[tuple[str, tuple[str, str]]] = []

    def fake_brainstorm(_root, **_kwargs):
        _write_synthesis(root, _CLEAN)
        return SessionEvent("output", "saved")

    def draft_spec(_root, _text, _attachments=(), *, progress):
        roles = relay_ops.planner_agents(root)
        seen.append(("spec", roles))
        progress(f"{roles[0]} is drafting the spec")
        if roles[0] != "codex":
            _planner_no_handoff(roles[0])
        return _draft(root / ".whyline" / "relay" / "draft-spec.md", _SPEC, "spec")

    def approve_spec(_root, draft, _name, *, replace=False):
        target = root / "docs" / "specs" / "plan.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft.text, encoding="utf-8")
        return target

    def draft_plan(_root, _description, _attachments=(), *, progress, spec=None):
        roles = relay_ops.planner_agents(root)
        seen.append(("plan", roles))
        progress(f"{roles[0]} is drafting the plan")
        if roles[0] != "codex":
            _planner_no_handoff(roles[0])
        return _draft(root / ".whyline" / "relay" / "draft-plan.md", _PLAN, "planner")

    def approve_plan(_root, draft, _name, *, replace=False, spec=""):
        target = root / "plans" / "plan.plan.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft.text, encoding="utf-8")
        return target

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    monkeypatch.setattr(relay_ops, "draft_spec", draft_spec)
    monkeypatch.setattr(relay_ops, "approve_spec", approve_spec)
    monkeypatch.setattr(relay_ops, "draft_plan", draft_plan)
    monkeypatch.setattr(relay_ops, "approve_plan", approve_plan)

    finished = auto_run.run(root, request, dismissed, through="plan")
    assert finished["phase"] == "plan"
    assert "pause" not in finished
    assert seen == [
        ("spec", ("claude", "codex")),
        ("spec", ("codex", "codex")),
        ("plan", ("claude", "codex")),
        ("plan", ("codex", "codex")),
    ]
    assert relay_ops.planner_agents(root) == ("claude", "codex")
    assert "grok" not in {agent for _phase, roles in seen for agent in roles}


def test_nonzero_exit_without_handoff_pauses_with_every_agent_tried(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request(chain=("codex",))
    dismissed = auto_run.fingerprint(root, request)
    spec_roles: list[tuple[str, str]] = []
    plan_roles: list[tuple[str, str]] = []

    def fake_brainstorm(_root, **kwargs):
        _write_synthesis(root, _CLEAN, topic=kwargs["topic"])
        return SessionEvent("output", "saved")

    def draft_spec(_root, _text, _attachments=(), *, progress):
        roles = relay_ops.planner_agents(root)
        spec_roles.append(roles)
        progress(f"{roles[0]} is drafting the spec")
        _planner_no_handoff(roles[0])

    def approve_spec(*_args, **_kwargs):
        raise AssertionError("approve_spec")

    def draft_plan(*_args, **_kwargs):
        raise AssertionError("draft_plan")

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    monkeypatch.setattr(relay_ops, "draft_spec", draft_spec)
    monkeypatch.setattr(relay_ops, "approve_spec", approve_spec)
    monkeypatch.setattr(relay_ops, "draft_plan", draft_plan)

    paused = auto_run.run(root, request, dismissed)
    assert spec_roles == [("claude", "codex"), ("codex", "codex")]
    assert "grok" not in {agent for roles in spec_roles for agent in roles}
    assert "antigravity" not in {agent for roles in spec_roles for agent in roles}
    assert paused["phase"] == "spec"
    assert "claude" in paused["pause"]["reason"]
    assert "codex" in paused["pause"]["reason"]
    assert "Backup chain exhausted" in paused["pause"]["reason"]
    assert paused["pause"]["actions"] == ["resume", "change", "cancel"]

    (root / ".whyline" / "relay" / "auto-run.json").unlink()
    plan_request = _request(topic="plan-exit", chain=("codex",))
    plan_dismissed = auto_run.fingerprint(root, plan_request)

    def succeeding_spec(_root, _text, _attachments=(), *, progress):
        progress("claude is drafting the spec")
        return _draft(root / ".whyline" / "relay" / "draft-spec.md", _SPEC, "spec")

    def approve_spec_now(_root, draft, _name, *, replace=False):
        target = root / "docs" / "specs" / "plan.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft.text, encoding="utf-8")
        return target

    def failing_plan(_root, _description, _attachments=(), *, progress, spec=None):
        roles = relay_ops.planner_agents(root)
        plan_roles.append(roles)
        progress(f"{roles[0]} is drafting the plan")
        _planner_no_handoff(roles[0])

    def approve_plan(*_args, **_kwargs):
        raise AssertionError("approve_plan")

    monkeypatch.setattr(relay_ops, "draft_spec", succeeding_spec)
    monkeypatch.setattr(relay_ops, "approve_spec", approve_spec_now)
    monkeypatch.setattr(relay_ops, "draft_plan", failing_plan)
    monkeypatch.setattr(relay_ops, "approve_plan", approve_plan)

    plan_pause = auto_run.run(root, plan_request, plan_dismissed)
    assert plan_roles == [("claude", "codex"), ("codex", "codex")]
    assert "grok" not in {agent for roles in plan_roles for agent in roles}
    assert plan_pause["phase"] == "plan"
    assert "claude" in plan_pause["pause"]["reason"]
    assert "codex" in plan_pause["pause"]["reason"]
    assert "Backup chain exhausted" in plan_pause["pause"]["reason"]
    assert plan_pause["pause"]["actions"] == ["resume", "change", "cancel"]


def test_exhausted_chain_pauses_with_the_agents_tried(tmp_path, monkeypatch):
    from whyline_relay import agents

    root = _repo(tmp_path)
    request = _request(
        agents=("claude", "codex"), final_agent="claude", chain=("codex",)
    )
    dismissed = auto_run.fingerprint(root, request)
    called: list[str] = []
    rosters: list[list[str]] = []

    def fake_brainstorm(_root, **kwargs):
        agent = kwargs["final_agent"]
        called.append(agent)
        rosters.append(kwargs["agents"])
        raise agents.AgentTimeout(f"{agent} exceeded 1s and was terminated")

    def fail_spec(*_args, **_kwargs):
        raise AssertionError("draft_spec")

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    monkeypatch.setattr(relay_ops, "draft_spec", fail_spec)
    paused = auto_run.run(root, request, dismissed)
    assert called == ["claude", "codex"]
    assert rosters == [["claude", "codex"], ["codex"]]
    assert "grok" not in called
    assert "antigravity" not in called
    assert "claude" in paused["pause"]["reason"]
    assert "codex" in paused["pause"]["reason"]
    assert paused["pause"]["actions"] == ["resume", "change", "cancel"]
    assert paused["phase"] == "research"


def _touch_config(root: Path) -> None:
    path = root / ".whyline" / "relay" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("timeout_minutes = 15\n", encoding="utf-8")


def _approve_target(root: Path, draft, relative: str) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(draft.text, encoding="utf-8")
    return target


def test_saved_spec_pause_reenters_resume_spec(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    _touch_config(root)
    request = _request()
    calls: list[str] = []

    def pending(_root):
        calls.append("pending_spec")
        return "Write the spec"

    def resume_spec(_root, *, progress):
        calls.append("resume_spec")
        return _draft(root / ".whyline" / "relay" / "draft-spec.md", _SPEC, "spec")

    def draft_spec(*_args, **_kwargs):
        calls.append("draft_spec")
        raise AssertionError("draft_spec")

    def approve_spec(_root, draft, _name, *, replace=False):
        calls.append("approve_spec")
        return _approve_target(root, draft, "docs/specs/plan.md")

    monkeypatch.setattr(relay_ops, "pending_spec", pending)
    monkeypatch.setattr(relay_ops, "resume_spec", resume_spec)
    monkeypatch.setattr(relay_ops, "draft_spec", draft_spec)
    monkeypatch.setattr(relay_ops, "approve_spec", approve_spec)
    current = {
        "phase": "spec",
        "pause": {
            "reason": "visit cap\nDraft: .whyline/relay/draft-spec.md",
            "actions": ["resume", "change", "cancel"],
        },
        "spec": {"path": None, "sha256": None},
    }
    result = auto_run._spec_phase(
        root, request, current, saved_phase="spec", progress=None, answer=None
    )
    assert calls == ["pending_spec", "resume_spec", "approve_spec"]
    assert result["phase"] == "spec"
    assert "pause" not in result


def test_saved_plan_pause_reenters_resume_draft(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    _touch_config(root)
    request = _request()
    calls: list[str] = []
    spec = root / "docs" / "specs" / "plan.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(_SPEC, encoding="utf-8")

    def pending(_root):
        calls.append("pending_draft")
        return "topic"

    def resume_draft(_root, *, progress):
        calls.append("resume_draft")
        return _draft(root / ".whyline" / "relay" / "draft-plan.md", _PLAN, "planner")

    def draft_plan(*_args, **_kwargs):
        calls.append("draft_plan")
        raise AssertionError("draft_plan")

    def approve_plan(_root, draft, _name, *, replace=False, spec=""):
        calls.append("approve_plan")
        return _approve_target(root, draft, "plans/plan.plan.md")

    monkeypatch.setattr(relay_ops, "pending_draft", pending)
    monkeypatch.setattr(relay_ops, "resume_draft", resume_draft)
    monkeypatch.setattr(relay_ops, "draft_plan", draft_plan)
    monkeypatch.setattr(relay_ops, "approve_plan", approve_plan)
    current = {
        "phase": "plan",
        "pause": {
            "reason": "visit cap\nDraft: .whyline/relay/draft-plan.md",
            "actions": ["resume", "change", "cancel"],
        },
        "spec": {"path": str(spec), "sha256": hashlib.sha256(_SPEC.encode()).hexdigest()},
        "plan": {"path": None, "sha256": None},
    }
    result = auto_run._plan_phase(
        root, request, current, saved_phase="plan", progress=None, answer=None
    )
    assert calls == ["pending_draft", "resume_draft", "approve_plan"]
    assert result["phase"] == "plan"
    assert "pause" not in result


def test_resumed_run_reenters_resume_spec_and_resume_draft(tmp_path, monkeypatch):
    from whyline_relay import loop

    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    calls: list[str] = []
    drafted = {"spec": 0, "plan": 0}

    def fake_brainstorm(_root, **_kwargs):
        _write_synthesis(root, _CLEAN)
        return SessionEvent("output", "saved")

    def pending_spec(_root):
        return "Write the spec" if drafted["spec"] else None

    def draft_spec(_root, _text, _attachments=(), *, progress):
        drafted["spec"] += 1
        calls.append("draft_spec")
        raise loop.Paused(
            "__spec__ hit stage 'review''s 3-visit cap without reaching \"@complete\"",
            None,
        )

    def resume_spec(_root, *, progress):
        calls.append("resume_spec")
        return _draft(root / ".whyline" / "relay" / "draft-spec.md", _SPEC, "spec")

    def approve_spec(_root, draft, _name, *, replace=False):
        calls.append("approve_spec")
        return _approve_target(root, draft, "docs/specs/plan.md")

    def pending_draft(_root):
        return "topic" if drafted["plan"] else None

    def draft_plan(_root, _description, _attachments=(), *, progress, spec=None):
        drafted["plan"] += 1
        calls.append("draft_plan")
        raise loop.Paused(
            "__plan__ hit stage 'review''s 3-visit cap without reaching \"@complete\"",
            None,
        )

    def resume_draft(_root, *, progress):
        calls.append("resume_draft")
        return _draft(root / ".whyline" / "relay" / "draft-plan.md", _PLAN, "planner")

    def approve_plan(_root, draft, _name, *, replace=False, spec=""):
        calls.append("approve_plan")
        return _approve_target(root, draft, "plans/plan.plan.md")

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    monkeypatch.setattr(relay_ops, "pending_spec", pending_spec)
    monkeypatch.setattr(relay_ops, "draft_spec", draft_spec)
    monkeypatch.setattr(relay_ops, "resume_spec", resume_spec)
    monkeypatch.setattr(relay_ops, "approve_spec", approve_spec)
    monkeypatch.setattr(relay_ops, "pending_draft", pending_draft)
    monkeypatch.setattr(relay_ops, "draft_plan", draft_plan)
    monkeypatch.setattr(relay_ops, "resume_draft", resume_draft)
    monkeypatch.setattr(relay_ops, "approve_plan", approve_plan)

    spec_pause = auto_run.run(root, request, dismissed)
    assert spec_pause["phase"] == "spec"
    assert "visit cap" in spec_pause["pause"]["reason"]
    assert calls == ["draft_spec"]

    plan_pause = auto_run.run(root, request, dismissed)
    assert plan_pause["phase"] == "plan"
    assert calls == ["draft_spec", "resume_spec", "approve_spec", "draft_plan"]

    finished = auto_run.run(root, request, dismissed, through="plan")
    assert calls == [
        "draft_spec",
        "resume_spec",
        "approve_spec",
        "draft_plan",
        "resume_draft",
        "approve_plan",
    ]
    assert finished["phase"] == "plan"
    assert "pause" not in finished


def test_final_synthesis_does_not_substitute_outside_the_chain(tmp_path, monkeypatch):
    from whyline_relay import agents, brainstorm, chat, config

    root = _repo(tmp_path)
    request = _request(agents=("claude", "grok"), final_agent="claude", chain=("codex",))
    dismissed = auto_run.fingerprint(root, request)
    attempted: list[str] = []
    research = (
        "# Topic\n\n## Claude\n\nClaude's research.\n\n"
        "## Grok\n\nGrok's research.\n\n"
        "## Codex\n\nCodex's research.\n"
    )

    def fake_turn(_root, *, agent, **_kwargs):
        attempted.append(agent)
        if agent != "codex":
            raise agents.AgentTimeout(f"{agent} exceeded 1s and was terminated")
        _write_synthesis(root, _CLEAN)
        return {"ok": True, "agent": agent, "response": "done"}

    def fake_brainstorm(root, **kwargs):
        _write_synthesis(root, research, topic=kwargs["topic"])
        labels = {"claude": "Claude", "grok": "Grok", "codex": "Codex"}
        models = [(agent, labels.get(agent, agent)) for agent in kwargs["agents"]]
        brainstorm.run_final_synthesis(
            root,
            kwargs["final_agent"],
            models,
            kwargs["topic"],
            settings=config.load(root),
            print_fn=lambda _line="": None,
        )
        return SessionEvent("output", "saved")

    monkeypatch.setattr(chat, "run_turn", fake_turn)
    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    _install_planning(monkeypatch, root, [], [], [])
    finished = auto_run.run(root, request, dismissed, through="plan")
    assert attempted == ["claude", "codex"]
    assert "grok" not in attempted
    assert finished["phase"] == "plan"
    assert "pause" not in finished


def test_blocked_brainstorm_pauses_without_drafting_a_spec(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)

    def fake_brainstorm(_root, **_kwargs):
        _write_synthesis(root, _CLEAN)
        return SessionEvent("error", "the brainstorm reported blocked: need a human")

    def fail_spec(*_args, **_kwargs):
        raise AssertionError("draft_spec")

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    monkeypatch.setattr(relay_ops, "draft_spec", fail_spec)
    paused = auto_run.run(root, request, dismissed)
    assert paused["phase"] == "research"
    assert "blocked" in paused["pause"]["reason"]
    assert paused["brainstorm"]["sha256"]
    assert paused["pause"]["actions"] == ["resume", "change", "cancel"]


class _Check:
    def __init__(self, status, message, hint=None):
        self.status = status
        self.message = message
        self.hint = hint


_BRAIN_COMMIT = 'brainstorm: claude final synthesis on "topic"'
_SPEC_COMMIT = "docs: add spec plan"
_PLAN_COMMIT = "docs: add plan plans/plan.plan.md"
_CONFIG_COMMIT = "setup: auto run roles, backup, and timeout"


def _commit_rel(root: Path, path: Path, message: str) -> None:
    relative = path.relative_to(root).as_posix()
    _git(root, "add", "--", relative)
    _git(root, "commit", "-qm", message, "--", relative)


def _subjects(root: Path) -> list[str]:
    return _git(root, "log", "--format=%s").splitlines()


def _assert_one_commit_each(root: Path) -> None:
    subjects = _subjects(root)
    assert subjects.count(_CONFIG_COMMIT) == 1
    assert subjects.count(_BRAIN_COMMIT) == 1
    assert subjects.count(_SPEC_COMMIT) == 1
    assert subjects.count(_PLAN_COMMIT) == 1


def _passing_checks(scope: str) -> list[_Check]:
    if scope == "repository":
        return [_Check("ok", "working tree is clean")]
    return [
        _Check("ok", "plan parses and has unchecked tasks"),
        _Check("warn", "grok is a generic agent"),
    ]


def _install_committed(monkeypatch, root, calls, launched, trace, checks):
    """Commit each artifact from the fakes, and let `checks(scope)` answer preflight."""
    from whyline_relay import preflight

    real_select = relay_ops.select_plan

    def fake_brainstorm(_root, **kwargs):
        calls.append("brainstorm")
        path = _write_synthesis(root, _CLEAN, topic=kwargs.get("topic", "topic"))
        _commit_rel(root, path, _BRAIN_COMMIT)
        return SessionEvent("output", "saved")

    def draft_spec(_root, _text, _attachments=(), *, progress):
        calls.append("spec")
        return _draft(root / ".whyline" / "relay" / "draft-spec.md", _SPEC, "spec")

    def approve_spec(_root, draft, _name, *, replace=False):
        calls.append("approve_spec")
        target = root / "docs" / "specs" / "plan.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft.text, encoding="utf-8")
        _commit_rel(root, target, _SPEC_COMMIT)
        return target

    def draft_plan(_root, _description, _attachments=(), *, progress, spec=None):
        calls.append("plan")
        return _draft(root / ".whyline" / "relay" / "draft-plan.md", _PLAN, "planner")

    def approve_plan(_root, draft, _name, *, replace=False, spec=""):
        calls.append("approve_plan")
        target = root / "plans" / "plan.plan.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft.text, encoding="utf-8")
        _commit_rel(root, target, _PLAN_COMMIT)
        return target

    def spy_select(target_root, path):
        trace.append("select")
        real_select(target_root, path)

    def fake_preflight(_root, plan_path=None, **kwargs):
        scope = kwargs.get("scope", "full")
        assert kwargs.get("allow_dirty", False) is False
        trace.append(("preflight", scope, plan_path))
        return checks(scope)

    def launcher(args):
        launched.append(list(args))

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    monkeypatch.setattr(relay_ops, "draft_spec", draft_spec)
    monkeypatch.setattr(relay_ops, "approve_spec", approve_spec)
    monkeypatch.setattr(relay_ops, "draft_plan", draft_plan)
    monkeypatch.setattr(relay_ops, "approve_plan", approve_plan)
    monkeypatch.setattr(relay_ops, "select_plan", spy_select)
    monkeypatch.setattr(preflight, "run", fake_preflight)
    return launcher


def _checkpoint(root: Path) -> dict:
    return json.loads(
        (root / ".whyline" / "relay" / "auto-run.json").read_text(encoding="utf-8")
    )


def test_clean_run_commits_each_artifact_and_launches_once(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request()
    assert request.release == "human"
    dismissed = auto_run.fingerprint(root, request)
    calls: list[str] = []
    launched: list[list[str]] = []
    trace: list = []
    lines: list[str] = []
    launcher = _install_committed(monkeypatch, root, calls, launched, trace, _passing_checks)
    finished = auto_run.run(
        root, request, dismissed, progress=lines.append, launcher=launcher
    )
    assert calls == ["brainstorm", "spec", "approve_spec", "plan", "approve_plan"]
    assert finished["phase"] == "relay"
    assert "pause" not in finished
    assert launched == [["start"]]
    assert "auto · final preflight" in lines
    _assert_one_commit_each(root)
    plan = root / "plans" / "plan.plan.md"
    assert trace[0] == "select"
    assert ("preflight", "full", plan) in trace
    # A warn is not a FAIL, and release human does not skip the launch.
    assert any(check.status == "warn" for check in _passing_checks("full"))
    event = threading.Event()
    auto_run.close_console(root, event)
    assert not event.is_set()
    assert _checkpoint(root)["phase"] == "relay"
    # Preflight runs again. The relay is already started, so start is not repeated.
    again = auto_run.resume(root, request, progress=lines.append, launcher=launcher)
    assert again["phase"] == "relay"
    assert launched == [["start"]]
    assert calls == ["brainstorm", "spec", "approve_spec", "plan", "approve_plan"]
    assert sum(1 for item in trace if item[:2] == ("preflight", "full")) == 2
    _assert_one_commit_each(root)


def test_final_preflight_fail_keeps_artifacts_and_resume_reruns_it(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    calls: list[str] = []
    launched: list[list[str]] = []
    trace: list = []
    lines: list[str] = []
    state = {"fail": True}

    def checks(scope):
        if scope == "repository":
            return [_Check("ok", "working tree is clean")]
        if state["fail"]:
            return [_Check("FAIL", "no unchecked tasks in plans/plan.plan.md", "add one")]
        return _passing_checks("full")

    launcher = _install_committed(monkeypatch, root, calls, launched, trace, checks)
    paused = auto_run.run(root, request, dismissed, progress=lines.append, launcher=launcher)
    assert launched == []
    assert paused["phase"] == "preflight"
    assert "no unchecked tasks" in paused["pause"]["reason"]
    assert "Set up can open on that plan." in paused["pause"]["reason"]
    assert paused["pause"]["actions"] == ["resume", "change", "cancel"]
    assert "auto · final preflight" in lines
    assert "no unchecked tasks" in "\n".join(lines)
    _assert_one_commit_each(root)
    assert (root / "docs" / "specs" / "plan.md").is_file()
    assert (root / "plans" / "plan.plan.md").is_file()
    kept = calls.copy()
    state["fail"] = False
    finished = auto_run.resume(root, request, progress=lines.append, launcher=launcher)
    assert calls == kept
    assert finished["phase"] == "relay"
    assert launched == [["start"]]
    assert sum(1 for item in trace if item[:2] == ("preflight", "full")) == 2
    _assert_one_commit_each(root)


def test_stop_after_each_artifact_and_resume_skips_a_matching_hash(tmp_path, monkeypatch):
    from whyline_relay import agents

    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    calls: list[str] = []
    launched: list[list[str]] = []
    trace: list = []
    launcher = _install_committed(
        monkeypatch, root, calls, launched, trace, _passing_checks
    )
    armed = {"research", "spec", "plan"}
    active = {"event": threading.Event()}
    original = auto_run._save

    def tracing_save(target, current):
        written = original(target, current)
        phase = current.get("phase")
        if phase in armed and "pause" not in current:
            armed.remove(phase)
            auto_run.stop(target, active["event"])
            raise agents.AgentCancelled(f"stopped after {phase}")
        return written

    monkeypatch.setattr(auto_run, "_save", tracing_save)

    def again():
        active["event"] = threading.Event()
        return auto_run.resume(root, request, cancel_event=active["event"], launcher=launcher)

    first = auto_run.run(
        root, request, dismissed, cancel_event=active["event"], launcher=launcher
    )
    assert first["phase"] == "stopped"
    assert calls == ["brainstorm"]
    assert _subjects(root).count(_BRAIN_COMMIT) == 1

    second = again()
    assert second["phase"] == "stopped"
    assert calls == ["brainstorm", "spec", "approve_spec"]

    third = again()
    assert third["phase"] == "stopped"
    assert calls == ["brainstorm", "spec", "approve_spec", "plan", "approve_plan"]

    finished = again()
    assert finished["phase"] == "relay"
    assert calls == ["brainstorm", "spec", "approve_spec", "plan", "approve_plan"]
    assert launched == [["start"]]
    _assert_one_commit_each(root)
    assert sum(1 for item in trace if item[:2] == ("preflight", "repository")) == 3


def test_close_during_research_sets_cancel_and_stops(tmp_path, monkeypatch):
    from whyline_relay import agents

    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    cancel = threading.Event()
    started = threading.Event()
    calls: list[str] = []
    launched: list[list[str]] = []

    def fake_brainstorm(_root, **_kwargs):
        calls.append("brainstorm")
        started.set()
        if not cancel.wait(5):
            raise AssertionError("cancel event was not set")
        raise agents.AgentCancelled("closed")

    def fail_spec(*_args, **_kwargs):
        calls.append("spec")
        raise AssertionError("draft_spec")

    def launcher(args):
        launched.append(list(args))

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    monkeypatch.setattr(relay_ops, "draft_spec", fail_spec)
    holder: dict = {}

    def worker():
        try:
            holder["result"] = auto_run.run(
                root, request, dismissed, cancel_event=cancel, launcher=launcher
            )
        except BaseException as error:
            holder["error"] = error

    thread = threading.Thread(target=worker)
    thread.start()
    assert started.wait(5)
    auto_run.close_console(root, cancel)
    thread.join(5)
    assert not thread.is_alive()
    assert "error" not in holder
    assert cancel.is_set()
    assert holder["result"]["phase"] == "stopped"
    assert _checkpoint(root)["phase"] == "stopped"
    assert calls == ["brainstorm"]
    assert launched == []
    assert not _lock(root).exists()


def test_resume_live_lock_fails(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    auto_run.run(root, request, dismissed, through="persist")
    _lock(root).write_text(f"{os.getpid()}\n", encoding="utf-8")
    calls: list[str] = []

    def boom(*_args, **_kwargs):
        calls.append("brainstorm")
        raise AssertionError("model started")

    monkeypatch.setattr(adapters, "run_brainstorm", boom)
    monkeypatch.setattr(
        __import__("whyline_relay.preflight", fromlist=["run"]),
        "run",
        lambda *_args, **_kwargs: [_Check("ok", "working tree is clean")],
    )
    with pytest.raises(auto_run.AutoBusy):
        auto_run.resume(root, request)
    assert calls == []
    assert int(_lock(root).read_text(encoding="utf-8").strip()) == os.getpid()
    assert _checkpoint(root)["phase"] == "persist"


def test_resume_dead_lock_is_taken(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    auto_run.run(root, request, dismissed, through="persist")
    _lock(root).write_text(f"{_dead_pid()}\n", encoding="utf-8")
    calls: list[str] = []
    launched: list[list[str]] = []
    seen: dict = {}

    def fake_brainstorm(_root, **_kwargs):
        calls.append("brainstorm")
        seen["pid"] = int(_lock(root).read_text(encoding="utf-8").strip())
        _write_synthesis(root, _CLEAN)
        _commit_rel(root, _write_synthesis(root, _CLEAN), _BRAIN_COMMIT)
        return SessionEvent("output", "saved")

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    launcher = _install_committed(monkeypatch, root, calls, launched, [], _passing_checks)
    # The installer replaced brainstorm. Put the pid-recording fake back on top.
    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)
    finished = auto_run.resume(root, request, launcher=launcher)
    assert seen["pid"] == os.getpid()
    assert "brainstorm" in calls
    assert finished["phase"] == "relay"
    assert launched == [["start"]]
    assert not _lock(root).exists()


def test_resume_form_mismatch_does_not_start_a_model(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    auto_run.run(root, request, dismissed, through="persist")

    def boom(*_args, **_kwargs):
        raise AssertionError("model started")

    monkeypatch.setattr(adapters, "run_brainstorm", boom)
    with pytest.raises(auto_run.AutoStale, match="out of date"):
        auto_run.resume(root, _request(topic="other"))
    assert _checkpoint(root)["phase"] == "persist"
    assert _subjects(root).count(_CONFIG_COMMIT) == 1
    assert not (root / "docs" / "brainstorm").exists()


def test_resume_repository_fail_does_not_start_a_model(tmp_path, monkeypatch):
    from whyline_relay import preflight

    root = _repo(tmp_path)
    request = _request()
    auto_run.run(root, request, auto_run.fingerprint(root, request), through="persist")

    def boom(*_args, **_kwargs):
        raise AssertionError("model started")

    def fake_preflight(_root, plan_path=None, **kwargs):
        assert kwargs.get("scope") == "repository"
        assert kwargs.get("allow_dirty", False) is False
        return [
            _Check(
                "FAIL",
                "working tree has uncommitted changes: README.md",
                "commit or stash your changes",
            )
        ]

    monkeypatch.setattr(adapters, "run_brainstorm", boom)
    monkeypatch.setattr(preflight, "run", fake_preflight)
    with pytest.raises(auto_run.AutoStale, match="uncommitted changes"):
        auto_run.resume(root, request)
    assert _checkpoint(root)["phase"] == "persist"


def test_resume_ignores_the_pre_persist_head(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    auto_run.run(root, request, dismissed, through="persist")
    (root / "note.md").write_text("n\n", encoding="utf-8")
    _git(root, "add", "--", "note.md")
    _git(root, "commit", "-qm", "unrelated")
    saved = _checkpoint(root)
    assert saved["fingerprint"] != auto_run.fingerprint(root, request)
    assert saved["request"] == auto_run.form_document(root, request)
    calls: list[str] = []
    launched: list[list[str]] = []
    launcher = _install_committed(monkeypatch, root, calls, launched, [], _passing_checks)
    finished = auto_run.resume(root, request, launcher=launcher)
    assert calls[0] == "brainstorm"
    assert finished["phase"] == "relay"
    assert launched == [["start"]]


def test_auto_pause_decision_log_only_commits_resumes_and_calls_launcher_once(tmp_path, monkeypatch):
    from whyline_relay import gitcheck

    root = _repo(tmp_path)
    subprocess.run(["whyline", "init", "--yes"], cwd=root, check=True)
    gitcheck.ensure_relay_ignored(root)
    (root / ".whyline" / "relay").mkdir(parents=True, exist_ok=True)
    (root / ".whyline" / "relay" / "claude-settings.json").write_text("{}\n", encoding="utf-8")
    (root / "plan.md").write_text("# Plan\n- [ ] REC-4: Task\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "setup"], cwd=root, check=True)

    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    auto_run.run(root, request, dismissed, through="persist")

    cp_path = auto_run.checkpoint_path(root)
    saved = auto_run.load_object(cp_path)
    saved["phase"] = "relay"
    saved["pause"] = {"reason": "paused with uncommitted changes", "actions": ["resume", "change", "cancel", "recover"]}
    auto_run.atomic_write_json(cp_path, saved)

    state_file = root / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "dirty",
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )

    (root / ".whyline" / "decisions.md").write_text("# Decisions\n- [2026-10-14] Test note\n", encoding="utf-8")

    launched: list[list[str]] = []
    lines: list[str] = []

    res = auto_run.resume(root, request, progress=lines.append, launcher=lambda args: launched.append(list(args)))

    assert res["phase"] == "relay"
    assert "pause" not in res
    assert launched == [["resume"]]
    assert "auto · recover decision-log" in lines
    status = _git(root, "status", "--porcelain")
    assert status == ""


def test_auto_no_handoff_pause_resumes_with_fake_agent(tmp_path, monkeypatch):
    from whyline_relay import gitcheck

    root = _repo(tmp_path)
    subprocess.run(["whyline", "init", "--yes"], cwd=root, check=True)
    gitcheck.ensure_relay_ignored(root)
    (root / ".whyline" / "relay").mkdir(parents=True, exist_ok=True)
    (root / ".whyline" / "relay" / "claude-settings.json").write_text("{}\n", encoding="utf-8")
    (root / "plan.md").write_text("# Plan\n- [ ] REC-4: Task\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "setup"], cwd=root, check=True)

    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    auto_run.run(root, request, dismissed, through="persist")

    cp_path = auto_run.checkpoint_path(root)
    saved = auto_run.load_object(cp_path)
    saved["phase"] = "relay"
    saved["pause"] = {"reason": "codex exited without handing off", "actions": ["resume", "change", "cancel", "recover"]}
    auto_run.atomic_write_json(cp_path, saved)

    state_file = root / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": "codex exited without handing off",
            "log_path": "round.log",
            "last_handoff_id": "old-100",
        }),
        encoding="utf-8",
    )
    (root / ".whyline" / "active-handoff.json").write_text(
        json.dumps({
            "v": 1,
            "id": "old-100",
            "type": "Handoff",
            "task": "REC-4",
            "status": "in-progress",
            "from_actor": "codex",
            "to_actor": "claude",
        }),
        encoding="utf-8",
    )

    def fake_runner(command, prompt, **kwargs):
        (root / ".whyline" / "active-handoff.json").write_text(
            json.dumps({
                "v": 1,
                "id": "new-200",
                "type": "Handoff",
                "task": "REC-4",
                "status": "ready-for-review",
                "from_actor": "codex",
                "to_actor": "claude",
            }),
            encoding="utf-8",
        )
        return "RECOVERY: resolved\n"

    launched: list[list[str]] = []
    lines: list[str] = []

    res = auto_run.resume(
        root,
        request,
        progress=lines.append,
        launcher=lambda args: launched.append(list(args)),
        runner=fake_runner,
    )

    assert res["phase"] == "relay"
    assert "pause" not in res
    assert launched == [["resume"]]
    assert "auto · recover no-handoff · codex" in lines


def test_auto_auth_pause_does_not_call_runner_and_keeps_pause(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    auto_run.run(root, request, dismissed, through="persist")

    cp_path = auto_run.checkpoint_path(root)
    saved = auto_run.load_object(cp_path)
    saved["phase"] = "relay"
    auth_reason = "codex is no longer logged in; try again once you've signed back in"
    saved["pause"] = {"reason": auth_reason, "actions": ["resume", "change", "cancel", "recover"]}
    auto_run.atomic_write_json(cp_path, saved)

    state_file = root / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": auth_reason,
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )

    called = False

    def boom(command, prompt, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("runner should not be called")

    launched: list[list[str]] = []
    lines: list[str] = []

    res = auto_run.resume(
        root,
        request,
        progress=lines.append,
        launcher=lambda args: launched.append(list(args)),
        runner=boom,
    )

    assert called is False
    assert launched == []
    assert "pause" in res
    assert "is no longer logged in" in res["pause"]["reason"]


def test_auto_failover_recovery_writes_override_and_resumes(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    request = _request()
    dismissed = auto_run.fingerprint(root, request)
    auto_run.run(root, request, dismissed, through="persist")

    from whyline_relay import failover

    (root / ".whyline" / "relay" / "config.toml").write_text(
        'plan = "plan.md"\n[roles]\nimplementer = "codex"\nreviewer = "claude"\n[backup]\nchain = ["grok"]\n',
        encoding="utf-8",
    )

    cp_path = auto_run.checkpoint_path(root)
    saved = auto_run.load_object(cp_path)
    saved["phase"] = "relay"
    rate_reason = "codex hit a usage or rate limit; try again when it resets"
    saved["pause"] = {"reason": rate_reason, "actions": ["resume", "change", "cancel", "recover"]}
    auto_run.atomic_write_json(cp_path, saved)

    state_file = root / ".whyline" / "relay" / "state.json"
    state_file.write_text(
        json.dumps({
            "plan": "plan.md",
            "branch": "main",
            "task_id": "REC-4",
            "round": 1,
            "base_commit": "abc",
            "paused_reason": rate_reason,
            "log_path": "round.log",
        }),
        encoding="utf-8",
    )

    launched: list[list[str]] = []
    lines: list[str] = []

    res = auto_run.resume(
        root,
        request,
        progress=lines.append,
        launcher=lambda args: launched.append(list(args)),
    )

    assert res["phase"] == "relay"
    assert "pause" not in res
    assert launched == [["resume"]]
    assert "auto · recover failover · grok" in lines
    overrides = failover.read_overrides(root)
    assert "implementer" in overrides
    assert overrides["implementer"].agent == "grok"

