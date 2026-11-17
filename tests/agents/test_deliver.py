import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.agents import after, deliver, deliveries as dl, records, service, state
from whyline.agents import definitions as d

REPORT = "Current search date: 9 Oct\nOpen: 6\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"


@pytest.fixture
def agent(home, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "jobs.toml").write_text(
        f'name="jobs"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n')
    defn = d.load(folder / "jobs.toml", kind="personal")
    state.accept(state.connect(), defn)
    return defn


def _run(defn, outcome="succeeded", reason="", text=REPORT):
    record, folder = records.new_run(defn, source="manual", now=datetime(2026, 10, 9, 7, 0))
    record.outcome, record.reason, record.cli = outcome, reason, "codex"
    return records.finish(record, folder, final_text=text, defn=defn)


class FakeTelegram:
    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    def token_get(self):
        return "123:secret"

    def send_document(self, token, chat, path, caption, label=""):
        if self.fail:
            raise RuntimeError(self.fail)
        self.sent.append(("doc", chat, Path(path).name, caption))

    def send_message(self, token, chat, text, label=""):
        if self.fail:
            raise RuntimeError(self.fail)
        self.sent.append(("msg", chat, text))


def _no_docx(monkeypatch):
    monkeypatch.setattr("whyline.agents.convert.to_docx", lambda md, out: None)


DELIVERY = dl.Delivery(email=("a@example.com",), subject="Daily jobs", telegram_chat=-100,
                       telegram_label="Family (group)")


def test_success_sends_the_attachment_and_summary_to_both(agent, monkeypatch):
    def to_docx(md, out):
        out.write_bytes(b"PK")
        return out
    monkeypatch.setattr("whyline.agents.convert.to_docx", to_docx)
    mails, tg = [], FakeTelegram()
    record = _run(agent)
    results = deliver.after_run(agent, record, delivery=DELIVERY,
                                mail=lambda *a, **k: mails.append(a), tg=tg)
    assert [r["to"] for r in results] == ["email", "telegram"] and all(r["ok"] for r in results)
    to, subject, body, attachments = mails[0]
    assert to == ["a@example.com"] and subject == "Daily jobs — 2026-10-09"
    assert "Open: 6" in body and "| A |" not in body and "Sent by whyline from" in body
    assert [p.name for p in attachments] == ["jobs-2026-10-09.docx"]
    kind, chat, name, caption = tg.sent[0]
    assert (kind, chat, name) == ("doc", -100, "jobs-2026-10-09.docx")
    assert caption.startswith("Daily jobs — 2026-10-09\n\n")
    assert records.load(record.run_id).deliveries == results
    assert records.load(record.run_id).outcome == "succeeded"


def test_markdown_fallback_note_without_word(agent, monkeypatch):
    _no_docx(monkeypatch)
    mails = []
    deliver.after_run(agent, _run(agent), delivery=dl.Delivery(email=("a@example.com",)),
                      mail=lambda *a, **k: mails.append(a), tg=FakeTelegram())
    assert mails[0][3][0].name == "jobs-2026-10-09.md"
    assert "Markdown file is attached" in mails[0][2]


def test_a_failed_run_sends_a_short_alert(agent, monkeypatch):
    _no_docx(monkeypatch)
    mails, tg = [], FakeTelegram()
    record = _run(agent, outcome="timed_out", reason="codex ran past 45 minutes", text="")
    deliver.after_run(agent, record, delivery=DELIVERY, mail=lambda *a, **k: mails.append(a), tg=tg)
    assert mails[0][1] == "Daily jobs failed — 2026-10-09" and mails[0][3] == []
    assert "jobs (personal) timed_out: codex ran past 45 minutes" in mails[0][2]
    assert tg.sent[0][0] == "msg"
    assert deliver.status_text(records.load(record.run_id)).startswith("alert: ")


