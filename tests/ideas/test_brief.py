"""Calendar export for the morning brief."""

import json
import subprocess
from datetime import datetime
from types import SimpleNamespace

import pytest

from whyline.ideas import brief, store


def _event(title, start, end, *, calendar="Work", location="", all_day=False):
    return {
        "title": title,
        "start": f"2026-10-28T{start}:00",
        "end": f"2026-10-28T{end}:00",
        "location": location,
        "allDay": all_day,
        "calendar": calendar,
    }


def _runner(events, *, calendars=("Work", "Home"), seen=None):
    payload = json.dumps(
        {"status": "ok", "date": "2026-10-28", "calendars": list(calendars), "events": events}
    )

    def run(command, **kwargs):
        if seen is not None:
            seen.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=payload, stderr="")

    return run


def _today(tmp_path, events, **kwargs):
    return brief.calendar(tmp_path / "brief", calendars=[], run=_runner(events, **kwargs))


def test_events_are_time_ordered(tmp_path):
    result = _today(
        tmp_path,
        [
            _event("Lunch", "12:00", "13:00", location="Cafe"),
            _event("Standup", "09:00", "09:15"),
        ],
    )
    text = (tmp_path / "brief" / "today.md").read_text()
    assert result.path == tmp_path / "brief" / "today.md"
    assert text == result.text
    assert text.index("09:00-09:15 Standup (Work)") < text.index("12:00-13:00 Lunch @ Cafe (Work)")


def test_free_blocks_are_thirty_minutes_or_more(tmp_path):
    result = _today(
        tmp_path,
        [
            _event("A", "08:00", "09:00"),
            _event("B", "09:20", "10:00"),  # 20 minute gap is not listed
            _event("C", "10:30", "17:00"),  # exactly 30 minutes is listed
        ],
    )
    free = result.text.split("## Free blocks")[1].split("## Clashes")[0]
    assert "- 10:00-10:30 (30m)" in free
    assert "- 17:00-19:00 (2h)" in free
    assert "09:00-09:20" not in free
    assert free.count("\n- ") == 2


def test_free_blocks_cover_an_empty_day(tmp_path):
    result = _today(tmp_path, [])
    assert "No events." in result.text
    assert "- 08:00-19:00 (11h)" in result.text


def test_clashes_are_reported_and_touching_events_are_not(tmp_path):
    result = _today(
        tmp_path,
        [
            _event("One", "09:00", "10:00"),
            _event("Two", "09:30", "10:30"),
            _event("Three", "10:30", "11:00"),
        ],
    )
    clashes = result.text.split("## Clashes")[1]
    assert "One (09:00-10:00) overlaps Two (09:30-10:30)" in clashes
    assert "Three" not in clashes


def test_no_clashes_says_none(tmp_path):
    result = _today(tmp_path, [_event("One", "09:00", "10:00")])
    assert result.text.split("## Clashes")[1].strip() == "None."


def test_all_day_events_are_listed_but_do_not_block_time(tmp_path):
    result = _today(
        tmp_path,
        [
            {
                "title": "Holiday",
                "start": "2026-10-28T00:00:00",
                "end": "2026-10-29T00:00:00",
                "location": "",
                "allDay": True,
                "calendar": "Home",
            },
            _event("Call", "09:00", "10:00"),
        ],
    )
    assert "- All day: Holiday (Home)" in result.text
    assert "- 10:00-19:00 (9h)" in result.text
    assert "Holiday" not in result.text.split("## Clashes")[1]


def test_access_denied_is_distinct(tmp_path):
    def run(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout='{"status": "denied"}', stderr="")

    with pytest.raises(brief.AccessDenied) as caught:
        brief.calendar(tmp_path / "brief", calendars=[], run=run)
    assert "System Settings > Privacy & Security > Calendars" in str(caught.value)
    assert not (tmp_path / "brief" / "today.md").exists()


def test_timeout_is_a_calendar_error_not_a_denial(tmp_path):
    def run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    with pytest.raises(brief.CalendarError) as caught:
        brief.calendar(tmp_path / "brief", calendars=[], run=run)
    assert not isinstance(caught.value, brief.AccessDenied)
    assert "30 seconds" in str(caught.value)


