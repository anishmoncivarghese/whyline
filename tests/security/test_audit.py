import json
import threading
from types import SimpleNamespace

import pytest

from whyline.security import audit

TRACE = [{"kind": "sink", "file": "a.py", "line": 3, "scope": "f", "description": "d"}]
EVIDENCE = [{"file": "a.py", "line": 3, "description": "seen"}]


def confirmed(fp="C-1"):
    score = {"score": "high", "reason": "r"}
    return {
        "verdict": "confirmed", "fingerprint": fp, "title": "Shell injection",
        "description": "User text reaches a shell.", "root_cause": "rc", "intended_behavior": "ib",
        "trace": TRACE, "evidence": EVIDENCE, "conditions": [],
        "execution": {"attacker_perspective": "a", "payloads": ["x"], "instructions": ["i"], "observed_result": "o"},
        "remediation": {"strategy": "Quote it."},
        "severity": {"likelihood": score, "impact": score, "overall_severity": "high"},
        "confidence": {"score": "high", "reason": "r"},
    }


def needs(fp="N-1"):
    return {
        "verdict": "needs_validation", "fingerprint": fp, "title": "Maybe SSRF", "description": "d",
        "claimed_root_cause": "rc", "trace": TRACE, "evidence": EVIDENCE,
        "blockers": ["no sandbox"], "validation_plan": {"local": "try it"},
    }


def rejected(fp="R-1"):
    return {
        "verdict": "rejected", "fingerprint": fp, "title": "Not real", "description": "d",
        "claimed_root_cause": "rc", "trace": TRACE, "evidence": EVIDENCE, "reason": "guarded",
    }


class FakeAgent:
    def __init__(self, content=None, replies=None):
        self.content = content
        self.replies = list(replies or [])
        self.calls = []

    def __call__(self, agent, prompt, *, cwd, cancel_event):
        self.calls.append(SimpleNamespace(agent=agent, prompt=prompt, cwd=cwd))
        run_dir = next(
            line.split(": ", 1)[1] for line in prompt.splitlines() if line.startswith("Output directory: ")
        )
        reply = self.replies.pop(0) if self.replies else SimpleNamespace(ok=True, failure="", text="")
        if reply.ok and self.content is not None:
            from pathlib import Path

            text = self.content if isinstance(self.content, str) else json.dumps(self.content)
            (Path(run_dir) / "findings.json").write_text(text, encoding="utf-8")
        return reply


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root


def audit_run(repo, tmp_path, agent, **kw):
    return audit.run(repo, agent=kw.pop("name", "claude"), ask_agent=agent, out_dir=tmp_path / "out", **kw)


def test_bundled_method_has_licence_version_and_playbooks():
    assert "MIT" in audit.method_text("LICENSE-cloudflare")
    assert audit.method_version()
    for name in audit.METHOD_FILES:
        assert audit.method_text(name).strip()
    assert audit.load_schema()["type"] == "array"


def test_output_dir_is_outside_the_repo_and_numbered(repo, tmp_path):
    agent = FakeAgent([])
    first = audit_run(repo, tmp_path, agent)
    second = audit_run(repo, tmp_path, agent)
    assert first.run_dir == (tmp_path / "out").resolve() / "project" / "run-1"
    assert second.run_number == 2 and second.run_dir.name == "run-2"
    assert repo not in first.run_dir.parents
    assert list(repo.iterdir()) == []


