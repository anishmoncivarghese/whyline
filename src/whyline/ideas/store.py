"""SQLite ledger for ideas: schema 5, statuses, and the allowed moves."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from whyline.ideas import paths

SCHEMA_VERSION = 5

STATUSES = (
    "captured",
    "scoring",
    "scored",
    "brainstorm_configuring",
    "brainstorming",
    "brainstormed",
    "dropped",
    "setup_configuring",
    "plan_waiting",
    "planning",
    "plan_review",
    "plan_discarded",
    "ready",
    "running",
    "paused",
    "stopped",
    "done",
)

# Destinations keyed by the status the idea is in. Cancel from
# brainstorm_configuring may go to captured or scored — the caller picks the
# origin, and the event records both ends.
ALLOWED = {
    "captured": frozenset({"scoring", "brainstorm_configuring", "dropped"}),
    "scoring": frozenset({"scored", "captured"}),
    "scored": frozenset({"brainstorm_configuring", "dropped", "scoring"}),
    "brainstorm_configuring": frozenset({"brainstorming", "captured", "scored"}),
    "brainstorming": frozenset({"brainstormed", "captured", "scored"}),
    "brainstormed": frozenset({"brainstorm_configuring", "setup_configuring", "dropped"}),
    "dropped": frozenset({"captured"}),
    "setup_configuring": frozenset({"plan_waiting", "planning", "brainstormed"}),
    "plan_waiting": frozenset({"planning", "brainstormed"}),
    "planning": frozenset({"plan_review", "brainstormed"}),
    "plan_review": frozenset({"ready", "planning", "plan_discarded"}),
    "plan_discarded": frozenset({"setup_configuring"}),
    "ready": frozenset({"running", "plan_discarded"}),
    "running": frozenset({"paused", "stopped", "done"}),
    "paused": frozenset({"running", "stopped"}),
    "stopped": frozenset({"running"}),
}

_PATH_COLUMNS = frozenset({"brainstorm_path", "spec_path", "plan_path"})

# Two statements, not executescript. Python 3.11's executescript always
# issues COMMIT first, and autocommit has no transaction for that COMMIT.
_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS ideas (
      id INTEGER PRIMARY KEY,
      created_at TEXT NOT NULL,
      source TEXT NOT NULL,
      source_ref TEXT,
      original_text TEXT NOT NULL,
      title TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 0,
      repo TEXT,
      brainstorm_path TEXT,
      spec_path TEXT,
      plan_path TEXT
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ideas_source_ref
      ON ideas (source, source_ref) WHERE source_ref IS NOT NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY,
      idea_id INTEGER NOT NULL,
      at TEXT NOT NULL,
      from_status TEXT NOT NULL,
      to_status TEXT NOT NULL,
      actor TEXT NOT NULL,
      note TEXT NOT NULL DEFAULT '',
      FOREIGN KEY (idea_id) REFERENCES ideas(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS analyses (
      id INTEGER PRIMARY KEY,
      idea_id INTEGER NOT NULL,
      version INTEGER NOT NULL,
      agent TEXT NOT NULL,
      report_path TEXT NOT NULL,
      usefulness INTEGER,
      complexity_mvp INTEGER,
      complexity_full INTEGER,
      verdict TEXT,
      confidence TEXT,
      sources_json TEXT NOT NULL DEFAULT '[]',
      created_at TEXT NOT NULL,
      FOREIGN KEY (idea_id) REFERENCES ideas(id),
      UNIQUE (idea_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS kv (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    )
    """,
)

# Schema 2: Telegram inbound updates. Applied on connect when the stored
# version is older than SCHEMA_VERSION. CREATE IF NOT EXISTS so a crash
# between the table and the version bump is safe to retry.
_SCHEMA_2 = (
    """
    CREATE TABLE IF NOT EXISTS inbound (
      update_id INTEGER PRIMARY KEY,
      chat_id INTEGER,
      at TEXT NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL DEFAULT '',
      callback_data TEXT,
      reply_to_message_id INTEGER,
      handled INTEGER NOT NULL DEFAULT 0
    )
    """,
)

# Schema 3: outgoing Telegram messages. idea_id is extra so a give-up can
# write an events note (that table requires an idea). /help leaves it null.
# message_id and callback_id are added to inbound: source_ref is
# chat:message_id, and answerCallbackQuery needs the callback id. Schema 2
# did not store either.
_SCHEMA_3 = (
    """
    CREATE TABLE IF NOT EXISTS outbox (
      id INTEGER PRIMARY KEY,
      chat_id INTEGER NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL DEFAULT '',
      buttons_json TEXT,
      document_path TEXT,
      attempts INTEGER NOT NULL DEFAULT 0,
      next_try_at TEXT,
      sent_at TEXT,
      idea_id INTEGER,
      FOREIGN KEY (idea_id) REFERENCES ideas(id)
    )
    """,
)

