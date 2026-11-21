"""`whyline tools mcp list|add|remove|import|test` and
`whyline tools skills list|show|new|copy|edit|remove|sources|browse|show-remote|
install|update`. Exit codes: 0 ok,
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
    cat = tools_sub.add_parser("catalogue", help="Connectors you can add: list, or add one by name")
    cat.add_argument("words", nargs="*", metavar="TEXT",
                     help="words to search for, or: add <name>, or: search <text> (public registry)")
    find = tools_sub.add_parser("find", help="What should the agent be able to do? Search everything")
    find.add_argument("text", nargs="+", metavar="TEXT")
    find.add_argument("--registry", action="store_true", help="search the public registry too")
    level = tools_sub.add_parser(
        "risk", help="Show or raise how much harm a tool can do: reads, writes, sends, pays")
    level.add_argument("tool", metavar="SERVER.TOOL")
    level.add_argument("level", nargs="?", default=None, metavar="LEVEL",
                       help="reads, writes, sends or pays; a level can be raised, never lowered")
    tools_sub.add_parser("serve", help="Run whyline's MCP server for an agent run (stdio)")
    for cli in _SAVED_SETUP:
        setup = tools_sub.add_parser(f"setup-{cli}", help=f"Add whyline's tools to {cli} (once)")
        setup.add_argument("--yes", action="store_true", help="do not ask first")
    _add_skills_parser(tools_sub)
    _add_knowledge_parser(tools_sub)
    _add_made_parser(tools_sub)


_SAVED_SETUP = ("grok", "antigravity")


def _risk(args: argparse.Namespace) -> int:
    from whyline.tools import risk

    server, _, tool = args.tool.partition(".")
    found = mcp_config.load().get(server)
    if found is None or tool not in {t.name for t in found.tools}:
        print(f"No tool named {args.tool}. Test the connector first to list its tools.", file=sys.stderr)
        return EXIT_ERROR
    if args.level is None:
        print(f"{args.tool}  {risk.of(server, tool)}")
        return EXIT_OK
    level = risk.normalise(args.level)
    try:
        if not level:
            raise ValueError(f"a level is one of {', '.join(risk.LEVELS)}")
        risk.set_level(server, tool, level)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    print(f"{args.tool}  {risk.of(server, tool)}")
    return EXIT_OK


def agents_limit(args: argparse.Namespace, root: Path | None) -> int:
    """``whyline agents limit``: what one agent may spend through one ``pays`` tool.
    Both amounts and the currency are needed, as the console's Add tools asks for them."""
    from dataclasses import replace

    from whyline.agents import definitions as d, service
    from whyline.tools import risk

    defn = service.find(args.name, root)
    server, _, tool = args.tool.partition(".")
    if args.tool not in defn.tools:
        print(f"{defn.name} does not use {args.tool}. Add it in Add tools first.", file=sys.stderr)
        return EXIT_ERROR
    if risk.of(server, tool) != "pays":
        print(f"{args.tool} is {risk.of(server, tool)}, not pays: it has no limit to set.", file=sys.stderr)
        return EXIT_ERROR
    currency = args.currency.strip().upper()
    amounts = (args.per_call, args.per_day)
    if not currency or not all(0 < a < float("inf") for a in amounts):
        print(f"Set both limits for {args.tool}: amounts above zero and a currency.", file=sys.stderr)
        return EXIT_USAGE
    limit = d.Limit(currency, args.per_call, args.per_day)
    path = d.save(replace(defn, limits={**defn.limits, args.tool: limit}))
    print(f"{defn.name}: {args.tool} limited to {args.per_call:g} per call and {args.per_day:g} per day "
          f"in {currency} ({path})")
    return EXIT_OK


