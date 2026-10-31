"""Handlers for the steps that pause a run: wait (a timer) and approval (a person)."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from whyline.workflows import state
from whyline.workflows.steps.basic import _render

DEFAULT_EXPIRES_HOURS = 24


def _result(*args, **kwargs):
    from whyline.workflows.engine import StepResult
    return StepResult(*args, **kwargs)


def _next_clock_time(now: datetime, text: str) -> datetime:
    """The next local time of day ``HH:MM``: today if still ahead, else tomorrow."""
    hour, minute = (int(part) for part in text.split(":"))
    local = now.astimezone()
    target = datetime.combine(local.date(), time(hour, minute))  # naive local wall time
    if target.astimezone() <= now:
        target += timedelta(days=1)
    return target.astimezone()


def run_wait(ctx, step):
    if step.id in ctx.resumed:
        recorded = ctx.resumed[step.id]
        due = datetime.fromisoformat(recorded) if recorded else None
        if due is not None and ctx.now < due:  # woken early: keep waiting
            return _result("waiting", {"wake_at": recorded}, reason="timer", wake_at=due)
        return _result("succeeded", {"waited": True})
    fields = step.fields
    if "minutes" in fields:
        wake = ctx.now + timedelta(minutes=int(fields["minutes"]))
    else:
        wake = _next_clock_time(ctx.now, fields["until"])
    return _result("waiting", {"wake_at": wake.isoformat(timespec="seconds")},
                   reason="timer", wake_at=wake)


def run_approval(ctx, step):
    from whyline.workflows.engine import _stamp
    conn = state.connect()
    run_id = ctx.run["id"]
    row = state.latest_approval(conn, run_id, step.id)
    if row is None:
        hours = int(step.fields.get("expires_hours") or DEFAULT_EXPIRES_HOURS)
        row = state.create_approval(
            conn, run_id, step.id, revision=ctx.run["revision"] or "",
            message=str(_render(step.fields["message"], ctx)),
            expires_at=ctx.now + timedelta(hours=hours))
    if row["status"] == "approved":
        return _result("succeeded", {"approved": True, "decided_by": row["decided_by"]})
    if row["status"] == "denied":
        return _result("failed", reason=f"denied by {row['decided_by']}")
    expires = datetime.fromisoformat(row["expires_at"])
    if row["status"] == "expired" or expires <= ctx.now:
        return _result("failed", reason="approval expired")
    return _result("waiting", {"approval_id": row["id"], "expires_at": _stamp(expires)},
                   reason="approval", wake_at=expires)


HANDLERS = {"wait": run_wait, "approval": run_approval}
