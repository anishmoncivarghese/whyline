"""`whyline ask` with fakes: no agent runs and nothing is written outside tmp."""
import pytest

from whyline import cli
from whyline.relaychat import ask as relay_ask
from whyline.relaychat import history, settings, snapshot


@pytest.fixture
def env(monkeypatch, tmp_path):
    base = tmp_path / "chat"
    monkeypatch.setattr(settings, "base_dir", lambda b=None: base)
    monkeypatch.setattr(history, "base_dir", lambda b=None: base)
    monkeypatch.setattr(snapshot, "build",
                        lambda repo, max_chars, **kw: snapshot.Snapshot("S", "run1", "running"))
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def fake_ask(monkeypatch, answer, calls=None):
    def fake(repo, question, *, agent=None, **kw):
        if calls is not None:
            calls.append((repo, question, agent))
        return answer

    monkeypatch.setattr(relay_ask, "ask", fake)


def test_answer_prints_text_agent_and_quota_note(env, monkeypatch, capsys):
    calls = []
    fake_ask(monkeypatch, relay_ask.Answer("On RCH-6.", "claude", True, 1.0, True), calls)
    assert cli.main(["ask", "where?", "--agent", "claude", "--repo", str(env)]) == 0
    out = capsys.readouterr().out
    assert "On RCH-6." in out and "claude" in out and "(shares quota with the relay)" in out
    assert calls == [(env, "where?", "claude")]


def test_no_quota_note_when_not_shared(env, monkeypatch, capsys):
    fake_ask(monkeypatch, relay_ask.Answer("ok", "codex", False, 1.0, True))
    assert cli.main(["ask", "q", "--repo", str(env)]) == 0
    assert "shares quota" not in capsys.readouterr().out


def test_failed_answer_exits_one(env, monkeypatch, capsys):
    fake_ask(monkeypatch, relay_ask.Answer("claude took too long", "claude", False, 1.0, False))
    assert cli.main(["ask", "q", "--repo", str(env)]) == 1
    assert "took too long" in capsys.readouterr().out


def test_history_prints_conversation(env, capsys):
    history.append(env, "run1", "user", "hello?")
    history.append(env, "run1", "assistant", "hi", agent="claude")
    assert cli.main(["ask", "--history", "--repo", str(env)]) == 0
    out = capsys.readouterr().out
    assert "Question: hello?" in out and "Answer (claude): hi" in out


def test_history_for_a_given_run(env, capsys):
    history.append(env, "other", "user", "old one")
    assert cli.main(["ask", "--history", "--run", "other", "--repo", str(env)]) == 0
    assert "old one" in capsys.readouterr().out


def test_history_empty(env, capsys):
    assert cli.main(["ask", "--history", "--repo", str(env)]) == 0
    assert "No conversation yet." in capsys.readouterr().out


def test_clear_starts_new_conversation(env, capsys):
    history.append(env, "run1", "user", "hello?")
    assert cli.main(["ask", "--clear", "--repo", str(env)]) == 0
    assert "Started a new conversation." in capsys.readouterr().out
    assert history.load(env, "run1") == []


def test_setters_call_settings_save(env, monkeypatch, capsys):
    saved = []

    def fake_save(repo, base=None, **changes):
        saved.append((repo, changes))
        return settings.ChatSettings(agent="grok", timeout_seconds=60, snapshot_chars=5000)

    monkeypatch.setattr(settings, "save", fake_save)
    assert cli.main(["ask", "--set-agent", "grok", "--repo", str(env)]) == 0
    assert cli.main(["ask", "--set-timeout", "60", "--repo", str(env)]) == 0
    assert cli.main(["ask", "--set-snapshot-chars", "5000", "--repo", str(env)]) == 0
    assert [changes for _, changes in saved] == [
        {"agent": "grok"}, {"timeout_seconds": 60}, {"snapshot_chars": 5000}]
    assert all(repo == env for repo, _ in saved)


def test_setters_really_persist(env, capsys):
    assert cli.main(["ask", "--set-timeout", "45", "--repo", str(env)]) == 0
    assert settings.load(env).timeout_seconds == 45


@pytest.mark.parametrize("flag,value", [("--set-timeout", "-5"), ("--set-snapshot-chars", "0"),
                                         ("--set-agent", "  ")])
def test_bad_setting_exits_two(env, capsys, flag, value):
    assert cli.main(["ask", flag, value, "--repo", str(env)]) == 2
    assert "whyline ask:" in capsys.readouterr().err


def test_no_question_exits_two(env, capsys):
    assert cli.main(["ask", "--repo", str(env)]) == 2
    assert "usage" in capsys.readouterr().err
