"""The canonical shared instruction that asks agents to read and record reasoning.

Both halves matter. Recording alone produces a decision log nobody consults; the
read instruction is what turns it into a handoff. 0.1.0 shipped with only the
write half — an omission found when the project's own author could not tell from
the docs how switching agents worked.

The wording is not arbitrary. `docs/superpowers/specs/2026-08-16-handover-observations.md`
records a controlled observation: a *declarative* instruction ("history lives in
whyline rather than here") was ignored unprompted through a six-hour session,
while an *imperative* one with a trigger, an exact command and pre-authorisation
fired twice without a reminder. An instruction fires when it states **when**,
gives the **exact command**, **pre-authorises**, and is **verifiable**. Every
directive below carries all four. Do not soften them into descriptions.
"""

from __future__ import annotations

import re
from pathlib import Path

BEGIN = "<!-- whyline:begin -->"
END = "<!-- whyline:end -->"

INSTRUCTION = f"""{BEGIN}
## Project history

At the start of a session, before touching code, run:

    whyline brief

That prints what previous agents decided and rejected on this project.
Do not ask permission. If it reports nothing recorded, say so in your first
message, so the human knows the history is empty rather than merely unread.

## Recording decisions

After completing any non-trivial change, record the reasoning:

    whyline note "<one-line decision>" \\
      --because "<why this choice>" \\
      --rejected "<option>: <why not>" \\
      --file <path>

Record only genuine choices a future reader would wonder about. Skip typos,
formatting and renames. `--rejected` is repeatable. Do not ask permission.
{END}
"""

_BLOCK = re.compile(
    re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.DOTALL
)


def install(path: Path) -> str:
    """Add or update the instruction block. Returns what happened.

    Upgrading matters: instructions improve, and a block written by an older
    version would otherwise be frozen forever. 0.1.0 returned "already-present"
    on any existing block, so the read instruction added later could never have
    reached a repository that had already run `init` — including this project's
    own. Only the marked region is touched; everything the human wrote around it
    is preserved byte for byte.
    """
    if not path.exists():
        path.write_text(INSTRUCTION, encoding="utf-8")
        return "installed"

    existing = path.read_text(encoding="utf-8")
    match = _BLOCK.search(existing)
    if match is None:
        separator = "" if existing.endswith("\n") else "\n"
        path.write_text(existing + separator + "\n" + INSTRUCTION, encoding="utf-8")
        return "installed"

    if match.group(0).strip() == INSTRUCTION.strip():
        return "already-present"

    path.write_text(existing.replace(match.group(0), INSTRUCTION), encoding="utf-8")
    return "upgraded"
