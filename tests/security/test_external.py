import json
import subprocess
from pathlib import Path

import pytest

from whyline.security import external
from whyline.security.findings import Finding

FAKE_KEY = "AKIA" + "IOSFODNN7" + "EXAMPLE"


def gitleaks_report() -> list[dict]:
    return [
        {
            "RuleID": "aws-access-token",
            "Description": "AWS access token",
            "File": "app/config.py",
            "StartLine": 12,
            "Commit": "abc123",
            "Secret": "REDACTED",
            "Match": "REDACTED",
            "Fingerprint": "abc123:app/config.py:aws-access-token:12",
        }
    ]


def osv_report() -> dict:
    return {
        "results": [
            {
                "source": {"path": "/repo/requirements.txt", "type": "lockfile"},
                "packages": [
                    {
                        "package": {"name": "django", "version": "3.0.0", "ecosystem": "PyPI"},
                        "vulnerabilities": [
                            {
                                "id": "GHSA-aaaa-bbbb-cccc",
                                "summary": "SQL injection",
                                "database_specific": {"severity": "HIGH"},
                            }
                        ],
                    }
                ],
            }
        ]
    }


class FakeRun:
    """Stands in for subprocess.run: writes the report where --report-path/--output says."""

    def __init__(self, payload=None, returncode=0, raises=None):
        self.payload = payload
        self.returncode = returncode
        self.raises = raises
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        assert kwargs["timeout"] == 60
        if self.raises:
            raise self.raises
        for flag in ("--report-path", "--output"):
            if flag in command and self.payload is not None:
                Path(command[command.index(flag) + 1]).write_text(json.dumps(self.payload))
        return subprocess.CompletedProcess(command, self.returncode, "", "")


def test_available_maps_installed_tools():
    paths = {"gitleaks": "/bin/gitleaks", "osv-scanner": "/bin/osv"}
    assert external.available(paths.get) == paths
    assert external.available(lambda name: None) == {}


@pytest.mark.parametrize("tool", ["gitleaks", "betterleaks"])
def test_scan_secrets_parses_report_without_a_value(tool, tmp_path):
    run = FakeRun(gitleaks_report())
    findings, warnings = external.scan_secrets(tool, f"/bin/{tool}", tmp_path, log_range="main..HEAD", run=run)
    assert warnings == []
    (finding,) = findings
    assert finding.source == tool
    assert finding.kind == "secret"
    assert finding.rule == "aws-access-token"
    assert finding.path == "app/config.py"
    assert finding.line == 12
    assert finding.commit == "abc123"
    assert finding.preview == f"(redacted by {tool})"
    assert "REDACTED" not in finding.preview
    command = run.commands[0]
    assert command[:2] == [f"/bin/{tool}", "git"]
    assert command[command.index("--log-opts") + 1] == "main..HEAD"


def test_dir_mode_for_paths(tmp_path):
    run = FakeRun([])
    external.scan_secrets("gitleaks", "gitleaks", tmp_path, path="src", run=run)
    assert run.commands[0][:3] == ["gitleaks", "dir", "src"]


@pytest.mark.parametrize("kwargs", [{"log_range": "a..b"}, {"path": "src"}, {}])
def test_redact_always_passed(kwargs, tmp_path):
    run = FakeRun([])
    external.scan_secrets("gitleaks", "gitleaks", tmp_path, run=run, **kwargs)
    assert "--redact" in run.commands[0]
    assert "--report-path" in run.commands[0]


def test_scan_deps_parses_osv(tmp_path):
    run = FakeRun(osv_report(), returncode=1)  # osv-scanner exits 1 when it finds vulnerabilities
    findings, warnings = external.scan_deps("/bin/osv-scanner", tmp_path, run=run)
    assert warnings == []
    (finding,) = findings
    assert finding.source == "osv-scanner"
    assert finding.kind == "dependency"
    assert finding.rule == "GHSA-aaaa-bbbb-cccc"
    assert finding.severity == "high"
    assert finding.path == "/repo/requirements.txt"
    assert finding.preview == "django==3.0.0"
    assert run.commands[0][:5] == ["/bin/osv-scanner", "scan", "source", "-r", "."]
    assert "json" in run.commands[0]


def test_osv_no_packages_is_not_a_warning(tmp_path):
    assert external.scan_deps("osv-scanner", tmp_path, run=FakeRun(returncode=128)) == ([], [])


@pytest.mark.parametrize(
    "run",
    [
        FakeRun(returncode=2),
        FakeRun(raises=subprocess.TimeoutExpired("gitleaks", 60)),
        FakeRun(raises=FileNotFoundError("gone")),
    ],
)
def test_tool_crash_becomes_a_warning(run, tmp_path):
    findings, warnings = external.scan_secrets("gitleaks", "gitleaks", tmp_path, run=run)
    assert findings == []
    assert len(warnings) == 1
    assert warnings[0].startswith("gitleaks ")


def test_unreadable_report_becomes_a_warning(tmp_path):
    class BadRun(FakeRun):
        def __call__(self, command, **kwargs):
            Path(command[command.index("--report-path") + 1]).write_text("{not json")
            return subprocess.CompletedProcess(command, 0, "", "")

    findings, warnings = external.scan_secrets("gitleaks", "gitleaks", tmp_path, run=BadRun())
    assert findings == []
    assert "unreadable" in warnings[0]


def test_missing_report_means_no_findings(tmp_path):
    assert external.scan_secrets("gitleaks", "gitleaks", tmp_path, run=FakeRun()) == ([], [])


def _secret(rule, path="a.py", line=3, source="builtin", preview="AK****LE"):
    return Finding(kind="secret", rule=rule, title=rule, path=path, line=line, preview=preview, source=source)


def test_merge_dedupes_and_prefers_external_rule_name():
    builtin = [_secret("aws_access_key", preview=FAKE_KEY[:2] + "****" + FAKE_KEY[-2:]), _secret("slack-token", line=9)]
    ext = [_secret("aws-access-token", source="gitleaks", preview="(redacted by gitleaks)")]
    merged = external.merge(builtin, ext)
    assert len(merged) == 2
    by_line = {f.line: f for f in merged}
    assert by_line[3].rule == "aws-access-token"
    assert by_line[3].source == "gitleaks"
    assert by_line[9].rule == "slack-token"


def test_merge_keeps_different_paths_and_families():
    builtin = [_secret("aws_key", path="a.py")]
    ext = [_secret("aws-token", path="b.py", source="gitleaks"), _secret("github-pat", path="a.py", source="gitleaks")]
    assert len(external.merge(builtin, ext)) == 3


def test_merge_keeps_dependencies_apart_by_id():
    def dep(vuln):
        return Finding(kind="dependency", rule=vuln, title=vuln, path="req.txt")

    merged = external.merge([dep("GHSA-1")], [dep("GHSA-2"), dep("GHSA-1")])
    assert sorted(f.rule for f in merged) == ["GHSA-1", "GHSA-2"]
