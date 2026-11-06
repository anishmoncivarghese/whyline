"""`whyline security` and the scan behind it, against temp git repos with fakes."""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
from pathlib import Path

import pytest

from whyline.release import config as release_config
from whyline.security import cli, scan
from whyline.security import settings as st
from whyline.security.findings import Finding
from whyline.security.settings import SecuritySettings, decide

KEY = "AKIA" + "QYLPMN5HHQKB3XZT"
_real_run = scan.run


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def no_net(method, url, body, timeout):
    raise OSError("no network in tests")


def no_tools(name):
    return None


@pytest.fixture
def repo(tmp_path):
    work = tmp_path / "work"
    git(tmp_path, "init", "-q", "-b", "main", str(work))
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")
    (work / "a.txt").write_text("hello\n")
    git(work, "add", ".")
    git(work, "commit", "-qm", "init")
    return work


def commit_secret(repo: Path) -> None:
    (repo / "cfg.py").write_text(f'V = "{KEY}"\n')
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "oops")


def go(repo, scope, settings=None, **kw):
    kw.setdefault("fetch", no_net)
    kw.setdefault("which", no_tools)
    return _real_run(repo, scope, settings or SecuritySettings(), **kw)


@pytest.fixture
def no_contents(monkeypatch):
    calls = []
    monkeypatch.setattr(scan.contents, "check", lambda root, run: calls.append("contents") or [])
    return calls


# --- scopes ----------------------------------------------------------------------


def test_release_scope_scans_unpushed_commits_and_contents(repo, no_contents):
    commit_secret(repo)
    report = go(repo, "release")
    assert [f.kind for f in report.decision.blocking] == ["secret"]
    assert no_contents == ["contents"]
    assert report.blocks


def test_release_scope_only_looks_past_origin(repo, tmp_path, no_contents):
    commit_secret(repo)
    bare = tmp_path / "o.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main")
    assert go(repo, "release").decision.blocking == ()


def test_release_includes_dependencies(repo, no_contents):
    (repo / "requirements.txt").write_text("requests==2.0.0\n")
    vuln = {"id": "GHSA-1", "summary": "bad", "database_specific": {"severity": "HIGH"}, "affected": []}

    def fetch(method, url, body, timeout):
        if method == "POST":
            return {"results": [{"vulns": [{"id": "GHSA-1"}]}]}
        return vuln

    report = go(repo, "release", fetch=fetch)
    assert [f.kind for f in report.decision.blocking] == ["dependency"]
    assert "could not reach" in go(repo, "release").error
    warn_only = go(repo, "release", SecuritySettings(dependencies="warn"))
    assert warn_only.error == "" and any("could not reach" in n for n in warn_only.notes)


def test_staged_scope_sees_only_the_index(repo, no_contents):
    commit_secret(repo)
    assert go(repo, "staged").findings == []
    (repo / "b.py").write_text(f'V = "{KEY}"\n')
    git(repo, "add", "b.py")
    assert [f.path for f in go(repo, "staged").decision.blocking] == ["b.py"]
    assert no_contents == []


def test_history_scope_finds_removed_secret_and_saves_date(repo, no_contents):
    commit_secret(repo)
    (repo / "cfg.py").unlink()
    git(repo, "commit", "-qam", "remove")
    report = go(repo, "history")
    assert [f.path for f in report.decision.blocking] == ["cfg.py"]
    assert release_config.load(repo).security.history_scanned
    assert no_contents == []


def test_cancelled_history_scan_does_not_save(repo, no_contents):
    event = threading.Event()
    event.set()
    report = go(repo, "history", cancel_event=event)
    assert report.cancelled
    assert release_config.load(repo).security.history_scanned == ""


def test_all_scope_combines_history_tree_and_the_rest(repo, no_contents):
    (repo / "work.py").write_text(f'V = "{KEY}"\n')  # untracked: only the tree scan sees it
    report = go(repo, "all")
    assert [f.path for f in report.decision.blocking] == ["work.py"]
    assert no_contents == ["contents"]
    assert release_config.load(repo).security.history_scanned


