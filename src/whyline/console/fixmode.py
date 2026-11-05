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
        resolved = path.resolve()
        if path.is_symlink():
            # Python 3.13's non-strict resolve no longer raises on a loop,
            # so resolve strictly to catch one. A dangling link keeps the
            # non-strict answer.
            try:
                resolved = path.resolve(strict=True)
            except FileNotFoundError:
                pass
        resolved.relative_to(root.resolve())
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


# ---------------------------------------------------------------------------
# A Fix turn: snapshot, run the agent with edits allowed, guard, report.
# ---------------------------------------------------------------------------


@dataclass
class FixResult:
    status: str  # proposal | violation | cancelled | exhausted
    agent: str = ""
    snapshot: Snapshot | None = None
    diagnosis: str = ""
    steps: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    counts: dict[str, tuple[int, int]] = field(default_factory=dict)  # path -> (+, -)
    violations: list[Violation] = field(default_factory=list)
    tried: list[str] = field(default_factory=list)
    fallbacks: list[tuple[str, str]] = field(default_factory=list)
    elapsed: float = 0.0


def change_counts(
    root: Path, snap: Snapshot, *, run: Run = subprocess.run
) -> dict[str, tuple[int, int]]:
    """Lines added and removed per path since the snapshot (binary files: 0, 0)."""
    root = Path(root)
    tree = _write_tree(root, run)
    out = _git(
        root,
        ["diff-tree", "-r", "--no-renames", "--numstat", "-z", snap.commit, tree],
        run=run,
    )
    counts: dict[str, tuple[int, int]] = {}
    for part in _split_nul(out):
        pieces = part.split("\t", 2)
        if len(pieces) != 3:
            continue
        added, removed, path = pieces
        counts[path] = (
            int(added) if added.isdigit() else 0,
            int(removed) if removed.isdigit() else 0,
        )
    return counts


def _restore(root: Path, snap: Snapshot, before: GuardState, run: Run) -> None:
    """Put the tree back after an agent that failed or was stopped."""
    guard(root, snap, before, run=run)  # undoes a commit or branch change, if any
    try:
        undo(root, snap, run=run)
    except FixModeError:
        pass


