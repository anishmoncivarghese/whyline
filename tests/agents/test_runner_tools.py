import dataclasses
import json
import os
import subprocess
from datetime import datetime

import pytest

from whyline.agents import capabilities, runner
from whyline.tools import cli as tools_cli, mcp_config

from .test_runner import NOW, Result, _agent, _script

EXE = "/bin/whyline"


@pytest.fixture(autouse=True)
def _tools(monkeypatch):
    server = mcp_config.Server("notion", "x", tools=(
        mcp_config.Tool("search", "Find pages", {"type": "object"}, True),))
    monkeypatch.setattr(mcp_config, "load", lambda: {"notion": server})
    monkeypatch.setattr(capabilities, "whyline_executable", lambda: EXE)


def _with_tools(repo, runner_cli="claude", backup=("codex",), tools=True):
    agent = _agent(repo, backup=())
    return dataclasses.replace(
        agent, runner=runner_cli, backup=tuple(backup),
        tools={"notion.search": "allowed"} if tools else {})


def test_tools_support():
    assert [capabilities.tools_support(c) for c in
            ("claude", "codex", "grok", "antigravity", "agy", "gemini")] == [
        "per-run", "per-run", "saved", "saved", "saved", "none"]


def test_prepare_run_writes_tools_json_and_mcp_json(repo, tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    extras = runner.prepare_run(_with_tools(repo), run)
    assert extras.tools_file == run / "tools.json"
    data = json.loads((run / "tools.json").read_text(encoding="utf-8"))
    assert data["run"] == "run" and data["agent"] == "a"
    assert data["tools"] == [{"server": "notion", "tool": "search", "permission": "allowed",
                              "description": "Find pages", "input_schema": {"type": "object"},
                              "read_only": True}]
    entry = json.loads((run / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["whyline"]
    assert entry["command"] == EXE and entry["args"] == ["tools", "serve"]


def test_no_tools_changes_nothing(repo, tmp_path):
    agent = _with_tools(repo, tools=False)
    run = tmp_path / "run"
    run.mkdir()
    assert runner.prepare_run(agent, run).tools_file is None
    assert not (run / "tools.json").exists()
    for cli in ("claude", "codex"):
        argv = runner._command(agent, cli, run)
        assert not any("whyline" in token or "mcp" in token for token in argv)


def test_claude_command_points_at_the_run_mcp_config(repo, tmp_path):
    argv = runner._command(_with_tools(repo), "claude", tmp_path)
    assert argv[argv.index("--mcp-config") + 1] == str(tmp_path / "mcp.json")
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--allowedTools") + 1] == "mcp__whyline__*"
    assert argv[argv.index("--allowedTools") + 2].startswith("-")


def test_codex_command_names_the_server(repo, tmp_path):
    argv = runner._command(_with_tools(repo), "codex", tmp_path)
    assert f'mcp_servers.whyline.command="{EXE}"' in argv
    assert 'mcp_servers.whyline.args=["tools","serve"]' in argv
    assert argv.count("-c") == 3


def test_grok_command_has_no_tool_flags(repo, tmp_path):
    with_tools = runner._command(_with_tools(repo), "grok", tmp_path)
    without = runner._command(_with_tools(repo, tools=False), "grok", tmp_path)
    assert with_tools == without


def _saved(monkeypatch, ready):
    monkeypatch.setattr(capabilities, "saved_ready", lambda cli: cli in ready)


def test_usable_clis_without_tools_keeps_everything(repo):
    agent = _with_tools(repo, "gemini", ("grok",), tools=False)
    assert runner.usable_clis(agent) == ["gemini", "grok"]


def test_grok_needs_its_saved_entry(repo, monkeypatch):
    agent = _with_tools(repo, "grok", ("claude",))
    _saved(monkeypatch, set())
    assert runner.usable_clis(agent) == ["claude"]
    _saved(monkeypatch, {"grok"})
    assert runner.usable_clis(agent) == ["grok", "claude"]


def test_antigravity_dropped_while_can_run_refuses_then_offered(repo, monkeypatch):
    agent = _with_tools(repo, "claude", ("antigravity", "codex"))
    _saved(monkeypatch, {"antigravity"})
    assert runner.usable_clis(agent) == ["claude", "codex"]
    monkeypatch.setitem(capabilities.READ_ONLY, "antigravity", lambda command: command)
    assert runner.usable_clis(agent) == ["claude", "antigravity", "codex"]
    _saved(monkeypatch, set())
    assert runner.usable_clis(agent) == ["claude", "codex"]


def test_backup_order_kept(repo, monkeypatch):
    agent = _with_tools(repo, "codex", ("grok", "claude"))
    _saved(monkeypatch, {"grok"})
    assert runner.usable_clis(agent) == ["codex", "grok", "claude"]


def test_run_sets_the_environment_per_cli_and_restores_it(repo, monkeypatch):
    seen = []

    def run_fn(command, prompt, **kwargs):
        seen.append((command[0], os.environ.get("WHYLINE_TOOLS_RUN")))
        return Result(0, json.dumps({"result": "ok", "permission_denials": []}))

    monkeypatch.delenv("WHYLINE_TOOLS_RUN", raising=False)
    rec = runner.execute_once(_with_tools(repo), source="manual", now=NOW, run_fn=run_fn)
    assert rec.outcome == "succeeded"
    assert seen[0][0] == "claude" and seen[0][1].endswith("tools.json")
    assert os.environ.get("WHYLINE_TOOLS_RUN") is None


def test_no_cli_can_use_the_tools(repo, monkeypatch):
    _saved(monkeypatch, set())
    agent = _with_tools(repo, "grok", ("gemini",))
    run_fn, calls = _script()
    rec = runner.execute_once(agent, source="manual", now=NOW, run_fn=run_fn)
    assert calls == [] and rec.outcome == "all_unavailable"
    assert rec.reason.startswith("No CLI can use this agent's tools: ")
    assert "gemini: cannot use tools" in rec.reason and "grok:" in rec.reason


def test_a_blocked_main_cli_falls_to_the_backup(repo, monkeypatch):
    _saved(monkeypatch, set())
    agent = _with_tools(repo, "grok", ("codex",))
    run_fn, calls = _script(Result(0, "done"))
    rec = runner.execute_once(agent, source="manual", now=NOW, run_fn=run_fn)
    assert rec.cli == "codex" and len(calls) == 1


def test_saved_ready_reads_the_clis_list(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/" + name)
    seen = []

    def fake(command, **kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="whyline  stdio\nother\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake)
    assert capabilities.saved_ready("grok") and seen[0] == ["grok", "mcp", "list"]
    assert capabilities.saved_ready("antigravity") and seen[1] == ["agy", "mcp", "list"]
    monkeypatch.setattr(subprocess, "run", lambda c, **k: subprocess.CompletedProcess(c, 0, "other\n", ""))
    assert not capabilities.saved_ready("grok")


def test_saved_setup_adds_the_entry(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/" + name)
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda c, **k: seen.append(c) or subprocess.CompletedProcess(c, 0, "", ""))
    capabilities.saved_setup("grok")
    capabilities.saved_setup("antigravity")
    assert seen == [["grok", "mcp", "add", "whyline", "--", EXE, "tools", "serve"],
                    ["agy", "mcp", "add", "whyline", "--", EXE, "tools", "serve"]]


def test_setup_refuses_when_the_cli_is_missing(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ValueError, match="not installed"):
        capabilities.saved_setup("grok")
    assert tools_cli._setup("antigravity", True) == tools_cli.EXIT_ERROR
    assert "agy is not installed" in capsys.readouterr().err
