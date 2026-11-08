"""Document templates: the built-in section lists, and per-repository overrides."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

OVERRIDE_DIR = ".whyline/sdlc/templates"

# Document kind -> template name. The spec kind is size-dependent (see template_for).
_NAMES = {
    "prd": "prd",
    "spec": "spec",
    "design": "design",
    "build-record": "build-record",
}
_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^##[ \t]+(.+?)[ \t#]*$")


def template_name(kind: str, size: str) -> str:
    if kind == "spec" and _size_value(size) == "small":
        return "short-spec"
    if kind in _NAMES:
        return _NAMES[kind]
    raise ValueError(f"No template for document kind {kind!r}.")


def template_for(root: Path, kind: str, size: str) -> str:
    """The override at `.whyline/sdlc/templates/<name>.md` when it exists, else the built-in."""
    name = template_name(kind, size)
    override = Path(root) / OVERRIDE_DIR / f"{name}.md"
    if override.is_file():
        return override.read_text(encoding="utf-8")
    return builtin(name)


def builtin(name: str) -> str:
    return (
        resources.files("whyline.sdlc")
        .joinpath("templates", f"{name}.md")
        .read_text(encoding="utf-8")
    )


def sections(text: str) -> list[str]:
    """The `##` headings in order, ignoring any inside fenced code."""
    found: list[str] = []
    fence = ""
    for line in text.splitlines():
        m = _FENCE.match(line)
        if m:
            marker = m.group(1)
            if not fence:
                fence = marker
            elif marker == fence:
                fence = ""
            continue
        if fence:
            continue
        h = _HEADING.match(line)
        if h:
            found.append(h.group(1))
    return found


def _size_value(size: object) -> str:
    return str(getattr(size, "value", size))
