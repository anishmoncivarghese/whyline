import pytest

from whyline import cli, credentials
from whyline.tools import made, made_draft

TOOL = """name = "weather"
about = "Weather"
method = "GET"
url = "https://api.example.com/v1/{city}"
credential = "weather-key"
credential_in = "header:Authorization"
risk = "reads"

[[inputs]]
name = "city"
type = "string"
"""


class Net:
    def __init__(self):
        self.sent = []

    def resolve(self, host):
        return ["93.184.216.34"]

    def request(self, method, url, headers, body, **kw):
        self.sent.append((method, url, dict(headers)))
        return 200, {}, b"sunny"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    net = Net()
    monkeypatch.setattr(made, "default_resolve", net.resolve)
    monkeypatch.setattr(made, "default_request", net.request)
    monkeypatch.setattr(made_draft.made, "default_resolve", net.resolve)
    monkeypatch.setattr(credentials, "value", lambda name: "s3cr3t")
    (tmp_path / "weather.toml").write_text(TOOL)
    return net


def run(*argv):
    return cli.main(["tools", "made", *argv])


def answer(monkeypatch, text):
    monkeypatch.setattr("builtins.input", lambda prompt="": text)


def test_new_list_show(home, capsys):
    assert run("new", "--from", "weather.toml") == 0
    assert made.load("weather") is not None and not made.accepted(made.load("weather"))
    run("list")
    assert "weather  not accepted" in capsys.readouterr().out
    run("show", "weather")
    assert "GET https://api.example.com/v1/{city}" in capsys.readouterr().out


def test_new_refuses_an_invalid_file(home, tmp_path, capsys):
    (tmp_path / "bad.toml").write_text(TOOL.replace("https", "http"))
    assert run("new", "--from", "bad.toml") == 1
    assert "https" in capsys.readouterr().err and made.load_all() == []


def test_test_shows_the_masked_request_and_sends_only_after_yes(home, monkeypatch, capsys):
    run("new", "--from", "weather.toml")
    answer(monkeypatch, "n")
    assert run("test", "weather", "city=Paris") == 1
    out = capsys.readouterr().out
    assert "This will send a GET request to api.example.com" in out
    assert "Authorization: •••" in out and "s3cr3t" not in out
    assert home.sent == []
    answer(monkeypatch, "y")
    assert run("test", "weather", "city=Paris") == 0
    assert "sunny" in capsys.readouterr().out
    assert home.sent[0][1] == "https://api.example.com/v1/Paris"
    assert home.sent[0][2]["Authorization"] == "s3cr3t"


def test_test_yes_skips_the_question(home, monkeypatch, capsys):
    run("new", "--from", "weather.toml")
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("asked"))
    assert run("test", "weather", "city=Rome", "--yes") == 0
    assert len(home.sent) == 1


def test_test_needs_key_value_inputs(home, capsys):
    run("new", "--from", "weather.toml")
    assert run("test", "weather", "Paris", "--yes") == 1
    assert "key=value" in capsys.readouterr().err and home.sent == []


def test_accept_asks_first(home, monkeypatch, capsys):
    run("new", "--from", "weather.toml")
    answer(monkeypatch, "")
    assert run("accept", "weather") == 1
    assert not made.accepted(made.load("weather"))
    answer(monkeypatch, "yes")
    assert run("accept", "weather") == 0
    assert made.accepted(made.load("weather"))


def test_accept_yes_and_remove(home, capsys):
    run("new", "--from", "weather.toml")
    assert run("accept", "weather", "--yes") == 0
    assert run("remove", "weather") == 0
    assert made.load("weather") is None


def test_unknown_tool(home, capsys):
    assert run("show", "nope") == 1
    assert "No made tool named nope" in capsys.readouterr().err
