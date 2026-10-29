"""Posting guard and preference filters for fetched job postings (JOB-10).

The shared rules (HTML comments, hidden elements, zero-width and bidi
characters, whitespace runs, AI-addressing lines) come from
``whyline.ideas.guard``; this module only re-labels the flag marker.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from whyline.ideas import guard as _shared

from .fetch import Posting

FLAG_PREFIX = "[flagged by whyline] "
_SHARED_PREFIX = "[flagged] "


def clean(text: str) -> tuple[str, list[str]]:
    """Return (cleaned_text, flagged_lines) for untrusted posting text."""
    cleaned, flagged = _shared.clean(text)
    lines = [
        FLAG_PREFIX + line[len(_SHARED_PREFIX):] if line.startswith(_SHARED_PREFIX) else line
        for line in cleaned.splitlines()
    ]
    return "\n".join(lines), flagged


@dataclass(frozen=True)
class Decision:
    keep: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.keep


def _words(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v.strip().lower() for v in value if isinstance(v, str) and v.strip()]


def match(posting: Posting, prefs: Mapping[str, Any]) -> Decision:
    """Apply remote/location, role keyword and deal-breaker rules."""
    mode = prefs.get("remote", "any")
    if mode == "remote" and posting.remote is False:
        return Decision(False, "not remote")
    if mode == "onsite" and posting.remote is True:
        return Decision(False, "remote role but onsite wanted")

    locations = _words(prefs.get("locations"))
    where = posting.location.lower()
    if locations and where and not (posting.remote is True and mode != "onsite"):
        if not any(loc in where for loc in locations):
            return Decision(False, f"location: {posting.location}")

    roles = _words(prefs.get("roles"))
    title = posting.title.lower()
    if roles and not any(role in title for role in roles):
        return Decision(False, "title matches no role")

    haystack = " ".join(
        (posting.title, posting.company, posting.location, posting.text)
    ).lower()
    for word in _words(prefs.get("deal_breakers")):
        if word in haystack:
            return Decision(False, f"deal breaker: {word}")

    return Decision(True)