def run_fix(
    root: Path,
    session: Session,
    *,
    agent_chain: list[str],
    runner: Callable[..., object] | None = None,
    on_progress: Callable[[str], None] | None = None,
    cancel_event: object | None = None,
    max_minutes: int | None = None,
    run: Run = subprocess.run,
) -> FixResult:
    """One Fix turn: the first agent in the chain that has a guarded fix command.

    A snapshot is taken first. An agent without a fix command is skipped; one
    that times out or hits a limit is undone and passes the turn on. Stop
    (``cancel_event``) ends the turn and undoes what it left. After the turn the
    guard runs; a violation is undone and reported.
    """
    import inspect
    import time

    from whyline.agents import capabilities
    from whyline.console import recovery, relay_ops
    from whyline_relay import agents as relay_agents
    from whyline_relay import chat as relay_chat
    from whyline_relay import config as relay_config
    from whyline_relay import state as relay_state

    root = Path(root).resolve()
    started = time.monotonic()
    say = on_progress or (lambda _text: None)

    def cancelled() -> bool:
        return cancel_event is not None and bool(cancel_event.is_set())  # type: ignore[attr-defined]

    result = FixResult(status="exhausted")

    def finish(status: str) -> FixResult:
        result.status = status
        result.elapsed = time.monotonic() - started
        return result

    if cancelled():
        return finish("cancelled")
    snap = snapshot(root, run=run)
    result.snapshot = snap
    session.snapshots.append(snap.id)
    session.attempts += 1
    session.level = FIX
    try:
        save_session(root, session, run=run)
    except (OSError, FixModeError):
        pass

    settings = relay_config.load(root)
    plan = Path(settings.plan) if getattr(settings, "plan", None) else None
    if plan is not None and not plan.is_absolute():
        plan = root / plan
    try:
        st = relay_state.load(root)
    except Exception:
        st = None
    minutes = (
        st.timeout_minutes
        if st and st.timeout_minutes is not None
        else getattr(settings, "timeout_minutes", None)
    )
    if max_minutes is not None:
        minutes = max_minutes if not minutes else min(minutes, max_minutes)
    timeout = relay_ops._timeout_seconds_kwarg(minutes)
    prompt = recovery.build_fix_prompt(root, session.turns)
    active = runner if runner is not None else relay_agents.run
    try:
        params = inspect.signature(active).parameters.values()
        takes_cancel = any(
            p.name == "cancel_event" or p.kind is inspect.Parameter.VAR_KEYWORD
            for p in params
        )
    except (TypeError, ValueError):
        takes_cancel = False

    def pass_over(agent: str, why: str) -> None:
        result.fallbacks.append((agent, why))
        say(f"{agent} {why}")

    for agent in agent_chain:
        if agent in result.tried:
            continue
        if cancelled():
            return finish("cancelled")
        try:
            command = relay_chat.resolve_command(settings, agent)
        except Exception:
            command = [agent]
        fix = capabilities.fix_command(agent, list(command))
        if fix is None:
            pass_over(agent, "has no guard for Fix mode, so it was skipped")
            continue
        result.tried.append(agent)
        before = observe(root, plan, run=run)
        log = root / ".whyline" / "relay" / "logs" / f"fix-agent-{agent}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict = {
            "cwd": root,
            "log_path": log,
            "echo": False,
            "agent_name": agent,
            **timeout,
        }
        if takes_cancel and cancel_event is not None:
            kwargs["cancel_event"] = cancel_event
        say(f"{agent} is fixing…")
        raw = ""
        failure: Exception | None = None
        try:
            out = active(fix, prompt, **kwargs)
            if isinstance(out, str):
                raw = out
            else:
                raw = getattr(out, "output", None) or getattr(out, "stdout", None) or ""
        except Exception as exc:  # noqa: BLE001
            failure = exc
        if not raw and failure is None and log.is_file():
            raw = log.read_text(encoding="utf-8", errors="replace")

        if cancelled() or isinstance(failure, relay_agents.AgentCancelled):
            _restore(root, snap, before, run)
            return finish("cancelled")
        if failure is not None:
            _restore(root, snap, before, run)
            if not recovery._is_model_failure(failure, ""):
                raise failure
            pass_over(agent, recovery._fallback_reason(failure, ""))
            continue

        result.agent = agent
        violations = guard(root, snap, before, run=run)
        if violations:
            result.violations = violations
            return finish("violation")
        result.changes = changed_since(root, snap, run=run)
        result.counts = change_counts(root, snap, run=run)
        data = recovery.extract_fenced_json(raw)
        if data is not None:
            result.diagnosis = str(data.get("diagnosis") or "").strip()
            result.steps, result.notes = recovery.validate_steps(
                root, data.get("steps") or []
            )
        else:
            result.diagnosis = raw.strip()
        stamp = datetime.now(timezone.utc).isoformat()
        session.turns.append(Turn(agent, result.diagnosis, stamp))
        session.agent = agent
        try:
            save_session(root, session, run=run)
        except (OSError, FixModeError):
            pass
        return finish("proposal")
    return finish("exhausted")


# ---------------------------------------------------------------------------
# Fix level: how far Fix mode may go on its own.
# ---------------------------------------------------------------------------

LEVEL_SUGGEST = "suggest"  # the agent only answers; it never edits
LEVEL_APPROVAL = "approval"  # it edits; the user approves before checks run
LEVEL_AUTO = "auto"  # it edits, the checks run, and a pass continues the relay
FIX_LEVELS = (LEVEL_SUGGEST, LEVEL_APPROVAL, LEVEL_AUTO)
FIX_LEVEL_LABELS = {
    LEVEL_SUGGEST: "Suggest",
    LEVEL_APPROVAL: "Fix with approval",
    LEVEL_AUTO: "Auto fix",
}
_LEVEL_IGNORE = ".whyline/relay/fix-level.json"


def fix_level_path(root: Path | str) -> Path:
    return Path(root) / ".whyline" / "relay" / "fix-level.json"


