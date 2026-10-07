from whyline import cli


def test_agents_list_and_unknown_name(repo, home, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    (repo / ".whyline/agents").mkdir(parents=True)
    (repo / ".whyline/agents/a.toml").write_text('name="a"\ninstructions="x"\nrunner="claude"')
    assert cli.main(["agents", "list"]) == 0
    out = capsys.readouterr().out
    assert "a (repo)" in out and "on demand" in out and "not accepted" in out
    assert cli.main(["agents", "run", "nope"]) != 0
    assert "No agent named nope" in capsys.readouterr().err
