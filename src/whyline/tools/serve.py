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
from decimal import Decimal, InvalidOperation
from pathlib import Path

from whyline import credentials
from whyline.tools import mcp, mcp_config, risk

ENV_VAR = "WHYLINE_TOOLS_RUN"
PROTOCOL_VERSION = mcp.PROTOCOL_VERSION
ARGUMENTS_LIMIT = 2_000
DENIED_TEXT = "The user denied this call."
TIMED_OUT_TEXT = "Not approved in time."


class Server:
    def __init__(self, tools_file: Path | None, *, servers=None, session_factory=None,
                 redaction_values=credentials.redaction_values, ask=None,
                 clock=time.monotonic, now=None):
        self.folder = tools_file.parent if tools_file else None
        self.run_id = ""
        self.agent = ""
        self.ticked: dict[str, dict] = {}
        self._servers = servers
        self._session_factory = session_factory or (lambda server: mcp.Session(server))
        self._redaction_values = redaction_values
        self._ask = ask or self._ask_first
        self._clock = clock
        self._now = now or (lambda: datetime.now(timezone.utc))
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

    def _ask_first(self, run_folder: Path, tool: str, arguments: dict, fields: dict | None = None) -> str:
        if run_folder is None:
            return "denied"
        from whyline.tools import approvals

        return approvals.request(run_folder, tool, arguments, redact=self._redact,
                                 fields=fields).status

    # -- risk -------------------------------------------------------------

    @staticmethod
    def _level(item: dict) -> str:
        """The tool's level; a level in tools.json can only raise it."""
        level = risk.of(item["server"], item["tool"])
        named = item.get("risk")
        if named in risk.LEVELS and risk.LEVELS.index(named) > risk.LEVELS.index(level):
            level = named
        return level

    @staticmethod
    def _hints(item: dict, kind: str) -> dict:
        given = item.get("hints")
        if isinstance(given, dict) and isinstance(given.get(kind), dict):
            return given[kind]
        return risk.hints(item["server"], item["tool"]).get(kind, {})

    @staticmethod
    def _number(value) -> Decimal | None:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return None
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation:
            return None
        return number if number.is_finite() and number > 0 else None

    def _paid_today(self, name: str, currency: str) -> Decimal:
        """What was approved for this tool today (the user's local day), from the
        call logs of this run and every run folder."""
        today = self._now().astimezone().date()
        folders: dict[Path, None] = {}
        if self.folder is not None:
            folders[self.folder.resolve()] = None
        try:
            from whyline.agents import paths

            for folder in paths.runs_dir().iterdir():
                folders[folder.resolve()] = None
        except OSError:
            pass
        total = Decimal(0)
        for folder in folders:
            try:
                lines = (folder / "tool-calls.jsonl").read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    record = json.loads(line)
                    paid = record["paid"]
                    when = datetime.fromisoformat(record["time"]).astimezone().date()
                    amount = Decimal(paid["amount"])
                except (ValueError, KeyError, TypeError, InvalidOperation):
                    continue
                if (record.get("tool") == name and record.get("decision") == "approved"
                        and when == today and paid.get("currency") == currency):
                    total += amount
        return total

    def _pay_check(self, name: str, item: dict, arguments: dict) -> tuple[str, dict, dict]:
        """(refusal, what the approval shows, what the log keeps) for a pays call."""
        key = f"{item['server']}.{item['tool']}"
        limit = item.get("limits")
        per_call, per_day = (self._number(limit.get("per_call")), self._number(limit.get("per_day"))) \
            if isinstance(limit, dict) else (None, None)
        currency = str(limit.get("currency", "")).strip().upper() if isinstance(limit, dict) else ""
        if not currency or (per_call is None and per_day is None):
            return f"Set a limit for {key} first", {}, {}
        hints = self._hints(item, "pay")
        if not hints.get("amount_arg") or not hints.get("currency_arg"):
            return f"{key} does not say which arguments hold the amount and currency", {}, {}
        amount = self._number(arguments.get(hints["amount_arg"]))
        if amount is None:
            return f"The amount for {key} is not a number above zero", {}, {}
        asked = str(arguments.get(hints["currency_arg"], "")).strip().upper()
        if asked != currency:
            return f"{key} is limited to {currency}, not {asked or 'no currency'}", {}, {}
        if per_call is not None and amount > per_call:
            return f"{amount} {currency} is over the {per_call} {currency} limit per call", {}, {}
        today = self._paid_today(name, currency)
        if per_day is not None and today + amount > per_day:
            return (f"{amount} {currency} would take today's total ({today}) over the "
                    f"{per_day} {currency} limit per day"), {}, {}
        payee = arguments.get(hints["payee_arg"], "") if hints.get("payee_arg") else ""
        shown = {"amount": str(amount), "currency": currency, "payee": str(payee),
                 "today": str(today),
                 "limits": {k: str(v) for k, v in (("per_call", per_call), ("per_day", per_day))
                            if v is not None}}
        return "", shown, {"amount": str(amount), "currency": currency}

    def _send_fields(self, item: dict, arguments: dict) -> dict:
        hints = self._hints(item, "send")
        return {label: str(arguments[hints[key]]) for label, key in (("to", "to_arg"), ("text", "text_arg"))
                if hints.get(key) and hints[key] in arguments}

    @staticmethod
    def _text_result(text: str) -> dict:
        return {"content": [{"type": "text", "text": text}], "isError": True}

    def _call(self, name: str, arguments: dict) -> dict:
        item = self.ticked[name]
        started = self._clock()
        decision, error, size = "allowed", "", 0
        level = self._level(item)
        fields, paid, refusal = {}, {}, ""
        if level == "pays":
            refusal, fields, paid = self._pay_check(name, item, arguments)
        elif level == "sends":
            fields = self._send_fields(item, arguments)
        if refusal:
            decision = "denied"
        elif item.get("permission") == "ask" or level == "pays":  # money is never allowed outright
            asked = (self._ask(self.folder, name, arguments, fields=fields) if fields
                     else self._ask(self.folder, name, arguments))
            decision = {"approved": "approved", "timed out": "timed out"}.get(asked, "denied")
        if refusal:
            body, error = self._text_result(refusal), refusal
        elif decision == "denied":
            body, error = self._text_result(DENIED_TEXT), DENIED_TEXT
        elif decision == "timed out":
            body, error = self._text_result(TIMED_OUT_TEXT), TIMED_OUT_TEXT
        elif item["server"] == mcp_config.MADE:
            body, error, size = self._call_made(item["tool"], arguments)
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
        self._log(name, item, arguments, decision, self._clock() - started, size, error, paid)
        return body

    def _call_made(self, name: str, arguments: dict) -> tuple[dict, str, int]:
        from whyline.tools import made

        tool = made.load(name)
        if tool is None or not made.accepted(tool):
            error = f"made.{name} is not accepted"
            return self._text_result(error), error, 0
        try:
            text = made.call(tool, arguments, get_credential=self._credential)
        except made.MadeToolError as problem:
            error = str(problem)
            return self._text_result(error), error, 0
        return {"content": [{"type": "text", "text": text}], "isError": False}, "", len(text)

    @staticmethod
    def _credential(name: str) -> str | None:
        try:
            return credentials.value(name)
        except Exception:
            return None

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

    def _log(self, name, item, arguments, decision, seconds, size, error, paid=None) -> None:
        if self.folder is None:
            return
        try:
            shown = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            shown = str(arguments)
        record = {
            "time": self._now().isoformat(timespec="seconds"),
            "tool": name,
            "arguments": self._redact(shown)[:ARGUMENTS_LIMIT],
            "decision": decision,
            "duration_s": round(seconds, 3),
            "result_size": size,
            "error": self._redact(error)[:ARGUMENTS_LIMIT],
        }
        if paid:
            record["paid"] = paid
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
