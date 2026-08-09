#!/usr/bin/env python3
"""Materialize every fixture and verify baseline and reference behavior."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


FIXTURES = {
    "cache_ttl": "cache.py",
    "webhook_dedupe": "webhooks.py",
    "config_reload": "config_store.py",
}


def test(repository: Path) -> tuple[int, int, str]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
        return 124, round((time.monotonic() - started) * 1000), stdout + stderr + "\nTIMEOUT"
    return result.returncode, round((time.monotonic() - started) * 1000), result.stdout + result.stderr


def main() -> int:
    fixture_root = Path(__file__).parent.resolve()
    results = []
    with tempfile.TemporaryDirectory(prefix="phase0-fixtures-") as temp:
        temp_root = Path(temp)
        for name, implementation in FIXTURES.items():
            source = fixture_root / name
            repository = temp_root / name
            shutil.copytree(source, repository, ignore=shutil.ignore_patterns("facilitator"))
            baseline_code, baseline_ms, baseline_output = test(repository)
            shutil.copy2(source / "facilitator" / "reference" / implementation, repository / implementation)
            reference_code, reference_ms, reference_output = test(repository)
            results.append(
                {
                    "fixture": name,
                    "baseline_failed_as_expected": baseline_code != 0,
                    "baseline_elapsed_ms": baseline_ms,
                    "baseline_summary": baseline_output.strip().splitlines()[-1],
                    "reference_passed": reference_code == 0,
                    "reference_elapsed_ms": reference_ms,
                    "reference_summary": reference_output.strip().splitlines()[-1],
                }
            )
    print(json.dumps(results, indent=2))
    return 0 if all(item["baseline_failed_as_expected"] and item["reference_passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
