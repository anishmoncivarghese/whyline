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
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from whyline.security import audit, contents, deps, external, lockfiles, secrets
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
    audit_missing: bool = False

    @property
    def blocks(self) -> bool:
        return bool(self.error) or bool(self.decision.blocking) or self.audit_missing


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
    audit_base: Path | None = None,
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
        if scope in ("release", "all") and settings.audit != "off":
            _gate_audit(root, settings, exempt, report, audit_base)
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
    lock = deps.without_skipped(lockfiles.read_report(root), settings.skip_paths)
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
    entries = st._read_allow(root)
    ignored = set(st._ignored(state_dir(root)))

    def is_exempt(finding: Finding) -> bool:
        return bool(finding.fingerprint) and (
            finding.fingerprint in ignored or any(st.matches_entry(e, finding) for e in entries)
        )

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


# --- the deep audit --------------------------------------------------------------

AUDIT_MISSING_TEXT = "run a deep audit first"
_HIGH = ("critical", "high")
_VERDICT_ORDER = {"confirmed": 0, "needs_validation": 1}
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass(frozen=True)
class AuditRun:
    """One finished run folder: its verdict counts and whether it can be read."""
    number: int
    path: Path
    findings: tuple[Finding, ...] = ()
    rejected: int = 0
    valid: bool = True
    has_report: bool = False

    def count(self, verdict: str) -> int:
        return sum(1 for f in self.findings if f.rule == verdict)

    @property
    def report_path(self) -> Path:
        return self.path / audit.REPORT_FILE


def sort_audit_findings(findings) -> list[Finding]:
    """By verdict (confirmed first), then severity (worst first)."""
    return sorted(findings, key=lambda f: (_VERDICT_ORDER.get(f.rule, 2),
                                           _SEVERITY_ORDER.get(f.severity, 4)))


def audit_runs(root: Path | str, base: Path | None = None) -> list[AuditRun]:
    """Past runs for this repository, newest first. Runs with no findings.json
    (stopped or failed before writing it) are left out."""
    parent = (base or audit.audits_root()) / Path(root).resolve().name
    runs: list[AuditRun] = []
    if not parent.is_dir():
        return runs
    for folder in parent.glob("run-*"):
        suffix = folder.name[4:]
        if not suffix.isdigit() or not (folder / audit.FINDINGS_FILE).is_file():
            continue
        found, rejected, errors = audit.parse_findings(folder)
        runs.append(AuditRun(int(suffix), folder, tuple(found), rejected, not errors,
                             (folder / audit.REPORT_FILE).is_file()))
    return sorted(runs, key=lambda r: r.number, reverse=True)


def latest_audit(root: Path | str, base: Path | None = None) -> AuditRun | None:
    """The newest run that can be read, or None when there is none."""
    return next((r for r in audit_runs(root, base) if r.valid), None)


def _gate_audit(root: Path, settings: SecuritySettings, exempt: Callable[[Finding], bool],
                report: ScanReport, base: Path | None) -> None:
    """Add the latest audit's confirmed findings to the decision. `warn` makes
    them warnings; `block-confirmed` blocks the critical and high ones and warns
    on the rest. `needs_validation` findings never reach the gate."""
    run_ = latest_audit(root, base)
    if run_ is None:
        if settings.audit == "block-confirmed":
            report.audit_missing = True
        return
    confirmed = [f for f in run_.findings if f.rule == "confirmed"]
    d = report.decision
    blocking, warnings, allowed = list(d.blocking), list(d.warnings), list(d.allowed)
    for f in confirmed:
        if exempt(f):
            allowed.append(f)
        elif settings.audit == "block-confirmed" and f.severity in _HIGH:
            blocking.append(f)
        else:
            warnings.append(f)
    report.findings = [*report.findings, *confirmed]
    report.decision = Decision(tuple(blocking), tuple(warnings), tuple(allowed))


def main_agents(root: Path | str) -> list[str]:
    """The relay's main agent (the implementer) followed by its backup chain."""
    from whyline.console import relay_ops

    root = Path(root)
    chain: list[str] = []
    for name in (relay_ops.current_roles(root).get("implementer"), *relay_ops.read_backup(root)):
        if isinstance(name, str) and name and name not in chain:
            chain.append(name)
    return chain


def _default_ask(agent: str, prompt: str, *, cwd: Path, cancel_event: threading.Event | None = None):
    """Run one agent with the audit prompt. It may take as long as the relay's own
    agent timeout allows, and it must be able to write into the output folder."""
    from types import SimpleNamespace

    from whyline.agents import runner as agent_runner
    from whyline_relay import agents, chat, config

    argv = chat.resolve_command(config.load(cwd), agent)
    extra = {} if cancel_event is None else {"cancel_event": cancel_event}
    code, raw, error = None, "", None
    try:
        with tempfile.TemporaryDirectory(prefix="whyline-audit-") as tmp:
            result = agents.run(argv, prompt, cwd=cwd, log_path=Path(tmp) / "output.log",
                                timeout_seconds=None, capture=True,
                                echo=False, agent_name=agent, **extra)
            code, raw = result.exit_code, result.output or ""
    except Exception as caught:  # AgentCancelled, AgentMissing, OSError
        error = caught
    if error is None and code == 0:
        return SimpleNamespace(ok=True, failure="", text=raw)
    outcome, reason = agent_runner._classify(agent, code, raw, error)
    failure = {"usage_limit": "limit", "login_needed": "auth"}.get(outcome, outcome or "error")
    return SimpleNamespace(ok=False, failure=failure, text=reason)


def run_audit(
    root: Path | str,
    *,
    agent: str | None = None,
    ask_agent: Callable[..., object] | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[str], None] | None = None,
    out_dir: Path | None = None,
) -> audit.AuditReport:
    """Run one deep audit; the Security screen and `whyline security audit` both
    call this. `agent` picks one agent; otherwise the main agent and its backups."""
    chain = [agent] if agent else main_agents(root)
    if not chain:
        raise ValueError("no agent is configured for the audit; pass --agent NAME")
    return audit.run(root, agent=chain, ask_agent=ask_agent or _default_ask, out_dir=out_dir,
                     cancel_event=cancel_event, on_progress=on_progress)


# --- the Release Ready items ---------------------------------------------------

_BLOCK_LABEL = (("secret", "secrets"), ("dependency", "dependencies"), ("contents", "contents"))


def ready_text(report: ScanReport) -> tuple[bool, str]:
    if report.error:
        return False, f"security scan failed: {report.error}"
    if report.audit_missing and not report.decision.blocking:
        return False, AUDIT_MISSING_TEXT
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
