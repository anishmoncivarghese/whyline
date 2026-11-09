"""Where a new project goes: its name, its folder, and whether the repo is still empty."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from whyline import paths
from whyline.console import repl, repo_setup
from whyline.sdlc import docset as docset_mod

MAX_FOLDER = 40
WANTED = 3
MINIMUM = 2
TIMEOUT_SECONDS = 180
FALLBACK_REASON = "from the plan's name"
PROMPT_ASK = (
    "Suggest 3 short names for this project. Reply with one line each: "
    "<Name> — <why, in under 12 words>. Nothing else."
)
_FRESH_NAMES = ("README", "LICENSE", ".gitignore", ".gitattributes")
_FRESH_DIRS = (".whyline/", ".claude/", "docs/", "plans/")
_SETTINGS = "sdlc-home.json"
_BULLET = re.compile(r"^\s*(?:[-*•]+|\d+[.)])?\s*")
_SPLIT = re.compile(r"\s+[—–-]+\s+|\s*—\s*|\s*–\s*")


@dataclass(frozen=True)
class NameIdea:
    name: str
    folder: str
    reason: str


def folder_name(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    text = text[:MAX_FOLDER].strip("-")
    return text or "project"


def _idea(name: str, reason: str) -> NameIdea:
    return NameIdea(name, folder_name(name), reason)


def _parse_line(line: str) -> NameIdea | None:
    text = _BULLET.sub("", line.strip()).replace("**", "").replace("`", "")
    parts = _SPLIT.split(text, maxsplit=1)
    if len(parts) != 2:
        return None
    name = parts[0].strip().strip("\"'<>").strip()
    reason = parts[1].strip()
    if not name or not reason or not re.search(r"[A-Za-z0-9]", name):
        return None
    return _idea(name, reason)


def parse_names(text: str) -> list[NameIdea]:
    found: list[NameIdea] = []
    for line in (text or "").splitlines():
        idea = _parse_line(line)
        if idea is not None:
            found.append(idea)
        if len(found) == WANTED:
            break
    return found


def _brief(root: Path, docset) -> str:
    doc = docset.document("brainstorm")
    if doc is not None:
        try:
            text = docset_mod._current_text(root, docset, doc).strip()
        except Exception:
            text = ""
        if text:
            return text
    return (docset.description or docset.name or "").strip()


def _fallback(docset) -> list[NameIdea]:
    return [_idea(docset.name or docset.slug or "Project", FALLBACK_REASON)]


def _run_once(root: Path, agent: str, argv: list[str], text: str, folder: Path,
              run: Callable) -> tuple[int | None, str, str]:
    from whyline.agents import runner as agent_runner
    from whyline.relaychat import ask

    answer_file = None
    try:
        adapter = agent_runner._adapter(SimpleNamespace(root=root), agent)
        if adapter is not None and adapter.uses_output_file:
            answer_file = folder / "answer.txt"
            argv = [*argv, "-o", str(answer_file)]
    except Exception:
        answer_file = None
    try:
        result = run(argv, text, cwd=folder, log_path=folder / "output.log",
                     timeout_seconds=TIMEOUT_SECONDS, capture=True, echo=False,
                     agent_name=agent, env={"GIT_OPTIONAL_LOCKS": "0"})
    except Exception:
        return None, "", ""
    code, out = result.exit_code, result.output or ""
    answer = ""
    if code == 0 and out.strip() and not ask.cancelled_turn(agent, out):
        answer = ask._extract(root, agent, out, answer_file).strip()
    return code, out, answer


def suggest_names(root, docset, *, agent: str, run_fn: Callable | None = None) -> list[NameIdea]:
    """Three name ideas from the set's Writer agent, run read-only. Never raises
    for an agent failure: it falls back to one idea from the set's name."""
    root = Path(root)
    try:
        from whyline.relaychat import ask

        argv = ask._command(root, agent)
        if argv is None:
            return _fallback(docset)
        if run_fn is None:
            from whyline_relay import agents

            run_fn = agents.run
        prompt = f"{_brief(root, docset)}\n\n{PROMPT_ASK}"
        with tempfile.TemporaryDirectory(prefix="whyline-name-") as tmp:
            folder = Path(tmp)
            code, raw, answer = _run_once(root, agent, argv, prompt, folder, run_fn)
            if code == 0 and not answer and ask.cancelled_turn(agent, raw):
                note = ask.RETRY_NOTE
                refused = ask.refused_command(raw)
                if refused:
                    note = f"Your last command, `{refused}`, is not allowed. {note}"
                code, raw, answer = _run_once(
                    root, agent, argv, f"{prompt}\n\n{note}", folder, run_fn)
        ideas = parse_names(answer) if code == 0 else []
    except Exception:
        return _fallback(docset)
    return ideas if len(ideas) >= MINIMUM else _fallback(docset)


def _tracked(root: Path) -> list[str] | None:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True,
                            encoding="utf-8")
    if result.returncode != 0:
        return None
    return [name for name in result.stdout.split("\0") if name]


def is_fresh(root) -> bool:
    """True when every tracked file is a README, LICENSE, ignore file or lives in
    .whyline/, .claude/, docs/ or plans/: a repository with no code yet."""
    names = _tracked(Path(root))
    if names is None:
        return False
    for name in names:
        if name.startswith(_FRESH_DIRS):
            continue
        if name in (".gitignore", ".gitattributes") or name.startswith(("README", "LICENSE")):
            continue
        return False
    return True


def check_target(root, parent: Path, folder: str) -> str | None:
    """A plain refusal for putting a new project at parent/folder, or None."""
    parent = Path(parent).expanduser()
    if not parent.is_dir():
        return f"{parent} doesn't exist."
    target = parent / folder
    inspection = repo_setup.inspect(target)
    if inspection.kind == "home":
        return repl._HOME_REFUSAL
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        return f"{target} already exists and isn't empty. Pick another name or folder."
    if inspection.kind == "nested":
        return f"{target} is inside the repository {inspection.outer}. Pick a folder outside it."
    return None


def _settings_path() -> Path:
    return paths.global_whyline_dir() / _SETTINGS


def last_parent() -> Path:
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
        saved = data.get("last_parent") if isinstance(data, dict) else None
    except (OSError, ValueError):
        saved = None
    if isinstance(saved, str) and saved:
        return Path(saved).expanduser()
    projects = Path.home() / "projects"
    return projects if projects.is_dir() else Path.home()


def save_parent(path) -> None:
    from whyline.state import atomic_write_json

    target = _settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, {"last_parent": str(Path(path).expanduser())})
