"""CLI coverage for `whyline idea`."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline import cli
from whyline.agents import launchd, telegram
from whyline.ideas import documents, store, telegram_in


TOKEN = "123:secret"
_WEBHOOK_BLOCKED = (
    "this bot has a webhook, so Telegram refuses polling; "
    "use a separate bot for whyline, or remove the webhook if nothing else uses it"
)
_CONFLICT = "another program is reading this bot's messages, or it has a webhook"


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture(autouse=True)
def _no_live_telegram_token(monkeypatch):
    """Doctor must not call Telegram with this Mac's real bot token."""
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: None)


def invoke(argv, capsys):
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _payload(**overrides):
    data = {
        "title": "Local idea inbox",
        "problem": "Ideas vanish before they are judged.",
        "users": "One person capturing ideas from their phone.",
        "usefulness": 7,
        "complexity_mvp": 4,
        "complexity_full": 8,
        "verdict": "YES",
        "confidence": "medium",
        "existing": [
            {
                "name": "Notion",
                "url": "https://notion.so",
                "how_it_differs": "A workspace, not a scored inbox.",
            }
        ],
        "sources": [{"url": "https://notion.so", "title": "Notion"}],
        "deploy": "On this Mac, beside Whyline.",
        "risks": ["The score depends on the pages opened."],
        "next_step": "Ship capture and one scored report.",
    }
    data.update(overrides)
    return data


def _wrap(payload):
    return f"notes\n```idea-report\n{json.dumps(payload)}\n```\n"


def _runner(replies):
    calls = []
    queue = list(replies)

    def run_fn(command, prompt, **kwargs):
        calls.append({"prompt": prompt, "agent_name": kwargs.get("agent_name")})
        item = queue.pop(0)
        return SimpleNamespace(exit_code=0, output=item)

    return calls, run_fn


def _add(capsys, text):
    code, out, err = invoke(["idea", "add", text], capsys)
    assert code == 0, err
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines[0].isdigit()
    assert Path(lines[-1]).is_file()
    return lines[0]


def test_add_then_list_shows_the_idea(ideas_home, capsys):
    idea_id = _add(capsys, "Ship a local idea inbox")

    code, out, err = invoke(["idea", "list"], capsys)

    assert code == 0, err
    assert f"{idea_id}  captured  Ship a local idea inbox" in out


def test_drop_then_reopen_round_trips(ideas_home, capsys):
    idea_id = _add(capsys, "Round trip")

    code, out, err = invoke(["idea", "drop", idea_id], capsys)
    assert code == 0, err
    assert f"idea {idea_id}  dropped" in out
    code, out, err = invoke(["idea", "list", "--status", "dropped"], capsys)
    assert code == 0, err
    assert f"{idea_id}  dropped  Round trip" in out

    code, out, err = invoke(["idea", "reopen", idea_id], capsys)
    assert code == 0, err
    assert f"idea {idea_id}  captured" in out
    code, out, err = invoke(["idea", "list"], capsys)
    assert f"{idea_id}  captured  Round trip" in out
    code, out, err = invoke(["idea", "list", "--status", "dropped"], capsys)
    assert idea_id not in out
    assert code == 0, err


def test_score_with_a_fake_runner_prints_the_scores(ideas_home, capsys, monkeypatch):
    calls, run_fn = _runner([_wrap(_payload())])
    monkeypatch.setattr("whyline_relay.agents.run", run_fn)
    idea_id = _add(capsys, "Score this idea")

    code, out, err = invoke(["idea", "score", idea_id, "--agent", "claude"], capsys)

    assert code == 0, err
    assert "agent: claude" in out
    assert "usefulness: 7" in out
    assert "complexity_mvp: 4" in out
    assert "complexity_full: 8" in out
    assert "verdict: YES" in out
    assert Path(out.splitlines()[-1]).is_file()
    assert [call["agent_name"] for call in calls] == ["claude"]

    code, shown, err = invoke(["idea", "show", idea_id], capsys)
    assert code == 0, err
    assert "Usefulness: 7/9" in shown
    assert "documents:" in shown
    assert "brainstorm:" in shown
    assert "history:" in shown
    assert "captured -> scoring" in shown
    assert "scoring -> scored" in shown


