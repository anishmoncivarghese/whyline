"""Release steps 4-9: commit, checks, push, CI, tag and GitHub release."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from whyline.release import config as release_config
from whyline.release.config import ReleaseConfig
from whyline.release.engine import Step
from whyline.release.ready import default_run

Run = Callable[..., object]
Sleep = Callable[[float], None]
Now = Callable[[], float]
OnProgress = Callable[[str], None]
# run_shell(command, root, on_line) -> (returncode, all output lines)
RunShell = Callable[[str, Path, Callable[[str], None]], "tuple[int, list[str]]"]

POLL_SECONDS = 15
NO_CI_SECONDS = 2 * 60
CI_TIMEOUT_SECONDS = 60 * 60
NETWORK_TIMEOUT = 300.0
_FAILED = {"failure", "cancelled", "timed_out", "startup_failure", "action_required", "stale"}


class StepError(RuntimeError):
    """A release step failed; the message is shown to the user."""

    def __init__(self, message: str, *, open_pr: bool = False) -> None:
        super().__init__(message)
        self.open_pr = open_pr


def _out(proc: object, name: str = "stdout") -> str:
    return (getattr(proc, name, "") or "").strip()


def _tail(text: str, count: int = 20) -> str:
    return "\n".join(text.splitlines()[-count:])


def _fail_text(proc: object) -> str:
    return _tail(_out(proc, "stderr") or _out(proc)) or "no output"


def _ok(proc: object) -> bool:
    return getattr(proc, "returncode", 1) == 0


def _git(root: Path, run: Run, *args: str, timeout: float | None = None) -> object:
    if timeout is None:
        return run(["git", *args], cwd=root)
    return run(["git", *args], cwd=root, timeout=timeout)


def _head(root: Path, run: Run) -> str:
    proc = _git(root, run, "rev-parse", "HEAD")
    if not _ok(proc):
        raise StepError(f"git rev-parse HEAD failed: {_fail_text(proc)}")
    return _out(proc)


def gh_json(root: Path, run: Run, args: list[str]) -> object:
    """Run a `gh ... --json` command and return its parsed output."""
    proc = run(["gh", *args], cwd=root)
    name = " ".join(args[:2])
    if not _ok(proc):
        raise StepError(f"gh {name} failed: {_fail_text(proc)}")
    try:
        return json.loads(_out(proc) or "[]")
    except ValueError as exc:
        raise StepError(f"gh {name} gave unreadable output: {exc}") from exc


def shell_runner(command: str, root: Path, on_line: Callable[[str], None]) -> tuple[int, list[str]]:
    proc = subprocess.Popen(
        command, shell=True, cwd=root, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        lines.append(line)
        on_line(line)
    return proc.wait(), lines


def open_pr(root: Path, branch: str, *, run: Run = default_run) -> str:
    """The Open PR action offered after a protected-branch rejection."""
    proc = run(["gh", "pr", "create", "--fill", "--base", branch], cwd=root)
    if not _ok(proc):
        raise StepError(f"gh pr create failed: {_fail_text(proc)}")
    return _out(proc)


def build_steps(
    root: Path,
    cfg: ReleaseConfig,
    version: str,
    *,
    changed_files: Callable[[], Sequence[Path]] = lambda: (),
    notes_path: Path | None = None,
    run: Run = default_run,
    run_shell: RunShell = shell_runner,
    sleep: Sleep = time.sleep,
    now: Now = time.monotonic,
    on_progress: OnProgress | None = None,
) -> list[Step]:
    tag = f"v{version}"
    message = f"chore: release {tag}"
    branch = cfg.branch
    detail = on_progress or (lambda text: None)

    def committed() -> bool:
        proc = _git(root, run, "log", "-1", "--format=%s")
        return _ok(proc) and _out(proc) == message

    def commit(cancel: threading.Event) -> None:
        paths = [*changed_files(), *([notes_path] if notes_path else []),
                 *release_config.pending(root)]
        wanted: list[str] = []
        for path in paths:
            full = path if path.is_absolute() else root / path
            if full.exists() and str(full) not in wanted:
                wanted.append(str(full))
        if wanted:
            proc = _git(root, run, "add", "--", *wanted)
            if not _ok(proc):
                raise StepError(f"git add failed: {_fail_text(proc)}")
        proc = _git(root, run, "commit", "-m", message)
        if not _ok(proc):
            raise StepError(f"git commit failed: {_fail_text(proc)}")
        release_config.clear_pending(root)

    def checks(cancel: threading.Event) -> bool | None:
        for command in cfg.checks:
            if cancel.is_set():
                return False
            detail(f"Running {command}")
            code, lines = run_shell(command, root, lambda line: detail(f"{command}: {line}"))
            if code != 0:
                raise StepError(f"Check failed: {command}\n{_tail(chr(10).join(lines))}")
        return None

    def push(cancel: threading.Event) -> None:
        _git(root, run, "fetch", "origin", branch, timeout=NETWORK_TIMEOUT)
        remote = f"origin/{branch}"
        if _ok(_git(root, run, "rev-parse", "--verify", "--quiet", remote)):
            if not _ok(_git(root, run, "merge-base", "--is-ancestor", remote, "HEAD")):
                raise StepError(f"{remote} has commits this branch doesn't; merge them first")
        proc = _git(root, run, "push", "origin", f"HEAD:{branch}", timeout=NETWORK_TIMEOUT)
        if not _ok(proc):
            text = f"{_out(proc, 'stderr')}\n{_out(proc)}"
            if "protected branch" in text or "GH006" in text:
                raise StepError(
                    f"{branch} is protected; open a pull request instead", open_pr=True
                )
            raise StepError(f"git push failed: {_fail_text(proc)}")

    def pushed() -> bool:
        proc = _git(root, run, "ls-remote", "origin", f"refs/heads/{branch}",
                    timeout=NETWORK_TIMEOUT)
        if not _ok(proc) or not _out(proc):
            return False
        return _out(proc).split()[0] == _head(root, run)

    def ci(cancel: threading.Event) -> bool | None:
        sha = _head(root, run)
        ignored = set(cfg.ci_ignore)
        started = now()
        while True:
            if cancel.is_set():
                return False
            runs = gh_json(root, run, ["run", "list", "--commit", sha, "--json",
                                       "name,status,conclusion,url"])
            runs = [r for r in runs if r.get("name") not in ignored]
            for item in runs:
                if item.get("status") == "completed" and item.get("conclusion") in _FAILED:
                    raise StepError(
                        f"CI failed: {item.get('name')} {item.get('url', '')}".strip()
                    )
            finished = sum(1 for r in runs if r.get("status") == "completed")
            elapsed = now() - started
            if runs and finished == len(runs):
                detail(f"{finished} of {len(runs)} checks")
                return None
            if not runs and elapsed >= NO_CI_SECONDS:
                detail("no CI configured")
                return None
            if elapsed >= CI_TIMEOUT_SECONDS:
                raise StepError(
                    f"CI is still running after 60 minutes ({finished} of {len(runs)} "
                    "checks); resume to keep waiting"
                )
            detail(f"{finished} of {len(runs)} checks" if runs else "Waiting for CI to start")
            sleep(POLL_SECONDS)

    def tag_pushed() -> bool:
        proc = _git(root, run, "ls-remote", "--tags", "origin", f"refs/tags/{tag}",
                    timeout=NETWORK_TIMEOUT)
        return _ok(proc) and bool(_out(proc))

    def make_tag(cancel: threading.Event) -> None:
        if not _ok(_git(root, run, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}")):
            proc = _git(root, run, "tag", "-a", tag, "-m", tag)
            if not _ok(proc):
                raise StepError(f"git tag failed: {_fail_text(proc)}")
        proc = _git(root, run, "push", "origin", f"refs/tags/{tag}", timeout=NETWORK_TIMEOUT)
        if not _ok(proc):
            raise StepError(f"git push of {tag} failed: {_fail_text(proc)}")

    def released() -> bool:
        return _ok(run(["gh", "release", "view", tag], cwd=root))

    def release(cancel: threading.Event) -> None:
        notes = ["--notes-file", str(notes_path)] if notes_path else ["--generate-notes"]
        proc = run(["gh", "release", "create", tag, "--title", tag, *notes],
                   cwd=root, timeout=NETWORK_TIMEOUT)
        if not _ok(proc):
            raise StepError(f"gh release create failed: {_fail_text(proc)}")

    return [
        Step("commit", "Commit the release", False, committed, commit),
        Step("checks", "Run checks", False, lambda: False, checks),
        Step("push", f"Push to {branch}", True, pushed, push),
        Step("ci", "Wait for CI", False, lambda: False, ci),
        Step("tag", f"Tag {tag}", True, tag_pushed, make_tag),
        Step("github_release", f"Create GitHub release {tag}", True, released, release),
    ]
