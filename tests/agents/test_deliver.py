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
    for outcome in ("skipped", "missed"):
        assert deliver.after_run(agent, _run(agent, outcome, "", ""), delivery=DELIVERY,
                                 mail=lambda *a, **k: mails.append(a), tg=FakeTelegram()) == []
    assert mails == []


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
