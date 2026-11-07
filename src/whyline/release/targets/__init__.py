"""Release targets: where a release is published besides GitHub.

Each target module registers itself in REGISTRY; `enabled` returns the switched-on
ones in the fixed order below."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from whyline.release.config import ReleaseConfig
from whyline.release.engine import Step
from whyline.release.ready import Fetch, ReadyItem, Run

ORDER = ("pypi", "npm", "docker", "homebrew", "custom")


class Target(Protocol):
    key: str
    title: str

    def ready_items(self, root: Path, cfg: ReleaseConfig, version: str, *,
                    run: Run, fetch: Fetch) -> list[ReadyItem]: ...

    def steps(self, root: Path, cfg: ReleaseConfig, version: str, *,
              run: Run, fetch: Fetch) -> list[Step]: ...

    def verify(self, root: Path, cfg: ReleaseConfig, version: str, *,
               run: Run, fetch: Fetch) -> tuple[bool, str]: ...

    def setup_status(self, root: Path, cfg: ReleaseConfig, *, run: Run) -> list[str]: ...


REGISTRY: dict[str, Target] = {}


def register(target: Target) -> None:
    REGISTRY[target.key] = target


def enabled(cfg: ReleaseConfig) -> list[Target]:
    """Registered targets that `cfg` switches on: pypi, npm, docker, homebrew, custom."""
    return [REGISTRY[key] for key in ORDER
            if key in REGISTRY and getattr(cfg.targets, key, False)]
