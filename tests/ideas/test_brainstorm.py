"""Brainstorm in the inbox workspace, with a fake agent runner."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.agents import telegram
from whyline.ideas import bot, brainstorm, documents, paths, store
from whyline_relay.agents import AgentTimeout

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


def _http(calls):
    def http(method, token, fields, files):
        calls.append((method, fields, files))
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


def _labels(row):
    keyboard = json.loads(row["buttons_json"])
    return [cell["text"] for line in keyboard for cell in line]


def _live(conn):
    return [row for row in _outbox(conn) if row["buttons_json"]]


def _card(conn):
    row = conn.execute(
        "SELECT value FROM kv WHERE key = 'telegram_card'"
    ).fetchone()
    return json.loads(row[0])[str(CHAT)]


def _cell(row, label):
    keyboard = json.loads(row["buttons_json"])
    for line in keyboard:
        for cell in line:
            if cell["text"] == label:
                return cell
    raise AssertionError(label)


def _capture(conn, text="Ship a quiet ledger"):
    bot.handle(conn, _message(text))
    return store.list_ideas(conn)[-1]


def _press_brainstorm(conn, idea):
    bot.handle(conn, _press(f"brainstorm:{idea.id}:{idea.revision}", "cb-b", update_id=2))
    return store.get(conn, idea.id)


def _usable(**flags):
    found = {
        "claude": {"available": False},
        "codex": {"available": False},
        "grok": {"available": False},
        "antigravity": {"available": True},
    }
    for name, available in flags.items():
        found[name] = {"available": available, "plan": "test"}
    return found


def _install_detect(monkeypatch, **flags):
    from whyline import account

    monkeypatch.setattr(account, "detect", lambda: _usable(**flags))


def _export(monkeypatch):
    docx = paths.documents_dir() / "synthesis.docx"
    pdf = paths.documents_dir() / "synthesis.pdf"
    docx.write_bytes(b"doc")
    pdf.write_bytes(b"pdf")

    def fake_export(md_path, **_kwargs):
        return documents.Exported(docx=docx, pdf=pdf, notes=[])

    monkeypatch.setattr(brainstorm.documents, "export", fake_export)
    return docx, pdf


def _reply(command, text="ok"):
    if "-o" in command:
        target = Path(command[command.index("-o") + 1])
        target.write_text(text + "\n", encoding="utf-8")
    return SimpleNamespace(exit_code=0, output='{"result": "ok"}')


def _research(cwd, agent):
    target = Path(cwd) / ".whyline" / "relay" / "brainstorm-tmp" / f"{agent}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{agent} looked\n", encoding="utf-8")


def _synthesis(cwd, marker):
    folder = Path(cwd) / "docs" / "brainstorm"
    written = list(folder.glob("*.md"))
    assert written, "the runner had no shared brainstorm document"
    for path in written:
        body = path.read_text(encoding="utf-8")
        if "## Final Synthesis" in body:
            continue
        path.write_text(f"## Final Synthesis\n\n{marker}\n\n{body}", encoding="utf-8")


def _runner(fail_final=None, marker="the synthesis"):
    calls = []

    def run_fn(command, prompt, **kwargs):
        calls.append({"command": list(command), "prompt": prompt, **kwargs})
        agent = kwargs.get("agent_name")
        cwd = kwargs["cwd"]
        if "Final Synthesis" in prompt:
            if fail_final and agent == fail_final:
                raise AgentTimeout(f"{agent} exceeded 1s and was terminated")
            _synthesis(cwd, marker if agent != fail_final else marker)
            return _reply(command, marker)
        _research(cwd, agent)
        return _reply(command)

    return calls, run_fn


def test_defaults_are_every_usable_agent_with_one_pass(conn, monkeypatch):
    _install_detect(monkeypatch, claude=True, codex=True, grok=True)
    request, notes = brainstorm.defaults(conn)

    assert request.models == ("claude", "codex", "grok")
    assert request.passes == 1
    assert request.final == "claude"
    assert request.backup == ()
    assert request.timeout == 15
    assert notes == ()

    idea = _capture(conn)
    shown = _press_brainstorm(conn, idea)
    card = _outbox(conn, "message")[-1]
    assert card["text"].startswith("Start brainstorm will use:")
    assert "To change any of these, reply with lines like:" in card["text"]
    assert "models: claude, codex, grok" in card["text"]
    assert "passes: 1" in card["text"]
    assert "final: claude" in card["text"]
    assert "backup: none" in card["text"]
    assert "timeout: 15" in card["text"]
    assert "backup: codex" in card["text"]
    assert "timeout: 30" in card["text"]
    assert _labels(card) == ["Start", "Edit", "Cancel"]
    assert shown.status == "brainstorm_configuring"


def test_default_agents_fill_models_and_the_rest_is_backup(conn, monkeypatch):
    _install_detect(monkeypatch, claude=True, codex=True, grok=True)
    conn.execute(
        "INSERT INTO kv (key, value) VALUES ('default_agents', ?)",
        (json.dumps(["grok", "antigravity"]),),
    )
    request, notes = brainstorm.defaults(conn)
    assert request.models == ("grok",)
    assert request.passes == 1
    assert request.final == "grok"
    assert request.backup == ()
    assert request.timeout == 15
    assert notes == ("antigravity: not cleared for unattended runs",)


def test_a_settings_message_updates_the_card_or_names_the_line(conn, monkeypatch):
    _install_detect(monkeypatch, claude=True, codex=True)
    idea = _press_brainstorm(conn, _capture(conn))

    bot.handle(conn, _message("passes: 2\ntimeout: none", update_id=3, message_id=6))
    updated = _outbox(conn, "message")[-1]
    assert "passes: 2" in updated["text"]
    assert "timeout: none" in updated["text"]
    assert _labels(updated) == ["Start", "Edit", "Cancel"]
    assert store.get(conn, idea.id).revision == idea.revision

    bot.handle(conn, _message("passes: 9", update_id=4, message_id=7))
    refused = _outbox(conn, "message")[-1]
    assert refused["text"] == "passes: 9"
    assert refused["buttons_json"] is None

    bot.handle(conn, _message("timeout: 10", update_id=5, message_id=8))
    assert _outbox(conn, "message")[-1]["text"] == "timeout: 10"

    bot.handle(conn, _message("final: banana", update_id=6, message_id=9))
    assert _outbox(conn, "message")[-1]["text"] == "final: banana"

    bot.handle(
        conn,
        _message("models: antigravity, claude", update_id=7, message_id=10),
    )
    cards = [row for row in _outbox(conn, "message") if row["buttons_json"]]
    removed = cards[-1]
    assert "antigravity: not cleared for unattended runs" in removed["text"]
    assert "models: claude" in removed["text"]
    assert _labels(removed) == ["Start", "Edit", "Cancel"]
    kept = json.loads(
        conn.execute("SELECT value FROM kv WHERE key = 'telegram_card'").fetchone()[0]
    )
    assert kept[str(CHAT)]["fields"]["models"] == ["claude"]


def test_an_assistant_proposal_updates_the_card(conn, monkeypatch):
    _install_detect(monkeypatch, claude=True, codex=True)
    idea = _press_brainstorm(conn, _capture(conn))
    conn.execute(
        "INSERT INTO kv (key, value) VALUES ('assistant', 'claude')"
    )
    block = (
        "```inbox-proposal\n"
        '{"kind":"brainstorm_settings","fields":{"passes":3,"backup":"codex"},'
        '"summary":"Three passes, codex as backup."}\n'
        "```"
    )

    def run_fn(command, prompt, **kwargs):
        return SimpleNamespace(exit_code=0, output=block)

    bot.handle(conn, _message("use codex for the backup", update_id=8, message_id=11), run_fn=run_fn)
    card = _outbox(conn, "message")[-1]
    assert "passes: 3" in card["text"]
    assert "backup: codex" in card["text"]
    assert _labels(card) == ["Start", "Edit", "Cancel"]
    assert store.get(conn, idea.id).status == "brainstorm_configuring"


def test_brainstorm_writes_inside_the_workspace_only(conn, monkeypatch):
    _export(monkeypatch)
    _install_detect(monkeypatch, claude=True)
    idea = store.add(
        conn,
        "Ship a quiet ledger",
        source="telegram",
        source_ref=f"{CHAT}:5",
    )
    conn.execute(
        """
        INSERT INTO events (idea_id, at, from_status, to_status, actor, note)
        VALUES (?, '2026-10-20T00:00:00.000Z', 'captured', 'captured', 'telegram', ?)
        """,
        (idea.id, "Mention receipts"),
    )
    report = paths.reports_dir() / "score.md"
    report.write_text("# score\n", encoding="utf-8")
    store.add_analysis(conn, idea.id, agent="claude", report_path=str(report))
    calls, run_fn = _runner()
    seen = []
    from whyline.console import adapters

    real = adapters.run_brainstorm

    def spy(root, **kwargs):
        seen.append({"root": root, **kwargs})
        return real(root, **kwargs)

    monkeypatch.setattr(adapters, "run_brainstorm", spy)
    request, _notes = brainstorm.defaults(conn)

    dest = brainstorm.run(conn, idea.id, request, run_fn=run_fn)

    workspace = paths.workspace()
    assert workspace.joinpath(".git").is_dir()
    assert {call["cwd"].resolve() for call in calls} == {workspace.resolve()}
    assert seen[0]["root"].resolve() == workspace.resolve()
    assert seen[0]["agents"] == ["claude"]
    assert seen[0]["passes"] == 1
    assert seen[0]["final_agent"] == "claude"
    assert seen[0]["attachments"] == [report]
    assert seen[0]["timeout_unlimited"] is False
    assert "Ship a quiet ledger" in calls[0]["prompt"]
    assert "Mention receipts" in calls[0]["prompt"]
    shared = workspace / "docs" / "brainstorm"
    assert shared.is_dir()
    assert any(path.is_file() for path in shared.glob("*.md"))
    assert dest == paths.home() / "brainstorms" / f"{idea.id}.md"
    assert dest.is_file()
    assert "## Final Synthesis" in dest.read_text(encoding="utf-8")
    assert store.get(conn, idea.id).brainstorm_path == str(dest)
    assert store.get(conn, idea.id).status == "brainstormed"
    progress = [row["text"] for row in _outbox(conn, "message")]
    assert len(progress) <= 1


def test_timeout_none_reaches_the_runner_as_no_limit(conn, monkeypatch):
    _export(monkeypatch)
    idea = store.add(
        conn, "Unlimited", source="telegram", source_ref=f"{CHAT}:5"
    )
    calls, run_fn = _runner()
    request = brainstorm.Request(("claude",), 1, "claude", (), "none")

    brainstorm.run(conn, idea.id, request, run_fn=run_fn)

    assert calls
    assert {call["timeout_seconds"] for call in calls} == {None}


def test_a_failing_final_writer_hands_the_synthesis_to_the_backup(conn, monkeypatch):
    _export(monkeypatch)
    idea = store.add(
        conn, "Fail over", source="telegram", source_ref=f"{CHAT}:5"
    )
    calls, run_fn = _runner(fail_final="claude", marker="backup synthesis")
    request = brainstorm.Request(("claude",), 1, "claude", ("codex",), 15)

    dest = brainstorm.run(conn, idea.id, request, run_fn=run_fn)

    synthesis_agents = [
        call["agent_name"]
        for call in calls
        if "Final Synthesis" in call["prompt"]
    ]
    assert synthesis_agents == ["claude", "codex"]
    text = dest.read_text(encoding="utf-8")
    assert "backup synthesis" in text
    assert store.get(conn, idea.id).status == "brainstormed"


def test_the_synthesis_is_sent_as_word_and_pdf_with_the_three_buttons(conn, token, monkeypatch):
    docx, pdf = _export(monkeypatch)
    idea = store.add(
        conn, "Send both", source="telegram", source_ref=f"{CHAT}:9"
    )
    _calls, run_fn = _runner(marker="ready to read")
    request = brainstorm.Request(("claude",), 1, "claude", (), 15)

    brainstorm.run(conn, idea.id, request, run_fn=run_fn)
    sent = []
    bot.flush_outbox(conn, http=_http(sent))

    documents_sent = [
        (fields, files) for method, fields, files in sent if method == "sendDocument"
    ]
    assert [files["document"] for _fields, files in documents_sent] == [str(docx), str(pdf)]
    buttons = ["Spec and plan", "Again", "Drop"]
    older, newer = documents_sent
    assert older[0].get("caption") == "Moved to the newer card ↓"
    assert "reply_markup" not in older[0]
    labels = [
        cell["text"]
        for line in newer[0]["reply_markup"]["inline_keyboard"]
        for cell in line
    ]
    assert labels == buttons
    stored = store.get(conn, idea.id)
    assert stored.status == "brainstormed"
    assert stored.brainstorm_path == str(paths.home() / "brainstorms" / f"{idea.id}.md")


def test_again_after_synthesis_opens_one_settings_card(conn, token, monkeypatch):
    """A finished brainstorm remembers the result, so Again does not revive the old card.

    The pre-run settings row is retired when the synthesis is queued. Again
    must open one newer settings card and take the buttons off the result.
    """
    _export(monkeypatch)
    _install_detect(monkeypatch, claude=True)
    monkeypatch.setattr(
        brainstorm.capabilities, "can_run_unattended", lambda name: name == "claude"
    )
    idea = _press_brainstorm(conn, _capture(conn))
    settings_id = _live(conn)[-1]["id"]
    request, _notes = brainstorm.defaults(conn)
    _calls, run_fn = _runner()

    brainstorm.run(conn, idea.id, request, run_fn=run_fn)
    bot.flush_outbox(conn, http=_http([]))

    delivered = _live(conn)
    assert len(delivered) == 1
    result = delivered[0]
    assert result["id"] != settings_id
    assert result["kind"] == "document"
    assert result["sent_at"] is not None
    pointer = _card(conn)
    assert pointer["kind"] == "brainstormed"
    assert pointer["idea_id"] == idea.id
    assert pointer["outbox_id"] == result["id"]
    retired = conn.execute(
        "SELECT * FROM outbox WHERE id = ?", (settings_id,)
    ).fetchone()
    assert retired["buttons_json"] is None
    assert retired["text"] == "Moved to the newer card ↓"

    bot.handle(
        conn,
        _press(_cell(result, "Again")["callback_data"], "cb-again", update_id=20),
    )

    live = _live(conn)
    assert len(live) == 1
    opened = live[0]
    assert opened["id"] not in {settings_id, result["id"]}
    assert opened["kind"] == "message"
    assert opened["text"].startswith("Start brainstorm will use:")
    assert _labels(opened) == ["Start", "Edit", "Cancel"]
    result_after = conn.execute(
        "SELECT * FROM outbox WHERE id = ?", (result["id"],)
    ).fetchone()
    assert result_after["buttons_json"] is None
    settings_after = conn.execute(
        "SELECT * FROM outbox WHERE id = ?", (settings_id,)
    ).fetchone()
    assert settings_after["buttons_json"] is None
    assert settings_after["text"] == "Moved to the newer card ↓"
    pointer = _card(conn)
    assert pointer["kind"] == "brainstorm"
    assert pointer["idea_id"] == idea.id
    assert pointer["outbox_id"] == opened["id"]
    assert store.get(conn, idea.id).status == "brainstorm_configuring"