def test_script_failure_is_a_calendar_error(tmp_path):
    def run(command, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="execution error: boom")

    with pytest.raises(brief.CalendarError, match="boom"):
        brief.calendar(tmp_path / "brief", calendars=[], run=run)


def test_runs_osascript_with_the_script_and_a_timeout(tmp_path):
    seen = []
    brief.calendar(
        tmp_path / "brief", calendars=["Work"], run=_runner([], seen=seen)
    )
    command, kwargs = seen[0]
    assert command[:3] == ["/usr/bin/osascript", "-l", "JavaScript"]
    assert command[3].endswith("calendar_today.js")
    assert json.loads(command[4]) == ["Work"]
    assert kwargs["timeout"] == 30


def test_calendar_filtering(tmp_path):
    result = brief.calendar(
        tmp_path / "brief",
        calendars=["Work"],
        run=_runner(
            [_event("Standup", "09:00", "09:15"), _event("Gym", "18:00", "19:00", calendar="Home")]
        ),
    )
    assert "Standup" in result.text
    assert "Gym" not in result.text
    assert result.calendars == ("Work", "Home")


def test_selected_calendars_round_trip_and_empty_means_all(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(tmp_path / "ideas"))
    conn = store.connect()
    try:
        assert brief.selected(conn) == []
        brief.select(conn, ["Work", "Home"])
        assert brief.selected(conn) == ["Work", "Home"]
        brief.select(conn, [])
        assert brief.selected(conn) == []
        row = conn.execute("SELECT value FROM kv WHERE key = 'brief_calendars'").fetchone()
        assert row[0] == ""
    finally:
        conn.close()


F, R = "\x1f", "\x1e"
NOW = datetime(2026, 10, 28, 12, 0)


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(tmp_path / "ideas"))


def _mail_answer(messages, names=("INBOX", "Archive")):
    rows = [f"{s}{F}{subj}{F}{when}{F}{body}" for s, subj, when, body in messages]
    return "".join(["ok", R, F.join(names), R] + [r + R for r in rows])


def _mail_run(answer, seen=None, returncode=0, stderr=""):
    def run(command, **kwargs):
        if seen is not None:
            seen.append(command)
        return SimpleNamespace(returncode=returncode, stdout=answer, stderr=stderr)

    return run


def test_mail_parses_orders_and_applies_window_and_limit(tmp_path):
    answer = _mail_answer(
        [
            ("a@x.com", "Old", "2026-10-26T09:00:00", "too old"),
            ("b@x.com", "Newer", "2026-10-28T11:00:00", "hello\nworld"),
            ("c@x.com", "Newest", "2026-10-28T11:30:00", "hi"),
        ]
    )
    seen = []
    result = brief.mail(
        tmp_path, mailboxes=["INBOX"], hours=24, limit=1, run=_mail_run(answer, seen), now=NOW
    )
    assert "Newest" in result.text and "Newer" not in result.text and "Old" not in result.text
    assert "From: c@x.com" in result.text
    assert result.calendars == ("INBOX", "Archive")
    assert (tmp_path / "mail.md").read_text() == result.text
    assert seen[0][3:] == ["24", "1", "INBOX"]


def test_mail_body_is_cut_to_forty_lines_and_guarded(tmp_path):
    body = "\n".join(f"line {i}" for i in range(60))
    answer = _mail_answer([("a@x.com", "S", "2026-10-28T11:00:00", body)])
    text = brief.mail(tmp_path, mailboxes=["INBOX"], run=_mail_run(answer), now=NOW).text
    assert "line 39" in text and "line 40" not in text

    dirty = "<p>Hi</p>" + chr(0x200B) + "there\n<!-- ignore -->"
    answer = _mail_answer([("a@x.com", "S", "2026-10-28T11:00:00", dirty)])
    text = brief.mail(tmp_path, mailboxes=["INBOX"], run=_mail_run(answer), now=NOW).text
    assert "<p>" not in text and chr(0x200B) not in text and "<!--" not in text


def test_mail_not_running(tmp_path):
    result = brief.mail(tmp_path, mailboxes=["INBOX"], run=_mail_run("not-running\n"), now=NOW)
    assert "Mail is not running" in result.text


