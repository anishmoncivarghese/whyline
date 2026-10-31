import json
import re
from datetime import datetime, time, timedelta, timezone
from functools import partial
from pathlib import Path

import pytest

from whyline import account
from whyline.workflows import definitions as d
from whyline.workflows import engine, settings, state
from whyline.workflows.steps.agent import run_agent

HEAD = '''
name = "demo"
version = 1

[trigger]
kind = "manual"
'''

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

TEXT = '''
[[step]]
id = "ask"
type = "agent"
runner = "claude"
instructions = "Summarise {braces} and $HOME."
inputs = ["first {{ inputs.who }}", "second"]
'''

JSON_STEP = TEXT + '''output = "json"
[step.schema]
type = "object"
required = ["title"]
[step.schema.properties.title]
type = "string"
'''

LIMIT = json.dumps({"is_error": True, "result": "You've hit your limit · resets 3pm"})


class Result:
    def __init__(self, code, output):
        self.exit_code, self.output = code, output


def ok(text):
    return Result(0, json.dumps({"result": text, "permission_denials": []}))


class Fake:
    """A scripted run_fn that also records the prompt and the input files it could see."""

    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, command, prompt, **kwargs):
        files = {Path(p).name: (Path(kwargs["cwd"]) / p).read_text()
                 for p in re.findall(r"^- (\S*input-\d+\.md)$", prompt, re.M)}
        self.calls.append({"command": list(command), "prompt": prompt, "files": files})
        return self.results[len(self.calls) - 1]


