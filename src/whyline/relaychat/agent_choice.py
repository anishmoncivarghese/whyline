"""Which agent answers relay chat: one with a read-only mode, kept off the working role."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from whyline.agents import capabilities


@dataclass(frozen=True)
class Pick:
    agent: str | None
    shares_quota: bool
    why: str


def _relay_ops():
    from whyline.console import relay_ops

    return relay_ops


def choices(repo: Path | str) -> list[str]:
    """Installed relay agents that can run read-only."""
    try:
        installed = _relay_ops().relay_agents(Path(repo))
    except Exception:
        return []
    return [name for name in installed if capabilities.can_run(name)]


def _working_agent(repo: Path, roles: dict) -> str | None:
    """The agent of the live turn, or None when no relay is running.

    Saved state while a relay runs is last-pause history, so only the live
    marker says who is using quota now.
    """
    try:
        from whyline_relay import running

        marker = running.live(repo)
    except Exception:
        return None
    if marker is None:
        return None
    return marker.agent


def pick(repo: Path | str, chosen: str | None = None) -> Pick:
    repo = Path(repo)
    available = choices(repo)
    if not available:
        return Pick(None, False, "No installed agent has a read-only mode, so chat can't answer.")

    from whyline.relaychat import settings

    wanted = chosen or settings.load(repo).agent
    if wanted and wanted in available:
        return Pick(wanted, False, f"{wanted} was chosen for chat.")

    try:
        roles = _relay_ops().current_roles(repo)
    except Exception:
        roles = {}
    try:
        backup = list(_relay_ops().read_backup(repo))
    except Exception:
        backup = []
    working = _working_agent(repo, roles)
    for name in backup:
        if name in available and name != working:
            return Pick(name, False, f"{name} is next in the backup chain and isn't working on the relay.")

    reviewer = roles.get("reviewer")
    if isinstance(reviewer, str) and reviewer in available:
        return Pick(reviewer, True,
                    f"No spare agent was found, so {reviewer} (the reviewer) answers and shares its quota.")
    return Pick(None, False, "No agent with a read-only mode is configured for chat.")
