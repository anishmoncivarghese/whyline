#!/usr/bin/env python3
"""Copy one participant-visible fixture into a fresh Git repository."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", choices=("cache_ttl", "webhook_dedupe", "config_reload"))
    parser.add_argument("destination", type=Path)
    parser.add_argument("--condition", required=True, choices=("cold", "human", "structured"))
    args = parser.parse_args()

    source = Path(__file__).parent / args.fixture
    destination = args.destination.resolve()
    if destination.exists():
        raise SystemExit(f"Destination already exists: {destination}")

    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("facilitator"))
    briefs = destination / "briefs"
    if args.condition == "cold":
        shutil.rmtree(briefs)
    else:
        selected = briefs / f"{args.condition}.md" if args.condition == "human" else briefs / "structured.yaml"
        shutil.copy2(selected, destination / "HANDOFF.md")
        shutil.rmtree(briefs)
    (destination / "CONDITION.txt").write_text(f"{args.condition}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=destination, check=True)
    subprocess.run(["git", "add", "."], cwd=destination, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Phase 0 Fixture",
            "-c",
            "user.email=fixture.invalid",
            "commit",
            "-qm",
            "Initial study fixture",
        ],
        cwd=destination,
        check=True,
    )
    print(f"{destination} ({args.fixture}, {args.condition})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
