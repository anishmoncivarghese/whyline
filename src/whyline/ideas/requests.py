"""Assistant requests: policy, confirmation, and the allowed state moves."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone

from whyline.ideas import actions, confirm as confirm_mod, store

LEASE_MARGIN = timedelta(minutes=30)
_COST_TIMEOUT_MINUTES = {
    "instant": 0,
    "turn": 15,
    "long": 15,
}

STATES = (
    "waiting_tap",
    "queued",
    "running",
    "done",
    "failed",
    "refused",
    "cancelled",
)

# Destinations keyed by the state the request is in. Reclaim of a dead
# or expired pid goes running → queued, then claim_next takes it again.
ALLOWED = {
    "waiting_tap": frozenset({"queued", "cancelled"}),
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"done", "failed", "queued"}),
    "done": frozenset(),
    "failed": frozenset(),
    "refused": frozenset(),
    "cancelled": frozenset(),
}

_UPDATABLE = frozenset({
    "confirmed_at",
    "started_at",
    "finished_at",
    "lease_until",
    "pid",
    "result_path",
    "error",
})


class IllegalMove(Exception):
    pass


class ConfirmError(Exception):
    pass


@dataclass(frozen=True)
class Request:
    id: int
    created_at: str | None
    channel: str | None
    actor: str | None
    chat_id: int | None
    action: str
    args_json: str
    proposed_by: str
    state: str
    approval: str
    confirmed_at: str | None
    started_at: str | None
    finished_at: str | None
    lease_until: str | None
    pid: int | None
    result_path: str | None
    error: str | None


def _request(row: sqlite3.Row) -> Request:
    return Request(**{field.name: row[field.name] for field in fields(Request)})


def _get(conn: sqlite3.Connection, request_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM requests WHERE id = ?", (request_id,)
    ).fetchone()


def _require(conn: sqlite3.Connection, request_id: int) -> sqlite3.Row:
    row = _get(conn, request_id)
    if row is None:
        raise LookupError(f"no request {request_id}")
    return row


def _move(conn: sqlite3.Connection, row: sqlite3.Row, to: str, **fields_to_set) -> Request:
    unknown = [key for key in fields_to_set if key not in _UPDATABLE]
    if unknown:
        raise TypeError(f"unknown request fields: {', '.join(sorted(unknown))}")
    current = row["state"]
    if to not in ALLOWED.get(current, frozenset()):
        raise IllegalMove(
            f"cannot move request {row['id']} from {current} to {to}"
        )
    assignments = ["state = ?"]
    values: list = [to]
    for key, value in fields_to_set.items():
        assignments.append(f"{key} = ?")
        values.append(value)
    values.append(row["id"])
    conn.execute(
        f"UPDATE requests SET {', '.join(assignments)} WHERE id = ?",
        values,
    )
    return _request(_require(conn, row["id"]))


def _moment(now) -> datetime:
    if isinstance(now, datetime):
        if now.tzinfo is None:
            return now
        return now.astimezone(timezone.utc).replace(tzinfo=None)
    parsed = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _stamp(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat(timespec="seconds")


def _pid(pid) -> int | None:
    if pid is None:
        return None
    try:
        number = int(pid)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _pid_alive(pid) -> bool:
    number = _pid(pid)
    if number is None:
        return False
    try:
        os.kill(number, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _stuck(row: sqlite3.Row, now: datetime) -> bool:
    """True when the pid is gone, or a live one has run past its lease.

    The lease is only a limit on a process that is still running. Sleep
    and shutdown kill the pid while the lease is still in the future.
    """
    if not _pid_alive(row["pid"]):
        return True
    lease = row["lease_until"]
    if not lease:
        return False
    try:
        deadline = _moment(lease)
    except ValueError:
        return True
    return deadline <= now


def _timeout_minutes(row: sqlite3.Row) -> int:
    action = actions.REGISTRY.get(row["action"])
    cost = action.cost if action is not None else "turn"
    return _COST_TIMEOUT_MINUTES.get(cost, 15)


def create(
    conn: sqlite3.Connection,
    *,
    channel: str | None,
    actor: str | None,
    chat_id: int | None,
    action: str,
    args,
    proposed_by: str,
) -> Request:
    """Store one request. Disabled actions are refused; unknown names raise."""
    if action not in actions.REGISTRY:
        raise actions.PolicyError(f"unknown action {action}")
    approval = actions.approval_for(conn, action, proposed_by=proposed_by)
    enabled = actions.policy(conn)[action]["enabled"]
    if not enabled:
        state = "refused"
        error = f"{actions.REGISTRY[action].verb} is turned off in the console"
    elif approval == "tap":
        state = "waiting_tap"
        error = None
    else:
        state = "queued"
        error = None
    args_json = json.dumps({} if args is None else args)
    actor_value = None if actor is None else str(actor)
    with store._txn(conn):
        cursor = conn.execute(
            """
            INSERT INTO requests (
              created_at, channel, actor, chat_id, action, args_json,
              proposed_by, state, approval, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                store._now(),
                channel,
                actor_value,
                chat_id,
                action,
                args_json,
                proposed_by,
                state,
                approval,
                error,
            ),
        )
        return _request(_require(conn, cursor.lastrowid))


def confirm(
    conn: sqlite3.Connection,
    request_id: int,
    code: str,
    *,
    actor: str,
) -> Request:
    """Queue a waiting request after consuming a bound confirmation code."""
    _require(conn, request_id)
    ok = confirm_mod.consume(
        conn,
        code,
        scope="request",
        subject=f"request:{request_id}",
        actor=str(actor),
    )
    if not ok:
        raise ConfirmError("this card is out of date")
    with store._txn(conn):
        row = _require(conn, request_id)
        return _move(conn, row, "queued", confirmed_at=store._now())


def cancel(conn: sqlite3.Connection, request_id: int) -> Request:
    with store._txn(conn):
        row = _require(conn, request_id)
        return _move(conn, row, "cancelled")


def claim_next(conn: sqlite3.Connection, now) -> Request | None:
    """Claim one queued request. Reclaim a dead pid even inside its lease."""
    moment = _moment(now)
    with store._txn(conn):
        running = conn.execute(
            "SELECT * FROM requests WHERE state = 'running' ORDER BY id"
        ).fetchall()
        for row in running:
            if _stuck(row, moment):
                _move(conn, row, "queued", lease_until=None, pid=None)
        busy = conn.execute(
            "SELECT id FROM requests WHERE state = 'running' LIMIT 1"
        ).fetchone()
        if busy is not None:
            return None
        row = conn.execute(
            "SELECT * FROM requests WHERE state = 'queued' ORDER BY id LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        lease = _stamp(moment + timedelta(minutes=_timeout_minutes(row)) + LEASE_MARGIN)
        return _move(
            conn,
            row,
            "running",
            lease_until=lease,
            pid=os.getpid(),
            started_at=_stamp(moment),
        )


def finish(
    conn: sqlite3.Connection,
    id: int,
    *,
    result_path: str | None = None,
    error: str | None = None,
) -> Request:
    dest = "failed" if error else "done"
    with store._txn(conn):
        row = _require(conn, id)
        return _move(
            conn,
            row,
            dest,
            result_path=result_path,
            error=error,
            finished_at=store._now(),
            lease_until=None,
            pid=None,
        )


def history(conn: sqlite3.Connection, limit: int = 50) -> list[Request]:
    rows = conn.execute(
        "SELECT * FROM requests ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_request(row) for row in rows]