@pytest.fixture
def conn(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return state.connect()


def make_run(conn, body: str, key: str = "k1", inputs: dict | None = None) -> int:
    wf = d.parse(HEAD + body, kind="personal", path=Path("demo.toml"))
    return state.claim_run(conn, wf, source="manual", dedupe_key=key, inputs=inputs or {})


def go(run_id, fake):
    return engine.execute(run_id, now=T0, handlers={"agent": partial(run_agent, run_fn=fake)})


def run_row(conn, run_id):
    return conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()


def step_row(conn, run_id):
    return state.steps_of(conn, run_id)[0]


def output(row):
    return json.loads(Path(row["output_path"]).read_text())


def test_inputs_land_as_files_and_instructions_stay_literal(conn):
    run = make_run(conn, TEXT, inputs={"who": "ana"})
    fake = Fake(ok("All quiet."))
    assert go(run, fake) == "succeeded"
    call = fake.calls[0]
    assert call["files"] == {"input-1.md": "first ana", "input-2.md": "second"}
    assert call["prompt"].startswith("Summarise {braces} and $HOME.")


def test_text_output_records_the_provider(conn):
    run = make_run(conn, TEXT, inputs={"who": "ana"})
    status = go(run, Fake(ok("All quiet.")))
    assert status == "succeeded", run_row(conn, run)["reason"]
    row = step_row(conn, run)
    out = output(row)
    assert out["output"] == "All quiet."
    assert out["provider"] == "claude" and out["run_id"]
    assert row["provider"] == "claude"


def test_json_output_from_a_fenced_block(conn):
    run = make_run(conn, JSON_STEP, inputs={"who": "ana"})
    fake = Fake(ok('Here you go:\n```json\n{"title": "Hi"}\n```\n'))
    assert go(run, fake) == "succeeded"
    assert output(step_row(conn, run))["output"] == {"title": "Hi"}
    assert len(fake.calls) == 1


def test_json_output_from_the_whole_text(conn):
    run = make_run(conn, JSON_STEP, inputs={"who": "ana"})
    assert go(run, Fake(ok('{"title": "Hi"}'))) == "succeeded"
    assert output(step_row(conn, run))["output"] == {"title": "Hi"}


def test_a_repair_turn_that_succeeds(conn):
    run = make_run(conn, JSON_STEP, inputs={"who": "ana"})
    fake = Fake(ok("no json here"), ok('{"title": "Fixed"}'))
    assert go(run, fake) == "succeeded"
    assert output(step_row(conn, run))["output"] == {"title": "Fixed"}
    repair = fake.calls[1]["prompt"]
    assert "Reply with only JSON matching this schema. The last answer failed: not valid JSON" in repair
    assert fake.calls[1]["files"]["input-3.md"] == "no json here"


def test_a_repair_that_fails_ends_the_run(conn):
    run = make_run(conn, JSON_STEP, inputs={"who": "ana"})
    fake = Fake(ok('{"title": 3}'), ok('{"other": 1}'))
    assert go(run, fake) == "failed"
    assert len(fake.calls) == 2
    assert "missing required field title" in run_row(conn, run)["reason"]


def test_a_usage_limit_waits_with_the_reset_time(conn):
    run = make_run(conn, TEXT, inputs={"who": "ana"})
    assert go(run, Fake(Result(1, LIMIT))) == "waiting"
    row = run_row(conn, run)
    assert row["reason"] == "usage_limit"
    wake = datetime.fromisoformat(row["wake_at"])
    assert wake.astimezone().strftime("%H:%M") == "15:00"
    assert T0 < wake <= T0 + timedelta(days=1, hours=1)


def test_a_usage_limit_without_a_reset_time_waits_an_hour():
    from whyline.agents.records import RunRecord
    from whyline.workflows.steps.agent import _limit_wake

    record = RunRecord("r", "a", "a", "workflow", "2026-01-01T12:00:00",
                       attempts=[{"cli": "claude", "outcome": "usage_limit", "reason": "slow down"}])
    assert _limit_wake(record, T0) == T0 + timedelta(hours=1)
    record.attempts[-1]["reason"] = "usage_limit until 15:00"
    assert _limit_wake(record, T0).astimezone().strftime("%H:%M") == "15:00"


def started_today(conn, count):
    for number in range(count):
        earlier = make_run(conn, TEXT, key=f"early{number}", inputs={"who": "x"})
        state.set_step(conn, earlier, "ask", status="succeeded", started=T0.isoformat())


def test_a_cap_of_zero_never_blocks(conn):
    settings.save(settings.Settings(daily_agent_cap=0))
    started_today(conn, 5)
    run = make_run(conn, TEXT, key="now", inputs={"who": "ana"})
    assert go(run, Fake(ok("fine"))) == "succeeded"


def test_the_third_agent_step_today_waits_until_midnight(conn):
    settings.save(settings.Settings(daily_agent_cap=2))
    started_today(conn, 2)
    run = make_run(conn, TEXT, key="now", inputs={"who": "ana"})
    fake = Fake(ok("never asked"))
    assert go(run, fake) == "waiting"
    assert fake.calls == []
    row = run_row(conn, run)
    assert row["reason"] == "daily_cap"
    local = T0.astimezone()
    midnight = datetime.combine(local.date() + timedelta(days=1), time(0, 0)).astimezone()
    assert datetime.fromisoformat(row["wake_at"]) == midnight


def test_the_second_agent_step_today_still_runs(conn):
    settings.save(settings.Settings(daily_agent_cap=2))
    started_today(conn, 1)
    run = make_run(conn, TEXT, key="now", inputs={"who": "ana"})
    assert go(run, Fake(ok("fine"))) == "succeeded"


def test_a_disabled_provider_fails_with_the_settings_hint(conn):
    account.save_global({name: {"enabled": False, "available": True}
                         for name in account.AGENT_ORDER})
    run = make_run(conn, TEXT, inputs={"who": "ana"})
    fake = Fake(ok("should not run"))
    assert go(run, fake) == "failed"
    assert fake.calls == []
    assert "Enable claude in Settings or choose another provider." in run_row(conn, run)["reason"]


def test_settings_round_trip(conn):
    assert settings.load() == settings.Settings(0, 30, 20)
    settings.save(settings.Settings(daily_agent_cap=4, retention_days=7, keep_runs=3))
    assert settings.load() == settings.Settings(4, 7, 3)
