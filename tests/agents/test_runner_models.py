import json
from datetime import datetime

from whyline.agents import definitions as d, runner, state

NOW = datetime(2026, 10, 5, 7, 0)


class Result:
    def __init__(self, code, output):
        self.exit_code, self.output = code, output


def _script(*results):
    calls = []

    def run_fn(command, prompt, **kwargs):
        calls.append(list(command))
        return results[len(calls) - 1]

    return run_fn, calls


def _agent(repo, models):
    path = repo / ".whyline/agents/a.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    table = "[models]\n" + "".join(f'{k} = "{v}"\n' for k, v in models.items())
    path.write_text(f'name="a"\ninstructions="Go."\nrunner="claude"\nbackup=["codex"]\n{table}')
    return d.load(path, kind="repo", repo_root=repo)


def _model_after(argv):
    return argv[argv.index("--model") + 1] if "--model" in argv else None


def test_run_uses_the_model_of_the_cli_that_runs(repo):
    limit = json.dumps({"is_error": True, "result": "You've hit your limit · resets 3pm"})
    run_fn, calls = _script(Result(1, limit), Result(0, "ok"))
    agent = _agent(repo, {"claude": "sonnet", "codex": "gpt-9"})
    state.accept(state.connect(), agent)
    rec = runner.execute_once(agent, source="manual", now=NOW, run_fn=run_fn)
    assert _model_after(calls[0]) == "sonnet"
    assert _model_after(calls[1]) == "gpt-9"
    assert rec.cli == "codex" and rec.model == "gpt-9" and rec.model_note == ""


def test_a_cli_without_a_model_flag_runs_without_one(repo, monkeypatch):
    agent = _agent(repo, {"claude": "sonnet"})
    monkeypatch.setattr(runner, "_model_flag", lambda defn, cli: None)
    run_fn, calls = _script(Result(0, json.dumps({"result": "ok"})))
    rec = runner.execute_once(agent, source="manual", now=NOW, run_fn=run_fn)
    assert "--model" not in calls[0] and rec.model == ""


def test_a_model_the_cli_refuses_is_retried_once_on_the_default(repo):
    refused = Result(1, json.dumps({"is_error": True, "result": "Error: unknown model: sonnet-9"}))
    run_fn, calls = _script(refused, Result(0, json.dumps({"result": "fine"})))
    rec = runner.execute_once(_agent(repo, {"claude": "sonnet-9"}), source="manual",
                              now=NOW, run_fn=run_fn)
    assert len(calls) == 2 and rec.cli == "claude" and rec.used_backup is None
    assert _model_after(calls[0]) == "sonnet-9" and "--model" not in calls[1]
    assert rec.outcome == "succeeded" and rec.model == ""
    assert rec.model_note == "sonnet-9 was refused; ran on the default"


def test_an_ordinary_failure_is_not_retried_on_the_default(repo):
    run_fn, calls = _script(Result(1, json.dumps({"is_error": True, "result": "Error: tool crashed"})))
    rec = runner.execute_once(_agent(repo, {"claude": "sonnet"}), source="manual",
                              now=NOW, run_fn=run_fn)
    assert len(calls) == 1 and rec.outcome == "failed" and rec.model == "sonnet"
    assert rec.model_note == ""


def test_the_default_retry_drops_a_model_the_relay_config_pins(repo, monkeypatch):
    from whyline_relay import chat

    real = chat.resolve_command
    monkeypatch.setattr(chat, "resolve_command",
                        lambda cfg, cli: [*real(cfg, cli), "--model", "opus"])
    refused = Result(1, json.dumps({"is_error": True, "result": "Error: unknown model: sonnet-9"}))
    run_fn, calls = _script(refused, Result(0, json.dumps({"result": "fine"})))
    runner.execute_once(_agent(repo, {"claude": "sonnet-9"}), source="manual", now=NOW, run_fn=run_fn)
    assert _model_after(calls[0]) == "sonnet-9"
    assert "--model" not in calls[1] and "opus" not in calls[1]


def test_without_model_removes_every_pair():
    out = runner._without_model(["claude", "--model", "opus", "-p", "--model", "x"], ("--model",))
    assert out == ["claude", "-p"]
