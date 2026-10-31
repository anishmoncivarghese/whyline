import json
import stat
from pathlib import Path

import pytest

from whyline.workflows import definitions as d
from whyline.workflows import engine, paths, state
from whyline.workflows.engine import StepResult

HEAD = '''
name = "demo"
version = 1

[trigger]
kind = "manual"
'''


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture
def conn(home):
    return state.connect()


def make_run(conn, body: str, key: str = "k1", inputs: dict | None = None):
    wf = d.parse(HEAD + body, kind="personal", path=Path("demo.toml"))
    return state.claim_run(conn, wf, source="manual", dedupe_key=key, inputs=inputs or {})


def statuses(conn, run_id):
    return {r["step_id"]: r["status"] for r in state.steps_of(conn, run_id)}


def output(run_id, step_id):
    return json.loads((paths.runs_dir() / str(run_id) / f"{step_id}.json").read_text())


LINEAR = '''
[[step]]
id = "a"
type = "set"
[step.values]
greeting = "hello {{ inputs.who }}"
n = 3

[[step]]
id = "b"
type = "set"
[step.values]
echo = "{{ steps.a.greeting }}!"
'''


def test_linear_run_succeeds_and_writes_outputs(conn):
    run = make_run(conn, LINEAR, inputs={"who": "ana"})
    assert engine.execute(run) == "succeeded"
    assert statuses(conn, run) == {"a": "succeeded", "b": "succeeded"}
    assert output(run, "a") == {"greeting": "hello ana", "n": 3}
    assert output(run, "b") == {"echo": "hello ana!"}
    path = paths.runs_dir() / str(run) / "a.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert engine.execute(run) == "succeeded"  # a finished run is left alone


CONDITION = '''
[[step]]
id = "check"
type = "condition"
left = "{{ inputs.n }}"
op = "gt"
right = "5"
then = "big"
else = "small"

[[step]]
id = "small"
type = "set"
[step.values]
size = "small"

[[step]]
id = "big"
type = "set"
[step.values]
size = "big"
'''


def test_condition_true_skips_the_other_branch(conn):
    run = make_run(conn, CONDITION, inputs={"n": 9})
    assert engine.execute(run) == "succeeded"
    assert statuses(conn, run) == {"check": "succeeded", "small": "skipped", "big": "succeeded"}


def test_condition_false_takes_else(conn):
    run = make_run(conn, CONDITION, inputs={"n": 1})
    assert engine.execute(run) == "succeeded"
    assert statuses(conn, run)["small"] == "succeeded"
    assert statuses(conn, run)["big"] == "succeeded"  # reached by falling through


SWITCH = '''
[[step]]
id = "pick"
type = "switch"
value = "{{ inputs.colour }}"
default = "other"
[step.cases.r]
equals = "red"
goto = "red"

[[step]]
id = "red"
type = "stop"

[[step]]
id = "other"
type = "set"
[step.values]
x = "1"
'''


def test_switch_takes_a_case(conn):
    run = make_run(conn, SWITCH, inputs={"colour": "red"})
    assert engine.execute(run) == "succeeded"
    assert statuses(conn, run) == {"pick": "succeeded", "red": "succeeded", "other": "skipped"}


def test_switch_takes_default(conn):
    run = make_run(conn, SWITCH, inputs={"colour": "blue"})
    assert engine.execute(run) == "succeeded"
    assert statuses(conn, run) == {"pick": "succeeded", "red": "skipped", "other": "succeeded"}


def test_stop_ends_succeeded_and_skips_the_rest(conn):
    run = make_run(conn, '''
[[step]]
id = "halt"
type = "stop"

[[step]]
id = "never"
type = "set"
[step.values]
x = "1"
''')
    assert engine.execute(run) == "succeeded"
    assert statuses(conn, run) == {"halt": "succeeded", "never": "skipped"}


