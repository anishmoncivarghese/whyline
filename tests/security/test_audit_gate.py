"""The deep audit in the Release gate and on the command line."""

import argparse
import copy
import json
import threading
from types import SimpleNamespace

import pytest

from whyline.security import audit, cli, scan
from whyline.security.settings import SecuritySettings

from .test_audit import confirmed, needs, rejected


def low_confirmed(fp="C-2"):
    item = copy.deepcopy(confirmed(fp))
    item["severity"]["overall_severity"] = "low"
    return item


def write_run(base, repo, number, items, report=True):
    folder = base / repo.name / f"run-{number}"
    folder.mkdir(parents=True)
    (folder / "findings.json").write_text(json.dumps(items), encoding="utf-8")
    if report:
        (folder / "REPORT.md").write_text("# Report\n", encoding="utf-8")
    return folder


@pytest.fixture
def repo(tmp_path):
    work = tmp_path / "project"
    work.mkdir()
    return work


@pytest.fixture
def base(tmp_path):
    return tmp_path / "audits"


@pytest.fixture
def no_scans(monkeypatch):
    monkeypatch.setattr(scan.contents, "check", lambda root, run: [])
    monkeypatch.setattr(scan.deps, "check", lambda *a, **k: SimpleNamespace(findings=[], error=""))


def gate(repo, base, level, no_scans):
    settings = SecuritySettings(secrets="off", dependencies="off", contents="off", audit=level)
    return scan.run(repo, "release", settings, audit_base=base)


def test_runs_are_listed_newest_first_with_verdict_counts(repo, base):
    write_run(base, repo, 1, [confirmed()])
    write_run(base, repo, 2, [confirmed("A"), needs(), rejected()], report=False)
    (base / repo.name / "run-3").mkdir()  # stopped before it wrote findings.json
    runs = scan.audit_runs(repo, base)
    assert [r.number for r in runs] == [2, 1]
    assert (runs[0].count("confirmed"), runs[0].count("needs_validation"), runs[0].rejected) == (1, 1, 1)
    assert runs[0].has_report is False and runs[1].has_report is True
    assert runs[1].report_path.name == "REPORT.md"
    assert scan.latest_audit(repo, base).number == 2


def test_invalid_findings_file_is_not_the_latest(repo, base):
    write_run(base, repo, 1, [confirmed()])
    bad = write_run(base, repo, 2, [])
    (bad / "findings.json").write_text("{not json", encoding="utf-8")
    runs = scan.audit_runs(repo, base)
    assert runs[0].valid is False
    assert scan.latest_audit(repo, base).number == 1


def test_findings_sort_by_verdict_then_severity(repo, base):
    write_run(base, repo, 1, [low_confirmed("L"), needs(), confirmed("H")])
    rows = scan.sort_audit_findings(scan.latest_audit(repo, base).findings)
    assert [(f.rule, f.severity) for f in rows] == [
        ("confirmed", "high"), ("confirmed", "low"), ("needs_validation", "unknown")]


def test_gate_off_ignores_the_audit(repo, base, no_scans):
    write_run(base, repo, 1, [confirmed()])
    report = gate(repo, base, "off", no_scans)
    assert not report.blocks and not report.decision.warnings and not report.audit_missing


def test_warn_shows_confirmed_as_warnings_and_never_blocks(repo, base, no_scans):
    write_run(base, repo, 1, [confirmed("H"), low_confirmed("L"), needs()])
    report = gate(repo, base, "warn", no_scans)
    assert not report.blocks and not report.decision.blocking
    assert sorted(f.title for f in report.decision.warnings) == ["Shell injection", "Shell injection"]
    assert all(f.rule == "confirmed" for f in report.decision.warnings)
    assert scan.ready_text(report) == (True, "2 warnings")


def test_warn_without_an_audit_passes(repo, base, no_scans):
    report = gate(repo, base, "warn", no_scans)
    assert not report.blocks and scan.ready_text(report) == (True, "no findings")


def test_block_confirmed_blocks_only_high_and_critical(repo, base, no_scans):
    write_run(base, repo, 1, [confirmed("H"), low_confirmed("L")])
    report = gate(repo, base, "block-confirmed", no_scans)
    assert report.blocks
    assert [f.severity for f in report.decision.blocking] == ["high"]
    assert [f.severity for f in report.decision.warnings] == ["low"]
    assert scan.ready_text(report) == (False, "1 blocking findings (audit: 1)")


def test_needs_validation_never_blocks(repo, base, no_scans):
    write_run(base, repo, 1, [needs("N-1"), needs("N-2")])
    report = gate(repo, base, "block-confirmed", no_scans)
    assert not report.blocks and not report.decision.blocking and not report.decision.warnings
    assert scan.ready_text(report) == (True, "no findings")


