from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from whyline.security import deps
from whyline.security.lockfiles import NPM, PYPI, Dependency

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def dep(name="requests", version="2.0.0", eco=PYPI, public=True):
    return Dependency(name, version, eco, "uv.lock", public)


class FakeOSV:
    def __init__(self, vulns=None, hits=None, fail=False):
        self.vulns = vulns or {}
        self.hits = hits or {}  # package name -> [vuln ids]
        self.fail = fail
        self.calls = []

    def __call__(self, method, url, body, timeout):
        self.calls.append((method, url, body, timeout))
        if self.fail:
            raise OSError("down")
        if url == deps.BATCH_URL:
            return {
                "results": [
                    {"vulns": [{"id": i} for i in self.hits.get(q["package"]["name"], [])]}
                    for q in body["queries"]
                ]
            }
        return self.vulns[url.rsplit("/", 1)[1]]

    def gets(self):
        return [c for c in self.calls if c[0] == "GET"]

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]


def vuln(vid="GHSA-1", **extra):
    return {
        "id": vid,
        "summary": "bad thing",
        "affected": [
            {
                "package": {"name": "requests", "ecosystem": "PyPI"},
                "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.5.0"}]}],
            }
        ],
        **extra,
    }


def run(tmp_path, items, osv, now=NOW):
    return deps.check(items, fetch=osv, cache_dir=tmp_path / "cache", now=now)


def test_vulnerable_and_clean_package(tmp_path):
    osv = FakeOSV(vulns={"GHSA-1": vuln(database_specific={"severity": "HIGH"})}, hits={"requests": ["GHSA-1"]})
    report = run(tmp_path, [dep(), dep("flask", "3.0.0")], osv)
    assert report.error == ""
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.kind == "dependency"
    assert finding.rule == "GHSA-1"
    assert finding.severity == "high"
    assert finding.path == "uv.lock"
    assert finding.fix_hint == "upgrade requests to 2.5.0"
    assert finding.fingerprint
    method, url, body, timeout = osv.posts()[0]
    assert url == "https://api.osv.dev/v1/querybatch" and timeout == 20
    assert body["queries"][0] == {"package": {"name": "requests", "ecosystem": "PyPI"}, "version": "2.0.0"}
    assert osv.gets()[0][1] == "https://api.osv.dev/v1/vulns/GHSA-1"
    assert osv.gets()[0][3] == 20


def test_chunks_of_500(tmp_path):
    items = [dep(f"p{i}", "1.0.0") for i in range(1201)]
    osv = FakeOSV()
    report = run(tmp_path, items, osv)
    assert [len(c[2]["queries"]) for c in osv.posts()] == [500, 500, 201]
    assert report.findings == []


def test_cache_hit_and_expiry(tmp_path):
    osv = FakeOSV(vulns={"GHSA-1": vuln()}, hits={"requests": ["GHSA-1"]})
    run(tmp_path, [dep()], osv)
    assert len(osv.gets()) == 1
    assert (tmp_path / "cache" / "GHSA-1.json").exists()
    run(tmp_path, [dep()], osv, now=NOW + timedelta(hours=23))
    assert len(osv.gets()) == 1
    run(tmp_path, [dep()], osv, now=NOW + timedelta(hours=25))
    assert len(osv.gets()) == 2


def test_each_vuln_fetched_once_for_many_packages(tmp_path):
    osv = FakeOSV(vulns={"GHSA-1": vuln()}, hits={"a": ["GHSA-1"], "b": ["GHSA-1"]})
    report = run(tmp_path, [dep("a"), dep("b")], osv)
    assert len(osv.gets()) == 1
    assert len(report.findings) == 2


def test_severity_from_database_specific(tmp_path):
    cases = {"CRITICAL": "critical", "HIGH": "high", "MODERATE": "medium", "LOW": "low"}
    for label, expected in cases.items():
        assert deps.severity_of({"database_specific": {"severity": label}}) == expected


def test_database_specific_beats_cvss():
    v = {
        "database_specific": {"severity": "LOW"},
        "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
    }
    assert deps.severity_of(v) == "low"


def test_severity_from_cvss_vector():
    def of(vector):
        return deps.severity_of({"severity": [{"type": "CVSS_V3", "score": vector}]})

    assert deps.cvss3_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") == 9.8
    assert deps.cvss3_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N") == 6.1
    assert deps.cvss3_score("CVSS:3.0/AV:L/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N") == 3.3
    assert deps.cvss3_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N") == 0.0
    assert of("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") == "critical"
    assert of("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N") == "high"
    assert of("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N") == "medium"
    assert of("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N") == "low"


def test_severity_unknown():
    assert deps.severity_of({}) == "unknown"
    assert deps.severity_of({"severity": [{"type": "CVSS_V4", "score": "CVSS:4.0/AV:N"}]}) == "unknown"
    assert deps.severity_of({"severity": [{"type": "CVSS_V3", "score": "garbage"}]}) == "unknown"
    assert deps.severity_of({"database_specific": {"severity": "weird"}}) == "unknown"


def test_fix_hints():
    assert deps.fix_hint(dep(), vuln()) == "upgrade requests to 2.5.0"
    # PyPI names compare normalised
    assert deps.fix_hint(dep("My_Pkg"), {"affected": [_affected("my-pkg", "PyPI", "1.2")]}) == "upgrade My_Pkg to 1.2"
    # a different package's fix is not ours
    assert deps.fix_hint(dep(), {"affected": [_affected("other", "PyPI", "9.9")]}) == "no fixed version yet"
    assert deps.fix_hint(dep("left-pad", "1.0.0", NPM), {"affected": [_affected("left-pad", "npm", "1.3.0")]}) == (
        "upgrade left-pad to 1.3.0"
    )
    assert deps.fix_hint(dep(), {"id": "X"}) == "no fixed version yet"
    no_fix = {"affected": [{"package": {"name": "requests", "ecosystem": "PyPI"}, "ranges": [
        {"events": [{"introduced": "0"}]}]}]}
    assert deps.fix_hint(dep(), no_fix) == "no fixed version yet"


def _affected(name, eco, fixed):
    return {"package": {"name": name, "ecosystem": eco}, "ranges": [{"events": [{"introduced": "0"}, {"fixed": fixed}]}]}


def test_private_dep_never_sent(tmp_path):
    private = dep("secret-internal-pkg", "0.0.1", public=False)
    osv = FakeOSV(vulns={"GHSA-1": vuln()}, hits={"requests": ["GHSA-1"]})
    report = run(tmp_path, [private, dep()], osv)
    assert report.not_checked == [private]
    for _, url, body, _ in osv.calls:
        assert "secret-internal-pkg" not in url
        assert "secret-internal-pkg" not in json.dumps(body)


def test_only_private_makes_no_request(tmp_path):
    osv = FakeOSV()
    report = run(tmp_path, [dep(public=False)], osv)
    assert osv.calls == []
    assert report.error == "" and len(report.not_checked) == 1


def test_network_error(tmp_path):
    report = run(tmp_path, [dep()], FakeOSV(fail=True))
    assert report.error == "could not reach OSV.dev"
    assert report.findings == []


def test_network_error_on_vuln_fetch_returns_no_findings(tmp_path):
    class Flaky(FakeOSV):
        def __call__(self, method, url, body, timeout):
            if method == "GET":
                raise TimeoutError("slow")
            return super().__call__(method, url, body, timeout)

    report = run(tmp_path, [dep()], Flaky(hits={"requests": ["GHSA-1"]}))
    assert report.error == "could not reach OSV.dev"
    assert report.findings == []
