"""The shape of one security finding, plus masking and fingerprints."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

KINDS = ("secret", "dependency", "contents", "audit")
SEVERITIES = ("critical", "high", "medium", "low", "unknown")
SOURCES = ("builtin", "gitleaks", "betterleaks", "osv-scanner", "audit")

_MASK = "****"
_SHORT = 8


def mask(value: str) -> str:
    """Never show a whole secret: short values show nothing, long ones the
    first two and last two characters around `****`."""
    if len(value) <= _SHORT:
        return _MASK
    return f"{value[:2]}{_MASK}{value[-2:]}"


def make_fingerprint(kind: str, rule: str, path: str, value: str = "") -> str:
    """Stable id for a finding. The line is left out so moving code does not
    revive an allowed finding; the value is hashed so it is never stored."""
    digest = hashlib.sha256("\0".join((kind, rule, path, value)).encode("utf-8"))
    return digest.hexdigest()[:16]


@dataclass(frozen=True)
class Finding:
    kind: str
    rule: str
    title: str
    severity: str = "unknown"
    path: str = ""
    line: int = 0
    commit: str = ""
    preview: str = ""
    fingerprint: str = ""
    fix_hint: str = ""
    source: str = "builtin"
    legacy_fingerprint: str = ""

    def __post_init__(self) -> None:
        for name, value, allowed in (
            ("kind", self.kind, KINDS),
            ("severity", self.severity, SEVERITIES),
            ("source", self.source, SOURCES),
        ):
            if value not in allowed:
                raise ValueError(f"finding.{name} must be one of {', '.join(allowed)}, not {value!r}")
