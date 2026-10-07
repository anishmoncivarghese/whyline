"""This Mac's acceptance of agents (spec section 2). Only an accepted,
active activation whose definition hash still matches may run on a schedule
or trigger. SQLite, so concurrent ticks can claim occurrences safely."""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from whyline.agents import definitions, paths

# Two statements, not executescript. Python 3.11's executescript always
# issues COMMIT first, and autocommit has no transaction for that COMMIT.
_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS activations (
      agent_id TEXT PRIMARY KEY, kind TEXT, root TEXT, def_path TEXT, accepted_hash TEXT,
      status TEXT, paused_reason TEXT DEFAULT '', last_run_at TEXT DEFAULT '',
      next_due_at TEXT DEFAULT '', consecutive_failures INTEGER DEFAULT 0,
      backoff_until TEXT DEFAULT '', using_backup_until TEXT DEFAULT '',
      folder_snapshot TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS occurrences (
      id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, due_at TEXT, source TEXT,
      payload_dir TEXT DEFAULT '', status TEXT, run_id TEXT DEFAULT '',
      UNIQUE(agent_id, due_at)
    )
    """,
)

# SQLITE_CORRUPT is 11, SQLITE_NOTADB is 26. A lock or a missing directory
# raises DatabaseError too, and must not be thrown away.
_CORRUPT_CODES = {11, 26}


@dataclass
class Activation:
    agent_id: str
    kind: str
    root: str
    def_path: str
    accepted_hash: str
    status: str
    paused_reason: str = ""
    last_run_at: str = ""
    next_due_at: str = ""
    consecutive_failures: int = 0
    backoff_until: str = ""
    using_backup_until: str = ""
    folder_snapshot: str = ""


def _create_private(path: Path) -> bool:
    """Create path as 0600 when it is absent. True when this call created it."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    os.close(fd)
    # open() masks the mode with umask; the store is 0600 regardless
    # (same reason paths._private_dir and records._write_private chmod).
    path.chmod(0o600)
    return True


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        for statement in _SCHEMA:
            conn.execute(statement)
    except sqlite3.DatabaseError:
        conn.close()
        raise
    return conn


def _corrupt(exc: sqlite3.DatabaseError) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    if code in _CORRUPT_CODES:
        return True
    message = str(exc).lower()
    return "not a database" in message or "malformed" in message


def _quarantine(path: Path) -> None:
    # A second failure in the same second must not overwrite the copy
    # already set aside.
    stamp = int(time.time())
    dest = path.with_name(f"state.sqlite3.corrupt-{stamp}")
    extra = 0
    while dest.exists():
        extra += 1
        dest = path.with_name(f"state.sqlite3.corrupt-{stamp}-{extra}")
    os.replace(path, dest)


def connect() -> sqlite3.Connection:
    path = paths.state_path()
    created = _create_private(path)
    conn: sqlite3.Connection | None = None
    try:
        conn = _open(path)
        conn.execute("SELECT count(*) FROM activations").fetchone()
    except sqlite3.DatabaseError as exc:
        # Close before the rename: replacing an open database fails on Windows.
        if conn is not None:
            conn.close()
        # Not a database, so there are no rows to mark needs_review. A lock
        # or an I/O error is not that case and must surface.
        if not _corrupt(exc) or not path.exists():
            raise
        _quarantine(path)
        _create_private(path)
        conn = _open(path)
        created = True
    if created:
        path.chmod(0o600)
    if conn is None:
        raise sqlite3.DatabaseError("could not open the state store")
    return conn


def _activation(row: sqlite3.Row) -> Activation:
    return Activation(**{key: row[key] for key in row.keys()})


def get(conn: sqlite3.Connection, agent_id: str) -> Activation | None:
    row = conn.execute(
        "SELECT * FROM activations WHERE agent_id=?", (agent_id,)
    ).fetchone()
    return None if row is None else _activation(row)


def all_activations(conn: sqlite3.Connection) -> list[Activation]:
    rows = conn.execute("SELECT * FROM activations ORDER BY agent_id").fetchall()
    return [_activation(row) for row in rows]


def _hash(defn) -> str:
    return definitions.definition_hash(defn.path.read_text(encoding="utf-8"))


def accept(conn: sqlite3.Connection, defn) -> Activation:
    act = get(conn, defn.agent_id) or Activation(
        defn.agent_id, defn.kind, str(defn.root), str(defn.path), "", "active"
    )
    act.accepted_hash, act.status, act.paused_reason = _hash(defn), "active", ""
    act.def_path, act.root = str(defn.path), str(defn.root)
    values = asdict(act)
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    conn.execute(
        f"INSERT OR REPLACE INTO activations ({cols}) VALUES ({marks})",
        tuple(values.values()),
    )
    return act


def update(conn: sqlite3.Connection, agent_id: str, **changes) -> None:
    allowed = {f.name for f in fields(Activation)} - {"agent_id"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"unknown activation fields: {sorted(unknown)}")
    if changes:
        sets = ", ".join(f"{name}=?" for name in changes)
        conn.execute(
            f"UPDATE activations SET {sets} WHERE agent_id=?",
            (*changes.values(), agent_id),
        )


def set_status(conn: sqlite3.Connection, agent_id: str, status: str, reason: str = "") -> None:
    update(conn, agent_id, status=status, paused_reason=reason)


def remove(conn: sqlite3.Connection, agent_id: str) -> None:
    conn.execute("DELETE FROM activations WHERE agent_id=?", (agent_id,))
    conn.execute("DELETE FROM occurrences WHERE agent_id=?", (agent_id,))


def check_hash(conn: sqlite3.Connection, defn) -> str:
    """Status after comparing the file to the accepted hash.

    A mismatch is stored as needs_review. A later match does not clear it:
    the agent stays stopped until accept() runs again.
    """
    act = get(conn, defn.agent_id)
    if act is None:
        return "not accepted"
    if act.accepted_hash != _hash(defn) and act.status != "needs_review":
        set_status(conn, defn.agent_id, "needs_review", "the definition changed")
        return "needs_review"
    stored = get(conn, defn.agent_id)
    if stored is None:
        return "not accepted"
    return stored.status


def status_of(conn: sqlite3.Connection, defn) -> str:
    """Stored status. This does not re-read the file; check_hash does."""
    act = get(conn, defn.agent_id)
    return "not accepted" if act is None else act.status
