"""Workflows state: activations, runs, step runs and approvals in one SQLite
file under the private workflows folder (spec section 3)."""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from whyline.workflows import capabilities, paths
from whyline.workflows.definitions import Workflow, semantic_hash

ACTIVE, PAUSED, NEEDS_REVIEW = "active", "paused", "needs_review"
REPLACED = "replaced by a newer trigger"

_MIGRATIONS = (
    """
    CREATE TABLE activations(
        workflow_id TEXT PRIMARY KEY, path TEXT, accepted_hash TEXT, accepted_at TEXT,
        status TEXT, reason TEXT, trusted_json TEXT, capability_text TEXT,
        last_run_at TEXT, next_due_at TEXT, folder_snapshot TEXT);
    CREATE TABLE runs(
        id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id TEXT, revision TEXT,
        definition_json TEXT, source TEXT, dedupe_key TEXT UNIQUE, inputs_json TEXT,
        status TEXT, reason TEXT, wake_at TEXT, created TEXT, started TEXT, ended TEXT,
        pid INTEGER);
    CREATE INDEX runs_by_workflow ON runs(workflow_id, id);
    CREATE TABLE step_runs(
        run_id INTEGER, step_id TEXT, seq INTEGER, status TEXT, reason TEXT,
        attempt INTEGER, provider TEXT, started TEXT, ended TEXT, output_path TEXT,
        PRIMARY KEY(run_id, step_id));
    CREATE TABLE approvals(
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, step_id TEXT, revision TEXT,
        args_hash TEXT, nonce TEXT, status TEXT, message TEXT, expires_at TEXT,
        decided_by TEXT, decided_at TEXT);
    """,
)


