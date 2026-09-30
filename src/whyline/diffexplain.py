"""`whyline explain --diff` / `--staged`: which recorded reasoning covers
the code a change touches.

For every changed line that existed in HEAD, the line is blamed *as it was
in HEAD* (one blame per hunk) and resolved with the same rules as
`explain`, so a reviewer sees which decisions the change is overriding or
extending, and how much of it has no recorded reasoning at all. Lines that
are purely new have no history yet and are only counted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from whyline import gitq, history, resolve

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
LEVELS = (resolve.HIGH, resolve.MEDIUM, resolve.LOW, resolve.NONE)


@dataclass
class _File:
    old_path: str | None
    hunks: list[tuple[int, int, int]] = field(default_factory=list)  # (old_start, old_len, new_len)


def _parse_diff(text: str) -> list[_File]:
    files: list[_File] = []
    current: _File | None = None
    for entry in text.splitlines():
        if entry.startswith("diff --git "):
            current = _File(old_path=None)
            files.append(current)
        elif current is None:
            continue
        elif entry.startswith("--- "):
            source = entry[4:]
            current.old_path = None if source == "/dev/null" else source.removeprefix("a/")
        elif entry.startswith("@@"):
            match = _HUNK.match(entry)
            if match:
                old_start = int(match.group(1))
                old_len = int(match.group(2)) if match.group(2) is not None else 1
                new_len = int(match.group(4)) if match.group(4) is not None else 1
                current.hunks.append((old_start, old_len, new_len))
    return [item for item in files if item.hunks]


def _ranges(lines: list[tuple[str, int]]) -> list[dict]:
    """[(path, line)] -> compact [{"path", "start", "end"}] runs."""
    runs: list[dict] = []
    for path, line in sorted(lines):
        if runs and runs[-1]["path"] == path and runs[-1]["end"] == line - 1:
            runs[-1]["end"] = line
        else:
            runs.append({"path": path, "start": line, "end": line})
    return runs


def explain_diff(root: Path, *, staged: bool = False) -> dict:
    args = ["diff", "--no-color", "--no-ext-diff", "-U0", "-M"]
    args += ["--cached"] if staged else ["HEAD"]
    diff_text = gitq._git(root, *args)
    changed = _parse_diff(diff_text)
    loaded = history.load(root)
    commits_cache: dict = {}
    coverage = {level: 0 for level in LEVELS}
    coverage["new"] = 0
    groups: dict[str, dict] = {}
    mechanical_only: list[tuple[str, int]] = []
    unexplained: list[tuple[str, int]] = []
    rank = {level: index for index, level in enumerate(LEVELS)}

    for item in changed:
        names = gitq.historical_paths(root, item.old_path) if item.old_path else []
        for old_start, old_len, new_len in item.hunks:
            coverage["new"] += max(new_len - old_len, 0)
            if old_len == 0 or item.old_path is None:
                continue
            end = old_start + old_len - 1
            blamed = gitq.blame_range(root, item.old_path, old_start, end, rev="HEAD")
            for line in range(old_start, end + 1):
                result = resolve.explain_blamed(
                    root, loaded, item.old_path, line, blamed.get(line),
                    names=names, commits_cache=commits_cache,
                )
                coverage[result.confidence] += 1
                where = (item.old_path, line)
                if result.confidence in (resolve.HIGH, resolve.MEDIUM):
                    for note in result.notes:
                        key = str(note.get("id") or note.get("decision", ""))
                        group = groups.setdefault(key, {
                            "id": note.get("id", ""),
                            "decision": note.get("decision", ""),
                            "confidence": result.confidence,
                            "lifecycle": note.get("lifecycle", "active"),
                            "_lines": [],
                        })
                        if rank[result.confidence] < rank[group["confidence"]]:
                            group["confidence"] = result.confidence
                        group["_lines"].append(where)
                elif result.confidence == resolve.LOW:
                    mechanical_only.append(where)
                else:
                    unexplained.append(where)

    decisions = []
    for group in groups.values():
        lines = group.pop("_lines")
        decisions.append({**group, "lines": _ranges(lines)})
    decisions.sort(key=lambda g: (rank[g["confidence"]], g["decision"]))
    return {
        "base": "index" if staged else "working tree",
        "files": len(changed),
        "decisions": decisions,
        "mechanical_only": _ranges(mechanical_only),
        "unexplained": _ranges(unexplained),
        "coverage": coverage,
    }


def _where(run: dict) -> str:
    if run["start"] == run["end"]:
        return f"{run['path']}:{run['start']}"
    return f"{run['path']}:{run['start']}-{run['end']}"


def text(report: dict) -> str:
    coverage = report["coverage"]
    existing = sum(coverage[level] for level in LEVELS)
    if not report["files"]:
        return "No changes against HEAD." if report["base"] == "working tree" else "Nothing staged."
    lines = [
        f"Changes in the {report['base']} against HEAD: {report['files']} file"
        + ("s" if report["files"] != 1 else "")
        + f", {existing} existing line{'s' if existing != 1 else ''} changed, "
        + f"{coverage['new']} new.",
        "",
    ]
    for group in report["decisions"]:
        status = "" if group["lifecycle"] == "active" else f" ({group['lifecycle']})"
        lines.append(f"{str(group['id'])[:8]}  {group['decision']}  [{group['confidence']}]{status}")
        lines.append("  " + ", ".join(_where(run) for run in group["lines"]))
    if report["mechanical_only"]:
        lines.append("Agent-touched, no recorded reasoning:")
        lines.append("  " + ", ".join(_where(run) for run in report["mechanical_only"]))
    if report["unexplained"]:
        lines.append("No recorded reasoning:")
        lines.append("  " + ", ".join(_where(run) for run in report["unexplained"]))
    lines.append("")
    lines.append(
        f"Coverage: {coverage['high']} high · {coverage['medium']} medium · "
        f"{coverage['low']} low · {coverage['none']} unexplained · {coverage['new']} new"
    )
    return "\n".join(lines)
