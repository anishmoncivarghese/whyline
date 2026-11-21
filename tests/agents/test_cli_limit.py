"""``whyline tools risk`` and ``whyline agents limit`` (RSK-3)."""
import pytest

from whyline import cli
from whyline.agents import definitions as d
from whyline.tools import mcp_config, risk

AGENT = (
    'name = "ok"\ninstructions = "x"\nrunner = "claude"\n'
    '[tools]\n"files.write" = "ask"\n"files.look" = "allowed"\n'
)


@pytest.fixture(autouse=True)
def shop(home, repo, monkeypatch):
    mcp_config.save_server(mcp_config.Server(
        "files", "cmd", tools_hash="h1",
        tools=(mcp_config.Tool("look", read_only=True), mcp_config.Tool("write"))))
    path = repo / ".whyline/agents/ok.toml"
    path.parent.mkdir(parents=True)
    path.write_text(AGENT)
    monkeypatch.chdir(repo)
    return path


def test_risk_shows_and_raises_but_never_lowers(capsys):
    assert cli.main(["tools", "risk", "files.look"]) == 0
    assert capsys.readouterr().out.strip() == "files.look  reads"
    assert cli.main(["tools", "risk", "files.write"]) == 0
    assert capsys.readouterr().out.strip() == "files.write  writes"
    assert cli.main(["tools", "risk", "files.write", "sends"]) == 0
    assert capsys.readouterr().out.strip() == "files.write  sends"
    assert risk.of("files", "write") == "sends"
    assert cli.main(["tools", "risk", "files.write", "reads"]) == 1
    assert "never lowered" in capsys.readouterr().err
    assert risk.of("files", "write") == "sends"
    assert cli.main(["tools", "risk", "files.write", "bogus"]) == 1
    assert cli.main(["tools", "risk", "files.nothing"]) == 1
    assert "No tool named files.nothing" in capsys.readouterr().err


def test_limit_is_saved_in_the_agent(shop):
    risk.set_level("files", "write", "pays")
    argv = ["agents", "limit", "ok", "files.write", "--per-call", "20", "--per-day", "50.5",
            "--currency", "eur"]
    assert cli.main(argv) == 0
    again = d.load(shop, kind="repo", repo_root=shop.parents[2])
    assert again.limits == {"files.write": d.Limit("EUR", 20.0, 50.5)}
    assert again.tools == {"files.write": "ask", "files.look": "allowed"}


def test_limit_needs_a_pays_tool_the_agent_uses_and_real_amounts(shop, capsys):
    base = ["agents", "limit", "ok", "files.write", "--per-call", "20", "--per-day", "50",
            "--currency", "EUR"]
    assert cli.main(base) == 1  # writes, not pays
    assert "not pays" in capsys.readouterr().err
    risk.set_level("files", "write", "pays")
    assert cli.main(["agents", "limit", "ok", "files.other", *base[4:]]) == 1
    assert "does not use files.other" in capsys.readouterr().err
    assert cli.main([*base[:5], "0", *base[6:]]) == 2
    assert "Set both limits for files.write" in capsys.readouterr().err
    assert "limits" not in shop.read_text()
