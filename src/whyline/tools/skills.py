"""The skills library: folders holding a ``SKILL.md`` that agents may be given.

Skills are read from four places, in this order: ``~/.whyline/skills/``,
``<root>/.whyline/skills/``, ``~/.claude/skills/`` and ``<root>/.claude/skills/``.
Only whyline skills can be changed here; Claude skills are copied first."""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from whyline.tools import users

SKILL_LIMIT = 20_000
AGENT_SKILLS_LIMIT = 60_000

ORIGINS = ("whyline", "whyline-repo", "claude", "claude-project")
CLAUDE_REFUSAL = "Claude skills are read where they are. Copy to whyline to change it."

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class Skill:
    origin: str
    name: str
    description: str
    path: Path
    size: int
    files: tuple[str, ...]
    problem: str = ""  # why the skill is broken; empty when it is fine

    @property
    def ref(self) -> str:
        return f"{self.origin}:{self.name}"

    @property
    def broken(self) -> bool:
        return bool(self.problem)


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name))


def _places(root: Path | None) -> list[tuple[str, Path]]:
    home = Path.home()
    places = [("whyline", home / ".whyline" / "skills")]
    if root is not None:
        places.append(("whyline-repo", Path(root) / ".whyline" / "skills"))
    places.append(("claude", home / ".claude" / "skills"))
    if root is not None:
        places.append(("claude-project", Path(root) / ".claude" / "skills"))
    return places


def parse_front_matter(text: str) -> dict[str, str]:
    """Simple ``key: value`` lines between the first two ``---`` lines."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    found: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return found
        key, sep, value = line.partition(":")
        if sep and key.strip():
            found[key.strip()] = value.strip().strip("\"'")
    return {}  # never closed


def body_of(text: str) -> str:
    """The text after the front matter (all of it when there is none)."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return "\n".join(lines[i + 1:]).strip()
    return text.strip()


def _files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file())


def _load(origin: str, folder: Path) -> Skill:
    files = _files(folder)
    size = sum(p.stat().st_size for p in files)
    names = tuple(p.relative_to(folder).as_posix() for p in files)
    meta: dict[str, str] = {}
    problem = ""
    manifest = folder / "SKILL.md"
    if not manifest.is_file():
        problem = "no SKILL.md"
    else:
        try:
            meta = parse_front_matter(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as error:
            problem = f"SKILL.md cannot be read ({error})"
    description = meta.get("description", "")
    if not problem:
        if not description:
            problem = "no description in SKILL.md"
        elif meta.get("name") != folder.name:
            problem = f"name {meta.get('name', '')!r} does not match folder {folder.name!r}"
    return Skill(origin, folder.name, description, folder, size, names, problem)


def find(root: Path | None = None) -> list[Skill]:
    found: list[Skill] = []
    for origin, place in _places(root):
        if not place.is_dir():
            continue
        for folder in sorted(place.iterdir()):
            if folder.is_dir() and not folder.name.startswith("."):
                found.append(_load(origin, folder))
    return found


def get(ref: str, root: Path | None = None) -> Skill:
    origin, sep, name = ref.partition(":")
    if not sep or origin not in ORIGINS or not name:
        raise ValueError(f"A skill is named origin:name, for example whyline:{name or 'notes'}.")
    for skill in find(root):
        if skill.origin == origin and skill.name == name:
            return skill
    raise KeyError(ref)


def _whyline_dir(repo_root: Path | None) -> Path:
    if repo_root is not None:
        return Path(repo_root) / ".whyline" / "skills"
    return Path.home() / ".whyline" / "skills"


def _render(name: str, description: str, body: str) -> str:
    if "\n" in description:
        raise ValueError("The description is one line.")
    text = f"---\nname: {name}\ndescription: {description}\n---\n\n{body.strip()}\n"
    if len(text.encode("utf-8")) > SKILL_LIMIT:
        raise ValueError(f"SKILL.md is over {SKILL_LIMIT} bytes.")
    return text


def create(name: str, description: str, body: str, *, repo_root: Path | None = None) -> Skill:
    if not valid_name(name):
        raise ValueError("A skill name is lowercase letters, digits, - and _.")
    if not description.strip():
        raise ValueError("A skill needs a description.")
    folder = _whyline_dir(repo_root) / name
    if folder.exists():
        raise ValueError(f"A skill named {name} already exists there.")
    text = _render(name, description.strip(), body)
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(text, encoding="utf-8")
    return _load("whyline-repo" if repo_root is not None else "whyline", folder)


def copy_to_whyline(ref: str, root: Path | None = None) -> Skill:
    source = get(ref, root)
    if not source.origin.startswith("claude"):
        raise ValueError("Only Claude skills are copied; this one is already whyline's.")
    target = _whyline_dir(None) / source.name
    if target.exists():
        raise ValueError(f"A whyline skill named {source.name} already exists.")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source.path, target)
    return _load("whyline", target)


def _writable(ref: str, root: Path | None) -> Skill:
    skill = get(ref, root)
    if skill.origin.startswith("claude"):
        raise ValueError(CLAUDE_REFUSAL)
    return skill


def edit(ref: str, root: Path | None = None, *, description: str | None = None,
         body: str | None = None) -> Skill:
    skill = _writable(ref, root)
    manifest = skill.path / "SKILL.md"
    current = manifest.read_text(encoding="utf-8") if manifest.is_file() else ""
    if description is None:
        description = skill.description
    if body is None:
        body = body_of(current)
    if not description.strip():
        raise ValueError("A skill needs a description.")
    manifest.write_text(_render(skill.name, description.strip(), body), encoding="utf-8")
    return _load(skill.origin, skill.path)


def remove(ref: str, root: Path | None = None) -> None:
    skill = _writable(ref, root)
    used = users.of("skill", ref)
    if used:
        raise ValueError(f"{ref} is used by {', '.join(used)}")
    shutil.rmtree(skill.path)
