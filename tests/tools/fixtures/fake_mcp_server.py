"""A tiny stdio MCP server for tests. Tools list in pages of two."""
import argparse
import json
import os
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--tools")
parser.add_argument("--hang-on")
parser.add_argument("--garbage", action="store_true")
parser.add_argument("--exit-on")
parser.add_argument("--echo-env")
args = parser.parse_args()

TOOLS = [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object"},
          "annotations": {"readOnlyHint": True}}]
if args.tools:
    with open(args.tools, encoding="utf-8") as handle:
        TOOLS = json.load(handle)
PAGE = 2


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def result(ident, body):
    send({"jsonrpc": "2.0", "id": ident, "result": body})


for raw in sys.stdin:
    message = json.loads(raw)
    method, ident = message.get("method"), message.get("id")
    params = message.get("params") or {}
    if ident is None:
        continue
    if args.garbage and method != "initialize":
        sys.stdout.write("this is not json\n")
        sys.stdout.flush()
        continue
    if method == "initialize":
        result(ident, {"protocolVersion": params.get("protocolVersion"), "capabilities": {"tools": {}},
                       "serverInfo": {"name": "fake", "version": "1"}})
    elif method == "tools/list":
        start = int(params.get("cursor") or 0)
        body = {"tools": TOOLS[start:start + PAGE]}
        if start + PAGE < len(TOOLS):
            body["nextCursor"] = str(start + PAGE)
        result(ident, body)
    elif method == "tools/call":
        name = params.get("name")
        if name == args.hang_on:
            time.sleep(3600)
        if name == args.exit_on:
            os._exit(3)
        if name == "fail":
            result(ident, {"content": [{"type": "text", "text": "it broke"}], "isError": True})
        elif name == "env":
            value = os.environ.get(args.echo_env or "", "")
            print(f"env {args.echo_env}={value}", file=sys.stderr, flush=True)
            result(ident, {"content": [{"type": "text", "text": "seen" if value else "unset"}]})
        else:
            result(ident, {
                "content": [{"type": "text", "text": str(params.get("arguments", {}).get("text", ""))},
                            {"type": "image", "data": "xx", "mimeType": "image/png"},
                            {"type": "resource", "resource": {"uri": "file:///a", "text": "t"}}],
                "structuredContent": {"ok": True},
            })
    else:
        send({"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "no such method"}})
