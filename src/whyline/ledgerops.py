"""Keeping the local ledger small and private: prompt capture policy,
pruning old mechanical events, and a summary of what the ledger holds.

Measured on this project on 2026-09-30: raw prompt bodies were 81% of a
2.1 MB ledger, and nothing but `timeline --include-prompts` ever read them.
The ledger is gitignored, but it still sits on disk, in backups and in
anything that copies the working tree, so the default now keeps no prompt
text at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from whyline import events, ledger, paths, state

METADATA = "metadata"
REDACTED = "redacted"
FULL = "full"
POLICIES = (METADATA, REDACTED, FULL)
DEFAULT_POLICY = METADATA

# Read by almost nothing; skipped on the light read path.
MECHANICAL_TYPES = (events.INSTRUCTION, events.FILE_TOUCHED)
# Safe to prune: mechanical detail. Decisions, handoffs, closes, attachments
# and retractions are the record and are never pruned.
PRUNABLE_TYPES = (
    events.INSTRUCTION,
    events.FILE_TOUCHED,
    events.SESSION_STARTED,
    events.SESSION_ENDED,
)


def config_path(root: Path) -> Path:
    return paths.whyline_dir(root) / "config.json"


def _load_config(root: Path) -> dict:
    try:
        value = json.loads(config_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def policy(root: Path) -> str:
    value = _load_config(root).get("prompt_capture")
    return value if value in POLICIES else DEFAULT_POLICY


def set_policy(root: Path, value: str) -> None:
    if value not in POLICIES:
        raise ValueError(f"prompt capture must be one of {', '.join(POLICIES)}")
    config = {**_load_config(root), "prompt_capture": value}
    state.atomic_write_json(config_path(root), config)
    _ensure_ignored(paths.whyline_dir(root) / ".gitignore", "config.json")


def _ensure_ignored(gitignore: Path, entry: str) -> None:
    """Repositories set up before config.json existed don't ignore it yet;
    a privacy setting must not be committed by accident."""
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if entry in existing.splitlines():
        return
    separator = "" if not existing or existing.endswith("\n") else "\n"
    gitignore.write_text(existing + separator + entry + "\n", encoding="utf-8")


# Best effort, and labelled so: it catches common secret shapes, not all.
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"eyJ[\w\-]+\.[\w\-]+\.[\w\-]+"),
    re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
)
_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_\-]?key)(\s*[=:]\s*)\S+"
)


def redact(text: str) -> str:
    text = _ASSIGNMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text


def capture_fields(text: str, chosen: str) -> dict:
    """The fields an Instruction event stores for prompt `text`."""
    fields = {
        "capture": chosen,
        "chars": len(text),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    if chosen == FULL:
        fields["text"] = text
    elif chosen == REDACTED:
        fields["text"] = redact(text)
    return fields


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _replace(tmp: Path, dest: Path) -> None:
    os.replace(tmp, dest)


def _tail_hook() -> None:
    """Test seam: the moment between writing the rewrite and copying the tail."""


def _rewrite(root: Path, transform, dry_run: bool) -> int:
    """Rewrite the ledger through `transform(event) -> event | None`;
    returns how many events it removed or changed.

    Appends take the same lock, so they wait for the rewrite. Lines that
    still appear after the snapshot -- from a writer that doesn't lock,
    such as an older whyline hook installed elsewhere -- are copied across
    unchanged just before the new file replaces the old one."""
    target = paths.ledger_path(root)
    if not target.exists():
        return 0
    with state.file_lock(target):
        raw = target.read_bytes()
        changed = 0
        kept_lines = []
        for line in raw.decode("utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                kept_lines.append(line)  # never silently drop what can't be read
                continue
            result = transform(event)
            if result is None:
                changed += 1
            elif result is not event:
                changed += 1
                kept_lines.append(ledger._serialise(result))
            else:
                kept_lines.append(line)
        if dry_run or not changed:
            return changed
        tmp = target.with_name(target.name + ".rewrite")
        tmp.write_text("".join(line + "\n" for line in kept_lines), encoding="utf-8")
        _tail_hook()
        tail = target.read_bytes()[len(raw):]
        if tail:
            with tmp.open("ab") as handle:
                handle.write(tail)
        _replace(tmp, target)
    return changed


def prune(root: Path, *, older_than_days: float, dry_run: bool = False, now=None) -> int:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=older_than_days)

    def transform(event: dict):
        if event.get("type") not in PRUNABLE_TYPES:
            return event
        ts = _parse_ts(event.get("ts"))
        return None if ts is not None and ts < cutoff else event

    return _rewrite(root, transform, dry_run)


def scrub(root: Path, *, dry_run: bool = False) -> int:
    chosen = policy(root)
    if chosen == FULL:
        raise ValueError("the prompt capture policy is full; nothing to scrub")

    def transform(event: dict):
        if event.get("type") != events.INSTRUCTION or "text" not in event:
            return event
        if event.get("capture") == chosen:
            return event
        text = str(event.get("text", ""))
        updated = {key: value for key, value in event.items() if key != "text"}
        updated.update(capture_fields(text, chosen))
        return updated

    return _rewrite(root, transform, dry_run)


def stats(root: Path) -> dict:
    target = paths.ledger_path(root)
    found, skipped = ledger.read_all(target)
    types: dict[str, int] = {}
    prompt_bytes = 0
    for event in found:
        kind = str(event.get("type", "?"))
        types[kind] = types.get(kind, 0) + 1
        if kind == events.INSTRUCTION:
            prompt_bytes += len(str(event.get("text", "")).encode("utf-8"))
    return {
        "path": str(target),
        "bytes": target.stat().st_size if target.exists() else 0,
        "events": len(found),
        "unreadable_lines": skipped,
        "types": dict(sorted(types.items(), key=lambda item: -item[1])),
        "prompt_text_bytes": prompt_bytes,
        "policy": policy(root),
    }