def test_silent_and_no_run_outcomes_send_nothing(agent, monkeypatch):
    _no_docx(monkeypatch)
    mails = []
    silent = dl.Delivery(email=("a@example.com",), on_failure="silent")
    assert deliver.after_run(agent, _run(agent, "failed", "boom", ""), delivery=silent,
                             mail=lambda *a, **k: mails.append(a), tg=FakeTelegram()) == []
    for outcome in ("skipped", "missed", "nothing_new", "cancelled"):
        assert deliver.after_run(agent, _run(agent, outcome, "", ""), delivery=silent,
                                 mail=lambda *a, **k: mails.append(a), tg=FakeTelegram()) == []
    for outcome in ("nothing_new", "cancelled"):
        assert deliver.after_run(agent, _run(agent, outcome, "", ""), delivery=DELIVERY,
                                 mail=lambda *a, **k: mails.append(a), tg=FakeTelegram()) == []
    assert mails == []


def test_missed_and_skipped_runs_alert_when_on_failure_is_alert(agent, monkeypatch):
    _no_docx(monkeypatch)
    mails, tg = [], FakeTelegram()
    deliver.after_run(agent, _run(agent, "missed", "", ""), delivery=DELIVERY,
                      mail=lambda *a, **k: mails.append(a), tg=tg)
    assert mails[0][1] == "Daily jobs missed — 2026-10-09"
    assert "missed the 07:00 run: the Mac was asleep or the scheduler was off." in mails[0][2]
    deliver.after_run(agent, _run(agent, "skipped", "another run was still going", ""),
                      delivery=DELIVERY, mail=lambda *a, **k: mails.append(a), tg=tg)
    assert "skipped: another run was still going" in mails[1][2]
    assert len(tg.sent) == 2


def test_missed_alert_names_the_run_and_next_run_and_logs_send_failures(agent, caplog):
    from datetime import datetime
    mails = []
    results = deliver.missed(agent, "2026-10-09T09:00:00", datetime(2026, 10, 10, 9, 0),
                             delivery=DELIVERY, mail=lambda *a, **k: mails.append(a),
                             tg=FakeTelegram(fail="down"))
    assert "missed the 09:00 run: the Mac was asleep or the scheduler was off. " in mails[0][2]
    assert "The next run is Sat 10 Oct 09:00." in mails[0][2]
    assert [r["ok"] for r in results] == [True, False]
    assert "telegram delivery failed" in caplog.text
    silent = dl.Delivery(email=("a@example.com",), on_failure="silent")
    assert deliver.missed(agent, "2026-10-09T09:00:00", None, delivery=silent) == []


def test_start_failed_alerts_both_places_and_never_raises(agent):
    mails, tg = [], FakeTelegram()
    results = deliver.start_failed(agent, RuntimeError("no such table:\nx"), delivery=DELIVERY,
                                   mail=lambda *a, **k: mails.append(a), tg=tg)
    assert [r["to"] for r in results] == ["email", "telegram"]
    assert ("jobs (personal) could not start: no such table: x. "
            "Run whyline doctor or open the console's Check.") in mails[0][2]
    def boom(*a, **k):
        raise RuntimeError("down")
    assert deliver.start_failed(agent, RuntimeError("e"), delivery=DELIVERY, mail=boom,
                                tg=FakeTelegram(fail="down"))[0]["ok"] is False
    silent = dl.Delivery(email=("a@example.com",), on_failure="silent")
    assert deliver.start_failed(agent, RuntimeError("e"), delivery=silent, mail=boom) == []


def test_mail_failing_still_sends_telegram(agent, monkeypatch):
    _no_docx(monkeypatch)
    from whyline.agents.mail_send import MailError

    def broken(*args, **kwargs):
        raise MailError("Mail has no account set up")

    tg = FakeTelegram()
    results = deliver.after_run(agent, _run(agent), delivery=DELIVERY, mail=broken, tg=tg)
    assert results[0] == {"to": "email", "ok": False, "detail": "Mail has no account set up"}
    assert results[1]["ok"] and tg.sent
    assert "email ✗ Mail has no account set up" in deliver.status_text(SimpleNamespace(
        outcome="succeeded", deliveries=results))


def test_telegram_not_set_up(agent, monkeypatch):
    _no_docx(monkeypatch)
    tg = FakeTelegram()
    tg.token_get = lambda: None
    results = deliver.after_run(agent, _run(agent), delivery=dl.Delivery(telegram_chat=-100),
                                mail=lambda *a, **k: None, tg=tg)
    assert results == [{"to": "telegram", "ok": False,
                        "detail": "Telegram isn't set up on this Mac; run Telegram setup"}]


