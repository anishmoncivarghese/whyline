import pytest

from whyline.agents import definitions as d


def _parse(repo, extra):
    path = repo / ".whyline/agents/m.toml"
    text = f'name = "m"\ninstructions = "x"\nrunner = "claude"\nbackup = ["codex"]\n{extra}'
    return d.parse(text, kind="repo", path=path, repo_root=repo), path


def test_old_model_field_keeps_the_hash(repo):
    # the canonical text an old-format definition was written as, before [models]
    legacy = ('name = "m"\ninstructions = "x"\nrunner = "claude"\nbackup = ["codex"]\n'
              'model = "sonnet"\nknowledge = []\ntimeout_minutes = 15\n\n'
              '[trigger]\nkind = "manual"\nmin_gap_minutes = 10\n')
    a = d.parse(legacy, kind="repo", path=repo / ".whyline/agents/m.toml", repo_root=repo)
    assert a.models == {"claude": "sonnet"} and a.model == "sonnet"
    again = d.render(a)
    assert 'model = "sonnet"' in again and "[models]" not in again
    assert d.definition_hash(again) == d.definition_hash(legacy)


def test_models_table_is_read_and_rendered(repo):
    a, path = _parse(repo, '[models]\nclaude = "sonnet"\ncodex = "gpt-x"\n')
    assert a.models == {"claude": "sonnet", "codex": "gpt-x"}
    out = d.render(a)
    assert "[models]" in out
    assert d.parse(out, kind="repo", path=path, repo_root=repo).models == a.models


def test_a_model_for_a_cli_that_is_not_the_runner_or_a_backup_is_refused(repo):
    with pytest.raises(d.DefinitionError, match="grok"):
        _parse(repo, '[models]\ngrok = "x"\n')


def test_no_models_renders_no_table(repo):
    a, _ = _parse(repo, "")
    assert "[models]" not in d.render(a) and "model =" not in d.render(a)