def test_default_output_dir_is_under_home(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    report = audit.run(repo, agent="claude", ask_agent=FakeAgent([]))
    assert report.run_dir == tmp_path / "home" / ".whyline" / "security" / "audits" / "project" / "run-1"


def test_out_dir_inside_repo_is_refused(repo):
    with pytest.raises(ValueError):
        audit.run(repo, agent="claude", ask_agent=FakeAgent([]), out_dir=repo / "audits")


def test_out_dir_that_is_the_repo_parent_is_refused(repo):
    with pytest.raises(ValueError):
        audit.run(repo, agent="claude", ask_agent=FakeAgent([]), out_dir=repo.parent)
    assert not (repo / "run-1").exists()


def test_prompt_has_the_must_not_lines(repo, tmp_path):
    agent = FakeAgent([])
    report = audit_run(repo, tmp_path, agent)
    prompt = agent.calls[0].prompt
    assert f"Repository to audit: {repo.resolve()}" in prompt
    assert f"Output directory: {report.run_dir}" in prompt
    assert "Do NOT run the project's code" in prompt
    assert "needs_validation" in prompt
    assert "Do NOT modify the repository" in prompt
    assert "findings.json" in prompt and '"oneOf"' in prompt
    assert agent.calls[0].cwd == repo.resolve()


def test_valid_file_becomes_findings_with_verdicts(repo, tmp_path):
    agent = FakeAgent([confirmed(), needs(), rejected(), rejected("R-2")])
    report = audit_run(repo, tmp_path, agent)
    assert report.ok and report.rejected == 2
    assert [(f.rule, f.kind, f.source) for f in report.findings] == [
        ("confirmed", "audit", "audit"), ("needs_validation", "audit", "audit"),
    ]
    top = report.with_verdict("confirmed")[0]
    assert (top.severity, top.path, top.line, top.fix_hint) == ("high", "a.py", 3, "Quote it.")
    assert report.findings[0].fingerprint != report.findings[1].fingerprint


def test_invalid_json_is_kept_and_reported(repo, tmp_path):
    report = audit_run(repo, tmp_path, FakeAgent("[not json"))
    assert not report.ok and report.findings == ()
    assert "the agent's output didn't match the schema" in report.summary
    assert "not valid JSON" in report.summary
    assert (report.run_dir / "findings.json").read_text() == "[not json"


def test_schema_errors_are_reported_first_five(repo, tmp_path):
    bad = confirmed()
    del bad["root_cause"]
    bad["title"] = "  "
    bad["extra"] = 1
    report = audit_run(repo, tmp_path, FakeAgent([bad, {"verdict": "maybe"}]))
    assert report.schema_errors
    assert "the agent's output didn't match the schema" in report.summary
    assert "missing root_cause" in report.summary
    assert (report.run_dir / "findings.json").is_file()


def test_missing_findings_file_is_reported(repo, tmp_path):
    report = audit_run(repo, tmp_path, FakeAgent(None))
    assert "findings.json was not written" in report.summary


def test_validator_subset():
    assert audit.validate([confirmed(), needs(), rejected()], audit.load_schema()) == []
    dup = needs()
    dup["blockers"] = ["a", "a"]
    assert any("unique" in e for e in audit.validate([dup], audit.load_schema()))
    line = needs()
    line["trace"] = [{**TRACE[0], "line": 0}]
    assert any("at least 1" in e for e in audit.validate([line], audit.load_schema()))
    boolean = needs()
    boolean["trace"] = [{**TRACE[0], "line": True}]
    assert audit.validate([boolean], audit.load_schema())
    assert audit.validate({}, audit.load_schema())


def test_backup_only_on_limit_or_auth(repo, tmp_path):
    limit = SimpleNamespace(ok=False, failure="limit", text="")
    agent = FakeAgent([needs()], replies=[limit])
    report = audit.run(repo, agent=["claude", "codex"], ask_agent=agent, out_dir=tmp_path / "out")
    assert [c.agent for c in agent.calls] == ["claude", "codex"]
    assert report.agent == "codex" and len(report.findings) == 1
    assert "claude failed (limit)" in report.warnings[0]

    crash = SimpleNamespace(ok=False, failure="crash", text="")
    agent = FakeAgent([needs()], replies=[crash])
    report = audit.run(repo, agent=["claude", "codex"], ask_agent=agent, out_dir=tmp_path / "out2")
    assert [c.agent for c in agent.calls] == ["claude"]
    assert report.findings == () and "did not finish" in report.summary


def test_cancel_before_start_and_during(repo, tmp_path):
    event = threading.Event()
    event.set()
    agent = FakeAgent([needs()])
    report = audit_run(repo, tmp_path, agent, cancel_event=event)
    assert report.cancelled and agent.calls == []

    event = threading.Event()

    def stopper(agent_name, prompt, *, cwd, cancel_event):
        event.set()
        return SimpleNamespace(ok=True, failure="", text="")

    report = audit_run(repo, tmp_path, stopper, cancel_event=event)
    assert report.cancelled and report.findings == ()


def test_progress_is_reported(repo, tmp_path):
    seen = []
    audit_run(repo, tmp_path, FakeAgent([]), on_progress=seen.append)
    assert seen and "Asking claude" in seen[0]