def test_block_confirmed_without_an_audit_says_run_one_first(repo, base, no_scans):
    report = gate(repo, base, "block-confirmed", no_scans)
    assert report.blocks and report.audit_missing
    assert scan.ready_text(report) == (False, "run a deep audit first")


def test_only_the_latest_run_counts(repo, base, no_scans):
    write_run(base, repo, 1, [confirmed()])
    write_run(base, repo, 2, [needs()])
    assert not gate(repo, base, "block-confirmed", no_scans).blocks


def test_allowed_audit_finding_does_not_block(repo, base, no_scans):
    from whyline.security import settings as st

    write_run(base, repo, 1, [confirmed("H")])
    first = gate(repo, base, "block-confirmed", no_scans)
    st.allow(repo, first.decision.blocking[0], "accepted")
    assert not gate(repo, base, "block-confirmed", no_scans).blocks


def test_staged_scope_skips_the_audit(repo, base, no_scans, monkeypatch):
    monkeypatch.setattr(scan.secrets, "scan_staged", lambda root, run: [])
    settings = SecuritySettings(secrets="block", audit="block-confirmed")
    assert not scan.run(repo, "staged", settings, audit_base=base).blocks


# --- run_audit and the command ---------------------------------------------------------


def test_run_audit_uses_the_given_agent(repo, tmp_path):
    seen = []

    def ask(agent, prompt, *, cwd, cancel_event):
        seen.append(agent)
        return SimpleNamespace(ok=False, failure="error", text="")

    report = scan.run_audit(repo, agent="codex", ask_agent=ask, out_dir=tmp_path / "out")
    assert seen == ["codex"] and not report.ok


def test_run_audit_uses_main_agent_then_backups(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(scan, "main_agents", lambda root: ["codex", "claude"])
    seen = []

    def ask(agent, prompt, *, cwd, cancel_event):
        seen.append(agent)
        return SimpleNamespace(ok=False, failure="limit", text="")

    scan.run_audit(repo, ask_agent=ask, out_dir=tmp_path / "out")
    assert seen == ["codex", "claude"]


def args(**kw):
    return argparse.Namespace(**{"security_command": "audit", "agent": None, **kw})


def test_cli_audit_calls_run_audit_and_prints_findings(repo, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "_root", lambda: repo)
    folder = write_run(tmp_path / "audits", repo, 1, [confirmed(), needs()])
    seen = {}

    def fake(root, **kw):
        seen.update(kw, root=root)
        items, rej, _ = audit.parse_findings(folder)
        return audit.AuditReport(folder, 1, tuple(items), rej, report_path=folder / "REPORT.md",
                                 summary="2 finding(s), 0 rejected.")

    monkeypatch.setattr(cli.scan, "run_audit", fake)
    assert cli.run(args(agent="grok")) == 0
    out = capsys.readouterr()
    assert seen["agent"] == "grok" and seen["root"] == repo
    assert "[confirmed] high Shell injection" in out.out and "[needs_validation]" in out.out
    assert out.out.index("[confirmed]") < out.out.index("[needs_validation]")
    assert "REPORT.md" in out.out
    assert "many tokens" in out.err and "only part" in out.err


def test_cli_audit_without_an_agent_is_an_error(repo, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_root", lambda: repo)
    monkeypatch.setattr(scan, "main_agents", lambda root: [])
    assert cli.run(args()) == 1
    assert "no agent" in capsys.readouterr().err


def test_cli_audit_stopped_run_exits_with_an_error(repo, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_root", lambda: repo)
    event = threading.Event()
    event.set()
    monkeypatch.setattr(cli.scan, "run_audit", lambda root, **kw: audit.AuditReport(
        repo, 1, cancelled=True, summary="Audit stopped."))
    assert cli.run(args()) == 1
    assert "Audit stopped." in capsys.readouterr().out


def test_default_ask_supplies_log_path_and_forwards_cancel(tmp_path, monkeypatch):
    from whyline_relay import agents, chat, config

    seen = {}

    def fake_run(argv, prompt, **kwargs):
        seen.update(kwargs)
        seen["log_dir_exists"] = kwargs["log_path"].parent.is_dir()
        return SimpleNamespace(exit_code=0, output="done")

    monkeypatch.setattr(config, "load", lambda cwd: None)
    monkeypatch.setattr(chat, "resolve_command", lambda conf, agent: ["fake"])
    monkeypatch.setattr(agents, "run", fake_run)
    cancel = threading.Event()
    reply = scan._default_ask("claude", "audit", cwd=tmp_path, cancel_event=cancel)
    assert reply.ok and reply.text == "done"
    assert seen["log_path"].name == "output.log" and seen["log_dir_exists"]
    assert tmp_path not in seen["log_path"].parents
    assert seen["cancel_event"] is cancel
