"""Pays tools and their limits on an agent definition (RSK-2)."""
import pytest

from whyline import cli
from whyline.agents import definitions as d
from whyline.tools import mcp_config, risk

BASE = 'name = "ok"\ninstructions = "x"\nrunner = "claude"\n'


@pytest.fixture(autouse=True)
def shop(home, monkeypatch):
    mcp_config.save_server(mcp_config.Server(
        "files", "cmd", tools_hash="h1",
        tools=(mcp_config.Tool("read"), mcp_config.Tool("write"))))
    real = risk.of
    monkeypatch.setattr(risk, "of", lambda s, t: "pays" if (s, t) == ("files", "write") else real(s, t))


def _parse(repo, extra):
    return d.parse(BASE + extra, kind="repo", path=repo / ".whyline/agents/ok.toml", repo_root=repo)


def test_pays_is_never_allowed(repo, monkeypatch, capsys):
    with pytest.raises(d.DefinitionError, match=r"files\.write moves money and can only be Ask first"):
        _parse(repo, '[tools]\n"files.write" = "allowed"')
    assert _parse(repo, '[tools]\n"files.write" = "ask"').tools == {"files.write": "ask"}
    assert _parse(repo, '[tools]\n"files.read" = "allowed"').tools == {"files.read": "allowed"}
    # a hand-edited file is broken, with the reason, in discover and in the CLI
    path = repo / ".whyline/agents/ok.toml"
    path.parent.mkdir(parents=True)
    path.write_text(BASE + '[tools]\n"files.write" = "allowed"\n')
    (found,) = [i for i in d.discover(repo) if i.path == path]
    assert isinstance(found, d.Broken) and "can only be Ask first" in found.error
    monkeypatch.chdir(repo)
    assert cli.main(["agents", "list"]) == 0
    assert "can only be Ask first" in capsys.readouterr().out


def test_limits_parse_and_round_trip(repo):
    a = _parse(repo, '[limits."shop.buy"]\nper_call = 20\nper_day = 50.5\ncurrency = "usd"\n')
    assert a.limits == {"shop.buy": d.Limit("USD", 20.0, 50.5)}
    again = d.parse(d.render(a), kind="repo", path=a.path, repo_root=repo)
    assert again.limits == a.limits


@pytest.mark.parametrize("body", [
    'per_call = 0\ncurrency = "USD"', 'per_day = -1\ncurrency = "USD"',
    'per_call = "5"\ncurrency = "USD"', 'per_call = true\ncurrency = "USD"', "per_call = 5",
    'per_call = 5\ncurrency = "USD"\nextra = 1',
])
def test_bad_limits_are_refused(repo, body):
    with pytest.raises(d.DefinitionError, match="limits"):
        _parse(repo, f'[limits."shop.buy"]\n{body}\n')
