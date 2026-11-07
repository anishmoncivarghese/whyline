"""`whyline security`: scan, allow and status. A thin command line over `scan`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from whyline.security import external, hook, scan
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
    scan_p.add_argument("--hook", action="store_true",
                        help="pre-commit mode: blocking secrets only, masked (use with --staged)")
    allow_p = sub.add_parser("allow", help="Allow one finding, by fingerprint")
    allow_p.add_argument("fingerprint")
    allow_p.add_argument("--reason", required=True, help="why this is safe")
    audit_p = sub.add_parser("audit", help="Deep audit by your main agent (slow, uses many tokens)")
    audit_p.add_argument("--agent", metavar="NAME", help="agent to use instead of the main agent")
    sub.add_parser("status", help="Settings, tools found, rules, last history scan")
    hook_p = sub.add_parser("hook", help="Check every commit with a pre-commit hook")
    hook_p.add_argument("hook_command", choices=("install", "uninstall", "status"))


def _root() -> Path:
    from whyline import paths

    return paths.find_repo_root() or Path.cwd()


def _settings_and_branch(root: Path):
    from whyline.release import config as release_config

    cfg = release_config.load(root)
    return cfg.security, cfg.branch


def run(args: argparse.Namespace) -> int:
    handlers = {"scan": _scan, "allow": _allow, "status": _status, "hook": _hook, "audit": _audit}
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


def _hook_scan(root: Path) -> int:
    """`scan --staged --hook`: secrets only, nothing else, exit 1 on a block."""
    settings, branch = _settings_and_branch(root)
    if settings.secrets == "off":
        return EXIT_OK
    report = scan.run(root, "staged", settings, branch=branch)
    if report.error:
        print(f"Security scan failed: {report.error}")
    for f in report.decision.blocking:
        if f.kind == "secret":
            print(f"[BLOCK] {f.title} ({f.rule}) {_where(f)}  {f.preview}".rstrip())
    if report.blocks:
        print(hook.STOP_LINE)
        return EXIT_ERROR
    return EXIT_OK


def _hook(args) -> int:
    root = _root()
    action = args.hook_command
    try:
        if action == "install":
            path = hook.install(root)
            print(f"Installed {path}.")
        elif action == "uninstall":
            print("Removed the whyline pre-commit hook." if hook.uninstall(root)
                  else "No whyline pre-commit hook to remove.")
        else:
            state = ("on" if hook.installed(root)
                     else "off (another pre-commit hook exists)" if hook.foreign(root) else "off")
            print(f"Check every commit: {state}")
    except hook.HookError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def _scan(args) -> int:
    root = _root()
    if getattr(args, "hook", False):
        if not args.staged:
            print("--hook needs --staged.", file=sys.stderr)
            return EXIT_ERROR
        return _hook_scan(root)
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
        "audit_missing": report.audit_missing,
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
    if report.audit_missing:
        print(f"[BLOCK] Audit: {scan.AUDIT_MISSING_TEXT}")
    for note in report.notes:
        print(f"note: {note}")
    if report.cancelled:
        print("The scan was cancelled; results are partial.")
    print(f"Summary: {len(d.blocking)} blocking, {len(d.warnings)} warnings, {len(d.allowed)} allowed")


AUDIT_NOTICE = ("The deep audit uses your main agent, may take a long time and many tokens, "
                "and one run finds only part of what repeated runs do.")


def _audit(args) -> int:
    root = _root()
    print(AUDIT_NOTICE, file=sys.stderr)
    try:
        report = scan.run_audit(root, agent=args.agent,
                                on_progress=lambda m: print(m, file=sys.stderr))
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    for f in scan.sort_audit_findings(report.findings):
        print(f"[{f.rule}] {f.severity} {f.title} {_where(f)}".rstrip())
        print(f"      fingerprint {f.fingerprint}")
    print(report.summary)
    if report.report_path:
        print(f"Report: {report.report_path}")
    return EXIT_OK if report.ok else EXIT_ERROR


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
