"""Snapshot and Undo for Fix mode.

A snapshot is a commit of the whole working tree (tracked changes plus
untracked files that are not ignored), built with a temporary index so HEAD,
the real index and the working tree are never touched. It is kept under
``refs/whyline/fix/<id>`` and described in ``.git/whyline-fix/snapshots.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat as stat_module
import subprocess
import tempfile
import uuid
from collections import Counter
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


@dataclass(frozen=True)
class Violation:
    kind: str  # head | branch | ref | config | hooks | plan | outside | pushed
    message: str


@dataclass(frozen=True)
class GuardState:
    """What an agent turn must leave alone, read before the turn."""

    head: str
    branch: str
    refs: dict[str, str]  # refs/heads and refs/tags
    remotes: dict[str, str]  # refs/remotes (a push moves these)
    config: str
    hooks: dict[str, str]
    ticked: list[str]
    plan: str
    outside: dict[str, str]  # symlinks that point outside the repo -> target state


def _refs(root: Path, run: Run, *patterns: str) -> dict[str, str]:
    out = _git(
        root,
        ["for-each-ref", "--format=%(refname) %(objectname)", *patterns],
        run=run,
    )
    refs: dict[str, str] = {}
    for line in out.splitlines():
        name, _, sha = line.partition(" ")
        if name:
            refs[name] = sha
    return refs


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _entry_state(path: Path) -> str:
    """Identify a path without following it: a link is its target text, not its content."""
    try:
        info = path.lstat()
    except OSError:
        return "missing"
    kind = stat_module.S_IFMT(info.st_mode)
    mode = info.st_mode & 0o7777
    if kind == stat_module.S_IFLNK:
        try:
            text = os.readlink(path)
        except OSError:
            text = "?"
        # Editing the target changes what git reads through the link.
        return f"link:{text}:{_target_state(path)}"
    if kind == stat_module.S_IFREG:
        return f"file:{_digest(path)}:{mode:o}"
    if kind == stat_module.S_IFDIR:
        return f"dir:{mode:o}"
    return f"other:{kind:o}:{mode:o}"


def _hooks(git_dir: Path) -> dict[str, str]:
    base = git_dir / "hooks"
    found: dict[str, str] = {"": _entry_state(base)}
    if base.is_dir() and not base.is_symlink():
        for here, dirs, files in os.walk(base):
            for name in dirs + files:
                item = Path(here) / name
                found[str(item.relative_to(base))] = _entry_state(item)
    return found


def _ticked(plan: Path | None) -> list[str]:
    if plan is None:
        return []
    try:
        lines = plan.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line for line in lines if re.match(r"\s*[-*]\s*\[[xX]\]", line)]


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    except (RuntimeError, OSError):
        # A symlink loop cannot be shown to stay inside: fail closed.
        return False
    return True


def _target_state(path: Path) -> str:
    try:
        target = path.resolve()
        info = target.stat()
    except (RuntimeError, OSError):
        return "missing"
    if target.is_dir():
        # A write to a child changes the child, not the directory's own metadata.
        parts = [f"{info.st_mtime_ns}"]
        for item in sorted(target.rglob("*")):
            try:
                stat = item.stat()
            except OSError:
                continue
            body = _digest(item) if item.is_file() and stat.st_size < 1_000_000 else ""
            parts.append(f"{item.relative_to(target)}:{stat.st_mtime_ns}:{stat.st_size}:{body}")
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()
    return f"{info.st_mtime_ns}:{info.st_size}:{_digest(target)}"


def _link_state(path: Path) -> str:
    # Keep the resolved target so a deleted or repointed link can still be re-checked.
    try:
        resolved = str(path.resolve())
    except (RuntimeError, OSError):
        resolved = str(path)
    return f"{resolved}\0{_target_state(path)}"


def _outside_links(root: Path, run: Run) -> dict[str, str]:
    # No --exclude-standard: an ignored symlink can still write outside the repository.
    names = _split_nul(_git(root, ["ls-files", "--cached", "--others", "-z"], run=run))
    links: dict[str, str] = {}
    for rel in names:
        path = root / rel
        if path.is_symlink():
            if not _inside(root, path):
                links[rel] = _link_state(path)
        elif path.is_dir():
            # ls-files lists a nested repository (or submodule) as one opaque entry.
            for base, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d != ".git"]
                for name in dirs + files:
                    item = Path(base) / name
                    if item.is_symlink() and not _inside(root, item):
                        links[str(item.relative_to(root))] = _link_state(item)
    return links


def observe(
    root: Path, plan: Path | None = None, *, run: Run = subprocess.run
) -> GuardState:
    """Read the state guard() compares against. Call it before each agent turn."""
    root = Path(root)
    git_dir = _git_dir(root, run)
    return GuardState(
        head=_head(root, run),
        branch=_branch(root, run),
        refs=_refs(root, run, "refs/heads", "refs/tags"),
        remotes=_refs(root, run, "refs/remotes"),
        config=_entry_state(git_dir / "config"),
        hooks=_hooks(git_dir),
        ticked=_ticked(Path(plan) if plan else None),
        plan=str(plan) if plan else "",
        outside=_outside_links(root, run),
    )


def _made_local_commit(root: Path, snap: Snapshot, run: Run) -> bool:
    if not snap.head:
        return False
    head = _head(root, run)
    if not head or head == snap.head:
        return False
    result = run(
        ["git", "merge-base", "--is-ancestor", snap.head, head],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def guard(
    root: Path, snap: Snapshot, before: GuardState, *, run: Run = subprocess.run
) -> list[Violation]:
    """Check an agent turn stayed inside the rules; undo the damage if not."""
    root = Path(root)
    found: list[Violation] = []
    try:
        after = observe(root, Path(before.plan) if before.plan else None, run=run)
    except FixModeError as exc:
        # Fail closed: nothing can be compared, so treat the turn as a violation.
        found.append(Violation("inspect", f"could not inspect the repository after the turn: {exc}"))
        try:
            if _made_local_commit(root, snap, run):
                _git(root, ["reset", "--soft", snap.head], run=run)
            undo(root, snap, run=run)
        except FixModeError as undo_exc:
            found.append(Violation("undo", f"could not undo: {undo_exc}"))
        return found

    if after.head != before.head:
        found.append(Violation("head", "the agent moved HEAD (it made a commit or reset)"))
    if after.branch != before.branch:
        found.append(
            Violation(
                "branch",
                f"the agent switched branch ({before.branch or 'detached'} -> "
                f"{after.branch or 'detached'})",
            )
        )
    for name in sorted(set(before.refs) | set(after.refs)):
        if before.refs.get(name) != after.refs.get(name):
            what = "created" if name not in before.refs else (
                "deleted" if name not in after.refs else "moved"
            )
            found.append(Violation("ref", f"the agent {what} {name}"))
    if after.config != before.config:
        found.append(Violation("config", "the agent changed .git/config"))
    if after.hooks != before.hooks:
        found.append(Violation("hooks", "the agent changed .git/hooks"))
    if before.ticked:
        remaining = Counter(after.ticked)
        missing: list[str] = []
        for line in before.ticked:
            if remaining[line] > 0:
                remaining[line] -= 1
            else:
                missing.append(line)
        if missing:
            found.append(
                Violation(
                    "plan",
                    "the agent changed ticked plan tasks: "
                    + "; ".join(line.strip() for line in missing[:3]),
                )
            )
    try:
        changes = changed_since(root, snap, run=run)
    except FixModeError as exc:
        # Fail closed: a check that could not run is a violation, not "no changes".
        found.append(Violation("outside", f"could not check changed files: {exc}"))
        changes = []
    for change in changes:
        if not _inside(root, root / change.path):
            found.append(
                Violation("outside", f"{change.path} resolves outside the repository")
            )
    for rel, state in before.outside.items():
        # A link the agent deleted or repointed still wrote to its original target.
        original, _, old_state = state.partition("\0")
        if after.outside.get(rel) == state:
            continue
        if rel in after.outside or _target_state(Path(original)) != old_state:
            found.append(
                Violation("outside", f"{rel} points outside the repository and its target changed")
            )
    for rel, state in after.outside.items():
        if rel not in before.outside:
            found.append(
                Violation("outside", f"{rel} points outside the repository and its target changed")
            )

    undo_needed = bool(found)
    pushed = [
        name for name in sorted(set(before.remotes) | set(after.remotes))
        if before.remotes.get(name) != after.remotes.get(name)
    ]
    for name in pushed:
        found.append(
            Violation("pushed", f"{name} moved, so the agent may have pushed; nothing was undone there")
        )

    if undo_needed:
        try:
            if _made_local_commit(root, snap, run):
                _git(root, ["reset", "--soft", snap.head], run=run)
            undo(root, snap, run=run)
        except FixModeError as exc:
            found.append(Violation("undo", f"could not undo: {exc}"))
    return found


# ---------------------------------------------------------------------------
# The Resolve conversation: one session per pause.
# ---------------------------------------------------------------------------

SUGGEST = "suggest"
FIX = "fix"
PROMPT_LIMIT = 40 * 1024  # bytes: the most a follow-up prompt may hold


@dataclass(frozen=True)
class Turn:
    role: str  # "you" or the agent's name
    text: str
    at: str = ""


@dataclass
class Session:
    pause_id: str
    agent: str = ""
    level: str = SUGGEST
    turns: list[Turn] = field(default_factory=list)
    snapshots: list[str] = field(default_factory=list)
    attempts: int = 0


def pause_id(reason: str, at: str | int | float) -> str:
    """Identify a pause by why it paused and when."""
    return hashlib.sha256(f"{at}\n{reason}".encode()).hexdigest()[:12]


def _session_dir(root: Path, run: Run) -> Path:
    return _git_dir(root, run) / "whyline-fix"


def session_path(root: Path, *, run: Run = subprocess.run) -> Path:
    return _session_dir(Path(root), run) / "session.json"


def load_session(root: Path, *, run: Run = subprocess.run) -> Session | None:
    try:
        data = json.loads(session_path(root, run=run).read_text(encoding="utf-8"))
    except (OSError, ValueError, FixModeError):
        return None
    if not isinstance(data, dict) or not data.get("pause_id"):
        return None
    turns = [
        Turn(str(t.get("role", "")), str(t.get("text", "")), str(t.get("at", "")))
        for t in data.get("turns") or []
        if isinstance(t, dict)
    ]
    attempts = data.get("attempts")
    return Session(
        pause_id=str(data["pause_id"]),
        agent=str(data.get("agent") or ""),
        level=str(data.get("level") or SUGGEST),
        turns=turns,
        snapshots=[str(s) for s in data.get("snapshots") or []],
        attempts=attempts if isinstance(attempts, int) else 0,
    )


def save_session(root: Path, session: Session, *, run: Run = subprocess.run) -> None:
    path = session_path(root, run=run)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(session), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def open_session(
    root: Path,
    pause: str,
    agent: str = "",
    level: str = SUGGEST,
    *,
    run: Run = subprocess.run,
) -> Session:
    """The saved session for this pause, or a new one.

    A session left from a different pause is kept as ``session-<n>.json``.
    """
    root = Path(root)
    current = load_session(root, run=run)
    if current is not None and current.pause_id == pause:
        return current
    path = session_path(root, run=run)
    if current is not None:
        n = 1
        while path.with_name(f"session-{n}.json").exists():
            n += 1
        os.replace(path, path.with_name(f"session-{n}.json"))
    fresh = Session(pause_id=pause, agent=agent, level=level)
    save_session(root, fresh, run=run)
    return fresh


def format_turn(turn: Turn) -> str:
    return f"{turn.role} › {turn.text}"


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


def trim_turns(turns: list[Turn], budget: int) -> list[Turn]:
    """The newest turns whose lines fit in ``budget`` bytes; oldest drop first.

    A single newest turn that is too big is cut from its start, not dropped.
    """
    kept: list[Turn] = []
    used = 0
    for turn in reversed(turns):
        cost = _size(format_turn(turn)) + 1
        if used + cost > budget:
            if not kept and budget > 0:
                room = budget - _size(f"{turn.role} › ") - _size("[trimmed]\n") - 1
                if room > 0:
                    tail = turn.text.encode("utf-8")[-room:].decode("utf-8", "ignore")
                    kept.append(Turn(turn.role, "[trimmed]\n" + tail, turn.at))
            break
        kept.append(turn)
        used += cost
    kept.reverse()
    return kept
