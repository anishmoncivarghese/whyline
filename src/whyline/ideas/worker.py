"""Run the inbox from the agents scheduler.

``run_once`` is one tick: read Telegram, handle what is new, reclaim a job
whose lease expired, start at most one queued job, and send the outbox.
The job itself runs in a detached ``whyline idea work <id>`` process, the
same way a scheduled agent is detached from the tick.

A lease is the agent timeout plus 30 minutes. ``timeout: none`` stores no
lease; that job is reclaimed only when its pid is gone. The first time a
lease expires the job is queued again. The second time it fails and the
chat is told.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

from whyline.ideas import paths, store

ENABLED_KEY = "enabled"
_ON = frozenset({"1", "on", "true", "yes"})
CATCH_UP = (
    "Telegram keeps undelivered updates for about 24 hours, "
    "so a tick after the Mac was off catches up."
)
# analyse() budgets a quick score 15 minutes. The lease adds the half hour
# the plan allows past that, or past a brainstorm card's own timeout.
SCORE_TIMEOUT_MINUTES = 15
LEASE_MARGIN = timedelta(minutes=30)
# One start, then one retry. The third time a running job is stuck, it fails.
_MAX_STARTS = 2
_CARD_KEY = "telegram_card"
_SETTINGS_PREFIX = "telegram_settings:"
_TIMEOUTS = frozenset({15, 30, 45, 60})

log = logging.getLogger(__name__)


class _AlreadyTold(Exception):
    """The runner already queued the chat message for this failure."""


def enabled(conn: sqlite3.Connection | None = None) -> bool:
    """True when ``whyline idea service on`` has set the flag.

    A missing database is off. Opening it here would create the inbox
    folder on every agent tick, including machines that never use it.
    """
    if conn is not None:
        return _is_on(_kv(conn, ENABLED_KEY))
    path = paths.configured_home() / "ideas.sqlite3"
    if not path.is_file():
        return False
    opened = store.connect()
    try:
        return _is_on(_kv(opened, ENABLED_KEY))
    finally:
        opened.close()


def is_on(value: object) -> bool:
    return _is_on(None if value is None else str(value))


class ServiceError(Exception):
    """The inbox could not be turned on. The message is safe to show."""


def turn_on() -> None:
    """Start the scheduler, then set kv ``enabled`` to ``on``.

    ``whyline idea service on`` and the console's Inbox screen both call
    this. The flag is written only after launchd accepts the scheduler, so
    a failed start leaves no database behind. A schema error is raised
    after the scheduler is on.
    """
    from whyline.agents import launchd

    if not launchd.supported():
        raise ServiceError(launchd.NEEDS_MACOS)
    try:
        launchd.turn_on()
    except (RuntimeError, OSError) as exc:
        raise ServiceError(str(exc)) from exc
    try:
        conn = store.connect()
    except store.SchemaError as exc:
        raise ServiceError(str(exc)) from exc
    try:
        _kv_set(conn, ENABLED_KEY, "on")
    finally:
        conn.close()


def read_kv(key: str) -> str | None:
    """One kv value, or None when the inbox database does not exist.

    ``store.connect`` would create the database. Doctor and service status
    are checks, so a machine that has no inbox stays that way.
    """
    path = paths.configured_home() / "ideas.sqlite3"
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10
        )
    except sqlite3.Error:
        return None
    try:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT value FROM kv WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.Error:
            return None
    finally:
        conn.close()
    return None if row is None else row["value"]


def telegram_error_line() -> str | None:
    """The last poll failure, or None after a poll that reached Telegram."""
    from whyline.ideas import telegram_in

    data = telegram_in.parse_last_error(read_kv(telegram_in.LAST_ERROR_KEY))
    if not data:
        return None
    message = " ".join(str(data.get("message") or "").split())
    if not message:
        return None
    at = str(data.get("at") or "").strip()
    if at:
        return f"Last Telegram error at {at}: {message}"
    return f"Last Telegram error: {message}"


def run_once(
    *,
    now: datetime | None = None,
    spawn=None,
    poll=None,
    handle=None,
    flush=None,
    pid_alive=None,
    stop=None,
) -> None:
    """One scheduler pass. Returns immediately when the inbox is off."""
    if not _database_exists():
        return
    from whyline.ideas import bot, telegram_in

    now = now or datetime.now().replace(microsecond=0)
    spawn = spawn or _spawn
    poll = poll or telegram_in.poll_once
    handle = handle or bot.handle
    flush = flush or bot.flush_outbox
    pid_alive = pid_alive or _pid_alive
    stop = stop or _stop
    conn = store.connect()
    try:
        if not enabled(conn):
            return
        poll(conn)
        _handle_pending(conn, handle)
        _recover(conn, now, pid_alive, stop)
        _start_one(conn, now, spawn)
        flush(conn)
    finally:
        conn.close()


def enqueue_brainstorm(conn: sqlite3.Connection, idea_id: int, request) -> bool:
    """Queue one brainstorm. False when one is already queued or running.

    The request is stored beside the idea so the detached process, and the
    lease, see the timeout the card confirmed.
    """
    with store._txn(conn):
        row = conn.execute(
            """
            SELECT id FROM jobs
            WHERE idea_id = ? AND kind = 'brainstorm'
              AND state IN ('queued', 'running')
            """,
            (idea_id,),
        ).fetchone()
        if row is not None:
            return False
        _kv_set(conn, f"{_SETTINGS_PREFIX}{idea_id}", json.dumps(request.as_fields()))
        conn.execute(
            """
            INSERT INTO jobs (idea_id, kind, state, attempts)
            VALUES (?, 'brainstorm', 'queued', 0)
            """,
            (idea_id,),
        )
        return True


def work(job_id: int) -> int:
    """Run the job the scheduler claimed. 0 when it finishes, 1 when it fails.

    A pid that is no longer ours means the lease was given to another
    process. This one must not overwrite that row.
    """
    from whyline.ideas import bot

    conn = store.connect()
    try:
        job = _job(conn, job_id)
        if job is None:
            print(f"no job {job_id}", file=sys.stderr)
            return 1
        if job["state"] != "running":
            print(f"job {job_id} is {job['state']}", file=sys.stderr)
            return 1
        if not _claim_pid(conn, job_id):
            return 0
        try:
            _execute(conn, job)
        except _AlreadyTold as exc:
            _mark_failed(conn, job, str(exc), tell=False)
            _flush(conn)
            return 1
        except Exception as exc:
            log.exception("idea job %s failed", job_id)
            _mark_failed(conn, job, str(exc), tell=True)
            _flush(conn)
            return 1
        conn.execute(
            """
            UPDATE jobs
            SET state = 'done', lease_until = NULL, error = NULL
            WHERE id = ? AND state = 'running' AND pid = ?
            """,
            (job_id, os.getpid()),
        )
        _publish(conn)
        _flush(conn)
        return 0
    finally:
        conn.close()


def _database_exists() -> bool:
    return (paths.configured_home() / "ideas.sqlite3").is_file()


def _is_on(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in _ON


def _kv(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def _kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _handle_pending(conn: sqlite3.Connection, handle) -> None:
    rows = conn.execute(
        "SELECT * FROM inbound WHERE handled = 0 ORDER BY update_id"
    ).fetchall()
    for row in rows:
        try:
            handle(conn, row)
        except Exception:
            # Leave the row unhandled so the next tick tries it again, and
            # keep going so one message cannot hold the queued job.
            log.exception("idea inbox could not handle update %s", row["update_id"])


def _recover(conn, now: datetime, pid_alive, stop) -> None:
    rows = conn.execute(
        "SELECT * FROM jobs WHERE state = 'running' ORDER BY id"
    ).fetchall()
    for row in rows:
        if not _stuck(row, now, pid_alive):
            continue
        if int(row["attempts"] or 0) >= _MAX_STARTS:
            _fail_expired(conn, row, stop)
        else:
            _requeue(conn, row, stop)


def _stuck(row, now: datetime, pid_alive) -> bool:
    lease = row["lease_until"]
    if lease:
        try:
            deadline = datetime.fromisoformat(str(lease))
        except ValueError:
            return True
        return deadline <= now
    return not pid_alive(row["pid"])


def _requeue(conn, row, stop) -> None:
    _stop_pid(row["pid"], stop)
    conn.execute(
        """
        UPDATE jobs
        SET state = 'queued', lease_until = NULL, pid = NULL, error = NULL
        WHERE id = ? AND state = 'running'
        """,
        (row["id"],),
    )


def _fail_expired(conn, row, stop) -> None:
    _stop_pid(row["pid"], stop)
    timed_out = bool(row["lease_until"])
    text = _lease_message(row["kind"], timed_out=timed_out)
    conn.execute(
        """
        UPDATE jobs
        SET state = 'failed', lease_until = NULL, pid = NULL, error = ?
        WHERE id = ? AND state = 'running'
        """,
        (text, row["id"]),
    )
    _tell(conn, int(row["idea_id"]), text)


def _lease_message(kind: str, *, timed_out: bool) -> str:
    reason = "it ran past its time limit" if timed_out else "it stopped before it finished"
    return (
        f"{_kind_label(kind)} failed: {reason}. "
        "It was tried again once and did not finish."
    )


def _kind_label(kind: str) -> str:
    if kind == "brainstorm":
        return "Brainstorm"
    if kind == "score":
        return "Quick score"
    return "Job"


def _start_one(conn, now: datetime, spawn) -> None:
    # One running job at a time. A second tick must not start another copy
    # of a job that is still inside its lease.
    busy = conn.execute(
        "SELECT id FROM jobs WHERE state = 'running' LIMIT 1"
    ).fetchone()
    if busy is not None:
        return
    row = conn.execute(
        "SELECT * FROM jobs WHERE state = 'queued' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return
    timeout = _job_timeout(conn, row)
    if timeout == "none":
        lease = None
    else:
        lease = _stamp(now + timedelta(minutes=int(timeout)) + LEASE_MARGIN)
    attempts = int(row["attempts"] or 0) + 1
    claimed = conn.execute(
        """
        UPDATE jobs
        SET state = 'running', lease_until = ?, attempts = ?, error = NULL, pid = NULL
        WHERE id = ? AND state = 'queued'
        """,
        (lease, attempts, row["id"]),
    )
    if claimed.rowcount != 1:
        return
    try:
        pid = spawn(int(row["id"]))
    except Exception:
        log.exception("could not start idea job %s", row["id"])
        conn.execute(
            """
            UPDATE jobs
            SET state = 'queued', lease_until = NULL, attempts = ?, pid = NULL
            WHERE id = ?
            """,
            (attempts - 1, row["id"]),
        )
        return
    if pid is not None:
        conn.execute(
            "UPDATE jobs SET pid = ? WHERE id = ?",
            (int(pid), row["id"]),
        )


def _job_timeout(conn, row) -> int | str:
    if row["kind"] == "brainstorm":
        return _brainstorm_timeout(conn, int(row["idea_id"]))
    return SCORE_TIMEOUT_MINUTES


def _brainstorm_timeout(conn, idea_id: int) -> int | str:
    found = _timeout_in(_json_object(_kv(conn, f"{_SETTINGS_PREFIX}{idea_id}")))
    if found is not None:
        return found
    card = _json_object(_kv(conn, _CARD_KEY))
    if isinstance(card, dict):
        for item in card.values():
            if not isinstance(item, dict) or item.get("idea_id") != idea_id:
                continue
            found = _timeout_in(item.get("fields"))
            if found is not None:
                return found
    return SCORE_TIMEOUT_MINUTES


def _timeout_in(data) -> int | str | None:
    if not isinstance(data, dict) or "timeout" not in data:
        return None
    return _canonical_timeout(data["timeout"])


def _canonical_timeout(value) -> int | str:
    if isinstance(value, str):
        text = value.strip().lower().removesuffix("m").strip()
        if text == "none":
            return "none"
        try:
            value = int(text)
        except ValueError:
            return SCORE_TIMEOUT_MINUTES
    if isinstance(value, int) and not isinstance(value, bool) and value in _TIMEOUTS:
        return value
    return SCORE_TIMEOUT_MINUTES


def _json_object(raw: str | None):
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed


def _stamp(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat(timespec="seconds")


def _spawn(job_id: int) -> int:
    command = [sys.executable, "-m", "whyline", "idea", "work", str(job_id)]
    options: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    # start_new_session is POSIX-only; Windows rejects it with ValueError.
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    proc = subprocess.Popen(command, **options)
    return proc.pid


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


def _stop(pid) -> None:
    number = _pid(pid)
    if number is None:
        return
    try:
        os.kill(number, signal.SIGTERM)
    except OSError:
        pass


def _stop_pid(pid, stop) -> None:
    number = _pid(pid)
    if number is None:
        return
    try:
        stop(number)
    except OSError:
        pass


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


def _job(conn, job_id: int):
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def _claim_pid(conn, job_id: int) -> bool:
    """Record this process as the owner. False when another pid already is."""
    mine = os.getpid()
    row = _job(conn, job_id)
    if row is None or row["state"] != "running":
        return False
    current = _pid(row["pid"])
    if current is not None and current != mine:
        return False
    if current == mine:
        return True
    claimed = conn.execute(
        """
        UPDATE jobs SET pid = ?
        WHERE id = ? AND state = 'running' AND pid IS NULL
        """,
        (mine, job_id),
    )
    return claimed.rowcount == 1


def _execute(conn, job) -> None:
    from whyline.ideas import analyse, bot, brainstorm

    kind = job["kind"]
    idea_id = int(job["idea_id"])
    if kind == "score":
        agents = bot.score_agents(conn)
        if not agents:
            raise RuntimeError("No agent can score unattended.")
        analyse.analyse(conn, idea_id, agents=agents)
        bot.send_score(conn, idea_id)
        return
    if kind == "brainstorm":
        request = _request_for(conn, idea_id)
        if not request.models or not request.final:
            raise RuntimeError("No agent can brainstorm unattended.")
        try:
            brainstorm.run(conn, idea_id, request)
        except brainstorm.BrainstormError as exc:
            raise _AlreadyTold(str(exc)) from exc
        return
    raise RuntimeError(f"unknown job kind {kind}")


def _request_for(conn, idea_id: int):
    from whyline.ideas import brainstorm

    fields = _stored_fields(conn, idea_id)
    if fields:
        try:
            request, _notes = brainstorm.request_from_fields(fields)
        except brainstorm.SettingsError:
            request = None
        else:
            if request.models and request.final:
                return request
    request, _notes = brainstorm.defaults(conn)
    return request


def _stored_fields(conn, idea_id: int) -> dict:
    parsed = _json_object(_kv(conn, f"{_SETTINGS_PREFIX}{idea_id}"))
    if isinstance(parsed, dict) and parsed:
        return parsed
    card = _json_object(_kv(conn, _CARD_KEY))
    if not isinstance(card, dict):
        return {}
    for item in card.values():
        if not isinstance(item, dict) or item.get("idea_id") != idea_id:
            continue
        fields = item.get("fields")
        if isinstance(fields, dict):
            return fields
    return {}


def _mark_failed(conn, job, detail: str, *, tell: bool) -> None:
    text = _failure_text(job["kind"], detail)
    updated = conn.execute(
        """
        UPDATE jobs
        SET state = 'failed', lease_until = NULL, error = ?
        WHERE id = ? AND state = 'running' AND pid = ?
        """,
        (text, job["id"], os.getpid()),
    )
    if updated.rowcount == 1 and tell:
        _tell(conn, int(job["idea_id"]), text)


def _failure_text(kind: str, detail: str) -> str:
    text = " ".join(str(detail).split()) or "it did not finish"
    if len(text) > 500:
        text = text[:500]
    return f"{_kind_label(kind)} failed: {text}"


def _tell(conn, idea_id: int, text: str) -> None:
    idea = store.get(conn, idea_id)
    if idea is None:
        return
    chat_id = _chat_from_ref(idea.source_ref)
    if chat_id is None:
        return
    conn.execute(
        """
        INSERT INTO outbox (chat_id, kind, text, attempts, idea_id)
        VALUES (?, 'message', ?, 0, ?)
        """,
        (chat_id, text, idea_id),
    )


def _chat_from_ref(source_ref: str | None) -> int | None:
    if not source_ref or ":" not in source_ref:
        return None
    head, _sep, _tail = source_ref.partition(":")
    try:
        return int(head)
    except ValueError:
        return None


def _publish(conn) -> None:
    from whyline.ideas import xlsx

    try:
        xlsx.export(conn)
    except OSError:
        log.exception("could not write the ideas workbook")


def _flush(conn) -> None:
    from whyline.ideas import bot

    try:
        bot.flush_outbox(conn)
    except Exception:
        log.exception("could not send the idea outbox")