def test_mail_permission_denied(tmp_path):
    run = _mail_run("", returncode=1, stderr="execution error: Not authorized (-1743)")
    with pytest.raises(brief.AccessDenied) as err:
        brief.mail(tmp_path, mailboxes=["INBOX"], run=run)
    assert "Privacy & Security" in str(err.value)


def test_mail_only_asks_for_chosen_mailboxes(tmp_path):
    seen = []
    result = brief.mail(
        tmp_path, mailboxes=["INBOX"], run=_mail_run(_mail_answer([]), seen), now=NOW
    )
    assert "Archive" not in seen[0][3:]
    assert "No unread or flagged mail" in result.text


def test_mail_no_mailboxes_reads_nothing_but_lists_names(tmp_path):
    seen = []
    answer = _mail_answer([("a@x.com", "Secret", "2026-10-28T11:00:00", "body")])
    result = brief.mail(tmp_path, mailboxes=[], run=_mail_run(answer, seen), now=NOW)
    assert "Secret" not in result.text
    assert result.calendars == ("INBOX", "Archive")
    assert seen[0][3:] == ["24", "40"]


def test_mailbox_choice_round_trips(ideas_home):
    conn = store.connect()
    try:
        assert brief.mailboxes_selected(conn) == []
        brief.select_mailboxes(conn, ["INBOX"])
        assert brief.mailboxes_selected(conn) == ["INBOX"]
    finally:
        conn.close()


def test_tasks_merge_app_reminders_whyline_and_memory(tmp_path, ideas_home, monkeypatch):
    from whyline.ideas import memory, reminders as ledger

    monkeypatch.setattr(memory, "for_prompt", lambda: "User's own notes:\n1. likes tea")
    conn = store.connect()
    try:
        ledger.create(conn, None, NOW.replace(hour=15), "call mum", now=NOW)
    finally:
        conn.close()
    answer = "".join(["ok", R, f"Pay rent{F}2026-10-28T09:00:00{F}Home", R])
    result = brief.reminders(tmp_path, run=_mail_run(answer), now=NOW)
    assert "Pay rent (2026-10-28 09:00, Home)" in result.text
    assert "call mum" in result.text
    assert "likes tea" in result.text
    assert "whyline:" in result.text
    assert (tmp_path / "tasks.md").read_text() == result.text


def test_tasks_status_names_failed_agents_and_paused_relay(tmp_path, ideas_home, monkeypatch):
    from types import SimpleNamespace

    from whyline.agents import service

    def row(name, outcome):
        return SimpleNamespace(defn=SimpleNamespace(name=name), last_outcome=outcome)

    monkeypatch.setattr(
        service, "rows",
        lambda repo: [row("digest", "failed"), row("ok-one", "succeeded"), row("new", "")],
    )
    conn = store.connect()
    try:
        idea = store.add(conn, "an idea", source="test")
        conn.execute("UPDATE ideas SET status = 'paused' WHERE id = ?", (idea.id,))
        conn.commit()
    finally:
        conn.close()
    answer = "".join(["ok", R])
    result = brief.reminders(tmp_path, run=_mail_run(answer), now=NOW)
    assert "whyline: 1 relay run paused; agents failed last run: digest" in result.text
    assert "ok-one" not in result.text


def test_tasks_denied(tmp_path, ideas_home):
    run = _mail_run("", returncode=1, stderr="Not authorized (-1743)")
    with pytest.raises(brief.AccessDenied):
        brief.reminders(tmp_path, run=run)


@pytest.fixture
def agent_env(tmp_path, monkeypatch, ideas_home):
    from whyline import account
    from whyline.agents import telegram
    from whyline.ideas import telegram_in

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(account, "enabled_agents", lambda: {"claude", "codex"})
    monkeypatch.setattr(telegram, "known_chats", lambda: {42: "Me (private)", 7: "Other"})
    conn = store.connect()
    try:
        telegram_in._save_allowed(conn, [42])
        conn.commit()
    finally:
        conn.close()


