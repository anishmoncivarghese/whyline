"""The job tracker: scored postings from a `job-search` run, kept in jobs.sqlite (JOB-14).

The agent's final answer ends with a fenced `scores` block; the `jobs-fetch` step wrote a
`manifest.json` that maps each posting file to its uid, company, title and url. Each scored file
is upserted into the `tracked` table. The status and notes you set are never overwritten by a
later run. The same rows are written as an xlsx view (standard library only).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import paths, seen

STATUSES = ("new", "shortlisted", "applied", "interview", "offer", "rejected", "archived")
XLSX_NAME = "jobs.xlsx"
MANIFEST = "manifest.json"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracked (
    uid TEXT PRIMARY KEY,
    company TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    score INTEGER,
    verdict TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
)
"""
_BLOCK = re.compile(r"```scores[ \t]*\r?\n(.*?)```", re.DOTALL)
_SHEET = (
    ("row", "number", 8),
    ("company", "text", 24),
    ("title", "text", 42),
    ("score", "number", 10),
    ("verdict", "text", 12),
    ("reason", "text", 60),
    ("status", "text", 14),
    ("notes", "text", 40),
    ("url", "text", 48),
    ("updated", "date", 22),
    ("uid", "text", 28),
)


class TrackerError(Exception):
    """A tracker request that cannot be done (unknown row, bad status)."""


def xlsx_path() -> Path:
    return paths.home() / XLSX_NAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = seen._connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def parse_scores(final_text: str) -> list[dict] | None:
    """The last `scores` block as a list of objects, or None when absent or malformed."""
    blocks = _BLOCK.findall(final_text or "")
    if not blocks:
        return None
    try:
        data = json.loads(blocks[-1])
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    return [item for item in data if isinstance(item, dict)]


def _read_manifest(run_dir: Path) -> dict[str, dict]:
    try:
        data = json.loads((Path(run_dir) / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _score(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    try:
        return round(value)
    except OverflowError:
        return None


def record_run(
    run_dir: Path, final_text: str, *, path: Path | None = None, export: bool = True
) -> int:
    """Upsert the scored postings of one run; return how many rows were written.

    A missing or malformed block, a missing manifest, or a `file` not in the manifest records
    nothing for that entry. Status and notes already on a row are kept.
    """
    items = parse_scores(final_text)
    if not items:
        return 0
    manifest = _read_manifest(run_dir)
    now = _now()
    written = 0
    conn = connect(path)
    try:
        with conn:
            for item in items:
                entry = manifest.get(item.get("file")) if isinstance(item.get("file"), str) else None
                if not isinstance(entry, dict) or not isinstance(entry.get("uid"), str) or not entry["uid"]:
                    continue
                verdict = str(item.get("verdict") or "").strip().lower()
                conn.execute(
                    "INSERT INTO tracked (uid, company, title, url, score, verdict, reason,"
                    " status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(uid) DO UPDATE SET company = excluded.company,"
                    " title = excluded.title, url = excluded.url, score = excluded.score,"
                    " verdict = excluded.verdict, reason = excluded.reason,"
                    " updated_at = excluded.updated_at",
                    (
                        entry["uid"],
                        str(entry.get("company") or ""),
                        str(entry.get("title") or ""),
                        str(entry.get("url") or ""),
                        _score(item.get("total")),
                        verdict,
                        str(item.get("reason") or ""),
                        "shortlisted" if verdict == "shortlist" else "new",
                        now,
                    ),
                )
                written += 1
        if written and export:
            try:
                export_xlsx(conn)
            except Exception:  # the view is rebuildable with `whyline jobs excel`
                pass
    finally:
        conn.close()
    return written


def list_rows(
    *, status: str | None = None, min_score: int | None = None, path: Path | None = None
) -> list[dict]:
    """Tracked rows, best score first, each with its `row` number."""
    sql = "SELECT rowid AS row, * FROM tracked"
    clauses, args = [], []
    if status:
        clauses.append("status = ?")
        args.append(status)
    if min_score is not None:
        clauses.append("score >= ?")
        args.append(min_score)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY score IS NULL, score DESC, rowid"
    conn = connect(path)
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def set_status(
    ref: str, status: str, note: str | None = None, *, path: Path | None = None
) -> dict:
    """Set the status (and optionally the notes) of a row given by uid or row number."""
    if status not in STATUSES:
        raise TrackerError(f"Unknown status '{status}'. Choose one of: {', '.join(STATUSES)}.")
    conn = connect(path)
    try:
        row = conn.execute("SELECT rowid AS row, * FROM tracked WHERE uid = ?", (ref,)).fetchone()
        if row is None and ref.isdigit():
            row = conn.execute("SELECT rowid AS row, * FROM tracked WHERE rowid = ?", (int(ref),)).fetchone()
        if row is None:
            raise TrackerError(f"No tracked job '{ref}'.")
        notes = row["notes"] if note is None else note
        with conn:
            conn.execute(
                "UPDATE tracked SET status = ?, notes = ?, updated_at = ? WHERE uid = ?",
                (status, notes, _now(), row["uid"]),
            )
        return dict(conn.execute(
            "SELECT rowid AS row, * FROM tracked WHERE uid = ?", (row["uid"],)
        ).fetchone())
    finally:
        conn.close()


def export_xlsx(conn: sqlite3.Connection | None = None, target: Path | None = None) -> Path:
    """Rebuild the workbook from the table (temp file, checked, then replaced)."""
    from whyline.ideas import xlsx

    destination = Path(target) if target is not None else xlsx_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    own = conn is None
    conn = conn if conn is not None else connect()
    try:
        rows = [
            [r["row"], r["company"], r["title"], r["score"], r["verdict"], r["reason"],
             r["status"], r["notes"], r["url"], r["updated_at"], r["uid"]]
            for r in (dict(x) for x in conn.execute(
                "SELECT rowid AS row, * FROM tracked"
                " ORDER BY score IS NULL, score DESC, rowid"))
        ]
    finally:
        if own:
            conn.close()
    fd, name = tempfile.mkstemp(prefix=".jobs-", suffix=".xlsx", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        xlsx._write(temporary, (("Jobs", _SHEET, rows),))
        xlsx._verify(temporary, {"Jobs": 1 + len(rows)})
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination
