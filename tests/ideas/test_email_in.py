"""Tests for email intake: ideas and settings by email (IDEA-21)."""

import json
import re
from email import message_from_string
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline import cli
from whyline.agents import telegram
from whyline.console import adapters
from whyline.ideas import documents, email_in, paths, store, telegram_in
from whyline_relay import brainstorm as relay_brainstorm


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    connection = store.connect()
    email_in.set_authserv(connection, "mx.google.com")
    return connection


HINT = "Enable {agent} in Settings or choose another provider."


@pytest.fixture(autouse=True)
def _isolate_global_account(monkeypatch, tmp_path):
    from whyline import account

    home = tmp_path / "whyline-account"
    home.mkdir()
    monkeypatch.setattr(account.paths, "global_whyline_dir", lambda: home)


def _set_enabled(enabled):
    from whyline import account

    account.save_global({
        name: {"enabled": name in set(enabled), "available": True}
        for name in account.AGENT_ORDER
    })


def _make_email(
    sender: str = "boss@example.com",
    subject: str = "idea",
    body: str = "A local accounting ledger for contractors",
    message_id: str = "<msg-101@example.com>",
    auth: str | list[str] | None = "mx.google.com; dkim=pass header.d=example.com",
) -> str:
    lines = [
        f"From: {sender}",
        f"Subject: {subject}",
        f"Message-ID: {message_id}",
    ]
    if auth is not None:
        headers = auth if isinstance(auth, list) else [auth]
        for header in headers:
            lines.append(f"Authentication-Results: {header}")
    lines.append("")
    lines.append(body)
    return "\n".join(lines)


def _auth_msg(auth, sender: str = "boss@example.com"):
    return message_from_string(_make_email(sender=sender, auth=auth))


def test_allowed_authenticated_sender_creates_idea_with_settings(conn):
    email_in.allow(conn, "boss@example.com")
    sent = []
    raw = _make_email(
        sender="boss@example.com",
        subject="idea",
        body="A tool for scanning invoices\nmodels: codex, grok\npasses: 2\ntimeout: 30",
        message_id="<invoice-1@example.com>",
        auth="mx.google.com; dkim=pass header.d=example.com",
    )
    idea = email_in.handle(conn, raw, mail_fn=lambda *a: sent.append(a))
    assert idea is not None
    assert idea.source == "email"
    assert idea.source_ref == "<invoice-1@example.com>"
    assert idea.status == "captured"
    assert "A tool for scanning invoices" in idea.title

    # Settings stored for idea
    raw_settings = conn.execute(
        "SELECT value FROM kv WHERE key = ?", (f"telegram_settings:{idea.id}",)
    ).fetchone()[0]
    settings = json.loads(raw_settings)
    assert settings["models"] == ["codex", "grok"]
    assert settings["passes"] == 2
    assert str(settings["timeout"]) == "30"

    # Confirmation email sent to sender
    assert len(sent) == 1
    to_addrs, subj, body, attachments = sent[0]
    assert to_addrs == ["boss@example.com"]
    assert "yes " in body
    assert attachments == []


def test_empty_subject_captures_idea(conn):
    email_in.allow(conn, "founder@example.com")
    sent = []
    raw = _make_email(
        sender="founder@example.com",
        subject="",
        body="Track daily habits with friends",
        message_id="<habits-1@example.com>",
        auth="mx.google.com; dkim=pass header.d=example.com",
    )
    idea = email_in.handle(conn, raw, mail_fn=lambda *a: sent.append(a))
    assert idea is not None
    assert idea.source == "email"
    assert idea.status == "captured"
    assert idea.title == "Track daily habits with friends"
    assert len(sent) == 1


def test_repeated_message_id_is_ignored(conn):
    email_in.allow(conn, "boss@example.com")
    sent = []
    raw = _make_email(
        sender="boss@example.com",
        subject="idea",
        body="First idea",
        message_id="<repeat-id@example.com>",
    )
    first = email_in.handle(conn, raw, mail_fn=lambda *a: sent.append(a))
    assert first is not None
    assert len(sent) == 1

    # Ingest the same message-id again
    second = email_in.handle(conn, raw, mail_fn=lambda *a: sent.append(a))
    assert second is None
    # No new idea created, no duplicate email sent
    assert len(store.list_ideas(conn)) == 1
    assert len(sent) == 1


