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
    hidden: tuple[str, ...] = ()  # files the step writes for itself, never shown to the agent


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


def jobs_fetch(defn, run_dir: Path, now: datetime) -> int:
    """Write today's new job postings (lazy import: Jobs is optional)."""
    from whyline.jobs import step

    return step.jobs_fetch(defn, run_dir, now)


STEPS: dict[str, Step] = {
    "brief-collect": Step(brief_collect),
    "jobs-fetch": Step(jobs_fetch, skip_when_empty=True, hidden=("manifest.json",)),
}


def names() -> tuple[str, ...]:
    return ("", *STEPS)
