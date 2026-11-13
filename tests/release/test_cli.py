import threading
from types import SimpleNamespace

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


def test_run_prints_the_source_line_before_the_steps(root, monkeypatch, capsys):
    calls = fake_run(monkeypatch)
    monkeypatch.setattr(release_plan, "bring_confirmation",
                        lambda r, cfg, **k: "Releasing feat · 3 commits\nMoves to plans/done: a.plan.md")
    assert release_cli.main(["run", "--yes"]) == 0
    out = capsys.readouterr().out
    assert out.index("Releasing feat · 3 commits") < out.index("[1/2]")
    assert "Moves to plans/done: a.plan.md" in out
    assert calls["plan"].version == "1.2.4"


def test_run_on_main_prints_the_short_line(root, monkeypatch, capsys):
    fake_run(monkeypatch)
    monkeypatch.setattr(release_plan, "bring_confirmation", lambda r, cfg, **k: "Releasing main")
    release_cli.main(["run", "--yes"])
    assert "Releasing main" in capsys.readouterr().out


def test_no_bring_in_turns_the_step_and_line_off(root, monkeypatch, capsys):
    seen = []
    fake_run(monkeypatch)
    monkeypatch.setattr(release_plan, "bring_confirmation",
                        lambda r, cfg, **k: seen.append(cfg.bring_in_main) or "Releasing feat")
    real_build = release_plan.build
    built = []
    monkeypatch.setattr(release_plan, "build",
                        lambda r, cfg, v, **k: built.append(cfg.bring_in_main) or real_build(r, cfg, v, **k))
    assert release_cli.main(["run", "--yes", "--no-bring-in"]) == 0
    assert seen == [] and built == [False]
    assert "Releasing feat" not in capsys.readouterr().out
    release_cli.main(["run", "--yes"])
    assert seen == [True] and built == [False, True]


def test_ask_mode_confirmation_shows_the_source_text(root, monkeypatch, capsys):
    tty(monkeypatch, True)
    calls = fake_run(monkeypatch)
    monkeypatch.setattr(release_plan, "bring_confirmation", lambda r, cfg, **k: "Releasing feat")
    release_cli.main(["run"])
    capsys.readouterr()
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    step = engine.Step("bring-in-main", "Bring in main", True, lambda: False, lambda c: None)
    assert calls["confirm"](step) is True
    assert "Releasing feat" in capsys.readouterr().out


def test_run_defaults_to_an_unreleased_current_version(root, monkeypatch, capsys):
    tty(monkeypatch, True)
    calls = fake_run(monkeypatch)
    monkeypatch.setattr(release_cli.release_version, "released", lambda *a, **k: False)
    assert release_cli.main(["run", "--yes"]) == 0
    assert calls["plan"].version == "1.2.3"
    assert "1.2.3" in capsys.readouterr().out.split("not released yet")[0]


def test_run_keeps_patch_when_the_current_version_is_tagged(root, monkeypatch):
    tty(monkeypatch, True)
    calls = fake_run(monkeypatch)
    monkeypatch.setattr(release_cli.release_version, "released", lambda *a, **k: True)
    assert release_cli.main(["run", "--yes"]) == 0
    assert calls["plan"].version == "1.2.4"


def _notes(root, text="# v1.2.3\n- a\n"):
    (root / "docs/releases").mkdir(parents=True, exist_ok=True)
    path = root / "docs/releases/v1.2.3.md"
    path.write_text(text)
    return path


def test_notes_prompt_shows_forty_lines_and_asks(root, monkeypatch, capsys):
    path = _notes(root, "\n".join(f"line {i}" for i in range(60)) + "\n")
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "y")
    confirm_notes = release_cli._confirmers(SimpleNamespace(yes=False))[1]
    assert confirm_notes(path) is True
    out = capsys.readouterr().out
    assert "line 39" in out and "line 40" not in out
    assert prompts == ["Use these notes? [y/N/e] "]