def test_sender_failing_dkim_and_spf_is_ignored(conn):
    email_in.allow(conn, "boss@example.com")
    sent = []
    raw = _make_email(
        sender="boss@example.com",
        subject="idea",
        body="Spoofed email",
        message_id="<spoof@example.com>",
        auth="mx.google.com; dkim=fail; spf=fail",
    )
    idea = email_in.handle(conn, raw, mail_fn=lambda *a: sent.append(a))
    assert idea is None
    assert len(store.list_ideas(conn)) == 0
    assert len(sent) == 0

    # Recorded as handled in inbound
    rows = conn.execute("SELECT * FROM inbound WHERE kind = 'email'").fetchall()
    assert len(rows) == 1
    assert rows[0]["handled"] == 1


def test_sender_without_authentication_results_is_ignored(conn):
    email_in.allow(conn, "boss@example.com")
    sent = []
    raw = _make_email(
        sender="boss@example.com",
        subject="idea",
        body="No auth headers",
        message_id="<noauth@example.com>",
        auth=None,
    )
    idea = email_in.handle(conn, raw, mail_fn=lambda *a: sent.append(a))
    assert idea is None
    assert len(store.list_ideas(conn)) == 0
    assert len(sent) == 0


def test_unallowed_sender_is_ignored(conn):
    sent = []
    raw = _make_email(
        sender="stranger@example.com",
        subject="idea",
        body="Unsolicited idea",
        message_id="<stranger-1@example.com>",
        auth="mx.google.com; dkim=pass header.d=example.com",
    )
    idea = email_in.handle(conn, raw, mail_fn=lambda *a: sent.append(a))
    assert idea is None
    assert len(store.list_ideas(conn)) == 0
    assert len(sent) == 0


def test_forged_header_below_the_real_one_is_ignored():
    msg = _auth_msg(
        [
            "mx.google.com; dkim=fail",
            "mx.google.com; dkim=pass header.d=example.com",
        ]
    )
    assert email_in.is_authenticated(msg, "mx.google.com") is False


def test_header_from_another_authserv_is_ignored():
    msg = _auth_msg(
        [
            "evil.example; dkim=pass header.d=example.com",
            "mx.google.com; dkim=fail",
        ]
    )
    assert email_in.is_authenticated(msg, "mx.google.com") is False
    only_other = _auth_msg("evil.example; dkim=pass header.d=example.com")
    assert email_in.is_authenticated(only_other, "mx.google.com") is False


def test_dkim_pass_for_a_different_domain_is_refused():
    msg = _auth_msg("mx.google.com; dkim=pass header.d=attacker.com")
    assert email_in.is_authenticated(msg, "mx.google.com") is False


def test_dkim_pass_with_an_aligned_subdomain_is_accepted():
    msg = _auth_msg(
        "mx.google.com; dkim=pass header.d=example.com",
        sender="boss@mail.example.com",
    )
    assert email_in.is_authenticated(msg, "mx.google.com") is True


def test_dmarc_pass_is_accepted():
    msg = _auth_msg("mx.google.com; dmarc=pass")
    assert email_in.is_authenticated(msg, "mx.google.com") is True


def test_spf_only_is_refused():
    msg = _auth_msg("mx.google.com; spf=pass")
    assert email_in.is_authenticated(msg, "mx.google.com") is False


def test_unset_authserv_refuses_with_the_note(ideas_home):
    conn = store.connect()
    email_in.allow(conn, "boss@example.com")
    sent = []
    raw = _make_email(
        sender="boss@example.com",
        subject="idea",
        body="Should be refused until authserv is set",
        message_id="<unset-authserv@example.com>",
        auth="mx.google.com; dkim=pass header.d=example.com",
    )
    idea = email_in.handle(conn, raw, mail_fn=lambda *a: sent.append(a))
    assert idea is None
    assert len(store.list_ideas(conn)) == 0
    assert sent == []
    rows = conn.execute("SELECT * FROM inbound WHERE kind = 'email'").fetchall()
    assert len(rows) == 1
    assert rows[0]["handled"] == 1
    assert rows[0]["text"] == email_in.AUTHSERV_UNSET_NOTE


