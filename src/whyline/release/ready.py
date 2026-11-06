"""The Ready check: everything that must be true before a release can start."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from whyline.release import config as release_config
from whyline.release.config import ReleaseConfig

BUDGET_SECONDS = 30.0

# relay_state() returns one of these.
RELAY_IDLE = "idle"
RELAY_RUNNING = "running"
RELAY_PAUSED_RELEASE = "paused-release"
RELAY_PAUSED_OTHER = "paused"


@dataclass(frozen=True)
class ReadyItem:
    key: str
    ok: bool
    text: str
    fix: str = ""


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""


# run(args, cwd=..., env=...) -> object with returncode, stdout, stderr
Run = Callable[..., object]
Fetch = Callable[[Path, str], object]
RelayState = Callable[[], str]
TargetCheck = Callable[[Path, ReleaseConfig, str, Run], ReadyItem | None]

_TARGET_CHECKS: dict[str, TargetCheck] = {}

# Checks that run on every release rather than for one switched-on target.
_ALWAYS = frozenset({"security", "security-history"})


def register_ready(target: str, fn: TargetCheck) -> None:
    """Add a target's ready item; it runs only when that target is switched on."""
    _TARGET_CHECKS[target] = fn


def default_run(args: list[str], *, cwd: Path | str | None = None,
                env: dict[str, str] | None = None, timeout: float = 30.0) -> Result:
    proc = subprocess.run(
        args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False
    )
    return Result(proc.returncode, proc.stdout or "", proc.stderr or "")


def default_fetch(root: Path, branch: str) -> None:
    res = default_run(["git", "fetch", "origin", branch], cwd=root, env=_git_env())
    if res.returncode != 0:
        raise RuntimeError(_short(res.stderr) or "git fetch failed")


def ok(items: list[ReadyItem]) -> bool:
    return all(i.ok for i in items)


def _git_env() -> dict[str, str]:
    return {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}


def _short(text: str, limit: int = 120) -> str:
    line = (text or "").strip().splitlines()
    first = line[0].strip() if line else ""
    return first if len(first) <= limit else first[: limit - 1] + "…"


def _git(run: Run, root: Path, *args: str):
    return run(["git", *args], cwd=root, env=_git_env())


def _installed(key: str, name: str, fix: str, run: Run, root: Path) -> ReadyItem:
    try:
        res = run([name, "--version"], cwd=root, env=_git_env())
    except FileNotFoundError:
        return ReadyItem(key, False, f"{name} is not installed", fix)
    if res.returncode != 0:
        return ReadyItem(key, False, f"{name} is not installed", fix)
    return ReadyItem(key, True, f"{name} is installed")


def _git_installed(root, cfg, version, run, **_):
    return _installed("git", "git", "Install git from https://git-scm.com", run, root)


def _gh_installed(root, cfg, version, run, **_):
    return _installed("gh", "gh", "Install the GitHub CLI: https://cli.github.com", run, root)


def _gh_auth(root, cfg, version, run, **_):
    try:
        res = run(["gh", "auth", "status"], cwd=root, env=_git_env())
    except FileNotFoundError:
        return ReadyItem("gh-auth", False, "gh is not signed in (gh is not installed)",
                         "Install gh, then run: gh auth login")
    if res.returncode != 0:
        return ReadyItem("gh-auth", False, "gh is not signed in", "Run: gh auth login")
    return ReadyItem("gh-auth", True, "gh is signed in")


def _remote_host(url: str) -> str:
    url = url.strip()
    if "://" in url:
        return (urlparse(url).hostname or "").lower()
    if "@" in url and ":" in url:  # scp-like: git@github.com:owner/repo.git
        return url.split("@", 1)[1].split(":", 1)[0].lower()
    return ""


def _origin(root, cfg, version, run, **_):
    fix = "Add a GitHub remote: git remote add origin https://github.com/<owner>/<repo>.git"
    res = _git(run, root, "remote", "get-url", "origin")
    if res.returncode != 0:
        return ReadyItem("origin", False, "No origin remote", fix)
    if _remote_host(res.stdout) != "github.com":
        return ReadyItem("origin", False, "origin is not on GitHub", fix)
    return ReadyItem("origin", True, "origin is on GitHub")


def _dirty_paths(porcelain: str) -> list[str]:
    paths: list[str] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip().strip('"'))
    return paths


def _is_pending(path: str, allowed: list[str]) -> bool:
    return any(path == a or path.startswith(a.rstrip("/") + "/") for a in allowed)