def test_notes_prompt_edit_shows_again_and_no_stops(root, monkeypatch, capsys):
    path = _notes(root)
    edited = []
    monkeypatch.setattr(release_cli, "_edit", lambda p: edited.append(p))
    answers = iter(["e", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    confirm_notes = release_cli._confirmers(SimpleNamespace(yes=False))[1]
    assert confirm_notes(path) is False
    assert edited == [path] and capsys.readouterr().out.count("# v1.2.3") == 2


def test_yes_skips_the_notes_question(root, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: 1 / 0)
    assert release_cli._confirmers(SimpleNamespace(yes=True))[1](_notes(root)) is True


def test_bump_with_unreleased_notes_asks_and_defaults_to_yes(root, monkeypatch):
    tty(monkeypatch, True)
    calls = fake_run(monkeypatch)
    _notes(root)
    monkeypatch.setattr(release_cli.release_version, "released", lambda *a, **k: False)
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or "")
    assert release_cli.main(["run", "--bump", "minor"]) == 0
    assert asked == ["v1.2.3 has notes and was never released. Release v1.2.3 instead? [Y/n] "]
    assert calls["plan"].version == "1.2.3"


def test_bump_keeps_the_bump_when_answered_no_or_no_notes(root, monkeypatch):
    tty(monkeypatch, True)
    calls = fake_run(monkeypatch)
    monkeypatch.setattr(release_cli.release_version, "released", lambda *a, **k: False)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert release_cli.main(["run", "--bump", "minor"]) == 0  # no notes file: no question
    assert calls["plan"].version == "1.3.0"
    _notes(root)
    assert release_cli.main(["run", "--bump", "minor", "--mode", "auto"]) == 0
    assert calls["plan"].version == "1.3.0"


# --- why and rerun -------------------------------------------------------------


def _stopped(root, cause="no-runner"):
    from whyline.release.ci_failure import Failure

    failure = Failure(cause=cause, run_id="77", job="test (macos)", workflow="ci", attempt=1)
    release_state.save(root, release_state.State(
        version="1.2.4", step_ids=["ready"], mode="auto", failed_id="ready",
        failure=failure.to_dict()))
    return failure


def test_why_prints_the_failure_text(root, capsys):
    failure = _stopped(root)
    assert release_cli.main(["why"]) == 0
    assert capsys.readouterr().out.strip() == failure.text()


def test_why_without_a_stopped_release(root, capsys):
    assert release_cli.main(["why"]) == 0
    assert "The release isn't stopped" in capsys.readouterr().out


def test_rerun_without_a_failure(root, capsys):
    assert release_cli.main(["rerun", "--yes"]) == 1
    assert "Nothing to rerun" in capsys.readouterr().err


@pytest.mark.parametrize("cause,asked", [("tests", True), ("no-runner", False)])
def test_rerun_asks_only_for_tests(root, monkeypatch, cause, asked):
    _stopped(root, cause)
    tty(monkeypatch, True)
    questions = []
    monkeypatch.setattr("builtins.input", lambda q="": questions.append(q) or "y")
    monkeypatch.setattr(engine, "rerun_and_resume",
                        lambda r, steps, **kw: engine.Result(engine.DONE, "The release finished."))
    assert release_cli.main(["rerun"]) == 0
    assert bool(questions) is asked
    if asked:
        assert "Rerunning won't fix a real failure" in questions[0]


def test_rerun_declined_does_nothing(root, monkeypatch):
    _stopped(root, "tests")
    tty(monkeypatch, True)
    monkeypatch.setattr("builtins.input", lambda q="": "n")
    monkeypatch.setattr(engine, "rerun_and_resume",
                        lambda *a, **k: pytest.fail("must not rerun"))
    assert release_cli.main(["rerun"]) == 1


def test_ask_prints_the_answer(root, monkeypatch, capsys):
    from whyline.release import ci_failure

    failure = ci_failure.Failure(cause="tests", run_id="7", job="test")
    release_state.save(root, release_state.State(
        version="1.2.3", step_ids=["a"], failed_id="a", failure=failure.to_dict()))
    seen = []
    monkeypatch.setattr(release_plan, "default_ask_agent", lambda r: lambda p: seen.append(p) or
                        "<answer>Fix it.</answer>\nNEEDS_CODE_FIX: yes")
    monkeypatch.setattr(release_ready, "default_run",
                        lambda args, cwd=None, **kw: SimpleNamespace(returncode=1, stdout="", stderr=""))
    assert release_cli.main(["ask"]) == 0
    assert "Fix it." in capsys.readouterr().out
    assert seen


def test_ask_without_a_stopped_release(root, capsys):
    assert release_cli.main(["ask"]) == 1
    assert "isn't stopped" in capsys.readouterr().err


def test_settings_prints_and_saves_on_no_runner(root, capsys):
    from whyline.release import config as release_config

    assert release_cli.main(["settings"]) == 0
    assert "release.on_no_runner = ask" in capsys.readouterr().out
    assert release_cli.main(["settings", "--on-no-runner", "rerun once"]) == 0
    assert release_config.load(root).on_no_runner == "rerun once"
    assert release_cli.main(["settings", "--on-no-runner", "off"]) == 0
    assert release_config.load(root).on_no_runner == "off"
    assert release_cli.main(["settings"]) == 0
    assert "release.on_no_runner = off" in capsys.readouterr().out
