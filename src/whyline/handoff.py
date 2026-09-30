"""Explicit, checkout-local active-task handoffs.

A handoff used to stay "active" forever: an approved FC-3 handoff many
commits behind HEAD kept heading every `sync` and even became the default
task that narrowed decision selection. A handoff can now be closed
explicitly, and one whose work is plainly finished is treated as settled.
"""

from __future__ import annotations

from pathlib import Path

from whyline import decisions, events, gitq, ledger, paths, state


def parse_test(value: str) -> dict[str, str]:
    """Parse ``COMMAND: RESULT`` using the final colon as the separator."""
    command, separator, result = value.rpartition(":")
    if not separator:
        return {"command": decisions.one_line(value), "result": ""}
    return {
        "command": decisions.one_line(command),
        "result": decisions.one_line(result),
    }


def load(root: Path) -> dict | None:
    return state.load_object(paths.active_handoff_path(root))


def create(
    root: Path,
    *,
    task: str,
    from_actor: str,
    to_actor: str,
    status: str,
    summary: str = "",
    files: list[str] | None = None,
    tests: list[dict] | None = None,
    risks: list[str] | None = None,
    questions: list[str] | None = None,
    base_commit: str | None = None,
    current_commit: str | None = None,
) -> dict:
    """Create a Handoff event and replace the active record atomically."""
    changed = gitq.changed_paths(root)
    head = gitq.head_commit(root)
    record = events.new_event(
        events.HANDOFF,
        task=decisions.one_line(task),
        from_actor=decisions.one_line(from_actor),
        to_actor=decisions.one_line(to_actor),
        status=decisions.one_line(status),
        summary=decisions.one_line(summary),
        files=sorted({decisions.one_line(path) for path in (files or changed)}),
        tests=[
            {
                "command": decisions.one_line(item.get("command", "")),
                "result": decisions.one_line(item.get("result", "")),
            }
            for item in (tests or [])
        ],
        risks=[decisions.one_line(value) for value in (risks or [])],
        questions=[decisions.one_line(value) for value in (questions or [])],
        base_commit=decisions.one_line(head if base_commit is None else base_commit),
        current_commit=decisions.one_line(
            head if current_commit is None else current_commit
        ),
        dirty=bool(changed),
    )
    state.atomic_write_json(paths.active_handoff_path(root), record)
    ledger.append(paths.ledger_path(root), record)
    return record


# Statuses that mean the handed-off work is finished. Compared lowercased.
TERMINAL_STATUSES = frozenset(
    {"approved", "completed", "complete", "done", "merged", "cancelled", "canceled", "closed"}
)


def finished_tasks(ledger_events: list[dict]) -> dict[str, str]:
    """Task -> when it was last recorded as finished: a handoff with a
    terminal status, or an explicit close. Used to retire ownership claims
    on evidence rather than age alone."""
    finished: dict[str, str] = {}
    for event in ledger_events:
        kind = event.get("type")
        terminal = kind == events.HANDOFF_CLOSED or (
            kind == events.HANDOFF
            and str(event.get("status", "")).strip().lower() in TERMINAL_STATUSES
        )
        task, ts = event.get("task"), event.get("ts")
        if terminal and isinstance(task, str) and task and isinstance(ts, str):
            if ts > finished.get(task, ""):
                finished[task] = ts
    return finished


def close(root: Path, *, status: str = "completed", summary: str = "") -> dict | None:
    """Mark the active handoff closed; None if there is none or it already is.

    whyline-relay reads active-handoff.json and routes on its `id`,
    `status` and `to_actor`, so those stay exactly as they were -- closing
    must not read as a new handoff. The closure is recorded alongside them
    and as its own ledger event.
    """
    with state.file_lock(paths.active_handoff_path(root)):
        active = load(root)
        if not active or active.get("closed"):
            return None
        event = events.new_event(
            events.HANDOFF_CLOSED,
            closes=active.get("id", ""),
            task=active.get("task", ""),
            status=decisions.one_line(status),
            summary=decisions.one_line(summary),
        )
        closed = {
            **active,
            "closed": True,
            "closed_at": event["ts"],
            "closed_status": event["status"],
            "closed_summary": event["summary"],
        }
        state.atomic_write_json(paths.active_handoff_path(root), closed)
    ledger.append(paths.ledger_path(root), event)
    return closed


def settled(root: Path, record: dict | None) -> dict | None:
    """Why `record` no longer describes current work, or None if it may.

    Closed handoffs are settled. So is one whose status is terminal *and*
    whose recorded commit HEAD has since moved past -- the work was finished
    and more has happened since. A terminal handoff still at HEAD is not:
    that is the moment right after approval, when it is still the news. An
    unknown commit is never taken as proof of anything.
    """
    if not record:
        return None
    if record.get("closed"):
        return {"reason": "closed"}
    if str(record.get("status", "")).strip().lower() not in TERMINAL_STATUSES:
        return None
    behind = gitq.commits_behind(root, str(record.get("current_commit") or ""))
    if not behind:
        return None
    return {"reason": "behind", "commits_behind": behind}


def format_text(record: dict) -> str:
    lines = [
        f"Handoff        {record.get('task', '')}",
        f"From / to      {record.get('from_actor', '')} -> {record.get('to_actor', '')}",
        f"Status         {record.get('status', '')}",
    ]
    if record.get("summary"):
        lines.append(f"Summary        {record['summary']}")
    if record.get("files"):
        lines.append(f"Files          {', '.join(record['files'])}")
    for test in record.get("tests") or []:
        lines.append(f"Test           {test.get('command', '')}: {test.get('result', '')}")
    for risk in record.get("risks") or []:
        lines.append(f"Risk           {risk}")
    for question in record.get("questions") or []:
        lines.append(f"Question       {question}")
    lines.append(f"Base           {record.get('base_commit', '') or '(no commit)'}")
    lines.append(f"Current        {record.get('current_commit', '') or '(no commit)'}")
    lines.append(f"Working tree   {'dirty' if record.get('dirty') else 'clean'}")
    return "\n".join(lines)
