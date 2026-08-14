"""The canonical shared instruction that asks agents to record reasoning."""

from __future__ import annotations

from pathlib import Path

BEGIN = "<!-- whyline:begin -->"
END = "<!-- whyline:end -->"

INSTRUCTION = f"""{BEGIN}
## Recording decisions

After completing any non-trivial change, record the reasoning:

    whyline note "<one-line decision>" \\
      --because "<why this choice>" \\
      --rejected "<option>: <why not>" \\
      --file <path>

Record only genuine choices a future reader would wonder about. Skip typos,
formatting and renames. `--rejected` is repeatable. Do not ask permission.
Store shared project instructions here, but record evolving decision history
through whyline rather than appending it to AGENTS.md.
{END}
"""


def install(path: Path) -> str:
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if BEGIN in existing and END in existing:
            return "already-present"
        separator = "" if existing.endswith("\n") else "\n"
        path.write_text(existing + separator + "\n" + INSTRUCTION, encoding="utf-8")
        return "installed"
    path.write_text(INSTRUCTION, encoding="utf-8")
    return "installed"