def test_template_reading_skipped_step_fails_clearly(conn):
    run = make_run(conn, '''
[[step]]
id = "check"
type = "condition"
left = "a"
op = "eq"
right = "a"
then = "last"
else = "mid"

[[step]]
id = "mid"
type = "set"
[step.values]
v = "1"

[[step]]
id = "last"
type = "set"
[step.values]
w = "{{ steps.mid.v }}"
''')
    assert engine.execute(run) == "failed"
    reason = conn.execute("SELECT reason FROM runs WHERE id=?", (run,)).fetchone()[0]
    assert "steps.mid.v" in reason and "skipped" in reason
    assert statuses(conn, run)["last"] == "failed"


def test_run_keeps_its_revision_after_edit(conn):
    run = make_run(conn, LINEAR, inputs={"who": "ana"})
    edited = d.parse(HEAD + LINEAR.replace("hello", "goodbye"), kind="personal",
                     path=Path("demo.toml"))
    conn.execute("UPDATE activations SET path=?", (str(edited.path),))
    assert engine.execute(run) == "succeeded"
    assert output(run, "a")["greeting"] == "hello ana"


DELIVER = '''
[[step]]
id = "a"
type = "set"
[step.values]
x = "1"

[[step]]
id = "send"
type = "deliver"
to = "file"
text = "hi"
'''


def crash(conn, run, step_id, monkeypatch):
    monkeypatch.setattr(engine, "_alive", lambda pid: False)
    state.set_run(conn, run, status="running", pid=999999)
    state.set_step(conn, run, step_id, status="running", attempt=1)


def test_crash_during_write_is_unknown_outcome(conn, monkeypatch):
    run = make_run(conn, DELIVER)
    state.set_step(conn, run, "a", status="succeeded")
    crash(conn, run, "send", monkeypatch)
    sent = []
    handlers = {"deliver": lambda ctx, step: sent.append(1) or StepResult("succeeded", {})}
    assert engine.execute(run, handlers=handlers) == "unknown_outcome"
    assert sent == []
    assert statuses(conn, run)["send"] == "unknown_outcome"


def test_crashed_set_step_is_rerun(conn, monkeypatch):
    run = make_run(conn, LINEAR, inputs={"who": "ana"})
    crash(conn, run, "a", monkeypatch)
    assert engine.execute(run) == "succeeded"
    assert output(run, "a")["greeting"] == "hello ana"
    assert conn.execute("SELECT attempt FROM step_runs WHERE run_id=? AND step_id='a'",
                        (run,)).fetchone()[0] == 2


def unknown_run(conn, monkeypatch):
    run = make_run(conn, DELIVER)
    state.set_step(conn, run, "a", status="succeeded")
    crash(conn, run, "send", monkeypatch)
    assert engine.execute(run, handlers={}) == "unknown_outcome"
    return run


def test_resolve_done_continues(conn, monkeypatch):
    run = unknown_run(conn, monkeypatch)
    assert engine.resolve_unknown(run, "done") == "succeeded"
    assert statuses(conn, run)["send"] == "succeeded"


def test_resolve_failed_fails_the_run(conn, monkeypatch):
    run = unknown_run(conn, monkeypatch)
    assert engine.resolve_unknown(run, "failed") == "failed"
    assert statuses(conn, run)["send"] == "failed"


def test_resolve_retry_reruns_the_step(conn, monkeypatch):
    run = unknown_run(conn, monkeypatch)
    sent = []
    handlers = {"deliver": lambda ctx, step: sent.append(1) or StepResult("succeeded", {})}
    assert engine.resolve_unknown(run, "retry", handlers=handlers) == "succeeded"
    assert sent == [1]


def test_resolve_needs_an_unknown_run(conn):
    run = make_run(conn, LINEAR)
    with pytest.raises(ValueError):
        engine.resolve_unknown(run, "done")


