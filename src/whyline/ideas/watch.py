"""Watch running or paused ideas: relay state, pause alerts, status, and stop."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from whyline.agents import telegram
from whyline.console import auto_run
from whyline.ideas import bot, run, setup, store

log = logging.getLogger(__name__)


def _kv(conn: store.sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def _kv_set(conn: store.sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def count_commits_since_start(root: Path, base_commit: str | None) -> int:
    if not base_commit:
        return 0
    try:
        proc = subprocess.run(
            ["git", "rev-list", "--count", f"{base_commit}..HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return int(proc.stdout.strip())
    except Exception:
        return 0


def get_time_taken(
    conn: store.sqlite3.Connection,
    idea_id: int,
    now: datetime | None = None,
) -> str:
    row = conn.execute(
        """
        SELECT at FROM events
        WHERE idea_id = ? AND to_status = 'running'
        ORDER BY id ASC LIMIT 1
        """,
        (idea_id,),
    ).fetchone()
    if row is None:
        return "unknown"
    try:
        from whyline_relay import agents as relay_agents

        started_dt = datetime.fromisoformat(row["at"])
        current_dt = now or (
            datetime.now(started_dt.tzinfo) if started_dt.tzinfo else datetime.now()
        )
        elapsed_sec = max(0.0, (current_dt - started_dt).total_seconds())
        return relay_agents.format_duration(elapsed_sec)
    except Exception:
        return "unknown"


def format_elapsed(started_str: str, now: datetime | None = None) -> str:
    try:
        from whyline_relay import agents as relay_agents

        started = datetime.fromisoformat(started_str)
        current = now or (
            datetime.now(started.tzinfo) if started.tzinfo else datetime.now()
        )
        elapsed_sec = max(0.0, (current - started).total_seconds())
        return relay_agents.format_duration(elapsed_sec)
    except Exception:
        return started_str


def read_log_snippet(
    root: Path | None,
    live: Any | None,
    saved: Any | None,
    *,
    token: str | None = None,
    lines_count: int = 5,
) -> list[str]:
    lp: Path | None = None
    if root is not None:
        if live is not None:
            try:
                from whyline_relay import loop as relay_loop

                lp = relay_loop.log_path(
                    root, live.task, live.round, live.agent, live.role
                )
            except Exception:
                pass
        if (lp is None or not lp.is_file()) and saved is not None and saved.log_path:
            p = Path(saved.log_path)
            lp = p if p.is_absolute() else root / saved.log_path

    if lp is None or not lp.is_file():
        return []

    try:
        raw_text = lp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    all_lines = raw_text.splitlines()
    tail = all_lines[-lines_count:] if len(all_lines) >= lines_count else all_lines
    effective_token = token if token is not None else telegram.token_get()
    return [telegram.redact(line, effective_token) for line in tail]


def find_idea_for_status(
    conn: store.sqlite3.Connection,
    *,
    chat_id: int | None = None,
    idea_id: int | None = None,
) -> store.Idea | None:
    if idea_id is not None:
        return store.get(conn, idea_id)
    if chat_id is not None:
        row = conn.execute(
            """
            SELECT id FROM ideas
            WHERE status IN ('running', 'paused')
              AND source = 'telegram' AND source_ref LIKE ?
            ORDER BY id DESC LIMIT 1
            """,
            (f"{int(chat_id)}:%",),
        ).fetchone()
        if row is not None:
            return store.get(conn, int(row["id"]))
    row = conn.execute(
        """
        SELECT id FROM ideas
        WHERE status IN ('running', 'paused')
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    if row is not None:
        return store.get(conn, int(row["id"]))
    if chat_id is not None:
        row = conn.execute(
            """
            SELECT id FROM ideas
            WHERE source = 'telegram' AND source_ref LIKE ?
            ORDER BY id DESC LIMIT 1
            """,
            (f"{int(chat_id)}:%",),
        ).fetchone()
        if row is not None:
            return store.get(conn, int(row["id"]))
    row = conn.execute("SELECT id FROM ideas ORDER BY id DESC LIMIT 1").fetchone()
    if row is not None:
        return store.get(conn, int(row["id"]))
    return None


