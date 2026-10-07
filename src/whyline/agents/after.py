"""What happens after each run (spec section 5): the failure streak,
backoff after usage limits, pausing after logins, one notification per run
plus one when an agent is paused or needs attention. Notifying never
changes the outcome."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from whyline import account
from whyline.agents import records, state

_FAILING = ("failed", "timed_out", "all_unavailable", "skipped")
_UNTIL = re.compile(r"until (\d{2}):(\d{2})")


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:120]
    return ""


def _earliest_reset(reason: str, now: datetime) -> datetime:
    times = []
    for hour, minute in _UNTIL.findall(reason or ""):
        hour_i, minute_i = int(hour), int(minute)
        # "until 99:99" matches the pattern and must not skip the state update.
        if hour_i > 23 or minute_i > 59:
            continue
        t = now.replace(hour=hour_i, minute=minute_i, second=0, microsecond=0)
        times.append(t if t > now else t + timedelta(days=1))
    return min(times) if times else now + timedelta(hours=3)


def _login_command(reason: str) -> str:
    for cli, argv in account.LOGIN_COMMANDS.items():
        if cli in (reason or ""):
            return " ".join(argv)
    return "log in to the CLI again"


def _notify(title: str, messages: list[str], send) -> None:
    """Send after the activation is saved. A notifier problem stops here."""
    notifier = send
    if notifier is None:
        try:
            from whyline_relay import notify as relay_notify
            notifier = relay_notify.send
        except Exception:
            return
    for body in messages:
        try:
            notifier(title, body)
        except Exception:  # a notification problem never changes the run
            pass


def finish(conn, defn, record, *, now=None, notify=True, send=None) -> None:
    now = now or datetime.now().replace(microsecond=0)
    act = state.get(conn, defn.agent_id)
    title = f"whyline · {defn.name}"
    messages = []
    changes = {"last_run_at": now.isoformat()}
    outcome = record.outcome
    if outcome.startswith("succeeded"):
        changes["consecutive_failures"] = 0
        changes["backoff_until"] = ""
        via = f" via {record.cli}"
        if record.used_backup:
            via += f" (backup; {record.used_backup['because']})"
        try:
            answer = _first_line(records.read_final(record.run_id))
        except OSError:
            answer = ""
        messages.append(f"{outcome}{via} — {answer}" if answer else f"{outcome}{via}")
    elif outcome == "login_needed":
        command = _login_command(record.reason)
        changes.update(status="paused", paused_reason=f"needs a login: {command}")
        messages.append(f"paused — needs a login: run {command}")
    elif outcome in ("usage_limit", "all_unavailable") and "usage_limit" in (record.reason or ""):
        changes["backoff_until"] = _earliest_reset(record.reason, now).isoformat()
        changes["consecutive_failures"] = (act.consecutive_failures if act else 0) + 1
        messages.append(f"{outcome} — waiting until {changes['backoff_until'][11:16]}")
    elif outcome in _FAILING:
        changes["consecutive_failures"] = (act.consecutive_failures if act else 0) + 1
        messages.append(f"{outcome} — {record.reason}" if record.reason else outcome)
    if act is not None:
        failures = changes.get("consecutive_failures", act.consecutive_failures)
        if failures >= 3 and act.status == "active" and "status" not in changes:
            changes.update(status="needs_attention", paused_reason=f"{failures} failures in a row")
            messages.append(f"needs attention — {failures} failures in a row; paused")
        state.update(conn, defn.agent_id, **changes)
    if notify:
        _notify(title, messages, send)
