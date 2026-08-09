#!/usr/bin/env python3
"""Phase 0 adapter capability probe.

Static mode is free and only invokes version/help commands. Live mode may consume
vendor quota and is deliberately opt-in. It uses a read-only prompt, never prints
the environment, and never supplies permission-bypass flags.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ProbeResult:
    adapter: str
    check: str
    command: list[str]
    exit_code: int | None
    elapsed_ms: int
    stdout_bytes: int
    stderr_bytes: int
    timed_out: bool
    stdout_preview: str
    stderr_preview: str


def run(adapter: str, check: str, command: list[str], cwd: Path, timeout: int) -> ProbeResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        return ProbeResult(
            adapter=adapter,
            check=check,
            command=command,
            exit_code=completed.returncode,
            elapsed_ms=round((time.monotonic() - started) * 1000),
            stdout_bytes=len(stdout.encode()),
            stderr_bytes=len(stderr.encode()),
            timed_out=False,
            stdout_preview=stdout[:500],
            stderr_preview=stderr[:500],
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
        return ProbeResult(
            adapter=adapter,
            check=check,
            command=command,
            exit_code=None,
            elapsed_ms=round((time.monotonic() - started) * 1000),
            stdout_bytes=len(stdout.encode()),
            stderr_bytes=len(stderr.encode()),
            timed_out=True,
            stdout_preview=stdout[:500],
            stderr_preview=stderr[:500],
        )


def command_path(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise SystemExit(f"Required CLI not found: {name}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Run read-only model calls; may consume quota")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="Trusted synthetic Git repository for live probes")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    cwd = args.cwd.resolve()
    if args.live and not (cwd / ".git").exists():
        raise SystemExit("Live probes require --cwd to be a synthetic Git repository root")

    claude = command_path("claude")
    codex = command_path("codex")
    commands: list[tuple[str, str, list[str]]] = [
        ("claude", "version", [claude, "--version"]),
        ("claude", "help", [claude, "--help"]),
        ("codex", "version", [codex, "--version"]),
        ("codex", "exec-help", [codex, "exec", "--help"]),
    ]

    if args.live:
        prompt = "Read the repository without modifying it. Reply with exactly: PROBE_OK"
        commands.extend(
            [
                (
                    "claude",
                    "live-read-only",
                    [claude, "--print", "--output-format", "json", "--permission-mode", "plan", prompt],
                ),
                (
                    "codex",
                    "live-read-only",
                    [codex, "exec", "--ephemeral", "--json", "--sandbox", "read-only", "--cd", str(cwd), prompt],
                ),
            ]
        )

    results = [run(adapter, check, command, cwd, args.timeout) for adapter, check, command in commands]
    json.dump([asdict(result) for result in results], sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 1 if any(result.exit_code not in (0,) or result.timed_out for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