def fix_level(root: Path | str) -> str:
    try:
        data = json.loads(fix_level_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return LEVEL_APPROVAL
    level = data.get("level") if isinstance(data, dict) else None
    return level if level in FIX_LEVELS else LEVEL_APPROVAL


def _ignore_level_file(root: Path) -> None:
    """Keep the saved level out of `git status`, as resolve-mode.json is."""
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-path", "info/exclude"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return
    target = Path(res.stdout.strip())
    if not target.is_absolute():
        target = root / target
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if _LEVEL_IGNORE in existing.splitlines():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(_LEVEL_IGNORE + "\n")


def save_fix_level(root: Path | str, level: str) -> None:
    if level not in FIX_LEVELS:
        raise ValueError(f"Invalid fix level: {level!r}; must be one of {', '.join(FIX_LEVELS)}")
    root = Path(root)
    _ignore_level_file(root)
    path = fix_level_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"schema": 1, "level": level}, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Check before continuing: doctor, then the task's tests.
# ---------------------------------------------------------------------------


@dataclass
class VerifyResult:
    ok: bool
    doctor_ok: bool = True
    tests_ok: bool = True
    ran: list[str] = field(default_factory=list)  # test commands that passed
    output: str = ""  # what failed, for the conversation

    def summary(self) -> str:
        doctor = "doctor ✓" if self.doctor_ok else "doctor ✗"
        if not self.tests_ok:
            return f"{doctor}, tests ✗"
        return f"{doctor}, tests ✓" if self.ran else f"{doctor}, no test command"


def verify_commands(root: Path, task: str) -> list[str]:
    """The task's `Verify with` commands, else the relay config's test command."""
    from whyline.console import recovery

    commands: list[str] = []
    if task:
        plan = str(recovery._read_state_dict(root).get("plan") or "")
        text = recovery._saved_task_text(root, plan, task)
        for line in text.splitlines():
            _, sep, tail = line.partition("Verify with")
            if sep:
                commands.extend(re.findall(r"`([^`]+)`", tail))
    if not commands:
        try:
            from whyline_relay import config as relay_config

            commands.append(relay_config.test_command(root))
        except Exception:
            pass
    unique: list[str] = []
    for command in (" ".join(c.split()) for c in commands if c and c.strip()):
        if command not in recovery._DOCTOR_COMMANDS and command not in unique:
            unique.append(command)
    return unique


def verify(
    root: Path,
    task: str,
    *,
    doctor: Callable[[Path], object] | None = None,
    check: Callable[[Path, dict], str] | None = None,
) -> VerifyResult:
    """Relay doctor, then each test command through run-check; stops at the first failure."""
    from whyline.console import adapters, recovery

    root = Path(root).resolve()
    doctor = doctor or adapters.run_doctor
    check = check or recovery._fix_run_check
    event = doctor(root)
    if getattr(event, "kind", "output") == "error":
        text = str(getattr(event, "text", ""))
        return VerifyResult(False, doctor_ok=False, output=f"relay doctor failed:\n{text}")
    result = VerifyResult(True)
    for command in verify_commands(root, task):
        try:
            out = check(root, {"command": command, "task": task})
        except ValueError as exc:
            out = f"run-check {command}: exit 1\n{exc}"
        match = re.match(r"run-check .*: exit (-?\d+)", out)
        if match and match.group(1) == "0":
            result.ran.append(command)
            continue
        result.ok = result.tests_ok = False
        result.output = out
        return result
    return result


# ---------------------------------------------------------------------------
# Auto fix guard rails: one attempt per pause, safe steps only, all recorded.
# ---------------------------------------------------------------------------

AUTO_FIX_MINUTES = 20  # the most one Auto fix turn may run
AUTO_FIX_KIND = "auto-fix"
# ASK-4's safe set lives in recovery; these steps are also safe in an Auto fix.
AUTO_EXTRA_STEPS = frozenset({"run-check", "config-commit", "report-bug", "undo-fix"})


@dataclass
class AutoFixOutcome:
    status: str  # applied | stopped
    reason: str = ""  # why Auto stopped, for the panel
    result: FixResult | None = None
    checked: VerifyResult | None = None
    message: str = ""
    resumed: bool = False
    check_failed: bool = False


def attempts_path(root: Path, run: Run = subprocess.run) -> Path:
    return _git_dir(Path(root), run) / "whyline-fix" / "attempts.json"