def test_cli_email_authserv_saves_through_set_authserv(conn, capsys, monkeypatch):
    called = []
    real = email_in.set_authserv

    def spy(connection, value):
        called.append(value)
        return real(connection, value)

    monkeypatch.setattr(email_in, "set_authserv", spy)
    assert cli.main(["idea", "email", "authserv", "icloud.com"]) == 0
    out = capsys.readouterr().out
    assert called == ["icloud.com"]
    assert out.strip() == "icloud.com"
    assert cli.main(["idea", "email", "authserv"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == "icloud.com"


def test_yes_code_starts_brainstorm_and_reply_carries_word_and_pdf(conn, monkeypatch):
    email_in.allow(conn, "boss@example.com")
    sent = []
    capture_raw = _make_email(
        sender="boss@example.com",
        subject="idea",
        body="Build a markdown parser\nmodels: claude\ntimeout: 15",
        message_id="<md-1@example.com>",
    )
    idea = email_in.handle(conn, capture_raw, mail_fn=lambda *a: sent.append(a))
    assert idea is not None
    assert len(sent) == 1
    confirmation_body = sent[0][2]
    import re
    match = re.search(r"yes\s+([a-zA-Z0-9]{8})", confirmation_body)
    assert match is not None
    code = match.group(1)

    # Set up fake brainstorm adapter and fake document export
    def fake_brainstorm(root, topic, **kwargs):
        shared = relay_brainstorm.shared_path(root, topic)
        shared.parent.mkdir(parents=True, exist_ok=True)
        shared.write_text("## Final Synthesis\n\nResult.\n", encoding="utf-8")
        return SimpleNamespace(kind="output", text="done")

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)

    docx_file = paths.documents_dir() / "brainstorm.docx"
    pdf_file = paths.documents_dir() / "brainstorm.pdf"
    docx_file.write_bytes(b"PK-docx")
    pdf_file.write_bytes(b"%PDF-sample")

    def fake_export(md_path, **_kwargs):
        return documents.Exported(docx=docx_file, pdf=pdf_file, notes=[])

    monkeypatch.setattr(documents, "export", fake_export)

    # Send confirmation reply
    reply_raw = _make_email(
        sender="boss@example.com",
        subject="Re: idea",
        body=f"yes {code}\n\nOn Fri, wrote:\n> Idea captured...",
        message_id="<md-reply-1@example.com>",
    )
    fresh = email_in.handle(conn, reply_raw, mail_fn=lambda *a: sent.append(a))
    assert fresh is not None
    assert fresh.id == idea.id
    assert fresh.status == "brainstormed"
    assert fresh.brainstorm_path is not None

    # Reply email carrying Word and PDF attachments
    assert len(sent) == 2
    to_addrs, subj, body, attachments = sent[1]
    assert to_addrs == ["boss@example.com"]
    assert docx_file in attachments
    assert pdf_file in attachments


def test_yes_code_does_not_run_a_disabled_provider(conn, monkeypatch):
    from whyline.ideas import brainstorm

    _set_enabled({"claude", "codex"})
    email_in.allow(conn, "boss@example.com")
    sent = []
    capture_raw = _make_email(
        sender="boss@example.com",
        subject="idea",
        body="Build a markdown parser\nmodels: claude\ntimeout: 15",
        message_id="<md-disabled-1@example.com>",
    )
    idea = email_in.handle(conn, capture_raw, mail_fn=lambda *a: sent.append(a))
    assert idea is not None
    match = re.search(r"yes\s+([a-zA-Z0-9]{8})", sent[0][2])
    assert match is not None
    code = match.group(1)

    _set_enabled({"codex"})
    called = []
    monkeypatch.setattr(
        adapters, "run_brainstorm", lambda *a, **k: called.append(True)
    )
    reply_raw = _make_email(
        sender="boss@example.com",
        subject="Re: idea",
        body=f"yes {code}",
        message_id="<md-disabled-reply@example.com>",
    )
    with pytest.raises(brainstorm.BrainstormError, match="Enable claude"):
        email_in.handle(conn, reply_raw, mail_fn=lambda *a: sent.append(a))
    assert called == []
    assert store.get(conn, idea.id).status == "captured"


def test_yes_code_refuses_a_mixed_saved_chain_before_a_subprocess(conn, monkeypatch):
    from whyline.ideas import brainstorm

    _set_enabled({"claude", "grok", "codex"})
    email_in.allow(conn, "boss@example.com")
    sent = []
    capture_raw = _make_email(
        sender="boss@example.com",
        subject="idea",
        body="Build a markdown parser\nmodels: claude, grok\nfinal: claude\nbackup: codex",
        message_id="<md-mixed-1@example.com>",
    )
    idea = email_in.handle(conn, capture_raw, mail_fn=lambda *a: sent.append(a))
    assert idea is not None
    match = re.search(r"yes\s+([a-zA-Z0-9]{8})", sent[0][2])
    assert match is not None
    code = match.group(1)
    stored = json.loads(
        conn.execute(
            "SELECT value FROM kv WHERE key = ?",
            (f"telegram_settings:{idea.id}",),
        ).fetchone()[0]
    )
    assert stored["models"] == ["claude", "grok"]
    assert stored["final"] == "claude"

    _set_enabled({"grok", "codex"})
    called = []
    monkeypatch.setattr(
        adapters, "run_brainstorm", lambda *a, **k: called.append(True)
    )
    reply_raw = _make_email(
        sender="boss@example.com",
        subject="Re: idea",
        body=f"yes {code}",
        message_id="<md-mixed-reply@example.com>",
    )
    with pytest.raises(brainstorm.BrainstormError, match="Enable claude"):
        email_in.handle(conn, reply_raw, mail_fn=lambda *a: sent.append(a))
    assert called == []
    assert store.get(conn, idea.id).status == "captured"


def test_stale_code_does_not_start_brainstorm(conn, monkeypatch):
    email_in.allow(conn, "boss@example.com")
    sent = []
    capture_raw = _make_email(
        sender="boss@example.com",
        subject="idea",
        body="Build a synthesizer",
        message_id="<synth-1@example.com>",
    )
    idea = email_in.handle(conn, capture_raw, mail_fn=lambda *a: sent.append(a))
    assert idea is not None
    match = re.search(r"yes\s+([a-zA-Z0-9]{8})", sent[0][2])
    old_code = match.group(1)

    # Bump revision so old_code becomes stale
    store.bump_revision(conn, idea.id, expected_revision=idea.revision, actor="test")
    fresh = store.get(conn, idea.id)
    assert fresh.revision == idea.revision + 1

    called = []
    monkeypatch.setattr(adapters, "run_brainstorm", lambda *a, **k: called.append(True))

    reply_raw = _make_email(
        sender="boss@example.com",
        subject="Re: idea",
        body=f"yes {old_code}",
        message_id="<synth-reply@example.com>",
    )
    result = email_in.handle(conn, reply_raw, mail_fn=lambda *a: sent.append(a))
    assert result is None
    assert len(called) == 0
    assert store.get(conn, idea.id).status == "captured"
    assert len(sent) == 1  # No second email sent


def test_old_email_code_keys_are_ignored(conn, monkeypatch):
    email_in.allow(conn, "boss@example.com")
    sent = []
    capture_raw = _make_email(
        sender="boss@example.com",
        subject="idea",
        body="Legacy confirmation keys must not start a brainstorm",
        message_id="<legacy-1@example.com>",
    )
    idea = email_in.handle(conn, capture_raw, mail_fn=lambda *a: sent.append(a))
    assert idea is not None
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?)",
        (
            "email_code:deadbeef",
            json.dumps({
                "idea_id": idea.id,
                "revision": idea.revision,
                "action": "start_brainstorm",
                "sender": "boss@example.com",
            }),
        ),
    )
    called = []
    monkeypatch.setattr(adapters, "run_brainstorm", lambda *a, **k: called.append(True))
    reply_raw = _make_email(
        sender="boss@example.com",
        subject="Re: idea",
        body="yes deadbeef",
        message_id="<legacy-reply@example.com>",
    )
    result = email_in.handle(conn, reply_raw, mail_fn=lambda *a: sent.append(a))
    assert result is None
    assert called == []
    assert store.get(conn, idea.id).status == "captured"
    assert len(sent) == 1