def _setup(cli: str, yes: bool) -> int:
    import shutil

    from whyline.agents import capabilities

    binary = capabilities._SAVED_BINARY[cli]
    if shutil.which(binary) is None:
        print(f"{binary} is not installed, so there is nothing to set up.", file=sys.stderr)
        return EXIT_ERROR
    if capabilities.saved_ready(cli):
        print(f"whyline is already set up in {binary}.")
        return EXIT_OK
    if not yes:
        answer = input(f"Add whyline's tools to {binary}'s saved MCP servers? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Not changed.")
            return EXIT_ERROR
    try:
        print(capabilities.saved_setup(cli))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


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
    sources = sub.add_parser("sources", help="Where skills can be found (list when no action)")
    actions = sources.add_subparsers(dest="sources_action")
    add = actions.add_parser("add", help="Add a source")
    add.add_argument("name")
    add.add_argument("url")
    add.add_argument("--path", default="", help="folder in the repository holding the skills")
    drop = actions.add_parser("remove", help="Forget a source")
    drop.add_argument("name")
    refresh = actions.add_parser("refresh", help="Fetch one source, or all enabled")
    refresh.add_argument("name", nargs="?")
    browse = sub.add_parser("browse", help="Search the fetched sources")
    browse.add_argument("text", nargs="+")
    remote = sub.add_parser("show-remote", help="Preview a skill in a source")
    remote.add_argument("ref", help="source:name")
    install = sub.add_parser("install", help="Install a skill from a source")
    install.add_argument("ref", help="source:name")
    install.add_argument("--as", dest="as_name", help="install under another name")
    install.add_argument("--yes", action="store_true", help="do not ask")
    update = sub.add_parser("update", help="Update an installed skill from its source")
    update.add_argument("name")
    update.add_argument("--yes", action="store_true", help="do not ask")


def _add_made_parser(tools_sub: "argparse._SubParsersAction") -> None:
    parser = tools_sub.add_parser("made", help="Tools you made: a saved web request an agent can call")
    sub = parser.add_subparsers(dest="made_command", required=True)
    sub.add_parser("list", help="Made tools and whether each is accepted")
    show = sub.add_parser("show", help="Show one made tool")
    show.add_argument("name")
    new = sub.add_parser("new", help="Save a made tool from a TOML file (not accepted yet)")
    new.add_argument("--from", dest="source", required=True, metavar="FILE")
    test = sub.add_parser("test", help="Show the request, then send it once when you say yes")
    test.add_argument("name")
    test.add_argument("values", nargs="*", metavar="key=value")
    test.add_argument("--yes", action="store_true", help="do not ask")
    accept = sub.add_parser("accept", help="Accept a made tool so agents may call it")
    accept.add_argument("name")
    accept.add_argument("--yes", action="store_true", help="do not ask")
    remove = sub.add_parser("remove", help="Delete a made tool")
    remove.add_argument("name")


def _made_values(pairs: list[str]) -> dict:
    values = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"Give inputs as key=value, not {pair!r}.")
        values[key] = value
    return values


def _made_show(tool) -> None:
    from whyline.tools import made

    state = "accepted" if made.accepted(tool) else "not accepted"
    print(f"{tool.name}  {state}  risk {tool.risk}")
    print(f"  {tool.about}")
    print(f"  {tool.method} {tool.url}")
    for name, value in tool.headers.items():
        print(f"  header {name}: {value}")
    for name, value in tool.query.items():
        print(f"  query {name}={value}")
    if tool.body:
        print(f"  body {tool.body}")
    if tool.credential:
        print(f"  credential {tool.credential} ({tool.credential_in})")
    if tool.pick:
        print(f"  pick {tool.pick}")
    for item in tool.inputs:
        print(f"  input {item.name} ({item.type}{'' if item.required else ', optional'}) {item.about}")


