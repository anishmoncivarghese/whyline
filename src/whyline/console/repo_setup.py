"""Inspecting a path the user typed into the context bar, and setting it up
for whyline step by step (spec section 3). No UI here."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

STEPS = ("folder", "git", "whyline", "agents")
_WORDS = {
    "folder": "create the folder",
    "git": "run git init",
    "whyline": "run whyline init",
    "agents": "write the relay's agent permission settings",
}
_COMMIT_MESSAGE = "chore: set up whyline"
# Lives in the git directory, so it never enters the user's tree or the
# commit. While it exists, setup has not finished: "step" is the first step
# still to do and "files" is every file setup has written so far, across
# attempts. A failed attempt's files already exist when the retry starts, so
# only this record can tell the retry they are setup's to commit.
_RECORD_NAME = "whyline-setup-pending.json"
# Earlier drafts wrote a one-line phase here. A leftover "agents" marker
# still means preparation has not returned, even when claude-settings.json
# already exists.
_LEGACY_MARKER = "whyline-agents-pending"
_RECORDED_STEPS = ("whyline", "agents")


@dataclass(frozen=True)
class Inspection:
    path: Path
    kind: str
    outer: Path | None = None
    missing: tuple[str, ...] = ()


class SetupError(RuntimeError):
    def __init__(self, step: str, error: Exception):
        super().__init__(f"Setting up stopped at '{_WORDS.get(step, step)}': {error}")
        self.step = step


def _git_root(path: Path) -> Path | None:
    probe = path if path.is_dir() else path.parent
    while not probe.exists():
        probe = probe.parent
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=probe,
        capture_output=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    return Path(text).resolve() if text else None


def _git_dir(root: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
    )
    text = result.stdout.strip() if result.returncode == 0 else ""
    return Path(text) if text else None


def _record_from_legacy(git_dir: Path) -> dict | None:
    marker = git_dir / _LEGACY_MARKER
    if not marker.is_file():
        return None
    try:
        phase = marker.read_text(encoding="utf-8").strip()
    except OSError:
        phase = ""
    if phase not in _RECORDED_STEPS:
        phase = _RECORDED_STEPS[0]
    return {"step": phase, "files": []}


def _read_record(root: Path) -> dict | None:
    git_dir = _git_dir(root) if root.is_dir() else None
    if git_dir is None:
        return None
    path = git_dir / _RECORD_NAME
    if path.is_file():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
        if record.get("step") not in _RECORDED_STEPS:
            record["step"] = _RECORDED_STEPS[0]  # unreadable: redo both steps
        if not isinstance(record.get("files"), list):
            record["files"] = []
        return record
    return _record_from_legacy(git_dir)


def _write_record(root: Path, record: dict) -> None:
    git_dir = _git_dir(root)
    (git_dir / _RECORD_NAME).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (git_dir / _LEGACY_MARKER).unlink(missing_ok=True)


def _clear_record(root: Path) -> None:
    git_dir = _git_dir(root)
    if git_dir is not None:
        (git_dir / _RECORD_NAME).unlink(missing_ok=True)
        (git_dir / _LEGACY_MARKER).unlink(missing_ok=True)


def _untracked(root: Path) -> set[str]:
    """Untracked, not-ignored files, relative to root, as posix paths."""
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return {entry[3:] for entry in result.stdout.split("\0") if entry.startswith("?? ")}


def inspect(path: Path) -> Inspection:
    path = Path(path).expanduser().resolve()
    if path == Path.home().resolve():
        return Inspection(path, "home")
    root = _git_root(path)
    if root is not None and root != path:
        return Inspection(path, "nested", outer=root)
    missing: list[str] = []
    if not path.exists():
        missing.append("folder")
    if root is None:
        missing.append("git")
    # A git root with .whyline/ and no pending record is set up (spec section
    # 3). The settings file is not that signal: setup with no agents writes
    # none. A pending record means our own setup has not finished, whatever
    # files a failed attempt left behind.
    record = _read_record(path) if root is not None else None
    if record is not None:
        missing += _RECORDED_STEPS[_RECORDED_STEPS.index(record["step"]):]
    elif not (path / ".whyline").is_dir():
        missing += _RECORDED_STEPS
    return Inspection(path, "ready" if not missing else "needs_setup", missing=tuple(missing))


def describe(inspection: Inspection) -> str:
    home = Path.home().resolve().as_posix()
    shown = inspection.path.as_posix()
    if shown == home:
        shown = "~"
    elif shown.startswith(home + "/"):
        shown = "~" + shown[len(home):]
    steps = " · ".join(_WORDS[step] for step in inspection.missing)
    return (
        f"Set up {shown} for whyline? This will: {steps} · make a first commit with "
        "those files. Antigravity will ask separately whether to trust this folder."
    )


def _whyline_init(root: Path) -> None:
    subprocess.run(
        ["whyline", "init", "--yes"],
        cwd=root,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )


def _prepare_agents(root: Path, agents: list[str]) -> list[Path]:
    from whyline.console import relay_ops

    return relay_ops.prepare_agents(root, agents, commit=False)


def _without_ignored(root: Path, paths: list[Path]) -> list[Path]:
    """git add fails the whole command when any named path is ignored.
    whyline init creates ledger.jsonl, which its own gitignore excludes."""
    ordered: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        if ".git" in Path(rel).parts or rel in seen:
            continue
        seen.add(rel)
        ordered.append((rel, path))
    if not ordered:
        return []
    proc = subprocess.run(
        ["git", "check-ignore", "-z", "--stdin"],
        cwd=root,
        input="\0".join(rel for rel, _path in ordered) + "\0",
        capture_output=True,
        encoding="utf-8",
    )
    ignored: set[str] = set()
    if proc.returncode in (0, 1):
        ignored = {Path(item).as_posix() for item in proc.stdout.split("\0") if item}
    return [path for rel, path in ordered if rel not in ignored]


def _identity_overlay(root: Path) -> dict[str, str]:
    """A fresh repo whose HOME has no gitconfig cannot commit. The overlay
    applies to this commit only; it is not written into .git/config."""
    found: dict[str, str] = {}
    for key in ("user.name", "user.email"):
        result = subprocess.run(
            ["git", "config", key],
            cwd=root,
            capture_output=True,
            encoding="utf-8",
        )
        if result.returncode == 0 and result.stdout.strip():
            found[key] = result.stdout.strip()
    if "user.name" in found and "user.email" in found:
        return {}
    name = found.get("user.name", "whyline")
    email = found.get("user.email", "whyline@localhost")
    return {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }


def _commit_created(root: Path, created: list[Path]) -> None:
    from whyline_relay import gitcheck

    committable = _without_ignored(root, created)
    if not committable:
        return
    overlay = _identity_overlay(root)
    previous = {key: os.environ.get(key) for key in overlay}
    os.environ.update(overlay)
    try:
        gitcheck.commit_paths(root, committable, _COMMIT_MESSAGE)
    finally:
        for key, old in previous.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def setup(inspection: Inspection, *, agents: list[str], progress) -> Path:
    if inspection.kind == "home":
        raise SetupError("folder", OSError("refusing to set up the home folder"))
    if inspection.kind == "nested":
        raise SetupError(
            "git",
            OSError(f"{inspection.path} is inside the repository {inspection.outer}"),
        )

    root = inspection.path
    record: dict | None = None
    for step in inspection.missing:
        progress(_WORDS[step])
        try:
            if step == "folder":
                root.mkdir(parents=True, exist_ok=True)
            elif step == "git":
                subprocess.run(
                    ["git", "init", "-q", "-b", "main"],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    encoding="utf-8",
                )
            else:
                record = record or _read_record(root) or {"files": []}
                record["step"] = step
                _write_record(root, record)
                before = _untracked(root)
                created_now: list[Path] = []
                try:
                    if step == "whyline":
                        _whyline_init(root)
                    else:
                        created_now = list(_prepare_agents(root, agents) or [])
                finally:
                    # Even when the step fails: untracked files it wrote,
                    # and paths it reports, are setup's to commit.
                    named: set[str] = set()
                    for path in created_now:
                        if not path.is_file():
                            continue
                        try:
                            named.add(
                                path.resolve().relative_to(root.resolve()).as_posix()
                            )
                        except ValueError:
                            continue
                    written = _untracked(root) - before
                    record["files"] = sorted(set(record["files"]) | written | named)
                    _write_record(root, record)
                later = _RECORDED_STEPS.index(step) + 1
                if later < len(_RECORDED_STEPS):
                    record["step"] = _RECORDED_STEPS[later]
                    _write_record(root, record)
        except (OSError, subprocess.CalledProcessError) as error:
            raise SetupError(step, error) from error
    if record is not None:
        _commit_created(root, [root / name for name in record["files"]])
        _clear_record(root)
    return root
