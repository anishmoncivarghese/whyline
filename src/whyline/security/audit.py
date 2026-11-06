"""Deep security audit run by the relay's main agent.

The method is Cloudflare's security-audit-skill (MIT), bundled in `audit_method/`
with its licence and a `VERSION` file. The agent reads the repository, writes
`findings.json` into a run folder under `~/.whyline/security/audits/`, and we
validate that file against the bundled schema before turning it into findings.
Nothing is written inside the audited repository.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from whyline.security.findings import Finding, make_fingerprint

METHOD_PACKAGE = "whyline.security"
METHOD_DIR = "audit_method"
SCHEMA_FILE = "report-schema.json"
FINDINGS_FILE = "findings.json"
REPORT_FILE = "REPORT.md"

# Phase instructions first, then the playbooks that fit this kind of project.
METHOD_FILES = (
    "SKILL.md",
    "RECONNAISSANCE.md",
    "HUNTING.md",
    "ATTACK-CLASSES.md",
    "AI-AND-LLM.md",
    "SUPPLY-CHAIN-AND-RELEASE.md",
    "WEB-PROTOCOL-AND-AUTH.md",
    "RESOURCE-EXHAUSTION-AND-AVAILABILITY.md",
    "DATA-ISOLATION-AND-LIFECYCLE.md",
    "DESKTOP-MOBILE-AND-LOCAL-IPC.md",
    "VALIDATION-AND-REPORTING.md",
)

VERDICTS = ("confirmed", "needs_validation", "rejected")
# Agent failures that move on to the next agent in the backup chain.
FALLBACK_FAILURES = ("limit", "auth")
MAX_ERRORS_SHOWN = 5
SCHEMA_MISMATCH = "the agent's output didn't match the schema"

_SEVERITY = {"critical": "critical", "high": "high", "medium": "medium", "low": "low", "informational": "low"}
_PREVIEW = 300

Progress = Callable[[str], None]


@dataclass(frozen=True)
class AuditReport:
    run_dir: Path
    run_number: int
    findings: tuple[Finding, ...] = ()
    rejected: int = 0
    warnings: tuple[str, ...] = ()
    schema_errors: tuple[str, ...] = ()
    agent: str = ""
    cancelled: bool = False
    report_path: Path | None = None
    summary: str = field(default="")

    @property
    def ok(self) -> bool:
        return not self.cancelled and not self.schema_errors and not self.warnings

    def with_verdict(self, verdict: str) -> list[Finding]:
        """Findings of one verdict (the verdict is the finding's `rule`)."""
        return [f for f in self.findings if f.rule == verdict]


def method_text(name: str) -> str:
    return resources.files(METHOD_PACKAGE).joinpath(f"{METHOD_DIR}/{name}").read_text("utf-8")


def method_version() -> str:
    return method_text("VERSION").strip()


def load_schema() -> dict[str, Any]:
    return json.loads(method_text(SCHEMA_FILE))


# ---------------------------------------------------------------------------
# A small validator for the subset of JSON Schema the findings schema uses:
# type, const, enum, pattern, minLength, minimum, minItems, uniqueItems,
# required, properties, additionalProperties, items, oneOf and visibleContent
# (a string with something other than whitespace in it).
# ---------------------------------------------------------------------------


def _type_ok(value: Any, kind: str) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    if kind == "null":
        return value is None
    return True


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Return one message per violation; an empty list means valid."""
    errors: list[str] = []
    kind = schema.get("type")
    if kind and not _type_ok(value, kind):
        return [f"{path}: expected {kind}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {', '.join(map(str, schema['enum']))}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: must not be empty")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match {schema['pattern']}")
        if schema.get("visibleContent") and not value.strip():
            errors.append(f"{path}: must have visible content")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value < schema.get("minimum", value):
        errors.append(f"{path}: must be at least {schema['minimum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        if schema.get("uniqueItems"):
            seen = [json.dumps(item, sort_keys=True) for item in value]
            if len(set(seen)) != len(seen):
                errors.append(f"{path}: items must be unique")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(validate(item, schema["items"], f"{path}[{index}]"))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", ()):
            if name not in value:
                errors.append(f"{path}: missing {name}")
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in properties:
                    errors.append(f"{path}: unexpected field {name}")
        for name, sub in properties.items():
            if name in value:
                errors.extend(validate(value[name], sub, f"{path}.{name}"))
    if "oneOf" in schema:
        errors.extend(_one_of(value, schema["oneOf"], path))
    return errors


def _one_of(value: Any, branches: list[dict[str, Any]], path: str) -> list[str]:
    results = [validate(value, branch, path) for branch in branches]
    if sum(1 for r in results if not r) == 1:
        return []
    if any(not r for r in results):
        return [f"{path}: matches more than one shape"]
    return min(results, key=len)


# ---------------------------------------------------------------------------
# Prompt, run folder, findings
# ---------------------------------------------------------------------------


def audits_root() -> Path:
    return Path.home() / ".whyline" / "security" / "audits"


def next_run_dir(base: Path, repo_name: str) -> tuple[Path, int]:
    parent = base / repo_name
    numbers = [
        int(p.name[4:]) for p in parent.glob("run-*") if p.name[4:].isdigit()
    ] if parent.is_dir() else []
    number = max(numbers, default=0) + 1
    return parent / f"run-{number}", number


def build_prompt(root: Path, run_dir: Path) -> str:
    method = "\n\n".join(f"<!-- {name} -->\n{method_text(name)}" for name in METHOD_FILES)
    schema = method_text(SCHEMA_FILE)
    return (
        "You are running a deep security audit of one repository, following the method below "
        f"(Cloudflare security-audit-skill, {method_version()}).\n\n"
        f"Repository to audit: {root}\n"
        f"Output directory: {run_dir}\n\n"
        "Rules for this run, which override anything in the method:\n"
        "- Do NOT run the project's code: no tests, builds, scripts, servers or installs. "
        "No sandbox is provided, so a lead you cannot confirm by reading the source stays "
        "`needs_validation`.\n"
        "- Do NOT modify the repository. Read it only.\n"
        f"- Write every file you produce into the output directory, never into the repository. "
        f"The method's helper scripts (validate-findings.cjs and the like) are not provided; skip them.\n"
        f"- Write `{FINDINGS_FILE}` in the output directory as a JSON array that validates against the schema "
        f"below, and optionally a human-readable `{REPORT_FILE}` there.\n\n"
        f"# Method\n\n{method}\n\n# Findings schema ({SCHEMA_FILE})\n\n```json\n{schema}\n```\n"
    )


def _to_finding(item: dict[str, Any]) -> Finding:
    verdict = item["verdict"]
    evidence = item.get("evidence") or [{}]
    where = evidence[0]
    severity = item.get("severity", {}).get("overall_severity", "")
    return Finding(
        kind="audit",
        rule=verdict,
        title=item["title"],
        severity=_SEVERITY.get(severity, "unknown"),
        path=str(where.get("file", "")),
        line=int(where.get("line", 0)),
        preview=item["description"][:_PREVIEW],
        fingerprint=make_fingerprint("audit", "", "", item["fingerprint"]),
        fix_hint=item.get("remediation", {}).get("strategy", "") if verdict == "confirmed" else "",
        source="audit",
    )


def parse_findings(run_dir: Path) -> tuple[list[Finding], int, list[str]]:
    """Read and validate `findings.json`: (findings, rejected count, errors).

    The file is left in place when it is invalid."""
    path = run_dir / FINDINGS_FILE
    if not path.is_file():
        return [], 0, [f"{FINDINGS_FILE} was not written"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], 0, [f"{FINDINGS_FILE} is not valid JSON: {exc}"]
    errors = validate(data, load_schema())
    if errors:
        return [], 0, errors
    findings = [_to_finding(item) for item in data if item["verdict"] != "rejected"]
    return findings, len(data) - len(findings), []


def _failure(reply: Any) -> str:
    return "" if getattr(reply, "ok", True) else (getattr(reply, "failure", "") or "error")


def run(
    root: Path | str,
    *,
    agent: str | Sequence[str],
    ask_agent: Callable[..., Any],
    out_dir: Path | str | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Progress | None = None,
) -> AuditReport:
    """Run one audit. `agent` is the main agent, or the main agent followed by its
    backup chain; a backup is used only after a `limit` or `auth` failure.

    `ask_agent(agent, prompt, *, cwd, cancel_event)` returns an object with `ok`,
    `failure` ("limit", "auth" or anything else) and `text`. No timeout is passed:
    the user's own setting decides how long the agent may take. `out_dir` replaces
    `~/.whyline/security/audits` and may not be inside the repository."""
    root = Path(root).resolve()
    base = Path(out_dir).expanduser().resolve() if out_dir is not None else audits_root()
    run_dir, number = next_run_dir(base, root.name)
    if run_dir == root or root in run_dir.parents:
        raise ValueError("the audit output directory must be outside the repository")
    cancel = cancel_event or threading.Event()
    progress = on_progress or (lambda _message: None)
    chain = [agent] if isinstance(agent, str) else list(agent)
    if not chain:
        raise ValueError("an agent is needed to run the audit")

    run_dir.mkdir(parents=True, exist_ok=True)
    if cancel.is_set():
        return AuditReport(run_dir, number, cancelled=True, summary="Audit stopped before it started.")

    prompt = build_prompt(root, run_dir)
    warnings: list[str] = []
    used = ""
    succeeded = False
    for name in chain:
        used = name
        progress(f"Asking {name} to audit {root.name}…")
        reply = ask_agent(name, prompt, cwd=root, cancel_event=cancel)
        if cancel.is_set():
            return AuditReport(run_dir, number, agent=name, cancelled=True, summary="Audit stopped.")
        failure = _failure(reply)
        if not failure:
            succeeded = True
            break
        warnings.append(f"{name} failed ({failure})")
        if failure not in FALLBACK_FAILURES:
            break
    if not succeeded and not (run_dir / FINDINGS_FILE).is_file():
        return AuditReport(
            run_dir, number, warnings=tuple(warnings), agent=used,
            summary="The audit did not finish: " + "; ".join(warnings) + ".",
        )

    progress("Checking findings.json against the schema…")
    findings, rejected, errors = parse_findings(run_dir)
    report = run_dir / REPORT_FILE
    if errors:
        shown = errors[:MAX_ERRORS_SHOWN]
        more = len(errors) - len(shown)
        summary = f"{SCHEMA_MISMATCH}. First errors: " + "; ".join(shown) + (f"; and {more} more" if more else "")
        return AuditReport(
            run_dir, number, warnings=tuple(warnings), schema_errors=tuple(errors), agent=used,
            report_path=report if report.is_file() else None, summary=summary + f". Kept in {run_dir}.",
        )
    summary = f"{len(findings)} finding(s), {rejected} rejected. Saved in {run_dir}."
    return AuditReport(
        run_dir, number, tuple(findings), rejected, tuple(warnings), agent=used,
        report_path=report if report.is_file() else None, summary=summary,
    )
