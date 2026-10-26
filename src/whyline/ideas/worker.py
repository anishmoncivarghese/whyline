"""Run the inbox from the agents scheduler.

``run_once`` is one tick: read Telegram, handle what is new, reclaim a job
whose lease expired, start at most one queued job, and send the outbox.
The job itself runs in a detached ``whyline idea work <id>`` process, the
same way a scheduled agent is detached from the tick.

A lease is the agent timeout plus 30 minutes, and it applies only while
the pid is still alive. A dead pid is reclaimed at once, whatever the
lease says, and the chat is told the Mac slept. ``timeout: none`` stores
no lease. The first time a live job runs past its lease it is queued
again. The second time a stuck job fails and the chat is told.
"""

from __future__ import annotations

import fcntl
import inspect
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

from whyline.ideas import paths, requests as assistant_requests, store

ENABLED_KEY = "enabled"
_ON = frozenset({"1", "on", "true", "yes"})
CATCH_UP = (
    "Telegram keeps undelivered updates for about 24 hours, "
    "so a tick after the Mac was off catches up."
)
LAST_TICK_KEY = "last_tick_at"
_CAFFEINATE = "/usr/bin/caffeinate"
# A gap this long is the Mac having been asleep or off, not a slow poll.
_AWAY = timedelta(minutes=10)
# analyse() budgets a quick score 15 minutes. The lease adds the half hour
# the plan allows past that, or past a brainstorm card's own timeout.
SCORE_TIMEOUT_MINUTES = 15
LEASE_MARGIN = timedelta(minutes=30)
# One start, then one retry. The third time a running job is stuck, it fails.
_MAX_STARTS = 2
_CARD_KEY = "telegram_card"
_SETTINGS_PREFIX = "telegram_settings:"
_TIMEOUTS = frozenset({15, 30, 45, 60})
_QUIET = timedelta(minutes=10)
_LOCK_NAME = "telegram-poll.lock"
# flock is per-process on macOS, so a second tick in this process would
# also obtain it. The flag makes that second tick return immediately.
_held_lock = None

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
        # The same description `whyline idea telegram setup` publishes.
        # A Telegram failure is stored for doctor and does not undo the on.
        from whyline.ideas import telegram_in

        telegram_in.publish_description(conn)
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
    clock=None,
    watch=None,
    request_spawn=None,
) -> None:
    """One scheduler pass. Returns immediately when the inbox is off.

    Idle, this is one short poll. A tap, a message, or a live job keeps
    the process long-polling until ten quiet minutes pass. A second tick
    that cannot take the lock returns without polling.

    ``now`` is the timestamp the scheduler tick started with. The awake
    loop can outlive it, so lease recovery and job start read ``clock``
    after every poll instead of reusing ``now``.
    """
    if not _database_exists():
        return
    from whyline.ideas import bot, telegram_in

    clock = clock or datetime.now
    supplied_spawn = spawn
    spawn = spawn or _spawn
    request_spawn = request_spawn or (
        spawn if supplied_spawn is not None else _spawn_request
    )
    poll = poll or telegram_in.poll_once
    handle = handle or bot.handle
    flush = flush or bot.flush_outbox
    pid_alive = pid_alive or _pid_alive
    stop = stop or _stop
    conn = store.connect()
    lock = None
    try:
        if not enabled(conn):
            return
        lock = _acquire_poll_lock()
        if lock is None:
            return
        _poll_while_in_use(
            conn,
            clock=clock,
            spawn=spawn,
            request_spawn=request_spawn,
            poll=poll,
            handle=handle,
            flush=flush,
            pid_alive=pid_alive,
            stop=stop,
            watch=watch,
        )
    finally:
        _release_poll_lock(lock)
        conn.close()


