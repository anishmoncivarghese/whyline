"""Setup check for the daily job shortlist, shared by `whyline jobs doctor` and the console."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from whyline.jobs import companies, profile

AGENT_NAME = "job-search"
OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Row:
    name: str
    state: str
    detail: str
    fix: str = ""


def _row(name: str, ok: bool, detail: str, fix: str, *, bad: str = FAIL) -> Row:
    return Row(name, OK if ok else bad, detail, "" if ok else fix)


def _statuses() -> dict:
    return profile.status()


def _companies() -> list:
    return list(companies.list(status="accepted"))


def _find_agent():
    from whyline.agents import service

    return service.find(AGENT_NAME, None)


def _agent_status(defn) -> str:
    from whyline.agents import state

    return state.check_hash(state.connect(), defn)


def _enabled() -> list[str]:
    from whyline.jobs import review

    return review.enabled_providers()


def _unattended(cli: str) -> bool:
    from whyline.agents import capabilities

    return capabilities.can_run_unattended(cli)


def _scheduler_loaded() -> bool:
    from whyline.agents import launchd

    return launchd.status().loaded


def _delivery(agent_id: str):
    from whyline.agents import deliveries

    return deliveries.get(agent_id)


def check(
    *,
    statuses_fn: Callable[[], dict] | None = None,
    companies_fn: Callable[[], list] | None = None,
    find_agent_fn: Callable[[], object] | None = None,
    agent_status_fn: Callable[[object], str] | None = None,
    enabled_fn: Callable[[], list[str]] | None = None,
    unattended_fn: Callable[[str], bool] | None = None,
    scheduler_fn: Callable[[], bool] | None = None,
    delivery_fn: Callable[[str], object] | None = None,
) -> list[Row]:
    """One row per setup step. Every probe can be stubbed; none writes anything."""
    statuses_fn = statuses_fn or _statuses
    companies_fn = companies_fn or _companies
    find_agent_fn = find_agent_fn or _find_agent
    agent_status_fn = agent_status_fn or _agent_status
    enabled_fn = enabled_fn or _enabled
    unattended_fn = unattended_fn or _unattended
    scheduler_fn = scheduler_fn or _scheduler_loaded
    delivery_fn = delivery_fn or _delivery

    try:
        files = statuses_fn()
    except Exception:  # noqa: BLE001 - a probe that breaks is a failed row, not a crash
        files = {}

    def present(name: str) -> bool:
        entry = files.get(name)
        return bool(entry is not None and entry.exists)

    rows = [
        _row("CV", present(profile.CV_FILE), "cv.md found" if present(profile.CV_FILE) else "no CV yet",
             "Import or paste your CV in Jobs, or run `whyline jobs profile import-cv FILE`."),
    ]
    both = present(profile.PROFILE_FILE) and present(profile.RUBRIC_FILE)
    rows.append(_row(
        "Profile and rubric", both,
        "profile.md and rubric.md accepted" if both else "not accepted yet",
        "Run Review my CV in Jobs, then Accept (or `whyline jobs review accept`).",
    ))

    try:
        accepted = companies_fn()
    except Exception:  # noqa: BLE001
        accepted = []
    known = [c for c in accepted if getattr(c, "ats", "unknown") != "unknown"]
    rows.append(_row(
        "Companies", bool(known),
        f"{len(known)} of {len(accepted)} accepted with a known board" if accepted else "no accepted companies",
        "Accept a company and run Check boards (or `whyline jobs companies check`).",
    ))

    defn = None
    try:
        defn = find_agent_fn()
        status = agent_status_fn(defn)
    except Exception:  # noqa: BLE001
        status = "missing"
    agent_ok = defn is not None and status not in ("missing", "not accepted", "needs_review")
    detail = {
        "missing": f"no {AGENT_NAME} agent",
        "not accepted": f"{AGENT_NAME} not accepted",
        "needs_review": f"{AGENT_NAME} changed since you accepted it",
    }.get(status, f"{AGENT_NAME} is {status}")
    rows.append(_row(
        "Agent", agent_ok, detail,
        "Create it from the Daily job shortlist template in Agents, then Accept it.",
    ))

    if defn is None or not agent_ok:
        runner_row = Row("Runner", FAIL, "no agent to check", "Fix the agent first.")
    else:
        try:
            enabled = set(enabled_fn())
        except Exception:  # noqa: BLE001
            enabled = set()
        chain = [c for c in (getattr(defn, "runner", ""), *getattr(defn, "backup", ())) if c]
        usable = [c for c in chain if c in enabled and unattended_fn(c)]
        runner_row = _row(
            "Runner", bool(usable),
            f"{usable[0]} will run it unattended" if usable else "no enabled runner is cleared for unattended runs",
            "Enable claude, codex or grok in Settings and clear it for unattended runs.",
        )
    rows.append(runner_row)

    try:
        loaded = bool(scheduler_fn())
    except Exception:  # noqa: BLE001
        loaded = False
    rows.append(_row(
        "Scheduler", loaded,
        "scheduler is loaded" if loaded else "scheduler is not loaded",
        "Turn the scheduler on in Agents.", bad=WARN,
    ))

    delivery = None
    if defn is not None:
        try:
            delivery = delivery_fn(getattr(defn, "agent_id", f"personal:{AGENT_NAME}"))
        except Exception:  # noqa: BLE001
            delivery = None
    has_delivery = delivery is not None and not getattr(delivery, "empty", False)
    rows.append(_row(
        "Delivery", has_delivery,
        "delivery is set" if has_delivery else "no delivery set",
        "Set an email or Telegram delivery for the agent in Agents.", bad=WARN,
    ))
    return rows


def format_rows(rows: list[Row]) -> list[str]:
    """The lines both `whyline jobs doctor` and the console Check button show."""
    lines = []
    for row in rows:
        lines.append(f"{row.state.upper():<4}  {row.name}: {row.detail}")
        if row.fix:
            lines.append(f"      {row.fix}")
    return lines
