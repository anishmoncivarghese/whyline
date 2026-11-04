"""Relay chat history: one JSONL file per repo and relay run."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from whyline.relaychat.settings import base_dir

ADHOC = "adhoc"
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def repo_slug(repo: Path | str) -> str:
    resolved = Path(repo).expanduser().resolve()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", resolved.name).strip("-.") or "repo"
    return f"{name}-{hashlib.sha256(str(resolved).encode()).hexdigest()[:10]}"


def path(repo: Path | str, run_id: str | None, base: Path | None = None) -> Path:
    run = run_id or ADHOC
    if not _SAFE.match(run):
        raise ValueError(f"run id {run!r} may only use letters, digits, '.', '_' and '-'")
    return base_dir(base) / repo_slug(repo) / f"{run}.jsonl"


def append(repo: Path | str, run_id: str | None, role: str, text: str,
           agent: str | None = None, base: Path | None = None) -> dict:
    if not isinstance(role, str) or not role.strip():
        raise ValueError("role must be a non-empty string")
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    record = {"ts": datetime.now(timezone.utc).isoformat(), "role": role,
              "text": text, "agent": agent}
    target = path(repo, run_id, base)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return record


def load(repo: Path | str, run_id: str | None, last: int | None = None,
         base: Path | None = None) -> list[dict]:
    try:
        raw = path(repo, run_id, base).read_text(encoding="utf-8")
    except OSError:
        return []
    records: list[dict] = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue  # a torn or hand-edited line is skipped
        if isinstance(item, dict):
            records.append(item)
    if last is not None:
        records = records[-last:] if last > 0 else []
    return records


def clear(repo: Path | str, run_id: str | None, base: Path | None = None) -> Path | None:
    """Move the history aside; it is renamed, never deleted."""
    source = path(repo, run_id, base)
    if not source.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run = run_id or ADHOC
    target = source.with_name(f"{run}.{stamp}.jsonl")
    source.rename(target)
    return target