def test_refine_appends_context_and_scores_again(ideas_home, capsys, monkeypatch):
    calls, run_fn = _runner(
        [
            _wrap(_payload(title="First cut")),
            _wrap(_payload(title="Second cut", usefulness=6, verdict="NOT YET")),
        ]
    )
    monkeypatch.setattr("whyline_relay.agents.run", run_fn)
    idea_id = _add(capsys, "Keep a private ledger")
    code, _out, err = invoke(["idea", "score", idea_id, "--agent", "claude"], capsys)
    assert code == 0, err

    code, out, err = invoke(
        ["idea", "refine", idea_id, "Ship it on this Mac", "--agent", "codex"],
        capsys,
    )

    assert code == 0, err
    assert "agent: codex" in out
    assert "usefulness: 6" in out
    assert "verdict: NOT YET" in out
    assert "Ship it on this Mac" in calls[-1]["prompt"]
    code, shown, err = invoke(["idea", "show", idea_id], capsys)
    assert code == 0, err
    assert "Ship it on this Mac" in shown
    assert "scored -> scored" in shown
    assert "scored -> scoring" in shown
    assert "Second cut" in shown
    assert "# Second cut" in shown or "title: Second cut" in shown


def test_doctor_reports_an_unwritable_workbook_and_a_missing_cupsfilter(
    ideas_home, capsys, monkeypatch
):
    ideas_home.mkdir()
    ideas_home.chmod(0o700)
    workbook = ideas_home / "ideas.xlsx"
    workbook.write_bytes(b"locked")
    workbook.chmod(0o444)
    monkeypatch.setattr(documents, "CUPSFILTER", str(ideas_home / "missing-cupsfilter"))

    code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert code == 1
    assert "workbook is not writable" in text
    assert "cupsfilter is missing" in text
    assert ideas_home.stat().st_mode & 0o777 == 0o700


def test_doctor_reports_a_0755_folder_and_leaves_it(ideas_home, capsys):
    ideas_home.mkdir()
    ideas_home.chmod(0o755)

    code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert code == 1
    assert f"{ideas_home} mode is 0755, expected 0700" in text
    assert ideas_home.stat().st_mode & 0o777 == 0o755
    assert not (ideas_home / "ideas.sqlite3").exists()
    assert list(ideas_home.iterdir()) == []


def test_doctor_does_not_create_an_absent_ledger(ideas_home, capsys):
    ideas_home.mkdir()
    ideas_home.chmod(0o700)
    database = ideas_home / "ideas.sqlite3"

    code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert code == 1
    assert f"ideas database is missing ({database})" in text
    assert not database.exists()
    assert list(ideas_home.iterdir()) == []
    assert ideas_home.stat().st_mode & 0o777 == 0o700


def test_doctor_reads_an_existing_ledger_without_changing_it(ideas_home, capsys):
    ideas_home.mkdir()
    ideas_home.chmod(0o700)
    conn = store.connect()
    conn.close()
    database = ideas_home / "ideas.sqlite3"
    before = database.read_bytes()
    mode = database.stat().st_mode & 0o777

    _code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert "ok     schema: schema version 4" in text
    assert f"ok     folder: {ideas_home} mode 0700" in text
    assert database.read_bytes() == before
    assert database.stat().st_mode & 0o777 == mode
    assert ideas_home.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize(
    "argv",
    [
        ["idea", "show", "42"],
        ["idea", "score", "42"],
        ["idea", "drop", "42"],
        ["idea", "reopen", "42"],
        ["idea", "refine", "42", "more context"],
    ],
)
def test_unknown_id_exits_1(ideas_home, capsys, argv):
    code, _out, err = invoke(argv, capsys)
    assert code == 1
    assert "no idea 42" in err