def _poll_while_in_use(
    conn,
    *,
    clock,
    spawn,
    request_spawn,
    poll,
    handle,
    flush,
    pid_alive,
    stop,
    watch=None,
) -> None:
    from whyline.agents import telegram
    from whyline.ideas import bot, telegram_in

    started = clock()
    away = _away(conn, started)
    told = False
    quiet_from = started
    first = True
    request_claimed = False
    # A row whose handler raised stays for a later tick. Retrying it on
    # every long poll would reset the quiet window and hold this lock.
    failed: set[int] = set()

    def announce(count: int) -> None:
        # Once, before this tick handles anything. The count is what this
        # tick stored. A reply already in the outbox has a smaller id;
        # flush_outbox sends the notice first because its kind is notice.
        nonlocal told
        if told:
            return
        told = True
        if away is None:
            return
        text = bot.away_text(away[0], away[1], count)
        if bot.tell_allowed(conn, text):
            flush(conn)

    try:
        while True:
            before = _kv(conn, telegram_in.LAST_ERROR_KEY)
            timeout = 25 if (_job_live(conn) or not first) else 0
            try:
                stored = _invoke_poll(poll, conn, timeout)
            except telegram.TelegramError as exc:
                telegram_in._record_poll_error(conn, "", None, str(exc))
                announce(0)
                return
            stored = int(stored or 0)
            after = _kv(conn, telegram_in.LAST_ERROR_KEY)
            announce(stored)
            if after and after != before:
                return
            handled = _handle_pending(conn, handle, failed)
            # After the poll, not the tick's original timestamp. A 25s long
            # poll, repeated while a job looks live, runs far past that instant.
            moment = clock()
            _recover(conn, moment, pid_alive, stop)
            _recover_requests(conn, moment, pid_alive, stop)
            _start_one(conn, moment, spawn)
            if not request_claimed:
                request_claimed = _start_one_request(
                    conn, moment, request_spawn
                )
            _watch(conn, watch_fn=watch)
            flush(conn)
            # ``handled`` is rows that ran. A failure is not new activity.
            activity = stored > 0 or handled > 0
            live = _job_live(conn)
            if activity or live:
                quiet_from = moment
            elif moment - quiet_from >= _QUIET:
                return
            elif first:
                return
            first = False
    finally:
        # A tick that took the lock ran, including one Telegram cut short.
        _remember_tick(conn, clock())


def _invoke_poll(poll, conn, timeout: int):
    try:
        parameters = inspect.signature(poll).parameters
    except (TypeError, ValueError):
        parameters = None
    accepts = parameters is not None and (
        "timeout" in parameters
        or any(
            item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values()
        )
    )
    if accepts:
        return poll(conn, timeout=timeout)
    try:
        return poll(conn, timeout=timeout)
    except TypeError:
        return poll(conn)


