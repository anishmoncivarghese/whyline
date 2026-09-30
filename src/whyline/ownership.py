"""Advisory checkout-local file and task ownership.

Claims are leases. Before 0.3.20 a claim lived until someone released it,
and nobody did: this repository accumulated 25 claims over two days, all
of which `sync` kept presenting as current, with overlap warnings between
tasks finished long ago. A claim now expires (72 hours unless `--ttl`
says otherwise); an expired claim stays in the file, so it can still be
inspected, but it no longer counts as ownership.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from whyline import decisions, events, handoff, ledger, paths, state


def load(root: Path) -> dict:
    found = state.load_object(paths.ownership_path(root))
    if not found or not isinstance(found.get("claims"), list):
        return {"v": 1, "claims": []}
    claims = [claim for claim in found["claims"] if isinstance(claim, dict)]
    return {"v": 1, "claims": claims}


DEFAULT_TTL_HOURS = 72


def _parse(stamp: object) -> datetime | None:
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def expires_at(claim: dict) -> datetime | None:
    """When `claim` stops counting. Claims written before leases existed
    have no `expires_at`; they get the default lease from `claimed_at`."""
    explicit = _parse(claim.get("expires_at"))
    if explicit is not None:
        return explicit
    claimed = _parse(claim.get("claimed_at"))
    return claimed + timedelta(hours=DEFAULT_TTL_HOURS) if claimed else None


def finished(root: Path) -> dict[str, str]:
    """Finished tasks per the ledger (see handoff.finished_tasks)."""
    return handoff.finished_tasks(ledger.read_all(paths.ledger_path(root))[0])


def is_stale(
    claim: dict, now: datetime, finished_tasks: dict[str, str] | None = None
) -> bool:
    """Expired, or its task was handed off as finished after it was made --
    evidence the work is done, however recent the claim. A claim made
    after the finishing handoff (someone picked the task back up) stands."""
    ends = expires_at(claim)
    if ends is not None and ends <= now:
        return True
    done = _parse((finished_tasks or {}).get(str(claim.get("task", ""))))
    claimed = _parse(claim.get("claimed_at"))
    return done is not None and claimed is not None and done > claimed


def split(
    claims: list[dict],
    now: datetime | None = None,
    finished_tasks: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """(active, stale). A claim whose time can't be read stays active:
    hiding it would be guessing, and ownership errs toward being seen."""
    now = now or datetime.now(timezone.utc)
    active, stale = [], []
    for item in claims:
        (stale if is_stale(item, now, finished_tasks) else active).append(item)
    return active, stale


def conflicts(claims: list[dict]) -> list[dict]:
    found = []
    for index, left in enumerate(claims):
        for right in claims[index + 1 :]:
            if left.get("actor") == right.get("actor"):
                continue
            shared_files = sorted(
                set(left.get("files") or []).intersection(right.get("files") or [])
            )
            same_task = bool(left.get("task")) and left.get("task") == right.get("task")
            if not shared_files and not same_task:
                continue
            found.append(
                {
                    "actors": [left.get("actor", ""), right.get("actor", "")],
                    "tasks": [left.get("task", ""), right.get("task", "")],
                    "files": shared_files,
                    "task_conflict": same_task,
                }
            )
    return found


def claim(
    root: Path,
    *,
    task: str,
    actor: str,
    role: str,
    files: list[str],
    ttl_hours: float = DEFAULT_TTL_HOURS,
) -> tuple[dict, list[dict]]:
    ownership_path = paths.ownership_path(root)
    with state.file_lock(ownership_path):
        current = load(root)
        clean_task = decisions.one_line(task)
        clean_actor = decisions.one_line(actor)
        claimed_at = events.now_iso()
        replacement = {
            "task": clean_task,
            "actor": clean_actor,
            "role": decisions.one_line(role),
            "files": sorted({decisions.one_line(path) for path in files}),
            "claimed_at": claimed_at,
            # Re-claiming replaces the claim below, which is also how a
            # lease is renewed.
            "expires_at": _iso(_parse(claimed_at) + timedelta(hours=ttl_hours)),
        }
        retained = [
            item
            for item in current["claims"]
            if not (
                item.get("task") == clean_task and item.get("actor") == clean_actor
            )
        ]
        updated = {"v": 1, "claims": retained + [replacement]}
        state.atomic_write_json(ownership_path, updated)
    # Only live claims can overlap; stale ones are history, not ownership.
    return updated, conflicts(split(updated["claims"], finished_tasks=finished(root))[0])


def release(root: Path, *, task: str, actor: str) -> dict:
    return release_matching(root, task=task, actor=actor)[0]


def release_matching(
    root: Path,
    *,
    task: str | None = None,
    actor: str | None = None,
    stale: bool = False,
    everything: bool = False,
) -> tuple[dict, int]:
    """Remove the claims selected by the arguments; returns (state, count).
    `task` alone releases every actor's claim on it; `stale` releases only
    expired claims; `everything` releases all of them."""
    ownership_path = paths.ownership_path(root)
    with state.file_lock(ownership_path):
        current = load(root)
        clean_task = decisions.one_line(task) if task is not None else None
        clean_actor = decisions.one_line(actor) if actor is not None else None
        expired = {
            id(item)
            for item in split(current["claims"], finished_tasks=finished(root))[1]
        }

        def selected(item: dict) -> bool:
            if everything:
                return True
            if stale:
                return id(item) in expired
            if item.get("task") != clean_task:
                return False
            return clean_actor is None or item.get("actor") == clean_actor

        kept = [item for item in current["claims"] if not selected(item)]
        updated = {"v": 1, "claims": kept}
        state.atomic_write_json(ownership_path, updated)
    return updated, len(current["claims"]) - len(kept)
