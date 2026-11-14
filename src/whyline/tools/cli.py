"""`whyline tools mcp list|add|remove|import`. Exit codes: 0 ok, 1 refused or
failed, 2 bad usage."""
from __future__ import annotations

import argparse
import sys

from whyline.tools import mcp_config

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def add_parser(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("tools", help="Tools agents may use: MCP servers")
    tools_sub = parser.add_subparsers(dest="tools_command", required=True)
    mcp = tools_sub.add_parser("mcp", help="Local MCP servers")
    sub = mcp.add_subparsers(dest="mcp_command", required=True)
    sub.add_parser("list", help="Registered servers")
    add = sub.add_parser("add", help="Register a local MCP server")
    add.add_argument("name")
    add.add_argument("--command", required=True, dest="server_command")
    add.add_argument("--arg", action="append", default=[], dest="arg", metavar="ARG")
    add.add_argument("--cwd", default="")
    add.add_argument("--env", action="append", default=[], metavar="VAR=CREDENTIAL",
                     help="environment variable filled from a named credential (repeatable)")
    remove = sub.add_parser("remove", help="Unregister a server nothing uses")
    remove.add_argument("name")
    imp = sub.add_parser("import", help="List servers from Claude and Codex configs; add those named")
    imp.add_argument("names", nargs="*")


def _list() -> int:
    servers = mcp_config.load()
    if not servers:
        print("No MCP servers registered.")
        return EXIT_OK
    for name, server in sorted(servers.items()):
        state = "on" if server.enabled else "off"
        command = " ".join([server.command, *server.args])
        print(f"{name}  {state}  {command}  tools: {len(server.tools)}")
    return EXIT_OK


def _add(args: argparse.Namespace) -> int:
    env: dict[str, str] = {}
    for item in args.env:
        var, sep, cred = item.partition("=")
        if not sep or not var or not cred:
            print(f"--env wants VAR=<credential name>, got {item!r}.", file=sys.stderr)
            return EXIT_USAGE
        env[var] = cred
    server = mcp_config.Server(
        name=args.name, command=args.server_command, args=tuple(args.arg), cwd=args.cwd, env=env,
    )
    try:
        mcp_config.save_server(server)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return EXIT_USAGE
    print(f"Added MCP server {args.name}.")
    return EXIT_OK


def _remove(args: argparse.Namespace) -> int:
    try:
        mcp_config.remove_server(args.name)
    except KeyError:
        print(f"No MCP server named {args.name}.", file=sys.stderr)
        return EXIT_ERROR
    except ValueError as error:
        print(f"Not removed: {error}.", file=sys.stderr)
        return EXIT_ERROR
    print(f"Removed MCP server {args.name}.")
    return EXIT_OK


def _import(args: argparse.Namespace) -> int:
    candidates = mcp_config.import_candidates()
    if not args.names:
        if not candidates:
            print("No MCP servers found in Claude or Codex config.")
        for c in candidates:
            line = f"{c.name}  ({c.source})"
            if c.command:
                line += "  " + " ".join([c.command, *c.args])
            notes = c.notes()
            print(line + (f"  [{'; '.join(notes)}]" if notes else ""))
        return EXIT_OK
    by_name = {c.name: c for c in candidates}
    status = EXIT_OK
    for name in args.names:
        c = by_name.get(name)
        if c is None:
            print(f"No candidate named {name}.", file=sys.stderr)
            status = EXIT_ERROR
        elif c.refused:
            print(f"Refused {name}: {c.refused}.", file=sys.stderr)
            status = EXIT_ERROR
        else:
            mcp_config.save_server(mcp_config.Server(
                name=c.name, command=c.command, args=c.args, cwd=c.cwd))
            print(f"Added MCP server {name}.")
            for note in c.notes():
                print(f"  {note} (set it with: whyline tools mcp add {name} ... --env VAR=<credential>)")
    return status


def run(args: argparse.Namespace) -> int:
    if args.tools_command != "mcp":
        return EXIT_USAGE
    command = args.mcp_command
    if command == "list":
        return _list()
    if command == "add":
        return _add(args)
    if command == "remove":
        return _remove(args)
    return _import(args)