def test_agents_sets_the_default_used_by_score(ideas_home, capsys, monkeypatch):
    calls, run_fn = _runner([_wrap(_payload())])
    monkeypatch.setattr("whyline_relay.agents.run", run_fn)
    idea_id = _add(capsys, "Use the saved default")
    code, out, err = invoke(["idea", "agents", "codex"], capsys)
    assert code == 0, err
    assert out.splitlines()[0] == "codex"

    code, out, err = invoke(["idea", "score", idea_id], capsys)

    assert code == 0, err
    assert "agent: codex" in out
    assert [call["agent_name"] for call in calls] == ["codex"]


def test_documents_stores_the_format(ideas_home, capsys):
    code, out, err = invoke(["idea", "documents", "word"], capsys)
    assert code == 0, err
    assert out.strip() == "word"
    assert not (ideas_home / "ideas.xlsx").exists()
    conn = store.connect()
    try:
        row = conn.execute(
            "SELECT value FROM kv WHERE key = 'doc_formats'"
        ).fetchone()
    finally:
        conn.close()
    assert row["value"] == "word"


def _answers(monkeypatch, replies):
    prompts = []
    pending = iter(replies)

    def ask(prompt=""):
        prompts.append(prompt)
        return next(pending)

    monkeypatch.setattr("builtins.input", ask)
    return prompts


def _secret(monkeypatch, token=TOKEN):
    seen = []

    def hidden(prompt=""):
        seen.append(prompt)
        return token

    monkeypatch.setattr("getpass.getpass", hidden)
    return seen


def _token_box(monkeypatch, current=None):
    saved = {"token": current}

    def token_get(**_kwargs):
        return saved["token"]

    def token_set(token, **_kwargs):
        saved["token"] = token

    monkeypatch.setattr(telegram, "token_get", token_get)
    monkeypatch.setattr(telegram, "token_set", token_set)
    return saved


def _http(monkeypatch, routes):
    methods = []

    def http(method, _token, _fields, _files):
        methods.append(method)
        if method not in routes:
            raise AssertionError(method)
        item = routes[method]
        if isinstance(item, Exception):
            raise type(item)(str(item))
        return item

    monkeypatch.setattr(telegram, "_http", http)
    return methods


def _quiet_launchd(monkeypatch):
    turned = []
    monkeypatch.setattr(launchd, "supported", lambda: True)
    monkeypatch.setattr(launchd, "turn_on", lambda: turned.append("on"))
    monkeypatch.setattr(
        launchd,
        "status",
        lambda: launchd.Status(loaded=True, plist=None, last_tick=""),
    )
    return turned


def _private_home(tmp_path, monkeypatch):
    import pathlib

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(pathlib.Path, "home", lambda: home)
    return home


def _kv(conn, key, value):
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _ready_inbox(ideas_home, monkeypatch):
    ideas_home.mkdir(exist_ok=True)
    ideas_home.chmod(0o700)
    stub = ideas_home / "cupsfilter"
    stub.write_text("x")
    monkeypatch.setattr(documents, "CUPSFILTER", str(stub))
    return store.connect()


