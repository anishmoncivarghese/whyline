import os
from whyline import cli, model


def run_in(repo, argv, capsys, monkeypatch=None, input_answers=None):
    if monkeypatch is not None and input_answers is not None:
        answers = iter(input_answers)
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        code = cli.main(argv)
    finally:
        os.chdir(previous)
    return code, capsys.readouterr().out


def test_model_set_writes_one_agent(repo, capsys):
    code, out = run_in(repo, ["model", "set", "codex", "gpt-5-codex"], capsys)
    assert code == cli.EXIT_OK
    assert model.load(repo.path) == {"codex": "gpt-5-codex"}


def test_model_status_with_nothing_set_says_so(repo, capsys):
    code, out = run_in(repo, ["model", "status"], capsys)
    assert code == cli.EXIT_OK
    assert "nothing set" in out.lower()


def test_model_status_prints_current_selections(repo, capsys):
    model.save(repo.path, {"codex": "gpt-5-codex"})
    code, out = run_in(repo, ["model", "status"], capsys)
    assert "gpt-5-codex" in out


def test_interactive_model_selection_writes_all_three_answers(repo, capsys, monkeypatch):
    code, out = run_in(
        repo,
        ["model"],
        capsys,
        monkeypatch,
        input_answers=["gpt-5-codex", "opus", ""],
    )
    assert code == cli.EXIT_OK
    assert model.load(repo.path) == {"codex": "gpt-5-codex", "claude": "opus"}


def test_interactive_model_selection_prints_the_antigravity_caveat(repo, monkeypatch, capsys):
    answers = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        cli.main(["model"])
    finally:
        os.chdir(previous)
    out = capsys.readouterr().out
    assert "not currently safe" in out or "unattended" in out


def test_cmd_run_passes_model_from_model_load(repo, monkeypatch):
    from whyline import paths, runner

    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()

    model.save(repo.path, {"codex": "gpt-5-codex"})
    launched = []

    def fake_launch(agent, task, brief_text, which=None, exec_fn=None, model=None):
        launched.append((agent, task, brief_text, model))
        return 0

    monkeypatch.setattr(runner, "launch", fake_launch)
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        code = cli.main(["run", "codex", "do task"])
    finally:
        os.chdir(previous)
    assert code == cli.EXIT_OK
    assert len(launched) == 1
    assert launched[0][0] == "codex"
    assert launched[0][3] == "gpt-5-codex"


def test_gitignore_lines_contain_account_and_model():
    assert "account.json" in cli.GITIGNORE_LINES
    assert "model.json" in cli.GITIGNORE_LINES


def test_interactive_model_selection_prints_plan_from_account(repo, monkeypatch, capsys):
    from whyline import account

    account.save_repo(repo.path, {"codex": {"plan": "plus"}, "confirmed": True})
    code, out = run_in(
        repo,
        ["model"],
        capsys,
        monkeypatch,
        input_answers=["", "", ""],
    )
    assert code == cli.EXIT_OK
    assert "codex -- plus" in out
