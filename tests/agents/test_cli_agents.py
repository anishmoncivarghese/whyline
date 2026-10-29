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