def test_the_command_gets_its_environment_and_log(agent, monkeypatch):
    _no_docx(monkeypatch)
    seen = {}

    def run(argv, **kwargs):
        seen.update(kwargs["env"])
        seen["argv"] = argv
        return SimpleNamespace(returncode=3, stdout="first\nlast line\n")

    record = _run(agent)
    results = deliver.after_run(agent, record, delivery=dl.Delivery(command="notify.sh"),
                                mail=None, tg=FakeTelegram(), run=run)
    assert seen["argv"][-1] == "notify.sh"
    assert seen["WHYLINE_AGENT"] == "jobs" and seen["WHYLINE_OUTCOME"] == "succeeded"
    assert seen["WHYLINE_REPORT"].endswith("final.md") and seen["WHYLINE_ATTACHMENT"].endswith(".md")
    assert "Open: 6" in seen["WHYLINE_SUMMARY"] and seen["WHYLINE_RUN_ID"] == record.run_id
    assert results == [{"to": "command", "ok": False, "detail": "command failed (exit 3): last line"}]
    assert "last line" in (records.run_folder(record.run_id) / "command.log").read_text()


def test_a_command_timeout(agent, monkeypatch):
    import subprocess
    _no_docx(monkeypatch)

    def run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 120)

    results = deliver.after_run(agent, _run(agent), delivery=dl.Delivery(command="sleep 999"),
                                tg=FakeTelegram(), run=run)
    assert results[0]["detail"] == "command failed (timed out after 2 minutes)"


def test_after_finish_delivers_and_never_raises(agent, monkeypatch):
    sent = []
    monkeypatch.setattr(deliver, "after_run", lambda defn, record: sent.append(record.run_id) or [])
    record = _run(agent)
    after.finish(state.connect(), agent, record, notify=False)
    assert sent == [record.run_id]

    def explode(defn, record):
        raise RuntimeError("boom")

    monkeypatch.setattr(deliver, "after_run", explode)
    after.finish(state.connect(), agent, _run(agent), notify=False)  # no exception


def test_resend_uses_the_latest_run(agent, monkeypatch):
    calls = []
    monkeypatch.setattr(deliver, "after_run", lambda defn, record: calls.append(record.run_id) or [])
    record = _run(agent)
    service.resend("jobs", None)
    service.resend("jobs", None, record.run_id)
    assert calls == [record.run_id, record.run_id]


BRIEF = "# Brief\n\nBody.\n\n```brief-actions\nremind in 1h call\n```\n"


def test_morning_brief_delivery_drops_the_block_and_makes_cards(agent, monkeypatch):
    from dataclasses import replace
    _no_docx(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "whyline.ideas.brief.after_delivery",
        lambda record, **kw: calls.append((record.run_id, kw))
        or {"to": "brief-actions", "ok": True, "detail": "1 reminder card"})
    defn = replace(agent, name="morning-brief")
    record = _run(defn, text=BRIEF)
    tg = FakeTelegram()
    results = deliver.after_run(defn, record, delivery=dl.Delivery(telegram_chat=-100), tg=tg)
    assert calls == [(record.run_id, {"chat_id": -100})]
    assert results[-1]["to"] == "brief-actions"
    caption = tg.sent[0][3]
    assert "brief-actions" not in caption and "Body." in caption
    folder = records.run_folder(record.run_id)
    assert "brief-actions" not in (folder / "morning-brief-2026-10-09.md").read_text()
    assert "brief-actions" in (folder / "final.md").read_text()


def test_other_agents_are_unaffected(agent, monkeypatch):
    _no_docx(monkeypatch)
    monkeypatch.setattr("whyline.ideas.brief.after_delivery",
                        lambda *a, **k: pytest.fail("hook must not run"))
    tg = FakeTelegram()
    record = _run(agent, text=BRIEF)
    results = deliver.after_run(agent, record, delivery=dl.Delivery(telegram_chat=-100), tg=tg)
    assert [r["to"] for r in results] == ["telegram"]
    folder = records.run_folder(record.run_id)
    assert "brief-actions" in (folder / "jobs-2026-10-09.md").read_text()