def test_wrong_code_changes_nothing(conn, monkeypatch):
    email_in.allow(conn, "boss@example.com")
    sent = []
    capture_raw = _make_email(
        sender="boss@example.com",
        subject="idea",
        body="Another idea",
        message_id="<diff-1@example.com>",
    )
    idea = email_in.handle(conn, capture_raw, mail_fn=lambda *a: sent.append(a))
    assert idea is not None

    called = []
    monkeypatch.setattr(adapters, "run_brainstorm", lambda *a, **k: called.append(True))

    reply_raw = _make_email(
        sender="boss@example.com",
        subject="Re: idea",
        body="yes 99999999",
        message_id="<diff-reply@example.com>",
    )
    result = email_in.handle(conn, reply_raw, mail_fn=lambda *a: sent.append(a))
    assert result is None
    assert len(called) == 0
    assert store.get(conn, idea.id).status == "captured"
    assert len(sent) == 1


def test_ideas_captured_by_email_appear_in_telegram_when_chat_allowed(conn, monkeypatch):
    monkeypatch.setattr(telegram, "known_chats", lambda: {11: "Boss (private)"})
    telegram_in.allow(conn, 11)
    email_in.allow(conn, "boss@example.com")
    raw = _make_email(
        sender="boss@example.com",
        subject="idea",
        body="Podcast transcription service",
        message_id="<pod-1@example.com>",
    )
    idea = email_in.handle(conn, raw, mail_fn=lambda *a: None)
    assert idea is not None

    rows = conn.execute("SELECT * FROM outbox WHERE chat_id = 11").fetchall()
    assert len(rows) == 1
    assert "Podcast transcription service" in rows[0]["text"]
    buttons = json.loads(rows[0]["buttons_json"])
    flattened = [btn["text"] for line in buttons for btn in line]
    assert "Brainstorm" in flattened