def _made(args: argparse.Namespace) -> int:
    from whyline import credentials
    from whyline.tools import made, made_draft

    command = args.made_command
    try:
        if command == "list":
            tools = made.load_all()
            if not tools:
                print("No made tools.")
            for t in tools:
                print(f"{t.name}  {'accepted' if made.accepted(t) else 'not accepted'}  {t.risk}  {t.about}")
            return EXIT_OK
        if command == "new":
            tool = made_draft.parse_toml(Path(args.source).read_text(encoding="utf-8"))
            made.save(tool)
            print(f"Saved made tool {tool.name}. It is not accepted yet: test it, then accept it.")
            return EXIT_OK
        tool = made.load(args.name)
        if tool is None:
            print(f"No made tool named {args.name}.", file=sys.stderr)
            return EXIT_ERROR
        if command == "show":
            _made_show(tool)
        elif command == "remove":
            made.remove(args.name)
            print(f"Removed made tool {args.name}.")
        elif command == "test":
            values = _made_values(args.values)
            made.validate(tool)
            print(made_draft.send_line(tool))
            print(made_draft.preview(tool, values))
            if made_draft.really_does_it(tool):
                print(made_draft.really_does_it(tool))
            if not _ask(args.yes, "Send it? [y/N] "):
                print("Not sent.")
                return EXIT_ERROR
            print(made_draft.send_test(tool, values, get_credential=_cred_value(credentials)))
        else:
            made.validate(tool)
            _made_show(tool)
            if not _ask(args.yes, f"Accept {tool.name} so agents may call it? [y/N] "):
                print("Not accepted.")
                return EXIT_ERROR
            made.accept(args.name)
            print(f"Accepted made tool {args.name}.")
        return EXIT_OK
    except (made.MadeToolError, made_draft.DraftError, ValueError, OSError, credentials.Locked) as error:
        print(str(error), file=sys.stderr)
    return EXIT_ERROR


def _cred_value(credentials):
    def get(name: str):
        try:
            return credentials.value(name)
        except (KeyError, ValueError, credentials.Locked):
            return None

    return get


def _ask(yes: bool, question: str = "Continue? [y/N] ") -> bool:
    if yes:
        return True
    try:
        return input(question).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _entry(ref: str):
    from whyline.tools import skill_sources

    source, _, name = ref.partition(":")
    if not name:
        raise ValueError("Use source:name.")
    if not any(s.name == source for s in skill_sources.load()):
        raise ValueError(f"There is no source called {source}.")
    for entry in skill_sources.index(next(s for s in skill_sources.load() if s.name == source)):
        if entry.name == name:
            return entry
    raise ValueError(f"No skill {name} in {source}. Refresh the source or browse.")


def _sources(args: argparse.Namespace) -> int:
    from whyline.tools import skill_sources

    action = args.sources_action
    if action == "add":
        added = skill_sources.add(args.name, args.url, args.path)
        print(f"Added source {added.name}. Run: whyline tools skills sources refresh {added.name}")
    elif action == "remove":
        if not skill_sources.remove(args.name):
            print(f"No source {args.name}.", file=sys.stderr)
            return EXIT_ERROR
        print(f"Removed source {args.name}.")
    elif action == "refresh":
        chosen = [s for s in skill_sources.load() if s.enabled and args.name in (None, s.name)]
        if not chosen:
            print(f"No source {args.name}." if args.name else "No sources to refresh.", file=sys.stderr)
            return EXIT_ERROR
        for source in chosen:
            commit = skill_sources.fetch(source)
            print(f"{source.name}: {commit[:12]}  {len(skill_sources.index(source))} skills")
    else:
        for source in skill_sources.load():
            state = "" if source.enabled else " (off)"
            got = skill_sources.fetched(source) or "not fetched"
            print(f"{source.name}{state}  {source.url}  {source.path or '.'}  {got}")
    return EXIT_OK


def _skills_remote(args: argparse.Namespace) -> int:
    from whyline.tools import skill_install, skill_sources

    command = args.skills_command
    if command == "sources":
        return _sources(args)
    if command == "browse":
        found = skill_sources.search(" ".join(args.text))
        if not found:
            print("No skills found.")
        for e in found:
            print(f"{e.source}:{e.name}  {e.size} bytes  {e.description}")
        return EXIT_OK
    if command == "update":
        diff = skill_install.update_diff(args.name)
        if not diff:
            print(f"{args.name} is up to date.")
            return EXIT_OK
        print(diff)
        if not _ask(args.yes):
            print("Nothing changed.")
            return EXIT_OK
        print(f"Updated {skill_install.update(args.name).ref}.")
        return EXIT_OK
    entry = _entry(args.ref)
    shown = skill_install.preview(entry)
    if command == "show-remote":
        print(f"{args.ref}  {shown.size} bytes  licence: {shown.licence}  commit: {shown.commit[:12]}")
        print(f"Files: {', '.join(f'{n} ({b})' for n, b in shown.files) or '(none)'}")
        for warning in shown.warnings:
            print(f"Warning: {warning}")
        print()
        print(shown.skill_md)
        return EXIT_OK
    print(f"{args.ref}  {shown.size} bytes  licence: {shown.licence}")
    for warning in shown.warnings:
        print(f"Warning: {warning}")
    if not _ask(args.yes):
        print("Nothing installed.")
        return EXIT_OK
    print(f"Installed {skill_install.install(entry, name=args.as_name).ref}.")
    return EXIT_OK


