"""Advisory checkout-local file and task ownership."""

from __future__ import annotations

from pathlib import Path

from whyline import decisions, events, paths, state


def load(root: Path) -> dict:
    found = state.load_object(paths.ownership_path(root))
    if not found or not isinstance(found.get("claims"), list):
        return {"v": 1, "claims": []}
    claims = [claim for claim in found["claims"] if isinstance(claim, dict)]
    return {"v": 1, "claims": claims}


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
) -> tuple[dict, list[dict]]:
    ownership_path = paths.ownership_path(root)
    with state.file_lock(ownership_path):
        current = load(root)
        clean_task = decisions.one_line(task)
        clean_actor = decisions.one_line(actor)
        replacement = {
            "task": clean_task,
            "actor": clean_actor,
            "role": decisions.one_line(role),
            "files": sorted({decisions.one_line(path) for path in files}),
            "claimed_at": events.now_iso(),
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
    return updated, conflicts(updated["claims"])


def release(root: Path, *, task: str, actor: str) -> dict:
    ownership_path = paths.ownership_path(root)
    with state.file_lock(ownership_path):
        current = load(root)
        clean_task = decisions.one_line(task)
        clean_actor = decisions.one_line(actor)
        updated = {
            "v": 1,
            "claims": [
                item
                for item in current["claims"]
                if not (
                    item.get("task") == clean_task
                    and item.get("actor") == clean_actor
                )
            ],
        }
        state.atomic_write_json(ownership_path, updated)
    return updated
