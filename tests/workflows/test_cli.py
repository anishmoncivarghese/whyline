import pytest

from whyline.cli import main
from whyline.workflows import service, state

COMMANDS = ["list", "show", "validate", "new", "accept", "pause", "resume", "run", "runs",
            "run-show", "cancel", "approve", "deny", "resolve", "retry", "dry-run", "cap",
            "_execute"]

FLOW = '''
name = "flow"
version = 1

[trigger]
kind = "manual"

[[input]]
name = "who"
type = "string"
default = "world"

[[step]]
id = "hi"
type = "set"
[step.values]
greeting = "hello {{ inputs.who }}"
'''


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(home)  # no .git above: only personal workflows
    return home


def write_flow(home):
    folder = home / ".whyline" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "flow.toml").write_text(FLOW)


def run_cli(capsys, *argv):
    code = main(["workflow", *argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_help_lists_every_command(capsys):
    with pytest.raises(SystemExit) as stop:
        main(["workflow", "--help"])
    assert stop.value.code == 0
    out = capsys.readouterr().out
    for command in COMMANDS:
        assert command in out


def test_list_when_empty_and_after_new(home, capsys):
    code, out, _ = run_cli(capsys, "list")
    assert code == 0 and "No workflows yet" in out
    code, out, _ = run_cli(capsys, "new", "fresh")
    assert code == 0 and "fresh.toml" in out
    code, out, _ = run_cli(capsys, "list")
    assert code == 0 and "fresh" in out and "needs_review" in out and "on demand" in out


def test_errors_print_and_exit_non_zero(home, capsys):
    code, out, err = run_cli(capsys, "show", "nope")
    assert code == 1 and out == "" and "No workflow named nope" in err
    code, _, err = run_cli(capsys, "run-show", "42")
    assert code == 1 and "No run 42" in err
    code, _, err = run_cli(capsys, "cancel", "42")
    assert code == 1 and "No run 42" in err
    code, _, err = run_cli(capsys, "new", "Bad Name")
    assert code == 1 and "lower-case" in err
    code, _, err = run_cli(capsys, "new", "x", "--repo")
    assert code == 1 and "repository" in err
    code, _, err = run_cli(capsys, "cap", "-3")
    assert code == 1 and "whole number" in err
    code, _, err = run_cli(capsys, "approve", "1", "nonce")
    assert code == 1 and "out of date" in err


def test_validate_a_file(home, capsys):
    good = home / "good.toml"
    good.write_text(FLOW)
    assert run_cli(capsys, "validate", str(good))[:2] == (0, "OK\n")
    bad = home / "bad.toml"
    bad.write_text('name = "x"\n[[step]]\nid = "a"\ntype = "nope"\n')
    code, out, err = run_cli(capsys, "validate", str(bad))
    assert code == 1 and out == "" and "type" in err
    code, _, err = run_cli(capsys, "validate", str(home / "missing.toml"))
    assert code == 1 and "missing.toml" in err


def test_accept_requires_yes_without_a_terminal(home, capsys):
    write_flow(home)
    code, out, err = run_cli(capsys, "accept", "flow")
    assert code == 1 and "Trigger: manual" in out and "--yes" in err
    assert service.rows(None)[0].status == state.NEEDS_REVIEW
    code, out, _ = run_cli(capsys, "accept", "flow", "--yes")
    assert code == 0 and "Accepted flow" in out
    assert service.rows(None)[0].status == state.ACTIVE


def test_show_pause_resume(home, capsys):
    write_flow(home)
    run_cli(capsys, "accept", "flow", "--yes")
    code, out, _ = run_cli(capsys, "show", "flow")
    assert code == 0 and "flow (personal): active" in out and 'name = "flow"' in out
    assert run_cli(capsys, "pause", "flow")[1] == "Paused flow\n"
    assert service.rows(None)[0].status == state.PAUSED
    assert run_cli(capsys, "resume", "flow")[1] == "Resumed flow\n"
    assert service.rows(None)[0].status == state.ACTIVE


def test_run_with_inputs_then_runs_and_run_show(home, capsys, monkeypatch):
    write_flow(home)
    spawned = []
    monkeypatch.setattr("whyline.workflows.tick._spawn", spawned.append)
    code, _, err = run_cli(capsys, "run", "flow")
    assert code == 1 and "accept it first" in err
    run_cli(capsys, "accept", "flow", "--yes")
    code, _, err = run_cli(capsys, "run", "flow", "--input", "nope=1")
    assert code == 1 and 'unknown input "nope"' in err
    code, _, err = run_cli(capsys, "run", "flow", "--input", "novalue")
    assert code == 1 and "key=value" in err
    code, out, _ = run_cli(capsys, "run", "flow", "--input", "who=Ann")
    assert code == 0 and out == "Started run 1\n" and spawned == [1]
    code, out, _ = run_cli(capsys, "runs", "flow")
    assert code == 0 and "running" in out and "manual" in out
    code, out, _ = run_cli(capsys, "run-show", "1")
    assert code == 0 and "Run 1" in out and "running" in out
    code, out, _ = run_cli(capsys, "cancel", "1")
    assert code == 0 and "cancelled" in out
    code, out, _ = run_cli(capsys, "retry", "1")
    assert code == 0 and out == "Started run 2\n"


def test_execute_runs_a_queued_run_to_the_end(home, capsys):
    write_flow(home)
    run_cli(capsys, "accept", "flow", "--yes")
    run_id = service.run_now("flow", {"who": "Bo"}, source="manual", repo_root=None,
                             spawn=lambda _id: None)
    assert run_cli(capsys, "_execute", str(run_id))[0] == 0
    assert service.run_detail(run_id).run["status"] == "succeeded"
    code, out, _ = run_cli(capsys, "runs", "flow")
    assert "succeeded" in out


def test_dry_run_prints_the_walk(home, capsys):
    write_flow(home)
    code, out, _ = run_cli(capsys, "dry-run", "flow", "--input", "who=Cy")
    assert code == 0 and 'greeting = "hello Cy"' in out and "nothing is run" in out
    assert service.runs("flow", None) == []


def test_resolve_and_approve_commands(home, capsys):
    write_flow(home)
    run_cli(capsys, "accept", "flow", "--yes")
    run_id = service.run_now("flow", {}, source="manual", repo_root=None,
                             spawn=lambda _id: None)
    code, _, err = run_cli(capsys, "resolve", str(run_id), "done")
    assert code == 1 and "not unknown_outcome" in err
    with pytest.raises(SystemExit):
        main(["workflow", "resolve", str(run_id), "maybe"])


def test_cap_shows_and_sets(home, capsys):
    assert run_cli(capsys, "cap")[1] == "Daily agent step cap: none\n"
    assert run_cli(capsys, "cap", "4")[1] == "Daily agent step cap: 4\n"
    assert service.get_cap() == 4
