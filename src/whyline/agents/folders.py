"""Folder triggers (spec section 5, step 4): polled by the tick (at most
~2 minutes late), merged into one run per minimum gap, triggering files
copied into the occurrence so the agent sees stable copies."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from whyline.agents import paths, state


def snapshot(folder: Path) -> dict[str, list]:
    out = {}
    if folder.is_dir():
        for entry in folder.iterdir():
            if entry.is_file() and not entry.is_symlink():
                info = entry.stat()
                out[entry.name] = [info.st_size, info.st_mtime_ns]
    return out


def payload_dir(agent_name: str, now: datetime) -> Path:
    folder = paths.home() / "payloads" / f"{now:%Y%m%d-%H%M%S}-{agent_name}"
    folder.mkdir(parents=True, mode=0o700)
    return folder


def copy_into(folder: Path, files) -> None:
    for file in files:
        shutil.copy2(file, folder / Path(file).name)


def check(conn, defn, act, *, now: datetime, start) -> None:
    watched = Path(defn.trigger.folder).expanduser()
    current = snapshot(watched)
    if not act.folder_snapshot:
        state.update(conn, act.agent_id, folder_snapshot=json.dumps(current))
        return
    before = json.loads(act.folder_snapshot)
    changed = [name for name, info in current.items() if before.get(name) != info]
    if not changed:
        state.update(conn, act.agent_id, folder_snapshot=json.dumps(current))
        return
    last = datetime.fromisoformat(act.last_run_at) if act.last_run_at else None
    if last and now - last < timedelta(minutes=defn.trigger.min_gap_minutes):
        return  # keep the old snapshot so these changes are still "new" next time
    target = payload_dir(defn.name, now)
    copy_into(target, [watched / name for name in sorted(changed)])
    occurrence = state.claim(conn, act.agent_id, now.isoformat(), "folder", str(target))
    state.update(conn, act.agent_id, folder_snapshot=json.dumps(current))
    if occurrence is not None:
        start(occurrence)
