"""Snapshot and Undo for Fix mode.

A snapshot is a commit of the whole working tree (tracked changes plus
untracked files that are not ignored), built with a temporary index so HEAD,
the real index and the working tree are never touched. It is kept under
``refs/whyline/fix/<id>`` and described in ``.git/whyline-fix/snapshots.json``.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

REF_PREFIX = "refs/whyline/fix/"
_IDENTITY = {
    "GIT_AUTHOR_NAME": "whyline",
    "GIT_AUTHOR_EMAIL": "whyline@localhost",
    "GIT_COMMITTER_NAME": "whyline",
    "GIT_COMMITTER_EMAIL": "whyline@localhost",
}


class FixModeError(RuntimeError):
    """A snapshot or undo step could not be done."""


@dataclass(frozen=True)
class Snapshot:
    id: str
    head: str
    branch: str
    commit: str
    untracked: list[str]
    created: str
    staged: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Change:
    path: str
    kind: str  # added | modified | deleted


Run = Callable[..., "subprocess.CompletedProcess[str]"]


def _git(
    root: Path,
    args: list[str],
    *,
    run: Run,
    env: dict[str, str] | None = None,
    input: str | None = None,
    check: bool = True,
) -> str:
    full_env = {**os.environ, **(env or {})}
    kwargs: dict = {
        "cwd": str(root),
        "env": full_env,
        "capture_output": True,
        "text": True,
    }
    if input is not None:
        kwargs["input"] = input
    result = run(["git", *args], **kwargs)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise FixModeError(f"git {' '.join(args[:2])} failed: {detail}")
    return result.stdout or ""


def _split_nul(text: str) -> list[str]:
    return [p for p in text.split("\0") if p]


def _git_dir(root: Path, run: Run) -> Path:
    out = _git(root, ["rev-parse", "--absolute-git-dir"], run=run).strip()
    return Path(out)


def _head(root: Path, run: Run) -> str:
    out = _git(root, ["rev-parse", "-q", "--verify", "HEAD"], run=run, check=False)
    return out.strip()


def _branch(root: Path, run: Run) -> str:
    out = _git(root, ["symbolic-ref", "-q", "--short", "HEAD"], run=run, check=False)
    return out.strip()


def _write_tree(root: Path, run: Run) -> str:
    """Tree of the working tree (non-ignored files), via a throwaway index."""
    with tempfile.TemporaryDirectory(prefix="whyline-fix-") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(root, ["add", "-A"], run=run, env=env)
        return _git(root, ["write-tree"], run=run, env=env).strip()


def _store_path(root: Path, run: Run) -> Path:
    return _git_dir(root, run) / "whyline-fix" / "snapshots.json"


def _load(root: Path, run: Run) -> dict[str, dict]:
    path = _store_path(root, run)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(root: Path, records: dict[str, dict], run: Run) -> None:
    path = _store_path(root, run)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def snapshot(root: Path, *, run: Run = subprocess.run) -> Snapshot:
    root = Path(root)
    snap_id = f"{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
    head = _head(root, run)
    tree = _write_tree(root, run)
    args = ["commit-tree", tree]
    if head:
        args += ["-p", head]
    args += ["-m", f"whyline fix snapshot {snap_id}"]
    commit = _git(root, args, run=run, env=_IDENTITY).strip()
    _git(root, ["update-ref", REF_PREFIX + snap_id, commit], run=run)
    untracked = _split_nul(
        _git(root, ["ls-files", "--others", "--exclude-standard", "-z"], run=run)
    )
    staged = _split_nul(_git(root, ["diff", "--cached", "--name-only", "-z"], run=run))
    snap = Snapshot(
        id=snap_id,
        head=head,
        branch=_branch(root, run),
        commit=commit,
        untracked=untracked,
        created=datetime.now(timezone.utc).isoformat(),
        staged=staged,
    )
    records = _load(root, run)
    records[snap_id] = asdict(snap)
    _save(root, records, run)
    return snap


def changed_since(
    root: Path, snap: Snapshot, *, run: Run = subprocess.run
) -> list[Change]:
    root = Path(root)
    tree = _write_tree(root, run)
    out = _git(
        root,
        ["diff-tree", "-r", "--no-renames", "--name-status", "-z", snap.commit, tree],
        run=run,
    )
    parts = _split_nul(out)
    kinds = {"A": "added", "D": "deleted"}
    changes: list[Change] = []
    for status, path in zip(parts[0::2], parts[1::2]):
        changes.append(Change(path, kinds.get(status[:1], "modified")))
    return sorted(changes, key=lambda c: c.path)


def undo(root: Path, snap: Snapshot, *, run: Run = subprocess.run) -> list[str]:
    root = Path(root)
    head = _head(root, run)
    if head != snap.head:
        raise FixModeError(
            f"HEAD moved since the snapshot ({snap.head[:8] or 'none'} -> "
            f"{head[:8] or 'none'}); undo would lose commits, so nothing was changed"
        )
    branch = _branch(root, run)
    if branch != snap.branch:
        raise FixModeError(
            f"the branch changed since the snapshot ({snap.branch or 'detached'} -> "
            f"{branch or 'detached'}); nothing was changed"
        )
    changes = changed_since(root, snap, run=run)
    restore = [c.path for c in changes if c.kind != "added"]
    added = [c.path for c in changes if c.kind == "added"]
    # Remove additions first: a path that was a file at snapshot time may now be
    # a directory (or the reverse), and restoring first would collide with it.
    for rel in added:
        target = root / rel
        try:
            target.unlink()
        except FileNotFoundError:
            continue
        parent = target.parent
        while parent != root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    if restore:
        _git(
            root,
            [
                "restore",
                f"--source={snap.commit}",
                "--worktree",
                "--pathspec-from-file=-",
                "--pathspec-file-nul",
            ],
            run=run,
            input="\0".join(restore) + "\0",
        )
    # Put the index back exactly as it was: reset it to HEAD, then re-add.
    if head:
        _git(root, ["reset", "-q"], run=run)
    if snap.staged:
        _git(
            root,
            [
                "add",
                "-A",
                "--pathspec-from-file=-",
                "--pathspec-file-nul",
            ],
            run=run,
            input="\0".join(snap.staged) + "\0",
        )
    return sorted(restore + added)


def load_snapshot(
    root: Path, snap_id: str, *, run: Run = subprocess.run
) -> Snapshot | None:
    record = _load(Path(root), run).get(snap_id)
    if not record:
        return None
    names = {f.name for f in fields(Snapshot)}
    return Snapshot(**{k: v for k, v in record.items() if k in names})


def prune(root: Path, keep: int = 20, *, run: Run = subprocess.run) -> list[str]:
    """Delete the oldest snapshot refs, keeping the newest ``keep``."""
    root = Path(root)
    records = _load(root, run)
    ordered = sorted(records, key=lambda i: (records[i].get("created", ""), i))
    doomed = ordered[: max(0, len(ordered) - max(0, keep))]
    for snap_id in doomed:
        _git(root, ["update-ref", "-d", REF_PREFIX + snap_id], run=run, check=False)
        del records[snap_id]
    if doomed:
        _save(root, records, run)
    return doomed
