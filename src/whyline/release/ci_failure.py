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


def rerun(root: Path | str, failure: Failure, *, run: Callable[..., object]) -> None:
    """Ask GitHub to rerun only the failed jobs of the run in `failure`."""
    from whyline.release.github import StepError

    proc = run(["gh", "run", "rerun", failure.run_id, "--failed"], cwd=Path(root))
    if not _ok(proc):
        text = (getattr(proc, "stderr", "") or "").strip() or _stdout(proc) or "no output"
        raise StepError(f"gh run rerun failed: {text}")


ASK_LOG_LINES = 200
ASK_LINE_CHARS = 400
ASK_COMMITS = 100
ASK_STAT_LINES = 100
_ANSWER = re.compile(r"<answer>(.*?)</answer>", re.DOTALL | re.IGNORECASE)
_NEEDS_FIX = re.compile(r"^\s*NEEDS_CODE_FIX:\s*(yes|no)\b", re.IGNORECASE | re.MULTILINE)


@dataclass
class Answer:
    text: str
    needs_fix: bool = False


def _cap(text: str, lines: int) -> str:
    kept = [line[:ASK_LINE_CHARS] for line in text.splitlines() if line.strip()]
    return "\n".join(kept[-lines:])


def _git_text(root: Path, run: Callable[..., object], args: list[str]) -> str:
    try:
        proc = run(["git", *args], cwd=root)
        return _stdout(proc) if _ok(proc) else ""
    except Exception:  # noqa: BLE001 - the prompt just goes without it
        return ""


def log_path(root: Path | str) -> Path:
    return Path(root) / ".git" / "whyline-release" / "release.log"


def append_log(root: Path | str, text: str) -> None:
    try:
        path = log_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text.rstrip() + "\n\n")
    except OSError:
        pass


def build_ask_prompt(root: Path | str, failure: Failure, *, run: Callable[..., object]) -> str:
    from whyline.release import notes

    root = Path(root)
    log = _text(root, run, ["run", "view", failure.run_id, "--log-failed"]) if failure.run_id else None
    excerpt = _cap(log, ASK_LOG_LINES) if log else _cap(failure.excerpt, ASK_LOG_LINES)
    tag = notes.last_tag(root, run=run)
    if tag:
        commits = _git_text(root, run, ["log", "--format=%s", f"{tag}..HEAD"])
        stat = _git_text(root, run, ["diff", "--stat", f"{tag}..HEAD"])
    else:
        commits = _git_text(root, run, ["log", "--format=%s", f"-{ASK_COMMITS}"])
        stat = ""
    commits = "\n".join(commits.splitlines()[:ASK_COMMITS])
    stat = "\n".join(stat.splitlines()[-ASK_STAT_LINES:])
    return (
        "A release's CI run failed. Work out what went wrong and what to do about it.\n"
        "You may not change anything; only read and answer.\n\n"
        f"The failure:\n{failure.text()}\n\n"
        f"Log of the failed job (last {ASK_LOG_LINES} lines at most):\n{excerpt or '(no log)'}\n\n"
        f"Commits since the last tag ({tag or 'none'}):\n{commits or '(none)'}\n\n"
        f"git diff --stat {tag or ''}..HEAD:\n{stat or '(none)'}\n\n"
        "Say what went wrong and what to do, in plain words, between <answer> and </answer>. "
        "End your reply with one line, `NEEDS_CODE_FIX: yes` if the code must change, "
        "or `NEEDS_CODE_FIX: no` if rerunning or changing settings is enough."
    )


def parse_answer(reply: str) -> Answer:
    flags = _NEEDS_FIX.findall(reply)
    needs_fix = bool(flags) and flags[-1].lower() == "yes"
    found = _ANSWER.search(reply)
    text = _NEEDS_FIX.sub("", found.group(1) if found else reply)
    return Answer(text.strip(), needs_fix)


def ask(root: Path | str, failure: Failure, *, ask_agent: Callable[[str], str],
        run: Callable[..., object]) -> Answer:
    """Ask a read-only agent why the run failed; the answer goes into the release log."""
    prompt = build_ask_prompt(root, failure, run=run)
    answer = parse_answer(ask_agent(prompt))
    append_log(root, f"Asked an agent about run {failure.run_id or '?'}:\n{answer.text}\n"
                     f"NEEDS_CODE_FIX: {'yes' if answer.needs_fix else 'no'}")
    return answer
