from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from whyline.release import config as release_config
from whyline.release import ready
from whyline.release.config import ReleaseConfig, Targets
from whyline.release.ready import ReadyItem, Result
from whyline.security.settings import SecuritySettings

KEYS = ["git", "gh", "gh-auth", "origin", "clean", "relay", "synced", "tag"]


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return out.stdout


@pytest.fixture(autouse=True)
def _no_targets(monkeypatch):
    monkeypatch.setattr(ready, "_TARGET_CHECKS", {})


@pytest.fixture
def repo(tmp_path):
    bare = tmp_path / "origin.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    _git(tmp_path, "init", "-b", "main", str(work))
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "t")
    (work / "a.txt").write_text("a\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "init")
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "origin", "main")
    return work


def make_run(repo: Path, *, gh_installed=True, gh_auth=True, git_installed=True,
             origin_url="https://github.com/o/r.git"):
    """Real git against the temp repo; gh and the origin URL are faked."""

    def run(args, cwd=None, env=None):
        if args[0] == "gh":
            if not gh_installed:
                raise FileNotFoundError("gh")
            if args[1:] == ["auth", "status"]:
                return Result(0 if gh_auth else 1)
            return Result(0)
        if args[0] == "git" and args[1:] == ["--version"] and not git_installed:
            raise FileNotFoundError("git")
        if args[:4] == ["git", "remote", "get-url", "origin"]:
            return Result(0, origin_url + "\n")
        proc = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
        return Result(proc.returncode, proc.stdout, proc.stderr)

    return run


def real_fetch(repo: Path):
    def fetch(root, branch):
        _git(root, "fetch", "origin", branch)

    return fetch


def run_check(repo, cfg=None, version="1.2.3", relay="idle", **kw):
    run_kw = {k: kw.pop(k) for k in list(kw) if k in
              ("gh_installed", "gh_auth", "git_installed", "origin_url")}
    return ready.check(
        repo, cfg or ReleaseConfig(), version,
        run=make_run(repo, **run_kw), fetch=kw.pop("fetch", real_fetch(repo)),
        relay_state=lambda: relay, **kw,
    )


def by_key(items):
    return {i.key: i for i in items}


def test_all_ok(repo):
    items = run_check(repo)
    assert [i.key for i in items] == KEYS
    assert all(i.ok for i in items), items
    assert ready.ok(items)


@pytest.mark.parametrize("kwargs,key", [
    ({"git_installed": False}, "git"),
    ({"gh_installed": False}, "gh"),
    ({"gh_auth": False}, "gh-auth"),
    ({"origin_url": "https://gitlab.com/o/r.git"}, "origin"),
    ({"relay": "running"}, "relay"),
])
def test_single_failure_has_fix(repo, kwargs, key):
    items = run_check(repo, **kwargs)
    got = by_key(items)
    assert not got[key].ok
    assert got[key].fix
    failed = [i.key for i in items if not i.ok]
    # without gh installed, the sign-in item cannot pass either
    assert failed == ([key, "gh-auth"] if key == "gh" else [key])
    assert not ready.ok(items)


def test_scp_style_github_remote_ok(repo):
    got = by_key(run_check(repo, origin_url="git@github.com:o/r.git"))
    assert got["origin"].ok


def test_dirty_tree(repo):
    (repo / "a.txt").write_text("changed\n")
    got = by_key(run_check(repo))
    assert not got["clean"].ok
    assert "a.txt" in got["clean"].text
    assert got["clean"].fix


def test_pending_paths_do_not_dirty_tree(repo):
    (repo / "whyline.toml").write_text("x\n")
    release_config.add_pending(repo, "whyline.toml")
    got = by_key(run_check(repo))
    assert got["clean"].ok


def test_relay_paused_on_release_ok(repo):
    got = by_key(run_check(repo, relay=ready.RELAY_PAUSED_RELEASE))
    assert got["relay"].ok


def test_relay_paused_elsewhere_fails(repo):
    got = by_key(run_check(repo, relay=ready.RELAY_PAUSED_OTHER))
    assert not got["relay"].ok


def test_behind_origin(repo, tmp_path):
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(tmp_path / "origin.git"), str(other))
    _git(other, "config", "user.email", "t@example.com")
    _git(other, "config", "user.name", "t")
    (other / "b.txt").write_text("b\n")
    _git(other, "add", ".")
    _git(other, "commit", "-m", "more")
    _git(other, "push", "origin", "main")
    got = by_key(run_check(repo))
    assert not got["synced"].ok
    assert got["synced"].fix