def test_cli_email_allow_deny_list(conn, capsys):
    assert cli.main(["idea", "email", "allow", "User@Example.COM"]) == 0
    out = capsys.readouterr().out
    assert "user@example.com  allowed" in out

    assert cli.main(["idea", "email", "list"]) == 0
    out = capsys.readouterr().out
    assert "user@example.com" in out

    assert cli.main(["idea", "email", "deny", "user@example.com"]) == 0
    out = capsys.readouterr().out
    assert "user@example.com  denied" in out

    assert cli.main(["idea", "email", "list"]) == 0
    out = capsys.readouterr().out
    assert "No allowed senders configured." in out


def test_cli_email_allow_rejects_invalid_address(capsys):
    assert cli.main(["idea", "email", "allow", "notanaddress"]) != 0
    err = capsys.readouterr().err
    assert "not an email address" in err


def test_cross_sender_confirmation_is_rejected(conn, monkeypatch):
    email_in.allow(conn, "alice@example.com")
    email_in.allow(conn, "bob@example.com")
    conn.execute(
        "INSERT INTO kv (key, value) VALUES ('default_agents', ?)",
        (json.dumps(["claude"]),),
    )
    monkeypatch.setattr(
        email_in.brainstorm.capabilities,
        "can_run_unattended",
        lambda name: name == "claude",
    )
    sent = []

    capture_raw = _make_email(
        sender="alice@example.com",
        subject="idea",
        body="Alice's confidential idea",
        message_id="<alice-1@example.com>",
    )
    idea = email_in.handle(conn, capture_raw, mail_fn=lambda *a: sent.append(a))
    assert idea is not None
    assert len(sent) == 1
    match = re.search(r"yes\s+([a-zA-Z0-9]{8})", sent[0][2])
    assert match is not None
    code = match.group(1)

    called = []
    monkeypatch.setattr(adapters, "run_brainstorm", lambda *a, **k: called.append(True))

    # Bob (who is also allowed and authenticated) tries to confirm Alice's idea
    bob_reply = _make_email(
        sender="bob@example.com",
        subject="Re: idea",
        body=f"yes {code}",
        message_id="<bob-reply@example.com>",
    )
    result = email_in.handle(conn, bob_reply, mail_fn=lambda *a: sent.append(a))
    # Must be rejected because Bob is not the originating sender
    assert result is None
    assert len(called) == 0
    assert store.get(conn, idea.id).status == "captured"
    assert len(sent) == 1  # No email sent to Bob

    # Alice herself confirms with the same code
    docx_file = paths.documents_dir() / "brainstorm.docx"
    pdf_file = paths.documents_dir() / "brainstorm.pdf"
    docx_file.write_bytes(b"PK-docx")
    pdf_file.write_bytes(b"%PDF-sample")
    monkeypatch.setattr(
        documents,
        "export",
        lambda md_path, **_kwargs: documents.Exported(docx=docx_file, pdf=pdf_file, notes=[]),
    )

    def fake_brainstorm(root, topic, **kwargs):
        shared = relay_brainstorm.shared_path(root, topic)
        shared.parent.mkdir(parents=True, exist_ok=True)
        shared.write_text("## Final Synthesis\n\nResult.\n", encoding="utf-8")
        return SimpleNamespace(kind="output", text="done")

    monkeypatch.setattr(adapters, "run_brainstorm", fake_brainstorm)

    alice_reply = _make_email(
        sender="alice@example.com",
        subject="Re: idea",
        body=f"yes {code}",
        message_id="<alice-reply@example.com>",
    )
    alice_result = email_in.handle(conn, alice_reply, mail_fn=lambda *a: sent.append(a))
    assert alice_result is not None
    assert alice_result.status == "brainstormed"
    assert len(sent) == 2
    assert sent[1][0] == ["alice@example.com"]


