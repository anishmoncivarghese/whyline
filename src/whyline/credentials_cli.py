"""`whyline cred`: add, list, rotate and remove named credentials.

The value is read with getpass, never from an argument. Exit codes: 0 ok,
1 refused or failed, 2 bad usage."""
from __future__ import annotations

import argparse
import getpass
import sys

from whyline import credentials
from whyline.tools import users

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def add_parser(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "cred", help="Named credentials for agent tools (values go to the system keychain)"
    )
    sub = parser.add_subparsers(dest="cred_command", required=True)
    add = sub.add_parser("add", help="Store a credential; the value is asked for, not passed")
    add.add_argument("name")
    add.add_argument("--kind", default="env", choices=credentials.KINDS)
    add.add_argument("--origin", action="append", default=[], metavar="URL",
                     help="https origin the credential may be sent to (HTTP kinds, repeatable)")
    add.add_argument("--header", default="",
                     help="header name (kind header) or query parameter (kind query)")
    sub.add_parser("list", help="Stored credentials (never their values)")
    rotate = sub.add_parser("rotate", help="Replace the stored value")
    rotate.add_argument("name")
    remove = sub.add_parser("remove", help="Delete a credential nothing uses")
    remove.add_argument("name")


def _read_value(prompt: str) -> str:
    return getpass.getpass(prompt)


def _add(args: argparse.Namespace) -> int:
    origins = tuple(args.origin)
    if args.kind == "env" and (origins or args.header):
        print("An env credential takes no --origin or --header.", file=sys.stderr)
        return EXIT_USAGE
    if args.kind == "header" and not args.header:
        print("A header credential needs --header NAME.", file=sys.stderr)
        return EXIT_USAGE
    if args.kind == "query" and not args.header:
        print("A query credential needs --header set to the parameter name.", file=sys.stderr)
        return EXIT_USAGE
    cred = credentials.Credential(
        name=args.name, kind=args.kind,
        header_name=args.header if args.kind == "header" else "",
        query_param=args.header if args.kind == "query" else "",
        origins=origins,
    )
    try:
        credentials._validate(cred)
        secret = _read_value(f"Value for {args.name}: ")
        credentials.save(cred, secret)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return EXIT_USAGE
    except credentials.Locked as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    print(f"Stored credential {args.name}.")
    return EXIT_OK


def _list() -> int:
    rows = credentials.list_all()
    if not rows:
        print("No credentials stored.")
        return EXIT_OK
    for cred in rows:
        detail = ", ".join(cred.origins) if cred.origins else "-"
        print(f"{cred.name}  {cred.kind}  {detail}  used: {cred.last_used or 'never'}")
    return EXIT_OK


def _rotate(args: argparse.Namespace) -> int:
    if credentials.get(args.name) is None:
        print(f"No credential named {args.name}.", file=sys.stderr)
        return EXIT_ERROR
    try:
        secret = _read_value(f"New value for {args.name}: ")
        credentials.rotate(args.name, secret)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return EXIT_USAGE
    except credentials.Locked as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    print(f"Rotated credential {args.name}.")
    return EXIT_OK


def _remove(args: argparse.Namespace) -> int:
    if credentials.get(args.name) is None:
        print(f"No credential named {args.name}.", file=sys.stderr)
        return EXIT_ERROR
    in_use = users.of("credential", args.name)
    if in_use:
        print(f"Not removed: {args.name} is used by {', '.join(in_use)}.", file=sys.stderr)
        return EXIT_ERROR
    credentials.remove(args.name)
    print(f"Removed credential {args.name}.")
    return EXIT_OK


def run(args: argparse.Namespace) -> int:
    command = args.cred_command
    if command == "add":
        return _add(args)
    if command == "list":
        return _list()
    if command == "rotate":
        return _rotate(args)
    return _remove(args)