def test_ahead_of_origin_ok(repo):
    (repo / "b.txt").write_text("b\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "local")
    assert by_key(run_check(repo))["synced"].ok


def test_local_tag_exists(repo):
    _git(repo, "tag", "v1.2.3")
    got = by_key(run_check(repo))
    assert not got["tag"].ok
    assert "locally" in got["tag"].text
    assert got["tag"].fix


def test_remote_tag_exists(repo, tmp_path):
    _git(repo, "tag", "v1.2.3")
    _git(repo, "push", "origin", "v1.2.3")
    _git(repo, "tag", "-d", "v1.2.3")
    got = by_key(run_check(repo))
    assert not got["tag"].ok
    assert "origin" in got["tag"].text


def test_exception_becomes_could_not_check(repo):
    def boom(root, branch):
        raise RuntimeError("network down")

    items = run_check(repo, fetch=boom)
    got = by_key(items)
    assert not got["synced"].ok
    assert got["synced"].text == "could not check: network down"
    assert got["tag"].ok  # later items still run


def test_registered_target_item_runs_only_when_enabled(repo):
    ready.register_ready("pypi", lambda root, cfg, v, run: ReadyItem("pypi", False, "no token", "set it"))
    assert "pypi" not in by_key(run_check(repo))
    cfg = ReleaseConfig(targets=Targets(pypi=True))
    items = run_check(repo, cfg=cfg)
    assert items[-1] == ReadyItem("pypi", False, "no token", "set it")


def test_time_budget(repo):
    ticks = iter([0.0, 0.0, 1.0, 31.0, 32.0, 33.0, 34.0, 35.0, 36.0, 37.0])
    items = run_check(repo, clock=lambda: next(ticks))
    assert [i.key for i in items] == KEYS
    assert items[0].ok and items[1].ok
    for i in items[2:]:
        assert not i.ok
        assert i.text == "not checked (time limit)"


# --- security ---------------------------------------------------------------------


def _security_items(repo, monkeypatch, report, cfg=None):
    from whyline.security import scan

    monkeypatch.setattr(ready, "_TARGET_CHECKS", {
        "security": ready._security, "security-history": ready._security_history})
    monkeypatch.setattr(scan, "run", lambda *a, **k: report)
    return by_key(run_check(repo, cfg=cfg))


def _findings(kind, n):
    from whyline.security.findings import Finding

    return tuple(Finding(kind=kind, rule="r", title="t", severity="high", fingerprint=f"{kind}{i}")
                 for i in range(n))


def test_security_item_states(repo, monkeypatch):
    from whyline.security.scan import ScanReport
    from whyline.security.settings import Decision

    got = _security_items(repo, monkeypatch, ScanReport("release"))["security"]
    assert got == ReadyItem("security", True, "no findings")
    warn = ScanReport("release", decision=Decision(warnings=_findings("dependency", 2)))
    assert _security_items(repo, monkeypatch, warn)["security"] == ReadyItem("security", True, "2 warnings")
    block = ScanReport("release", decision=Decision(
        blocking=_findings("secret", 2) + _findings("dependency", 1) + _findings("contents", 3)))
    assert _security_items(repo, monkeypatch, block)["security"] == ReadyItem(
        "security", False, "6 blocking findings (secrets: 2, dependencies: 1, contents: 3)",
        "Open Security to review")
    failed = ScanReport("release", error="git log failed")
    assert _security_items(repo, monkeypatch, failed)["security"] == ReadyItem(
        "security", False, "security scan failed: git log failed", "Open Security to review")


def test_history_suggestion_only_before_first_push(repo, tmp_path, monkeypatch):
    from whyline.security.scan import ScanReport

    # the fixture repo has pushed origin/main: no suggestion
    assert "security-history" not in _security_items(repo, monkeypatch, ScanReport("release"))
    fresh = tmp_path / "fresh"
    _git(tmp_path, "init", "-b", "main", str(fresh))
    _git(fresh, "config", "user.email", "t@example.com")
    _git(fresh, "config", "user.name", "t")
    (fresh / "a.txt").write_text("a\n")
    _git(fresh, "add", ".")
    _git(fresh, "commit", "-m", "init")
    got = _security_items(fresh, monkeypatch, ScanReport("release"))["security-history"]
    assert got == ReadyItem("security-history", False, "History has not been scanned for secrets", "Scan history")
    warn = ReleaseConfig(security=SecuritySettings(secrets="warn"))
    assert _security_items(fresh, monkeypatch, ScanReport("release"), warn)["security-history"].ok
    done = ReleaseConfig(security=SecuritySettings(history_scanned="2026-11-06"))
    assert "security-history" not in _security_items(fresh, monkeypatch, ScanReport("release"), done)
    off = ReleaseConfig(security=SecuritySettings(secrets="off"))
    assert "security-history" not in _security_items(fresh, monkeypatch, ScanReport("release"), off)
