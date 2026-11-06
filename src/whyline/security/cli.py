"""`whyline security`: scan, allow and status. A thin command line over `scan`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from whyline.security import external, scan
from whyline.security import settings as st
from whyline.security.findings import Finding

EXIT_OK = 0
EXIT_ERROR = 1

_KIND_TITLES = (("secret", "Secrets"), ("dependency", "Dependencies"),
                ("contents", "Package contents"), ("audit", "Audit"))


def add_parser(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("security", help="Security: scan, allow, status")
    sub = parser.add_subparsers(dest="security_command", required=True)
    scan_p = sub.add_parser("scan", help="Scan for secrets, vulnerable dependencies and package contents")
    group = scan_p.add_mutually_exclusive_group()
    group.add_argument("--staged", action="store_true", help="only what is staged for commit")
    group.add_argument("--history", action="store_true", help="every commit ever made")
    group.add_argument("--all", action="store_true", help="history, working tree, contents and dependencies")
    scan_p.add_argument("--json", action="store_true", help="print the result as JSON")
    allow_p = sub.add_parser("allow", help="Allow one finding, by fingerprint")
    allow_p.add_argument("fingerprint")
    allow_p.add_argument("--reason", required=True, help="why this is safe")
    sub.add_parser("status", help="Settings, tools found, rules, last history scan")


def _root() -> Path:
    from whyline import paths

    return paths.find_repo_root() or Path.cwd()


def _settings_and_branch(root: Path):
    from whyline.release import config as release_config

    cfg = release_config.load(root)
    return cfg.security, cfg.branch


def run(args: argparse.Namespace) -> int:
    handlers = {"scan": _scan, "allow": _allow, "status": _status}
    try:
        return handlers[args.security_command](args)
    except Exception as exc:  # noqa: BLE001 - config and allowlist errors print one line
        from whyline.release.config import ConfigError

        if isinstance(exc, (ConfigError, st.SettingsError)):
            print(str(exc), file=sys.stderr)
            return EXIT_ERROR
        raise


def _scope(args) -> str:
    for name in ("staged", "history", "all"):
        if getattr(args, name, False):
            return name
    return "release"


def _progress(done: int, total: int) -> None:
    if sys.stderr.isatty():
        print(f"\rScanning history: {done}/{total or '?'} commits", end="", file=sys.stderr, flush=True)


def _where(f: Finding) -> str:
    place = f"{f.path}:{f.line}" if f.path and f.line else f.path
    return f"{place} @ {f.commit[:8]}" if f.commit and place else place or f.commit[:8]


def as_dict(f: Finding) -> dict:
    return {"kind": f.kind, "rule": f.rule, "title": f.title, "severity": f.severity,
            "path": f.path, "line": f.line, "commit": f.commit, "preview": f.preview,
            "fingerprint": f.fingerprint, "fix_hint": f.fix_hint, "source": f.source}


def _scan(args) -> int:
    root = _root()
    settings, branch = _settings_and_branch(root)
    scope = _scope(args)
    report = scan.run(root, scope, settings, branch=branch,
                      on_progress=None if args.json else _progress)
    if args.json:
        print(json.dumps(_json(report), indent=2))
    else:
        _print(report)
    return EXIT_ERROR if report.blocks else EXIT_OK


def _json(report: scan.ScanReport) -> dict:
    d = report.decision
    return {
        "scope": report.scope,
        "error": report.error,
        "blocks": report.blocks,
        "blocking": [as_dict(f) for f in d.blocking],
        "warnings": [as_dict(f) for f in d.warnings],
        "allowed": [as_dict(f) for f in d.allowed],
        "notes": report.notes,
    }


def _print(report: scan.ScanReport) -> None:
    if report.error:
        print(f"Security scan failed: {report.error}")
        return
    d = report.decision
    groups = (("BLOCK", d.blocking), ("warn", d.warnings), ("allowed", d.allowed))
    for kind, title in _KIND_TITLES:
        rows = [(label, f) for label, items in groups for f in items if f.kind == kind]
        if not rows:
            continue
        print(f"{title}:")
        for label, f in rows:
            print(f"  [{label}] {f.severity} {f.title} ({f.rule}) {_where(f)}  {f.preview}".rstrip())
            print(f"      fingerprint {f.fingerprint}")
            if f.fix_hint and label != "allowed":
                print(f"      {f.fix_hint}")
    for note in report.notes:
        print(f"note: {note}")
    if report.cancelled:
        print("The scan was cancelled; results are partial.")
    print(f"Summary: {len(d.blocking)} blocking, {len(d.warnings)} warnings, {len(d.allowed)} allowed")


def _allow(args) -> int:
    root = _root()
    settings, branch = _settings_and_branch(root)
    found = None
    for scope in ("release", "history"):
        report = scan.run(root, scope, settings, branch=branch)
        found = next((f for f in report.findings if f.fingerprint == args.fingerprint), None)
        if found:
            break
    if found is None:
        print(f"No finding with fingerprint {args.fingerprint} in the release or history scan.",
              file=sys.stderr)
        return EXIT_ERROR
    st.allow(root, found, args.reason)
    print(f"Allowed {found.fingerprint} ({found.rule} in {found.path or 'history'}).")
    return EXIT_OK


def _status(args) -> int:
    from whyline.security.rules import load_rules

    root = _root()
    settings, _ = _settings_and_branch(root)
    print("Settings:")
    for key in ("secrets", "dependencies", "contents", "audit", "pre_commit"):
        print(f"  {key}: {getattr(settings, key)}")
    tools = external.available()
    print("Tools:")
    for tool in (*external.SECRET_TOOLS, external.DEP_TOOL):
        print(f"  {tool}: {tools.get(tool, 'not found')}")
    print(f"Rules: {len(load_rules().rules)} bundled")
    print(f"Last history scan: {settings.history_scanned or 'never'}")
    return EXIT_OK
