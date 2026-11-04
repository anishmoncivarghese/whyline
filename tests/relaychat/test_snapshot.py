import json
from types import SimpleNamespace

from whyline.relaychat import snapshot
from whyline_relay import state as relay_state

PLAN = "- [x] T-1: First thing\n- [ ] T-2: Second thing\n"


def _fake_run(calls):
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="out for " + " ".join(argv[2:]), stderr="")
    return run


def _relay(tmp_path, log_lines=5):
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "p.plan.md").write_text(PLAN, encoding="utf-8")
    log = tmp_path / ".whyline" / "relay" / "logs" / "T-2-1.log"
    log.parent.mkdir(parents=True)
    log.write_text("".join(f"log line {i}\n" for i in range(log_lines)), encoding="utf-8")
    relay_state.save(tmp_path, relay_state.RelayState(
        plan="plans/p.plan.md", branch="relay/p", task_id="T-2", round=1,
        base_commit="abcdef1234567890", paused_reason="rate limit", log_path=str(log)))
    (tmp_path / ".whyline" / "active-handoff.json").write_text(json.dumps({
        "task": "T-1", "status": "ready", "summary": "did the thing",
        "files": ["a.py"], "tests": ["pytest: ok"]}), encoding="utf-8")
    return log


def test_every_section_appears(tmp_path):
    _relay(tmp_path)
    calls = []
    snap = snapshot.build(tmp_path, max_chars=20000, run=_fake_run(calls))
    for name in ("relay-state", "recent-log", "latest-handoff", "plan-progress", "changes-so-far"):
        assert f'<untrusted-data section="{name}">' in snap.text
    assert snap.state == "paused"
    assert snap.run_id == "p.plan-abcdef12"
    assert "relay/p" in snap.text and "log line 4" in snap.text
    assert "did the thing" in snap.text and "pytest: ok" in snap.text
    assert "T-1: First thing" in snap.text and "T-2: Second thing" in snap.text
    assert "out for diff --stat abcdef1234567890" in snap.text


def test_trimming_removes_oldest_log_lines_first(tmp_path):
    _relay(tmp_path, log_lines=100)
    full = snapshot.build(tmp_path, max_chars=100000, run=_fake_run([]))
    trimmed = snapshot.build(tmp_path, max_chars=len(full.text) - 300, run=_fake_run([]))
    assert len(trimmed.text) <= len(full.text) - 300
    assert "log line 99" in trimmed.text
    assert "log line 0\n" not in trimmed.text
    assert "latest-handoff" in trimmed.text and "plan-progress" in trimmed.text


def test_every_git_call_has_no_optional_locks(tmp_path):
    _relay(tmp_path)
    calls = []
    snapshot.build(tmp_path, max_chars=20000, run=_fake_run(calls))
    assert len(calls) >= 2
    assert all(c[:2] == ["git", "--no-optional-locks"] for c in calls)
    assert ["git", "--no-optional-locks", "log", "--oneline", "-10"] in calls


def test_no_relay_gives_plain_line(tmp_path):
    calls = []
    snap = snapshot.build(tmp_path, max_chars=1000, run=_fake_run(calls))
    assert "No relay has run here yet" in snap.text
    assert snap.state == "none" and snap.run_id is None


def test_missing_log_and_handoff_are_plain_lines(tmp_path):
    _relay(tmp_path)
    (tmp_path / ".whyline" / "active-handoff.json").unlink()
    (tmp_path / ".whyline" / "relay" / "logs" / "T-2-1.log").unlink()
    snap = snapshot.build(tmp_path, max_chars=20000, run=_fake_run([]))
    assert "No handoff has been recorded." in snap.text
    assert "No log has been written yet." in snap.text
