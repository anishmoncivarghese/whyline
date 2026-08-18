#!/usr/bin/env python3
"""Score the read-side check against thresholds fixed before collection.

Deliberately mechanical. M0's weakness was that "unprompted" was never recorded
as data, so it had to be reconstructed by hand from timestamp clustering. This
computes the number instead, and refuses to guess where it cannot.

Usage:
    python3 m0/analyse-readside.py [--repo /Users/anish/CodeGraph]
                                   [--log ~/.whyline-readside.log]
                                   [--window-minutes 10]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Fixed 2026-08-18, before collection. See READ-SIDE-PROTOCOL.md.
THRESHOLD_FIRES = 0.50
THRESHOLD_UNRELIABLE = 0.20

# The controller's own smoke tests while installing the instrument.
EXCLUDED_BEFORE = datetime(2026, 8, 18, 5, 0, tzinfo=timezone.utc)


def parse_ts(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_sessions(ledger: Path) -> list[datetime]:
    """SessionStarted timestamps. Only the Claude Code hook writes these."""
    starts = []
    if not ledger.exists():
        return starts
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "SessionStarted":
            continue
        stamp = parse_ts(str(event.get("ts", "")))
        if stamp and stamp >= EXCLUDED_BEFORE:
            starts.append(stamp)
    return sorted(starts)


def load_invocations(log: Path, repo_name: str) -> list[tuple[datetime, str]]:
    found = []
    if not log.exists():
        return found
    for line in log.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        stamp = parse_ts(parts[0])
        if stamp is None or stamp < EXCLUDED_BEFORE:
            continue
        if parts[2].strip() != repo_name:
            continue
        found.append((stamp, parts[1].strip()))
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("/Users/anish/CodeGraph"))
    parser.add_argument(
        "--log", type=Path, default=Path.home() / ".whyline-readside.log"
    )
    parser.add_argument("--window-minutes", type=int, default=10)
    args = parser.parse_args()

    sessions = load_sessions(args.repo / ".whyline" / "ledger.jsonl")
    invocations = load_invocations(args.log, args.repo.name)
    window = timedelta(minutes=args.window_minutes)

    briefs = [stamp for stamp, sub in invocations if sub == "brief"]
    read_sessions = [
        start
        for start in sessions
        if any(start <= stamp <= start + window for stamp in briefs)
    ]

    print(f"Repository        {args.repo}")
    print(f"Window            {args.window_minutes} min after SessionStarted")
    print(f"Collection since  {EXCLUDED_BEFORE.isoformat()}")
    print()
    print(f"Claude sessions   {len(sessions)}")
    print(f"brief invocations {len(briefs)}")
    print(f"Sessions with a read  {len(read_sessions)}")

    if not sessions:
        print()
        print("No sessions recorded yet. Nothing to score — keep working normally.")
        return 0

    rate = len(read_sessions) / len(sessions)
    print(f"Unprompted read rate  {rate:.0%}")
    print()

    if rate >= THRESHOLD_FIRES:
        verdict = (
            "THE INSTRUCTION FIRES. Lead the README with `brief`; the four-part "
            "instruction shape is validated for the read direction too."
        )
    elif rate >= THRESHOLD_UNRELIABLE:
        verdict = (
            "UNRELIABLE. Lead with `run`, keep `brief` as a documented manual "
            "command, and say plainly that agents read it inconsistently."
        )
    else:
        verdict = (
            "THE INSTRUCTION DOES NOT FIRE. `run` becomes the only supported "
            "handoff path; remove the read half of the AGENTS.md instruction "
            "rather than ship an instruction that does nothing."
        )
    print(f"Verdict: {verdict}")

    other = sorted({sub for _, sub in invocations if sub != "brief"})
    if other:
        print()
        print(f"Other subcommands seen (context only): {', '.join(other)}")
    print()
    print(
        "Caveat: this rate covers Claude Code only, because SessionStarted is "
        "written by its hook alone. Codex reads appear in the invocation count "
        "but have no denominator, so they are observational."
    )
    print(
        "Any `brief` that followed a human mentioning it must be excluded by "
        "hand — the log cannot see prompting."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
