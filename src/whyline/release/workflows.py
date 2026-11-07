"""GitHub Actions helpers for release targets: find a publishing workflow, write a
template, and wait for the run a tag push starts."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from whyline.release import github
from whyline.release.github import StepError
from whyline.release.ready import default_run

TAG_RUN_TIMEOUT_SECONDS = 45 * 60

_PUSH = re.compile(r"^(\s*)push\s*:(.*)$")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _runs_on_tags(text: str) -> bool:
    """True when a `push:` trigger lists `tags:` (block or inline form)."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _PUSH.match(line)
        if not match or line.lstrip().startswith("#"):
            continue
        rest = match.group(2).split("#", 1)[0]
        if re.search(r"\btags\s*:", rest):
            return True
        base = len(match.group(1))
        for inner in lines[index + 1:]:
            stripped = inner.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if _indent(inner) <= base:
                break
            if re.match(r"tags\s*:", stripped):
                return True
    return False


def find_publishing(root: Path | str, needle: str) -> Path | None:
    """The first workflow that mentions `needle` and runs when a tag is pushed."""
    folder = Path(root) / ".github" / "workflows"
    if not folder.is_dir():
        return None
    for path in sorted([*folder.glob("*.yml"), *folder.glob("*.yaml")]):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if needle in text and _runs_on_tags(text):
            return path
    return None


def write_template(root: Path | str, name: str, text: str) -> Path:
    """Write `.github/workflows/<name>`; never replaces a file that is already there."""
    path = Path(root) / ".github" / "workflows" / name
    if path.exists():
        raise FileExistsError(f"{path} already exists; it was not changed")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _failed_job(root: Path, run_id: object, run: github.Run) -> str:
    try:
        data = github.gh_json(root, run, ["run", "view", str(run_id), "--json", "jobs"])
    except StepError:
        return ""
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    for job in jobs:
        if job.get("conclusion") in github._FAILED:
            return str(job.get("name", ""))
    return ""


def wait_for_tag_run(
    root: Path | str,
    tag: str,
    workflow_file: str | Path,
    *,
    run: github.Run = default_run,
    sleep: github.Sleep = time.sleep,
    now: github.Now = time.monotonic,
    cancel_event: threading.Event | None = None,
    on_detail: Callable[[str], None] | None = None,
) -> bool | None:
    """Poll the workflow run for `tag` until it passes (None), is cancelled (False),
    or raise StepError if it fails or is still going after 45 minutes."""
    root = Path(root)
    name = Path(workflow_file).name
    cancel = cancel_event or threading.Event()
    detail = on_detail or (lambda text: None)
    started = now()
    while True:
        if cancel.is_set():
            return False
        runs = github.gh_json(root, run, [
            "run", "list", "--workflow", name, "--branch", tag, "--json",
            "status,conclusion,url,databaseId"])
        latest = runs[0] if runs else None
        if latest is None:
            detail(f"Waiting for {name} to start")
        elif latest.get("status") == "completed":
            if latest.get("conclusion") in github._FAILED:
                job = _failed_job(root, latest.get("databaseId"), run)
                where = f" in job {job}" if job else ""
                raise StepError(
                    f"{name} failed{where} {latest.get('url', '')}".strip())
            detail(f"{name} finished")
            return None
        else:
            detail(f"{name} is {latest.get('status', 'running')}")
        if now() - started >= TAG_RUN_TIMEOUT_SECONDS:
            raise StepError(
                f"{name} is still running after 45 minutes; resume to keep waiting")
        sleep(github.POLL_SECONDS)
