"""Cards, buttons, and the retrying outbox."""

import json
from pathlib import Path

import pytest

from whyline.agents import telegram
from whyline.ideas import bot, documents, paths, report, store

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
    assert texts.count("Scoring with claude…") == 1
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
    assert _outbox(conn, "callback")[0]["text"] == "cb-stale"


def test_excel_sends_a_document(conn, token):
    idea = _capture(conn)
    calls = []

    bot.handle(conn, _press(f"excel:{idea.id}:0", "cb-xl", update_id=8))
    sent = bot.flush_outbox(conn, http=_http(calls))

    documents_sent = [
        (method, fields, files) for method, fields, files in calls if method == "sendDocument"
    ]
    assert sent >= 1
    assert len(documents_sent) == 1
    path = Path(documents_sent[0][2]["document"])
    assert path.suffix == ".xlsx"
    assert path.is_file()
    assert path == paths.workbook() or path.name.startswith("ideas-")


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

    bot.handle(conn, _press(f"report:{idea.id}:0", "cb-rp", update_id=9))
    bot.flush_outbox(conn, http=_http(calls))

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

    bot.handle(conn, _press(f"report:{idea.id}:0", "cb-w", update_id=10))
    bot.flush_outbox(conn, http=_http(calls))

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

    bot.handle(conn, _press(f"report:{idea.id}:0", "cb-md", update_id=11))
    bot.flush_outbox(conn, http=_http(calls))

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
    labels = [
        cell["text"]
        for line in json.loads(card["buttons_json"])
        for cell in line
    ]
    assert labels == ["Brainstorm", "Full report", "Refine", "Drop", "Excel"]
    assert labels[0] == "Brainstorm"


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
    assert card["text"].startswith("Brainstorm\n")
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
