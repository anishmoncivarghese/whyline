"""One list of models for every agent CLI.

A CLI's own listing (where a command is known), then the built-in list, then
the user's additions, each id once. The listing is cached in
``~/.whyline/models.json`` so `cached` never starts a process.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

AGENT_MODELS: dict[str, list[str]] = {
    "claude": [
        "opus",
        "sonnet",
        "haiku",
        "claude-opus-5-5",
        "claude-sonnet-4-6",
        "claude-opus-4-6",
    ],
    "codex": [
        "gpt-5.6-sol",
        "gpt-5.6",
        "gpt-5-codex",
    ],
    "grok": [
        "grok-4.6",
        "grok-4",
    ],
}

# CLIs that can list their own models.
LISTERS: dict[str, list[str]] = {"antigravity": ["agy", "models"]}

LIST_TIMEOUT = 10
STALE_AFTER = 24 * 3600.0
_AGY_NEGATIVE_TTL = 60.0
_ID = re.compile(r"[A-Za-z0-9._:/\[\]-]{1,80}")

_clock = time.monotonic


def _path() -> Path:
    return Path.home() / ".whyline" / "models.json"


def _load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _entry(data: dict, cli: str) -> dict:
    entry = data.get(cli)
    return entry if isinstance(entry, dict) else {}


def _pairs(raw) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if (
            isinstance(item, list)
            and len(item) == 2
            and all(isinstance(x, str) for x in item)
        ):
            out.append((item[0], item[1]))
    return out


def _merge(*groups: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    merged: list[tuple[str, str]] = []
    for group in groups:
        for label, model_id in group:
            if model_id not in seen:
                seen.add(model_id)
                merged.append((label, model_id))
    return merged


def _builtin(cli: str) -> list[tuple[str, str]]:
    return [(m, m) for m in AGENT_MODELS.get(cli, [])]


def _added(entry: dict) -> list[tuple[str, str]]:
    ids = entry.get("added")
    if not isinstance(ids, list):
        return []
    return [(m, m) for m in ids if isinstance(m, str)]


def _combined(cli: str, listed: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return _merge(listed, _builtin(cli), _added(_entry(_load(), cli)))


def valid_id(model_id: str) -> bool:
    return isinstance(model_id, str) and _ID.fullmatch(model_id) is not None


def parse_listing(stdout: str) -> list[tuple[str, str]]:
    """(label, id) pairs from a listing command's output."""
    models: list[tuple[str, str]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("Fetching") or line.startswith("⠋") or line.startswith("..."):
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            model_id = parts[0].strip()
            label = parts[1].strip()
        else:
            tokens = line.split(None, 1)
            if not tokens:
                continue
            model_id = tokens[0].strip()
            label = tokens[1].strip() if len(tokens) > 1 else model_id
        if model_id and (label, model_id) not in models:
            models.append((label, model_id))
    return models


# Kept under its old name for callers that parsed Antigravity output.
_parse_agy_models = parse_listing


def run_lister(cli: str, run=subprocess.run) -> list[tuple[str, str]] | None:
    """The CLI's own list, or None when it fails, times out or is empty."""
    cmd = LISTERS.get(cli)
    if cmd is None:
        return None
    try:
        res = run(cmd, capture_output=True, text=True, timeout=LIST_TIMEOUT)
        if res.returncode != 0:
            return None
        return parse_listing(res.stdout) or None
    except Exception:
        return None


def options(
    cli: str, *, refresh: bool = False, run=subprocess.run, now=time.time
) -> list[tuple[str, str]]:
    """(label, id) options: the CLI's list, built-in list, then user additions.

    A listing command is run when `refresh` is set or the cache is missing or
    stale. If it fails the cache is left as it is.
    """
    if cli in LISTERS and (refresh or _cache_state(cli, now) != "fresh"):
        listed = run_lister(cli, run)
        if listed:
            data = _load()
            entry = dict(_entry(data, cli))
            entry["models"] = [list(p) for p in listed]
            entry["fetched"] = now()
            data[cli] = entry
            try:
                _save(data)
            except OSError:
                pass
    return cached(cli)


def _cache_state(cli: str, now=time.time) -> str:
    entry = _entry(_load(), cli)
    fetched = entry.get("fetched")
    if not _pairs(entry.get("models")) or not isinstance(fetched, (int, float)):
        return "none"
    return "stale" if now() - fetched > STALE_AFTER else "fresh"


def cached(cli: str) -> list[tuple[str, str]]:
    """Options from the file and built-in list. Never starts a process."""
    return _combined(cli, _pairs(_entry(_load(), cli).get("models")))


def stale(cli: str, *, now=time.time) -> bool:
    """True when the cached listing is more than 24 hours old."""
    return _cache_state(cli, now) == "stale"


def add(cli: str, model_id: str) -> None:
    if not valid_id(model_id):
        raise ValueError(
            f"'{model_id}' is not a model id: use 1 to 80 letters, digits "
            "or . _ : / - [ ]"
        )
    data = _load()
    entry = dict(_entry(data, cli))
    added = [m for m in entry.get("added", []) if isinstance(m, str)]
    if model_id not in added:
        added.append(model_id)
    entry["added"] = added
    data[cli] = entry
    _save(data)


def remove(cli: str, model_id: str) -> None:
    if not valid_id(model_id):
        raise ValueError(f"'{model_id}' is not a model id")
    data = _load()
    entry = dict(_entry(data, cli))
    added = [m for m in entry.get("added", []) if isinstance(m, str)]
    if model_id in added:
        entry["added"] = [m for m in added if m != model_id]
        data[cli] = entry
        _save(data)


# --- Antigravity session cache (moved from relay_ops) -----------------------


@dataclass(frozen=True)
class _AgyMiss:
    """Negative cache for a failed or empty `agy models` run."""

    expires_at: float


# None = never tried; list = session-long success; _AgyMiss = failure/empty TTL.
_AGY_MODELS_CACHE: list[tuple[str, str]] | _AgyMiss | None = None


def clear_antigravity_models_cache() -> None:
    global _AGY_MODELS_CACHE
    _AGY_MODELS_CACHE = None


def antigravity_models_status(*, now: float | None = None) -> str:
    """Cache state for Antigravity's dynamic catalogue: `untried`, `ok`, or `failed`.

    A failed or empty fetch is an `_AgyMiss`. After the negative TTL the
    status becomes `untried` again and a later fetch may retry.
    """
    cache = _AGY_MODELS_CACHE
    if cache is None:
        return "untried"
    if isinstance(cache, _AgyMiss):
        tick = _clock() if now is None else now
        return "failed" if tick < cache.expires_at else "untried"
    return "ok"


def antigravity_cached() -> list[tuple[str, str]] | None:
    """The session cache when it holds a list, else None."""
    if antigravity_models_status() == "ok" and isinstance(_AGY_MODELS_CACHE, list):
        return list(_AGY_MODELS_CACHE)
    return None


def antigravity_models(
    *, runner=None, clock=None, now: float | None = None
) -> list[tuple[str, str]] | None:
    """Fetch `agy models` unless the session cache says not to.

    Success is cached for the session. Failure, an empty list and an
    exception are cached for 60 seconds. Returns the (label, id) list, or None.
    """
    global _AGY_MODELS_CACHE
    tick_fn = clock or _clock
    run = runner if runner is not None else subprocess.run
    tick = tick_fn() if now is None else now
    status = antigravity_models_status(now=tick)
    if status == "ok" and isinstance(_AGY_MODELS_CACHE, list):
        return list(_AGY_MODELS_CACHE)
    if status == "failed":
        return None
    models = run_lister("antigravity", run)
    if models is None:
        _AGY_MODELS_CACHE = _AgyMiss(tick_fn() + _AGY_NEGATIVE_TTL)
        return None
    _AGY_MODELS_CACHE = models
    return list(models)
