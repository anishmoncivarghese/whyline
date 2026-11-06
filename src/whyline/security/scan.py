"""Run the security checks for one scope and decide what blocks.

Scopes: `release` (commits not yet on `origin/<branch>`, the built package
contents, and pinned dependencies), `staged`, `history` (every commit ever) and
`all` (history, the working tree, contents and dependencies). Everything that
touches git, the network or an installed tool is injected, so tests use fakes.
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from whyline.security import contents, deps, external, lockfiles, secrets
from whyline.security import settings as st
from whyline.security.findings import Finding
from whyline.security.settings import Decision, SecuritySettings

SCOPES = ("release", "staged", "history", "all")
STATE_DIR = Path(".git") / "whyline-release"


@dataclass
class ScanReport:
    scope: str
    findings: list[Finding] = field(default_factory=list)
    decision: Decision = field(default_factory=Decision)
    notes: list[str] = field(default_factory=list)
    error: str = ""
    cancelled: bool = False

    @property
    def blocks(self) -> bool:
        return bool(self.error) or bool(self.decision.blocking)


def state_dir(root: Path) -> Path:
    return Path(root) / STATE_DIR


def _has_ref(root: Path, ref: str, run: Callable) -> bool:
    try:
        done = run(["git", "rev-parse", "--verify", "-q", ref], cwd=str(root),
                   capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(done, "returncode", 1) == 0


def release_range(root: Path, branch: str, run: Callable) -> str:
    """`origin/<branch>..HEAD`, or `HEAD` (everything) before the first push."""
    ref = f"origin/{branch}"
    return f"{ref}..HEAD" if _has_ref(root, ref, run) else "HEAD"


def run(
    root: Path | str,
    scope: str,
    settings: SecuritySettings,
    *,
    run: Callable = subprocess.run,
    fetch: Callable = deps.urllib_fetch,
    which: Callable[[str], str | None] = shutil.which,
    on_progress: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
    branch: str = "main",
    now: Callable[[], datetime] = datetime.now,
) -> ScanReport:
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {', '.join(SCOPES)}, not {scope!r}")
    root = Path(root)
    report = ScanReport(scope)
    found: list[Finding] = []
    tools = external.available(which)
    secret_tool = next((t for t in external.SECRET_TOOLS if t in tools), None)
    want_secrets = settings.secrets != "off"
    try:
        if want_secrets:
            found.extend(_secrets(root, scope, run, secret_tool and tools[secret_tool], secret_tool,
                                  branch, on_progress, cancel_event, report))
        if scope in ("release", "all") and settings.contents != "off":
            found.extend(contents.check(root, run=run))
        if scope in ("release", "all") and settings.dependencies != "off":
            found.extend(_deps(root, settings, run, fetch, tools, now, report))
        report.cancelled = bool(cancel_event is not None and cancel_event.is_set())
        exempt = _exempt(root)
        report.findings = found
        report.decision = st.decide(found, settings, exempt)
    except (secrets.ScanError, st.SettingsError) as exc:
        report.error = str(exc)
        return report
    if scope in ("history", "all") and want_secrets and not report.cancelled:
        _save_history(root, settings, now(), report)
    return report


def _secrets(root, scope, run, tool_path, tool, branch, on_progress, cancel_event, report):
    found: list[Finding] = []
    outside: list[Finding] = []
    if scope == "staged":
        return secrets.scan_staged(root, run=run)
    if scope == "release":
        rev_range = release_range(root, branch, run)
        found = secrets.scan_range(root, rev_range, run=run)
        if tool:
            outside, notes = external.scan_secrets(tool, tool_path, root, rev_range, run=run)
            report.notes.extend(notes)
    else:
        found = secrets.scan_history(root, run=run, on_progress=on_progress, cancel_event=cancel_event)
        if scope == "all":
            found = secrets._dedupe([*found, *secrets.scan_paths(root, ["."])])
        if tool:
            outside, notes = external.scan_secrets(tool, tool_path, root, None, run=run)
            report.notes.extend(notes)
    return external.merge(found, outside)


def _deps(root, settings, run, fetch, tools, now, report):
    lock = lockfiles.read_report(root)
    for item in lock.unpinned:
        report.notes.append(item.note)
    for dep in (d for d in lock.dependencies if not d.public):
        report.notes.append(f"{dep.name}: private package, not checked")
    result = deps.check(lock.dependencies, fetch=fetch, cache_dir=state_dir(root) / "osv-cache", now=now())
    found = list(result.findings)
    if result.error:
        if settings.dependencies in ("block", "block-high"):
            raise secrets.ScanError(result.error)
        report.notes.append(result.error)
    if external.DEP_TOOL in tools:
        outside, notes = external.scan_deps(tools[external.DEP_TOOL], root, run=run)
        report.notes.extend(notes)
        found = external.merge(found, outside)
    return found


def _exempt(root: Path) -> Callable[[Finding], bool]:
    allowed = {e.get("fingerprint") for e in st._read_allow(root)}
    ignored = set(st._ignored(state_dir(root)))

    def is_exempt(finding: Finding) -> bool:
        return bool(finding.fingerprint) and (finding.fingerprint in allowed or finding.fingerprint in ignored)

    return is_exempt


def _save_history(root: Path, settings: SecuritySettings, when: datetime, report: ScanReport) -> None:
    from whyline.release import config as release_config

    try:
        cfg = release_config.load(root)
        stamp = when.date().isoformat() if isinstance(when, datetime) else date.today().isoformat()
        release_config.save(root, dataclasses.replace(
            cfg, security=dataclasses.replace(cfg.security, history_scanned=stamp)))
    except (release_config.ConfigError, OSError) as exc:
        report.notes.append(f"could not save the history scan date: {exc}")


# --- the Release Ready items ---------------------------------------------------

_BLOCK_LABEL = (("secret", "secrets"), ("dependency", "dependencies"), ("contents", "contents"))


def ready_text(report: ScanReport) -> tuple[bool, str]:
    if report.error:
        return False, f"security scan failed: {report.error}"
    blocking = report.decision.blocking
    if blocking:
        parts = []
        for kind, label in _BLOCK_LABEL:
            count = sum(1 for f in blocking if f.kind == kind)
            if count:
                parts.append(f"{label}: {count}")
        other = sum(1 for f in blocking if f.kind not in {k for k, _ in _BLOCK_LABEL})
        if other:
            parts.append(f"audit: {other}")
        return False, f"{len(blocking)} blocking findings ({', '.join(parts)})"
    warned = len(report.decision.warnings)
    return True, f"{warned} warnings" if warned else "no findings"