def test_setup_without_a_token_allows_the_only_private_chat_and_turns_the_service_on(
    ideas_home, capsys, monkeypatch, tmp_path
):
    _private_home(tmp_path, monkeypatch)
    saved = _token_box(monkeypatch)
    prompts = _answers(monkeypatch, ["", "", "y"])
    secrets = _secret(monkeypatch)
    methods = _http(
        monkeypatch,
        {
            "getMe": {"ok": True, "result": {"username": "InboxBot"}},
            "getUpdates": {
                "ok": True,
                "result": [
                    {
                        "message": {
                            "chat": {
                                "id": 11,
                                "type": "private",
                                "first_name": "Anish",
                                "last_name": "V",
                            }
                        }
                    },
                    {
                        "message": {
                            "chat": {
                                "id": -100,
                                "type": "supergroup",
                                "title": "Family",
                            }
                        }
                    },
                ],
            },
        },
    )
    turned = _quiet_launchd(monkeypatch)

    code, out, err = invoke(["idea", "telegram", "setup"], capsys)

    text = out + err
    assert code == 0, err
    assert TOKEN not in text
    assert "Connected to @InboxBot" in out
    assert "Keeping it" not in out
    assert secrets and "hidden" in secrets[0]
    assert methods == ["getMe", "getUpdates"]
    allow = [prompt for prompt in prompts if prompt.startswith("Allow ")]
    assert len(allow) == 1
    assert "(11)" in allow[0]
    assert "Family" not in allow[0] and "-100" not in allow[0]
    assert any(prompt.startswith("Turn the inbox on") for prompt in prompts)
    assert "Inbox on." in out
    assert turned == ["on"]
    assert not (ideas_home / "ideas.xlsx").exists()
    conn = store.connect()
    try:
        assert telegram_in.allowed_chats(conn) == [11]
        assert conn.execute(
            "SELECT value FROM kv WHERE key = 'enabled'"
        ).fetchone()[0] == "on"
    finally:
        conn.close()
    assert saved["token"] == TOKEN


def test_setup_with_a_token_asks_which_private_chat_and_never_offers_a_group(
    ideas_home, capsys, monkeypatch
):
    _token_box(monkeypatch, TOKEN)
    prompts = _answers(monkeypatch, ["22", "n"])
    secrets = _secret(monkeypatch)
    methods = _http(
        monkeypatch,
        {"getMe": {"ok": True, "result": {"username": "InboxBot"}}},
    )
    monkeypatch.setattr(
        telegram,
        "known_chats",
        lambda: {
            11: "Anish V (private)",
            22: "Sam Q (private)",
            -100: "Family (group)",
        },
    )
    turned = _quiet_launchd(monkeypatch)

    code, out, err = invoke(["idea", "telegram", "setup"], capsys)

    text = out + err + "\n".join(prompts)
    assert code == 0, err
    assert TOKEN not in text
    assert secrets == []
    assert methods == ["getMe"]
    assert "Keeping it" in out
    assert "@InboxBot" in out
    assert any(
        prompt.startswith("Which private chat id should the inbox read?")
        for prompt in prompts
    )
    assert "Anish V (private)  (11)" in out
    assert "Sam Q (private)  (22)" in out
    assert "Family" not in text and "-100" not in text
    assert "Sam Q (private)  (22)  allowed" in out
    assert "Inbox left off" in out
    assert turned == []
    conn = store.connect()
    try:
        assert telegram_in.allowed_chats(conn) == [22]
        row = conn.execute(
            "SELECT value FROM kv WHERE key = 'enabled'"
        ).fetchone()
    finally:
        conn.close()
    assert row is None