def test_allowlist_and_ignore_once_exempt_findings(repo, no_contents):
    commit_secret(repo)
    found = go(repo, "release").decision.blocking[0]
    st.ignore_once(scan.state_dir(repo), found)
    report = go(repo, "release")
    assert report.decision.blocking == () and len(report.decision.allowed) == 1
    st.clear_ignored(scan.state_dir(repo))
    st.allow(repo, found, "test key")
    assert not go(repo, "release").blocks


def test_warn_setting_warns_instead_of_blocking(repo, no_contents):
    commit_secret(repo)
    report = go(repo, "release", SecuritySettings(secrets="warn"))
    assert report.decision.blocking == () and len(report.decision.warnings) == 1


def test_scan_error_is_reported_not_raised(repo, no_contents):
    def broken(*a, **k):
        raise OSError("x")

    report = go(repo, "staged", run=broken)
    assert report.error and report.blocks


def test_bad_scope(repo):
    with pytest.raises(ValueError):
        go(repo, "everything")


# --- the command line --------------------------------------------------------------


def run_cli(repo, monkeypatch, **kw):
    monkeypatch.setattr(cli, "_root", lambda: repo)
    monkeypatch.setattr(
        cli.scan, "run",
        lambda r, s, set_, **k: _real_run(r, s, set_, fetch=no_net, which=no_tools, **k),
    )
    monkeypatch.setattr(scan.contents, "check", lambda root, run: [])
    base = dict(security_command="scan", staged=False, history=False, all=False, json=False)
    return cli.run(argparse.Namespace(**{**base, **kw}))


def test_exit_codes(repo, monkeypatch, capsys):
    assert run_cli(repo, monkeypatch, staged=True) == 0
    capsys.readouterr()
    commit_secret(repo)
    assert run_cli(repo, monkeypatch, history=True) == 1
    out = capsys.readouterr().out
    assert "Secrets:" in out and "Summary: 1 blocking" in out and KEY not in out


def test_json_has_no_secret(repo, monkeypatch, capsys):
    commit_secret(repo)
    code = run_cli(repo, monkeypatch, history=True, json=True)
    out = capsys.readouterr().out
    assert code == 1 and KEY not in out
    data = json.loads(out)
    assert data["blocks"] and data["blocking"][0]["kind"] == "secret"
    assert data["blocking"][0]["preview"] == "AK****ZT"


def fingerprint(repo, monkeypatch, capsys) -> str:
    commit_secret(repo)
    run_cli(repo, monkeypatch, history=True, json=True)
    return json.loads(capsys.readouterr().out)["blocking"][0]["fingerprint"]


def test_allow_from_cli(repo, monkeypatch, capsys):
    fp = fingerprint(repo, monkeypatch, capsys)
    assert run_cli(repo, monkeypatch, security_command="allow", fingerprint=fp, reason="test key") == 0
    assert "test key" in (repo / ".whyline" / "security-allow.toml").read_text()
    assert run_cli(repo, monkeypatch, history=True) == 0
    assert run_cli(repo, monkeypatch, security_command="allow", fingerprint="nope", reason="x") == 1


def test_allow_needs_a_reason(repo, monkeypatch, capsys):
    fp = fingerprint(repo, monkeypatch, capsys)
    assert run_cli(repo, monkeypatch, security_command="allow", fingerprint=fp, reason=" ") == 1


def test_status(repo, monkeypatch, capsys):
    assert run_cli(repo, monkeypatch, security_command="status") == 0
    out = capsys.readouterr().out
    for text in ("secrets: block", "gitleaks:", "Rules:", "Last history scan: never"):
        assert text in out


def test_ready_text():
    secret = Finding(kind="secret", rule="r", title="t", fingerprint="a")
    dep = Finding(kind="dependency", rule="r", title="t", severity="high", fingerprint="b")
    report = scan.ScanReport("release", decision=decide([secret, secret, dep], SecuritySettings()))
    assert scan.ready_text(report) == (False, "3 blocking findings (secrets: 2, dependencies: 1)")
    warn = scan.ScanReport("release", decision=decide([secret], SecuritySettings(secrets="warn")))
    assert scan.ready_text(warn) == (True, "1 warnings")
    assert scan.ready_text(scan.ScanReport("release")) == (True, "no findings")
    assert scan.ready_text(scan.ScanReport("release", error="boom")) == (False, "security scan failed: boom")
