"""Explicit, checkout-local active-task handoffs."""

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
