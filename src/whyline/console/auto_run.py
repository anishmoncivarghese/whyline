"""Schema 1 fingerprint of an unsaved Auto request, and its run.

`document` is the canonical mapping. `fingerprint` is the sha256 hex of that
mapping as JSON with `sort_keys=True` and separators `(',', ':')`.

Keys: `schema`, every `AutoRunRequest` field (`attachments` entries are
`path`, `size`, and `sha256`, or null size and digest when the path is not a
readable file), `models`, `available`, `head` (`git rev-parse HEAD` stdout),
`porcelain` (`git status --porcelain` stdout), and `antigravity`
(`trusted`, `declined`, `ask`, or `unused`).

`run` revalidates that fingerprint, takes `.whyline/relay/auto-run.lock`,
persists the relay config once, then researches, gates the synthesis, and
drafts the spec and the plan. Final preflight selects that plan and runs
`preflight` at full scope. Zero `FAIL` lines launch the relay. A pause stops
the run. The runner does not invent an answer. Widget handlers stay out.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from whyline import account, model
from whyline.console import relay_ops
from whyline.console.plan_job import AutoRunRequest
from whyline.state import atomic_write_json, load_object, unlink_busy_safe

SCHEMA = 1

# These redirect git at a different repository than `root`. A caller inside
# another checkout, or a hook that exported them, must still fingerprint `root`.
_IGNORED_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")

# Revalidate compares the form, not the git snapshot. The persist commit
# moves HEAD, and porcelain is a separate clean-tree check.
_SKIPPED_IN_FORM = ("head", "porcelain")

PAUSE_ACTIONS = frozenset({"resume", "change", "replace", "cancel", "recover"})

_COMMIT_MESSAGE = "setup: auto run roles, backup, and timeout"

# The paragraph RUN-1 appends to an unattended synthesis. Spec drafting gets
# the same paragraph. Plan drafting does not.
_UNATTENDED_PARAGRAPH = (
    "Decide questions whose answer follows from the request, "
    "record each decision in the document, and leave "
    '"## Open questions" only for a choice that would change what '
    "gets built and cannot be derived from the request."
)

_GATE_ACTIONS = ("resume", "change", "cancel")

_PREFLIGHT_PROGRESS = "auto · final preflight"

# Printed with the FAIL lines when full preflight stops before the launcher.
_SETUP_CAN_OPEN = "Set up can open on that plan."

_PLANNER_LINE = re.compile(
    r"^(?P<agent>\S+) is (?P<action>drafting the spec|drafting the plan|drafting the test plan|reviewing the draft)$"
)


def _request_test_planner(request: AutoRunRequest) -> str:
    return str(
        getattr(request, "test_planner", "")
        or getattr(request, "test", "")
        or getattr(getattr(request, "drafter", ""), "_test_planner", "")
        or ""
    )


def named_agents(request: AutoRunRequest) -> tuple[str, ...]:
    """Research agents, the final writer, drafter, reviewer, implementer, tester,
    execution reviewer, every chain member, and release when it is not `human`.

    Empty strings are not names. Each name appears once, in that order.
    """
    names: list[str] = [
        *request.agents,
        request.final_agent,
        request.drafter,
        _request_test_planner(request),
        request.reviewer,
        request.implementer,
        request.tester,
        request.reviewer_role,
        *request.chain,
    ]
    if request.release != "human":
        names.append(request.release)
    seen: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def _resolved_models(root: Path, names: tuple[str, ...]) -> dict[str, str]:
    """The model string `model.resolve` uses: repo `load`, then `load_global()["models"]`.

    Unset, or a non-string, is `""`.
    """
    repo = model.load(root)
    glob = model.load_global()
    models = glob.get("models")
    if not isinstance(models, dict):
        models = {}
    resolved: dict[str, str] = {}
    for agent in names:
        chosen = repo.get(agent) or models.get(agent) or ""
        resolved[agent] = chosen if isinstance(chosen, str) else ""
    return resolved


def _attachment(path: Path) -> dict:
    """`size` and `sha256` are null when the path is missing or not a readable file.

    Size is the number of bytes that were hashed, so the two fields describe
    the same read.
    """
    record: dict = {"path": str(path), "size": None, "sha256": None}
    if not path.is_file():
        return record
    try:
        data = path.read_bytes()
    except OSError:
        return record
    record["size"] = len(data)
    record["sha256"] = hashlib.sha256(data).hexdigest()
    return record


def _git_stdout(root: Path, *args: str) -> str:
    env = os.environ.copy()
    for key in _IGNORED_GIT_ENV:
        env.pop(key, None)
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout


def _antigravity(root: Path, names: tuple[str, ...]) -> str:
    if "antigravity" not in names:
        return "unused"
    return relay_ops.antigravity_state(root)


def document(root: Path, request: AutoRunRequest) -> dict:
    """The schema-1 mapping `fingerprint` hashes."""
    names = named_agents(request)
    status = account.agent_status(root)
    test_planner = _request_test_planner(request)
    doc = {
        "schema": SCHEMA,
        "name": request.name,
        "topic": request.topic,
        "replace": request.replace,
        "continue_paths": request.continue_paths,
        "agents": list(request.agents),
        "passes": request.passes,
        "final_agent": request.final_agent,
        "timeout_minutes": request.timeout_minutes,
        "attachments": [_attachment(path) for path in request.attachments],
        "drafter": str(request.drafter),
        "reviewer": str(request.reviewer),
        "implementer": request.implementer,
        "tester": request.tester,
        "reviewer_role": request.reviewer_role,
        "release": request.release,
        "chain": list(request.chain),
        "models": _resolved_models(root, names),
        "available": {agent: status[agent]["available"] for agent in names},
        "head": _git_stdout(root, "rev-parse", "HEAD"),
        "porcelain": _git_stdout(root, "status", "--porcelain"),
        "antigravity": _antigravity(root, names),
    }
    if test_planner:
        doc["test_planner"] = test_planner
    return doc


def fingerprint(root: Path, request: AutoRunRequest) -> str:
    raw = json.dumps(document(root, request), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _digest(body: dict) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _form_view(body: dict) -> dict:
    """Request fields, attachment hashes, models, availability, and trust.

    `head` and `porcelain` stay in `document` for Check. They are not part of
    this view: a persist commit is allowed to move HEAD.
    """
    return {key: value for key, value in body.items() if key not in _SKIPPED_IN_FORM}


def form_document(root: Path, request: AutoRunRequest) -> dict:
    """The form half of `document`, with `head` and `porcelain` removed."""
    return _form_view(document(root, request))


def form_fingerprint(root: Path, request: AutoRunRequest) -> str:
    """sha256 of `form_document`, in the same canonical JSON as `fingerprint`."""
    return _digest(form_document(root, request))


class AutoBusy(RuntimeError):
    """A live pid holds `.whyline/relay/auto-run.lock`."""


class AutoStale(RuntimeError):
    """The form does not match the fingerprint Check dismissed with."""


def checkpoint_path(root: Path) -> Path:
    return root / ".whyline" / "relay" / "auto-run.json"


def lock_path(root: Path) -> Path:
    return root / ".whyline" / "relay" / "auto-run.lock"


def _read_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def acquire_lock(root: Path) -> None:
    """Take `.whyline/relay/auto-run.lock` for this process.

    `gitcheck.ensure_relay_ignored` runs before the lock file is created.
    The create flag is `O_CREAT|O_EXCL`. A lock whose pid is dead is removed
    and the create is retried. A live pid, or a lock that is not a pid,
    raises `AutoBusy`.
    """
    from whyline_relay import gitcheck, running

    gitcheck.ensure_relay_ignored(root)
    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = f"{os.getpid()}\n".encode("ascii")
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if not path.exists():
                continue
            pid = _read_pid(path)
            if pid is not None and not running.pid_is_alive(pid):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            raise AutoBusy("An Auto run is already in progress.") from None
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
        finally:
            os.close(descriptor)
        return


def release_lock(root: Path) -> None:
    """Remove the lock when this process holds it. A foreign lock stays."""
    path = lock_path(root)
    if _read_pid(path) != os.getpid():
        return
    # Closing during a run releases from the UI thread and the worker at
    # once; on Windows the other thread's _read_pid can hold the file open.
    unlink_busy_safe(path)


def _matches(fresh: dict, dismissed: str, saved: dict | None) -> bool:
    """True when `dismissed` still authorizes this form.

    The first call accepts Check's full fingerprint, or the form fingerprint.
    A later call accepts that same dismissed value when the stored form still
    matches. The stored HEAD is not compared.
    """
    if dismissed == _digest(fresh) or dismissed == _digest(_form_view(fresh)):
        return True
    if not isinstance(saved, dict) or saved.get("schema") != SCHEMA:
        return False
    if dismissed not in (saved.get("fingerprint"), saved.get("last_check")):
        return False
    stored = saved.get("request")
    return isinstance(stored, dict) and stored == _form_view(fresh)


def _artifact_record(saved: dict | None, key: str) -> dict:
    record = saved.get(key) if isinstance(saved, dict) else None
    if isinstance(record, dict):
        return {"path": record.get("path"), "sha256": record.get("sha256")}
    return {"path": None, "sha256": None}


def _checked_pause(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("pause must be an object with a reason and actions")
    reason = value.get("reason")
    actions = value.get("actions")
    if not isinstance(reason, str) or not isinstance(actions, list):
        raise ValueError("pause must be an object with a reason and actions")
    if any(not isinstance(item, str) or item not in PAUSE_ACTIONS for item in actions):
        raise ValueError(
            "pause actions must be a subset of resume, change, replace, cancel, recover"
        )
    if len(set(actions)) != len(actions):
        raise ValueError(
            "pause actions must be a subset of resume, change, replace, cancel, recover"
        )
    return {"reason": reason, "actions": list(actions)}


def _checkpoint(
    saved: dict | None,
    request: AutoRunRequest,
    fresh: dict,
    dismissed: str,
    *,
    phase: str,
    persist_commit: str | None,
) -> dict:
    body = {
        "schema": SCHEMA,
        "fingerprint": dismissed,
        "phase": phase,
        "topic": request.topic,
        "name": request.name,
        "request": _form_view(fresh),
        "brainstorm": _artifact_record(saved, "brainstorm"),
        "spec": _artifact_record(saved, "spec"),
        "plan": _artifact_record(saved, "plan"),
        "persist_commit": persist_commit,
        "last_check": dismissed,
    }
    if isinstance(saved, dict) and "pause" in saved:
        body["pause"] = _checked_pause(saved["pause"])
    return body


def _persist(root: Path, request: AutoRunRequest) -> str:
    """Write the setup keys without committing, then commit them once.

    `reviewer` is the planner. `reviewer_role` is the execution reviewer.
    `commit_paths` is a no-op when those files have no diff, so a second call
    with the same content does not add a commit. `timeout_minutes` is the
    request value, including 0, written as an unquoted integer.
    """
    from whyline_relay import gitcheck, setup

    setup.write_planner(
        root,
        str(request.drafter),
        str(request.reviewer),
        _request_test_planner(request),
        commit=False,
    )
    written = setup.write_roles(
        root,
        request.implementer,
        request.tester,
        request.reviewer_role,
        request.chain,
        commit=False,
    )
    setup.write_release(root, request.release, commit=False)
    setup.write_timeout_minutes(root, request.timeout_minutes, commit=False)
    # select_plan commits when `plan` changes. The path is fixed by the
    # request, so writing it into this commit keeps phase 7 from committing
    # config.toml again.
    plan_rel = relay_ops.plan_path(root, _work_name(request)).relative_to(root).as_posix()
    setup.write_plan(root, plan_rel, commit=False)
    gitcheck.commit_paths(root, list(written), _COMMIT_MESSAGE)
    return _git_stdout(root, "rev-parse", "HEAD").strip()


def artifact_matches(record: object) -> bool:
    """True when `record`'s file exists and its bytes hash to `sha256`.

    A later phase whose stored artifact matches is not called again. Persist
    has no file hash; it uses `commit_paths` instead of this check.
    """
    if not isinstance(record, dict):
        return False
    path_text = record.get("path")
    digest = record.get("sha256")
    if not isinstance(path_text, str) or not path_text:
        return False
    if not isinstance(digest, str) or not digest:
        return False
    path = Path(path_text)
    if not path.is_file():
        return False
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return hashlib.sha256(data).hexdigest() == digest


class _ModelFailure(Exception):
    """The agent that just ran failed. The backup chain may try the next one."""


class _NeedPause(Exception):
    """The chain is exhausted, or the draft loop stopped for a person."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _emit(progress, line: str) -> None:
    if progress is not None:
        progress(line)