def test_mail_production_path_preserves_headers_and_invokes_handler(conn, tmp_path, capsys, monkeypatch):
    from whyline.agents import mail

    # Verify script text for idea intake
    text = mail.script_text("idea", "/opt/bin/whyline")
    assert "/opt/bin/whyline idea email intake --file" in text
    assert "Message-ID" in text
    assert "all headers" in text

    email_in.allow(conn, "founder@example.com")

    # Create an email file matching what Mail.app rule would write
    email_content = _make_email(
        sender="founder@example.com",
        subject="idea",
        body="A production path idea via Mail.app",
        message_id="<prod-msg-42@example.com>",
        auth="mx.google.com; dkim=pass header.d=example.com",
    )
    mail_file = tmp_path / "incoming.eml"
    mail_file.write_text(email_content, encoding="utf-8")

    # 1. Ingest via CLI idea email intake
    sent = []
    monkeypatch.setattr(email_in.mail_send, "send", lambda *a: sent.append(a))
    assert cli.main(["idea", "email", "intake", "--file", str(mail_file)]) == 0

    ideas = store.list_ideas(conn)
    assert len(ideas) == 1
    assert ideas[0].title == "A production path idea via Mail.app"
    assert ideas[0].source == "email"
    assert ideas[0].source_ref == "<prod-msg-42@example.com>"

    # Repeated Message-ID through production path is deduplicated / ignored
    assert cli.main(["idea", "email", "intake", "--file", str(mail_file)]) == 0
    assert len(store.list_ideas(conn)) == 1

    # 2. Ingest via mail.intake() directly
    mail_file2 = tmp_path / "incoming2.eml"
    mail_file2.write_text(
        _make_email(
            sender="founder@example.com",
            subject="idea",
            body="A second production idea",
            message_id="<prod-msg-43@example.com>",
            auth="mx.google.com; dkim=pass header.d=example.com",
        ),
        encoding="utf-8",
    )
    res2 = mail.intake(mail_file2, conn=conn)
    assert res2 is not None
    assert res2.source_ref == "<prod-msg-43@example.com>"
    assert len(store.list_ideas(conn)) == 2

    # 3. Ingest via agents trigger idea --file
    mail_file3 = tmp_path / "incoming3.eml"
    mail_file3.write_text(
        _make_email(
            sender="founder@example.com",
            subject="idea",
            body="A third idea via agents trigger",
            message_id="<prod-msg-44@example.com>",
            auth="mx.google.com; dkim=pass header.d=example.com",
        ),
        encoding="utf-8",
    )
    assert cli.main(["agents", "trigger", "idea", "--file", str(mail_file3)]) == 0
    assert len(store.list_ideas(conn)) == 3
    assert store.list_ideas(conn)[2].source_ref == "<prod-msg-44@example.com>"


def test_cli_email_mail_script(tmp_path, monkeypatch, capsys):
    from whyline.agents import mail

    monkeypatch.setattr(mail, "supported", lambda: True)
    monkeypatch.setattr(mail, "_whyline_path", lambda: "/opt/bin/whyline")
    script_dir = tmp_path / "Library" / "Application Scripts" / "com.apple.mail"
    monkeypatch.setenv("HOME", str(tmp_path))

    assert cli.main(["idea", "email", "mail-script"]) == 0
    out = capsys.readouterr().out
    assert "whyline-idea.applescript" in out
    installed_file = script_dir / "whyline-idea.applescript"
    assert installed_file.is_file()
    text = installed_file.read_text(encoding="utf-8")
    assert "/opt/bin/whyline idea email intake --file" in text
