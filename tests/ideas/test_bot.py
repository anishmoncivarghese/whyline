"""Cards, buttons, and the retrying outbox."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.agents import telegram
from whyline.ideas import (
    analyse,
    bot,
    brainstorm,
    documents,
    paths,
    report,
    store,
    telegram_in,
)
from whyline_relay.agents import AgentCancelled

CHAT = 11
TOKEN = "123:secret"


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: TOKEN)
    return TOKEN


def _http(calls, *, fail=False):
    def http(method, token, fields, files):
        calls.append((method, fields, files))
        if fail:
            raise OSError("down")
        return {"ok": True, "result": {"message_id": 1}}

    return http


def _message(text, *, update_id=1, message_id=5):
    return {
        "update_id": update_id,
        "chat_id": CHAT,
        "message_id": message_id,
        "text": text,
        "callback_data": None,
        "callback_id": None,
        "kind": "message",
        "handled": 0,
    }


def _press(data, callback_id, *, update_id=2):
    return {
        "update_id": update_id,
        "chat_id": CHAT,
        "message_id": 5,
        "text": "",
        "callback_data": data,
        "callback_id": callback_id,
        "kind": "callback_query",
        "handled": 0,
    }


def _outbox(conn, kind=None):
    if kind is None:
        return conn.execute("SELECT * FROM outbox ORDER BY id").fetchall()
    return conn.execute(
        "SELECT * FROM outbox WHERE kind = ? ORDER BY id", (kind,)
    ).fetchall()


def _jobs(conn):
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
    ).fetchone()
    if found is None:
        return []
    return conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()


def _allow_claude(conn, monkeypatch):
    conn.execute(
        "INSERT INTO kv (key, value) VALUES ('default_agents', ?)",
        (json.dumps(["claude"]),),
    )
    monkeypatch.setattr(
        bot.capabilities, "can_run_unattended", lambda name: name == "claude"
    )


def _button(row, label):
    keyboard = json.loads(row["buttons_json"])
    for line in keyboard:
        for cell in line:
            if cell["text"] == label:
                return cell
    raise AssertionError(f"no button {label}")


def _capture(conn):
    bot.handle(conn, _message("  A quiet ledger  \nfor receipts"))
    return store.list_ideas(conn)[0]


def test_a_message_produces_one_idea_and_a_card_with_brainstorm_first(conn, token):
    calls = []
    idea = _capture(conn)

    assert idea.source == "telegram"
    assert idea.source_ref == f"{CHAT}:5"
    assert [item.id for item in store.list_ideas(conn)] == [idea.id]
    cards = _outbox(conn, "message")
    assert len(cards) == 1
    assert cards[0]["text"] == "A quiet ledger"
    keyboard = json.loads(cards[0]["buttons_json"])
    assert keyboard[0][0]["text"] == "Brainstorm"
    assert keyboard[0][0]["callback_data"] == f"brainstorm:{idea.id}:0"
    labels = [cell["text"] for cell in keyboard[0]]
    assert labels == ["Brainstorm", "Quick score", "Cancel"]

    assert bot.flush_outbox(conn, http=_http(calls)) == 1
    assert calls[0][0] == "sendMessage"
    assert calls[0][1]["text"] == "A quiet ledger"
    sent = calls[0][1]["reply_markup"]["inline_keyboard"]
    assert sent[0][0]["text"] == "Brainstorm"
    assert bot.flush_outbox(conn, http=_http(calls)) == 0
    assert len(calls) == 1


def test_pressing_quick_score_twice_queues_one_job(conn, token, monkeypatch):
    _allow_claude(conn, monkeypatch)
    idea = _capture(conn)
    data = _button(_outbox(conn, "message")[0], "Quick score")["callback_data"]

    bot.handle(conn, _press(data, "cb-1", update_id=2))
    bot.handle(conn, _press(data, "cb-2", update_id=3))

    jobs = _jobs(conn)
    assert len(jobs) == 1
    assert jobs[0]["idea_id"] == idea.id
    assert jobs[0]["kind"] == "score"
    assert jobs[0]["state"] == "queued"
    texts = [row["text"] for row in _outbox(conn, "message")]
    started = (
        "Quick score started with claude. "
        "Usually 2-5 minutes; I'll message you when it's done."
    )
    assert texts.count(started) == 1
    again = store.get(conn, idea.id)
    assert again.status == "captured"
    assert again.revision == 0


def test_a_stale_button_changes_nothing(conn, token):
    idea = _capture(conn)
    data = _button(_outbox(conn, "message")[0], "Quick score")["callback_data"]
    action, idea_s, revision = data.split(":")
    stale = f"{action}:{idea_s}:{int(revision) + 1}"
    before = (
        idea.status,
        idea.revision,
        idea.original_text,
        len(_jobs(conn)),
    )

    bot.handle(conn, _press(stale, "cb-stale"))

    after = store.get(conn, idea.id)
    assert (after.status, after.revision, after.original_text, len(_jobs(conn))) == before
    assert [row["text"] for row in _outbox(conn, "message")].count(bot.OUT_OF_DATE) == 1
    assert _outbox(conn, "callback") == []


def test_excel_sends_a_document(conn, token, monkeypatch):
    idea = _capture(conn)
    calls = []
    http = _http(calls)
    during = {}
    real_export = bot.xlsx.export

    def wrapped(db):
        during["texts"] = [
            fields.get("text")
            for method, fields, _files in calls
            if method == "sendMessage"
        ]
        return real_export(db)

    monkeypatch.setattr(bot.xlsx, "export", wrapped)
    bot.handle(conn, _press(f"excel:{idea.id}:0", "cb-xl", update_id=8), http=http)
    sent = bot.flush_outbox(conn, http=http)

    documents_sent = [
        (method, fields, files) for method, fields, files in calls if method == "sendDocument"
    ]
    assert sent >= 1
    assert len(documents_sent) == 1
    path = Path(documents_sent[0][2]["document"])
    assert path.suffix == ".xlsx"
    assert path.is_file()
    assert path == paths.workbook() or path.name.startswith("ideas-")
    assert "▶ Excel" in during["texts"]
    assert "Rebuilding your workbook…" in during["texts"]
    assert "Workbook sent ↓" not in during["texts"]
    edits = [
        fields.get("text") for method, fields, _files in calls if method == "editMessageText"
    ]
    assert "Workbook sent ↓" in edits


def test_a_report_sends_word_and_pdf_when_both_export(conn, token, monkeypatch):
    idea = _capture(conn)
    md = paths.reports_dir() / "1-v1.md"
    md.write_text("# Report\n", encoding="utf-8")
    store.add_analysis(
        conn, idea.id, agent="claude", report_path=str(md),
        usefulness=7, complexity_mvp=3, complexity_full=6,
        verdict="YES", confidence="medium",
    )
    docx = paths.documents_dir() / "1-v1.docx"
    pdf = paths.documents_dir() / "1-v1.pdf"
    seen = []

    def fake_export(md_path, **_kwargs):
        seen.append(Path(md_path))
        return documents.Exported(docx=docx, pdf=pdf, notes=[])

    monkeypatch.setattr(bot.documents, "export", fake_export)
    calls = []
    http = _http(calls)

    bot.handle(conn, _press(f"report:{idea.id}:0", "cb-rp", update_id=9), http=http)
    bot.flush_outbox(conn, http=http)

    assert seen == [md]
    sent = [files["document"] for method, _fields, files in calls if method == "sendDocument"]
    assert sent == [str(docx), str(pdf)]


def test_a_report_sends_word_with_the_note_when_pdf_is_missing(conn, token, monkeypatch):
    idea = _capture(conn)
    md = paths.reports_dir() / "1-v1.md"
    md.write_text("# Report\n", encoding="utf-8")
    store.add_analysis(conn, idea.id, agent="claude", report_path=str(md))
    docx = paths.documents_dir() / "1-v1.docx"

    def fake_export(_md_path, **_kwargs):
        return documents.Exported(docx=docx, pdf=None, notes=[documents.PDF_NOTE])

    monkeypatch.setattr(bot.documents, "export", fake_export)
    calls = []
    http = _http(calls)

    bot.handle(conn, _press(f"report:{idea.id}:0", "cb-w", update_id=10), http=http)
    bot.flush_outbox(conn, http=http)

    sent = [(fields, files) for method, fields, files in calls if method == "sendDocument"]
    assert len(sent) == 1
    assert sent[0][1]["document"] == str(docx)
    assert sent[0][0]["caption"] == documents.PDF_NOTE


def test_a_report_sends_markdown_when_both_exports_fail(conn, token, monkeypatch):
    idea = _capture(conn)
    md = paths.reports_dir() / "1-v1.md"
    md.write_text("# Report\n", encoding="utf-8")
    store.add_analysis(conn, idea.id, agent="claude", report_path=str(md))

    def fake_export(_md_path, **_kwargs):
        return documents.Exported(docx=None, pdf=None, notes=[documents.BOTH_FAILED_NOTE])

    monkeypatch.setattr(bot.documents, "export", fake_export)
    calls = []
    http = _http(calls)

    bot.handle(conn, _press(f"report:{idea.id}:0", "cb-md", update_id=11), http=http)
    bot.flush_outbox(conn, http=http)

    sent = [(fields, files) for method, fields, files in calls if method == "sendDocument"]
    assert len(sent) == 1
    assert sent[0][1]["document"] == str(md)
    assert sent[0][0]["caption"] == documents.BOTH_FAILED_NOTE


def test_a_failed_outbox_send_is_retried_later_and_not_duplicated(conn, token, monkeypatch):
    clock = {"now": "2026-10-20T12:00:00.000Z"}
    monkeypatch.setattr(bot, "_now", lambda: clock["now"])
    _capture(conn)
    calls = []
    failing = _http(calls, fail=True)

    assert bot.flush_outbox(conn, http=failing) == 0
    row = _outbox(conn, "message")[0]
    assert row["attempts"] == 1
    assert row["sent_at"] is None
    assert row["next_try_at"] == "2026-10-20T12:01:00.000Z"
    failed_calls = len(calls)

    assert bot.flush_outbox(conn, http=failing) == 0
    assert len(calls) == failed_calls

    clock["now"] = "2026-10-20T12:01:00.000Z"
    ok = _http(calls, fail=False)
    assert bot.flush_outbox(conn, http=ok) == 1
    assert _outbox(conn, "message")[0]["sent_at"] == "2026-10-20T12:01:00.000Z"
    sent_calls = len(calls)

    assert bot.flush_outbox(conn, http=ok) == 0
    assert len(calls) == sent_calls
    assert len(_outbox(conn, "message")) == 1


def test_eight_failures_give_up_with_an_event_note(conn, token, monkeypatch):
    clock = {"i": 0}

    def now():
        stamp = f"2026-01-01T{clock['i'] * 2:02d}:00:00.000Z"
        clock["i"] += 1
        return stamp

    monkeypatch.setattr(bot, "_now", now)
    idea = _capture(conn)
    calls = []
    http = _http(calls, fail=True)

    for _ in range(8):
        assert bot.flush_outbox(conn, http=http) == 0

    row = _outbox(conn, "message")[0]
    assert row["attempts"] == 8
    assert row["sent_at"] is None
    notes = conn.execute(
        "SELECT note, actor, from_status, to_status FROM events WHERE idea_id = ?",
        (idea.id,),
    ).fetchall()
    assert len(notes) == 1
    assert notes[0]["actor"] == "outbox"
    assert notes[0]["from_status"] == "captured"
    assert notes[0]["to_status"] == "captured"
    assert "gave up after 8 attempts" in notes[0]["note"]
    used = len(calls)
    assert bot.flush_outbox(conn, http=http) == 0
    assert len(calls) == used


def test_a_landed_score_sends_the_summary_and_its_buttons(conn, token):
    idea = store.add(
        conn, "A quiet ledger", source="telegram", source_ref=f"{CHAT}:5"
    )
    parsed = report.Report(
        title="Quiet ledger",
        problem="Notes get lost.",
        users="One person.",
        usefulness=7,
        complexity_mvp=3,
        complexity_full=6,
        verdict="YES",
        confidence="medium",
        existing=(
            report.Existing("Alpha", "https://a.example", "narrower"),
            report.Existing("Beta", "https://b.example", "no ledger"),
            report.Existing("Gamma", "https://c.example", "hosted"),
            report.Existing("Delta", "https://d.example", "unrelated"),
        ),
        sources=(report.Source("https://a.example", "Alpha"),),
        deploy="On this Mac.",
        risks=("Small audience.",),
        next_step="Write the capture card.",
    )
    md = paths.reports_dir() / "1-v1.md"
    md.write_text(report.render_markdown(parsed, idea.original_text), encoding="utf-8")
    store.add_analysis(
        conn, idea.id, agent="claude", report_path=str(md),
        usefulness=7, complexity_mvp=3, complexity_full=6,
        verdict="YES", confidence="medium",
    )
    conn.execute("UPDATE ideas SET title = ? WHERE id = ?", ("Quiet ledger", idea.id))

    bot.send_score(conn, idea.id)

    card = _outbox(conn, "message")[0]
    assert "Quiet ledger" in card["text"]
    assert "Usefulness: 7/9" in card["text"]
    assert "MVP complexity: 3/9" in card["text"]
    assert "Full complexity: 6/9" in card["text"]
    assert "Verdict: YES" in card["text"]
    assert "Confidence: medium" in card["text"]
    assert "- Alpha" in card["text"]
    assert "- Beta" in card["text"]
    assert "- Gamma" in card["text"]
    assert "Delta" not in card["text"]
    keyboard = json.loads(card["buttons_json"])
    assert [cell["text"] for cell in keyboard[0]] == ["Brainstorm"]
    assert all(len(line) <= 3 for line in keyboard)
    labels = [cell["text"] for line in keyboard for cell in line]
    assert labels == ["Brainstorm", "Full report", "Refine", "Excel", "Drop"]


def test_help_lists_commands_and_the_settings_template(conn, token):
    bot.handle(conn, _message("/help", message_id=9))
    text = _outbox(conn, "message")[0]["text"]
    for command in (
        "/new", "/list", "/status", "/excel", "/brainstorm",
        "/plan", "/stop", "/drop", "/help",
    ):
        assert command in text
    assert "models: claude, codex, grok" in text
    assert "passes: 1" in text
    assert "final: claude" in text
    assert "backup: codex" in text
    assert "timeout: 30" in text
    assert "plan_reviewer: codex" in text


def test_list_shows_the_ten_newest_ideas_with_status(conn, token):
    for index in range(12):
        store.add(conn, f"idea {index}", source="cli")
    bot.handle(conn, _message("/list", message_id=4))
    lines = _outbox(conn, "message")[0]["text"].splitlines()
    assert len(lines) == 10
    assert lines[0].startswith("12  captured  idea 11")
    assert lines[-1].startswith("3  captured  idea 2")
    assert all("captured" in line for line in lines)


def test_settings_open_the_matching_confirm_card(conn, token):
    _capture(conn)
    bot.handle(conn, _message("models: claude\ntimeout: 30", update_id=6, message_id=6))
    card = _outbox(conn, "message")[-1]
    assert card["text"].startswith("Start brainstorm will use:")
    assert "To change any of these, reply with lines like:" in card["text"]
    assert "models: claude" in card["text"]
    assert "timeout: 30" in card["text"]
    labels = [cell["text"] for cell in json.loads(card["buttons_json"])[0]]
    assert labels == ["Confirm", "Edit", "Cancel"]

    bot.handle(conn, _message("models: banana", update_id=7, message_id=7))
    refusal = _outbox(conn, "message")[-1]
    assert refusal["text"] == "unknown agent banana"
    assert refusal["buttons_json"] is None


def test_refine_stores_the_reply_as_extra_context(conn, token, monkeypatch):
    _allow_claude(conn, monkeypatch)
    idea = _capture(conn)
    store.transition(
        conn, idea.id, "scoring", expected_revision=0, actor="t"
    )
    store.transition(
        conn, idea.id, "scored", expected_revision=1, actor="t"
    )
    idea = store.get(conn, idea.id)

    bot.handle(conn, _press(f"refine:{idea.id}:{idea.revision}", "cb-rf", update_id=12))
    assert "▶ Refine" in [row["text"] for row in _outbox(conn, "message")]
    assert _outbox(conn, "message")[-1]["text"] == "What should I add?"

    bot.handle(conn, _message("mention the ledger", update_id=13, message_id=13))

    updated = store.get(conn, idea.id)
    assert "mention the ledger" in updated.original_text
    notes = conn.execute(
        "SELECT note FROM events WHERE idea_id = ? AND actor = 'telegram'",
        (idea.id,),
    ).fetchall()
    assert [row["note"] for row in notes] == ["mention the ledger"]
    assert len(_jobs(conn)) == 1


def _flat(row):
    return [
        cell["text"]
        for line in json.loads(row["buttons_json"])
        for cell in line
    ]


def _button_rows(conn):
    return [
        row for row in _outbox(conn, "message")
        if row["buttons_json"]
    ]


def test_quick_score_buttons_are_brainstorm_and_cancel(conn, token, monkeypatch):
    _allow_claude(conn, monkeypatch)
    idea = _capture(conn)
    data = _button(_outbox(conn, "message")[0], "Quick score")["callback_data"]

    bot.handle(conn, _press(data, "cb-score", update_id=2))

    card = _button_rows(conn)[-1]
    assert _flat(card) == ["Brainstorm", "Cancel"]
    started = (
        "Quick score started with claude. "
        "Usually 2-5 minutes; I'll message you when it's done."
    )
    assert started in [row["text"] for row in _outbox(conn, "message")]
    assert store.get(conn, idea.id).status == "captured"


def test_cancel_during_scoring_stops_the_job_and_restores_captured(conn, token, monkeypatch):
    _allow_claude(conn, monkeypatch)
    idea = _capture(conn)
    data = _button(_outbox(conn, "message")[0], "Quick score")["callback_data"]
    bot.handle(conn, _press(data, "cb-score", update_id=2))
    cancel = _button(_button_rows(conn)[-1], "Cancel")["callback_data"]

    bot.handle(conn, _press(cancel, "cb-stop", update_id=3))

    job = _jobs(conn)[0]
    assert job["state"] == "cancelled"
    fresh = store.get(conn, idea.id)
    assert fresh.status == "captured"
    assert _flat(_button_rows(conn)[-1]) == ["Brainstorm", "Quick score", "Cancel"]


def _tap_while_scoring(conn, idea, callback_id, label, action):
    """Run the score until it has entered scoring, then tap ``label``."""
    seen = {}

    def run_fn(command, prompt, **kwargs):
        fresh = store.get(conn, idea.id)
        assert fresh.status == "scoring"
        assert fresh.revision > idea.revision
        data = _button(_button_rows(conn)[-1], label)["callback_data"]
        assert data == f"{action}:{fresh.id}:{fresh.revision}"
        seen["data"] = data
        seen["revision"] = fresh.revision
        bot.handle(conn, _press(data, callback_id, update_id=4))
        raise AgentCancelled("stopped")

    with pytest.raises(AgentCancelled):
        analyse.analyse(conn, idea.id, agents=["claude"], run_fn=run_fn)
    return seen


def test_cancel_after_scoring_starts_uses_the_new_revision(conn, token, monkeypatch):
    _allow_claude(conn, monkeypatch)
    idea = _capture(conn)
    data = _button(_outbox(conn, "message")[0], "Quick score")["callback_data"]
    bot.handle(conn, _press(data, "cb-score", update_id=2))
    queued = _button(_button_rows(conn)[-1], "Cancel")["callback_data"]

    tapped = _tap_while_scoring(conn, idea, "cb-stop", "Cancel", "cancel")

    assert tapped["data"] != queued
    assert tapped["data"] == f"cancel:{idea.id}:{tapped['revision']}"
    job = _jobs(conn)[0]
    assert job["state"] == "cancelled"
    fresh = store.get(conn, idea.id)
    assert fresh.status == "captured"
    assert fresh.revision == tapped["revision"] + 1
    assert _flat(_button_rows(conn)[-1]) == ["Brainstorm", "Quick score", "Cancel"]
    assert _button(_button_rows(conn)[-1], "Cancel")["callback_data"].endswith(
        f":{fresh.revision}"
    )


def test_brainstorm_during_scoring_opens_the_settings_card(conn, token, monkeypatch):
    _allow_claude(conn, monkeypatch)
    idea = _capture(conn)
    data = _button(_outbox(conn, "message")[0], "Quick score")["callback_data"]
    bot.handle(conn, _press(data, "cb-score", update_id=2))

    _tap_while_scoring(conn, idea, "cb-brain", "Brainstorm", "brainstorm")

    job = _jobs(conn)[0]
    assert job["state"] == "cancelled"
    fresh = store.get(conn, idea.id)
    assert fresh.status == "brainstorm_configuring"
    card = _button_rows(conn)[-1]
    assert card["text"].startswith("Start brainstorm will use:")
    assert _flat(card) == ["Start", "Edit", "Cancel"]
    assert _button(card, "Start")["callback_data"] == f"start_brainstorm:{fresh.id}:{fresh.revision}"
    assert "can't be brainstormed from scoring" not in [
        row["text"] for row in _outbox(conn, "message")
    ]


def test_brainstorm_during_a_rescore_returns_to_scored(conn, token, monkeypatch):
    _allow_claude(conn, monkeypatch)
    idea = _capture(conn)
    idea = store.transition(
        conn, idea.id, "scoring", expected_revision=idea.revision, actor="t"
    )
    idea = store.transition(
        conn, idea.id, "scored", expected_revision=idea.revision, actor="t"
    )
    bot.handle(conn, _press(f"score:{idea.id}:{idea.revision}", "cb-score", update_id=3))

    _tap_while_scoring(conn, idea, "cb-brain", "Brainstorm", "brainstorm")

    fresh = store.get(conn, idea.id)
    assert fresh.status == "brainstorm_configuring"
    rows = conn.execute(
        "SELECT from_status, to_status FROM events WHERE idea_id = ? ORDER BY id",
        (idea.id,),
    ).fetchall()
    assert (rows[-2]["from_status"], rows[-2]["to_status"]) == ("scoring", "scored")
    assert (rows[-1]["from_status"], rows[-1]["to_status"]) == (
        "scored",
        "brainstorm_configuring",
    )


def test_brainstorm_while_a_score_is_still_queued_stops_that_score(conn, token, monkeypatch):
    _allow_claude(conn, monkeypatch)
    idea = _capture(conn)
    data = _button(_outbox(conn, "message")[0], "Quick score")["callback_data"]
    bot.handle(conn, _press(data, "cb-score", update_id=2))
    assert store.get(conn, idea.id).status == "captured"
    brain = _button(_button_rows(conn)[-1], "Brainstorm")["callback_data"]

    bot.handle(conn, _press(brain, "cb-brain", update_id=3))

    assert _jobs(conn)[0]["state"] == "cancelled"
    fresh = store.get(conn, idea.id)
    assert fresh.status == "brainstorm_configuring"
    assert _button_rows(conn)[-1]["text"].startswith("Start brainstorm will use:")


def test_a_failed_score_puts_captured_buttons_on_the_new_revision(conn, token, monkeypatch):
    _allow_claude(conn, monkeypatch)
    idea = _capture(conn)
    data = _button(_outbox(conn, "message")[0], "Quick score")["callback_data"]
    bot.handle(conn, _press(data, "cb-score", update_id=2))

    def run_fn(command, prompt, **kwargs):
        return SimpleNamespace(exit_code=1, output="rate limit")

    with pytest.raises(analyse.AnalyseError):
        analyse.analyse(conn, idea.id, agents=["claude"], run_fn=run_fn)

    fresh = store.get(conn, idea.id)
    assert fresh.status == "captured"
    assert fresh.revision > idea.revision
    assert _flat(_button_rows(conn)[-1]) == ["Brainstorm", "Quick score", "Cancel"]
    assert _button(_button_rows(conn)[-1], "Quick score")["callback_data"] == (
        f"score:{fresh.id}:{fresh.revision}"
    )


def test_cancel_after_brainstorm_starts_uses_the_new_revision(conn, token, monkeypatch):
    _allow_claude(conn, monkeypatch)
    idea = _capture(conn)
    opened = _button(_outbox(conn, "message")[0], "Brainstorm")["callback_data"]
    bot.handle(conn, _press(opened, "cb-open", update_id=2))
    start = _button(_button_rows(conn)[-1], "Start")["callback_data"]
    bot.handle(conn, _press(start, "cb-start", update_id=3))
    before = store.get(conn, idea.id)
    assert before.status == "brainstorm_configuring"
    queued = _button(_button_rows(conn)[-1], "Cancel")["callback_data"]
    assert queued == f"cancel:{idea.id}:{before.revision}"

    entered = brainstorm._begin(conn, before)

    assert entered.status == "brainstorming"
    assert entered.revision == before.revision + 1
    cancel = _button(_button_rows(conn)[-1], "Cancel")["callback_data"]
    assert cancel == f"cancel:{idea.id}:{entered.revision}"
    assert cancel != queued

    bot.handle(conn, _press(cancel, "cb-stop", update_id=4))

    job = _jobs(conn)[0]
    assert job["state"] == "cancelled"
    fresh = store.get(conn, idea.id)
    assert fresh.status == "captured"
    assert _flat(_button_rows(conn)[-1]) == ["Brainstorm", "Quick score", "Cancel"]
    assert _button(_button_rows(conn)[-1], "Cancel")["callback_data"].endswith(
        f":{fresh.revision}"
    )


def test_every_status_has_the_buttons_for_that_moment():
    expected = {
        "captured": ["Brainstorm", "Quick score", "Cancel"],
        "scoring": ["Brainstorm", "Cancel"],
        "scored": ["Brainstorm", "Full report", "Refine", "Excel", "Drop"],
        "brainstorm_configuring": ["Start", "Edit", "Cancel"],
        "brainstorming": ["Cancel"],
        "brainstormed": ["Spec and plan", "Again", "Drop"],
        "dropped": ["Reopen"],
    }
    for status, labels in expected.items():
        assert [label for label, _action in bot.buttons_for(status)] == labels
        rows = bot._keyboard(bot.buttons_for(status), 1, 0)
        assert rows
        assert all(len(row) <= 3 for row in rows)
        assert all(len(cell["text"]) <= 14 for row in rows for cell in row)
    scored = bot._keyboard(bot.buttons_for("scored"), 1, 0)
    assert [cell["text"] for cell in scored[0]] == ["Brainstorm"]
    assert [cell["text"] for cell in scored[1]] == ["Full report", "Refine", "Excel"]
    assert [cell["text"] for cell in scored[2]] == ["Drop"]


def test_an_older_card_loses_its_buttons_when_a_newer_one_is_sent(conn, token, monkeypatch):
    _allow_claude(conn, monkeypatch)
    _capture(conn)
    data = _button(_outbox(conn, "message")[0], "Brainstorm")["callback_data"]

    bot.handle(conn, _press(data, "cb-open", update_id=2))

    rows = _outbox(conn, "message")
    assert rows[0]["text"] == "Moved to the newer card ↓"
    assert rows[0]["buttons_json"] is None
    assert rows[-1]["buttons_json"]
    assert rows[-1]["text"].startswith("Start brainstorm will use:")


def test_a_failing_edit_does_not_raise(conn, token):
    idea = _capture(conn)
    bot.flush_outbox(conn, http=_http([]))

    def http(method, _token, _fields, _files):
        return {
            "ok": False,
            "error_code": 400,
            "description": "Bad Request: message is too old",
        }

    bot._retire_older(conn, idea.id, http=http)

    row = _outbox(conn, "message")[0]
    assert row["text"] == "Moved to the newer card ↓"
    assert row["buttons_json"] is None


def test_brainstorm_settings_edit_the_same_card(conn, token, monkeypatch):
    conn.execute(
        "INSERT INTO kv (key, value) VALUES ('default_agents', ?)",
        (json.dumps(["claude", "codex", "grok"]),),
    )
    monkeypatch.setattr(bot.capabilities, "can_run_unattended", lambda _name: True)
    _capture(conn)
    data = _button(_outbox(conn, "message")[0], "Brainstorm")["callback_data"]
    bot.handle(conn, _press(data, "cb-open", update_id=2))
    card = _button_rows(conn)[-1]
    assert card["text"].startswith("Start brainstorm will use:")
    assert "To change any of these, reply with lines like:" in card["text"]
    assert "timeout: 15" in card["text"]
    before = len(_outbox(conn))

    bot.handle(conn, _message("timeout: 30", update_id=3, message_id=8))

    assert len(_outbox(conn)) == before
    edited = _button_rows(conn)[-1]
    assert edited["id"] == card["id"]
    assert "timeout: 30" in edited["text"]
    assert "timeout: 15" not in edited["text"]
    assert "Reply `key: value` to change a setting" in edited["text"]
    assert "To change any of these, reply with lines like:" not in edited["text"]


def test_changing_models_does_not_keep_the_old_final_writer(conn, token, monkeypatch):
    conn.execute(
        "INSERT INTO kv (key, value) VALUES ('default_agents', ?)",
        (json.dumps(["claude", "codex", "grok"]),),
    )
    monkeypatch.setattr(bot.capabilities, "can_run_unattended", lambda _name: True)
    _capture(conn)
    data = _button(_outbox(conn, "message")[0], "Brainstorm")["callback_data"]
    bot.handle(conn, _press(data, "cb-open", update_id=2))

    bot.handle(conn, _message("models: codex, grok", update_id=3, message_id=8))

    card = _button_rows(conn)[-1]
    assert "models: codex, grok" in card["text"]
    assert "final: codex" in card["text"]
    assert "claude is no longer a model" in card["text"]
    stored = json.loads(
        conn.execute("SELECT value FROM kv WHERE key = 'telegram_card'").fetchone()[0]
    )
    fields = stored[str(CHAT)]["fields"]
    assert fields["models"] == ["codex", "grok"]
    assert fields["final"] == "codex"

    bot.handle(
        conn,
        _message("models: codex, grok\nfinal: claude", update_id=4, message_id=9),
    )
    card = _button_rows(conn)[-1]
    assert "final: claude (added; it is not one of the models)" in card["text"]
    stored = json.loads(
        conn.execute("SELECT value FROM kv WHERE key = 'telegram_card'").fetchone()[0]
    )
    fields = stored[str(CHAT)]["fields"]
    assert fields["models"] == ["codex", "grok", "claude"]
    assert fields["final"] == "claude"


def test_the_write_up_phase_edits_one_status_line(conn, token):
    idea = store.add(conn, "A quiet ledger", source="telegram", source_ref=f"{CHAT}:5")
    from whyline.ideas import brainstorm

    emit = brainstorm._progress(conn, CHAT, idea.id)
    emit("Researching independently: claude, codex, grok")
    assert _outbox(conn, "message")[0]["text"] == "Researching: claude …, codex, grok"
    emit("Review pass 1 of 1")
    assert _outbox(conn, "message")[0]["text"] == "Review pass 1 of 1: …"
    emit("Final synthesis by codex")
    rows = _outbox(conn, "message")
    assert len(rows) == 1
    assert rows[0]["text"] == "Writing the final synthesis with codex…"


def test_full_report_echoes_and_the_status_ends_sent(conn, token, monkeypatch):
    idea = _capture(conn)
    md = paths.reports_dir() / "1-v1.md"
    md.write_text("# Report\n", encoding="utf-8")
    store.add_analysis(conn, idea.id, agent="claude", report_path=str(md))
    docx = paths.documents_dir() / "1-v1.docx"
    pdf = paths.documents_dir() / "1-v1.pdf"
    calls = []
    http = _http(calls)
    during = {}

    def fake_export(_md_path, **_kwargs):
        during["texts"] = [
            fields.get("text")
            for method, fields, _files in calls
            if method == "sendMessage"
        ]
        return documents.Exported(docx=docx, pdf=pdf, notes=[])

    monkeypatch.setattr(bot.documents, "export", fake_export)
    bot.handle(conn, _press(f"report:{idea.id}:0", "cb-rp2", update_id=20), http=http)
    bot.flush_outbox(conn, http=http)

    texts = [row["text"] for row in _outbox(conn, "message")]
    assert "▶ Full report" in texts
    assert "Report sent ↓" in texts
    docs = [row["document_path"] for row in _outbox(conn, "document")]
    assert docs == [str(docx), str(pdf)]
    assert "▶ Full report" in during["texts"]
    assert "Preparing your report as Word and PDF…" in during["texts"]
    assert "Report sent ↓" not in during["texts"]
    edits = [
        fields.get("text") for method, fields, _files in calls if method == "editMessageText"
    ]
    assert "Report sent ↓" in edits


def test_full_report_names_a_preparation_failure(conn, token, monkeypatch):
    idea = _capture(conn)
    md = paths.reports_dir() / "1-v1.md"
    md.write_text("# Report\n", encoding="utf-8")
    store.add_analysis(conn, idea.id, agent="claude", report_path=str(md))
    calls = []
    http = _http(calls)
    during = {}

    def fake_export(_md_path, **_kwargs):
        during["texts"] = [
            fields.get("text")
            for method, fields, _files in calls
            if method == "sendMessage"
        ]
        raise OSError("disk full")

    monkeypatch.setattr(bot.documents, "export", fake_export)
    bot.handle(conn, _press(f"report:{idea.id}:0", "cb-bad", update_id=21), http=http)

    texts = [row["text"] for row in _outbox(conn, "message")]
    assert "▶ Full report" in texts
    assert "Couldn't prepare the report: disk full" in texts
    assert "Preparing your report as Word and PDF…" in during["texts"]
    edits = [
        fields.get("text") for method, fields, _files in calls if method == "editMessageText"
    ]
    assert "Couldn't prepare the report: disk full" in edits


def test_a_failed_document_send_is_said_in_the_chat(conn, token, monkeypatch):
    idea = _capture(conn)
    md = paths.reports_dir() / "1-v1.md"
    md.write_text("# Report\n", encoding="utf-8")
    store.add_analysis(conn, idea.id, agent="claude", report_path=str(md))
    docx = paths.documents_dir() / "1-v1.docx"
    pdf = paths.documents_dir() / "1-v1.pdf"

    def fake_export(_md_path, **_kwargs):
        return documents.Exported(docx=docx, pdf=pdf, notes=[])

    monkeypatch.setattr(bot.documents, "export", fake_export)

    def http(method, _token, _fields, _files):
        if method == "sendDocument":
            return {"ok": False, "error_code": 400, "description": "upload failed"}
        return {"ok": True, "result": {"message_id": 4}}

    bot.handle(conn, _press(f"report:{idea.id}:0", "cb-send", update_id=22), http=http)

    clock = {"i": 0}

    def now():
        stamp = f"2026-01-01T{clock['i'] * 2:02d}:00:00.000Z"
        clock["i"] += 1
        return stamp

    monkeypatch.setattr(bot, "_now", now)
    bot.flush_outbox(conn, http=http)
    status = [
        row["text"] for row in _outbox(conn, "message")
        if "upload failed" in row["text"] or "Couldn't send the report" in row["text"]
    ]
    assert status
    assert "Couldn't send the report: upload failed" in status[-1]


def test_a_failed_synthesis_send_says_it_will_retry_then_where_it_is_saved(
    conn, token, monkeypatch
):
    idea = store.add(conn, "Ship it", source="telegram", source_ref=f"{CHAT}:9")
    saved = paths.home() / "brainstorms" / f"{idea.id}.md"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text("synthesis\n", encoding="utf-8")
    store.set_paths(conn, idea.id, brainstorm_path=str(saved))
    bot.begin_progress(conn, CHAT, idea.id, "Synthesis written; sending it ↓")
    doc = paths.documents_dir() / "synth.docx"
    doc.write_text("x", encoding="utf-8")
    outbox_id = bot._enqueue(
        conn, CHAT, "document", "Brainstorm", document_path=str(doc), idea_id=idea.id,
    )
    bot.mark_delivery(conn, outbox_id, "synthesis")
    clock = {"i": 0}

    def now():
        stamp = f"2026-01-01T{clock['i'] * 2:02d}:00:00.000Z"
        clock["i"] += 1
        return stamp

    monkeypatch.setattr(bot, "_now", now)

    def http(method, _token, _fields, _files):
        if method == "sendDocument":
            return {"ok": False, "error_code": 400, "description": "upload failed"}
        return {"ok": True, "result": {"message_id": 8}}

    bot.flush_outbox(conn, http=http)
    status = conn.execute(
        "SELECT text FROM outbox WHERE kind = 'message'"
    ).fetchone()["text"]
    assert status == (
        "The synthesis is ready but sending it failed: upload failed; I'll retry"
    )
    for _ in range(7):
        bot.flush_outbox(conn, http=http)
    status = conn.execute(
        "SELECT text FROM outbox WHERE kind = 'message'"
    ).fetchone()["text"]
    assert status == (
        f"Couldn't send the synthesis; it is saved at {saved} on the Mac"
    )


def test_away_text_names_the_gap_the_count_and_the_day_limit():
    start = datetime(2026, 10, 20, 13, 50)
    end = datetime(2026, 10, 20, 15, 10)
    assert bot.away_text(start, end, 0) == (
        "I was offline from 13:50 to 15:10 (Mac asleep or off)."
    )
    assert bot.away_text(start, end, 1) == (
        "I was offline from 13:50 to 15:10 (Mac asleep or off). "
        "Catching up on 1 message."
    )
    assert bot.away_text(start, end, 2) == (
        "I was offline from 13:50 to 15:10 (Mac asleep or off). "
        "Catching up on 2 messages."
    )
    later = start + timedelta(hours=30)
    day = (
        "Telegram keeps undelivered messages for about a day, "
        "so anything older may be lost; please resend it."
    )
    assert bot.away_text(start, later, 2) == (
        "I was offline from 13:50 to 19:50 (Mac asleep or off). "
        f"Catching up on 2 messages. {day}"
    )


def test_an_offline_notice_goes_to_each_allowed_chat_and_leaves_the_card(conn):
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?)",
        (telegram_in.ALLOW_KEY, json.dumps([11, 22])),
    )
    buttons = json.dumps([[{"text": "Drop", "callback_data": "drop:1:1"}]])
    conn.execute(
        """
        INSERT INTO outbox (chat_id, kind, text, buttons_json, attempts)
        VALUES (11, 'message', 'card', ?, 0)
        """,
        (buttons,),
    )
    text = bot.away_text(
        datetime(2026, 10, 20, 13, 50),
        datetime(2026, 10, 20, 15, 10),
        2,
    )

    assert bot.tell_allowed(conn, text) == 2

    rows = conn.execute(
        "SELECT chat_id, text, buttons_json FROM outbox ORDER BY id"
    ).fetchall()
    assert rows[0]["text"] == "card"
    assert rows[0]["buttons_json"] == buttons
    assert [(row["chat_id"], row["text"], row["buttons_json"]) for row in rows[1:]] == [
        (11, text, None),
        (22, text, None),
    ]
