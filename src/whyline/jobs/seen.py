"""Seen-postings store: ~/.whyline/jobs/jobs.sqlite (mode 0600) (JOB-10)."""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from . import paths
from .fetch import Posting

DB_NAME = "jobs.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS postings (
    uid TEXT PRIMARY KEY,
    company TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    dropped_reason TEXT
)
"""


def db_path() -> Path:
    return paths.home() / DB_NAME


def _connect(path: Path | None = None) -> sqlite3.Connection:
    target = Path(path) if path is not None else db_path()
    if target.is_symlink():
        raise OSError(f"refusing symlinked jobs database: {target}")
    if not target.exists():
        os.close(os.open(target, os.O_CREAT | os.O_WRONLY, 0o600))
    if os.name != "nt":
        target.chmod(0o600)
    conn = sqlite3.connect(target)
    conn.execute(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_only(postings: Iterable[Posting], *, path: Path | None = None) -> list[str]:
    """Return uids not seen before (in order), recording every posting."""
    now = _now()
    fresh: list[str] = []
    conn = _connect(path)
    try:
        with conn:
            for p in postings:
                cur = conn.execute(
                    "UPDATE postings SET last_seen = ? WHERE uid = ?", (now, p.uid)
                )
                if cur.rowcount == 0:
                    conn.execute(
                        "INSERT INTO postings (uid, company, title, url, first_seen, last_seen)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (p.uid, p.company, p.title, p.url, now, now),
                    )
                    fresh.append(p.uid)
    finally:
        conn.close()
    return fresh


def mark_dropped(uid: str, reason: str, *, path: Path | None = None) -> None:
    conn = _connect(path)
    try:
        with conn:
            conn.execute("UPDATE postings SET dropped_reason = ? WHERE uid = ?", (reason, uid))
    finally:
        conn.close()