def load_attempts(root: Path, run: Run = subprocess.run) -> list[dict]:
    try:
        data = json.loads(attempts_path(root, run).read_text(encoding="utf-8"))
    except (OSError, ValueError, FixModeError):
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def record_attempt(
    root: Path,
    *,
    task: str,
    round_num: int,
    pause: str,
    reason: str,
    agent: str,
    diagnosis: str,
    files: list[str],
    checks: str,
    result: str,
    run: Run = subprocess.run,
) -> dict:
    """Write one Auto fix attempt to recovery.json and .git/whyline-fix/attempts.json."""
    from whyline.console import recovery

    root = Path(root)
    entry = {
        "task": task,
        "round": round_num,
        "kind": AUTO_FIX_KIND,
        "pause_id": pause,
        "pause_reason": reason,
        "cause": recovery.normalise_cause(reason),
        "agent": agent,
        "diagnosis": diagnosis,
        "files": files,
        "checks": checks,
        "result": result,
        "verdict": result,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        recovery.record_attempt(root, dict(entry))
    except OSError:
        pass
    try:
        path = attempts_path(root, run)
        records = load_attempts(root, run)
        records.append(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, FixModeError):
        pass
    return entry


def auto_gate(
    root: Path, *, pause: str, reason: str, run: Run = subprocess.run
) -> str:
    """Why Auto may not try a fix now, or "" when it may."""
    from whyline.console import recovery

    cause = recovery.normalise_cause(reason)
    records = load_attempts(root, run)
    if cause:
        for rec in reversed(records):
            if rec.get("result") == "applied" and rec.get("cause") == cause:
                files = ", ".join(rec.get("files") or []) or "no files"
                what = rec.get("diagnosis") or "a fix"
                return (
                    f"the same pause came back after Auto applied {what} "
                    f"(files: {files})"
                )
    if any(rec.get("pause_id") == pause for rec in records):
        return "Auto already tried one fix for this pause"
    return ""


def auto_steps_ok(
    root: Path, steps: list[dict], task: str, notes: list[str] | None = None
) -> tuple[bool, str]:
    """Whether every proposed step may run without asking."""
    from whyline.console import recovery

    if notes:
        return False, f"the proposal has invalid or dropped steps: {'; '.join(notes)}"
    if not steps:
        return False, "the fix proposed no steps to continue with"
    caps = 0
    for step in steps:
        action = step.get("action", "")
        if action == "commit-task":
            status = recovery._last_handoff_status(root, str(step.get("task") or task))
            if status != "approved":
                return False, (
                    "commit-task needs an approved handoff "
                    f"(the last one is {status or 'missing'})"
                )
        elif action in AUTO_EXTRA_STEPS:
            continue
        else:
            if action in ("retry-stage", "raise-rounds", "more-rounds"):
                caps += 1
                if caps > 1:
                    return False, "multiple cap options proposed"
            ok, why = recovery._is_step_auto_safe(root, step, task)
            if not ok:
                return False, why
    return True, ""


def auto_fix(
    root: Path,
    session: Session,
    *,
    task: str,
    round_num: int,
    reason: str,
    agent_chain: list[str],
    runner: Callable[..., object] | None = None,
    launch: Callable[[list[str]], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
    cancel_event: object | None = None,
    verify_fn: Callable[[Path, str], VerifyResult] | None = None,
    run: Run = subprocess.run,
) -> AutoFixOutcome:
    """One guarded Auto fix: gate, fix turn, safe steps, checks, then apply."""
    from whyline.console import recovery

    root = Path(root).resolve()
    why = auto_gate(root, pause=session.pause_id, reason=reason, run=run)
    if why:
        return AutoFixOutcome("stopped", why)

    agent, diagnosis, files, checks = "", "", [], ""

    def done(outcome: AutoFixOutcome, result: str) -> AutoFixOutcome:
        record_attempt(
            root, task=task, round_num=round_num, pause=session.pause_id,
            reason=reason, agent=agent, diagnosis=diagnosis, files=files,
            checks=checks, result=result, run=run,
        )
        return outcome

    try:
        res = run_fix(
            root, session, agent_chain=agent_chain, runner=runner,
            on_progress=on_progress, cancel_event=cancel_event,
            max_minutes=AUTO_FIX_MINUTES, run=run,
        )
    except Exception as exc:  # noqa: BLE001
        return done(AutoFixOutcome("stopped", f"the fix agent failed: {exc}"), "error")
    agent, diagnosis = res.agent, res.diagnosis
    files = [c.path for c in res.changes]
    if res.status != "proposal":
        text = {
            "cancelled": "the fix was stopped; its edits were undone",
            "violation": "the fix broke a guard rule and was undone",
        }.get(res.status, "no agent could make a guarded fix")
        return done(AutoFixOutcome("stopped", text, res), res.status)

    ok, why = auto_steps_ok(root, res.steps, task, res.notes)
    if not ok:
        return done(AutoFixOutcome("stopped", why, res), "needs-approval")

    check = verify_fn or verify
    try:
        checked = check(root, task)
    except Exception as exc:  # noqa: BLE001
        checked = VerifyResult(False, tests_ok=False, output=f"The check could not run: {exc}")
    checks = checked.summary()
    if not checked.ok:
        return done(
            AutoFixOutcome(
                "stopped", f"the checks failed ({checks})", res, checked, check_failed=True
            ),
            "check-failed",
        )

    resumed = False

    def launcher(args: list[str]) -> None:
        nonlocal resumed
        resumed = True
        if launch is not None:
            launch(args)

    try:
        out = recovery.apply_steps(root, res.steps, launch=launcher)
    except Exception as exc:  # noqa: BLE001
        return done(
            AutoFixOutcome("stopped", f"applying the steps failed: {exc}", res, checked),
            "apply-failed",
        )
    message = str(out.message)
    if not out.success:
        return done(AutoFixOutcome("stopped", message, res, checked), "apply-failed")
    return done(AutoFixOutcome("applied", "", res, checked, message, resumed), "applied")


# ---------------------------------------------------------------------------
# Check: a read-only health note on a relay that is running or paused.
# ---------------------------------------------------------------------------

CHECK_LOG_LINES = 200
CHECK_MAX_SECONDS = 10 * 60


@dataclass
class CheckResult:
    status: str  # note | cancelled | exhausted
    agent: str = ""
    note: str = ""
    steps: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    tried: list[str] = field(default_factory=list)
    fallbacks: list[tuple[str, str]] = field(default_factory=list)


def _seconds_since(started: str, now: datetime) -> int | None:
    try:
        then = datetime.fromisoformat(started)
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.astimezone()
    return max(0, int((now - then).total_seconds()))


def _minutes_text(seconds: int) -> str:
    return f"{seconds // 60}m{seconds % 60:02d}s"


def _check_timeout_minutes(root: Path, st: object | None) -> int | None:
    minutes = getattr(st, "timeout_minutes", None)
    if minutes is not None:
        return minutes
    try:
        from whyline_relay import config as relay_config

        return getattr(relay_config.load(root), "timeout_minutes", None)
    except Exception:  # noqa: BLE001
        return None


def _check_round_lines(root: Path, task: str) -> list[str]:
    if not task:
        return []
    try:
        from whyline.console import relay_ops

        rounds = relay_ops.task_rounds(root, task)
    except Exception:  # noqa: BLE001 - no ledger, or no relay installed
        return []
    return [
        f"- {r.from_actor} -> {r.to_actor}: {r.status}"
        f"{' (sent back)' if r.sent_back else ''} {r.summary[:200]}".rstrip()
        for r in rounds
    ]


def _check_plan_progress(root: Path, st: object | None) -> str:
    plan_name = str(getattr(st, "plan", "") or "")
    if not plan_name:
        try:
            from whyline_relay import config as relay_config

            plan_name = str(relay_config.load(root).plan or "")
        except Exception:  # noqa: BLE001
            return "(no plan found)"
    if not plan_name:
        return "(no plan found)"
    plan = Path(plan_name)
    plan = plan if plan.is_absolute() else root / plan
    try:
        lines = plan.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "(no plan found)"
    boxes = [ln for ln in lines if re.match(r"\s*[-*]\s*\[[ xX]\]", ln)]
    done = [ln for ln in boxes if re.match(r"\s*[-*]\s*\[[xX]\]", ln)]
    return f"{len(done)} of {len(boxes)} plan items ticked"


def _file_time(path: Path) -> str:
    """A file's modification time, as a local timestamp."""
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def _quota_lines_with_times(root: Path) -> list[str]:
    """recovery's quota lines, each log it quotes tagged with its mtime."""
    from whyline.console import recovery

    logs = root / ".whyline" / "relay" / "logs"
    out: list[str] = []
    for line in recovery._ask_quota_lines(root):
        tail = re.search(r"; ([^;()]+\.log)\)$", line)
        if tail is not None:
            try:
                stamp = _file_time(logs / tail.group(1))
                line = line[: tail.start(1)] + f"{tail.group(1)}, modified {stamp})"
            except OSError:
                pass
        out.append(line)
    return out


def build_check_prompt(root: Path | str, *, now: datetime | None = None) -> str:
    """The context for a Check: live marker, turn time against the timeout, the
    last 200 log lines, quota evidence, stage visits, send-backs and progress.

    It asks for a health note, and its step catalog is the one Ask agent uses.
    """
    from whyline.console import recovery

    root = Path(root).resolve()
    now = now or datetime.now(timezone.utc)
    st_dict = recovery._read_state_dict(root)
    try:
        from whyline_relay import state as relay_state

        st = relay_state.load(root)
    except Exception:  # noqa: BLE001
        st = None
    marker = None
    try:
        from whyline_relay import running

        marker = running.read(root)
    except Exception:  # noqa: BLE001
        pass
    if marker is not None:
        elapsed = _seconds_since(marker.started, now)
        live = (
            f"agent {marker.agent} ({marker.role or 'no role'}) on {marker.task} "
            f"round {marker.round}, stage {marker.stage or '-'} visit {marker.visit}, "
            f"pid {marker.pid}, turn started {marker.started}"
        )
    else:
        elapsed = None
        live = "no live marker: no agent turn is running"
    minutes = _check_timeout_minutes(root, st)
    limit = "no limit" if minutes == 0 else (_minutes_text(minutes * 60) if minutes else "unknown")
    turn_time = (
        f"{_minutes_text(elapsed)} elapsed of a {limit} timeout"
        if elapsed is not None
        else f"no running turn; the timeout is {limit}"
    )
    log_tail = ""
    log_time = ""
    log_path = str(st_dict.get("log_path") or "")
    if log_path:
        lp = Path(log_path)
        lp = lp if lp.is_absolute() else root / lp
        try:
            lines = lp.read_text(encoding="utf-8", errors="replace").splitlines()
            log_tail = "\n".join(lines[-CHECK_LOG_LINES:])
            log_time = _file_time(lp)
        except OSError:
            pass
    visits = st_dict.get("stage_visits")
    visits_text = (
        ", ".join(f"{k}={v}" for k, v in sorted(visits.items()))
        if isinstance(visits, dict) and visits
        else "(none)"
    )
    task = str(st_dict.get("task_id") or "")
    rounds = _check_round_lines(root, task)
    sent_back = sum(1 for line in rounds if "(sent back)" in line)
    catalog = recovery.get_rec_4c_options(root)
    parts = [
        "You are checking on a relay while it runs or is paused. Be read-only: "
        "do not edit, stage or commit anything, and nothing you suggest is "
        "applied while the relay runs.",
        "",
        "## Live Marker",
        live,
        "",
        "## Turn Time Against Timeout",
        turn_time,
        "",
        f"## Last {CHECK_LOG_LINES} Transcript Lines"
        + (f" (log last modified {log_time})" if log_time else ""),
        log_tail or "None",
        "",
        "## Quota Evidence",
        "A failure older than the agent's most recent successful turn is history, "
        "not current state.",
        "\n".join(_quota_lines_with_times(root)),
        "",
        "## Stage Visits and Send-backs",
        f"task: {task or '(none)'}; stage: {st_dict.get('stage') or '(none)'}; "
        f"round: {st_dict.get('round') or '(none)'}",
        f"visits: {visits_text}",
        f"send-backs this task: {sent_back} of {len(rounds)} handoffs",
        *rounds,
        "",
        "## Plan Progress",
        _check_plan_progress(root, st),
        "",
        "## Available Step Catalog",
        "- set-model {agent, model}",
        "- set-roles {implementer?, tester?, reviewer?, backup?}",
        "- clear-override reviewer",
        "- raise-rounds {by}",
        "- retry-stage",
        "- resume {allow_dirty}",
        "- wait-until {time}",
        "- human {text}",
        "",
        "## Available REC-4C Options",
        *(f"- {opt_id}: {label}" for opt_id, label in catalog.items()),
        "",
        "## Instructions",
        "Give a short health note. Start it with exactly one of: stuck, going "
        "round in circles, quota risk, fine. Then one or two sentences why.",
        "If you suggest changes, pick steps only from the catalog above and end "
        "with a fenced JSON block: "
        '{"diagnosis": "...", "steps": [...], "confidence": "high|medium|low"}. '
        "They are kept for the next pause and not applied now. If the relay is "
        "fine, give no steps.",
    ]
    return "\n".join(parts)


def _check_answer(
    root: Path, agent: str, raw: str, answer_file: Path | None, prompt: str = ""
) -> str:
    """The agent's reply, as relaychat.ask extracts it (Codex's -o file, the
    result field of JSON output). A JSON-less multi-line reply that the
    adapter would cut down to its last line is kept whole."""
    from types import SimpleNamespace

    from whyline.agents import runner as agent_runner

    text = agent_runner._answer(SimpleNamespace(root=root), agent, raw, answer_file).strip()
    if answer_file is not None and answer_file.is_file() and answer_file.read_text(
        encoding="utf-8", errors="replace"
    ).strip():
        return text
    if prompt and prompt.strip()[:200] in raw:
        return text
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if len(lines) > 1 and text and text != raw.strip() and text in lines[-1] and text == (
        "".join(ch for ch in lines[-1].strip() if ch.isprintable())
    ):
        return raw.strip()
    return text


# How Chat words each outcome (relaychat.ask), as the tail of "<agent> …".
_CHECK_PASS_OVER = {
    "usage_limit": "has reached its usage limit.",
    "login_needed": "needs you to sign in.",
    "timed_out": "took too long, so it was stopped.",
    "missing": "is not installed or not on PATH.",
    "failed": "could not answer.",
}


def run_check(
    root: Path,
    *,
    agent_chain: list[str],
    runner: Callable[..., object] | None = None,
    cancel_event: object | None = None,
    on_progress: Callable[[str], None] | None = None,
    on_agent: Callable[[str], None] | None = None,
    now: datetime | None = None,
) -> CheckResult:
    """Ask the first agent in the chain that has a read-only mode for a note.

    An agent known to be out (agent_readiness), or whose run is judged a usage
    limit, sign-in, timeout, failure or empty answer, is passed over for the
    next one. on_agent is told which agent is being asked.

    Nothing is applied: any steps are only validated and returned.
    """
    import inspect
    from types import SimpleNamespace

    from whyline.agents import capabilities
    from whyline.agents import runner as agent_runner
    from whyline.console import recovery, relay_ops
    from whyline_relay import agents as relay_agents
    from whyline_relay import chat as relay_chat
    from whyline_relay import config as relay_config

    root = Path(root).resolve()
    say = on_progress or (lambda _text: None)
    asking = on_agent or (lambda _agent: None)
    result = CheckResult(status="exhausted")

    def cancelled() -> bool:
        return cancel_event is not None and bool(cancel_event.is_set())  # type: ignore[attr-defined]

    settings = relay_config.load(root)
    try:
        from whyline_relay import state as relay_state

        st = relay_state.load(root)
    except Exception:  # noqa: BLE001
        st = None
    timeout = relay_ops._timeout_seconds_kwarg(_check_timeout_minutes(root, st))
    seconds = timeout.get("timeout_seconds")
    if isinstance(seconds, int) and not isinstance(seconds, bool):
        timeout = {"timeout_seconds": max(1, min(seconds, CHECK_MAX_SECONDS))}
    else:
        timeout = {"timeout_seconds": CHECK_MAX_SECONDS}
    prompt = build_check_prompt(root, now=now)
    active = runner if runner is not None else relay_agents.run
    try:
        params = inspect.signature(active).parameters.values()
        takes_cancel = any(
            p.name == "cancel_event" or p.kind is inspect.Parameter.VAR_KEYWORD
            for p in params
        )
    except (TypeError, ValueError):
        takes_cancel = False

    def pass_over(agent: str, why: str) -> None:
        result.fallbacks.append((agent, why))
        later = [
            a for a in agent_chain
            if a != agent and a not in result.tried and a not in {f for f, _ in result.fallbacks}
        ]
        if later:
            say(f"{agent} {why.rstrip('.')}, trying {later[0]}…")
        else:
            say(f"{agent} {why}")

    not_ready: dict[str, str] = {}
    try:
        for row in relay_ops.agent_readiness(root):
            if not row.ready:
                why = str(row.why or "is not ready").strip()
                not_ready[row.agent] = why[len(row.agent):].strip() if why.startswith(row.agent) else why
    except Exception:  # noqa: BLE001 - readiness unreadable: skip nobody
        not_ready = {}

    for agent in agent_chain:
        if agent in result.tried or agent in {f for f, _ in result.fallbacks}:
            continue
        if cancelled():
            result.status = "cancelled"
            return result
        if agent in not_ready:
            pass_over(agent, not_ready[agent])
            continue
        try:
            command = relay_chat.resolve_command(settings, agent)
        except Exception:  # noqa: BLE001
            command = [agent]
        read_only = capabilities.read_only_command(agent, list(command))
        if read_only is None:
            pass_over(agent, "has no read-only mode, so it was skipped")
            continue
        result.tried.append(agent)
        asking(agent)
        log = root / ".whyline" / "relay" / "logs" / f"check-agent-{agent}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict = {
            "cwd": root, "log_path": log, "echo": False, "agent_name": agent, **timeout,
        }
        if takes_cancel and cancel_event is not None:
            kwargs["cancel_event"] = cancel_event
        raw = ""
        code: int | None = 0  # a bare string result counts as exit 0
        failure: Exception | None = None
        answer_dir = tempfile.TemporaryDirectory(prefix="whyline-check-")
        answer_file: Path | None = None
        try:
            adapter = agent_runner._adapter(SimpleNamespace(root=root), agent)
            if adapter is not None and adapter.uses_output_file:
                answer_file = Path(answer_dir.name) / "answer.txt"
                read_only = [*read_only, "-o", str(answer_file)]
        except Exception:  # noqa: BLE001
            answer_file = None
        try:
            out = active(read_only, prompt, **kwargs)
            if isinstance(out, str):
                raw = out
            else:
                raw = getattr(out, "output", None) or getattr(out, "stdout", None) or ""
                got = getattr(out, "exit_code", None)
                if isinstance(got, int) and not isinstance(got, bool):
                    code = got
        except Exception as exc:  # noqa: BLE001
            failure = exc
        if not raw and failure is None and log.is_file():
            raw = log.read_text(encoding="utf-8", errors="replace")
        answer = ""
        if failure is None and code == 0 and raw.strip():
            answer = _check_answer(root, agent, raw, answer_file, prompt)
        answer_dir.cleanup()
        if cancelled() or isinstance(failure, relay_agents.AgentCancelled):
            result.status = "cancelled"
            return result
        outcome, _reason = agent_runner._classify(agent, code, raw, failure)
        if outcome == "cancelled":
            result.status = "cancelled"
            return result
        if outcome in _CHECK_PASS_OVER:
            pass_over(agent, _CHECK_PASS_OVER[outcome])
            continue
        # The agent's answer, not its transcript (codex echoes the prompt).
        if not answer:
            pass_over(agent, "gave no answer.")
            continue
        result.agent = agent
        data = recovery.extract_fenced_json(answer)
        if data is not None:
            result.note = str(data.get("diagnosis") or "").strip()
            result.steps, result.notes = recovery.validate_steps(root, data.get("steps") or [])
            prose = answer.split("```", 1)[0].strip()
            if prose:
                result.note = prose
        else:
            result.note = answer
        result.status = "note"
        return result
    return result


# A Check's proposal waits here until the relay pauses.
def check_proposal_path(root: Path, *, run: Run = subprocess.run) -> Path:
    return _session_dir(Path(root), run) / "check-proposal.json"


def store_check_proposal(
    root: Path, steps: list[dict], note: str, agent: str, *, run: Run = subprocess.run
) -> None:
    path = check_proposal_path(root, run=run)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    record = {
        "steps": steps,
        "note": note,
        "agent": agent,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_check_proposal(root: Path, *, run: Run = subprocess.run) -> dict | None:
    try:
        data = json.loads(check_proposal_path(root, run=run).read_text(encoding="utf-8"))
    except (OSError, ValueError, FixModeError):
        return None
    if not isinstance(data, dict) or not data.get("steps"):
        return None
    return data


def clear_check_proposal(root: Path, *, run: Run = subprocess.run) -> None:
    try:
        check_proposal_path(root, run=run).unlink(missing_ok=True)
    except (OSError, FixModeError):
        pass