@dataclass(frozen=True)
class Activation:
    workflow_id: str
    path: str
    accepted_hash: str
    accepted_at: str
    status: str
    reason: str = ""
    trusted_json: str = "{}"
    capability_text: str = ""
    last_run_at: str | None = None
    next_due_at: str | None = None
    folder_snapshot: str | None = None

    @property
    def capabilities(self) -> list[str]:
        return self.capability_text.splitlines()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = Path(path) if path else paths.state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    os.close(os.open(target, os.O_CREAT | os.O_RDWR, 0o600))
    target.chmod(0o600)
    conn = sqlite3.connect(target, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, script in enumerate(_MIGRATIONS[version:], start=version + 1):
        conn.executescript(f"BEGIN;{script}PRAGMA user_version={number};COMMIT;")
    return conn


# ---- activations ----------------------------------------------------------

def get(conn: sqlite3.Connection, workflow_id: str) -> Activation | None:
    row = conn.execute("SELECT * FROM activations WHERE workflow_id=?",
                       (workflow_id,)).fetchone()
    return Activation(**dict(row)) if row else None


def all_activations(conn: sqlite3.Connection) -> list[Activation]:
    rows = conn.execute("SELECT * FROM activations ORDER BY workflow_id").fetchall()
    return [Activation(**dict(r)) for r in rows]


def accept(conn: sqlite3.Connection, workflow: Workflow) -> Activation:
    conn.execute(
        "INSERT INTO activations(workflow_id, path, accepted_hash, accepted_at, status,"
        " reason, trusted_json, capability_text) VALUES(?,?,?,?,?,?,?,?)"
        " ON CONFLICT(workflow_id) DO UPDATE SET path=excluded.path,"
        " accepted_hash=excluded.accepted_hash, accepted_at=excluded.accepted_at,"
        " status=excluded.status, reason='', capability_text=excluded.capability_text",
        (workflow.workflow_id, str(workflow.path), semantic_hash(workflow.raw), _now(),
         ACTIVE, "", "{}", "\n".join(capabilities.summary(workflow))))
    return get(conn, workflow.workflow_id)  # type: ignore[return-value]


def check(conn: sqlite3.Connection, workflow: Workflow) -> str:
    found = get(conn, workflow.workflow_id)
    if found is None:
        return NEEDS_REVIEW
    if found.accepted_hash != semantic_hash(workflow.raw):
        if found.status != NEEDS_REVIEW:
            conn.execute("UPDATE activations SET status=?, reason=? WHERE workflow_id=?",
                         (NEEDS_REVIEW, "definition changed since it was accepted",
                          workflow.workflow_id))
        return NEEDS_REVIEW
    return found.status


def pause(conn: sqlite3.Connection, workflow_id: str, reason: str = "") -> None:
    conn.execute("UPDATE activations SET status=?, reason=? WHERE workflow_id=?"
                 " AND status=?", (PAUSED, reason, workflow_id, ACTIVE))


def resume(conn: sqlite3.Connection, workflow_id: str) -> None:
    conn.execute("UPDATE activations SET status=?, reason='' WHERE workflow_id=?"
                 " AND status=?", (ACTIVE, workflow_id, PAUSED))


def remove(conn: sqlite3.Connection, workflow_id: str) -> None:
    conn.execute("DELETE FROM activations WHERE workflow_id=?", (workflow_id,))


# ---- runs -----------------------------------------------------------------

def claim_run(conn: sqlite3.Connection, workflow: Workflow, *, source: str,
              dedupe_key: str, inputs: dict) -> int | None:
    wid = workflow.workflow_id
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM runs WHERE dedupe_key=?", (dedupe_key,)).fetchone():
            conn.execute("ROLLBACK")
            return None
        busy = conn.execute(
            "SELECT 1 FROM runs WHERE workflow_id=? AND status IN ('running','waiting')",
            (wid,)).fetchone()
        if busy:
            conn.execute(
                "UPDATE runs SET status='cancelled', reason=?, ended=? "
                "WHERE workflow_id=? AND status='queued'", (REPLACED, _now(), wid))
        cur = conn.execute(
            "INSERT INTO runs(workflow_id, revision, definition_json, source, dedupe_key,"
            " inputs_json, status, created) VALUES(?,?,?,?,?,?,?,?)",
            (wid, semantic_hash(workflow.raw), json.dumps(workflow.raw, default=str),
             source, dedupe_key, json.dumps(inputs), "queued", _now()))
        conn.execute("COMMIT")
        return cur.lastrowid
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def next_queued(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM runs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()


_RUN_COLUMNS = {"status", "reason", "wake_at", "started", "ended", "pid"}
_STEP_COLUMNS = {"seq", "status", "reason", "attempt", "provider", "started", "ended",
                 "output_path"}


def set_run(conn: sqlite3.Connection, run_id: int, **values: object) -> None:
    if not values or not set(values) <= _RUN_COLUMNS:
        raise ValueError(f"unknown run fields: {sorted(set(values) - _RUN_COLUMNS)}")
    marks = ", ".join(f"{k}=?" for k in values)
    conn.execute(f"UPDATE runs SET {marks} WHERE id=?", (*values.values(), run_id))


def set_step(conn: sqlite3.Connection, run_id: int, step_id: str, **values: object) -> None:
    if not set(values) <= _STEP_COLUMNS:
        raise ValueError(f"unknown step fields: {sorted(set(values) - _STEP_COLUMNS)}")
    conn.execute("INSERT OR IGNORE INTO step_runs(run_id, step_id) VALUES(?,?)",
                 (run_id, step_id))
    if values:
        marks = ", ".join(f"{k}=?" for k in values)
        conn.execute(f"UPDATE step_runs SET {marks} WHERE run_id=? AND step_id=?",
                     (*values.values(), run_id, step_id))


def steps_of(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM step_runs WHERE run_id=? ORDER BY seq, step_id",
                        (run_id,)).fetchall()


def runs_of(conn: sqlite3.Connection, workflow_id: str, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM runs WHERE workflow_id=? ORDER BY id DESC LIMIT ?",
                        (workflow_id, limit)).fetchall()
