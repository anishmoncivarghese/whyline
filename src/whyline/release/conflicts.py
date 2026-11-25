"""Merge conflicts when bringing main in: read them, settle the plain ones, merge.

`read` and `preview` use `git merge-tree --write-tree`, which writes no ref, index or
working file. `merge` is the only function that touches the repository, and it checks
what it wrote before it commits. No model is used here.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from whyline.release import config as release_config
from whyline.release import ready as release_ready
from whyline.release.config import ReleaseConfig
from whyline.release.ready import Run, _git, _short
from whyline.release.resolve import Outcome

TICKS = "only ticked and unticked tasks differ"
SAME = "both sides added the same lines"
VERSION = "only the version number differs"

_ENTRY = re.compile(r"^\d+ [0-9a-f]+ ([123])\t(.+)$", re.DOTALL)
_TICK = re.compile(r"^(\s*- \[)([ xX])(\])")
_VERSION = re.compile(r'^\s*(?:__version__|version)\s*=\s*"[^"]*"\s*$')


@dataclass(frozen=True)
class Conflict:
    path: str
    places: int
    kind: str  # lines, deleted, binary
    reading: str = ""

    @property
    def choices(self) -> tuple[str, ...]:
        if self.kind != "lines":
            return ("agent",)
        if self.reading == TICKS:
            return ("ticks", "ours", "theirs", "agent")
        return ("ours", "theirs", "agent")

    @property
    def default(self) -> str:
        return "ticks" if self.reading == TICKS else ""


# A file is a list of segments: a str of plain text, or an (ours, theirs) pair of lines.
Segment = str | tuple[list[str], list[str]]


def _parse(text: str) -> list[Segment] | None:
    """Split merged text at its conflict markers; None when the markers don't balance."""
    segments: list[Segment] = []
    plain: list[str] = []
    ours: list[str] = []
    theirs: list[str] = []
    state = "plain"
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        if state == "plain":
            if bare == "<<<<<<<" or bare.startswith("<<<<<<< "):
                if plain:
                    segments.append("".join(plain))
                    plain = []
                state = "ours"
            else:
                plain.append(line)
        elif state == "ours":
            if bare == "=======":
                state = "theirs"
            elif bare == "|||||||" or bare.startswith("||||||| "):
                state = "base"
            else:
                ours.append(line)
        elif state == "base":
            if bare == "=======":
                state = "theirs"
        else:
            if bare == ">>>>>>>" or bare.startswith(">>>>>>> "):
                segments.append((ours, theirs))
                ours, theirs = [], []
                state = "plain"
            else:
                theirs.append(line)
    if state != "plain":
        return None
    if plain:
        segments.append("".join(plain))
    return segments


def _places(segments: list[Segment]) -> list[tuple[list[str], list[str]]]:
    return [s for s in segments if not isinstance(s, str)]


def _untick(line: str) -> str:
    return _TICK.sub(r"\1 \3", line.rstrip())


def _reading(places: list[tuple[list[str], list[str]]]) -> str:
    if not places:
        return ""
    if all([_untick(a) for a in o] == [_untick(b) for b in t] for o, t in places) and any(
        [a.rstrip() for a in o] != [b.rstrip() for b in t] for o, t in places
    ):
        return TICKS
    if all([a.rstrip() for a in o] == [b.rstrip() for b in t] for o, t in places):
        return SAME
    if all(len(o) == len(t) and all(
            a.rstrip() == b.rstrip() or (_VERSION.match(a) and _VERSION.match(b))
            for a, b in zip(o, t)) for o, t in places):
        return VERSION
    return ""


def _ticked(line: str) -> bool:
    m = _TICK.match(line)
    return bool(m) and m.group(2) in "xX"


def _ticks(ours: list[str], theirs: list[str]) -> list[str]:
    out: list[str] = []
    for mine, other in zip(ours, theirs):
        if _ticked(other) and not _ticked(mine):
            mine = _TICK.sub(r"\1x\3", mine, count=1)
        out.append(mine)
    return out


def _tree(root: Path, branch: str, run: Run) -> tuple[str, dict[str, set[int]]]:
    res = _git(run, root, "merge-tree", "--write-tree", "-z", "--no-messages",
               "HEAD", f"origin/{branch}")
    code = getattr(res, "returncode", None)
    out = getattr(res, "stdout", "") or ""
    if code not in (0, 1):
        raise RuntimeError(_short(getattr(res, "stderr", "")) or "git merge-tree failed")
    parts = [p for p in out.split("\0") if p]
    if not parts:
        raise RuntimeError("git merge-tree wrote no tree")
    stages: dict[str, set[int]] = {}
    if code == 1:
        for part in parts[1:]:
            m = _ENTRY.match(part)
            if m:
                stages.setdefault(m.group(2), set()).add(int(m.group(1)))
    return parts[0].strip(), stages


def _scan(root: Path, branch: str, run: Run) -> list[tuple[Conflict, list[Segment]]]:
    tree, stages = _tree(root, branch, run)
    found: list[tuple[Conflict, list[Segment]]] = []
    for path in sorted(stages):
        if not {2, 3} <= stages[path]:
            found.append((Conflict(path, 1, "deleted"), []))
            continue
        try:
            res = _git(run, root, "cat-file", "-p", f"{tree}:{path}")
        except UnicodeDecodeError:  # run decodes stdout as text: a non-UTF-8 blob is binary
            found.append((Conflict(path, 1, "binary"), []))
            continue
        text =getattr(res, "stdout", "") or ""
        segments = None if getattr(res, "returncode", 1) != 0 or "\0" in text else _parse(text)
        places = _places(segments) if segments is not None else []
        if not places:
            found.append((Conflict(path, 1, "binary"), []))
            continue
        found.append((Conflict(path, len(places), "lines", _reading(places)), segments))
    return found


