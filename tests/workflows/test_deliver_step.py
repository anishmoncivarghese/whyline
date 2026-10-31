import json
import stat
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

import pytest

from whyline.workflows import definitions as d
from whyline.workflows import engine, state
from whyline.workflows.steps.deliver import run_deliver

HEAD = '''
name = "demo"
version = 1

[trigger]
kind = "manual"

[[input]]
name = "who"
default = "ana"
'''

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
CHAT = 555


class FakeTelegram:
    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    def token_get(self):
        return "123:secret"

    def send_message(self, token, chat, text, label=""):
        if self.fail:
            raise RuntimeError(self.fail)
        self.sent.append((chat, text))


@pytest.fixture
def conn(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr("whyline.workflows.steps.deliver._allowed_chats", lambda: [CHAT])
    return state.connect()


def body(to: str, extra: str = "") -> str:
    return (f'[[step]]\nid = "out"\ntype = "deliver"\nto = "{to}"\n'
            f'subject = "Hi {{{{ inputs.who }}}}"\ntext = "Hello {{{{ inputs.who }}}}"\n{extra}')


def go(conn, text, **fakes):
    wf = d.parse(HEAD + text, kind="personal", path=Path("demo.toml"))
    run = state.claim_run(conn, wf, source="manual", dedupe_key="k", inputs={})
    status = engine.execute(run, now=T0, handlers={"deliver": partial(run_deliver, **fakes)})
    return run, status


def step_of(conn, run):
    return state.steps_of(conn, run)[0]


def test_telegram_sends_once_to_the_allowed_chat(conn):
    tg = FakeTelegram()
    run, status = go(conn, body("telegram", f'chat = "{CHAT}"\n'), tg=tg)
    assert status == "succeeded"
    assert tg.sent == [(CHAT, "Hi ana\n\nHello ana")]


def test_telegram_defaults_to_the_only_allowed_chat(conn):
    tg = FakeTelegram()
    _, status = go(conn, body("telegram"), tg=tg)
    assert status == "succeeded" and tg.sent[0][0] == CHAT


def test_email_sends_once_to_the_literal_addresses(conn):
    mails = []
    _, status = go(conn, body("email", 'email = "a@example.com, b@example.com"\n'),
                   mail=lambda *a: mails.append(a))
    assert status == "succeeded" and len(mails) == 1
    to, subject, text, attachments = mails[0]
    assert to == ["a@example.com", "b@example.com"] and subject == "Hi ana"
    assert text.startswith("Hello ana") and attachments == []


def test_file_writes_a_private_report(conn):
    run, status = go(conn, body("file"))
    assert status == "succeeded"
    out = json.loads(Path(step_of(conn, run)["output_path"]).read_text())
    path = Path(out["path"])
    assert path.name == f"{T0.astimezone().strftime('%Y-%m-%d-%H%M')}-{run}.md"
    assert path.parent.name == "demo" and path.read_text() == "Hello ana"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_chat_that_is_not_allowed_is_refused_without_sending(conn):
    tg = FakeTelegram()
    run, status = go(conn, body("telegram", 'chat = "999"\n'), tg=tg)
    assert status == "failed" and tg.sent == []
    assert step_of(conn, run)["reason"] == "chat 999 is not an allowed inbox chat"


def test_a_send_failure_fails_the_step(conn):
    tg = FakeTelegram(fail="network down")
    run, status = go(conn, body("telegram"), tg=tg)
    assert status == "failed"
    assert "network down" in step_of(conn, run)["reason"]
