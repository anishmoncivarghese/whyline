import json

import pytest

from whyline import cli
from whyline.agents import deliver, deliveries as dl, telegram


@pytest.fixture
def agent(home, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "jobs.toml").write_text(
        f'name="jobs"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n')
    from whyline.agents import definitions as d, state
    defn = d.load(folder / "jobs.toml", kind="personal")
    state.accept(state.connect(), defn)
    return defn


def main(*argv):
    return cli.main(["agents", *argv])


def test_deliver_sets_and_shows(agent, capsys, monkeypatch):
    monkeypatch.setattr(telegram, "known_chats", lambda: {-100: "Family (group)"})
    assert main("deliver", "jobs", "--email", "a@example.com,b@example.com",
                "--subject", "Daily jobs", "--telegram", "Family (group)",
                "--attach", "md", "--on-failure", "silent") == 0
    got = dl.get(agent.agent_id)
    assert got.email == ("a@example.com", "b@example.com") and got.telegram_chat == -100
    assert got.subject == "Daily jobs" and got.attach == "md" and got.on_failure == "silent"
    capsys.readouterr()
    assert main("deliver", "jobs") == 0
    out = capsys.readouterr().out
    assert "a@example.com, b@example.com" in out and "Family (group)" in out


def test_deliver_rejects_a_bad_address_and_unknown_chat(agent, capsys, monkeypatch):
    monkeypatch.setattr(telegram, "known_chats", lambda: {})
    assert main("deliver", "jobs", "--email", "nope") != 0
    assert "not an email address" in capsys.readouterr().err
    assert main("deliver", "jobs", "--telegram", "Nobody") != 0
    assert "Telegram setup" in capsys.readouterr().err


def test_deliver_clear_and_test(agent, capsys, monkeypatch):
    dl.save(agent.agent_id, dl.Delivery(email=("a@example.com",)))
    monkeypatch.setattr(deliver, "send_test",
                        lambda label, delivery, **k: [{"to": "email", "ok": True, "detail": ""}])
    assert main("deliver", "jobs", "--test") == 0
    assert "email ✓" in capsys.readouterr().out
    assert main("deliver", "jobs", "--clear") == 0
    assert dl.get(agent.agent_id) is None


def test_resend(agent, capsys, monkeypatch):
    from whyline.agents import service
    monkeypatch.setattr(service, "resend",
                        lambda name, root, run_id=None: [{"to": "telegram", "ok": False, "detail": "x"}])
    assert main("resend", "jobs") == 1
    assert "telegram ✗ x" in capsys.readouterr().out


def test_telegram_setup_and_chats(home, capsys, monkeypatch):
    saved = {}
    monkeypatch.setattr(telegram, "check_token", lambda token: "@JobsBot")
    monkeypatch.setattr(telegram, "token_set", lambda token: saved.setdefault("token", token))
    monkeypatch.setattr(telegram, "find_chats", lambda token: {11: "Anish V (private)"})
    answers = iter([""])
    rc = cli._cmd_agents_telegram(
        cli.build_parser().parse_args(["agents", "telegram", "setup"]),
        input_fn=lambda prompt="": next(answers), getpass_fn=lambda prompt="": "123:secret")
    assert rc == 0 and saved["token"] == "123:secret"
    out = capsys.readouterr().out
    assert "Connected to @JobsBot" in out and "Anish V (private)" in out and "123:secret" not in out
    assert main("telegram", "chats") == 0
    assert "Anish V (private)" in capsys.readouterr().out


def test_deliver_command_flag_stays_a_delivery_setting(agent, capsys):
    assert main("deliver", "jobs", "--command", "echo hi") == 0
    assert dl.get(agent.agent_id).command == "echo hi"
    assert "echo hi" in capsys.readouterr().out


def test_history_appends_delivery_status(agent, capsys, monkeypatch):
    from whyline.agents import records, service
    sent = records.RunRecord(
        run_id="r1", agent_id=agent.agent_id, agent_name="jobs", source="schedule",
        started="2026-10-09T07:00:00", cli="codex", outcome="succeeded",
        deliveries=[{"to": "email", "ok": True, "detail": ""},
                    {"to": "telegram", "ok": False, "detail": "no connection"}],
    )
    quiet = records.RunRecord(
        run_id="r0", agent_id=agent.agent_id, agent_name="jobs", source="manual",
        started="2026-10-08T07:00:00", cli="codex", outcome="succeeded",
    )
    monkeypatch.setattr(service, "history", lambda name, root, n=20: [sent, quiet])
    assert main("history", "jobs") == 0
    out = capsys.readouterr().out
    assert "delivered: email ✓  telegram ✗ no connection" in out
    assert "2026-10-08 07:00  manual    codex        succeeded\n" in out
