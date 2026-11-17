import os
import time

import pytest

from whyline import cli
from whyline.agents import definitions as d, service, state


def main(*argv):
    return cli.main(["agents", *argv])


@pytest.fixture
def agent(home, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "watch.toml").write_text(
        f'name="watch"\ninstructions="x"\nrunner="claude"\nworkdir="{work}"\n')
    defn = d.load(folder / "watch.toml", kind="personal")
    state.accept(state.connect(), defn)
    return defn


def _saved(agent):
    return d.load(agent.path, kind="personal")


def test_add_goes_through_save_checkin_and_stays_accepted(agent, home, monkeypatch, capsys):
    calls = []
    real = service.save_checkin
    monkeypatch.setattr(service, "save_checkin", lambda *a, **k: calls.append((a, k)) or real(*a, **k))
    assert main("checkin", "add", "watch", "--gate", "changed", "--arg", f"path={home}",
                "--every", "30", "--hours", "09:00-17:00 mon-fri", "--silent") == 0
    assert calls and calls[0][0] == ("watch",)
    assert calls[0][1]["gate"] == "changed" and calls[0][1]["every_minutes"] == 30
    got = _saved(agent)
    assert (got.gate, got.active_hours, got.silent) == ("changed", "09:00-17:00 mon-fri", True)
    assert got.gate_args == {"path": str(home.resolve())}
    assert (got.trigger.kind, got.trigger.every_minutes) == ("every", 30)
    assert state.check_hash(state.connect(), got) == "active"
    capsys.readouterr()
    assert main("checkin", "list") == 0
    out = capsys.readouterr().out
    assert "watch" in out and "changed" in out and "30 min" in out and "09:00-17:00 mon-fri" in out


def test_a_bad_argument_shows_the_gates_reason_and_saves_nothing(agent, capsys):
    before = agent.path.read_text()
    assert main("checkin", "add", "watch", "--gate", "event-soon", "--arg", "minutes=soon") != 0
    assert "Minutes ahead must be a whole number" in capsys.readouterr().err
    assert main("checkin", "add", "watch", "--gate", "event-soon", "--arg", "colour=red") != 0
    assert "has no argument colour" in capsys.readouterr().err
    assert agent.path.read_text() == before


def test_test_runs_the_gate_without_changing_seen_state(agent, home, capsys):
    target = home / "notes.txt"
    target.write_text("x")
    assert main("checkin", "add", "watch", "--gate", "changed", "--arg", f"path={target}") == 0
    conn = state.connect()
    old = {"checked": time.time() - 100, "seen": []}
    state.save_gate_state(conn, agent.agent_id, old)
    os.utime(target, None)
    capsys.readouterr()
    assert main("checkin", "test", "watch") == 0
    assert "Changed:" in capsys.readouterr().out
    assert state.get_gate_state(state.connect(), agent.agent_id) == old
    assert main("checkin", "test", "watch") == 0  # still found: nothing was marked seen
    assert "Changed:" in capsys.readouterr().out


def test_test_without_a_check_in_says_so(agent, capsys):
    assert main("checkin", "test", "watch") != 0
    assert "has no check-in" in capsys.readouterr().err


def test_off_restores_a_plain_agent(agent, capsys):
    assert main("checkin", "add", "watch", "--gate", "reminder-overdue", "--hours",
                "09:00-17:00", "--silent") == 0
    state.save_gate_state(state.connect(), agent.agent_id, {"seen": ["a"]})
    assert main("checkin", "off", "watch") == 0
    got = _saved(agent)
    assert (got.gate, got.gate_args, got.active_hours, got.silent) == ("", {}, "", False)
    assert "[checkin" not in agent.path.read_text()
    assert state.get_gate_state(state.connect(), agent.agent_id) == {}
    capsys.readouterr()
    assert main("checkin", "list") == 0
    assert "No agents have a check-in" in capsys.readouterr().out