def _job_live(conn) -> bool:
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
    ).fetchone()
    if found is not None:
        row = conn.execute(
            """
            SELECT 1 FROM jobs
            WHERE state IN ('queued', 'running')
            LIMIT 1
            """
        ).fetchone()
        if row is not None:
            return True
    row = conn.execute(
        """
        SELECT 1 FROM requests
        WHERE state IN ('queued', 'running')
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def _acquire_poll_lock():
    global _held_lock
    if _held_lock is not None:
        return None
    path = paths.home() / _LOCK_NAME
    handle = path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    _held_lock = handle
    return handle


def _release_poll_lock(handle) -> None:
    global _held_lock
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    handle.close()
    if _held_lock is handle:
        _held_lock = None


def enqueue_plan(conn: sqlite3.Connection, idea_id: int, **kwargs) -> bool:
    """Queue one plan job. False when one is already queued or running."""
    from whyline.ideas import planning

    return planning.enqueue_plan(conn, idea_id, **kwargs)


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
        if job["kind"] in ("score", "brainstorm", "plan"):
            _keep_awake(os.getpid())
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
        if job["kind"] == "start":
            conn.execute(
                """
                UPDATE jobs
                SET state = 'done', lease_until = NULL, error = NULL
                WHERE id = ? AND state = 'running'
                """,
                (job_id,),
            )
        else:
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


def request(request_id: int) -> int:
    """Run one claimed assistant request in its detached process."""
    from whyline.agents import service

    conn = store.connect()
    try:
        row = conn.execute(
            "SELECT * FROM requests WHERE id = ?", (request_id,)
        ).fetchone()
        if row is None:
            print(f"no request {request_id}", file=sys.stderr)
            return 1
        if row["state"] != "running":
            print(f"request {request_id} is {row['state']}", file=sys.stderr)
            return 1
        current = _pid(row["pid"])
        if current is not None and current != os.getpid():
            return 0
        if current is None:
            claimed = conn.execute(
                """
                UPDATE requests SET pid = ?
                WHERE id = ? AND state = 'running' AND pid IS NULL
                """,
                (os.getpid(), request_id),
            )
            if claimed.rowcount != 1:
                return 0
        if row["action"] != "run_agent":
            error = f"unknown request action {row['action']}"
            assistant_requests.finish(conn, request_id, error=error)
            _notify_request(conn, row, error)
            _flush(conn)
            return 1
        name = _request_agent(row)
        if name == "agent":
            error = "run request has no saved agent name"
            assistant_requests.finish(conn, request_id, error=error)
            _notify_request(conn, row, error)
            _flush(conn)
            return 1
        try:
            record = _run_remote_agent(name)
        except Exception as exc:
            error = " ".join(str(exc).split()) or "the run did not finish"
            assistant_requests.finish(conn, request_id, error=error)
            _notify_request(conn, row, f"{name}: failed — {error}")
            _flush(conn)
            return 1
        run_id = getattr(record, "run_id", "")
        # The run ledger owns the actual private path. Keeping its stable id
        # here avoids reopening (and chmodding) that directory just to refer
        # to a result the agent service has already recorded.
        result_path = str(run_id) if run_id else None
        reason = " ".join(str(record.reason or "").split())
        outcome = str(record.outcome or "failed")
        text = f"{name}: {outcome}"
        if reason:
            text += f" — {reason}"
        if outcome.startswith("succeeded"):
            assistant_requests.finish(conn, request_id, result_path=result_path)
            code = 0
        else:
            error = _request_error(reason or outcome)
            assistant_requests.finish(
                conn, request_id, result_path=result_path, error=error
            )
            code = 1
        _notify_request(conn, row, text)
        _flush(conn)
        return code
    finally:
        conn.close()


def _request_error(detail: str) -> str:
    marker = "Enable "
    if marker in detail and " in Settings or choose another provider." in detail:
        return marker + detail.split(marker, 1)[1]
    return detail


def _run_remote_agent(name: str):
    """Run a chat request through the scheduled-agent safety boundary.

    ``service.run_now`` remains the public execution path (and therefore
    still owns history and after-run state), but its ordinary callers are
    watched, manual runs.  This detached caller first uses the scheduler's
    activation gate and forces the runner's unattended provider filtering.
    """
    from whyline.agents import deliver, runner, service

    defn = _require_remote_runnable(name)
    execute_once = runner.execute_once

    def execute_unattended(defn, **kwargs):
        kwargs["unattended"] = True
        return execute_once(defn, **kwargs)

    runner.execute_once = execute_unattended
    try:
        record = service.run_now(name, None)
    finally:
        runner.execute_once = execute_once
    # ``run_now`` currently delivers through ``after.finish`` even though it
    # suppresses the watched/manual desktop notification.  Keep the detached
    # request boundary explicit and compatible with a run_now implementation
    # that only finalizes: deliver here when it returned no delivery results.
    # A configured email, Telegram, or command delivery always contributes a
    # result, so a real delivery is never sent twice.
    if not getattr(record, "deliveries", None):
        try:
            deliver.after_run(defn, record)
        except Exception:
            pass  # configured delivery must never change the run outcome
    return record


def _require_remote_runnable(name: str):
    """Refuse remote starts that the scheduler would hold back."""
    from whyline.agents import service, state, tick

    defn = service.find(name, None)
    conn = state.connect()
    now = datetime.now().replace(microsecond=0)
    try:
        if tick._runnable(conn, defn.agent_id, now) is not None:
            return defn
        act = state.get(conn, defn.agent_id)
        status = state.status_of(conn, defn).replace("_", " ")
        if act is not None and act.backoff_until:
            try:
                backoff_until = datetime.fromisoformat(act.backoff_until)
            except ValueError:
                backoff_until = None
            if backoff_until is not None and backoff_until > now:
                raise ValueError(
                    f"{defn.label} is in backoff until "
                    f"{act.backoff_until[:16].replace('T', ' ')} after a usage limit"
                )
        raise ValueError(f"{defn.label} is {status}; it can't be run remotely")
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


def _handle_pending(conn: sqlite3.Connection, handle, failed: set[int]) -> int:
    """Run pending rows. Return how many finished without raising.

    ``failed`` holds update ids already tried this tick. A row that raises
    stays unhandled and is added there, so this tick does not call it
    again. The next tick passes a new set and tries it once more.
    """
    rows = conn.execute(
        "SELECT * FROM inbound WHERE handled = 0 ORDER BY update_id"
    ).fetchall()
    done = 0
    for row in rows:
        update_id = int(row["update_id"])
        if update_id in failed:
            continue
        try:
            handle(conn, row)
        except Exception:
            # Leave the row unhandled so a later tick tries it again, and
            # keep going so one message cannot hold the queued job.
            failed.add(update_id)
            log.exception("idea inbox could not handle update %s", update_id)
            continue
        done += 1
    return done


def _recover(conn, now: datetime, pid_alive, stop) -> None:
    rows = conn.execute(
        "SELECT * FROM jobs WHERE state = 'running' ORDER BY id"
    ).fetchall()
    for row in rows:
        if not _stuck(row, now, pid_alive):
            continue
        alive = bool(pid_alive(row["pid"]))
        if int(row["attempts"] or 0) >= _MAX_STARTS:
            _fail_expired(conn, row, stop, alive=alive)
        else:
            _requeue(conn, row, stop, slept=not alive)


def _stuck(row, now: datetime, pid_alive) -> bool:
    """True when the pid is gone, or a live one has run past its lease.

    The lease is only a limit on a process that is still running. Sleep
    and shutdown kill the pid while the lease is still in the future.
    """
    if not pid_alive(row["pid"]):
        return True
    lease = row["lease_until"]
    if not lease:
        return False
    try:
        deadline = datetime.fromisoformat(str(lease))
    except ValueError:
        return True
    return deadline <= now


def _requeue(conn, row, stop, *, slept: bool = False) -> None:
    _stop_pid(row["pid"], stop)
    conn.execute(
        """
        UPDATE jobs
        SET state = 'queued', lease_until = NULL, pid = NULL, error = NULL
        WHERE id = ? AND state = 'running'
        """,
        (row["id"],),
    )
    if slept:
        _tell(conn, int(row["idea_id"]), _sleep_message(row["kind"]))


def _fail_expired(conn, row, stop, *, alive: bool = True) -> None:
    _stop_pid(row["pid"], stop)
    # A dead pid did not run past its lease. The lease is for a live one.
    timed_out = alive and bool(row["lease_until"])
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


def _sleep_message(kind: str) -> str:
    if kind == "brainstorm":
        name = "brainstorm"
    elif kind == "score":
        name = "quick score"
    elif kind == "plan":
        name = "plan"
    elif kind == "start":
        name = "start"
    else:
        name = "job"
    return (
        f"Your {name} stopped when the Mac went to sleep or shut down; "
        "starting it again."
    )


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
    if kind == "plan":
        return "Plan"
    if kind == "start":
        return "Start"
    return "Job"


def _start_one(conn, now: datetime, spawn) -> None:
    # One running job at a time. A second tick must not start another copy
    # of a job that is still inside its lease.
    request_busy = conn.execute(
        "SELECT id FROM requests WHERE state = 'running' LIMIT 1"
    ).fetchone()
    if request_busy is not None:
        return
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

    if row["kind"] == "start":
        from whyline.ideas import run as ideas_run

        ready, reason = ideas_run.check_repo_ready(conn, int(row["idea_id"]))
        if not ready:
            return

    if row["kind"] == "plan":
        from whyline.ideas import planning

        ready, reason = planning.check_repo_ready(conn, int(row["idea_id"]))
        if not ready:
            idea = store.get(conn, int(row["idea_id"]))
            if idea is not None and idea.status != "plan_waiting":
                try:
                    idea = store.transition(
                        conn,
                        idea.id,
                        "plan_waiting",
                        expected_revision=idea.revision,
                        actor="planning",
                    )
                except (store.IllegalMove, store.StaleRevision):
                    pass
            told_key = f"plan_waiting_told:{row['idea_id']}"
            if not _kv(conn, told_key):
                _kv_set(conn, told_key, "1")
                chat_id = _chat_from_ref(idea.source_ref) if idea else None
                if chat_id is not None:
                    from whyline.ideas import bot

                    rev = idea.revision if idea else 0
                    keyboard = bot._keyboard(
                        bot.buttons_for("plan_waiting"),
                        int(row["idea_id"]),
                        rev,
                    )
                    conn.execute(
                        """
                        INSERT INTO outbox (chat_id, kind, text, buttons_json, attempts, idea_id)
                        VALUES (?, 'message', ?, ?, 0, ?)
                        """,
                        (chat_id, str(reason), json.dumps(keyboard), int(row["idea_id"])),
                    )
            return

        _kv_set(conn, f"plan_waiting_told:{row['idea_id']}", "")
        idea = store.get(conn, int(row["idea_id"]))
        if idea is not None and idea.status in {"setup_configuring", "plan_waiting"}:
            try:
                store.transition(
                    conn,
                    idea.id,
                    "planning",
                    expected_revision=idea.revision,
                    actor="planning",
                )
            except (store.IllegalMove, store.StaleRevision):
                pass
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


def _recover_requests(conn, now: datetime, pid_alive, stop) -> None:
    """Requeue request processes lost to sleep or an expired lease."""
    rows = conn.execute(
        "SELECT * FROM requests WHERE state = 'running' ORDER BY id"
    ).fetchall()
    for row in rows:
        alive = bool(pid_alive(row["pid"]))
        expired = False
        if alive and row["lease_until"]:
            try:
                expired = datetime.fromisoformat(str(row["lease_until"])) <= now
            except ValueError:
                expired = True
        if alive and not expired:
            continue
        if alive:
            _stop_pid(row["pid"], stop)
        conn.execute(
            """
            UPDATE requests
            SET state = 'queued', lease_until = NULL, pid = NULL
            WHERE id = ? AND state = 'running'
            """,
            (row["id"],),
        )
        if not alive:
            _notify_request(conn, row, "The Mac slept")


def _start_one_request(conn, now: datetime, spawn) -> bool:
    """Claim and detach one assistant request when no idea process owns the slot."""
    if conn.execute(
        "SELECT 1 FROM jobs WHERE state = 'running' LIMIT 1"
    ).fetchone() is not None:
        return False
    if conn.execute(
        "SELECT 1 FROM requests WHERE state = 'running' LIMIT 1"
    ).fetchone() is not None:
        return False
    row = conn.execute(
        "SELECT * FROM requests WHERE state = 'queued' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return False
    timeout = _request_timeout(row)
    lease = _stamp(now + timedelta(minutes=timeout) + LEASE_MARGIN)
    claimed = conn.execute(
        """
        UPDATE requests
        SET state = 'running', started_at = ?, lease_until = ?, pid = NULL
        WHERE id = ? AND state = 'queued'
        """,
        (_stamp(now), lease, row["id"]),
    )
    if claimed.rowcount != 1:
        return False
    try:
        pid = spawn(int(row["id"]))
    except Exception:
        log.exception("could not start assistant request %s", row["id"])
        conn.execute(
            """
            UPDATE requests
            SET state = 'queued', started_at = NULL, lease_until = NULL, pid = NULL
            WHERE id = ? AND state = 'running'
            """,
            (row["id"],),
        )
        return True
    if pid is not None:
        conn.execute(
            "UPDATE requests SET pid = ? WHERE id = ? AND state = 'running'",
            (int(pid), row["id"]),
        )
    _notify_request(conn, row, f"Started {_request_agent(row)}.")
    return True


def _request_agent(row) -> str:
    try:
        args = json.loads(row["args_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return "agent"
    if not isinstance(args, dict):
        return "agent"
    name = args.get("agent")
    return name if isinstance(name, str) and name else "agent"


def _request_timeout(row) -> int:
    if row["action"] != "run_agent":
        return SCORE_TIMEOUT_MINUTES
    name = _request_agent(row)
    try:
        from whyline.agents import service

        found = next(
            item
            for item in service.rows(None)
            if getattr(getattr(item, "defn", None), "name", None) == name
        )
    except Exception:
        return SCORE_TIMEOUT_MINUTES
    return int(getattr(found.defn, "timeout_minutes", SCORE_TIMEOUT_MINUTES))


def _notify_request(conn, row, text: str) -> None:
    channel = str(row["channel"] or "")
    if channel == "telegram" and row["chat_id"] is not None:
        conn.execute(
            """
            INSERT INTO outbox (chat_id, kind, text, attempts)
            VALUES (?, 'message', ?, 0)
            """,
            (int(row["chat_id"]), text),
        )
    elif channel == "email" and row["actor"]:
        from whyline.agents import mail_send

        try:
            mail_send.send([str(row["actor"])], f"Run {_request_agent(row)}", text, [])
        except Exception:
            log.exception("could not email assistant request %s", row["id"])


def _watch(conn: sqlite3.Connection, watch_fn=None) -> None:
    try:
        if watch_fn is not None:
            watch_fn(conn)
        else:
            from whyline.ideas import watch

            watch.tick(conn)
    except Exception:
        log.exception("watch tick failed")


def _job_timeout(conn, row) -> int | str:
    if row["kind"] in ("brainstorm", "plan", "start"):
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


def _away(conn, now: datetime):
    """The previous completed tick and this one, when the gap is too long."""
    raw = _kv(conn, LAST_TICK_KEY)
    if not raw:
        return None
    try:
        previous = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if now - previous > _AWAY:
        return previous, now
    return None


def _remember_tick(conn, moment: datetime) -> None:
    _kv_set(conn, LAST_TICK_KEY, _stamp(moment))


def _keep_awake(pid: int) -> None:
    """Idle-sleep waits for this job. Closing the lid still sleeps the Mac.

    ``caffeinate -i -w`` holds idle sleep until ``pid`` exits. The binary
    is missing on anything but macOS, and that is not a failed job.
    """
    if not os.path.isfile(_CAFFEINATE):
        return
    try:
        subprocess.Popen(
            [_CAFFEINATE, "-i", "-w", str(pid)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        log.warning("could not start caffeinate for pid %s", pid)


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


def _spawn_request(request_id: int) -> int:
    command = [sys.executable, "-m", "whyline", "idea", "request", str(request_id)]
    options: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
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
            raise RuntimeError(bot.score_unavailable_reason(conn))

        def on_fallback(agent, reason, nxt):
            short = str(reason).split("—", 1)[0].split(" - ", 1)[0]
            short = " ".join(short.split()) or "it failed"
            bot.edit_progress(
                conn, idea_id, f"{agent} failed ({short}); trying {nxt}…"
            )

        try:
            analyse.analyse(conn, idea_id, agents=agents, on_fallback=on_fallback)
        except analyse.AnalyseError as exc:
            bot.edit_progress(conn, idea_id, f"Quick score failed: {exc}")
            raise
        bot.edit_progress(conn, idea_id, "Quick score done ↓")
        bot.send_score(conn, idea_id)
        return
    if kind == "brainstorm":
        request = _request_for(conn, idea_id)
        disabled = brainstorm.disabled_provider(request)
        if disabled is None:
            fields = _stored_fields(conn, idea_id)
            if isinstance(fields, dict):
                disabled = brainstorm.disabled_in_fields(fields)
        if disabled:
            raise RuntimeError(
                f"Enable {disabled} in Settings or choose another provider."
            )
        if not request.models or not request.final:
            raise RuntimeError("No agent can brainstorm unattended.")
        try:
            brainstorm.run(conn, idea_id, request)
        except brainstorm.BrainstormError as exc:
            raise _AlreadyTold(str(exc)) from exc
        return
    if kind == "plan":
        from whyline.ideas import planning

        planning.run(conn, idea_id)
        return
    if kind == "start":
        from whyline.ideas import run as ideas_run

        ideas_run.run(conn, idea_id, job_id=int(job["id"]))
        return
    raise RuntimeError(f"unknown job kind {kind}")


def _request_for(conn, idea_id: int):
    from whyline.ideas import brainstorm

    fields = _stored_fields(conn, idea_id)
    if fields:
        try:
            request, notes = brainstorm.request_from_fields(fields)
        except brainstorm.SettingsError:
            request = None
        else:
            if brainstorm.disabled_provider(request) or brainstorm.disabled_in_fields(fields):
                return request
            if request.models and request.final:
                return request
            if any(" in Settings or choose another provider." in note for note in notes):
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