def test_send_test(home, monkeypatch, tmp_path):
    mails, tg = [], FakeTelegram()
    results = deliver.send_test("jobs (personal)", DELIVERY, mail=lambda *a, **k: mails.append(a),
                                tg=tg, cwd=tmp_path)
    assert [r["to"] for r in results] == ["email", "telegram"]
    assert mails[0][1] == "Test from whyline: jobs (personal)"


def test_describe():
    assert deliver.describe(dl.Delivery()) == ""
    text = deliver.describe(DELIVERY)
    assert "a@example.com" in text and "Telegram 'Family (group)'" in text
    assert "Word file attached" in text and "short alert" in text


# --- check-in agents: active hours, silence and the hourly limit (CKN-3) ---

def _checkin(home, tmp_path, hours="", silent=False, name="watch"):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    extra = f'active_hours = "{hours}"\n' if hours else ""
    (folder / f"{name}.toml").write_text(
        f'name="{name}"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n'
        f'[checkin]\ngate = "event-soon"\nsilent = {str(silent).lower()}\n{extra}'
        '[checkin.gate_args]\nminutes = "15"\n')
    defn = d.load(folder / f"{name}.toml", kind="personal")
    state.accept(state.connect(), defn)
    return defn


CHAT = dl.Delivery(telegram_chat=-100, telegram_label="Me")
NIGHT = datetime(2026, 11, 17, 2, 0)
DAY = datetime(2026, 11, 17, 10, 0)


def test_held_until_active_hours(home, tmp_path, monkeypatch):
    _no_docx(monkeypatch)
    defn = _checkin(home, tmp_path, hours="09:00-17:00")
    tg = FakeTelegram()
    results = deliver.after_run(defn, _run(defn), delivery=CHAT, tg=tg, now=NIGHT)
    assert tg.sent == [] and results[0]["to"] == "held"
    assert deliver.flush_held(NIGHT, {defn.agent_id: defn}, tg=tg) == []
    assert tg.sent == []
    out = deliver.flush_held(DAY, {defn.agent_id: defn}, tg=tg)
    assert [r["ok"] for r in out] == [True]
    assert tg.sent[0][0] == "msg" and tg.sent[0][2].startswith("While you were away:")
    assert "Current search date" in tg.sent[0][2]
    assert deliver.flush_held(DAY, {defn.agent_id: defn}, tg=tg) == []
    assert len(tg.sent) == 1


def test_nothing_answer_is_silent(home, tmp_path, monkeypatch):
    _no_docx(monkeypatch)
    defn = _checkin(home, tmp_path, silent=True)
    tg = FakeTelegram()
    record = _run(defn, text="Nothing.\n")
    assert deliver.after_run(defn, record, delivery=CHAT, tg=tg, now=DAY) == []
    assert tg.sent == [] and record.reason == "nothing to report"
    # a real answer from the same agent still goes out
    assert deliver.after_run(defn, _run(defn), delivery=CHAT, tg=tg, now=DAY)[0]["ok"]
    assert len(tg.sent) == 1
    # a non-silent gate agent sends even NOTHING
    loud = _checkin(home, tmp_path, name="loud")
    deliver.after_run(loud, _run(loud, text="NOTHING"), delivery=CHAT, tg=FakeTelegram(),
                      now=DAY.replace(hour=12))


def test_one_checkin_message_per_hour(home, tmp_path, monkeypatch):
    _no_docx(monkeypatch)
    a, b = _checkin(home, tmp_path, name="a"), _checkin(home, tmp_path, name="b")
    tg = FakeTelegram()
    deliver.after_run(a, _run(a), delivery=CHAT, tg=tg, now=DAY)
    second = deliver.after_run(b, _run(b, text="Line one\nLine two"), delivery=CHAT, tg=tg,
                               now=DAY.replace(minute=30))
    assert len(tg.sent) == 1 and second[0]["to"] == "held"
    known = {a.agent_id: a, b.agent_id: b}
    assert deliver.flush_held(DAY.replace(minute=45), known, tg=tg) == []
    later = deliver.flush_held(DAY.replace(hour=11, minute=1), known, tg=tg)
    assert len(later) == 1 and len(tg.sent) == 2
    assert "While you were away:" in tg.sent[1][2] and "Line two" in tg.sent[1][2]


