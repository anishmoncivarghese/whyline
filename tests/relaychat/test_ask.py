import threading
from types import SimpleNamespace

import pytest

from whyline.relaychat import agent_choice, ask, history, settings, snapshot

READ_ONLY = ["claude", "--permission-mode", "plan"]


class Runner:
    def __init__(self, output="It is on RCH-4 (src/a.py:3).", code=0, error=None):
        self.output, self.code, self.error = output, code, error
        self.calls = []

    def __call__(self, argv, prompt, **kwargs):
        self.calls.append((argv, prompt, kwargs))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(exit_code=self.code, output=self.output)


@pytest.fixture
def env(monkeypatch, tmp_path):
    base = tmp_path / "chat"
    monkeypatch.setattr(settings, "base_dir", lambda b=None: base)
    monkeypatch.setattr(history, "base_dir", lambda b=None: base)
    monkeypatch.setattr(settings, "load", lambda repo, base=None: settings.ChatSettings(timeout_seconds=30))
    monkeypatch.setattr(snapshot, "build",
                        lambda repo, max_chars, **kw: snapshot.Snapshot("SNAPSHOT-TEXT", "run1", "running"))
    monkeypatch.setattr(agent_choice, "pick",
                        lambda repo, chosen=None: agent_choice.Pick("claude", False, "chosen"))
    monkeypatch.setattr(ask, "_command", lambda repo, cli: list(READ_ONLY))
    monkeypatch.setattr(ask, "_extract", lambda repo, cli, raw, f: raw)
    monkeypatch.setattr("whyline.agents.runner._adapter", lambda defn, cli: None)
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def test_runs_read_only_with_env_and_records(env):
    runner = Runner()
    answer = ask.ask(env, "What now?", runner=runner)
    argv, _prompt, kwargs = runner.calls[0]
    assert argv == READ_ONLY
    assert kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0"
    assert kwargs["cwd"] == env and kwargs["timeout_seconds"] == 30
    assert answer.ok and answer.agent == "claude" and answer.text.startswith("It is on")
    saved = history.load(env, "run1")
    assert [r["role"] for r in saved] == ["user", "assistant"]
    assert saved[0]["text"] == "What now?"


def test_prompt_has_snapshot_history_and_question(env):
    for n in range(8):
        history.append(env, "run1", "user", f"old question {n}")
        history.append(env, "run1", "assistant", f"old answer {n}")
    runner = Runner()
    ask.ask(env, "Newest?", runner=runner)
    prompt = runner.calls[0][1]
    assert "SNAPSHOT-TEXT" in prompt and "Newest?" in prompt
    assert "read-only observer" in prompt and "path:line" in prompt
    assert "old question 7" in prompt and "old answer 2" in prompt
    assert "old question 1" not in prompt  # only the last 6 exchanges


def test_timeout_zero_means_no_limit(env, monkeypatch):
    monkeypatch.setattr(settings, "load", lambda repo, base=None: settings.ChatSettings(timeout_seconds=0))
    runner = Runner()
    ask.ask(env, "q", runner=runner)
    assert runner.calls[0][2]["timeout_seconds"] is None


def test_timeout_is_plain_and_recorded(env):
    from whyline_relay import agents

    answer = ask.ask(env, "q", runner=Runner(error=agents.AgentTimeout("slow")))
    assert not answer.ok and "30 seconds" in answer.text
    assert history.load(env, "run1")[-1]["text"] == answer.text


def test_cancel_records_stopped(env):
    from whyline_relay import agents

    event = threading.Event()
    runner = Runner(error=agents.AgentCancelled("stopped"))
    answer = ask.ask(env, "q", runner=runner, cancel_event=event)
    assert runner.calls[0][2]["cancel_event"] is event
    assert not answer.ok and answer.text == "Stopped."
    assert history.load(env, "run1")[-1]["text"] == "Stopped."


def test_missing_agent_binary(env):
    from whyline_relay import agents

    answer = ask.ask(env, "q", runner=Runner(error=agents.AgentMissing("claude gone")))
    assert not answer.ok and "not installed" in answer.text
    assert len(history.load(env, "run1")) == 2


def test_no_agent_refuses_and_records(env, monkeypatch):
    monkeypatch.setattr(agent_choice, "pick", lambda repo, chosen=None: agent_choice.Pick(None, False, "No agent."))
    runner = Runner()
    answer = ask.ask(env, "q", runner=runner)
    assert not answer.ok and answer.text == "No agent." and not runner.calls
    assert len(history.load(env, "run1")) == 2


def test_no_read_only_command_refuses(env, monkeypatch):
    monkeypatch.setattr(ask, "_command", lambda repo, cli: None)
    runner = Runner()
    answer = ask.ask(env, "q", runner=runner)
    assert not answer.ok and "read-only" in answer.text and not runner.calls


def test_usage_limit_is_not_ok(env):
    answer = ask.ask(env, "q", runner=Runner(output="Rate limit reached", code=1))
    assert not answer.ok and "limit" in answer.text.lower()


