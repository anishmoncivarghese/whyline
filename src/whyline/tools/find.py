"""`What should the agent be able to do?`: one search over connectors already added,
the catalogue, the skill library, fetched skill sources and, only when asked, the
public registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from whyline.tools import catalogue, mcp_config, skill_sources, skills

PER_KIND = 5
KINDS = ("connector", "catalogue", "skill", "remote-skill", "registry")
NOTHING = "Nothing found. You can make a tool for it."


@dataclass(frozen=True)
class Hit:
    kind: str  # one of KINDS
    title: str
    about: str
    ref: str  # connector name, catalogue name, skill ref, "source:name", registry name
    item: object = field(default=None, compare=False, repr=False)  # the entry behind the hit


def _all(words: list[str], *parts: str) -> bool:
    hay = " ".join(parts).lower()
    return all(w in hay for w in words)


def match(text: str, *, registry_search: Callable[[str], list] | None = None,
          root: Path | None = None) -> list[Hit]:
    """Hits grouped by kind in the order of KINDS, at most PER_KIND of each. Every word
    must match. ``registry_search`` is only called when it is given."""
    words = text.lower().split()
    if not words:
        return []
    hits: list[Hit] = []

    connectors = []
    for name, server in sorted(mcp_config.load().items()):
        if _all(words, name, *(f"{t.name} {t.description}" for t in server.tools)):
            tools = ", ".join(t.name for t in server.tools[:4])
            connectors.append(Hit("connector", name, tools or "not tested yet", name, server))
    hits += connectors[:PER_KIND]

    hits += [Hit("catalogue", e.title, e.about, e.name, e)
             for e in catalogue.search(text)][:PER_KIND]

    library = [Hit("skill", s.name, s.description, s.ref, s)
               for s in skills.find(root) if not s.broken
               and _all(words, s.name, s.description)]
    hits += library[:PER_KIND]

    hits += [Hit("remote-skill", e.name, e.description, f"{e.source}:{e.name}", e)
             for e in skill_sources.search(text)][:PER_KIND]

    if registry_search is not None:
        hits += [Hit("registry", e.title, e.about, e.name, e)
                 for e in registry_search(text) if not e.refused][:PER_KIND]
    return hits