def test_setup_again_changes_nothing(ideas_home, capsys, monkeypatch):
    _token_box(monkeypatch, TOKEN)
    monkeypatch.setattr(
        telegram,
        "known_chats",
        lambda: {
            11: "Anish V (private)",
            22: "Sam Q (private)",
            -100: "Family (group)",
        },
    )
    _http(monkeypatch, {"getMe": {"ok": True, "result": {"username": "InboxBot"}}})
    turned = _quiet_launchd(monkeypatch)
    conn = store.connect()
    try:
        telegram_in.allow(conn, 22)
        _kv(conn, "enabled", "on")
        before = conn.execute(
            "SELECT value FROM kv WHERE key = 'telegram_allow'"
        ).fetchone()[0]
    finally:
        conn.close()

    def refuse(prompt=""):
        raise AssertionError(prompt)

    monkeypatch.setattr("builtins.input", refuse)
    monkeypatch.setattr("getpass.getpass", refuse)
    monkeypatch.setattr(telegram, "token_set", lambda *_args, **_kwargs: refuse())

    code, out, err = invoke(["idea", "telegram", "setup"], capsys)

    assert code == 0, err
    assert TOKEN not in out + err
    assert "Keeping it" in out
    assert "Already allowed: Sam Q (private)  (22)" in out
    assert "Inbox already on." in out
    assert "Family" not in out and "-100" not in out
    assert turned == []
    conn = store.connect()
    try:
        assert conn.execute(
            "SELECT value FROM kv WHERE key = 'telegram_allow'"
        ).fetchone()[0] == before
        assert conn.execute(
            "SELECT value FROM kv WHERE key = 'enabled'"
        ).fetchone()[0] == "on"
    finally:
        conn.close()


def test_agents_saves_without_touching_an_unwritable_workbook(ideas_home, capsys):
    ideas_home.mkdir()
    ideas_home.chmod(0o700)
    workbook = ideas_home / "ideas.xlsx"
    workbook.write_bytes(b"locked")
    workbook.chmod(0o444)
    before = workbook.stat().st_mtime_ns

    code, out, err = invoke(["idea", "agents", "claude", "codex"], capsys)

    assert code == 0, err
    assert out.strip() == "claude codex"
    assert "ideas.xlsx" not in out
    assert workbook.stat().st_mtime_ns == before
    assert workbook.read_bytes() == b"locked"
    conn = store.connect()
    try:
        row = conn.execute(
            "SELECT value FROM kv WHERE key = 'default_agents'"
        ).fetchone()
    finally:
        conn.close()
    assert json.loads(row["value"]) == ["claude", "codex"]


def test_assistant_saves_without_writing_the_workbook(ideas_home, capsys):
    code, out, err = invoke(
        ["idea", "assistant", "grok", "--backup", "codex"], capsys
    )
    assert code == 0, err
    assert out.strip() == "grok codex"
    assert not (ideas_home / "ideas.xlsx").exists()


def test_doctor_telegram_checks_pass(ideas_home, capsys, monkeypatch):
    conn = _ready_inbox(ideas_home, monkeypatch)
    try:
        _kv(conn, telegram_in.ALLOW_KEY, json.dumps([11]))
        _kv(conn, "enabled", "on")
    finally:
        conn.close()
    database = ideas_home / "ideas.sqlite3"
    before = database.read_bytes()
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: TOKEN)
    methods = _http(
        monkeypatch,
        {
            "getMe": {"ok": True, "result": {"username": "InboxBot"}},
            "getWebhookInfo": {"ok": True, "result": {"url": ""}},
        },
    )

    code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert code == 0, err
    assert TOKEN not in text
    assert "ok     telegram token: @InboxBot" in text
    assert "ok     allowed chats: 1" in text
    assert "ok     service: on" in text
    assert "ok     webhook: none" in text
    assert methods == ["getMe", "getWebhookInfo"]
    assert database.read_bytes() == before


def test_doctor_reports_a_missing_telegram_token(ideas_home, capsys, monkeypatch):
    conn = _ready_inbox(ideas_home, monkeypatch)
    try:
        _kv(conn, telegram_in.ALLOW_KEY, json.dumps([11]))
        _kv(conn, "enabled", "on")
    finally:
        conn.close()

    def http(*_args, **_kwargs):
        raise AssertionError("doctor called Telegram")

    monkeypatch.setattr(telegram, "_http", http)

    code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert code == 1
    assert "fail   telegram token: run whyline idea telegram setup" in text
    assert "warn   webhook: no bot token" in text
    assert TOKEN not in text


