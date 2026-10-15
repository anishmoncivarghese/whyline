"""Decide which file changed and follow agent writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_BYTES = 1_000_000
SAMPLE_BYTES = 8192


@dataclass(frozen=True)
class Snap:
    mtime_ns: int
    size: int


@dataclass(frozen=True)
class FollowUpdate:
    path: str
    text: str | None
    notice: str | None
    changed_line: int


def porcelain_argv() -> list[str]:
    return ["status", "--porcelain", "-z", "--untracked-files=all"]


def parse_porcelain_z(blob: bytes) -> list[str]:
    if not blob:
        return []
    tokens = blob.split(b"\x00")
    paths: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        item = tokens[i]
        if not item or len(item) < 3:
            i += 1
            continue
        xy = item[:2]
        path_bytes = item[3:]
        paths.append(path_bytes.decode("utf-8", errors="surrogateescape"))
        if b"R" in xy or b"C" in xy:
            i += 1
        i += 1
    return paths


def is_ignored(rel: str) -> bool:
    norm = rel.replace("\\", "/")
    parts = PurePosixPath(norm).parts
    if not parts:
        return False
    return parts[0] in (".whyline", ".git")


def classify(raw: bytes) -> str | None:
    if len(raw) > MAX_BYTES:
        return f"too large to show ({len(raw)} bytes)"
    if b"\x00" in raw[:SAMPLE_BYTES]:
        return "binary, not shown"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return "not UTF-8, not shown"
    return None


def first_changed_line(before: str, after: str) -> int:
    b_lines = before.splitlines()
    a_lines = after.splitlines()
    for i, (b, a) in enumerate(zip(b_lines, a_lines), start=1):
        if b != a:
            return i
    if len(b_lines) != len(a_lines):
        return min(len(b_lines), len(a_lines)) + 1
    return 1


def display_path(root: Path, repo: Path, rel: str) -> str:
    if Path(repo) == Path(root):
        return rel
    return f"{Path(repo).name}:{rel}"


def poll(
    baseline: dict[str, Snap],
    found: dict[str, tuple[Snap, bytes]],
    hints: list[str],
    head: dict[str, str],
) -> tuple[dict[str, Snap], FollowUpdate | None]:
    new_baseline = dict(baseline)
    candidates: list[str] = []
    for path, (snap, _raw) in found.items():
        if path not in baseline or baseline[path] != snap:
            candidates.append(path)
            new_baseline[path] = snap

    if not candidates:
        return new_baseline, None

    winner = max(candidates, key=lambda p: found[p][0].mtime_ns)
    _snap, raw = found[winner]
    notice = classify(raw)
    if notice is not None:
        return new_baseline, FollowUpdate(
            path=winner,
            text=None,
            notice=notice,
            changed_line=1,
        )

    text = raw.decode("utf-8")
    changed_line = first_changed_line(head.get(winner, ""), text)
    return new_baseline, FollowUpdate(
        path=winner,
        text=text,
        notice=None,
        changed_line=changed_line,
    )
