import threading

import pytest

from whyline.release import cli as release_cli
from whyline.release import engine, plan as release_plan
from whyline.release import ready as release_ready
from whyline.release import state as release_state
from whyline.release.config import ReleaseConfig


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.2.3"\n')
    monkeypatch.setattr(release_cli, "_root", lambda: tmp_path)
    return tmp_path


def tty(monkeypatch, value):
    monkeypatch.setattr(release_cli, "_interactive", lambda: value)


def test_check_prints_items_and_exits_one_on_a_failure(root, monkeypatch, capsys):
    seen = []
    items = [release_ready.ReadyItem("git", True, "git is installed"),
             release_ready.ReadyItem("clean", False, "Uncommitted changes: a.py", "Commit them")]

    def fake_check(r, cfg, version):
        seen.append(version)
        return items

    monkeypatch.setattr(release_ready, "check", fake_check)
    assert release_cli.main(["check"]) == 1
    out = capsys.readouterr().out
    assert "✓ git is installed" in out and "✗ Uncommitted changes: a.py" in out
    assert "Commit them" in out and seen == ["1.2.4"]
    assert release_cli.main(["check", "--version", "2.0.0"]) == 1
    assert seen[-1] == "2.0.0"


def test_check_exits_zero_when_all_ready(root, monkeypatch):
    monkeypatch.setattr(release_ready, "check",
                        lambda *a, **k: [release_ready.ReadyItem("git", True, "ok")])
    assert release_cli.main(["check"]) == 0


def fake_run(monkeypatch, status=engine.DONE):
    calls = {}

    def run(r, plan, **kwargs):
        calls.update(plan=plan, **kwargs)
        kwargs["on_progress"](engine.Progress(0, 2, "Check ready", "Running", None, None))
        return engine.Result(status, "The release finished." if status == engine.DONE else "Stopped")

    monkeypatch.setattr(engine, "run", run)
    return calls


def test_run_bumps_and_prints_progress(root, monkeypatch, capsys):
    tty(monkeypatch, True)
    calls = fake_run(monkeypatch)
    assert release_cli.main(["run", "--bump", "minor", "--yes"]) == 0
    assert calls["plan"].version == "1.3.0" and calls["mode"] == "ask"
    assert calls["confirm"](None) is True
    out = capsys.readouterr().out
    assert "[1/2] Check ready: Running" in out and "The release finished." in out


def test_run_with_explicit_version_and_mode(root, monkeypatch):
    calls = fake_run(monkeypatch)
    assert release_cli.main(["run", "--version", "3.0.0", "--mode", "auto"]) == 0
    assert calls["plan"].version == "3.0.0" and calls["mode"] == "auto"


def test_run_asks_at_each_confirm_on_a_terminal(root, monkeypatch):
    tty(monkeypatch, True)
    calls = fake_run(monkeypatch)
    release_cli.main(["run"])
    step = engine.Step("push", "Push", True, lambda: False, lambda c: None)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert calls["confirm"](step) is True
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert calls["confirm"](step) is False


def test_run_refuses_without_a_terminal(root, monkeypatch, capsys):
    tty(monkeypatch, False)
    calls = fake_run(monkeypatch)
    assert release_cli.main(["run"]) == 1
    assert "--yes" in capsys.readouterr().err and not calls


def test_run_without_a_terminal_goes_ahead_with_yes_or_auto(root, monkeypatch):
    tty(monkeypatch, False)
    calls = fake_run(monkeypatch)
    assert release_cli.main(["run", "--yes"]) == 0
    calls.clear()
    assert release_cli.main(["run", "--mode", "auto"]) == 0
    assert calls["mode"] == "auto"


def test_run_stopped_exits_one(root, monkeypatch, capsys):
    fake_run(monkeypatch, status=engine.FAILED)
    assert release_cli.main(["run", "--yes"]) == 1
    assert "whyline release resume" in capsys.readouterr().err


def test_status(root, capsys):
    assert release_cli.main(["status"]) == 0
    assert "No release in progress." in capsys.readouterr().out
    release_state.save(root, release_state.State(
        version="1.2.4", step_ids=["a", "b", "c"], done=["a"], failed_id="b", reason="b broke"))
    assert release_cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "v1.2.4" in out and "failed at b" in out and "1 of 3" in out and "b broke" in out


def test_resume(root, monkeypatch, capsys):
    release_state.save(root, release_state.State(version="1.2.4", step_ids=["ready"], mode="step"))
    tty(monkeypatch, False)
    assert release_cli.main(["resume"]) == 1
    assert "--yes" in capsys.readouterr().err
    seen = {}

    def resume(r, steps, **kwargs):
        seen.update(steps=steps, **kwargs)
        return engine.Result(engine.DONE, "The release finished.")

    monkeypatch.setattr(engine, "resume", resume)
    assert release_cli.main(["resume", "--yes"]) == 0
    assert seen["version"] == "1.2.4" and "ready" in seen["steps"]


def test_resume_without_a_saved_run(root, capsys):
    assert release_cli.main(["resume", "--yes"]) == 1
    assert "no stopped release" in capsys.readouterr().err


def test_release_verbs_are_routed_from_the_main_command(root, monkeypatch, capsys):
    from whyline import cli

    assert cli.main(["release", "status"]) == 0
    assert "No release in progress." in capsys.readouterr().out


# --- plan.py: the after step -------------------------------------------------


def after_step(root, cfg, target, shell, said):
    plan = release_plan.build(root, cfg, "1.2.4", run_shell=shell, telegram_target=lambda: target,
                              say=said.append)
    return next(s for s in plan.steps if s.id == "after")


def test_after_runs_commands_warns_on_failure_and_sends_telegram(root, monkeypatch):
    from whyline.agents import telegram

    sent = []
    monkeypatch.setattr(telegram, "send_message",
                        lambda token, chat, text, **kw: sent.append((token, chat, text)))
    ran, said = [], []

    def shell(command, r, on_line):
        ran.append(command)
        return (1 if command == "bad" else 0), []

    cfg = ReleaseConfig(after=("good", "bad"))
    after_step(root, cfg, ("tok", 7), shell, said).run(threading.Event())
    assert ran == ["good", "bad"]
    assert any("bad" in line and "Warning" in line for line in said)
    assert sent == [("tok", 7, f"Released v1.2.4 of {root.name}")]


def test_after_skips_quietly_without_telegram_and_warns_when_it_fails(root, monkeypatch):
    from whyline.agents import telegram

    said = []
    after_step(root, ReleaseConfig(), None, lambda *a: (0, []), said).run(threading.Event())
    assert said == []

    def boom(token, chat, text, **kw):
        raise telegram.TelegramError("down tok")

    monkeypatch.setattr(telegram, "send_message", boom)
    after_step(root, ReleaseConfig(), ("tok", 7), lambda *a: (0, []), said).run(threading.Event())
    assert len(said) == 1 and "tok" not in said[0] and "Telegram" in said[0]


def test_plan_step_order(root):
    plan = release_plan.build(root, ReleaseConfig(), "1.2.4")
    assert [s.id for s in plan.steps] == [
        "ready", "version", "notes", "commit", "checks", "push", "ci", "tag",
        "github_release", "after"]
