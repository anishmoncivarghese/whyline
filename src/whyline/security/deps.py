"""Check pinned dependencies against OSV.dev.

Only public packages are ever sent. Network access goes through an injected
`fetch(method, url, body, timeout)` that returns parsed JSON and raises
`OSError` (or `ValueError` for a bad body) on failure, so tests never touch the
network. Each vulnerability record is cached on disk for 24 hours.
"""

from __future__ import annotations

import json
import math
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from whyline.security.findings import Finding, make_fingerprint
from whyline.security.lockfiles import PYPI, Dependency, normalize_pypi

BATCH_URL = "https://api.osv.dev/v1/querybatch"
VULN_URL = "https://api.osv.dev/v1/vulns/"
CHUNK_SIZE = 500
TIMEOUT = 20
CACHE_SECONDS = 24 * 60 * 60
NETWORK_ERROR = "could not reach OSV.dev"

Fetch = Callable[[str, str, "dict[str, Any] | None", float], Any]

_GHSA = {"critical": "critical", "high": "high", "moderate": "medium", "medium": "medium", "low": "low"}
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


@dataclass
class DepReport:
    findings: list[Finding] = field(default_factory=list)
    not_checked: list[Dependency] = field(default_factory=list)
    error: str = ""


def urllib_fetch(method: str, url: str, body: dict[str, Any] | None, timeout: float) -> Any:
    """The real network fetch; raises OSError (URLError, timeouts) on failure."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URLs
        return json.loads(response.read().decode("utf-8"))


def check(
    deps: list[Dependency],
    *,
    fetch: Fetch,
    cache_dir: str | Path,
    now: datetime,
) -> DepReport:
    public = [d for d in deps if d.public]
    report = DepReport(not_checked=[d for d in deps if not d.public])
    if not public:
        return report
    cache = Path(cache_dir)
    try:
        hits = _query(public, fetch)
        vulns: dict[str, dict[str, Any]] = {}
        for vuln_id in sorted({i for ids in hits for i in ids}):
            vulns[vuln_id] = _load_vuln(vuln_id, fetch, cache, now)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        report.error = NETWORK_ERROR
        return report
    for dep, ids in zip(public, hits):
        for vuln_id in ids:
            report.findings.append(_finding(dep, vulns[vuln_id]))
    return report


def _query(public: list[Dependency], fetch: Fetch) -> list[list[str]]:
    hits: list[list[str]] = []
    for start in range(0, len(public), CHUNK_SIZE):
        chunk = public[start : start + CHUNK_SIZE]
        queries = [
            {"package": {"name": d.name, "ecosystem": d.ecosystem}, "version": d.version} for d in chunk
        ]
        data = fetch("POST", BATCH_URL, {"queries": queries}, TIMEOUT)
        results = data["results"]
        if len(results) != len(chunk):
            raise ValueError("OSV returned a different number of results than queries")
        for result in results:
            hits.append([v["id"] for v in (result.get("vulns") or [])])
    return hits


def _cache_path(cache: Path, vuln_id: str) -> Path:
    return cache / f"{_SAFE_ID.sub('_', vuln_id)}.json"


def _load_vuln(vuln_id: str, fetch: Fetch, cache: Path, now: datetime) -> dict[str, Any]:
    path = _cache_path(cache, vuln_id)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        age = now.timestamp() - float(cached["fetched_at"])
        if 0 <= age < CACHE_SECONDS and isinstance(cached["vuln"], dict):
            return cached["vuln"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    vuln = fetch("GET", VULN_URL + vuln_id, None, TIMEOUT)
    if not isinstance(vuln, dict):
        raise ValueError("OSV returned a non-object vulnerability")
    try:
        cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched_at": now.timestamp(), "vuln": vuln}), encoding="utf-8")
    except OSError:
        pass  # a cache that cannot be written only costs a refetch
    return vuln


def _finding(dep: Dependency, vuln: dict[str, Any]) -> Finding:
    vuln_id = str(vuln.get("id", ""))
    title = str(vuln.get("summary") or vuln_id)
    return Finding(
        kind="dependency",
        rule=vuln_id,
        title=f"{dep.name} {dep.version}: {title}",
        severity=severity_of(vuln),
        path=dep.source_file,
        preview=f"{dep.name}=={dep.version}",
        fingerprint=make_fingerprint("dependency", vuln_id, f"{dep.ecosystem}:{dep.name}@{dep.version}"),
        fix_hint=fix_hint(dep, vuln),
    )


def severity_of(vuln: dict[str, Any]) -> str:
    database = vuln.get("database_specific")
    label = database.get("severity") if isinstance(database, dict) else None
    if isinstance(label, str) and label.lower() in _GHSA:
        return _GHSA[label.lower()]
    for entry in vuln.get("severity") or []:
        if not isinstance(entry, dict):
            continue
        score = cvss3_score(str(entry.get("score", "")))
        if score is not None:
            return _band(score)
    return "unknown"


def _band(score: float) -> str:
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low"


_AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}
_AC = {"L": 0.77, "H": 0.44}
_UI = {"N": 0.85, "R": 0.62}
_CIA = {"H": 0.56, "L": 0.22, "N": 0.0}
_PR_UNCHANGED = {"N": 0.85, "L": 0.62, "H": 0.27}
_PR_CHANGED = {"N": 0.85, "L": 0.68, "H": 0.5}


def _roundup(value: float) -> float:
    scaled = round(value * 100000)
    if scaled % 10000 == 0:
        return scaled / 100000.0
    return (math.floor(scaled / 10000) + 1) / 10.0


def cvss3_score(vector: str) -> float | None:
    """CVSS v3.x base score from a vector string, or None if it is not v3."""
    if not vector.startswith(("CVSS:3.0/", "CVSS:3.1/")):
        return None
    try:
        metrics = dict(part.split(":", 1) for part in vector.split("/")[1:])
        changed = {"U": False, "C": True}[metrics["S"]]
        pr = (_PR_CHANGED if changed else _PR_UNCHANGED)[metrics["PR"]]
        impact_base = 1 - (1 - _CIA[metrics["C"]]) * (1 - _CIA[metrics["I"]]) * (1 - _CIA[metrics["A"]])
        exploit = 8.22 * _AV[metrics["AV"]] * _AC[metrics["AC"]] * pr * _UI[metrics["UI"]]
    except (KeyError, ValueError):
        return None
    if changed:
        impact = 7.52 * (impact_base - 0.029) - 3.25 * (impact_base - 0.02) ** 15
    else:
        impact = 6.42 * impact_base
    if impact <= 0:
        return 0.0
    total = impact + exploit
    return _roundup(min(1.08 * total, 10) if changed else min(total, 10))


def fix_hint(dep: Dependency, vuln: dict[str, Any]) -> str:
    for affected in vuln.get("affected") or []:
        package = affected.get("package") or {}
        if not _same_package(dep, package):
            continue
        for rng in affected.get("ranges") or []:
            for event in rng.get("events") or []:
                fixed = event.get("fixed")
                if fixed:
                    return f"upgrade {dep.name} to {fixed}"
    return "no fixed version yet"


def _same_package(dep: Dependency, package: dict[str, Any]) -> bool:
    if package.get("ecosystem") != dep.ecosystem:
        return False
    name = str(package.get("name", ""))
    if dep.ecosystem == PYPI:
        return normalize_pypi(name) == normalize_pypi(dep.name)
    return name == dep.name
