import io
import json
import sys
from pathlib import Path

import pytest

from whyline.tools import made, mcp, mcp_config, serve
from whyline.tools.mcp_config import Server

FAKE = str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")
SECRET = "s3cr3t-value-123"


def _servers(env=None):
    return {"fake": Server(name="fake", command=sys.executable, args=(FAKE,), env=env or {})}


def _tools_json(folder, tools):
    path = folder / "tools.json"
    path.write_text(json.dumps({"run": "r1", "agent": "a", "tools": tools}), encoding="utf-8")
    return path


def _tool(name="echo", permission="allowed", **extra):
    return {"server": "fake", "tool": name, "permission": permission, "description": "Echo it",
            "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}}, **extra}


def _drive(messages, path, **options):
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    stdout = io.StringIO()
    environ = {serve.ENV_VAR: str(path)} if path else {}
    serve.serve(stdin, stdout, environ=environ, **options)
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def _call(name, arguments=None, ident=2):
    return {"jsonrpc": "2.0", "id": ident, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}}}


LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
INIT = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}


def test_no_variable_initializes_and_lists_nothing():
    replies = _drive([INIT, {"jsonrpc": "2.0", "method": "notifications/initialized"}, LIST], None)
    assert replies[0]["result"]["serverInfo"]["name"] == "whyline"
    assert len(replies) == 2
    assert replies[1]["result"]["tools"] == []


def test_missing_file_lists_nothing(tmp_path):
    replies = _drive([LIST], tmp_path / "tools.json")
    assert replies[0]["result"]["tools"] == []


def test_ticked_tools_are_listed_and_nothing_else(tmp_path):
    path = _tools_json(tmp_path, [_tool("echo", read_only=True), _tool("write")])
    tools = _drive([LIST], path, servers=_servers())[0]["result"]["tools"]
    assert [t["name"] for t in tools] == ["fake__echo", "fake__write"]
    assert tools[0]["description"] == "Echo it"
    assert tools[0]["inputSchema"]["properties"]["text"] == {"type": "string"}
    assert tools[0]["annotations"] == {"readOnlyHint": True}
    assert "annotations" not in tools[1]


def test_call_is_forwarded(tmp_path):
    path = _tools_json(tmp_path, [_tool("echo")])
    result = _drive([_call("fake__echo", {"text": "hi"})], path, servers=_servers())[0]["result"]
    assert result["isError"] is False
    assert result["content"][0] == {"type": "text", "text": "hi"}
    assert result["content"][1]["type"] == "image"
    assert result["structuredContent"] == {"ok": True}


def test_unticked_tool_is_refused(tmp_path):
    path = _tools_json(tmp_path, [_tool("echo")])
    reply = _drive([_call("fake__other")], path, servers=_servers())[0]
    assert reply["error"]["message"] == "This agent may not use fake__other."
    assert not (tmp_path / "tool-calls.jsonl").exists()


def test_server_error_is_returned_as_is_error(tmp_path):
    path = _tools_json(tmp_path, [_tool("fail")])
    result = _drive([_call("fake__fail")], path, servers=_servers())[0]["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"] == "it broke"
    record = json.loads((tmp_path / "tool-calls.jsonl").read_text().splitlines()[0])
    assert record["error"] == "it broke"


def test_ask_first_denied_is_not_forwarded(tmp_path):
    path = _tools_json(tmp_path, [_tool("echo", permission="ask")])
    asked = []
    result = _drive([_call("fake__echo")], path, servers=_servers(),
                    ask=lambda folder, tool, args: asked.append(tool) or "denied")[0]["result"]
    assert asked == ["fake__echo"]
    assert result == {"content": [{"type": "text", "text": serve.DENIED_TEXT}], "isError": True}
    record = json.loads((tmp_path / "tool-calls.jsonl").read_text())
    assert record["decision"] == "denied"


def test_ask_first_approved_is_forwarded(tmp_path):
    path = _tools_json(tmp_path, [_tool("echo", permission="ask")])
    result = _drive([_call("fake__echo", {"text": "ok"})], path, servers=_servers(),
                    ask=lambda *a: "approved")[0]["result"]
    assert result["content"][0]["text"] == "ok"
    assert json.loads((tmp_path / "tool-calls.jsonl").read_text())["decision"] == "approved"


def test_call_log_redacts_credentials_and_cuts_length(tmp_path):
    path = _tools_json(tmp_path, [_tool("echo")])
    servers = _servers(env={"TOKEN": "my-key"})
    _drive([_call("fake__echo", {"text": SECRET}),
            _call("fake__echo", {"text": "x" * 5000}, ident=3)],
           path, servers=servers, session_factory=lambda server: _FakeSession(server),
           redaction_values=lambda names: [SECRET] if "my-key" in names else [])
    lines = (tmp_path / "tool-calls.jsonl").read_text().splitlines()
    first, second = (json.loads(line) for line in lines)
    assert SECRET not in lines[0]
    assert "[redacted]" in first["arguments"]
    assert first["tool"] == "fake__echo" and first["decision"] == "allowed"
    assert first["result_size"] > 0 and "duration_s" in first and first["time"]
    assert len(second["arguments"]) == serve.ARGUMENTS_LIMIT