def build_status(
    conn: store.sqlite3.Connection,
    idea: store.Idea,
    *,
    root: Path | None = None,
    token: str | None = None,
    now: datetime | None = None,
) -> tuple[str, list[tuple[str, str]]]:
    if root is None:
        _repo_name, root = run._get_repo_root(conn, idea)

    saved = None
    live = None
    if root is not None and root.exists():
        try:
            from whyline_relay import state as relay_state

            saved = relay_state.load(root)
        except Exception:
            saved = None
        try:
            from whyline_relay import running as relay_running

            live = relay_running.live(root)
        except Exception:
            live = None

    plan_name = None
    plan_path = None
    if saved and saved.plan:
        p = Path(saved.plan)
        plan_name = p.name
        plan_path = p if p.is_absolute() else (root / saved.plan if root else None)
    elif idea.plan_path:
        p = Path(idea.plan_path)
        plan_name = p.name
        plan_path = p if p.is_absolute() else (root / idea.plan_path if root else None)
    else:
        plan_name = idea.title or f"idea {idea.id}"

    tasks_done = 0
    tasks_total = 0
    if plan_path and plan_path.is_file():
        try:
            from whyline_relay import plan as relay_plan

            content = plan_path.read_text(encoding="utf-8")
            tasks = relay_plan.parse(content)
            tasks_total = len(tasks)
            tasks_done = sum(1 for t in tasks if t.checked)
        except Exception:
            pass

    task_id = (
        (saved.task_id if saved and saved.task_id else "")
        or (live.task if live else "")
        or "(none)"
    )
    stage = (saved.stage if saved and saved.stage else "") or ""

    round_num = (live.round if live else None) or (saved.round if saved else None) or 1

    if live is not None:
        how_long = format_elapsed(live.started, now=now)
        agent_str = f"{live.agent} ({how_long})"
    elif idea.status == "paused" and saved and saved.paused_reason:
        agent_str = f"None (paused: {saved.paused_reason})"
    elif idea.status == "stopped":
        agent_str = "None (stopped)"
    else:
        agent_str = "None"

    log_lines = read_log_snippet(root, live, saved, token=token, lines_count=5)

    stage_part = f" ({stage})" if stage and stage != "(none)" else ""
    lines = [
        f"Plan: {plan_name}",
        f"Tasks: {tasks_done} of {tasks_total}",
        f"Task: {task_id}{stage_part}",
        f"Round: {round_num}",
        f"Agent: {agent_str}",
    ]
    if log_lines:
        lines.append("Log:")
        lines.extend(log_lines)

    text = "\n".join(lines)
    buttons = [("Stop", "stop"), ("Refresh", "refresh")]
    return text, buttons