def test_seconds_come_from_clock(env):
    ticks = iter([10.0, 12.5])
    answer = ask.ask(env, "q", runner=Runner(), clock=lambda: next(ticks))
    assert answer.seconds == 2.5


def test_prompt_asks_for_final_answer_only():
    prompt = ask.build_prompt("snap", [], "q")
    assert "Reply with the final answer only. Do not describe what you are about to read or do." in prompt


def test_final_message_returns_text_unchanged():
    assert ask.final_message("grok", '{"text": "a b"}', "a b") == "a b"
    assert ask.final_message("claude", "raw", "answer") == "answer"


GROK = ["grok", "--mode", "dontAsk", "-p"]
CANCELLED = (
    "permission required: Execute `git -c x diff`\n"
    '{"stopReason": "cancelled", "text": "I\'ll read the relay snapshot…", "sessionId": "sess-1"}'
)


@pytest.fixture
def grok(env, monkeypatch):
    monkeypatch.setattr(agent_choice, "pick",
                        lambda repo, chosen=None: agent_choice.Pick("grok", False, "chosen"))
    monkeypatch.setattr(ask, "_command", lambda repo, cli: list(GROK))
    return env


class Sequence(Runner):
    def __init__(self, *outputs, on_call=None):
        super().__init__()
        self.outputs, self.on_call = list(outputs), on_call

    def __call__(self, argv, prompt, **kwargs):
        self.calls.append((argv, prompt, kwargs))
        if self.on_call:
            self.on_call()
        return SimpleNamespace(exit_code=0, output=self.outputs[len(self.calls) - 1])


def test_instructions_forbid_shell():
    assert "never run shell commands" in ask.INSTRUCTIONS


def test_cancelled_turn_only_for_grok():
    assert ask.cancelled_turn("grok", CANCELLED)
    assert not ask.cancelled_turn("grok", '{"stopReason": "end_turn"}')
    assert not ask.cancelled_turn("codex", CANCELLED)
    assert not ask.cancelled_turn("claude", '{"stopReason": "cancelled"}')
    assert ask.refused_command(CANCELLED) == "git -c x diff"
    assert ask.refused_command("nothing") is None


def test_cancelled_turn_resumes_and_answers(grok):
    runner = Sequence(CANCELLED, "It is on RCH-4.")
    seen = []
    answer = ask.ask(grok, "What now?", agent="grok", runner=runner, on_progress=seen.append)
    _first, second = runner.calls
    assert second[0] == ["grok", "--mode", "dontAsk", "--resume", "sess-1", "-p"]
    assert "`git -c x diff`" in second[1] and "Don't run shell commands" in second[1]
    assert seen == ["grok was stopped by its read-only rules, retrying…"]
    assert answer.ok and answer.text == "It is on RCH-4."
    saved = history.load(grok, "run1")
    assert [r["text"] for r in saved] == ["What now?", "It is on RCH-4."]


def test_cancelled_twice_is_a_failure_without_the_opening_line(grok):
    runner = Sequence(CANCELLED, CANCELLED)
    answer = ask.ask(grok, "What now?", agent="grok", runner=runner)
    assert not answer.ok
    assert answer.text.startswith("grok stopped before answering: its read-only mode refused `git -c x diff`.")
    assert "pick another agent" in answer.text
    assert not any("read the relay snapshot" in r["text"] for r in history.load(grok, "run1"))


def test_cancelled_without_session_retries_fresh(grok):
    raw = '{"stopReason": "cancelled", "text": "Let me look"}'
    runner = Sequence(raw, "Fine.")
    answer = ask.ask(grok, "Q?", agent="grok", runner=runner)
    assert runner.calls[1][0] == GROK
    assert "SNAPSHOT-TEXT" in runner.calls[1][1] and "Don't run shell commands" in runner.calls[1][1]
    assert "Your last command" not in runner.calls[1][1]
    assert answer.ok and answer.text == "Fine."


def test_cancelled_without_command_has_plain_message(grok):
    raw = '{"stopReason": "cancelled", "text": "x"}'
    answer = ask.ask(grok, "Q?", agent="grok", runner=Sequence(raw, raw))
    assert answer.text.startswith("grok stopped before answering (its read-only mode refused a command).")


@pytest.mark.parametrize("cli", ["codex", "claude"])
def test_other_clis_with_stop_reason_are_answers(env, monkeypatch, cli):
    monkeypatch.setattr(agent_choice, "pick",
                        lambda repo, chosen=None: agent_choice.Pick(cli, False, "chosen"))
    runner = Sequence('{"stopReason": "cancelled"}')
    answer = ask.ask(env, "Q?", agent=cli, runner=runner)
    assert len(runner.calls) == 1 and answer.ok


def test_stop_during_first_run_does_not_retry(grok):
    stop = threading.Event()
    runner = Sequence(CANCELLED, on_call=stop.set)
    answer = ask.ask(grok, "Q?", agent="grok", runner=runner, cancel_event=stop)
    assert len(runner.calls) == 1
    assert answer.text == ask.STOPPED and not answer.ok
