import json
import pytest

from whyline import cli
from whyline.agents import definitions as d, pagefetch, service, state


def main(*argv):
    return cli.main(["agents", *argv])


@pytest.fixture
def agent(home, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "shop.toml").write_text(
        f'name="shop"\ninstructions="Say the price."\nrunner="claude"\nworkdir={json.dumps(str(work))}\n')
    defn = d.load(folder / "shop.toml", kind="personal")
    state.accept(state.connect(), defn)
    return defn


def _saved(agent):
    return d.load(agent.path, kind="personal")


def _spy(monkeypatch, name):
    calls = []
    real = getattr(service, name)
    monkeypatch.setattr(service, name, lambda *a, **k: calls.append((a, k)) or real(*a, **k))
    return calls


@pytest.mark.parametrize("text,minutes", [("30m", 30), ("2h", 120), ("3d", 4320)])
def test_every_gives_the_right_minutes(agent, monkeypatch, text, minutes):
    calls = _spy(monkeypatch, "save_schedule")
    assert main("schedule", "shop", "--every", text) == 0
    assert calls[0][1]["every_minutes"] == minutes
    assert _saved(agent).trigger.every_minutes == minutes


def test_every_30s_is_refused(agent, capsys):
    before = agent.path.read_text(encoding="utf-8")
    assert main("schedule", "shop", "--every", "30s") == 2
    assert "the shortest interval is 5 minutes" in capsys.readouterr().err
    assert agent.path.read_text(encoding="utf-8") == before


def test_schedule_kinds_call_save_schedule_and_keep_the_rest(agent, monkeypatch):
    calls = _spy(monkeypatch, "save_schedule")
    assert main("schedule", "shop", "--weekly", "mon,thu", "--at", "07:00",
                "--from", "2026-12-01", "--until", "2027-01-31", "--max-runs", "5") == 0
    assert calls[0][1]["kind"] == "weekly" and calls[0][1]["days"] == ("mon", "thu")
    got = _saved(agent)
    assert (got.trigger.kind, got.trigger.at, got.trigger.days) == ("weekly", "07:00", ("mon", "thu"))
    assert (got.trigger.starts, got.trigger.ends, got.trigger.max_runs) == (
        "2026-12-01", "2027-01-31", 5)
    assert got.instructions == "Say the price."
    assert main("schedule", "shop", "--once", "2026-12-25", "--at", "09:30") == 0
    assert (_saved(agent).trigger.kind, _saved(agent).trigger.on) == ("once", "2026-12-25")
    assert main("schedule", "shop", "--daily", "--at", "08:00") == 0
    assert main("schedule", "shop", "--weekdays", "--at", "08:00") == 0
    assert main("schedule", "shop", "--manual") == 0
    assert _saved(agent).trigger.kind == "manual"


def test_schedule_errors_exit_2(agent, capsys):
    assert main("schedule", "shop", "--daily") == 2
    assert "24-hour time" in capsys.readouterr().err
    assert main("schedule", "nobody", "--manual") == 2


def test_watch_saves_gate_and_table_through_the_service(agent, monkeypatch, capsys):
    gate = _spy(monkeypatch, "save_checkin")
    watch = _spy(monkeypatch, "save_watch")
    assert main("watch", "shop", "--url", "https://example.com/p", "--rule", "appears",
                "--text", "in stock", "--between", "<main>", "</main>", "--below", "4000",
                "--stop-first", "--urgent", "--cap", "3") == 0
    assert watch and gate and gate[0][1]["gate"] == "page"
    got = _saved(agent)
    assert got.gate == "page"
    assert got.gate_args == {"url": "https://example.com/p", "rule": "appears",
                             "text": "in stock", "start": "<main>", "end": "</main>"}
    assert (got.watch.stop, got.watch.value, got.watch.urgent, got.watch.daily_cap) == (
        "first", "below 4000", True, 3)
    assert state.check_hash(state.connect(), got) == "active"


def test_watch_needs_url_and_rule(agent, capsys):
    assert main("watch", "shop") == 2
    assert "--url" in capsys.readouterr().err
    assert main("watch", "shop", "--url", "https://example.com", "--rule", "appears") == 2
    assert "text to look for" in capsys.readouterr().err