def test_held_items_for_one_chat_go_as_one_message_with_five_lines(home, tmp_path, monkeypatch):
    _no_docx(monkeypatch)
    a, b = _checkin(home, tmp_path, hours="09:00-17:00", name="a"), \
        _checkin(home, tmp_path, hours="09:00-17:00", name="b")
    tg = FakeTelegram()
    many = "\n".join(f"row {n}" for n in range(1, 9))
    deliver.after_run(a, _run(a, text=many), delivery=CHAT, tg=tg, now=NIGHT)
    deliver.after_run(b, _run(b, text="short"), delivery=CHAT, tg=tg, now=NIGHT)
    deliver.flush_held(DAY, {a.agent_id: a, b.agent_id: b}, tg=tg)
    assert len(tg.sent) == 1
    text = tg.sent[0][2]
    assert "row 5" in text and "row 6" not in text and "short" in text


def test_a_failure_alert_follows_the_hours(home, tmp_path, monkeypatch):
    _no_docx(monkeypatch)
    defn = _checkin(home, tmp_path, hours="09:00-17:00")
    tg = FakeTelegram()
    out = deliver.after_run(defn, _run(defn, "failed", "boom", ""), delivery=CHAT, tg=tg, now=NIGHT)
    assert tg.sent == [] and out[0]["to"] == "held"


def test_held_list_keeps_the_newest_twenty(home, tmp_path, monkeypatch):
    _no_docx(monkeypatch)
    defn = _checkin(home, tmp_path, hours="09:00-17:00")
    tg = FakeTelegram()
    for n in range(25):
        deliver.after_run(defn, _run(defn, text=f"item {n}"), delivery=CHAT, tg=tg, now=NIGHT)
    held = deliver._load_held()["held"][defn.agent_id]
    assert len(held) == 20 and held[0]["answer"].strip() == "item 5" and held[-1]["answer"].strip() == "item 24"


def test_email_is_held_outside_hours_but_not_limited_hourly(home, tmp_path, monkeypatch):
    _no_docx(monkeypatch)
    defn = _checkin(home, tmp_path, hours="09:00-17:00")
    mails = []
    both = dl.Delivery(email=("a@example.com",), telegram_chat=-100)
    deliver.after_run(defn, _run(defn), delivery=both, mail=lambda *a, **k: mails.append(a),
                      tg=FakeTelegram(), now=NIGHT)
    assert mails == []
    deliver.flush_held(DAY, {defn.agent_id: defn}, mail=lambda *a, **k: mails.append(a),
                       tg=FakeTelegram())
    assert len(mails) == 1
    assert [p.name for p in mails[0][3]] == ["watch-2026-10-09.md"]


def test_concurrent_deliveries_send_one_telegram_an_hour(home, tmp_path, monkeypatch):
    import threading
    import time
    _no_docx(monkeypatch)
    a, b = _checkin(home, tmp_path, name="a"), _checkin(home, tmp_path, name="b")

    class Slow(FakeTelegram):
        def send_message(self, *args, **kwargs):
            time.sleep(0.2)
            return super().send_message(*args, **kwargs)

        def send_document(self, *args, **kwargs):
            time.sleep(0.2)
            return super().send_document(*args, **kwargs)

    tg = Slow()
    threads = [threading.Thread(target=deliver.after_run, args=(x, _run(x)),
                                kwargs={"delivery": CHAT, "tg": tg, "now": DAY}) for x in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(tg.sent) == 1
    assert sum(len(v) for v in deliver._load_held()["held"].values()) == 1


def test_an_agent_with_no_gate_delivers_as_before(agent, monkeypatch):
    _no_docx(monkeypatch)
    tg = FakeTelegram()
    results = deliver.after_run(agent, _run(agent, text="NOTHING"), delivery=CHAT, tg=tg,
                                now=NIGHT)
    deliver.after_run(agent, _run(agent), delivery=CHAT, tg=tg, now=NIGHT)
    assert [r["to"] for r in results] == ["telegram"]
    assert len(tg.sent) == 2 and deliver._load_held()["held"] == {}