def _text(value: str | None) -> str | None:
    return sys.stdin.read() if value == "-" else value


_REMOTE = ("sources", "browse", "show-remote", "install", "update")


def _skills(args: argparse.Namespace) -> int:
    command = args.skills_command
    root = Path.cwd()
    try:
        if command in _REMOTE:
            return _skills_remote(args)
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
    except (ValueError, RuntimeError) as error:
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


def _catalogue(args: argparse.Namespace) -> int:
    from whyline.tools import catalogue

    words = list(args.words)
    if words[:1] == ["search"]:
        from whyline.tools import registry

        found = registry.search(" ".join(words[1:]))
        print(registry.HEADING)
        if not found:
            print(registry.last_error() or "Nothing in the public registry matches.")
        for e in found:
            print(f"{e.name}  {e.title}  {e.refused or e.status}  {e.about}")
        return EXIT_ERROR if registry.last_error() else EXIT_OK
    if words[:1] != ["add"]:
        found = catalogue.search(" ".join(words))
        if not found:
            print("Nothing in the catalogue matches.")
        for e in found:
            state = "added" if catalogue.added(e) else e.status
            print(f"{e.name}  {e.title}  {state}  {e.about}")
        return EXIT_OK
    if len(words) != 2:
        print("Usage: whyline tools catalogue add <name>", file=sys.stderr)
        return EXIT_USAGE
    entry = next((e for e in catalogue.load() if e.name == words[1]), None)
    if entry is None:
        print(f"No catalogue entry named {words[1]}.", file=sys.stderr)
        return EXIT_ERROR
    if catalogue.added(entry) and mcp_config.load()[entry.name].enabled:
        print(f"{entry.name} is already added.")
        return EXIT_OK
    print(f"Will run: {catalogue.command_line(entry)}")
    for t in entry.tools:
        print(f"  {t.name}  {t.risk}")
    import getpass

    values: dict[str, str] = {}
    for c in entry.credentials:
        if c.where:
            print(f"{c.label}: get it at {c.where}")
        values[c.var] = getpass.getpass(f"{c.label} ({c.var}): ")
    try:
        passed, message = catalogue.check(entry, values, test=lambda n: mcp_config.test_server(n))
        if passed:
            catalogue.enable(entry.name)
    except (ValueError, KeyError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    if not passed:
        print(f"Test failed: {message}. {entry.name} is saved and left off.", file=sys.stderr)
        return EXIT_ERROR
    print(f"Added {entry.name}. {message}")
    return EXIT_OK


def _find(args: argparse.Namespace) -> int:
    from whyline.tools import find, registry

    hits = find.match(" ".join(args.text), registry_search=registry.search if args.registry else None)
    if not hits:
        print(find.NOTHING)
    for h in hits:
        print(f"{h.kind}  {h.ref}  {h.title}  {h.about}")
    return EXIT_ERROR if args.registry and registry.last_error() else EXIT_OK


def run(args: argparse.Namespace) -> int:
    if args.tools_command == "catalogue":
        return _catalogue(args)
    if args.tools_command == "find":
        return _find(args)
    if args.tools_command == "risk":
        return _risk(args)
    if args.tools_command == "serve":
        from whyline.tools import serve

        return serve.serve()
    if args.tools_command.startswith("setup-"):
        return _setup(args.tools_command.removeprefix("setup-"), args.yes)
    if args.tools_command == "skills":
        return _skills(args)
    if args.tools_command == "knowledge":
        return _knowledge(args)
    if args.tools_command == "made":
        return _made(args)
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
