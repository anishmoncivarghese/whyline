"""`whyline doctor`: every health check in one list, each with its fix.

The checks used to be scattered: hook state in `status`, stale ownership
and unclosed handoffs visible only by reading `sync` carefully, ledger size
and prompt policy nowhere. Each check here is read-only -- doctor reports
and suggests; it never changes anything, least of all another tool's
security settings (Antigravity's trusted folders).
"""

from __future__ import annotations

import json
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "fail"
ANTIGRAVITY_SETTINGS = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
LARGE_LEDGER_BYTES = 50_000_000


def _check(name: str, status: str, detail: str, fix: str = "") -> dict:
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def _instructions(root: Path) -> dict:
    from whyline import agentsmd

    target = root / "AGENTS.md"
    if not target.exists():
        return _check("instructions", WARN, "no AGENTS.md, so agents are never told to use whyline", "whyline init")
    text = target.read_text(encoding="utf-8")
    match = agentsmd._BLOCK.search(text)
    if match is None:
        return _check("instructions", WARN, "AGENTS.md has no whyline block", "whyline init")
    if match.group(0).strip() != agentsmd.INSTRUCTION.strip():
        return _check("instructions", WARN, "the whyline block in AGENTS.md is outdated", "whyline init")
    return _check("instructions", OK, "AGENTS.md carries the current whyline block")


def _hooks(root: Path) -> list[dict]:
    import shutil

    from whyline import render

    reports = render.status_payload(root)["hooks"]
    in_use = {
        "claude": shutil.which("claude") is not None or (root / ".claude").is_dir(),
        "codex": shutil.which("codex") is not None or (root / ".codex").is_dir(),
        "antigravity": "antigravity" in reports,
    }
    checks = []
    for agent, report in reports.items():
        if not in_use.get(agent):
            continue
        name = f"{agent} hook"
        if report["healthy"]:
            checks.append(_check(name, OK, report["detail"]))
        elif not report["configured"]:
            checks.append(_check(name, WARN, report["detail"], "whyline init"))
        else:
            checks.append(_check(name, WARN, "configured but not recording yet", report["detail"]))
    return checks


def _antigravity_trust(root: Path) -> dict | None:
    from whyline import hooks

    configured, _ = hooks.antigravity_configured(root)
    if not configured:
        return None
    fix = (
        "trust this folder in Antigravity: run `agy` here and accept the trust "
        "prompt (whyline does not change Antigravity's settings)"
    )
    try:
        settings = json.loads(ANTIGRAVITY_SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _check("antigravity trust", WARN, f"could not read {ANTIGRAVITY_SETTINGS}", fix)
    trusted = settings.get("trustedWorkspaces") if isinstance(settings, dict) else None
    here = root.resolve()
    for entry in trusted if isinstance(trusted, list) else []:
        try:
            if isinstance(entry, str) and Path(entry).expanduser().resolve() == here:
                return _check("antigravity trust", OK, "this folder is trusted, so agy loads its hooks")
        except OSError:
            continue
    return _check(
        "antigravity trust", WARN,
        "this folder is not trusted in Antigravity, so agy ignores its hooks", fix,
    )


def _state(root: Path) -> list[dict]:
    from whyline import handoff, history, ownership

    loaded = history.load(root, mechanical=False)
    finished = handoff.finished_tasks(loaded.ledger_events)
    live, stale = ownership.split(ownership.load(root)["claims"], finished_tasks=finished)
    checks = []
    if stale:
        checks.append(_check(
            "stale claims", WARN,
            f"{len(stale)} claim{'s' if len(stale) != 1 else ''} expired or for a finished task",
            "whyline release --stale",
        ))
    else:
        checks.append(_check("stale claims", OK, "none"))
    overlaps = ownership.conflicts(live)
    if overlaps:
        checks.append(_check(
            "overlapping claims", WARN,
            f"{len(overlaps)} overlap{'s' if len(overlaps) != 1 else ''} between live claims",
            "coordinate with the other agent, or: whyline release TASK",
        ))
    active = handoff.load(root)
    settled = handoff.settled(root, active)
    if not active:
        checks.append(_check("handoff", OK, "none active"))
    elif settled and settled["reason"] == "closed":
        checks.append(_check("handoff", OK, f"{active.get('task', '')} closed"))
    elif settled:
        checks.append(_check(
            "handoff", WARN,
            f"{active.get('task', '')} is {active.get('status', '')} and "
            f"{settled['commits_behind']} commit(s) behind HEAD but was never closed",
            "whyline handoff close --status completed",
        ))
    else:
        checks.append(_check(
            "handoff", OK, f"{active.get('task', '')} open ({active.get('status', '')})"
        ))
    return checks


def _ledger(root: Path) -> list[dict]:
    from whyline import ledgerops

    report = ledgerops.stats(root)
    checks = []
    if report["unreadable_lines"]:
        checks.append(_check(
            "ledger", WARN,
            f"{report['unreadable_lines']} unreadable line(s) are being skipped",
            "inspect .whyline/ledger.jsonl; a torn final line after a crash is harmless",
        ))
    elif report["bytes"] > LARGE_LEDGER_BYTES:
        checks.append(_check(
            "ledger", WARN, f"{report['bytes'] / 1e6:.0f} MB",
            "whyline ledger prune --older-than 30",
        ))
    else:
        checks.append(_check("ledger", OK, f"{report['events']} events, {report['bytes'] / 1e6:.1f} MB"))
    stored = report["prompt_text_bytes"]
    if stored and report["policy"] != "full":
        # The policy stops new prompt text; text recorded earlier stays until
        # scrubbed, which is easy to miss.
        checks.append(_check(
            "prompt capture", WARN,
            f"{report['policy']}, but {stored / 1e6:.2f} MB of earlier prompt text is still stored",
            "whyline ledger scrub-prompts",
        ))
    else:
        checks.append(_check("prompt capture", OK, report["policy"]))
    return checks


def _decisions_md(root: Path) -> dict:
    from whyline import decisions, paths

    target = paths.decisions_path(root)
    if decisions.has_conflict_markers(target):
        return _check(
            "decisions.md", FAIL, "holds unresolved merge conflict markers",
            "resolve the conflict in .whyline/decisions.md (keep both sides' entries)",
        )
    return _check("decisions.md", OK, f"{len(decisions.parse_entries(target))} entries readable")


def _relay() -> dict:
    import importlib.util

    if importlib.util.find_spec("whyline_relay") is None:
        return _check("relay", WARN, "whyline-relay is missing from this install",
                      "uv tool install --reinstall whyline")
    return _check("relay", OK, "whyline-relay is installed")


def run(root: Path) -> list[dict]:
    from whyline import paths

    if not paths.is_initialised(root):
        return [_check("initialised", FAIL, "whyline is not set up in this repository", "whyline init")]
    checks = [_check("initialised", OK, str(root)), _instructions(root)]
    checks += _hooks(root)
    trust = _antigravity_trust(root)
    if trust:
        checks.append(trust)
    checks += _state(root)
    checks += _ledger(root)
    checks.append(_decisions_md(root))
    checks.append(_relay())
    return checks


def text(checks: list[dict]) -> str:
    lines = []
    for item in checks:
        lines.append(f"{item['status']:<6}{item['name']}: {item['detail']}")
        if item["fix"] and item["status"] != OK:
            lines.append(f"      fix: {item['fix']}")
    counts = {status: sum(1 for c in checks if c["status"] == status) for status in (OK, WARN, FAIL)}
    lines.append("")
    lines.append(f"{counts[OK]} ok, {counts[WARN]} warning(s), {counts[FAIL]} failure(s)")
    return "\n".join(lines)
