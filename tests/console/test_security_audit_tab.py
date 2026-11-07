"""The Audit tab of the Security popup."""

import json
import threading
from types import SimpleNamespace

import pytest
from textual.app import App
from textual.widgets import Button, Static

from whyline.console import security_screens as ss
from whyline.console import tui
from whyline.release.config import ReleaseConfig
from whyline.security import scan
from whyline.security.settings import Decision

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

TRACE = [{"kind": "sink", "file": "a.py", "line": 3, "scope": "f", "description": "d"}]
EVIDENCE = [{"file": "a.py", "line": 3, "description": "seen"}]
SCORE = {"score": "high", "reason": "r"}


class Host(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen

    def on_mount(self):
        self.push_screen(self._screen)


async def _settle(pilot, n=15):
    for _ in range(n):
        await pilot.pause()


def _confirmed(fp, severity):
    return {
        "verdict": "confirmed", "fingerprint": fp, "title": f"Confirmed {severity}",
        "description": "d", "root_cause": "rc", "intended_behavior": "ib", "trace": TRACE,
        "evidence": EVIDENCE, "conditions": [],
        "execution": {"attacker_perspective": "a", "payloads": ["x"], "instructions": ["i"],
                      "observed_result": "o"},
        "remediation": {"strategy": "Fix it."},
        "severity": {"likelihood": SCORE, "impact": SCORE, "overall_severity": severity},
        "confidence": SCORE,
    }


def _needs():
    return {
        "verdict": "needs_validation", "fingerprint": "N", "title": "Maybe SSRF", "description": "d",
        "claimed_root_cause": "rc", "trace": TRACE, "evidence": EVIDENCE, "blockers": ["b"],
        "validation_plan": {"local": "try"},
    }


def _items():
    return [_needs(), _confirmed("L", "low"), _confirmed("H", "high")]


def _write_run(base, root, number, findings, report=True):
    folder = base / root.name / f"run-{number}"
    folder.mkdir(parents=True)
    (folder / "findings.json").write_text(json.dumps(findings), encoding="utf-8")
    if report:
        (folder / "REPORT.md").write_text("# Report\n", encoding="utf-8")
    return folder


@pytest.fixture
def root(tmp_path):
    work = tmp_path / "project"
    work.mkdir()
    return work


def _screen(root, base, audit_run=None, opened=None, clock=None):
    def open_file(path, line):
        if opened is not None:
            opened.append(path)
        return ""

    return ss.SecurityScreen(
        root, config=ReleaseConfig(), open_file=open_file, audit_run=audit_run, audit_base=base,
        clock=clock, scan_run=lambda *a, **k: scan.ScanReport("release", decision=Decision()))


def _status(app):
    return str(app.screen.query_one("#aud-status", Static).renderable)


def _texts(app, cls):
    return [str(w.renderable) for w in app.screen.query(cls).results(Static)]


async def _start(pilot, screen):
    screen.query_one("#aud-run", Button).press()
    await _settle(pilot)
    screen.query_one("#aud-start", Button).press()


async def test_tab_lists_findings_by_verdict_and_severity_and_past_runs(tmp_path, root):
    base = tmp_path / "audits"
    _write_run(base, root, 1, _items()[:1])
    _write_run(base, root, 2, _items())
    async with Host(_screen(root, base)).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        found = _texts(pilot.app, ".aud-finding")
        assert [t.splitlines()[0] for t in found] == [
            "confirmed [HIGH] Confirmed high", "confirmed [LOW] Confirmed low",
            "needs_validation [?] Maybe SSRF"]
        assert _texts(pilot.app, ".aud-run-text") == [
            "Run 2: 2 confirmed, 1 need validation, 0 rejected",
            "Run 1: 0 confirmed, 1 need validation, 0 rejected"]


async def test_show_switches_to_an_older_run(tmp_path, root):
    base = tmp_path / "audits"
    _write_run(base, root, 1, _items()[:1])
    _write_run(base, root, 2, _items())
    async with Host(_screen(root, base)).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        pilot.app.screen.query_one("#aud-show-1", Button).press()
        await _settle(pilot)
        assert len(_texts(pilot.app, ".aud-finding")) == 1


async def test_empty_tab_and_open_report(tmp_path, root):
    base = tmp_path / "audits"
    async with Host(_screen(root, base)).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        assert pilot.app.screen.query_one("#aud-empty")
        assert pilot.app.screen.query_one("#aud-open", Button).disabled
    folder = _write_run(base, root, 1, _items())
    opened = []
    async with Host(_screen(root, base, opened=opened)).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        pilot.app.screen.query_one("#aud-open", Button).press()
        await _settle(pilot)
        pilot.app.screen.query_one("#aud-report-1", Button).press()
        await _settle(pilot)
        assert opened == [folder / "REPORT.md", folder / "REPORT.md"]


async def test_run_warns_first_then_shows_elapsed_and_refreshes(tmp_path, root):
    base = tmp_path / "audits"
    started, release = threading.Event(), threading.Event()
    calls = []

    def clock():
        calls.append(1)
        return 0.0 if len(calls) == 1 else 75.0  # the start, then every later reading

    def fake_audit(repo, **kw):
        _write_run(base, repo, 1, _items())
        started.set()
        assert release.wait(5)
        return SimpleNamespace(cancelled=False, summary="3 finding(s), 0 rejected.")

    screen = _screen(root, base, audit_run=fake_audit, clock=clock)
    async with Host(screen).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        screen.query_one("#aud-run", Button).press()
        await _settle(pilot)
        notice = str(screen.query_one("#aud-notice", Static).renderable)
        assert "main agent" in notice and "many tokens" in notice and "only part" in notice
        assert not started.is_set()
        screen.query_one("#aud-start", Button).press()
        for _ in range(100):
            await pilot.pause()
            if started.is_set():
                break
        assert started.is_set()
        screen._tick_audit()
        assert "Auditing… 1m 15s elapsed" in _status(pilot.app)
        assert screen.query_one("#aud-run", Button).disabled
        assert not screen.query_one("#aud-stop", Button).disabled
        release.set()
        await _settle(pilot, 40)
        assert _status(pilot.app) == "3 finding(s), 0 rejected."
        assert not screen.query_one("#aud-run", Button).disabled
        assert len(_texts(pilot.app, ".aud-finding")) == 3


async def test_stop_cancels_the_audit(tmp_path, root):
    seen = {}

    def fake_audit(repo, **kw):
        seen["cancel"] = kw["cancel_event"]
        assert kw["cancel_event"].wait(5)
        return SimpleNamespace(cancelled=True, summary="Audit stopped.")

    screen = _screen(root, tmp_path / "audits", audit_run=fake_audit)
    async with Host(screen).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        await _start(pilot, screen)
        for _ in range(100):
            await pilot.pause()
            if "cancel" in seen:
                break
        screen.query_one("#aud-stop", Button).press()
        await _settle(pilot, 40)
        assert seen["cancel"].is_set()
        assert _status(pilot.app) == "The audit was stopped."
        assert screen.query_one("#aud-stop", Button).disabled


async def test_a_failed_audit_is_shown(tmp_path, root):
    def boom(repo, **kw):
        raise ValueError("no agent is configured for the audit; pass --agent NAME")

    screen = _screen(root, tmp_path / "audits", audit_run=boom)
    async with Host(screen).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        await _start(pilot, screen)
        await _settle(pilot, 40)
        assert "could not run: no agent" in _status(pilot.app)
