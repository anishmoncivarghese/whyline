import json
import os
import stat

import pytest

from whyline import cli
from whyline.tools import mcp_config, users
from whyline.tools.mcp_config import Server, Tool


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(users, "_providers", {})
    return tmp_path


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_round_trip_and_mode(home):
    server = Server(
        name="files", command="npx", args=("-y", "srv", 'q"uote'), cwd="/tmp/x",
        env={"API_KEY": "my-key"}, enabled=False, tools_hash="abc",
        tools=(Tool("read", "Reads \"it\"", {"type": "object", "properties": {"p": {"type": "string"}}}, True),),
    )
    mcp_config.save_server(server)
    assert mcp_config.load() == {"files": server}
    mode = stat.S_IMODE(os.stat(home / ".whyline" / "mcp.toml").st_mode)
    assert mode == 0o600


def test_bad_name_and_value_in_env_refused(home):
    with pytest.raises(ValueError):
        mcp_config.save_server(Server(name="Bad_Name", command="x"))
    with pytest.raises(ValueError):
        mcp_config.save_server(Server(name="ok", command="x", env={"K": "Not A Credential"}))
    assert mcp_config.load() == {}


def test_import_from_three_configs(home):
    secret = "sk-live-123"
    _write(home / ".claude.json", json.dumps({"mcpServers": {
        "Github": {"command": "npx", "args": ["-y", "gh"], "env": {"GITHUB_TOKEN": secret}},
        "remote": {"type": "http", "url": "https://example.com/mcp"},
    }}))
    _write(home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
           json.dumps({"mcpServers": {"fs": {"command": "node", "args": ["fs.js"]}}}))
    _write(home / ".codex" / "config.toml",
           '[mcp_servers.docs]\ncommand = "docs-mcp"\nargs = ["--x"]\n[mcp_servers.docs.env]\nTOKEN = "' + secret + '"\n'
           '[mcp_servers.web]\nurl = "https://web.example/mcp"\n')
    found = {c.name: c for c in mcp_config.import_candidates()}
    assert set(found) == {"github", "remote", "fs", "docs", "web"}
    assert found["github"].command == "npx" and found["github"].args == ("-y", "gh")
    assert found["github"].notes() == ["needs a credential: GITHUB_TOKEN"]
    assert found["fs"].source == "Claude Desktop" and found["fs"].notes() == []
    assert found["docs"].notes() == ["needs a credential: TOKEN"]
    assert "remote servers are not supported" in found["remote"].refused
    assert found["web"].refused
    assert secret not in repr(list(found.values()))


def test_import_leaves_sources_unchanged(home):
    path = home / ".claude.json"
    _write(path, json.dumps({"mcpServers": {"a": {"command": "x"}}}))
    before = path.read_bytes()
    mcp_config.import_candidates()
    assert path.read_bytes() == before


def test_remove_refused_while_used(home):
    mcp_config.save_server(Server(name="files", command="x"))
    users.register("t", lambda: [users.Use("server", "files", "agent digest")])
    with pytest.raises(ValueError, match="agent digest"):
        mcp_config.remove_server("files")
    assert "files" in mcp_config.load()
    users.unregister("t")
    mcp_config.remove_server("files")
    assert mcp_config.load() == {}


def test_cli_add_list_import_remove(home, capsys):
    _write(home / ".claude.json", json.dumps({"mcpServers": {
        "gh": {"command": "npx", "env": {"T": "secret-value"}},
        "far": {"url": "https://x.example"},
    }}))
    assert cli.main(["tools", "mcp", "add", "files", "--command", "node", "--arg", "a.js",
                     "--arg=--flag", "--env", "KEY=my-key"]) == 0
    assert mcp_config.load()["files"].args == ("a.js", "--flag")
    assert mcp_config.load()["files"].env == {"KEY": "my-key"}
    assert cli.main(["tools", "mcp", "add", "x", "--command", "n", "--env", "KEY=a value"]) == 2
    assert cli.main(["tools", "mcp", "import"]) == 0
    out = capsys.readouterr().out
    assert "needs a credential: T" in out and "refused" in out and "secret-value" not in out
    assert cli.main(["tools", "mcp", "import", "gh", "far"]) == 1
    assert "gh" in mcp_config.load() and "far" not in mcp_config.load()
    assert "secret-value" not in (home / ".whyline" / "mcp.toml").read_text()
    assert cli.main(["tools", "mcp", "list"]) == 0
    assert cli.main(["tools", "mcp", "remove", "gh"]) == 0
    assert cli.main(["tools", "mcp", "remove", "gh"]) == 1