# Schema 4: inbox jobs the scheduler claims. The same CREATE runs from the
# score button, so a database that already has the table only bumps the
# version. Kinds today are score and brainstorm; later phases add more.
_SCHEMA_4 = (
    """
    CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY,
      idea_id INTEGER NOT NULL,
      kind TEXT NOT NULL,
      state TEXT NOT NULL,
      lease_until TEXT,
      attempts INTEGER NOT NULL DEFAULT 0,
      error TEXT,
      pid INTEGER
    )
    """,
)


class IllegalMove(Exception):
    pass


class StaleRevision(Exception):
    pass


class SchemaError(Exception):
    pass


@dataclass(frozen=True)
class Idea:
    id: int
    created_at: str
    source: str
    source_ref: str | None
    original_text: str
    title: str
    status: str
    revision: int
    repo: str | None
    brainstorm_path: str | None
    spec_path: str | None
    plan_path: str | None


@dataclass(frozen=True)
class Analysis:
    id: int
    idea_id: int
    version: int
    agent: str
    report_path: str
    usefulness: int | None
    complexity_mvp: int | None
    complexity_full: int | None
    verdict: str | None
    confidence: str | None
    sources_json: str
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _title_from(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _create_private(path: Path) -> bool:
    """Create path as 0600 when it is absent. True when this call created it."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    os.close(fd)
    path.chmod(0o600)
    return True


class _txn:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")


def _idea(row: sqlite3.Row) -> Idea:
    return Idea(**{field.name: row[field.name] for field in fields(Idea)})


def _analysis(row: sqlite3.Row) -> Analysis:
    return Analysis(**{field.name: row[field.name] for field in fields(Analysis)})


def _apply_schema_2(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_2:
        conn.execute(statement)


def _apply_schema_3(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_3:
        conn.execute(statement)
    _add_column(conn, "inbound", "message_id", "INTEGER")
    _add_column(conn, "inbound", "callback_id", "TEXT")


def _apply_schema_4(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_4:
        conn.execute(statement)


def _apply_schema_5(conn: sqlite3.Connection) -> None:
    """Remember Telegram message ids, and drop unsent callback acknowledgements.

    Taps are answered inside the poll, so a queued ``callback`` row would
    only fail later and be retried. A sent row is left as history.
    """
    _add_column(conn, "outbox", "tg_message_id", "INTEGER")
    conn.execute(
        "DELETE FROM outbox WHERE kind = 'callback' AND sent_at IS NULL"
    )


def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    found = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in found:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _check_schema(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT value FROM kv WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        version = 0
    else:
        try:
            version = int(row["value"])
        except (TypeError, ValueError) as exc:
            raise SchemaError(
                f"ideas database has an invalid schema_version: {row['value']!r}"
            ) from exc
        if version > SCHEMA_VERSION:
            raise SchemaError(
                f"ideas database is schema version {version}; "
                f"this whyline supports version {SCHEMA_VERSION}"
            )
        if version == SCHEMA_VERSION:
            return
    with _txn(conn):
        if version < 2:
            _apply_schema_2(conn)
        if version < 3:
            _apply_schema_3(conn)
        if version < 4:
            _apply_schema_4(conn)
        if version < 5:
            _apply_schema_5(conn)
        if version == 0:
            conn.execute(
                "INSERT INTO kv (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        else:
            conn.execute(
                "UPDATE kv SET value = ? WHERE key = 'schema_version'",
                (str(SCHEMA_VERSION),),
            )


def connect() -> sqlite3.Connection:
    paths.home()
    path = paths.db_path()
    created = _create_private(path)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for statement in _SCHEMA:
            conn.execute(statement)
        _check_schema(conn)
    except Exception:
        conn.close()
        raise
    if created:
        path.chmod(0o600)
    return conn


def add(conn: sqlite3.Connection, text: str, *, source: str, source_ref: str | None = None) -> Idea:
    with _txn(conn):
        if source_ref is not None:
            row = conn.execute(
                "SELECT * FROM ideas WHERE source = ? AND source_ref = ?",
                (source, source_ref),
            ).fetchone()
            if row is not None:
                return _idea(row)
        try:
            cursor = conn.execute(
                """
                INSERT INTO ideas (
                  created_at, source, source_ref, original_text, title, status, revision
                ) VALUES (?, ?, ?, ?, ?, 'captured', 0)
                """,
                (_now(), source, source_ref, text, _title_from(text)),
            )
        except sqlite3.IntegrityError:
            row = conn.execute(
                "SELECT * FROM ideas WHERE source = ? AND source_ref = ?",
                (source, source_ref),
            ).fetchone()
            if row is None:
                raise
            return _idea(row)
        row = conn.execute(
            "SELECT * FROM ideas WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return _idea(row)


def get(conn: sqlite3.Connection, idea_id: int) -> Idea | None:
    row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    return None if row is None else _idea(row)


def list_ideas(conn: sqlite3.Connection, status: str | None = None) -> list[Idea]:
    if status is None:
        rows = conn.execute("SELECT * FROM ideas ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM ideas WHERE status = ? ORDER BY id", (status,)
        ).fetchall()
    return [_idea(row) for row in rows]


def transition(
    conn: sqlite3.Connection,
    idea_id: int,
    to: str,
    *,
    expected_revision: int,
    actor: str,
    note: str = "",
) -> Idea:
    with _txn(conn):
        row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        if row is None:
            raise LookupError(f"no idea {idea_id}")
        if row["revision"] != expected_revision:
            raise StaleRevision(
                f"idea {idea_id} is at revision {row['revision']}, not {expected_revision}"
            )
        current = row["status"]
        if to not in ALLOWED.get(current, frozenset()):
            raise IllegalMove(f"cannot move idea {idea_id} from {current} to {to}")
        conn.execute(
            "UPDATE ideas SET status = ?, revision = ? WHERE id = ?",
            (to, expected_revision + 1, idea_id),
        )
        conn.execute(
            """
            INSERT INTO events (idea_id, at, from_status, to_status, actor, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (idea_id, _now(), current, to, actor, note),
        )
        return _idea(
            conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        )


def set_paths(conn: sqlite3.Connection, idea_id: int, **given: str | None) -> Idea:
    unknown = [key for key in given if key not in _PATH_COLUMNS]
    if unknown:
        raise TypeError(f"unknown path fields: {', '.join(sorted(unknown))}")
    with _txn(conn):
        row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        if row is None:
            raise LookupError(f"no idea {idea_id}")
        if given:
            assignments = ", ".join(f"{key} = ?" for key in given)
            conn.execute(
                f"UPDATE ideas SET {assignments} WHERE id = ?",
                (*given.values(), idea_id),
            )
        return _idea(
            conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        )


def set_repo(conn: sqlite3.Connection, idea_id: int, repo: str) -> Idea:
    with _txn(conn):
        row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        if row is None:
            raise LookupError(f"no idea {idea_id}")
        conn.execute("UPDATE ideas SET repo = ? WHERE id = ?", (repo, idea_id))
        return _idea(
            conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        )


def bump_revision(
    conn: sqlite3.Connection,
    idea_id: int,
    *,
    expected_revision: int,
    actor: str,
    note: str = "",
) -> Idea:
    with _txn(conn):
        row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        if row is None:
            raise LookupError(f"no idea {idea_id}")
        if row["revision"] != expected_revision:
            raise StaleRevision(
                f"idea {idea_id} is at revision {row['revision']}, not {expected_revision}"
            )
        conn.execute(
            "UPDATE ideas SET revision = ? WHERE id = ?",
            (expected_revision + 1, idea_id),
        )
        current = row["status"]
        conn.execute(
            """
            INSERT INTO events (idea_id, at, from_status, to_status, actor, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (idea_id, _now(), current, current, actor, note),
        )
        return _idea(
            conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        )


def add_analysis(
    conn: sqlite3.Connection,
    idea_id: int,
    *,
    agent: str,
    report_path: str,
    usefulness: int | None = None,
    complexity_mvp: int | None = None,
    complexity_full: int | None = None,
    verdict: str | None = None,
    confidence: str | None = None,
    sources_json: str = "[]",
) -> Analysis:
    with _txn(conn):
        row = conn.execute("SELECT id FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        if row is None:
            raise LookupError(f"no idea {idea_id}")
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM analyses WHERE idea_id = ?",
            (idea_id,),
        ).fetchone()[0]
        cursor = conn.execute(
            """
            INSERT INTO analyses (
              idea_id, version, agent, report_path, usefulness, complexity_mvp,
              complexity_full, verdict, confidence, sources_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                idea_id,
                version,
                agent,
                report_path,
                usefulness,
                complexity_mvp,
                complexity_full,
                verdict,
                confidence,
                sources_json,
                _now(),
            ),
        )
        return _analysis(
            conn.execute(
                "SELECT * FROM analyses WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        )