def test_setup_writes_the_definition(agent_env):
    from whyline.agents import deliveries, state

    defn = brief.setup(at="06:45", runner="claude", backup=["codex"], chat_id=42)
    assert defn.name == "morning-brief" and defn.kind == "personal"
    assert (defn.trigger.kind, defn.trigger.at) == ("weekdays", "06:45")
    assert defn.before == "brief-collect"
    assert (defn.runner, defn.backup) == ("claude", ("codex",))
    assert defn.timeout_minutes == 15
    for part in ("schedule", "top 3 priorities", "suggested reply", "Clashes",
                 "brief-actions", "at most 5", "remind <when> <text>",
                 "Never act", "Never invent"):
        assert part in defn.instructions
    sent = deliveries.get(defn.agent_id)
    assert sent.telegram_chat == 42 and not sent.email and not sent.command
    assert state.check_hash(state.connect(), defn) != "needs_review"


def test_setup_again_updates_without_duplicating(agent_env):
    from whyline.agents import definitions as d

    from whyline.agents import deliveries
    from whyline.ideas import telegram_in

    conn = store.connect()
    try:
        telegram_in._save_allowed(conn, [42, 7])
        conn.commit()
    finally:
        conn.close()
    brief.setup(at="07:00", runner="claude", chat_id=42)
    assert brief.current_chat() == 42
    brief.setup(at="08:15", runner="codex", chat_id=7)
    found = [a for a in d.discover(None) if isinstance(a, d.AgentDef)]
    assert [a.name for a in found] == ["morning-brief"]
    assert (found[0].trigger.at, found[0].runner) == ("08:15", "codex")
    assert brief.current().runner == "codex"
    assert brief.current_chat() == 7
    assert deliveries.get(found[0].agent_id).telegram_chat == 7
    assert len(deliveries.load_all()) == 1


@pytest.mark.parametrize("runner,backup", [("grok", ()), ("claude", ("grok",)), ("antigravity", ())])
def test_setup_refuses_disabled_or_uncleared_providers(agent_env, monkeypatch, runner, backup):
    from whyline import account

    # grok is disabled; antigravity is enabled but not cleared for unattended runs.
    monkeypatch.setattr(account, "enabled_agents", lambda: {"claude", "codex", "antigravity"})
    with pytest.raises(brief.SetupError, match="not enabled"):
        brief.setup(runner=runner, backup=backup, chat_id=42)
    assert brief.current() is None


def test_setup_refuses_a_chat_that_is_not_allowed(agent_env):
    with pytest.raises(brief.SetupError, match="not an allowed inbox chat"):
        brief.setup(runner="claude", chat_id=7)
    assert brief.current() is None


def test_setup_refuses_a_bad_time(agent_env):
    with pytest.raises(brief.SetupError, match="24-hour"):
        brief.setup(at="7am", runner="claude", chat_id=42)
    assert brief.current() is None


NOW = datetime(2026, 10, 28, 7, 0)


def _cards(monkeypatch, text):
    from whyline.ideas import requests

    monkeypatch.setattr("whyline.agents.records.read_final", lambda run_id: text)
    result = brief.after_delivery(SimpleNamespace(run_id="r1"), chat_id=42, now=NOW)
    conn = store.connect()
    try:
        rows = conn.execute("SELECT * FROM requests ORDER BY id").fetchall()
        return result, [requests._request(r) for r in rows]
    finally:
        conn.close()


def _brief_text(*lines):
    return "# Brief\n\nBody.\n\n```brief-actions\n" + "\n".join(lines) + "\n```\n"


def test_valid_remind_lines_become_tap_cards(ideas_home, monkeypatch):
    result, rows = _cards(
        monkeypatch, _brief_text("remind in 2h call the bank", "remind tomorrow 9:00 pay rent")
    )
    assert [r.state for r in rows] == ["waiting_tap", "waiting_tap"]
    assert all(r.action == "remind" and r.proposed_by == "assistant" and r.chat_id == 42 for r in rows)
    assert json.loads(rows[0].args_json) == {"when": "in 2h", "text": "call the bank"}
    assert result["detail"] == "2 reminder cards"
    conn = store.connect()
    try:
        cards = conn.execute("SELECT * FROM outbox WHERE kind = 'message' ORDER BY id").fetchall()
    finally:
        conn.close()
    assert len(cards) == 2
    assert all(int(c["chat_id"]) == 42 and c["buttons_json"] for c in cards)
    assert "call the bank" in cards[0]["text"] and "pay rent" in cards[1]["text"]


