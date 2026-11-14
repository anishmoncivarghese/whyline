"""`whyline tools mcp list|add|remove|import|test` and
`whyline tools skills list|show|new|copy|edit|remove`. Exit codes: 0 ok,
1 refused or failed, 2 bad usage."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from whyline.tools import knowledge, mcp_config, skills

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
    test = sub.add_parser("test", help="Start a server, list its tools and store them")
    test.add_argument("name")
    tools_sub.add_parser("serve", help="Run whyline's MCP server for an agent run (stdio)")
    _add_skills_parser(tools_sub)
    _add_knowledge_parser(tools_sub)


def _add_knowledge_parser(tools_sub: "argparse._SubParsersAction") -> None:
    parser = tools_sub.add_parser("knowledge", help="Knowledge packs: files and web pages for agents")
    sub = parser.add_subparsers(dest="knowledge_command", required=True)
    sub.add_parser("list", help="Packs")
    show = sub.add_parser("show", help="Show a pack and what its items resolve to")
    show.add_argument("name")
    add = sub.add_parser("add", help="Create or replace a pack")
    add.add_argument("name")
    add.add_argument("--description", default="")
    add.add_argument("--item", action="append", default=[], dest="items", metavar="ITEM",
                     help="path, http(s) URL or pack:<name> (repeatable)")
    remove = sub.add_parser("remove", help="Delete a pack nothing uses")
    remove.add_argument("name")


def _knowledge(args: argparse.Namespace) -> int:
    command = args.knowledge_command
    try:
        if command == "list":
            packs = knowledge.list_packs()
            if not packs:
                print("No knowledge packs.")
            for p in packs:
                print(f"{p.name}  {len(p.items)} items  {p.description}")
        elif command == "show":
            pack = knowledge.get_pack(args.name)
            print(f"{pack.name}  {pack.description}")
            for item in knowledge.resolve(pack.items, Path.cwd()):
                print(f"  {'url' if item.is_url else 'path'}  {item.value}")
        elif command == "add":
            knowledge.save_pack(knowledge.Pack(args.name, args.description, tuple(args.items)))
            print(f"Saved knowledge pack {args.name}.")
        else:
            knowledge.remove_pack(args.name)
            print(f"Removed knowledge pack {args.name}.")
        return EXIT_OK
    except KeyError:
        print(f"No knowledge pack named {args.name}.", file=sys.stderr)
    except ValueError as error:
        print(str(error), file=sys.stderr)
    return EXIT_ERROR


def _add_skills_parser(tools_sub: "argparse._SubParsersAction") -> None:
    parser = tools_sub.add_parser("skills", help="Skills agents may be given")
    sub = parser.add_subparsers(dest="skills_command", required=True)
    sub.add_parser("list", help="Skills from whyline and Claude folders")
    show = sub.add_parser("show", help="Show one skill")
    show.add_argument("ref", help="origin:name")
    new = sub.add_parser("new", help="Create a whyline skill")
    new.add_argument("name")
    new.add_argument("--description", required=True)
    new.add_argument("--body", default="", help="text of the skill, or - to read stdin")
    new.add_argument("--repo", action="store_true", help="create it in this repository")
    copy = sub.add_parser("copy", help="Copy a Claude skill to whyline")
    copy.add_argument("ref", help="claude:name or claude-project:name")
    edit = sub.add_parser("edit", help="Change a whyline skill")
    edit.add_argument("ref")
    edit.add_argument("--description")
    edit.add_argument("--body", help="new text, or - to read stdin")
    remove = sub.add_parser("remove", help="Delete a whyline skill nothing uses")
    remove.add_argument("ref")


def _text(value: str | None) -> str | None:
    return sys.stdin.read() if value == "-" else value


def _skills(args: argparse.Namespace) -> int:
    command = args.skills_command
    root = Path.cwd()
    try:
        if command == "list":
            found = skills.find(root)
            if not found:
                print("No skills found.")
            for s in found:
                note = f"BROKEN: {s.problem}" if s.broken else s.description
                print(f"{s.ref}  {s.size} bytes  {note}")
            return EXIT_OK
        if command == "show":
            skill = skills.get(args.ref, root)
            print(f"{skill.ref}  {skill.path}")
            if skill.broken:
                print(f"Broken: {skill.problem}")
            print(f"Files: {', '.join(skill.files) or '(none)'}")
            manifest = skill.path / "SKILL.md"
            if manifest.is_file():
                print()
                print(manifest.read_text(encoding="utf-8"))
            return EXIT_OK
        if command == "new":
            skill = skills.create(args.name, args.description, _text(args.body) or "",
                                  repo_root=root if args.repo else None)
            print(f"Created {skill.ref}.")
        elif command == "copy":
            skill = skills.copy_to_whyline(args.ref, root)
            print(f"Copied to {skill.ref}.")
        elif command == "edit":
            skill = skills.edit(args.ref, root, description=args.description, body=_text(args.body))
            print(f"Updated {skill.ref}.")
        else:
            skills.remove(args.ref, root)
            print(f"Removed {args.ref}.")
        return EXIT_OK
    except KeyError:
        print(f"No skill {getattr(args, 'ref', '')}.", file=sys.stderr)
    except ValueError as error:
        print(str(error), file=sys.stderr)
    return EXIT_ERROR


def _test(args: argparse.Namespace) -> int:
    from whyline.tools import mcp

    try:
        print(mcp_config.test_server(args.name))
    except KeyError:
        print(f"No MCP server named {args.name}.", file=sys.stderr)
        return EXIT_ERROR
    except mcp.McpError as error:
        print(f"Test failed: {error}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


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
    if args.tools_command == "serve":
        from whyline.tools import serve

        return serve.serve()
    if args.tools_command == "skills":
        return _skills(args)
    if args.tools_command == "knowledge":
        return _knowledge(args)
    if args.tools_command != "mcp":
        return EXIT_USAGE
    command = args.mcp_command
    if command == "list":
        return _list()
    if command == "add":
        return _add(args)
    if command == "remove":
        return _remove(args)
    if command == "test":
        return _test(args)
    return _import(args)
