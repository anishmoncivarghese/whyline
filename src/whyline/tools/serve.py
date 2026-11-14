"""`whyline tools serve`: the one MCP server an agent's CLI is pointed at for a
run. It offers only the tools the agent ticked, starts each real server on first
use, and logs every call. Reads ``WHYLINE_TOOLS_RUN``, the path of the run's
``tools.json``::

    {"run": "...", "agent": "...", "tools": [
        {"server": "notion", "tool": "search", "permission": "allowed" | "ask",
         "description": "...", "input_schema": {...}, "read_only": true}]}
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from whyline import credentials
from whyline.tools import mcp, mcp_config

ENV_VAR = "WHYLINE_TOOLS_RUN"
PROTOCOL_VERSION = mcp.PROTOCOL_VERSION
ARGUMENTS_LIMIT = 2_000
DENIED_TEXT = "The user denied this call."
TIMED_OUT_TEXT = "Not approved in time."


def _ask_first(run_folder: Path, tool: str, arguments: dict) -> str:
    """TLS-10's approvals. Without them an Ask first call is denied."""
    try:
        from whyline.tools import approvals
    except ImportError:
        return "denied"
    decision = approvals.request(run_folder, tool, arguments)
    return str(getattr(decision, "status", decision))


class Server:
    def __init__(self, tools_file: Path | None, *, servers=None, session_factory=None,
                 redaction_values=credentials.redaction_values, ask=_ask_first,
                 clock=time.monotonic):
        self.folder = tools_file.parent if tools_file else None
        self.run_id = ""
        self.agent = ""
        self.ticked: dict[str, dict] = {}
        self._servers = servers
        self._session_factory = session_factory or (lambda server: mcp.Session(server))
        self._redaction_values = redaction_values
        self._ask = ask
        self._clock = clock
        self._sessions: dict[str, mcp.Session] = {}
        if tools_file is not None:
            self._load(tools_file)

    def _load(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        self.run_id = str(data.get("run", ""))
        self.agent = str(data.get("agent", ""))
        for item in data.get("tools", []):
            if isinstance(item, dict) and item.get("server") and item.get("tool"):
                self.ticked[f"{item['server']}__{item['tool']}"] = item

    # -- protocol ---------------------------------------------------------

    def handle(self, message: dict) -> dict | None:
        method, ident = message.get("method"), message.get("id")
        if ident is None:
            return None  # a notification
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        if method == "initialize":
            return self._result(ident, {
                "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "whyline", "version": "1"},
            })
        if method == "ping":
            return self._result(ident, {})
        if method == "tools/list":
            return self._result(ident, {"tools": [self._describe(n, t) for n, t in self.ticked.items()]})
        if method == "tools/call":
            name = str(params.get("name", ""))
            arguments = params.get("arguments")
            arguments = arguments if isinstance(arguments, dict) else {}
            if name not in self.ticked:
                return self._error(ident, -32602, f"This agent may not use {name}.")
            return self._result(ident, self._call(name, arguments))
        return self._error(ident, -32601, f"no such method: {method}")

    @staticmethod
    def _result(ident, body: dict) -> dict:
        return {"jsonrpc": "2.0", "id": ident, "result": body}

    @staticmethod
    def _error(ident, code: int, text: str) -> dict:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": text}}

    @staticmethod
    def _describe(name: str, item: dict) -> dict:
        schema = item.get("input_schema")
        entry = {
            "name": name,
            "description": str(item.get("description") or ""),
            "inputSchema": schema if isinstance(schema, dict) and schema else {"type": "object"},
        }
        if item.get("read_only"):
            entry["annotations"] = {"readOnlyHint": True}
        return entry

    # -- calls ------------------------------------------------------------

    def _session(self, server_name: str) -> mcp.Session:
        session = self._sessions.get(server_name)
        if session is None:
            servers = self._servers if self._servers is not None else mcp_config.load()
            server = servers.get(server_name)
            if server is None:
                raise mcp.McpError(f"No MCP server named {server_name}.")
            session = self._session_factory(server)
            session.__enter__()
            self._sessions[server_name] = session
        return session

    @staticmethod
    def _text_result(text: str) -> dict:
        return {"content": [{"type": "text", "text": text}], "isError": True}

    def _call(self, name: str, arguments: dict) -> dict:
        item = self.ticked[name]
        started = self._clock()
        decision, error, size = "allowed", "", 0
        if item.get("permission") == "ask":
            decision = {"approved": "approved", "timed out": "timed out"}.get(
                self._ask(self.folder, name, arguments), "denied")
        if decision == "denied":
            body, error = self._text_result(DENIED_TEXT), DENIED_TEXT
        elif decision == "timed out":
            body, error = self._text_result(TIMED_OUT_TEXT), TIMED_OUT_TEXT
        else:
            try:
                result = self._session(item["server"]).call(item["tool"], arguments)
                content = result.content or ([{"type": "text", "text": result.text}] if result.text else [])
                body = {"content": content, "isError": result.is_error}
                if result.structured is not None:
                    body["structuredContent"] = result.structured
                size = len(result.text)
                if result.is_error:
                    error = result.text
            except mcp.McpError as problem:
                self._drop(item["server"])
                error = str(problem)
                body = self._text_result(error)
        self._log(name, item, arguments, decision, self._clock() - started, size, error)
        return body

    def _drop(self, server_name: str) -> None:
        session = self._sessions.pop(server_name, None)
        if session is not None:
            try:
                session.__exit__(None, None, None)
            except Exception:
                pass

    # -- the call log -----------------------------------------------------

    def _redact(self, text: str) -> str:
        servers = self._servers if self._servers is not None else mcp_config.load()
        names = {cred for item in self.ticked.values()
                 for cred in (servers[item["server"]].env.values() if item["server"] in servers else ())}
        try:
            values = self._redaction_values(sorted(names))
        except Exception:
            values = []
        for value in sorted((v for v in values if v), key=len, reverse=True):
            text = text.replace(value, "[redacted]")
        return text

    def _log(self, name, item, arguments, decision, seconds, size, error) -> None:
        if self.folder is None:
            return
        try:
            shown = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            shown = str(arguments)
        record = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": name,
            "arguments": self._redact(shown)[:ARGUMENTS_LIMIT],
            "decision": decision,
            "duration_s": round(seconds, 3),
            "result_size": size,
            "error": self._redact(error)[:ARGUMENTS_LIMIT],
        }
        try:
            with open(self.folder / "tool-calls.jsonl", "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def close(self) -> None:
        for name in list(self._sessions):
            self._drop(name)


def serve(stdin=None, stdout=None, *, environ=None, **options) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    path = (environ if environ is not None else os.environ).get(ENV_VAR)
    server = Server(Path(path) if path else None, **options)
    try:
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            reply = server.handle(message)
            if reply is not None:
                stdout.write(json.dumps(reply) + "\n")
                stdout.flush()
    finally:
        server.close()
    return 0
