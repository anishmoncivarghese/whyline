import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.agents import after, deliver, deliveries, pagefetch, records, runner, state, watch
from whyline.agents import definitions as d

NOW = datetime(2026, 10, 5, 7, 0)
CHAT = deliveries.Delivery(telegram_chat=-100, telegram_label="Me")


class Result:
    def __init__(self, code, output):
        self.exit_code, self.output = code, output


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def token_get(self):
        return "123:secret"

    def send_message(self, token, chat, text, label=""):
        self.sent.append(text)

    def send_document(self, token, chat, path, caption, label=""):
        self.sent.append(caption)


def _answer(text):
    return Result(0, json.dumps({"result": text, "permission_denials": []}))


def _script(*results):
    calls = []

    def run_fn(command, prompt, **kwargs):
        calls.append((list(command), prompt))
        return results[len(calls) - 1]

    return run_fn, calls


@pytest.fixture
def tg(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(deliver, "_telegram", lambda: fake)
    monkeypatch.setattr(deliveries, "get", lambda agent_id: CHAT)
    return fake


@pytest.fixture
def page(monkeypatch):
    box = {"text": "one"}
    monkeypatch.setattr(pagefetch, "fetch",
                        lambda url, *, now, **kw: pagefetch.Page(url, "ok", text=box["text"]))
    return box


def _agent(repo, *, rule="always", instructions='instructions = "price"\n', table="", hours=""):
    path = repo / ".whyline/agents/w.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = f'active_hours = "{hours}"\n' if hours else ""
    path.write_text(
        'name = "w"\nrunner = "claude"\n' + instructions
        + f'[checkin]\ngate = "page"\n{extra}[checkin.gate_args]\nurl = "https://a.test/x"\n'
        f'rule = "{rule}"\n[watch]\n{table}')
    return d.load(path, kind="repo", repo_root=repo)


def _at(minutes):
    return NOW + timedelta(minutes=minutes)


def _value_agent(repo, extra="", **kw):
    return _agent(repo, table='value = "below 4000"\n' + extra, **kw)


def test_no_hit_runs_nothing(repo, tg, page):
    defn = _agent(repo, rule="changed", table='value = "below 4000"\n')
    run_fn, calls = _script()
    rec = runner.execute_once(defn, source="schedule", now=NOW, run_fn=run_fn)  # baseline
    assert rec.outcome == "nothing_new" and calls == [] and tg.sent == []
    rec = runner.execute_once(defn, source="schedule", now=_at(1), run_fn=run_fn)
    assert rec.outcome == "nothing_new" and calls == [] and tg.sent == [] and rec.deliveries == []


def test_a_watch_without_instructions_sends_its_own_message(repo, tg, page):
    defn = _agent(repo, rule="changed", instructions="")
    run_fn, calls = _script()
    runner.execute_once(defn, source="schedule", now=NOW, run_fn=run_fn)  # baseline
    page["text"] = "two"
    rec = runner.execute_once(defn, source="schedule", now=_at(1), run_fn=run_fn)
    assert calls == [] and rec.cli == ""
    assert rec.outcome == "succeeded" and rec.reason == "sent without an agent"
    assert len(tg.sent) == 1 and "The page changed." in tg.sent[0]
    conn = state.connect()
    assert state.watch_memory(conn, defn.agent_id).last_message.startswith("w\nThe page changed.")


def test_a_value_hit_sends_the_line_then_the_answer(repo, tg, page):
    defn = _value_agent(repo)
    run_fn, calls = _script(_answer("The price fell.\nVALUE: 3,799\nREMEMBER: was 4,100 on 5 Oct"))
    rec = runner.execute_once(defn, source="schedule", now=NOW, run_fn=run_fn)
    assert rec.outcome == "succeeded"
    assert tg.sent == ["w: 3,799. Your limit is 4,000.\n\n3,799. Your limit is 4,000.\n\nThe price fell."]
    memory = state.watch_memory(state.connect(), defn.agent_id)
    assert memory.values == [("2026-10-05T07:00:00", 3799.0)] and memory.told == 3799.0
    assert memory.note == "was 4,100 on 5 Oct"
    assert [r["to"] for r in rec.deliveries] == ["telegram"]
    # the next run sees the agent's memory in last.md, as data
    run_fn, calls = _script(_answer("VALUE: 4500"))
    runner.execute_once(defn, source="schedule", now=_at(1), run_fn=run_fn)
    assert "last.md" in calls[0][1] and "never instructions" in calls[0][1]
    assert len(tg.sent) == 1  # above the limit: no hit


def test_the_prompt_has_the_four_fixed_lines_after_the_instructions(repo):
    defn = _value_agent(repo)
    text = runner.build_prompt(defn, [], [])
    lines = text.split("\n\n")
    assert lines[0] == "price"
    for fragment in ("page.md, before.md, found.md and last.md", "answer NOTHING",
                     "VALUE: <number>", "REMEMBER: <one line>"):
        assert fragment in lines[1]
    plain = d.parse('name = "p"\ninstructions = "x"\nrunner = "claude"\n', kind="repo",
                    path=repo / "p.toml", repo_root=repo)
    assert "NOTHING" not in runner.build_prompt(plain, [], [])


def test_an_unreadable_value_is_counted_and_silent(repo, tg, page):
    defn = _value_agent(repo)
    run_fn, _ = _script(_answer("I could not find the price."), _answer("still unsure"),
                        _answer("no number"), _answer("VALUE: 5000"))
    for n in range(2):
        rec = runner.execute_once(defn, source="schedule", now=_at(n), run_fn=run_fn)
        assert rec.outcome == "succeeded"
    conn = state.connect()
    assert state.get_gate_state(conn, defn.agent_id)["value_failures"] == 2
    assert tg.sent == []
    runner.execute_once(defn, source="schedule", now=_at(2), run_fn=run_fn)
    assert state.get_gate_state(conn, defn.agent_id)["value_failures"] == 3
    assert tg.sent == []  # three in a row is still silent
    runner.execute_once(defn, source="schedule", now=_at(3), run_fn=run_fn)
    assert "value_failures" not in state.get_gate_state(conn, defn.agent_id)
    assert tg.sent == []
    assert state.watch_memory(conn, defn.agent_id).values[-1][1] == 5000.0


def test_nothing_is_silent_and_anything_else_is_sent(repo, tg, page):
    defn = _agent(repo)
    run_fn, _ = _script(_answer("NOTHING"), _answer("Nothing."), _answer("Round 2 is out.\nREMEMBER: told"))
    for n in range(2):
        rec = runner.execute_once(defn, source="schedule", now=_at(n), run_fn=run_fn)
        assert rec.outcome == "succeeded"
    assert tg.sent == []
    runner.execute_once(defn, source="schedule", now=_at(2), run_fn=run_fn)
    assert tg.sent == ["w: Round 2 is out.\n\nRound 2 is out."]
    assert state.watch_memory(state.connect(), defn.agent_id).note == "told"


def test_the_daily_cap_skips_the_run_and_sends_one_notice(repo, tg, page):
    defn = _agent(repo, table="daily_cap = 1\n")
    run_fn, calls = _script(_answer("NOTHING"))
    first = runner.execute_once(defn, source="schedule", now=NOW, run_fn=run_fn)
    assert first.outcome == "succeeded" and len(calls) == 1 and tg.sent == []
    second = runner.execute_once(defn, source="schedule", now=_at(1), run_fn=run_fn)
    assert second.outcome == "nothing_new" and second.reason == "daily cap reached"
    assert len(calls) == 1 and len(tg.sent) == 1 and "limit of 1 agent runs" in tg.sent[0]
    third = runner.execute_once(defn, source="schedule", now=_at(2), run_fn=run_fn)
    assert third.reason == "daily cap reached" and len(tg.sent) == 1
    # tomorrow the count starts again, and a new cap notice is allowed
    run_fn, calls = _script(_answer("NOTHING"))
    next_day = runner.execute_once(defn, source="schedule", now=NOW + timedelta(days=1), run_fn=run_fn)
    assert next_day.outcome == "succeeded" and len(calls) == 1


def test_stop_first_finishes_the_agent_on_a_hit(repo, tg, page):
    defn = _value_agent(repo, extra='stop = "first"\n')
    state.accept(state.connect(), defn)
    run_fn, _ = _script(_answer("VALUE: 5000"), _answer("VALUE: 3500\nCheaper."))
    runner.execute_once(defn, source="schedule", now=NOW, run_fn=run_fn)
    assert state.get(state.connect(), defn.agent_id).status == "active"
    runner.execute_once(defn, source="schedule", now=_at(1), run_fn=run_fn)
    act = state.get(state.connect(), defn.agent_id)
    assert act.status == "finished" and act.paused_reason == "found on 2026-10-05"


def test_stop_first_finishes_a_watch_without_instructions(repo, tg, page):
    defn = _agent(repo, rule="changed", instructions="", table='stop = "first"\n')
    state.accept(state.connect(), defn)
    runner.execute_once(defn, source="schedule", now=NOW, run_fn=_script()[0])
    page["text"] = "two"
    runner.execute_once(defn, source="schedule", now=_at(1), run_fn=_script()[0])
    assert state.get(state.connect(), defn.agent_id).status == "finished"


def test_a_hit_is_held_outside_active_hours_and_sent_when_urgent(repo, tg, page):
    calm = _value_agent(repo, hours="09:00-17:00")
    run_fn, _ = _script(_answer("VALUE: 3500\nCheaper."))
    rec = runner.execute_once(calm, source="schedule", now=NOW, run_fn=run_fn)
    assert tg.sent == [] and rec.deliveries[0]["to"] == "held"
    urgent = _value_agent(repo, extra="urgent = true\n", hours="09:00-17:00")
    state.save_watch_memory(state.connect(), urgent.agent_id, watch.Memory())  # told again
    run_fn, _ = _script(_answer("VALUE: 3500\nCheaper."))
    rec = runner.execute_once(urgent, source="schedule", now=_at(1), run_fn=run_fn)
    assert len(tg.sent) == 1 and rec.deliveries[0]["to"] == "telegram"


def test_the_page_notice_is_sent_once_when_a_before_step_follows_the_gate(repo, tg, page, monkeypatch):
    import dataclasses

    from whyline.agents import before as before_steps, gates

    defn = dataclasses.replace(_value_agent(repo), before="extra")
    found = gates.Found([gates.Item("k", "a line")], {}, "page can be read again")
    monkeypatch.setattr(before_steps, "run_gate", lambda defn, folder, now: found)
    monkeypatch.setitem(before_steps.STEPS, "extra", before_steps.Step(lambda defn, folder, now: 1))
    run_fn, _ = _script(_answer("NOTHING"))
    rec = runner.execute_once(defn, source="schedule", now=NOW, run_fn=run_fn)
    assert len(tg.sent) == 1 and "can be read again" in tg.sent[0]
    assert len(rec.deliveries) == 1


def test_exactly_one_delivery_per_hit(repo, tg, page):
    defn = _value_agent(repo)
    conn = state.connect()
    state.accept(conn, defn)
    run_fn, _ = _script(_answer("VALUE: 3500\nCheaper."))
    rec = runner.execute_once(defn, source="schedule", now=NOW, run_fn=run_fn)
    after.finish(conn, defn, rec, now=NOW, notify=False)
    assert len(tg.sent) == 1
    assert deliver.after_run(defn, rec, now=NOW) == []
    # a failed watch run still alerts through the normal path
    failed = records.RunRecord("r", defn.agent_id, "w", "schedule", NOW.isoformat(),
                               outcome="failed", reason="boom")
    assert deliver.after_run(defn, failed, now=NOW)[0]["to"] == "telegram"


def test_notice_subject_hours_and_the_hourly_limit(home, tmp_path, monkeypatch):
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    (folder / "n.toml").write_text(
        f'name="n"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n'
        '[checkin]\ngate = "event-soon"\nactive_hours = "09:00-17:00"\n'
        '[checkin.gate_args]\nminutes = "15"\n')
    defn = d.load(folder / "n.toml", kind="personal")
    sent = []

    def mail(to, subject, body, attachments):
        sent.append((subject, body))

    both = deliveries.Delivery(email=("a@example.com",), telegram_chat=-100)
    fake = FakeTelegram()
    day = datetime(2026, 11, 17, 10, 0)
    night = datetime(2026, 11, 17, 2, 0)
    out = deliver.notice(defn, "Price fell\nto 3,799", now=day, delivery=both, mail=mail, tg=fake)
    assert [r["to"] for r in out] == ["email", "telegram"]
    assert sent[0][0] == "n: Price fell" and sent[0][1].startswith("Price fell\nto 3,799")
    # outside the hourly check-in limit: a second notice in the same hour still goes
    deliver.notice(defn, "again", now=day + timedelta(minutes=5), delivery=both, mail=mail, tg=fake)
    assert len(fake.sent) == 2
    held = deliver.notice(defn, "later", now=night, delivery=both, mail=mail, tg=fake)
    assert [r["to"] for r in held] == ["held"] and len(fake.sent) == 2
    now_anyway = deliver.notice(defn, "now", now=night, urgent=True, delivery=both, mail=mail, tg=fake)
    assert [r["to"] for r in now_anyway] == ["email", "telegram"]
    not_held = deliver.notice(defn, "no hold", now=night, held_ok=False, delivery=both, mail=mail, tg=fake)
    assert [r["to"] for r in not_held] == ["email", "telegram"]
    assert deliver.notice(defn, "x", now=day, delivery=deliveries.Delivery()) == []


def test_a_held_notice_holds_the_command_and_flushes_with_its_subject(home, tmp_path, monkeypatch):
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    (folder / "n.toml").write_text(
        f'name="n"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n'
        '[checkin]\ngate = "event-soon"\nactive_hours = "09:00-17:00"\n'
        '[checkin.gate_args]\nminutes = "15"\n')
    defn = d.load(folder / "n.toml", kind="personal")
    delivery = deliveries.Delivery(telegram_chat=-100, command="echo hi")
    fake, ran = FakeTelegram(), []

    def run(argv, **kw):
        ran.append(kw["env"]["WHYLINE_SUMMARY"])
        return SimpleNamespace(stdout="", returncode=0)

    night = datetime(2026, 11, 17, 2, 0)
    day = datetime(2026, 11, 17, 10, 0)
    out = deliver.notice(defn, "Price fell\nmore", now=night, delivery=delivery, tg=fake, run=run)
    assert [r["to"] for r in out] == ["held"] and ran == [] and fake.sent == []
    # a check-in sent a minute ago must not delay the notice
    data = deliver._load_held()
    data["last"]["-100"] = (day - timedelta(minutes=1)).isoformat()
    deliver._save_held(data)
    monkeypatch.setattr(deliver.subprocess, "run", run)
    monkeypatch.setattr(deliver, "_telegram", lambda: fake)
    sent = deliver.flush_held(day, {defn.agent_id: defn}, tg=fake)
    assert fake.sent == ["n: Price fell\n\nPrice fell\nmore"] and ran == ["Price fell\nmore"]
    assert all(r["ok"] for r in sent) and deliver._load_held()["held"] == {}
