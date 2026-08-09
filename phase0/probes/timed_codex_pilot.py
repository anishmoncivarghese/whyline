#!/usr/bin/env python3
"""Run one timestamped Codex pilot against a synthetic Phase 0 fixture.

This command transmits the selected synthetic fixture to Codex and may consume
substantial quota. It requires an explicit acknowledgement flag. Raw event text
is not persisted; the emitted summary contains timing, event types, usage, exit
status, and the resulting changed paths.
"""

from __future__ import annotations

import argparse
import json
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", choices=("cache_ttl", "webhook_dedupe", "config_reload"))
    parser.add_argument("condition", choices=("cold", "human", "structured"))
    parser.add_argument("--timeout", type=int, default=1_200)
    parser.add_argument(
        "--confirm-external-synthetic-data",
        action="store_true",
        help="Confirm the synthetic fixture may be sent to Codex and quota may be consumed",
    )
    args = parser.parse_args()
    if not args.confirm_external_synthetic_data:
        raise SystemExit("Refusing live call without --confirm-external-synthetic-data")

    codex = shutil.which("codex")
    if codex is None:
        raise SystemExit("Codex CLI not found")

    project_root = Path(__file__).resolve().parents[2]
    materializer = project_root / "phase0" / "fixtures" / "materialize.py"
    prompt = (
        "Complete the task in TASK.md. Inspect only this synthetic repository, "
        "implement the smallest correct change, and run the documented tests."
        if args.condition == "cold"
        else "Complete the task in TASK.md. A previous agent handoff is in HANDOFF.md. "
        "Inspect only this synthetic repository, implement the smallest correct change, "
        "and run the documented tests."
    )

    started = time.monotonic()
    event_counts: dict[str, int] = {}
    first_agent_message_ms: int | None = None
    first_file_change_ms: int | None = None
    usage: dict[str, Any] | None = None
    parse_errors = 0

    with tempfile.TemporaryDirectory(prefix="phase0-codex-pilot-") as temporary:
        repository = Path(temporary) / "repository"
        subprocess.run(
            [sys.executable, str(materializer), args.fixture, str(repository), "--condition", args.condition],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )
        command = [
            codex,
            "exec",
            "--ignore-user-config",
            "--ephemeral",
            "--json",
            "--sandbox",
            "workspace-write",
            "--cd",
            str(repository),
            prompt,
        ]
        stderr_file = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=stderr_file, text=True)
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = started + args.timeout
        exit_code: int | None = None
        timed_out = False
        try:
            while True:
                if time.monotonic() >= deadline:
                    timed_out = True
                    process.terminate()
                    try:
                        exit_code = process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        exit_code = process.wait()
                    break
                ready = selector.select(timeout=0.25)
                if not ready:
                    exit_code = process.poll()
                    if exit_code is not None:
                        break
                    continue
                line = process.stdout.readline()
                if not line:
                    exit_code = process.wait()
                    break
                elapsed_ms = round((time.monotonic() - started) * 1000)
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                event_type = str(event.get("type", "unknown"))
                event_counts[event_type] = event_counts.get(event_type, 0) + 1
                item = event.get("item") or {}
                if first_agent_message_ms is None and item.get("type") == "agent_message":
                    first_agent_message_ms = elapsed_ms
                if first_file_change_ms is None and item.get("type") == "file_change":
                    first_file_change_ms = elapsed_ms
                if event_type == "turn.completed":
                    usage = event.get("usage")
        finally:
            selector.close()
            process.stdout.close()
        stderr_file.seek(0)
        stderr = stderr_file.read()
        stderr_file.close()
        changed = subprocess.run(
            ["git", "status", "--short"],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.splitlines()

    summary = {
        "fixture": args.fixture,
        "condition": args.condition,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "first_agent_message_ms": first_agent_message_ms,
        "first_file_change_ms": first_file_change_ms,
        "event_counts": event_counts,
        "usage": usage,
        "changed_paths": changed,
        "stdout_parse_errors": parse_errors,
        "stderr_bytes": len(stderr.encode()),
    }
    print(json.dumps(summary, indent=2))
    return 0 if exit_code == 0 and not timed_out else 1


if __name__ == "__main__":
    raise SystemExit(main())
