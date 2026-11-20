import argparse

import pytest

from whyline import credentials
from whyline.tools import catalogue, cli, mcp_config

SECRET = "s3cr3t-value-123"
ENTRY_TEXT = (
    '[[connector]]\nname = "x"\ntitle = "X"\nabout = "a"\nargs = []\n'
    'command = "npx"\nsource = "https://e.com"\n'
    '[[connector.credentials]]\nvar = "X_TOKEN"\nlabel = "Token"\nwhere = "https://e.com/t"\n'
)


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    kept = {}

    def put(name, value, run, which, system):
        kept[name] = value

    monkeypatch.setattr(credentials, "_put", put)
    return kept


@pytest.fixture
def entry():
    return catalogue.parse(ENTRY_TEXT)[0]


def test_nothing_enabled_before_test(stored, entry):
    seen = []

    def fake_test(name):
        seen.append(mcp_config.load()[name].enabled)
        return "2 tools: a, b"

    assert catalogue.add(entry, {"X_TOKEN": SECRET}, test=fake_test) == "2 tools: a, b"
    assert seen == [False]
    assert mcp_config.load()["x"].enabled is True


def test_failed_test_leaves_it_disabled_with_the_reason(stored, entry):
    def failing(name):
        raise RuntimeError("server would not start")

    assert catalogue.add(entry, {"X_TOKEN": SECRET}, test=failing) == "server would not start"
    assert mcp_config.load()["x"].enabled is False


def test_credentials_go_only_to_the_keychain(stored, entry, tmp_path):
    catalogue.add(entry, {"X_TOKEN": SECRET}, test=lambda n: "ok")
    assert stored == {"x-x-token": SECRET}
    assert mcp_config.load()["x"].env == {"X_TOKEN": "x-x-token"}
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(errors="ignore")


def test_already_added(stored, entry):
    assert not catalogue.added(entry)
    catalogue.add(entry, {"X_TOKEN": SECRET}, test=lambda n: "ok")
    assert catalogue.added(entry)
    with pytest.raises(ValueError, match="already added"):
        catalogue.add(entry, {"X_TOKEN": SECRET}, test=lambda n: "ok")


def test_cli_lists_and_adds(stored, monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": SECRET)
    monkeypatch.setattr(mcp_config, "test_server", lambda name: "1 tools: a")
    monkeypatch.setattr(catalogue, "load", lambda: catalogue.parse(ENTRY_TEXT))

    def run(*words):
        return cli.run(argparse.Namespace(tools_command="catalogue", words=list(words)))

    assert run() == 0
    assert "x  X" in capsys.readouterr().out
    assert run("add", "x") == 0
    assert "Added x" in capsys.readouterr().out
    assert stored == {"x-x-token": SECRET}
    assert run() == 0
    assert "added" in capsys.readouterr().out
    assert run("add", "x") == 0
    assert "already added" in capsys.readouterr().out
    assert run("add", "nope") == 1
