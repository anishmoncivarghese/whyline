import os
import urllib.error

import pytest

from whyline.agents import telegram as tg

TOKEN = "123:secret"


def fake(responses):
    calls = []

    def http(method, token, fields, files):
        calls.append((method, fields, files))
        item = responses[min(len(calls), len(responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    return http, calls


def test_check_token_ok_and_rejected():
    http, _ = fake([{"ok": True, "result": {"username": "JobsBot"}}])
    assert tg.check_token(TOKEN, http=http) == "@JobsBot"
    http, _ = fake([{"ok": False, "error_code": 401, "description": "Unauthorized"}])
    with pytest.raises(tg.TelegramError, match="token was rejected"):
        tg.check_token(TOKEN, http=http)


def test_find_chats_private_and_group():
    http, _ = fake([{"ok": True, "result": [
        {"message": {"chat": {"id": 11, "type": "private", "first_name": "Anish", "last_name": "V"}}},
        {"my_chat_member": {"chat": {"id": -100, "type": "supergroup", "title": "Family jobs"}}},
        {"message": {"chat": {"id": 11, "type": "private", "first_name": "Anish", "last_name": "V"}}},
    ]}])
    assert tg.find_chats(TOKEN, http=http) == {11: "Anish V (private)", -100: "Family jobs (group)"}


def test_known_chats_are_remembered_privately(home):
    tg.remember_chats({11: "Anish V (private)"})
    assert tg.remember_chats({-100: "Family jobs (group)"}) == {
        11: "Anish V (private)", -100: "Family jobs (group)",
    }
    assert tg.known_chats() == {11: "Anish V (private)", -100: "Family jobs (group)"}
    if os.name != "nt":
        path = home / ".whyline/agents/settings/telegram-chats.toml"
        assert (path.stat().st_mode & 0o777) == 0o600


def test_send_document_is_plain_text_and_caption_limited(tmp_path):
    report = tmp_path / "jobs.docx"
    report.write_bytes(b"PK")
    http, calls = fake([{"ok": True, "result": {}}])
    tg.send_document(TOKEN, -100, report, "x" * 3000, http=http)
    method, fields, files = calls[0]
    assert method == "sendDocument" and files == {"document": report}
    assert len(fields["caption"]) == tg.CAPTION_LIMIT and "parse_mode" not in fields


def test_a_chat_the_bot_cannot_reach():
    http, _ = fake([{"ok": False, "error_code": 403, "description": "Forbidden: bot was kicked"}])
    with pytest.raises(tg.TelegramError, match="can't reach Family jobs"):
        tg.send_message(TOKEN, -100, "hi", label="Family jobs (group)", http=http)


def test_one_retry_on_a_network_error_then_no_connection():
    slept = []
    http, calls = fake([urllib.error.URLError("down"), {"ok": True, "result": {}}])
    tg.send_message(TOKEN, 1, "hi", http=http, sleep=slept.append)
    assert len(calls) == 2 and slept == [30]
    http, _ = fake([OSError("down"), OSError("down")])
    with pytest.raises(tg.TelegramError, match="no connection"):
        tg.send_message(TOKEN, 1, "hi", http=http, sleep=lambda s: None)


def test_the_token_is_redacted_from_errors():
    http, _ = fake([{"ok": False, "error_code": 400,
                     "description": f"Bad Request: url /bot{TOKEN}/sendMessage"}])
    with pytest.raises(tg.TelegramError) as raised:
        tg.send_message(TOKEN, 1, "hi", http=http)
    assert TOKEN not in str(raised.value) and "•••" in str(raised.value)


def test_keychain_token_on_mac():
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        class R:
            returncode = 0
            stdout = "123:secret\n"
        return R()

    tg.token_set(TOKEN, run=run, mac=True)
    assert calls[0][:2] == ["security", "add-generic-password"] and "whyline-telegram" in calls[0]
    assert tg.token_get(run=run, mac=True) == TOKEN


def test_token_file_off_mac(home):
    assert tg.token_get(mac=False) is None
    tg.token_set(TOKEN, mac=False)
    assert tg.token_get(mac=False) == TOKEN
    if os.name != "nt":
        assert ((home / ".whyline/agents/settings/telegram-token").stat().st_mode & 0o777) == 0o600
