import json
import os
import sys
from pathlib import Path

import pytest

from whyline import cli
from whyline.tools import mcp, mcp_config, users
from whyline.tools.mcp_config import Server

FAKE = str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")
SECRET = "s3cr3t-value-123"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(users, "_providers", {})
    return tmp_path


def _server(*extra, env=None):
    return Server(name="fake", command=sys.executable, args=(FAKE, *extra), env=env or {})


def _tools_file(tmp_path, count=5):
    path = tmp_path / "tools.json"
    path.write_text(json.dumps([
        {"name": f"t{i}", "description": f"d{i}", "inputSchema": {"type": "object", "n": i}}
        for i in range(count)
    ]), encoding="utf-8")
    return str(path)


def test_initialize_list_two_pages_and_call(tmp_path):
    with mcp.Session(_server("--tools", _tools_file(tmp_path, 3)), timeout_s=10) as session:
        tools = session.list_tools()
        assert [t.name for t in tools] == ["t0", "t1", "t2"]
        assert tools[0].read_only is None
        result = session.call("t0", {"text": "hi"})
    assert result.text == "hi\n[image]\n[resource file:///a]"
    assert result.structured == {"ok": True}
    assert result.is_error is False
    assert result.content[1]["type"] == "image"


def test_read_only_hint(tmp_path):
    with mcp.Session(_server(), timeout_s=10) as session:
        assert session.list_tools()[0].read_only is True


def test_tool_error_is_not_an_exception():
    with mcp.Session(_server(), timeout_s=10) as session:
        result = session.call("fail", {})
    assert result.is_error is True
    assert result.text == "it broke"


@pytest.mark.skipif(os.name == "nt", reason="process groups")
def test_hung_server_is_killed_at_timeout():
    with pytest.raises(mcp.McpError, match="did not answer tools/call"):
        with mcp.Session(_server("--hang-on", "echo"), timeout_s=1) as session:
            pid = session.pid
            session.call("echo", {})
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)


def test_garbage_output_gives_plain_error():
    with pytest.raises(mcp.McpError, match="not JSON"):
        with mcp.Session(_server("--garbage"), timeout_s=10) as session:
            session.list_tools()


def test_early_exit_gives_plain_error():
    with pytest.raises(mcp.McpError, match="exited early"):
        with mcp.Session(_server("--exit-on", "echo"), timeout_s=10) as session:
            session.call("echo", {})


def test_missing_command_is_plain_error():
    with pytest.raises(mcp.McpError, match="could not start"):
        with mcp.Session(Server(name="x", command="/no/such/command-xyz"), timeout_s=2):
            pass


def test_mcp_secret_never_leaves_env():
    server = _server("--echo-env", "TOKEN", "--hang-on", "echo", env={"TOKEN": "tok"})
    with pytest.raises(mcp.McpError) as caught:
        with mcp.Session(server, timeout_s=1, secret_value=lambda name: SECRET) as session:
            assert SECRET not in " ".join(server.args)
            assert session.call("env", {}).text == "seen"
            session.call("echo", {})
    message = str(caught.value)
    assert SECRET not in message
    assert "env TOKEN=[redacted]" in message


def test_stderr_tail_is_limited_to_20_lines():
    session = mcp.Session(_server())
    for i in range(50):
        session._stderr.append(f"line {i}")
    error = session._fail("boom")
    assert "line 29" not in str(error) and "line 30" in str(error) and "line 49" in str(error)


def test_tools_hash_ignores_order_and_description():
    a = mcp.Tool("a", "x", {"p": 1})
    b = mcp.Tool("b", "y", {"p": 2})
    assert mcp.tools_hash([a, b]) == mcp.tools_hash([b, mcp.Tool("a", "other", {"p": 1})])
    assert mcp.tools_hash([a, b]) != mcp.tools_hash([a])


def test_test_stores_tools_and_hash(home, tmp_path, capsys):
    mcp_config.save_server(_server("--tools", _tools_file(tmp_path, 12)))
    summary = mcp_config.test_server("fake")
    assert summary == "12 tools: " + ", ".join(f"t{i}" for i in range(10))
    stored = mcp_config.load()["fake"]
    assert [t.name for t in stored.tools] == [f"t{i}" for i in range(12)]
    assert len(stored.tools_hash) == 64
    assert cli.main(["tools", "mcp", "test", "fake"]) == 0
    assert "12 tools" in capsys.readouterr().out
    assert cli.main(["tools", "mcp", "test", "nope"]) == 1


def test_cli_test_reports_failure(home, capsys):
    mcp_config.save_server(_server("--garbage"))
    assert cli.main(["tools", "mcp", "test", "fake"]) == 1
    assert "Test failed" in capsys.readouterr().err
