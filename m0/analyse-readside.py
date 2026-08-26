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

# Collection closed when `end-readside-collection.sh` restored the real
# executable over the shim. Taken from the restored symlink's mtime
# (Aug 23 00:15:34 +05:30, truncated to the minute), so the boundary is an
# observable event rather than a date chosen afterwards.
#
# The load-bearing fact, stronger than the mtime: the shim that produced the
# *numerator* wrote its last line at 2026-08-22T18:12:48Z. After that no read
# could be logged at all, so a later session cannot score one by construction —
# counting such sessions in the denominator would be structurally invalid, not
# merely inconvenient. Without this bound the rate is 3/9 = 33%, still inside
# the 20-50% UNRELIABLE band, so the boundary does not change the published
# verdict or any precommitted action. The session dedup above does: scored per
# event it reads 12%, which crosses into a different band.
COLLECTION_CLOSED = datetime(2026, 8, 22, 18, 45, tzinfo=timezone.utc)


def parse_ts(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_sessions(ledger: Path) -> list[datetime]:
    """Start time of each DISTINCT Claude Code session, earliest event per id.

    Counting SessionStarted *events* was wrong, and wrong in the direction that
    understated the result. Claude Code's SessionStart hook fires on resume as
    well as on launch, so one long-lived session emits many events: on
    2026-08-25 the ledger held 26 events for 10 distinct sessions, 17 of them
    from a single session resumed over several days. Scored per event that gave
    3/26 = 12% and printed "THE INSTRUCTION DOES NOT FIRE", contradicting the
    published 3/7 = 43% and crossing a threshold band on nothing but how often
    one session happened to be resumed.

    A session is therefore counted once, at its earliest event, keyed by the
    `session` field the hook records.
    """
    first_seen: dict[str, datetime] = {}
    if not ledger.exists():
        return []
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
        if stamp is None:
            continue
        # Fall back to the event id when no session field exists: an older event
        # without one is its own session rather than silently merged with others.
        key = str(event.get("session") or event.get("id") or stamp.isoformat())
        if key not in first_seen or stamp < first_seen[key]:
            first_seen[key] = stamp
    # Window applied AFTER the dedup, deliberately. Filtering events first would
    # let a session that began before the window but was resumed inside it enter
    # as a new session whose "start" is really a resume — reintroducing at the
    # boundary the exact artefact this function exists to remove.
    return sorted(
        start
        for start in first_seen.values()
        if EXCLUDED_BEFORE <= start <= COLLECTION_CLOSED
    )


def load_invocations(log: Path, repo_name: str) -> list[tuple[datetime, str, str]]:
    """Returns (timestamp, subcommand, invoker). Invoker is claude / codex / human.

    Attribution matters: without it the log cannot distinguish the human running
    `whyline brief` from an agent doing so, and a human invocation inside the
    measurement window would be falsely scored as a read.
    """
    found = []
    if not log.exists():
        return found
    for line in log.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        stamp = parse_ts(parts[0])
        # Bounded at both ends for the same reason as sessions: an invocation
        # after collection closed is not part of the experiment, and counting it
        # would make the reported read counts disagree with the scored result.
        if stamp is None or not EXCLUDED_BEFORE <= stamp <= COLLECTION_CLOSED:
            continue
        if parts[2].strip() != repo_name:
            continue
        invoker = parts[3].strip() if len(parts) > 3 and parts[3].strip() else "unknown"
        found.append((stamp, parts[1].strip(), invoker))
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
    # Two log locations. The in-workspace one is authoritative for sandboxed
    # agents: Codex cannot write outside the workspace, so a $HOME-only log
    # silently recorded none of its reads.
    invocations = sorted(
        load_invocations(args.log, args.repo.name)
        + load_invocations(args.repo / ".whyline" / "readside.log", args.repo.name)
    )
    window = timedelta(minutes=args.window_minutes)

    # Only Claude Code's own invocations can score a Claude Code session.
    #
    # This previously accepted `who in ("claude", "codex")` while the denominator
    # stayed Claude-only, so any Codex read landing within the window of a Claude
    # session start credited that session. It went unnoticed until 2026-08-19,
    # when a Codex `brief` at 03:34:33 fell 30 seconds after a Claude session
    # started at 03:34:03 and pushed the reported rate from a true 50% to 75%.
    # The intent of the original filter was to exclude the *human*; excluding one
    # vendor from the other's numerator is the same requirement, missed.
    briefs = [
        stamp for stamp, sub, who in invocations if sub == "brief" and who == "claude"
    ]
    codex_briefs = [
        stamp for stamp, sub, who in invocations if sub == "brief" and who == "codex"
    ]
    human_briefs = [
        stamp for stamp, sub, who in invocations if sub == "brief" and who == "human"
    ]
    unknown_briefs = [
        stamp for stamp, sub, who in invocations if sub == "brief" and who == "unknown"
    ]
    read_sessions = [
        start
        for start in sessions
        if any(start <= stamp <= start + window for stamp in briefs)
    ]

    print(f"Repository        {args.repo}")
    print(f"Window            {args.window_minutes} min after SessionStarted")
    print(f"Collection since  {EXCLUDED_BEFORE.isoformat()}")
    print(f"Collection closed {COLLECTION_CLOSED.isoformat()} (final; later sessions not scored)")
    print()
    print(f"Claude sessions        {len(sessions)}")
    print(f"brief by Claude Code   {len(briefs)}")
    print(f"brief by Codex         {len(codex_briefs)}  (observational, no denominator)")
    print(f"brief by you (excluded) {len(human_briefs)}")
    if unknown_briefs:
        print(f"brief unattributed     {len(unknown_briefs)}  (logged before attribution existed)")
    print(f"Sessions with a read   {len(read_sessions)}")

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

    other = sorted({sub for _, sub, _ in invocations if sub != "brief"})
    if other:
        print()
        print(f"Other subcommands seen (context only): {', '.join(other)}")
    print()
    print(
        "Caveat: this rate covers Claude Code only, because SessionStarted is "
        "written by its hook alone. Codex reads are counted separately above and "
        "never score a Claude session — a Codex read that happens to fall inside "
        "a Claude session's window is not evidence that Claude read anything."
    )
    print(
        "Your own `brief` invocations are attributed and excluded automatically. "
        "What the log still cannot see is prompting — if you mentioned `brief` to "
        "an agent, strike that invocation by hand."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
