"""The optional pre-commit hook: `whyline security scan --staged --hook` on every commit."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

COMMAND = "whyline security scan --staged --hook"
MARKER = "# whyline security pre-commit hook"
SCRIPT = f"#!/bin/sh\n{MARKER}\n{COMMAND}\n"
STOP_LINE = "Commit stopped by whyline security. Review: whyline security scan --staged"


class HookError(RuntimeError):
    """The hook could not be installed or removed; the message says what to do."""


def hook_path(root: Path | str) -> Path:
    """`.git/hooks/pre-commit`, following `git rev-parse --git-path` for worktrees."""
    root = Path(root)
    try:
        done = subprocess.run(["git", "rev-parse", "--git-path", "hooks/pre-commit"], cwd=str(root),
                              capture_output=True, text=True, timeout=10)
        out = done.stdout.strip() if done.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        out = ""
    if not out:
        raise HookError(f"{root} is not a git repository")
    path = Path(out)
    return path if path.is_absolute() else root / path


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _is_ours(text: str | None) -> bool:
    return text is not None and MARKER in text


def installed(root: Path | str) -> bool:
    try:
        return _is_ours(_text(hook_path(root)))
    except HookError:
        return False


def foreign(root: Path | str) -> bool:
    """A pre-commit hook exists that whyline did not write."""
    try:
        path = hook_path(root)
    except HookError:
        return False
    return path.exists() and not _is_ours(_text(path))


def install(root: Path | str) -> Path:
    """Write the hook. A hook that is not whyline's is kept and `HookError` names the line to add."""
    path = hook_path(root)
    if path.exists() and not _is_ours(_text(path)):
        raise HookError(f"{path} already exists and is not whyline's, so it was kept. "
                        f"Add this line to it yourself:\n{COMMAND}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SCRIPT, encoding="utf-8")
        path.chmod(path.stat().st_mode | 0o111)
    except OSError as exc:
        raise HookError(f"could not write {path}: {exc}") from exc
    return path


def uninstall(root: Path | str) -> bool:
    """Remove whyline's hook only. True when something was removed."""
    if not installed(root):
        return False
    path = hook_path(root)
    try:
        os.unlink(path)
    except OSError as exc:
        raise HookError(f"could not remove {path}: {exc}") from exc
    return True


def set_installed(root: Path | str, on: bool) -> str:
    """What the console switch calls. Returns a one-line status."""
    try:
        if on:
            if installed(root):
                return "The commit check is already on."
            install(root)
            return "Commit check installed."
        return "Commit check removed." if uninstall(root) else ""
    except HookError as exc:
        return str(exc)