def _timeout_seconds(minutes: int):
    """`0` is no watchdog. A positive count is that many seconds."""
    from whyline_relay import chat

    if minutes == 0:
        return chat.NO_LIMIT
    return minutes * 60


def _mark_pause(current: dict, phase: str, reason: str) -> dict:
    current["phase"] = phase
    current["pause"] = {"reason": reason, "actions": list(_GATE_ACTIONS)}
    return current


def _clear_pause(current: dict) -> None:
    current.pop("pause", None)


def _save(root: Path, current: dict) -> dict:
    atomic_write_json(checkpoint_path(root), current)
    return current


def _hold_pause(current: dict, saved_phase: str | None, phase: str, answer: str | None) -> bool:
    """Hold a research pause until a person answers it.

    A spec or plan pause is a Resume. Returning it again would skip
    `resume_spec` / `resume_draft`, so those phases always re-enter.
    """
    if phase != "research":
        return False
    if saved_phase != phase or not isinstance(current.get("pause"), dict):
        return False
    if answer:
        return False
    current["phase"] = phase
    return True


def _questions_reason(questions: list[str]) -> str:
    lines = "\n".join(f"{index}. {question}" for index, question in enumerate(questions, 1))
    return f"Open questions:\n{lines}"


def _exhausted(tried: list[str]) -> str:
    return "Backup chain exhausted. Agents tried: " + ", ".join(tried) + "."


