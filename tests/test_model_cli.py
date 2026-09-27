import os
from whyline import account, cli, model


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
    captured = capsys.readouterr()
    return code, captured.out + captured.err



def _mark_all_available(monkeypatch, tmp_path, home):
    monkeypatch.setattr(account.paths.Path, "home", lambda: home)
    account.save_global({
        agent: {"plan": None, "available": True}
        for agent in ("codex", "claude", "antigravity", "grok")
    })


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


def test_interactive_model_selection_writes_all_four_answers(
    repo, capsys, monkeypatch, tmp_path
):
    home = tmp_path / "home"
    _mark_all_available(monkeypatch, tmp_path, home)
    code, out = run_in(
        repo,
        ["model"],
        capsys,
        monkeypatch,
        input_answers=["gpt-5-codex", "opus", "", "grok-4.6"],
    )
    assert code == cli.EXIT_OK
    assert model.load(repo.path) == {
        "codex": "gpt-5-codex",
        "claude": "opus",
        "grok": "grok-4.6",
    }


def test_interactive_model_selection_offers_grok(
    repo, capsys, monkeypatch, tmp_path
):
    home = tmp_path / "home"
    _mark_all_available(monkeypatch, tmp_path, home)
    # Regression proof: grok was added to runner.AGENTS/MODEL_FLAG in 0.3.3
    # but this loop's own agent tuple was hardcoded and missed it -- fixed
    # in 0.3.4. `whyline run grok`/`model set grok` worked the whole time;
    # only the interactive `whyline model` prompt never asked about it.
    code, out = run_in(
        repo,
        ["model"],
        capsys,
        monkeypatch,
        input_answers=["", "", "", "grok-4.6"],
    )
    assert code == cli.EXIT_OK
    assert model.load(repo.path) == {"grok": "grok-4.6"}


def test_interactive_model_selection_only_offers_available_agents(
    repo, capsys, monkeypatch, tmp_path
):
    from whyline import account
    home = tmp_path / "home"
    monkeypatch.setattr(account.paths.Path, "home", lambda: home)
    account.save_global({
        "codex": {"plan": "plus", "available": True},
        "claude": {"plan": "unknown", "available": False},
        "antigravity": {"plan": None, "available": False},
        "grok": {"plan": None, "available": False},
    })
    code, out = run_in(
        repo, ["model"], capsys, monkeypatch, input_answers=["gpt-5-codex"]
    )
    assert code == cli.EXIT_OK
    assert model.load(repo.path) == {"codex": "gpt-5-codex"}
    assert "claude" not in out.lower() or "Model for claude" not in out


def test_interactive_model_selection_with_nothing_available_says_so(
    repo, capsys, monkeypatch, tmp_path
):
    from whyline import account
    home = tmp_path / "home"
    monkeypatch.setattr(account.paths.Path, "home", lambda: home)
    account.save_global({
        agent: {"plan": None, "available": False}
        for agent in ("codex", "claude", "antigravity", "grok")
    })
    code, out = run_in(repo, ["model"], capsys)
    assert code == cli.EXIT_ERROR
    assert "whyline account detect" in out or "whyline account enable" in out


def test_interactive_model_selection_prints_the_antigravity_caveat(
    repo, monkeypatch, capsys, tmp_path
):
    home = tmp_path / "home"
    _mark_all_available(monkeypatch, tmp_path, home)
    answers = iter(["", "", "", ""])
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

    account.save_repo(repo.path, {"codex": {"plan": "plus", "available": True}, "confirmed": True})
    code, out = run_in(
        repo,
        ["model"],
        capsys,
        monkeypatch,
        input_answers=["", "", "", ""],
    )
    assert code == cli.EXIT_OK
    assert "codex -- plus" in out