class _FakeSession:
    instances = []

    def __init__(self, server):
        self.entered = self.exited = False
        self.calls = 0
        _FakeSession.instances.append(self)

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        self.exited = True

    def call(self, tool, arguments):
        self.calls += 1
        return mcp.ToolResult(text="done", content=[{"type": "text", "text": "done"}])


def test_sessions_start_once_and_close_at_end(tmp_path):
    _FakeSession.instances = []
    path = _tools_json(tmp_path, [_tool("echo")])
    _drive([_call("fake__echo"), _call("fake__echo", ident=3)], path,
           servers=_servers(), session_factory=_FakeSession)
    assert len(_FakeSession.instances) == 1
    session = _FakeSession.instances[0]
    assert session.entered and session.calls == 2 and session.exited


def test_no_session_starts_without_a_call(tmp_path):
    _FakeSession.instances = []
    path = _tools_json(tmp_path, [_tool("echo")])
    _drive([LIST], path, servers=_servers(), session_factory=_FakeSession)
    assert _FakeSession.instances == []


# --- made tools (MKT-2) -------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    return h


def _made(name="weather", risk="reads", accept=True):
    tool = made.MadeTool(name=name, about="Weather", url="https://api.example.com/{city}",
                         inputs=[made.ToolInput("city", "string", "City")], risk=risk)
    made.save(tool)
    return made.accept(name) if accept else tool


def _made_item(name="weather", permission="allowed"):
    return {"server": "made", "tool": name, "permission": permission, "description": "",
            "input_schema": {"type": "object"}}


@pytest.fixture
def fake_call(monkeypatch):
    seen = []

    def call(tool, args, **kw):
        seen.append((tool.name, args))
        return "sunny"

    monkeypatch.setattr(made, "call", call)
    return seen


def test_made_server_lists_accepted_tools_only(home):
    _made("weather")
    _made("pay", risk="spends")
    _made("draft", accept=False)
    server = mcp_config.load()["made"]
    assert [t.name for t in server.tools] == ["pay", "weather"]
    by_name = {t.name: t for t in server.tools}
    assert by_name["weather"].read_only is True
    assert by_name["pay"].read_only is False
    assert by_name["weather"].input_schema["properties"]["city"] == {"type": "string", "description": "City"}
    assert by_name["weather"].input_schema["required"] == ["city"]
    assert not (home / ".whyline" / "mcp.toml").exists()


def test_saving_a_server_never_writes_made(home):
    _made()
    mcp_config.save_server(mcp_config.Server("other", "cmd"))
    assert "made" not in (home / ".whyline" / "mcp.toml").read_text()
    with pytest.raises(ValueError):
        mcp_config.save_server(mcp_config.Server("made", "cmd"))


def test_made_tool_is_listed_and_callable(tmp_path, home, fake_call):
    _made()
    path = _tools_json(tmp_path, [_made_item()])
    replies = _drive([LIST, _call("made__weather", {"city": "Oslo"})], path, servers={})
    assert [t["name"] for t in replies[0]["result"]["tools"]] == ["made__weather"]
    assert replies[1]["result"] == {"content": [{"type": "text", "text": "sunny"}], "isError": False}
    assert fake_call == [("weather", {"city": "Oslo"})]


def test_made_tool_ask_first_asks_and_logs(tmp_path, home, fake_call):
    _made()
    path = _tools_json(tmp_path, [_made_item(permission="ask")])
    asked = []
    result = _drive([_call("made__weather", {"city": "Oslo"})], path, servers={},
                    ask=lambda folder, tool, args: asked.append(tool) or "approved")[0]["result"]
    assert asked == ["made__weather"]
    assert result["content"][0]["text"] == "sunny"
    record = json.loads((tmp_path / "tool-calls.jsonl").read_text())
    assert (record["tool"], record["decision"], record["result_size"]) == ("made__weather", "approved", 5)


def test_made_tool_ask_first_denied_is_not_run(tmp_path, home, fake_call):
    _made()
    path = _tools_json(tmp_path, [_made_item(permission="ask")])
    result = _drive([_call("made__weather")], path, servers={}, ask=lambda *a: "denied")[0]["result"]
    assert result["content"][0]["text"] == serve.DENIED_TEXT
    assert fake_call == []


def test_changed_made_tool_is_refused_and_logged(tmp_path, home, fake_call):
    tool = _made()
    made.save(made.replace(tool, url="https://evil.example.com/{city}"))
    path = _tools_json(tmp_path, [_made_item()])
    replies = _drive([_call("made__weather"), _call("made__weather", ident=3)], path, servers={})
    assert replies[0]["result"]["isError"] is True
    assert replies[0]["result"]["content"][0]["text"] == "made.weather is not accepted"
    assert replies[1]["result"]["isError"] is True
    assert fake_call == []
    record = json.loads((tmp_path / "tool-calls.jsonl").read_text().splitlines()[0])
    assert record["error"] == "made.weather is not accepted"


def test_removed_made_tool_is_refused(tmp_path, home, fake_call):
    _made()
    made.remove("weather")
    path = _tools_json(tmp_path, [_made_item()])
    result = _drive([_call("made__weather")], path, servers={})[0]["result"]
    assert result["content"][0]["text"] == "made.weather is not accepted"
    assert fake_call == []
