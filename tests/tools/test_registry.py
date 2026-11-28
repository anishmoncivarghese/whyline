import argparse
import json
import socket
from pathlib import Path

from whyline.tools import cli, registry

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "registry_search.json").read_text(encoding="utf-8"))


def fake_get(url, *, timeout):
    fake_get.calls.append((url, timeout))
    return FIXTURE


fake_get.calls = []


def test_results_map_to_unchecked_entries():
    found = registry.search("weather", get=fake_get)
    url, timeout = fake_get.calls[-1]
    assert url.startswith(registry.REGISTRY_URL) and "search=weather" in url
    assert timeout == 10
    weather, notes, hosted = found
    assert (weather.command, weather.args) == ("npx", ("-y", "@example/weather-mcp"))
    assert weather.title == "io.github.example/weather"
    assert weather.source == "https://github.com/example/weather-mcp"
    assert [c.var for c in weather.credentials] == ["WEATHER_API_KEY"]
    assert weather.checked == "" and weather.tools == () and weather.refused == ""
    assert weather.status == "not checked by whyline yet"
    assert (notes.command, notes.args) == ("uvx", ("notes-mcp",))
    assert registry.last_error() == ""


def test_remote_results_are_refused_with_the_reason():
    hosted = registry.search("hosted", get=fake_get)[2]
    assert hosted.refused == "needs a browser sign-in, which whyline can't do yet"
    assert hosted.command == ""


def test_limit_applies():
    assert len(registry.search("x", get=fake_get, limit=1)) == 1


def test_timeout_gives_empty_list_and_a_reason():
    def slow(url, *, timeout):
        raise socket.timeout("timed out")

    assert registry.search("x", get=slow) == []
    assert "timed out" in registry.last_error()
    registry.search("x", get=fake_get)
    assert registry.last_error() == ""


def test_bad_response_gives_empty_list_and_a_reason():
    assert registry.search("x", get=lambda url, *, timeout: ["nope"]) == []
    assert registry.last_error()


def test_cli_search_prints_the_heading_and_results(monkeypatch, capsys):
    real = registry.search
    monkeypatch.setattr(registry, "search", lambda text, **kw: real(text, get=fake_get))
    args = argparse.Namespace(tools_command="catalogue", words=["search", "weather"])
    assert cli.run(args) == 0
    out = capsys.readouterr().out
    assert registry.HEADING in out
    assert "needs a browser sign-in" in out


def test_cli_search_failure_exits_with_error(monkeypatch, capsys):
    def boom(url, *, timeout):
        raise OSError("offline")

    real = registry.search
    monkeypatch.setattr(registry, "search", lambda text, **kw: real(text, get=boom))
    args = argparse.Namespace(tools_command="catalogue", words=["search", "weather"])
    assert cli.run(args) == 1
    assert "offline" in capsys.readouterr().out
