"""Draft the spec and plan into a repository, with questions over Telegram."""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from whyline.console import auto_run
from whyline.ideas import store


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
    from whyline.ideas import setup

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


def extract_questions(pause: dict, root: Path | None = None) -> list[str]:
    if isinstance(pause.get("questions"), (list, tuple)):
        return [str(q).strip() for q in pause["questions"] if str(q).strip()]
    reason = str(pause.get("reason") or "")
    lines = []
    in_questions = False
    for raw_line in reason.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if "open questions:" in lower or "open questions" in lower:
            in_questions = True
            continue
        if in_questions:
            if line.startswith("Draft:"):
                break
            if line.startswith(("-", "*", "•")):
                q = line.lstrip("-*• ").strip()
                if q:
                    lines.append(q)
            elif re.match(r"^\d+[.)]\s*", line):
                q = re.sub(r"^\d+[.)]\s*", "", line).strip()
                if q:
                    lines.append(q)
            elif line:
                lines.append(line)
    if lines:
        return lines
    if reason.endswith("?") or reason.lower().startswith("question"):
        return [reason.strip()]
    return []


def enqueue_plan(
    conn: sqlite3.Connection,
    idea_id: int,
    *,
    action: str = "run",
    answer: str | None = None,
    feedback: str | None = None,
) -> bool:
    with store._txn(conn):
        payload = {"action": action, "answer": answer, "feedback": feedback}
        _kv_set(conn, f"plan_job:{idea_id}", json.dumps(payload))
        row = conn.execute(
            """
            SELECT id FROM jobs
            WHERE idea_id = ? AND kind = 'plan'
              AND state IN ('queued', 'running')
            """,
            (idea_id,),
        ).fetchone()
        if row is not None:
            return True
        conn.execute(
            """
            INSERT INTO jobs (idea_id, kind, state, attempts)
            VALUES (?, 'plan', 'queued', 0)
            """,
            (idea_id,),
        )
        return True


