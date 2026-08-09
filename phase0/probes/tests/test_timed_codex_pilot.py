from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
HARNESS = PROJECT_ROOT / "phase0" / "probes" / "timed_codex_pilot.py"


class TimedCodexPilotTests(unittest.TestCase):
    def make_fake_codex(self, directory: Path, body: str) -> Path:
        executable = directory / "codex"
        executable.write_text(
            f"#!{sys.executable}\n" + textwrap.dedent(body),
            encoding="utf-8",
        )
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        return executable

    def run_harness(self, fake_directory: Path, timeout: int = 5) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PATH"] = f"{fake_directory}{os.pathsep}{environment.get('PATH', '')}"
        return subprocess.run(
            [
                sys.executable,
                str(HARNESS),
                "cache_ttl",
                "cold",
                "--timeout",
                str(timeout),
                "--confirm-external-synthetic-data",
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_collects_timing_and_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.make_fake_codex(
                directory,
                """
                import json
                import sys
                events = [
                    {"type": "thread.started"},
                    {"type": "item.completed", "item": {"type": "agent_message"}},
                    {"type": "item.started", "item": {"type": "file_change"}},
                    {"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 4}},
                ]
                for event in events:
                    print(json.dumps(event), flush=True)
                sys.exit(0)
                """,
            )
            result = self.run_harness(directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertFalse(summary["timed_out"])
            self.assertEqual(summary["usage"]["input_tokens"], 10)
            self.assertIsNotNone(summary["first_agent_message_ms"])
            self.assertIsNotNone(summary["first_file_change_ms"])

    def test_terminates_silent_process_at_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.make_fake_codex(
                directory,
                """
                import time
                time.sleep(5)
                """,
            )
            result = self.run_harness(directory, timeout=1)
            self.assertNotEqual(result.returncode, 0)
            summary = json.loads(result.stdout)
            self.assertTrue(summary["timed_out"])
            self.assertLess(summary["elapsed_ms"], 4_000)


if __name__ == "__main__":
    unittest.main()