def stop_relay(root: Path, *, runner=None) -> None:
    if runner is not None:
        runner(["whyline", "relay", "stop"], cwd=root)
    else:
        try:
            subprocess.run(
                ["whyline", "relay", "stop"],
                cwd=root,
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            subprocess.run(
                [sys.executable, "-m", "whyline", "relay", "stop"],
                cwd=root,
                check=False,
                capture_output=True,
            )
    auto_run.stop(root)


def resume_relay(
    root: Path,
    idea_id: int,
    conn: store.sqlite3.Connection,
    *,
    launcher=None,
    spawn_fn=None,
    caffeinate_fn=None,
) -> str:
    from whyline.console import recovery
    from whyline.ideas import run as ideas_run

    launch = launcher or ideas_run.make_launcher(
        root, conn, idea_id, spawn_fn=spawn_fn, caffeinate_fn=caffeinate_fn
    )
    problem = recovery.Problem(
        id="stopped",
        summary="Relay stopped",
        evidence=[],
        options=[
            recovery.Option(
                "resume",
                "Resume",
                "run whyline relay resume",
                recommended=True,
                confirm=False,
            )
        ],
    )
    res = recovery.apply(root, problem, "resume", launch)
    return str(res)


def handle_resolve(
    conn: store.sqlite3.Connection,
    idea: store.Idea,
    option_id: str,
    *,
    confirmed: bool = False,
    launcher=None,
    spawn_fn=None,
    caffeinate_fn=None,
) -> tuple[str, store.Idea, bool, str | None]:
    from whyline.console import recovery
    from whyline.ideas import run as ideas_run

    repo_name, root = ideas_run._get_repo_root(conn, idea)
    if root is None or not root.exists():
        return ("Repository not found.", idea, False, None)

    saved = None
    try:
        from whyline_relay import state as relay_state

        saved = relay_state.load(root)
    except Exception:
        pass
    paused_reason = saved.paused_reason if saved else ""
    problems = recovery.diagnose(root, [], paused_reason)
    if not problems:
        return ("No problem diagnosed.", idea, False, None)

    problem = problems[0]
    matched_opt = next((o for o in problem.options if o.id == option_id), None)
    if matched_opt is None:
        return (f"Option {option_id} is no longer available.", idea, False, None)

    if matched_opt.confirm and not confirmed:
        return (f"Confirm {matched_opt.label}?", idea, True, matched_opt.label)

    launch = launcher or ideas_run.make_launcher(
        root, conn, idea.id, spawn_fn=spawn_fn, caffeinate_fn=caffeinate_fn
    )
    result = recovery.apply(root, problem, option_id, launch)
    result_str = str(result)

    resumed = (
        option_id
        in (
            "resume",
            "resume-longer",
            "resume-keep",
            "reset-keep",
            "move-aside",
            "retry-stage",
        )
        or option_id.startswith("use-")
        or "resume" in result_str.lower()
    )
    fresh = idea
    if resumed and fresh.status == "paused":
        try:
            fresh = store.transition(
                conn,
                fresh.id,
                "running",
                expected_revision=fresh.revision,
                actor="recovery",
                note=f"applied {option_id}",
            )
        except (store.IllegalMove, store.StaleRevision):
            fresh = store.get(conn, fresh.id) or fresh

    if option_id == "stop" and fresh.status in ("running", "paused"):
        try:
            fresh = store.transition(
                conn,
                fresh.id,
                "stopped",
                expected_revision=fresh.revision,
                actor="recovery",
                note="applied stop",
            )
        except (store.IllegalMove, store.StaleRevision):
            fresh = store.get(conn, fresh.id) or fresh

    return (result_str, fresh, False, None)


def tick(
    conn: store.sqlite3.Connection,
    *,
    clock=None,
    spawn_fn=None,
    caffeinate_fn=None,
) -> list[int]:
    ideas = [
        i
        for s in ("running", "paused")
        for i in store.list_ideas(conn, status=s)
    ]
    acted_ideas: list[int] = []
    for idea in ideas:
        repo_name, root = run._get_repo_root(conn, idea)
        if root is None or not root.exists():
            continue

        saved = None
        try:
            from whyline_relay import state as relay_state

            saved = relay_state.load(root)
        except Exception:
            saved = None

        live = None
        try:
            from whyline_relay import running as relay_running

            live = relay_running.live(root)
        except Exception:
            live = None

        plan_path = None
        if saved and saved.plan:
            p = Path(saved.plan)
            plan_path = p if p.is_absolute() else root / saved.plan
        elif idea.plan_path:
            p = Path(idea.plan_path)
            plan_path = p if p.is_absolute() else root / idea.plan_path

        tasks = []
        if plan_path and plan_path.is_file():
            try:
                from whyline_relay import plan as relay_plan

                content = plan_path.read_text(encoding="utf-8")
                tasks = relay_plan.parse(content)
            except Exception:
                pass

        # 1. Done check:
        # Every checkbox in the plan is ticked and no relay is live
        if tasks and all(t.checked for t in tasks) and live is None:
            fresh = idea
            if fresh.status == "paused":
                try:
                    fresh = store.transition(
                        conn,
                        fresh.id,
                        "running",
                        expected_revision=fresh.revision,
                        actor="watch",
                        note="resumed before done",
                    )
                except (store.IllegalMove, store.StaleRevision):
                    fresh = store.get(conn, fresh.id) or fresh
            if fresh.status == "running":
                try:
                    fresh = store.transition(
                        conn,
                        fresh.id,
                        "done",
                        expected_revision=fresh.revision,
                        actor="watch",
                        note="all tasks done",
                    )
                except (store.IllegalMove, store.StaleRevision):
                    fresh = store.get(conn, fresh.id) or fresh

            commit_count = count_commits_since_start(
                root, saved.base_commit if saved else None
            )
            now_dt = clock() if clock else datetime.now()
            time_taken = get_time_taken(conn, fresh.id, now=now_dt)
            summary = (
                f"Finished {fresh.title or f'idea {fresh.id}'}!\n"
                f"Tasks: {len(tasks)}\n"
                f"Commits: {commit_count}\n"
                f"Time taken: {time_taken}"
            )
            chat_id = run._chat_from_ref(fresh.source_ref)
            if chat_id is not None and plan_path and plan_path.is_file():
                bot._enqueue(
                    conn,
                    chat_id,
                    "document",
                    summary,
                    document_path=str(plan_path),
                    idea_id=fresh.id,
                )
            acted_ideas.append(fresh.id)
            continue

        # 2. Pause alert check:
        paused_reason = saved.paused_reason if saved else ""
        if paused_reason:
            last_reason = _kv(conn, f"paused_reason:{idea.id}")
            if last_reason != paused_reason:
                _kv_set(conn, f"paused_reason:{idea.id}", paused_reason)
                fresh = idea
                if fresh.status != "paused":
                    try:
                        fresh = store.transition(
                            conn,
                            fresh.id,
                            "paused",
                            expected_revision=fresh.revision,
                            actor="watch",
                            note="paused",
                        )
                    except (store.IllegalMove, store.StaleRevision):
                        fresh = store.get(conn, fresh.id) or fresh

                task_id = saved.task_id if saved else ""
                paused_task = None
                if tasks and task_id:
                    from whyline_relay import plan as relay_plan

                    paused_task = relay_plan.find(tasks, task_id)

                is_release = (
                    (paused_task is not None and paused_task.profile == "release")
                    or (saved is not None and saved.profile == "release")
                )

                log_path_str = saved.log_path if saved and saved.log_path else ""
                if is_release:
                    lines = [
                        "Release is yours: run it from the console",
                        f"Task: {task_id}",
                    ]
                    if log_path_str:
                        lines.append(f"Log: {log_path_str}")
                    alert_text = "\n".join(lines)
                else:
                    lines = [
                        f"{paused_reason}",
                        f"Task: {task_id}",
                    ]
                    if log_path_str:
                        lines.append(f"Log: {log_path_str}")
                    alert_text = "\n".join(lines)

                from whyline.console import recovery

                problems = recovery.diagnose(root, [], paused_reason)
                first_problem = problems[0] if problems else None

                raw_options = first_problem.options if first_problem else []
                filtered_options = [
                    opt for opt in raw_options if opt.id not in ("show", "cancel")
                ]
                if is_release:
                    filtered_options = [
                        opt
                        for opt in filtered_options
                        if "publish" not in opt.id.lower()
                        and "publish" not in opt.label.lower()
                    ]

                ordered_options = sorted(
                    filtered_options, key=lambda o: not o.recommended
                )
                buttons = []
                for opt in ordered_options:
                    label = f"★ {opt.label}" if opt.recommended else opt.label
                    buttons.append((label, f"resolve_{opt.id}"))
                buttons.append(("Show evidence", "evidence"))

                chat_id = run._chat_from_ref(fresh.source_ref)
                if chat_id is not None:
                    keyboard = bot._keyboard(buttons, fresh.id, fresh.revision)
                    bot._enqueue(
                        conn,
                        chat_id,
                        "message",
                        alert_text,
                        buttons=keyboard,
                        idea_id=fresh.id,
                    )
                acted_ideas.append(fresh.id)
        else:
            last_reason = _kv(conn, f"paused_reason:{idea.id}")
            if last_reason:
                _kv_set(conn, f"paused_reason:{idea.id}", "")

    return acted_ideas
