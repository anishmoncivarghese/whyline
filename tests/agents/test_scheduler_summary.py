from datetime import datetime
from pathlib import Path

from whyline.agents import definitions as d, service

NOW = datetime(2026, 10, 9, 21, 0)  # a Friday evening


def _row(name, kind, status="active", at="07:00", folder=""):
    trigger = d.Trigger(kind=kind, at=at if kind in ("daily", "weekdays") else "",
                        every_hours=6 if kind == "every" else 0, folder=folder)
    defn = d.AgentDef(name=name, kind="personal", path=Path(f"/tmp/{name}.toml"), root=Path("/tmp"),
                      instructions="x", runner="codex", trigger=trigger)
    return service.Row(defn, status, "", "", "", service.when_text(trigger))


def test_on_lists_scheduled_agents_with_their_next_run_and_the_conditions():
    rows = [_row("govt-job-search", "daily"), _row("notes", "manual"), _row("ad-hoc", "manual")]
    text = service.scheduler_summary(rows, on=True, now=NOW)
    assert text.startswith("Scheduler on. whyline checks for due agents every 2 minutes")
    assert "Scheduled agents (1):" in text
    assert "• govt-job-search (personal) — every day at 07:00 · next: Sat 10 Oct, 07:00" in text
    assert "Manual agents (2) run only when you start them." in text
    assert "this Mac on and you logged in" in text and "runs once when it wakes" in text


def test_on_says_which_scheduled_agents_will_not_run_and_why():
    rows = [_row("a", "daily", "paused"), _row("b", "weekdays", "needs_review"),
            _row("c", "every", "needs_attention"), _row("d", "folder", folder="~/Inbox")]
    text = service.scheduler_summary(rows, on=True, now=NOW)
    assert "Scheduled agents (4):" in text
    assert "• a (personal) — every day at 07:00 · won't run until you resume it" in text
    assert "• b (personal) — every weekday at 07:00 · won't run until you accept its changes" in text
    assert "won't run until you resume it after checking its failures" in text
    assert "• d (personal) — when files appear in ~/Inbox · watching the folder" in text


def test_on_with_no_scheduled_agents():
    text = service.scheduler_summary([_row("notes", "manual")], on=True, now=NOW)
    assert "no agent has a schedule yet" in text and "When" in text


def test_off():
    text = service.scheduler_summary([_row("govt-job-search", "daily")], on=False, now=NOW)
    assert text.startswith("Scheduler off.")
    assert "won't run until you turn it back on" in text and "Run now still works" in text


def test_broken_files_are_not_counted():
    broken = service.Row(d.Broken(path=Path("/tmp/x.toml"), kind="personal", error="bad"),
                         "needs_review", "", "", "", "bad")
    text = service.scheduler_summary([broken, _row("a", "daily")], on=True, now=NOW)
    assert "Scheduled agents (1):" in text
