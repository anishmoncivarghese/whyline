import json

import pytest

from whyline import cli
from whyline.agents import paths
from whyline.tools import approvals


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()


class Clock:
    def __init__(self, on_sleep=None):
        self.now = 0.0
        self.sleeps = 0
        self.on_sleep = on_sleep

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.sleeps += 1
        if self.on_sleep:
            self.on_sleep(self.sleeps)


def _folder(run="r1"):
    folder = paths.runs_dir() / run
    folder.mkdir(exist_ok=True)
    return folder


def _ask(folder, clock, arguments=None, **options):
    return approvals.request(folder, "notion__search", arguments or {"q": "x"},
                             clock=clock, sleep=clock.sleep, **options)


def test_approve(tmp_path):
    folder = _folder()
    clock = Clock(lambda n: approvals.answer("r1", 1, True) if n == 2 else None)
    decision = _ask(folder, clock)
    assert decision.status == "approved"
    record = json.loads((folder / "approvals" / "1.json").read_text(encoding="utf-8"))
    assert record["tool"] == "notion__search" and record["by"] == "you" and record["asked_at"]


def test_deny():
    folder = _folder()
    clock = Clock(lambda n: approvals.answer("r1", 1, False, by="me"))
    assert _ask(folder, clock).status == "denied"
    assert json.loads((folder / "approvals" / "1.json").read_text(encoding="utf-8"))["by"] == "me"


def test_unanswered_call_is_denied():
    folder = _folder()
    clock = Clock()
    decision = _ask(folder, clock)
    assert decision.status == "timed out"
    assert clock.now >= approvals.APPROVAL_TIMEOUT
    assert json.loads((folder / "approvals" / "1.json").read_text(encoding="utf-8"))["status"] == "timed out"
    assert approvals.pending() == []


def test_arguments_are_redacted():
    folder = _folder()
    _ask(folder, Clock(), {"token": "hunter2"}, redact=lambda t: t.replace("hunter2", "[redacted]"))
    text = (folder / "approvals" / "1.json").read_text(encoding="utf-8")
    assert "hunter2" not in text and "[redacted]" in text


def test_pending_across_two_runs():
    for run in ("r1", "r2"):
        folder = _folder(run)
        (folder / "approvals").mkdir()
        (folder / "approvals" / "1.json").write_text(json.dumps(
            {"tool": f"t-{run}", "arguments": "{}", "asked_at": "now", "status": "waiting"}))
    (paths.runs_dir() / "r2" / "approvals" / "2.json").write_text(json.dumps({"tool": "done", "status": "approved"}))
    assert [(p.run_id, p.n, p.tool) for p in approvals.pending()] == [("r1", 1, "t-r1"), ("r2", 1, "t-r2")]
    assert [p.run_id for p in approvals.pending("r2")] == ["r2"]


def test_answering_a_finished_request_is_refused():
    folder = _folder()
    _ask(folder, Clock())
    with pytest.raises(approvals.ApprovalError, match="already timed out"):
        approvals.answer("r1", 1, True)
    with pytest.raises(approvals.ApprovalError):
        approvals.answer("r1", 9, True)


def test_cli(capsys):
    folder = _folder()
    (folder / "approvals").mkdir()
    (folder / "approvals" / "1.json").write_text(json.dumps(
        {"tool": "notion__search", "arguments": "{}", "asked_at": "now", "status": "waiting"}))
    assert cli.main(["agents", "approvals"]) == 0
    assert "r1 1  notion__search" in capsys.readouterr().out
    assert cli.main(["agents", "approve", "r1", "1"]) == 0
    assert json.loads((folder / "approvals" / "1.json").read_text(encoding="utf-8"))["status"] == "approved"
    assert cli.main(["agents", "deny", "r1", "1"]) != 0
    assert "already approved" in capsys.readouterr().err
    assert cli.main(["agents", "approvals"]) == 0
    assert "No calls are waiting" in capsys.readouterr().out
