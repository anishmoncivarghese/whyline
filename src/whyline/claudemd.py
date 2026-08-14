"""Claude Code shim for importing the canonical AGENTS.md instructions."""

from __future__ import annotations

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


def install(path: Path) -> str:
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        has_import = _imports_agents(existing)
        has_guidance = BEGIN in existing and END in existing
        if has_import and has_guidance:
            return "already-present"
        separator = "" if existing.endswith("\n") else "\n"
        addition = GUIDANCE if has_import else SHIM
        path.write_text(existing + separator + "\n" + addition, encoding="utf-8")
        return "installed"
    path.write_text(SHIM, encoding="utf-8")
    return "installed"
