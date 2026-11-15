"""Draft release notes from the commits since the last tag, with a plain fallback."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from whyline.release.config import ReleaseConfig
from whyline.release.ready import default_run
from whyline.security.rules import Rule, RuleSet, load_rules
from whyline.security.secrets import scan_text

Run = Callable[..., object]
AskAgent = Callable[[str], str]

NO_TAG_LIMIT = 50
END_INSTRUCTION = "Put the notes between a line <notes> and a line </notes>. Write nothing else."
UNUSABLE = "The agent's notes were not usable; using the commit list"
TEXT_LIMIT = 120
_MARKED = re.compile(r"^[ \t]*<notes>[ \t]*\r?\n(.*?)^[ \t]*</notes>[ \t]*$", re.S | re.M)
_LIST_MARKER = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")
_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$")
_HOME_PATH = re.compile(r"/(?:Users|home)/[^\s/]+|[Cc]:\\Users\\[^\s\\]+")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_INLINE_CODE = re.compile(r"`[^`]*`")
_QUOTED = re.compile(r'"[^"]*"')
_FIRST_PERSON = re.compile(
    r"(?i)(?<![A-Za-z])(?:I'm|I'll|I|my|me)(?![A-Za-z/])"
)
_TALK_PHRASES = (
    "here are", "here is", "here's", "below are", "below is",
    "i have", "i've", "i created", "i wrote", "as requested",
    "let me know", "please review", "please let", "hope this helps",
    "feel free", "happy to",
)
_PROCESS_PREFIXES = (
    "chore: tick",
    "chore: release",
    "chore: record",
    "chore: move finished plans",
    "setup:",
    "merge:",
    "plan:",
)


@dataclass(frozen=True)
class Problem:
    line: int
    text: str
    reason: str
    removable: bool


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


def _after_marker(line: str) -> str:
    stripped = line.strip()
    match = _LIST_MARKER.match(stripped)
    return stripped[match.end():].strip() if match else stripped


def _is_fence(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("```") or stripped.startswith("~~~")


def _heading_level(line: str) -> int | None:
    match = _HEADING.match(line.strip())
    return len(match.group(1)) if match else None


def _is_version_title(line: str, version: str) -> bool:
    match = _HEADING.match(line.strip())
    if not match:
        return False
    title = match.group(2).strip().rstrip("#").strip()
    return bool(re.match(rf"v{re.escape(version)}(\s|$)", title))


def _talks_to_reader(line: str) -> bool:
    body = _after_marker(line)
    if body.endswith("?"):
        return True
    low = body.lower()
    return any(low.startswith(phrase) for phrase in _TALK_PHRASES)


def _first_person(line: str) -> bool:
    # Quoted UI copy ("I have a plan already") and inline code (`my-package`)
    # are not the writer talking.
    stripped = _QUOTED.sub(" ", _INLINE_CODE.sub(" ", line))
    return _FIRST_PERSON.search(stripped) is not None


def _process_noise(line: str) -> bool:
    body = _after_marker(line).lower()
    return any(body.startswith(prefix) for prefix in _PROCESS_PREFIXES)


def _disallowed_email(line: str, allowed: frozenset[str]) -> bool:
    allowed_l = {email.lower() for email in allowed}
    return any(addr.lower() not in allowed_l for addr in _EMAIL.findall(line))


def _secret_value(rule: Rule, match: re.Match[str]) -> str:
    if rule.secret_group:
        try:
            return match.group(rule.secret_group) or ""
        except IndexError:
            pass
    for index in range(1, (match.lastindex or 0) + 1):
        value = match.group(index)
        if value:
            return value
    return match.group(0) or ""


def _display_secret(line: str, found: list, rules: RuleSet) -> str:
    by_id = {rule.id: rule for rule in rules.rules}
    redacted = line
    for item in found:
        rule = by_id.get(item.rule)
        if rule is None or rule.regex is None:
            continue
        for match in rule.regex.finditer(redacted):
            secret = _secret_value(rule, match)
            if secret:
                redacted = redacted.replace(secret, item.rule)
    return redacted[:TEXT_LIMIT]


def _reason(
    line: str,
    *,
    allowed_emails: frozenset[str],
    repeat_title: bool,
    fence: bool,
) -> str | None:
    if _HOME_PATH.search(line):
        return "home path"
    if _disallowed_email(line, allowed_emails):
        return "email address"
    if _talks_to_reader(line):
        return "talks to the reader"
    if _first_person(line):
        return "first person"
    if _process_noise(line):
        return "process noise"
    if repeat_title:
        return "repeats the title"
    if fence:
        return "code fence around everything"
    return None


def lint(
    text: str,
    *,
    version: str,
    allowed_emails: frozenset[str] = frozenset(),
) -> list[Problem]:
    """Flag chatter, process noise, secrets and similar problems in notes."""
    lines = (text or "").splitlines()
    rules = load_rules()
    secrets_at: dict[int, list] = {}
    for item in scan_text(text or "", f"docs/releases/v{version}.md", rules):
        if item.line:
            secrets_at.setdefault(item.line, []).append(item)
    nonempty = [(n, line) for n, line in enumerate(lines, 1) if line.strip()]
    fence_lines: set[int] = set()
    if (
        len(nonempty) >= 2
        and _is_fence(nonempty[0][1])
        and _is_fence(nonempty[-1][1])
    ):
        fence_lines = {nonempty[0][0], nonempty[-1][0]}
    problems: list[Problem] = []
    seen_title = False
    for number, line in enumerate(lines, 1):
        if number in secrets_at:
            problems.append(Problem(
                number,
                _display_secret(line, secrets_at[number], rules),
                "secret",
                True,
            ))
            if _is_version_title(line, version):
                seen_title = True
            continue
        repeat_title = seen_title and _is_version_title(line, version)
        if _is_version_title(line, version):
            seen_title = True
        reason = _reason(
            line,
            allowed_emails=allowed_emails,
            repeat_title=repeat_title,
            fence=number in fence_lines,
        )
        if reason:
            problems.append(Problem(number, line[:TEXT_LIMIT], reason, True))
    return problems


def _drop_empty_headings(lines: list[str]) -> list[str]:
    while True:
        headings: list[tuple[int, int]] = []
        for i, line in enumerate(lines):
            level = _heading_level(line)
            if level is not None:
                headings.append((i, level))
        remove: set[int] = set()
        for index, (start, level) in enumerate(headings):
            end = len(lines)
            for later, later_level in headings[index + 1:]:
                if later_level <= level:
                    end = later
                    break
            body = lines[start + 1:end]
            if not any(
                part.strip() and _heading_level(part) is None for part in body
            ):
                remove.add(start)
        if not remove:
            return lines
        lines = [line for i, line in enumerate(lines) if i not in remove]


def _collapse_blank(lines: list[str]) -> list[str]:
    out: list[str] = []
    pending_blank = False
    for line in lines:
        if not line.strip():
            if out:
                pending_blank = True
            continue
        if pending_blank:
            out.append("")
            pending_blank = False
        out.append(line)
    return out


def clean(text: str, problems: list[Problem]) -> str:
    """Remove flagged lines and headings left with no content, collapse blanks."""
    drop = {problem.line for problem in problems}
    kept = [line for i, line in enumerate((text or "").splitlines(), 1) if i not in drop]
    kept = _collapse_blank(_drop_empty_headings(kept))
    return "\n".join(kept) + "\n" if kept else ""


def usable(text: str) -> bool:
    """True when a bullet or sentence remains besides headings."""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or _heading_level(line) is not None or _is_fence(stripped):
            continue
        return True
    return False


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
