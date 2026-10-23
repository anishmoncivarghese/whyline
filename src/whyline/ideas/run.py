"""Start the relay on a confirmed tap: preflight, launch, and caffeinate."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from whyline.console import auto_run
from whyline.ideas import bot, setup, store

log = logging.getLogger(__name__)

_CAFFEINATE = "/usr/bin/caffeinate"


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


def _chat_from_ref(source_ref: str | None) -> int | None:
    if not source_ref or ":" not in source_ref:
        return None
    head, _sep, _tail = source_ref.partition(":")
    try:
        return int(head)
    except ValueError:
        return None


def _get_repo_root(conn: sqlite3.Connection, idea: store.Idea) -> tuple[str, Path | None]:
    repos = setup.list_repos(conn)
    repo_name = idea.repo or ""
    if not repo_name:
        raw = _kv(conn, f"telegram_settings:{idea.id}") or _kv(conn, "telegram_settings")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    repo_name = parsed.get("repo") or ""
            except (json.JSONDecodeError, TypeError):
                pass
    if not repo_name and len(repos) == 1:
        repo_name = next(iter(repos.keys()))

    path_str = repos.get(repo_name)
    root = Path(path_str) if path_str else None
    return repo_name, root


def check_repo_ready(conn: sqlite3.Connection, idea_id: int) -> tuple[bool, str | None]:
    idea = store.get(conn, idea_id)
    if idea is None:
        return False, "No such idea"
    repo_name, root = _get_repo_root(conn, idea)
    if root is None or not root.exists():
        return False, f"Repository not found for idea {idea_id}"

    # Check whyline_relay.running.live(root)
    try:
        from whyline_relay import running
        live_relay = running.live(root)
    except Exception:
        live_relay = None

    if live_relay is not None:
        return False, f"Waiting: a relay is running in {repo_name}"

    # Check git status --porcelain
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        stdout = proc.stdout.strip()
    except subprocess.SubprocessError as exc:
        return False, str(exc)

    if stdout:
        lines = []
        for line in stdout.splitlines():
            line_str = line.strip()
            if line_str:
                p = line_str[2:].strip()
                if " -> " in p:
                    p = p.split(" -> ")[-1].strip()
                lines.append(p)
        dirty_paths = "\n".join(lines) if lines else stdout
        return False, dirty_paths

    return True, None


def enqueue_start(conn: sqlite3.Connection, idea_id: int) -> bool:
    with store._txn(conn):
        row = conn.execute(
            """
            SELECT id FROM jobs
            WHERE idea_id = ? AND kind = 'start'
              AND state IN ('queued', 'running')
            """,
            (idea_id,),
        ).fetchone()
        if row is not None:
            return True
        conn.execute(
            """
            INSERT INTO jobs (idea_id, kind, state, attempts)
            VALUES (?, 'start', 'queued', 0)
            """,
            (idea_id,),
        )
        return True


def _record_job_pid(
    conn: sqlite3.Connection,
    idea_id: int | None,
    pid: int,
    *,
    job_id: int | None = None,
) -> None:
    with store._txn(conn):
        if job_id is not None:
            conn.execute("UPDATE jobs SET pid = ? WHERE id = ?", (pid, job_id))
        elif idea_id is not None:
            conn.execute(
                """
                UPDATE jobs SET pid = ?
                WHERE id = (
                    SELECT id FROM jobs
                    WHERE idea_id = ? AND kind = 'start'
                    ORDER BY id DESC LIMIT 1
                )
                """,
                (pid, idea_id),
            )


def _spawn_relay(root: Path, argv: list[str]) -> int:
    command = [sys.executable, "-m", "whyline", "relay", *argv]
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "cwd": str(root),
    }
    if os.name == "nt":
        options["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        options["start_new_session"] = True
    proc = subprocess.Popen(command, **options)
    return proc.pid


def keep_awake(pid: int) -> None:
    caff = _CAFFEINATE if os.path.isfile(_CAFFEINATE) else shutil.which("caffeinate")
    if not caff:
        return
    try:
        subprocess.Popen(
            [caff, "-i", "-w", str(pid)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        log.warning("could not start caffeinate for pid %s", pid)


def launch(
    argv: list[str],
    *,
    root: Path | None = None,
    conn: sqlite3.Connection | None = None,
    idea_id: int | None = None,
    job_id: int | None = None,
    spawn_fn=None,
    caffeinate_fn=None,
) -> int:
    target_root = Path(root) if root is not None else Path.cwd()
    spawner = spawn_fn or _spawn_relay
    pid = spawner(target_root, argv)
    if conn is not None and (job_id is not None or idea_id is not None):
        _record_job_pid(conn, idea_id, pid, job_id=job_id)
    awakener = caffeinate_fn or keep_awake
    awakener(pid)
    return pid


def make_launcher(
    root: Path,
    conn: sqlite3.Connection | None = None,
    idea_id: int | None = None,
    *,
    job_id: int | None = None,
    spawn_fn=None,
    caffeinate_fn=None,
):
    def _launch(argv: list[str]) -> int:
        return launch(
            argv,
            root=root,
            conn=conn,
            idea_id=idea_id,
            job_id=job_id,
            spawn_fn=spawn_fn,
            caffeinate_fn=caffeinate_fn,
        )

    return _launch


def run(
    conn: sqlite3.Connection,
    idea_id: int,
    *,
    job_id: int | None = None,
    resume_fn=None,
    launcher=None,
    spawn_fn=None,
    caffeinate_fn=None,
    cancel_event: threading.Event | None = None,
) -> dict | None:
    idea = store.get(conn, idea_id)
    if idea is None:
        raise LookupError(f"no idea {idea_id}")

    # Recheck clean tree and that no relay is live
    ready, wait_reason = check_repo_ready(conn, idea_id)
    if not ready:
        return None

    repo_name, root = _get_repo_root(conn, idea)
    if root is None or not root.exists():
        raise RuntimeError(f"Repository not found for idea {idea_id}")

    try:
        req = setup.request(conn, idea_id)
        if not req.drafter or not req.reviewer or not req.agents:
            req_def, _notes = setup.defaults(conn, idea_id, repo_name, root)
            raw = _kv(conn, f"telegram_settings:{idea_id}") or _kv(
                conn, "telegram_settings"
            )
            raw_fields = json.loads(raw) if raw else {}
            has_explicit_timeout = "timeout" in raw_fields
            if has_explicit_timeout:
                timeout_minutes = req.timeout_minutes
            else:
                timeout_minutes = (
                    0
                    if str(req_def.timeout).lower() == "none"
                    else int(req_def.timeout)
                )
            req = setup.AutoRunRequest(
                name=idea.title,
                topic=idea.original_text,
                replace=False,
                continue_paths=False,
                agents=tuple(req.agents or req_def.models),
                passes=req.passes or req_def.passes,
                final_agent=req.final_agent or req_def.final,
                timeout_minutes=timeout_minutes,
                attachments=req.attachments,
                drafter=req.drafter or req_def.drafter,
                reviewer=req.reviewer or req_def.plan_reviewer,
                implementer=req.implementer or req_def.implementer,
                tester=req.tester or req_def.tester,
                reviewer_role=req.reviewer_role or req_def.reviewer,
                release=req.release or req_def.release,
                chain=tuple(req.chain or req_def.backup),
            )
    except Exception:
        req = setup.request(conn, idea_id)

    chat_id = _chat_from_ref(idea.source_ref)

    launch_fn = launcher or make_launcher(
        root,
        conn,
        idea.id,
        job_id=job_id,
        spawn_fn=spawn_fn,
        caffeinate_fn=caffeinate_fn,
    )

    call_resume = resume_fn or auto_run.resume
    try:
        current = call_resume(root, req, launcher=launch_fn)
    except auto_run.AutoStale as exc:
        current = {"phase": "preflight", "pause": {"reason": str(exc)}}

    if not isinstance(current, dict):
        return None

    # Auto's final preflight runs first: any FAIL lines go to the chat
    # with Retry / Cancel and nothing starts.
    if "pause" in current or current.get("phase") == "preflight":
        pause = current.get("pause") if isinstance(current.get("pause"), dict) else {}
        reason = str(pause.get("reason") or "Preflight failed.")
        fail_lines = [
            line for line in reason.splitlines() if line.strip().startswith("FAIL")
        ]
        fail_text = "\n".join(fail_lines) if fail_lines else reason.strip()
        if chat_id is not None:
            fresh = store.get(conn, idea.id) or idea
            keyboard = bot._keyboard(
                (("Retry", "retry_start"), ("Cancel", "cancel")),
                fresh.id,
                fresh.revision,
            )
            bot._enqueue(
                conn,
                chat_id,
                "message",
                fail_text,
                buttons=keyboard,
                idea_id=fresh.id,
            )
        return current

    # Preflight passed and launcher was called: move to running and notify chat
    fresh = store.get(conn, idea.id) or idea
    if fresh.status != "running":
        try:
            fresh = store.transition(
                conn,
                fresh.id,
                "running",
                expected_revision=fresh.revision,
                actor="run",
                note="started",
            )
        except (store.IllegalMove, store.StaleRevision):
            fresh = store.get(conn, fresh.id) or fresh

    if chat_id is not None:
        keyboard = bot._keyboard(
            bot.buttons_for("running"),
            fresh.id,
            fresh.revision,
        )
        bot._enqueue(
            conn,
            chat_id,
            "message",
            "Started. Ask /status any time.",
            buttons=keyboard,
            idea_id=fresh.id,
        )

    return current
