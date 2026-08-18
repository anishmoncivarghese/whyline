"""Claude Code shim for importing the canonical AGENTS.md instructions."""

from __future__ import annotations

import re
from pathlib import Path

IMPORT = "@AGENTS.md"
BEGIN = "<!-- whyline:claude-guidance-begin -->"
END = "<!-- whyline:claude-guidance-end -->"

GUIDANCE = f"""{BEGIN}
AGENTS.md is the canonical source for shared project instructions.
Do not add shared project instructions, decisions, or session notes here.
{END}
"""

SHIM = f"{IMPORT}\n\n{GUIDANCE}"


def _imports_agents(text: str) -> bool:
    return any(line.strip() == IMPORT for line in text.splitlines())


_BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.DOTALL)


def install(path: Path) -> str:
    """Add or update the Claude shim. Returns what happened.

    Upgrades an outdated block rather than leaving it frozen, for the same reason
    as `agentsmd.install`: a block written by an older version would otherwise
    never receive an improved wording. Only the marked region is touched.
    """
    if not path.exists():
        path.write_text(SHIM, encoding="utf-8")
        return "installed"

    existing = path.read_text(encoding="utf-8")
    has_import = _imports_agents(existing)
    match = _BLOCK.search(existing)

    if match is not None and has_import:
        if match.group(0).strip() == GUIDANCE.strip():
            return "already-present"
        path.write_text(existing.replace(match.group(0), GUIDANCE), encoding="utf-8")
        return "upgraded"

    separator = "" if existing.endswith("\n") else "\n"
    if match is not None:
        # Guidance present but the @AGENTS.md import is missing: without it Claude
        # never reads the canonical instructions at all.
        updated = existing.replace(match.group(0), GUIDANCE)
        path.write_text(IMPORT + "\n\n" + updated, encoding="utf-8")
        return "upgraded"
    addition = GUIDANCE if has_import else SHIM
    path.write_text(existing + separator + "\n" + addition, encoding="utf-8")
    return "installed"