def test_run_and_do_lines_are_ignored_and_counted(ideas_home, monkeypatch):
    result, rows = _cards(
        monkeypatch, _brief_text("run jobs", "do T-1", "remind never call", "remind in 1h stretch")
    )
    assert [r.action for r in rows] == ["remind"]
    assert result["detail"] == "1 reminder card; ignored 3 other lines"


def test_more_than_five_lines_are_cut_to_five(ideas_home, monkeypatch):
    lines = [f"remind in {n}h task {n}" for n in range(1, 8)]
    result, rows = _cards(monkeypatch, _brief_text(*lines))
    assert len(rows) == 5
    assert result["detail"] == "5 reminder cards; ignored 2 other lines"


def test_split_actions_removes_the_block():
    text, lines = brief.split_actions(_brief_text("remind in 1h x", "run y"))
    assert text == "# Brief\n\nBody.\n"
    assert lines == ["remind in 1h x", "run y"]


def _check_runner(*, mail="ok\x1e", calendar_denied=False):
    cal = json.dumps(
        {"status": "denied"}
        if calendar_denied
        else {"status": "ok", "date": "2026-10-28", "calendars": [], "events": []}
    )

    def run(command, **kwargs):
        if "JavaScript" in command:
            return SimpleNamespace(returncode=0, stdout=cal, stderr="")
        if command[2] == brief.MAIL_SCRIPT:
            # the script reads argv items 1 and 2 (hours, limit) before anything else
            assert command[:2] == [brief.OSASCRIPT, "-e"]
            assert command[3:5] == ["1", "1"]
            answer = mail
        else:
            answer = "ok\x1e"
        return SimpleNamespace(returncode=0, stdout=answer, stderr="")

    return run


def _agent():
    from whyline.agents import definitions as d

    return SimpleNamespace(name=brief.AGENT_NAME, trigger=d.Trigger(kind="weekdays", at="07:00"))


def test_check_warns_when_the_agent_is_not_set_up(monkeypatch):
    monkeypatch.setattr(brief, "current", lambda: None)

    def boom(*a, **k):
        raise AssertionError("probed without an agent")

    results = brief.check(run=boom)
    assert [(c.name, c.level) for c in results] == [("morning brief", "warn")]


def test_check_reports_access_agent_last_run_next_run_and_wake_hint(monkeypatch):
    from whyline.agents import service

    agent = _agent()
    monkeypatch.setattr(brief, "current", lambda: agent)
    row = SimpleNamespace(
        defn=agent, status="active", last_outcome="failed", last_run="2026-10-27 07:00"
    )
    monkeypatch.setattr(service, "rows", lambda root: [row])
    results = {
        c.name: c for c in brief.check(run=_check_runner(), now=datetime(2026, 10, 28, 12, 0))
    }
    assert results["brief calendar"].ok
    assert results["brief mail"].ok
    assert results["brief reminders"].ok
    assert results["brief agent"].ok
    assert not results["brief last run"].ok
    assert "failed" in results["brief last run"].detail
    assert "2026-10-29 07:00" in results["brief next run"].detail
    assert "pmset repeat wakeorpoweron MTWRF 06:55:00" in results["brief wake"].detail
    assert "never runs it" in results["brief wake"].detail


def test_check_reports_denied_calendar_and_mail_not_running(monkeypatch):
    from whyline.agents import service

    monkeypatch.setattr(brief, "current", lambda: _agent())
    monkeypatch.setattr(service, "rows", lambda root: [])
    results = {
        c.name: c
        for c in brief.check(run=_check_runner(mail="not-running", calendar_denied=True))
    }
    assert not results["brief calendar"].ok
    assert "denied" in results["brief calendar"].detail
    assert results["brief mail"].level == "warn"
    assert not results["brief agent"].ok
    assert results["brief last run"].level == "warn"
