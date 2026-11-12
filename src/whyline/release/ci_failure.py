"""Say why a CI run failed, in one plain sentence a person can act on."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

NO_RUNNER = "no-runner"
TIMEOUT = "timeout"
TESTS = "tests"
PUBLISH = "publish"
OTHER = "other"

_BAD = {"failure", "cancelled", "timed_out", "startup_failure", "action_required", "stale"}
EXCERPT_LINES = 20
_FAILED_TEST = re.compile(r"FAILED\s+(\S+)")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class Failure:
    cause: str = OTHER
    run_id: str = ""
    workflow: str = ""
    attempt: int = 1
    job: str = ""
    step: str = ""
    url: str = ""
    tests: list[str] = field(default_factory=list)
    excerpt: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> Failure | None:
        if not isinstance(data, dict) or not data:
            return None
        try:
            return cls(
                cause=str(data.get("cause", OTHER)),
                run_id=str(data.get("run_id", "")),
                workflow=str(data.get("workflow", "")),
                attempt=int(data.get("attempt", 1) or 1),
                job=str(data.get("job", "")),
                step=str(data.get("step", "")),
                url=str(data.get("url", "")),
                tests=[str(t) for t in data.get("tests", [])],
                excerpt=str(data.get("excerpt", "")),
            )
        except (TypeError, ValueError):
            return None

    def sentence(self) -> str:
        job = self.job or "the job"
        if self.cause == NO_RUNNER:
            low = job.lower()
            os_name = next((label for key, label in (
                ("macos", "macOS "), ("windows", "Windows "), ("ubuntu", "Linux "),
            ) if key in low), "")
            return (f"GitHub couldn't find a {os_name}machine for {job}. "
                    "Your code is fine; rerun it.")
        if self.cause == TIMEOUT:
            return f"{job} ran past its time limit and was stopped. Rerun it."
        if self.cause == TESTS:
            return f"Tests failed in {job}. Your code needs a fix."
        if self.cause == PUBLISH:
            step = f" at {self.step}" if self.step else ""
            return f"Publishing failed in {job}{step}. The tests passed; check the publish settings."
        step = f" at {self.step}" if self.step else ""
        return f"{job} failed{step} for a reason that isn't clear."

    def text(self) -> str:
        parts = [self.sentence()]
        where = self.workflow
        if self.attempt:
            where = f"{where}, attempt {self.attempt}" if where else f"attempt {self.attempt}"
        if where:
            parts.append(where)
        if self.cause == TESTS and self.tests:
            parts.append("\n".join(self.tests))
        elif self.excerpt:
            parts.append(self.excerpt)
        if self.url:
            parts.append(self.url)
        return "\n".join(parts)


def _stdout(proc: object) -> str:
    return (getattr(proc, "stdout", "") or "").strip()


def _ok(proc: object) -> bool:
    return getattr(proc, "returncode", 1) == 0


_FAILED = object()  # a gh call that failed, as opposed to one that answered with nothing


def _json(root: Path, run: Callable[..., object], args: list[str]) -> object:
    try:
        proc = run(["gh", *args], cwd=root)
        if not _ok(proc):
            return _FAILED
        return json.loads(_stdout(proc) or "null")
    except Exception:  # noqa: BLE001 - a broken gh gives an unknown cause, not a crash
        return _FAILED


def _text(root: Path, run: Callable[..., object], args: list[str]) -> str | None:
    try:
        proc = run(["gh", *args], cwd=root)
        return _ANSI.sub("", getattr(proc, "stdout", "") or "") if _ok(proc) else None
    except Exception:  # noqa: BLE001
        return None


def _excerpt(log: str) -> str:
    lines = [line.rstrip() for line in log.splitlines() if line.strip()]
    return "\n".join(lines[-EXCERPT_LINES:])


def diagnose(root: Path | str, run_id: object, *, run: Callable[..., object]) -> Failure:
    """Work out why run `run_id` failed; never raises."""
    root = Path(root)
    failure = Failure(run_id=str(run_id))
    data = _json(root, run, ["run", "view", str(run_id), "--json", "jobs,name,url,attempt"])
    if not isinstance(data, dict):
        return failure
    failure.workflow = str(data.get("name", "") or "")
    failure.url = str(data.get("url", "") or "")
    try:
        failure.attempt = int(data.get("attempt", 1) or 1)
    except (TypeError, ValueError):
        failure.attempt = 1
    jobs = [j for j in data.get("jobs", []) or [] if isinstance(j, dict)]
    bad = next((j for j in jobs if j.get("conclusion") in _BAD), None)
    if bad is None:
        return failure
    failure.job = str(bad.get("name", "") or "")
    failure.url = str(bad.get("url", "") or failure.url)
    steps = [s for s in bad.get("steps", []) or [] if isinstance(s, dict)]
    failed_step = next((s for s in steps if s.get("conclusion") in _BAD), None)
    if failed_step is not None:
        failure.step = str(failed_step.get("name", "") or "")
    job_id = bad.get("databaseId")

    notes = (_json(root, run, ["api", f"repos/{{owner}}/{{repo}}/check-runs/{job_id}/annotations"])
             if job_id else None)
    if notes is _FAILED:
        return failure
    messages = " ".join(
        str(n.get("message", "")) for n in notes if isinstance(n, dict)
    ) if isinstance(notes, list) else ""

    if (not any(s.get("conclusion") for s in steps)
            or "not acquired by Runner" in messages or "capacity" in messages):
        failure.cause = NO_RUNNER
        return failure
    if "exceeded the maximum execution time" in messages:
        failure.cause = TIMEOUT
        return failure

    log = _text(root, run, ["run", "view", str(run_id), "--log-failed"])
    if log is None:
        return failure
    if not log.strip() and job_id:
        log = _text(root, run, ["api", f"repos/{{owner}}/{{repo}}/actions/jobs/{job_id}/logs"])
        if log is None:
            return failure
    failure.excerpt = _excerpt(log)
    step = failure.step.lower()
    if "pytest" in step or "test" in step:
        failure.cause = TESTS
        seen: list[str] = []
        for match in _FAILED_TEST.finditer(log):
            if match.group(1) not in seen:
                seen.append(match.group(1))
        failure.tests = seen
    elif "publish" in step or "upload" in step:
        failure.cause = PUBLISH
    return failure