def test_test_watch_changes_nothing(agent, monkeypatch, home, capsys):
    assert main("watch", "shop", "--url", "https://example.com/p", "--rule", "appears",
                "--text", "sale") == 0
    got = _saved(agent)
    conn = state.connect()
    memory_before = state.watch_memory(conn, got.agent_id)
    state.save_gate_state(conn, got.agent_id, {"seen": ["a"]})
    conn.close()
    gate_before = state.get_gate_state(state.connect(), got.agent_id)
    cache = home / ".whyline" / "agents" / "pages"

    fetched = []

    def fake_get(url, now, opener_, resolve):
        fetched.append(url)
        return pagefetch.Page(url, "ok", text="Big sale " + "x" * 3000)

    monkeypatch.setattr(pagefetch, "_get", fake_get)
    file_before = got.path.read_text(encoding="utf-8")
    result = service.test_watch("shop")
    assert fetched == ["https://example.com/p"]
    assert result.would_fire is True
    assert result.message == "The agent would run and write the message."
    assert len(result.pages[0].text) == 2000 and result.pages[0].state == "ok"
    assert not cache.exists()
    assert state.get_gate_state(state.connect(), got.agent_id) == gate_before
    assert state.watch_memory(state.connect(), got.agent_id) == memory_before
    assert got.path.read_text(encoding="utf-8") == file_before
    from whyline.agents import records
    assert records.list_runs(got.agent_id) == []
    assert main("watch", "test", "shop") == 0
    assert "Would send: yes" in capsys.readouterr().out


def test_test_watch_without_instructions_gives_the_exact_message(home, tmp_path, monkeypatch):
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plain.toml").write_text(
        f'name="plain"\ninstructions=""\nrunner="claude"\nworkdir={json.dumps(str(tmp_path))}\n'
        '[checkin]\ngate="page"\n[checkin.gate_args]\nurl="https://example.com/p"\n'
        'rule="appears"\ntext="hi"\n[watch]\n')
    monkeypatch.setattr(pagefetch, "_get", lambda url, now, o, r: pagefetch.Page(url, "ok", text="hi"))
    result = service.test_watch("plain")
    assert result.would_fire
    assert result.message.startswith("plain\n") and "https://example.com/p" in result.message


def test_test_watch_says_why_a_page_could_not_be_read(agent, monkeypatch):
    service.save_watch("shop", url="https://example.com/p", rule="always")
    monkeypatch.setattr(pagefetch, "_get", lambda url, now, o, r: pagefetch.Page(
        url, "blocked", reason="the site asked for a login"))
    result = service.test_watch("shop")
    assert not result.would_fire and result.message == ""
    assert result.pages[0].state == "blocked"
    assert "the site asked for a login" in result.why


def test_watch_off_restores_a_plain_agent(agent, capsys):
    assert main("watch", "shop", "--url", "https://example.com/p", "--rule", "changed") == 0
    conn = state.connect()
    state.save_gate_state(conn, agent.agent_id, {"seen": ["a"]})
    assert main("watch", "off", "shop") == 0
    got = _saved(agent)
    assert got.watch is None and got.gate == "" and got.gate_args == {}
    assert state.get_gate_state(state.connect(), agent.agent_id) == {}
    assert main("watch", "test", "shop") == 2
    assert "not a watch" in capsys.readouterr().err


def _prior(agent, url="https://example.com/p"):
    conn = state.connect()
    state.save_gate_state(conn, agent.agent_id, {"pages": {
        url: {"hash": "old", "text": "old text", "failures": 0, "changes": 0}}})
    conn.close()


def test_test_watch_reports_missing_markers_as_failed(agent, monkeypatch):
    service.save_watch("shop", url="https://example.com/p", rule="changed",
                       start="<main>", end="</main>")
    _prior(agent)
    monkeypatch.setattr(pagefetch, "_get", lambda url, now, o, r: pagefetch.Page(
        url, "ok", text="no markers here"))
    result = service.test_watch("shop")
    assert result.pages[0].state == "failed"
    assert "start or end text" in result.pages[0].reason
    assert result.pages[0].text != "old text"
    assert not result.would_fire and "start or end text" in result.why


def test_test_watch_exception_with_prior_state_is_failed(agent, monkeypatch):
    service.save_watch("shop", url="https://example.com/p", rule="changed")
    _prior(agent)

    def boom(url, now, o, r):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(pagefetch, "_get", boom)
    result = service.test_watch("shop")
    assert result.pages[0].state == "failed"
    assert "connection reset" in result.pages[0].reason
    assert result.pages[0].text == ""


def test_watch_refuses_repository_agents_before_writing(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    (repo / ".whyline/agents").mkdir(parents=True)
    path = repo / ".whyline/agents/rep.toml"
    path.write_text('name="rep"\ninstructions="Do it."\nrunner="claude"\n')
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="personal agent"):
        service.save_watch("rep", url="https://example.com/p", rule="always", repo_root=repo)
    assert path.read_text(encoding="utf-8") == before
    monkeypatch.setattr(cli, "_repo_root_or_none", lambda: repo)
    assert main("watch", "rep", "--url", "https://example.com/p", "--rule", "always") == 2
    assert "personal agent" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == before


def test_start_again_calls_the_service(agent, monkeypatch, capsys):
    calls = _spy(monkeypatch, "start_again")
    assert main("start-again", "shop") == 2
    assert calls and calls[0][0][0] == "shop"
    assert "not finished" in capsys.readouterr().err
    state.set_status(state.connect(), agent.agent_id, "finished", "")
    assert main("start-again", "shop") == 0
