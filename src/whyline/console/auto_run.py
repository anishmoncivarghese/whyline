"""Schema 1 fingerprint of an unsaved Auto request, and the start of its run.

`document` is the canonical mapping. `fingerprint` is the sha256 hex of that
mapping as JSON with `sort_keys=True` and separators `(',', ':')`.

Keys: `schema`, every `AutoRunRequest` field (`attachments` entries are
`path`, `size`, and `sha256`, or null size and digest when the path is not a
readable file), `models`, `available`, `head` (`git rev-parse HEAD` stdout),
`porcelain` (`git status --porcelain` stdout), and `antigravity`
(`trusted`, `declined`, `ask`, or `unused`).

`run` revalidates that fingerprint, takes `.whyline/relay/auto-run.lock`,
and persists the relay config once. Later phases stay out of this module
until their tasks land. Widget handlers stay out.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from whyline import account, model
from whyline.console import relay_ops
from whyline.console.plan_job import AutoRunRequest
from whyline.state import atomic_write_json, load_object

SCHEMA = 1

# These redirect git at a different repository than `root`. A caller inside
# another checkout, or a hook that exported them, must still fingerprint `root`.
_IGNORED_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")

# Revalidate compares the form, not the git snapshot. The persist commit
# moves HEAD, and porcelain is a separate clean-tree check.
_SKIPPED_IN_FORM = ("head", "porcelain")

PAUSE_ACTIONS = frozenset({"resume", "change", "replace", "cancel"})

_COMMIT_MESSAGE = "setup: auto run roles, backup, and timeout"


def named_agents(request: AutoRunRequest) -> tuple[str, ...]:
    """Research agents, the final writer, drafter, reviewer, implementer, tester,
    execution reviewer, every chain member, and release when it is not `human`.

    Empty strings are not names. Each name appears once, in that order.
    """
    names: list[str] = [
        *request.agents,
        request.final_agent,
        request.drafter,
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
    return {
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
        "drafter": request.drafter,
        "reviewer": request.reviewer,
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
    try:
        path.unlink()
    except FileNotFoundError:
        pass


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
            "pause actions must be a subset of resume, change, replace, cancel"
        )
    if len(set(actions)) != len(actions):
        raise ValueError(
            "pause actions must be a subset of resume, change, replace, cancel"
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
    """Write the four setup keys without committing, then commit them once.

    `reviewer` is the planner. `reviewer_role` is the execution reviewer.
    `commit_paths` is a no-op when those files have no diff, so a second call
    with the same content does not add a commit. `timeout_minutes` is the
    request value, including 0, written as an unquoted integer.
    """
    from whyline_relay import gitcheck, setup

    setup.write_planner(root, request.drafter, request.reviewer, commit=False)
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


def run(root: Path, request: AutoRunRequest, dismissed: str) -> dict:
    """Revalidate, lock, write phase `start`, and persist the config once.

    Returns the checkpoint mapping. The lock is released when this call
    returns, including when persist raises. A stale form raises `AutoStale`
    before any write. A live lock raises `AutoBusy`.
    """
    fresh = document(root, request)
    path = checkpoint_path(root)
    saved = load_object(path)
    if not _matches(fresh, dismissed, saved):
        raise AutoStale("This check is out of date. Check again.")
    previous = saved.get("persist_commit") if isinstance(saved, dict) else None
    if previous is not None and not isinstance(previous, str):
        previous = None
    acquire_lock(root)
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
        current["phase"] = "persist"
        current["persist_commit"] = _persist(root, request)
        atomic_write_json(path, current)
        return current
    finally:
        release_lock(root)
