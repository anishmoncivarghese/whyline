"""GitHub setup for releases: sign in with gh, then create and link the repository."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from whyline.release.ready import default_run

Run = Callable[..., object]
# run_streaming(args, stdin, on_line) -> exit code
RunStreaming = Callable[[list[str], str, Callable[[str], None]], int]

NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
SIGN_IN_ARGS = ["gh", "auth", "login", "--web", "--git-protocol", "https",
                "--hostname", "github.com"]
NETWORK_TIMEOUT = 120.0


class SetupError(RuntimeError):
    """Setup cannot go ahead; the message is shown to the user."""


@dataclass(frozen=True)
class GitHubStatus:
    gh_installed: bool
    signed_in: bool
    user: str
    origin_url: str
    origin_is_github: bool


def default_run_streaming(args: list[str], stdin: str, on_line: Callable[[str], None]) -> int:
    proc = subprocess.Popen(args, text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    assert proc.stdin is not None and proc.stdout is not None
    try:
        proc.stdin.write(stdin)
        proc.stdin.close()
    except OSError:
        pass
    for raw in proc.stdout:
        on_line(raw.rstrip("\n"))
    return proc.wait()


def _ok(proc: object) -> bool:
    return getattr(proc, "returncode", 1) == 0


def _out(proc: object, name: str = "stdout") -> str:
    return (getattr(proc, name, "") or "").strip()


def _try(run: Run, args: list[str], **kwargs) -> object | None:
    try:
        return run(args, **kwargs)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _is_github(url: str) -> bool:
    return bool(re.match(r"^(https?://([^/@]+@)?github\.com/|(ssh://)?git@github\.com[:/])", url))


def _origin(root: Path, run: Run) -> str:
    proc = _try(run, ["git", "remote", "get-url", "origin"], cwd=root)
    return _out(proc) if proc is not None and _ok(proc) else ""


def status(root: Path, *, run: Run = default_run) -> GitHubStatus:
    origin = _origin(root, run)
    installed = _try(run, ["gh", "--version"], cwd=root)
    if installed is None or not _ok(installed):
        return GitHubStatus(False, False, "", origin, _is_github(origin))
    auth = _try(run, ["gh", "auth", "status", "--hostname", "github.com"], cwd=root)
    if auth is None or not _ok(auth):
        return GitHubStatus(True, False, "", origin, _is_github(origin))
    who = _try(run, ["gh", "api", "user", "--jq", ".login"], cwd=root,
               timeout=NETWORK_TIMEOUT)
    user = _out(who) if who is not None and _ok(who) else ""
    return GitHubStatus(True, True, user, origin, _is_github(origin))


def sign_in(*, run_streaming: RunStreaming = default_run_streaming,
            on_line: Callable[[str], None]) -> int:
    """Run the browser sign-in; the one-time code arrives through on_line."""
    return run_streaming(list(SIGN_IN_ARGS), "\n", on_line)


def create_repo(root: Path, name: str, *, private: bool = True, description: str = "",
                run: Run = default_run) -> str:
    """Create the GitHub repository and add it as origin. Never pushes."""
    if not NAME_PATTERN.match(name):
        raise SetupError(
            "A repository name is 1 to 100 letters, numbers, dots, dashes or underscores."
        )
    existing = _origin(root, run)
    if existing:
        raise SetupError(f"This project already has an origin: {existing}")
    args = ["gh", "repo", "create", name, "--private" if private else "--public",
            "--source", ".", "--remote", "origin"]
    if description:
        args += ["--description", description]
    proc = _try(run, args, cwd=root, timeout=NETWORK_TIMEOUT)
    if proc is None:
        raise SetupError("gh repo create could not run; is gh installed?")
    if not _ok(proc):
        detail = _out(proc, "stderr") or _out(proc) or "no output"
        raise SetupError(f"gh repo create failed: {detail}")
    url = _origin(root, run)
    if url:
        return url
    lines = _out(proc).splitlines()
    return lines[-1].strip() if lines else ""
