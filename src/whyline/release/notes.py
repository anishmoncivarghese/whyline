"""Draft release notes from the commits since the last tag, with a plain fallback."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from whyline.release.config import ReleaseConfig
from whyline.release.ready import default_run

Run = Callable[..., object]
AskAgent = Callable[[str], str]

NO_TAG_LIMIT = 50
END_INSTRUCTION = "Put the notes between a line <notes> and a line </notes>. Write nothing else."
UNUSABLE = "The agent's notes were not usable; using the commit list"
_MARKED = re.compile(r"^[ \t]*<notes>[ \t]*\r?\n(.*?)^[ \t]*</notes>[ \t]*$", re.S | re.M)


def _ok(proc: object) -> bool:
    return getattr(proc, "returncode", 1) == 0


def _stdout(proc: object) -> str:
    return (getattr(proc, "stdout", "") or "").strip()


def last_tag(root: Path, *, run: Run = default_run) -> str:
    """The newest `v*` tag reachable from HEAD, or "" when there is none."""
    proc = run(["git", "describe", "--tags", "--abbrev=0", "--match", "v*"], cwd=root)
    return _stdout(proc) if _ok(proc) else ""


def commits_since_last_tag(root: Path, *, run: Run = default_run) -> list[str]:
    tag = last_tag(root, run=run)
    if tag:
        args = ["git", "log", "--format=%s", f"{tag}..HEAD"]
    else:
        args = ["git", "log", "--format=%s", f"-{NO_TAG_LIMIT}"]
    proc = run(args, cwd=root)
    if not _ok(proc):
        return []
    return [line.strip() for line in _stdout(proc).splitlines() if line.strip()]


def _notes_path(root: Path, cfg: ReleaseConfig, version: str) -> Path | None:
    if not cfg.notes:
        return None
    try:
        return Path(root) / cfg.notes.format(version=version)
    except (KeyError, IndexError, ValueError):
        return None


def _style_example(root: Path, cfg: ReleaseConfig, *, run: Run) -> str:
    tag = last_tag(root, run=run)
    if not tag:
        return ""
    path = _notes_path(root, cfg, tag.removeprefix("v"))
    if path is None or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def fallback(version: str, commits: list[str]) -> str:
    lines = [f"# v{version}", ""]
    lines += [f"- {subject}" for subject in commits]
    return "\n".join(lines) + "\n"


def build_prompt(version: str, commits: list[str], example: str) -> str:
    parts = [
        f"Write release notes in markdown for version v{version}, for the people who use this software.",
        "Group the notes by what changed (for example New, Improved, Fixed).",
        "Only describe changes that appear in the commit subjects below. Do not invent features, "
        "fixes or details that are not in them.",
        "",
        "Commit subjects:",
    ]
    parts += [f"- {subject}" for subject in commits] or ["(none)"]
    if example:
        parts += ["", "Match the style and tone of the previous release notes:", "", example]
    parts += ["", END_INSTRUCTION]
    return "\n".join(parts) + "\n"


def extract(text: str) -> str | None:
    """What sits between the last `<notes>` line and its `</notes>` line, stripped."""
    found = None
    for match in _MARKED.finditer(text or ""):
        found = match.group(1)
    if found is None or not found.strip():
        return None
    return found.strip()


def draft(
    root: Path,
    cfg: ReleaseConfig,
    version: str,
    *,
    ask_agent: AskAgent,
    run: Run = default_run,
    say: Callable[[str], None] | None = None,
) -> str:
    """Ask the agent for notes; a failed, empty or unmarked answer gives the plain list."""
    commits = commits_since_last_tag(root, run=run)
    prompt = build_prompt(version, commits, _style_example(root, cfg, run=run))
    try:
        text = (ask_agent(prompt) or "").strip()
    except Exception:  # every agent failed: a release never blocks on notes
        text = ""
    if not text:
        return fallback(version, commits)
    marked = extract(text)
    if marked is None:
        if say is not None:
            say(UNUSABLE)
        return fallback(version, commits)
    return marked + "\n"


def write(root: Path, cfg: ReleaseConfig, version: str, text: str) -> Path | None:
    path = _notes_path(root, cfg, version)
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return path
