from whyline import cli

NO_AGENTS = "No agents yet. Create one with New in the console's Agents tab."


def test_agents_list_when_there_are_none_says_how_to_create_one(repo, home, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    code = cli.main(["agents", "list"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out == NO_AGENTS + "\n"


def test_agents_list_and_unknown_name(repo, home, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    (repo / ".whyline/agents").mkdir(parents=True)
    (repo / ".whyline/agents/a.toml").write_text('name="a"\ninstructions="x"\nrunner="claude"')
    assert cli.main(["agents", "list"]) == 0
    out = capsys.readouterr().out
    assert "a (repo)" in out and "on demand" in out and "not accepted" in out
    assert cli.main(["agents", "run", "nope"]) != 0
    assert "No agent named nope" in capsys.readouterr().err


def test_agents_templates_and_new_from_template_cli(repo, home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    assert cli.main(["agents", "templates"]) == 0
    listed = capsys.readouterr()
    assert listed.err == ""
    assert "example-digest" in listed.out
    assert "Example digest" in listed.out
    assert "Read-only summary" in listed.out

    workdir = tmp_path / "my-digest-dir"
    assert cli.main([
        "agents", "new", "--from", "example-digest",
        "--name", "my-digest", "--workdir", str(workdir),
    ]) == 0
    created = capsys.readouterr()
    assert created.err == ""
    assert "my-digest (personal)" in created.out
    assert str(workdir) in created.out
    assert "Not accepted yet" in created.out
    assert (workdir / "notes.md").is_file()

    assert cli.main(["agents", "list"]) == 0
    rows_out = capsys.readouterr().out
    assert "my-digest (personal)" in rows_out
    assert "on demand" in rows_out
    assert "not accepted" in rows_out

    # Name clash is refused on the CLI.
    assert cli.main([
        "agents", "new", "--from", "example-digest",
        "--name", "my-digest", "--workdir", str(tmp_path / "other"),
    ]) != 0
    assert "already exists" in capsys.readouterr().err

    # Defaults for --name and --workdir create ~/.whyline/<template>.
    assert cli.main(["agents", "new", "--from", "example-digest"]) == 0
    default_out = capsys.readouterr().out
    assert "example-digest (personal)" in default_out
    assert "~/.whyline/example-digest" in default_out
    assert (home / ".whyline/example-digest/notes.md").is_file()

    # Unknown template fails cleanly.
    assert cli.main(["agents", "new", "--from", "no-such-template"]) != 0
    assert "unknown template" in capsys.readouterr().err


def test_agents_models_lists_adds_and_removes(home, capsys):
    assert cli.main(["agents", "models", "codex", "--add", "my-model"]) == 0
    assert capsys.readouterr().out == ""
    assert cli.main(["agents", "models", "codex"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "gpt-5.6" in lines
    assert "my-model (added by you)" in lines
    assert cli.main(["agents", "models", "codex", "--remove", "my-model"]) == 0
    capsys.readouterr()
    assert cli.main(["agents", "models", "codex"]) == 0
    assert "my-model" not in capsys.readouterr().out
    assert cli.main(["agents", "models", "codex", "--add", "bad id!"]) != 0
    assert "not a model id" in capsys.readouterr().err


def test_agents_new_model_and_model_for_backup(home, tmp_path, capsys):
    assert cli.main([
        "agents", "new", "--from", "example-digest", "--name", "m1", "--workdir", str(tmp_path / "w"),
        "--model", "sonnet", "--model-for", "codex=gpt-5.6",
    ]) == 0
    capsys.readouterr()
    text = (home / ".whyline/agents/m1.toml").read_text()
    assert '"claude" = "sonnet"' in text
    assert '"codex" = "gpt-5.6"' in text


def test_agents_new_model_for_other_cli_is_refused(home, tmp_path, capsys):
    code = cli.main([
        "agents", "new", "--from", "example-digest", "--name", "m2", "--workdir", str(tmp_path / "w"),
        "--model-for", "grok=grok-4",
    ])
    assert code != 0
    assert "models names grok, which is not the runner or a backup" in capsys.readouterr().err
    assert not (home / ".whyline/agents/m2.toml").exists()
    assert cli.main(["agents", "new", "--from", "example-digest", "--model-for", "oops"]) != 0
    assert "CLI=ID" in capsys.readouterr().err

