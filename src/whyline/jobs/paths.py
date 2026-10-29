"""Where Jobs keeps its per-user personal data (~/.whyline/jobs/, mode 0700)."""
from __future__ import annotations

import os
from pathlib import Path


def configured_home() -> Path:
    """Return ~/.whyline/jobs without creating it or changing its mode."""
    return Path.home() / ".whyline" / "jobs"


def _private_dir(path: Path) -> Path:
    parent = path.parent
    if parent.is_symlink() or path.is_symlink():
        raise OSError(f"refusing symlinked jobs directory: {path}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink() or path.is_symlink() or not path.is_dir():
        raise OSError(f"refusing non-directory jobs path: {path}")
    if os.name != "nt":
        path.chmod(0o700)
    return path


def home() -> Path:
    """Ensure ~/.whyline/jobs/ exists with mode 0700 and return its Path."""
    return _private_dir(configured_home())