def _shown(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _has_final(path: Path) -> bool:
    return "## Final Synthesis" in _read_text(path)


def _store_artifact(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def _brainstorm_doc(root: Path, topic: str) -> tuple[Path, str]:
    from whyline_relay import brainstorm

    shared = brainstorm.shared_path(root, topic)
    return shared, _shown(root, shared)


def _work_name(request: AutoRunRequest) -> str:
    return request.name or request.topic or "plan"


def _spec_request(doc: str) -> str:
    base = (
        f"Write the spec from the brainstorm in {doc} "
        "(its Final Synthesis is the agreed direction)."
    )
    return f"{base}\n\n{_UNATTENDED_PARAGRAPH}"


def _next_backup(chain: tuple[str, ...] | list[str], tried: list[str]) -> str | None:
    from whyline_relay import failover

    backup = failover.next_backup(list(chain), set(tried))
    if not isinstance(backup, str) or backup not in tuple(chain):
        return None
    return backup


def _substitute_agent(agents: list[str], failed: str, backup: str) -> list[str]:
    """Replace a failed agent without running an existing backup twice."""
    replaced: list[str] = []
    for agent in agents:
        candidate = backup if agent == failed else agent
        if candidate not in replaced:
            replaced.append(candidate)
    if backup not in replaced:
        replaced.append(backup)
    return replaced


def _requested_writer(args, kwargs) -> str | None:
    writer = kwargs.get("final_agent")
    if isinstance(writer, str) and writer:
        return writer
    if len(args) >= 2 and isinstance(args[1], str) and args[1]:
        return args[1]
    return None


def _only_writer(models, writer: str | None):
    """The synthesis roster brainstorm is allowed to walk on this attempt.

    `run_final_synthesis` tries every selected research agent after a failure.
    That substitutes an agent that is not in the saved chain. Auto walks the
    chain itself, through `failover.next_backup`, so this attempt keeps only
    the writer it asked for.
    """
    if not isinstance(models, (list, tuple)) or not writer:
        return models
    kept = []
    for item in models:
        key = item[0] if isinstance(item, (tuple, list)) and item else item
        if key == writer:
            kept.append(item)
    if isinstance(models, tuple):
        return tuple(kept)
    return kept


def _limit_synthesis_models(args, kwargs):
    writer = _requested_writer(args, kwargs)
    if len(args) >= 3 and "models" not in kwargs:
        limited = _only_writer(args[2], writer)
        if limited is args[2]:
            return args, kwargs
        updated = list(args)
        updated[2] = limited
        return tuple(updated), kwargs
    models = kwargs.get("models")
    limited = _only_writer(models, writer)
    if limited is models:
        return args, kwargs
    copied = dict(kwargs)
    copied["models"] = limited
    return args, copied


def _on_brainstorm_progress(progress):
    """Translate a brainstorm start event into the Auto transcript line."""

    def on_event(event) -> None:
        if progress is None or getattr(event, "status", None) != "starting":
            return
        phase = getattr(event, "phase", "")
        agent = getattr(event, "agent", "")
        if phase == "pass-zero":
            progress(f"auto · research {event.ordinal}/{event.total} · {agent}")
        elif phase == "synthesis":
            progress(f"auto · synthesis · {agent}")

    return on_event


def _substitution_print(progress):
    """Brainstorm already names a substituted section on this stream."""

    def print_fn(line="") -> None:
        text = line if isinstance(line, str) else str(line)
        if progress is not None and "substitut" in text.lower():
            progress(text)

    return print_fn


def _planner_progress_line(kind: str, stage: str, visit: int, cap: int, agent: str) -> str | None:
    if kind == "spec" and stage == "review":
        return f"auto · spec review {visit}/{cap} · {agent}"
    if kind == "spec" and stage == "draft":
        return f"auto · spec draft {visit}/{cap} · {agent}"
    if kind == "plan" and stage == "review":
        return "auto · plan review"
    if kind == "plan" and stage == "draft":
        return f"auto · plan draft {visit}/{cap} · {agent}"
    return None


def _planner_visit(root: Path, kind: str, stage: str) -> tuple[int, int]:
    from whyline_relay import config, planner, state

    kind_obj = planner.SPEC_KIND if kind == "spec" else planner.PLAN_KIND
    saved = state.load_plan(root, name=kind_obj.state_name)
    visit = 1
    if saved is not None and isinstance(saved.stage_visits, dict):
        raw = saved.stage_visits.get(stage)
        if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
            visit = raw
    cap = 3
    try:
        loaded = config.load(root).planner.max_visits
    except Exception:
        loaded = 3
    if isinstance(loaded, int) and not isinstance(loaded, bool) and loaded > 0:
        cap = loaded
    return visit, cap


def _on_planner_line(root: Path, kind: str, progress, line, last_agent: dict) -> None:
    match = _PLANNER_LINE.match(str(line).strip())
    if not match:
        return
    agent = match.group("agent")
    last_agent["name"] = agent
    if progress is None:
        return
    stage = "review" if match.group("action") == "reviewing the draft" else "draft"
    visit, cap = _planner_visit(root, kind, stage)
    text = _planner_progress_line(kind, stage, visit, cap, agent)
    if text:
        progress(text)


@contextmanager
def _brainstorm_call(timeout_seconds, cancel_event, on_progress):
    """Apply Auto's timeout, cancel, and unattended flag to brainstorm's own calls.

    `adapters.run_brainstorm` multiplies minutes by 60 and does not take
    `cancel_event` or `unattended`. This task cannot change that adapter.
    """
    from whyline_relay import brainstorm

    names = ("run_pass_zero", "run_review_pass", "run_final_synthesis")
    saved = {name: getattr(brainstorm, name) for name in names}

    def wrap(name: str, **forced):
        original = saved[name]

        def wrapped(*args, **kwargs):
            kwargs["timeout_seconds"] = timeout_seconds
            kwargs["cancel_event"] = cancel_event
            kwargs.update(forced)
            if on_progress is not None:
                kwargs["progress_fn"] = on_progress
            if name == "run_final_synthesis":
                args, kwargs = _limit_synthesis_models(args, kwargs)
            return original(*args, **kwargs)

        return wrapped

    brainstorm.run_pass_zero = wrap("run_pass_zero")
    brainstorm.run_review_pass = wrap("run_review_pass")
    brainstorm.run_final_synthesis = wrap("run_final_synthesis", unattended=True)
    try:
        yield
    finally:
        for name, original in saved.items():
            setattr(brainstorm, name, original)


@contextmanager
def _synthesis_revision_call(cancel_event):
    """Pass Auto's cancellation event through relay_ops' fixed interface."""
    from whyline_relay import brainstorm

    original = brainstorm.revise_synthesis

    def wrapped(*args, **kwargs):
        kwargs["cancel_event"] = cancel_event
        return original(*args, **kwargs)

    brainstorm.revise_synthesis = wrapped
    try:
        yield
    finally:
        brainstorm.revise_synthesis = original


def _research_status(result) -> tuple[str, str]:
    from whyline.console import adapters

    if result is None:
        return "ok", ""
    kind = getattr(result, "kind", None)
    text = getattr(result, "text", "")
    if isinstance(result, dict):
        kind = result.get("outcome", result.get("kind", kind))
        text = str(result.get("text") or result.get("reason") or text or "")
    text = text if isinstance(text, str) else str(text or "")
    if kind == "blocked" or adapters.failure_kind(text) == "blocked":
        return "blocked", text or "Brainstorm blocked."
    if kind == "error":
        return "failure", text or "Research failed."
    return "ok", ""


def _invoke_brainstorm(root, request, agents, final_agent, progress, cancel_event):
    from whyline.console import adapters
    from whyline_relay import agents as relay_agents
    from whyline_relay import brainstorm, chat

    timeout = _timeout_seconds(request.timeout_minutes)
    try:
        with _brainstorm_call(timeout, cancel_event, _on_brainstorm_progress(progress)):
            result = adapters.run_brainstorm(
                root,
                topic=request.topic,
                agents=list(agents),
                passes=request.passes,
                final_agent=final_agent,
                timeout_minutes=request.timeout_minutes,
                progress=_substitution_print(progress),
                attachments=list(request.attachments),
            )
    except relay_agents.AgentCancelled:
        raise
    except (
        relay_agents.AgentTimeout,
        relay_agents.AgentMissing,
        chat.AgentUnavailable,
        brainstorm.NothingToSynthesize,
    ) as error:
        raise _ModelFailure(str(error)) from error
    status, detail = _research_status(result)
    if status == "failure":
        raise _ModelFailure(detail or "Research failed.")
    return status, detail


def _config_text(root: Path) -> str:
    return (root / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8")


def _restore_config(root: Path, text: str) -> None:
    path = root / ".whyline" / "relay" / "config.toml"
    if path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def _use_planner(
    root: Path, drafter: str, reviewer: str, test_planner: str = ""
) -> None:
    from whyline_relay import setup

    setup.write_planner(root, str(drafter), str(reviewer), str(test_planner), commit=False)


def _spec_draft_path(root: Path) -> Path:
    from whyline_relay import specs

    return specs.draft_path(root)


def _plan_draft_path(root: Path) -> Path:
    from whyline_relay import planner

    return planner.draft_path(root)


def _paused_reason(error: BaseException, root: Path, path: Path) -> str:
    questions = getattr(error, "questions", ())
    if questions:
        text = _questions_reason(list(questions))
    else:
        text = str(error)
    return f"{text}\nDraft: {_shown(root, path)}"


def _reason_for_draft_pause(error: _NeedPause, root: Path, path: Path) -> str:
    cause = error.__cause__
    if cause is not None and not error.reason:
        return _paused_reason(cause, root, path)
    shown = _shown(root, path)
    if error.reason.endswith(shown):
        return error.reason
    return f"{error.reason}\nDraft: {shown}"


def _no_handoff_pause(error: BaseException) -> bool:
    """A planner turn that finished without a handoff.

    `agents.run` returns after a nonzero exit. The planner then raises
    `loop.Paused` with this reason and no `AgentTimeout` or `AgentMissing`
    cause. Visit caps, questions, and blocked handoffs use other reasons.
    """
    from whyline.console import adapters

    reason = getattr(error, "reason", None)
    text = reason if isinstance(reason, str) and reason else str(error)
    return adapters.failure_kind(text) == "no-handoff"


def _guard_draft(call):
    """Return the draft, or raise `_NeedPause` / `_ModelFailure`."""
    from whyline_relay import agents as relay_agents
    from whyline_relay import chat, loop

    questions = relay_ops.plan_questions_error()
    try:
        return call()
    except questions as error:
        raise _NeedPause("") from error
    except loop.Paused as error:
        cause = error.__cause__
        if isinstance(cause, relay_agents.AgentCancelled):
            raise
        if isinstance(cause, (relay_agents.AgentTimeout, relay_agents.AgentMissing)):
            raise _ModelFailure(str(error)) from error
        if _no_handoff_pause(error):
            raise _ModelFailure(str(error)) from error
        raise _NeedPause(str(error)) from error
    except (relay_agents.AgentTimeout, relay_agents.AgentMissing, chat.AgentUnavailable) as error:
        raise _ModelFailure(str(error)) from error


def _revise(
    root: Path,
    request: AutoRunRequest,
    answer: str,
    progress,
    cancel_event: threading.Event | None,
) -> None:
    from whyline_relay import agents as relay_agents
    from whyline_relay import chat

    agent = request.final_agent
    roster = list(request.agents)
    tried: list[str] = []
    while True:
        _emit(progress, f"auto · synthesis · {agent}")
        try:
            with _synthesis_revision_call(cancel_event):
                relay_ops.revise_synthesis(
                    root,
                    request.topic,
                    agent,
                    roster,
                    answer,
                    progress=progress or (lambda _line: None),
                    timeout_minutes=(
                        request.timeout_minutes if request.timeout_minutes else None
                    ),
                    attachments=list(request.attachments),
                )
            return
        except relay_agents.AgentCancelled:
            raise
        except (
            relay_agents.AgentTimeout,
            relay_agents.AgentMissing,
            chat.AgentUnavailable,
        ):
            if agent not in tried:
                tried.append(agent)
            backup = _next_backup(request.chain, tried)
            if backup is None:
                raise _NeedPause(_exhausted(tried)) from None
            _emit(progress, f"{agent} failed; trying {backup}")
            roster = _substitute_agent(roster, agent, backup)
            agent = backup


def _accept_synthesis(current: dict, path: Path) -> dict:
    if not path.is_file() or not _has_final(path):
        return _mark_pause(current, "research", "Research did not write a Final Synthesis.")
    current["brainstorm"] = _store_artifact(path)
    questions = relay_ops.open_questions(_read_text(path))
    if questions:
        return _mark_pause(current, "research", _questions_reason(questions))
    _clear_pause(current)
    current["phase"] = "research"
    return current


def _research_phase(
    root,
    request,
    current,
    *,
    saved_phase,
    progress,
    cancel_event,
    answer,
    synthesis: Path | None = None,
):
    if synthesis is not None:
        synthesis_path = Path(synthesis)
        if _has_final(synthesis_path):
            from whyline_relay import brainstorm

            target = brainstorm.shared_path(root, request.topic)
            target.parent.mkdir(parents=True, exist_ok=True)
            if synthesis_path.resolve() != target.resolve():
                shutil.copyfile(synthesis_path, target)
            return _accept_synthesis(current, target)

    if _hold_pause(current, saved_phase, "research", answer):
        return current
    path, _doc = _brainstorm_doc(root, request.topic)
    if answer and saved_phase == "research" and isinstance(current.get("pause"), dict):
        try:
            _revise(root, request, answer, progress, cancel_event)
        except _NeedPause as error:
            return _mark_pause(current, "research", error.reason)
        _clear_pause(current)
        return _accept_synthesis(current, path)
    if artifact_matches(current.get("brainstorm")):
        return _accept_synthesis(current, path)

    agents = list(request.agents)
    final = request.final_agent
    tried: list[str] = []
    while True:
        try:
            status, detail = _invoke_brainstorm(
                root, request, agents, final, progress, cancel_event
            )
        except _ModelFailure:
            if final not in tried:
                tried.append(final)
            backup = _next_backup(request.chain, tried)
            if backup is None:
                return _mark_pause(current, "research", _exhausted(tried))
            _emit(progress, f"{final} failed; trying {backup}")
            agents = _substitute_agent(agents, final, backup)
            final = backup
            continue
        if status == "blocked":
            if path.is_file() and _has_final(path):
                current["brainstorm"] = _store_artifact(path)
            reason = detail or "Brainstorm blocked."
            if path.is_file():
                questions = relay_ops.open_questions(_read_text(path))
                if questions:
                    reason = f"{reason}\n{_questions_reason(questions)}"
            return _mark_pause(current, "research", reason)
        if not _has_final(path):
            if final not in tried:
                tried.append(final)
            backup = _next_backup(request.chain, tried)
            if backup is None:
                return _mark_pause(current, "research", _exhausted(tried))
            _emit(progress, f"{final} failed; trying {backup}")
            agents = _substitute_agent(agents, final, backup)
            final = backup
            continue
        return _accept_synthesis(current, path)


def _draft_spec_once(root, request, text, progress, last_agent):
    def print_fn(line=""):
        _on_planner_line(root, "spec", progress, line, last_agent)

    def call():
        if relay_ops.pending_spec(root):
            return relay_ops.resume_spec(root, progress=print_fn)
        return relay_ops.draft_spec(
            root, text, list(request.attachments), progress=print_fn
        )

    return _guard_draft(call)


def _spec_with_failover(root, request, text, progress):
    drafter = str(request.drafter)
    reviewer = str(request.reviewer)
    test_planner = _request_test_planner(request)
    tried: list[str] = []
    last_agent = {"name": drafter}
    substituted = False
    while True:
        if substituted:
            _use_planner(root, drafter, reviewer, test_planner)
        try:
            return _draft_spec_once(root, request, text, progress, last_agent)
        except _ModelFailure:
            failed = last_agent["name"] or drafter
            if failed not in tried:
                tried.append(failed)
            backup = _next_backup(request.chain, tried)
            if backup is None:
                raise _NeedPause(_exhausted(tried)) from None
            _emit(progress, f"{failed} failed; trying {backup}")
            if failed == reviewer and failed != drafter:
                reviewer = backup
            else:
                drafter = backup
            last_agent["name"] = backup
            substituted = True


def _spec_phase(root, request, current, *, saved_phase, progress, answer):
    if _hold_pause(current, saved_phase, "spec", answer):
        return current
    if artifact_matches(current.get("spec")):
        _clear_pause(current)
        current["phase"] = "spec"
        return current
    _path, doc = _brainstorm_doc(root, request.topic)
    text = _spec_request(doc)
    original = _config_text(root)
    try:
        try:
            draft = _spec_with_failover(root, request, text, progress)
        except _NeedPause as error:
            return _mark_pause(
                current, "spec", _reason_for_draft_pause(error, root, _spec_draft_path(root))
            )
    finally:
        _restore_config(root, original)
    if not draft.text.strip() or relay_ops.open_questions(draft.text):
        if draft.text.strip():
            reason = _questions_reason(relay_ops.open_questions(draft.text))
        else:
            reason = "The spec draft is empty."
        reason = f"{reason}\nDraft: {_shown(root, draft.path)}"
        return _mark_pause(current, "spec", reason)
    target = relay_ops.approve_spec(
        root, draft, _work_name(request), replace=request.replace
    )
    current["spec"] = _store_artifact(target)
    _clear_pause(current)
    current["phase"] = "spec"
    return current


def _draft_plan_once(
    root,
    request,
    spec_path: Path,
    progress,
    last_agent,
    feedback: str | None = None,
):
    def print_fn(line=""):
        _on_planner_line(root, "plan", progress, line, last_agent)

    def call():
        if feedback and relay_ops.pending_draft(root):
            relay_ops.discard_draft(root, None)
        elif relay_ops.pending_draft(root):
            return relay_ops.resume_draft(root, progress=print_fn)
        plan_topic = request.topic
        if feedback:
            if feedback.startswith("Changes asked for after review:"):
                feedback_line = feedback
            else:
                feedback_line = f"Changes asked for after review: {feedback}"
            topic = request.topic.rstrip()
            plan_topic = f"{topic}\n\n{feedback_line}" if topic else feedback_line
        return relay_ops.draft_plan(
            root,
            plan_topic,
            list(request.attachments),
            progress=print_fn,
            spec=spec_path,
        )

    return _guard_draft(call)


def _plan_with_failover(
    root,
    request,
    spec_path: Path,
    progress,
    feedback: str | None = None,
):
    drafter = str(request.drafter)
    reviewer = str(request.reviewer)
    test_planner = _request_test_planner(request)
    tried: list[str] = []
    last_agent = {"name": drafter}
    substituted = False
    while True:
        if substituted:
            _use_planner(root, drafter, reviewer, test_planner)
        try:
            return _draft_plan_once(
                root,
                request,
                spec_path,
                progress,
                last_agent,
                feedback=feedback,
            )
        except _ModelFailure:
            failed = last_agent["name"] or drafter
            if failed not in tried:
                tried.append(failed)
            backup = _next_backup(request.chain, tried)
            if backup is None:
                raise _NeedPause(_exhausted(tried)) from None
            _emit(progress, f"{failed} failed; trying {backup}")
            if failed == reviewer and failed != drafter:
                reviewer = backup
            elif failed == test_planner and failed != drafter:
                test_planner = backup
            else:
                drafter = backup
            last_agent["name"] = backup
            substituted = True


def _plan_phase(
    root,
    request,
    current,
    *,
    saved_phase,
    progress,
    answer,
    feedback: str | None = None,
):
    if _hold_pause(current, saved_phase, "plan", answer):
        return current
    if artifact_matches(current.get("plan")):
        _clear_pause(current)
        current["phase"] = "plan"
        return current
    spec_record = current.get("spec") if isinstance(current.get("spec"), dict) else {}
    spec_text = spec_record.get("path") if isinstance(spec_record, dict) else None
    if not isinstance(spec_text, str) or not spec_text:
        return _mark_pause(current, "plan", "The approved spec is missing.")
    spec_path = Path(spec_text)
    original = _config_text(root)
    try:
        try:
            draft = _plan_with_failover(
                root, request, spec_path, progress, feedback=feedback
            )
        except _NeedPause as error:
            return _mark_pause(
                current, "plan", _reason_for_draft_pause(error, root, _plan_draft_path(root))
            )
    finally:
        _restore_config(root, original)
    problems = relay_ops.validate_plan(draft.text)
    if problems:
        reason = "\n".join(problems) + f"\nDraft: {_shown(root, draft.path)}"
        return _mark_pause(current, "plan", reason)
    spec_shown = _shown(root, spec_path)
    target = relay_ops.approve_plan(
        root,
        draft,
        _work_name(request),
        replace=True if feedback else request.replace,
        spec=spec_shown,
    )
    current["plan"] = _store_artifact(target)
    _clear_pause(current)
    current["phase"] = "plan"
    return current


def _cancelled(cancel_event: threading.Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def _as_stopped(root: Path, current: dict) -> dict:
    """Mark `current` stopped and write it. Completed artifacts stay."""
    current["phase"] = "stopped"
    current.pop("pause", None)
    atomic_write_json(checkpoint_path(root), current)
    return current


def _halted(root: Path, current: dict, cancel_event: threading.Event | None) -> dict | None:
    """The checkpoint to return when this phase must not continue.

    A pause is the phase's own result. A set cancel event, or a phase that
    already wrote `stopped`, ends the run before the next model call.
    """
    if current.get("phase") == "stopped":
        return current
    if "pause" in current:
        return current
    if _cancelled(cancel_event):
        return _as_stopped(root, current)
    return None


def _after_persist(
    root,
    request,
    current,
    *,
    saved_phase,
    progress,
    cancel_event,
    answer,
    synthesis: Path | None = None,
):
    current = _research_phase(
        root,
        request,
        current,
        saved_phase=saved_phase,
        progress=progress,
        cancel_event=cancel_event,
        answer=answer,
        synthesis=synthesis,
    )
    if current.get("phase") != "stopped":
        _save(root, current)
    halted = _halted(root, current, cancel_event)
    if halted is not None:
        return halted
    current = _spec_phase(
        root,
        request,
        current,
        saved_phase=saved_phase,
        progress=progress,
        answer=answer,
    )
    if current.get("phase") != "stopped":
        _save(root, current)
    halted = _halted(root, current, cancel_event)
    if halted is not None:
        return halted
    current = _plan_phase(
        root,
        request,
        current,
        saved_phase=saved_phase,
        progress=progress,
        answer=answer,
    )
    if current.get("phase") != "stopped":
        _save(root, current)
    halted = _halted(root, current, cancel_event)
    if halted is not None:
        return halted
    return current


def _fail_lines(checks) -> str:
    body = "\n".join(f"{check.status:<4}  {check.message}" for check in checks)
    return f"{body}\n{_SETUP_CAN_OPEN}"


def _preflight_phase(root: Path, current: dict, *, progress) -> dict:
    """Select the approved plan and run full preflight.

    This phase has no artifact hash. Resume runs it again so it sees the
    tree as it is. `FAIL` stops before the launcher. `warn` does not.
    Release `human` is not a failure and does not skip the launch.
    """
    _emit(progress, _PREFLIGHT_PROGRESS)
    record = current.get("plan") if isinstance(current.get("plan"), dict) else None
    path_text = record.get("path") if isinstance(record, dict) else None
    plan = Path(path_text) if isinstance(path_text, str) and path_text else None
    if plan is None or not plan.is_file():
        reason = f"The approved plan is missing.\n{_SETUP_CAN_OPEN}"
        _emit(progress, reason)
        return _mark_pause(current, "preflight", reason)
    relay_ops.select_plan(root, plan)
    from whyline_relay import preflight

    checks = preflight.run(root, plan, scope="full")
    fails = [check for check in checks if check.status == "FAIL"]
    if fails:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        dirty = [line[3:].strip().split(" -> ")[-1] for line in proc.stdout.splitlines() if line.strip()]
        if dirty == [".whyline/decisions.md"]:
            _emit(progress, "auto · recover decision-log")
            from whyline.console import recovery

            actual_task_id = current.get("name") or ""
            fix_res = recovery.fix(root, actual_task_id)
            recovery.record_attempt(
                root,
                task=actual_task_id,
                round=1,
                kind="dirty",
                agent="",
                verdict=fix_res.verdict,
            )
            if fix_res.verdict == "resolved":
                checks = preflight.run(root, plan, scope="full")
                fails = [check for check in checks if check.status == "FAIL"]
    if fails:
        reason = _fail_lines(fails)
        _emit(progress, reason)
        return _mark_pause(current, "preflight", reason)
    _clear_pause(current)
    current["phase"] = "preflight"
    return current


def _repository_failures(root: Path) -> list:
    """FAIL lines from `preflight.run(root, scope="repository")`.

    Resume uses this as the clean-tree gate. It does not pass `allow_dirty`.
    """
    from whyline_relay import preflight

    checks = preflight.run(root, scope="repository")
    return [check for check in checks if check.status == "FAIL"]


def _launch(current: dict, *, launcher, saved_phase: str | None) -> dict:
    """Call the injected launcher once when preflight has just passed.

    A checkpoint that is already `relay` has launched. Resume re-runs
    preflight and, when that still passes, leaves the running relay alone.
    Release `human` is not a reason to skip this call.
    """
    if saved_phase != "relay":
        if launcher is None:
            raise ValueError("launcher is required")
        launcher(["start"])
    _clear_pause(current)
    current["phase"] = "relay"
    return current


def run(
    root: Path,
    request: AutoRunRequest,
    dismissed: str,
    *,
    progress=None,
    cancel_event: threading.Event | None = None,
    answer: str | None = None,
    through: str = "relay",
    launcher=None,
    runner=None,
    synthesis: Path | None = None,
) -> dict:
    """Revalidate, lock, persist, then research, spec, plan, preflight, and launch.

    `through="persist"` returns after the config commit. `through="plan"`
    returns after the plan artifact. The default runs final preflight and,
    when that has zero `FAIL` lines, calls `launcher` with `["start"]`.
    `answer` is a person's reply to a synthesis pause: it goes through
    `revise_synthesis`, and that gate runs again. The lock is released when
    this call returns, including when a phase raises. A stale form raises
    `AutoStale` before any write. A live lock raises `AutoBusy`.
    """
    if through not in {"persist", "plan", "relay"}:
        raise ValueError("through must be persist, plan, or relay")
    if answer is not None:
        answer = answer.strip() or None
    fresh = document(root, request)
    path = checkpoint_path(root)
    saved = load_object(path)
    if not _matches(fresh, dismissed, saved):
        raise AutoStale("This check is out of date. Check again.")
    saved_phase = saved.get("phase") if isinstance(saved, dict) else None
    if not isinstance(saved_phase, str):
        saved_phase = None
    previous = saved.get("persist_commit") if isinstance(saved, dict) else None
    if previous is not None and not isinstance(previous, str):
        previous = None
    from whyline_relay import agents as relay_agents

    acquire_lock(root)
    current = None
    try:
        current = _checkpoint(
            saved,
            request,
            fresh,
            dismissed,
            phase="start",
            persist_commit=previous,
        )
        atomic_write_json(path, current)
        if _cancelled(cancel_event):
            return _as_stopped(root, current)
        current["phase"] = "persist"
        current["persist_commit"] = _persist(root, request)
        atomic_write_json(path, current)
        if through == "persist":
            return current
        if _cancelled(cancel_event):
            return _as_stopped(root, current)
        current = _after_persist(
            root,
            request,
            current,
            saved_phase=saved_phase,
            progress=progress,
            cancel_event=cancel_event,
            answer=answer,
            synthesis=synthesis,
        )
        if through == "plan" or current.get("phase") == "stopped" or "pause" in current:
            return current
        if _cancelled(cancel_event):
            return _as_stopped(root, current)
        current = _preflight_phase(root, current, progress=progress)
        _save(root, current)
        if "pause" in current:
            return current
        if _cancelled(cancel_event):
            return _as_stopped(root, current)
        current = _launch(current, launcher=launcher, saved_phase=saved_phase)
        return _save(root, current)
    except relay_agents.AgentCancelled:
        if not isinstance(current, dict):
            raise
        return _as_stopped(root, current)
    finally:
        release_lock(root)


def stop(root: Path, cancel_event: threading.Event | None = None) -> None:
    """Set the in-flight cancel event, mark the checkpoint stopped, release the lock.

    The event is the one `run` passed into `agents.run`. Setting it is the
    whole kill: `agents.run` SIGTERMs the process group when that event is
    set. Completed artifacts stay in the checkpoint.
    """
    if cancel_event is not None:
        cancel_event.set()
    path = checkpoint_path(root)
    saved = load_object(path)
    if isinstance(saved, dict):
        saved["phase"] = "stopped"
        saved.pop("pause", None)
        atomic_write_json(path, saved)
    release_lock(root)


def close_console(root: Path, cancel_event: threading.Event | None = None) -> None:
    """Closing during phases 1–7 uses the same cancel and writes `stopped`.

    There is no "Leave it running" choice on that path. Once the checkpoint
    phase is `relay`, this returns without writing. `QuitRelayScreen` is the
    quit UI for a running relay, and this function does not replace it.
    """
    saved = load_object(checkpoint_path(root))
    phase = saved.get("phase") if isinstance(saved, dict) else None
    if phase == "relay":
        return
    stop(root, cancel_event)


def _apply_recovery_outcome_to_pause(
    root: Path,
    checkpoint: dict | None,
    st: Any,
    original_reason: str,
    res: Any,
) -> None:
    outcome = str(res)
    if outcome and outcome not in original_reason:
        new_reason = f"{original_reason}\n{outcome}" if original_reason else outcome
    else:
        new_reason = original_reason

    cp_path = checkpoint_path(root)
    if isinstance(checkpoint, dict):
        if "pause" in checkpoint:
            checkpoint["pause"]["reason"] = new_reason
        else:
            checkpoint["pause"] = {"reason": new_reason, "actions": list(_GATE_ACTIONS)}
        atomic_write_json(cp_path, checkpoint)
    elif cp_path.is_file():
        saved = load_object(cp_path)
        if isinstance(saved, dict):
            if "pause" in saved:
                saved["pause"]["reason"] = new_reason
            else:
                saved["pause"] = {"reason": new_reason, "actions": list(_GATE_ACTIONS)}
            atomic_write_json(cp_path, saved)

    st_path = root / ".whyline" / "relay" / "state.json"
    if st_path.is_file():
        try:
            raw = json.loads(st_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw["paused_reason"] = new_reason
                atomic_write_json(st_path, raw)
        except Exception:
            pass


def _clear_pause_in_checkpoint_and_state(
    root: Path,
    checkpoint: dict | None,
) -> None:
    cp_path = checkpoint_path(root)
    if isinstance(checkpoint, dict):
        checkpoint.pop("pause", None)
        checkpoint["phase"] = "relay"
        atomic_write_json(cp_path, checkpoint)
    elif cp_path.is_file():
        saved = load_object(cp_path)
        if isinstance(saved, dict):
            saved.pop("pause", None)
            saved["phase"] = "relay"
            atomic_write_json(cp_path, saved)


def recover_pause(
    root: Path | str,
    *,
    session: Any = None,
    progress: Any = None,
    launcher: Any = None,
    runner: Any = None,
    task_id: str = "",
    round: int | None = None,
    pause_reason: str = "",
    request: AutoRunRequest | None = None,
) -> Any:
    from whyline_relay import (
        config as relay_config,
        failover as relay_failover,
        setup as relay_setup,
        state as relay_state,
    )
    from whyline.console import adapters, recovery

    root_path = Path(root).resolve()
    st = relay_state.load(root_path)
    cp_path = checkpoint_path(root_path)
    checkpoint = load_object(cp_path) if cp_path.is_file() else None

    actual_task_id = task_id
    if not actual_task_id and st and st.task_id:
        actual_task_id = st.task_id
    if not actual_task_id and isinstance(checkpoint, dict):
        plan_record = checkpoint.get("plan")
        if isinstance(plan_record, dict) and plan_record.get("path"):
            try:
                from whyline_relay import plan as plan_mod

                p_file = Path(plan_record["path"])
                if not p_file.is_absolute():
                    p_file = root_path / p_file
                if p_file.is_file():
                    tasks = plan_mod.parse(p_file.read_text(encoding="utf-8"))
                    if tasks:
                        actual_task_id = tasks[0].task_id
            except Exception:
                pass
    if not actual_task_id:
        plan_file = root_path / (st.plan if st and st.plan else "plan.md")
        if plan_file.is_file():
            try:
                from whyline_relay import plan as plan_mod

                tasks = plan_mod.parse(plan_file.read_text(encoding="utf-8"))
                if tasks:
                    actual_task_id = tasks[0].task_id
            except Exception:
                pass
    if not actual_task_id:
        actual_task_id = "REC"

    round_num = round if round is not None else (st.round if st and st.round else 1)

    actual_pause_reason = pause_reason
    if not actual_pause_reason and st and st.paused_reason:
        actual_pause_reason = st.paused_reason
    if not actual_pause_reason and isinstance(checkpoint, dict) and "pause" in checkpoint:
        actual_pause_reason = checkpoint["pause"].get("reason", "")

    dirty_files: list[str] = []
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root_path,
            capture_output=True,
            text=True,
        )
        for line in proc.stdout.splitlines():
            if line.strip():
                p = line[3:].strip()
                if " -> " in p:
                    p = p.split(" -> ")[-1]
                if not p.startswith(".whyline/relay/"):
                    dirty_files.append(p)
    except Exception:
        pass

    if "uncommitted changes" in actual_pause_reason or actual_pause_reason == "dirty":
        kind = "dirty"
    else:
        kind = adapters.failure_kind(actual_pause_reason)

    from whyline.console import relay_ops

    mode = relay_ops.resolve_mode(root_path)
    if mode == "auto":
        if not recovery.allowed(root_path, actual_task_id, round_num):
            reason = f"recovery already attempted for {actual_task_id} round {round_num}"
            res = recovery.RecoveryResult("human", [reason], reason=reason)
            _apply_recovery_outcome_to_pause(root_path, checkpoint, st, actual_pause_reason, res)
            return res

        problems = recovery.diagnose(
            root_path,
            fail_lines=[],
            pause_reason=actual_pause_reason,
        )
        if not problems:
            res = recovery.RecoveryResult("human", [actual_pause_reason], reason=actual_pause_reason)
            _apply_recovery_outcome_to_pause(root_path, checkpoint, st, actual_pause_reason, res)
            return res

        for problem in problems:
            opt = recovery.auto_option(problem)
            if opt is None:
                reason = problem.summary
                res = recovery.RecoveryResult("human", [reason], reason=reason)
                _apply_recovery_outcome_to_pause(root_path, checkpoint, st, actual_pause_reason, res)
                return res

            _emit(progress, f"resolve · auto · {problem.id} · {opt.id}")
            did_resume = False

            def auto_launcher(args: list[str]) -> None:
                nonlocal did_resume
                did_resume = True
                if launcher is not None:
                    launcher(args)

            res_line = recovery.apply(
                root_path,
                problem,
                opt.id,
                launch=auto_launcher,
            )
            if res_line:
                _emit(progress, res_line)

            recovery.record_attempt(
                root_path,
                task=actual_task_id,
                round=round_num,
                kind="resolve-auto",
                agent="",
                verdict="resolved",
            )
            if not did_resume and opt.id != "wait" and launcher is not None:
                launcher(["resume"])

            _clear_pause_in_checkpoint_and_state(root_path, checkpoint)
            return recovery.RecoveryResult("resolved", [], reason="resolved")

    route = recovery.route(kind, dirty_files)

    if not recovery.allowed(root_path, actual_task_id, round_num):
        reason = f"recovery already attempted for {actual_task_id} round {round_num}"
        res = recovery.RecoveryResult("human", [reason], reason=reason)
        _apply_recovery_outcome_to_pause(root_path, checkpoint, st, actual_pause_reason, res)
        return res

    if route == "human":
        res = recovery.RecoveryResult("human", [actual_pause_reason], reason=actual_pause_reason)
        _apply_recovery_outcome_to_pause(root_path, checkpoint, st, actual_pause_reason, res)
        return res

    if route == "fix":
        _emit(progress, "auto · recover decision-log")
        fix_res = recovery.fix(root_path, actual_task_id)
        verdict = fix_res.verdict
        recovery.record_attempt(
            root_path,
            task=actual_task_id,
            round=round_num,
            kind="dirty",
            agent="",
            verdict=verdict,
        )
        if verdict == "resolved":
            res = recovery.RecoveryResult("resolved", [], reason="resolved")
            _clear_pause_in_checkpoint_and_state(root_path, checkpoint)
            if launcher is not None:
                launcher(["resume"])
            return res
        else:
            reason = f"repository preflight failed: {', '.join(fix_res.fail_lines)}"
            res = recovery.RecoveryResult("human", fix_res.fail_lines, reason=reason)
            _apply_recovery_outcome_to_pause(root_path, checkpoint, st, actual_pause_reason, res)
            return res

    if route == "agent":
        agent_name = ""
        if session is not None and getattr(session, "agent", None):
            agent_name = session.agent
        if not agent_name and actual_pause_reason:
            m = re.search(r"(\S+)\s+exited without handing off", actual_pause_reason)
            if m:
                agent_name = m.group(1)
        if not agent_name and request is not None:
            agent_name = request.implementer if round_num == 1 else request.reviewer
        if not agent_name:
            try:
                settings = relay_config.load(root_path)
                role = "reviewer" if round_num == 2 else "implementer"
                agent_name = relay_failover.effective_agent(root_path, settings, role)
            except Exception:
                agent_name = "codex"

        _emit(progress, f"auto · recover no-handoff · {agent_name}")
        res = recovery.recover(
            root_path,
            session=session,
            agent=agent_name,
            runner=runner,
            task_id=actual_task_id,
            round=round_num,
            pause_reason=actual_pause_reason,
        )
        if res.verdict == "resolved":
            _clear_pause_in_checkpoint_and_state(root_path, checkpoint)
            if launcher is not None:
                launcher(["resume"])
            return res
        else:
            _apply_recovery_outcome_to_pause(root_path, checkpoint, st, actual_pause_reason, res)
            return res

    if route == "failover":
        try:
            backup_chain = list(relay_setup.read_backup(root_path))
        except Exception:
            backup_chain = []
        if not backup_chain:
            try:
                settings = relay_config.load(root_path)
                backup_chain = list(getattr(settings, "backup_chain", []))
            except Exception:
                backup_chain = []

        failed_agent = ""
        if actual_pause_reason:
            m = re.search(r"(\S+)\s+hit a usage or rate limit", actual_pause_reason)
            if m:
                failed_agent = m.group(1)
        if not failed_agent and session is not None and getattr(session, "agent", None):
            failed_agent = session.agent

        try:
            settings = relay_config.load(root_path)
        except Exception:
            settings = None

        role = "reviewer" if round_num == 2 else "implementer"
        if settings is not None and hasattr(settings, "roles"):
            for r in ("implementer", "reviewer"):
                if getattr(settings.roles, r, None) == failed_agent:
                    role = r
                    break

        existing = relay_failover.read_overrides(root_path).get(role)
        tried = list(existing.tried) if existing is not None else []
        if failed_agent and failed_agent not in tried:
            tried.append(failed_agent)

        backup = relay_failover.next_backup(backup_chain, set(tried))
        if backup is not None:
            _emit(progress, f"auto · recover failover · {backup}")
            relay_failover.write_override(
                root_path,
                role,
                relay_failover.ActiveOverride(
                    agent=backup,
                    backup_for=failed_agent or "agent",
                    reason="rate-limit",
                    since=datetime.now().astimezone().isoformat(),
                    tried=tried,
                ),
            )
            recovery.record_attempt(
                root_path,
                task=actual_task_id,
                round=round_num,
                kind="rate-limit",
                agent=backup,
                verdict="resolved",
            )
            res = recovery.RecoveryResult("resolved", [], reason="resolved")
            _clear_pause_in_checkpoint_and_state(root_path, checkpoint)
            if launcher is not None:
                launcher(["resume"])
            return res
        else:
            agents_list = sorted(set(tried))
            reason = (
                f"exhausted recovery chain: {', '.join(agents_list)}"
                if agents_list
                else "exhausted recovery chain: none"
            )
            recovery.record_attempt(
                root_path,
                task=actual_task_id,
                round=round_num,
                kind="rate-limit",
                agent=failed_agent,
                verdict="human",
            )
            res = recovery.RecoveryResult("human", [reason], reason=reason, agents=agents_list)
            _apply_recovery_outcome_to_pause(root_path, checkpoint, st, actual_pause_reason, res)
            return res

    res = recovery.RecoveryResult("human", [actual_pause_reason], reason=actual_pause_reason)
    _apply_recovery_outcome_to_pause(root_path, checkpoint, st, actual_pause_reason, res)
    return res


def resume(
    root: Path,
    request: AutoRunRequest,
    *,
    progress=None,
    cancel_event: threading.Event | None = None,
    answer: str | None = None,
    launcher=None,
    runner=None,
    synthesis: Path | None = None,
) -> dict:
    """Continue from the first phase whose artifact is missing or stale.

    Compares the form fields with a fresh computation, then a
    `scope="repository"` check. It does not compare the pre-persist `HEAD`
    stored inside the old fingerprint. A form mismatch raises `AutoStale`
    before the lock and before any model call. A repository `FAIL` raises
    `AutoStale` with those lines, also before a model call. Artifact hashes
    are compared by the phase walker, which does not call `approve_spec` or
    `approve_plan` again when the hash matches. Final preflight runs again.
    """
    saved = load_object(checkpoint_path(root))
    if not isinstance(saved, dict) or saved.get("schema") != SCHEMA:
        raise AutoStale("This check is out of date. Check again.")
    if saved.get("request") != form_document(root, request):
        raise AutoStale("This check is out of date. Check again.")

    st = None
    try:
        from whyline_relay import state as relay_state
        st = relay_state.load(root)
    except Exception:
        pass

    dirty_files: list[str] = []
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        for line in proc.stdout.splitlines():
            if line.strip():
                p = line[3:].strip()
                if " -> " in p:
                    p = p.split(" -> ")[-1]
                if not p.startswith(".whyline/relay/"):
                    dirty_files.append(p)
    except Exception:
        pass

    decision_log_only = dirty_files == [".whyline/decisions.md"]
    is_relay_pause = (st is not None and bool(st.paused_reason)) or (
        isinstance(saved, dict) and (saved.get("phase") == "relay" and "pause" in saved)
    )

    if is_relay_pause or decision_log_only:
        res = recover_pause(
            root,
            request=request,
            progress=progress,
            launcher=launcher,
            runner=runner,
        )
        saved = load_object(checkpoint_path(root))
        if res == "resolved":
            if isinstance(saved, dict):
                return saved
            return {"phase": "relay"}
        else:
            if isinstance(saved, dict):
                return saved
            return {"phase": "paused", "pause": {"reason": str(res), "actions": list(_GATE_ACTIONS)}}

    fails = _repository_failures(root)
    if fails:
        fail_msgs = [check.message for check in fails]
        if len(fail_msgs) == 1 and ".whyline/decisions.md" in fail_msgs[0]:
            res = recover_pause(
                root,
                request=request,
                progress=progress,
                launcher=launcher,
                runner=runner,
            )
            saved = load_object(checkpoint_path(root))
            if res == "resolved":
                if isinstance(saved, dict):
                    return saved
                return {"phase": "relay"}
        lines = "\n".join(f"{check.status:<4}  {check.message}" for check in fails)
        raise AutoStale(lines)
    dismissed = saved.get("fingerprint")
    if not isinstance(dismissed, str):
        dismissed = saved.get("last_check")
    if not isinstance(dismissed, str):
        raise AutoStale("This check is out of date. Check again.")
    return run(
        root,
        request,
        dismissed,
        progress=progress,
        cancel_event=cancel_event,
        answer=answer,
        through="relay",
        launcher=launcher,
        runner=runner,
        synthesis=synthesis,
    )


def redraft_plan(
    root: Path,
    request: AutoRunRequest,
    feedback: str,
    *,
    progress=None,
    launcher=None,
    runner=None,
) -> dict:
    """Take the lock, drop the plan artifact from checkpoint, run plan phase with feedback.

    The planner's request has feedback appended as "Changes asked for after review: ...".
    Returns the checkpoint at phase "plan" or paused, and never launches.
    """
    from whyline_relay import agents as relay_agents

    root = Path(root)
    acquire_lock(root)
    current = None
    try:
        path = checkpoint_path(root)
        saved = load_object(path)
        if not isinstance(saved, dict) or saved.get("schema") != SCHEMA:
            fresh = document(root, request)
            dismissed = fingerprint(root, request)
            current = _checkpoint(
                None,
                request,
                fresh,
                dismissed,
                phase="plan",
                persist_commit=None,
            )
        else:
            current = saved
        current.pop("plan", None)
        current.pop("pause", None)
        _save(root, current)
        current = _plan_phase(
            root,
            request,
            current,
            saved_phase=current.get("phase"),
            progress=progress,
            answer=None,
            feedback=feedback,
        )
        return _save(root, current)
    except relay_agents.AgentCancelled:
        if not isinstance(current, dict):
            raise
        return _as_stopped(root, current)
    finally:
        release_lock(root)
