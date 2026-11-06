"""Optional external scanners: gitleaks, betterleaks and osv-scanner.

Each tool writes its JSON report to a temp file, never to stdout, and secret
scanners always run with `--redact`, so no secret value reaches us. A tool that
crashes or times out becomes a warning; the built-in results stand.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from whyline.security.deps import severity_of
from whyline.security.findings import Finding, make_fingerprint

SECRET_TOOLS = ("gitleaks", "betterleaks")
DEP_TOOL = "osv-scanner"
TIMEOUT_SECONDS = 60

# osv-scanner exits 128 when it finds no packages to scan: not a failure.
_OSV_NO_PACKAGES = 128

Runner = Callable[..., Any]
Result = tuple[list[Finding], list[str]]


def available(which: Callable[[str], str | None] = shutil.which) -> dict[str, str]:
    """Map each installed external tool to its path."""
    found: dict[str, str] = {}
    for tool in (*SECRET_TOOLS, DEP_TOOL):
        path = which(tool)
        if path:
            found[tool] = path
    return found


def secret_command(tool: str, report: str, log_range: str | None = None, path: str | None = None) -> list[str]:
    """Build the secret scan command. `--redact` is always present."""
    if path is not None:
        head = [tool, "dir", path]
    else:
        head = [tool, "git"]
        if log_range:
            head += ["--log-opts", log_range]
    return [*head, "--report-format", "json", "--report-path", report, "--redact", "--exit-code", "0"]


def deps_command(report: str) -> list[str]:
    return [DEP_TOOL, "scan", "source", "-r", ".", "--format", "json", "--output", report]


def scan_secrets(
    tool: str,
    tool_path: str,
    repo: Path,
    log_range: str | None = None,
    path: str | None = None,
    run: Runner = subprocess.run,
) -> Result:
    """Run a secret scanner over a git range, or over a directory when `path` is set."""
    with tempfile.TemporaryDirectory(prefix="whyline-scan-") as tmp:
        report = str(Path(tmp) / "report.json")
        command = secret_command(tool_path, report, log_range, path)
        data, warning = _run_json(tool, command, report, repo, run, ok_codes=(0,))
    if warning:
        return [], [warning]
    return parse_secrets(tool, data), []


def scan_deps(tool_path: str, repo: Path, run: Runner = subprocess.run) -> Result:
    with tempfile.TemporaryDirectory(prefix="whyline-scan-") as tmp:
        report = str(Path(tmp) / "report.json")
        command = deps_command(report)
        command[0] = tool_path
        data, warning = _run_json(DEP_TOOL, command, report, repo, run, ok_codes=(0, 1, _OSV_NO_PACKAGES))
    if warning:
        return [], [warning]
    return parse_osv(data), []


def _run_json(
    tool: str, command: Sequence[str], report: str, repo: Path, run: Runner, ok_codes: Sequence[int]
) -> tuple[Any, str]:
    try:
        proc = run(
            list(command),
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"{tool} timed out after {TIMEOUT_SECONDS}s; built-in results used"
    except OSError as exc:
        return None, f"{tool} could not run ({exc}); built-in results used"
    if proc.returncode not in ok_codes:
        return None, f"{tool} failed (exit {proc.returncode}); built-in results used"
    try:
        text = Path(report).read_text(encoding="utf-8")
    except OSError:
        return [], ""  # some tools write no report when there is nothing to report
    if not text.strip():
        return [], ""
    try:
        return json.loads(text), ""
    except ValueError:
        return None, f"{tool} wrote unreadable JSON; built-in results used"


def parse_secrets(tool: str, data: Any) -> list[Finding]:
    """Convert a gitleaks/betterleaks JSON report. The report is run with
    `--redact`, so the preview never holds a value."""
    if not isinstance(data, list):
        return []
    findings: list[Finding] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        rule = str(item.get("RuleID") or "unknown")
        path = str(item.get("File") or "")
        findings.append(
            Finding(
                kind="secret",
                rule=rule,
                title=str(item.get("Description") or rule),
                severity="high",
                path=path,
                line=_int(item.get("StartLine")),
                commit=str(item.get("Commit") or ""),
                preview=f"(redacted by {tool})",
                fingerprint=make_fingerprint("secret", rule, path, str(item.get("Fingerprint") or "")),
                fix_hint="Remove the value, rotate the credential, and load it from the environment.",
                source=tool,
            )
        )
    return findings


def parse_osv(data: Any) -> list[Finding]:
    """Convert an `osv-scanner --format json` report."""
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []
    findings: list[Finding] = []
    for result in results:
        source = result.get("source") if isinstance(result, dict) else None
        path = str(source.get("path", "")) if isinstance(source, dict) else ""
        for entry in (result.get("packages") or []) if isinstance(result, dict) else []:
            package = entry.get("package") or {}
            name = str(package.get("name", ""))
            version = str(package.get("version", ""))
            ecosystem = str(package.get("ecosystem", ""))
            for vuln in entry.get("vulnerabilities") or []:
                vuln_id = str(vuln.get("id", ""))
                summary = str(vuln.get("summary") or vuln_id)
                findings.append(
                    Finding(
                        kind="dependency",
                        rule=vuln_id,
                        title=f"{name} {version}: {summary}",
                        severity=severity_of(vuln),
                        path=path,
                        preview=f"{name}=={version}",
                        fingerprint=make_fingerprint("dependency", vuln_id, f"{ecosystem}:{name}@{version}"),
                        source=DEP_TOOL,
                    )
                )
    return findings


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def rule_family(finding: Finding) -> str:
    """Rules from different tools name the same thing differently
    (`aws-access-token`, `aws_access_key`), so secrets compare on the leading
    word. Other kinds compare on the whole id."""
    rule = finding.rule.lower()
    if finding.kind != "secret":
        return rule
    return next((part for part in re.split(r"[^a-z0-9]+", rule) if part), rule)


def merge(builtin: Iterable[Finding], external: Iterable[Finding]) -> list[Finding]:
    """Combine both lists, one finding per (path, line, rule family). When both
    tools report it, the external finding wins so its rule name is kept."""
    merged: dict[tuple[str, int, str], Finding] = {}
    for finding in builtin:
        merged.setdefault((finding.path, finding.line, rule_family(finding)), finding)
    for finding in external:
        merged[(finding.path, finding.line, rule_family(finding))] = finding
    return list(merged.values())
