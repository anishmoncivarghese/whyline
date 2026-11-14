"""A small MCP client over stdio: start a registered server, list its tools and
call one. Secrets reach the server only through its environment, and anything
the server writes to stderr is redacted before it can be shown."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import signal
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field

from whyline import credentials

PROTOCOL_VERSION = "2025-06-18"
MAX_LINE_BYTES = 1_000_000
_PASS_THROUGH = (
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP",
    "SHELL", "SYSTEMROOT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PATHEXT",
)


class McpError(RuntimeError):
    """A server failed. The message is plain and safe to show."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    read_only: bool | None = None


@dataclass(frozen=True)
class ToolResult:
    text: str
    is_error: bool = False
    structured: object = None
    content: list = field(default_factory=list)


def tools_hash(tools) -> str:
    items = [[t.name, t.input_schema] for t in sorted(tools, key=lambda t: t.name)]
    return hashlib.sha256(json.dumps(items, sort_keys=True).encode("utf-8")).hexdigest()


def _text_of(content: list) -> str:
    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text", "")))
        elif kind == "resource":
            resource = item.get("resource")
            uri = resource.get("uri", "") if isinstance(resource, dict) else ""
            parts.append(f"[resource {uri}]")
        elif kind == "resource_link":
            parts.append(f"[resource {item.get('uri', '')}]")
        else:
            parts.append(f"[{kind or 'content'}]")
    return "\n".join(parts)


class Session:
    def __init__(self, server, *, timeout_s: float = 60, popen=subprocess.Popen,
                 secret_value=credentials.value):
        self.server = server
        self.timeout_s = timeout_s
        self._popen = popen
        self._secret_value = secret_value
        self._proc = None
        self._lines: queue.Queue = queue.Queue()
        self._stderr: deque = deque(maxlen=20)
        self._secrets: list[str] = []
        self._next_id = 0

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    def _environment(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in _PASS_THROUGH if k in os.environ}
        for var, cred in self.server.env.items():
            try:
                secret = self._secret_value(cred)
            except credentials.Locked as error:
                raise McpError(f"credential {cred} is not available: {error}") from None
            env[var] = secret
            if secret:
                self._secrets.append(secret)
        return env

    def __enter__(self) -> "Session":
        env = self._environment()
        kwargs: dict = dict(
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=self.server.cwd or None,
        )
        if os.name != "nt":
            kwargs["start_new_session"] = True
        try:
            self._proc = self._popen([self.server.command, *self.server.args], **kwargs)
        except OSError as error:
            raise McpError(f"could not start {self.server.command}: {error.strerror or error}") from None
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        try:
            self._request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "whyline", "version": "1"},
            })
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except BaseException:
            self._kill()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self._kill()

    # -- plumbing ---------------------------------------------------------

    def _read_stdout(self) -> None:
        stream = self._proc.stdout
        while True:
            try:
                line = stream.readline(MAX_LINE_BYTES + 1)
            except (OSError, ValueError):
                line = b""
            if len(line) > MAX_LINE_BYTES:
                self._lines.put(("big", None))
                return
            if not line:
                self._lines.put(("eof", None))
                return
            self._lines.put(("line", line))

    def _read_stderr(self) -> None:
        for raw in iter(self._proc.stderr.readline, b""):
            self._stderr.append(raw.decode("utf-8", "replace").rstrip("\r\n"))

    def _redact(self, text: str) -> str:
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, "[redacted]")
        return text

    def _fail(self, reason: str) -> McpError:
        self._kill()
        tail = self._redact("\n".join(self._stderr))
        message = self._redact(reason)
        if tail:
            message += f"\nlast server output:\n{tail}"
        return McpError(message)

    def _kill(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                stream.close()
            except Exception:
                pass

    def _send(self, message: dict) -> None:
        try:
            self._proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
        except (OSError, ValueError):
            raise self._fail("the server closed its input before the request was sent") from None

    def _request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        ident = self._next_id
        self._send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        while True:
            try:
                kind, line = self._lines.get(timeout=self.timeout_s)
            except queue.Empty:
                raise self._fail(f"the server did not answer {method} within {self.timeout_s:g}s") from None
            if kind == "big":
                raise self._fail("server output over 1 MB")
            if kind == "eof":
                code = self._proc.poll()
                suffix = f" (exit code {code})" if code is not None else ""
                raise self._fail(f"the server exited early{suffix}")
            try:
                message = json.loads(line)
            except ValueError:
                raise self._fail("the server wrote a line that is not JSON") from None
            if not isinstance(message, dict):
                raise self._fail("the server wrote a line that is not a JSON-RPC message")
            if message.get("id") != ident or "method" in message:
                continue  # a notification or a request from the server
            error = message.get("error")
            if error:
                detail = error.get("message", "") if isinstance(error, dict) else str(error)
                raise self._fail(f"the server returned an error: {detail}")
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    # -- the protocol -----------------------------------------------------

    def list_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        cursor = None
        seen: set[str] = set()
        while True:
            result = self._request("tools/list", {"cursor": cursor} if cursor else {})
            for item in result.get("tools", []):
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                annotations = item.get("annotations")
                hint = annotations.get("readOnlyHint") if isinstance(annotations, dict) else None
                schema = item.get("inputSchema")
                tools.append(Tool(
                    name=str(item["name"]),
                    description=str(item.get("description") or ""),
                    input_schema=schema if isinstance(schema, dict) else {},
                    read_only=hint if isinstance(hint, bool) else None,
                ))
            cursor = result.get("nextCursor")
            if not cursor or cursor in seen:
                return tools
            seen.add(cursor)

    def call(self, tool: str, arguments: dict) -> ToolResult:
        result = self._request("tools/call", {"name": tool, "arguments": arguments})
        content = result.get("content")
        content = content if isinstance(content, list) else []
        return ToolResult(
            text=_text_of(content),
            is_error=bool(result.get("isError", False)),
            structured=result.get("structuredContent"),
            content=content,
        )