def test_doctor_reports_no_allowed_chat(ideas_home, capsys, monkeypatch):
    conn = _ready_inbox(ideas_home, monkeypatch)
    try:
        _kv(conn, "enabled", "on")
    finally:
        conn.close()
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: TOKEN)
    _http(
        monkeypatch,
        {
            "getMe": {"ok": True, "result": {"username": "InboxBot"}},
            "getWebhookInfo": {"ok": True, "result": {"url": ""}},
        },
    )

    code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert code == 1
    assert TOKEN not in text
    assert "fail   allowed chats: none" in text
    assert "ok     telegram token: @InboxBot" in text


def test_doctor_warns_when_the_service_is_off(ideas_home, capsys, monkeypatch):
    conn = _ready_inbox(ideas_home, monkeypatch)
    try:
        _kv(conn, telegram_in.ALLOW_KEY, json.dumps([11, 22]))
    finally:
        conn.close()
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: TOKEN)
    _http(
        monkeypatch,
        {
            "getMe": {"ok": True, "result": {"username": "InboxBot"}},
            "getWebhookInfo": {"ok": True, "result": {"url": ""}},
        },
    )

    code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert code == 0, err
    assert TOKEN not in text
    assert "warn   service: off; run whyline idea service on" in text
    assert "fail   service" not in text
    assert "ok     allowed chats: 2" in text


def test_doctor_fails_when_the_bot_has_a_webhook(ideas_home, capsys, monkeypatch):
    conn = _ready_inbox(ideas_home, monkeypatch)
    try:
        _kv(conn, telegram_in.ALLOW_KEY, json.dumps([11]))
        _kv(conn, "enabled", "on")
    finally:
        conn.close()
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: TOKEN)
    methods = _http(
        monkeypatch,
        {
            "getMe": {"ok": True, "result": {"username": "InboxBot"}},
            "getWebhookInfo": {
                "ok": True,
                "result": {"url": f"https://example.test/hook/{TOKEN}"},
            },
        },
    )

    code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert code == 1
    assert TOKEN not in text
    assert f"fail   webhook: {_WEBHOOK_BLOCKED}" in text
    assert "getUpdates" not in methods
    assert "deleteWebhook" not in methods


def test_doctor_warns_when_the_webhook_check_cannot_reach_telegram(
    ideas_home, capsys, monkeypatch
):
    conn = _ready_inbox(ideas_home, monkeypatch)
    try:
        _kv(conn, telegram_in.ALLOW_KEY, json.dumps([11]))
        _kv(conn, "enabled", "on")
    finally:
        conn.close()
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: TOKEN)
    _http(
        monkeypatch,
        {
            "getMe": {"ok": True, "result": {"username": "InboxBot"}},
            "getWebhookInfo": OSError("down"),
        },
    )

    code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert code == 0, err
    assert TOKEN not in text
    assert "warn   webhook: no connection to Telegram" in text


def test_doctor_fails_the_service_check_while_a_poll_error_is_set(
    ideas_home, capsys, monkeypatch
):
    conn = _ready_inbox(ideas_home, monkeypatch)
    try:
        _kv(conn, telegram_in.ALLOW_KEY, json.dumps([11]))
        _kv(conn, "enabled", "on")
        _kv(
            conn,
            telegram_in.LAST_ERROR_KEY,
            json.dumps(
                {
                    "at": "2026-10-20T12:00:00.000Z",
                    "code": 409,
                    "message": _CONFLICT,
                }
            ),
        )
    finally:
        conn.close()
    monkeypatch.setattr(telegram, "token_get", lambda **_kwargs: TOKEN)
    _http(
        monkeypatch,
        {
            "getMe": {"ok": True, "result": {"username": "InboxBot"}},
            "getWebhookInfo": {"ok": True, "result": {"url": ""}},
        },
    )

    code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert code == 1
    assert TOKEN not in text
    assert "fail   service: Last Telegram error at 2026-10-20T12:00:00.000Z: " in text
    assert _CONFLICT in text
    assert "ok     service" not in text