def read(root: Path | str, branch: str, *, run: Run) -> list[Conflict]:
    """The files that conflict merging origin/<branch> into HEAD. Changes nothing."""
    return [c for c, _ in _scan(Path(root), branch, run)]


def _check(conflict: Conflict, choice: str) -> None:
    if choice not in conflict.choices:
        raise ValueError(f"{choice!r} is not offered for {conflict.path}")


def _build(segments: list[Segment], choice: str) -> str:
    out: list[str] = []
    for seg in segments:
        if isinstance(seg, str):
            out.append(seg)
            continue
        ours, theirs = seg
        out.extend(ours if choice == "ours" else theirs if choice == "theirs"
                   else _ticks(ours, theirs))
    return "".join(out)


def _previews(scanned, choices: dict[str, str]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for conflict, segments in scanned:
        choice = choices.get(conflict.path, "")
        if not choice or choice == "agent":
            continue
        _check(conflict, choice)
        texts[conflict.path] = _build(segments, choice)
    return texts


def preview(root: Path | str, branch: str, choices: dict[str, str], *, run: Run) -> dict[str, str]:
    """Each settled file's text as it would be merged; files left to `agent` are omitted."""
    return _previews(_scan(Path(root), branch, run), choices)


def _dirty(root: Path, run: Run) -> list[str] | str:
    res = _git(run, root, "status", "--porcelain")
    if getattr(res, "returncode", 1) != 0:
        return _short(getattr(res, "stderr", "")) or "git status failed"
    pending = [p.as_posix() for p in release_config.pending(root)]
    return [p for p in release_ready._dirty_paths(getattr(res, "stdout", "") or "")
            if not release_ready._is_pending(p, pending)]


def _abort(root: Path, run: Run, why: str, snap_id: str) -> Outcome:
    _git(run, root, "merge", "--abort")
    return Outcome(False, f"{why}. Nothing was changed.", 0, snap_id)


def merge(root: Path | str, cfg: ReleaseConfig, version: str, choices: dict[str, str], *,
          run: Run, fix_run: Run | None = None,
          relay_running: Callable[[Path], bool] | None = None) -> Outcome:
    """Merge origin/<branch> in with every conflict settled, then commit."""
    from whyline.console import fixmode
    from whyline.release import source

    root = Path(root)
    if (relay_running or source._relay_running)(root):  # noqa: SLF001
        return Outcome(False, "A relay is running here; release when it finishes")
    dirty = _dirty(root, run)
    if isinstance(dirty, str):
        return Outcome(False, dirty)
    if dirty:
        return Outcome(False, "Commit or stash these first: " + ", ".join(dirty))
    try:
        scanned = _scan(root, cfg.branch, run)
        if not scanned:
            return Outcome(False, f"Nothing conflicts with origin/{cfg.branch}")
        left = [c.path for c, _ in scanned if choices.get(c.path, "") in ("", "agent")]
        if left:
            return Outcome(False, "Choose how to settle: " + ", ".join(left))
        texts = _previews(scanned, choices)
        branch_name = (getattr(_git(run, root, "rev-parse", "--abbrev-ref", "HEAD"),
                               "stdout", "") or "").strip() or "HEAD"
    except Exception as exc:  # noqa: BLE001 - a refusal is reported, not raised
        return Outcome(False, str(exc) or "it failed")
    snap_id = ""
    try:
        snap_id = fixmode.snapshot(root, run=fix_run or subprocess.run).id
    except Exception as exc:  # noqa: BLE001
        return Outcome(False, f"Couldn't take a snapshot first: {exc}")
    res = _git(run, root, "merge", "--no-ff", "--no-commit", f"origin/{cfg.branch}")
    if getattr(res, "returncode", 0) != 1:
        return _abort(root, run, _short(getattr(res, "stderr", "")) or
                      "The merge did not stop on the conflicts that were read", snap_id)
    try:
        for path, text in texts.items():
            with open(root / path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        res = _git(run, root, "add", "--", *texts)
        if getattr(res, "returncode", 1) != 0:
            return _abort(root, run, _failed(res, "git add"), snap_id)
        for path, text in texts.items():
            with open(root / path, encoding="utf-8", newline="") as fh:
                if fh.read() != text:
                    return _abort(root, run, f"{path} is not what was previewed", snap_id)
        left = _git(run, root, "diff", "--name-only", "--diff-filter=U")
        if getattr(left, "returncode", 1) != 0 or (getattr(left, "stdout", "") or "").strip():
            return _abort(root, run, "Some files are still conflicted", snap_id)
        lines = [f"{path}: {choices[path]}" for path in sorted(texts)]
        message = (f"merge: bring {cfg.branch} into {branch_name} for v{version}\n\n"
                   + "\n".join(lines))
        res = _git(run, root, "commit", "-m", message)
        if getattr(res, "returncode", 1) != 0:
            return _abort(root, run, _failed(res, "git commit"), snap_id)
    except Exception as exc:  # noqa: BLE001
        return _abort(root, run, str(exc) or "it failed", snap_id)
    return Outcome(True, f"Merged {cfg.branch} into {branch_name}, settling "
                   f"{len(texts)} file{'s' if len(texts) != 1 else ''}", 1, snap_id)


def _failed(res, what: str) -> str:
    return _short(getattr(res, "stderr", "") or getattr(res, "stdout", "")) or f"{what} failed"