def run(
    conn: sqlite3.Connection,
    idea_id: int,
    *,
    run_fn=None,
    resume_fn=None,
    redraft_fn=None,
    cancel_event=None,
) -> dict | None:
    from whyline.ideas import bot, setup

    idea = store.get(conn, idea_id)
    if idea is None:
        raise LookupError(f"no idea {idea_id}")

    ready, wait_reason = check_repo_ready(conn, idea_id)
    if not ready:
        if idea.status != "plan_waiting":
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
        told_key = f"plan_waiting_told:{idea_id}"
        if not _kv(conn, told_key):
            _kv_set(conn, told_key, "1")
            chat_id = _chat_from_ref(idea.source_ref)
            if chat_id is not None:
                keyboard = bot._keyboard(
                    bot.buttons_for("plan_waiting"),
                    idea.id,
                    idea.revision,
                )
                bot._enqueue(
                    conn,
                    chat_id,
                    "message",
                    str(wait_reason),
                    buttons=keyboard,
                    idea_id=idea.id,
                )
        return None

    # Clear told key if it was set
    _kv_set(conn, f"plan_waiting_told:{idea_id}", "")

    # Retrieve payload if any
    raw_job = _kv(conn, f"plan_job:{idea_id}")
    action = "run"
    answer = None
    feedback = None
    if raw_job:
        try:
            job_data = json.loads(raw_job)
            if isinstance(job_data, dict):
                action = job_data.get("action", "run")
                answer = job_data.get("answer")
                feedback = job_data.get("feedback")
        except json.JSONDecodeError:
            pass
        _kv_set(conn, f"plan_job:{idea_id}", "")

    # Status transition
    if idea.status in {"setup_configuring", "plan_waiting"}:
        try:
            idea = store.transition(
                conn,
                idea.id,
                "planning",
                expected_revision=idea.revision,
                actor="planning",
            )
        except (store.IllegalMove, store.StaleRevision):
            pass
    elif action == "redraft" and idea.status == "plan_review":
        try:
            idea = store.transition(
                conn,
                idea.id,
                "planning",
                expected_revision=idea.revision,
                actor="planning",
            )
        except (store.IllegalMove, store.StaleRevision):
            pass

    repo_name, root = _get_repo_root(conn, idea)
    if root is None:
        raise RuntimeError(f"Repository not found for idea {idea_id}")

    try:
        req = setup.request(conn, idea_id)
        if not req.drafter or not req.reviewer or not req.agents:
            req_def, _notes = setup.defaults(conn, idea_id, repo_name, root)
            req = setup.AutoRunRequest(
                name=idea.title,
                topic=idea.original_text,
                replace=False,
                continue_paths=False,
                agents=tuple(req.agents or req_def.models),
                passes=req.passes or req_def.passes,
                final_agent=req.final_agent or req_def.final,
                timeout_minutes=req.timeout_minutes or (0 if str(req_def.timeout).lower() == "none" else int(req_def.timeout)),
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

    # Throttled progress: at most once a minute
    last_sent = [0.0]

    def on_progress(line=""):
        text = str(line).strip() if line else ""
        if not text or chat_id is None:
            return
        now = time.monotonic()
        if last_sent[0] > 0.0 and (now - last_sent[0] < 60.0):
            return
        last_sent[0] = now
        bot.edit_progress(conn, idea_id, text, chat_id=chat_id)

    synthesis_path = Path(idea.brainstorm_path) if idea.brainstorm_path else None

    # Call run / resume / redraft
    if action == "redraft":
        call_redraft = redraft_fn or auto_run.redraft_plan
        current = call_redraft(
            root,
            req,
            feedback or "",
            progress=on_progress,
        )
    elif action == "resume":
        call_resume = resume_fn or auto_run.resume
        import inspect

        kwargs: dict[str, Any] = {
            "answer": answer,
            "progress": on_progress,
            "cancel_event": cancel_event,
            "synthesis": synthesis_path,
        }
        try:
            sig = inspect.signature(call_resume)
            has_var_kw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
            if "through" in sig.parameters or has_var_kw:
                kwargs["through"] = "plan"
            if "synthesis" not in sig.parameters and not has_var_kw:
                kwargs.pop("synthesis", None)
            if "cancel_event" not in sig.parameters and not has_var_kw:
                kwargs.pop("cancel_event", None)
            if "progress" not in sig.parameters and not has_var_kw:
                kwargs.pop("progress", None)
        except (ValueError, TypeError):
            kwargs["through"] = "plan"
        current = call_resume(root, req, **kwargs)
    else:
        call_run = run_fn or auto_run.run
        dismissed = auto_run.fingerprint(root, req)
        current = call_run(
            root,
            req,
            dismissed,
            through="plan",
            synthesis=synthesis_path,
            progress=on_progress,
            cancel_event=cancel_event,
        )

    if not isinstance(current, dict):
        return None

    # Pause check must happen before phase completion check because real auto_run
    # pauses keep the current phase (e.g. "plan") and add "pause".
    if "pause" in current or current.get("phase") == "paused":
        pause = current.get("pause") if isinstance(current.get("pause"), dict) else {}
        questions = extract_questions(pause, root)
        if questions:
            # Send questions as one message and moves nothing
            text = "\n".join(questions)
            if chat_id is not None:
                bot._enqueue(conn, chat_id, "message", text, idea_id=idea.id)
                bot._set_open(conn, chat_id, {"kind": "plan_question", "idea_id": idea.id})
            return current
        else:
            # Any other pause sends its reason with Retry / Cancel
            reason = str(pause.get("reason") or "Planning paused.")
            if chat_id is not None:
                fresh = store.get(conn, idea.id) or idea
                keyboard = bot._keyboard(
                    (("Retry", "retry_plan"), ("Cancel", "cancel")),
                    fresh.id,
                    fresh.revision,
                )
                bot._enqueue(
                    conn,
                    chat_id,
                    "message",
                    reason,
                    buttons=keyboard,
                    idea_id=fresh.id,
                )
            return current

    # Check phase (when not paused)
    if current.get("phase") == "plan":
        if action == "redraft":
            plan_record = current.get("plan")
            new_plan_path = (
                plan_record.get("path")
                if isinstance(plan_record, dict)
                else current.get("plan_path")
            )
            if new_plan_path:
                store.set_paths(conn, idea.id, plan_path=str(new_plan_path))
            fresh = store.get(conn, idea.id)
            if fresh.status != "plan_review":
                try:
                    fresh = store.transition(
                        conn,
                        fresh.id,
                        "plan_review",
                        expected_revision=fresh.revision,
                        actor="planning",
                    )
                except (store.IllegalMove, store.StaleRevision):
                    pass
            keyboard = bot._keyboard(
                bot.buttons_for("plan_review"), fresh.id, fresh.revision
            )
            if chat_id is not None and new_plan_path:
                bot._enqueue(
                    conn,
                    chat_id,
                    "document",
                    "Plan",
                    buttons=keyboard,
                    document_path=str(new_plan_path),
                    idea_id=fresh.id,
                )
            return current
        else:
            spec_record = current.get("spec")
            spec_path = (
                spec_record.get("path")
                if isinstance(spec_record, dict)
                else current.get("spec_path")
            )
            plan_record = current.get("plan")
            plan_path = (
                plan_record.get("path")
                if isinstance(plan_record, dict)
                else current.get("plan_path")
            )

            store.set_paths(
                conn,
                idea.id,
                spec_path=str(spec_path) if spec_path else None,
                plan_path=str(plan_path) if plan_path else None,
            )
            fresh = store.get(conn, idea.id)
            if fresh.status != "plan_review":
                try:
                    fresh = store.transition(
                        conn,
                        fresh.id,
                        "plan_review",
                        expected_revision=fresh.revision,
                        actor="planning",
                    )
                except (store.IllegalMove, store.StaleRevision):
                    pass

            keyboard = bot._keyboard(
                bot.buttons_for("plan_review"), fresh.id, fresh.revision
            )
            if chat_id is not None:
                if spec_path:
                    bot._enqueue(
                        conn,
                        chat_id,
                        "document",
                        "Spec",
                        buttons=keyboard,
                        document_path=str(spec_path),
                        idea_id=fresh.id,
                    )
                if plan_path:
                    bot._enqueue(
                        conn,
                        chat_id,
                        "document",
                        "Plan",
                        buttons=keyboard,
                        document_path=str(plan_path),
                        idea_id=fresh.id,
                    )
            return current

    return current