def _clean(root, cfg, version, run, **_):
    fix = "Commit or stash your changes, then check again"
    res = _git(run, root, "status", "--porcelain")
    if res.returncode != 0:
        raise RuntimeError(_short(res.stderr) or "git status failed")
    allowed = [p.as_posix() for p in release_config.pending(root)]
    dirty = [p for p in _dirty_paths(res.stdout) if not _is_pending(p, allowed)]
    if dirty:
        more = f" and {len(dirty) - 1} more" if len(dirty) > 1 else ""
        return ReadyItem("clean", False, f"Uncommitted changes: {dirty[0]}{more}", fix)
    return ReadyItem("clean", True, "Working tree is clean")


def _relay(root, cfg, version, run, *, relay_state, **_):
    state = relay_state()
    if state == RELAY_RUNNING:
        return ReadyItem("relay", False, "A relay is running",
                         "Pause the relay (or wait for it to finish), then check again")
    if state == RELAY_PAUSED_OTHER:
        return ReadyItem("relay", False, "A relay is paused on another task",
                         "Finish or close that relay, then check again")
    return ReadyItem("relay", True, "No relay is running")


def _synced(root, cfg, version, run, *, fetch, **_):
    branch = cfg.branch
    fix = f"Pull or push so that {branch} matches origin/{branch}, then check again"
    fetch(root, branch)
    res = _git(run, root, "merge-base", "--is-ancestor", f"origin/{branch}", "HEAD")
    if res.returncode == 0:
        return ReadyItem("synced", True, f"HEAD is up to date with origin/{branch}")
    if res.returncode == 1:
        return ReadyItem("synced", False, f"HEAD is behind origin/{branch}", fix)
    raise RuntimeError(_short(res.stderr) or "git merge-base failed")


def _tag_free(root, cfg, version, run, **_):
    tag = f"v{version}"
    fix = f"Pick another version; {tag} is already used"
    local = _git(run, root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}")
    if local.returncode == 0:
        return ReadyItem("tag", False, f"Tag {tag} exists locally", fix)
    remote = _git(run, root, "ls-remote", "--tags", "origin", f"refs/tags/{tag}")
    if remote.returncode != 0:
        raise RuntimeError(_short(remote.stderr) or "git ls-remote failed")
    if remote.stdout.strip():
        return ReadyItem("tag", False, f"Tag {tag} exists on origin", fix)
    return ReadyItem("tag", True, f"Tag {tag} is free")


_BASE = (
    ("git", _git_installed),
    ("gh", _gh_installed),
    ("gh-auth", _gh_auth),
    ("origin", _origin),
    ("clean", _clean),
    ("relay", _relay),
    ("synced", _synced),
    ("tag", _tag_free),
)


def check(root: Path | str, cfg: ReleaseConfig, version: str, *,
          run: Run = default_run, fetch: Fetch = default_fetch,
          relay_state: RelayState = lambda: RELAY_IDLE,
          clock: Callable[[], float] = time.monotonic,
          budget: float = BUDGET_SECONDS) -> list[ReadyItem]:
    root = Path(root)
    jobs: list[tuple[str, Callable[[], ReadyItem]]] = []
    for key, fn in _BASE:
        jobs.append((key, lambda fn=fn: fn(root, cfg, version, run,
                                           fetch=fetch, relay_state=relay_state)))
    for target, fn in _TARGET_CHECKS.items():
        if target in _ALWAYS or getattr(cfg.targets, target, False):
            jobs.append((target, lambda fn=fn: fn(root, cfg, version, run)))

    start = clock()
    items: list[ReadyItem] = []
    for key, job in jobs:
        if clock() - start >= budget:
            items.append(ReadyItem(key, False, "not checked (time limit)"))
            continue
        try:
            item = job()
            if item is not None:
                items.append(item)
        except Exception as exc:  # noqa: BLE001 - one broken item must not stop the rest
            reason = _short(str(exc)) or type(exc).__name__
            items.append(ReadyItem(key, False, f"could not check: {reason}"))
    return items


_SECURITY_FIX = "Open Security to review"


def _security(root, cfg, version, run, **_):
    from whyline.security import scan

    report = scan.run(root, "release", cfg.security, branch=cfg.branch)
    good, text = scan.ready_text(report)
    return ReadyItem("security", good, text, "" if good else _SECURITY_FIX)


def _security_history(root, cfg, version, run, **_):
    """Before the first push, suggest a one-off scan of the whole history."""
    if cfg.security.history_scanned or cfg.security.secrets == "off":
        return None
    if _git(run, root, "rev-parse", "--verify", "-q", f"origin/{cfg.branch}").returncode == 0:
        return None
    return ReadyItem("security-history", cfg.security.secrets != "block",
                     "History has not been scanned for secrets", "Scan history")


register_ready("security", _security)
register_ready("security-history", _security_history)
