"""Review lenses: short reviewer briefs, which ones apply, and parsing what they report."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

OVERRIDE_DIR = ".whyline/sdlc/lenses"

LENSES = ("zoom-out", "comprehension", "design-critic", "codebase-fit", "readiness")

# (size, kind) -> lens names. Anything not listed (such as build-record) gets none.
_TABLE: dict[tuple[str, str], list[str]] = {
    ("small", "spec"): ["zoom-out", "readiness"],
    ("small", "plan"): ["readiness"],
    ("feature", "brainstorm"): ["zoom-out"],
    ("feature", "prd"): ["zoom-out", "comprehension"],
    ("feature", "spec"): ["comprehension", "codebase-fit", "design-critic"],
    ("feature", "plan"): ["readiness", "zoom-out"],
    ("large", "brainstorm"): ["zoom-out"],
    ("large", "prd"): ["zoom-out", "comprehension"],
    ("large", "design"): list(LENSES),
    ("large", "plan"): ["readiness", "zoom-out", "codebase-fit"],
}

_FENCE = re.compile(r"^\s*(```|~~~)")
_FINDING = re.compile(
    r"^\s*[-*]\s*\[(blocker|major|nit)\]\s*(.+?)\s+—\s+(.+?)\s+—\s+(.+?)\s*$",
    re.IGNORECASE,
)
_NONE = re.compile(r"^\s*No findings\.\s*$")


@dataclass(frozen=True)
class Finding:
    lens: str
    severity: str
    section: str
    problem: str
    fix: str


def lenses_for(size: object, kind: str) -> list[str]:
    size_name = str(getattr(size, "value", size))
    return list(_TABLE.get((size_name, kind), []))


def lens_text(root: Path, name: str) -> str:
    """The override at `.whyline/sdlc/lenses/<name>.md` when it exists, else the built-in."""
    if name not in LENSES:
        raise ValueError(f"No review lens named {name!r}.")
    override = Path(root) / OVERRIDE_DIR / f"{name}.md"
    if override.is_file():
        return override.read_text(encoding="utf-8")
    return (
        resources.files("whyline.sdlc")
        .joinpath("lenses", f"{name}.md")
        .read_text(encoding="utf-8")
    )


def parse_findings(lens: str, text: str) -> list[Finding] | None:
    """Findings in the reply, [] for `No findings.`, or None when it has neither."""
    found: list[Finding] = []
    said_none = False
    fence = ""
    for line in text.splitlines():
        m = _FENCE.match(line)
        if m:
            marker = m.group(1)
            if not fence:
                fence = marker
            elif fence == marker:
                fence = ""
            continue
        if fence:
            continue
        if _NONE.match(line):
            said_none = True
            continue
        f = _FINDING.match(line)
        if f:
            found.append(Finding(lens, f.group(1).lower(), f.group(2), f.group(3), f.group(4)))
    if found:
        return found
    return [] if said_none else None