def test_output_over_one_megabyte_fails_the_step(conn):
    run = make_run(conn, LINEAR, inputs={"who": "ana"})
    big = {"set": lambda ctx, step: StepResult("succeeded", {"blob": "x" * 1_100_000})}
    assert engine.execute(run, handlers=big) == "failed"
    assert statuses(conn, run)["a"] == "failed"
    assert not (paths.runs_dir() / str(run) / "a.json").exists()


def test_secret_is_redacted_on_disk(conn):
    run = make_run(conn, LINEAR, inputs={"who": "ana"})
    leaky = {"set": lambda ctx, step: StepResult(
        "succeeded", {"note": "api_key=sk-abcdefghijklmnopqrstuvwxyz123456"})}
    engine.execute(run, handlers=leaky)
    text = (paths.runs_dir() / str(run) / "a.json").read_text()
    assert "abcdefghijklmnopqrstuvwxyz" not in text and "[redacted]" in text


def test_template_reads_run_started(conn):
    body = '''
[[step]]
id = "a"
type = "set"
[step.values]
since = "{{ run.started }}"
'''
    run = make_run(conn, body)
    assert engine.execute(run) == "succeeded"
    stored = conn.execute("SELECT started FROM runs WHERE id=?", (run,)).fetchone()["started"]
    assert stored and output(run, "a") == {"since": stored}


def test_two_hour_limit_sees_time_passing_during_a_step(conn, monkeypatch):
    from datetime import datetime, timedelta, timezone
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(engine, "_utcnow", lambda: clock[0])

    def slow(ctx, step):
        clock[0] += timedelta(hours=3)
        return StepResult("succeeded", {"ok": True})

    run = make_run(conn, LINEAR, inputs={"who": "ana"})
    assert engine.execute(run, handlers={"set": slow}) == "failed"
    assert statuses(conn, run) == {"a": "succeeded"}
    reason = conn.execute("SELECT reason FROM runs WHERE id=?", (run,)).fetchone()["reason"]
    assert "2 hours" in reason


def test_two_hour_limit_applies_to_the_final_step(conn, monkeypatch):
    from datetime import datetime, timedelta, timezone
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(engine, "_utcnow", lambda: clock[0])

    def slow(ctx, step):
        clock[0] += timedelta(hours=3)
        return StepResult("succeeded", {"ok": True})

    body = '''
[[step]]
id = "a"
type = "set"
[step.values]
x = "1"
'''
    run = make_run(conn, body, key="one-step")
    assert engine.execute(run, handlers={"set": slow}) == "failed"
    assert statuses(conn, run) == {"a": "succeeded"}
    reason = conn.execute("SELECT reason FROM runs WHERE id=?", (run,)).fetchone()["reason"]
    assert "2 hours" in reason


ONE_STEP = '''
[[step]]
id = "a"
type = "set"
[step.values]
x = "1"
'''


def test_cancel_during_handler_is_not_overwritten(conn):
    run = make_run(conn, ONE_STEP, key="cancel-mid")

    def cancelling(ctx, step):
        engine.cancel(run)
        return StepResult("succeeded", {"ok": True})

    assert engine.execute(run, handlers={"set": cancelling}) == "cancelled"
    row = conn.execute("SELECT status FROM runs WHERE id=?", (run,)).fetchone()
    assert row["status"] == "cancelled"
    assert statuses(conn, run) == {"a": "cancelled"}


def test_empty_output_still_writes_a_private_artifact(conn):
    run = make_run(conn, ONE_STEP, key="empty-out")

    def empty(ctx, step):
        return StepResult("succeeded", {})

    assert engine.execute(run, handlers={"set": empty}) == "succeeded"
    path = paths.runs_dir() / str(run) / "a.json"
    assert output(run, "a") == {}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_cancel_stops_a_queued_run(conn):
    run = make_run(conn, LINEAR)
    assert engine.cancel(run) == "cancelled"
    assert engine.execute(run) == "cancelled"
    assert statuses(conn, run) == {}
