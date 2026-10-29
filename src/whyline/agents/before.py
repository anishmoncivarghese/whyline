"""Built-in `before` steps: a registry of named callables, never shell
commands. A step writes files into the run folder and returns how many."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Step:
    run: Callable[[object, Path, datetime], int]
    skip_when_empty: bool = False


def brief_collect(defn, run_dir: Path, now: datetime) -> int:
    """Write today.md, mail.md, tasks.md for the morning brief."""
    from whyline.ideas import brief, store

    conn = store.connect()
    try:
        calendars = brief.selected(conn)
        mailboxes = brief.mailboxes_selected(conn)
    finally:
        conn.close()
    brief.calendar(run_dir, calendars=calendars)
    brief.mail(run_dir, mailboxes=mailboxes)
    brief.reminders(run_dir)
    return 3


STEPS: dict[str, Step] = {"brief-collect": Step(brief_collect)}


def names() -> tuple[str, ...]:
    return ("", *STEPS)
